"""Financial AI Diagnosis API endpoints."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.dependencies import get_current_user, get_supabase_client
from app.middleware.rbac import require_permission
from app.models.financial import (
    FinancialAnalysisHistoryEntry,
    FinancialAnalysisInput,
    FinancialAnalysisResult,
    FinancialWithPricingInput,
    FinancialWithPricingResult,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/financial", tags=["financial"])


# ------------------------------------------------------------------ #
# Helpers – pure-function financial scoring
# ------------------------------------------------------------------ #


def _compute_ratios(inp: FinancialAnalysisInput) -> dict:
    """Derive financial ratios from raw inputs."""
    equity_ratio = inp.equity / inp.total_assets if inp.total_assets else 0.0
    current_ratio = (
        inp.current_assets / inp.current_liabilities
        if inp.current_liabilities
        else 999.0
    )
    quick_ratio = (
        (inp.quick_assets / inp.current_liabilities)
        if inp.quick_assets is not None and inp.current_liabilities
        else None
    )
    debt_ratio = (
        inp.total_liabilities / inp.equity if inp.equity > 0 else 999.0
    )
    operating_profit_margin = (
        inp.operating_profit / inp.revenue if inp.revenue else 0.0
    )
    # Simplified EBITDA = operating_profit (depreciation not provided)
    ebitda = inp.operating_profit
    lease_to_revenue = (
        (inp.existing_lease_monthly * 12) / inp.revenue if inp.revenue else 0.0
    )
    return {
        "equity_ratio": round(equity_ratio, 4),
        "current_ratio": round(current_ratio, 4),
        "quick_ratio": round(quick_ratio, 4) if quick_ratio is not None else None,
        "debt_ratio": round(debt_ratio, 4),
        "operating_profit_margin": round(operating_profit_margin, 4),
        "ebitda": ebitda,
        "lease_to_revenue_ratio": round(lease_to_revenue, 4),
    }


def _score_component(value: float, thresholds: list[tuple[float, float]]) -> float:
    """Score a single metric 0-100 based on (threshold, score) pairs (descending)."""
    for threshold, score in thresholds:
        if value >= threshold:
            return score
    return thresholds[-1][1] if thresholds else 0.0


def _run_analysis(inp: FinancialAnalysisInput) -> FinancialAnalysisResult:
    """Execute the financial diagnosis algorithm."""
    ratios = _compute_ratios(inp)

    # Detail scores by category
    profitability = _score_component(
        ratios["operating_profit_margin"],
        [(0.08, 100), (0.05, 80), (0.03, 60), (0.01, 40), (0.0, 20)],
    )
    safety = _score_component(
        ratios["equity_ratio"],
        [(0.50, 100), (0.35, 80), (0.20, 60), (0.10, 40), (0.0, 20)],
    )
    liquidity = _score_component(
        ratios["current_ratio"],
        [(2.0, 100), (1.5, 80), (1.2, 60), (1.0, 40), (0.0, 20)],
    )
    efficiency = 50.0  # baseline
    if inp.vehicle_count > 0 and inp.vehicle_utilization_rate > 0:
        efficiency = _score_component(
            inp.vehicle_utilization_rate,
            [(0.90, 100), (0.80, 80), (0.70, 60), (0.60, 40), (0.0, 20)],
        )

    detail_scores = {
        "収益性": profitability,
        "安全性": safety,
        "流動性": liquidity,
        "効率性": efficiency,
    }

    score_numeric = round(
        profitability * 0.30
        + safety * 0.30
        + liquidity * 0.25
        + efficiency * 0.15,
        1,
    )

    # Letter grade
    if score_numeric >= 80:
        score = "A"
    elif score_numeric >= 60:
        score = "B"
    elif score_numeric >= 40:
        score = "C"
    else:
        score = "D"

    # Risk level
    risk_map = {"A": "推奨", "B": "推奨", "C": "要注意", "D": "非推奨"}
    risk_level = risk_map[score]

    # Max monthly lease capacity (heuristic: 10-20% of monthly revenue minus existing)
    monthly_revenue = inp.revenue / 12 if inp.revenue else 0
    capacity_rate = 0.15 if score in ("A", "B") else 0.08
    max_monthly_lease = max(
        0, int(monthly_revenue * capacity_rate - inp.existing_lease_monthly)
    )

    # Recommended lease terms
    if score in ("A", "B"):
        term_min, term_max = 24, 60
    elif score == "C":
        term_min, term_max = 12, 36
    else:
        term_min, term_max = 12, 24

    # Recommendations & warnings
    recommendations: list[str] = []
    warnings: list[str] = []

    if ratios["equity_ratio"] >= 0.35:
        recommendations.append("自己資本比率が高く安定した財務体質です")
    if ratios["current_ratio"] >= 1.5:
        recommendations.append("流動性が十分で短期支払能力に問題ありません")
    if ratios["operating_profit_margin"] >= 0.05:
        recommendations.append("営業利益率が良好です")
    if max_monthly_lease > 0:
        recommendations.append(
            f"追加リース余力: 月額約{max_monthly_lease:,}円"
        )

    if ratios["equity_ratio"] < 0.20:
        warnings.append("自己資本比率が低く財務リスクが高い状態です")
    if ratios["current_ratio"] < 1.0:
        warnings.append("流動比率が1.0未満で短期資金繰りに懸念があります")
    if ratios["debt_ratio"] > 3.0:
        warnings.append("負債比率が高く過剰債務の可能性があります")
    if ratios["lease_to_revenue_ratio"] > 0.10:
        warnings.append("既存リース負担率が売上高の10%を超えています")
    if inp.operating_profit < 0:
        warnings.append("営業利益がマイナスです。リース審査に大きく影響します")

    return FinancialAnalysisResult(
        score=score,
        score_numeric=score_numeric,
        risk_level=risk_level,
        max_monthly_lease=max_monthly_lease,
        recommended_lease_term_min=term_min,
        recommended_lease_term_max=term_max,
        equity_ratio=ratios["equity_ratio"],
        current_ratio=ratios["current_ratio"],
        quick_ratio=ratios["quick_ratio"],
        debt_ratio=ratios["debt_ratio"],
        operating_profit_margin=ratios["operating_profit_margin"],
        ebitda=ratios["ebitda"],
        lease_to_revenue_ratio=ratios["lease_to_revenue_ratio"],
        recommendations=recommendations,
        warnings=warnings,
        detail_scores=detail_scores,
    )


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #


@router.post("/analyze")
async def analyze_financials(
    input_data: FinancialAnalysisInput,
    request: Request,
    # NOTE: RBAC_MATRIX has no dedicated "financial_analysis" entry yet;
    # gating on "simulations"/read as the closest semantic match per audit.
    user=Depends(require_permission("simulations", "read")),
    supabase=Depends(get_supabase_client),
):
    """Run financial AI diagnosis for a transport company.

    Computes financial ratios, scores the company across profitability /
    safety / liquidity / efficiency dimensions, and returns an overall
    grade with lease capacity recommendations.
    """
    try:
        result = _run_analysis(input_data)

        # Persist to database
        row = {
            "user_id": str(user["id"]),
            "company_name": input_data.company_name,
            "input_data": input_data.model_dump(),
            "result": result.model_dump(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        saved = (
            supabase.table("financial_analyses").insert(row).execute()
        )

        return JSONResponse(content={
            "status": "success",
            "data": {
                "id": saved.data[0]["id"] if saved.data else None,
                "result": result.model_dump(),
            },
        })
    except Exception as e:
        logger.error("financial_analysis_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Financial analysis failed: {str(e)}",
        )


@router.post("/analyze-with-pricing")
async def analyze_with_pricing(
    input_data: FinancialWithPricingInput,
    request: Request,
    # NOTE: No dedicated "financial_analysis" matrix entry; gate on
    # "simulations"/read as the closest semantic match per audit.
    user=Depends(require_permission("simulations", "read")),
    supabase=Depends(get_supabase_client),
):
    """Run combined financial analysis + pricing simulation.

    Performs financial diagnosis first, then runs the integrated pricing
    engine, and returns a merged result with an overall assessment.
    """
    try:
        # Step 1: Financial analysis
        fin_result = _run_analysis(input_data.financial)

        # Step 2: Pricing simulation
        from app.core.integrated_pricing import IntegratedPricingEngine
        from app.db.repositories.pricing_repo import PricingMasterRepository

        engine = IntegratedPricingEngine(supabase)
        pricing_params = None
        if input_data.pricing.pricing_master_id:
            repo = PricingMasterRepository(supabase)
            master = await repo.get_by_id(input_data.pricing.pricing_master_id)
            if master:
                pricing_params = master

        pricing_result = await engine.calculate(input_data.pricing, pricing_params)

        # Step 3: Combined assessment
        fin_ok = fin_result.score in ("A", "B")
        pricing_ok = pricing_result.assessment == "推奨"

        if fin_ok and pricing_ok:
            overall = "推奨"
            reasons = ["財務スコアが良好かつプライシング評価も推奨"]
        elif fin_ok or pricing_ok:
            overall = "要検討"
            reasons = []
            if not fin_ok:
                reasons.append(f"財務スコア{fin_result.score}: 要注意項目あり")
            if not pricing_ok:
                reasons.append(f"プライシング評価: {pricing_result.assessment}")
        else:
            overall = "非推奨"
            reasons = [
                f"財務スコア{fin_result.score}",
                f"プライシング評価: {pricing_result.assessment}",
            ]

        combined = FinancialWithPricingResult(
            financial=fin_result,
            pricing=pricing_result,
            overall_assessment=overall,
            overall_reasons=reasons,
        )

        # Persist
        row = {
            "user_id": str(user["id"]),
            "company_name": input_data.financial.company_name,
            "input_data": {
                "financial": input_data.financial.model_dump(),
                "pricing": input_data.pricing.model_dump(),
            },
            "result": combined.model_dump(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        saved = (
            supabase.table("financial_analyses").insert(row).execute()
        )

        return JSONResponse(content={
            "status": "success",
            "data": {
                "id": saved.data[0]["id"] if saved.data else None,
                "result": combined.model_dump(),
            },
        })
    except Exception as e:
        logger.error("financial_with_pricing_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Financial analysis with pricing failed: {str(e)}",
        )


@router.get("/history/{company_name}")
async def get_financial_history(
    company_name: str,
    # NOTE: No dedicated "financial_analysis" matrix entry; gate on
    # "simulations"/read as the closest semantic match per audit.
    user=Depends(require_permission("simulations", "read")),
    supabase=Depends(get_supabase_client),
):
    """Get past financial analyses for a company.

    Returns all historical analyses ordered by creation date descending.
    """
    try:
        response = (
            supabase.table("financial_analyses")
            .select("*")
            .eq("company_name", company_name)
            .order("created_at", desc=True)
            .execute()
        )

        return JSONResponse(content={
            "status": "success",
            "data": response.data,
        })
    except Exception as e:
        logger.error(
            "financial_history_fetch_failed",
            company_name=company_name,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch financial history: {str(e)}",
        )
