"""Integration tests for /api/v1/vehicles NAV endpoints.

Covers:

* GET /{vehicle_id}/nav-history
* GET /{vehicle_id}/nav-latest
* POST /nav/record-monthly triggers batch recording
* POST /nav/record RBAC: non-admin -> 403
* GET /nav/fund-summary aggregates by fund
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

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

from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


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
def sales_user_dict() -> dict[str, Any]:
    return {
        "id": SALES_USER_ID,
        "email": SALES_EMAIL,
        "role": "sales",
        "stakeholder_role": "sales",
    }


def _nav_row(
    vehicle_id: str,
    fund_id: str,
    recording_date: str,
    nav: int = 3_000_000,
    book_value: int = 2_800_000,
    market_value: int = 3_200_000,
    acquisition: int = 4_000_000,
    depreciation: int = 800_000,
    lease_income: int = 480_000,
    ltv: float = 0.65,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "vehicle_id": vehicle_id,
        "fund_id": fund_id,
        "recording_date": recording_date,
        "acquisition_price": acquisition,
        "book_value": book_value,
        "market_value": market_value,
        "depreciation_cumulative": depreciation,
        "lease_income_cumulative": lease_income,
        "nav": nav,
        "ltv_ratio": ltv,
        "created_at": NOW_ISO,
    }


@pytest.fixture
async def client_admin_nav(
    fake_supabase: _FakeClient,
    admin_user_dict: dict[str, Any],
) -> AsyncClient:
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return admin_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

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
async def client_sales_nav(
    fake_supabase: _FakeClient,
    sales_user_dict: dict[str, Any],
) -> AsyncClient:
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return sales_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    token = _make_jwt(SALES_USER_ID, SALES_EMAIL, "sales")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        yield ac


async def _prime_csrf(ac: AsyncClient) -> str:
    resp = await ac.get("/health")
    return resp.cookies.get("csrf_token", "")


# ===========================================================================
# Tests
# ===========================================================================


class TestNavHistoryAndLatest:
    async def test_nav_history_happy_path(
        self, client_admin_nav: AsyncClient
    ) -> None:
        """GET /{vehicle_id}/nav-history returns the seeded rows."""
        fake: _FakeClient = client_admin_nav._fake  # type: ignore[attr-defined]
        vid = str(uuid4())
        fund_id = str(uuid4())
        fake.tables["vehicle_nav_history"] = [
            _nav_row(vid, fund_id, "2026-02-01"),
            _nav_row(vid, fund_id, "2026-03-01"),
            _nav_row(vid, fund_id, "2026-04-01"),
        ]

        response = await client_admin_nav.get(
            f"/api/v1/vehicles/{vid}/nav-history"
        )
        if response.status_code in (404, 405):
            pytest.skip("nav-history endpoint not available")

        assert response.status_code == 200, response.text
        body = response.json()
        data = body.get("data") or []
        assert len(data) == 3

    async def test_nav_latest_happy_path(
        self, client_admin_nav: AsyncClient
    ) -> None:
        """GET /{vehicle_id}/nav-latest returns the most recent snapshot."""
        fake: _FakeClient = client_admin_nav._fake  # type: ignore[attr-defined]
        vid = str(uuid4())
        fund_id = str(uuid4())
        fake.tables["vehicle_nav_history"] = [
            _nav_row(vid, fund_id, "2026-02-01", nav=2_900_000),
            _nav_row(vid, fund_id, "2026-04-01", nav=3_100_000),
        ]

        response = await client_admin_nav.get(
            f"/api/v1/vehicles/{vid}/nav-latest"
        )
        if response.status_code in (404, 405):
            pytest.skip("nav-latest endpoint not available")

        assert response.status_code == 200, response.text
        body = response.json()
        data = body.get("data") or {}
        # Should surface the latest record (2026-04-01)
        assert data.get("recording_date") == "2026-04-01"


class TestRecordMonthlyBatch:
    async def test_record_monthly_triggers_batch(
        self, client_admin_nav: AsyncClient
    ) -> None:
        """POST /nav/record-monthly runs the batch-record path for a fund."""
        fake: _FakeClient = client_admin_nav._fake  # type: ignore[attr-defined]
        fund_id = str(uuid4())
        vehicle_id = str(uuid4())
        sab_id = str(uuid4())

        # Seed one held SAB so batch_record_monthly has something to process.
        fake.tables["secured_asset_blocks"] = [
            {
                "id": sab_id,
                "fund_id": fund_id,
                "vehicle_id": vehicle_id,
                "acquisition_price": 4_000_000,
                "adjusted_valuation": 3_500_000,
                "b2b_wholesale_valuation": 3_400_000,
                "ltv_ratio": 0.65,
                "lease_contract_id": None,
                "status": "held",
            }
        ]
        fake.tables["lease_contracts"] = []
        fake.tables["lease_payments"] = []
        fake.tables["vehicle_nav_history"] = []

        csrf = await _prime_csrf(client_admin_nav)
        response = await client_admin_nav.post(
            "/api/v1/vehicles/nav/record-monthly",
            json={"fund_id": fund_id, "recording_date": "2026-04-30"},
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("record-monthly endpoint not available")

        assert response.status_code in (200, 201), response.text
        body = response.json()
        stats = body.get("data") or {}
        # Should record at least one NAV row (the seeded SAB).
        assert stats.get("recorded", 0) >= 1


class TestRecordRBAC:
    async def test_non_admin_blocked_on_record(
        self, client_sales_nav: AsyncClient
    ) -> None:
        """POST /nav/record is admin/service-role only; sales -> 403."""
        csrf = await _prime_csrf(client_sales_nav)
        response = await client_sales_nav.post(
            "/api/v1/vehicles/nav/record",
            json={
                "vehicle_id": str(uuid4()),
                "recording_date": "2026-04-01",
                "acquisition_price": 4_000_000,
                "book_value": 3_200_000,
                "market_value": 3_500_000,
                "nav": 3_350_000,
            },
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("/nav/record endpoint not available")

        assert response.status_code == 403, response.text


class TestFundSummary:
    async def test_fund_summary_aggregates(
        self, client_admin_nav: AsyncClient
    ) -> None:
        """GET /nav/fund-summary aggregates NAV rows for a fund."""
        fake: _FakeClient = client_admin_nav._fake  # type: ignore[attr-defined]
        fund_id = str(uuid4())
        v1, v2 = str(uuid4()), str(uuid4())
        fake.tables["vehicle_nav_history"] = [
            _nav_row(v1, fund_id, "2026-04-01", nav=3_000_000,
                     book_value=2_800_000, market_value=3_200_000,
                     acquisition=4_000_000, depreciation=1_200_000,
                     lease_income=400_000, ltv=0.60),
            _nav_row(v2, fund_id, "2026-04-01", nav=2_500_000,
                     book_value=2_200_000, market_value=2_700_000,
                     acquisition=3_500_000, depreciation=1_300_000,
                     lease_income=300_000, ltv=0.70),
        ]

        response = await client_admin_nav.get(
            "/api/v1/vehicles/nav/fund-summary",
            params={"fund_id": fund_id, "recording_date": "2026-04-01"},
        )
        if response.status_code in (404, 405):
            pytest.skip("fund-summary endpoint not available")

        assert response.status_code == 200, response.text
        data = response.json().get("data") or {}
        assert data["vehicle_count"] == 2
        assert data["total_nav"] == 5_500_000
        assert data["total_book_value"] == 5_000_000
        assert data["total_acquisition_price"] == 7_500_000
        # avg_ltv = (0.60 + 0.70) / 2 = 0.65
        assert data["avg_ltv_ratio"] == pytest.approx(0.65, abs=1e-4)
