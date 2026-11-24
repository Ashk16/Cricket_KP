"""Migration: add IST (UTC+5:30) timestamp columns and backfill them.

Adds the new ``*_ist`` columns to existing tables (SQLite ADD COLUMN) and
populates them from the corresponding UTC columns for all existing rows.

Idempotent: skips columns that already exist and the UPDATE is safe to re-run.
Run once after pulling the schema change:

    python migrate_add_ist.py
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine, init_db

# (table, [(utc_col, ist_col), ...])
IST_COLUMNS = [
    ("matches", [("starting_at_utc", "starting_at_ist"), ("first_ball_utc", "first_ball_ist")]),
    ("innings", [("start_utc", "start_ist"), ("end_utc", "end_ist")]),
    ("ball_events", [("event_utc", "event_ist")]),
    ("astro_charts", [("datetime_utc", "datetime_ist")]),
    ("astro_timeline_periods", [("start_utc", "start_ist"), ("end_utc", "end_ist")]),
    ("odds_snapshots", [("captured_utc", "captured_ist")]),
]

# IST is UTC + 5h30m = +330 minutes.
IST_SHIFT = "+330 minutes"


def _existing_columns(conn, table: str) -> set:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def main() -> None:
    # Make sure base tables exist (fresh DBs get the columns from create_all).
    init_db()

    with engine.begin() as conn:
        for table, pairs in IST_COLUMNS:
            cols = _existing_columns(conn, table)
            if not cols:
                print(f"  [skip] table {table} does not exist")
                continue
            for utc_col, ist_col in pairs:
                if ist_col not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ist_col} DATETIME"))
                    print(f"  [add ] {table}.{ist_col}")
                else:
                    print(f"  [have] {table}.{ist_col}")
                result = conn.execute(text(
                    f"UPDATE {table} SET {ist_col} = datetime({utc_col}, '{IST_SHIFT}') "
                    f"WHERE {utc_col} IS NOT NULL"
                ))
                print(f"         backfilled {result.rowcount} row(s) from {utc_col}")

    print("\nIST migration complete.")


if __name__ == "__main__":
    main()
