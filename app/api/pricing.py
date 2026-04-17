"""Integrated pricing API endpoints."""

from __future__ import annotations
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.dependencies import get_current_user, get_supabase_client
from app.middleware.rbac import require_permission
from app.core.integrated_pricing import IntegratedPricingEngine
from app.db.repositories.pricing_repo import PricingMasterRepository
from app.models.pricing import (
    IntegratedPricingInput,
    IntegratedPricingResult,
    IntegratedPricingResponse,
    PricingMasterCreate,
    PricingMasterResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


def _flatten_for_template(
    result: IntegratedPricingResult,
    input_data: IntegratedPricingInput,
    result_id: str | None,
) -> dict:
    """Build a flat view-model the pricing_result.html partial expects.

    The template pre-dates the nested IntegratedPricingResult schema and
    references `result.step1.*`, `result.step2.*`, `result.step3.*`, plus
    top-level aliases like `result.acquisition_price`. This helper adapts
    the nested model into that flat shape without touching the template.
    """
    acq = result.acquisition
    res = result.residual
    lea = result.lease
    fb = lea.fee_breakdown

    term = input_data.lease_term_months
    invest_yield = input_data.investor_yield_rate or (fb.investor_dividend_portion * 12 / acq.recommended_price if acq.recommended_price else 0)
    am_rate = input_data.am_fee_rate or (fb.am_fee_portion * 12 / acq.recommended_price if acq.recommended_price else 0)
    placement_rate = input_data.placement_fee_rate or (fb.placement_fee_portion * term / acq.recommended_price if acq.recommended_price else 0)
    principal_gap = max(acq.recommended_price - res.base_residual_value, 0)
    op_rate = input_data.operator_margin_rate or (fb.operator_margin_portion * term / principal_gap if principal_gap else 0)

    safety_margin_amount = int(acq.market_median * acq.safety_margin_rate)
    market_deviation = (
        (acq.recommended_price - acq.market_median) / acq.market_median
        if acq.market_median else 0.0
    )

    # Convert NAV curve into the monthly_schedule shape the table expects.
    monthly_schedule = []
    prev_income = 0
    prev_book = acq.recommended_price
    prev_cum_profit = 0
    for p in result.nav_curve:
        lease_income = max(p.cumulative_lease_income - prev_income, 0)
        depreciation = max(prev_book - p.asset_book_value, 0)
        monthly_profit = p.cumulative_profit - prev_cum_profit
        monthly_schedule.append({
            "month": p.month,
            "asset_value": p.asset_book_value,
            "lease_income": lease_income,
            "cumulative_income": p.cumulative_lease_income,
            "depreciation_expense": depreciation,
            "monthly_profit": monthly_profit,
            "cumulative_profit": p.cumulative_profit,
            "nav": p.nav,
        })
        prev_income = p.cumulative_lease_income
        prev_book = p.asset_book_value
        prev_cum_profit = p.cumulative_profit

    return {
        "result_id": result_id,
        "assessment": result.assessment,
        "assessment_reasons": result.assessment_reasons,
        "acquisition_price": acq.recommended_price,
        "residual_value": res.base_residual_value,
        "monthly_lease_fee": lea.monthly_lease_fee,
        "effective_yield_rate": lea.effective_yield_rate,
        "total_lease_fee": lea.total_lease_fee,
        "breakeven_months": lea.breakeven_month,
        "market_deviation_rate": market_deviation,
        "profit_conversion_month": result.profit_conversion_month,
        "step1": {
            "market_median": acq.market_median,
            "sample_count": acq.sample_count,
            "mileage_adjustment": 0,
            "mileage_km": input_data.mileage_km,
            "age_adjustment": 0,
            "vehicle_age_years": res.elapsed_years,
            "body_option_value": acq.body_option_value,
            "safety_margin_amount": safety_margin_amount,
            "safety_margin_rate": acq.safety_margin_rate,
            "trend_factor": acq.trend_factor,
            "trend_direction": acq.trend_direction,
        },
        "step2": {
            "depreciation_method": res.depreciation_method,
            "useful_life_years": res.useful_life_years,
            "book_value_at_end": res.base_residual_value,
            "lease_term_months": term,
            "projected_market_value": res.base_residual_value,
            "scenarios": [s.model_dump() for s in res.scenarios],
        },
        "step3": {
            "principal_monthly": fb.depreciation_portion,
            "principal_total": fb.depreciation_portion * term,
            "investor_yield_monthly": fb.investor_dividend_portion,
            "investor_yield_rate": invest_yield,
            "am_fee_monthly": fb.am_fee_portion,
            "am_fee_rate": am_rate,
            "placement_fee_monthly": fb.placement_fee_portion,
            "placement_fee_rate": placement_rate,
            "accounting_fee_monthly": fb.accounting_fee_portion,
            "operator_margin_monthly": fb.operator_margin_portion,
            "operator_margin_rate": op_rate,
        },
        "monthly_schedule": monthly_schedule,
    }


@router.post("/calculate")
async def calculate_integrated_pricing(
    input_data: IntegratedPricingInput,
    request: Request,
    user=Depends(require_permission("pricing_logic", "read")),
    supabase=Depends(get_supabase_client),
):
    """Run integrated 3-step pricing calculation.

    Step 1: Acquisition price from market data
    Step 2: Residual value with scenarios
    Step 3: Lease fee with stakeholder yields
    + NAV curve generation
    """
    try:
        engine = IntegratedPricingEngine(supabase)

        # Load pricing master if specified
        pricing_params = None
        if input_data.pricing_master_id:
            repo = PricingMasterRepository(supabase)
            master = await repo.get_by_id(input_data.pricing_master_id)
            if master:
                pricing_params = master

        result = await engine.calculate(input_data, pricing_params)

        # Save to simulations table
        sim_data = {
            "user_id": str(user["id"]),
            "title": f"統合プライシング: {input_data.maker} {input_data.model}",
            "input_data": input_data.model_dump(),
            "result": result.model_dump(),
            "status": "completed",
        }
        saved = supabase.table("simulations").insert(sim_data).execute()
        result_id = saved.data[0]["id"] if saved.data else None

        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            flat = _flatten_for_template(result, input_data, result_id)
            nav_labels = [f"{p.month}ヶ月" for p in result.nav_curve]
            from app.main import templates
            return templates.TemplateResponse(
                "partials/pricing_result.html",
                {
                    "request": request,
                    "result": flat,
                    "input_data": input_data,
                    "nav_labels": nav_labels,
                    "nav_book_value": [p.asset_book_value for p in result.nav_curve],
                    "nav_market_value": [p.termination_value for p in result.nav_curve],
                    "nav_cumulative_income": [p.cumulative_lease_income for p in result.nav_curve],
                },
            )

        return JSONResponse(content={
            "status": "success",
            "data": {
                "simulation_id": result_id,
                "result": result.model_dump(),
            }
        })
    except Exception as e:
        logger.error("pricing_calculation_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Pricing calculation failed: {str(e)}")


# --- Pricing Master CRUD ---

@router.get("/masters")
async def list_pricing_masters(
    user=Depends(require_permission("pricing_masters", "read")),
    supabase=Depends(get_supabase_client),
):
    """List all pricing masters."""
    repo = PricingMasterRepository(supabase)
    masters = await repo.list_all()
    return {"status": "success", "data": masters}


@router.post("/masters")
async def create_pricing_master(
    data: PricingMasterCreate,
    user=Depends(require_permission("pricing_masters", "write")),
    supabase=Depends(get_supabase_client),
):
    """Create a new pricing master (admin only)."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    repo = PricingMasterRepository(supabase)
    master = await repo.create(data.model_dump(exclude_none=True))
    return {"status": "success", "data": master}


@router.get("/masters/{master_id}")
async def get_pricing_master(
    master_id: UUID,
    user=Depends(require_permission("pricing_masters", "read")),
    supabase=Depends(get_supabase_client),
):
    """Get a pricing master by ID."""
    repo = PricingMasterRepository(supabase)
    master = await repo.get_by_id(master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Pricing master not found")
    return {"status": "success", "data": master}


@router.put("/masters/{master_id}")
async def update_pricing_master(
    master_id: UUID,
    data: PricingMasterCreate,
    user=Depends(require_permission("pricing_masters", "write")),
    supabase=Depends(get_supabase_client),
):
    """Update a pricing master (admin only)."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    repo = PricingMasterRepository(supabase)
    master = await repo.update(
        master_id,
        data.model_dump(exclude_none=True),
        changed_by=UUID(user["id"])
    )
    return {"status": "success", "data": master}


@router.delete("/masters/{master_id}")
async def delete_pricing_master(
    master_id: UUID,
    user=Depends(require_permission("pricing_masters", "write")),
    supabase=Depends(get_supabase_client),
):
    """Soft-delete a pricing master (admin only)."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    repo = PricingMasterRepository(supabase)
    await repo.delete(master_id)
    return {"status": "success"}


@router.get("/masters/{master_id}/history")
async def get_pricing_master_history(
    master_id: UUID,
    user=Depends(require_permission("pricing_masters", "read")),
    supabase=Depends(get_supabase_client),
):
    """Get parameter change history."""
    repo = PricingMasterRepository(supabase)
    history = await repo.get_history(master_id)
    return {"status": "success", "data": history}
