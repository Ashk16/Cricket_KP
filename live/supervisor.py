"""Always-on supervisor daemon.

Runs continuously (independent of any UI). It:
  1. Periodically syncs the Sportmonks schedule + livescores into the DB.
  2. Watches matches in their active window.
  3. On the FIRST detected ball of a match, resolves the venue coordinates and
     generates the KP chart anchored to that first-ball instant.
  4. Continuously ingests balls (real UTC timestamps) and aligns them to the
     astrology timeline.

All state lives in the database, so a UI can connect at any time and read the
match's chart + scores "as of now" without the supervisor being aware of it.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AstroChart, BallEvent, Match
from live.astro_writer import duration_for_match, write_match_chart
from live.aligner import align_match
from live.match_setup import apply_coordinates, ensure_match_from_fixture
from live.odds import capture_odds
from live.poller import LivePoller, SportmonksBallSource
from live.sportmonks_client import (
    SportmonksClient,
    normalize_odds,
    resolve_venue_payload,
)
from timeutils import to_ist

logger = logging.getLogger("kp.supervisor")

# Statuses that mean the match is over (best-effort; Sportmonks varies).
FINISHED_STATUSES = {"finished", "aborted", "cancelled", "postponed"}


class MatchWatcher:
    """Watches a single match: ensures chart on first ball, ingests balls."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        match: Match,
        fixture: Dict[str, Any],
        client: SportmonksClient,
        poll_interval: float = 30.0,
        clock: Optional[Callable[[], datetime]] = None,
        allow_ai_coords: bool = True,
        capture_odds: bool = False,
    ):
        self.session_factory = session_factory
        self.match_id = match.id
        self.fixture_id = fixture.get("id")
        self.venue_payload = resolve_venue_payload(client, fixture)
        self.allow_ai_coords = allow_ai_coords
        self.capture_odds = capture_odds
        self.client = client
        self.clock = clock or (lambda: datetime.utcnow())
        self._odds_unavailable = False
        self.poller = LivePoller(
            session_factory,
            match,
            SportmonksBallSource(client, self.fixture_id),
            poll_interval=poll_interval,
            clock=clock,
            on_first_ball=self._on_first_ball,
        )

    def _on_first_ball(self, session: Session, match_id: int, event_utc: datetime) -> None:
        """Resolve coords (if needed) and build the chart anchored at first ball."""
        match = session.get(Match, match_id)
        if match is None:
            return
        if session.scalar(select(AstroChart).where(AstroChart.match_id == match_id)) is not None:
            return

        if match.lat is None or match.lon is None:
            apply_coordinates(session, match, self.venue_payload, allow_ai=self.allow_ai_coords)

        match.first_ball_utc = event_utc
        match.first_ball_ist = to_ist(event_utc)

        if match.lat is None or match.lon is None:
            logger.warning(
                "Match %s: first ball at %s but venue coords unresolved; "
                "balls will be stored unaligned until coords are added.",
                match_id, event_utc,
            )
            return

        write_match_chart(session, match, anchor_utc=event_utc)
        logger.info("Match %s: chart generated, anchored at first ball %s", match_id, event_utc)

    def step(self) -> int:
        """One ingestion pass. Returns number of new balls."""
        new_balls = self.poller.poll_once()
        if self.capture_odds and not self._odds_unavailable:
            self._capture_odds_step()
        return new_balls

    def _capture_odds_step(self) -> None:
        try:
            raw, strategy = self.client.get_fixture_odds(self.fixture_id)
        except Exception as exc:  # noqa: BLE001 - odds must never break score capture
            logger.warning("Match %s: odds fetch failed: %s", self.match_id, exc)
            return
        if not raw:
            # Likely no cricket odds on this plan; stop trying for this match.
            self._odds_unavailable = True
            logger.info("Match %s: no odds available (plan/feed); disabling odds capture.",
                        self.match_id)
            return

        normalized = normalize_odds(raw)
        captured_utc = self.clock()
        with self.session_factory() as session:
            match = session.get(Match, self.match_id)
            is_inplay = bool(match and match.first_ball_utc is not None)
            n = capture_odds(session, self.match_id, normalized, captured_utc, is_inplay=is_inplay)
            session.commit()
        if n:
            logger.info("Match %s: stored %d odds change(s) via %s", self.match_id, n, strategy)


