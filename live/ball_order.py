"""Cricket delivery order helpers (over / ball), independent of Sportmonks updated_at."""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple


def delivery_sort_key(over: Any, ball_in_over: Any, tiebreaker: int = 0) -> Tuple[int, int, int]:
    """Sort key for one delivery: over, ball in over, stable tiebreaker."""
    o = int(over) if over is not None else -1
    b = int(ball_in_over) if ball_in_over is not None else -1
    return (o, b, tiebreaker)


def ball_event_cricket_key(row) -> Tuple[int, int, int]:
    """SQLAlchemy BallEvent or compatible row."""
    rid = int(getattr(row, "id", 0) or 0)
    return delivery_sort_key(getattr(row, "over", None), getattr(row, "ball", None), rid)


def sort_ball_events_cricket(balls: Sequence) -> List:
    """Return balls sorted by over, then ball, then id (wides / duplicates)."""
    return sorted(balls, key=ball_event_cricket_key)


def sort_db_ball_rows_cricket(rows: Sequence) -> List:
    """Rows from persist_treated_timestamps query (over index 4, ball 5 in tuple)."""
    # (id, ball_seq, innings_number, over, ball, event_utc, commentary, is_wicket)
    return sorted(
        rows,
        key=lambda r: (
            int(r[2]),
            delivery_sort_key(r[3], r[4], int(r[0] or 0)),
        ),
    )