"""KP Cricket Live Dashboard — Streamlit entrypoint."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from live.day_manager import (  # noqa: E402
    ensure_fixture_in_day_db,
    fetch_fixtures_for_date,
    fixture_label,
    fixture_tab_label,
    load_corrected_balls,
    match_context_for_analysis,
    sync_balls,
)
from live.day_session import day_session  # noqa: E402
from live.dashboard.display import (  # noqa: E402
    display_ball_score_tables,
    display_static_chart,
    display_timeline_sections,
)
from live.live_analysis import apply_all_ball_stats, run_live_analysis  # noqa: E402
from live.match_setup import apply_manual_ground  # noqa: E402
from live.sportmonks_client import SportmonksClient, _unwrap_obj  # noqa: E402
from live.dashboard.open_tabs_store import load_open_tabs_registry, save_open_tabs  # noqa: E402
from live.venue_coords import list_ground_options  # noqa: E402


def _fixture_by_id(fixtures, fid: int):
    for f in fixtures:
        if f.get("id") == fid:
            return f
    return None


def _fixture_missing_venue(fixture: dict) -> bool:
    """True when Sportmonks left venue/venue_id empty (coords cannot resolve)."""
    venue = _unwrap_obj(fixture.get("venue"))
    if venue.get("name") or venue.get("id"):
        return False
    if fixture.get("venue_id"):
        return False
    return True


def _day_match_has_coords(day: date, fixture_id: int) -> bool:
    """True if this fixture already has lat/lon stored in the day DB."""
    from db.models import Match  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    with day_session(day) as session:
        match = session.scalar(
            select(Match).where(Match.sportmonks_fixture_id == fixture_id)
        )
        return match is not None and match.lat is not None and match.lon is not None


@st.cache_resource
def _client():
    return SportmonksClient()


@st.cache_data(ttl=300, show_spinner=False)
def _fixtures_for_date(day_iso: str):
    client = _client()
    day = date.fromisoformat(day_iso)
    return fetch_fixtures_for_date(client, day)


@st.cache_data(ttl=3600, show_spinner=False)
def _ground_options():
    return list_ground_options()


def _is_live(fixture: dict) -> bool:
    s = str(fixture.get("status") or "").lower()
    return any(x in s for x in ("innings", "live", "stumps")) and "finished" not in s


def _tab_id(day_iso: str, fid: int) -> str:
    return f"{day_iso}:{fid}"


def _analysis_cache_key(day_iso: str, fid: int, anchor_utc) -> str:
    return f"{day_iso}:{fid}:{anchor_utc}"


def _init_session() -> None:
    if "open_charts" not in st.session_state:
        st.session_state.open_charts = []
    if "active_tab_id" not in st.session_state:
        st.session_state.active_tab_id = None


def _persist_open_tabs() -> None:
    save_open_tabs(
        st.session_state.get("open_charts") or [],
        st.session_state.get("active_tab_id"),
    )


def _try_restore_open_charts() -> None:
    """Reload tab list from disk after Streamlit session reconnect."""
    if st.session_state.open_charts:
        return
    if st.session_state.get("_open_tabs_restore_attempted"):
        return
    st.session_state._open_tabs_restore_attempted = True

    reg = load_open_tabs_registry()
    if not reg:
        return

    client = _client()
    restored: List[Dict[str, Any]] = []
    for rec in reg.get("tabs") or []:
        day_iso = rec.get("day_iso")
        fid = rec.get("fixture_id")
        if not day_iso or fid is None:
            continue
        try:
            fixture = client.get_fixture(
                int(fid),
                includes="localteam,visitorteam,venue",
            )
            entry = _load_chart_entry(date.fromisoformat(day_iso), fixture)
            if entry is not None:
                restored.append(entry)
        except Exception:  # noqa: BLE001
            continue

    if not restored:
        return

    st.session_state.open_charts = restored
    active = reg.get("active_tab_id")
    if active and any(c["tab_id"] == active for c in restored):
        st.session_state.active_tab_id = active
    else:
        st.session_state.active_tab_id = restored[0]["tab_id"]

    active_chart = _active_chart()
    if active_chart:
        st.session_state.picked_date = date.fromisoformat(active_chart["day_iso"])

    _persist_open_tabs()
    st.toast(f"Restored {len(restored)} open chart(s).")


def _fetch_fixtures_safe(day_iso: str) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        return _fixtures_for_date(day_iso), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _find_open_chart(tab_id: str) -> Optional[Dict[str, Any]]:
    for chart in st.session_state.open_charts:
        if chart["tab_id"] == tab_id:
            return chart
    return None


def _active_chart() -> Optional[Dict[str, Any]]:
    tab_id = st.session_state.active_tab_id
    if tab_id is None:
        return None
    return _find_open_chart(tab_id)


def _remove_chart(tab_id: str) -> None:
    remaining = [c for c in st.session_state.open_charts if c["tab_id"] != tab_id]
    st.session_state.open_charts = remaining
    if st.session_state.active_tab_id == tab_id:
        st.session_state.active_tab_id = remaining[-1]["tab_id"] if remaining else None
    _persist_open_tabs()


def _apply_live_ball_comments(base_results: dict, balls, innings_by_id: Optional[dict] = None) -> dict:
    return apply_all_ball_stats(base_results, balls, innings_by_id=innings_by_id)


def _load_chart_entry(
    day: date,
    fixture: dict,
    manual_ground: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    fid = fixture["id"]
    day_iso = day.isoformat()
    client = _client()

    with day_session(day) as session:
        match = ensure_fixture_in_day_db(session, client, fixture)
        if manual_ground is not None and (match.lat is None or match.lon is None):
            apply_manual_ground(session, match, manual_ground)
            # Keep analysis venue label in sync with the manual pick.
            fixture = dict(fixture)
            fixture["venue"] = {
                "id": int(manual_ground["key"]) if str(manual_ground.get("key", "")).isdigit() else None,
                "name": manual_ground.get("name"),
                "city": manual_ground.get("city") or None,
            }
            fixture["venue_id"] = fixture["venue"]["id"]
        sync_balls(session, client, match, fixture)
        ctx = match_context_for_analysis(session, match, fixture)
        match_id = match.id

    if ctx["lat"] is None or ctx["lon"] is None:
        flag = f"needs_venue_{day_iso}_{fid}"
        if not st.session_state.get(flag):
            st.session_state[flag] = True
            st.rerun()
        st.error(
            "Venue coordinates not resolved — pick a venue from the dropdown "
            "(to the right of Match), then click **Open chart** again."
        )
        return None

    st.session_state.pop(f"needs_venue_{day_iso}_{fid}", None)

    cache_key = _analysis_cache_key(day_iso, fid, str(ctx["chart_anchor_utc"]))
    with st.spinner(f"Building chart for {fixture_tab_label(fixture)}…"):
        base_results = run_live_analysis(ctx)

    entry: Dict[str, Any] = {
        "tab_id": _tab_id(day_iso, fid),
        "day_iso": day_iso,
        "fixture_id": fid,
        "match_id": match_id,
        "label": fixture_tab_label(fixture),
        "base_results": base_results,
        "cache_key": cache_key,
        "fixture_snapshot": fixture,
    }
    _seed_live_results_from_db(entry)
    return entry


def _innings_by_match(session, match_id: int) -> dict:
    from db.models import Innings  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    innings_rows = session.scalars(select(Innings).where(Innings.match_id == match_id)).all()
    return {
        inn.id: {
            "innings_number": inn.innings_number,
            "batting_team_id": inn.batting_team_id,
        }
        for inn in innings_rows
    }


def _seed_live_results_from_db(chart: Dict[str, Any]) -> None:
    """Populate live_results from day DB only (no Sportmonks)."""
    day = date.fromisoformat(chart["day_iso"])
    with day_session(day) as session:
        balls = load_corrected_balls(session, chart["match_id"])
        innings_by_id = _innings_by_match(session, chart["match_id"])
    _refresh_live_results(chart, balls, 0, innings_by_id)


def _maybe_rebuild_on_anchor_change(chart: Dict[str, Any]) -> None:
    """Rebuild analysis only when chart anchor shifts (e.g. first ball). Uses day DB only."""
    day = date.fromisoformat(chart["day_iso"])
    fixture = chart["fixture_snapshot"]

    with day_session(day) as session:
        from db.models import Match  # noqa: PLC0415

        match = session.get(Match, chart["match_id"])
        if match is None:
            return
        ctx = match_context_for_analysis(session, match, fixture)

    cache_key = _analysis_cache_key(chart["day_iso"], chart["fixture_id"], str(ctx["chart_anchor_utc"]))
    if chart.get("cache_key") != cache_key:
        chart["base_results"] = run_live_analysis(ctx)
        chart["cache_key"] = cache_key
    else:
        _patch_match_details(chart, ctx)


def _patch_match_details(chart: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    """Keep team/toss ids in match_details current for live score labels."""
    base = chart.get("base_results")
    if not base or base.get("error"):
        return
    md = base.setdefault("match_details", {})
    for key in (
        "team_a",
        "team_b",
        "team_a_short",
        "team_b_short",
        "localteam_id",
        "visitorteam_id",
        "toss_won_team_id",
        "toss_elected",
    ):
        if key in ctx:
            md[key] = ctx[key]


def _sync_and_load_balls(chart: Dict[str, Any]) -> tuple[list, int, dict]:
    """Fetch latest balls from Sportmonks, then read corrected balls from day DB."""
    day = date.fromisoformat(chart["day_iso"])
    fixture = chart["fixture_snapshot"]
    client = _client()

    with day_session(day) as session:
        from db.models import Match  # noqa: PLC0415

        match = session.get(Match, chart["match_id"])
        if match is None:
            match = ensure_fixture_in_day_db(session, client, fixture)
            chart["match_id"] = match.id
        n_balls = sync_balls(session, client, match, fixture)
        balls = load_corrected_balls(session, match.id)
        innings_by_id = _innings_by_match(session, match.id)
    return balls, n_balls, innings_by_id


def _pull_scores_from_sportmonks(chart: Dict[str, Any]) -> int:
    """Sync Sportmonks, rebuild chart if anchor moved, refresh live score tables."""
    balls, n_new, innings_by_id = _sync_and_load_balls(chart)
    _maybe_rebuild_on_anchor_change(chart)
    _refresh_live_results(chart, balls, n_new, innings_by_id)
    return n_new


def _render_tab_selector(open_charts: List[Dict[str, Any]]) -> None:
    """Horizontal chip per chart with its own ✕ close button."""
    st.caption("Open charts — click to switch")
    cols = st.columns(len(open_charts))
    for col, chart in zip(cols, open_charts):
        is_active = chart["tab_id"] == st.session_state.active_tab_id
        with col:
            sel_col, close_col = st.columns([5, 1])
            with sel_col:
                if st.button(
                    chart["label"],
                    key=f"select_{chart['tab_id']}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                ):
                    if st.session_state.active_tab_id != chart["tab_id"]:
                        st.session_state.active_tab_id = chart["tab_id"]
                        _persist_open_tabs()
                        st.rerun()
            with close_col:
                if st.button("✕", key=f"close_{chart['tab_id']}", help=f"Close {chart['label']}"):
                    _remove_chart(chart["tab_id"])
                    st.rerun()


def _refresh_live_results(chart: Dict[str, Any], balls, n_new: int, innings_by_id: dict) -> None:
    chart["last_ball_count"] = len(balls)
    chart["live_results"] = _apply_live_ball_comments(chart["base_results"], balls, innings_by_id)
    chart["live_updated_at"] = datetime.now().isoformat()
    chart["live_n_new"] = n_new


def _live_status_caption(chart: Dict[str, Any]) -> None:
    if not chart.get("live_updated_at"):
        return
    updated = datetime.fromisoformat(chart["live_updated_at"]).strftime("%H:%M:%S")
    note = f"Scores updated {updated} · {chart.get('last_ball_count', 0)} balls tracked"
    if chart.get("live_n_new"):
        note += f" · {chart['live_n_new']} new on last update"
    st.caption(note)


def _display_live_timeline_sections(chart: Dict[str, Any]) -> None:
    """Ascendant expander + Moon SSL/SSSL timelines (default live-timeline view)."""
    if not chart.get("live_results"):
        _seed_live_results_from_db(chart)
    if not chart.get("live_results"):
        st.info("No ball data in the day database yet. Use **Refresh scores** to pull from Sportmonks.")
        return
    display_timeline_sections(chart["live_results"], styled=True)


def _render_live_timeline_block(chart: Dict[str, Any], auto_refresh: bool, live: bool) -> None:
    """Show cached scores; Sportmonks only via Refresh scores or optional auto-refresh."""
    tab_id = chart["tab_id"]
    score_row = st.columns([1, 2, 2])
    with score_row[0]:
        if st.button("Refresh scores", key=f"refresh_scores_{tab_id}", type="secondary"):
            with st.spinner("Syncing from Sportmonks…"):
                n_new = _pull_scores_from_sportmonks(chart)
            if n_new:
                st.toast(f"Synced {n_new} new ball(s).")
            else:
                st.toast("Scores refreshed.")
            st.rerun()

    if auto_refresh and live:
        if not chart.get("live_results"):
            _seed_live_results_from_db(chart)
        if chart.get("live_results"):
            display_ball_score_tables(chart["live_results"], styled=True)
            _live_status_caption(chart)
        st.caption("Auto-refresh on — polls Sportmonks every 15s for in-play matches.")

        @st.fragment(run_every=timedelta(seconds=15))
        def _poll_scores() -> None:
            balls, n_new, innings_by_id = _sync_and_load_balls(chart)
            if n_new > 0 or chart.get("last_ball_count") != len(balls):
                _maybe_rebuild_on_anchor_change(chart)
                _refresh_live_results(chart, balls, n_new, innings_by_id)
                st.rerun()

        _poll_scores()
        return

    _display_live_timeline_sections(chart)
    _live_status_caption(chart)
    with score_row[2]:
        st.caption("Tab switches use cached data. Click **Refresh scores** to pull from Sportmonks.")


def _render_active_chart(chart: Dict[str, Any], auto_refresh: bool) -> None:
    _maybe_rebuild_on_anchor_change(chart)
    base_results = chart["base_results"]

    if base_results.get("error"):
        display_static_chart(base_results)
        return

    display_static_chart(base_results)

    st.divider()
    st.subheader("Live timeline scores")
    live = _is_live(chart["fixture_snapshot"])
    _render_live_timeline_block(chart, auto_refresh, live)

    with st.expander("Match meta"):
        day = date.fromisoformat(chart["day_iso"])
        with day_session(day) as session:
            from db.models import Match  # noqa: PLC0415

            match = session.get(Match, chart["match_id"])
            balls = load_corrected_balls(session, match.id) if match else []
            ctx = match_context_for_analysis(session, match, chart["fixture_snapshot"]) if match else {}
        st.json(
            {
                "tab_id": chart["tab_id"],
                "sportmonks_fixture_id": chart["fixture_id"],
                "scheduled_utc": str(ctx.get("scheduled_utc")),
                "chart_anchor_utc": str(ctx.get("chart_anchor_utc")),
                "timeline_hours": ctx.get("duration_hours"),
                "balls_in_day_db": len(balls),
                "day_db": f"data/live/live_{chart['day_iso']}.db",
            }
        )


def main():
    st.set_page_config(page_title="KP Cricket Live", layout="wide")
    st.title("KP Cricket Live Dashboard")
    _init_session()
    _try_restore_open_charts()

    # Resolve day from session before laying out columns (venue column is conditional).
    picked_preview = st.session_state.get("picked_date", date.today())
    if isinstance(picked_preview, datetime):
        picked_preview = picked_preview.date()
    if not isinstance(picked_preview, date):
        picked_preview = date.today()
    day_iso = picked_preview.isoformat()

    fixtures, fixtures_err = _fetch_fixtures_safe(day_iso)
    if fixtures_err:
        st.warning(
            f"Could not refresh today's fixture list ({fixtures_err}). "
            "Open charts below are unchanged."
        )

    fixture_ids = [f["id"] for f in fixtures] if fixtures else []
    labels = {f["id"]: fixture_label(f) for f in fixtures} if fixtures else {}

    fid_preview = st.session_state.get(f"match_picker_{day_iso}")
    fixture_preview = (
        _fixture_by_id(fixtures, fid_preview) if fid_preview and fixtures else None
    )
    needs_venue = bool(
        fixture_preview
        and (
            _fixture_missing_venue(fixture_preview)
            or st.session_state.get(f"needs_venue_{day_iso}_{fid_preview}")
        )
    )

    if needs_venue:
        col_date, col_match, col_venue, col_open, col_opts = st.columns([1, 2, 2, 1, 1])
    else:
        col_date, col_match, col_open, col_opts = st.columns([1, 2, 1, 1])
        col_venue = None

    with col_date:
        picked = st.date_input("Date", value=date.today(), key="picked_date")
    day_iso = picked.isoformat()

    # Re-fetch if the date widget changed this run.
    if day_iso != picked_preview.isoformat():
        fixtures, fixtures_err = _fetch_fixtures_safe(day_iso)
        if fixtures_err:
            st.warning(f"Could not load fixtures for {day_iso} ({fixtures_err}).")
        fixture_ids = [f["id"] for f in fixtures] if fixtures else []
        labels = {f["id"]: fixture_label(f) for f in fixtures} if fixtures else {}

    with col_match:
        if fixture_ids:
            fid = st.selectbox(
                "Match",
                options=fixture_ids,
                index=None,
                placeholder="Choose a match…",
                format_func=lambda x: labels[x],
                key=f"match_picker_{day_iso}",
            )
        else:
            st.caption("No fixtures for this date (or API unavailable).")
            fid = None

    # Recompute after the match widget (selection may have just changed).
    fixture = _fixture_by_id(fixtures, fid) if fid and fixtures else None
    needs_venue = bool(
        fixture
        and (
            _fixture_missing_venue(fixture)
            or st.session_state.get(f"needs_venue_{day_iso}_{fid}")
        )
    )

    manual_ground: Optional[Dict[str, Any]] = None
    if col_venue is not None and needs_venue and fid is not None:
        with col_venue:
            grounds = _ground_options()
            ground_by_key = {g["key"]: g for g in grounds}
            picked_key = st.selectbox(
                "Venue",
                options=list(ground_by_key.keys()),
                index=None,
                placeholder="Select ground (Sportmonks venue missing)…",
                format_func=lambda key: ground_by_key[key]["label"],
                key=f"venue_picker_{day_iso}_{fid}",
                help="Type to search known cricket grounds. Uses coordinates from the ground library.",
            )
            if picked_key:
                manual_ground = ground_by_key[picked_key]
                st.caption(
                    f"Library coords: {manual_ground['lat']:.4f}, {manual_ground['lon']:.4f}"
                )
    elif col_venue is not None:
        with col_venue:
            st.empty()

    has_stored_coords = bool(fid and _day_match_has_coords(picked, fid))
    open_disabled = fid is None or (
        needs_venue and manual_ground is None and not has_stored_coords
    )
    with col_open:
        if st.button("Open chart", type="primary", disabled=open_disabled):
            tab_id = _tab_id(day_iso, fid)
            if _find_open_chart(tab_id) is None:
                entry = _load_chart_entry(picked, fixture, manual_ground=manual_ground)
                if entry is not None:
                    st.session_state.open_charts.append(entry)
                    st.session_state.active_tab_id = entry["tab_id"]
                    _persist_open_tabs()
                    st.rerun()
            else:
                st.session_state.active_tab_id = tab_id
                _persist_open_tabs()
                st.toast(f"{fixture_tab_label(fixture)} is already open.")

    with col_opts:
        st.checkbox("Auto-refresh scores 15s", value=False, key="auto_refresh")
        if st.session_state.open_charts and st.button("Close all"):
            st.session_state.open_charts = []
            st.session_state.active_tab_id = None
            _persist_open_tabs()
            st.rerun()

    open_charts: List[Dict[str, Any]] = st.session_state.open_charts
    if not open_charts:
        if not fixture_ids:
            st.info("No fixtures for this date. Pick another day or try again later.")
        elif needs_venue and fid is not None and manual_ground is None and not has_stored_coords:
            st.info(
                "Sportmonks did not provide a venue for this match. "
                "Select a ground from **Venue**, then click **Open chart**."
            )
        else:
            st.info("Select a match and click **Open chart** to load it.")
        return

    if st.session_state.active_tab_id is None:
        st.session_state.active_tab_id = open_charts[0]["tab_id"]
    _persist_open_tabs()

    _render_tab_selector(open_charts)

    chart = _active_chart()
    if chart is None:
        return

    _render_active_chart(chart, auto_refresh=st.session_state.auto_refresh)


if __name__ == "__main__":
    main()
