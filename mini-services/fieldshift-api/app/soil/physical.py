"""Physical soil indicators (Milestone 6B.2 — Step 4).

- USDA texture triangle (TEXTURE_CLASSIFIER_VERSION): point-in-polygon over
  the canonical USDA class polygons. The vertex table is transcribed from
  the `soiltexture` R package (Moeys, J. — CRAN), whose USDA.TT triangle is
  the de-facto computational reference for the USDA Soil Survey Manual
  triangle; the transcription is unit-tested against the package's worked
  geometry and against independent textbook examples. Other systems (WRB,
  national) are pass-through labels only — no cross-system mapping is
  attempted (ADR-0023).
- Bulk density with explicit basis (whole_soil vs fine_earth) and coarse
  fragments; mixing bases without reconciliation is a validation error.
- Porosity n = 1 − BD/PD: PD is a MEASURED input or the disclosed 2.65 g/cm³
  mineral-soil assumption; assumed-PD outputs are labelled `estimated`.
- Available water capacity per layer (θFC − θWP with the matric potentials
  recorded); compatible with the M6A water balance (same FAO-56 identities).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.soil.contracts import (
    TEXTURE_CLASSIFIER_VERSION,
    SoilValidationError,
)
from app.soil.layers import DepthInterval

# Documented mineral-soil particle density assumption (e.g. quartz-dominated
# temperate mineral soils). Used ONLY when no measured PD exists; every output
# derived from it is labelled estimated with this disclosure.
DEFAULT_PARTICLE_DENSITY_G_CM3 = 2.65
PD_ASSUMPTION_DISCLOSURE = (
    "particle density assumed 2.65 g/cm³ (documented mineral-soil assumption); "
    "a measured particle density refines this estimate"
)


def _finite(value: Any, name: str) -> float:
    if value is None or not math.isfinite(float(value)):
        raise SoilValidationError(f"{name} must be a finite number")
    return float(value)


# ---------------------------------------------------------------- texture

# Canonical USDA texture-class polygons, (sand%, silt%, clay%) triples.
# Transcribed from the soiltexture R package USDA.TT table (26 points,
# 12 polygons; fractions × 100 here). Class names are the 12 USDA classes.
_USDA_POINTS: dict[str, tuple[float, float, float]] = {
    "P01": (45.0, 0.0, 55.0),
    "P02": (0.0, 40.0, 60.0),
    "P03": (65.0, 0.0, 35.0),
    "P04": (45.0, 20.0, 35.0),
    "P05": (45.0, 15.0, 40.0),
    "P06": (20.0, 40.0, 40.0),
    "P07": (0.0, 60.0, 40.0),
    "P08": (80.0, 0.0, 20.0),
    "P09": (52.5, 27.5, 20.0),
    "P10": (45.0, 27.5, 27.5),
    "P11": (22.5, 50.0, 27.5),
    "P12": (20.0, 52.5, 27.5),
    "P13": (0.0, 72.5, 27.5),
    "P14": (85.0, 0.0, 15.0),
    "P15": (90.0, 0.0, 10.0),
    "P16": (52.5, 40.0, 7.5),
    "P17": (42.5, 50.0, 7.5),
    "P18": (7.5, 80.0, 12.5),
    "P19": (0.0, 87.5, 12.5),
    "P20": (85.0, 15.0, 0.0),
    "P21": (70.0, 30.0, 0.0),
    "P22": (50.0, 50.0, 0.0),
    "P23": (20.0, 80.0, 0.0),
    "P24": (0.0, 0.0, 100.0),
    "P25": (100.0, 0.0, 0.0),
    "P26": (0.0, 100.0, 0.0),
}

_USDA_POLYGONS: dict[str, list[str]] = {
    "clay": ["P24", "P01", "P05", "P06", "P02"],
    "silty clay": ["P02", "P06", "P07"],
    "sandy clay": ["P01", "P03", "P04", "P05"],
    "clay loam": ["P05", "P04", "P10", "P11", "P12", "P06"],
    "silty clay loam": ["P06", "P12", "P13", "P07"],
    "sandy clay loam": ["P03", "P08", "P09", "P10", "P04"],
    "loam": ["P10", "P09", "P16", "P17", "P11"],
    "silt loam": ["P11", "P17", "P22", "P23", "P18", "P19", "P13", "P12"],
    "sandy loam": ["P08", "P14", "P21", "P22", "P17", "P16", "P09"],
    "silt": ["P18", "P23", "P26", "P19"],
    "loamy sand": ["P14", "P15", "P20", "P21"],
    "sand": ["P15", "P25", "P20"],
}

USDA_TEXTURE_CLASSES: tuple[str, ...] = tuple(_USDA_POLYGONS.keys())


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon with inclusive edges (vertices belong to
    a class — triangle polygons tile the ternary domain, so boundary points
    must resolve deterministically)."""
    x, y = point
    n = len(polygon)
    inside = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        # on-edge check (inclusive)
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if abs(cross) < 1e-9 and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return True
        if (y1 > y) != (y2 > y):
            x_int = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_int:
                inside = not inside
    return inside


