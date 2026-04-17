"""LTV (Loan-to-Value) valuation API router.

Endpoints
---------
* ``POST /api/v1/ltv/calculate``                       — compute + persist fund LTV
* ``GET  /api/v1/ltv/{fund_id}/vehicle/{vehicle_id}``  — per-vehicle LTV
* ``POST /api/v1/ltv/{fund_id}/stress-test``           — scenario stress test
* ``GET  /api/v1/ltv/{fund_id}/history``               — LTV snapshot time series

RBAC: ``fund_info/read`` for read endpoints, ``fund_info/write`` for mutations.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client

from app.core.ltv_valuator import (
    DEFAULT_BREACH_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    LTVValuator,
)
from app.db.repositories.ltv_repo import LTVRepository
from app.dependencies import get_supabase_client
from app.middleware.rbac import require_permission
from app.models.common import SuccessResponse
from app.models.ltv import (
    LTVFundResult,
    LTVVehicleResult,
    StressTestResult,
)

router = APIRouter(prefix="/api/v1/ltv", tags=["ltv"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CalculateRequest(BaseModel):
    """Request body for POST /calculate."""

    fund_id: UUID = Field(..., description="UUID of the fund")
    as_of_date: Optional[date] = Field(
        default=None, description="Valuation date (defaults to today)"
    )
    warning_threshold: float = Field(
        default=DEFAULT_WARNING_THRESHOLD,
        ge=0.0,
        le=2.0,
        description="Warning LTV threshold (default 0.75)",
    )
    breach_threshold: float = Field(
        default=DEFAULT_BREACH_THRESHOLD,
        ge=0.0,
        le=2.0,
        description="Breach LTV threshold (default 0.85)",
    )


class StressTestRequest(BaseModel):
    """Request body for POST /{fund_id}/stress-test."""

    shock_percentages: list[float] = Field(
        default_factory=lambda: [0.05, 0.10, 0.20],
        description="List of book-value shock fractions, e.g. [0.05, 0.10, 0.20]",
    )
    as_of_date: Optional[date] = Field(
        default=None, description="Valuation date (defaults to today)"
    )
    warning_threshold: float = Field(
        default=DEFAULT_WARNING_THRESHOLD,
        ge=0.0,
        le=2.0,
    )
    breach_threshold: float = Field(
        default=DEFAULT_BREACH_THRESHOLD,
        ge=0.0,
        le=2.0,
    )


# ---------------------------------------------------------------------------
# POST /calculate — compute + persist fund LTV
# ---------------------------------------------------------------------------


@router.post("/calculate")
async def calculate_fund_ltv(
    payload: CalculateRequest,
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
) -> SuccessResponse:
    """Compute fund-level LTV and persist a snapshot.

    Read permission is sufficient because the computation only *derives*
    values from existing NAV and lease data.  Persistence is performed
    using the service-role Supabase client so investors can trigger
    recalculation of their own fund's LTV without holding write RBAC.
    """
    as_of = payload.as_of_date or date.today()
    valuator = LTVValuator(
        supabase,
        warning_threshold=payload.warning_threshold,
        breach_threshold=payload.breach_threshold,
    )
    result_dict = valuator.calculate_fund_ltv(
        fund_id=str(payload.fund_id),
        as_of_date=as_of,
    )

    # Persist snapshot (upsert)
    repo = LTVRepository(supabase)
    try:
        await repo.snapshot_ltv(
            fund_id=str(payload.fund_id),
            as_of_date=as_of,
            result=result_dict,
        )
    except Exception as exc:  # noqa: BLE001
        # Persistence failure should not mask the calculation response,
        # but surface as a 500 because downstream consumers expect history.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LTV calculated but snapshot failed: {exc}",
        ) from exc

    model = LTVFundResult(**result_dict)
    return SuccessResponse(data=model.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# GET /{fund_id}/vehicle/{vehicle_id} — per-vehicle LTV
# ---------------------------------------------------------------------------


@router.get("/{fund_id}/vehicle/{vehicle_id}")
async def get_vehicle_ltv(
    fund_id: UUID,
    vehicle_id: UUID,
    as_of_date: Optional[date] = Query(
        default=None, description="Valuation date (defaults to today)"
    ),
    warning_threshold: float = Query(default=DEFAULT_WARNING_THRESHOLD, ge=0.0, le=2.0),
    breach_threshold: float = Query(default=DEFAULT_BREACH_THRESHOLD, ge=0.0, le=2.0),
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
) -> SuccessResponse:
    """Return the per-vehicle LTV snapshot for the given vehicle."""
    as_of = as_of_date or date.today()
    valuator = LTVValuator(
        supabase,
        warning_threshold=warning_threshold,
        breach_threshold=breach_threshold,
    )
    result_dict = valuator.calculate_vehicle_ltv(
        vehicle_id=str(vehicle_id),
        as_of_date=as_of,
    )
    # Attach fund_id if the NAV history didn't carry one
    if not result_dict.get("fund_id"):
        result_dict["fund_id"] = fund_id

    model = LTVVehicleResult(**result_dict)
    return SuccessResponse(data=model.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# POST /{fund_id}/stress-test — scenario analysis
# ---------------------------------------------------------------------------


@router.post("/{fund_id}/stress-test")
async def stress_test_fund(
    fund_id: UUID,
    payload: StressTestRequest,
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
) -> SuccessResponse:
    """Run a list of shock scenarios against the fund's current book value."""
    as_of = payload.as_of_date or date.today()
    valuator = LTVValuator(
        supabase,
        warning_threshold=payload.warning_threshold,
        breach_threshold=payload.breach_threshold,
    )
    scenario_dicts = valuator.stress_test(
        fund_id=str(fund_id),
        shock_percentages=payload.shock_percentages,
        as_of_date=as_of,
    )
    models = [StressTestResult(**d) for d in scenario_dicts]
    return SuccessResponse(
        data=[m.model_dump(mode="json") for m in models],
        meta={
            "fund_id": str(fund_id),
            "as_of_date": str(as_of),
            "scenario_count": len(models),
        },
    )


# ---------------------------------------------------------------------------
# GET /{fund_id}/history — time series
# ---------------------------------------------------------------------------


@router.get("/{fund_id}/history")
async def get_ltv_history(
    fund_id: UUID,
    start: Optional[date] = Query(default=None, description="Inclusive start date"),
    end: Optional[date] = Query(default=None, description="Inclusive end date"),
    limit: int = Query(default=500, ge=1, le=5000),
    supabase: Client = Depends(get_supabase_client),
    user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
) -> SuccessResponse:
    """Return the time series of LTV snapshots for a fund."""
    repo = LTVRepository(supabase)
    rows = await repo.get_history(
        fund_id=str(fund_id),
        start=start,
        end=end,
        limit=limit,
    )
    return SuccessResponse(
        data=rows,
        meta={
            "fund_id": str(fund_id),
            "count": len(rows),
            "start": str(start) if start else None,
            "end": str(end) if end else None,
        },
    )
