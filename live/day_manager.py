"""Live day store: fixtures, charts, balls (Sportmonks -> day DB)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AstroChart, BallEvent, Innings, Match
from live.astro_writer import LIVE_CHART_DURATION_HOURS, duration_for_match, write_match_chart
from live.ball_timestamp_treatment import (
    BallStamp,
    SPORTMONKS_DELAY_SEC,
    apply_delay_correction,
    persist_treated_timestamps_for_match,
    treat_match_balls,
)
from live.match_setup import (
    apply_coordinates,
    apply_innings_batting_teams,
    apply_match_outcome,
    batting_team_for_innings,
    ensure_match_from_fixture,
    parse_utc,
)
from live.sportmonks_client import (
    SportmonksClient,
    _unwrap_list,
    _unwrap_obj,
    normalize_ball,
    resolve_venue_payload,
)
from live.ball_order import ball_event_cricket_key, delivery_sort_key, sort_ball_events_cricket
from live.venue_coords import resolve_coordinates
from timeutils import to_ist

logger = logging.getLogger("kp.live.day")

LIVE_STATUSES = {"live", "1st innings", "2nd innings", "innings break", "stumps", "finished", "aborted"}
NOT_STARTED = {"ns", "scheduled", "not started", "upcoming", ""}


def fetch_fixtures_for_date(client: SportmonksClient, day: date) -> List[Dict[str, Any]]:
    day_s = day.isoformat()
    fixtures = client.get_fixtures_between(day_s, day_s, includes="localteam,visitorteam,venue")
    seen = {f["id"] for f in fixtures}
    for live in client.get_livescores(includes="localteam,visitorteam,venue"):
        start = str(live.get("starting_at") or "")
        if start[:10] == day_s and live.get("id") not in seen:
            fixtures.append(live)
            seen.add(live["id"])
    fixtures.sort(key=lambda f: f.get("starting_at") or "")
    return fixtures


def fixture_tab_label(fixture: Dict[str, Any]) -> str:
    """Short tab title: team code (or abbreviated name) vs team code."""
    lt = _unwrap_obj(fixture.get("localteam"))
    vt = _unwrap_obj(fixture.get("visitorteam"))

    def short(team: Dict[str, Any]) -> str:
        code = (team.get("code") or "").strip()
        if code:
            return code
        name = (team.get("name") or "?").strip()
        return name[:3].upper() if name else "?"

    return f"{short(lt)} vs {short(vt)}"


def fixture_label(fixture: Dict[str, Any]) -> str:
    lt = _unwrap_obj(fixture.get("localteam"))
    vt = _unwrap_obj(fixture.get("visitorteam"))
    lt_name = lt.get("name") or lt.get("code") or "?"
    vt_name = vt.get("name") or vt.get("code") or "?"
    start_utc = parse_utc(fixture.get("starting_at"))
    start_s = to_ist(start_utc).strftime("%H:%M") if start_utc else "??:??"
    league = fixture.get("league_id") or ""
    return f"{start_s} IST | {lt_name} vs {vt_name} (L{league})"


def _fixture_started(fixture: Dict[str, Any], match: Optional[Match] = None) -> bool:
    status = str(fixture.get("status") or match.status if match else "").lower()
    if status in NOT_STARTED:
        return False
    if match and match.first_ball_utc:
        return True
    return status in LIVE_STATUSES or "innings" in status


def chart_anchor_utc(
    fixture: Dict[str, Any],
    match: Match,
    session: Session,
) -> datetime:
    """Scheduled start before play; first corrected ball time once started."""
    if _fixture_started(fixture, match):
        first_corr = session.scalar(
            select(BallEvent.event_utc_corrected)
            .where(BallEvent.match_id == match.id, BallEvent.event_utc_corrected.is_not(None))
            .order_by(BallEvent.ball_seq)
            .limit(1)
        )
        if first_corr:
            return first_corr
        if match.first_ball_utc:
            return match.first_ball_utc
    scheduled = parse_utc(fixture.get("starting_at")) or match.starting_at_utc
    if scheduled is None:
        raise ValueError("No scheduled start time for chart anchor.")
    return scheduled


def ensure_fixture_in_day_db(
    session: Session,
    client: SportmonksClient,
    fixture: Dict[str, Any],
    *,
    league_name: Optional[str] = None,
) -> Match:
    """Register fixture + coords; pre-build chart at scheduled start if possible."""
    detail = client.get_fixture(fixture["id"], includes="localteam,visitorteam,venue,balls")
    venue_payload = resolve_venue_payload(client, detail if detail.get("venue_id") else fixture)
    detail["venue"] = venue_payload

    match = ensure_match_from_fixture(session, detail)
    if league_name:
        match.league = league_name
    match.status = str(fixture.get("status") or "")
    match.format = match.format or detail.get("type") or "T20"
    apply_coordinates(session, match, venue_payload, allow_ai=True)

    has_chart = session.scalar(select(AstroChart).where(AstroChart.match_id == match.id)) is not None
    if match.lat is not None and match.lon is not None and not _fixture_started(fixture, match):
        scheduled = parse_utc(fixture.get("starting_at")) or match.starting_at_utc
        if scheduled and not has_chart:
            write_match_chart(
                session,
                match,
                anchor_utc=scheduled,
                duration_hours=LIVE_CHART_DURATION_HOURS,
            )
            logger.info("Pre-built chart for fixture %s at scheduled %s", fixture["id"], scheduled)

    session.flush()
    return match


def _ensure_innings(
    session: Session,
    match: Match,
    innings_number: int,
    event_utc: Optional[datetime],
) -> Innings:
    inn = session.scalar(
        select(Innings).where(Innings.match_id == match.id, Innings.innings_number == innings_number)
    )
    if inn is None:
        inn = Innings(match_id=match.id, innings_number=innings_number)
        session.add(inn)
        session.flush()
    if inn.batting_team_id is None:
        inn.batting_team_id = batting_team_for_innings(
            innings_number,
            localteam_id=match.localteam_id,
            visitorteam_id=match.visitorteam_id,
            toss_won_team_id=match.toss_won_team_id,
            toss_elected=match.toss_elected,
        )
    if event_utc:
        if inn.start_utc is None or event_utc < inn.start_utc:
            inn.start_utc = event_utc
            inn.start_ist = to_ist(event_utc)
        if inn.end_utc is None or event_utc > inn.end_utc:
            inn.end_utc = event_utc
            inn.end_ist = to_ist(event_utc)
    return inn


def _innings_from_scoreboard(scoreboard: Any) -> int:
    if not scoreboard:
        return 1
    s = str(scoreboard).upper()
    if s in ("S2", "2", "II"):
        return 2
    return 1


def _renumber_ball_seq_cricket(session: Session, match_id: int) -> None:
    """Align ball_seq with over/ball order (cheap O(n); decoupled from Sportmonks updated_at)."""
    innings_nums = {
        i.id: i.innings_number
        for i in session.scalars(select(Innings).where(Innings.match_id == match_id)).all()
    }
    balls = list(
        session.scalars(select(BallEvent).where(BallEvent.match_id == match_id)).all()
    )
    balls.sort(
        key=lambda b: (
            innings_nums.get(b.innings_id, 1),
            *ball_event_cricket_key(b),
        )
    )
    for seq, ball in enumerate(balls, start=1):
        ball.ball_seq = seq


def _sort_raw_deliveries(balls_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keyed: List[tuple] = []
    for raw in balls_raw:
        nb = normalize_ball(raw)
        inn = _innings_from_scoreboard(nb.get("scoreboard"))
        keyed.append(
            (
                inn,
                *delivery_sort_key(nb.get("over"), nb.get("ball"), int(raw.get("id") or 0)),
                raw,
            )
        )
    keyed.sort(key=lambda t: t[:4])
    return [t[-1] for t in keyed]


def _recompute_running_totals(session: Session, match_id: int) -> None:
    """Set score_after / wickets_after on each ball and innings totals from row flags."""
    for inn in session.scalars(select(Innings).where(Innings.match_id == match_id)).all():
        balls = sort_ball_events_cricket(
            session.scalars(select(BallEvent).where(BallEvent.innings_id == inn.id)).all()
        )
        running_runs = 0
        running_wkts = 0
        for ball in balls:
            running_runs += (ball.runs or 0) + (ball.extras or 0)
            if ball.is_wicket:
                running_wkts += 1
            ball.score_after = running_runs
            ball.wickets_after = running_wkts
        if balls:
            inn.total_runs = running_runs
            inn.wickets = running_wkts


def _apply_ball_fields(ball: BallEvent, nb: Dict[str, Any]) -> bool:
    """Update mutable ball fields from normalized Sportmonks payload. Returns True if changed."""
    changed = False
    pairs = (
        ("runs", nb.get("runs")),
        ("extras", nb.get("extras")),
        ("is_wicket", bool(nb.get("is_wicket"))),
        ("is_four", bool(nb.get("is_four"))),
        ("is_six", bool(nb.get("is_six"))),
        ("commentary", nb.get("commentary")),
        ("over", nb.get("over")),
        ("ball", nb.get("ball")),
    )
    for attr, value in pairs:
        if getattr(ball, attr) != value:
            setattr(ball, attr, value)
            changed = True
    return changed


def sync_balls(
    session: Session,
    client: SportmonksClient,
    match: Match,
    fixture: Dict[str, Any],
) -> int:
    """Pull latest balls from Sportmonks, treat timestamps, re-anchor chart if started."""
    detail = client.get_fixture(fixture["id"], includes="balls,scoreboards,batting,bowling,runs")
    apply_match_outcome(session, match, detail)
    balls_raw = _unwrap_list(detail.get("balls"))
    if not balls_raw:
        return 0

    existing = {
        row.sportmonks_ball_id: row
        for row in session.scalars(
            select(BallEvent).where(
                BallEvent.match_id == match.id,
                BallEvent.sportmonks_ball_id.is_not(None),
            )
        ).all()
        if row.sportmonks_ball_id is not None
    }

    written = 0
    updated = 0
    ball_seq = session.scalar(
        select(func.max(BallEvent.ball_seq)).where(BallEvent.match_id == match.id)
    ) or 0

    for raw in _sort_raw_deliveries(balls_raw):
        sm_id = raw.get("id")
        if sm_id is None:
            continue
        nb = normalize_ball(raw)
        event_utc = parse_utc(raw.get("updated_at"))
        if event_utc is None:
            continue

        if sm_id in existing:
            if _apply_ball_fields(existing[sm_id], nb):
                updated += 1
            continue

        inn_num = _innings_from_scoreboard(nb.get("scoreboard"))
        innings = _ensure_innings(session, match, inn_num, event_utc)
        ball_seq += 1
        session.add(
            BallEvent(
                match_id=match.id,
                innings_id=innings.id,
                over=nb.get("over"),
                ball=nb.get("ball"),
                ball_seq=ball_seq,
                runs=nb.get("runs"),
                extras=nb.get("extras"),
                is_wicket=bool(nb.get("is_wicket")),
                is_four=bool(nb.get("is_four")),
                is_six=bool(nb.get("is_six")),
                commentary=nb.get("commentary"),
                event_utc=event_utc,
                event_ist=to_ist(event_utc),
                time_source="sportmonks_ts",
                sportmonks_ball_id=sm_id,
            )
        )
        written += 1

    session.flush()
    touched = written + updated
    if session.scalar(select(func.count(BallEvent.id)).where(BallEvent.match_id == match.id)):
        _renumber_ball_seq_cricket(session, match.id)
        _recompute_running_totals(session, match.id)
    if touched:
        persist_treated_timestamps_for_match(session, match.id)
    apply_innings_batting_teams(session, match)

    started = _fixture_started(fixture, match) or touched > 0
    if started and match.lat and match.lon:
        anchor = chart_anchor_utc(fixture, match, session)
        last_corr = session.scalar(
            select(func.max(BallEvent.event_utc_corrected)).where(BallEvent.match_id == match.id)
        )
        write_match_chart(
            session,
            match,
            anchor_utc=anchor,
            duration_hours=LIVE_CHART_DURATION_HOURS,
            rebuild=True,
        )
        match.first_ball_utc = anchor
        match.first_ball_ist = to_ist(anchor)

    session.flush()
    return touched


def load_corrected_balls(session: Session, match_id: int) -> List[BallEvent]:
    return list(
        session.scalars(
            select(BallEvent)
            .where(BallEvent.match_id == match_id, BallEvent.event_utc_corrected.is_not(None))
            .order_by(BallEvent.ball_seq)
        ).all()
    )


def match_context_for_analysis(
    session: Session,
    match: Match,
    fixture: Dict[str, Any],
) -> Dict[str, Any]:
    """Build match_details dict for AnalysisEngine / run_live_analysis."""
    local = _unwrap_obj(fixture.get("localteam"))
    visitor = _unwrap_obj(fixture.get("visitorteam"))

    anchor = chart_anchor_utc(fixture, match, session)
    lt_name = local.get("name") or "Team A"
    vt_name = visitor.get("name") or "Team B"
    lt_short = (local.get("code") or "").strip() or lt_name[:3].upper()
    vt_short = (visitor.get("code") or "").strip() or vt_name[:3].upper()

    venue_name = "Unknown venue"
    venue_payload = _unwrap_obj(fixture.get("venue"))
    if venue_payload.get("name"):
        venue_name = venue_payload["name"]
        if venue_payload.get("city"):
            venue_name = f"{venue_name}, {venue_payload['city']}"
    if match.venue_id:
        from db.models import Venue  # noqa: PLC0415

        venue_row = session.get(Venue, match.venue_id)
        if venue_row and venue_row.name:
            venue_name = venue_row.name
            if venue_row.city:
                venue_name = f"{venue_name}, {venue_row.city}"

    return {
        "datetime_utc": anchor,
        "lat": match.lat,
        "lon": match.lon,
        "venue_name": venue_name,
        "team_a": lt_name,
        "team_b": vt_name,
        "team_a_short": lt_short,
        "team_b_short": vt_short,
        "localteam_id": match.localteam_id,
        "visitorteam_id": match.visitorteam_id,
        "toss_won_team_id": match.toss_won_team_id,
        "toss_elected": match.toss_elected,
        "duration_hours": LIVE_CHART_DURATION_HOURS,
        "ayanamsa": "KRISHNAMURTI",
        "sportmonks_fixture_id": fixture.get("id"),
        "scheduled_utc": parse_utc(fixture.get("starting_at")),
        "chart_anchor_utc": anchor,
        "match_status": str(fixture.get("status") or match.status or ""),
        "delay_sec": SPORTMONKS_DELAY_SEC,
    }
