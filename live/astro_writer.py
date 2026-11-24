"""Generate and persist a match's event chart + timelines.

Called once when a match is set up (at/near match start). Produces the
muhurta/event chart, planetary table, cusp table, and the Ascendant + Moon
timelines, and writes them into the astro_* tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from astro.chart_service import build_match_chart
from db.models import (
    AstroChart,
    AstroCusp,
    AstroPlanet,
    AstroTimelinePeriod,
    Match,
)
from timeutils import to_ist

# Default timeline duration (hours) by match format.
DURATION_BY_FORMAT = {
    "T20": 4.0,
    "T20I": 4.0,
    "ODI": 9.0,
    "TEST": 8.0,
    "TEST_DAY": 8.0,
}
DEFAULT_DURATION_HOURS = 4.0
# Live dashboard + day DB charts always span this many hours from the anchor.
LIVE_CHART_DURATION_HOURS = 9.0
BUFFER_AFTER_LAST_BALL = timedelta(minutes=15)
MIN_DURATION_HOURS = 1.0
MAX_DURATION_HOURS = 120.0  # cap for multi-day Tests


def duration_for_format(fmt: Optional[str]) -> float:
    if not fmt:
        return DEFAULT_DURATION_HOURS
    return DURATION_BY_FORMAT.get(fmt.upper(), DEFAULT_DURATION_HOURS)


def duration_for_match(
    anchor_utc: Optional[datetime],
    last_ball_utc: Optional[datetime],
    fmt: Optional[str] = None,
) -> float:
    """Timeline span from chart anchor through last ball + 15 minutes.

    Falls back to format-based defaults when last-ball time is not known yet
    (live first-ball chart generation).
    """
    if anchor_utc and last_ball_utc and last_ball_utc >= anchor_utc:
        hours = (last_ball_utc - anchor_utc + BUFFER_AFTER_LAST_BALL).total_seconds() / 3600.0
        hours = max(hours, MIN_DURATION_HOURS)
        return min(hours, MAX_DURATION_HOURS)
    return duration_for_format(fmt)


def write_match_chart(
    session: Session,
    match: Match,
    duration_hours: Optional[float] = None,
    ayanamsa: str = "KRISHNAMURTI",
    rebuild: bool = False,
    anchor_utc: Optional[datetime] = None,
) -> AstroChart:
    """Build and persist the chart + timelines for ``match``.

    Args:
        session: Active DB session.
        match: A persisted Match with lat, lon.
        duration_hours: Override timeline duration; default derived from format.
        ayanamsa: Sidereal ayanamsa (KP/Krishnamurti default).
        rebuild: If True, delete an existing chart first and regenerate.
        anchor_utc: The instant to cast the chart at. Defaults to the match's
            first_ball_utc, then its scheduled starting_at_utc. The chart is
            anchored to actual first ball when play starts late.

    Returns:
        The persisted AstroChart.
    """
    chart_dt = anchor_utc or match.first_ball_utc or match.starting_at_utc
    if chart_dt is None or match.lat is None or match.lon is None:
        raise ValueError(
            "Match needs an anchor time (first_ball_utc/starting_at_utc) and lat/lon "
            "before a chart can be built."
        )

    existing = session.scalar(select(AstroChart).where(AstroChart.match_id == match.id))
    if existing is not None:
        if not rebuild:
            return existing
        session.delete(existing)
        session.flush()

    if duration_hours is None:
        duration_hours = duration_for_match(chart_dt, None, match.format)

    chart = build_match_chart(
        datetime_utc=chart_dt,
        lat=match.lat,
        lon=match.lon,
        duration_hours=duration_hours,
        ayanamsa=ayanamsa,
    )

    chart_dt_naive = chart.datetime_utc.replace(tzinfo=None)
    astro_chart = AstroChart(
        match_id=match.id,
        datetime_utc=chart_dt_naive,
        datetime_ist=to_ist(chart_dt_naive),
        lat=chart.lat,
        lon=chart.lon,
        ayanamsa=chart.ayanamsa,
        ayanamsa_value=chart.ayanamsa_value,
        julian_day=chart.julian_day,
        duration_hours=chart.duration_hours,
    )
    session.add(astro_chart)
    session.flush()  # assign astro_chart.id

    session.add_all(
        AstroPlanet(
            chart_id=astro_chart.id,
            planet=p.planet,
            longitude=p.longitude,
            sign=p.sign,
            sign_lord=p.sign_lord,
            nl=p.nl,
            sl=p.sl,
            ssl=p.ssl,
            sssl=p.sssl,
            is_retrograde=p.is_retrograde,
            speed=p.speed,
            significators=p.significators,
            significators_display=p.significators_display,
        )
        for p in chart.planets
    )

    session.add_all(
        AstroCusp(
            chart_id=astro_chart.id,
            cusp_no=c.cusp_no,
            longitude=c.longitude,
            sign=c.sign,
            sign_lord=c.sign_lord,
            nl=c.nl,
            sl=c.sl,
            ssl=c.ssl,
            sssl=c.sssl,
        )
        for c in chart.cusps
    )

    def _naive(dt):
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    session.add_all(
        AstroTimelinePeriod(
            chart_id=astro_chart.id,
            match_id=match.id,
            body=t.body,
            level=t.level,
            start_utc=_naive(t.start_utc),
            end_utc=_naive(t.end_utc),
            start_ist=to_ist(_naive(t.start_utc)),
            end_ist=to_ist(_naive(t.end_utc)),
            nl=t.nl,
            sl=t.sl,
            ssl=t.ssl,
            sssl=t.sssl,
            longitude_start=t.longitude_start,
        )
        for t in chart.timeline
    )

    session.flush()
    return astro_chart
