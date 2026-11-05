"""Soil-cover timeline engine (M6C Increment 3).

Builds an interval/day-level cover timeline for a field from the evidence
that actually exists:

- `crop_history` sowing/harvest pairs        → living_main_crop intervals
- `cover_crop_plan_items` sowing/termination → living_cover_crop intervals
- `soil_management_events` residue/mulch     → surface_residue / mulch intervals
  (residue_retention opens residue; residue_removal / tillage /
  residue-incorporating events close the open residue interval)
- `soil_cover_observations`                  → dated state/fraction evidence

HONESTY CONTRACT (spec §5):

- Missing evidence is `unknown` — NEVER bare. Bare requires an explicit
  observation or an explicit bare-state evidence (property-tested).
- NDVI-style index values are carried as index values with provenance; there
  is NO conversion to percentage cover (no validated regional model exists).
- Metrics are reported without pass/fail unless a sourced, region-scoped
  threshold applies; none ship with the platform (the thresholds section is
  an honest empty list with an explanation).
- Every day's classification is explainable: the timeline records which
  evidence contributed to each day.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

PROTECTIVE_STATES = frozenset(
    {"living_main_crop", "living_cover_crop", "surface_residue", "mulch"}
)

# Residue-closing events: what ends an open residue/mulch interval.
_RESIDUE_CLOSING_EVENTS = frozenset({"residue_removal", "tillage"})
# Events that open a residue interval (retention) — the ledger's vocabulary.
_RESIDUE_OPENING_EVENTS = frozenset({"residue_retention"})


@dataclass(frozen=True)
class EvidenceInterval:
    """One evidence-backed interval contributing cover state."""

    start: dt.date
    end: dt.date
    state: str
    evidence_class: str
    source_kind: str  # crop_history | cover_crop_plan | management_event | observation
    source_id: str
    label: str | None = None

    def clamp(self, lo: dt.date, hi: dt.date) -> "EvidenceInterval | None":
        s, e = max(self.start, lo), min(self.end, hi)
        if s > e:
            return None
        return EvidenceInterval(s, e, self.state, self.evidence_class, self.source_kind, self.source_id, self.label)


@dataclass
class CoverDay:
    date: dt.date
    states: list[str] = field(default_factory=list)
    classification: str = "unknown"  # protective | bare | unknown
    evidence: list[dict[str, Any]] = field(default_factory=list)


def _intervals_from_crop_history(rows: list[dict[str, Any]]) -> list[EvidenceInterval]:
    out: list[EvidenceInterval] = []
    for row in rows:
        sowing, harvest = row.get("sowing_date"), row.get("harvest_date")
        if not sowing or not harvest:
            # A crop with only one endpoint cannot produce a cover interval —
            # the missing endpoint is a data gap, never assumed.
            continue
        s, e = _as_date(sowing), _as_date(harvest)
        if e < s:
            continue  # malformed pair is ignored (validator prevents this via API)
        out.append(
            EvidenceInterval(s, e, "living_main_crop", row.get("evidence_class", "farmer_reported_record"), "crop_history", row["id"], row.get("crop_label"))
        )
    return out


def _intervals_from_cover_items(rows: list[dict[str, Any]]) -> list[EvidenceInterval]:
    out: list[EvidenceInterval] = []
    for row in rows:
        sowing, termination = row.get("intended_sowing_start"), row.get(
            "intended_termination_window_start"
        )
        # Prefer ACTUAL establishment/termination when present (status-driven);
        # the plan item carries intended windows until events land in the
        # management ledger (Increment 4 wires the events; the timeline reads
        # what exists).
        start = row.get("established_date") or sowing
        end = row.get("terminated_date") or termination
        if not start or not end:
            continue
        s, e = _as_date(start), _as_date(end)
        if e < s:
            continue
        out.append(
            EvidenceInterval(s, e, "living_cover_crop", row.get("evidence_class", "farmer_reported_record"), "cover_crop_plan", row["id"], row.get("crop_label"))
        )
    return out


def _intervals_from_management_events(
    rows: list[dict[str, Any]], window_end: dt.date
) -> tuple[list[EvidenceInterval], list[dict[str, Any]]]:
    """Residue/mulch intervals from the event ledger.

    residue_retention opens a residue interval that stays open until a closing
    event (residue_removal, tillage) or the window end. The OPEN end is
    disclosed as such in the timeline's evidence notes.
    """
    intervals: list[EvidenceInterval] = []
    notes: list[dict[str, Any]] = []
    opens: list[dict[str, Any]] = []
    closers: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: _as_date(r["event_date"])):
        etype = row["event_type"]
        d = _as_date(row["event_date"])
        details = row.get("details") or {}
        if etype in _RESIDUE_OPENING_EVENTS:
            opens.append(row)
        elif etype in _RESIDUE_CLOSING_EVENTS:
            closers.append(row)
        elif etype == "soil_amendment" and details.get("mulch"):
            opens.append({**row, "_state": "mulch"})

    for opener in opens:
        state = opener.get("_state", "surface_residue")
        d = _as_date(opener["event_date"])
        # closes at the FIRST closing event strictly after the opener
        close = next((c for c in closers if _as_date(c["event_date"]) >= d), None)
        end = _as_date(close["event_date"]) if close else window_end
        intervals.append(
            EvidenceInterval(
                d, end, state, "farmer_reported_record", "management_event",
                opener["id"], opener.get("title") or state,
            )
        )
        if close is None:
            notes.append(
                {
                    "note": "residue_interval_open_at_window_end",
                    "event_id": opener["id"],
                    "detail": "no closing event recorded yet; the interval is "
                    "extended to the window end and will follow future events",
                }
            )
    return intervals, notes


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def build_cover_timeline(
    *,
    window_start: dt.date,
    window_end: dt.date,
    crop_history: list[dict[str, Any]],
    cover_crop_items: list[dict[str, Any]],
    management_events: list[dict[str, Any]],
    cover_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic day-level cover timeline + metrics.

    Every input is a plain dict (id-keyed rows) so the engine is unit-testable
    without a database; the API layer maps ORM rows into these.
    """
    if window_end < window_start:
        raise ValueError("window_end before window_start")

    intervals: list[EvidenceInterval] = []
    intervals += _intervals_from_crop_history(crop_history)
    intervals += _intervals_from_cover_items(cover_crop_items)
    event_intervals, open_notes = _intervals_from_management_events(
        management_events, window_end
    )
    intervals += event_intervals

    day_count = (window_end - window_start).days + 1
    days: list[CoverDay] = [
        CoverDay(window_start + dt.timedelta(days=i)) for i in range(day_count)
    ]
    index = {d.date: i for i, d in enumerate(days)}

    # Observation evidence (point measurements) — indexed by date.
    obs_by_date: dict[dt.date, list[dict[str, Any]]] = {}
    for obs in cover_observations:
        obs_by_date.setdefault(_as_date(obs["observed_date"]), []).append(obs)

    for iv in intervals:
        clamped = iv.clamp(window_start, window_end)
        if clamped is None:
            continue
        for i in range(index[clamped.start], index[clamped.end] + 1):
            days[i].states.append(clamped.state)
            days[i].evidence.append(
                {
                    "source_kind": clamped.source_kind,
                    "source_id": clamped.source_id,
                    "state": clamped.state,
                    "evidence_class": clamped.evidence_class,
                    "label": clamped.label,
                    "interval": [clamped.start.isoformat(), clamped.end.isoformat()],
                }
            )

    for date, obs_list in obs_by_date.items():
        if date not in index:
            continue
        day = days[index[date]]
        for obs in obs_list:
            state = obs.get("cover_state") or "unknown"
            fraction = obs.get("cover_fraction")
            day.evidence.append(
                {
                    "source_kind": "observation",
                    "source_id": obs["id"],
                    "state": state,
                    "evidence_class": obs.get("evidence_class", "farmer_reported_record"),
                    "measurement_basis": obs.get("measurement_basis", "unknown"),
                    "cover_fraction": fraction,
                    "index_type": obs.get("index_type"),
                    "index_value": obs.get("index_value"),
                }
            )
            if state not in ("unknown", "mixed"):
                day.states.append(state)
            elif state == "mixed":
                day.states.append("mixed")
            # fraction is positive evidence of (some) protective cover even
            # when the qualitative state is unknown; fraction 0 is positive
            # evidence of bareness. Missing fraction + unknown state = unknown.
            if fraction is not None:
                day.states.append("__fraction_positive" if fraction > 0 else "__fraction_zero")

    # Classify each day.
    for day in days:
        protective = bool(PROTECTIVE_STATES & set(day.states)) or (
            "__fraction_positive" in day.states
        )
        explicit_bare = "bare" in day.states or "__fraction_zero" in day.states
        if protective:
            day.classification = "protective"
        elif explicit_bare:
            day.classification = "bare"
        else:
            day.classification = "unknown"

    metrics = _metrics(days, window_start, window_end)
    timeline = [
        {"date": d.date.isoformat(), "states": sorted(set(d.states) - {"__fraction_positive", "__fraction_zero"}), "classification": d.classification}
        for d in days
    ]
    return {
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "timeline": timeline,
        "metrics": metrics,
        "evidence_notes": open_notes,
        "thresholds": {
            "applicable": [],
            "note": (
                "No sourced, region-scoped cover threshold applies to this "
                "field, so no pass/fail classification is reported — metrics "
                "only (spec §5.3). Thresholds must arrive as versioned, "
                "region-scoped knowledge."
            ),
        },
        "method": {
            "engine": "soil-cover-timeline",
            "version": "soil-cover-1.0.0",
            "rules": [
                "unknown is the absence of evidence; bare requires explicit evidence",
                "protective = living_main_crop | living_cover_crop | surface_residue | mulch | measured fraction > 0",
                "residue intervals open on residue_retention and close on the next "
                "residue_removal or tillage event, else extend to window end (disclosed)",
                "index observations are stored as indices; no NDVI→%cover conversion exists",
            ],
        },
    }


