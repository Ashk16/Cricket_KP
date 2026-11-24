"""Win/loss by Moon NL for West Indies W and Scotland W (historical DB)."""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import or_, select

load_dotenv()

from db.models import BallAstroState, BallEvent, Match, Team, Team
from db.session import SessionLocal, init_db

TEAMS = {
    "West Indies W": 118,
    "Scotland W": 117,
}

PLANET_LABELS = {
    "Su": "Sun",
    "Mo": "Moon",
    "Ma": "Mars",
    "Me": "Mercury",
    "Ju": "Jupiter",
    "Ve": "Venus",
    "Sa": "Saturn",
    "Ra": "Rahu",
    "Ke": "Ketu",
}


@dataclass
class Rec:
    moon_nl: str
    won: bool
    match_date: date


def _first_ball_moon_nl(session, match_id: int) -> str | None:
    ball = session.scalar(
        select(BallEvent)
        .where(BallEvent.match_id == match_id)
        .order_by(BallEvent.ball_seq)
        .limit(1)
    )
    if ball is None:
        return None
    st = session.scalar(select(BallAstroState).where(BallAstroState.ball_id == ball.id))
    return st.moon_nl if st else None


def _collect_records(session, team_id: int) -> list[Rec]:
    matches = session.scalars(
        select(Match)
        .where(
            Match.winner_team_id.is_not(None),
            Match.first_ball_utc.is_not(None),
            or_(Match.localteam_id == team_id, Match.visitorteam_id == team_id),
        )
        .order_by(Match.starting_at_utc)
    ).all()

    out: list[Rec] = []
    for m in matches:
        moon_nl = _first_ball_moon_nl(session, m.id)
        if not moon_nl:
            continue
        won = m.winner_team_id == team_id
        d = m.first_ball_utc.date() if m.first_ball_utc else m.starting_at_utc.date()
        out.append(Rec(moon_nl=moon_nl, won=won, match_date=d))
    return out


def _aggregate(recs: list[Rec]) -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"w": 0, "l": 0})
    for r in recs:
        key = r.moon_nl
        agg[key]["w" if r.won else "l"] += 1
    return agg


def _fmt_table(title: str, agg: dict[str, dict[str, int]]) -> str:
    lines = [title, ""]
    hdr = f"{'Moon NL':<12} {'Wins':>5} {'Losses':>7} {'Total':>6} {'Win %':>7}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    rows = []
    for nl, c in agg.items():
        w, l = c["w"], c["l"]
        t = w + l
        pct = 100.0 * w / t if t else 0.0
        label = f"{nl} ({PLANET_LABELS.get(nl, nl)})"
        rows.append((nl, label, w, l, t, pct))
    rows.sort(key=lambda x: (-(x[4]), x[0]))
    for _, label, w, l, t, pct in rows:
        lines.append(f"{label:<12} {w:5} {l:7} {t:6} {pct:6.1f}%")
    tw = sum(c["w"] for c in agg.values())
    tl = sum(c["l"] for c in agg.values())
    tt = tw + tl
    lines.append("-" * len(hdr))
    lines.append(f"{'TOTAL':<12} {tw:5} {tl:7} {tt:6} {100*tw/tt if tt else 0:6.1f}%")
    return "\n".join(lines)


def _mercury_summary(team: str, all_recs: list[Rec], recent_recs: list[Rec]) -> str:
    def me_stats(recs: list[Rec]) -> tuple[int, int, float]:
        me = [r for r in recs if r.moon_nl == "Me"]
        w = sum(1 for r in me if r.won)
        l = sum(1 for r in me if not r.won)
        t = w + l
        return w, l, (100.0 * w / t if t else 0.0)

    aw, al, ap = me_stats(all_recs)
    rw, rl, rp = me_stats(recent_recs)
    non_me_all = [r for r in all_recs if r.moon_nl != "Me"]
    nw = sum(1 for r in non_me_all if r.won)
    nl = sum(1 for r in non_me_all if not r.won)
    nt = nw + nl
    np = 100.0 * nw / nt if nt else 0.0
    return (
        f"{team}: Mercury NL — all-time {aw}W/{al}L ({ap:.1f}%, n={aw+al}); "
        f"last 2y {rw}W/{rl}L ({rp:.1f}%, n={rw+rl}); "
        f"non-Mercury all-time {np:.1f}% (n={nt})"
    )


