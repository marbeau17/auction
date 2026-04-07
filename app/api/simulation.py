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
from pydantic import BaseModel, Field
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
# Formatting helpers for HTMX HTML fragments
# ---------------------------------------------------------------------------


def _yen(value: int) -> str:
    """Format an integer as a Japanese-yen string."""
    return f"{value:,}"


def _pct(value: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{value * 100:.2f}%"


def _render_result_fragment(result: SimulationResult) -> str:
    """Return an HTML fragment summarising the simulation result."""
    assessment_class = {
        "推奨": "text-green-700 bg-green-100",
        "要検討": "text-yellow-700 bg-yellow-100",
        "非推奨": "text-red-700 bg-red-100",
    }.get(result.assessment, "")

    rows = "".join(
        f"<tr>"
        f"<td class='px-2 py-1 text-right'>{s.month}</td>"
        f"<td class='px-2 py-1 text-right'>{_yen(s.lease_income)}</td>"
        f"<td class='px-2 py-1 text-right'>{_yen(s.cumulative_income)}</td>"
        f"<td class='px-2 py-1 text-right'>{_yen(s.monthly_profit)}</td>"
        f"<td class='px-2 py-1 text-right'>{_yen(s.cumulative_profit)}</td>"
        f"</tr>"
        for s in result.monthly_schedule
    )

    return f"""
    <div id="simulation-result" class="space-y-4">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">最大購入価格</p>
          <p class="text-lg font-bold">&yen;{_yen(result.max_purchase_price)}</p>
        </div>
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">推奨購入価格</p>
          <p class="text-lg font-bold">&yen;{_yen(result.recommended_purchase_price)}</p>
        </div>
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">月額リース料</p>
          <p class="text-lg font-bold">&yen;{_yen(result.monthly_lease_fee)}</p>
        </div>
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">実効利回り</p>
          <p class="text-lg font-bold">{_pct(result.effective_yield_rate)}</p>
        </div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">リース料総額</p>
          <p class="font-semibold">&yen;{_yen(result.total_lease_fee)}</p>
        </div>
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">残価</p>
          <p class="font-semibold">&yen;{_yen(result.estimated_residual_value)} ({_pct(result.residual_rate_result)})</p>
        </div>
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">損益分岐</p>
          <p class="font-semibold">{f'{result.breakeven_months}ヶ月' if result.breakeven_months else '-'}</p>
        </div>
        <div class="p-3 border rounded">
          <p class="text-xs text-gray-500">市場中央値</p>
          <p class="font-semibold">&yen;{_yen(result.market_median_price)} (n={result.market_sample_count})</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium">総合判定:</span>
        <span class="px-3 py-1 rounded-full text-sm font-bold {assessment_class}">{result.assessment}</span>
      </div>
      <details class="border rounded">
        <summary class="px-4 py-2 cursor-pointer font-medium">月別スケジュール</summary>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50">
                <th class="px-2 py-1 text-right">月</th>
                <th class="px-2 py-1 text-right">リース収入</th>
                <th class="px-2 py-1 text-right">累計収入</th>
                <th class="px-2 py-1 text-right">月次損益</th>
                <th class="px-2 py-1 text-right">累計損益</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </details>
    </div>
    """


def _render_history_table_fragment(
    simulations: list[dict[str, Any]],
    meta: PaginationMeta,
) -> str:
    """Return an HTML table fragment for the simulation history list."""
    if not simulations:
        return '<p class="text-gray-500 py-4 text-center">シミュレーション履歴がありません。</p>'

    rows = ""
    for sim in simulations:
        result = sim.get("result", {})
        assessment = result.get("assessment", "-")
        assessment_class = {
            "推奨": "text-green-700",
            "要検討": "text-yellow-700",
            "非推奨": "text-red-700",
        }.get(assessment, "")
        created = sim.get("created_at", "")[:10]
        monthly_fee = result.get("monthly_lease_fee", 0)
        rows += (
            f"<tr class='border-b hover:bg-gray-50'>"
            f"<td class='px-3 py-2'>"
            f"<a href='/simulation/{sim['id']}/result' "
            f"   hx-get='/api/v1/simulations/{sim['id']}' "
            f"   hx-target='#main-content' "
            f"   class='text-blue-600 hover:underline'>"
            f"{sim.get('title', '-')}</a></td>"
            f"<td class='px-3 py-2 text-right'>&yen;{_yen(monthly_fee)}</td>"
            f"<td class='px-3 py-2 text-center {assessment_class}'>{assessment}</td>"
            f"<td class='px-3 py-2 text-center'>{created}</td>"
            f"<td class='px-3 py-2 text-center'>"
            f"<button hx-delete='/api/v1/simulations/{sim['id']}' "
            f"        hx-confirm='このシミュレーションを削除しますか？' "
            f"        hx-target='closest tr' hx-swap='outerHTML' "
            f"        class='text-red-500 hover:text-red-700 text-sm'>削除</button>"
            f"</td>"
            f"</tr>"
        )

    pagination = ""
    if meta.total_pages > 1:
        pages = "".join(
            f"<button hx-get='/api/v1/simulations?page={p}&per_page={meta.per_page}' "
            f"        hx-target='#simulation-history' hx-swap='innerHTML' "
            f"        class='px-3 py-1 border rounded {'bg-blue-600 text-white' if p == meta.page else 'hover:bg-gray-100'}'>"
            f"{p}</button>"
            for p in range(1, meta.total_pages + 1)
        )
        pagination = f'<div class="flex gap-1 justify-center mt-4">{pages}</div>'

    return f"""
    <table class="w-full text-sm">
      <thead>
        <tr class="bg-gray-50 border-b">
          <th class="px-3 py-2 text-left">タイトル</th>
          <th class="px-3 py-2 text-right">月額リース料</th>
          <th class="px-3 py-2 text-center">判定</th>
          <th class="px-3 py-2 text-center">作成日</th>
          <th class="px-3 py-2 text-center">操作</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    {pagination}
    """


# ---------------------------------------------------------------------------
# 1. POST / - Execute simulation
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
    """Run a pricing simulation, save the result, and return it.

    If the ``HX-Request`` header is present the response is an HTML fragment
    suitable for swapping into the page via htmx.
    """
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
        html = _render_result_fragment(result)
        return HTMLResponse(content=html, status_code=201)

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
        html = _render_history_table_fragment(items, meta)
        return HTMLResponse(content=html)

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
    """Return the full detail of a single simulation.

    The user must own the simulation or have the ``admin`` role.
    """
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
        html = _render_result_fragment(sim_response.result)
        return HTMLResponse(content=html)

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
    """Delete a simulation owned by the current user.

    Only simulations with ``draft`` status can be deleted.
    """
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

    # Authorization: user must own both or be admin
    is_admin = current_user.get("role") == "admin"
    for row in rows:
        if row["user_id"] != current_user["id"] and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="比較対象のシミュレーションへのアクセス権がありません",
            )

    # Ensure consistent ordering (match the requested ID order)
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
# 6. POST /calculate - Quick calculation (no save)
# ---------------------------------------------------------------------------


