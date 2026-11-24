"""Dump ball timestamps for a live fixture (raw / treated / corrected IST)."""

from __future__ import annotations

import sys
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from db.models import BallEvent
from live.day_manager import ensure_fixture_in_day_db, fetch_fixtures_for_date, fixture_label, sync_balls
from live.day_session import day_session
from live.sportmonks_client import SportmonksClient


def main() -> None:
    fixture_id = int(sys.argv[1]) if len(sys.argv) > 1 else 69951
    day = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 6, 9)

    client = SportmonksClient()
    fixtures = fetch_fixtures_for_date(client, day)
    fixture = next(f for f in fixtures if f["id"] == fixture_id)

    print(fixture_label(fixture), "| status:", fixture.get("status"))
    print()

    with day_session(day) as session:
        match = ensure_fixture_in_day_db(session, client, fixture)
        n = sync_balls(session, client, match, fixture)
        balls = list(
            session.scalars(
                select(BallEvent)
                .where(BallEvent.match_id == match.id)
                .order_by(BallEvent.ball_seq)
            ).all()
        )

    print(f"Synced {n} new ball(s). Total balls: {len(balls)}")
    print()
    hdr = (
        f"{'seq':>4} {'ball':>5} {'raw_utc':>19} {'raw_ist':>19} "
        f"{'treated_ist':>19} {'corrected_ist':>19} {'corr_s':>6} {'runs':>4} {'w':>2}"
    )
    print(hdr)
    print("-" * len(hdr))

    show = balls if len(balls) <= 40 else balls[-40:]
    if len(balls) > 40:
        print(f"(showing last 40 of {len(balls)} balls)\n")

    for b in show:
        ob = f"{b.over}.{b.ball}" if b.over is not None and b.ball is not None else "?"
        print(
            f"{b.ball_seq:4} {ob:>5} "
            f"{str(b.event_utc)[:19]:>19} "
            f"{str(b.event_ist)[:19]:>19} "
            f"{str(b.event_ist_treated)[:19]:>19} "
            f"{str(b.event_ist_corrected)[:19]:>19} "
            f"{(b.time_correction_sec or 0):6.0f} "
            f"{(b.runs or 0):4} "
            f"{int(bool(b.is_wicket)):2}"
        )


if __name__ == "__main__":
    main()
