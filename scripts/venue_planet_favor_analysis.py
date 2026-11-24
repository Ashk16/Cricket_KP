"""Venue/time-window planet favor analysis from on-field SSL/NL periods.

Groups planets by which side they favor (local vs visitor) using ball-level
moon SSL and ascendant NL/SL, with data-driven RR/wicket thresholds.

Usage:
  python scripts/venue_planet_favor_analysis.py --venue headingley --days 15 --ist-hour 23
  python scripts/venue_planet_favor_analysis.py --match-ids 4273,67046,4276,4278,67047
  python scripts/venue_planet_favor_analysis.py --fixture 67047 --learn-from 4273,67046,4276
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import or_, select

from db.models import BallAstroState, BallEvent, Innings, Match, Team, Venue
from db.session import SessionLocal, init_db
from live.ball_timestamp_treatment import ball_alignment_utc
from timeutils import to_ist

PLANET = {
    "Su": "Sun", "Mo": "Moon", "Ma": "Mars", "Me": "Mercury", "Ju": "Jupiter",
    "Ve": "Venus", "Sa": "Saturn", "Ra": "Rahu", "Ke": "Ketu",
}


@dataclass
class PeriodSample:
    match_id: int
    label: str
    timeline: str  # moon_ssl | asc_nl | asc_sl
    planet: str
    batting_team: str
    bowling_team: str
    local_name: str
    visit_name: str
    balls: int
    runs: int
    wickets: int
    rr: float
    innings_rr: float
    favor_side: str  # local | visitor | neutral
    strength: str  # strong_bat | bat | bowl | strong_bowl | neutral
    winner: str


@dataclass
class PlanetAgg:
    local_bat: int = 0
    local_bowl: int = 0
    visit_bat: int = 0
    visit_bowl: int = 0
    neutral: int = 0
    balls: int = 0
    transitions: List[str] = field(default_factory=list)


def _batting_team_for_innings(match: Match, inn: Innings, local: Team, visit: Team) -> int:
    if match.toss_won_team_id and match.toss_elected:
        first = match.toss_won_team_id if str(match.toss_elected).lower().startswith("bat") else (
            visit.id if match.toss_won_team_id == local.id else local.id
        )
        return first if inn.innings_number == 1 else (visit.id if first == local.id else local.id)
    return local.id if inn.innings_number == 1 else visit.id


def _innings_rr(inn: Innings, balls: List[BallEvent]) -> float:
    inn_balls = [b for b in balls if b.innings_id == inn.id]
    if not inn_balls:
        return 7.0
    n = len(inn_balls)
    runs = sum(b.runs or 0 for b in inn_balls)
    return (runs / n) * 6.0 if n else 7.0


def _global_thresholds(samples: List[PeriodSample]) -> dict:
    rrs = [s.rr for s in samples if s.balls >= 3]
    if not rrs:
        return {"bat_rr": 8.0, "strong_bat_rr": 10.0, "bowl_rr": 6.0, "strong_bowl_rr": 4.5}
    rrs.sort()
    n = len(rrs)

    def pct(p: float) -> float:
        return rrs[int((n - 1) * p)]

    return {
        "bat_rr": pct(0.60),
        "strong_bat_rr": pct(0.80),
        "bowl_rr": pct(0.35),
        "strong_bowl_rr": pct(0.15),
    }


def _classify(
    runs: int,
    balls: int,
    wickets: int,
    innings_rr: float,
    thr: dict,
) -> Tuple[str, str]:
    if balls == 0:
        return "neutral", "neutral"
    rr = (runs / balls) * 6.0
    rel = rr / innings_rr if innings_rr > 0 else 1.0

    if wickets >= 2 or (wickets >= 1 and rr <= thr["strong_bowl_rr"]):
        return "bowling", "strong_bowl"
    if wickets >= 1 and (rr < thr["bowl_rr"] or rel < 0.72):
        return "bowling", "bowl"
    if rr >= max(thr["strong_bat_rr"], innings_rr * 1.12) and wickets == 0:
        return "batting", "strong_bat"
    if rr >= max(thr["bat_rr"], innings_rr * 0.92) and wickets <= 1:
        return "batting", "bat"
    if rr < thr["bowl_rr"] or rel < 0.68:
        return "bowling", "bowl"
    return "neutral", "neutral"


def _group_balls(
    balls: List[BallEvent],
    states: Dict[int, BallAstroState],
    field: str,
) -> List[Tuple[str, List[BallEvent]]]:
    """Contiguous runs grouped by planet field on astro state."""
    ordered = sorted(
        [b for b in balls if states.get(b.id) and getattr(states[b.id], field, None)],
        key=lambda b: (b.ball_seq or 0),
    )
    if not ordered:
        return []

    groups: List[Tuple[str, List[BallEvent]]] = []
    cur_p = getattr(states[ordered[0].id], field)
    cur_balls = [ordered[0]]
    for b in ordered[1:]:
        p = getattr(states[b.id], field)
        if p == cur_p:
            cur_balls.append(b)
        else:
            groups.append((cur_p, cur_balls))
            cur_p, cur_balls = p, [b]
    groups.append((cur_p, cur_balls))
    return groups


def _analyze_match(session, match_id: int, thr: dict) -> List[PeriodSample]:
    m = session.get(Match, match_id)
    if not m:
        return []
    local = session.get(Team, m.localteam_id)
    visit = session.get(Team, m.visitorteam_id)
    winner = session.get(Team, m.winner_team_id)
    if not local or not visit:
        return []

    balls = list(
        session.scalars(
            select(BallEvent)
            .where(BallEvent.match_id == match_id, BallEvent.event_utc_corrected.is_not(None))
            .order_by(BallEvent.ball_seq)
        ).all()
    )
    if not balls:
        return []

    states = {
        s.ball_id: s
        for s in session.scalars(
            select(BallAstroState).where(
                BallAstroState.ball_id.in_([b.id for b in balls])
            )
        ).all()
    }
    inn_map = {i.id: i for i in session.scalars(select(Innings).where(Innings.match_id == match_id)).all()}
    inn_rr = {i.id: _innings_rr(i, balls) for i in inn_map.values()}

    date_s = (m.starting_at_ist or m.first_ball_ist or datetime.utcnow()).strftime("%Y-%m-%d")
    label = f"{date_s} {local.name} vs {visit.name}"

    out: List[PeriodSample] = []
    for timeline, field in (("moon_ssl", "moon_ssl"), ("asc_nl", "asc_nl"), ("asc_sl", "asc_sl")):
        for planet, chunk in _group_balls(balls, states, field):
            if not planet or len(chunk) < 1:
                continue
            by_inn: Dict[int, List[BallEvent]] = defaultdict(list)
            for b in chunk:
                if b.innings_id:
                    by_inn[b.innings_id].append(b)

            for inn_id, inn_balls in by_inn.items():
                inn = inn_map.get(inn_id)
                if not inn:
                    continue
                bat_id = _batting_team_for_innings(m, inn, local, visit)
                bowl_id = visit.id if bat_id == local.id else local.id
                bat_name = local.name if bat_id == local.id else visit.name
                bowl_name = visit.name if bat_id == local.id else local.name
                n = len(inn_balls)
                runs = sum(b.runs or 0 for b in inn_balls)
                wkts = sum(1 for b in inn_balls if b.is_wicket)
                irr = inn_rr.get(inn_id, 7.0)
                kind, strength = _classify(runs, n, wkts, irr, thr)

                if kind == "batting":
                    favor_id = bat_id
                elif kind == "bowling":
                    favor_id = bowl_id
                else:
                    favor_id = None

                if favor_id == local.id:
                    favor_side = "local"
                elif favor_id == visit.id:
                    favor_side = "visitor"
                else:
                    favor_side = "neutral"

                out.append(
                    PeriodSample(
                        match_id=match_id,
                        label=label,
                        timeline=timeline,
                        planet=planet,
                        batting_team=bat_name,
                        bowling_team=bowl_name,
                        local_name=local.name,
                        visit_name=visit.name,
                        balls=n,
                        runs=runs,
                        wickets=wkts,
                        rr=(runs / n) * 6 if n else 0,
                        innings_rr=irr,
                        favor_side=favor_side,
                        strength=strength,
                        winner=winner.name if winner else "?",
                    )
                )
    return out


def _find_venue_matches(
    session,
    venue_pat: str,
    days: int,
    ist_hour: int,
    ist_minute: int = 0,
) -> List[int]:
    venues = session.scalars(
        select(Venue).where(
            or_(
                Venue.name.ilike(f"%{venue_pat}%"),
                Venue.city.ilike(f"%{venue_pat}%"),
            )
        )
    ).all()
    if not venues:
        return []
    vids = [v.id for v in venues]
    cutoff = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    ids = []
    for m in session.scalars(
        select(Match)
        .where(Match.venue_id.in_(vids), Match.starting_at_ist >= cutoff)
        .order_by(Match.starting_at_ist)
    ).all():
        ist = m.starting_at_ist
        if ist and ist.hour == ist_hour and ist.minute == ist_minute:
            ids.append(m.id)
    return ids


def _aggregate(samples: List[PeriodSample], timeline: str, local_name: str, visit_name: str = "") -> Dict[str, PlanetAgg]:
    agg: Dict[str, PlanetAgg] = defaultdict(PlanetAgg)
    by_match_planet: Dict[Tuple[int, str], List[PeriodSample]] = defaultdict(list)
    for s in samples:
        if s.timeline != timeline:
            continue
        by_match_planet[(s.match_id, s.planet)].append(s)

    for (mid, planet), chunks in by_match_planet.items():
        a = agg[planet]
        for s in chunks:
            a.balls += s.balls
            if s.favor_side == "local":
                if s.strength in ("bat", "strong_bat"):
                    a.local_bat += s.balls
                elif s.strength in ("bowl", "strong_bowl"):
                    a.local_bowl += s.balls
                else:
                    a.neutral += s.balls
            elif s.favor_side == "visitor":
                if s.strength in ("bat", "strong_bat"):
                    a.visit_bat += s.balls
                elif s.strength in ("bowl", "strong_bowl"):
                    a.visit_bowl += s.balls
                else:
                    a.neutral += s.balls
            else:
                a.neutral += s.balls

        # transition note: first chunk in match for this planet
        first = chunks[0]
        last = chunks[-1]
        win = first.winner
        fav = "local" if (first.local_name == win and first.favor_side == "local") or (
            first.visit_name == win and first.favor_side == "visitor"
        ) else "other"
        if first.favor_side != "neutral":
            a.transitions.append(
                f"{first.label.split(' ',1)[1]}: {PLANET.get(planet,planet)}→{first.favor_side} ({win} won)"
            )
    return agg


def _planet_side(agg: PlanetAgg, local_label: str, visit_label: str) -> str:
    local_score = agg.local_bat + agg.local_bowl * 1.1
    visit_score = agg.visit_bat + agg.visit_bowl * 1.1
    total = local_score + visit_score + agg.neutral
    if total < 6:
        return "neutral"
    if local_score > visit_score * 1.25:
        return f"favors {local_label}"
    if visit_score > local_score * 1.25:
        return f"favors {visit_label}"
    return "neutral / mixed"


def _aggregate_by_winner(samples: List[PeriodSample], timeline: str) -> Dict[str, dict]:
    """Planet -> balls favoring winner vs loser (cross-match normalized)."""
    out: Dict[str, dict] = defaultdict(lambda: {"winner": 0, "loser": 0, "neutral": 0})
    for s in samples:
        if s.timeline != timeline or s.winner == "?":
            continue
        win_is_local = s.winner == s.local_name
        if s.favor_side == "neutral":
            out[s.planet]["neutral"] += s.balls
        elif (s.favor_side == "local" and win_is_local) or (s.favor_side == "visitor" and not win_is_local):
            out[s.planet]["winner"] += s.balls
        else:
            out[s.planet]["loser"] += s.balls
    return out


def _print_winner_groups(agg: Dict[str, dict], title: str) -> None:
    win_p, lose_p, neu_p = [], [], []
    for p in sorted(agg, key=lambda x: PLANET.get(x, x)):
        name = PLANET.get(p, p)
        w, l, n = agg[p]["winner"], agg[p]["loser"], agg[p]["neutral"]
        total = w + l
        if total < 6:
            neu_p.append(name)
        elif w > l * 1.3:
            win_p.append(f"{name} ({w}b)")
        elif l > w * 1.3:
            lose_p.append(f"{name} ({l}b)")
        else:
            neu_p.append(f"{name} ({w}/{l})")
    print(f"\n{title}")
    print(f"  Favors WINNER: {', '.join(win_p) or '-'}")
    print(f"  Favors LOSER:  {', '.join(lose_p) or '-'}")
    print(f"  Neutral:       {', '.join(neu_p) or '-'}")


def _print_groups(agg: Dict[str, PlanetAgg], local: str, visit: str, title: str) -> None:
    local_p, visit_p, neutral_p = [], [], []
    for p in sorted(agg, key=lambda x: PLANET.get(x, x)):
        side = _planet_side(agg[p], local, visit)
        name = PLANET.get(p, p)
        entry = f"{name} ({agg[p].balls}b)"
        if side.startswith("favors " + local):
            local_p.append(entry)
        elif side.startswith("favors " + visit):
            visit_p.append(entry)
        else:
            neutral_p.append(entry)

    print(f"\n{title}")
    print(f"  {local}: {', '.join(local_p) or '-'}")
    print(f"  {visit}: {', '.join(visit_p) or '-'}")
    print(f"  Neutral: {', '.join(neutral_p) or '-'}")


def _print_match_highlights(samples: List[PeriodSample]) -> None:
    by_match: Dict[int, List[PeriodSample]] = defaultdict(list)
    for s in samples:
        by_match[s.match_id].append(s)

    print("\n--- Match highlights (planet transitions) ---")
    for mid, ss in by_match.items():
        label = ss[0].label
        win = ss[0].winner
        print(f"\n{label} | winner: {win}")
        for timeline in ("moon_ssl", "asc_nl", "asc_sl"):
            seen = set()
            for s in sorted(ss, key=lambda x: (x.timeline, x.planet)):
                if s.timeline != timeline or s.balls < 3:
                    continue
                key = (s.planet, s.favor_side)
                if key in seen:
                    continue
                seen.add(key)
                if s.favor_side == "neutral":
                    continue
                fav_team = s.local_name if s.favor_side == "local" else s.visit_name
                print(
                    f"  {timeline} {PLANET.get(s.planet,s.planet):8} "
                    f"{s.balls}b RR{s.rr:.1f} w{s.wickets} -> {fav_team} ({s.strength})"
                )


def _analyze_day_fixture(fixture_id: int, thr: dict) -> List[PeriodSample]:
    from live.day_session import day_session
    from live.day_manager import (
        ensure_fixture_in_day_db,
        fetch_fixtures_for_date,
        match_context_for_analysis,
        sync_balls,
    )
    from live.astro_writer import write_match_chart
    from live.aligner import align_match
    from live.sportmonks_client import SportmonksClient

    client = SportmonksClient()
    day = date.today()
    fixture = next((f for f in fetch_fixtures_for_date(client, day) if f["id"] == fixture_id), None)
    if not fixture:
        return []

    with day_session(day) as session:
        m = ensure_fixture_in_day_db(session, client, fixture)
        sync_balls(session, client, m, fixture)
        ctx = match_context_for_analysis(session, m, fixture)
        write_match_chart(session, m, duration_hours=ctx["duration_hours"])
        align_match(session, m.id, rebuild=True)
        samples = _analyze_match(session, m.id, thr)
        session.commit()
        return samples


def _preview_fixture(fixture_id: int, learn_samples: List[PeriodSample], thr: dict) -> None:
    samples = _analyze_day_fixture(fixture_id, thr)
    if not samples:
        print(f"\nFixture {fixture_id}: no ball/astro data yet.")
        return
    local, visit = samples[0].local_name, samples[0].visit_name
    print(f"\n=== TONIGHT: {local} vs {visit} (fixture {fixture_id}) ===")
    _print_match_highlights(samples)

    combined = learn_samples + samples
    _print_groups(_aggregate(combined, "moon_ssl", local, visit), local, visit, "Moon SSL (learn + tonight)")
    _print_groups(_aggregate(combined, "asc_nl", local, visit), local, visit, "Asc NL (learn + tonight)")

    print("\n  Script planets (learn-set Moon SSL):")
    for code, pname in (("Ju", "Jupiter"), ("Sa", "Saturn"), ("Me", "Mercury")):
        chunks = [s for s in learn_samples if s.planet == code and s.timeline == "moon_ssl"]
        if not chunks:
            continue
        loc = sum(s.balls for s in chunks if s.favor_side == "local")
        vis = sum(s.balls for s in chunks if s.favor_side == "visitor")
        wins = {s.winner for s in chunks}
        print(f"    {pname}: local {loc}b | visitor {vis}b | winners seen: {', '.join(wins)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Planet favor analysis by venue/time")
    parser.add_argument("--venue", default="headingley", help="Venue name/city substring")
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--ist-hour", type=int, default=23)
    parser.add_argument("--ist-minute", type=int, default=0)
    parser.add_argument("--match-ids", default="", help="Comma-separated historical match ids")
    parser.add_argument("--day-fixtures", default="", help="Comma Sportmonks fixture ids (today day DB)")
    parser.add_argument("--learn-from", default="", help="Historical match ids for learn-set")
    parser.add_argument("--fixture", type=int, default=0, help="Tonight fixture id for preview")
    args = parser.parse_args()

    init_db()
    day_fixture_ids = [int(x) for x in args.day_fixtures.split(",") if x.strip()]
    learn_hist = [int(x) for x in args.learn_from.split(",") if x.strip()] if args.learn_from else [4273, 4276]

    with SessionLocal() as session:
        match_ids: List[int] = []
        if args.match_ids:
            match_ids = [int(x) for x in args.match_ids.split(",") if x.strip()]
        else:
            match_ids = _find_venue_matches(
                session, args.venue, args.days, args.ist_hour, args.ist_minute
            )

        probe: List[PeriodSample] = []
        for mid in learn_hist + match_ids:
            probe.extend(_analyze_match(session, mid, {"bat_rr": 8, "strong_bat_rr": 10, "bowl_rr": 6, "strong_bowl_rr": 4.5}))
        thr = _global_thresholds(probe)

        all_learn: List[PeriodSample] = []
        for mid in learn_hist:
            all_learn.extend(_analyze_match(session, mid, thr))

        for fid in day_fixture_ids:
            all_learn.extend(_analyze_day_fixture(fid, thr))

        all_venue: List[PeriodSample] = []
        for mid in match_ids:
            all_venue.extend(_analyze_match(session, mid, thr))

        print(f"Thresholds: bat>={thr['bat_rr']:.1f} strong>={thr['strong_bat_rr']:.1f} "
              f"bowl<={thr['bowl_rr']:.1f}")

        if all_venue:
            local, visit = all_venue[0].local_name, all_venue[0].visit_name
            print(f"\n=== {args.venue.title()} {args.ist_hour:02d}:{args.ist_minute:02d} IST "
                  f"({args.days}d) — {len(match_ids)} match(es) ===")
            _print_match_highlights(all_venue)
            _print_groups(_aggregate(all_venue, "moon_ssl", local, visit), local, visit, "Moon SSL")
            _print_groups(_aggregate(all_venue, "asc_nl", local, visit), local, visit, "Asc NL")
            _print_groups(_aggregate(all_venue, "asc_sl", local, visit), local, visit, "Asc SL")
        else:
            print("No historical venue matches in window.")

        print("\n=== Learn-set (script matches) ===")
        _print_match_highlights(all_learn)
        _print_winner_groups(_aggregate_by_winner(all_learn, "moon_ssl"), "Moon SSL (winner vs loser)")
        _print_winner_groups(_aggregate_by_winner(all_learn, "asc_nl"), "Asc NL (winner vs loser)")
        if all_venue:
            local, visit = all_venue[0].local_name, all_venue[0].visit_name
            print(f"\n=== Tonight watch: {local} vs {visit} ===")
            print("From learn-set script (3 matches):")
            print("  Moon Jupiter SSL -> underdog/winner lift (SL, Ban W)")
            print("  Moon Saturn/Mercury SSL -> often bowling squeeze on favourite")
            print("  Asc Jupiter NL -> batting collapse risk (Ban W, Ind W)")
            _print_groups(_aggregate(all_venue, "moon_ssl", local, visit), local, visit, "Headingley prior Moon SSL")

        if args.fixture:
            _preview_fixture(args.fixture, all_learn, thr)


if __name__ == "__main__":
    main()
