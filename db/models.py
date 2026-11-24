"""SQLAlchemy models - schema v1.

Design notes:
- All timestamps are stored as naive UTC datetimes (no local time anywhere).
- Cricket tables mirror Sportmonks concepts; astrology tables mirror the KP
  chart engine output; `ball_astro_state` is the alignment bridge between them.
- Prediction / learning tables are created now (design-ready) but populated in
  later phases.
- The schema is intentionally PostgreSQL-friendly (no SQLite-only types).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


# --------------------------------------------------------------------------- #
# Reference / cricket
# --------------------------------------------------------------------------- #
class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    sportmonks_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[Optional[str]] = mapped_column(String(20))


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    sportmonks_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[Optional[str]] = mapped_column(String(40))


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    sportmonks_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[Optional[str]] = mapped_column(String(120))
    country: Mapped[Optional[str]] = mapped_column(String(120))
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)
    timezone: Mapped[Optional[str]] = mapped_column(String(60))
    coords_source: Mapped[Optional[str]] = mapped_column(String(20))  # library | ai | manual | none


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    sportmonks_fixture_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    format: Mapped[Optional[str]] = mapped_column(String(20))      # T20 / ODI / Test
    league: Mapped[Optional[str]] = mapped_column(String(120))
    season: Mapped[Optional[str]] = mapped_column(String(40))

    localteam_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    visitorteam_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    venue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("venues.id"))

    starting_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    starting_at_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # The instant the first ball was actually detected (chart is anchored here,
    # not at the scheduled time, since play may start late).
    first_ball_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    first_ball_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Venue coordinates snapshotted on the match (chart needs lat/lon at start).
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)

    toss_won_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    toss_elected: Mapped[Optional[str]] = mapped_column(String(20))  # bat / bowl

    status: Mapped[Optional[str]] = mapped_column(String(40))
    winner_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    result_note: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    innings = relationship("Innings", back_populates="match", cascade="all, delete-orphan")
    balls = relationship("BallEvent", back_populates="match", cascade="all, delete-orphan")
    chart = relationship("AstroChart", back_populates="match", uselist=False, cascade="all, delete-orphan")


class IngestFixture(Base):
    """Per-fixture ingest ledger for the nightly historical backfill.

    Finished Sportmonks fixtures that repeatedly fail (no ball-by-ball, or
    hard errors) are flagged ``blocked`` so later nights skip them instead of
    retrying forever. Tests are blocked immediately. Unresolved coordinates
    still store balls and are not auto-blocked.
    """

    __tablename__ = "ingest_fixtures"
    __table_args__ = (
        Index("ix_ingest_fixtures_blocked", "blocked"),
        Index("ix_ingest_fixtures_status", "status"),
    )

    sportmonks_fixture_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # complete | no_balls | error | skipped_test | blocked | coords_unresolved | pending
    status: Mapped[str] = mapped_column(String(40), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_status: Mapped[Optional[str]] = mapped_column(String(40))  # Sportmonks fixture status
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[Optional[str]] = mapped_column(String(80))
    last_attempt_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_attempt_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Innings(Base):
    __tablename__ = "innings"
    __table_args__ = (UniqueConstraint("match_id", "innings_number", name="uq_innings_match_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    innings_number: Mapped[int] = mapped_column(Integer)
    batting_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    bowling_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    start_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    start_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    total_runs: Mapped[Optional[int]] = mapped_column(Integer)
    wickets: Mapped[Optional[int]] = mapped_column(Integer)
    overs: Mapped[Optional[float]] = mapped_column(Float)

    match = relationship("Match", back_populates="innings")


class BallEvent(Base):
    __tablename__ = "ball_events"
    __table_args__ = (
        UniqueConstraint("match_id", "innings_id", "ball_seq", name="uq_ball_match_innings_seq"),
        Index("ix_ball_match_event_utc", "match_id", "event_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    innings_id: Mapped[Optional[int]] = mapped_column(ForeignKey("innings.id"), index=True)

    over: Mapped[Optional[int]] = mapped_column(Integer)
    ball: Mapped[Optional[int]] = mapped_column(Integer)
    ball_seq: Mapped[Optional[int]] = mapped_column(Integer)  # global delivery index within match

    batsman_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))
    bowler_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))

    runs: Mapped[Optional[int]] = mapped_column(Integer)
    extras: Mapped[Optional[int]] = mapped_column(Integer)
    is_wicket: Mapped[bool] = mapped_column(Boolean, default=False)
    is_four: Mapped[bool] = mapped_column(Boolean, default=False)
    is_six: Mapped[bool] = mapped_column(Boolean, default=False)
    score_after: Mapped[Optional[int]] = mapped_column(Integer)
    wickets_after: Mapped[Optional[int]] = mapped_column(Integer)
    commentary: Mapped[Optional[str]] = mapped_column(Text)

    # Raw Sportmonks updated_at (unchanged after ingest).
    event_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    event_ist: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    time_source: Mapped[str] = mapped_column(String(20), default="live_poll")  # live_poll | estimated
    # Burst-adjusted delivery time (reverse-walk treatment).
    event_utc_treated: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    event_ist_treated: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Treated time minus flat Sportmonks publication delay (default 35s).
    event_utc_corrected: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    event_ist_corrected: Mapped[Optional[datetime]] = mapped_column(DateTime)
    time_correction_sec: Mapped[Optional[float]] = mapped_column(Float)
    timestamp_in_burst: Mapped[bool] = mapped_column(Boolean, default=False)

    sportmonks_ball_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    match = relationship("Match", back_populates="balls")
    astro_state = relationship(
        "BallAstroState", back_populates="ball", uselist=False, cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# Astrology
# --------------------------------------------------------------------------- #
class AstroChart(Base):
    __tablename__ = "astro_charts"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True, index=True)
    datetime_utc: Mapped[datetime] = mapped_column(DateTime)
    datetime_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    ayanamsa: Mapped[str] = mapped_column(String(40))
    ayanamsa_value: Mapped[Optional[float]] = mapped_column(Float)
    julian_day: Mapped[Optional[float]] = mapped_column(Float)
    duration_hours: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    match = relationship("Match", back_populates="chart")
    planets = relationship("AstroPlanet", back_populates="chart", cascade="all, delete-orphan")
    cusps = relationship("AstroCusp", back_populates="chart", cascade="all, delete-orphan")
    periods = relationship("AstroTimelinePeriod", back_populates="chart", cascade="all, delete-orphan")


class AstroPlanet(Base):
    __tablename__ = "astro_planets"

    id: Mapped[int] = mapped_column(primary_key=True)
    chart_id: Mapped[int] = mapped_column(ForeignKey("astro_charts.id"), index=True)
    planet: Mapped[str] = mapped_column(String(10))
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    sign: Mapped[Optional[str]] = mapped_column(String(20))
    sign_lord: Mapped[Optional[str]] = mapped_column(String(10))
    nl: Mapped[Optional[str]] = mapped_column(String(10))
    sl: Mapped[Optional[str]] = mapped_column(String(10))
    ssl: Mapped[Optional[str]] = mapped_column(String(10))
    sssl: Mapped[Optional[str]] = mapped_column(String(10))
    is_retrograde: Mapped[bool] = mapped_column(Boolean, default=False)
    speed: Mapped[Optional[float]] = mapped_column(Float)
    # KP significators: [{"house": int, "rule": int}, ...] sorted by rule then house.
    significators: Mapped[Optional[list]] = mapped_column(JSON)
    significators_display: Mapped[Optional[str]] = mapped_column(String(500))

    chart = relationship("AstroChart", back_populates="planets")


class AstroCusp(Base):
    __tablename__ = "astro_cusps"

    id: Mapped[int] = mapped_column(primary_key=True)
    chart_id: Mapped[int] = mapped_column(ForeignKey("astro_charts.id"), index=True)
    cusp_no: Mapped[int] = mapped_column(Integer)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    sign: Mapped[Optional[str]] = mapped_column(String(20))
    sign_lord: Mapped[Optional[str]] = mapped_column(String(10))
    nl: Mapped[Optional[str]] = mapped_column(String(10))
    sl: Mapped[Optional[str]] = mapped_column(String(10))
    ssl: Mapped[Optional[str]] = mapped_column(String(10))
    sssl: Mapped[Optional[str]] = mapped_column(String(10))

    chart = relationship("AstroChart", back_populates="cusps")


class AstroTimelinePeriod(Base):
    __tablename__ = "astro_timeline_periods"
    __table_args__ = (
        Index("ix_period_lookup", "match_id", "body", "level", "start_utc", "end_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chart_id: Mapped[int] = mapped_column(ForeignKey("astro_charts.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    body: Mapped[str] = mapped_column(String(20))   # Ascendant | Moon
    level: Mapped[str] = mapped_column(String(10))  # NL | SL | SSL | SSSL
    start_utc: Mapped[datetime] = mapped_column(DateTime)
    end_utc: Mapped[datetime] = mapped_column(DateTime)
    start_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    nl: Mapped[Optional[str]] = mapped_column(String(10))
    sl: Mapped[Optional[str]] = mapped_column(String(10))
    ssl: Mapped[Optional[str]] = mapped_column(String(10))
    sssl: Mapped[Optional[str]] = mapped_column(String(10))
    longitude_start: Mapped[Optional[float]] = mapped_column(Float)

    chart = relationship("AstroChart", back_populates="periods")


# --------------------------------------------------------------------------- #
# Alignment bridge
# --------------------------------------------------------------------------- #
class BallAstroState(Base):
    """Denormalized active KP lords for each ball (recomputable from periods)."""

    __tablename__ = "ball_astro_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    ball_id: Mapped[int] = mapped_column(ForeignKey("ball_events.id"), unique=True, index=True)

    asc_nl: Mapped[Optional[str]] = mapped_column(String(10))
    asc_sl: Mapped[Optional[str]] = mapped_column(String(10))
    asc_ssl: Mapped[Optional[str]] = mapped_column(String(10))
    asc_sssl: Mapped[Optional[str]] = mapped_column(String(10))

    moon_nl: Mapped[Optional[str]] = mapped_column(String(10))
    moon_sl: Mapped[Optional[str]] = mapped_column(String(10))
    moon_ssl: Mapped[Optional[str]] = mapped_column(String(10))
    moon_sssl: Mapped[Optional[str]] = mapped_column(String(10))

    asc_period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("astro_timeline_periods.id"))
    moon_period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("astro_timeline_periods.id"))

    ball = relationship("BallEvent", back_populates="astro_state")


# --------------------------------------------------------------------------- #
# Odds (optional; plan-gated). Stored as a time series aligned to the timeline.
# --------------------------------------------------------------------------- #
class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        Index("ix_odds_match_captured", "match_id", "captured_utc"),
        UniqueConstraint(
            "match_id", "market", "bookmaker", "selection", "updated_at_source",
            name="uq_odds_change",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)

    # When WE captured it (aligns to the astro timeline, like a ball's event_utc).
    captured_utc: Mapped[datetime] = mapped_column(DateTime, index=True)
    captured_ist: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # When the bookmaker value last changed, per the API (used for dedup).
    updated_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime)

    market: Mapped[Optional[str]] = mapped_column(String(80))      # e.g. "Match Winner"
    bookmaker: Mapped[Optional[str]] = mapped_column(String(80))
    selection: Mapped[Optional[str]] = mapped_column(String(120))  # e.g. team / "home" / "away"
    odd_value: Mapped[Optional[float]] = mapped_column(Float)      # decimal odd
    is_inplay: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[Optional[dict]] = mapped_column(JSON)

    # Active KP lords at capture time (denormalized for movement analysis).
    asc_ssl: Mapped[Optional[str]] = mapped_column(String(10))
    asc_sssl: Mapped[Optional[str]] = mapped_column(String(10))
    moon_ssl: Mapped[Optional[str]] = mapped_column(String(10))
    moon_sssl: Mapped[Optional[str]] = mapped_column(String(10))
    asc_period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("astro_timeline_periods.id"))
    moon_period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("astro_timeline_periods.id"))


# --------------------------------------------------------------------------- #
# Prediction / learning (design-ready; populated in later phases)
# --------------------------------------------------------------------------- #
class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    condition: Mapped[Optional[str]] = mapped_column(Text)
    outcome: Mapped[Optional[str]] = mapped_column(Text)
    authority: Mapped[Optional[str]] = mapped_column(String(40))  # verified_from_book, AI_suggested, ...
    status: Mapped[Optional[str]] = mapped_column(String(40))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RuleConfidence(Base):
    __tablename__ = "rule_confidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.rule_id"), index=True)
    matches_tested: Mapped[Optional[int]] = mapped_column(Integer)
    success_rate: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[Optional[str]] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MappingExperiment(Base):
    __tablename__ = "mapping_experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    hypothesis: Mapped[Optional[str]] = mapped_column(Text)
    params: Mapped[Optional[dict]] = mapped_column(JSON)
    result: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    made_at_utc: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    phase: Mapped[Optional[str]] = mapped_column(String(40))  # pre_match, after_toss, over_5, ...
    target: Mapped[Optional[str]] = mapped_column(String(60))
    predicted_value: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    actual_value: Mapped[Optional[str]] = mapped_column(Text)
    correct: Mapped[Optional[bool]] = mapped_column(Boolean)


class PredictionEvidence(Base):
    __tablename__ = "prediction_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(60))
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)


class LearningReport(Base):
    __tablename__ = "learning_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    report: Mapped[Optional[str]] = mapped_column(Text)
    suggested_updates: Mapped[Optional[dict]] = mapped_column(JSON)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    config: Mapped[Optional[dict]] = mapped_column(JSON)
    results: Mapped[Optional[dict]] = mapped_column(JSON)
