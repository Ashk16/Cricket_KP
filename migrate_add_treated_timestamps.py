"""Migration: add treated + corrected timestamp columns to ball_events.

Idempotent. Run once before batch treatment:

    python migrate_add_treated_timestamps.py
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine, init_db

NEW_COLUMNS = [
    ("event_utc_treated", "DATETIME"),
    ("event_ist_treated", "DATETIME"),
    ("event_utc_corrected", "DATETIME"),
    ("event_ist_corrected", "DATETIME"),
    ("time_correction_sec", "FLOAT"),
    ("timestamp_in_burst", "BOOLEAN DEFAULT 0"),
]


def _existing_columns(conn, table: str) -> set:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def main() -> None:
    init_db()
    with engine.begin() as conn:
        cols = _existing_columns(conn, "ball_events")
        for col_name, col_type in NEW_COLUMNS:
            if col_name not in cols:
                conn.execute(text(f"ALTER TABLE ball_events ADD COLUMN {col_name} {col_type}"))
                print(f"  [add ] ball_events.{col_name}")
            else:
                print(f"  [have] ball_events.{col_name}")
    print("\nTreated-timestamp columns ready.")


if __name__ == "__main__":
    main()
