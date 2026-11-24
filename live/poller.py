"""Live ball poller.

Polls a ball source on an interval, detects newly-arrived deliveries, stamps
each with a real wall-clock UTC ``event_utc`` (time_source = live_poll), writes
``ball_events`` (creating innings as needed), and aligns each ball to the
astrology timeline.

The ball source is abstracted so the same loop works for the live Sportmonks
client and for a replay source used in testing.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import BallEvent, Innings, Match
from live.aligner import align_ball
from live.match_setup import ensure_player
from live.sportmonks_client import SportmonksClient, normalize_ball
from timeutils import to_ist


class BallSource(Protocol):
    def fetch(self) -> List[Dict[str, Any]]:
        """Return the current full list of raw ball objects."""
        ...


class SportmonksBallSource:
    def __init__(self, client: SportmonksClient, fixture_id: int):
        self.client = client
        self.fixture_id = fixture_id

    def fetch(self) -> List[Dict[str, Any]]:
        return self.client.get_balls(self.fixture_id)


class ReplayBallSource:
    """Replays a finished fixture's balls in growing batches (for testing)."""

    def __init__(self, all_balls: List[Dict[str, Any]], batch_size: int = 3):
        self._all = all_balls
        self._batch = max(1, batch_size)
        self._revealed = 0

    def fetch(self) -> List[Dict[str, Any]]:
        self._revealed = min(len(self._all), self._revealed + self._batch)
        return self._all[: self._revealed]

    @property
    def exhausted(self) -> bool:
        return self._revealed >= len(self._all)


def _innings_number_from_scoreboard(scoreboard: Optional[str]) -> int:
    if not scoreboard:
        return 1
    m = re.search(r"(\d+)", str(scoreboard))
    return int(m.group(1)) if m else 1


class LivePoller:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        match: Match,
        ball_source: BallSource,
        poll_interval: float = 30.0,
        clock: Optional[Callable[[], datetime]] = None,
        on_first_ball: Optional[Callable[[Session, int, datetime], None]] = None,
    ):
        self.session_factory = session_factory
        self.match_id = match.id
        self.ball_source = ball_source
        self.poll_interval = poll_interval
        self.clock = clock or (lambda: datetime.utcnow())
        # Hook invoked exactly once, with the first ingested ball's event_utc,
        # before that ball is aligned. Used to generate the chart on first ball.
        self.on_first_ball = on_first_ball

    # ------------------------------------------------------------------ #
    def _existing_keys(self, session: Session) -> tuple[set, set]:
        rows = session.execute(
            select(BallEvent.sportmonks_ball_id, BallEvent.innings_id, BallEvent.over, BallEvent.ball)
            .where(BallEvent.match_id == self.match_id)
        ).all()
        by_sm_id = {r[0] for r in rows if r[0] is not None}
        by_composite = {(r[1], r[2], r[3]) for r in rows}
        return by_sm_id, by_composite

    def _ensure_innings(self, session: Session, innings_number: int,
                        batting_team_id: Optional[int], start_utc: datetime) -> Innings:
        innings = session.scalar(
            select(Innings).where(
                Innings.match_id == self.match_id,
                Innings.innings_number == innings_number,
            )
        )
        if innings is None:
            innings = Innings(
                match_id=self.match_id,
                innings_number=innings_number,
                batting_team_id=batting_team_id,
                start_utc=start_utc,
                start_ist=to_ist(start_utc),
                total_runs=0,
                wickets=0,
            )
            session.add(innings)
            session.flush()
        return innings

    def poll_once(self) -> int:
        """One polling pass. Returns the number of new balls ingested."""
        raw_balls = self.ball_source.fetch()
        new_count = 0

        with self.session_factory() as session:
            by_sm_id, by_composite = self._existing_keys(session)
            # If the match has no balls yet, the next ball we ingest is the very
            # first delivery -> trigger the chart-generation hook with its time.
            first_ball_pending = not (by_sm_id or by_composite)
            # team id for batting side resolution would need scoreboard mapping;
            # left None for now (filled by learning layer / future enrichment).
            for raw in raw_balls:
                nb = normalize_ball(raw)
                innings_number = _innings_number_from_scoreboard(nb.get("scoreboard"))

                event_utc = self.clock()
                innings = self._ensure_innings(session, innings_number, None, event_utc)

                composite_key = (innings.id, nb.get("over"), nb.get("ball"))
                sm_id = nb.get("sportmonks_ball_id")
                if sm_id is not None and sm_id in by_sm_id:
                    continue
                if sm_id is None and composite_key in by_composite:
                    continue

                ball_seq = (session.scalar(
                    select(func.coalesce(func.max(BallEvent.ball_seq), 0)).where(
                        BallEvent.innings_id == innings.id
                    )
                ) or 0) + 1

                prior_runs = session.scalar(
                    select(func.coalesce(func.sum(BallEvent.runs + func.coalesce(BallEvent.extras, 0)), 0))
                    .where(BallEvent.innings_id == innings.id)
                ) or 0
                prior_wkts = session.scalar(
                    select(func.count(BallEvent.id)).where(
                        BallEvent.innings_id == innings.id, BallEvent.is_wicket.is_(True)
                    )
                ) or 0

                # First-ever ball for this match: build the chart anchored here
                # before we align this (or any) ball.
                if first_ball_pending and self.on_first_ball is not None:
                    self.on_first_ball(session, self.match_id, event_utc)
                first_ball_pending = False

                runs = nb.get("runs") or 0
                extras = nb.get("extras") or 0
                batsman = ensure_player(session, nb.get("batsman_id"))
                bowler = ensure_player(session, nb.get("bowler_id"))

                ball = BallEvent(
                    match_id=self.match_id,
                    innings_id=innings.id,
                    over=nb.get("over"),
                    ball=nb.get("ball"),
                    ball_seq=ball_seq,
                    batsman_id=batsman.id if batsman else None,
                    bowler_id=bowler.id if bowler else None,
                    runs=runs,
                    extras=extras,
                    is_wicket=nb.get("is_wicket", False),
                    is_four=nb.get("is_four", False),
                    is_six=nb.get("is_six", False),
                    score_after=prior_runs + runs + extras,
                    wickets_after=prior_wkts + (1 if nb.get("is_wicket") else 0),
                    commentary=nb.get("commentary"),
                    event_utc=event_utc,
                    event_ist=to_ist(event_utc),
                    time_source="live_poll",
                    sportmonks_ball_id=sm_id,
                )
                session.add(ball)
                session.flush()

                # Update running innings totals.
                innings.total_runs = ball.score_after
                innings.wickets = ball.wickets_after
                innings.end_utc = event_utc
                innings.end_ist = to_ist(event_utc)

                align_ball(session, ball)

                # Track within this pass to avoid duplicates from the same batch.
                if sm_id is not None:
                    by_sm_id.add(sm_id)
                by_composite.add(composite_key)
                new_count += 1

            # SessionLocal()'s context manager closes but does not commit; the
            # poller owns its transaction boundary, so commit explicitly.
            session.commit()

        return new_count

    def run(self, max_polls: Optional[int] = None, stop_when_idle: bool = False) -> None:
        """Run the polling loop.

        Args:
            max_polls: Stop after this many passes (None = run indefinitely).
            stop_when_idle: Stop once a pass yields no new balls (useful for replay).
        """
        polls = 0
        while True:
            ingested = self.poll_once()
            polls += 1
            if max_polls is not None and polls >= max_polls:
                break
            if stop_when_idle and ingested == 0:
                break
            time.sleep(self.poll_interval)
