"""
Training diagnostics that explain the fitness trend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from .bq_standards import MILE_METERS


@dataclass
class DiagnosticAnnotation:
    week_start: pd.Timestamp
    kind: str
    text: str


@dataclass
class Diagnostics:
    weekly: pd.DataFrame
    annotations: List[DiagnosticAnnotation] = field(default_factory=list)
    consistency_notes: List[str] = field(default_factory=list)
    hr_efficiency: Optional[pd.DataFrame] = None

    def narrative(self) -> str:
        lines = ["=== Training diagnostics ==="]
        lines.extend(self.consistency_notes)
        if self.annotations:
            lines.append("Key annotations:")
            for a in self.annotations:
                lines.append(f"  • {a.week_start.date()}: {a.text}")
        else:
            lines.append("No major mileage/consistency shocks flagged.")
        if self.hr_efficiency is None or self.hr_efficiency.empty:
            lines.append("Aerobic efficiency (pace-per-HR): unavailable (no HR data).")
        else:
            lines.append(
                f"Aerobic efficiency series computed on {len(self.hr_efficiency)} easy-effort runs."
            )
        return "\n".join(lines)


def weekly_mileage(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby("week_start", dropna=True)
        .agg(
            miles=("distance_m", lambda s: float(s.sum()) / MILE_METERS),
            n_runs=("id", "count"),
            longest_mi=("distance_m", lambda s: float(s.max()) / MILE_METERS),
        )
        .reset_index()
        .sort_values("week_start")
    )
    return g


def consistency_gaps(df: pd.DataFrame) -> List[str]:
    notes = []
    d = df.sort_values("start_date")
    if len(d) < 2:
        return ["Fewer than 2 runs — consistency not assessed."]
    dates = d["start_date"].tolist()
    gaps = []
    for a, b in zip(dates, dates[1:]):
        gap_days = (b - a).days
        if gap_days > 7:
            gaps.append((a, b, gap_days))
    if not gaps:
        notes.append("No gaps >7 days between consecutive runs.")
    else:
        notes.append(f"{len(gaps)} training gap(s) >7 days:")
        for a, b, g in gaps[:8]:
            notes.append(f"  • {a.date()} → {b.date()} ({g} days)")
        if len(gaps) > 8:
            notes.append(f"  • … and {len(gaps) - 8} more")
    return notes


def annotate_mileage_shocks(weekly: pd.DataFrame) -> List[DiagnosticAnnotation]:
    """Flag sudden mileage drops / stalls that can explain flat fitness."""
    ann: List[DiagnosticAnnotation] = []
    if len(weekly) < 4:
        return ann
    miles = weekly["miles"].values
    weeks = weekly["week_start"].tolist()
    # rolling median baseline
    for i in range(3, len(weekly)):
        baseline = np.median(miles[max(0, i - 4) : i])
        if baseline >= 8 and miles[i] < 0.5 * baseline:
            ann.append(
                DiagnosticAnnotation(
                    week_start=weeks[i],
                    kind="mileage_drop",
                    text=(
                        f"Mileage drop to {miles[i]:.1f} mi "
                        f"(prior ~4-week median {baseline:.1f} mi) — "
                        "possible illness/injury/life interruption."
                    ),
                )
            )
        # long-run regression
        if i >= 1 and weekly["longest_mi"].iloc[i] < 0.6 * weekly["longest_mi"].iloc[max(0, i - 3) : i].max():
            prev_long = weekly["longest_mi"].iloc[max(0, i - 3) : i].max()
            if prev_long >= 8:
                ann.append(
                    DiagnosticAnnotation(
                        week_start=weeks[i],
                        kind="long_run_drop",
                        text=(
                            f"Longest run fell to {weekly['longest_mi'].iloc[i]:.1f} mi "
                            f"from recent {prev_long:.1f} mi peak."
                        ),
                    )
                )
    # de-dupe same week
    seen = set()
    uniq = []
    for a in ann:
        key = (a.week_start, a.kind)
        if key not in seen:
            seen.add(key)
            uniq.append(a)
    return uniq


def easy_hr_efficiency(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pace-per-HR on easy efforts as a secondary aerobic signal.
    Lower sec/m per bpm ≈ more efficient (faster at same HR).
    Easy heuristic: efforts below median pace (slower) with HR present,
    distance 3–12 km (not race-like).
    """
    d = df.dropna(subset=["average_hr", "pace_sec_per_m"]).copy()
    if d.empty:
        return pd.DataFrame()
    # slower half ≈ easier
    med = d["pace_sec_per_m"].median()
    easy = d[
        (d["pace_sec_per_m"] >= med * 0.95)
        & (d["distance_m"] >= 3000)
        & (d["distance_m"] <= 14000)
        & (d["average_hr"] > 0)
    ].copy()
    if easy.empty:
        return pd.DataFrame()
    easy["pace_per_hr"] = easy["pace_sec_per_m"] / easy["average_hr"]
    return easy[["start_date", "pace_sec_per_m", "average_hr", "pace_per_hr", "distance_m"]].sort_values(
        "start_date"
    )


def build_diagnostics(df: pd.DataFrame) -> Diagnostics:
    weekly = weekly_mileage(df)
    notes = consistency_gaps(df)
    if not weekly.empty:
        notes.append(
            f"Weekly mileage range: {weekly['miles'].min():.1f}–{weekly['miles'].max():.1f} mi "
            f"(median {weekly['miles'].median():.1f})."
        )
        notes.append(
            f"Long-run progression peak: {weekly['longest_mi'].max():.1f} mi "
            f"(latest week {weekly['longest_mi'].iloc[-1]:.1f} mi)."
        )
    ann = annotate_mileage_shocks(weekly)
    hr = easy_hr_efficiency(df)
    return Diagnostics(weekly=weekly, annotations=ann, consistency_notes=notes, hr_efficiency=hr)
