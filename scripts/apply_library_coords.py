"""Apply ground_coords.json to existing venues/matches and optionally re-chart.

Updates venue.lat/lon and match.lat/lon from the library for every row that
was missing coordinates. With --rechart, rebuilds charts + re-aligns balls for
newly-resolvable matches (no API calls).

    python scripts/apply_library_coords.py
    python scripts/apply_library_coords.py --rechart
    python scripts/apply_library_coords.py --rechart --limit 10
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from sqlalchemy import func

from db.models import AstroChart, BallEvent, Match, Venue
from db.session import SessionLocal, init_db
from live.aligner import align_match
from live.astro_writer import duration_for_match, write_match_chart
from live.match_setup import apply_coordinates
from live.venue_coords import resolve_coordinates

logger = logging.getLogger("kp.apply_coords")


def apply(rechart: bool = False, limit: int | None = None) -> None:
    init_db()
    venues_updated = 0
    matches_updated = 0
    recharted = 0
    aligned_balls = 0

    with SessionLocal() as session:
        venues = session.scalars(select(Venue)).all()
        for venue in venues:
            if venue.sportmonks_id is None and not venue.name:
                continue
            payload = {
                "id": venue.sportmonks_id,
                "name": venue.name,
                "city": venue.city,
                "country": venue.country,
            }
            result = resolve_coordinates(payload, allow_ai=False)
            if not result.resolved:
                continue
            if venue.lat is None or venue.lon is None:
                venue.lat = result.lat
                venue.lon = result.lon
                venue.coords_source = result.source
                venues_updated += 1
        session.commit()

    candidates = []
    with SessionLocal() as session:
        for match in session.scalars(select(Match)).all():
            venue = session.get(Venue, match.venue_id) if match.venue_id else None
            payload = {}
            if venue:
                payload = {"id": venue.sportmonks_id, "name": venue.name, "city": venue.city}
            if not payload:
                continue
            result = resolve_coordinates(payload, allow_ai=False)
            if not result.resolved:
                continue
            changed = match.lat is None or match.lon is None
            match.lat = result.lat
            match.lon = result.lon
            if venue and (venue.lat is None or venue.lon is None):
                venue.lat = result.lat
                venue.lon = result.lon
                venue.coords_source = result.source
            if changed:
                matches_updated += 1
            has_chart = session.scalar(
                select(AstroChart).where(AstroChart.match_id == match.id)
            ) is not None
            anchor = match.first_ball_utc or match.starting_at_utc
            if rechart and anchor and match.lat is not None and (not has_chart or changed):
                candidates.append(match.id)
        session.commit()

    if rechart and candidates:
        for i, mid in enumerate(candidates):
            if limit is not None and i >= limit:
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
                    aligned_balls += align_match(session, mid, rebuild=True)
                    session.commit()
                recharted += 1
                if recharted % 25 == 0:
                    logger.info("Recharted %d/%d matches, %d balls aligned so far",
                                recharted, len(candidates), aligned_balls)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Rechart match %s failed: %s", mid, exc)

    print("=" * 60)
    print(f"Venues updated (coords added) : {venues_updated}")
    print(f"Matches updated (coords added): {matches_updated}")
    if rechart:
        print(f"Matches recharted + aligned   : {recharted}")
        print(f"Balls aligned this run        : {aligned_balls}")
    with SessionLocal() as session:
        m_total = session.scalar(select(func.count(Match.id))) or 0
        m_coords = session.scalar(select(func.count(Match.id)).where(Match.lat.is_not(None))) or 0
        m_chart = session.scalar(select(func.count(AstroChart.id))) or 0
    print(f"Coverage now: {m_coords}/{m_total} matches with coords, {m_chart} charts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rechart", action="store_true", help="Rebuild charts for newly-resolvable matches")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    apply(rechart=args.rechart, limit=args.limit)


if __name__ == "__main__":
    main()
