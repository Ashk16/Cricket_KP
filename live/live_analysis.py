"""Run KP analysis for live dashboard (same output shape as KP_AI_astrologer)."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any, Dict, List, Optional

import pandas as pd

from astro.analysis_engine import AnalysisEngine
from astro.kp_engine import KPEngine
from astro.timeline_generator import TimelineGenerator
from live.ball_order import ball_event_cricket_key
from live.ball_timestamp_treatment import ball_alignment_utc
from live.match_setup import batting_team_for_innings


def _as_naive_utc(value) -> Optional[pd.Timestamp]:
    """Normalize timestamps for safe bisect comparisons."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, utc=True)
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


DEFAULT_HOUSE_WEIGHTS = {
    1: 0.5, 2: 0.2, 3: 0.3, 4: -0.2, 5: -0.8, 6: 1.0, 7: -0.6, 8: -1.0,
    9: 0.3, 10: 0.7, 11: 0.9, 12: -0.9,
}
DEFAULT_TIMELINE_WEIGHTS = {
    "ssl_timeline": {"NL": 0.1, "SL": 0.2, "SSL": 0.7},
    "asc_timeline": {"NL": 0.2, "SL": 0.3, "Context": 0.5},
}


def run_live_analysis(
    match_details: Dict[str, Any],
    *,
    house_weights: Optional[dict] = None,
    timeline_weights: Optional[dict] = None,
) -> Dict[str, Any]:
    """Mirror ``run_analysis`` from KP_AI_astrologer main_dashboard."""
    try:
        ayanamsa = match_details.get("ayanamsa", "KRISHNAMURTI")
        engine_dt = match_details["datetime_utc"]
        if hasattr(engine_dt, "tzinfo") and engine_dt.tzinfo:
            engine_dt = engine_dt.replace(tzinfo=None)

        engine = KPEngine(
            dt=engine_dt,
            lat=match_details["lat"],
            lon=match_details["lon"],
            ayanamsa=ayanamsa,
        )
        hw = house_weights or DEFAULT_HOUSE_WEIGHTS.copy()
        tw = timeline_weights or DEFAULT_TIMELINE_WEIGHTS.copy()
        analysis_engine = AnalysisEngine(
            engine,
            match_details["team_a"],
            match_details["team_b"],
            house_weights=hw,
            timeline_weights=tw,
        )

        muhurta_analysis = analysis_engine.analyze_muhurta_chart(scoring_method="authentic_kp")
        planets_df = analysis_engine.get_all_planet_details_df()
        cusps_df = engine.get_all_cusps_df()

        asc_gen = TimelineGenerator(engine, "Ascendant")
        asc_df = asc_gen.generate_aggregated_timeline_df(
            engine_dt, match_details["duration_hours"]
        )
        asc_df, asc_analysis = analysis_engine.analyze_aggregated_timeline(asc_df, "ascendant")

        moon_gen = TimelineGenerator(engine, "Moon")
        moon_df = moon_gen.generate_timeline_df(engine_dt, match_details["duration_hours"])
        moon_df, moon_analysis = analysis_engine.analyze_timeline(moon_df, "ascendant")

        detailed = moon_gen.generate_detailed_timeline_df(engine_dt, match_details["duration_hours"])
        analyzed_detailed = analysis_engine.analyze_detailed_timeline(detailed, "ascendant")

        return {
            "muhurta_analysis": muhurta_analysis,
            "planets_df": planets_df,
            "cusps_df": cusps_df,
            "asc_timeline_df": asc_df,
            "asc_timeline_analysis": asc_analysis,
            "moon_timeline_df": moon_df,
            "moon_timeline_analysis": moon_analysis,
            "detailed_timelines": analyzed_detailed,
            "match_details": match_details,
            "error": None,
            "traceback": None,
        }
    except Exception as exc:  # noqa: BLE001
        import traceback

        return {"error": exc, "traceback": traceback.format_exc()}


def _sorted_balls_for_stats(balls) -> tuple[List, List]:
    """Balls with alignment UTC, sorted by time (for window scans)."""
    ordered: List = []
    for b in balls:
        ts = _as_naive_utc(ball_alignment_utc(b))
        if ts is None:
            continue
        ordered.append((ts.to_pydatetime(), b))
    ordered.sort(key=lambda item: item[0])
    balls_only = [b for _, b in ordered]
    times = [t for t, _ in ordered]
    return balls_only, times


