"""Resolve Sportmonks player names for placeholder rows (player_{id})."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from db.session import SessionLocal, init_db
from live.player_registry import enrich_placeholder_players
from live.sportmonks_client import SportmonksClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich player names from Sportmonks API.")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N placeholders.")
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    init_db()
    client = SportmonksClient()
    with SessionLocal() as session:
        stats = enrich_placeholder_players(
            session, client, limit=args.limit, progress_every=args.progress_every
        )
    print(f"Done: seen={stats['seen']} resolved={stats['resolved']} failed={stats['failed']}")


if __name__ == "__main__":
    main()
