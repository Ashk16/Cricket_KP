"""Nightly historical ingest: finished matches from the last few IST days.

Runs against the historical database (``DATABASE_URL`` / ``data/kp_cricket.db``).
Each Sportmonks fixture is tracked in ``ingest_fixtures`` so repeated failures
(no ball-by-ball, or hard errors) are blocked instead of being retried forever.

Block rules:
- format ``test`` → blocked immediately (``skipped_test``), no detail fetch
- ``no_balls`` twice in a row → blocked (``no_balls_x2``)
- ``error`` three times in a row → blocked (``error_x3``)
- ``coords_unresolved`` stores balls and is **not** auto-blocked
- success (``complete``) resets the consecutive-failure counter

The default window is a short lookback through **yesterday IST**, not a full-year
crawl. Blocked ids are skipped until ``reset_blocked``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AstroChart, BallEvent, IngestFixture, Match
from live.backfill import (
    FINISHED_STATUSES,
    SKIP_FORMATS,
    BackfillStats,
    backfill_fixture,
    league_name_map,
)
from timeutils import now_ist, now_utc, next_ist_clock_time, to_ist

logger = logging.getLogger("kp.nightly")

NO_BALLS_BLOCK_AFTER = 2
ERROR_BLOCK_AFTER = 3
DEFAULT_LOOKBACK_DAYS = 3
DEFAULT_HOUR = 1
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_RUN_PATH = _PROJECT_ROOT / "data" / "nightly_backfill_last_ist.txt"
_ERROR_MAX_LEN = 2000

IngestFn = Callable[[Dict[str, Any]], str]


@dataclass
class NightlyStats:
    fixtures_seen: int = 0
    ingested: int = 0
    already_complete: int = 0
    skipped_blocked: int = 0
    skipped_test: int = 0
    skipped_not_finished: int = 0
    no_balls: int = 0
    coords_unresolved: int = 0
    errors: int = 0
    newly_blocked: int = 0
    attempted: int = 0
    date_from: str = ""
    date_to: str = ""
    blocked_ids: List[int] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"window={self.date_from}..{self.date_to} seen={self.fixtures_seen} "
            f"ingested={self.ingested} already={self.already_complete} "
            f"attempted={self.attempted} no_balls={self.no_balls} "
            f"coords={self.coords_unresolved} errors={self.errors} "
            f"skipped_test={self.skipped_test} skipped_blocked={self.skipped_blocked} "
            f"skipped_live={self.skipped_not_finished} newly_blocked={self.newly_blocked}"
        )


def lookback_window(
    lookback_days: int,
    now: Optional[datetime] = None,
) -> Tuple[date, date]:
    """Inclusive IST dates: ``lookback_days`` calendar days ending yesterday."""
    now = now if now is not None else now_ist()
    days = max(int(lookback_days), 1)
    yesterday = now.date() - timedelta(days=1)
    start = yesterday - timedelta(days=days - 1)
    return start, yesterday


def should_run_now(
    now: Optional[datetime] = None,
    last_run: Optional[date] = None,
    *,
    hour: int = DEFAULT_HOUR,
    catchup: bool = True,
) -> bool:
    """True when today's 1 AM IST slot is due and has not already run."""
    now = now if now is not None else now_ist()
    scheduled = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if last_run == now.date():
        return False
    if now < scheduled:
        return False
    if catchup:
        return True
    # No catch-up: only fire in the first couple of minutes after the hour so a
    # late-started process waits until tomorrow rather than ingesting at 7pm.
    return (now - scheduled) < timedelta(minutes=2)


def load_last_run(path: Path = LAST_RUN_PATH) -> Optional[date]:
    try:
        text = path.read_text(encoding="utf-8").strip()
        return date.fromisoformat(text) if text else None
    except (OSError, ValueError):
        return None


