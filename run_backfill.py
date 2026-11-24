"""Historical backfill entrypoint.

Crawls finished matches year-by-year into the database (charts + balls + astro
alignment), reusing the same tables the live pipeline writes.

Examples:
    python run_backfill.py 2021
    python run_backfill.py 2021 2022 2023
    python run_backfill.py 2021 --leagues 1            # IPL only
    python run_backfill.py 2026 --end-date 2026-06-04  # exclude today/future
    python run_backfill.py 2021 --limit 5              # smoke test
    python run_backfill.py 2021 --rebuild              # re-ingest existing

Coordinate resolution uses the local library first; set ALLOW_AI_COORDS=1 (with
OPENAI_API_KEY) in .env to resolve unknown venues via the LLM fallback.
"""

from __future__ import annotations

import argparse
import logging
import os

from dotenv import load_dotenv

from db.session import SessionLocal, init_db
from live.backfill import backfill_year
from live.sportmonks_client import SportmonksClient


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Backfill historical cricket + KP data by year.")
    parser.add_argument("years", nargs="+", type=int, help="Calendar year(s) to crawl, e.g. 2021")
    parser.add_argument("--leagues", type=str, default=None,
                        help="Comma-separated Sportmonks league ids to restrict to (default: all).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N successfully ingested matches per year (smoke test).")
    parser.add_argument("--end-date", type=str, default=None,
                        help="Cap end date 'YYYY-MM-DD' (e.g. exclude today). Applies to each year.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Re-ingest matches even if already present.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    init_db()
    client = SportmonksClient()
    leagues = [int(x) for x in args.leagues.split(",")] if args.leagues else None
    allow_ai = os.getenv("ALLOW_AI_COORDS", "0") == "1"

    print("=" * 74)
    print(f"BACKFILL years={args.years} leagues={leagues or 'ALL'} "
          f"allow_ai_coords={allow_ai} limit={args.limit} rebuild={args.rebuild}")
    print("=" * 74)

    grand = {}
    for year in args.years:
        # For the year matching end_date, pass the cap through.
        end_date = args.end_date if (args.end_date and args.end_date.startswith(str(year))) else None
        stats = backfill_year(
            SessionLocal,
            client,
            year,
            leagues=leagues,
            allow_ai_coords=allow_ai,
            limit=args.limit,
            rebuild=args.rebuild,
            end_date=end_date,
        )
        grand[year] = stats

    print("\n" + "=" * 74)
    print("SUMMARY")
    print("=" * 74)
    for year, stats in grand.items():
        print(f"  {year}: {stats.line()}")
    print("\nNext: run `python db_summary.py` to inspect the database.")


if __name__ == "__main__":
    main()
