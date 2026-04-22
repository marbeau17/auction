"""Simulation API router.

Provides endpoints to execute, list, retrieve, delete, compare, and
quick-calculate commercial vehicle leaseback pricing simulations.
All endpoints require an authenticated user (JWT via cookie).  Endpoints
that may be called from HTMX return an HTML fragment when the ``HX-Request``
header is present; otherwise they return JSON.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from supabase import Client

from app.core.pricing import calculate_simulation
from app.db.repositories.simulation_repo import SimulationRepository
from app.dependencies import get_current_user, get_supabase_client
from app.main import templates
from app.models.common import (
    ErrorResponse,
    PaginatedResponse,
    PaginationMeta,
    SuccessResponse,
)
from app.models.simulation import (
    SimulationInput,
    SimulationResponse,
    SimulationResult,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/simulations", tags=["simulation"])


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    """Body for the compare endpoint."""

    simulation_ids: list[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Exactly two simulation IDs to compare",
    )


class ComparisonItem(BaseModel):
    """One side of a simulation comparison."""

    id: str
    title: str
    input_data: dict[str, Any]
    result: dict[str, Any]


class ComparisonDiff(BaseModel):
    """Numeric differences between two simulation results."""

    max_purchase_price: int = 0
    recommended_purchase_price: int = 0
    monthly_lease_fee: int = 0
    total_lease_fee: int = 0
    effective_yield_rate: float = 0.0
    breakeven_months: Optional[int] = None
    estimated_residual_value: int = 0
    market_deviation_rate: float = 0.0


class CompareResponse(BaseModel):
    """Response for the compare endpoint."""

    simulations: list[ComparisonItem]
    diff: ComparisonDiff


def _is_htmx(request: Request) -> bool:
    """Return ``True`` when the request originates from htmx."""
    return request.headers.get("HX-Request", "").lower() == "true"


def _get_repo(supabase: Client = Depends(get_supabase_client)) -> SimulationRepository:
    """Provide a ``SimulationRepository`` via dependency injection."""
    return SimulationRepository(client=supabase)


def _row_to_response(row: dict[str, Any]) -> SimulationResponse:
    """Convert a raw DB row dict into a ``SimulationResponse``."""
    return SimulationResponse(
        id=row["id"],
        user_id=row["user_id"],
        title=row.get("title", ""),
        input_data=SimulationInput(**row["input_data"]),
        result=SimulationResult(**row["result"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _compute_diff(a: dict[str, Any], b: dict[str, Any]) -> ComparisonDiff:
    """Compute the numeric difference ``b - a`` for key result fields."""

    def _int_diff(key: str) -> int:
        return int(b.get(key, 0) or 0) - int(a.get(key, 0) or 0)

    def _float_diff(key: str) -> float:
        return float(b.get(key, 0.0) or 0.0) - float(a.get(key, 0.0) or 0.0)

    be_a = a.get("breakeven_months")
    be_b = b.get("breakeven_months")
    be_diff = (be_b - be_a) if (be_a is not None and be_b is not None) else None

    return ComparisonDiff(
        max_purchase_price=_int_diff("max_purchase_price"),
        recommended_purchase_price=_int_diff("recommended_purchase_price"),
        monthly_lease_fee=_int_diff("monthly_lease_fee"),
        total_lease_fee=_int_diff("total_lease_fee"),
        effective_yield_rate=round(_float_diff("effective_yield_rate"), 6),
        breakeven_months=be_diff,
        estimated_residual_value=_int_diff("estimated_residual_value"),
        market_deviation_rate=round(_float_diff("market_deviation_rate"), 6),
    )


# ---------------------------------------------------------------------------
# Form-data parsing helpers
# ---------------------------------------------------------------------------


def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _form_to_input_dict(form_data: Any) -> dict[str, Any]:
    """Convert a Starlette FormData (or dict) into a SimulationInput-shaped dict.

    Honours the simulation form's idiosyncratic shapes:
    * ``model_select`` / ``model_custom`` fall-back chain
    * Separate ``registration_year`` + ``registration_month`` selects
      (also accepts a combined ``registration_year_month`` for legacy callers)
    * Target yield is posted as a percentage (e.g. ``8`` = 8%)
    """
    get = form_data.get
    getlist = (
        form_data.getlist
        if hasattr(form_data, "getlist")
        else (lambda k: form_data.get(k, []))
    )

    model = get("model", "") or get("model_custom", "") or get("model_select", "")
    if model == "__custom__":
        model = get("model_custom", "")

    # Build registration_year_month from either the new split selects or any
    # legacy combined value. The Pydantic validator handles year-only inputs.
    reg_year = get("registration_year") or ""
    reg_month = get("registration_month") or ""
    if reg_year:
        reg_ym = f"{reg_year}-{reg_month}" if reg_month else str(reg_year)
    else:
        reg_ym = str(get("registration_year_month") or "")

    target_yield_raw = _to_float(get("target_yield_rate"), 0.0)
    # Form posts a percentage (8 means 8%). JSON callers may post 0.08 directly;
    # treat <=1 as already-decimal to keep both shapes working.
    target_yield = (
        target_yield_raw if 0 < target_yield_raw <= 1 else target_yield_raw / 100.0
    )

    body_option_value = _to_int(get("body_option_value"), 0) or None
    insurance_monthly = _to_int(get("insurance_monthly"), 0) or None
    maintenance_monthly = _to_int(get("maintenance_monthly"), 0) or None

    payload_ton = get("payload_ton")
    payload_ton_val = _to_float(payload_ton) if payload_ton not in (None, "") else None

    residual_rate_raw = get("residual_rate")
    residual_rate: float | None = None
    if residual_rate_raw not in (None, ""):
        rr = _to_float(residual_rate_raw)
        residual_rate = rr if 0 < rr <= 1 else rr / 100.0

    return {
        "maker": str(get("maker") or "").strip(),
        "model": str(model or "").strip(),
        "model_code": (str(get("model_code")).strip() or None) if get("model_code") else None,
        "registration_year_month": reg_ym,
        "mileage_km": _to_int(get("mileage_km"), 0),
        "acquisition_price": _to_int(get("acquisition_price"), 0),
        "book_value": _to_int(get("book_value"), 0),
        "vehicle_class": str(get("vehicle_class") or "").strip(),
        "payload_ton": payload_ton_val,
        "body_type": str(get("body_type") or "").strip(),
        "body_option_value": body_option_value,
        "target_yield_rate": target_yield,
        "lease_term_months": _to_int(get("lease_term_months"), 0),
        "residual_rate": residual_rate,
        "insurance_monthly": insurance_monthly,
        "maintenance_monthly": maintenance_monthly,
        "remarks": str(get("remarks") or "").strip() or None,
        # Equipment list isn't part of SimulationInput; carried separately.
        "_equipment": list(getlist("equipment") or []),
    }


async def _parse_simulation_payload(
    request: Request,
) -> tuple[SimulationInput, list[str]]:
    """Parse the incoming request body into a ``SimulationInput``.

    Accepts either ``application/json`` or ``application/x-www-form-urlencoded``
    / ``multipart/form-data``. Returns ``(SimulationInput, equipment_list)``.
    Raises ``HTTPException(422)`` on validation errors.
    """
    content_type = request.headers.get("content-type", "").lower()
    equipment_list: list[str] = []

    try:
        if "application/json" in content_type:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            sim_input = SimulationInput(**body)
        else:
            form = await request.form()
            payload = _form_to_input_dict(form)
            equipment_list = payload.pop("_equipment", []) or []
            sim_input = SimulationInput(**payload)
    except ValidationError as exc:
        # Pydantic v2's ValidationError.errors() embeds raw `ValueError` objects
        # under `ctx.error`, which FastAPI then tries to json.dumps → 500.
        # Strip non-serialisable ctx so the client gets a clean 422 instead.
        safe_errors = [
            {k: v for k, v in err.items() if k != "ctx"}
            for err in exc.errors()
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=safe_errors,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return sim_input, equipment_list


def _build_chart_context(
    result: SimulationResult, recommended_price: int
) -> dict[str, Any]:
    """Extract the JSON-friendly chart series the result_card template needs."""
    schedule = result.monthly_schedule
    labels = [f"{s.month}月" for s in schedule]
    asset = [s.asset_value for s in schedule]
    cum_income = [s.cumulative_income for s in schedule]
    monthly_pl = [s.monthly_profit for s in schedule]
    cum_pl = [s.cumulative_profit for s in schedule]
    nav = [
        round(
            ((s.asset_value + s.cumulative_income) / recommended_price * 100.0)
            if recommended_price > 0
            else 0.0,
            2,
        )
        for s in schedule
    ]
    return {
        "chart_labels": labels,
        "chart_asset": asset,
        "chart_cum_income": cum_income,
        "chart_monthly_pl": monthly_pl,
        "chart_cum_pl": cum_pl,
        "chart_nav_ratios": nav,
        "chart_nav_baseline": [60] * len(schedule),
    }


# ---------------------------------------------------------------------------
# 1. POST / - Execute simulation (canonical, JSON-only persistence path)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute a leaseback simulation",
    responses={
        201: {"description": "Simulation created successfully"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def create_simulation(
    request: Request,
    input_data: SimulationInput,
    current_user: dict[str, Any] = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
    repo: SimulationRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Run a pricing simulation, save the result, and return it."""
    logger.info(
        "simulation_execute",
        user_id=current_user["id"],
        maker=input_data.maker,
        model=input_data.model,
    )

    try:
        result = await calculate_simulation(input_data=input_data, supabase=supabase)
    except Exception:
        logger.exception("simulation_calculation_failed", user_id=current_user["id"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="シミュレーション計算中にエラーが発生しました",
        )

    try:
        row = await repo.create(
            user_id=current_user["id"],
            input_data=input_data.model_dump(mode="json"),
            result=result.model_dump(mode="json"),
        )
    except Exception:
        logger.exception("simulation_save_failed", user_id=current_user["id"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="シミュレーション保存中にエラーが発生しました",
        )

    sim_response = _row_to_response(row)

    if _is_htmx(request):
        ctx = {
            "request": request,
            "result": result,
            "input_data": input_data,
            "saved_simulation_id": str(sim_response.id),
            "equipment_list": [],
            **_build_chart_context(result, result.recommended_purchase_price),
        }
        return templates.TemplateResponse(
            "partials/simulation/result_card.html", ctx, status_code=201
        )

    return JSONResponse(
        content=SuccessResponse(
            data=sim_response.model_dump(mode="json"),
            meta={"simulation_id": str(sim_response.id)},
        ).model_dump(mode="json"),
        status_code=201,
    )


# ---------------------------------------------------------------------------
# 2. GET / - List simulation history
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PaginatedResponse[dict[str, Any]],
    summary="List simulation history",
    responses={
        200: {"description": "Paginated simulation list"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_simulations(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    sort: str = "created_at",
    order: Literal["asc", "desc"] = "desc",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: dict[str, Any] = Depends(get_current_user),
    repo: SimulationRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return the authenticated user's simulation history (paginated)."""
    items, total_count = await repo.list_by_user(
        user_id=current_user["id"],
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
        date_from=date_from,
        date_to=date_to,
    )

    total_pages = max(1, math.ceil(total_count / per_page))
    meta = PaginationMeta(
        total_count=total_count,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )

    if _is_htmx(request):
        return templates.TemplateResponse(
            "partials/simulation/history_table.html",
            {"request": request, "simulations": items, "meta": meta},
        )

    return JSONResponse(
        content=PaginatedResponse[dict[str, Any]](
            data=items,
            meta=meta,
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 3. GET /{simulation_id} - Get simulation detail
# ---------------------------------------------------------------------------


@router.get(
    "/{simulation_id}",
    response_model=SuccessResponse,
    summary="Get simulation detail",
    responses={
        200: {"description": "Simulation detail"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not found"},
    },
)
async def get_simulation(
    request: Request,
    simulation_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    repo: SimulationRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return the full detail of a single simulation."""
    row = await repo.get_by_id(simulation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="シミュレーションが見つかりません",
        )

    is_owner = row["user_id"] == current_user["id"]
    is_admin = current_user.get("role") == "admin"
    if not is_owner and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このシミュレーションへのアクセス権がありません",
        )

    sim_response = _row_to_response(row)

    if _is_htmx(request):
        ctx = {
            "request": request,
            "result": sim_response.result,
            "input_data": sim_response.input_data,
            "saved_simulation_id": str(sim_response.id),
            "equipment_list": [],
            **_build_chart_context(
                sim_response.result, sim_response.result.recommended_purchase_price
            ),
        }
        return templates.TemplateResponse(
            "partials/simulation/result_card.html", ctx
        )

    return JSONResponse(
        content=SuccessResponse(
            data=sim_response.model_dump(mode="json"),
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 4. DELETE /{simulation_id} - Delete simulation
# ---------------------------------------------------------------------------


@router.delete(
    "/{simulation_id}",
    response_model=SuccessResponse,
    summary="Delete a simulation",
    responses={
        200: {"description": "Simulation deleted"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden or wrong status"},
        404: {"model": ErrorResponse, "description": "Not found"},
    },
)
async def delete_simulation(
    simulation_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    repo: SimulationRepository = Depends(_get_repo),
) -> JSONResponse:
    """Delete a simulation owned by the current user."""
    row = await repo.get_by_id(simulation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="シミュレーションが見つかりません",
        )

    if row["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="自分のシミュレーションのみ削除できます",
        )

    if row.get("status") != "draft":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="下書きステータスのシミュレーションのみ削除できます",
        )

    deleted = await repo.delete(simulation_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="削除処理に失敗しました",
        )

    logger.info(
        "simulation_deleted",
        simulation_id=simulation_id,
        user_id=current_user["id"],
    )

    return JSONResponse(
        content=SuccessResponse(
            data={"deleted": True, "id": simulation_id},
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 5. POST /compare - Compare two simulations
# ---------------------------------------------------------------------------


@router.post(
    "/compare",
    response_model=SuccessResponse,
    summary="Compare two simulations",
    responses={
        200: {"description": "Comparison result"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Simulation not found"},
    },
)
async def compare_simulations(
    body: CompareRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    repo: SimulationRepository = Depends(_get_repo),
) -> JSONResponse:
    """Return two simulations side-by-side with computed differences."""
    rows = await repo.get_multiple(body.simulation_ids)

    if len(rows) != 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたシミュレーションの一部が見つかりません",
        )

    is_admin = current_user.get("role") == "admin"
    for row in rows:
        if row["user_id"] != current_user["id"] and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="比較対象のシミュレーションへのアクセス権がありません",
            )

    id_to_row = {row["id"]: row for row in rows}
    ordered = [id_to_row[sid] for sid in body.simulation_ids]

    comparison_items = [
        ComparisonItem(
            id=r["id"],
            title=r.get("title", ""),
            input_data=r["input_data"],
            result=r["result"],
        )
        for r in ordered
    ]

    diff = _compute_diff(ordered[0]["result"], ordered[1]["result"])

    compare_resp = CompareResponse(
        simulations=comparison_items,
        diff=diff,
    )

    return JSONResponse(
        content=SuccessResponse(
            data=compare_resp.model_dump(mode="json"),
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 6. POST /calculate - Unified form/JSON entry point used by the page form
# ---------------------------------------------------------------------------


@router.post(
    "/calculate",
    response_model=None,
    summary="Run a leaseback simulation from form or JSON input and persist it",
    responses={
        200: {"description": "Calculation result as HTML fragment (HTMX) or JSON"},
        201: {"description": "Calculation result with persisted simulation"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def calculate_simulation_quick(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
    repo: SimulationRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Run a pricing simulation from form-encoded or JSON data, then persist it.

    The simulation form (``hx-post="/api/v1/simulations/calculate"``) sends
    ``application/x-www-form-urlencoded`` data, while integration / monkey
    tests post JSON. This endpoint accepts both, normalises them through
    :class:`SimulationInput` (which absorbs year-only inputs), runs
    :func:`calculate_simulation` end-to-end, persists via
    :class:`SimulationRepository`, and returns either the result-card HTMX
    fragment or a JSON envelope mirroring ``create_simulation``.
    """
    sim_input, equipment_list = await _parse_simulation_payload(request)

    logger.info(
        "simulation_calculate",
        user_id=current_user["id"],
        maker=sim_input.maker,
        model=sim_input.model,
        equipment_count=len(equipment_list),
    )

    try:
        result = await calculate_simulation(input_data=sim_input, supabase=supabase)
    except Exception:
        logger.exception(
            "simulation_calculate_failed", user_id=current_user["id"]
        )
        if _is_htmx(request):
            return HTMLResponse(
                content=(
                    '<div class="alert alert--error">'
                    'シミュレーション計算に失敗しました。入力値を確認してください。'
                    '</div>'
                ),
                status_code=422,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="シミュレーション計算中にエラーが発生しました",
        )

    saved_id: str | None = None
    try:
        row = await repo.create(
            user_id=current_user["id"],
            input_data=sim_input.model_dump(mode="json"),
            result=result.model_dump(mode="json"),
        )
        saved_id = str(row["id"])
    except Exception:
        # Persist-failure must not block returning the calculated result —
        # the user still wants to see the numbers. Logged for ops follow-up.
        logger.exception(
            "simulation_calculate_save_failed", user_id=current_user["id"]
        )

    if _is_htmx(request):
        ctx = {
            "request": request,
            "result": result,
            "input_data": sim_input,
            "saved_simulation_id": saved_id,
            "equipment_list": equipment_list,
            **_build_chart_context(result, result.recommended_purchase_price),
        }
        try:
            return templates.TemplateResponse(
                "partials/simulation/result_card.html",
                ctx,
                status_code=201 if saved_id else 200,
            )
        except Exception:
            # Template rendering failure must not surface as a 500 — the
            # calculation (and persistence, if any) already succeeded.
            logger.exception(
                "sim_calc_template_render_failed", saved_id=saved_id
            )
            if saved_id:
                fallback = (
                    '<div class="alert alert--error">'
                    '結果表示でエラーが発生しました。シミュレーションは保存されました。'
                    f' <a href="/simulation/{saved_id}/result">保存結果を確認</a>'
                    '</div>'
                )
                return HTMLResponse(content=fallback, status_code=200)
            return HTMLResponse(
                content=(
                    '<div class="alert alert--error">'
                    '結果表示でエラーが発生しました。'
                    '</div>'
                ),
                status_code=500,
            )

    payload: dict[str, Any] = {
        "input_data": sim_input.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }
    if saved_id:
        payload["simulation_id"] = saved_id
    return JSONResponse(
        content=SuccessResponse(
            data=payload,
            meta={"simulation_id": saved_id} if saved_id else None,
        ).model_dump(mode="json"),
        status_code=201 if saved_id else 200,
    )
