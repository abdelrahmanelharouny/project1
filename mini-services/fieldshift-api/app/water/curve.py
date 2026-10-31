"""FAO-56 single-Kc curve (Milestone 6A — Phase 1/2).

The curve is RECONSTRUCTED from the three sourced anchors (initial, mid, late)
and the four sourced stage lengths (init/dev/mid/late, FAO-56 Table 11) using
the FAO-56 construction: constant Kc_ini through the initial stage, a linear
ramp across the development stage from Kc_ini to Kc_mid, constant Kc_mid
through the mid-season stage, and a linear ramp across the late stage from
Kc_mid to Kc_end. This is the FAO-56 methodology itself (ch. 6, Fig. 34/35) —
not an interpolation invented for this platform.

Dual-Kc (Kcb + Ke) is REFUSED: the knowledge base holds no Kcb rows, and
fabricating them is forbidden (the schema accepts kc_method='dual' rows but
the loader will not produce a curve from them).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

STAGES: tuple[str, ...] = ("initial", "development", "mid", "late")
STAGE_LENGTH_TRAITS: dict[str, str] = {
    "initial": "stage_init_days",
    "development": "stage_dev_days",
    "mid": "stage_mid_days",
    "late": "stage_late_days",
}


class KcCurveError(ValueError):
    """The curve cannot be built from the supplied knowledge (honest refusal)."""


@dataclass(frozen=True)
class KcCurve:
    """Single-Kc curve over the crop season, indexed by DAY SINCE SOWING (0-based)."""

    lengths: tuple[int, int, int, int]          # init, dev, mid, late (days)
    kc_initial: float
    kc_mid: float
    kc_late: float
    source_key: str
    citation_text: str
    evidence_class: str
    pack_code: str
    pack_version: str

    @property
    def total_days(self) -> int:
        return sum(self.lengths)

    def stage_bounds(self) -> tuple[tuple[str, int, int], ...]:
        """(stage, first_day_index, last_day_index) inclusive bounds."""
        out: list[tuple[str, int, int]] = []
        start = 0
        for stage, length in zip(STAGES, self.lengths):
            out.append((stage, start, start + length - 1))
            start += length
        return tuple(out)

    def stage_of_day(self, day_index: int) -> str:
        for stage, lo, hi in self.stage_bounds():
            if lo <= day_index <= hi:
                return stage
        if day_index < 0:
            raise KcCurveError("day index before sowing")
        raise KcCurveError(
            f"day index {day_index} beyond the curve length {self.total_days}"
        )

    def kc_on_day(self, day_index: int) -> float:
        """FAO-56 single-Kc value at day_index (0 = sowing day).

        Days beyond the digitized curve hold the late-stage (end) Kc — the
        curve ends at crop maturity, and a season window longer than the
        curve keeps the end value (the same convention the M5 screening
        estimator used, preserved for coefficient stability)."""
        init_len, dev_len, mid_len, late_len = self.lengths
        if day_index < 0:
            raise KcCurveError("day index before sowing")
        if day_index < init_len:
            return self.kc_initial
        if day_index < init_len + dev_len:
            t = (day_index - init_len) / max(dev_len, 1)
            return self.kc_initial + t * (self.kc_mid - self.kc_initial)
        if day_index < init_len + dev_len + mid_len:
            return self.kc_mid
        if day_index < self.total_days:
            t = (day_index - init_len - dev_len - mid_len) / max(late_len, 1)
            t = min(max(t, 0.0), 1.0)
            return self.kc_mid + t * (self.kc_late - self.kc_mid)
        return self.kc_late

    def mean_kc(self, start_index: int, end_index: int) -> float:
        """Mean Kc over the INCLUSIVE day-index window [start_index, end_index]."""
        if end_index < start_index:
            raise KcCurveError("empty window")
        total = 0.0
        for day in range(start_index, end_index + 1):
            total += self.kc_on_day(day)
        return total / (end_index - start_index + 1)


def build_curve(
    *,
    stage_lengths: dict[str, float | None],
    kc_initial: float,
    kc_mid: float,
    kc_late: float,
    source_key: str,
    citation_text: str,
    evidence_class: str,
    pack_code: str,
    pack_version: str,
) -> KcCurve:
    """Validate and assemble the curve. Every stage length must be present —
    a partial stage set is an honest refusal, never a zero-filled stage."""
    lengths: list[int] = []
    for stage in STAGES:
        raw = stage_lengths.get(stage)
        if raw is None:
            raise KcCurveError(
                f"stage length for '{stage}' missing from the knowledge base — "
                "the curve is not reconstructed from partial stage data"
            )
        value = int(raw)
        if value <= 0:
            raise KcCurveError(
                f"stage length for '{stage}' must be a positive day count (got {raw})"
            )
        lengths.append(value)
    for name, kc in (("initial", kc_initial), ("mid", kc_mid), ("late", kc_late)):
        if kc is None or not math.isfinite(kc) or kc < 0 or kc > 3:
            raise KcCurveError(f"Kc anchor '{name}' out of the valid range [0, 3]: {kc}")
    return KcCurve(
        lengths=(lengths[0], lengths[1], lengths[2], lengths[3]),
        kc_initial=kc_initial,
        kc_mid=kc_mid,
        kc_late=kc_late,
        source_key=source_key,
        citation_text=citation_text,
        evidence_class=evidence_class,
        pack_code=pack_code,
        pack_version=pack_version,
    )


# --------------------------------------------------------------------- ETc


def daily_etc_mm(et0_mm: float, kc: float) -> float:
    """ETc = Kc × ET0 for one day (FAO-56 Eq. 60/62 basis). Reference ET0 and
    crop ETc are kept conceptually distinct by the callers' labels."""
    if et0_mm < 0 or kc < 0:
        raise KcCurveError("negative ET0 or Kc")
    return kc * et0_mm


