"""Autonomous supervisor flow test (no real Sportmonks key needed).

Validates the user's requirements:
  - Match scheduled; NO chart until the first ball.
  - On first ball, coords resolve from the library and the chart auto-generates
    anchored at the first-ball instant.
  - Balls store + align continuously while no UI is connected.
  - A reader can connect at any time and get state "as of now"; reconnecting
    later shows more, and an earlier "as_of" still shows the historical snapshot.

Run: python -m tests.test_autonomous
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import select

from db.models import AstroChart, BallEvent, Match, Venue

VENUE_SM_ID = 55
from db.session import SessionLocal, get_session, init_db
from live.match_state import get_match_state
from live.supervisor import Supervisor

FIXTURE_ID = 888888
BASE = datetime(2025, 7, 4, 17, 35, 0)  # scheduled-ish anchor for the test clock


def _fixture() -> Dict[str, Any]:
    # Venue intentionally has NO inline lat/lon -> forces library resolution by id/name.
    return {
        "id": FIXTURE_ID,
        "type": "T20I",
        "status": "NS",
        "localteam_id": 100,
        "visitorteam_id": 200,
        "localteam": {"data": {"id": 100, "name": "Eng", "code": "ENG"}},
        "visitorteam": {"data": {"id": 200, "name": "Ind", "code": "IND"}},
        "venue": {"data": {"id": 55, "name": "The Oval", "city": "London", "country": "England"}},
        "starting_at": "2025-07-04T17:35:00.000000Z",
    }


def _balls() -> List[Dict[str, Any]]:
    out = []
    for i in range(1, 13):
        sb = "S1" if i <= 8 else "S2"
        over = (i - 1) // 6 if sb == "S1" else (i - 9) // 6
        ball = ((i - 1) % 6) + 1 if sb == "S1" else ((i - 9) % 6) + 1
        out.append({
            "id": i,
            "scoreboard": sb,
            "team_id": 100 if sb == "S1" else 200,
            "ball": float(f"{over}.{ball}"),
            "batsman_id": 1000 + i,
            "bowler_id": 2000 + i,
            "score": {"runs": (i % 4), "four": i % 5 == 0, "six": i % 6 == 0, "out": i % 7 == 0},
        })
    return out


class FakeClient:
    """Implements only what the Supervisor uses, with controllable ball reveal."""

    def __init__(self):
        self._all_balls = _balls()
        self.reveal = 0

    def get_upcoming_fixtures(self, days_ahead: int = 2, includes: str = "") -> List[Dict[str, Any]]:
        return [_fixture()]

    def get_livescores(self, includes: str = "") -> List[Dict[str, Any]]:
        return []

    def get_balls(self, fixture_id: int) -> List[Dict[str, Any]]:
        return self._all_balls[: self.reveal]


def _clean(session):
    m = session.scalar(select(Match).where(Match.sportmonks_fixture_id == FIXTURE_ID))
    if m:
        session.delete(m)
        session.flush()
    # Also drop the shared venue so coord resolution is exercised fresh (other
    # tests may have created venue id 55 with a different coords_source).
    v = session.scalar(select(Venue).where(Venue.sportmonks_id == VENUE_SM_ID))
    if v:
        session.delete(v)
        session.flush()


def run() -> bool:
    init_db()
    with get_session() as s:
        _clean(s)

    client = FakeClient()
    n = {"i": 0}

    def clock():
        n["i"] += 1
        return BASE + timedelta(seconds=60 * n["i"])

    supervisor = Supervisor(
        client=client,
        session_factory=SessionLocal,
        poll_interval=0.0,
        schedule_refresh_seconds=10_000,
        clock=clock,
        allow_ai_coords=False,  # library only for the test
    )

    ok = True

    # --- Step 0: scheduled, no ball yet -> match registered, NO chart ---
    client.reveal = 0
    supervisor.step()
    with get_session() as s:
        match = s.scalar(select(Match).where(Match.sportmonks_fixture_id == FIXTURE_ID))
        assert match is not None, "match should be registered from schedule"
        match_id = match.id
        chart = s.scalar(select(AstroChart).where(AstroChart.match_id == match_id))
        balls = s.scalar(select(__import__("sqlalchemy").func.count(BallEvent.id)).where(BallEvent.match_id == match_id))
        venue = s.get(Venue, match.venue_id) if match.venue_id else None
        print(f"[step0] registered match {match_id}; chart={chart is not None}; balls={balls}; "
              f"coords=({match.lat},{match.lon}) source={venue.coords_source if venue else None}")
        ok = ok and chart is None and balls == 0
        ok = ok and match.lat is not None and venue and venue.coords_source == "library"

    # --- Step 1: first ball -> chart auto-generated, anchored at first ball ---
    client.reveal = 1
    supervisor.step()
    with get_session() as s:
        match = s.get(Match, match_id)
        chart = s.scalar(select(AstroChart).where(AstroChart.match_id == match_id))
        print(f"[step1] first ball; chart={chart is not None}; "
              f"first_ball_utc={match.first_ball_utc}; chart_dt={chart.datetime_utc if chart else None}")
        ok = ok and chart is not None and match.first_ball_utc is not None
        ok = ok and chart.datetime_utc == match.first_ball_utc  # anchored at first ball

    # --- Steps 2..6: more balls arrive while nobody watches ("till 7:20") ---
    for r in range(2, 7):
        client.reveal = r
        supervisor.step()
    with get_session() as s:
        state_at_6 = get_match_state(s, match_id)
        as_of_6 = state_at_6["recent_balls"][-1]["event_utc"]
        print(f"[till-7:20] total_balls={state_at_6['total_balls']} as_of={as_of_6} "
              f"moon_now={state_at_6['current_astro']['moon']}")
        ok = ok and state_at_6["total_balls"] == 6

    # --- Steps 7..12: rest of the match ("reconnect at 8 PM") ---
    for r in range(7, 13):
        client.reveal = r
        supervisor.step()
    with get_session() as s:
        now_state = get_match_state(s, match_id)
        snapshot_earlier = get_match_state(s, match_id, as_of=datetime.fromisoformat(as_of_6))
        print(f"[8pm-now] total_balls={now_state['total_balls']} innings={now_state['innings']}")
        print(f"[8pm-as_of_7:20] total_balls={snapshot_earlier['total_balls']} (historical snapshot)")
        ok = ok and now_state["total_balls"] == 12
        ok = ok and snapshot_earlier["total_balls"] == 6  # earlier snapshot unchanged

        # every ball aligned
        unaligned = [
            b for b in now_state["recent_balls"]
            if b["moon"] is None or b["moon"]["sssl"] is None
        ]
        ok = ok and not unaligned

    print("\nRESULT:", "PASS - autonomous capture + anytime read works" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
