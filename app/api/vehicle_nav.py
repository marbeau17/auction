"""Vehicle NAV history API router.

Provides endpoints for recording and querying monthly Net Asset Value
snapshots for individual vehicles and fund-level aggregations.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client

from app.db.repositories.vehicle_nav_repo import VehicleNavRepository
from app.dependencies import get_current_user, get_supabase_client, require_role
from app.middleware.rbac import require_permission
from app.models.common import SuccessResponse

router = APIRouter(prefix="/api/v1/vehicles", tags=["vehicle_nav"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class NavRecordRequest(BaseModel):
    """Request body for recording a single vehicle NAV snapshot."""

    vehicle_id: UUID = Field(..., description="UUID of the vehicle")
    fund_id: Optional[UUID] = Field(default=None, description="UUID of the fund")
    sab_id: Optional[UUID] = Field(default=None, description="UUID of the SAB")
    recording_date: date = Field(..., description="Snapshot date (typically month-end)")
    acquisition_price: int = Field(..., gt=0, description="Original acquisition price (JPY)")
    book_value: int = Field(..., ge=0, description="Current book value (JPY)")
    market_value: Optional[int] = Field(default=None, ge=0, description="Estimated market value (JPY)")
    depreciation_cumulative: int = Field(default=0, ge=0, description="Cumulative depreciation (JPY)")
    lease_income_cumulative: int = Field(default=0, ge=0, description="Cumulative lease income (JPY)")
    nav: int = Field(..., description="Net Asset Value (JPY)")
    ltv_ratio: Optional[float] = Field(default=None, ge=0, description="LTV ratio as decimal")
    notes: Optional[str] = Field(default=None, description="Optional notes")


class BatchRecordRequest(BaseModel):
    """Request body for batch monthly NAV recording."""

    fund_id: UUID = Field(..., description="UUID of the fund")
    recording_date: date = Field(..., description="Month-end date for recording")


# ---------------------------------------------------------------------------
# GET /{vehicle_id}/nav-history — NAV history for a vehicle
# ---------------------------------------------------------------------------


@router.get("/{vehicle_id}/nav-history")
async def get_vehicle_nav_history(
    vehicle_id: UUID,
    limit: int = Query(default=120, ge=1, le=600, description="Max records"),
    offset: int = Query(default=0, ge=0, description="Records to skip"),
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("vehicle_inventory", "read")),
) -> SuccessResponse:
    """Return NAV history for a specific vehicle, ordered by date descending."""
    repo = VehicleNavRepository(supabase)
    history = await repo.get_nav_history(
        vehicle_id=str(vehicle_id),
        limit=limit,
        offset=offset,
    )

    if not history:
        return SuccessResponse(
            data=[],
            meta={"vehicle_id": str(vehicle_id), "count": 0},
        )

    return SuccessResponse(
        data=history,
        meta={"vehicle_id": str(vehicle_id), "count": len(history)},
    )


# ---------------------------------------------------------------------------
# GET /{vehicle_id}/nav-latest — Latest NAV for a vehicle
# ---------------------------------------------------------------------------


@router.get("/{vehicle_id}/nav-latest")
async def get_vehicle_nav_latest(
    vehicle_id: UUID,
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("vehicle_inventory", "read")),
) -> SuccessResponse:
    """Return the most recent NAV snapshot for a vehicle."""
    repo = VehicleNavRepository(supabase)
    latest = await repo.get_latest_nav(vehicle_id=str(vehicle_id))

    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No NAV history found for vehicle {vehicle_id}",
        )

    return SuccessResponse(data=latest)


# ---------------------------------------------------------------------------
# POST /nav/record — Record a single vehicle NAV snapshot
# ---------------------------------------------------------------------------


@router.post("/nav/record", status_code=status.HTTP_201_CREATED)
async def record_vehicle_nav(
    payload: NavRecordRequest,
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Record a NAV snapshot for a single vehicle (admin/service only)."""
    repo = VehicleNavRepository(supabase)

    data = payload.model_dump(mode="json")
    vehicle_id = data.pop("vehicle_id")
    # Convert UUID fields to strings for Supabase
    for key in ("fund_id", "sab_id"):
        if data.get(key) is not None:
            data[key] = str(data[key])

    result = await repo.record_monthly_nav(
        vehicle_id=str(vehicle_id),
        data=data,
    )

    return SuccessResponse(data=result)


# ---------------------------------------------------------------------------
# POST /nav/record-monthly — Batch monthly NAV recording for a fund
# ---------------------------------------------------------------------------


@router.post("/nav/record-monthly", status_code=status.HTTP_201_CREATED)
async def record_monthly_nav_batch(
    payload: BatchRecordRequest,
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Trigger monthly NAV recording for all vehicles in a fund.

    Fetches all active SABs in the fund, calculates NAV from current
    valuations and lease income, and upserts snapshots for each vehicle.
    """
    repo = VehicleNavRepository(supabase)

    stats = await repo.batch_record_monthly(
        fund_id=str(payload.fund_id),
        recording_month=payload.recording_date,
    )

    return SuccessResponse(
        data=stats,
        meta={
            "fund_id": str(payload.fund_id),
            "recording_date": str(payload.recording_date),
        },
    )


# ---------------------------------------------------------------------------
# GET /nav/fund-summary — Fund-level NAV summary
# ---------------------------------------------------------------------------


@router.get("/nav/fund-summary")
async def get_fund_nav_summary(
    fund_id: UUID = Query(..., description="UUID of the fund"),
    recording_date: Optional[date] = Query(
        default=None, description="Specific date (defaults to latest)"
    ),
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("vehicle_inventory", "read")),
) -> SuccessResponse:
    """Return aggregated NAV statistics for all vehicles in a fund."""
    repo = VehicleNavRepository(supabase)

    summary = await repo.get_fund_nav_summary(
        fund_id=str(fund_id),
        recording_date=recording_date,
    )

    return SuccessResponse(data=summary)