@router.post(
    "/calculate",
    summary="Quick calculation from form data, returns HTML result fragment",
    responses={
        200: {"description": "Calculation result as HTML fragment"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def calculate_simulation_quick(request: Request) -> HTMLResponse:
    """Quick calculation from form data, returns HTML result fragment.

    Accepts ``application/x-www-form-urlencoded`` data from the simulation
    form and returns an HTML fragment suitable for HTMX swapping.  Does not
    persist results and does not require authentication.
    """
    from app.core.pricing import (
        _assessment,
        _max_purchase_price,
        _monthly_lease_fee,
        _residual_value,
    )

    form = await request.form()

    # Parse form fields with safe defaults
    maker = form.get("maker", "")
    model = form.get("model", "")
    mileage_km = int(form.get("mileage_km", 0) or 0)
    acquisition_price = int(form.get("acquisition_price", 0) or 0)
    book_value = int(form.get("book_value", 0) or 0)
    body_type = form.get("body_type", "")
    body_option_value = int(form.get("body_option_value", 0) or 0)
    target_yield_rate = float(form.get("target_yield_rate", 8.0) or 8.0)
    lease_term_months = int(form.get("lease_term_months", 36) or 36)

    # Calculate max purchase price
    max_price = _max_purchase_price(book_value, acquisition_price, body_option_value)
    recommended_price = int(max_price * 0.95)  # 5% below max

    # Calculate residual value
    residual, residual_rate = _residual_value(recommended_price, lease_term_months)

    # Calculate monthly lease
    monthly_fee = _monthly_lease_fee(
        recommended_price, residual, lease_term_months,
        target_yield_rate / 100, 15000, 10000,
    )

    total_fee = monthly_fee * lease_term_months
    effective_yield = (
        ((total_fee + residual - recommended_price) / recommended_price)
        * (12 / lease_term_months)
        if recommended_price > 0
        else 0
    )

    # Assessment
    assessment = _assessment(effective_yield, target_yield_rate / 100, 0.05)

    # Breakeven
    net_monthly = monthly_fee - 15000 - 10000
    breakeven = math.ceil(recommended_price / net_monthly) if net_monthly > 0 else None

    # Build HTML response
    badge_class = {"推奨": "success", "要検討": "warning", "非推奨": "danger"}.get(
        assessment, ""
    )

    html = f"""
    <div class="result-summary">
        <h3>シミュレーション結果</h3>
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-card__label">推奨買取価格</div>
                <div class="kpi-card__value">&yen;{recommended_price:,}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">上限買取価格</div>
                <div class="kpi-card__value">&yen;{max_price:,}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">月額リース料</div>
                <div class="kpi-card__value">&yen;{monthly_fee:,}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">リース料総額</div>
                <div class="kpi-card__value">&yen;{total_fee:,}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">想定残価</div>
                <div class="kpi-card__value">&yen;{residual:,}</div>
                <div class="kpi-card__sub">残価率 {residual_rate * 100:.0f}%</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">実質利回り</div>
                <div class="kpi-card__value">{effective_yield * 100:.1f}%</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">損益分岐点</div>
                <div class="kpi-card__value">{breakeven if breakeven else "--"}ヶ月</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-card__label">判定</div>
                <div class="kpi-card__value"><span class="badge badge--{badge_class}">{assessment}</span></div>
            </div>
        </div>
        <div class="actions-row" style="margin-top:24px">
            <p><strong>{maker} {model}</strong> | 目標利回り {target_yield_rate}% | {lease_term_months}ヶ月</p>
        </div>
    </div>
    """

    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# 7. POST /calculate-form - Quick calculation from HTML form data (no save)
# ---------------------------------------------------------------------------


@router.post(
    "/calculate-form",
    summary="Quick calculation from form data without saving",
    responses={
        200: {"description": "Calculation result as HTML fragment"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def quick_calculate_form(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    """Run a pricing simulation from HTML form data without persisting.

    Accepts standard form-encoded data from the simulation input page and
    returns an HTML fragment for HTMX to swap into the result preview area.
    Uses the standalone pricing helper functions so it works without a full
    Supabase market-data lookup.
    """
    from app.core.pricing import (
        _assessment,
        _build_schedule,
        _max_purchase_price,
        _monthly_lease_fee,
        _residual_value,
    )

    form = await request.form()

    try:
        maker = form.get("maker", "")
        model = form.get("model", "")
        year = form.get("year", "")
        mileage = int(form.get("mileage", 0) or 0)
        vehicle_class = form.get("vehicle_class", "")
        body_type = form.get("body_type", "")
        acquisition_price = int(form.get("acquisition_price", 0) or 0)
        book_value = int(form.get("book_value", 0) or 0)
        target_yield_rate_pct = float(form.get("target_yield_rate", 0) or 0)
        target_yield_rate = target_yield_rate_pct / 100.0
        lease_term_months = int(form.get("lease_term_months", 0) or 0)
        residual_rate_pct = form.get("residual_rate", "")
        residual_rate = float(residual_rate_pct) / 100.0 if residual_rate_pct else None
        insurance_monthly = int(form.get("insurance_monthly", 0) or 0)
        maintenance_monthly = int(form.get("maintenance_monthly", 0) or 0)
        body_option_value = int(form.get("body_option_value", 0) or 0)
    except (ValueError, TypeError) as exc:
        logger.warning("calculate_form_parse_error", error=str(exc))
        return HTMLResponse(
            content='<div class="alert alert--error">入力値に不正な値があります。数値フィールドを確認してください。</div>',
            status_code=422,
        )

    if lease_term_months <= 0 or acquisition_price <= 0:
        return HTMLResponse(
            content='<div class="alert alert--error">取得価格とリース期間は必須です。</div>',
            status_code=422,
        )

    # Use book_value as a rough market proxy when no DB lookup is available
    market_median = book_value if book_value > 0 else acquisition_price

    max_price = _max_purchase_price(book_value, market_median, body_option_value)
    recommended_price = int(max_price * 0.95)
    rv, rv_rate = _residual_value(recommended_price, lease_term_months, residual_rate)
    monthly_fee = _monthly_lease_fee(
        recommended_price, rv, lease_term_months, target_yield_rate,
        insurance_monthly, maintenance_monthly,
    )
    total_fee = monthly_fee * lease_term_months
    effective_yield = (
        (total_fee + rv - recommended_price) / recommended_price / (lease_term_months / 12)
        if recommended_price > 0 and lease_term_months > 0
        else 0.0
    )
    market_deviation = (
        (recommended_price - market_median) / market_median
        if market_median > 0
        else 0.0
    )
    assessment = _assessment(effective_yield, target_yield_rate, market_deviation)

    schedule = _build_schedule(
        recommended_price, rv, lease_term_months, monthly_fee,
        target_yield_rate, insurance_monthly, maintenance_monthly,
    )

    breakeven_months = None
    for item in schedule:
        if item.cumulative_profit >= 0:
            breakeven_months = item.month
            break

    result = SimulationResult(
        max_purchase_price=max_price,
        recommended_purchase_price=recommended_price,
        estimated_residual_value=rv,
        residual_rate_result=rv_rate,
        monthly_lease_fee=monthly_fee,
        total_lease_fee=total_fee,
        breakeven_months=breakeven_months,
        effective_yield_rate=effective_yield,
        market_median_price=market_median,
        market_sample_count=0,
        market_deviation_rate=market_deviation,
        assessment=assessment,
        monthly_schedule=schedule,
    )

    html = _render_result_fragment(result)
    return HTMLResponse(content=html)
