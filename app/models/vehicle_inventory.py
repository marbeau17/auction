"""Vehicle inventory models for Epic 4 (NAV / fund vehicle holdings).

Corresponds to change_request_v2.md §3.4.1 — represents a vehicle as held
by a fund / secured asset block, including its current NAV and lease
contract linkage, alongside an embedded NAV history series.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

VehicleInventoryStatus = Literal["held", "leased", "disposing", "disposed"]


# ---------------------------------------------------------------------------
# NAV history point (embedded)
# ---------------------------------------------------------------------------


class VehicleNAVHistoryPoint(BaseModel):
    """Single NAV snapshot embedded inside a VehicleInventory payload."""

    recording_date: date = Field(..., description="Snapshot date (typically month-end)")
    book_value: int = Field(..., ge=0, description="Book value at recording_date (JPY)")
    market_value: Optional[int] = Field(
        None, ge=0, description="Estimated market value (JPY)"
    )
    nav: int = Field(..., description="Net Asset Value at recording_date (JPY)")


# ---------------------------------------------------------------------------
# VehicleInventory
# ---------------------------------------------------------------------------


class VehicleInventory(BaseModel):
    """Vehicle inventory record — one row per physical vehicle in fund holdings.

    Mirrors the `vehicles` table columns added in migration
    `20260417000001_vehicle_inventory_columns.sql` plus an embedded
    `nav_history` assembled from `vehicle_nav_history`.
    """

    model_config = ConfigDict(from_attributes=True)

    vehicle_id: UUID = Field(..., description="Vehicles.id")
    fund_id: Optional[UUID] = Field(None, description="Owning fund (if held by a fund)")
    sab_id: Optional[UUID] = Field(
        None, description="Secured Asset Block allocation (if any)"
    )
    acquisition_price: int = Field(..., ge=0, description="Purchase price in JPY")
    current_nav: int = Field(..., description="Latest NAV in JPY (can be 0)")
    residual_value_setting: int = Field(
        ..., ge=0, description="Residual value used for lease pricing (JPY)"
    )
    status: VehicleInventoryStatus = Field(
        ..., description="Lifecycle status: held / leased / disposing / disposed"
    )
    lease_contract_id: Optional[UUID] = Field(
        None, description="Active lease contract if status == leased"
    )
    acquisition_date: date = Field(..., description="Date vehicle was acquired")
    nav_history: list[VehicleNAVHistoryPoint] = Field(
        default_factory=list,
        description="Chronological NAV snapshots (from vehicle_nav_history)",
    )


# ---------------------------------------------------------------------------
# List response
# ---------------------------------------------------------------------------


class VehicleInventoryList(BaseModel):
    """Response envelope for list endpoints returning VehicleInventory rows."""

    items: list[VehicleInventory] = Field(
        default_factory=list, description="Inventory rows"
    )
    total: int = Field(0, ge=0, description="Total matching rows")
    fund_id: Optional[UUID] = Field(
        None, description="Fund filter applied to the query, if any"
    )
