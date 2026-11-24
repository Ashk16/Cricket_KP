"""Check Sportmonks for Bangladesh vs Australia on a given date."""

from __future__ import annotations

import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from live.day_manager import fetch_fixtures_for_date, fixture_label
from live.sportmonks_client import SportmonksClient


def _teams(fixture: dict) -> tuple[str, str, str, str]:
    lt = fixture.get("localteam") or {}
    vt = fixture.get("visitorteam") or {}
    if isinstance(lt, dict) and "data" in lt:
        lt = lt["data"]
    if isinstance(vt, dict) and "data" in vt:
        vt = vt["data"]
    return (
        lt.get("name") or "",
        vt.get("name") or "",
        lt.get("code") or "",
        vt.get("code") or "",
    )


def _league_name(fixture: dict) -> str:
    lg = fixture.get("league") or {}
    if isinstance(lg, dict) and "data" in lg:
        lg = lg["data"]
    return lg.get("name") or "" if isinstance(lg, dict) else ""


def main() -> None:
    day = date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-06-09")
    client = SportmonksClient()
    fixtures = fetch_fixtures_for_date(client, day)
    print(f"Fixtures on {day.isoformat()}: {len(fixtures)}")

    ban_aus = []
    for f in fixtures:
        lt, vt, lc, vc = _teams(f)
        blob = f"{lt} {vt}".lower()
        if "bangladesh" in blob and "australia" in blob:
            ban_aus.append(f)
            print(
                f"  id={f['id']} | {fixture_label(f)} | type={f.get('type')} | "
                f"status={f.get('status')} | league={_league_name(f)}"
            )
            print(f"    {lt} ({lc}) vs {vt} ({vc}) | start={f.get('starting_at')}")

    if not ban_aus:
        print("No Bangladesh vs Australia fixture on this date.")

    wider = client.get_fixtures_between("2026-06-08", "2026-06-10", includes="localteam,visitorteam,league")
    print("\nBangladesh vs Australia in 2026-06-08..10:")
    found = False
    for f in wider:
        lt, vt, _, _ = _teams(f)
        lt_l, vt_l = lt.lower(), vt.lower()
        if ("bangladesh" in lt_l and "australia" in vt_l) or ("australia" in lt_l and "bangladesh" in vt_l):
            found = True
            print(
                f"  id={f['id']} | {lt} vs {vt} | type={f.get('type')} | "
                f"{f.get('starting_at')} | status={f.get('status')} | league={_league_name(f)}"
            )
    if not found:
        print("  (none)")


if __name__ == "__main__":
    main()
