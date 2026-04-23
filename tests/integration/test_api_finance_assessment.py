"""Integration tests for ``/api/v1/financial/assess-document`` and friends.

Uses the existing ``_FakeClient`` Supabase substitute and monkey-patches
``app.api.financial._build_genai_client`` so zero real Gemini calls are
made. Tests enable the ``finance_llm_enabled`` flag per-test by
overriding ``get_settings`` via ``app.dependency_overrides``.

The real ``pdf_text_extractor.extract`` runs on every text/vision test —
we use ``reportlab`` to generate a tiny real PDF so pypdf's text-layer
extraction succeeds. ``reportlab`` is already a dev dep in
``pyproject.toml``.

No real secrets, no real network calls, no real Gemini calls.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_USER_ID,
    NOW_ISO,
    SALES_EMAIL,
    SALES_USER_ID,
    _FakeClient,
    _make_jwt,
)

from app.config import Settings, get_settings
from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_minimal_pdf_bytes(text: str = "売上高 100,000,000円") -> bytes:
    """Generate a tiny real PDF via reportlab so pdf_extract returns text."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:  # pragma: no cover — reportlab is in dev deps
        pytest.skip("reportlab not installed")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    # Draw enough text to get past the MIN_TEXT_LEN=100 cutoff
    c.drawString(100, 750, text)
    c.drawString(100, 730, "operating profit 10,000,000 yen")
    for i in range(20):
        c.drawString(100, 700 - i * 18, f"line-{i} sample financial data padding text")
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_needs_vision_pdf_bytes() -> bytes:
    """Generate a PDF with essentially no text layer (``needs_vision=True``)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:  # pragma: no cover
        pytest.skip("reportlab not installed")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    # Draw nothing — blank page → text layer shorter than MIN_TEXT_LEN
    c.showPage()
    c.save()
    return buf.getvalue()


def _full_schema_dict(company_name: str = "test-transport") -> dict:
    """Dict matching FinancialInputSchema with every required field set."""
    return {
        "company_name": company_name,
        "revenue": 500_000_000,
        "operating_profit": 25_000_000,
        "ordinary_profit": 22_000_000,
        "total_assets": 300_000_000,
        "total_liabilities": 180_000_000,
        "equity": 120_000_000,
        "current_assets": 120_000_000,
        "current_liabilities": 80_000_000,
        "quick_assets": 90_000_000,
        "interest_bearing_debt": 100_000_000,
        "operating_cf": 30_000_000,
        "free_cf": 20_000_000,
        "vehicle_count": 20,
        "vehicle_utilization_rate": 0.85,
        "existing_lease_monthly": 500_000,
        "existing_loan_balance": 50_000_000,
    }


def _make_fake_genai_response(
    schema_dict: dict,
    prompt_tokens: int = 1000,
    completion_tokens: int = 500,
):
    """Build a minimal Gemini-like response object."""
    resp = MagicMock()
    # ``FinanceLLMExtractor._parse_response`` accepts a dict-shaped ``parsed``.
    resp.parsed = schema_dict
    resp.text = json.dumps(schema_dict)
    meta = MagicMock()
    meta.prompt_token_count = prompt_tokens
    meta.candidates_token_count = completion_tokens
    resp.usage_metadata = meta
    return resp


class _FakeGenAIClient:
    """Stand-in for ``google.genai.Client`` — tracks calls."""

    def __init__(self, canned_response: Any) -> None:
        self._canned = canned_response
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None
        # Mimic ``client.models.generate_content(...)``
        self.models = self

    def generate_content(self, *, model, contents, config):  # noqa: D401
        self.call_count += 1
        self.last_kwargs = {"model": model, "contents": contents, "config": config}
        return self._canned


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def admin_user_dict() -> dict[str, Any]:
    return {
        "id": ADMIN_USER_ID,
        "email": ADMIN_EMAIL,
        "role": "admin",
        "stakeholder_role": "admin",
    }


@pytest.fixture
def sales_user_dict() -> dict[str, Any]:
    return {
        "id": SALES_USER_ID,
        "email": SALES_EMAIL,
        "role": "sales",
        "stakeholder_role": "sales",
    }


def _enable_flag_settings() -> Settings:
    """Return a Settings object with finance_llm_enabled=True + small budget."""
    base = get_settings()
    data = base.model_dump()
    data["finance_llm_enabled"] = True
    data["finance_llm_max_pdf_mb"] = 10
    data["finance_llm_monthly_budget_usd"] = 50.0
    data["gemini_api_key"] = "test-key"
    data["gemini_model"] = "gemini-flash-latest"
    return Settings(**data)


@pytest.fixture
async def client_flag_on(
    fake_supabase: _FakeClient,
    admin_user_dict: dict[str, Any],
) -> AsyncClient:
    """Admin client with finance feature flag ON."""
    fake_supabase.tables.setdefault("finance_assessments", [])
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return admin_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    def _override_settings() -> Settings:
        return _enable_flag_settings()

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase
    app.dependency_overrides[get_settings] = _override_settings

    token = _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        ac._fake = fake_supabase  # type: ignore[attr-defined]
        ac._app = app  # type: ignore[attr-defined]
        yield ac


@pytest.fixture
async def client_flag_off(
    fake_supabase: _FakeClient,
    admin_user_dict: dict[str, Any],
) -> AsyncClient:
    """Admin client with finance feature flag OFF (default)."""
    fake_supabase.tables.setdefault("finance_assessments", [])
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return admin_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase
    # NOTE: no settings override — flag stays False

    token = _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        ac._fake = fake_supabase  # type: ignore[attr-defined]
        yield ac


@pytest.fixture
async def client_sales_flag_on(
    fake_supabase: _FakeClient,
    sales_user_dict: dict[str, Any],
) -> AsyncClient:
    """Sales-role client with finance feature flag ON — should 403 on writes."""
    fake_supabase.tables.setdefault("finance_assessments", [])
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return sales_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    def _override_settings() -> Settings:
        return _enable_flag_settings()

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase
    app.dependency_overrides[get_settings] = _override_settings

    token = _make_jwt(SALES_USER_ID, SALES_EMAIL, "sales")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        ac._fake = fake_supabase  # type: ignore[attr-defined]
        yield ac


# --------------------------------------------------------------------------- #
# Test 1 — feature flag off → 503
# --------------------------------------------------------------------------- #


class TestFeatureFlagOff:
    async def test_feature_flag_off_returns_503(
        self, client_flag_off: AsyncClient
    ) -> None:
        pdf = _make_minimal_pdf_bytes()
        resp = await client_flag_off.post(
            "/api/v1/financial/assess-document",
            files={"file": ("small.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 503, resp.text
        assert "disabled" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Test 2 — happy path (text PDF)
# --------------------------------------------------------------------------- #


class TestHappyPathText:
    async def test_happy_path_text_pdf(
        self,
        client_flag_on: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = _FakeGenAIClient(
            _make_fake_genai_response(_full_schema_dict())
        )
        import app.api.financial as fin_module

        monkeypatch.setattr(
            fin_module, "_build_genai_client", lambda _api_key: fake_client
        )

        pdf = _make_minimal_pdf_bytes()
        resp = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("small.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cached"] is False
        assert body["needs_vision"] is False
        assert body["diagnosis"]["score"] in ("A", "B", "C", "D")
        assert body["extracted_input"]["revenue"] == 500_000_000
        assert body["cost_usd"] > 0
        assert body["llm_tokens_used"]["prompt"] == 1000
        assert body["llm_tokens_used"]["completion"] == 500
        assert fake_client.call_count == 1


# --------------------------------------------------------------------------- #
# Test 3 — happy path (vision PDF)
# --------------------------------------------------------------------------- #


class TestHappyPathVision:
    async def test_happy_path_vision_pdf(
        self,
        client_flag_on: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = _FakeGenAIClient(
            _make_fake_genai_response(_full_schema_dict())
        )
        import app.api.financial as fin_module

        monkeypatch.setattr(
            fin_module, "_build_genai_client", lambda _api_key: fake_client
        )

        pdf = _make_needs_vision_pdf_bytes()
        resp = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("blank.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["needs_vision"] is True
        assert fake_client.call_count == 1


# --------------------------------------------------------------------------- #
# Test 4 — dedup cache hit
# --------------------------------------------------------------------------- #


class TestDedupCacheHit:
    async def test_dedup_cache_hit(
        self,
        client_flag_on: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = _FakeGenAIClient(
            _make_fake_genai_response(_full_schema_dict())
        )
        import app.api.financial as fin_module

        monkeypatch.setattr(
            fin_module, "_build_genai_client", lambda _api_key: fake_client
        )

        pdf = _make_minimal_pdf_bytes()

        # First upload — LLM called once
        resp1 = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("dup.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp1.status_code == 200, resp1.text
        assert resp1.json()["cached"] is False
        assert fake_client.call_count == 1

        # Second upload — cache hit, LLM not called again
        resp2 = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("dup.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["cached"] is True
        assert fake_client.call_count == 1  # unchanged


# --------------------------------------------------------------------------- #
# Test 5 — budget exceeded → 429 (fail-closed, no LLM call)
# --------------------------------------------------------------------------- #


class TestBudgetFailClosed:
    async def test_budget_fail_closed(
        self,
        client_flag_on: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake: _FakeClient = client_flag_on._fake  # type: ignore[attr-defined]
        # Prime an assessment row dated this month that blows the budget cap.
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        fake.tables["finance_assessments"] = [
            {
                "id": str(uuid4()),
                "user_id": ADMIN_USER_ID,
                "pdf_sha256": "primed-" + "a" * 56,
                "cost_usd": 49.999,
                "created_at": (month_start.isoformat()),
            }
        ]

        fake_client = _FakeGenAIClient(
            _make_fake_genai_response(_full_schema_dict())
        )
        import app.api.financial as fin_module

        monkeypatch.setattr(
            fin_module, "_build_genai_client", lambda _api_key: fake_client
        )

        pdf = _make_minimal_pdf_bytes(text="unique-budget-test-pdf-content")
        resp = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("budget.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 429, resp.text
        assert "budget" in resp.json()["detail"].lower()
        # Fail-closed: no LLM call was ever issued
        assert fake_client.call_count == 0


# --------------------------------------------------------------------------- #
# Test 6 — missing required field → 422 with warnings
# --------------------------------------------------------------------------- #


class TestMissingRequiredField:
    async def test_missing_required_field_422(
        self,
        client_flag_on: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        partial = _full_schema_dict()
        partial["revenue"] = None  # simulate LLM missing a required line
        fake_client = _FakeGenAIClient(_make_fake_genai_response(partial))
        import app.api.financial as fin_module

        monkeypatch.setattr(
            fin_module, "_build_genai_client", lambda _api_key: fake_client
        )

        pdf = _make_minimal_pdf_bytes(text="distinct-missing-required-pdf")
        resp = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("missing.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        # FastAPI serialises dict-shaped ``detail`` as-is.
        assert "revenue" in detail["extraction_warnings"]
        assert detail["needs_vision"] is False


# --------------------------------------------------------------------------- #
# Test 7 — file too large → 413
# --------------------------------------------------------------------------- #


class TestFileTooLarge:
    async def test_file_too_large_413(
        self,
        client_flag_on: AsyncClient,
    ) -> None:
        big = b"0" * (11 * 1024 * 1024)  # 11 MB > default 10 MB cap
        resp = await client_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("big.pdf", big, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 413, resp.text
        assert "exceeds" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Test 8 — sales role (non-admin) → 403
# --------------------------------------------------------------------------- #


class TestRBACNonAdmin:
    async def test_non_admin_rbac_403(
        self,
        client_sales_flag_on: AsyncClient,
    ) -> None:
        pdf = _make_minimal_pdf_bytes()
        resp = await client_sales_flag_on.post(
            "/api/v1/financial/assess-document",
            files={"file": ("sales.pdf", pdf, "application/pdf")},
            data={"company_name": "test-transport", "narrative": "false"},
        )
        assert resp.status_code == 403, resp.text


# --------------------------------------------------------------------------- #
# Test 9 — GET /assessments/{id} happy path
# --------------------------------------------------------------------------- #


class TestGetAssessmentHappyPath:
    async def test_get_assessment_happy_path(
        self,
        client_flag_on: AsyncClient,
    ) -> None:
        fake: _FakeClient = client_flag_on._fake  # type: ignore[attr-defined]
        row_id = str(uuid4())
        fake.tables["finance_assessments"] = [
            {
                "id": row_id,
                "user_id": ADMIN_USER_ID,
                "pdf_sha256": "aa" * 32,
                "needs_vision": False,
                "extracted_input": {"company_name": "seeded"},
                "diagnosis": {"score": "B"},
                "narrative": None,
                "model": "gemini-flash-latest",
                "cost_usd": 0.003,
                "created_at": NOW_ISO,
            }
        ]
        resp = await client_flag_on.get(f"/api/v1/financial/assessments/{row_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["id"] == row_id
        assert body["data"]["diagnosis"]["score"] == "B"


# --------------------------------------------------------------------------- #
# Test 10 — GET /assessments/{id} 404
# --------------------------------------------------------------------------- #


class TestGetAssessmentNotFound:
    async def test_get_assessment_404(
        self,
        client_flag_on: AsyncClient,
    ) -> None:
        missing_id = str(uuid4())
        resp = await client_flag_on.get(
            f"/api/v1/financial/assessments/{missing_id}"
        )
        assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# Test 11 — DELETE then GET → 404
# --------------------------------------------------------------------------- #


class TestDeleteAssessment:
    async def test_delete_assessment(
        self,
        client_flag_on: AsyncClient,
    ) -> None:
        fake: _FakeClient = client_flag_on._fake  # type: ignore[attr-defined]
        row_id = str(uuid4())
        fake.tables["finance_assessments"] = [
            {
                "id": row_id,
                "user_id": ADMIN_USER_ID,
                "pdf_sha256": "bb" * 32,
                "needs_vision": False,
                "extracted_input": {},
                "diagnosis": {"score": "A"},
                "narrative": None,
                "model": "gemini-flash-latest",
                "cost_usd": 0.001,
                "created_at": NOW_ISO,
            }
        ]
        resp_del = await client_flag_on.delete(
            f"/api/v1/financial/assessments/{row_id}"
        )
        assert resp_del.status_code == 204, resp_del.text

        resp_get = await client_flag_on.get(
            f"/api/v1/financial/assessments/{row_id}"
        )
        assert resp_get.status_code == 404, resp_get.text