def season_months(start: date, end: date) -> list[tuple[int, int]]:
    """Calendar months (year, month) covered by [start, end]."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_days_in_season(start: date, end: date, year: int, month: int) -> tuple[date, date, int]:
    """(first_day, last_day, n_days) of the month's overlap with the season."""
    import calendar as cal

    first = max(start, date(year, month, 1))
    last = min(end, date(year, month, cal.monthrange(year, month)[1]))
    return first, last, (last - first).days + 1


def season_etc_by_day(
    curve: KcCurve,
    start: date,
    end: date,
    sowing_date: date,
    monthly_et0: tuple[tuple[int, int, float], ...],
) -> tuple[list[float], list[str], list[str]]:
    """Daily ETc series for the season window.

    Temporal alignment: the Kc curve is indexed by days since SOWING. Days of
    the season window BEFORE the sowing date have no crop in the ground —
    their crop ETc is 0 (bare-soil evaporation is dual-Kc territory and is
    NOT claimed; the omission is disclosed by callers when sowing ≠ season
    start). Each calendar day's ET0 comes from its month's climatology total
    divided by the number of days in that calendar month (the screening
    assumption, recorded).

    Returns (etc_by_day, months_used_labels, missing_month_labels).
    A season month WITHOUT ET0 evidence is reported in `missing` — the caller
    refuses the whole estimate (F-07 monotone honesty).
    """
    et0_by_month = {(y, m): v for y, m, v in monthly_et0}
    etc_by_day: list[float] = []
    months_used: list[str] = []
    missing: list[str] = []
    day = start
    while day <= end:
        y, m = day.year, day.month
        key = (y, m)
        if key not in et0_by_month:
            missing.append(f"{y:04d}-{m:02d}")
            etc_by_day.append(float("nan"))
        else:
            # ET0 total divided by the FULL calendar month length (the
            # screening assumption distributes the monthly total uniformly).
            et0_daily = et0_by_month[key] / _days_in_month(y, m)
            day_index = (day - sowing_date).days
            if day_index < 0:
                # before sowing: no crop in the ground — crop ETc = 0
                etc_by_day.append(0.0)
            else:
                etc_by_day.append(daily_etc_mm(et0_daily, curve.kc_on_day(day_index)))
            label = f"{y:04d}-{m:02d}"
            if label not in months_used:
                months_used.append(label)
        day += timedelta(days=1)
    return etc_by_day, months_used, missing


def _days_in_month(year: int, month: int) -> int:
    import calendar as cal

    return cal.monthrange(year, month)[1]


def season_etc_mm(
    curve: KcCurve,
    start: date,
    end: date,
    sowing_date: date,
    monthly_et0: tuple[tuple[int, int, float], ...],
) -> tuple[float | None, list[str], list[str]]:
    """Seasonal ETc (mm) = sum of the daily series.

    Monotone honesty (deepening F-07): any season month without ET0 evidence
    refuses the WHOLE estimate — dropping the month would under-report the
    requirement. Returns (mm | None, months_used, missing_months)."""
    series, months_used, missing = season_etc_by_day(
        curve, start, end, sowing_date, monthly_et0
    )
    if missing:
        return None, months_used, missing
    total = sum(v for v in series if not math.isnan(v))
    return round(total, 2), months_used, missing
