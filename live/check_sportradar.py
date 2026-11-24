"""Sportradar Cricket v2 connectivity checker.

Verifies that SPORTRADAR_API_KEY works and lists a sample of tournaments /
today's schedule. Does NOT print your key.

Usage:
  python -m live.check_sportradar
  python -m live.check_sportradar --search "Tamil Nadu" --search ECS
  python -m live.check_sportradar --date 2026-03-30
  python -m live.check_sportradar --event sr:sport_event:12345
"""

from __future__ import annotations

import argparse
import os
from datetime import date

from dotenv import load_dotenv

from live.sportradar_client import (
    SportradarClient,
    SportradarError,
    default_base_url,
    sport_event_label,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Sportradar Cricket API connectivity")
    parser.add_argument(
        "--date",
        default=None,
        help="YYYY-MM-DD for daily schedule (default: today)",
    )
    parser.add_argument(
        "--search",
        action="append",
        default=[],
        help="Keyword to filter tournaments (repeatable)",
    )
    parser.add_argument(
        "--event",
        default=None,
        help="Match id to probe summary + timeline (e.g. sr:match:...)",
    )
    args = parser.parse_args()

    load_dotenv()
    key = os.getenv("SPORTRADAR_API_KEY")
    access = os.getenv("SPORTRADAR_ACCESS_LEVEL") or "trial"
    print(f"Access level: {access}")
    print(f"Base URL: {os.getenv('SPORTRADAR_BASE_URL') or default_base_url(access)}")
    if not key or key.strip() in ("", "your_sportradar_key_here"):
        print(
            "FAIL: SPORTRADAR_API_KEY is not set.\n"
            "  1. Open Cricket_KP/.env\n"
            "  2. Paste your key after SPORTRADAR_API_KEY=\n"
            "  3. Keep SPORTRADAR_ACCESS_LEVEL=trial for the one-month trial\n"
            "  4. Re-run: python -m live.check_sportradar"
        )
        raise SystemExit(1)
    print(f"API key: present (length {len(key)})\n")

    try:
        client = SportradarClient()
    except SportradarError as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)

    all_ok = True

    # Tournaments
    try:
        tournaments = client.get_tournaments()
        print(f"[OK ] tournaments                 {len(tournaments)} tournament(s)")
    except SportradarError as exc:
        all_ok = False
        print(f"[ERR] tournaments                 {exc}")
        tournaments = []

    keywords = args.search or ["ECS", "Tamil", "Belgium", "IPL", "T10"]
    if tournaments:
        print("\nSample tournament matches for keywords:", ", ".join(keywords))
        hits = client.find_tournaments(*keywords, limit=25)
        if not hits:
            print("  (no name matches — try --search <word>)")
        for t in hits:
            cat = (t.get("category") or {}).get("name")
            season = (t.get("current_season") or {}).get("name")
            print(f"  {t.get('id')}: {t.get('name')} | {cat} | season={season} | type={t.get('type')}")

    # Daily schedule
    day = date.fromisoformat(args.date) if args.date else date.today()
    try:
        schedule = client.get_daily_schedule(day)
        print(f"\n[OK ] daily schedule {day.isoformat():10}  {len(schedule)} event(s)")
        for ev in schedule[:12]:
            print(f"  {sport_event_label(ev)}")
        if len(schedule) > 12:
            print(f"  ... +{len(schedule) - 12} more")
    except SportradarError as exc:
        all_ok = False
        print(f"\n[ERR] daily schedule {day.isoformat():10}  {exc}")

    # Live
    try:
        live = client.get_live_schedule()
        print(f"\n[OK ] live schedule               {len(live)} event(s)")
        for ev in live[:8]:
            print(f"  {sport_event_label(ev)}")
    except SportradarError as exc:
        # Live can be empty / restricted; don't fail hard.
        print(f"\n[WARN] live schedule               {exc}")

    if args.event:
        print(f"\nMatch probe: {args.event}")
        try:
            summary = client.get_match_summary(args.event)
            print(f"[OK ] summary keys: {', '.join(list(summary.keys())[:12])}")
        except SportradarError as exc:
            all_ok = False
            print(f"[ERR] summary: {exc}")
        try:
            timeline = client.get_match_timeline(args.event)
            events = timeline.get("timeline") or []
            print(f"[OK ] timeline events: {len(events)}")
        except SportradarError as exc:
            print(f"[WARN] timeline: {exc}")

    print()
    if all_ok:
        print("Sportradar connectivity looks good.")
        print("Next: we can wire the dashboard/daemon to use Sportradar for leagues")
        print("Sportmonks does not cover (e.g. TNPL, ECS Belgium).")
    else:
        print(
            "Some checks failed. Common causes: wrong key, trial not for Cricket v2, "
            "or SPORTRADAR_ACCESS_LEVEL should be trial (not production)."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
