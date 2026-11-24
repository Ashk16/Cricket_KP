"""Entrypoint for the always-on supervisor daemon.

Runs independently of any UI. It watches the Sportmonks schedule, auto-generates
each match's KP chart on the first ball, and continuously stores + aligns balls.

Usage:
  python run_daemon.py                 # run forever
  POLL_INTERVAL=15 python run_daemon.py

Also starts a 1:00 AM IST historical ingest thread unless NIGHTLY_BACKFILL=0.
"""

from __future__ import annotations

import logging
import os

from db.session import SessionLocal, init_db
from live.sportmonks_client import SportmonksClient
from live.supervisor import Supervisor


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()

    if os.getenv("NIGHTLY_BACKFILL", "1") != "0":
        from live.nightly_backfill import start_nightly_thread

        start_nightly_thread(SessionLocal)

    client = SportmonksClient()  # reads SPORTMONKS_API_KEY from env/.env
    supervisor = Supervisor(
        client=client,
        session_factory=SessionLocal,
        poll_interval=float(os.getenv("POLL_INTERVAL", "30")),
        schedule_refresh_seconds=float(os.getenv("SCHEDULE_REFRESH", "300")),
        days_ahead=int(os.getenv("SCHEDULE_DAYS_AHEAD", "2")),
        allow_ai_coords=os.getenv("ALLOW_AI_COORDS", "1") != "0",
        capture_odds=os.getenv("CAPTURE_ODDS", "0") == "1",
    )
    supervisor.run()


if __name__ == "__main__":
    main()
