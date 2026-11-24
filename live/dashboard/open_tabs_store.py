"""Persist open dashboard tabs so they survive Streamlit session reconnect."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

OPEN_TABS_PATH = Path(__file__).resolve().parents[2] / "data" / "live" / "open_charts.json"


def _tab_record(chart: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "day_iso": chart["day_iso"],
        "fixture_id": int(chart["fixture_id"]),
        "label": chart.get("label") or "",
    }


def save_open_tabs(open_charts: List[Dict[str, Any]], active_tab_id: Optional[str]) -> None:
    OPEN_TABS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not open_charts:
        if OPEN_TABS_PATH.is_file():
            OPEN_TABS_PATH.unlink(missing_ok=True)
        return
    payload = {
        "active_tab_id": active_tab_id,
        "tabs": [_tab_record(c) for c in open_charts],
    }
    OPEN_TABS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_open_tabs_registry() -> Optional[Dict[str, Any]]:
    if not OPEN_TABS_PATH.is_file():
        return None
    try:
        data = json.loads(OPEN_TABS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    tabs = data.get("tabs")
    if not isinstance(tabs, list) or not tabs:
        return None
    return data