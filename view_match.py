"""Read-only CLI viewer - demonstrates connecting to a match at any time.

Examples:
  python view_match.py --list
  python view_match.py --match 1
  python view_match.py --match 1 --as-of 2025-07-04T18:00:00
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from db.session import get_session, init_db
from live.match_state import get_match_state, list_matches


def main() -> None:
    parser = argparse.ArgumentParser(description="View KP cricket match state")
    parser.add_argument("--list", action="store_true", help="List matches")
    parser.add_argument("--match", type=int, help="Match id to view")
    parser.add_argument("--as-of", type=str, help="ISO UTC instant; show state as of this time")
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    args = parser.parse_args()

    init_db()
    with get_session() as session:
        if args.list or args.match is None:
            matches = list_matches(session)
            if args.json:
                print(json.dumps(matches, indent=2))
            else:
                for m in matches:
                    print(f"[{m['match_id']}] {m['localteam']} vs {m['visitorteam']} "
                          f"({m['format']}) status={m['status']} balls={m['balls']} "
                          f"chart={'Y' if m['has_chart'] else 'N'}")
            return

        as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
        state = get_match_state(session, args.match, as_of=as_of)
        if state is None:
            print(f"No match {args.match}")
            return
        if args.json:
            print(json.dumps(state, indent=2))
            return
        _print_state(state)


def _print_state(state: dict) -> None:
    m = state["match"]
    print(f"\n{m['localteam']} vs {m['visitorteam']} ({m['format']})  status={m['status']}")
    print(f"scheduled: {m['starting_at_utc']}   first ball: {m['first_ball_utc']}")
    print(f"as of: {state['as_of_utc'] or 'now'}   total balls: {state['total_balls']}")

    ca = state["current_astro"]
    if ca["ascendant"] or ca["moon"]:
        asc, moon = ca["ascendant"], ca["moon"]
        print("\ncurrent KP period:")
        if asc:
            print(f"  Ascendant  NL/SL/SSL/SSSL: {asc['nl']}/{asc['sl']}/{asc['ssl']}/{asc['sssl']}")
        if moon:
            print(f"  Moon       NL/SL/SSL/SSSL: {moon['nl']}/{moon['sl']}/{moon['ssl']}/{moon['sssl']}")

    if state["innings"]:
        print("\ninnings:")
        for inn in state["innings"]:
            print(f"  Innings {inn['innings_number']}: {inn['runs']}/{inn['wickets']} "
                  f"({inn['deliveries']} balls)")

    if state["recent_balls"]:
        print("\nrecent balls:")
        for b in state["recent_balls"]:
            wk = "W" if b["is_wicket"] else " "
            moon = b["moon"]
            moon_s = f"{moon['ssl']}/{moon['sssl']}" if moon else "-"
            print(f"  {b['event_utc']}  {b['over']}.{b['ball']}  {b['runs']}r {wk}  moon(ssl/sssl)={moon_s}")
    print()


if __name__ == "__main__":
    main()
