"""Financial AI Diagnosis API endpoints."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.core.finance_llm_extractor import (
    BudgetExceeded,
    FinanceLLMExtractor,
    FinancialInputSchema,
)
from app.core.financial_analyzer import FinancialAnalyzer, FinancialInput
from app.core.pdf_text_extractor import PDFExtractionError, extract as pdf_extract
from app.db.repositories.finance_assessment_repo import FinanceAssessmentRepository
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


# ====================================================================== #
# Finance Assessment — Phase-1 (LLM-extracted 決算書 → rule diagnosis)
# ====================================================================== #
#
# All routes below are dark-launched behind ``settings.finance_llm_enabled``.
# They are admin/operator-only via the ``financial`` entry in RBAC_MATRIX.


def _get_finance_repo(
    supabase=Depends(get_supabase_client),
) -> FinanceAssessmentRepository:
    """Dependency factory for the finance-assessment repository."""
    return FinanceAssessmentRepository(client=supabase)


def _require_finance_llm_enabled(settings: Settings) -> None:
    """Feature-flag gate — raises 503 when the LLM pipeline is disabled."""
    if not settings.finance_llm_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="finance assessment feature disabled",
        )


def _build_genai_client(api_key: str):
    """Construct a ``google.genai.Client``. Overridden in tests."""
    from google import genai  # local import — optional dep at test time

    return genai.Client(api_key=api_key)


class AssessDocumentResponse(BaseModel):
    """Response envelope for ``POST /assess-document``."""

    id: str
    cached: bool = False
    diagnosis: dict[str, Any]
    extracted_input: dict[str, Any]
    narrative: Optional[str] = None
    extraction_warnings: list[str] = Field(default_factory=list)
    needs_vision: bool = False
    llm_tokens_used: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0


_REQUIRED_FIELDS = (
    "revenue",
    "operating_profit",
    "ordinary_profit",
    "total_assets",
    "total_liabilities",
    "equity",
    "current_assets",
    "current_liabilities",
)


def _schema_to_financial_input(
    schema: FinancialInputSchema,
) -> tuple[FinancialInput, list[str]]:
    """Project the LLM schema (Optional fields) into the strict dataclass.

    Returns the dataclass and a list of required-field names that were
    ``None`` in the schema. Missing required fields are back-filled with
    ``0`` so construction succeeds; the caller decides whether to 422
    based on the warnings list.
    """
    data = schema.model_dump()
    missing: list[str] = []
    for field_name in _REQUIRED_FIELDS:
        if data.get(field_name) is None:
            missing.append(field_name)
            data[field_name] = 0

    fi = FinancialInput(
        company_name=data["company_name"],
        revenue=data["revenue"],
        operating_profit=data["operating_profit"],
        ordinary_profit=data["ordinary_profit"],
        total_assets=data["total_assets"],
        total_liabilities=data["total_liabilities"],
        equity=data["equity"],
        current_assets=data["current_assets"],
        current_liabilities=data["current_liabilities"],
        quick_assets=data.get("quick_assets"),
        interest_bearing_debt=data.get("interest_bearing_debt") or 0,
        operating_cf=data.get("operating_cf"),
        free_cf=data.get("free_cf"),
        vehicle_count=data.get("vehicle_count") or 0,
        vehicle_utilization_rate=data.get("vehicle_utilization_rate") or 0.0,
        existing_lease_monthly=data.get("existing_lease_monthly") or 0,
        existing_loan_balance=data.get("existing_loan_balance") or 0,
    )
    return fi, missing


def _diagnosis_to_dict(d) -> dict[str, Any]:
    """``FinancialDiagnosisResult`` is a dataclass; ``asdict`` is safe."""
    return asdict(d)


def _financial_input_to_dict(fi: FinancialInput) -> dict[str, Any]:
    return asdict(fi)


@router.post(
    "/assess-document",
    summary="Upload a 決算書 PDF and run the LLM-extract + rule-diagnose pipeline",
)
async def assess_document(
    request: Request,
    file: UploadFile = File(...),
    company_name: str = Form(...),
    narrative: bool = Form(False),
    current_user: dict[str, Any] = Depends(require_permission("financial", "write")),
    settings: Settings = Depends(get_settings),
    repo: FinanceAssessmentRepository = Depends(_get_finance_repo),
) -> JSONResponse:
    """Dark-launched PDF-to-diagnosis pipeline (feature-flag gated)."""
    _require_finance_llm_enabled(settings)

    # 1. Read + size-check
    pdf_bytes = await file.read()
    max_bytes = settings.finance_llm_max_pdf_mb * 1024 * 1024
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"PDF size exceeds {settings.finance_llm_max_pdf_mb} MB cap",
        )

    # 2. Hash + dedup lookup
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    user_id = current_user["id"]

    cached = await repo.get_by_hash(UUID(str(user_id)), pdf_sha256)
    if cached:
        logger.info(
            "finance_assess_cache_hit",
            user_id=str(user_id),
            pdf_sha256=pdf_sha256,
            assessment_id=cached.get("id"),
        )
        return JSONResponse(
            content={
                "id": str(cached.get("id")),
                "cached": True,
                "diagnosis": cached.get("diagnosis") or {},
                "extracted_input": cached.get("extracted_input") or {},
                "narrative": cached.get("narrative"),
                "extraction_warnings": [],
                "needs_vision": cached.get("needs_vision", False),
                "llm_tokens_used": {"prompt": 0, "completion": 0},
                "cost_usd": float(cached.get("cost_usd") or 0.0),
            }
        )

    # 3. Text-layer extraction
    try:
        extraction = pdf_extract(pdf_bytes)
    except PDFExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"PDF extraction failed: {exc}",
        )

    # 4. Pre-compute monthly spend snapshot, then build Gemini extractor.
    # Passing a closure ``lambda: snapshot`` sidesteps the sync-vs-async
    # mismatch between the repo (async) and the extractor's budget_fn
    # (sync). One extra request's worth of drift is acceptable for a
    # fail-closed budget check.
    current_spend = await repo.sum_cost_current_month(None)

    try:
        genai_client = _build_genai_client(settings.gemini_api_key)
    except Exception as exc:  # noqa: BLE001
        logger.exception("finance_assess_genai_client_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gemini client init failed: {exc}",
        )

    extractor = FinanceLLMExtractor(
        client=genai_client,
        model=settings.gemini_model,
        monthly_budget_usd=settings.finance_llm_monthly_budget_usd,
        budget_used_usd_fn=lambda: current_spend,
    )

    # 5. Vision vs text branch
    try:
        if extraction.needs_vision:
            ext_out = extractor.extract_from_pdf_bytes(company_name, pdf_bytes)
        else:
            ext_out = extractor.extract_from_text(
                company_name, extraction.text or ""
            )
    except BudgetExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="monthly budget exceeded",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("finance_assess_llm_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM extraction failed: {exc}",
        )

    # 6. Schema → FinancialInput + required-field check
    fi, missing_required = _schema_to_financial_input(ext_out.input_data)
    extracted_input_dict = _financial_input_to_dict(fi)

    if missing_required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "required fields missing from PDF",
                "extraction_warnings": missing_required + ext_out.extraction_warnings,
                "extracted_input": extracted_input_dict,
                "needs_vision": extraction.needs_vision,
            },
        )

    # 7. Rule-engine diagnosis
    analyzer = FinancialAnalyzer()
    diagnosis = analyzer.analyze(fi)
    diagnosis_dict = _diagnosis_to_dict(diagnosis)

    # 8. Optional narrative
    narrative_text: Optional[str] = None
    narrative_cost = 0.0
    narrative_prompt_tokens = 0
    narrative_completion_tokens = 0
    if narrative:
        try:
            narr_out = extractor.write_narrative(
                ext_out.input_data, diagnosis.score, diagnosis_dict,
            )
            narrative_text = narr_out.text
            narrative_cost = narr_out.cost_usd
            narrative_prompt_tokens = narr_out.prompt_tokens
            narrative_completion_tokens = narr_out.completion_tokens
        except BudgetExceeded:
            # Narrative is opt-in — drop silently on budget exceed.
            logger.warning("finance_assess_narrative_budget_skip")
            narrative_text = None
        except Exception:  # noqa: BLE001
            logger.exception("finance_assess_narrative_failed")
            narrative_text = None

    total_cost = ext_out.cost_usd + narrative_cost
    total_prompt = ext_out.prompt_tokens + narrative_prompt_tokens
    total_completion = ext_out.completion_tokens + narrative_completion_tokens

    # 9. Persist
    try:
        row = await repo.create(
            user_id=str(user_id),
            pdf_sha256=pdf_sha256,
            needs_vision=extraction.needs_vision,
            extracted_input=extracted_input_dict,
            diagnosis=diagnosis_dict,
            narrative=narrative_text,
            model=settings.gemini_model,
            cost_usd=total_cost,
        )
    except Exception:
        logger.exception("finance_assess_persist_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to persist assessment",
        )

    return JSONResponse(
        content={
            "id": str(row.get("id")),
            "cached": False,
            "diagnosis": diagnosis_dict,
            "extracted_input": extracted_input_dict,
            "narrative": narrative_text,
            "extraction_warnings": ext_out.extraction_warnings,
            "needs_vision": extraction.needs_vision,
            "llm_tokens_used": {
                "prompt": total_prompt,
                "completion": total_completion,
            },
            "cost_usd": total_cost,
        }
    )


@router.get(
    "/assessments",
    summary="List the current user's persisted finance assessments",
)
async def list_assessments(
    page: int = 1,
    per_page: int = 20,
    current_user: dict[str, Any] = Depends(require_permission("financial", "read")),
    settings: Settings = Depends(get_settings),
    repo: FinanceAssessmentRepository = Depends(_get_finance_repo),
) -> JSONResponse:
    """Paginated list of assessments owned by the calling user.

    Mirrors the pagination envelope used by other list routes in the app
    (see ``/api/v1/invoices``). Feature-flag gated via
    ``settings.finance_llm_enabled`` so the endpoint is 503 while the
    pipeline is dark-launched.
    """
    _require_finance_llm_enabled(settings)

    # Clamp inputs — avoid surprising negative or oversized pages.
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1
    if per_page > 100:
        per_page = 100

    rows, total = await repo.list_by_user(
        user_id=UUID(str(current_user["id"])),
        page=page,
        per_page=per_page,
    )
    total_pages = math.ceil(total / per_page) if per_page else 0

    return JSONResponse(
        content={
            "items": rows,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    )


@router.get(
    "/assessments/{assessment_id}",
    summary="Fetch a persisted finance assessment by id",
)
async def get_assessment(
    assessment_id: UUID,
    current_user: dict[str, Any] = Depends(require_permission("financial", "read")),
    settings: Settings = Depends(get_settings),
    repo: FinanceAssessmentRepository = Depends(_get_finance_repo),
) -> JSONResponse:
    _require_finance_llm_enabled(settings)
    row = await repo.get_by_id(assessment_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="assessment not found",
        )
    return JSONResponse(content={"data": row})


@router.delete(
    "/assessments/{assessment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a finance assessment",
)
async def delete_assessment(
    assessment_id: UUID,
    current_user: dict[str, Any] = Depends(require_permission("financial", "write")),
    settings: Settings = Depends(get_settings),
    repo: FinanceAssessmentRepository = Depends(_get_finance_repo),
) -> JSONResponse:
    _require_finance_llm_enabled(settings)
    existing = await repo.get_by_id(assessment_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="assessment not found",
        )
    await repo.delete(assessment_id)
    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
