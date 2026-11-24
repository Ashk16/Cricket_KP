"""Ground coordinate resolution.

Strategy (no geocoding packages, per project requirement):
  1. Look up a curated JSON library (data/ground_coords.json) by Sportmonks
     venue id, then by normalized name|city.
  2. If not found and an OpenAI key is configured, ask the model for the
     coordinates, validate them, and cache the result back into the library.
  3. If still unresolved, return source='none' so the caller can defer/flag.

The OpenAI call is made via the REST API with `requests` (no extra SDK
dependency) and only fires when OPENAI_API_KEY is present.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from live.sportmonks_client import _unwrap_obj

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PATH = _PROJECT_ROOT / "data" / "ground_coords.json"

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


@dataclass
class CoordResult:
    lat: Optional[float]
    lon: Optional[float]
    source: str  # library | ai | none

    @property
    def resolved(self) -> bool:
        return self.lat is not None and self.lon is not None


# --------------------------------------------------------------------------- #
# Library I/O
# --------------------------------------------------------------------------- #
def load_library(path: Path = LIBRARY_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {"grounds": []}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_library(data: Dict[str, Any], path: Path = LIBRARY_PATH) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _lookup_library(
    grounds: List[Dict[str, Any]],
    sportmonks_id: Optional[int],
    name: Optional[str],
    city: Optional[str],
) -> Optional[Dict[str, Any]]:
    if sportmonks_id is not None:
        for g in grounds:
            if g.get("sportmonks_id") == sportmonks_id and _valid(g.get("lat"), g.get("lon")):
                return g
    key_name, key_city = _normalize(name), _normalize(city)
    for g in grounds:
        if not _valid(g.get("lat"), g.get("lon")):
            continue
        if _normalize(g.get("name")) == key_name and (not key_city or _normalize(g.get("city")) == key_city):
            return g
    # Name-only fallback (cities sometimes differ in spelling).
    for g in grounds:
        if _valid(g.get("lat"), g.get("lon")) and _normalize(g.get("name")) == key_name:
            return g
    return None


def _valid(lat: Any, lon: Any) -> bool:
    try:
        return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# AI fallback
# --------------------------------------------------------------------------- #
def _ai_resolve(name: str, city: Optional[str], country: Optional[str]) -> Optional[Tuple[float, float]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    location = ", ".join([p for p in [name, city, country] if p])
    system = (
        "You are a precise geocoder for cricket stadiums. Given a stadium, "
        "return ONLY its decimal latitude and longitude as JSON: "
        '{"lat": <float>, "lon": <float>}. Use WGS84. If unsure, return '
        '{"lat": null, "lon": null}.'
    )
    body = {
        "model": OPENAI_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Cricket stadium: {location}"},
        ],
    }
    try:
        resp = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        lat, lon = parsed.get("lat"), parsed.get("lon")
        if _valid(lat, lon):
            return float(lat), float(lon)
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
        return None
    return None


# --------------------------------------------------------------------------- #
# Dashboard / manual picker helpers
# --------------------------------------------------------------------------- #
def _ground_key(ground: Dict[str, Any]) -> str:
    sportmonks_id = ground.get("sportmonks_id")
    if sportmonks_id is not None:
        return str(sportmonks_id)
    return _normalize(ground.get("name")) or "ground"


def format_ground_label(ground: Dict[str, Any]) -> str:
    name = str(ground.get("name") or "").strip()
    city = str(ground.get("city") or "").strip()
    if name and city:
        return f"{name} - {city}"
    return name or city


def list_ground_options() -> List[Dict[str, Any]]:
    """Return searchable ground options with coordinates from the library.

    Shape matches KP_AI_astrologer's venue picker: key / name / label / city / lat / lon.
    """
    options: List[Dict[str, Any]] = []
    for ground in load_library().get("grounds", []):
        if not _valid(ground.get("lat"), ground.get("lon")):
            continue
        name = str(ground.get("name") or "").strip()
        if not name:
            continue
        options.append(
            {
                "key": _ground_key(ground),
                "name": name,
                "label": format_ground_label(ground),
                "city": str(ground.get("city") or "").strip(),
                "lat": float(ground["lat"]),
                "lon": float(ground["lon"]),
            }
        )
    options.sort(key=lambda item: item["label"].lower())
    return options


# --------------------------------------------------------------------------- #
# Public resolver
# --------------------------------------------------------------------------- #
def resolve_coordinates(
    venue_payload: Dict[str, Any],
    allow_ai: bool = True,
    cache_ai: bool = True,
) -> CoordResult:
    """Resolve coordinates for a Sportmonks venue payload.

    Library-first; OpenAI fallback (if a key is set and allow_ai); caches AI
    results back into the library.
    """
    venue_payload = _unwrap_obj(venue_payload)
    sportmonks_id = venue_payload.get("id")
    name = venue_payload.get("name")
    city = venue_payload.get("city")
    country = venue_payload.get("country")

    library = load_library()
    grounds = library.setdefault("grounds", [])

    hit = _lookup_library(grounds, sportmonks_id, name, city)
    if hit is not None:
        return CoordResult(float(hit["lat"]), float(hit["lon"]), "library")

    if allow_ai and name:
        coords = _ai_resolve(name, city, country)
        if coords is not None:
            lat, lon = coords
            if cache_ai:
                grounds.append({
                    "sportmonks_id": sportmonks_id,
                    "name": name,
                    "city": city,
                    "country": country,
                    "lat": lat,
                    "lon": lon,
                    "source": "ai",
                })
                save_library(library)
            return CoordResult(lat, lon, "ai")

    return CoordResult(None, None, "none")
