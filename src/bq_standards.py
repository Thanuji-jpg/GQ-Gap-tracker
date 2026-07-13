"""
Boston Marathon qualifying standards (BAA), safe-buffer target,
and 2027+ net-downhill course penalties.

Source: BAA published standards confirmed current as of July 2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence, Tuple

GenderCategory = Literal["Men", "Women", "Non-binary"]

# (min_age_inclusive, max_age_inclusive, men_seconds, women_nonbinary_seconds)
BQ_STANDARDS: Sequence[Tuple[int, int, int, int]] = (
    (18, 34, 2 * 3600 + 55 * 60, 3 * 3600 + 25 * 60),
    (35, 39, 3 * 3600 + 0 * 60, 3 * 3600 + 30 * 60),
    (40, 44, 3 * 3600 + 5 * 60, 3 * 3600 + 35 * 60),
    (45, 49, 3 * 3600 + 15 * 60, 3 * 3600 + 45 * 60),
    (50, 54, 3 * 3600 + 20 * 60, 3 * 3600 + 50 * 60),
    (55, 59, 3 * 3600 + 30 * 60, 4 * 3600 + 0 * 60),
    (60, 64, 3 * 3600 + 50 * 60, 4 * 3600 + 20 * 60),
    (65, 69, 4 * 3600 + 5 * 60, 4 * 3600 + 35 * 60),
    (70, 74, 4 * 3600 + 20 * 60, 4 * 3600 + 50 * 60),
    (75, 79, 4 * 3600 + 35 * 60, 5 * 3600 + 5 * 60),
    (80, 200, 4 * 3600 + 50 * 60, 5 * 3600 + 20 * 60),
)

MARATHON_METERS = 42195.0
MILE_METERS = 1609.344

# 2027+ BAA net-downhill index penalties applied to the submitted result.
# (min_ft_inclusive, max_ft_inclusive, penalty_seconds); None max = open-ended DQ.
DOWNHILL_PENALTIES: Sequence[Tuple[float, float | None, int | None]] = (
    (0.0, 1499.999, 0),
    (1500.0, 2999.999, 5 * 60),
    (3000.0, 5999.999, 10 * 60),
    (6000.0, None, None),  # disqualified
)


@dataclass(frozen=True)
class BQTarget:
    age: int
    gender: GenderCategory
    age_group_label: str
    standard_seconds: int
    safe_buffer_seconds: int
    safe_target_seconds: int
    downhill_penalty_seconds: int
    downhill_disqualified: bool

    @property
    def effective_standard_seconds(self) -> int:
        """Bare standard — downhill penalty is applied to the race result, not the bar."""
        return self.standard_seconds

    @property
    def effective_safe_target_seconds(self) -> int:
        return self.safe_target_seconds


def _age_group(age: int) -> Tuple[int, int, int, int]:
    for lo, hi, men, women in BQ_STANDARDS:
        if lo <= age <= hi:
            return lo, hi, men, women
    raise ValueError(f"Age {age} is outside BQ table (need ≥18).")


def downhill_penalty_seconds(net_downhill_ft: float) -> Tuple[int, bool]:
    """
    Return (penalty_seconds, is_disqualified) for a course's net elevation drop.
    Penalty is added to the submitted finish time under 2027+ rules.
    """
    drop = max(0.0, float(net_downhill_ft))
    for lo, hi, pen in DOWNHILL_PENALTIES:
        if drop < lo:
            continue
        if hi is None or drop <= hi:
            if pen is None:
                return 0, True
            return int(pen), False
    return 0, False


def resolve_bq_target(
    age: int,
    gender: GenderCategory,
    safe_buffer_seconds: int = 6 * 60,
    course_net_downhill_ft: float = 0.0,
) -> BQTarget:
    lo, hi, men, women = _age_group(age)
    label = f"{lo}-{hi}" if hi < 200 else f"{lo}+"
    standard = men if gender == "Men" else women
    penalty, dq = downhill_penalty_seconds(course_net_downhill_ft)
    safe = max(0, standard - int(safe_buffer_seconds))
    return BQTarget(
        age=age,
        gender=gender,
        age_group_label=label,
        standard_seconds=standard,
        safe_buffer_seconds=int(safe_buffer_seconds),
        safe_target_seconds=safe,
        downhill_penalty_seconds=penalty,
        downhill_disqualified=dq,
    )


def format_hms(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(abs(s), 3600)
    m, sec = divmod(rem, 60)
    sign = "-" if s < 0 else ""
    return f"{sign}{h}:{m:02d}:{sec:02d}"


def format_pace_min_per_mile(seconds_per_meter: float) -> str:
    sec_per_mile = seconds_per_meter * MILE_METERS
    m, s = divmod(int(round(sec_per_mile)), 60)
    return f"{m}:{s:02d} /mi"