def main() -> None:
    init_db()
    cutoff = date.today() - timedelta(days=365 * 2)

    with SessionLocal() as session:
        all_data: dict[str, list[Rec]] = {}
        recent_data: dict[str, list[Rec]] = {}
        for name, tid in TEAMS.items():
            recs = _collect_records(session, tid)
            all_data[name] = recs
            recent_data[name] = [r for r in recs if r.match_date >= cutoff]

    print(f"Analysis date: {date.today()} | Last-2-years cutoff: {cutoff}")
    print()

    for name in TEAMS:
        print(_fmt_table(f"=== {name} — ALL TIME (n={len(all_data[name])}) ===", _aggregate(all_data[name])))
        print()
        print(
            _fmt_table(
                f"=== {name} — LAST 2 YEARS (n={len(recent_data[name])}) ===",
                _aggregate(recent_data[name]),
            )
        )
        print()

    print("=== MERCURY NL (Me) — SPECIAL COMPARISON ===")
    print()
    hdr = f"{'Team':<16} {'Period':<12} {'Wins':>5} {'Losses':>7} {'Total':>6} {'Win %':>7}"
    print(hdr)
    print("-" * len(hdr))
    for name in TEAMS:
        for period, recs in (("All time", all_data[name]), ("Last 2 years", recent_data[name])):
            me = [r for r in recs if r.moon_nl == "Me"]
            w = sum(1 for r in me if r.won)
            l = sum(1 for r in me if not r.won)
            t = w + l
            pct = 100.0 * w / t if t else 0.0
            print(f"{name:<16} {period:<12} {w:5} {l:7} {t:6} {pct:6.1f}%")
    print()
    for name in TEAMS:
        print(_mercury_summary(name, all_data[name], recent_data[name]))


def _opponent_name(session, match: Match, focus_id: int) -> str:
    opp_id = match.visitorteam_id if match.localteam_id == focus_id else match.localteam_id
    t = session.get(Team, opp_id)
    return t.name if t else str(opp_id)


def detail_opponents() -> None:
    """List WI-W Mercury NL wins (last 2y) and Scotland W losses."""
    init_db()
    cutoff = date.today() - timedelta(days=365 * 2)
    wi_id, sco_id = TEAMS["West Indies W"], TEAMS["Scotland W"]

    with SessionLocal() as session:
        print(f"=== West Indies W WINS — Last 2 years, Mercury Moon NL (since {cutoff}) ===\n")
        wi_matches = session.scalars(
            select(Match)
            .where(
                Match.winner_team_id.is_not(None),
                Match.first_ball_utc.is_not(None),
                or_(Match.localteam_id == wi_id, Match.visitorteam_id == wi_id),
            )
            .order_by(Match.starting_at_utc)
        ).all()
        wins_me = []
        for m in wi_matches:
            if (m.first_ball_utc.date() if m.first_ball_utc else m.starting_at_utc.date()) < cutoff:
                continue
            if _first_ball_moon_nl(session, m.id) != "Me":
                continue
            if m.winner_team_id == wi_id:
                wins_me.append(m)

        if not wins_me:
            print("(no wins in Mercury NL in last 2 years)\n")
        else:
            print(f"{'Date':<12} {'Opponent':<30} {'Format':<6} {'Side':<6} {'League':<35}")
            print("-" * 95)
            for m in wins_me:
                d = (m.first_ball_ist or m.starting_at_ist).strftime("%Y-%m-%d")
                side = "Home" if m.localteam_id == wi_id else "Away"
                print(
                    f"{d:<12} {_opponent_name(session, m, wi_id):<30} "
                    f"{(m.format or '-'):<6} {side:<6} {(m.league or '-'):<35}"
                )

        print(f"\n=== Scotland W LOSSES — All time (n with Moon NL) ===\n")
        sco_matches = session.scalars(
            select(Match)
            .where(
                Match.winner_team_id.is_not(None),
                Match.first_ball_utc.is_not(None),
                or_(Match.localteam_id == sco_id, Match.visitorteam_id == sco_id),
            )
            .order_by(Match.starting_at_utc)
        ).all()
        losses = [m for m in sco_matches if m.winner_team_id != sco_id]
        print(f"{'Date':<12} {'Opponent':<30} {'Format':<6} {'Side':<6} {'Moon NL':<16} {'League':<30}")
        print("-" * 105)
        for m in losses:
            nl = _first_ball_moon_nl(session, m.id)
            d = (m.first_ball_ist or m.starting_at_ist).strftime("%Y-%m-%d")
            side = "Home" if m.localteam_id == sco_id else "Away"
            nll = f"{nl} ({PLANET_LABELS.get(nl, nl)})" if nl else "-"
            print(
                f"{d:<12} {_opponent_name(session, m, sco_id):<30} "
                f"{(m.format or '-'):<6} {side:<6} {nll:<16} {(m.league or '-'):<30}"
            )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--opponents":
        detail_opponents()
    else:
        main()
        print()
        detail_opponents()
