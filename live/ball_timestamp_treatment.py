"""Reverse-walk ball timestamp treatment for Sportmonks batch updates.

When the feed falls behind and dumps several balls with 1–3 second ``updated_at``
gaps, forward-filling from the last good ball is unreliable (unknown dead time
after that ball — DRS, injury, rain, etc.).  We instead anchor on the *next*
good ball and walk backwards using the typical pace between trustworthy balls.

Persistence helpers write ``event_*_treated`` and ``event_*_corrected`` on
``BallEvent`` rows.  Raw ``event_utc`` / ``event_ist`` are never modified.

Corner cases
------------
* **Wide / no-ball**: same ``over.ball`` replay pairs are excluded from burst
  detection (2s gap is normal); only the legal delivery participates in bursts.
* **Over change**: burst may span overs (e.g. 10.6 -> 11.1..11.6); reverse walk
  still anchors on the next good ball; minimum step is slightly higher across
  an over boundary.
* **Wicket**: wicket balls use a larger minimum backward step (12s) so treated
  time does not collapse onto the dismissal.
* **Innings break**: treatment is per-innings; gaps > 180s are ignored when
  computing typical pace.
* **Catch-up dump**: if a good ball is followed by a 60s+ gap and then a tight
  cluster, the first clustered ball is included in the burst (its timestamp is
  the batch arrival time, not delivery time).
* **Opening bulk dump**: fast gaps chain through over breaks until the first long
  pause; reverse-walk ball-by-ball from the next good ball (~60s + over change);
  ``scheduled_start`` is only a floor (never push deliveries to exact scheduled time).
* **Trailing burst** (no good ball after): reverse-walk from the **last burst ball's raw
  feed time** (same as in-burst segments).  Forward expansion is never used — feed data
  cannot arrive before a delivery occurs, so ``treated_utc`` never exceeds ``raw_utc``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import List, Optional, Sequence, Tuple

# Gaps shorter than this between different ball labels => likely batch dump.
BURST_GAP_SEC = 10.0
# Gap from previous ball >= this => previous delivery timestamp is trustworthy.
GOOD_GAP_SEC = 10.0
# Huge gap before a fast cluster => API catch-up, include lead ball in burst.
CATCHUP_GAP_SEC = 60.0
# Ignore gaps above this when computing typical pace (innings break, DR pause).
MAX_PACE_GAP_SEC = 180.0
# Minimum time after anchor-before (seconds).
MIN_AFTER_ANCHOR_SEC = 3.0
# Wicket / over-end: allow slightly longer reverse step floor.
WICKET_MIN_GAP_SEC = 12.0
OVER_END_MIN_GAP_SEC = 10.0
# Typical per-ball pace when reverse-walking from a good anchor (T20 ~50–60s).
DELIVERY_PACE_SEC = 60.0
# Never use innings-break-scale gaps as per-ball reverse pace.
REVERSE_PACE_CAP_SEC = 65.0
# Extra seconds when stepping back across an over boundary.
OVER_CHANGE_BACK_EXTRA_SEC = 8.0
# Flat offset: Sportmonks ``updated_at`` lags real delivery by ~this many seconds.
SPORTMONKS_DELAY_SEC = 35.0


@dataclass
class BallStamp:
    """One delivery with its raw (Sportmonks) timestamp."""

    ball_seq: int
    innings_number: int
    over: int
    ball: int
    raw_utc: datetime  # naive UTC
    commentary: Optional[str] = None
    is_wicket: bool = False

    @property
    def label(self) -> str:
        return f"{self.over}.{self.ball}"


@dataclass
class TreatedBallStamp(BallStamp):
    """Ball with treated timestamp and audit metadata."""

    treated_utc: datetime = field(default_factory=datetime.utcnow)
    in_burst: bool = False
    anchor_before_utc: Optional[datetime] = None
    anchor_after_utc: Optional[datetime] = None
    pace_sec: Optional[float] = None
    note: str = ""


def _as_utc(value: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.replace("Z", "").split(".")[0]
        return datetime.fromisoformat(s)
    raise TypeError(f"expected datetime, got {type(value)}")


def _gap_sec(later: datetime, earlier: datetime) -> float:
    return (_as_utc(later) - _as_utc(earlier)).total_seconds()


def _is_wide_replay(curr: BallStamp, prev: Optional[BallStamp]) -> bool:
    """Wide/no-ball followed by legal delivery on the same over.ball."""
    return prev is not None and curr.over == prev.over and curr.ball == prev.ball


def _typical_pace(good_gaps: Sequence[float]) -> float:
    """Median gap between trustworthy balls, ignoring innings-break-scale pauses."""
    usable = [g for g in good_gaps if GOOD_GAP_SEC <= g <= MAX_PACE_GAP_SEC]
    if not usable:
        usable = [g for g in good_gaps if g >= GOOD_GAP_SEC]
    if not usable:
        return DELIVERY_PACE_SEC
    return min(float(median(usable)), REVERSE_PACE_CAP_SEC)


def _collect_good_gaps(balls: Sequence[BallStamp], burst_indices: set[int]) -> List[float]:
    gaps: List[float] = []
    for i in range(1, len(balls)):
        if i in burst_indices or (i - 1) in burst_indices:
            continue
        if _is_wide_replay(balls[i], balls[i - 1]):
            continue
        gaps.append(_gap_sec(balls[i].raw_utc, balls[i - 1].raw_utc))
    return gaps


def _extend_burst_to_earlier_balls(balls: Sequence[BallStamp], start: int, end: int) -> Tuple[int, int]:
    """Walk start index back while gaps remain < BURST_GAP_SEC (includes 0.1)."""
    while start > 0:
        if _is_wide_replay(balls[start], balls[start - 1]):
            break
        # Ball at start-1 ended a long pause — it is a good anchor, not part of the burst.
        if start >= 2:
            pause_before = _gap_sec(balls[start - 1].raw_utc, balls[start - 2].raw_utc)
            if pause_before >= CATCHUP_GAP_SEC:
                break
        if _gap_sec(balls[start].raw_utc, balls[start - 1].raw_utc) < BURST_GAP_SEC:
            start -= 1
        else:
            break
    return start, end


def _extend_burst_to_later_balls(balls: Sequence[BallStamp], start: int, end: int) -> Tuple[int, int]:
    """Walk end forward through over-break / API lag gaps until a real pause (>= CATCHUP)."""
    while end + 1 < len(balls):
        if _is_wide_replay(balls[end + 1], balls[end]):
            break
        if _gap_sec(balls[end + 1].raw_utc, balls[end].raw_utc) < CATCHUP_GAP_SEC:
            end += 1
        else:
            break
    return start, end


def _step_back_sec(prev: BallStamp, nxt: BallStamp, base_pace: float) -> float:
    """Seconds to step back from ``nxt`` to ``prev`` when reverse-walking."""
    if nxt.is_wicket:
        return max(base_pace, WICKET_MIN_GAP_SEC)
    if nxt.over != prev.over:
        return base_pace + OVER_CHANGE_BACK_EXTRA_SEC
    return base_pace


def _walk_back_from_anchor(
    balls: Sequence[BallStamp],
    start: int,
    end: int,
    anchor_after: datetime,
    base_pace: float,
) -> List[datetime]:
    """Place treated times for ``start..end`` stepping back from anchor_after.

    The ball at ``end`` is placed at ``anchor_after``; earlier burst balls step back
    ball-by-ball.  Callers must cap results to each ball's ``raw_utc``.
    """
    anchor_after = _as_utc(anchor_after)
    if end < start:
        return []
    if end == start:
        return [anchor_after]

    treated: List[datetime] = []
    t = anchor_after
    treated.append(t)
    for idx in range(end - 1, start - 1, -1):
        step = _step_back_sec(balls[idx], balls[idx + 1], base_pace)
        t -= timedelta(seconds=step)
        treated.insert(0, t)
    return treated


def _cap_times_to_raw(balls: Sequence[BallStamp], times: Sequence[datetime]) -> List[datetime]:
    """Treated delivery time cannot be after the feed publication instant."""
    return [min(_as_utc(t), _as_utc(b.raw_utc)) for t, b in zip(times, balls)]


def _enforce_monotonic_under_raw_caps(
    balls: Sequence[BallStamp],
    times: Sequence[datetime],
) -> List[datetime]:
    """Ensure rising delivery order without pushing any ball past its raw feed time."""
    out = _cap_times_to_raw(balls, times)
    if len(out) < 2:
        return out

    # Forward pass: minimum spacing, capped at raw.
    for i in range(1, len(out)):
        step = _min_step(balls[i - 1], balls[i])
        min_t = out[i - 1] + timedelta(seconds=step)
        if out[i] < min_t:
            out[i] = min(min_t, _as_utc(balls[i].raw_utc))

    # Backward pass: pull earlier balls back if spacing still broken (never push later).
    for i in range(len(out) - 1, 0, -1):
        step = _min_step(balls[i - 1], balls[i])
        max_prev = out[i] - timedelta(seconds=step)
        if out[i - 1] > max_prev:
            out[i - 1] = max_prev

    return _cap_times_to_raw(balls, out)


def _detect_burst_segments(balls: Sequence[BallStamp]) -> List[Tuple[int, int]]:
    """Return [start, end] inclusive indices of burst segments within one innings."""
    n = len(balls)
    if n < 2:
        return []

    segments: List[Tuple[int, int]] = []
    i = 1
    while i < n:
        if _is_wide_replay(balls[i], balls[i - 1]):
            i += 1
            continue

        gap = _gap_sec(balls[i].raw_utc, balls[i - 1].raw_utc)
        if gap >= BURST_GAP_SEC:
            i += 1
            continue

        # Fast gap (<10s) — start of a burst run.
        start = i
        end = i
        j = i + 1
        while j < n:
            if _is_wide_replay(balls[j], balls[j - 1]):
                j += 1
                continue
            g = _gap_sec(balls[j].raw_utc, balls[j - 1].raw_utc)
            if g >= BURST_GAP_SEC:
                break
            end = j
            j += 1

        # Catch-up: include lead only when it arrived with the cluster, not after a long pause.
        lead = start - 1
        if lead >= 0 and not _is_wide_replay(balls[start], balls[lead]):
            gap_into_lead = _gap_sec(balls[lead].raw_utc, balls[lead - 1].raw_utc) if lead > 0 else 0.0
            gap_cluster_entry = _gap_sec(balls[start].raw_utc, balls[lead].raw_utc)
            if lead == 0 or (
                gap_cluster_entry < BURST_GAP_SEC and gap_into_lead < CATCHUP_GAP_SEC
            ):
                start = lead

        start, end = _extend_burst_to_earlier_balls(balls, start, end)
        start, end = _extend_burst_to_later_balls(balls, start, end)

        if end >= start:
            segments.append((start, end))
        i = end + 1

    return segments


def _min_step(prev: BallStamp, curr: BallStamp) -> float:
    """Minimum seconds allowed before ``curr`` when walking backwards."""
    if curr.is_wicket:
        return WICKET_MIN_GAP_SEC
    if prev.over != curr.over:
        return OVER_END_MIN_GAP_SEC
    return MIN_AFTER_ANCHOR_SEC


def _enforce_monotonic_steps(
    balls: Sequence[BallStamp],
    start: int,
    end: int,
    treated_times: List[datetime],
) -> List[datetime]:
    """Ensure treated times rise with minimum per-ball steps."""
    out = list(treated_times)
    for offset in range(1, len(out)):
        idx = start + offset
        step = _min_step(balls[idx - 1], balls[idx])
        out[offset] = max(out[offset], out[offset - 1] + timedelta(seconds=step))
    return out


def _apply_scheduled_floor(
    treated_times: List[datetime],
    scheduled_floor: Optional[datetime],
    balls: Sequence[BallStamp],
    start: int,
    end: int,
) -> List[datetime]:
    if scheduled_floor is None:
        return treated_times
    segment = balls[start : end + 1]
    out = [max(t, scheduled_floor) for t in treated_times]
    out = _cap_times_to_raw(segment, out)
    return _enforce_monotonic_under_raw_caps(segment, out)


def _reverse_fill_segment(
    balls: Sequence[BallStamp],
    start: int,
    end: int,
    anchor_before: Optional[datetime],
    anchor_after: datetime,
    pace: float,
    scheduled_floor: Optional[datetime] = None,
) -> List[Tuple[int, datetime, str]]:
    """Assign treated times to burst indices ``start..end`` walking back from anchor_after."""
    burst_len = end - start + 1
    out: List[Tuple[int, datetime, str]] = []

    treated_times = _walk_back_from_anchor(balls, start, end, anchor_after, pace)
    note = (
        f"reverse from burst ceiling @ {anchor_after.strftime('%H:%M:%S')} "
        f"using ~{pace:.0f}s/ball (+over change)"
    )

    # Floor: must stay after anchor_before with per-ball minimum steps.
    if anchor_before is not None:
        floor = anchor_before + timedelta(seconds=MIN_AFTER_ANCHOR_SEC)
        if treated_times[0] < floor:
            # Compress pace to fit between anchors (still reverse-anchored, not forward).
            span = _gap_sec(anchor_after, anchor_before)
            min_span = sum(
                _min_step(balls[idx - 1] if idx > start else balls[start], balls[idx])
                for idx in range(start + 1, end + 1)
            ) + MIN_AFTER_ANCHOR_SEC
            usable = max(span - MIN_AFTER_ANCHOR_SEC, min_span)
            pace = usable / burst_len
            treated_times = _walk_back_from_anchor(balls, start, end, anchor_after, pace)
            note += f"; compressed pace to {pace:.1f}s to respect prior good ball"

        if treated_times[0] < floor:
            treated_times[0] = floor
            for idx in range(start + 1, end + 1):
                prev_t = treated_times[idx - start - 1]
                step = _min_step(balls[idx - 1], balls[idx])
                treated_times[idx - start] = max(
                    treated_times[idx - start],
                    prev_t + timedelta(seconds=step),
                )
            note += "; floor-clamped after anchor-before"

    treated_times = _apply_scheduled_floor(treated_times, scheduled_floor, balls, start, end)
    segment = balls[start : end + 1]
    treated_times = _cap_times_to_raw(segment, treated_times)
    treated_times = _enforce_monotonic_under_raw_caps(segment, treated_times)
    if (
        scheduled_floor is not None
        and treated_times
        and treated_times[0] <= scheduled_floor + timedelta(seconds=MIN_AFTER_ANCHOR_SEC)
    ):
        note += f"; clamped to scheduled floor {scheduled_floor.strftime('%H:%M:%S')}"

    for offset, idx in enumerate(range(start, end + 1)):
        out.append((idx, treated_times[offset], note))
    return out


def treat_innings_balls(
    balls: Sequence[BallStamp],
    *,
    scheduled_start_utc: Optional[datetime] = None,
) -> List[TreatedBallStamp]:
    """Treat timestamps for one innings (ordered by ball_seq)."""
    if not balls:
        return []

    balls = [
        BallStamp(
            b.ball_seq, b.innings_number, b.over, b.ball, _as_utc(b.raw_utc),
            b.commentary, b.is_wicket,
        )
        for b in balls
    ]

    segments = _detect_burst_segments(balls)
    burst_indices = {i for s, e in segments for i in range(s, e + 1)}
    pace = _typical_pace(_collect_good_gaps(balls, burst_indices))

    treated_map: dict[int, Tuple[datetime, str, Optional[datetime], Optional[datetime], float]] = {}

    for start, end in segments:
        anchor_after_external: Optional[datetime] = None
        after_idx = end + 1
        while after_idx < len(balls):
            if after_idx not in burst_indices:
                anchor_after_external = balls[after_idx].raw_utc
                break
            after_idx += 1

        anchor_before: Optional[datetime] = None
        before_idx = start - 1
        while before_idx >= 0:
            if before_idx not in burst_indices:
                anchor_before = balls[before_idx].raw_utc
                break
            before_idx -= 1

        scheduled_floor = _as_utc(scheduled_start_utc) if scheduled_start_utc else None
        seg_pace = DELIVERY_PACE_SEC if anchor_before is None else pace

        # Reverse-walk ceiling: latest publication time in the burst (never the next
        # good ball's raw time — that would spread burst deliveries forward in time).
        ceiling = balls[end].raw_utc
        if anchor_after_external is not None:
            ceiling = min(ceiling, anchor_after_external)

        for idx, t, note in _reverse_fill_segment(
            balls, start, end, anchor_before, ceiling, seg_pace, scheduled_floor
        ):
            treated_map[idx] = (t, note, anchor_before, ceiling, seg_pace)

    scheduled_floor = _as_utc(scheduled_start_utc) if scheduled_start_utc else None
    final_times: List[datetime] = []
    for i, b in enumerate(balls):
        if i in treated_map:
            final_times.append(treated_map[i][0])
        else:
            final_times.append(b.raw_utc)

    for i in range(1, len(balls)):
        step = _min_step(balls[i - 1], balls[i])
        min_t = final_times[i - 1] + timedelta(seconds=step)
        if scheduled_floor is not None:
            min_t = max(min_t, scheduled_floor)
        if final_times[i] < min_t:
            final_times[i] = min(min_t, balls[i].raw_utc)

    final_times = _enforce_monotonic_under_raw_caps(balls, final_times)

    result: List[TreatedBallStamp] = []
    for i, b in enumerate(balls):
        if i in treated_map:
            t, note, ab, aa, p = treated_map[i]
            adjusted = final_times[i]
            if adjusted != t:
                note = f"{note}; monotonic fix"
            result.append(
                TreatedBallStamp(
                    **{k: getattr(b, k) for k in BallStamp.__dataclass_fields__},
                    treated_utc=adjusted,
                    in_burst=True,
                    anchor_before_utc=ab,
                    anchor_after_utc=aa,
                    pace_sec=p,
                    note=note,
                )
            )
        else:
            adjusted = final_times[i]
            note = "raw timestamp trusted"
            if adjusted != b.raw_utc:
                note = "raw adjusted for monotonic order"
            result.append(
                TreatedBallStamp(
                    **{k: getattr(b, k) for k in BallStamp.__dataclass_fields__},
                    treated_utc=adjusted,
                    in_burst=adjusted != b.raw_utc,
                    note=note,
                )
            )
    return result


def treat_match_balls(
    balls: Sequence[BallStamp],
    *,
    scheduled_start_utc: Optional[datetime] = None,
) -> List[TreatedBallStamp]:
    """Treat all balls for a match, partitioned by innings."""
    by_innings: dict[int, List[BallStamp]] = {}
    for b in balls:
        by_innings.setdefault(b.innings_number, []).append(b)
    out: List[TreatedBallStamp] = []
    for inn in sorted(by_innings):
        chunk = sorted(by_innings[inn], key=lambda x: x.ball_seq)
        out.extend(treat_innings_balls(chunk, scheduled_start_utc=scheduled_start_utc))
    return sorted(out, key=lambda x: x.ball_seq)


def format_treatment_table(
    treated: Sequence[TreatedBallStamp],
    *,
    ball_seq_from: Optional[int] = None,
    ball_seq_to: Optional[int] = None,
) -> str:
    """Human-readable before/after table for inspection."""
    lines = [
        f"{'seq':>4} {'ball':>5} {'raw_ist':>19} {'treated_ist':>19} {'delta':>7}  note"
    ]
    for b in treated:
        if ball_seq_from is not None and b.ball_seq < ball_seq_from:
            continue
        if ball_seq_to is not None and b.ball_seq > ball_seq_to:
            continue
        delta = _gap_sec(b.treated_utc, b.raw_utc)
        sign = "+" if delta >= 0 else ""
        raw_s = b.raw_utc.strftime("%Y-%m-%d %H:%M:%S")
        tr_s = b.treated_utc.strftime("%Y-%m-%d %H:%M:%S")
        flag = "BURST" if b.in_burst else "ok"
        lines.append(
            f"{b.ball_seq:>4} {b.label:>5} {raw_s:>19} {tr_s:>19} {sign}{delta:>5.0f}s  {flag} {b.note}"
        )
    return "\n".join(lines)


def apply_delay_correction(treated_utc: datetime) -> datetime:
    """Subtract the flat Sportmonks publication delay from a treated timestamp."""
    return _as_utc(treated_utc) - timedelta(seconds=SPORTMONKS_DELAY_SEC)


def ball_alignment_utc(ball) -> Optional[datetime]:
    """Best UTC instant for astro alignment: corrected > treated > raw."""
    return ball.event_utc_corrected or ball.event_utc_treated or ball.event_utc


def stamps_from_db_rows(rows) -> List[BallStamp]:
    """Build BallStamp list from (ball_seq, innings_number, over, ball, event_utc, commentary, is_wicket) rows."""
    return [
        BallStamp(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6]))
        for r in rows
    ]


def persist_treated_timestamps_for_match(session, match_id: int) -> int:
    """Compute and persist treated + corrected timestamps for one match.

    Returns the number of ball rows updated.
    """
    from sqlalchemy import select

    from db.models import BallEvent, Innings, Match

    from live.ball_order import sort_db_ball_rows_cricket

    rows = list(
        session.execute(
            select(
                BallEvent.id,
                BallEvent.ball_seq,
                Innings.innings_number,
                BallEvent.over,
                BallEvent.ball,
                BallEvent.event_utc,
                BallEvent.commentary,
                BallEvent.is_wicket,
            )
            .join(Innings, Innings.id == BallEvent.innings_id)
            .where(BallEvent.match_id == match_id, BallEvent.event_utc.is_not(None))
        ).all()
    )
    if not rows:
        return 0

    rows = sort_db_ball_rows_cricket(rows)
    id_by_inn_seq = {(r[2], r[1]): r[0] for r in rows}
    match = session.get(Match, match_id)
    scheduled = match.starting_at_utc if match is not None else None

    stamps = stamps_from_db_rows([(r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows])
    treated = treat_match_balls(stamps, scheduled_start_utc=scheduled)

    from timeutils import to_ist

    updated = 0
    for t in treated:
        ball = session.get(BallEvent, id_by_inn_seq[(t.innings_number, t.ball_seq)])
        if ball is None:
            continue
        tr = _as_utc(t.treated_utc)
        corr = apply_delay_correction(tr)
        ball.event_utc_treated = tr
        ball.event_ist_treated = to_ist(tr)
        ball.event_utc_corrected = corr
        ball.event_ist_corrected = to_ist(corr)
        ball.time_correction_sec = SPORTMONKS_DELAY_SEC
        ball.timestamp_in_burst = t.in_burst
        updated += 1

    # Snap first-ball anchor to corrected time of earliest delivery.
    if match is not None:
        first = session.scalar(
            select(BallEvent)
            .where(BallEvent.match_id == match_id, BallEvent.event_utc_corrected.is_not(None))
            .order_by(BallEvent.event_utc_corrected, BallEvent.ball_seq)
            .limit(1)
        )
        if first is not None:
            match.first_ball_utc = first.event_utc_corrected
            match.first_ball_ist = first.event_ist_corrected

    session.flush()
    return updated
