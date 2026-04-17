"""ESG / transition-finance scoring API (Phase-3c).

Endpoints:
 - POST /api/v1/esg/score-vehicle   — score a single vehicle
 - POST /api/v1/esg/score-fleet     — score + persist a fund's fleet snapshot
 - GET  /api/v1/esg/fleet/{fund_id}/history — historical fleet snapshots
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client

from app.core.esg_scorer import score_fleet, score_vehicle
from app.db.repositories.esg_repo import ESGRepository
from app.dependencies import get_supabase_client
from app.middleware.rbac import require_permission
from app.models.common import SuccessResponse

router = APIRouter(prefix="/api/v1/esg", tags=["esg"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ScoreVehicleRequest(BaseModel):
    vehicle_id: UUID = Field(..., description="UUID of the vehicle to score")
    annual_km: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional assumed annual km driven (defaults to 60,000)",
    )


class ScoreFleetRequest(BaseModel):
    fund_id: UUID = Field(..., description="UUID of the fund to score")
    annual_km: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional per-vehicle annual km override",
    )


# ---------------------------------------------------------------------------
# POST /score-vehicle
# ---------------------------------------------------------------------------


@router.post("/score-vehicle", status_code=status.HTTP_201_CREATED)
async def post_score_vehicle(
    payload: ScoreVehicleRequest,
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(
        require_permission("vehicle_inventory", "read")
    ),
) -> SuccessResponse:
    """Score one vehicle and persist its ESG score."""
    # Load the vehicle record first
    veh_resp = (
        supabase.table("vehicles")
        .select("*")
        .eq("id", str(payload.vehicle_id))
        .maybe_single()
        .execute()
    )
    vehicle = veh_resp.data if veh_resp else None
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle {payload.vehicle_id} not found",
        )

    score = score_vehicle(vehicle, annual_km=payload.annual_km)

    repo = ESGRepository(supabase)
    await repo.save_vehicle_score(score)

    return SuccessResponse(data=score.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# POST /score-fleet
# ---------------------------------------------------------------------------


@router.post("/score-fleet", status_code=status.HTTP_201_CREATED)
async def post_score_fleet(
    payload: ScoreFleetRequest,
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
) -> SuccessResponse:
    """Score all vehicles in a fund and persist the snapshot."""
    snapshot = score_fleet(
        fund_id=str(payload.fund_id),
        supabase=supabase,
        annual_km=payload.annual_km,
    )

    repo = ESGRepository(supabase)
    await repo.save_fleet_snapshot(snapshot)

    # Also persist per-vehicle score rows so history is captured
    for vs in snapshot.vehicles_scored:
        try:
            await repo.save_vehicle_score(vs)
        except Exception:
            # Individual vehicle write failures shouldn't abort the fleet response
            continue

    return SuccessResponse(
        data=snapshot.model_dump(mode="json"),
        meta={
            "fund_id": str(payload.fund_id),
            "vehicles_scored": snapshot.vehicles_count,
        },
    )


# ---------------------------------------------------------------------------
# GET /fleet/{fund_id}/history
# ---------------------------------------------------------------------------


@router.get("/fleet/{fund_id}/history")
async def get_fleet_history(
    fund_id: UUID,
    start: Optional[date] = Query(default=None, description="Inclusive start date"),
    end: Optional[date] = Query(default=None, description="Inclusive end date"),
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
) -> SuccessResponse:
    """Return fleet ESG-snapshot time series for a fund."""
    repo = ESGRepository(supabase)
    rows = await repo.get_fleet_trend(
        fund_id=str(fund_id), start=start, end=end
    )
    return SuccessResponse(
        data=rows,
        meta={
            "fund_id": str(fund_id),
            "count": len(rows),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
    )
