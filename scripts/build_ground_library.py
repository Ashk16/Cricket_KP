"""Build data/ground_coords.json from Sportmonks venue list + curated coordinates.

Fetches all venues from the API (or reads data/_venues_api.json), merges with
the coordinate seed in data/ground_coords_seed.json, and writes the final
library used by live/venue_coords.py.

Run:
    python scripts/build_ground_library.py
    python scripts/build_ground_library.py --refresh   # re-fetch venues from API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from live.venue_coords import load_library, save_library

VENUES_API_PATH = _ROOT / "data" / "_venues_api.json"
SEED_PATH = _ROOT / "data" / "ground_coords_seed.json"
OUTPUT_PATH = _ROOT / "data" / "ground_coords.json"


def fetch_venues() -> list:
    from live.sportmonks_client import SportmonksClient

    return SportmonksClient()._get_pages("venues", {})


def load_seed() -> dict:
    if not SEED_PATH.exists():
        return {"by_id": {}, "by_name": {}}
    with open(SEED_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_name(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def build(refresh: bool = False) -> None:
    if refresh or not VENUES_API_PATH.exists():
        venues = fetch_venues()
        VENUES_API_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VENUES_API_PATH, "w", encoding="utf-8") as fh:
            json.dump(venues, fh, indent=2, ensure_ascii=False)
    else:
        with open(VENUES_API_PATH, encoding="utf-8") as fh:
            venues = json.load(fh)

    seed = load_seed()
    by_id: dict = seed.get("by_id", {})
    by_name: dict = seed.get("by_name", {})

    existing = load_library()
    # Preserve any AI-cached entries from the live library.
    for g in existing.get("grounds", []):
        sid = g.get("sportmonks_id")
        if sid is not None and g.get("lat") is not None:
            by_id[str(sid)] = {"lat": g["lat"], "lon": g["lon"]}
        elif g.get("name") and g.get("lat") is not None:
            by_name[_normalize_name(g["name"])] = {"lat": g["lat"], "lon": g["lon"]}

    grounds = []
    mapped = 0
    unmapped = []

    for v in venues:
        vid = v.get("id")
        name = v.get("name") or "unknown"
        city = v.get("city")
        coord = None
        source = "manual"

        if vid is not None and str(vid) in by_id:
            coord = by_id[str(vid)]
        elif _normalize_name(name) in by_name:
            coord = by_name[_normalize_name(name)]
        else:
            # Partial name match for aliases (e.g. "MA Chidambaram" vs full name).
            nkey = _normalize_name(name)
            for alias, c in by_name.items():
                if alias in nkey or nkey in alias:
                    coord = c
                    break

        entry = {
            "sportmonks_id": vid,
            "name": name,
            "city": city,
            "country": None,
            "lat": coord["lat"] if coord else None,
            "lon": coord["lon"] if coord else None,
            "source": source if coord else "none",
        }
        grounds.append(entry)
        if coord:
            mapped += 1
        else:
            unmapped.append(f"{vid}|{name}|{city}")

    out = {
        "_comment": (
            "Ground lat/lon library keyed by sportmonks_id. Built by "
            "scripts/build_ground_library.py. Matched first by id, then name."
        ),
        "grounds": grounds,
    }
    save_library(out, OUTPUT_PATH)

    print(f"Venues total : {len(venues)}")
    print(f"Mapped       : {mapped}")
    print(f"Unmapped     : {len(unmapped)}")
    if unmapped:
        unmapped_path = _ROOT / "data" / "_venues_unmapped.txt"
        with open(unmapped_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(unmapped))
        print(f"Unmapped list: {unmapped_path}")
    print(f"Wrote library: {OUTPUT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-fetch venues from API")
    args = parser.parse_args()
    build(refresh=args.refresh)


if __name__ == "__main__":
    main()
