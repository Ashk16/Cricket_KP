"""Report how current the historical match backfill is."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import func, select

load_dotenv()

from db.models import Match, Player
from db.session import SessionLocal, init_db


def main() -> None:
    init_db()
    today = date.today()
    with SessionLocal() as session:
        latest_fb = session.scalar(select(func.max(Match.first_ball_utc)))
        latest_sched = session.scalar(select(func.max(Match.starting_at_utc)))
        total = session.scalar(select(func.count()).select_from(Match)) or 0
        named = session.scalar(
            select(func.count()).select_from(Player).where(~Player.name.like("player_%"))
        ) or 0
        placeholders = session.scalar(
            select(func.count()).select_from(Player).where(Player.name.like("player_%"))
        ) or 0

        print("Historical DB status")
        print("=" * 50)
        print(f"Total matches:           {total:,}")
        print(f"Latest scheduled start:  {latest_sched}")
        print(f"Latest first ball:       {latest_fb}")
        print(f"Players with real names: {named:,}")
        print(f"Players placeholder:     {placeholders:,}")
        if latest_fb:
            gap = (today - latest_fb.date()).days
            print(f"Gap to today:            {gap} day(s)")
            if gap > 0:
                print(f"\nRun backfill for gap:")
                print(f"  python run_backfill.py {latest_fb.year} --end-date {today.isoformat()}")


if __name__ == "__main__":
    main()
