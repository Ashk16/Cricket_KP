"""Sportmonks connectivity checker.

Verifies that SPORTMONKS_API_KEY works and reports which key endpoints/includes
your plan allows. Does NOT print your token.

Usage:
  python -m live.check_api
  python -m live.check_api --fixture 12345
"""

from __future__ import annotations

import argparse
import os

import requests
from dotenv import load_dotenv

from live.sportmonks_client import DEFAULT_BASE_URL


def _probe(base_url: str, token: str, path: str, params: dict) -> tuple[int, str]:
    q = dict(params)
    q["api_token"] = token
    try:
        resp = requests.get(f"{base_url}/{path.lstrip('/')}", params=q, timeout=20)
    except requests.RequestException as exc:
        return 0, f"request error: {exc}"
    snippet = ""
    if resp.status_code != 200:
        snippet = resp.text[:200].replace("\n", " ")
    else:
        data = resp.json().get("data")
        if isinstance(data, list):
            snippet = f"{len(data)} item(s)"
        elif isinstance(data, dict):
            snippet = f"keys: {', '.join(list(data.keys())[:8])}"
    return resp.status_code, snippet


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Sportmonks API connectivity")
    parser.add_argument("--fixture", type=int, help="A known fixture id to test ball-by-ball includes")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("SPORTMONKS_API_KEY")
    base_url = (os.getenv("SPORTMONKS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    print(f"Base URL: {base_url}")
    if not token:
        print("FAIL: SPORTMONKS_API_KEY is not set. Add it to .env and retry.")
        raise SystemExit(1)
    print(f"Token: present (length {len(token)})\n")

    checks = [
        ("leagues", "leagues", {}),
        ("livescores", "livescores", {"include": "localteam,visitorteam,venue"}),
        ("fixtures (today window)", "fixtures", {}),
    ]
    if args.fixture:
        checks.append((
            f"fixture {args.fixture} + balls",
            f"fixtures/{args.fixture}",
            {"include": "localteam,visitorteam,venue,balls"},
        ))

    all_ok = True
    for label, path, params in checks:
        status, info = _probe(base_url, token, path, params)
        ok = status == 200
        all_ok = all_ok and (ok or status in (404,))  # 404 on a guessed fixture is acceptable
        flag = "OK " if ok else "ERR"
        print(f"[{flag}] {label:28} HTTP {status}  {info}")

    # Odds probing (optional / plan-gated for cricket).
    if args.fixture:
        print("\nOdds availability:")
        _probe_odds(base_url, token, args.fixture)
    else:
        print("\nOdds availability: pass --fixture <id> to probe odds for a real match.")

    print()
    if all_ok:
        print("Connectivity looks good. You can run: python run_daemon.py")
    else:
        print("Some checks failed. Common causes: cricket plan not active, wrong base URL, "
              "or token lacks access to that endpoint/include.")


def _probe_odds(base_url: str, token: str, fixture_id: int) -> None:
    from live.sportmonks_client import DEFAULT_ODDS_BASE_URL, normalize_odds

    odds_base = (os.getenv("SPORTMONKS_ODDS_BASE_URL") or DEFAULT_ODDS_BASE_URL).rstrip("/")
    probes = [
        ("v2 fixture include=odds", f"{base_url}/fixtures/{fixture_id}", {"include": "odds"}, "odds"),
        ("v3 inplay odds", f"{odds_base}/odds/inplay/fixtures/{fixture_id}", {}, None),
        ("v3 pre-match odds", f"{odds_base}/odds/pre-match/fixtures/{fixture_id}", {}, None),
    ]
    for label, url, params, dig in probes:
        q = dict(params); q["api_token"] = token
        try:
            resp = requests.get(url, params=q, timeout=20)
        except requests.RequestException as exc:
            print(f"  [ERR] {label:24} request error: {exc}")
            continue
        if resp.status_code != 200:
            print(f"  [ERR] {label:24} HTTP {resp.status_code} {resp.text[:120]}")
            continue
        data = resp.json().get("data")
        if dig and isinstance(data, dict):
            data = data.get(dig)
            if isinstance(data, dict):
                data = data.get("data")
        count = len(data) if isinstance(data, list) else (1 if data else 0)
        sample = normalize_odds(data if isinstance(data, list) else [data]) if data else []
        print(f"  [OK ] {label:24} entries={count}  normalized={len(sample)}")
        if sample:
            s = sample[0]
            print(f"         sample: market={s['market']} bookmaker={s['bookmaker']} "
                  f"selection={s['selection']} value={s['odd_value']}")


if __name__ == "__main__":
    main()