@dataclass(frozen=True)
class TextureResult:
    sand_pct: float
    silt_pct: float
    clay_pct: float
    texture_class: str
    silt_basis: str            # measured | derived_silt_100_minus_sand_clay
    classifier_version: str = TEXTURE_CLASSIFIER_VERSION


def classify_usda_texture(
    *,
    sand_pct: float | None = None,
    silt_pct: float | None = None,
    clay_pct: float | None = None,
    sand_g_kg: float | None = None,
    silt_g_kg: float | None = None,
    clay_g_kg: float | None = None,
) -> TextureResult:
    """USDA texture class from particle-size fractions.

    Accepts percentages or g/kg (mutually exclusive groups). When silt is not
    supplied, silt = 100 − sand − clay is DERIVED and the derivation is
    disclosed in the result (`silt_basis`). Refusals: fractions outside
    [0, 100]; when all three fractions are supplied, sums outside
    100 ± 0.5 (the declared tolerance). Boundary points (on polygon edges)
    resolve deterministically via inclusive edge tests."""
    if (sand_pct is not None or silt_pct is not None or clay_pct is not None) and (
        sand_g_kg is not None or silt_g_kg is not None or clay_g_kg is not None
    ):
        raise SoilValidationError("supply fractions as percentages OR g/kg, not both")

    def pct(value: float | None, g_kg: float | None, name: str) -> float | None:
        if value is not None:
            return _finite(value, name)
        if g_kg is not None:
            return _finite(g_kg, name) / 10.0  # g/kg → %
        return None

    sand = pct(sand_pct, sand_g_kg, "sand")
    silt = pct(silt_pct, silt_g_kg, "silt")
    clay = pct(clay_pct, clay_g_kg, "clay")
    if sand is None or clay is None:
        raise SoilValidationError("sand and clay fractions are required for USDA classification")

    silt_basis = "measured"
    if silt is None:
        silt = 100.0 - sand - clay
        silt_basis = "derived_silt_100_minus_sand_clay"

    for name, v in (("sand", sand), ("silt", silt), ("clay", clay)):
        if v < 0 or v > 100:
            raise SoilValidationError(f"{name} fraction {v}% outside [0, 100]")

    if silt_basis == "measured":
        total = sand + silt + clay
        if abs(total - 100.0) > 0.5:
            raise SoilValidationError(
                f"sand+silt+clay = {total:.2f}% — outside the 100 ± 0.5 tolerance; "
                "refusing to classify inconsistent fractions"
            )
    elif silt < -0.5:
        raise SoilValidationError(
            f"derived silt {silt:.2f}% is negative — sand+clay exceed 100%; refusing"
        )

    silt = max(silt, 0.0)
    point = (sand, silt)
    for class_name, point_keys in _USDA_POLYGONS.items():
        polygon = [_USDA_POINTS[k][:2] for k in point_keys]  # (sand, silt) plane
        if _point_in_polygon(point, polygon):
            return TextureResult(
                sand_pct=round(sand, 4),
                silt_pct=round(silt, 4),
                clay_pct=round(clay, 4),
                texture_class=class_name,
                silt_basis=silt_basis,
            )
    raise SoilValidationError(
        f"fractions (sand {sand}%, silt {silt}%, clay {clay}%) fall outside every "
        "USDA class polygon — refusing rather than snapping to a nearest class"
    )


# ------------------------------------------------------- bulk density / porosity

BD_BASES = ("whole_soil", "fine_earth")


@dataclass(frozen=True)
class PorosityResult:
    porosity: float
    basis: str                    # measured_pd | assumed_pd
    particle_density_g_cm3: float
    disclosure: str | None
    bulk_density_g_cm3: float
    bulk_density_basis: str


