"""
Load and clean local Strava activity data.

Units convention (consistent everywhere):
  - distance: meters
  - time: seconds
  - pace: seconds per meter (sec/m)
  - display helpers also expose min/mile
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .bq_standards import MILE_METERS, format_pace_min_per_mile

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}

# Plausible moving pace bounds for GPS-glitch detection (sec/m).
# ~3:00/mi ≈ 0.1119 sec/m; ~20:00/mi ≈ 0.7458 sec/m
PACE_MIN_SEC_PER_M = (3 * 60) / MILE_METERS
PACE_MAX_SEC_PER_M = (20 * 60) / MILE_METERS

# Drop tiny "runs" that aren't useful for fitness estimation
MIN_DISTANCE_M = 800.0
MIN_MOVING_TIME_S = 120.0


@dataclass
class DataQualityReport:
    n_raw_activities: int = 0
    n_runs: int = 0
    date_min: Optional[pd.Timestamp] = None
    date_max: Optional[pd.Timestamp] = None
    pct_with_hr: float = 0.0
    n_missing_pace: int = 0
    n_missing_hr: int = 0
    n_pace_outliers: int = 0
    n_short_excluded: int = 0
    notes: List[str] = field(default_factory=list)

    def summary_text(self) -> str:
        lines = [
            "=== Data quality summary ===",
            f"Raw activities loaded: {self.n_raw_activities}",
            f"Running activities kept: {self.n_runs}",
        ]
        if self.date_min is not None and self.date_max is not None:
            lines.append(
                f"Date range: {self.date_min.date()} → {self.date_max.date()}"
            )
        lines.append(f"% of runs with average HR: {self.pct_with_hr:.1f}%")
        lines.append(f"Runs missing pace (no distance or moving time): {self.n_missing_pace}")
        lines.append(f"Runs missing HR: {self.n_missing_hr}")
        lines.append(f"Implausible pace outliers flagged: {self.n_pace_outliers}")
        lines.append(f"Short runs excluded from fitness modeling (<{MIN_DISTANCE_M:.0f} m): {self.n_short_excluded}")
        for n in self.notes:
            lines.append(f"Note: {n}")
        return "\n".join(lines)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_data_path() -> Path:
    return _project_root() / "data" / "activities_raw.json"


def _normalize_activity(raw: Dict[str, Any]) -> Dict[str, Any]:
    distance = float(raw.get("distance") or 0.0)
    moving = float(raw.get("moving_time") or 0.0)
    elapsed = float(raw.get("elapsed_time") or 0.0)
    elev = float(raw.get("total_elevation_gain") or 0.0)
    avg_speed = raw.get("average_speed")  # m/s

    pace = None
    if moving > 0 and distance > 0:
        pace = moving / distance
    elif avg_speed and float(avg_speed) > 0:
        pace = 1.0 / float(avg_speed)

    hr = raw.get("average_heartrate")
    start = pd.to_datetime(raw.get("start_date_local") or raw.get("start_date"), utc=True)

    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "type": raw.get("type") or raw.get("sport_type"),
        "sport_type": raw.get("sport_type") or raw.get("type"),
        "start_date": start,
        "distance_m": distance,
        "moving_time_s": moving,
        "elapsed_time_s": elapsed,
        "elevation_gain_m": elev,
        "pace_sec_per_m": pace,
        "average_hr": float(hr) if hr is not None else None,
        "has_heartrate": bool(raw.get("has_heartrate")) and hr is not None,
        "workout_type": raw.get("workout_type"),
    }


def load_raw_activities(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = Path(path) if path else default_data_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No activity file at {path}. Run: python -m src.strava_sync"
        )
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        return df.to_dict(orient="records")
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "activities" in data:
        return data["activities"]
    if not isinstance(data, list):
        raise ValueError(f"Unexpected JSON shape in {path}")
    return data


def load_runs(
    path: Optional[Path] = None,
    *,
    exclude_pace_outliers_from_fitness: bool = True,
) -> Tuple[pd.DataFrame, DataQualityReport]:
    """
    Load activities, filter to runs, parse units, flag missing/outlier values.

    Outliers and missing HR are flagged, not silently dropped from the dataframe.
    Fitness modeling should use the `use_for_fitness` column.
    """
    raw = load_raw_activities(path)
    report = DataQualityReport(n_raw_activities=len(raw))

    rows = []
    for a in raw:
        t = a.get("type") or a.get("sport_type")
        if t not in RUN_TYPES:
            continue
        rows.append(_normalize_activity(a))

    if not rows:
        report.notes.append("No running activities found.")
        return pd.DataFrame(), report

    df = pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)
    report.n_runs = len(df)
    report.date_min = df["start_date"].min()
    report.date_max = df["start_date"].max()

    missing_pace = df["pace_sec_per_m"].isna()
    report.n_missing_pace = int(missing_pace.sum())
    if report.n_missing_pace:
        report.notes.append(
            f"{report.n_missing_pace} run(s) missing pace — kept in table, excluded from fitness."
        )

    missing_hr = df["average_hr"].isna()
    report.n_missing_hr = int(missing_hr.sum())
    report.pct_with_hr = 100.0 * (1.0 - report.n_missing_hr / len(df))
    if report.pct_with_hr == 0:
        report.notes.append(
            "No average heart-rate data present — aerobic-efficiency diagnostic will be skipped."
        )

    pace_ok = df["pace_sec_per_m"].notna()
    outlier = pace_ok & (
        (df["pace_sec_per_m"] < PACE_MIN_SEC_PER_M)
        | (df["pace_sec_per_m"] > PACE_MAX_SEC_PER_M)
    )
    df["pace_outlier"] = outlier
    report.n_pace_outliers = int(outlier.sum())
    if report.n_pace_outliers:
        samples = df.loc[outlier, ["start_date", "name", "distance_m", "moving_time_s", "pace_sec_per_m"]].head(5)
        for _, r in samples.iterrows():
            p = format_pace_min_per_mile(r["pace_sec_per_m"]) if pd.notna(r["pace_sec_per_m"]) else "?"
            report.notes.append(
                f"Pace outlier: {r['start_date'].date()} '{r['name']}' → {p}"
            )

    short = (df["distance_m"] < MIN_DISTANCE_M) | (df["moving_time_s"] < MIN_MOVING_TIME_S)
    report.n_short_excluded = int(short.sum())

    df["use_for_fitness"] = (
        df["pace_sec_per_m"].notna()
        & ~short
        & (~df["pace_outlier"] if exclude_pace_outliers_from_fitness else True)
    )

    df["distance_mi"] = df["distance_m"] / MILE_METERS
    df["pace_min_per_mi"] = df["pace_sec_per_m"].apply(
        lambda x: (x * MILE_METERS / 60.0) if pd.notna(x) else None
    )
    # Week buckets in UTC, timezone-naive timestamps for clean weekly joins
    utc_dates = df["start_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    df["week_start"] = utc_dates.dt.to_period("W-SUN").dt.start_time

    return df, report


def print_quality_report(report: DataQualityReport) -> None:
    print(report.summary_text())


if __name__ == "__main__":
    runs, rep = load_runs()
    print_quality_report(rep)
    print()
    print(runs[["start_date", "name", "distance_mi", "pace_min_per_mi", "average_hr", "use_for_fitness"]].to_string(index=False))
