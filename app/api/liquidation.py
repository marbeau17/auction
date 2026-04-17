"""Phase-2C Global Liquidation API.

Endpoints:

* ``POST /api/v1/liquidation/cases``               — Create a case.
* ``GET  /api/v1/liquidation/cases``               — List cases.
* ``GET  /api/v1/liquidation/cases/{id}``          — Case detail + events.
* ``POST /api/v1/liquidation/cases/{id}/assess``   — Run NLV across 4 routes.
* ``POST /api/v1/liquidation/cases/{id}/route``    — Commit a route.
* ``POST /api/v1/liquidation/cases/{id}/close``    — Finalise realised price.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.nlv_router import CLOSURE_SLA_DAYS, choose_best_route, estimate_nlv
from app.db.repositories.liquidation_repo import LiquidationRepository
from app.dependencies import get_supabase_client
from app.middleware.rbac import require_permission
from app.models.liquidation import (
    CloseCaseRequest,
    LiquidationCaseCreate,
    Route,
    RouteCommitRequest,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/liquidation", tags=["liquidation"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


ASSESSMENT_SLA_DAYS: int = 10


async def _load_vehicle(supabase, vehicle_id: str) -> dict:
    """Load the vehicle record needed for NLV estimation."""
    try:
        resp = (
            supabase.table("vehicles")
            .select("*")
            .eq("id", vehicle_id)
            .maybe_single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vehicle {vehicle_id} not found")
        return resp.data
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("liquidation_vehicle_lookup_failed", vehicle_id=vehicle_id)
        raise HTTPException(status_code=500, detail=f"Vehicle lookup failed: {e}")


# ---------------------------------------------------------------------------
# POST /cases — create
# ---------------------------------------------------------------------------


@router.post("/cases")
async def create_case(
    body: LiquidationCaseCreate,
    request: Request,
    user=Depends(require_permission("vehicle_inventory", "write")),
    supabase=Depends(get_supabase_client),
):
    """Create a new liquidation case.

    Assessment deadline is set to T+10 days from creation. Closure
    deadline defaults to T+74 (longest SLA, tightened when a route is
    committed).
    """
    today = date.today()
    assessment_deadline = today + timedelta(days=ASSESSMENT_SLA_DAYS)
    closure_deadline = today + timedelta(days=CLOSURE_SLA_DAYS["export"])

    repo = LiquidationRepository(supabase)
    try:
        case = await repo.create_case(
            vehicle_id=str(body.vehicle_id),
            triggered_by=body.triggered_by,
            assessment_deadline=assessment_deadline,
            closure_deadline=closure_deadline,
            sab_id=str(body.sab_id) if body.sab_id else None,
            fund_id=str(body.fund_id) if body.fund_id else None,
            notes=body.notes,
        )
        await repo.add_event(
            case_id=case["id"],
            event_type="case_created",
            payload={"triggered_by": body.triggered_by},
            actor_user_id=str(user["id"]) if user.get("id") else None,
        )
        return JSONResponse(status_code=201, content={"status": "success", "data": case})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("liquidation_case_create_failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /cases — list
# ---------------------------------------------------------------------------


@router.get("/cases")
async def list_cases(
    status: Optional[str] = Query(default=None),
    fund_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_permission("vehicle_inventory", "read")),
    supabase=Depends(get_supabase_client),
):
    """List liquidation cases, optionally filtered by status / fund."""
    repo = LiquidationRepository(supabase)
    try:
        cases = await repo.list_cases(
            status=status,
            fund_id=str(fund_id) if fund_id else None,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(content={"status": "success", "data": cases})
    except Exception as e:
        logger.exception("liquidation_case_list_failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /cases/{id} — detail + events
# ---------------------------------------------------------------------------


@router.get("/cases/{case_id}")
async def get_case(
    case_id: UUID,
    user=Depends(require_permission("vehicle_inventory", "read")),
    supabase=Depends(get_supabase_client),
):
    """Return a case with its full event history."""
    repo = LiquidationRepository(supabase)
    try:
        case = await repo.get_case(str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        events = await repo.list_events(str(case_id))
        return JSONResponse(
            content={"status": "success", "data": {"case": case, "events": events}}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("liquidation_case_get_failed", case_id=str(case_id))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /cases/{id}/assess — run NLV for all four routes
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/assess")
async def assess_case(
    case_id: UUID,
    user=Depends(require_permission("vehicle_inventory", "write")),
    supabase=Depends(get_supabase_client),
):
    """Compute NLV estimates across every route and emit an audit event."""
    repo = LiquidationRepository(supabase)
    try:
        case = await repo.get_case(str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        vehicle = await _load_vehicle(supabase, case["vehicle_id"])

        estimates = {
            r: estimate_nlv(vehicle, routing_option=r).model_dump()
            for r in ("domestic_resale", "export", "auction", "scrap")
        }
        recommendation = choose_best_route(vehicle).model_dump(mode="json")

        payload = {
            "estimates": estimates,
            "recommendation": recommendation,
        }
        await repo.add_event(
            case_id=str(case_id),
            event_type="nlv_estimated",
            payload=payload,
            actor_user_id=str(user["id"]) if user.get("id") else None,
        )
        await repo.update_status(
            str(case_id),
            status="routing",
            extra={"assessed_by": str(user["id"]) if user.get("id") else None},
        )

        return JSONResponse(content={"status": "success", "data": payload})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("liquidation_assess_failed", case_id=str(case_id))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /cases/{id}/route — commit the chosen route
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/route")
async def commit_route(
    case_id: UUID,
    body: RouteCommitRequest,
    user=Depends(require_permission("vehicle_inventory", "write")),
    supabase=Depends(get_supabase_client),
):
    """Commit a routing decision; tightens the closure deadline per SLA."""
    repo = LiquidationRepository(supabase)
    try:
        case = await repo.get_case(str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        closure_deadline = date.today() + timedelta(days=CLOSURE_SLA_DAYS[body.route])
        extras = {
            "route": body.route,
            "nlv_jpy": body.nlv_jpy,
            "closure_deadline": closure_deadline.isoformat(),
            "cost_breakdown": body.cost_breakdown.model_dump(),
            "status": "listed",
        }
        updated = await repo.update_status(str(case_id), status="listed", extra=extras)
        await repo.add_event(
            case_id=str(case_id),
            event_type="route_committed",
            payload={
                "route": body.route,
                "nlv_jpy": body.nlv_jpy,
                "rationale": body.rationale,
                "closure_deadline": closure_deadline.isoformat(),
            },
            actor_user_id=str(user["id"]) if user.get("id") else None,
        )
        return JSONResponse(content={"status": "success", "data": updated})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("liquidation_route_commit_failed", case_id=str(case_id))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /cases/{id}/close — finalise
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/close")
async def close_case(
    case_id: UUID,
    body: CloseCaseRequest,
    user=Depends(require_permission("vehicle_inventory", "write")),
    supabase=Depends(get_supabase_client),
):
    """Finalise a case with the realised sale price."""
    repo = LiquidationRepository(supabase)
    try:
        case = await repo.get_case(str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        extras: dict = {
            "realized_price_jpy": body.realized_price_jpy,
            "status": "closed",
        }
        if body.cost_breakdown is not None:
            extras["cost_breakdown"] = body.cost_breakdown.model_dump()
        if body.notes is not None:
            extras["notes"] = body.notes

        updated = await repo.update_status(str(case_id), status="closed", extra=extras)
        await repo.add_event(
            case_id=str(case_id),
            event_type="closed",
            payload={
                "realized_price_jpy": body.realized_price_jpy,
                "notes": body.notes,
            },
            actor_user_id=str(user["id"]) if user.get("id") else None,
        )
        return JSONResponse(content={"status": "success", "data": updated})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("liquidation_close_failed", case_id=str(case_id))
        raise HTTPException(status_code=500, detail=str(e))
