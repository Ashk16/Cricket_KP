"""Streamlit display for live KP dashboard (mirrors KP_AI_astrologer layout)."""

from __future__ import annotations

from typing import List, Optional

import pandas as pd
import streamlit as st

from astro.analysis_engine import AnalysisEngine
from astro.kp_engine import KPEngine, PlanetNameUtils
from live.dashboard.styling import color_planets, color_timeline_planets_by_score, styler_map
from timeutils import to_ist


def _utc_value_to_ist_str(value) -> str:
    """Format a naive-UTC timestamp as an IST clock time (HH:MM:SS)."""
    if pd.isna(value):
        return ""
    if isinstance(value, str) and len(value) <= 8 and ":" in value:
        return value
    dt = pd.to_datetime(value, utc=True).to_pydatetime().replace(tzinfo=None)
    return to_ist(dt).strftime("%H:%M:%S")


def _format_ist_times(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("Start Time", "End Time"):
        if col in out.columns:
            out[col] = out[col].apply(_utc_value_to_ist_str)
    rename = {"Start Time": "Start (IST)", "End Time": "End (IST)"}
    return out.rename(columns={k: v for k, v in rename.items() if k in out.columns})


def _retro_name(planet_short, planets_df, planet_full_index):
    if pd.isna(planet_short):
        return planet_short
    full = PlanetNameUtils.to_full_name(PlanetNameUtils.to_short_name(str(planet_short)))
    if full in planet_full_index and "is_retrograde" in planets_df.columns:
        return PlanetNameUtils.standardize_for_display(
            planet_short, bool(planets_df.loc[full, "is_retrograde"])
        )
    return planet_short


def _planet_score_lookup(planets_df: pd.DataFrame) -> dict:
    return {
        PlanetNameUtils.to_short_name(p): planets_df.loc[p, "Score"] for p in planets_df.index
    }


def display_venue_info(results: dict) -> None:
    """Venue name and coordinates above muhurta."""
    md = results.get("match_details", {})
    venue = md.get("venue_name") or "Unknown venue"
    lat, lon = md.get("lat"), md.get("lon")
    lat_s = f"{lat:.4f}" if lat is not None else "—"
    lon_s = f"{lon:.4f}" if lon is not None else "—"
    st.markdown(f"**Venue:** {venue} &nbsp;|&nbsp; **Lat:** {lat_s} &nbsp;|&nbsp; **Lon:** {lon_s}")


def display_chart_header(results: dict) -> None:
    md = results.get("match_details", {})
    anchor_utc = md.get("chart_anchor_utc")
    anchor_ist = ""
    if anchor_utc is not None:
        anchor_dt = pd.to_datetime(anchor_utc, utc=True).to_pydatetime().replace(tzinfo=None)
        anchor_ist = to_ist(anchor_dt).strftime("%Y-%m-%d %H:%M:%S")
    duration = md.get("duration_hours", 9)
    st.info(
        f"Chart anchor: **{anchor_ist} IST** ({anchor_utc} UTC) | "
        f"Timeline span: **{duration:.0f}h** | "
        f"Status: **{md.get('match_status', '-')}** | "
        f"Delay correction: **{md.get('delay_sec', 35)}s** after burst treatment"
    )


def display_static_chart(results: dict) -> None:
    """Muhurta, cusps, and planetary table — stable between live refreshes."""
    if results.get("error"):
        st.error("Analysis error")
        st.code(results.get("traceback", str(results["error"])))
        return

    display_chart_header(results)
    display_venue_info(results)
    md = results.get("match_details", {})

    st.header("Authentic KP Muhurta Chart Analysis")
    muhurta = results.get("muhurta_analysis", {})
    if isinstance(muhurta, dict):
        if muhurta.get("final_verdict"):
            st.success(muhurta["final_verdict"].get("verdict", ""))
            st.metric("11th Cusp Strength", f"{muhurta['final_verdict'].get('eleventh_cusp_strength', 0):.2f}")
        promise = muhurta.get("promise_test", {})
        if promise.get("analysis"):
            rows = []
            for cusp_key, data in promise["analysis"].items():
                strength = data["strength_data"]
                rows.append({
                    "Cusp": cusp_key,
                    "Sub Lord": data["sub_lord"],
                    "Score": data["score"],
                    "Classification": strength["classification"],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
            st.metric("Total Promise Score", f"{promise.get('total_score', 0):.2f}")

    st.subheader("Cusp Details (All 12 Houses)")
    cusps_df = results.get("cusps_df")
    if cusps_df is not None and not cusps_df.empty:
        disp = cusps_df[["longitude", "sign", "sign_lord", "nl", "sl", "ssl"]].copy()
        disp.columns = ["Longitude", "Sign", "Sign Lord", "NL", "SL", "SSL"]
        disp["Longitude"] = disp["Longitude"].apply(
            lambda x: f"{int(x)}°{int((x % 1) * 60):02d}'" if pd.notna(x) else ""
        )
        try:
            engine = KPEngine(
                md["datetime_utc"], md["lat"], md["lon"], ayanamsa=md.get("ayanamsa", "KRISHNAMURTI")
            )
            ae = AnalysisEngine(engine, md["team_a"], md["team_b"])
            sl_sigs = []
            for cusp_num in disp.index:
                sl_short = disp.loc[cusp_num, "SL"]
                sigs = ae.get_significators(PlanetNameUtils.to_full_name(sl_short))
                groups = {1: [], 2: [], 3: [], 4: []}
                for h, r in sigs:
                    groups[r].append(h)
                parts = []
                for rule in (1, 2, 3, 4):
                    if groups[rule]:
                        parts.append(f"R{rule}:{','.join(str(h) for h in sorted(set(groups[rule])))}")
                sl_sigs.append(" | ".join(parts))
            disp["SL Significators"] = sl_sigs
        except Exception:
            disp["SL Significators"] = ""
        disp.index.name = "Cusp"
        st.dataframe(disp, use_container_width=True)

    st.subheader("Planetary Positions & Scores")
    planets_df = results["planets_df"].copy()
    base_cols = [c for c in planets_df.columns if c not in ("is_retrograde",)]
    order = [c for c in base_cols if c not in ("Score", "Significators", "Comment")]
    order += ["Score", "Significators", "Comment"]
    reordered = planets_df.reindex(columns=[c for c in order if c in planets_df.columns])
    styler = reordered.style.apply(lambda col: col.map(color_planets), subset=["Score"])
    planet_colors = {p: color_planets(s) for p, s in reordered["Score"].items()}
    styler = styler.apply(
        lambda col: pd.Series([planet_colors.get(idx, "") for idx in col.index], index=col.index),
        axis=0,
    )
    st.dataframe(styler.format({"Score": "{:.2f}"}), use_container_width=True)


def _format_kp_score_column(show: pd.DataFrame) -> pd.DataFrame:
    """Rename astro Score to KP Score; rename Verdict (match score) to Score."""
    out = show.copy()
    if "Score" in out.columns:
        out = out.rename(columns={"Score": "KP Score"})
        out["KP Score"] = out["KP Score"].apply(
            lambda x: f"{float(x):+.3f}" if pd.notna(x) and str(x).strip() != "" else ""
        )
    if "Verdict" in out.columns:
        out = out.rename(columns={"Verdict": "Score"})
    return out


def _timeline_column_order(show: pd.DataFrame, planet_cols: list) -> pd.DataFrame:
    base = [c for c in ["Start (IST)", "End (IST)"] + planet_cols if c in show.columns]
    extra = [c for c in ["KP Score", "Score", "Comment"] if c in show.columns]
    return show[base + extra].copy()


def _render_timeline_table(
    show: pd.DataFrame,
    planet_cols: list,
    planet_scores: dict,
    *,
    styled: bool,
    height: int = 400,
) -> None:
    if styled and planet_cols:
        styler = styler_map(
            show.style,
            lambda x: color_timeline_planets_by_score(x, planet_scores),
            subset=[c for c in planet_cols if c in show.columns],
        )
        st.dataframe(styler, use_container_width=True, height=height)
    else:
        st.dataframe(show, use_container_width=True, height=height, hide_index=True)


def _timeline_show_df(
    df: pd.DataFrame,
    planets_df: pd.DataFrame,
    planet_cols: list,
) -> pd.DataFrame:
    """Format IST times, retro labels, and score column for a timeline table."""
    if df is None or df.empty:
        return df
    out = _format_ist_times(df)
    for col in planet_cols:
        if col in out.columns:
            out[col] = out[col].apply(lambda x: _retro_name(x, planets_df, planets_df.index))
    out = _format_kp_score_column(out)
    return _timeline_column_order(out, planet_cols)


def display_ball_score_tables(results: dict, *, styled: bool = False) -> None:
    """Moon SSL + SSSL ball stats — optimized for frequent live score refresh."""
    if results.get("error"):
        return

    md = results.get("match_details", {})
    planets_df = results["planets_df"]
    planet_scores = _planet_score_lookup(planets_df)

    moon_df = results.get("moon_timeline_df")
    if moon_df is not None and not moon_df.empty:
        st.markdown("**Moon SSL** — balls, runs, RR, wickets, boundaries per period")
        show = _timeline_show_df(
            moon_df, planets_df, ["NL_Planet", "SL_Planet", "SSL_Planet"]
        )
        _render_timeline_table(
            show,
            ["NL_Planet", "SL_Planet", "SSL_Planet"],
            planet_scores,
            styled=styled,
        )

    detailed = results.get("detailed_timelines") or {}
    sssl = detailed.get("sssl_timeline")
    if sssl is not None and not sssl.empty:
        st.markdown("**Moon SSSL** — balls, runs, RR, wickets, boundaries per period")
        show = _timeline_show_df(
            sssl,
            planets_df,
            ["NL_Planet", "SL_Planet", "SSL_Planet", "SSSL_Planet"],
        )
        _render_timeline_table(
            show,
            [c for c in show.columns if c.endswith("_Planet")],
            planet_scores,
            styled=styled,
            height=320,
        )


def display_timeline_sections(results: dict, *, styled: bool = True) -> None:
    """Collapsed Asc NL/SL + Moon SSL / Moon SSSL tables."""
    if results.get("error"):
        return

    md = results.get("match_details", {})
    planets_df = results["planets_df"]
    planet_scores = _planet_score_lookup(planets_df)

    with st.expander("Ascendant Timeline (NL & SL Analysis)", expanded=False):
        asc_df = results.get("asc_timeline_df")
        if asc_df is not None and not asc_df.empty:
            asc_df = _format_ist_times(asc_df)
            for col in ("NL_Planet", "SL_Planet"):
                if col in asc_df.columns:
                    asc_df[col] = asc_df[col].apply(
                        lambda x: _retro_name(x, planets_df, planets_df.index)
                    )
            show = _format_kp_score_column(asc_df)
            show = _timeline_column_order(show, ["NL_Planet", "SL_Planet"])
            styler = styler_map(
                show.style,
                lambda x: color_timeline_planets_by_score(x, planet_scores),
                subset=[c for c in ("NL_Planet", "SL_Planet") if c in show.columns],
            )
            st.dataframe(styler, use_container_width=True, height=400)
            if results.get("asc_timeline_analysis"):
                st.caption(results["asc_timeline_analysis"].get("summary", ""))
        else:
            st.info("Ascendant timeline not available")

    st.subheader("Moon SSL Timeline - Enhanced Dynamic Full Granular Detail")
    moon_df = results.get("moon_timeline_df")
    if moon_df is not None and not moon_df.empty:
        show = _timeline_show_df(
            moon_df, planets_df, ["NL_Planet", "SL_Planet", "SSL_Planet"]
        )
        _render_timeline_table(
            show,
            ["NL_Planet", "SL_Planet", "SSL_Planet"],
            planet_scores,
            styled=styled,
        )
        if results.get("moon_timeline_analysis"):
            st.write(results["moon_timeline_analysis"].get("summary", ""))
    else:
        st.info("Moon SSL timeline not available")

    detailed = results.get("detailed_timelines") or {}
    sssl = detailed.get("sssl_timeline")
    if sssl is not None and not sssl.empty:
        st.subheader("Moon SSSL Timeline - Full Detailed Analysis (NL-SL-SSL-SSSL)")
        show = _timeline_show_df(
            sssl,
            planets_df,
            ["NL_Planet", "SL_Planet", "SSL_Planet", "SSSL_Planet"],
        )
        _render_timeline_table(
            show,
            [c for c in show.columns if c.endswith("_Planet")],
            planet_scores,
            styled=styled,
        )


def display_live_analysis(results: dict) -> None:
    """Full page render (static chart + timelines)."""
    display_static_chart(results)
    display_timeline_sections(results)
