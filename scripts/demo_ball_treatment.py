"""Demonstrate reverse-walk ball timestamp treatment on one real burst."""

from __future__ import annotations

from sqlalchemy import text

from db.session import SessionLocal, init_db
from live.ball_timestamp_treatment import (
    BallStamp,
    _collect_good_gaps,
    _detect_burst_segments,
    _gap_sec,
    _typical_pace,
    format_treatment_table,
    treat_innings_balls,
)
from timeutils import to_ist

MATCH_ID = 4  # IPL 2021 — clear 11.x burst in 1st innings
SEQ_FROM = 65
SEQ_TO = 76


def main() -> None:
    init_db()
    with SessionLocal() as s:
        meta = s.execute(
            text(
                """
                SELECT lt.name, vt.name, m.starting_at_ist
                FROM matches m
                JOIN teams lt ON lt.id = m.localteam_id
                JOIN teams vt ON vt.id = m.visitorteam_id
                WHERE m.id = :mid
                """
            ),
            {"mid": MATCH_ID},
        ).one()
        rows = s.execute(
            text(
                """
                SELECT be.ball_seq, i.innings_number, be.over, be.ball,
                       be.event_utc, be.commentary, be.is_wicket
                FROM ball_events be
                JOIN innings i ON i.id = be.innings_id
                WHERE be.match_id = :mid AND i.innings_number = 1
                ORDER BY be.ball_seq
                """
            ),
            {"mid": MATCH_ID},
        ).all()

    balls = [BallStamp(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6])) for r in rows]
    segments = _detect_burst_segments(balls)
    burst_idx = {i for seg in segments for i in range(seg[0], seg[1] + 1)}
    pace = _typical_pace(_collect_good_gaps(balls, burst_idx))
    treated = treat_innings_balls(balls)

    print(f"EXAMPLE: {meta[0]} vs {meta[1]} (match_id={MATCH_ID}, 1st innings)")
    print(f"Scheduled IST: {meta[2]}")
    print(f"Burst segments (innings indices): {segments}")
    print(f"Typical good-ball pace: {pace:.1f}s\n")

    # Show IST for readability.
    print("=== BEFORE / AFTER (IST) ===")
    print(f"{'seq':>4} {'ball':>5} {'raw_ist':>19} {'treated_ist':>19} {'shift':>7}  status")
    for b in treated:
        if b.ball_seq < SEQ_FROM or b.ball_seq > SEQ_TO:
            continue
        raw_ist = to_ist(b.raw_utc)
        tr_ist = to_ist(b.treated_utc)
        shift = _gap_sec(b.treated_utc, b.raw_utc)
        sign = "+" if shift >= 0 else ""
        status = "BURST" if b.in_burst else "ok"
        print(
            f"{b.ball_seq:>4} {b.label:>5} {str(raw_ist):>19} {str(tr_ist):>19} "
            f"{sign}{shift:>5.0f}s  {status}"
        )

    # Walkthrough for over 11 cluster.
    for start, end in segments:
        if not any(balls[i].ball_seq == 70 for i in range(start, end + 1)):
            continue
        before_t = next((t for t in treated if t.ball_seq == balls[start - 1].ball_seq), None)
        after_t = next((t for t in treated if t.ball_seq == balls[end + 1].ball_seq), None)
        burst_t = [t for t in treated if balls[start].ball_seq <= t.ball_seq <= balls[end].ball_seq]
        print("\nLOGIC")
        print(
            f"- Good ball before: {before_t.label} @ {to_ist(before_t.raw_utc)} "
            f"(raw gap to burst lead = {_gap_sec(burst_t[0].raw_utc, before_t.raw_utc):.0f}s -> catch-up)"
        )
        print(
            f"- Raw burst: {burst_t[0].label}-{burst_t[-1].label} clustered "
            f"{to_ist(burst_t[0].raw_utc)} - {to_ist(burst_t[-1].raw_utc)}"
        )
        print(f"- Next good ball: {after_t.label} @ {to_ist(after_t.raw_utc)}")
        print(f"- Median pace from other good balls: {pace:.1f}s")
        print("- Reverse walk from next good ball:")
        for t in burst_t:
            back = _gap_sec(after_t.raw_utc, t.treated_utc)
            print(f"    {t.label}: {to_ist(after_t.raw_utc)} - {back:.0f}s -> {to_ist(t.treated_utc)}")


if __name__ == "__main__":
    main()
