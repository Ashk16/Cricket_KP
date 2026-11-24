# KP Cricket Predictor

An explainable KP-astrology cricket prediction system, built as an **always-on
backend**. A supervisor daemon watches the Sportmonks schedule, and for each
match it:

- detects the **first ball**, then resolves the venue coordinates and generates
  the KP chart **anchored to the first-ball instant** (not the scheduled time -
  play often starts late);
- polls ball-by-ball data, stamping each new ball with a **real UTC timestamp**
  as it arrives, and maps that ball to the active astrology period;
- stores everything in the database continuously, whether or not a UI is open.

Because all state lives in the database, a UI is just a **read-only viewer**: a
user can open it at 7:20 and see the chart + score so far, close it, reopen at
8:00 and see the state up to 8:00 - or request any earlier "as of" instant.

The chart-generation engine is ported from the existing `KP_AI_astrologer`
project (chart + timelines only; the legacy scoring layer was intentionally
left out).

## What's built (Phase 1)

```
astro/                 KP chart engine (ported) + chart_service
  kp_engine.py         planets, cusps, NL/SL/SSL/SSSL lords (sidereal, Krishnamurti)
  timeline_generator.py exact lord-transition timelines (to the second)
  chart_service.py     build_match_chart() -> planets, cusps, Asc + Moon timelines
swisseph/              Swiss Ephemeris support files
db/
  models.py            SQLAlchemy schema v1 (cricket + astrology + alignment + design-ready tables)
  session.py           engine/session from DATABASE_URL (SQLite now, Postgres-ready)
  schema.sql           generated DDL reference
  export_schema.py     create DB + dump schema.sql
live/
  sportmonks_client.py fixtures + balls + schedule/livescores fetch and normalization
  sportradar_client.py Sportradar Cricket v2 client (trial/production; optional second feed)
  check_sportradar.py  verify SPORTRADAR_API_KEY + list tournaments/schedule
  venue_coords.py      ground lat/long resolver: JSON library + OpenAI fallback (cached)
  match_setup.py       persist teams / venue / players / match; apply coordinates
  astro_writer.py      generate + persist chart and timelines (anchored at first ball)
  poller.py            poll balls, stamp real event_utc, write ball_events, align; first-ball hook
  aligner.py           map each ball's event_utc to active Asc/Moon periods
  supervisor.py        always-on daemon: schedule sync + per-match watchers
  nightly_backfill.py  1 AM IST historical ingest + failure flags (ingest_fixtures)
  match_state.py       read-only snapshot for UIs/APIs ("as of now" or any instant)
learning/              (later) historical analysis / rule mining
data/
  kp_cricket.db        SQLite database
  ground_coords.json   curated ground lat/long library (AI results cached here)
run_daemon.py          entrypoint for the always-on supervisor (+ nightly thread)
run_nightly_backfill.py  one-shot or 1 AM IST daemon for historical DB ingest
view_match.py          read-only CLI viewer (connect anytime)
```

## Ground coordinates (no geocoding packages)

`live/venue_coords.py` resolves a ground's lat/long **library-first**:

1. `data/ground_coords.json` matched by Sportmonks venue id, then by name|city.
2. If missing and `OPENAI_API_KEY` is set, an OpenAI call resolves it (via the
   REST API, no extra SDK), validates the result, and **caches it back** into
   the library with `source: "ai"`.
3. If still unresolved, the ball data is still stored; alignment fills in once
   coordinates are added.

## Configuring the token + which data we request

1. Put your cricket token in `.env`: `SPORTMONKS_API_KEY=...`
2. Verify and discover what your plan allows:

```bash
python -m live.check_api                 # leagues / livescores / fixtures
python -m live.check_api --fixture 12345 # also probes ball-by-ball + odds
```

### Sportradar (optional second feed)

Use this for leagues Sportmonks may not include on your plan (e.g. TNPL, ECS Belgium).

