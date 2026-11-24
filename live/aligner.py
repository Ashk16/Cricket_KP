"""Align cricket balls to the astrology timeline.

For a ball's ``event_utc`` we find the active period for each body at that body's
finest persisted level:

- Ascendant -> SL level (fast-moving; we keep only NL/SL). The SL row carries
  both the NL and SL lords.
- Moon -> SSSL level (slow-moving; SSSL rows carry all four lords).

We denormalize the active lords into ``ball_astro_state`` for fast downstream
rule mining.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AstroTimelinePeriod, BallAstroState, BallEvent
from live.ball_timestamp_treatment import ball_alignment_utc

# Finest level persisted per body (see astro.chart_service.BODY_LEVELS).
ASC_RESOLUTION_LEVEL = "SL"
MOON_RESOLUTION_LEVEL = "SSSL"


def find_active_period(
    session: Session,
    match_id: int,
    body: str,
    ts: datetime,
    level: str = MOON_RESOLUTION_LEVEL,
) -> Optional[AstroTimelinePeriod]:
    """Return the period covering ``ts`` for the given body/level, if any."""
    stmt = (
        select(AstroTimelinePeriod)
        .where(
            AstroTimelinePeriod.match_id == match_id,
            AstroTimelinePeriod.body == body,
            AstroTimelinePeriod.level == level,
            AstroTimelinePeriod.start_utc <= ts,
            AstroTimelinePeriod.end_utc > ts,
        )
        .order_by(AstroTimelinePeriod.start_utc.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def align_ball(session: Session, ball: BallEvent, rebuild: bool = False) -> Optional[BallAstroState]:
    """Compute and persist the BallAstroState for a single ball.

    Returns the state, or None if the ball has no event_utc yet.
    """
    ts = ball_alignment_utc(ball)
    if ts is None:
        return None

    existing = session.scalar(
        select(BallAstroState).where(BallAstroState.ball_id == ball.id)
    )
    if existing is not None and not rebuild:
        return existing
    asc = find_active_period(session, ball.match_id, "Ascendant", ts, level=ASC_RESOLUTION_LEVEL)
    moon = find_active_period(session, ball.match_id, "Moon", ts, level=MOON_RESOLUTION_LEVEL)

    state = existing or BallAstroState(ball_id=ball.id)
    # Ascendant: only NL/SL are persisted; SSL/SSSL intentionally left null.
    state.asc_nl = asc.nl if asc else None
    state.asc_sl = asc.sl if asc else None
    state.asc_ssl = None
    state.asc_sssl = None
    state.asc_period_id = asc.id if asc else None

    state.moon_nl = moon.nl if moon else None
    state.moon_sl = moon.sl if moon else None
    state.moon_ssl = moon.ssl if moon else None
    state.moon_sssl = moon.sssl if moon else None
    state.moon_period_id = moon.id if moon else None

    if existing is None:
        session.add(state)
    session.flush()
    return state


def align_match(session: Session, match_id: int, rebuild: bool = False) -> int:
    """Align all balls of a match that have an event_utc. Returns count aligned."""
    balls = session.scalars(
        select(BallEvent).where(
            BallEvent.match_id == match_id,
            BallEvent.event_utc_corrected.is_not(None) | BallEvent.event_utc.is_not(None),
        )
    ).all()

    count = 0
    for ball in balls:
        if align_ball(session, ball, rebuild=rebuild) is not None:
            count += 1
    return count
