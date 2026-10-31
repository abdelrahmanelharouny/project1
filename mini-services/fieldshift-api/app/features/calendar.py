"""Calendar and timezone basis for feature aggregation (Milestone 4).

Every aggregation is explicit about its calendar:

- A target timezone (the farm's zone by default) defines LOCAL calendar days.
- A daily observation is assigned to the local date containing the MIDPOINT of
  its observation period. For UTC-anchored daily data (Open-Meteo, CSV import,
  synthetic fixtures) this is the local day that holds the majority of the
  observation's 24 h window — deterministic, never a silent day shift.
- Monthly periods are local calendar months; seasons are meteorological
  seasons of the configured hemisphere (DJF/MAM/JJA/SON, north by default;
  'south' swaps DJF<->JJA and MAM<->SON).
- The basis (timezone, hemisphere, assignment rule) is recorded on every run
  and echoed into feature provenance, so aggregations are reproducible and
  auditable rather than implicit.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MONTHS_IN_SEASON = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}

CALENDAR_ASSIGNMENT_RULE = "period_midpoint_local_date"


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 — mapped to validation by the caller
        raise ValueError(f"Unknown calendar timezone '{name}'.") from exc


def day_bounds_utc(local_day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC interval [start, next-start) of a local calendar day."""
    start = datetime(local_day.year, local_day.month, local_day.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def assign_local_date(period_start: datetime, period_end: datetime, tz: ZoneInfo) -> date:
    """Local date that contains the midpoint of the observation period.

    Daily UTC-anchored observations map to the local day holding the majority
    of their window; multi-day periods (pentads/months) are not assigned by
    this helper — aggregation works on their explicit bounds instead.
    """
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    midpoint = period_start.astimezone(tz) + (
        period_end.astimezone(tz) - period_start.astimezone(tz)
    ) / 2
    return midpoint.date()


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def month_bounds_utc(year: int, month: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC interval [start, next-start) of a local calendar month."""
    start = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=tz)
    return start.astimezone(timezone.utc), nxt.astimezone(timezone.utc)


def month_end_utc(year: int, month: int, tz: ZoneInfo) -> datetime:
    _, nxt = month_bounds_utc(year, month, tz)
    return nxt - timedelta(seconds=1)


def season_of(day: date, hemisphere: str = "north") -> str:
    """Meteorological season label of a local date ('DJF','MAM','JJA','SON')."""
    month = day.month
    if month in (12, 1, 2):
        season = "DJF"
    elif month in (3, 4, 5):
        season = "MAM"
    elif month in (6, 7, 8):
        season = "JJA"
    else:
        season = "SON"
    if hemisphere == "south":
        swap = {"DJF": "JJA", "JJA": "DJF", "MAM": "SON", "SON": "MAM"}
        season = swap[season]
    return season


def season_label(day: date, hemisphere: str = "north") -> str:
    """Season label including the (shifted) label year.

    For DJF the season spans a year boundary; the label year is the year of
    the season's majority months (Jan/Feb -> previous year's DJF).
    """
    season = season_of(day, hemisphere)
    year = day.year
    if season == "DJF" and day.month != 12:
        year -= 1
    return f"{year:04d}-{season}"


def season_month_range(label_year: int, season: str) -> list[tuple[int, int]]:
    """(year, month) pairs covered by a season label (DJF wraps years)."""
    months = MONTHS_IN_SEASON[season]
    result = []
    for m in months:
        if m == 12:
            result.append((label_year, 12))
        elif season == "DJF":
            result.append((label_year + 1, m))
        else:
            result.append((label_year, m))
    return result


def season_bounds_utc(label: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC interval of a season label like '2023-JJA' or '2023-DJF'."""
    year_s, season = label.split("-")
    label_year = int(year_s)
    pairs = season_month_range(label_year, season)
    start_year, start_month = pairs[0]
    start = datetime(start_year, start_month, 1, tzinfo=tz).astimezone(timezone.utc)
    last_year, last_month = pairs[-1]
    _, nxt = month_bounds_utc(last_year, last_month, tz)
    return start, nxt


def iter_months(start: date, end: date) -> list[tuple[int, int]]:
    """Calendar months overlapping [start, end], inclusive, in order."""
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months