1. Open **`Cricket_KP/.env`** (same file as Sportmonks).
2. Paste your key from [console.sportradar.com](https://console.sportradar.com/) onto:

```bash
SPORTRADAR_API_KEY=paste_your_key_here
SPORTRADAR_ACCESS_LEVEL=trial
```

3. Verify:

```bash
python -m live.check_sportradar
python -m live.check_sportradar --search "Tamil Nadu" --search Belgium --search ECS
```

Keep `SPORTRADAR_ACCESS_LEVEL=trial` for the 30-day trial; change to `production` only after you upgrade. The live dashboard still uses Sportmonks today; Sportradar is wired as a client + connectivity check so we can plug it into match listing next.

The data we request per fixture (the "includes") is configurable via
`SPORTMONKS_FIXTURE_INCLUDES` (default:
`localteam,visitorteam,venue,balls,batting,bowling,runs,scoreboards`).

## Odds (optional, plan-gated)

Cricket odds availability on Sportmonks depends on your plan. When enabled,
odds are captured as a **time series aligned to the KP timeline** (each change
becomes an `odds_snapshots` row carrying the active Ascendant/Moon lords), so
odds movement can be studied against astrology periods alongside live score.

Enable with `CAPTURE_ODDS=1`. The client tries strategies in order
(`ODDS_STRATEGY=v2_include,v3_inplay,v3_prematch`) and caches whichever returns
data; if none do, odds capture disables itself for that match and scoring
continues unaffected. Odds live on the v3 Odds API
(`SPORTMONKS_ODDS_BASE_URL`, default `https://api.sportmonks.com/v3/cricket`).

> The exact cricket odds field shape varies by plan; `normalize_odds` is
> defensive and `check_api --fixture <id>` prints a normalized sample so we can
> confirm the mapping against your real response.

## Always-on daemon

```bash
python run_daemon.py          # watches schedule, auto-captures matches (+odds if enabled)
```

Environment knobs: `POLL_INTERVAL` (s), `SCHEDULE_REFRESH` (s),
`SCHEDULE_DAYS_AHEAD`, `ALLOW_AI_COORDS` (set `0` to disable AI fallback),
`CAPTURE_ODDS` (set `1` to capture odds).

By default the daemon also starts a **nightly historical ingest** thread
(`NIGHTLY_BACKFILL=1`). At **1:00 AM IST** it pulls finished fixtures from the
last `NIGHTLY_LOOKBACK_DAYS` (default 3, through yesterday IST) into
`data/kp_cricket.db`. Fixtures that have no ball-by-ball twice, or error three
times in a row, are flagged `blocked` in `ingest_fixtures` and skipped on later
nights. Tests are blocked immediately. Unresolved coordinates still store balls
and are not auto-blocked.

```bash
python run_nightly_backfill.py              # one pass now
python run_nightly_backfill.py --status     # blocked / status counts
python run_nightly_backfill.py --reset-blocked 123456
python run_nightly_backfill.py --daemon     # standalone 1 AM IST loop
```

Optional Windows daily task (01:00 local / IST): `scripts/install_nightly_task.ps1`.
If both the daemon thread and the Windows task would run the same IST day, the
`data/nightly_backfill_last_ist.txt` marker keeps it to one pass.

## Data architecture (alignment)

Astrology data is keyed by precise UTC instants; cricket balls are keyed by
over/ball. The bridge is `ball_events.event_utc` plus the `ball_astro_state`
table, which denormalizes the active Ascendant and Moon lords (NL/SL/SSL/SSSL)
for every ball so the learning layer can mine rules without range joins.

`time_source` on each ball:
- `live_poll` - real wall-clock UTC captured when a ball first appears (used now).
- `estimated` - reserved for the future historical layer.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # add your SPORTMONKS_API_KEY
python -m db.export_schema    # create the database + schema.sql
```

## Live dashboard (Streamlit)

A separate **day-level** SQLite store (`data/live/live_YYYY-MM-DD.db`) powers the
live KP dashboard. It does not read from the historical `kp_cricket.db`. Finished
matches are ingested into the historical DB overnight from Sportmonks (see nightly
ingest above).

```bash
pip install -r requirements.txt
python run_live_dashboard.py
```

In the UI:

- Pick a **date** and **match** (fixtures from Sportmonks for that day).
- Chart anchor: **scheduled start** before play; **first corrected ball** once the
  match has started (burst-treated Sportmonks timestamp minus 35s).
- **Muhurta**, cusps, planetary table (scoring + comments), collapsed Asc timeline,
  Moon SSL + SSSL timelines.
- Moon **SSL Comment** shows live ball stats (`runs, dots, wickets`) per SSL window;
  other planetary comments are unchanged.

Enable **Auto-refresh 15s** for in-play matches.

## Viewing a match (read-only, connect anytime)

```bash
python view_match.py --list
python view_match.py --match 1                       # state as of now
python view_match.py --match 1 --as-of 2025-07-04T18:00:00   # historical snapshot
python view_match.py --match 1 --json                # machine-readable (for a web UI)
```

`live/match_state.get_match_state(session, match_id, as_of=...)` is the single
read entrypoint a future web UI/API would call.

## Testing the pipeline without a live match

```bash
python -m tests.test_autonomous   # scheduler -> first-ball chart -> capture -> anytime read
python -m tests.test_replay       # poller + alignment over synthetic balls
python -m tests.test_nightly_backfill  # 1 AM ingest skip/block ledger
```

`tests/test_autonomous.py` exercises the full daemon path with a fake client and
a clock anchored to the scheduled time: it asserts there is no chart before the
first ball, that the first ball auto-generates the anchored chart with
library-resolved coordinates, and that an earlier "as of" read still returns the
historical snapshot while a later read shows the full match.
