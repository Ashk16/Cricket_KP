"""Player performance: Mercury Moon NL vs non-Mercury (T20, last 2 years).

Batting and bowling metrics split by match-start Moon NL at first ball.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import func, or_, select

load_dotenv()

from db.models import BallAstroState, BallEvent, Innings, Match, Player
from db.session import SessionLocal, init_db

# Sportmonks player ids (resolved via team squad API)
PLAYERS = {
    "Scotland W": {
        "Kathryn Bryce": 7812,
        "Sarah Bryce": 19212,  # user wrote "Bruce"; Sportmonks = Bryce
        "Katherine Fraser": 23319,
        "Kirstie Gordon": 500,  # user wrote Kristie
    },
    "West Indies W": {
        "Hayley Matthews": 549,
        "Deandra Dottin": 544,
        "Shemaine Campbelle": 541,
    },
}


@dataclass
class BatBucket:
    matches: Set[int] = field(default_factory=set)
    innings: Set[Tuple[int, int]] = field(default_factory=set)  # (match_id, innings_id)
    balls: int = 0
    runs: int = 0
    fours: int = 0
    sixes: int = 0
    dots: int = 0
    dismissals: int = 0

    @property
    def sr(self) -> float:
        return 100.0 * self.runs / self.balls if self.balls else 0.0

    @property
    def avg(self) -> Optional[float]:
        return self.runs / self.dismissals if self.dismissals else None

    @property
    def boundary_pct(self) -> float:
        return 100.0 * (self.fours + self.sixes) / self.balls if self.balls else 0.0

    @property
    def dot_pct(self) -> float:
        return 100.0 * self.dots / self.balls if self.balls else 0.0


@dataclass
class BowlBucket:
    matches: Set[int] = field(default_factory=set)
    innings: Set[Tuple[int, int]] = field(default_factory=set)
    balls: int = 0
    runs_conceded: int = 0
    wickets: int = 0
    dots: int = 0
    boundaries: int = 0

    @property
    def economy(self) -> float:
        return 6.0 * self.runs_conceded / self.balls if self.balls else 0.0

    @property
    def average(self) -> Optional[float]:
        return self.runs_conceded / self.wickets if self.wickets else None

    @property
    def strike_rate(self) -> Optional[float]:
        return self.balls / self.wickets if self.wickets else None

    @property
    def dot_pct(self) -> float:
        return 100.0 * self.dots / self.balls if self.balls else 0.0


def _is_t20(fmt: Optional[str]) -> bool:
    return bool(fmt and "T20" in fmt.upper())


def _match_moon_nl_cache(session, match_ids: Iterable[int]) -> Dict[int, Optional[str]]:
    cache: Dict[int, Optional[str]] = {}
    for mid in match_ids:
        ball = session.scalar(
            select(BallEvent)
            .where(BallEvent.match_id == mid)
            .order_by(BallEvent.ball_seq)
            .limit(1)
        )
        if ball is None:
            cache[mid] = None
            continue
        st = session.scalar(select(BallAstroState).where(BallAstroState.ball_id == ball.id))
        cache[mid] = st.moon_nl if st else None
    return cache


def _player_db_id(session, sportmonks_id: int) -> Optional[int]:
    return session.scalar(select(Player.id).where(Player.sportmonks_id == sportmonks_id))


def _collect_player_stats(session, player_id: int, cutoff: datetime) -> Tuple[Dict[str, BatBucket], Dict[str, BowlBucket]]:
    balls = session.execute(
        select(
            BallEvent.match_id,
            BallEvent.innings_id,
            BallEvent.batsman_id,
            BallEvent.bowler_id,
            BallEvent.runs,
            BallEvent.extras,
            BallEvent.is_four,
            BallEvent.is_six,
            BallEvent.is_wicket,
            Match.format,
            Match.first_ball_utc,
        )
        .join(Match, Match.id == BallEvent.match_id)
        .where(
            Match.first_ball_utc.is_not(None),
            Match.first_ball_utc >= cutoff,
            or_(BallEvent.batsman_id == player_id, BallEvent.bowler_id == player_id),
        )
    ).all()

    match_ids = {row.match_id for row in balls if _is_t20(row.format)}
    moon_cache = _match_moon_nl_cache(session, match_ids)

    bat: Dict[str, BatBucket] = {"Me": BatBucket(), "non-Me": BatBucket()}
    bowl: Dict[str, BowlBucket] = {"Me": BowlBucket(), "non-Me": BowlBucket()}

    for row in balls:
        if not _is_t20(row.format):
            continue
        nl = moon_cache.get(row.match_id)
        bucket_key = "Me" if nl == "Me" else "non-Me"

        if row.batsman_id == player_id:
            b = bat[bucket_key]
            b.matches.add(row.match_id)
            if row.innings_id is not None:
                b.innings.add((row.match_id, row.innings_id))
            b.balls += 1
            r = row.runs or 0
            b.runs += r
            if row.is_four:
                b.fours += 1
            if row.is_six:
                b.sixes += 1
            if r == 0:
                b.dots += 1
            if row.is_wicket:
                b.dismissals += 1

        if row.bowler_id == player_id:
            bw = bowl[bucket_key]
            bw.matches.add(row.match_id)
            if row.innings_id is not None:
                bw.innings.add((row.match_id, row.innings_id))
            bw.balls += 1
            conceded = (row.runs or 0) + (row.extras or 0)
            bw.runs_conceded += conceded
            if row.is_wicket:
                bw.wickets += 1
            if conceded == 0:
                bw.dots += 1
            if row.is_four or row.is_six:
                bw.boundaries += 1

    return bat, bowl


def _fmt_opt(v: Optional[float], suffix: str = "") -> str:
    if v is None:
        return "—"
    return f"{v:.1f}{suffix}"


def _league_breakdown(session, player_id: int, cutoff: datetime) -> None:
    """Show which competitions are in the dataset for this player."""
    rows = session.execute(
        select(Match.id, Match.league, Match.format)
        .join(BallEvent, BallEvent.match_id == Match.id)
        .where(
            Match.first_ball_utc.is_not(None),
            Match.first_ball_utc >= cutoff,
            or_(BallEvent.batsman_id == player_id, BallEvent.bowler_id == player_id),
        )
        .group_by(Match.id, Match.league, Match.format)
    ).all()
    moon_cache = _match_moon_nl_cache(session, {r.id for r in rows if _is_t20(r.format)})
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "Me": 0})
    for mid, league, fmt in rows:
        if not _is_t20(fmt):
            continue
        key = f"{fmt} | {league or 'Unknown'}"
        counts[key]["total"] += 1
        if moon_cache.get(mid) == "Me":
            counts[key]["Me"] += 1
    if not counts:
        print("    (no T20/T20I matches in dataset)")
        return
    print("    Competitions in dataset:")
    for key, c in sorted(counts.items(), key=lambda x: -x[1]["total"]):
        me_note = f", {c['Me']} Mercury NL" if c["Me"] else ""
        print(f"      {c['total']:2} matches{me_note} — {key}")


def _print_batting(name: str, bat: Dict[str, BatBucket]) -> None:
    print(f"\n  BATTING — {name}")
    hdr = (
        f"    {'Moon NL':<10} {'Matches':>7} {'Innings':>8} {'Runs':>5} {'Balls':>6} "
        f"{'SR':>7} {'Avg':>7} {'4s':>4} {'6s':>4} {'Bnd%':>6} {'Dot%':>6}"
    )
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))
    for key, label in (("Me", "Mercury"), ("non-Me", "Non-Mercury")):
        b = bat[key]
        print(
            f"    {label:<10} {len(b.matches):7} {len(b.innings):8} {b.runs:5} {b.balls:6} "
            f"{b.sr:6.1f} {_fmt_opt(b.avg):>7} {b.fours:4} {b.sixes:4} {b.boundary_pct:5.1f}% {b.dot_pct:5.1f}%"
        )
    me, other = bat["Me"], bat["non-Me"]
    if me.balls and other.balls:
        delta_sr = me.sr - other.sr
        print(f"    Delta SR (Mercury - Non): {delta_sr:+.1f}")


def _print_bowling(name: str, bowl: Dict[str, BowlBucket]) -> None:
    if not any(bowl[k].balls for k in bowl):
        return
    print(f"\n  BOWLING — {name}")
    hdr = (
        f"    {'Moon NL':<10} {'Matches':>7} {'Innings':>8} {'Overs':>6} {'Runs':>5} "
        f"{'Wkts':>5} {'Econ':>6} {'Avg':>7} {'BowlSR':>7} {'Dot%':>6} {'Bnd':>5}"
    )
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))
    for key, label in (("Me", "Mercury"), ("non-Me", "Non-Mercury")):
        b = bowl[key]
        overs = b.balls / 6.0
        print(
            f"    {label:<10} {len(b.matches):7} {len(b.innings):8} {overs:6.1f} {b.runs_conceded:5} "
            f"{b.wickets:5} {b.economy:6.2f} {_fmt_opt(b.average):>7} {_fmt_opt(b.strike_rate):>7} "
            f"{b.dot_pct:5.1f}% {b.boundaries:5}"
        )
    me, other = bowl["Me"], bowl["non-Me"]
    if me.balls and other.balls:
        print(f"    Delta Economy (Mercury - Non): {me.economy - other.economy:+.2f}")


def _summary_comparison(all_stats: Dict[str, Tuple[Dict[str, BatBucket], Dict[str, BowlBucket]]]) -> None:
    print("\n" + "=" * 72)
    print("GROUP SUMMARY — Mercury vs Non-Mercury (T20, last 2 years)")
    print("=" * 72)

    for group in PLAYERS:
        print(f"\n{group}")
        for metric, fn in (
            ("Bat SR", lambda b: b.sr),
            ("Bat Avg", lambda b: b.avg),
            ("Bowl Econ", lambda bw: bw.economy if bw.balls else None),
            ("Bowl Avg", lambda bw: bw.average),
        ):
            me_vals, non_vals = [], []
            for name in PLAYERS[group]:
                bat, bowl = all_stats[name]
                if "Bat" in metric:
                    if bat["Me"].balls:
                        me_vals.append(fn(bat["Me"]))
                    if bat["non-Me"].balls:
                        non_vals.append(fn(bat["non-Me"]))
                else:
                    if bowl["Me"].balls:
                        me_vals.append(fn(bowl["Me"]))
                    if bowl["non-Me"].balls:
                        non_vals.append(fn(bowl["non-Me"]))
            me_vals = [v for v in me_vals if v is not None]
            non_vals = [v for v in non_vals if v is not None]
            if me_vals or non_vals:
                me_m = sum(me_vals) / len(me_vals) if me_vals else None
                non_m = sum(non_vals) / len(non_vals) if non_vals else None
                me_s = f"{me_m:.1f}" if me_m is not None else "—"
                non_s = f"{non_m:.1f}" if non_m is not None else "—"
                print(f"  {metric:<12} Mercury avg: {me_s:<8} Non-Mercury avg: {non_s}")


def main() -> None:
    init_db()
    cutoff = datetime.utcnow() - timedelta(days=365 * 2)
    today = date.today()

    print("Player performance under Mercury Moon NL vs Non-Mercury")
    print("Scope: T20 + T20I (format), all competitions present in DB | Since {0}".format(cutoff.date()))
    print("Note: domestic/league coverage depends on Sportmonks backfill (e.g. T20 Blast Women's yes; WPL not in API)")
    print("Moon NL: first-ball match-start significator | Mercury = Me")
    print()
    print("METRICS")
    print("  Batting: Matches, Innings, Runs, Balls, SR, Avg, 4s/6s, Boundary%, Dot%")
    print("  Bowling: Matches, Innings, Overs, Runs conceded, Wkts, Economy, Avg, Bowl SR, Dot%, Boundaries conceded")

    all_stats: Dict[str, Tuple[Dict[str, BatBucket], Dict[str, BowlBucket]]] = {}

    with SessionLocal() as session:
        for group, roster in PLAYERS.items():
            print("\n" + "=" * 72)
            print(group)
            print("=" * 72)
            for display_name, sm_id in roster.items():
                pid = _player_db_id(session, sm_id)
                if pid is None:
                    print(f"\n{display_name}: not in DB (sportmonks {sm_id})")
                    continue
                bat, bowl = _collect_player_stats(session, pid, cutoff)
                all_stats[display_name] = (bat, bowl)
                print(f"\n{display_name}")
                _league_breakdown(session, pid, cutoff)
                _print_batting(display_name, bat)
                _print_bowling(display_name, bowl)

    _summary_comparison(all_stats)
    print(f"\nAnalysis run: {today}")


if __name__ == "__main__":
    main()
