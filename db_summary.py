"""Database summary + sample rows.

Prints row counts for every table and a 10-row sample of the aligned data
(ball + match + active KP lords) so you can eyeball how match data and astrology
data line up. Read-only.

Usage:
    python db_summary.py
    python db_summary.py --rows 20
"""

from __future__ import annotations

import argparse

from sqlalchemy import func, select

from db.models import (
    AstroChart,
    AstroPlanet,
    AstroTimelinePeriod,
    BallAstroState,
    BallEvent,
    Innings,
    Match,
    OddsSnapshot,
    Player,
    Team,
    Venue,
)
from db.session import SessionLocal

COUNT_TABLES = [
    ("matches", Match),
    ("innings", Innings),
    ("ball_events", BallEvent),
    ("ball_astro_state", BallAstroState),
    ("astro_charts", AstroChart),
    ("astro_planets", AstroPlanet),
    ("astro_timeline_periods", AstroTimelinePeriod),
    ("odds_snapshots", OddsSnapshot),
    ("teams", Team),
    ("players", Player),
    ("venues", Venue),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the KP cricket database.")
    parser.add_argument("--rows", type=int, default=10, help="Number of sample ball rows to show.")
    args = parser.parse_args()

    with SessionLocal() as session:
        print("=" * 92)
        print("TABLE ROW COUNTS")
        print("=" * 92)
        for label, model in COUNT_TABLES:
            n = session.scalar(select(func.count()).select_from(model)) or 0
            print(f"  {label:24s} {n:>10,}")

        # Coverage breakdown by league + season.
        print("\n" + "=" * 92)
        print("MATCHES BY LEAGUE / SEASON")
        print("=" * 92)
        rows = session.execute(
            select(Match.league, Match.season, func.count(Match.id))
            .group_by(Match.league, Match.season)
            .order_by(func.count(Match.id).desc())
        ).all()
        if not rows:
            print("  (no matches yet)")
        for league, season, n in rows[:25]:
            print(f"  {str(league or '-'):42s} {str(season or '-'):8s} {n:>6}")

        # Coords + chart coverage.
        total_m = session.scalar(select(func.count(Match.id))) or 0
        with_coords = session.scalar(
            select(func.count(Match.id)).where(Match.lat.is_not(None))
        ) or 0
        with_chart = session.scalar(select(func.count(AstroChart.id))) or 0
        aligned_balls = session.scalar(
            select(func.count(BallAstroState.id)).where(BallAstroState.asc_sl.is_not(None))
        ) or 0
        total_balls = session.scalar(select(func.count(BallEvent.id))) or 0
        print("\n" + "=" * 92)
        print("COVERAGE")
        print("=" * 92)
        print(f"  matches with coords : {with_coords}/{total_m}")
        print(f"  matches with chart  : {with_chart}/{total_m}")
        print(f"  balls aligned       : {aligned_balls}/{total_balls}")

        # Planet significator coverage.
        planets_total = session.scalar(select(func.count(AstroPlanet.id))) or 0
        planets_with_sigs = session.scalar(
            select(func.count(AstroPlanet.id)).where(AstroPlanet.significators.is_not(None))
        ) or 0
        print(f"  planets w/ sigs     : {planets_with_sigs}/{planets_total}")

        sample_chart = session.scalar(select(AstroChart).limit(1))
        if sample_chart:
            sample_planet = session.scalar(
                select(AstroPlanet)
                .where(AstroPlanet.chart_id == sample_chart.id, AstroPlanet.planet == "Moon")
            )
            if sample_planet and sample_planet.significators_display:
                print(f"  sample (Moon)       : {sample_planet.significators_display}")

        # Sample joined rows: ball + match + active KP lords.
        print("\n" + "=" * 92)
        print(f"SAMPLE: {args.rows} ALIGNED BALLS (match data + astrology data, joined)")
        print("=" * 92)
        local = Team.__table__.alias("local")
        visitor = Team.__table__.alias("visitor")
        stmt = (
            select(
                Match.id,
                Match.league,
                Match.season,
                local.c.name,
                visitor.c.name,
                BallEvent.event_ist,
                Innings.innings_number,
                BallEvent.over,
                BallEvent.ball,
                BallEvent.runs,
                BallEvent.is_wicket,
                BallAstroState.asc_nl,
                BallAstroState.asc_sl,
                BallAstroState.moon_ssl,
                BallAstroState.moon_sssl,
            )
            .join(BallEvent, BallEvent.match_id == Match.id)
            .join(Innings, Innings.id == BallEvent.innings_id)
            .join(BallAstroState, BallAstroState.ball_id == BallEvent.id)
            .join(local, local.c.id == Match.localteam_id, isouter=True)
            .join(visitor, visitor.c.id == Match.visitorteam_id, isouter=True)
            .order_by(Match.id, Innings.innings_number, BallEvent.ball_seq)
            .limit(args.rows)
        )
        results = session.execute(stmt).all()
        if not results:
            print("  (no aligned balls yet - run the backfill first)")
            return

        header = (
            f"{'match':>6} {'league':16} {'teams':26} {'event_ist (IST)':19} "
            f"{'inn':>3} {'o.b':>5} {'r':>2} {'W':1} "
            f"{'asc nl/sl':12} {'moon ssl/sssl':13}"
        )
        print(header)
        print("-" * len(header))
        for r in results:
            (mid, league, season, lt, vt, ev, inn, over, ball, runs, wkt,
             a_nl, a_sl, m_ssl, m_sssl) = r
            teams = f"{(lt or '?')[:11]} v {(vt or '?')[:10]}"
            ob = f"{over}.{ball}" if over is not None else "-"
            asc = f"{a_nl or '-'}/{a_sl or '-'}"
            moon = f"{m_ssl or '-'}/{m_sssl or '-'}"
            print(
                f"{mid:>6} {str(league or '-')[:16]:16} {teams:26} "
                f"{str(ev):19} {inn:>3} {ob:>5} {runs or 0:>2} {'W' if wkt else '.':1} "
                f"{asc:12} {moon:13}"
            )


if __name__ == "__main__":
    main()
