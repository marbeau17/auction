"""Pydantic models for LTV (Loan-to-Value) valuation engine.

Defines the request / response contracts for:

* Per-vehicle LTV calculation    (`LTVVehicleResult`)
* Per-fund LTV aggregation       (`LTVFundResult`)
* Stress test scenarios & output (`StressScenario`, `StressTestResult`)

Thresholds follow the parent LTV control spec (``docs/ltv_valuation_spec.md``):

* ``WARNING``  when ``ltv_ratio`` >= 0.75
* ``BREACH``   when ``ltv_ratio`` >= 0.85

These are the covenant-level defaults for outstanding-principal / book-value
LTV (different from the 0.60 origination LTV which governs *new* purchases).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Per-vehicle LTV
# ---------------------------------------------------------------------------


class LTVVehicleResult(BaseModel):
    """Per-vehicle Loan-to-Value snapshot."""

    vehicle_id: UUID = Field(..., description="UUID of the vehicle")
    fund_id: Optional[UUID] = Field(default=None, description="UUID of the owning fund")
    as_of_date: date = Field(..., description="Valuation date")

    book_value: int = Field(..., ge=0, description="Current book value (JPY)")
    outstanding_principal: int = Field(
        ..., ge=0, description="Remaining unpaid lease principal (JPY)"
    )
    ltv_ratio: float = Field(
        ..., ge=0.0, description="outstanding_principal / book_value (0 if book_value=0)"
    )
    collateral_headroom: int = Field(
        ...,
        description=(
            "book_value - outstanding_principal in JPY. "
            "Negative values indicate a collateral shortfall."
        ),
    )

    warning_flag: bool = Field(
        default=False, description="True when ltv_ratio >= warning threshold"
    )
    breach_flag: bool = Field(
        default=False, description="True when ltv_ratio >= breach threshold"
    )
    status: str = Field(
        default="HEALTHY",
        description="HEALTHY | WARNING | BREACH",
    )


# ---------------------------------------------------------------------------
# Per-fund LTV
# ---------------------------------------------------------------------------


class LTVFundResult(BaseModel):
    """Fund-level LTV aggregation across all its vehicles."""

    fund_id: UUID = Field(..., description="UUID of the fund")
    as_of_date: date = Field(..., description="Valuation date")

    vehicles_count: int = Field(..., ge=0, description="Number of vehicles valued")
    book_value_total: int = Field(
        ..., ge=0, description="Sum of book values across vehicles (JPY)"
    )
    outstanding_principal_total: int = Field(
        ..., ge=0, description="Sum of outstanding principals across vehicles (JPY)"
    )
    ltv_ratio: float = Field(
        ...,
        ge=0.0,
        description="Aggregate LTV = Σ principal / Σ book_value",
    )
    collateral_headroom: int = Field(
        ..., description="book_value_total - outstanding_principal_total (JPY)"
    )

    warning_count: int = Field(
        default=0, ge=0, description="Vehicles at or above warning threshold"
    )
    breach_count: int = Field(
        default=0, ge=0, description="Vehicles at or above breach threshold"
    )
    warning_flag: bool = Field(
        default=False, description="Fund-level warning (aggregate LTV breached warning)"
    )
    breach_flag: bool = Field(
        default=False, description="Fund-level covenant breach (aggregate LTV >= breach threshold)"
    )
    status: str = Field(
        default="HEALTHY",
        description="HEALTHY | WARNING | BREACH",
    )

    warning_threshold: float = Field(
        default=0.75,
        description="Warning LTV threshold (default 0.75)",
    )
    breach_threshold: float = Field(
        default=0.85,
        description="Covenant breach LTV threshold (default 0.85)",
    )

    vehicles: list[LTVVehicleResult] = Field(
        default_factory=list,
        description="Per-vehicle breakdown",
    )


# ---------------------------------------------------------------------------
# Stress testing
# ---------------------------------------------------------------------------


class StressScenario(BaseModel):
    """A single stress-test shock scenario."""

    shock_pct: float = Field(
        ...,
        ge=0.0,
        le=0.95,
        description=(
            "Market value shock as a positive decimal (e.g. 0.20 = -20% to book_value). "
            "Book value is reduced by (1 - shock_pct)."
        ),
    )
    label: Optional[str] = Field(default=None, description="Optional human label")


class StressTestResult(BaseModel):
    """Output of a single stress scenario applied to a fund."""

    fund_id: UUID = Field(..., description="UUID of the fund")
    as_of_date: date = Field(..., description="Valuation date")
    shock_pct: float = Field(..., description="Applied shock as decimal")
    label: Optional[str] = Field(default=None, description="Optional human label")

    stressed_book_value_total: int = Field(
        ..., ge=0, description="book_value_total × (1 - shock_pct)"
    )
    outstanding_principal_total: int = Field(..., ge=0)
    fund_ltv: float = Field(
        ..., ge=0.0, description="Stressed aggregate LTV"
    )
    fund_ltv_baseline: float = Field(
        ..., ge=0.0, description="Unstressed baseline LTV for comparison"
    )

    vehicles_in_breach: int = Field(
        ..., ge=0, description="Number of vehicles with stressed LTV >= breach threshold"
    )
    vehicles_in_warning: int = Field(
        ..., ge=0, description="Number of vehicles at or above warning threshold"
    )
    breach_flag: bool = Field(
        default=False, description="Whether fund-level stressed LTV breaches covenant"
    )
    status: str = Field(
        default="HEALTHY",
        description="HEALTHY | WARNING | BREACH for the stressed scenario",
    )


# ---------------------------------------------------------------------------
# Historical snapshot row (repository)
# ---------------------------------------------------------------------------


class LTVSnapshotRow(BaseModel):
    """Row shape persisted in ``ltv_snapshots`` table."""

    id: Optional[UUID] = None
    fund_id: UUID
    as_of_date: date
    ltv_ratio: float
    book_value_total: int
    outstanding_principal_total: int
    vehicles_count: int
    breach_count: int
    payload: dict[str, Any] = Field(default_factory=dict)
