"""Nightly backfill ledger + skip/block rules (no Sportmonks key needed).

Run: python -m tests.test_nightly_backfill
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.models import AstroChart, BallEvent, IngestFixture, Match
from db.session import Base
from live.nightly_backfill import (
    lookback_window,
    reset_blocked,
    run_nightly,
    should_run_now,
)


def _memory_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class FakeClient:
    def __init__(self, fixtures: List[Dict[str, Any]]):
        self.fixtures = fixtures
        self.between_calls = 0

    def get_fixtures_between(self, date_from: str, date_to: str, includes: str = "") -> List[Dict[str, Any]]:
        self.between_calls += 1
        return list(self.fixtures)


def _fx(fid: int, *, status: str = "Finished", typ: str = "T20I") -> Dict[str, Any]:
    return {"id": fid, "status": status, "type": typ, "league_id": 1}


def _seed_complete(session_factory, fixture_id: int) -> None:
    with session_factory() as session:
        match = Match(sportmonks_fixture_id=fixture_id, format="T20")
        session.add(match)
        session.flush()
        session.add(BallEvent(match_id=match.id, runs=1, is_wicket=False, is_four=False, is_six=False))
        session.add(
            AstroChart(
                match_id=match.id,
                datetime_utc=datetime(2026, 9, 1, 10, 0, 0),
                lat=0.0,
                lon=0.0,
                ayanamsa="krishnamurti",
            )
        )
        session.commit()


def test_lookback_ends_yesterday():
    now = datetime(2026, 9, 7, 4, 0, 0)
    start, end = lookback_window(3, now)
    assert start == date(2026, 9, 4)
    assert end == date(2026, 9, 6)


def test_should_run_catchup_after_1am():
    now = datetime(2026, 9, 7, 18, 55, 0)
    assert should_run_now(now, last_run=None, hour=1, catchup=True)
    assert not should_run_now(now, last_run=date(2026, 9, 7), hour=1, catchup=True)
    assert not should_run_now(datetime(2026, 9, 7, 0, 59, 0), last_run=None, hour=1, catchup=True)
    assert not should_run_now(now, last_run=None, hour=1, catchup=False)


def test_ingest_success():
    factory = _memory_factory()
    calls: List[int] = []

    def ingest(fixture):
        calls.append(fixture["id"])
        return "complete"

    stats = run_nightly(
        factory,
        FakeClient([_fx(11)]),
        now=datetime(2026, 9, 7, 4, 0, 0),
        ingest_fn=ingest,
        mark_last_run=False,
    )
    assert stats.ingested == 1 and stats.attempted == 1
    assert calls == [11]
    with factory() as session:
        row = session.get(IngestFixture, 11)
        assert row is not None
        assert row.status == "complete"
        assert row.blocked is False
        assert row.consecutive_failures == 0


def test_skip_already_complete_no_ingest():
    factory = _memory_factory()
    _seed_complete(factory, 22)
    calls: List[int] = []

    stats = run_nightly(
        factory,
        FakeClient([_fx(22)]),
        now=datetime(2026, 9, 7, 4, 0, 0),
        ingest_fn=lambda f: calls.append(f["id"]) or "complete",
        mark_last_run=False,
    )
    assert stats.already_complete == 1
    assert calls == []
    with factory() as session:
        row = session.get(IngestFixture, 22)
        assert row.status == "complete"


def test_no_balls_blocked_after_two():
    factory = _memory_factory()
    client = FakeClient([_fx(33)])
    ingest = lambda f: "no_balls"
    now = datetime(2026, 9, 7, 4, 0, 0)

    s1 = run_nightly(factory, client, now=now, ingest_fn=ingest, mark_last_run=False)
    assert s1.no_balls == 1 and s1.newly_blocked == 0
    s2 = run_nightly(
        factory, client, now=now + timedelta(days=1), ingest_fn=ingest, mark_last_run=False
    )
    assert s2.no_balls == 1 and s2.newly_blocked == 1
    with factory() as session:
        row = session.get(IngestFixture, 33)
        assert row.blocked is True
        assert row.blocked_reason == "no_balls_x2"
        assert row.status == "blocked"
        assert row.attempts == 2

    s3 = run_nightly(
        factory, client, now=now + timedelta(days=2), ingest_fn=ingest, mark_last_run=False
    )
    assert s3.skipped_blocked == 1
    assert s3.attempted == 0
    with factory() as session:
        assert session.get(IngestFixture, 33).attempts == 2


def test_error_blocked_after_three():
    factory = _memory_factory()
    client = FakeClient([_fx(44)])
    now = datetime(2026, 9, 7, 4, 0, 0)

    def boom(fixture):
        raise RuntimeError("feed down")

    for i in range(3):
        stats = run_nightly(
            factory,
            client,
            now=now + timedelta(days=i),
            ingest_fn=boom,
            mark_last_run=False,
        )
        if i < 2:
            assert stats.errors == 1 and stats.newly_blocked == 0
        else:
            assert stats.newly_blocked == 1

    with factory() as session:
        row = session.get(IngestFixture, 44)
        assert row.blocked is True
        assert row.blocked_reason == "error_x3"
        assert row.attempts == 3
        assert "feed down" in (row.last_error or "")

    later = run_nightly(
        factory, client, now=now + timedelta(days=4), ingest_fn=boom, mark_last_run=False
    )
    assert later.skipped_blocked == 1


def test_success_resets_consecutive_failures():
    factory = _memory_factory()
    client = FakeClient([_fx(55)])
    now = datetime(2026, 9, 7, 4, 0, 0)
    run_nightly(factory, client, now=now, ingest_fn=lambda f: "error", mark_last_run=False)
    run_nightly(
        factory,
        client,
        now=now + timedelta(days=1),
        ingest_fn=lambda f: "complete",
        mark_last_run=False,
    )
    with factory() as session:
        row = session.get(IngestFixture, 55)
        assert row.status == "complete"
        assert row.consecutive_failures == 0
        assert row.blocked is False


def test_skip_test_format_blocks_without_ingest():
    factory = _memory_factory()
    calls: List[int] = []
    stats = run_nightly(
        factory,
        FakeClient([_fx(66, typ="test")]),
        now=datetime(2026, 9, 7, 4, 0, 0),
        ingest_fn=lambda f: calls.append(f["id"]) or "complete",
        mark_last_run=False,
    )
    assert stats.skipped_test == 1
    assert stats.newly_blocked == 1
    assert calls == []
    with factory() as session:
        row = session.get(IngestFixture, 66)
        assert row.blocked is True
        assert row.blocked_reason == "skipped_test"


def test_coords_unresolved_not_blocked():
    factory = _memory_factory()
    client = FakeClient([_fx(77)])
    now = datetime(2026, 9, 7, 4, 0, 0)
    for i in range(3):
        stats = run_nightly(
            factory,
            client,
            now=now + timedelta(days=i),
            ingest_fn=lambda f: "coords_unresolved",
            mark_last_run=False,
        )
        assert stats.coords_unresolved == 1
        assert stats.newly_blocked == 0
    with factory() as session:
        row = session.get(IngestFixture, 77)
        assert row.blocked is False
        assert row.status == "coords_unresolved"
        assert row.consecutive_failures == 0


def test_skip_unfinished():
    factory = _memory_factory()
    calls: List[int] = []
    stats = run_nightly(
        factory,
        FakeClient([_fx(88, status="1st Innings")]),
        now=datetime(2026, 9, 7, 4, 0, 0),
        ingest_fn=lambda f: calls.append(f["id"]) or "complete",
        mark_last_run=False,
    )
    assert stats.skipped_not_finished == 1
    assert calls == []
    with factory() as session:
        assert session.get(IngestFixture, 88) is None


def test_reset_blocked_retries():
    factory = _memory_factory()
    client = FakeClient([_fx(99)])
    now = datetime(2026, 9, 7, 4, 0, 0)
    ingest = lambda f: "no_balls"
    run_nightly(factory, client, now=now, ingest_fn=ingest, mark_last_run=False)
    run_nightly(factory, client, now=now + timedelta(days=1), ingest_fn=ingest, mark_last_run=False)
    assert reset_blocked(factory, 99) is True
    calls: List[int] = []
    stats = run_nightly(
        factory,
        client,
        now=now + timedelta(days=2),
        ingest_fn=lambda f: calls.append(f["id"]) or "complete",
        mark_last_run=False,
    )
    assert calls == [99]
    assert stats.ingested == 1
    with factory() as session:
        row = session.get(IngestFixture, 99)
        assert row.blocked is False
        assert row.status == "complete"


def run() -> bool:
    tests = [
        test_lookback_ends_yesterday,
        test_should_run_catchup_after_1am,
        test_ingest_success,
        test_skip_already_complete_no_ingest,
        test_no_balls_blocked_after_two,
        test_error_blocked_after_three,
        test_success_resets_consecutive_failures,
        test_skip_test_format_blocks_without_ingest,
        test_coords_unresolved_not_blocked,
        test_skip_unfinished,
        test_reset_blocked_retries,
    ]
    ok = True
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:
            ok = False
            print(f"FAIL {fn.__name__}: {exc}")
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if run() else 1)
