"""Value Transfer Engine API endpoints.

Exposes the per-period allocation / plan / approve flows built on top of
Epic 6 invoicing. Money is never moved here — these endpoints produce
and persist plans only.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import Client

from app.core.value_transfer import ValueTransferEngine
from app.db.repositories.value_transfer_repo import ValueTransferRepository
from app.dependencies import get_current_user, get_supabase_client
from app.middleware.rbac import require_any_role, require_permission
from app.models.common import ErrorResponse, SuccessResponse

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/value-transfers", tags=["value-transfers"])


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_repo(
    supabase: Client = Depends(get_supabase_client),
) -> ValueTransferRepository:
    return ValueTransferRepository(client=supabase)


def _get_engine(
    supabase: Client = Depends(get_supabase_client),
) -> ValueTransferEngine:
    return ValueTransferEngine(client=supabase)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class AllocateRequest(BaseModel):
    """Body for POST /allocate."""

    fund_id: UUID = Field(..., description="Target fund identifier")
    period_start: date = Field(..., description="Inclusive period start date")
    period_end: date = Field(..., description="Inclusive period end date")


# ---------------------------------------------------------------------------
# 1. POST /allocate — compute + persist a new allocation
# ---------------------------------------------------------------------------


@router.post(
    "/allocate",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compute and persist a value allocation for a period",
    responses={
        201: {"description": "Allocation created"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def allocate_period(
    body: AllocateRequest,
    current_user: dict[str, Any] = Depends(
        require_permission("fund_info", "read")
    ),
    repo: ValueTransferRepository = Depends(_get_repo),
    engine: ValueTransferEngine = Depends(_get_engine),
) -> JSONResponse:
    """Compute the value allocation for a period and persist it.

    RBAC: admin + operator (via ``fund_info/read``). Asset managers can
    view results via GET but cannot initiate an allocation.
    """
    logger.info(
        "value_transfer_allocate",
        user_id=current_user["id"],
        fund_id=str(body.fund_id),
        period_start=body.period_start.isoformat(),
        period_end=body.period_end.isoformat(),
    )

    try:
        allocation = engine.compute_period_allocation(
            fund_id=body.fund_id,
            period_start=body.period_start,
            period_end=body.period_end,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception:
        logger.exception(
            "value_transfer_compute_failed",
            fund_id=str(body.fund_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="バリュートランスファー計算中にエラーが発生しました",
        )

    plan = engine.generate_distribution_plan(allocation)

    try:
        created = await repo.create_allocation(allocation, plan)
    except Exception:
        logger.exception(
            "value_transfer_persist_failed",
            fund_id=str(body.fund_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="バリュートランスファーの保存中にエラーが発生しました",
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=SuccessResponse(
            data=created,
            meta={
                "allocation_id": str(created.get("id")),
                "gross_income": allocation.gross_income,
                "net_income": allocation.net_income,
                "reconciliation_diff": allocation.reconciliation_diff,
                "instruction_count": len(plan.instructions),
            },
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 2. GET /{allocation_id} — detail with instructions
# ---------------------------------------------------------------------------


@router.get(
    "/{allocation_id}",
    response_model=SuccessResponse,
    summary="Get a value allocation with its transfer instructions",
    responses={
        200: {"description": "Allocation detail"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Allocation not found"},
    },
)
async def get_allocation_detail(
    allocation_id: UUID,
    current_user: dict[str, Any] = Depends(
        require_permission("fund_info", "read")
    ),
    repo: ValueTransferRepository = Depends(_get_repo),
) -> JSONResponse:
    """Return a single allocation joined with its instructions."""
    logger.info(
        "value_transfer_get",
        user_id=current_user["id"],
        allocation_id=str(allocation_id),
    )

    allocation = await repo.get_allocation(allocation_id)
    if allocation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="バリュートランスファーが見つかりません",
        )

    return JSONResponse(
        content=SuccessResponse(data=allocation).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 3. POST /{allocation_id}/approve — admin-only lock
# ---------------------------------------------------------------------------


@router.post(
    "/{allocation_id}/approve",
    response_model=SuccessResponse,
    summary="Approve (lock) a value allocation — admin only",
    responses={
        200: {"description": "Allocation approved"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Allocation not found"},
    },
)
async def approve_allocation(
    allocation_id: UUID,
    admin_user: dict[str, Any] = Depends(require_any_role("admin")),
    repo: ValueTransferRepository = Depends(_get_repo),
) -> JSONResponse:
    """Promote a draft allocation to ``approved``. Admin-only."""
    logger.info(
        "value_transfer_approve",
        user_id=admin_user["id"],
        allocation_id=str(allocation_id),
    )

    existing = await repo.get_allocation(allocation_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="バリュートランスファーが見つかりません",
        )

    if existing.get("status") != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"ステータスが {existing.get('status')} のため承認できません"
            ),
        )

    try:
        updated = await repo.approve_allocation(
            allocation_id=allocation_id,
            approver_user_id=UUID(admin_user["id"]),
        )
    except Exception:
        logger.exception(
            "value_transfer_approve_failed",
            allocation_id=str(allocation_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="承認処理中にエラーが発生しました",
        )

    return JSONResponse(
        content=SuccessResponse(data=updated).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 4. GET / — list (optionally filtered by fund)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=SuccessResponse,
    summary="List value allocations",
    responses={
        200: {"description": "Allocation list"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    },
)
async def list_allocations(
    fund_id: Optional[UUID] = Query(default=None, description="Filter by fund"),
    allocation_status: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status (draft / approved / executed)",
    ),
    current_user: dict[str, Any] = Depends(
        require_permission("fund_info", "read")
    ),
    repo: ValueTransferRepository = Depends(_get_repo),
) -> JSONResponse:
    """List allocations with optional fund/status filters."""
    logger.info(
        "value_transfer_list",
        user_id=current_user["id"],
        fund_id=str(fund_id) if fund_id else None,
        status=allocation_status,
    )

    items = await repo.list_allocations(
        fund_id=fund_id, status=allocation_status
    )

    return JSONResponse(
        content=SuccessResponse(
            data=items,
            meta={"count": len(items)},
        ).model_dump(mode="json"),
    )
