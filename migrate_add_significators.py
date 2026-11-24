"""Migration: add planet significator columns and backfill existing charts.

Adds ``significators`` (JSON) and ``significators_display`` to astro_planets,
then recomputes significators from each chart's stored datetime + coordinates.

Idempotent: skips columns that already exist; safe to re-run.

    python migrate_add_significators.py
"""

from __future__ import annotations

from sqlalchemy import select, text

from astro.kp_engine import KPEngine
from astro.significators import significators_for_engine
from db.models import AstroChart, AstroPlanet
from db.session import SessionLocal, engine, init_db

NEW_COLUMNS = [
    ("significators", "JSON"),
    ("significators_display", "VARCHAR(500)"),
]


def _existing_columns(conn, table: str) -> set:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def _add_columns() -> None:
    with engine.begin() as conn:
        cols = _existing_columns(conn, "astro_planets")
        for col_name, col_type in NEW_COLUMNS:
            if col_name not in cols:
                conn.execute(text(f"ALTER TABLE astro_planets ADD COLUMN {col_name} {col_type}"))
                print(f"  [add ] astro_planets.{col_name}")
            else:
                print(f"  [have] astro_planets.{col_name}")


def _backfill() -> None:
    init_db()
    with SessionLocal() as session:
        charts = session.scalars(select(AstroChart)).all()
        print(f"\nBackfilling significators for {len(charts)} chart(s)...")
        updated = 0
        for chart in charts:
            engine_dt = chart.datetime_utc
            kp = KPEngine(
                dt=engine_dt,
                lat=chart.lat,
                lon=chart.lon,
                ayanamsa=chart.ayanamsa or "KRISHNAMURTI",
            )
            sig_by_planet = significators_for_engine(kp)
            planets = session.scalars(
                select(AstroPlanet).where(AstroPlanet.chart_id == chart.id)
            ).all()
            for planet_row in planets:
                sig = sig_by_planet.get(planet_row.planet, {})
                planet_row.significators = sig.get("significators")
                planet_row.significators_display = sig.get("significators_display")
                updated += 1
            session.commit()
        print(f"  updated {updated} planet row(s)")


def main() -> None:
    init_db()
    print("Adding significator columns...")
    _add_columns()
    _backfill()
    print("\nSignificators migration complete.")


if __name__ == "__main__":
    main()
