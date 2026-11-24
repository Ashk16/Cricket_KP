"""Set matches.first_ball_* from earliest corrected ball and rebuild charts if needed."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import func, select

load_dotenv()

from db.models import AstroChart, BallEvent, Match
from db.session import SessionLocal, init_db
from live.aligner import align_match
from live.astro_writer import duration_for_match, write_match_chart
from live.ball_timestamp_treatment import persist_treated_timestamps_for_match

logger = logging.getLogger("kp.fix_first_ball")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    fixed = 0
    charts = 0
    with SessionLocal() as session:
        match_ids = [
            mid
            for (mid,) in session.execute(
                select(Match.id)
                .join(BallEvent, BallEvent.match_id == Match.id)
                .where(Match.first_ball_utc.is_(None))
                .group_by(Match.id)
            ).all()
        ]
        logger.info("Matches with balls but no first_ball anchor: %d", len(match_ids))
        for mid in match_ids:
            match = session.get(Match, mid)
            if match is None:
                continue
            persist_treated_timestamps_for_match(session, mid)
            if match.first_ball_utc is None or match.lat is None:
                session.commit()
                continue
            has_chart = session.scalar(select(AstroChart).where(AstroChart.match_id == mid)) is not None
            last_corr = session.scalar(
                select(func.max(BallEvent.event_utc_corrected)).where(BallEvent.match_id == mid)
            )
            span_h = duration_for_match(match.first_ball_utc, last_corr, match.format)
            write_match_chart(
                session, match, anchor_utc=match.first_ball_utc, duration_hours=span_h, rebuild=True
            )
            align_match(session, mid, rebuild=True)
            fixed += 1
            if not has_chart:
                charts += 1
            session.commit()
    logger.info("Fixed first_ball + chart/align: %d (new charts: %d)", fixed, charts)


if __name__ == "__main__":
    main()
