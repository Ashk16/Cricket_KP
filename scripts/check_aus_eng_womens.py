"""Quick Sportmonks lookup: Australia vs England women's fixtures."""

from __future__ import annotations

import os
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://cricket.sportmonks.com/api/v2.0"
TOKEN = os.getenv("SPORTMONKS_API_KEY")


def team_name(obj) -> str:
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], dict):
            obj = obj["data"]
        return (obj.get("name") or obj.get("code") or "").lower()
    return ""


def league_name(obj) -> str:
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], dict):
            obj = obj["data"]
        return (obj.get("name") or obj.get("code") or "").lower()
    return ""


def fetch_fixtures(days_back: int = 60, days_ahead: int = 60):
    d0 = (date.today() - timedelta(days=days_back)).isoformat()
    d1 = (date.today() + timedelta(days=days_ahead)).isoformat()
    params = {
        "api_token": TOKEN,
        "include": "localteam,visitorteam,league",
        "filter[starts_between]": f"{d0} 00:00:00,{d1} 23:59:59",
    }
    out = []
    page = 1
    while True:
        params["page"] = page
        resp = requests.get(f"{BASE}/fixtures", params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        out.extend(payload.get("data") or [])
        last = (payload.get("meta") or {}).get("last_page", 1)
        if page >= last:
            break
        page += 1
    return out


def is_aus_eng(fixture: dict) -> bool:
    lt, vt = team_name(fixture.get("localteam")), team_name(fixture.get("visitorteam"))
    aus = "australia" in lt or "australia" in vt
    eng = "england" in lt or "england" in vt
    return aus and eng


def is_womens(fixture: dict) -> bool:
    ln = league_name(fixture.get("league"))
    lt = team_name(fixture.get("localteam"))
    vt = team_name(fixture.get("visitorteam"))
    blob = f"{ln} {lt} {vt} {fixture.get('type', '')}".lower()
    return any(k in blob for k in ("women", "womens", "female"))


def main() -> None:
    fixtures = fetch_fixtures()
    print(f"Scanned {len(fixtures)} fixtures (+/-60 days)")

    aus_eng = [f for f in fixtures if is_aus_eng(f)]
    print(f"\nAustralia vs England (any gender): {len(aus_eng)}")
    for f in aus_eng:
        lt, vt = team_name(f["localteam"]), team_name(f["visitorteam"])
        print(
            f"  id={f['id']} | {f.get('starting_at')} | {lt} vs {vt} | "
            f"status={f.get('status')} | league={league_name(f.get('league'))} | type={f.get('type')}"
        )

    womens = [f for f in aus_eng if is_womens(f)]
    print(f"\nAustralia vs England (women's): {len(womens)}")
    for f in womens:
        lt, vt = team_name(f["localteam"]), team_name(f["visitorteam"])
        print(
            f"  id={f['id']} | {f.get('starting_at')} | {lt} vs {vt} | "
            f"status={f.get('status')} | league={league_name(f.get('league'))}"
        )

    live = requests.get(
        f"{BASE}/livescores",
        params={"api_token": TOKEN, "include": "localteam,visitorteam,league"},
        timeout=20,
    ).json().get("data") or []
    live_aus_eng = [f for f in live if is_aus_eng(f)]
    print(f"\nLive now - Australia vs England: {len(live_aus_eng)}")
    for f in live_aus_eng:
        lt, vt = team_name(f["localteam"]), team_name(f["visitorteam"])
        print(
            f"  LIVE id={f['id']} | {f.get('starting_at')} | {lt} vs {vt} | "
            f"status={f.get('status')} | league={league_name(f.get('league'))}"
        )


if __name__ == "__main__":
    main()
