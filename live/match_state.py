"""Read-only match state for UIs / APIs.

Everything here reads from the database, so a client can connect at any moment
(or reconnect later) and get the match's chart + scores "as of now" or "as of
any earlier instant". The supervisor writes; this module only reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import (
    AstroChart,
    AstroPlanet,
    BallAstroState,
    BallEvent,
    Innings,
    Match,
    OddsSnapshot,
    Team,
)
from live.aligner import ASC_RESOLUTION_LEVEL, MOON_RESOLUTION_LEVEL, find_active_period
from timeutils import to_ist


def _team_name(session: Session, team_id: Optional[int]) -> Optional[str]:
    if team_id is None:
        return None
    team = session.get(Team, team_id)
    return team.name if team else None


def list_matches(session: Session, limit: int = 50) -> List[Dict[str, Any]]:
    """List matches with light status info (for a match-picker UI)."""
    matches = session.scalars(select(Match).order_by(Match.starting_at_utc.desc()).limit(limit)).all()
    out = []
    for m in matches:
        balls_count = session.scalar(
            select(func.count(BallEvent.id)).where(BallEvent.match_id == m.id)
        ) or 0
        has_chart = session.scalar(
            select(func.count(AstroChart.id)).where(AstroChart.match_id == m.id)
        ) or 0
        out.append({
            "match_id": m.id,
            "fixture_id": m.sportmonks_fixture_id,
            "format": m.format,
            "localteam": _team_name(session, m.localteam_id),
            "visitorteam": _team_name(session, m.visitorteam_id),
            "status": m.status,
            "starting_at_utc": _iso(m.starting_at_utc),
            "starting_at_ist": _iso(m.starting_at_ist),
            "first_ball_utc": _iso(m.first_ball_utc),
            "first_ball_ist": _iso(m.first_ball_ist),
            "has_chart": bool(has_chart),
            "balls": balls_count,
        })
    return out


def get_match_state(
    session: Session,
    match_id: int,
    as_of: Optional[datetime] = None,
    last_n_balls: int = 12,
) -> Optional[Dict[str, Any]]:
    """Full match snapshot as of ``as_of`` (default: now / all balls).

    Returns None if the match doesn't exist.
    """
    match = session.get(Match, match_id)
    if match is None:
        return None

    ball_filter = [BallEvent.match_id == match_id]
    if as_of is not None:
        ball_filter.append(BallEvent.event_utc <= as_of)

    # Innings summaries (computed up to as_of so older snapshots are accurate).
    innings_rows = session.scalars(
        select(Innings).where(Innings.match_id == match_id).order_by(Innings.innings_number)
    ).all()
    innings_summary = []
    for inn in innings_rows:
        as_of_clause = [BallEvent.event_utc <= as_of] if as_of else []
        runs = session.scalar(
            select(func.coalesce(func.sum(BallEvent.runs + func.coalesce(BallEvent.extras, 0)), 0))
            .where(BallEvent.innings_id == inn.id, *as_of_clause)
        ) or 0
        wkts = session.scalar(
            select(func.count(BallEvent.id))
            .where(BallEvent.innings_id == inn.id, BallEvent.is_wicket.is_(True), *as_of_clause)
        ) or 0
        deliveries = session.scalar(
            select(func.count(BallEvent.id))
            .where(BallEvent.innings_id == inn.id, *as_of_clause)
        ) or 0
        if deliveries == 0:
            continue
        innings_summary.append({
            "innings_number": inn.innings_number,
            "runs": int(runs),
            "wickets": int(wkts),
            "deliveries": int(deliveries),
        })

    # Recent balls (most recent last_n, oldest-first for display).
    recent = session.scalars(
        select(BallEvent).where(*ball_filter).order_by(BallEvent.event_utc.desc()).limit(last_n_balls)
    ).all()
    recent = list(reversed(recent))
    recent_balls = []
    for b in recent:
        st = session.scalar(select(BallAstroState).where(BallAstroState.ball_id == b.id))
        recent_balls.append({
            "event_utc": _iso(b.event_utc),
            "event_ist": _iso(b.event_ist),
            "over": b.over,
            "ball": b.ball,
            "runs": b.runs,
            "extras": b.extras,
            "is_wicket": b.is_wicket,
            "is_four": b.is_four,
            "is_six": b.is_six,
            "score_after": b.score_after,
            "wickets_after": b.wickets_after,
            "asc": _lords(st, "asc") if st else None,
            "moon": _lords(st, "moon") if st else None,
        })

    # "Current" KP period: at as_of if given, else at the latest ingested ball
    # (so reviewing a match reflects its last delivery rather than wall-clock now).
    effective_ts = as_of
    if effective_ts is None:
        effective_ts = session.scalar(
            select(func.max(BallEvent.event_utc)).where(BallEvent.match_id == match_id)
        ) or datetime.utcnow()

    return {
        "match": {
            "match_id": match.id,
            "fixture_id": match.sportmonks_fixture_id,
            "format": match.format,
            "localteam": _team_name(session, match.localteam_id),
            "visitorteam": _team_name(session, match.visitorteam_id),
            "status": match.status,
            "starting_at_utc": _iso(match.starting_at_utc),
            "starting_at_ist": _iso(match.starting_at_ist),
            "first_ball_utc": _iso(match.first_ball_utc),
            "first_ball_ist": _iso(match.first_ball_ist),
            "lat": match.lat,
            "lon": match.lon,
        },
        "as_of_utc": _iso(as_of),
        "as_of_ist": _iso(to_ist(as_of)),
        "chart": _chart_summary(session, match_id),
        "innings": innings_summary,
        "current_astro": _current_astro(session, match_id, effective_ts),
        "recent_balls": recent_balls,
        "total_balls": session.scalar(select(func.count(BallEvent.id)).where(*ball_filter)) or 0,
        "odds": _latest_odds(session, match_id, as_of),
    }


def _latest_odds(session: Session, match_id: int, as_of: Optional[datetime]) -> List[Dict[str, Any]]:
    """Latest odd value per (market, bookmaker, selection) as of the given time."""
    clause = [OddsSnapshot.match_id == match_id]
    if as_of is not None:
        clause.append(OddsSnapshot.captured_utc <= as_of)
    rows = session.scalars(
        select(OddsSnapshot).where(*clause).order_by(OddsSnapshot.captured_utc.desc()).limit(200)
    ).all()
    latest: Dict[tuple, Dict[str, Any]] = {}
    for o in rows:
        key = (o.market, o.bookmaker, o.selection)
        if key in latest:
            continue
        latest[key] = {
            "market": o.market,
            "bookmaker": o.bookmaker,
            "selection": o.selection,
            "odd_value": o.odd_value,
            "is_inplay": o.is_inplay,
            "captured_utc": _iso(o.captured_utc),
            "captured_ist": _iso(o.captured_ist),
            "moon_ssl": o.moon_ssl,
            "moon_sssl": o.moon_sssl,
        }
    return list(latest.values())


def _chart_summary(session: Session, match_id: int) -> Optional[Dict[str, Any]]:
    chart = session.scalar(select(AstroChart).where(AstroChart.match_id == match_id))
    if chart is None:
        return None
    planets = session.scalars(
        select(AstroPlanet).where(AstroPlanet.chart_id == chart.id)
    ).all()
    return {
        "datetime_utc": _iso(chart.datetime_utc),
        "datetime_ist": _iso(chart.datetime_ist),
        "ayanamsa": chart.ayanamsa,
        "ayanamsa_value": chart.ayanamsa_value,
        "duration_hours": chart.duration_hours,
        "planets": [
            {
                "planet": p.planet, "sign": p.sign, "longitude": round(p.longitude, 3) if p.longitude else None,
                "nl": p.nl, "sl": p.sl, "ssl": p.ssl, "sssl": p.sssl,
                "retrograde": p.is_retrograde,
                "significators": p.significators,
                "significators_display": p.significators_display,
            }
            for p in planets
        ],
    }


def _current_astro(session: Session, match_id: int, ts: datetime) -> Dict[str, Any]:
    asc = find_active_period(session, match_id, "Ascendant", ts, level=ASC_RESOLUTION_LEVEL)
    moon = find_active_period(session, match_id, "Moon", ts, level=MOON_RESOLUTION_LEVEL)
    return {
        "at_utc": _iso(ts),
        "at_ist": _iso(to_ist(ts)),
        "ascendant": {"nl": asc.nl, "sl": asc.sl} if asc else None,
        "moon": {"nl": moon.nl, "sl": moon.sl, "ssl": moon.ssl, "sssl": moon.sssl} if moon else None,
    }


def _lords(state: BallAstroState, prefix: str) -> Dict[str, Any]:
    return {
        "nl": getattr(state, f"{prefix}_nl"),
        "sl": getattr(state, f"{prefix}_sl"),
        "ssl": getattr(state, f"{prefix}_ssl"),
        "sssl": getattr(state, f"{prefix}_sssl"),
    }


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None