class Supervisor:
    def __init__(
        self,
        client: SportmonksClient,
        session_factory: Callable[[], Session],
        poll_interval: float = 30.0,
        schedule_refresh_seconds: float = 300.0,
        days_ahead: int = 2,
        clock: Optional[Callable[[], datetime]] = None,
        allow_ai_coords: bool = True,
        capture_odds: bool = False,
    ):
        self.client = client
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.schedule_refresh_seconds = schedule_refresh_seconds
        self.days_ahead = days_ahead
        self.clock = clock or (lambda: datetime.utcnow())
        self.allow_ai_coords = allow_ai_coords
        self.capture_odds = capture_odds
        self.watchers: Dict[int, MatchWatcher] = {}
        self._last_schedule_sync = 0.0

    # ------------------------------------------------------------------ #
    def _register_fixture(self, fixture: Dict[str, Any]) -> Optional[MatchWatcher]:
        fixture_id = fixture.get("id")
        if fixture_id is None:
            return None
        venue_payload = resolve_venue_payload(self.client, fixture)
        fixture["venue"] = venue_payload  # ensure ensure_venue() sees a real name
        with self.session_factory() as session:
            match = ensure_match_from_fixture(session, fixture)
            # Try to resolve coords early (library only here to avoid AI cost on
            # every scheduled fixture; AI fallback happens at first ball).
            apply_coordinates(session, match, venue_payload, allow_ai=False)
            session.commit()
            match_id = match.id
            status = match.status
            already = session.get(Match, match_id)  # keep loaded
            detached_match = already

        if status and status.lower() in FINISHED_STATUSES:
            return None
        if match_id in self.watchers:
            return self.watchers[match_id]

        watcher = MatchWatcher(
            self.session_factory,
            detached_match,
            fixture,
            self.client,
            poll_interval=self.poll_interval,
            clock=self.clock,
            allow_ai_coords=self.allow_ai_coords,
            capture_odds=self.capture_odds,
        )
        self.watchers[match_id] = watcher
        return watcher

    def sync_schedule(self) -> None:
        """Pull upcoming + live fixtures and register watchers."""
        fixtures: List[Dict[str, Any]] = []
        try:
            fixtures.extend(self.client.get_upcoming_fixtures(days_ahead=self.days_ahead))
        except Exception as exc:  # noqa: BLE001 - schedule endpoints vary; keep daemon alive
            logger.warning("Schedule fetch failed: %s", exc)
        try:
            fixtures.extend(self.client.get_livescores())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Livescores fetch failed: %s", exc)

        seen = set()
        for fixture in fixtures:
            fid = fixture.get("id")
            if fid in seen:
                continue
            seen.add(fid)
            self._register_fixture(fixture)

    def _retire_finished(self) -> None:
        if not self.watchers:
            return
        with self.session_factory() as session:
            for match_id in list(self.watchers):
                match = session.get(Match, match_id)
                if match and match.status and match.status.lower() in FINISHED_STATUSES:
                    self._extend_chart_to_last_ball(session, match)
                    session.commit()
                    logger.info("Retiring watcher for finished match %s", match_id)
                    del self.watchers[match_id]

    def _extend_chart_to_last_ball(self, session: Session, match: Match) -> None:
        """Rebuild the chart timeline to span first ball -> last ball + 15 min."""
        anchor = match.first_ball_utc or match.starting_at_utc
        if anchor is None or match.lat is None or match.lon is None:
            return
        last_ball = session.scalar(
            select(func.max(BallEvent.event_utc)).where(BallEvent.match_id == match.id)
        )
        if last_ball is None:
            return
        span_h = duration_for_match(anchor, last_ball, match.format)
        chart = session.scalar(select(AstroChart).where(AstroChart.match_id == match.id))
        if chart is not None and chart.duration_hours is not None:
            if span_h <= chart.duration_hours + 0.01:
                return
        write_match_chart(session, match, anchor_utc=anchor, duration_hours=span_h, rebuild=True)
        align_match(session, match.id, rebuild=True)
        logger.info(
            "Match %s: chart extended to %.2fh (last ball + 15m)", match.id, span_h
        )

    def step(self) -> int:
        now = time.monotonic()
        if now - self._last_schedule_sync >= self.schedule_refresh_seconds or not self.watchers:
            self.sync_schedule()
            self._last_schedule_sync = now

        total_new = 0
        for watcher in list(self.watchers.values()):
            try:
                total_new += watcher.step()
            except Exception as exc:  # noqa: BLE001 - one match failing must not kill the daemon
                logger.exception("Watcher for match %s errored: %s", watcher.match_id, exc)

        self._retire_finished()
        return total_new

    def run(self, max_cycles: Optional[int] = None) -> None:
        logger.info("Supervisor started (poll=%ss, schedule_refresh=%ss)",
                    self.poll_interval, self.schedule_refresh_seconds)
        cycles = 0
        while True:
            self.step()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            time.sleep(self.poll_interval)