def save_last_run(when: date, path: Path = LAST_RUN_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(when.isoformat() + "\n", encoding="utf-8")


def reset_blocked(session_factory: Callable[[], Session], fixture_id: int) -> bool:
    """Clear the block flag so the next nightly run will retry this fixture."""
    with session_factory() as session:
        row = session.get(IngestFixture, fixture_id)
        if row is None:
            return False
        row.blocked = False
        row.blocked_reason = None
        row.consecutive_failures = 0
        row.status = "pending"
        row.updated_at = now_utc()
        session.commit()
        return True


def list_blocked(session_factory: Callable[[], Session]) -> List[IngestFixture]:
    with session_factory() as session:
        return list(
            session.scalars(
                select(IngestFixture)
                .where(IngestFixture.blocked.is_(True))
                .order_by(IngestFixture.sportmonks_fixture_id)
            ).all()
        )


def format_status_report(session_factory: Callable[[], Session]) -> str:
    with session_factory() as session:
        rows = list(session.scalars(select(IngestFixture)).all())
    if not rows:
        return "ingest_fixtures: (empty)"
    counts: Dict[str, int] = {}
    blocked: List[IngestFixture] = []
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        if row.blocked:
            blocked.append(row)
    lines = ["ingest_fixtures status counts:"]
    for key in sorted(counts):
        lines.append(f"  {key}: {counts[key]}")
    lines.append(f"blocked: {len(blocked)}")
    for row in blocked[:50]:
        lines.append(
            f"  id={row.sportmonks_fixture_id} reason={row.blocked_reason} "
            f"attempts={row.attempts} last={row.last_error or '-'}"
        )
    if len(blocked) > 50:
        lines.append(f"  ... {len(blocked) - 50} more")
    return "\n".join(lines)


def run_nightly(
    session_factory: Callable[[], Session],
    client: Any,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    allow_ai_coords: bool = True,
    now: Optional[datetime] = None,
    clock_utc: Optional[Callable[[], datetime]] = None,
    ingest_fn: Optional[IngestFn] = None,
    mark_last_run: bool = True,
) -> NightlyStats:
    """Ingest finished fixtures in the lookback window. Idempotent."""
    now = now if now is not None else now_ist()
    utc_now = clock_utc or now_utc
    date_from, date_to = lookback_window(lookback_days, now)
    stats = NightlyStats(date_from=date_from.isoformat(), date_to=date_to.isoformat())

    fixtures = client.get_fixtures_between(
        stats.date_from,
        stats.date_to,
        includes="localteam,visitorteam",
    )
    stats.fixtures_seen = len(fixtures)
    logger.info("Nightly window %s..%s: %d fixtures", stats.date_from, stats.date_to, len(fixtures))

    names: Dict[int, str] = {}
    if ingest_fn is None:
        try:
            names = league_name_map(client)
        except Exception:  # noqa: BLE001 - names are cosmetic
            logger.warning("Could not load league names; continuing without them.")

    worker = ingest_fn or _default_ingest_fn(session_factory, client, allow_ai_coords, names)

    for fixture in fixtures:
        fid = fixture.get("id")
        if fid is None:
            continue
        fid = int(fid)
        sm_status = str(fixture.get("status") or "")
        fmt = str(fixture.get("type") or "").lower()

        if str(sm_status).lower() not in FINISHED_STATUSES:
            stats.skipped_not_finished += 1
            continue

        with session_factory() as session:
            row = session.get(IngestFixture, fid)
            if row is not None and row.blocked:
                stats.skipped_blocked += 1
                continue
            if _complete_in_db(session, fid) or (row is not None and row.status == "complete"):
                if row is None or row.status != "complete":
                    _upsert_complete(session, fid, sm_status, utc_now())
                stats.already_complete += 1
                continue

        if fmt in SKIP_FORMATS:
            _record_outcome(
                session_factory,
                fid,
                outcome="skipped_test",
                sm_status=sm_status,
                error=None,
                when=utc_now(),
            )
            stats.skipped_test += 1
            stats.newly_blocked += 1
            stats.blocked_ids.append(fid)
            continue

        stats.attempted += 1
        try:
            outcome = worker(fixture)
        except Exception as exc:  # noqa: BLE001 - one fixture must not kill the night
            logger.exception("Fixture %s failed: %s", fid, exc)
            outcome = "error"
            error = str(exc)[:_ERROR_MAX_LEN]
        else:
            error = None if outcome in ("complete", "coords_unresolved") else (outcome or "unknown")
            if outcome not in {
                "complete",
                "no_balls",
                "error",
                "skipped_test",
                "coords_unresolved",
            }:
                error = f"unexpected_outcome:{outcome}"
                outcome = "error"

        newly = _record_outcome(
            session_factory,
            fid,
            outcome=outcome,
            sm_status=sm_status,
            error=error,
            when=utc_now(),
        )
        if outcome == "complete":
            stats.ingested += 1
        elif outcome == "no_balls":
            stats.no_balls += 1
        elif outcome == "coords_unresolved":
            stats.coords_unresolved += 1
        elif outcome == "skipped_test":
            stats.skipped_test += 1
        else:
            stats.errors += 1
        if newly:
            stats.newly_blocked += 1
            stats.blocked_ids.append(fid)

    logger.info("Nightly done: %s", stats.line())
    if mark_last_run:
        save_last_run(now.date())
    return stats


def start_nightly_thread(
    session_factory: Callable[[], Session],
    *,
    client: Any = None,
    lookback_days: Optional[int] = None,
    hour: Optional[int] = None,
    catchup: Optional[bool] = None,
    allow_ai_coords: Optional[bool] = None,
) -> None:
    """Background thread: sleep until 1:00 IST, then run ``run_nightly``."""
    import threading

    from live.sportmonks_client import SportmonksClient

    lookback = lookback_days if lookback_days is not None else int(
        os.getenv("NIGHTLY_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS))
    )
    hour_ist = hour if hour is not None else int(os.getenv("NIGHTLY_HOUR", str(DEFAULT_HOUR)))
    do_catchup = (os.getenv("NIGHTLY_CATCHUP", "1") != "0") if catchup is None else catchup
    allow_ai = (
        (os.getenv("ALLOW_AI_COORDS", "0") == "1") if allow_ai_coords is None else allow_ai_coords
    )

    def loop() -> None:
        local_client = client or SportmonksClient()
        logger.info(
            "Nightly backfill thread started (1:00 IST, lookback=%sd, catchup=%s)",
            lookback,
            do_catchup,
        )
        while True:
            try:
                ist = now_ist()
                last = load_last_run()
                if should_run_now(ist, last, hour=hour_ist, catchup=do_catchup):
                    logger.info("Nightly backfill starting (IST %s)", ist.strftime("%Y-%m-%d %H:%M"))
                    run_nightly(
                        session_factory,
                        local_client,
                        lookback_days=lookback,
                        allow_ai_coords=allow_ai,
                        now=ist,
                    )
                    continue
                nxt = next_ist_clock_time(ist, hour=hour_ist)
                delay = min(60.0, max(1.0, (nxt - ist).total_seconds()))
                time.sleep(delay)
            except Exception:  # noqa: BLE001 - keep the thread alive
                logger.exception("Nightly loop error; sleeping 60s")
                time.sleep(60)

    threading.Thread(target=loop, name="nightly-backfill", daemon=True).start()


def _complete_in_db(session: Session, fixture_id: int) -> bool:
    match = session.scalar(select(Match).where(Match.sportmonks_fixture_id == fixture_id))
    if match is None:
        return False
    balls = session.scalar(
        select(func.count(BallEvent.id)).where(BallEvent.match_id == match.id)
    ) or 0
    chart = session.scalar(select(AstroChart).where(AstroChart.match_id == match.id))
    return balls > 0 and chart is not None


def _upsert_complete(
    session: Session,
    fixture_id: int,
    sm_status: str,
    when: datetime,
) -> None:
    row = session.get(IngestFixture, fixture_id)
    if row is None:
        row = IngestFixture(sportmonks_fixture_id=fixture_id)
        session.add(row)
    row.status = "complete"
    row.blocked = False
    row.blocked_reason = None
    row.consecutive_failures = 0
    row.last_status = sm_status or row.last_status
    row.last_error = None
    row.updated_at = when
    session.commit()


def _get_or_create(session: Session, fixture_id: int) -> IngestFixture:
    row = session.get(IngestFixture, fixture_id)
    if row is None:
        row = IngestFixture(
            sportmonks_fixture_id=fixture_id,
            status="pending",
            attempts=0,
            consecutive_failures=0,
            blocked=False,
        )
        session.add(row)
        session.flush()
    return row


def _record_outcome(
    session_factory: Callable[[], Session],
    fixture_id: int,
    *,
    outcome: str,
    sm_status: Optional[str],
    error: Optional[str],
    when: datetime,
) -> bool:
    """Persist ledger row. Returns True if this call newly blocked the fixture."""
    with session_factory() as session:
        row = _get_or_create(session, fixture_id)
        was_blocked = bool(row.blocked)
        row.attempts = int(row.attempts or 0) + 1
        row.last_attempt_utc = when
        row.last_attempt_ist = to_ist(when)
        row.last_status = sm_status
        row.updated_at = when
        row.status = outcome
        row.last_error = (error[:_ERROR_MAX_LEN] if error else None)

        if outcome in ("complete", "coords_unresolved"):
            row.consecutive_failures = 0
            row.blocked = False
            row.blocked_reason = None
        elif outcome == "skipped_test":
            row.blocked = True
            row.blocked_reason = "skipped_test"
        elif outcome == "no_balls":
            row.consecutive_failures = int(row.consecutive_failures or 0) + 1
            if row.consecutive_failures >= NO_BALLS_BLOCK_AFTER:
                row.blocked = True
                row.blocked_reason = "no_balls_x2"
                row.status = "blocked"
        else:
            row.consecutive_failures = int(row.consecutive_failures or 0) + 1
            if row.consecutive_failures >= ERROR_BLOCK_AFTER:
                row.blocked = True
                row.blocked_reason = "error_x3"
                row.status = "blocked"

        newly = row.blocked and not was_blocked
        session.commit()
        if newly:
            logger.info(
                "Blocked fixture %s reason=%s after %s consecutive failures",
                fixture_id,
                row.blocked_reason,
                row.consecutive_failures,
            )
        return newly


def _classify_stats(stats: BackfillStats) -> str:
    if stats.no_ball_data:
        return "no_balls"
    if stats.matches_ingested or stats.skipped_existing:
        return "complete"
    if stats.coords_unresolved:
        return "coords_unresolved"
    if stats.errors:
        return "error"
    if stats.skipped_test:
        return "skipped_test"
    return "error"


def _default_ingest_fn(
    session_factory: Callable[[], Session],
    client: Any,
    allow_ai_coords: bool,
    names: Dict[int, str],
) -> IngestFn:
    def ingest(fixture: Dict[str, Any]) -> str:
        stats = BackfillStats()
        backfill_fixture(
            session_factory,
            client,
            fixture,
            allow_ai_coords=allow_ai_coords,
            league_name=names.get(fixture.get("league_id")),
            stats=stats,
        )
        return _classify_stats(stats)

    return ingest
