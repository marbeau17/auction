"""Gemini-based LLM extractor for transport-company financial statements.

Takes either plain text (post-OCR / text-extracted) or raw PDF bytes and
returns a structured :class:`FinancialInputSchema` mirroring the 17 fields
of :class:`app.core.financial_analyzer.FinancialInput`.

Budget-safe:
    * Pre-call worst-case USD estimate is checked against a caller-supplied
      monthly budget before any SDK call.
    * A single retry with 1s backoff handles transient 429 / 503 errors.
    * Token counts from the response are turned into a precise post-call
      cost (Gemini Flash pricing, April 2026).

Privacy:
    * Never logs ``pdf_text`` or ``pdf_bytes`` content — only lengths.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Pricing — Gemini Flash, April 2026
# (cloud.google.com/vertex-ai/generative-ai/pricing)
# --------------------------------------------------------------------------- #

_PRICE_INPUT_PER_1M_USD = 0.10
_PRICE_OUTPUT_PER_1M_USD = 0.40

# Worst-case pre-call estimate (10 k in / 2 k out).
_EST_PROMPT_TOKENS = 10_000
_EST_COMPLETION_TOKENS = 2_000


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """\
You extract Japanese financial-statement line items into structured JSON.
Return ONLY JSON matching the given schema. If a field is not present in
the document, set it to null — do not invent values. Numbers must be in
yen (convert 千円/百万円 units if the source uses them).
"""

_NARRATIVE_SYSTEM_PROMPT = """\
You write brief, factual commentary about a transport company's financial
state. Write 2–3 paragraphs in Japanese for a non-specialist reader. Do
NOT contradict the given grade or make up numbers.
"""


# --------------------------------------------------------------------------- #
# Pydantic schema mirroring FinancialInput (17 fields)
# --------------------------------------------------------------------------- #


class FinancialInputSchema(BaseModel):
    """Structured-output schema for Gemini.

    Matches :class:`app.core.financial_analyzer.FinancialInput` exactly.
    Only ``company_name`` is required — every numeric field is Optional so
    the LLM may return ``null`` when a line item is missing from the
    source document.  Required-ness is enforced later, in the API layer.
    """

    company_name: str
    revenue: Optional[int] = None
    operating_profit: Optional[int] = None
    ordinary_profit: Optional[int] = None
    total_assets: Optional[int] = None
    total_liabilities: Optional[int] = None
    equity: Optional[int] = None
    current_assets: Optional[int] = None
    current_liabilities: Optional[int] = None
    quick_assets: Optional[int] = None
    interest_bearing_debt: Optional[int] = None
    operating_cf: Optional[int] = None
    free_cf: Optional[int] = None
    vehicle_count: Optional[int] = None
    vehicle_utilization_rate: Optional[float] = None
    existing_lease_monthly: Optional[int] = None
    existing_loan_balance: Optional[int] = None


# --------------------------------------------------------------------------- #
# Output containers
# --------------------------------------------------------------------------- #


@dataclass
class ExtractionOutput:
    input_data: FinancialInputSchema
    extraction_warnings: list[str]
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class NarrativeOutput:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class BudgetExceeded(Exception):
    """Raised pre-call when the monthly budget cap would be blown."""


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #


class FinanceLLMExtractor:
    """Thin wrapper around ``google-genai`` for finance extraction.

    Parameters
    ----------
    client
        A ``google.genai.Client`` (or a test fake with the same
        ``client.models.generate_content(*, model, contents, config)``
        surface).
    model
        Gemini model id, e.g. ``"gemini-2.5-flash"``.
    monthly_budget_usd
        Hard budget cap — exceeded estimates raise :class:`BudgetExceeded`
        *before* any SDK call is made.
    budget_used_usd_fn
        Zero-arg callable that returns the USD spent so far this month.
        Injected so the storage layer (Agent 3) owns the source of truth.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        monthly_budget_usd: float,
        budget_used_usd_fn: Callable[[], float],
    ) -> None:
        self._client = client
        self._model = model
        self._monthly_budget_usd = float(monthly_budget_usd)
        self._budget_used_usd_fn = budget_used_usd_fn

    # ---- public API ------------------------------------------------------ #

    def extract_from_text(self, company_name: str, pdf_text: str) -> ExtractionOutput:
        """Extract structured financials from already-extracted PDF text."""

        logger.info(
            "finance_llm_extract_start",
            company_name=company_name,
            mode="text",
            pdf_len=len(pdf_text),
        )
        self._check_budget()

        contents = self._build_text_contents(company_name, pdf_text)
        config = self._build_extraction_config()

        response = self._call_with_retry(
            lambda: self._client.models.generate_content(
                model=self._model, contents=contents, config=config,
            )
        )
        return self._finish_extraction(response)

    def extract_from_pdf_bytes(
        self, company_name: str, pdf_bytes: bytes,
    ) -> ExtractionOutput:
        """Extract structured financials from raw PDF bytes (vision mode)."""

        logger.info(
            "finance_llm_extract_start",
            company_name=company_name,
            mode="vision",
            pdf_bytes_len=len(pdf_bytes),
        )
        self._check_budget()

        contents = self._build_vision_contents(company_name, pdf_bytes)
        config = self._build_extraction_config()

        response = self._call_with_retry(
            lambda: self._client.models.generate_content(
                model=self._model, contents=contents, config=config,
            )
        )
        return self._finish_extraction(response)

    def write_narrative(
        self,
        input_data: FinancialInputSchema,
        diagnosis_grade: str,
        diagnosis_summary: dict,
    ) -> NarrativeOutput:
        """Write a 2–3 paragraph Japanese commentary on the diagnosis."""

        logger.info(
            "finance_llm_narrative_start",
            company_name=input_data.company_name,
            grade=diagnosis_grade,
        )
        self._check_budget()

        prompt = (
            f"会社名: {input_data.company_name}\n"
            f"総合評価: {diagnosis_grade}\n"
            f"診断サマリ: {json.dumps(diagnosis_summary, ensure_ascii=False)}\n"
            "上記を踏まえ、2〜3段落の日本語コメントを書いてください。"
        )
        config = self._build_narrative_config()

        response = self._call_with_retry(
            lambda: self._client.models.generate_content(
                model=self._model, contents=prompt, config=config,
            )
        )
        prompt_tokens, completion_tokens = self._usage(response)
        cost = self._cost_usd(prompt_tokens, completion_tokens)
        text = getattr(response, "text", "") or ""

        logger.info(
            "finance_llm_narrative_success",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )
        return NarrativeOutput(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )

    # ---- internal helpers ----------------------------------------------- #

    def _check_budget(self) -> None:
        est = self._cost_usd(_EST_PROMPT_TOKENS, _EST_COMPLETION_TOKENS)
        used = float(self._budget_used_usd_fn())
        if used + est > self._monthly_budget_usd:
            raise BudgetExceeded(
                f"Monthly LLM budget would be exceeded: "
                f"used={used:.4f} + est={est:.4f} > cap={self._monthly_budget_usd:.4f}",
            )

    @staticmethod
    def _cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * _PRICE_INPUT_PER_1M_USD / 1_000_000
            + completion_tokens * _PRICE_OUTPUT_PER_1M_USD / 1_000_000
        )

    @staticmethod
    def _usage(response: Any) -> tuple[int, int]:
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return 0, 0
        p = int(getattr(meta, "prompt_token_count", 0) or 0)
        c = int(getattr(meta, "candidates_token_count", 0) or 0)
        return p, c

    @staticmethod
    def _is_retryable(err: BaseException) -> bool:
        code = getattr(err, "code", None)
        if code in (429, 503):
            return True
        msg = str(err)
        return "429" in msg or "503" in msg

    def _call_with_retry(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as err:  # noqa: BLE001 — we re-raise if not retryable
            if not self._is_retryable(err):
                raise
            logger.warning("finance_llm_retry", error=str(err))
            time.sleep(1.0)
            return fn()

    def _build_extraction_config(self) -> Any:
        from google.genai import types  # local import: optional dep at test time

        return types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=FinancialInputSchema,
        )

    def _build_narrative_config(self) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=_NARRATIVE_SYSTEM_PROMPT,
        )

    @staticmethod
    def _build_text_contents(company_name: str, pdf_text: str) -> str:
        return (
            f"会社名: {company_name}\n"
            "以下は同社の決算書テキストです。スキーマに従って抽出してください。\n"
            "----\n"
            f"{pdf_text}"
        )

    @staticmethod
    def _build_vision_contents(company_name: str, pdf_bytes: bytes) -> list:
        from google.genai import types

        part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        prompt = (
            f"会社名: {company_name}\n"
            "添付PDFは同社の決算書です。スキーマに従って抽出してください。"
        )
        return [part, prompt]

    def _parse_response(self, response: Any) -> FinancialInputSchema:
        parsed = getattr(response, "parsed", None)
        try:
            if parsed is not None:
                if isinstance(parsed, FinancialInputSchema):
                    return parsed
                # Gemini may hand back a dict shaped like the schema.
                return FinancialInputSchema.model_validate(parsed)
            text = getattr(response, "text", None)
            if not text:
                raise RuntimeError(
                    "LLM returned unparseable JSON: empty response",
                )
            data = json.loads(text)
            return FinancialInputSchema.model_validate(data)
        except (ValidationError, json.JSONDecodeError) as err:
            raise RuntimeError(
                f"LLM returned unparseable JSON: {err}",
            ) from err

    @staticmethod
    def _post_validate(data: FinancialInputSchema) -> list[str]:
        warnings: list[str] = []
        dumped = data.model_dump()
        for name, value in dumped.items():
            if name == "company_name":
                continue
            if value is None:
                warnings.append(name)

        ta = data.total_assets
        tl = data.total_liabilities
        eq = data.equity
        if ta is not None and tl is not None and eq is not None:
            tolerance = max(1, abs(ta) * 0.01)
            if abs(ta - (tl + eq)) > tolerance:
                warnings.append("balance_sheet_mismatch")
        return warnings

    def _finish_extraction(self, response: Any) -> ExtractionOutput:
        input_data = self._parse_response(response)
        warnings = self._post_validate(input_data)
        prompt_tokens, completion_tokens = self._usage(response)
        cost = self._cost_usd(prompt_tokens, completion_tokens)

        logger.info(
            "finance_llm_extract_success",
            company_name=input_data.company_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            warnings_count=len(warnings),
        )
        return ExtractionOutput(
            input_data=input_data,
            extraction_warnings=warnings,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )
