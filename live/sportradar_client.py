"""Thin Sportradar Cricket v2 API client.

Auth: API key via ``x-api-key`` header (also sent as ``api_key`` query for
legacy compatibility). Trial vs production is selected with
``SPORTRADAR_ACCESS_LEVEL`` (``trial``/``t`` or ``production``/``p``).

Default base (trial)::

    https://api.sportradar.com/cricket-t2/en

Docs: https://developer.sportradar.com/cricket/reference
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_LANGUAGE = "en"
DEFAULT_FORMAT = "json"


class SportradarError(RuntimeError):
    pass


def _normalize_access_level(raw: Optional[str]) -> str:
    """Return path segment letter: ``t`` (trial) or ``p`` (production)."""
    val = (raw or os.getenv("SPORTRADAR_ACCESS_LEVEL") or "trial").strip().lower()
    if val in ("t", "trial"):
        return "t"
    if val in ("p", "prod", "production"):
        return "p"
    raise SportradarError(
        f"Invalid SPORTRADAR_ACCESS_LEVEL={raw!r}. Use trial/t or production/p."
    )


def default_base_url(
    access_level: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    level = _normalize_access_level(access_level)
    lang = (language or os.getenv("SPORTRADAR_LANGUAGE") or DEFAULT_LANGUAGE).strip()
    return f"https://api.sportradar.com/cricket-{level}2/{lang}"


class SportradarClient:
    """Minimal Cricket v2 client for connectivity + schedule discovery."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        access_level: Optional[str] = None,
        language: Optional[str] = None,
        timeout: int = 30,
    ):
        self.api_key = api_key or os.getenv("SPORTRADAR_API_KEY")
        self.access_level = _normalize_access_level(access_level)
        self.language = (language or os.getenv("SPORTRADAR_LANGUAGE") or DEFAULT_LANGUAGE).strip()
        override = base_url or os.getenv("SPORTRADAR_BASE_URL")
        self.base_url = (override or default_base_url(self.access_level, self.language)).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise SportradarError(
                "No Sportradar API key. Set SPORTRADAR_API_KEY in the environment/.env."
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        q = dict(params or {})
        # OpenAPI lists query api_key; newer docs prefer x-api-key header. Send both.
        q.setdefault("api_key", self.api_key)
        resp = requests.get(url, headers=self._headers(), params=q, timeout=self.timeout)
        if resp.status_code != 200:
            raise SportradarError(
                f"GET {url} -> {resp.status_code}: {resp.text[:400]}"
            )
        if not resp.content:
            return {}
        return resp.json()

    # --- Discovery feeds -------------------------------------------------

    def get_tournaments(self) -> List[Dict[str, Any]]:
        payload = self._get(f"tournaments.{DEFAULT_FORMAT}")
        return list(payload.get("tournaments") or [])

    def get_daily_schedule(self, day: Union[date, str]) -> List[Dict[str, Any]]:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        payload = self._get(f"schedules/{day_s}/schedule.{DEFAULT_FORMAT}")
        return list(payload.get("sport_events") or [])

    def get_daily_results(self, day: Union[date, str]) -> List[Dict[str, Any]]:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        payload = self._get(f"schedules/{day_s}/results.{DEFAULT_FORMAT}")
        return list(payload.get("results") or payload.get("sport_events") or [])

    def get_live_schedule(self) -> List[Dict[str, Any]]:
        payload = self._get(f"schedules/live/schedule.{DEFAULT_FORMAT}")
        return list(payload.get("sport_events") or [])

    def get_match_summary(self, match_id: str) -> Dict[str, Any]:
        mid = match_id.strip()
        # Cricket v2 uses /matches/{id}/... (ids often look like sr:match:...)
        return self._get(f"matches/{mid}/summary.{DEFAULT_FORMAT}")

    def get_match_timeline(self, match_id: str) -> Dict[str, Any]:
        """Ball-by-ball / play-by-play when coverage supports it."""
        mid = match_id.strip()
        return self._get(f"matches/{mid}/timeline.{DEFAULT_FORMAT}")

    def get_tournament_info(self, tournament_id: str) -> Dict[str, Any]:
        tid = tournament_id.strip()
        return self._get(f"tournaments/{tid}/info.{DEFAULT_FORMAT}")

    def find_tournaments(
        self,
        *keywords: str,
        limit: int = 40,
    ) -> List[Dict[str, Any]]:
        """Case-insensitive name/category filter over tournament list."""
        keys = [k.lower() for k in keywords if k]
        hits: List[Dict[str, Any]] = []
        for t in self.get_tournaments():
            name = (t.get("name") or "").lower()
            cat = ((t.get("category") or {}).get("name") or "").lower()
            blob = f"{name} {cat}"
            if keys and not any(k in blob for k in keys):
                continue
            hits.append(t)
            if len(hits) >= limit:
                break
        return hits

    def get_schedules_between(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
    ) -> List[Dict[str, Any]]:
        """Fetch daily schedules for each calendar day in [from, to] inclusive."""
        start = date.fromisoformat(date_from) if isinstance(date_from, str) else date_from
        end = date.fromisoformat(date_to) if isinstance(date_to, str) else date_to
        if end < start:
            start, end = end, start
        out: List[Dict[str, Any]] = []
        day = start
        while day <= end:
            try:
                out.extend(self.get_daily_schedule(day))
            except SportradarError:
                # Empty / no coverage days can 404 on some plans; skip.
                pass
            day += timedelta(days=1)
        return out


def sport_event_label(event: Dict[str, Any]) -> str:
    """Human-readable one-liner for a Sportradar sport_event."""
    competitors = event.get("competitors") or []
    names = [c.get("name") or c.get("abbreviation") or "?" for c in competitors[:2]]
    vs = " vs ".join(names) if names else (event.get("id") or "?")
    start = event.get("scheduled") or event.get("start_time") or ""
    if isinstance(start, datetime):
        start = start.isoformat()
    tour = ((event.get("tournament") or {}).get("name")) or ""
    status = ((event.get("sport_event_status") or {}).get("status")) or event.get("status") or ""
    bits = [str(start)[:19], vs]
    if tour:
        bits.append(f"({tour})")
    if status:
        bits.append(f"[{status}]")
    return " | ".join(bits)
