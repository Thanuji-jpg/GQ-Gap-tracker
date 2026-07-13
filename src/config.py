"""
Athlete / BQ target configuration.

Fill AGE_ON_RACE_DAY before treating the verdict as final.
Gender is taken from Strava (F → Women) unless overridden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional


GenderCategory = Literal["Men", "Women", "Non-binary"]


@dataclass(frozen=True)
class AthleteConfig:
    # Age on Boston 2027 race day (approx. April 19, 2027). FILL THIS IN.
    age_on_race_day: int = 24

    # Override Strava sex if needed. None = derive from Strava athlete.json.
    gender_override: Optional[GenderCategory] = None

    # Qualifying race (optional). Leave blank if still choosing.
    qualifying_race_name: Optional[str] = None
    qualifying_race_date: Optional[date] = None

    # Net downhill of the qualifying course in feet (0 if flat / unknown).
    # BAA 2027+: ≥1500 ft net drop gets a time penalty on the submitted result.
    course_net_downhill_ft: float = 0.0

    # Buffer under the bare BQ standard for a "safe" acceptance target (seconds).
    # Recent cutoffs have run ~4:34–6:51 faster than the published standard.
    safe_buffer_seconds: int = 6 * 60

    # Boston Marathon race day used for age / runway calculations.
    boston_race_day: date = date(2027, 4, 19)

    # End of the qualifying window if no specific race is chosen
    # (BAA typically: mid-Sep year-2 through mid-Sep year-1; use race day as horizon).
    qualifying_window_end: date = date(2027, 4, 19)


def gender_from_strava_sex(sex: Optional[str]) -> GenderCategory:
    if not sex:
        return "Women"  # conservative default only if unknown
    s = sex.strip().upper()
    if s == "M":
        return "Men"
    if s == "F":
        return "Women"
    return "Non-binary"


CONFIG = AthleteConfig()
