"""High-level chart service.

Wraps the ported KP engine + timeline generator into a single entry point
that produces everything the rest of the system needs for one match:

- the muhurta / event chart metadata (cast at match start),
- the planetary table,
- the cusp table,
- the Ascendant timeline (NL and SL levels),
- the Moon timeline (SSL and SSSL levels).

This module performs NO prediction or scoring. It only generates raw
astrological data that downstream modules (alignment, learning, live) consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import pandas as pd

from astro.kp_engine import KPEngine
from astro.significators import significators_for_engine
from astro.timeline_generator import TimelineGenerator

# Bodies and the sub-lord levels we persist per body for cricket alignment.
# The Ascendant moves fast, so we only keep the coarser NL/SL layers (SSL/SSSL
# would be seconds long and add no usable signal). The Moon is slow, so we keep
# the finer SSL/SSSL layers.
TIMELINE_BODIES = ("Ascendant", "Moon")
BODY_LEVELS = {
    "Ascendant": ("NL", "SL"),
    "Moon": ("SSL", "SSSL"),
}
# Default for any body not explicitly listed.
TIMELINE_LEVELS = ("SSL", "SSSL")

_LEVEL_TO_DF_KEY = {
    "NL": "nl_timeline",
    "SL": "sl_timeline",
    "SSL": "ssl_timeline",
    "SSSL": "sssl_timeline",
}


@dataclass
class PlanetPosition:
    planet: str
    longitude: float
    sign: str
    sign_lord: str
    nl: str
    sl: str
    ssl: str
    sssl: str
    is_retrograde: bool = False
    speed: Optional[float] = None
    significators: Optional[list] = None
    significators_display: Optional[str] = None


@dataclass
class CuspPosition:
    cusp_no: int
    longitude: float
    sign: str
    sign_lord: str
    nl: str
    sl: str
    ssl: str
    sssl: str


@dataclass
class TimelinePeriod:
    body: str          # 'Ascendant' or 'Moon'
    level: str         # 'NL' | 'SL' | 'SSL' | 'SSSL'
    start_utc: datetime
    end_utc: datetime
    nl: str
    sl: str
    ssl: str
    sssl: str
    longitude_start: Optional[float] = None


@dataclass
class MatchChart:
    """All raw astrological data for a single match's event chart."""
    datetime_utc: datetime
    lat: float
    lon: float
    ayanamsa: str
    ayanamsa_value: float
    julian_day: float
    duration_hours: float
    planets: List[PlanetPosition] = field(default_factory=list)
    cusps: List[CuspPosition] = field(default_factory=list)
    timeline: List[TimelinePeriod] = field(default_factory=list)


def _planet_positions(engine: KPEngine) -> List[PlanetPosition]:
    sig_by_planet = significators_for_engine(engine)
    positions: List[PlanetPosition] = []
    for name, d in engine.planets.items():
        sig = sig_by_planet.get(name, {})
        positions.append(
            PlanetPosition(
                planet=name,
                longitude=d.get("longitude"),
                sign=d.get("sign"),
                sign_lord=d.get("sign_lord"),
                nl=d.get("nl"),
                sl=d.get("sl"),
                ssl=d.get("ssl"),
                sssl=d.get("sssl"),
                is_retrograde=bool(d.get("is_retrograde", False)),
                speed=d.get("speed"),
                significators=sig.get("significators"),
                significators_display=sig.get("significators_display"),
            )
        )
    return positions


def _cusp_positions(engine: KPEngine) -> List[CuspPosition]:
    cusps: List[CuspPosition] = []
    for cusp_no, d in engine.cusps.items():
        cusps.append(
            CuspPosition(
                cusp_no=int(cusp_no),
                longitude=d.get("longitude"),
                sign=d.get("sign"),
                sign_lord=d.get("sign_lord"),
                nl=d.get("nl"),
                sl=d.get("sl"),
                ssl=d.get("ssl"),
                sssl=d.get("sssl"),
            )
        )
    return cusps


def _timeline_periods_for_body(
    engine: KPEngine,
    body: str,
    start_dt: datetime,
    duration_hours: float,
    levels=TIMELINE_LEVELS,
) -> List[TimelinePeriod]:
    """Generate timeline periods for one body at the requested levels."""
    generator = TimelineGenerator(engine, body)
    detailed = generator.generate_detailed_timeline_df(start_dt, duration_hours)

    periods: List[TimelinePeriod] = []
    for level in levels:
        df: pd.DataFrame = detailed.get(_LEVEL_TO_DF_KEY[level], pd.DataFrame())
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            periods.append(
                TimelinePeriod(
                    body=body,
                    level=level,
                    start_utc=_to_datetime(row["Start Time"]),
                    end_utc=_to_datetime(row["End Time"]),
                    nl=row.get("NL_Planet"),
                    sl=row.get("SL_Planet"),
                    ssl=row.get("SSL_Planet"),
                    sssl=row.get("SSSL_Planet"),
                )
            )
    return periods


def _to_datetime(value) -> datetime:
    """Coerce pandas Timestamp / datetime into a plain datetime."""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def build_match_chart(
    datetime_utc: datetime,
    lat: float,
    lon: float,
    duration_hours: float,
    ayanamsa: str = "KRISHNAMURTI",
    bodies=TIMELINE_BODIES,
    body_levels=BODY_LEVELS,
) -> MatchChart:
    """Build the full event chart + timelines for a match.

    Args:
        datetime_utc: Match start (UTC, timezone-aware or naive UTC).
        lat: Venue latitude.
        lon: Venue longitude.
        duration_hours: How long to generate timelines for.
        ayanamsa: Ayanamsa for sidereal calc (KP/Krishnamurti by default).
        bodies: Which bodies to build timelines for.
        body_levels: Mapping of body -> sub-lord levels to persist for it.

    Returns:
        A populated MatchChart.
    """
    # KPEngine expects a naive UTC datetime for Julian-day computation.
    engine_dt = datetime_utc.replace(tzinfo=None) if datetime_utc.tzinfo else datetime_utc

    engine = KPEngine(dt=engine_dt, lat=lat, lon=lon, ayanamsa=ayanamsa)

    timeline: List[TimelinePeriod] = []
    for body in bodies:
        levels = body_levels.get(body, TIMELINE_LEVELS)
        timeline.extend(
            _timeline_periods_for_body(engine, body, engine_dt, duration_hours, levels)
        )

    return MatchChart(
        datetime_utc=datetime_utc,
        lat=lat,
        lon=lon,
        ayanamsa=ayanamsa,
        ayanamsa_value=engine.ayanamsa_value,
        julian_day=engine.jd,
        duration_hours=duration_hours,
        planets=_planet_positions(engine),
        cusps=_cusp_positions(engine),
        timeline=timeline,
    )


if __name__ == "__main__":
    from datetime import timezone

    chart = build_match_chart(
        datetime_utc=datetime(2025, 7, 4, 17, 35, tzinfo=timezone.utc),
        lat=51.4821031,
        lon=-0.1117327,
        duration_hours=4.5,
    )
    print(f"Ayanamsa: {chart.ayanamsa} ({chart.ayanamsa_value:.4f} deg)")
    print(f"Planets: {len(chart.planets)} | Cusps: {len(chart.cusps)}")
    print(f"Timeline periods: {len(chart.timeline)}")
    moon = next(p for p in chart.planets if p.planet == "Moon")
    print(f"Moon: {moon.longitude:.3f} {moon.sign} NL={moon.nl} SL={moon.sl} SSL={moon.ssl}")
