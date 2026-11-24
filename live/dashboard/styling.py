"""Color styling ported from KP_AI_astrologer main_dashboard."""

from __future__ import annotations

import pandas as pd

from astro.kp_engine import PlanetNameUtils


def styler_map(styler, func, **kwargs):
    if hasattr(styler, "map"):
        return styler.map(func, **kwargs)
    return styler.applymap(func, **kwargs)


def color_planets(val):
    if not isinstance(val, (int, float)) or pd.isna(val):
        return ""
    opacity = min(1.0, max(0.2, abs(val) / 3.0))
    green = "rgba(0, 128, 0, {opacity})"
    red = "rgba(255, 0, 0, {opacity})"
    if val > 0:
        return f"background-color: {green.format(opacity=opacity)}"
    if val < 0:
        return f"background-color: {red.format(opacity=opacity)}"
    return ""


def color_timeline_planets_by_score(planet_short_name, planet_scores):
    if pd.isna(planet_short_name):
        return ""
    lookup = str(planet_short_name).replace("(R)", "").strip()
    lookup = PlanetNameUtils.to_full_name(PlanetNameUtils.to_short_name(lookup))
    short = PlanetNameUtils.to_short_name(lookup)
    if short not in planet_scores:
        return ""
    return color_planets(planet_scores[short])


def color_verdict_cell(verdict_text, team_a_name="Team A", team_b_name="Team B"):
    if pd.isna(verdict_text):
        return ""
    v = str(verdict_text).lower()
    asc = team_a_name.lower()
    desc = team_b_name.lower()
    if "strong advantage" in v:
        if asc in v:
            return "background-color: #008000; color: white; font-weight: bold"
        if desc in v:
            return "background-color: #ff0000; color: white; font-weight: bold"
    if "advantage" in v or "favor" in v or "supports" in v:
        if asc in v:
            return "background-color: rgba(0, 128, 0, 0.5); color: #004000; font-weight: 500"
        if desc in v:
            return "background-color: rgba(255, 0, 0, 0.5); color: #800000; font-weight: 500"
    if "balanced" in v:
        return "background-color: #e0e0e0; color: #333; font-weight: 400"
    return ""
