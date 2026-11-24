"""Regenerate charts + re-align already-loaded matches in place (no API calls).

Use this after changing how charts/timelines are generated (e.g. switching the
Ascendant to NL/SL only). For every match that already has coordinates and an
anchor time, it rebuilds the chart + timeline periods and re-aligns every ball.

    python regenerate_charts.py
    python regenerate_charts.py --limit 10
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import func, select

from db.models import BallEvent, Match
from db.session import SessionLocal, init_db
from live.aligner import align_match
from live.astro_writer import duration_for_match, write_match_chart

logger = logging.getLogger("kp.regenerate")


def regenerate(limit: int | None = None) -> None:
    init_db()
    with SessionLocal() as session:
        candidates = [
            m.id
            for m in session.scalars(
                select(Match).where(Match.lat.is_not(None), Match.lon.is_not(None))
            ).all()
            if (m.first_ball_utc or m.starting_at_utc) is not None
        ]

    logger.info("Regenerating %d matches with coords + anchor", len(candidates))
    done = 0
    total_aligned = 0
    errors = 0
    for mid in candidates:
        if limit is not None and done >= limit:
            break
        try:
            with SessionLocal() as session:
                match = session.get(Match, mid)
                anchor = match.first_ball_utc or match.starting_at_utc
                last_ball = session.scalar(
                    select(func.max(BallEvent.event_utc)).where(BallEvent.match_id == mid)
                )
                span_h = duration_for_match(anchor, last_ball, match.format)
                write_match_chart(
                    session, match, anchor_utc=anchor, duration_hours=span_h, rebuild=True
                )
                total_aligned += align_match(session, mid, rebuild=True)
                session.commit()
            done += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.exception("Match %s regeneration failed: %s", mid, exc)
        if done % 20 == 0:
            logger.info("  regenerated %d/%d matches, aligned %d balls",
                        done, len(candidates), total_aligned)

    logger.info("Done: regenerated %d matches, aligned %d balls, errors=%d",
                done, total_aligned, errors)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild charts + re-align loaded matches (no API).")
    parser.add_argument("--limit", type=int, default=None, help="Only regenerate the first N matches.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    regenerate(limit=args.limit)


if __name__ == "__main__":
    main()
