"""Time helpers.

The whole system stores canonical timestamps as **naive UTC** (this is what the
KP/Swiss-Ephemeris engine computes against, together with venue lat/lon).

For convenience we also denormalize an **IST** (Indian Standard Time, UTC+5:30)
representation of every timestamp, so the same single clock can be used across
cricket data and astrology data when viewing/analyzing - instead of localizing
to each venue's timezone.

IMPORTANT: IST is a *display/working* representation only. It is derived from the
UTC instant and never feeds back into the astronomical calculation (which must
use the true UTC moment + the venue's coordinates).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# India has a single, fixed timezone with no daylight saving.
IST_OFFSET = timedelta(hours=5, minutes=30)


def to_ist(dt_utc: Optional[datetime]) -> Optional[datetime]:
    """Convert a naive UTC datetime to a naive IST datetime (UTC + 5:30).

    Returns None if the input is None. Aware datetimes are normalized to UTC
    first; the result is naive to match how the rest of the schema stores
    datetimes.
    """
    if dt_utc is None:
        return None
    if dt_utc.tzinfo is not None:
        dt_utc = dt_utc.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_utc + IST_OFFSET


def now_utc() -> datetime:
    """Naive UTC 'now' (matches how the rest of the schema stores instants)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_ist() -> datetime:
    """Naive IST 'now' (UTC + 5:30)."""
    return now_utc() + IST_OFFSET


def next_ist_clock_time(now: Optional[datetime] = None, *, hour: int = 4, minute: int = 0) -> datetime:
    """Next occurrence of ``hour:minute`` on the naive IST clock.

    If ``now`` is already at or past that clock time, returns tomorrow.
    """
    now = now if now is not None else now_ist()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target
