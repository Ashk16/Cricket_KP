"""Nightly historical ingest entrypoint.

Default: one pass over recently finished fixtures (lookback through yesterday IST).
Schedule: 1:00 AM IST via ``--daemon``, the live ``run_daemon.py`` background
thread, or Windows Task Scheduler (``scripts/install_nightly_task.ps1``).

Examples:
    python run_nightly_backfill.py
    python run_nightly_backfill.py --lookback-days 5
    python run_nightly_backfill.py --status
    python run_nightly_backfill.py --reset-blocked 123456
    python run_nightly_backfill.py --daemon
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from db.session import SessionLocal, init_db
from live.nightly_backfill import (
    DEFAULT_HOUR,
    DEFAULT_LOOKBACK_DAYS,
    format_status_report,
    reset_blocked,
    run_nightly,
    start_nightly_thread,
)
from live.sportmonks_client import SportmonksClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nightly ingest of finished matches into the historical database."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one pass now (default if neither --daemon nor --status).",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Stay running and fire at 1:00 AM IST every day (catch-up if already past 1 AM).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.getenv("NIGHTLY_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS))),
        help="IST calendar days through yesterday to scan (default: 3).",
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=int(os.getenv("NIGHTLY_HOUR", str(DEFAULT_HOUR))),
        help="IST hour to run in --daemon mode (default: 4).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print ingest_fixtures counts and blocked ids, then exit.",
    )
    parser.add_argument(
        "--reset-blocked",
        type=int,
        metavar="FIXTURE_ID",
        default=None,
        help="Unblock a Sportmonks fixture id so the next run will retry it.",
    )
    parser.add_argument(
        "--no-catchup",
        action="store_true",
        help="In --daemon mode, wait until the next 1 AM instead of running immediately if already past it.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log_path = ROOT / "data" / "nightly_backfill.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logging.getLogger().addHandler(file_handler)

    init_db()

    if args.status:
        print(format_status_report(SessionLocal))
        return

    if args.reset_blocked is not None:
        ok = reset_blocked(SessionLocal, args.reset_blocked)
        if ok:
            print(f"Unblocked fixture {args.reset_blocked}; it will be retried on the next run.")
        else:
            print(f"No ingest_fixtures row for {args.reset_blocked}.")
        return

    allow_ai = os.getenv("ALLOW_AI_COORDS", "0") == "1"

    if args.daemon:
        start_nightly_thread(
            SessionLocal,
            lookback_days=args.lookback_days,
            hour=args.hour,
            catchup=not args.no_catchup,
            allow_ai_coords=allow_ai,
        )
        logging.getLogger("kp.nightly").info("Daemon idle; waiting for 1:00 AM IST.")
        while True:
            time.sleep(3600)

    client = SportmonksClient()
    stats = run_nightly(
        SessionLocal,
        client,
        lookback_days=args.lookback_days,
        allow_ai_coords=allow_ai,
    )
    print(stats.line())
    if stats.blocked_ids:
        print(f"newly blocked: {stats.blocked_ids}")


if __name__ == "__main__":
    main()
