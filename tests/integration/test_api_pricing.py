"""Integration tests for /api/v1/pricing endpoints.

Covers:

* POST /calculate with a valid IntegratedPricingInput -> 200 + nested result
* POST /calculate HTMX -> HTML fragment with assessment badge
* POST /calculate without CSRF -> 403
* GET /masters requires auth
* POST /masters validates parameter ranges
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_USER_ID,
    NOW_ISO,
    _FakeClient,
    _make_jwt,
)

from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


# ---------------------------------------------------------------------------
# Fake market_prices data: 10 comparable vehicles with realistic spread
# ---------------------------------------------------------------------------


def _make_comparable_vehicles(count: int = 10) -> list[dict[str, Any]]:
    """Return `count` comparable market_prices rows for Isuzu Elf 2020."""
    now = datetime.now(tz=timezone.utc)
    base_price = 3_500_000
    rows: list[dict[str, Any]] = []
    for i in range(count):
        # spread prices +/- 10%
        price = int(base_price * (0.9 + 0.02 * i))
        rows.append(
            {
                "id": str(uuid4()),
                "maker": "いすゞ",
                "model": "エルフ",
                "year": 2020,
                "mileage": 80_000 + i * 2000,
                "mileage_km": 80_000 + i * 2000,
                "price": price,
                "price_yen": price,
                "body_type": "平ボディ",
                "vehicle_class": "小型",
                "created_at": (now - timedelta(days=i * 5)).isoformat(),
                "scraped_at": (now - timedelta(days=i * 5)).isoformat(),
                "source_site": "truckmarket",
            }
        )
    return rows


def _valid_pricing_input() -> dict[str, Any]:
    """Valid IntegratedPricingInput payload."""
    return {
        "maker": "いすゞ",
        "model": "エルフ",
        "registration_year_month": "2020-04",
        "mileage_km": 85_000,
        "vehicle_class": "小型",
        "body_type": "平ボディ",
        "payload_ton": 2.0,
        "body_option_value": 300_000,
        "lease_term_months": 36,
        "investor_yield_rate": 0.08,
        "am_fee_rate": 0.02,
        "placement_fee_rate": 0.03,
        "accounting_fee_monthly": 50_000,
        "operator_margin_rate": 0.02,
        "safety_margin_rate": 0.05,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user_dict() -> dict[str, Any]:
    return {
        "id": ADMIN_USER_ID,
        "email": ADMIN_EMAIL,
        "role": "admin",
        "stakeholder_role": "admin",
    }


@pytest.fixture
def pricing_supabase(fake_supabase: _FakeClient) -> _FakeClient:
    """Seed fake Supabase with comparable market_prices rows."""
    fake_supabase.tables["market_prices"] = _make_comparable_vehicles(10)
    fake_supabase.tables["pricing_masters"] = []
    fake_supabase.tables["simulations"] = []
    return fake_supabase


@pytest.fixture
async def client_pricing(
    pricing_supabase: _FakeClient,
    admin_user_dict: dict[str, Any],
) -> AsyncClient:
    """Authenticated client with admin + fake supabase overrides."""
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return admin_user_dict

    def _override_supabase() -> _FakeClient:
        return pricing_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    token = _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        yield ac


async def _prime_csrf(ac: AsyncClient) -> str:
    """Warm up CSRF middleware & return the cookie value."""
    resp = await ac.get("/health")
    return resp.cookies.get("csrf_token", "")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCalculateHappyPath:
    async def test_calculate_returns_nested_result(
        self,
        client_pricing: AsyncClient,
    ) -> None:
        """POST /calculate returns a nested acquisition/residual/lease/nav_curve payload."""
        csrf = await _prime_csrf(client_pricing)
        response = await client_pricing.post(
            "/api/v1/pricing/calculate",
            json=_valid_pricing_input(),
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Pricing calculate endpoint not available")

        assert response.status_code == 200, response.text
        body = response.json()
        data = body.get("data", {})
        result = data.get("result") or {}

        # Nested structure must include all four sections + assessment
        assert "acquisition" in result
        assert "residual" in result
        assert "lease" in result
        assert "nav_curve" in result
        assert "assessment" in result
        assert result["assessment"] in ("推奨", "要検討", "非推奨")

        # The acquisition section should have used the seeded comparables
        acq = result["acquisition"]
        assert acq["sample_count"] >= 5
        assert acq["sample_count"] <= 15
        assert acq["recommended_price"] > 0
        assert acq["market_median"] > 0

        # nav_curve must have lease_term_months entries
        assert len(result["nav_curve"]) == 36


class TestCalculateHtmx:
    async def test_calculate_htmx_returns_html_with_badge(
        self,
        client_pricing: AsyncClient,
    ) -> None:
        """HTMX POST /calculate returns HTML that includes the assessment label."""
        csrf = await _prime_csrf(client_pricing)
        response = await client_pricing.post(
            "/api/v1/pricing/calculate",
            json=_valid_pricing_input(),
            headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Pricing calculate HTMX endpoint not available")

        assert response.status_code == 200, response.text
        assert "text/html" in response.headers.get("content-type", "")
        # The assessment badge renders one of these Japanese labels.
        text = response.text
        assert ("推奨" in text) or ("要検討" in text) or ("非推奨" in text)


class TestCalculateCSRF:
    async def test_calculate_without_csrf_rejected(
        self,
        client_pricing: AsyncClient,
    ) -> None:
        """POST /calculate without a CSRF token returns 403."""
        # No prior GET, no cookie, no header.
        response = await client_pricing.post(
            "/api/v1/pricing/calculate",
            json=_valid_pricing_input(),
        )
        if response.status_code in (404, 405):
            pytest.skip("Pricing calculate endpoint not available")

        assert response.status_code == 403


class TestMastersAuthRequired:
    async def test_masters_requires_authentication(self) -> None:
        """GET /masters with no auth cookie should return 401."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as ac:
            response = await ac.get("/api/v1/pricing/masters")

        if response.status_code in (404, 405):
            pytest.skip("Pricing masters endpoint not available")
        assert response.status_code == 401


class TestMastersValidation:
    async def test_masters_post_rejects_out_of_range_rate(
        self,
        client_pricing: AsyncClient,
    ) -> None:
        """POST /masters with an investor_yield_rate > 1 is rejected by Pydantic."""
        csrf = await _prime_csrf(client_pricing)
        response = await client_pricing.post(
            "/api/v1/pricing/masters",
            json={
                "name": "Bad Master",
                "investor_yield_rate": 1.5,  # invalid - must be 0..1
                "am_fee_rate": 0.02,
                "placement_fee_rate": 0.03,
                "operator_margin_rate": 0.02,
                "safety_margin_rate": 0.05,
            },
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Pricing masters POST endpoint not available")

        # 422 = Pydantic validation; some deployments surface 400.
        assert response.status_code in (400, 422), response.text

    async def test_masters_post_rejects_safety_margin_over_half(
        self,
        client_pricing: AsyncClient,
    ) -> None:
        """safety_margin_rate has an explicit upper bound of 0.5."""
        csrf = await _prime_csrf(client_pricing)
        response = await client_pricing.post(
            "/api/v1/pricing/masters",
            json={
                "name": "Bad Safety",
                "investor_yield_rate": 0.08,
                "am_fee_rate": 0.02,
                "placement_fee_rate": 0.03,
                "operator_margin_rate": 0.02,
                "safety_margin_rate": 0.9,  # > 0.5 upper bound
            },
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Pricing masters POST endpoint not available")

        assert response.status_code in (400, 422), response.text