def _batting_team_id(
    innings_number: int,
    match_details: Dict[str, Any],
    *,
    innings_batting_team_id: Optional[int] = None,
) -> Optional[int]:
    return batting_team_for_innings(
        innings_number,
        localteam_id=match_details.get("localteam_id"),
        visitorteam_id=match_details.get("visitorteam_id"),
        toss_won_team_id=match_details.get("toss_won_team_id"),
        toss_elected=match_details.get("toss_elected"),
        innings_batting_team_id=innings_batting_team_id,
    )


def _team_short_name(team_id: Optional[int], match_details: Dict[str, Any]) -> str:
    if team_id == match_details.get("localteam_id"):
        raw = str(match_details.get("team_a_short") or "A")
    elif team_id == match_details.get("visitorteam_id"):
        raw = str(match_details.get("team_b_short") or "B")
    else:
        return "?"
    if raw.isupper() and len(raw) <= 4:
        return raw.title()
    return raw


def _innings_totals_at_ball(ball) -> tuple[int, int]:
    if ball.score_after is not None and ball.wickets_after is not None:
        return int(ball.score_after), int(ball.wickets_after)
    return 0, 0


def _format_overs(over: Optional[int], ball: Optional[int]) -> str:
    if over is None and ball is None:
        return "0.0"
    return f"{over or 0}.{ball or 0}"


def period_match_score(
    balls,
    start_utc,
    end_utc,
    match_details: Dict[str, Any],
    innings_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
) -> str:
    """Cumulative innings score at the last ball in a timeline period."""
    ordered, times = _sorted_balls_for_stats(balls)
    lo = bisect_left(times, start_utc)
    hi = bisect_right(times, end_utc)
    in_window = ordered[lo:hi]
    if not in_window:
        return ""

    last = in_window[-1]
    innings_info = (innings_by_id or {}).get(last.innings_id, {})
    inn_num = innings_info.get("innings_number") or 1
    bat_id = _batting_team_id(
        inn_num,
        match_details,
        innings_batting_team_id=innings_info.get("batting_team_id"),
    )
    short = _team_short_name(bat_id, match_details)

    last_key = ball_event_cricket_key(last)
    # Recompute through this delivery when stored running totals are missing.
    if last.score_after is None or last.wickets_after is None:
        inn_balls = [
            b
            for b in balls
            if b.innings_id == last.innings_id
            and ball_event_cricket_key(b) <= last_key
        ]
        inn_balls.sort(key=ball_event_cricket_key)
        runs = sum((b.runs or 0) + (b.extras or 0) for b in inn_balls)
        wkts = sum(1 for b in inn_balls if b.is_wicket)
    else:
        runs, wkts = _innings_totals_at_ball(last)

    overs = _format_overs(last.over, last.ball)
    return f"{short}: {runs}/{wkts} in {overs} overs"


def period_ball_summary(balls, start_utc, end_utc) -> str:
    """Summarise ball activity in a timeline period (corrected UTC).

    Metrics: total balls, runs, run rate (per over), wickets, boundaries (4s+6s).
    """
    ordered, times = _sorted_balls_for_stats(balls)
    lo = bisect_left(times, start_utc)
    hi = bisect_right(times, end_utc)
    in_window = ordered[lo:hi]
    if not in_window:
        return "0 balls, 0 runs, RR 0.0, 0 wkts, 0 bdry"

    n_balls = len(in_window)
    runs = sum(b.runs or 0 for b in in_window)
    wickets = sum(1 for b in in_window if b.is_wicket)
    boundaries = sum(1 for b in in_window if b.is_four or b.is_six)
    rr = (runs / n_balls * 6.0) if n_balls else 0.0
    w_label = "wkt" if wickets == 1 else "wkts"
    b_label = "bdry" if boundaries == 1 else "bdry"
    return (
        f"{n_balls} balls, {runs} runs, RR {rr:.1f}, "
        f"{wickets} {w_label}, {boundaries} {b_label}"
    )


