"""Thin Sportmonks Cricket API client + ball normalization.

The Sportmonks cricket API nests included relations under a {"data": ...}
envelope (v2) or returns them inline (v3). This client unwraps both shapes and
normalizes ball deliveries into a flat dict the rest of the system understands.

NOTE on timestamps: Sportmonks ball objects do NOT carry a reliable per-ball
UTC timestamp. We therefore stamp each ball with our own wall-clock UTC at the
moment we first see it (handled by the poller, not here).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://cricket.sportmonks.com/api/v2.0"
# Odds live on the separate v3 Odds API (plan-gated for cricket).
DEFAULT_ODDS_BASE_URL = "https://api.sportmonks.com/v3/cricket"

# Includes that give us teams, venue, toss and ball-by-ball detail.
FIXTURE_INCLUDES = "localteam,visitorteam,venue,balls,batting,bowling,runs,scoreboards"

# Order in which we try to obtain odds; first one that returns data is cached.
DEFAULT_ODDS_STRATEGIES = ("v2_include", "v3_inplay", "v3_prematch")


class SportmonksError(RuntimeError):
    pass


class SportmonksClient:
    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        odds_base_url: Optional[str] = None,
        timeout: int = 20,
    ):
        self.api_token = api_token or os.getenv("SPORTMONKS_API_KEY")
        self.base_url = (base_url or os.getenv("SPORTMONKS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.odds_base_url = (
            odds_base_url or os.getenv("SPORTMONKS_ODDS_BASE_URL") or DEFAULT_ODDS_BASE_URL
        ).rstrip("/")
        self.fixture_includes = os.getenv("SPORTMONKS_FIXTURE_INCLUDES", FIXTURE_INCLUDES)
        self.odds_strategies = tuple(
            s.strip() for s in os.getenv("ODDS_STRATEGY", ",".join(DEFAULT_ODDS_STRATEGIES)).split(",")
            if s.strip()
        )
        self._working_odds_strategy: Optional[str] = None
        self._venue_cache: Dict[int, Dict[str, Any]] = {}
        self._player_name_cache: Dict[int, str] = {}
        self.timeout = timeout
        if not self.api_token:
            raise SportmonksError(
                "No Sportmonks API token. Set SPORTMONKS_API_KEY in the environment/.env."
            )

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._get_abs(f"{self.base_url}/{path.lstrip('/')}", params)

    def _get_abs(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        payload = self._get_raw_abs(url, params)
        return payload.get("data", payload)

    def _get_raw_abs(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return the full JSON envelope (data + meta + links)."""
        params = dict(params or {})
        params["api_token"] = self.api_token
        resp = requests.get(url, params=params, timeout=self.timeout)
        if resp.status_code != 200:
            raise SportmonksError(f"GET {url} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _get_pages(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch every page of a paginated list endpoint (follows meta.last_page).

        The Sportmonks v2 list endpoints cap at 100 items/page and expose
        ``meta.last_page``; without paging we'd silently truncate large queries
        (e.g. a full year of fixtures across all leagues).
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            page_params = dict(params or {})
            page_params["page"] = page
            payload = self._get_raw_abs(url, page_params)
            data = payload.get("data") or []
            out.extend(data)
            last_page = (payload.get("meta") or {}).get("last_page")
            page += 1
            if not last_page or page > last_page:
                break
            if max_pages is not None and page > max_pages:
                break
        return out

    def get_fixture(self, fixture_id: int, includes: Optional[str] = None) -> Dict[str, Any]:
        """Fetch a single fixture with the configured includes."""
        return self._get(f"fixtures/{fixture_id}", {"include": includes or self.fixture_includes})

    def get_venue(self, venue_id: int) -> Dict[str, Any]:
        """Fetch a venue by id (name/city/country). Cached per process.

        The v2 cricket `venue` include does not hydrate on fixtures (it returns
        only ``venue_id``), so we resolve the venue separately to get a name we
        can geocode. Sportmonks venues carry no lat/lon themselves.
        """
        if venue_id in self._venue_cache:
            return self._venue_cache[venue_id]
        try:
            data = _unwrap_obj(self._get(f"venues/{venue_id}"))
        except SportmonksError:
            data = {}
        self._venue_cache[venue_id] = data
        return data

    def get_player_name(self, player_id: int) -> Optional[str]:
        """Resolve a player's display name (cached). Returns None if unavailable."""
        if player_id in self._player_name_cache:
            return self._player_name_cache[player_id]
        try:
            data = _unwrap_obj(self._get(f"players/{player_id}"))
        except SportmonksError:
            return None
        name = (
            data.get("fullname")
            or data.get("full_name")
            or data.get("name")
            or data.get("common_name")
        )
        if name:
            self._player_name_cache[player_id] = str(name).strip()
            return self._player_name_cache[player_id]
        return None

    def get_balls(self, fixture_id: int) -> List[Dict[str, Any]]:
        """Fetch raw ball-by-ball deliveries for a fixture."""
        fixture = self.get_fixture(fixture_id, includes="balls")
        return _unwrap_list(fixture.get("balls"))

    def get_livescores(self, includes: str = "localteam,visitorteam,venue") -> List[Dict[str, Any]]:
        """Fetch fixtures currently live."""
        return _unwrap_list(self._get("livescores", {"include": includes}))

    def get_fixtures_between(
        self,
        date_from: str,
        date_to: str,
        includes: str = "localteam,visitorteam,venue",
        paginate: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch fixtures between two dates (YYYY-MM-DD inclusive).

        Paginates by default so large windows (e.g. a full year across all
        leagues) return every fixture, not just the first 100.

        Sportmonks treats a same-day ``YYYY-MM-DD,YYYY-MM-DD`` filter as empty;
        date-only bounds are expanded to ``00:00:00`` .. ``23:59:59``.
        """
        params = {
            "include": includes,
            "filter[starts_between]": _starts_between_filter(date_from, date_to),
        }
        if paginate:
            return self._get_pages("fixtures", params)
        return _unwrap_list(self._get("fixtures", params))

    def get_upcoming_fixtures(
        self,
        days_ahead: int = 2,
        includes: str = "localteam,visitorteam,venue",
    ) -> List[Dict[str, Any]]:
        """Fetch fixtures scheduled from today through ``days_ahead`` days."""
        from datetime import datetime, timedelta, timezone

        today = datetime.now(timezone.utc).date()
        return self.get_fixtures_between(
            today.isoformat(),
            (today + timedelta(days=days_ahead)).isoformat(),
            includes,
        )

    # ------------------------------------------------------------------ #
    # Odds (optional / plan-gated)
    # ------------------------------------------------------------------ #
    def _odds_via_v2_include(self, fixture_id: int) -> List[Dict[str, Any]]:
        fixture = self._get(f"fixtures/{fixture_id}", {"include": "odds"})
        return _unwrap_list(fixture.get("odds"))

    def _odds_via_v3(self, fixture_id: int, phase: str) -> List[Dict[str, Any]]:
        # phase: "inplay" or "pre-match"
        url = f"{self.odds_base_url}/odds/{phase}/fixtures/{fixture_id}"
        return _unwrap_list(self._get_abs(url, {}))

    def get_fixture_odds(self, fixture_id: int) -> tuple[List[Dict[str, Any]], Optional[str]]:
        """Best-effort odds fetch. Tries configured strategies in order and
        caches the first that yields data. Returns (raw_odds, strategy_used).

        Never raises on a missing/forbidden odds plan - returns ([], None).
        """
        strategies = (
            (self._working_odds_strategy,) if self._working_odds_strategy else self.odds_strategies
        )
        for strategy in strategies:
            try:
                if strategy == "v2_include":
                    data = self._odds_via_v2_include(fixture_id)
                elif strategy == "v3_inplay":
                    data = self._odds_via_v3(fixture_id, "inplay")
                elif strategy == "v3_prematch":
                    data = self._odds_via_v3(fixture_id, "pre-match")
                else:
                    continue
            except SportmonksError:
                continue
            if data:
                self._working_odds_strategy = strategy
                return data, strategy
        return [], None


def resolve_venue_payload(client: "SportmonksClient", fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Return a usable venue dict for a fixture.

    Prefers the inline ``venue`` include; if that is empty (the v2 cricket case)
    it falls back to fetching the venue by ``venue_id``.
    """
    venue = _unwrap_obj(fixture.get("venue"))
    if venue.get("name"):
        return venue
    venue_id = fixture.get("venue_id") or venue.get("id")
    if venue_id is not None:
        return client.get_venue(venue_id)
    return venue


# --------------------------------------------------------------------------- #
# Unwrapping + normalization helpers
# --------------------------------------------------------------------------- #
def _is_date_only(value: str) -> bool:
    s = value.strip()
    return len(s) == 10 and s[4] == "-" and s[7] == "-"


def _starts_between_filter(date_from: str, date_to: str) -> str:
    """Build a Sportmonks ``starts_between`` filter that works for single days."""
    start = date_from.strip()
    end = date_to.strip()
    if _is_date_only(start):
        start = f"{start} 00:00:00"
    if _is_date_only(end):
        end = f"{end} 23:59:59"
    return f"{start},{end}"


def _unwrap_list(value: Any) -> List[Dict[str, Any]]:
    """Accept either {"data": [...]}, [...] or None and return a list."""
    if value is None:
        return []
    if isinstance(value, dict) and "data" in value:
        return value["data"] or []
    if isinstance(value, list):
        return value
    return []


def _unwrap_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict) and "data" in value and isinstance(value["data"], dict):
        return value["data"]
    if isinstance(value, dict):
        return value
    return {}


def _split_over_ball(raw_ball: Any) -> tuple[Optional[int], Optional[int]]:
    """Sportmonks encodes deliveries as over.ball (e.g. 12.3). Split that.

    Returns (over, ball_in_over) as ints when possible.
    """
    if raw_ball is None:
        return None, None
    try:
        s = str(raw_ball)
        if "." in s:
            over_str, ball_str = s.split(".", 1)
            return int(over_str), int(ball_str)
        return int(float(s)), None
    except (ValueError, TypeError):
        return None, None


def normalize_ball(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map a raw Sportmonks ball object to our internal flat representation.

    Defensive: different API versions expose slightly different field names,
    so everything is accessed via .get with sensible fallbacks.
    """
    score = raw.get("score") or {}
    over, ball_in_over = _split_over_ball(raw.get("ball"))

    runs = _first_present(score.get("runs"), raw.get("runs"), default=0)
    extras = _sum_extras(score)
    is_four = bool(_first_present(score.get("four"), raw.get("four"), default=False))
    is_six = bool(_first_present(score.get("six"), raw.get("six"), default=False))
    is_wicket = _as_wicket(
        _first_present(
            score.get("out"),
            score.get("wicket"),
            raw.get("is_wicket"),
            raw.get("wicket"),
            default=False,
        )
    )

    return {
        "sportmonks_ball_id": raw.get("id"),
        "scoreboard": raw.get("scoreboard"),  # e.g. "S1", "S2" -> innings marker
        "team_id": raw.get("team_id"),
        "over": over,
        "ball": ball_in_over,
        "ball_label": raw.get("ball"),
        "batsman_id": raw.get("batsman_id") or raw.get("batsmanone_id"),
        "bowler_id": raw.get("bowler_id"),
        "runs": _safe_int(runs),
        "extras": _safe_int(extras),
        "is_four": is_four,
        "is_six": is_six,
        "is_wicket": is_wicket,
        "commentary": raw.get("commentary") or score.get("name"),
    }


_ODDS_VALUE_KEYS = ("value", "odd", "price", "decimal", "dp3", "american", "odds_value")
_ODDS_LABEL_KEYS = ("label", "name", "selection", "total", "handicap", "participant")
_ODDS_MARKET_KEYS = ("market", "market_name", "market_description")
_ODDS_BOOKMAKER_KEYS = ("bookmaker", "bookmaker_name")
_ODDS_UPDATED_KEYS = ("updated_at", "last_update", "latest_bookmaker_update", "updated")
_ODDS_NESTED_KEYS = ("odds", "values", "bookmaker", "bookmakers", "data", "markets")


def normalize_odds(raw_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten Sportmonks odds (shape varies by version/plan) into leaf records:
    {market, bookmaker, selection, odd_value, updated_at_source, raw}.

    Defensive: walks nested bookmaker/market/odds structures and emits a record
    wherever a numeric odd value is found, carrying market/bookmaker context down.
    """
    out: List[Dict[str, Any]] = []
    # stack items: (node, context_dict)
    stack = [(_unwrap_obj(e) if isinstance(e, dict) else e, {}) for e in (raw_entries or [])]
    guard = 0
    while stack and guard < 100_000:
        guard += 1
        node, ctx = stack.pop()
        if not isinstance(node, dict):
            continue

        ctx = dict(ctx)
        _carry(ctx, "market", node, _ODDS_MARKET_KEYS, ("market_id",))
        _carry(ctx, "bookmaker", node, _ODDS_BOOKMAKER_KEYS, ("bookmaker_id",))
        updated = _first_present(*[node.get(k) for k in _ODDS_UPDATED_KEYS])
        if updated is not None:
            ctx["updated_at_source"] = updated

        value = _first_present(*[node.get(k) for k in _ODDS_VALUE_KEYS])
        nested_found = False
        for key in _ODDS_NESTED_KEYS:
            if key in node:
                for child in _unwrap_list(node[key]):
                    stack.append((child, ctx))
                    nested_found = True

        if value is not None:
            label = _first_present(*[node.get(k) for k in _ODDS_LABEL_KEYS])
            out.append({
                "market": _stringify(ctx.get("market")),
                "bookmaker": _stringify(ctx.get("bookmaker")),
                "selection": _stringify(label),
                "odd_value": _safe_float(value),
                "updated_at_source": ctx.get("updated_at_source"),
                "raw": node,
            })
        elif not nested_found:
            # leaf with no recognizable value; ignore.
            continue
    return out


def _carry(ctx: Dict[str, Any], field: str, node: Dict[str, Any], name_keys, id_keys) -> None:
    val = _first_present(*[_extract_name(node.get(k)) for k in name_keys])
    if val is None:
        val = _first_present(*[node.get(k) for k in id_keys])
    if val is not None:
        ctx[field] = val


def _extract_name(value):
    if isinstance(value, dict):
        inner = _unwrap_obj(value)
        return inner.get("name") or inner.get("description")
    return value


def _stringify(value):
    return None if value is None else str(value)


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values, default=None):
    for v in values:
        if v is not None:
            return v
    return default


def _as_wicket(value) -> bool:
    """Sportmonks may send out/wicket as bool, 0/1, or short strings."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "out", "wicket")
    return bool(value)


def _sum_extras(score: Dict[str, Any]) -> int:
    total = 0
    for key in ("bye", "leg_bye", "legbye", "wide", "noball", "no_ball"):
        v = score.get(key)
        if isinstance(v, (int, float)):
            total += int(v)
    return total


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
