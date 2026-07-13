"""
Pace / race equivalency models.

- Riegel: T2 = T1 * (D2/D1)^1.06
- Jack Daniels VDOT (published continuous formulas, not a hardcoded lookup table)

Daniels VDOT (from "Daniels' Running Formula"):
  Percent VO2max for a race lasting t minutes:
    %VO2 = 0.8 + 0.1894393 * exp(-0.012778 * t) + 0.2989558 * exp(-0.1932605 * t)
  VO2 cost of velocity v (m/min):
    VO2 = -4.60 + 0.182258 * v + 0.000104 * v^2
  VDOT = VO2 / %VO2

Training paces from VDOT use Daniels intensity %VO2 targets, solved for velocity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

from .bq_standards import MARATHON_METERS, MILE_METERS, format_hms, format_pace_min_per_mile

RIEGEL_EXPONENT = 1.06


def riegel_predict(time_s: float, distance_m: float, target_m: float = MARATHON_METERS) -> float:
    """Predict time at target_m given an effort of time_s over distance_m."""
    if time_s <= 0 or distance_m <= 0:
        raise ValueError("time and distance must be positive")
    return time_s * (target_m / distance_m) ** RIEGEL_EXPONENT


def marathon_pace_sec_per_m(marathon_time_s: float) -> float:
    return marathon_time_s / MARATHON_METERS


def _pct_vo2_at_duration_min(t_min: float) -> float:
    return (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t_min)
        + 0.2989558 * math.exp(-0.1932605 * t_min)
    )


def _vo2_cost(v_m_per_min: float) -> float:
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min**2


def vdot_from_race(distance_m: float, time_s: float) -> float:
    """Daniels VDOT from a race performance."""
    t_min = time_s / 60.0
    v = (distance_m / time_s) * 60.0  # m/min
    return _vo2_cost(v) / _pct_vo2_at_duration_min(t_min)


def _velocity_for_vo2(vo2: float) -> float:
    """Invert VO2 cost equation for velocity (m/min); take positive root."""
    # 0.000104 v^2 + 0.182258 v + (-4.60 - vo2) = 0
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    disc = b * b - 4 * a * c
    return (-b + math.sqrt(disc)) / (2 * a)


def _pace_at_intensity(vdot: float, intensity: float) -> float:
    """Return seconds per meter at a given fraction of VDOT."""
    v = _velocity_for_vo2(vdot * intensity)  # m/min
    return 60.0 / v  # sec/m


@dataclass(frozen=True)
class TrainingPaces:
    vdot: float
    easy_sec_per_m: float
    marathon_sec_per_m: float
    tempo_sec_per_m: float
    interval_sec_per_m: float

    def as_min_per_mile(self) -> Dict[str, str]:
        return {
            "easy": format_pace_min_per_mile(self.easy_sec_per_m),
            "marathon": format_pace_min_per_mile(self.marathon_sec_per_m),
            "tempo": format_pace_min_per_mile(self.tempo_sec_per_m),
            "interval": format_pace_min_per_mile(self.interval_sec_per_m),
        }


def training_paces_from_marathon_time(marathon_time_s: float) -> TrainingPaces:
    """
    Derive supporting paces from a goal marathon time via VDOT.

    Intensity anchors (Daniels approximate %VO2):
      Easy ~59–74% → use 70%
      Marathon ~80–85% → use 84%
      Threshold/Tempo ~88%
      Interval ~98%
    """
    vdot = vdot_from_race(MARATHON_METERS, marathon_time_s)
    return TrainingPaces(
        vdot=vdot,
        easy_sec_per_m=_pace_at_intensity(vdot, 0.70),
        marathon_sec_per_m=marathon_pace_sec_per_m(marathon_time_s),
        tempo_sec_per_m=_pace_at_intensity(vdot, 0.88),
        interval_sec_per_m=_pace_at_intensity(vdot, 0.98),
    )


def describe_target_paces(standard_s: float, safe_s: float) -> dict:
    std_paces = training_paces_from_marathon_time(standard_s)
    safe_paces = training_paces_from_marathon_time(safe_s)
    return {
        "standard_time": format_hms(standard_s),
        "standard_marathon_pace": format_pace_min_per_mile(std_paces.marathon_sec_per_m),
        "standard_training": std_paces.as_min_per_mile(),
        "standard_vdot": round(std_paces.vdot, 1),
        "safe_time": format_hms(safe_s),
        "safe_marathon_pace": format_pace_min_per_mile(safe_paces.marathon_sec_per_m),
        "safe_training": safe_paces.as_min_per_mile(),
        "safe_vdot": round(safe_paces.vdot, 1),
    }