def porosity(
    bulk_density_g_cm3: float,
    particle_density_g_cm3: float | None,
    *,
    bulk_density_basis: str = "fine_earth",
) -> PorosityResult:
    """Total porosity n = 1 − BD/PD.

    PD must be measured; otherwise the documented 2.65 g/cm³ mineral
    assumption is used and the output is labelled `estimated` (never
    presented as measured)."""
    if bulk_density_basis not in BD_BASES:
        raise SoilValidationError(
            f"bulk-density basis must be one of {BD_BASES} (got '{bulk_density_basis}')"
        )
    bd = _finite(bulk_density_g_cm3, "bulk_density")
    if bd <= 0 or bd >= 2.65:
        raise SoilValidationError(
            f"bulk density {bd} g/cm³ outside the plausible (0, 2.65) range — refusing"
        )
    if particle_density_g_cm3 is not None:
        pd = _finite(particle_density_g_cm3, "particle_density")
        basis = "measured_pd"
        disclosure = None
    else:
        pd = DEFAULT_PARTICLE_DENSITY_G_CM3
        basis = "assumed_pd"
        disclosure = PD_ASSUMPTION_DISCLOSURE
    if pd <= bd:
        raise SoilValidationError(
            f"particle density ({pd}) must exceed bulk density ({bd}) — inputs not usable"
        )
    n = 1.0 - bd / pd
    return PorosityResult(
        porosity=round(n, 4),
        basis=basis,
        particle_density_g_cm3=pd,
        disclosure=disclosure,
        bulk_density_g_cm3=bd,
        bulk_density_basis=bulk_density_basis,
    )


# ------------------------------------------------------------------- AWC

@dataclass(frozen=True)
class LayerAWC:
    interval: DepthInterval
    theta_fc: float
    theta_wp: float
    awc_m3_m3: float
    awc_mm: float                 # AWC × thickness_cm × 10 (cm→mm identity)
    fc_potential_kpa: float | None
    pwp_potential_kpa: float | None


def layer_awc(
    interval: DepthInterval,
    theta_fc: float,
    theta_wp: float,
    *,
    fc_potential_kpa: float | None = None,
    pwp_potential_kpa: float | None = None,
) -> LayerAWC:
    """Available water capacity for ONE layer: AWC = θFC − θWP (volumetric).

    The mm figure uses thickness_cm × 10 (1 cm water over 1 m² = 10 mm — the
    same depth identity the water engine uses). Potentials are recorded with
    the values when supplied (standard: −33 / −1500 kPa)."""
    fc = _finite(theta_fc, "theta_fc")
    wp = _finite(theta_wp, "theta_wp")
    if not 0 < wp < fc < 1.0:
        raise SoilValidationError(
            f"water contents must satisfy 0 < θWP ({wp}) < θFC ({fc}) < 1 — refusing"
        )
    awc = fc - wp
    return LayerAWC(
        interval=interval,
        theta_fc=fc,
        theta_wp=wp,
        awc_m3_m3=round(awc, 6),
        awc_mm=round(awc * interval.thickness_cm * 10.0, 4),
        fc_potential_kpa=fc_potential_kpa,
        pwp_potential_kpa=pwp_potential_kpa,
    )


def profile_awc_mm(layers: list[LayerAWC]) -> tuple[float | None, dict[str, Any]]:
    """Depth-integrated profile AWC (mm) over the covered intervals.

    Returns (total_mm | None, info). Overlapping layers REFUSE aggregation
    (never double-counted); GAPS are reported in `info` and the total covers
    ONLY the measured contiguous coverage (labelled, not silently whole-profile)."""
    if not layers:
        return None, {"reason": "no layers with both θFC and θWP"}
    intervals = [l.interval for l in layers]
    from app.soil.layers import validate_layer_set

    check = validate_layer_set(intervals)
    info: dict[str, Any] = {
        "gaps": check["gaps"],
        "coverage_cm": check["coverage"],
        "layers_used": len(layers),
    }
    if check["overlaps"]:
        return None, {**info, "reason": "overlapping depth intervals — aggregation refused"}
    total_mm = sum(l.awc_mm for l in layers)
    if check["gaps"]:
        info["note"] = (
            "total covers the measured intervals only; listed gaps are NOT interpolated"
        )
    return round(total_mm, 4), info