# Backward-compatible alias
ssl_ball_summary = period_ball_summary


def _attach_ball_stats_to_timeline(
    timeline_df: pd.DataFrame,
    balls,
    *,
    match_details: Optional[Dict[str, Any]] = None,
    innings_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    only_with_balls: bool = False,
) -> pd.DataFrame:
    """Attach ball metrics (Comment) and match score (Verdict column) per period."""
    if timeline_df is None or timeline_df.empty:
        return timeline_df

    ordered, times = _sorted_balls_for_stats(balls)
    df = timeline_df.copy()
    summaries = []
    match_scores = []
    keep_mask = []
    md = match_details or {}
    for _, row in df.iterrows():
        start = _as_naive_utc(row["Start Time"])
        end = _as_naive_utc(row["End Time"])
        if start is None or end is None:
            summaries.append("0 balls, 0 runs, RR 0.0, 0 wkts, 0 bdry")
            match_scores.append("")
            keep_mask.append(False)
            continue
        start = start.to_pydatetime()
        end = end.to_pydatetime()
        lo = bisect_left(times, start)
        hi = bisect_right(times, end)
        in_window = ordered[lo:hi]
        if in_window:
            n_balls = len(in_window)
            runs = sum(b.runs or 0 for b in in_window)
            wickets = sum(1 for b in in_window if b.is_wicket)
            boundaries = sum(1 for b in in_window if b.is_four or b.is_six)
            rr = (runs / n_balls * 6.0) if n_balls else 0.0
            w_label = "wkt" if wickets == 1 else "wkts"
            summary = (
                f"{n_balls} balls, {runs} runs, RR {rr:.1f}, "
                f"{wickets} {w_label}, {boundaries} bdry"
            )
            keep_mask.append(True)
            match_scores.append(period_match_score(balls, start, end, md, innings_by_id))
        else:
            summary = "0 balls, 0 runs, RR 0.0, 0 wkts, 0 bdry"
            match_scores.append("")
            keep_mask.append(False)
        summaries.append(summary)
    df["Comment"] = summaries
    if "Comment_Clean" in df.columns:
        df["Comment_Clean"] = summaries
    df["Verdict"] = match_scores
    if only_with_balls:
        df = df.loc[keep_mask].copy()
    return df


def attach_ssl_ball_stats(
    timeline_df: pd.DataFrame,
    balls,
    chart_anchor_utc=None,
    *,
    match_details: Optional[Dict[str, Any]] = None,
    innings_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """Replace SSL-level Comment with ball summaries and Verdict with match score."""
    return _attach_ball_stats_to_timeline(
        timeline_df,
        balls,
        match_details=match_details,
        innings_by_id=innings_by_id,
    )


def attach_sssl_ball_stats(
    detailed_timelines: dict,
    balls,
    *,
    match_details: Optional[Dict[str, Any]] = None,
    innings_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
) -> dict:
    """Replace SSSL-level Comment with ball summaries and Verdict with match score."""
    if not detailed_timelines:
        return detailed_timelines

    out = dict(detailed_timelines)
    sssl = out.get("sssl_timeline")
    if sssl is not None and not sssl.empty:
        out["sssl_timeline"] = _attach_ball_stats_to_timeline(
            sssl,
            balls,
            match_details=match_details,
            innings_by_id=innings_by_id,
        )
    return out


def apply_all_ball_stats(
    results: dict,
    balls,
    *,
    innings_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
) -> dict:
    """Attach period ball metrics and match scores to Asc/Moon timelines."""
    import copy

    out = copy.copy(results)
    md = out.get("match_details") or {}
    asc = out.get("asc_timeline_df")
    if asc is not None:
        out["asc_timeline_df"] = attach_ssl_ball_stats(
            asc, balls, match_details=md, innings_by_id=innings_by_id
        )
    moon = out.get("moon_timeline_df")
    if moon is not None:
        out["moon_timeline_df"] = attach_ssl_ball_stats(
            moon, balls, match_details=md, innings_by_id=innings_by_id
        )
    detailed = out.get("detailed_timelines")
    if detailed:
        out["detailed_timelines"] = attach_sssl_ball_stats(
            detailed, balls, match_details=md, innings_by_id=innings_by_id
        )
    return out
