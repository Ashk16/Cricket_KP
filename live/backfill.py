"""Historical backfill crawler.

Loads finished matches from Sportmonks into the same tables the live pipeline
uses, but stamps each ball with its own ``updated_at`` (the feed-entry time)
instead of wall-clock time. The chart is anchored at the first ball's
``updated_at`` and the Ascendant/Moon timelines are aligned to every ball.

Design:
- Crawls **by year** (one calendar year per invocation), all leagues by default.
- **Idempotent**: re-running skips matches already fully ingested (chart + balls)
  and de-dupes individual balls by ``sportmonks_ball_id``.
- **Resumable**: because it skips completed matches, a crashed/stopped run can be
  restarted and will continue where it left off.
- **Graceful**: a venue without resolvable coordinates still has its balls stored
  (unaligned, flagged) so nothing is lost; the chart can be built later.

Ball timestamps come from ``updated_at`` (verified to track real delivery time to
within seconds for live-scored matches), so ``time_source`` is recorded as
``sportmonks_ts`` to distinguish it from live wall-clock capture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db.models import (
    AstroChart,
    AstroTimelinePeriod,
    BallAstroState,
    BallEvent,
    Innings,
    Match,
    Team,
)
from live.aligner import align_match
from live.ball_timestamp_treatment import persist_treated_timestamps_for_match
from live.astro_writer import duration_for_match, write_match_chart
from live.match_setup import (
    apply_coordinates,
    ensure_match_from_fixture,
    ensure_player,
    parse_utc,
)
from live.player_registry import sync_players_from_fixture
from live.poller import _innings_number_from_scoreboard
from live.sportmonks_client import (
    SportmonksClient,
    _unwrap_list,
    normalize_ball,
    resolve_venue_payload,
)
from timeutils import to_ist

logger = logging.getLogger("kp.backfill")

TIME_SOURCE = "sportmonks_ts"
FINISHED_STATUSES = {"finished", "aborted"}
SKIP_FORMATS = {"test"}
DETAIL_INCLUDES = "localteam,visitorteam,balls,batting,bowling,scoreboards"


@dataclass
class BackfillStats:
    fixtures_seen: int = 0
    matches_ingested: int = 0
    skipped_existing: int = 0
    skipped_test: int = 0
    no_ball_data: int = 0
    coords_unresolved: int = 0
    charts_built: int = 0
    balls_written: int = 0
    balls_aligned: int = 0
    errors: int = 0

    def line(self) -> str:
        return (
            f"ingested={self.matches_ingested} skipped={self.skipped_existing} "
            f"skipped_test={self.skipped_test} "
            f"no_balls={self.no_ball_data} coords_unresolved={self.coords_unresolved} "
            f"charts={self.charts_built} balls={self.balls_written} "
            f"aligned={self.balls_aligned} errors={self.errors}"
        )


# --------------------------------------------------------------------------- #
# League name map (id -> readable name), fetched once.
# --------------------------------------------------------------------------- #
def league_name_map(client: SportmonksClient) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for lg in client._get_pages("leagues"):
        if lg.get("id") is not None:
            out[lg["id"]] = str(lg.get("name") or lg.get("code") or lg["id"])
    return out


# --------------------------------------------------------------------------- #
# Per-fixture backfill
# --------------------------------------------------------------------------- #
def backfill_fixture(
    session_factory: Callable[[], Session],
    client: SportmonksClient,
    fixture: Dict[str, Any],
    *,
    allow_ai_coords: bool = True,
    rebuild: bool = False,
    league_name: Optional[str] = None,
    stats: Optional[BackfillStats] = None,
) -> BackfillStats:
    """Ingest a single finished fixture (chart + balls + alignment)."""
    stats = stats or BackfillStats()
    stats.fixtures_seen += 1
    fid = fixture.get("id")

    detail = client.get_fixture(fid, includes=DETAIL_INCLUDES)
    balls_raw = _unwrap_list(detail.get("balls"))
    if not balls_raw:
        stats.no_ball_data += 1
        return stats

    venue_payload = resolve_venue_payload(client, detail if detail.get("venue_id") else fixture)
    detail["venue"] = venue_payload

    with session_factory() as session:
        match = ensure_match_from_fixture(session, detail)
        if league_name:
            match.league = league_name

        existing_balls = session.scalar(
            select(func.count(BallEvent.id)).where(BallEvent.match_id == match.id)
        ) or 0
        has_chart = session.scalar(
            select(AstroChart).where(AstroChart.match_id == match.id)
        ) is not None

        if existing_balls and has_chart and not rebuild:
            stats.skipped_existing += 1
            session.commit()
            return stats

        if rebuild:
            _reset_match(session, match.id)
            # The match was wiped clean, so prior chart/balls no longer exist.
            has_chart = False
            existing_balls = 0

        apply_coordinates(session, match, venue_payload, allow_ai=allow_ai_coords)
        _enrich_outcome(session, match, detail)
        sync_players_from_fixture(session, client, detail, balls_raw)

        anchor = parse_utc(balls_raw[0].get("updated_at")) or match.starting_at_utc
        aligned = match.lat is not None and match.lon is not None and anchor is not None
        if not aligned:
            stats.coords_unresolved += 1
            logger.warning("Fixture %s: coords/anchor unresolved; storing balls unaligned.", fid)

        _write_balls(session, match, balls_raw, stats)
        persist_treated_timestamps_for_match(session, match.id)
        session.flush()  # ensure first_ball_* visible before chart build

        if aligned:
            last_corr = session.scalar(
                select(func.max(BallEvent.event_utc_corrected)).where(BallEvent.match_id == match.id)
            )
            span_h = duration_for_match(match.first_ball_utc, last_corr, match.format)
            write_match_chart(
                session,
                match,
                anchor_utc=match.first_ball_utc,
                duration_hours=span_h,
                rebuild=has_chart or rebuild,
            )
            if not has_chart:
                stats.charts_built += 1
            stats.balls_aligned += align_match(session, match.id, rebuild=True)
            stats.matches_ingested += 1
        session.commit()

    return stats


def _reset_match(session: Session, match_id: int) -> None:
    """Delete prior balls/innings/chart for a clean rebuild."""
    ball_ids = [
        r[0] for r in session.execute(
            select(BallEvent.id).where(BallEvent.match_id == match_id)
        ).all()
    ]
    if ball_ids:
        session.execute(delete(BallAstroState).where(BallAstroState.ball_id.in_(ball_ids)))
    session.execute(delete(BallEvent).where(BallEvent.match_id == match_id))
    session.execute(delete(Innings).where(Innings.match_id == match_id))
    session.execute(delete(AstroTimelinePeriod).where(AstroTimelinePeriod.match_id == match_id))
    chart = session.scalar(select(AstroChart).where(AstroChart.match_id == match_id))
    if chart is not None:
        session.delete(chart)
    session.flush()


def _ensure_innings(
    session: Session, match_id: int, innings_number: int, start_utc: Optional[datetime]
) -> Innings:
    innings = session.scalar(
        select(Innings).where(
            Innings.match_id == match_id,
            Innings.innings_number == innings_number,
        )
    )
    if innings is None:
        innings = Innings(
            match_id=match_id,
            innings_number=innings_number,
            start_utc=start_utc,
            start_ist=to_ist(start_utc),
            total_runs=0,
            wickets=0,
        )
        session.add(innings)
        session.flush()
    return innings


def _write_balls(
    session: Session,
    match: Match,
    balls_raw: List[Dict[str, Any]],
    stats: BackfillStats,
) -> None:
    match_id = match.id
    seen_sm = {
        r[0] for r in session.execute(
            select(BallEvent.sportmonks_ball_id).where(BallEvent.match_id == match_id)
        ).all() if r[0] is not None
    }

    for raw in balls_raw:
        nb = normalize_ball(raw)
        sm_id = nb.get("sportmonks_ball_id")
        if sm_id is not None and sm_id in seen_sm:
            continue

        event_utc = parse_utc(raw.get("updated_at"))
        innings_number = _innings_number_from_scoreboard(nb.get("scoreboard"))
        innings = _ensure_innings(session, match_id, innings_number, event_utc)

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

        runs = nb.get("runs") or 0
        extras = nb.get("extras") or 0
        batsman = ensure_player(session, nb.get("batsman_id"))
        bowler = ensure_player(session, nb.get("bowler_id"))

        ball = BallEvent(
            match_id=match_id,
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
            time_source=TIME_SOURCE,
            sportmonks_ball_id=sm_id,
        )
        session.add(ball)
        session.flush()

        innings.total_runs = ball.score_after
        innings.wickets = ball.wickets_after
        if event_utc is not None:
            if innings.start_utc is None or event_utc < innings.start_utc:
                innings.start_utc = event_utc
                innings.start_ist = to_ist(event_utc)
            if innings.end_utc is None or event_utc > innings.end_utc:
                innings.end_utc = event_utc
                innings.end_ist = to_ist(event_utc)

        stats.balls_written += 1
        if sm_id is not None:
            seen_sm.add(sm_id)


def _enrich_outcome(session: Session, match: Match, detail: Dict[str, Any]) -> None:
    """Map Sportmonks winner/toss ids to local team ids for outcome labels."""
    def local_team_id(sm_id: Any) -> Optional[int]:
        if sm_id is None:
            return None
        t = session.scalar(select(Team).where(Team.sportmonks_id == sm_id))
        return t.id if t else None

    match.winner_team_id = local_team_id(detail.get("winner_team_id"))
    match.toss_won_team_id = local_team_id(detail.get("toss_won_team_id"))
    elected = detail.get("elected")
    if elected:
        match.toss_elected = str(elected)


# --------------------------------------------------------------------------- #
# Year crawler
# --------------------------------------------------------------------------- #
def backfill_year(
    session_factory: Callable[[], Session],
    client: SportmonksClient,
    year: int,
    *,
    leagues: Optional[List[int]] = None,
    allow_ai_coords: bool = True,
    limit: Optional[int] = None,
    rebuild: bool = False,
    progress_every: int = 25,
    end_date: Optional[str] = None,
) -> BackfillStats:
    """Backfill all finished fixtures for a calendar year.

    Args:
        year: Calendar year to crawl.
        leagues: Optional list of Sportmonks league ids to restrict to.
        allow_ai_coords: Allow OpenAI coordinate fallback for unknown venues.
        limit: Stop after this many successfully-ingested matches (debugging).
        rebuild: Re-ingest matches even if already present.
        end_date: Optional 'YYYY-MM-DD' cap (e.g. exclude today/future).
    """
    stats = BackfillStats()
    names = league_name_map(client)

    date_from = f"{year}-01-01"
    date_to = end_date or f"{year}-12-31"
    fixtures = client.get_fixtures_between(date_from, date_to, includes="localteam,visitorteam")
    finished = [f for f in fixtures if str(f.get("status", "")).lower() in FINISHED_STATUSES]
    if leagues:
        wanted = set(leagues)
        finished = [f for f in finished if f.get("league_id") in wanted]

    logger.info(
        "Year %s [%s..%s]: %d fixtures, %d finished%s",
        year, date_from, date_to, len(fixtures), len(finished),
        f" (leagues={sorted(leagues)})" if leagues else "",
    )

    for i, fixture in enumerate(finished, 1):
        if limit is not None and stats.matches_ingested >= limit:
            logger.info("Reached limit=%d; stopping year %s early.", limit, year)
            break
        if str(fixture.get("type") or "").lower() in SKIP_FORMATS:
            stats.skipped_test += 1
            continue
        league_name = names.get(fixture.get("league_id"))
        try:
            backfill_fixture(
                session_factory,
                client,
                fixture,
                allow_ai_coords=allow_ai_coords,
                rebuild=rebuild,
                league_name=league_name,
                stats=stats,
            )
        except Exception as exc:  # noqa: BLE001 - one bad fixture must not kill the crawl
            stats.errors += 1
            logger.exception("Fixture %s failed: %s", fixture.get("id"), exc)
        if i % progress_every == 0:
            logger.info("  [%d/%d] %s", i, len(finished), stats.line())

    logger.info("Year %s done: %s", year, stats.line())
    return stats
