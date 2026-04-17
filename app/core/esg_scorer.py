"""ESG / transition-finance scorer (Phase-3c).

Estimates vehicle-level CO2 emissions and fleet-level transition-finance
eligibility for green-bond underwriting.

NOTE ON DATA SOURCES
--------------------
The fuel-efficiency table below is **illustrative**. Values are coarse
industry rules-of-thumb for Japanese commercial trucks. Before using in a
production green-bond offering, replace with official 国土交通省 "自動車燃費
一覧" figures, TABEZON / JARI reference data, or OEM spec sheets.

CO2 emission factors (per liter of fuel) follow the MOE / 温対法 defaults:
 - Diesel (軽油):   2.58 kg CO2 / L
 - Gasoline (ガソリン): 2.32 kg CO2 / L
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog

from app.models.esg import FleetESGScore, FuelType, VehicleESGScore

logger = structlog.get_logger()


# ===========================================================================
# Constants
# ===========================================================================

# kg CO2 per liter of fuel (source: 温対法 施行令 default factors)
CO2_KG_PER_LITER: dict[FuelType, float] = {
    FuelType.DIESEL: 2.58,
    FuelType.GASOLINE: 2.32,
    # CNG / LPG / hybrid / EV are handled via specific branches below.
    FuelType.LPG: 1.67,
    FuelType.CNG: 2.23,
}

# Default annual mileage per vehicle when not provided (commercial trucks)
DEFAULT_ANNUAL_KM = 60_000

# Transition-finance threshold (g CO2 per km)
TRANSITION_CO2_THRESHOLD_G_PER_KM = 600.0

# Grade thresholds on CO2 intensity (g CO2 / km)
# Tuned for Japanese commercial trucks; EVs land in A by construction.
GRADE_THRESHOLDS: list[tuple[str, float]] = [
    ("A", 150.0),   # ≤ 150 g/km (essentially zero-emission / light EV-class)
    ("B", 400.0),   # ≤ 400 g/km
    ("C", 700.0),   # ≤ 700 g/km
    ("D", 1_000.0), # ≤ 1,000 g/km
    # anything above → E
]


# ---------------------------------------------------------------------------
# Fuel-efficiency reference table (km/L)
# ---------------------------------------------------------------------------
# Illustrative values — (vehicle_class, body_type) → km/L.
# Replace with 国交省 official figures when available.
FUEL_EFFICIENCY_TABLE: dict[tuple[str, str], float] = {
    ("小型", "平ボディ"): 8.0,
    ("小型", "バンボディ"): 7.5,
    ("小型", "ウイング"): 7.0,
    ("小型", "ダンプ"): 7.0,
    ("中型", "平ボディ"): 6.5,
    ("中型", "ウイング"): 6.0,
    ("中型", "バンボディ"): 6.0,
    ("大型", "平ボディ"): 4.5,
    ("大型", "ウイング"): 4.0,
    ("大型", "ダンプ"): 3.8,
    ("大型", "トレーラー"): 3.5,
}

# Per-class fallback (body-type unknown)
CLASS_FALLBACK_KM_PER_L: dict[str, float] = {
    "小型": 7.5,
    "中型": 6.0,
    "大型": 4.0,
}

# Global fallback for fully unknown rows
DEFAULT_KM_PER_L = 6.0


# ===========================================================================
# Data container
# ===========================================================================


@dataclass
class CO2Estimate:
    """Return value from :func:`estimate_co2_kg`."""

    co2_kg: float
    fuel_liters: Optional[float]
    methodology_note: str


# ===========================================================================
# Fuel-efficiency / CO2 helpers
# ===========================================================================


def _normalize_fuel_type(raw: Optional[str]) -> FuelType:
    """Map a free-form fuel-type string to the FuelType enum.

    Defaults to DIESEL for commercial trucks when unknown/empty.
    """
    if not raw:
        return FuelType.DIESEL

    token = str(raw).strip().lower()
    mapping = {
        "diesel": FuelType.DIESEL,
        "軽油": FuelType.DIESEL,
        "ディーゼル": FuelType.DIESEL,
        "gasoline": FuelType.GASOLINE,
        "petrol": FuelType.GASOLINE,
        "ガソリン": FuelType.GASOLINE,
        "hybrid": FuelType.HYBRID,
        "ハイブリッド": FuelType.HYBRID,
        "ev": FuelType.EV,
        "electric": FuelType.EV,
        "電気": FuelType.EV,
        "cng": FuelType.CNG,
        "lpg": FuelType.LPG,
    }
    return mapping.get(token, FuelType.OTHER)


def lookup_fuel_efficiency(
    vehicle_class: Optional[str],
    body_type: Optional[str],
) -> tuple[float, str]:
    """Look up km/L from the reference table with graceful fallbacks.

    Returns:
        A tuple ``(km_per_l, note)`` where note describes which lookup tier
        produced the value.
    """
    vc = (vehicle_class or "").strip()
    bt = (body_type or "").strip()

    if vc and bt and (vc, bt) in FUEL_EFFICIENCY_TABLE:
        return FUEL_EFFICIENCY_TABLE[(vc, bt)], (
            f"reference table ({vc} × {bt})"
        )

    if vc in CLASS_FALLBACK_KM_PER_L:
        return CLASS_FALLBACK_KM_PER_L[vc], (
            f"class-fallback ({vc}); body_type '{bt or 'unknown'}' not in table"
        )

    return DEFAULT_KM_PER_L, (
        f"global fallback; class='{vc or 'unknown'}' body_type='{bt or 'unknown'}' "
        "not in reference table"
    )


def estimate_co2_kg(
    km_driven: float,
    vehicle_class: Optional[str],
    body_type: Optional[str],
    fuel_type: Optional[str] = None,
) -> CO2Estimate:
    """Estimate annual CO2 (kg) for a vehicle.

    Methodology:
    1. Normalize ``fuel_type`` (defaults to diesel).
    2. EVs return 0 kg tailpipe CO2 (scope 1); upstream grid emissions are
       out of scope for green-bond eligibility here.
    3. Hybrid: apply a 0.75 multiplier on the diesel/gasoline baseline.
    4. All others: fuel_liters = km / (km/L from reference table), then
       multiply by the per-fuel factor.
    """
    if km_driven < 0:
        raise ValueError("km_driven must be non-negative")

    ft = _normalize_fuel_type(fuel_type)

    # ---- EV: zero tailpipe emissions ---------------------------------
    if ft == FuelType.EV:
        return CO2Estimate(
            co2_kg=0.0,
            fuel_liters=0.0,
            methodology_note=(
                "EV — tailpipe CO2 set to 0 kg. "
                "Grid-upstream emissions excluded (scope 2, out of scope)."
            ),
        )

    km_per_l, lookup_note = lookup_fuel_efficiency(vehicle_class, body_type)

    # ---- Hybrid: 25% efficiency improvement on the base fuel --------
    if ft == FuelType.HYBRID:
        effective_km_per_l = km_per_l / 0.75  # consumes less fuel per km
        base_factor = CO2_KG_PER_LITER[FuelType.DIESEL]
        liters = km_driven / effective_km_per_l if effective_km_per_l > 0 else 0.0
        co2 = liters * base_factor
        return CO2Estimate(
            co2_kg=co2,
            fuel_liters=liters,
            methodology_note=(
                f"Hybrid — base km/L from {lookup_note}, "
                "adjusted by hybrid efficiency factor 0.75× fuel use; "
                "diesel emission factor applied."
            ),
        )

    # ---- Conventional fuel --------------------------------------------
    factor = CO2_KG_PER_LITER.get(ft)
    if factor is None:
        # "other" → conservative default using diesel factor
        factor = CO2_KG_PER_LITER[FuelType.DIESEL]
        fuel_note = f"unknown fuel '{fuel_type}'; diesel factor applied"
    else:
        fuel_note = f"{ft.value} factor {factor} kg/L"

    liters = km_driven / km_per_l if km_per_l > 0 else 0.0
    co2 = liters * factor

    return CO2Estimate(
        co2_kg=co2,
        fuel_liters=liters,
        methodology_note=f"{fuel_note}; km/L from {lookup_note}",
    )


# ===========================================================================
# Grading
# ===========================================================================


def grade_from_co2_intensity(g_per_km: float) -> str:
    """Map a CO2 intensity (g/km) to a letter grade A-E."""
    for grade, threshold in GRADE_THRESHOLDS:
        if g_per_km <= threshold:
            return grade
    return "E"


def _is_transition_eligible(fuel_type: FuelType, co2_g_per_km: float) -> bool:
    if fuel_type in {FuelType.EV, FuelType.HYBRID, FuelType.CNG}:
        return True
    return co2_g_per_km <= TRANSITION_CO2_THRESHOLD_G_PER_KM


# ===========================================================================
# Vehicle scoring
# ===========================================================================


def score_vehicle(
    vehicle_dict: dict[str, Any],
    annual_km: Optional[int] = None,
) -> VehicleESGScore:
    """Score a single vehicle.

    Args:
        vehicle_dict: Row from the ``vehicles`` table. Expected keys:
            ``id``, ``vehicle_class`` (or ``category`` / class label),
            ``body_type``, ``fuel_type``.
        annual_km: Optional override for annual km driven. Defaults to
            ``DEFAULT_ANNUAL_KM`` when not supplied.

    Returns:
        A :class:`VehicleESGScore`.
    """
    vid = vehicle_dict.get("id") or vehicle_dict.get("vehicle_id")
    if vid is None:
        raise ValueError("vehicle_dict must contain 'id' or 'vehicle_id'")

    km = int(annual_km) if annual_km is not None else DEFAULT_ANNUAL_KM
    if km <= 0:
        km = DEFAULT_ANNUAL_KM

    vehicle_class = (
        vehicle_dict.get("vehicle_class")
        or vehicle_dict.get("category")
        or vehicle_dict.get("size_class")
    )
    body_type = vehicle_dict.get("body_type")
    fuel_type_raw = vehicle_dict.get("fuel_type")

    ft = _normalize_fuel_type(fuel_type_raw)

    estimate = estimate_co2_kg(
        km_driven=float(km),
        vehicle_class=vehicle_class,
        body_type=body_type,
        fuel_type=ft.value,
    )

    intensity_g_per_km = (estimate.co2_kg * 1_000.0) / km if km > 0 else 0.0
    grade = grade_from_co2_intensity(intensity_g_per_km)
    eligible = _is_transition_eligible(ft, intensity_g_per_km)

    km_per_l = None
    if ft not in {FuelType.EV}:
        km_per_l, _ = lookup_fuel_efficiency(vehicle_class, body_type)

    return VehicleESGScore(
        vehicle_id=UUID(str(vid)),
        scored_at=datetime.now(timezone.utc),
        annual_km=km,
        fuel_type=ft,
        vehicle_class=vehicle_class,
        body_type=body_type,
        fuel_efficiency_km_per_l=km_per_l,
        fuel_liters_year=estimate.fuel_liters,
        co2_kg_year=round(estimate.co2_kg, 2),
        co2_intensity_g_per_km=round(intensity_g_per_km, 2),
        grade=grade,
        transition_eligibility=eligible,
        methodology_note=estimate.methodology_note,
    )


# ===========================================================================
# Fleet scoring
# ===========================================================================


_GRADE_TO_NUMERIC = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
_NUMERIC_TO_GRADE = {v: k for k, v in _GRADE_TO_NUMERIC.items()}


def _weighted_avg_grade(scores: list[VehicleESGScore]) -> str:
    if not scores:
        return "E"
    # Weight by annual km so larger vehicles pull more weight
    total_km = sum(s.annual_km for s in scores)
    if total_km <= 0:
        return "E"
    num = sum(_GRADE_TO_NUMERIC[s.grade] * s.annual_km for s in scores)
    avg = num / total_km
    # Round to nearest integer grade bucket
    bucket = max(1, min(5, int(round(avg))))
    return _NUMERIC_TO_GRADE[bucket]


def score_fleet(
    fund_id: str | UUID,
    supabase: Any,
    annual_km: Optional[int] = None,
) -> FleetESGScore:
    """Score all vehicles in a fund and return an aggregated :class:`FleetESGScore`.

    Args:
        fund_id: UUID of the fund.
        supabase: Supabase client (or any object exposing ``.table().select().eq().execute()``).
        annual_km: Optional assumed annual km per vehicle.
    """
    fund_uuid = UUID(str(fund_id))

    # ------------------------------------------------------------------
    # Pull all vehicles linked to this fund via secured_asset_blocks.
    # Fall back to a direct ``vehicles.fund_id`` match if that column exists.
    # ------------------------------------------------------------------
    vehicles: list[dict[str, Any]] = []
    try:
        sab_resp = (
            supabase.table("secured_asset_blocks")
            .select("vehicle_id")
            .eq("fund_id", str(fund_uuid))
            .execute()
        )
        vehicle_ids = [
            r["vehicle_id"] for r in (sab_resp.data or []) if r.get("vehicle_id")
        ]
        if vehicle_ids:
            veh_resp = (
                supabase.table("vehicles")
                .select("*")
                .in_("id", vehicle_ids)
                .execute()
            )
            vehicles = veh_resp.data or []
    except Exception:
        logger.exception("fleet_vehicle_fetch_failed", fund_id=str(fund_uuid))
        vehicles = []

    scores = [score_vehicle(v, annual_km=annual_km) for v in vehicles]

    now = datetime.now(timezone.utc)

    if scores:
        total_tco2 = sum(s.co2_kg_year for s in scores) / 1_000.0
        total_km = sum(s.annual_km for s in scores)
        avg_intensity = (
            sum(s.co2_intensity_g_per_km * s.annual_km for s in scores) / total_km
            if total_km > 0
            else 0.0
        )
        eligible = sum(1 for s in scores if s.transition_eligibility)
        pct = (eligible / len(scores)) * 100.0
        weighted_grade = _weighted_avg_grade(scores)
    else:
        total_tco2 = 0.0
        avg_intensity = 0.0
        eligible = 0
        pct = 0.0
        weighted_grade = "E"

    methodology = (
        "Fleet ESG score = aggregate of per-vehicle estimates. "
        "CO2 derived from fuel-efficiency reference table (illustrative; "
        "to be replaced with 国交省 official figures) and 温対法 fuel emission "
        "factors. Weighted averages use annual_km as weight. "
        f"Transition-eligibility threshold: <={TRANSITION_CO2_THRESHOLD_G_PER_KM} g/km, "
        "OR fuel_type in {EV, hybrid, CNG}."
    )

    return FleetESGScore(
        fund_id=fund_uuid,
        as_of_date=date.today(),
        scored_at=now,
        vehicles_count=len(scores),
        vehicles_scored=scores,
        avg_co2_intensity_g_per_km=round(avg_intensity, 2),
        total_tco2_year=round(total_tco2, 3),
        transition_eligible_count=eligible,
        transition_pct=round(pct, 2),
        weighted_avg_grade=weighted_grade,
        methodology_note=methodology,
        payload={
            "vehicles_count": len(scores),
            "eligible": eligible,
            "total_tco2_year": round(total_tco2, 3),
            "avg_co2_intensity_g_per_km": round(avg_intensity, 2),
        },
    )


__all__ = [
    "CO2_KG_PER_LITER",
    "DEFAULT_ANNUAL_KM",
    "DEFAULT_KM_PER_L",
    "FUEL_EFFICIENCY_TABLE",
    "GRADE_THRESHOLDS",
    "TRANSITION_CO2_THRESHOLD_G_PER_KM",
    "CO2Estimate",
    "estimate_co2_kg",
    "grade_from_co2_intensity",
    "lookup_fuel_efficiency",
    "score_fleet",
    "score_vehicle",
]