def _metrics(days: list[CoverDay], window_start: dt.date, window_end: dt.date) -> dict[str, Any]:
    protective = sum(1 for d in days if d.classification == "protective")
    bare = sum(1 for d in days if d.classification == "bare")
    unknown = sum(1 for d in days if d.classification == "unknown")
    total = len(days)
    assert protective + bare + unknown == total

    longest_bare = 0
    current = 0
    longest_bare_end: dt.date | None = None
    for d in days:
        if d.classification == "bare":
            current += 1
            if current > longest_bare:
                longest_bare = current
                longest_bare_end = d.date
        else:
            current = 0
    longest_bare_start = (
        longest_bare_end - dt.timedelta(days=longest_bare - 1)
        if longest_bare
        else None
    )

    by_state_counts: dict[str, int] = {}
    for d in days:
        for s in set(d.states):
            if not s.startswith("__"):
                by_state_counts[s] = by_state_counts.get(s, 0) + 1

    denominator = protective + bare + unknown
    fraction = round(protective / denominator, 4) if denominator else None
    return {
        "window_days": total,
        "days_protective_cover": protective,
        "days_known_bare": bare,
        "days_unknown": unknown,
        "protective_cover_fraction": fraction,
        "protective_fraction_basis": (
            "protective / (protective + bare + unknown) over the requested "
            "window — unknown days are reported separately, never merged "
            "into bare"
        ),
        "longest_bare_interval_days": longest_bare,
        "longest_bare_interval": (
            [longest_bare_start.isoformat(), longest_bare_end.isoformat()]
            if longest_bare
            else None
        ),
        "state_day_counts": dict(sorted(by_state_counts.items())),
        "month_breakdown": _month_breakdown(days),
    }


def _month_breakdown(days: list[CoverDay]) -> list[dict[str, Any]]:
    """Per-calendar-month protective/bare/unknown counts (local dates)."""
    out: list[dict[str, Any]] = []
    current_month: str | None = None
    bucket: dict[str, int] = {}
    for d in days:
        key = d.date.strftime("%Y-%m")
        if key != current_month:
            if current_month is not None:
                out.append({"month": current_month, **bucket})
            current_month = key
            bucket = {"protective": 0, "bare": 0, "unknown": 0}
        bucket[d.classification] += 1
    if current_month is not None:
        out.append({"month": current_month, **bucket})
    return out
