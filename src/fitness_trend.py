"""
Rolling equivalent-marathon fitness time series and BQ gap projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .bq_standards import MARATHON_METERS, format_hms
from .pace_models import riegel_predict

# Efforts that meaningfully inform marathon fitness (meters).
# Shorter than ~5K is noisy for marathon projection; still allow ≥3K with lower weight.
MIN_EFFORT_M = 3000.0
LONG_RUN_M = 16000.0  # ~10 mi
TEMPOISH_M = 5000.0


def _effort_weight(distance_m: float) -> float:
    """Longer efforts get more weight; races/long runs dominate."""
    if distance_m >= LONG_RUN_M:
        return 1.0
    if distance_m >= TEMPOISH_M:
        return 0.75
    if distance_m >= MIN_EFFORT_M:
        return 0.45
    return 0.0


def per_run_marathon_equiv(df: pd.DataFrame) -> pd.DataFrame:
    """Add Riegel marathon-equivalent time for each fitness-eligible run."""
    out = df.copy()
    eqs = []
    weights = []
    for _, r in out.iterrows():
        if not r.get("use_for_fitness", False):
            eqs.append(np.nan)
            weights.append(0.0)
            continue
        d, t = float(r["distance_m"]), float(r["moving_time_s"])
        w = _effort_weight(d)
        weights.append(w)
        if w <= 0 or t <= 0:
            eqs.append(np.nan)
        else:
            eqs.append(riegel_predict(t, d, MARATHON_METERS))
    out["marathon_equiv_s"] = eqs
    out["effort_weight"] = weights
    return out


def weekly_fitness_series(
    df: pd.DataFrame,
    *,
    lookback_weeks: int = 4,
) -> pd.DataFrame:
    """
    For each week, estimate current marathon fitness as the weighted best
    (fastest) Riegel-equivalent among efforts in a rolling lookback window.

    Using the best recent efforts (not the mean) matches how race fitness
    is usually judged: what you can do when you push, not your easy-day average.
    """
    work = per_run_marathon_equiv(df)
    work = work.dropna(subset=["marathon_equiv_s"])
    if work.empty:
        return pd.DataFrame(columns=["week_start", "pred_marathon_s", "n_efforts", "best_source"])

    work = work.sort_values("start_date")
    weeks = sorted(work["week_start"].dropna().unique())
    rows = []
    lookback = timedelta(weeks=lookback_weeks)

    for w in weeks:
        w_ts = pd.Timestamp(w)
        if w_ts.tzinfo is None:
            w_ts = w_ts.tz_localize("UTC")
        window_start = w_ts - lookback + timedelta(days=1)
        window_end = w_ts + timedelta(days=7)
        mask = (work["start_date"] >= window_start) & (work["start_date"] < window_end)
        chunk = work.loc[mask]
        if chunk.empty:
            continue

        # Score: lower marathon equiv is better; prefer higher weight.
        # Effective time = equiv / weight^0.15 so long runs slightly favored at equal pace quality.
        scored = chunk.copy()
        scored["score"] = scored["marathon_equiv_s"] / np.power(scored["effort_weight"].clip(0.2), 0.15)
        best = scored.loc[scored["score"].idxmin()]
        # Also take top-2 weighted average if multiple solid efforts
        top = scored.nsmallest(min(3, len(scored)), "score")
        wts = top["effort_weight"].values
        preds = top["marathon_equiv_s"].values
        if wts.sum() > 0:
            pred = float(np.average(preds, weights=wts))
        else:
            pred = float(best["marathon_equiv_s"])

        rows.append(
            {
                "week_start": w_ts,
                "pred_marathon_s": pred,
                "n_efforts": int(len(chunk)),
                "best_source": f"{best['start_date'].date()} {best['name']} ({best['distance_m']/1000:.1f} km)",
            }
        )

    return pd.DataFrame(rows)


@dataclass
class ProjectionResult:
    slope_sec_per_week: float
    intercept_s: float
    n_weeks_fit: int
    fit_start: Optional[pd.Timestamp]
    fit_end: Optional[pd.Timestamp]
    crosses_standard_on: Optional[date]
    crosses_safe_on: Optional[date]
    trend_direction: str  # improving / flat / worsening
    r_squared: float
    message: str


def _fit_recent_trend(
    series: pd.DataFrame,
    *,
    recent_weeks: int = 14,
) -> Tuple[np.ndarray, np.ndarray, float, float, float]:
    """Return x (week index), y, slope, intercept, r^2 for recent window."""
    s = series.dropna(subset=["pred_marathon_s"]).sort_values("week_start").tail(recent_weeks)
    if len(s) < 3:
        raise ValueError("Need at least 3 weekly fitness points to fit a trend.")
    x0 = s["week_start"].iloc[0]
    x = np.array([(t - x0).days / 7.0 for t in s["week_start"]], dtype=float)
    y = s["pred_marathon_s"].values.astype(float)
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return x, y, float(slope), float(intercept), r2


def project_gap(
    series: pd.DataFrame,
    standard_s: float,
    safe_s: float,
    *,
    recent_weeks: int = 14,
    horizon_date: Optional[date] = None,
) -> ProjectionResult:
    """
    Fit a linear trend to recent weekly predicted marathon times and find
    when (if ever) the trend crosses the BQ standard / safe target.
    """
    try:
        x, y, slope, intercept, r2 = _fit_recent_trend(series, recent_weeks=recent_weeks)
    except ValueError as e:
        return ProjectionResult(
            slope_sec_per_week=0.0,
            intercept_s=float("nan"),
            n_weeks_fit=0,
            fit_start=None,
            fit_end=None,
            crosses_standard_on=None,
            crosses_safe_on=None,
            trend_direction="unknown",
            r_squared=0.0,
            message=str(e),
        )

    s = series.dropna(subset=["pred_marathon_s"]).sort_values("week_start").tail(recent_weeks)
    fit_start, fit_end = s["week_start"].iloc[0], s["week_start"].iloc[-1]

    # Negative slope = getting faster = improving
    if slope < -15:  # >15 sec/week faster
        direction = "improving"
    elif slope > 15:
        direction = "worsening"
    else:
        direction = "flat"

    def crossing(target: float) -> Optional[date]:
        if slope >= -1e-6:
            # Not improving — only "crosses" if already under
            if y[-1] <= target:
                return fit_end.date() if hasattr(fit_end, "date") else fit_end
            return None
        # intercept + slope * w = target → w = (target - intercept) / slope
        w = (target - intercept) / slope
        if w < x[-1]:
            # Already crossed in-sample or before end of fit
            if y[-1] <= target:
                return fit_end.date() if hasattr(fit_end, "date") else fit_end
            # Slope says we crossed earlier but latest point is still above — noisy
            return None
        cross = fit_start + timedelta(weeks=float(w))
        return cross.date() if hasattr(cross, "date") else cross

    cross_std = crossing(standard_s)
    cross_safe = crossing(safe_s)

    parts: List[str] = []
    parts.append(
        f"Recent {len(s)}-week trend: {format_hms(abs(slope))}/week "
        f"{'faster' if slope < 0 else 'slower'} (R²={r2:.2f})."
    )
    if direction == "improving":
        if cross_safe:
            parts.append(f"At this rate, projected to hit the safe target around {cross_safe}.")
        elif cross_std:
            parts.append(
                f"Projected to hit the bare BQ standard around {cross_std}, "
                "but not the buffered safe target on the current slope."
            )
        else:
            parts.append("Improving, but the current slope does not reach either target in a reasonable extrapolation.")
    elif direction == "flat":
        parts.append("Trend is essentially flat — no reliable crossing date.")
    else:
        parts.append("Fitness trend is moving the wrong way — not projecting a hopeful crossing date.")

    if horizon_date and direction == "improving" and slope < 0:
        weeks_left = (horizon_date - (fit_end.date() if hasattr(fit_end, "date") else fit_end)).days / 7.0
        projected = y[-1] + slope * max(0.0, weeks_left)
        parts.append(
            f"By {horizon_date}, trend projects ~{format_hms(projected)} "
            f"(gap to standard: {format_hms(projected - standard_s)})."
        )

    return ProjectionResult(
        slope_sec_per_week=slope,
        intercept_s=intercept,
        n_weeks_fit=len(s),
        fit_start=fit_start,
        fit_end=fit_end,
        crosses_standard_on=cross_std,
        crosses_safe_on=cross_safe,
        trend_direction=direction,
        r_squared=r2,
        message=" ".join(parts),
    )


def feasibility(
    series: pd.DataFrame,
    projection: ProjectionResult,
    standard_s: float,
    safe_s: float,
    horizon: date,
    *,
    realistic_max_improvement_sec_per_week: float = 45.0,
) -> str:
    """Plain-language race-day / window feasibility verdict."""
    if series.empty:
        return "Insufficient run data to judge BQ feasibility."

    latest = float(series.dropna(subset=["pred_marathon_s"]).iloc[-1]["pred_marathon_s"])
    today = date.today()
    weeks_left = max(0.0, (horizon - today).days / 7.0)
    gap_std = latest - standard_s
    gap_safe = latest - safe_s

    lines = [
        f"Current predicted marathon fitness: {format_hms(latest)}.",
        f"Gap to BQ standard ({format_hms(standard_s)}): {format_hms(gap_std)} "
        f"({'already under' if gap_std <= 0 else 'to close'}).",
        f"Gap to safe target ({format_hms(safe_s)}): {format_hms(gap_safe)}.",
        f"Time remaining until {horizon}: {weeks_left:.1f} weeks.",
    ]

    if gap_safe <= 0:
        lines.append("VERDICT: Already at/under the safe target on current fitness estimate.")
        return "\n".join(lines)
    if gap_std <= 0:
        lines.append(
            "VERDICT: At/under the bare standard, but still short of the buffered safe target "
            "used for acceptance cushion."
        )
        return "\n".join(lines)

    if weeks_left <= 0:
        lines.append("VERDICT: Qualifying horizon has passed; use the latest fitness estimate as the snapshot.")
        return "\n".join(lines)

    needed_per_week = gap_safe / weeks_left
    lines.append(
        f"To reach the safe target by {horizon}, need ~{format_hms(needed_per_week)} "
        f"improvement per week."
    )
    lines.append(
        f"Recent trend: {format_hms(abs(projection.slope_sec_per_week))}/week "
        f"{'faster' if projection.slope_sec_per_week < 0 else 'slower'} "
        f"({projection.trend_direction})."
    )

    if projection.trend_direction == "improving" and projection.crosses_safe_on:
        if projection.crosses_safe_on <= horizon:
            lines.append(
                f"VERDICT: ON TRACK for the safe target — trend crosses around "
                f"{projection.crosses_safe_on}, before {horizon}."
            )
        else:
            lines.append(
                f"VERDICT: IMPROVING but LATE — crossing ~{projection.crosses_safe_on}, "
                f"after {horizon}. Bare standard "
                f"{'by ' + str(projection.crosses_standard_on) if projection.crosses_standard_on else 'not clearly reached'}."
            )
    elif needed_per_week <= realistic_max_improvement_sec_per_week and projection.trend_direction != "worsening":
        lines.append(
            f"VERDICT: POSSIBLE BUT AGGRESSIVE — required rate "
            f"({format_hms(needed_per_week)}/wk) is within a stretch zone "
            f"(≤{format_hms(realistic_max_improvement_sec_per_week)}/wk), "
            "but current trend does not yet show it."
        )
    else:
        lines.append(
            "VERDICT: NOT ON TRACK — required improvement rate exceeds what the recent "
            "training pattern supports, or fitness is flat/worsening."
        )

    return "\n".join(lines)
