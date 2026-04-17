"""ESG / transition-finance scoring models (Phase-3c).

CO2 estimation + fleet transition-eligibility scores used by green-bond
underwriting and investor ESG reports.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FuelType(str, Enum):
    """Vehicle fuel-type classification used for CO2 / transition scoring."""

    DIESEL = "diesel"
    GASOLINE = "gasoline"
    HYBRID = "hybrid"
    EV = "ev"
    CNG = "cng"
    LPG = "lpg"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Vehicle-level ESG score
# ---------------------------------------------------------------------------


class VehicleESGScore(BaseModel):
    """Estimated ESG profile for a single vehicle.

    All CO2 values are *estimates* produced from fuel-efficiency reference
    tables when no telemetry is available.
    """

    vehicle_id: UUID = Field(..., description="UUID of the vehicle")
    scored_at: datetime = Field(..., description="Scoring timestamp (UTC)")

    annual_km: int = Field(
        ..., ge=0, description="Assumed annual kilometers driven"
    )
    fuel_type: FuelType = Field(
        ..., description="Fuel-type used for calculation"
    )
    vehicle_class: Optional[str] = Field(
        default=None, description="Vehicle class (e.g. 小型/中型/大型)"
    )
    body_type: Optional[str] = Field(
        default=None, description="Body type (e.g. 平ボディ/ウイング)"
    )

    fuel_efficiency_km_per_l: Optional[float] = Field(
        default=None,
        ge=0,
        description="Assumed fuel efficiency (km/L). None for EV.",
    )
    fuel_liters_year: Optional[float] = Field(
        default=None, ge=0, description="Estimated annual fuel consumption (L)"
    )
    co2_kg_year: float = Field(
        ..., ge=0, description="Estimated annual CO2 emissions (kg)"
    )
    co2_intensity_g_per_km: float = Field(
        ..., ge=0, description="CO2 intensity (g/km)"
    )

    grade: str = Field(
        ...,
        pattern=r"^[A-E]$",
        description="ESG grade A (best) through E (worst)",
    )
    transition_eligibility: bool = Field(
        ...,
        description=(
            "True if vehicle qualifies for transition-finance / green-bond "
            "eligibility (EV/hybrid/CNG fuel OR co2 <= 600 g/km)."
        ),
    )

    methodology_note: str = Field(
        ...,
        description="Plain-text explanation of the estimation method used",
    )


# ---------------------------------------------------------------------------
# Fleet-level ESG score
# ---------------------------------------------------------------------------


class FleetESGScore(BaseModel):
    """Aggregated ESG profile for a fund's fleet."""

    fund_id: UUID = Field(..., description="UUID of the fund")
    as_of_date: date = Field(..., description="Snapshot date (YYYY-MM-DD)")
    scored_at: datetime = Field(..., description="Scoring timestamp (UTC)")

    vehicles_count: int = Field(
        ..., ge=0, description="Number of vehicles scored"
    )
    vehicles_scored: list[VehicleESGScore] = Field(
        default_factory=list,
        description="Per-vehicle score breakdown",
    )

    avg_co2_intensity_g_per_km: float = Field(
        ..., ge=0, description="Weighted-average CO2 intensity (g/km)"
    )
    total_tco2_year: float = Field(
        ..., ge=0, description="Fleet total estimated annual CO2 (tonnes/year)"
    )
    transition_eligible_count: int = Field(
        ..., ge=0, description="Number of vehicles eligible for transition finance"
    )
    transition_pct: float = Field(
        ...,
        ge=0,
        le=100,
        description="% of fleet that is transition-eligible",
    )
    weighted_avg_grade: str = Field(
        ...,
        pattern=r"^[A-E]$",
        description="Weighted-average fleet grade A–E",
    )

    methodology_note: str = Field(
        ..., description="Plain-text methodology description"
    )
    payload: Optional[dict[str, Any]] = Field(
        default=None, description="Raw calculation inputs/outputs for audit"
    )


__all__ = [
    "FuelType",
    "VehicleESGScore",
    "FleetESGScore",
]
