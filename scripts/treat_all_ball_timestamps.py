"""Batch-apply burst treatment + 35s delay correction to all matches.

1. Adds treated/corrected columns if missing (via migration).
2. Reverse-walk burst treatment -> ``event_*_treated``.
3. Subtract 35s flat -> ``event_*_corrected``.
4. Updates ``matches.first_ball_*`` to corrected first delivery.
5. Re-aligns ``ball_astro_state`` using corrected timestamps.

Raw ``event_utc`` / ``event_ist`` are never modified.

    python scripts/treat_all_ball_timestamps.py
    python scripts/treat_all_ball_timestamps.py --limit 10
    python scripts/treat_all_ball_timestamps.py --no-realign
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from db.models import AstroChart, BallEvent, Match
from db.session import SessionLocal, init_db
from live.aligner import align_match
from live.astro_writer import duration_for_match, write_match_chart
from live.ball_timestamp_treatment import persist_treated_timestamps_for_match

logger = logging.getLogger("kp.treat_all")


def _rechart_match(session, match_id: int) -> bool:
    """Rebuild chart/timeline anchored at corrected first_ball_utc."""
    match = session.get(Match, match_id)
    if match is None or match.lat is None or match.lon is None or match.first_ball_utc is None:
        return False
    if session.scalar(select(AstroChart).where(AstroChart.match_id == match_id)) is None:
        return False
    last_ball = session.scalar(
        select(func.max(BallEvent.event_utc_corrected)).where(BallEvent.match_id == match_id)
    )
    span_h = duration_for_match(match.first_ball_utc, last_ball, match.format)
    write_match_chart(
        session, match, anchor_utc=match.first_ball_utc, duration_hours=span_h, rebuild=True
    )
    return True


def treat_all(*, limit: int | None = None, realign: bool = True, rechart: bool = True) -> None:
    init_db()

    # Ensure columns exist.
    from migrate_add_treated_timestamps import main as migrate_cols

    migrate_cols()

    with SessionLocal() as session:
        match_ids = [
            mid
            for (mid,) in session.execute(
                select(BallEvent.match_id).distinct().order_by(BallEvent.match_id)
            ).all()
        ]

    logger.info("Treating timestamps for %d matches", len(match_ids))
    done = 0
    total_balls = 0
    total_aligned = 0
    total_recharted = 0
    errors = 0

    for mid in match_ids:
        if limit is not None and done >= limit:
            break
        try:
            with SessionLocal() as session:
                n = persist_treated_timestamps_for_match(session, mid)
                if rechart and _rechart_match(session, mid):
                    total_recharted += 1
                aligned = align_match(session, mid, rebuild=True) if realign else 0
                session.commit()
            total_balls += n
            total_aligned += aligned
            done += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.exception("Match %s failed: %s", mid, exc)

        if done % 50 == 0:
            logger.info("  %d/%d matches, %d balls treated, %d aligned", done, len(match_ids), total_balls, total_aligned)

    logger.info(
        "Done: matches=%d balls_treated=%d recharted=%d aligned=%d errors=%d",
        done, total_balls, total_recharted, total_aligned, errors,
    )

    with SessionLocal() as session:
        with_treated = session.scalar(
            select(func.count(BallEvent.id)).where(BallEvent.event_utc_treated.is_not(None))
        ) or 0
        with_corrected = session.scalar(
            select(func.count(BallEvent.id)).where(BallEvent.event_utc_corrected.is_not(None))
        ) or 0
        in_burst = session.scalar(
            select(func.count(BallEvent.id)).where(BallEvent.timestamp_in_burst.is_(True))
        ) or 0
        total = session.scalar(select(func.count(BallEvent.id))) or 0
        logger.info(
            "Coverage: treated=%d/%d corrected=%d/%d in_burst=%d",
            with_treated, total, with_corrected, total, in_burst,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch treat ball timestamps for all matches.")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N matches.")
    parser.add_argument("--no-realign", action="store_true", help="Skip ball_astro_state rebuild.")
    parser.add_argument("--no-rechart", action="store_true", help="Skip chart rebuild at corrected anchor.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    treat_all(limit=args.limit, realign=not args.no_realign, rechart=not args.no_rechart)


if __name__ == "__main__":
    main()
