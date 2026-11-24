"""End-to-end replay test for the live pipeline (no Sportmonks key needed).

Flow exercised:
  1. ensure_match_from_fixture  (teams + venue + match)
  2. write_match_chart          (chart + Asc/Moon timelines)
  3. LivePoller + ReplayBallSource with a clock anchored to match start
  4. verify every ball resolved to active Ascendant + Moon lords

Run: python -m tests.test_replay
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count

from sqlalchemy import select

from db.models import BallAstroState, BallEvent, Innings, Match
from db.session import SessionLocal, get_session, init_db
from live.astro_writer import write_match_chart
from live.match_setup import ensure_match_from_fixture
from live.poller import LivePoller, ReplayBallSource

TEST_FIXTURE_ID = 999999
VENUE_LAT = 51.4821031   # The Oval, London
VENUE_LON = -0.1117327
START_UTC = datetime(2025, 7, 4, 17, 35, tzinfo=timezone.utc)


def _synthetic_fixture():
    return {
        "id": TEST_FIXTURE_ID,
        "type": "T20I",
        "localteam_id": 100,
        "visitorteam_id": 200,
        "localteam": {"data": {"id": 100, "name": "Eng", "code": "ENG"}},
        "visitorteam": {"data": {"id": 200, "name": "Ind", "code": "IND"}},
        "venue": {"data": {"id": 55, "name": "The Oval", "city": "London",
                           "country": "England", "lat": VENUE_LAT, "lon": VENUE_LON}},
        "starting_at": "2025-07-04T17:35:00.000000Z",
        "status": "Finished",
        "note": "Replay test fixture",
    }


def _synthetic_balls():
    specs = [
        (1, "S1", 0.1, 1, False, False, False),
        (2, "S1", 0.2, 0, False, False, True),   # wicket
        (3, "S1", 0.3, 4, True, False, False),   # four
        (4, "S1", 0.4, 6, False, True, False),   # six
        (5, "S1", 0.5, 1, False, False, False),
        (6, "S1", 0.6, 2, False, False, False),
        (7, "S1", 1.1, 0, False, False, False),
        (8, "S1", 1.2, 1, False, False, False),
        (9, "S2", 0.1, 4, True, False, False),   # 2nd innings
        (10, "S2", 0.2, 0, False, False, True),  # wicket
        (11, "S2", 0.3, 1, False, False, False),
        (12, "S2", 0.4, 6, False, True, False),
    ]
    balls = []
    for sm_id, sb, ball_label, runs, four, six, out in specs:
        balls.append({
            "id": sm_id,
            "scoreboard": sb,
            "team_id": 100 if sb == "S1" else 200,
            "ball": ball_label,
            "batsman_id": 1000 + sm_id,
            "bowler_id": 2000 + sm_id,
            "score": {"runs": runs, "four": four, "six": six, "out": out},
            "commentary": f"Ball {ball_label} ({sb})",
        })
    return balls


def _cleanup(session):
    existing = session.scalar(select(Match).where(Match.sportmonks_fixture_id == TEST_FIXTURE_ID))
    if existing is not None:
        session.delete(existing)
        session.flush()


def run_replay() -> bool:
    init_db()

    with get_session() as s:
        _cleanup(s)
        match = ensure_match_from_fixture(s, _synthetic_fixture(), fmt="T20I")
        write_match_chart(s, match, duration_hours=1.0)
        match_id = match.id

    with get_session() as s:
        match = s.get(Match, match_id)

    # Clock anchored to match start, advancing 60s per ball.
    start_naive = START_UTC.replace(tzinfo=None)
    ticks = count(start=1)
    clock = lambda: start_naive + timedelta(seconds=60 * next(ticks))

    source = ReplayBallSource(_synthetic_balls(), batch_size=3)
    poller = LivePoller(SessionLocal, match, source, poll_interval=0.0, clock=clock)
    poller.run(max_polls=10, stop_when_idle=True)

    # Verify
    ok = True
    with get_session() as s:
        rows = s.execute(
            select(BallEvent, BallAstroState, Innings.innings_number)
            .join(BallAstroState, BallAstroState.ball_id == BallEvent.id, isouter=True)
            .join(Innings, Innings.id == BallEvent.innings_id, isouter=True)
            .where(BallEvent.match_id == match_id)
            .order_by(BallEvent.event_utc)
        ).all()

        print(f"\nIngested {len(rows)} balls for match {match_id}\n")
        header = f"{'utc':19} {'inn':3} {'o.b':4} {'runs':4} {'W':1} {'asc_nl/sl':14} {'moon_ssl/sssl':14}"
        print(header)
        print("-" * len(header))
        for ball, state, innings_number in rows:
            aligned = state is not None and state.moon_sssl is not None and state.asc_sl is not None
            ok = ok and aligned
            asc = f"{state.asc_nl}/{state.asc_sl}" if state else "-"
            moon = f"{state.moon_ssl}/{state.moon_sssl}" if state else "-"
            wk = "W" if ball.is_wicket else "."
            print(f"{ball.event_utc!s:19} {innings_number or 0:<3} {str(ball.over)+'.'+str(ball.ball):4} "
                  f"{ball.runs:4} {wk:1} {asc:14} {moon:14}")

        if len(rows) != 12:
            print(f"\nFAIL: expected 12 balls, got {len(rows)}")
            ok = False

    print("\nRESULT:", "PASS - every ball aligned to Asc + Moon lords" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_replay() else 1)
