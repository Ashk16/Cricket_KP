"""Odds capture (optional / plan-gated).

Stores odds as a time series: each time a bookmaker value changes we write one
``OddsSnapshot``, stamped with our capture time and aligned to the active KP
period (so odds movement can be studied against astrology periods, mirroring the
"live score confirmation" idea in the project spec).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import OddsSnapshot
from live.aligner import ASC_RESOLUTION_LEVEL, MOON_RESOLUTION_LEVEL, find_active_period
from live.match_setup import parse_utc
from timeutils import to_ist


def capture_odds(
    session: Session,
    match_id: int,
    normalized_odds: List[Dict[str, Any]],
    captured_utc: datetime,
    is_inplay: bool = True,
) -> int:
    """Persist changed odds as snapshots. Returns the number of new snapshots.

    Dedup key: (match, market, bookmaker, selection, updated_at_source). If the
    bookmaker's last-update timestamp hasn't changed, we don't store a duplicate.
    When the API gives no update timestamp, we fall back to comparing the value.
    """
    if not normalized_odds:
        return 0

    asc = find_active_period(session, match_id, "Ascendant", captured_utc, level=ASC_RESOLUTION_LEVEL)
    moon = find_active_period(session, match_id, "Moon", captured_utc, level=MOON_RESOLUTION_LEVEL)

    new = 0
    for odd in normalized_odds:
        if odd.get("odd_value") is None:
            continue
        updated_src = parse_utc(odd.get("updated_at_source"))

        if _is_duplicate(session, match_id, odd, updated_src):
            continue

        session.add(OddsSnapshot(
            match_id=match_id,
            captured_utc=captured_utc,
            captured_ist=to_ist(captured_utc),
            updated_at_source=updated_src,
            market=odd.get("market"),
            bookmaker=odd.get("bookmaker"),
            selection=odd.get("selection"),
            odd_value=odd.get("odd_value"),
            is_inplay=is_inplay,
            raw=odd.get("raw"),
            asc_ssl=None,   # Ascendant only persisted at NL/SL now.
            asc_sssl=None,
            moon_ssl=moon.ssl if moon else None,
            moon_sssl=moon.sssl if moon else None,
            asc_period_id=asc.id if asc else None,
            moon_period_id=moon.id if moon else None,
        ))
        new += 1

    session.flush()
    return new


def _is_duplicate(
    session: Session,
    match_id: int,
    odd: Dict[str, Any],
    updated_src: Optional[datetime],
) -> bool:
    base = [
        OddsSnapshot.match_id == match_id,
        OddsSnapshot.market == odd.get("market"),
        OddsSnapshot.bookmaker == odd.get("bookmaker"),
        OddsSnapshot.selection == odd.get("selection"),
    ]
    if updated_src is not None:
        existing = session.scalar(
            select(OddsSnapshot.id).where(*base, OddsSnapshot.updated_at_source == updated_src)
        )
        return existing is not None

    # No source timestamp: treat an unchanged latest value as a duplicate.
    latest = session.scalar(
        select(OddsSnapshot.odd_value)
        .where(*base)
        .order_by(OddsSnapshot.captured_utc.desc())
        .limit(1)
    )
    return latest is not None and latest == odd.get("odd_value")
