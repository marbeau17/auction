"""Unit tests for :mod:`app.core.finance_llm_extractor`.

These tests stub the ``google-genai`` client so no network call is made.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.finance_llm_extractor import (
    BudgetExceeded,
    ExtractionOutput,
    FinanceLLMExtractor,
    FinancialInputSchema,
    NarrativeOutput,
)


# --------------------------------------------------------------------------- #
# Fake google-genai client
# --------------------------------------------------------------------------- #


class _FakeUsage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = completion


class _FakeResponse:
    def __init__(
        self,
        parsed: Any = None,
        text: str | None = None,
        usage: tuple[int, int] = (100, 50),
    ) -> None:
        self.parsed = parsed
        self.text = text
        self.usage_metadata = _FakeUsage(*usage)


class _FakeModels:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, *, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if not self._responses:
            raise AssertionError("No fake response queued for generate_content call")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeClient:
    def __init__(self, responses: list) -> None:
        self.models = _FakeModels(responses)


# --------------------------------------------------------------------------- #
# Builder helpers
# --------------------------------------------------------------------------- #


def _make_extractor(
    responses: list,
    *,
    budget_cap: float = 50.0,
    budget_used: float = 0.0,
) -> tuple[FinanceLLMExtractor, _FakeClient]:
    client = _FakeClient(responses)
    ex = FinanceLLMExtractor(
        client=client,
        model="gemini-2.5-flash",
        monthly_budget_usd=budget_cap,
        budget_used_usd_fn=lambda: budget_used,
    )
    return ex, client


def _schema_full(**overrides) -> FinancialInputSchema:
    """Build a FinancialInputSchema with all fields populated by default."""
    base: dict = {
        "company_name": "A",
        "revenue": 1_000_000,
        "operating_profit": 100_000,
        "ordinary_profit": 90_000,
        "total_assets": 500_000,
        "total_liabilities": 300_000,
        "equity": 200_000,
        "current_assets": 250_000,
        "current_liabilities": 150_000,
        "quick_assets": 200_000,
        "interest_bearing_debt": 100_000,
        "operating_cf": 50_000,
        "free_cf": 30_000,
        "vehicle_count": 10,
        "vehicle_utilization_rate": 0.85,
        "existing_lease_monthly": 5_000,
        "existing_loan_balance": 40_000,
    }
    base.update(overrides)
    return FinancialInputSchema(**base)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_extract_from_text_happy_path() -> None:
    parsed = _schema_full(revenue=1_000_000, operating_profit=None)
    response = _FakeResponse(parsed=parsed, usage=(6000, 1000))

    ex, client = _make_extractor([response])
    result = ex.extract_from_text("A", "...some text...")

    assert isinstance(result, ExtractionOutput)
    assert result.input_data.revenue == 1_000_000
    assert "operating_profit" in result.extraction_warnings
    assert "revenue" not in result.extraction_warnings
    assert result.prompt_tokens == 6000
    assert result.completion_tokens == 1000
    # 6000 * 1e-7 + 1000 * 4e-7 = 0.0006 + 0.0004 = 0.001
    assert result.cost_usd == pytest.approx(6000 * 1e-7 + 1000 * 4e-7)
    # Exactly one SDK call was made, to the configured model.
    assert len(client.models.calls) == 1
    assert client.models.calls[0]["model"] == "gemini-2.5-flash"


def test_extract_from_pdf_bytes_vision_mode() -> None:
    from google.genai import types  # runtime dep; 1.47.0 installed system-wide

    parsed = _schema_full()
    response = _FakeResponse(parsed=parsed, usage=(6000, 1000))

    ex, client = _make_extractor([response])
    result = ex.extract_from_pdf_bytes("A", b"%PDF-1.4 fake")

    assert result.input_data.company_name == "A"
    assert result.prompt_tokens == 6000
    assert result.completion_tokens == 1000
    assert result.cost_usd == pytest.approx(6000 * 1e-7 + 1000 * 4e-7)

    contents = client.models.calls[0]["contents"]
    assert isinstance(contents, list)
    part = contents[0]
    assert isinstance(part, types.Part)
    assert part.inline_data.mime_type == "application/pdf"
    # The second element is the prompt string.
    assert isinstance(contents[1], str)


def test_malformed_json_response() -> None:
    response = _FakeResponse(parsed=None, text="not json{{")
    ex, _ = _make_extractor([response])

    with pytest.raises(RuntimeError, match="unparseable"):
        ex.extract_from_text("A", "...")


def test_invented_numbers_balance_sheet_mismatch() -> None:
    parsed = _schema_full(total_assets=500, total_liabilities=300, equity=100)
    response = _FakeResponse(parsed=parsed, usage=(100, 50))

    ex, _ = _make_extractor([response])
    result = ex.extract_from_text("A", "...")

    assert "balance_sheet_mismatch" in result.extraction_warnings


def test_budget_precheck_blocks_call() -> None:
    # Worst-case estimate = 10_000*1e-7 + 2_000*4e-7 = 0.0018 USD.
    # To trip the precheck at cap=50.0 we need budget_used + 0.0018 > 50.0.
    ex, client = _make_extractor(
        responses=[],  # no response queued — call must never happen
        budget_cap=50.0,
        budget_used=49.999,
    )

    with pytest.raises(BudgetExceeded):
        ex.extract_from_text("A", "...some text...")

    assert client.models.calls == []


def test_rate_limit_retry_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = _schema_full()
    first_err = Exception("429 rate limit exceeded")
    response = _FakeResponse(parsed=parsed, usage=(100, 50))

    # monkey-patch sleep so the test is fast
    from app.core import finance_llm_extractor as mod

    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_kw: None)

    ex, client = _make_extractor([first_err, response])
    result = ex.extract_from_text("A", "...")

    assert result.input_data.company_name == "A"
    assert len(client.models.calls) == 2


def test_write_narrative_happy_path() -> None:
    response = _FakeResponse(
        parsed=None,
        text="段落1\n\n段落2\n\n段落3",
        usage=(500, 300),
    )
    ex, _ = _make_extractor([response])

    input_data = _schema_full()
    narrative = ex.write_narrative(
        input_data=input_data,
        diagnosis_grade="B",
        diagnosis_summary={"equity_ratio": 0.4, "debt_ratio": 0.3},
    )

    assert isinstance(narrative, NarrativeOutput)
    assert narrative.text.startswith("段落1")
    assert narrative.prompt_tokens == 500
    assert narrative.completion_tokens == 300
    # 500 * 1e-7 + 300 * 4e-7 = 0.00005 + 0.00012 = 0.00017
    assert narrative.cost_usd == pytest.approx(500 * 1e-7 + 300 * 4e-7)
