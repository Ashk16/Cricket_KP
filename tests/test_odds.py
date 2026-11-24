"""Odds normalization + capture test (no real key needed).

Verifies:
  - normalize_odds flattens a nested Sportmonks-like odds payload,
  - capture_odds stores snapshots aligned to the KP timeline,
  - dedup: unchanged odds aren't re-stored; changed odds are.

Run: python -m tests.test_odds
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from db.models import Match, OddsSnapshot
from db.session import get_session, init_db
from live.astro_writer import write_match_chart
from live.match_setup import ensure_match_from_fixture
from live.odds import capture_odds
from live.sportmonks_client import normalize_odds

FIXTURE_ID = 777777
ANCHOR = datetime(2025, 7, 4, 17, 36, 0)
LAT, LON = 51.4821031, -0.1117327


def _fixture():
    return {
        "id": FIXTURE_ID, "type": "T20I", "status": "1st innings",
        "localteam_id": 100, "visitorteam_id": 200,
        "localteam": {"data": {"id": 100, "name": "Eng"}},
        "visitorteam": {"data": {"id": 200, "name": "Ind"}},
        "venue": {"data": {"id": 55, "name": "The Oval", "city": "London"}},
        "starting_at": "2025-07-04T17:35:00.000000Z",
    }


def _odds_payload(value_eng="1.85", value_ind="2.00", updated="2025-07-04 17:40:00"):
    return [{
        "bookmaker": {"data": {"id": 2, "name": "bet365"}},
        "market": {"data": {"id": 1, "name": "Match Winner"}},
        "odds": {"data": [
            {"label": "Eng", "value": value_eng, "updated_at": updated},
            {"label": "Ind", "value": value_ind, "updated_at": updated},
        ]},
    }]


def run() -> bool:
    init_db()
    ok = True

    # normalize
    norm = normalize_odds(_odds_payload())
    print(f"normalized {len(norm)} records: "
          f"{[(r['market'], r['bookmaker'], r['selection'], r['odd_value']) for r in norm]}")
    ok = ok and len(norm) == 2
    ok = ok and all(r["market"] == "Match Winner" and r["bookmaker"] == "bet365" for r in norm)
    ok = ok and {r["selection"] for r in norm} == {"Eng", "Ind"}

    with get_session() as s:
        existing = s.scalar(select(Match).where(Match.sportmonks_fixture_id == FIXTURE_ID))
        if existing:
            s.delete(existing); s.flush()
        match = ensure_match_from_fixture(s, _fixture(), lat=LAT, lon=LON, fmt="T20I")
        match.first_ball_utc = ANCHOR
        write_match_chart(s, match, duration_hours=1.0, anchor_utc=ANCHOR)
        match_id = match.id

    captured = datetime(2025, 7, 4, 17, 42, 0)

    # First capture -> 2 stored, aligned to KP
    with get_session() as s:
        n1 = capture_odds(s, match_id, normalize_odds(_odds_payload()), captured, is_inplay=True)
        s.commit()
        sample = s.scalar(select(OddsSnapshot).where(OddsSnapshot.match_id == match_id))
        aligned = sample is not None and sample.moon_sssl is not None
        print(f"capture#1 stored={n1} aligned_moon_sssl={sample.moon_sssl if sample else None}")
        ok = ok and n1 == 2 and aligned

    # Same odds again -> dedup, 0 stored
    with get_session() as s:
        n2 = capture_odds(s, match_id, normalize_odds(_odds_payload()), captured, is_inplay=True)
        s.commit()
        print(f"capture#2 (unchanged) stored={n2}")
        ok = ok and n2 == 0

    # Changed value + timestamp -> stored
    with get_session() as s:
        changed = _odds_payload(value_eng="1.70", value_ind="2.20", updated="2025-07-04 17:45:00")
        n3 = capture_odds(s, match_id, normalize_odds(changed),
                          datetime(2025, 7, 4, 17, 46, 0), is_inplay=True)
        s.commit()
        total = s.scalar(select(func.count(OddsSnapshot.id)).where(OddsSnapshot.match_id == match_id))
        print(f"capture#3 (changed) stored={n3} total_snapshots={total}")
        ok = ok and n3 == 2 and total == 4

    print("\nRESULT:", "PASS - odds normalize + capture + align + dedup" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
