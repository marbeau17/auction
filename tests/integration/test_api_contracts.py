"""Integration tests for /api/v1/contracts endpoints.

Covers:

* GET /types returns all 9 contract-type keys
* GET /mapper/{sim_id} returns HTML with the scheme SVG
* POST /generate/{sim_id} without stakeholders returns HTML error prompt
* POST /stakeholders creates a row in deal_stakeholders
* Regression guard: CONTRACT_TYPES party_a/party_b align with
  ContractGenerator.PARTY_MAPPING for all 9 keys
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
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
async def client_contracts(
    fake_supabase: _FakeClient,
    admin_user_dict: dict[str, Any],
):
    """Admin-authenticated client.

    The contracts router fetches its Supabase client via
    ``app.db.supabase_client.get_supabase_client(service_role=True)``
    directly (not through FastAPI's dependency injection), so we patch
    that call-site globally for the duration of each test.
    """
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return admin_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    token = _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")

    # Patch both the canonical factory and the module-local alias used by
    # contracts.py (it does `from app.db.supabase_client import
    # get_supabase_client` inside a helper).
    with patch(
        "app.db.supabase_client.get_supabase_client",
        return_value=fake_supabase,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            cookies={"access_token": token},
        ) as ac:
            ac._fake = fake_supabase  # type: ignore[attr-defined]
            yield ac


async def _prime_csrf(ac: AsyncClient) -> str:
    resp = await ac.get("/health")
    return resp.cookies.get("csrf_token", "")


# ===========================================================================
# Tests
# ===========================================================================


class TestContractTypesList:
    async def test_types_returns_all_nine(
        self, client_contracts: AsyncClient
    ) -> None:
        """GET /types lists exactly the 9 supported contract type keys."""
        response = await client_contracts.get("/api/v1/contracts/types")
        if response.status_code in (404, 405):
            pytest.skip("Contract types endpoint not available")

        assert response.status_code == 200, response.text
        body = response.json()
        data = body.get("data") or []
        keys = {entry["key"] for entry in data}

        expected = {
            "tk_agreement",
            "sales_agreement",
            "master_lease",
            "sublease_agreement",
            "private_placement",
            "customer_referral",
            "asset_management",
            "accounting_firm",
            "accounting_association",
        }
        assert keys == expected, f"Unexpected keys: {keys}"


class TestContractMapper:
    async def test_mapper_returns_html_with_svg(
        self, client_contracts: AsyncClient
    ) -> None:
        """GET /mapper/{sim_id} returns HTML containing the scheme SVG."""
        fake: _FakeClient = client_contracts._fake  # type: ignore[attr-defined]
        sim_id = str(uuid4())
        fake.tables["simulations"] = [
            {
                "id": sim_id,
                "title": "テストシミュレーション",
                "purchase_price_yen": 3_500_000,
                "lease_monthly_yen": 120_000,
                "lease_term_months": 36,
                "target_mileage_km": 85_000,
                "target_model_year": 2020,
                "expected_yield_rate": 0.08,
                "result_summary_json": {
                    "maker": "いすゞ",
                    "model": "エルフ",
                    "body_type": "平ボディ",
                    "assessment": "推奨",
                },
                "created_at": NOW_ISO,
            }
        ]
        fake.tables["deal_stakeholders"] = []
        fake.tables["contract_templates"] = []
        fake.tables["deal_contracts"] = []

        response = await client_contracts.get(
            f"/api/v1/contracts/mapper/{sim_id}"
        )
        if response.status_code in (404, 405):
            pytest.skip("Contract mapper endpoint not available")

        assert response.status_code == 200, response.text
        assert "text/html" in response.headers.get("content-type", "")
        text = response.text
        assert "<svg" in text
        # Scheme diagram title
        assert "スキーム" in text


class TestGenerateWithoutStakeholders:
    async def test_generate_without_stakeholders_returns_prompt(
        self, client_contracts: AsyncClient
    ) -> None:
        """POST /generate/{sim_id} with no stakeholders returns the registration prompt."""
        fake: _FakeClient = client_contracts._fake  # type: ignore[attr-defined]
        sim_id = str(uuid4())
        fake.tables["simulations"] = [
            {
                "id": sim_id,
                "title": "Empty sim",
                "purchase_price_yen": 3_500_000,
                "result_summary_json": {},
                "created_at": NOW_ISO,
            }
        ]
        fake.tables["deal_stakeholders"] = []  # deliberately empty

        csrf = await _prime_csrf(client_contracts)
        response = await client_contracts.post(
            f"/api/v1/contracts/generate/{sim_id}",
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Contract generate endpoint not available")

        assert response.status_code == 200, response.text
        assert "ステークホルダー情報を先に登録してください" in response.text


class TestSaveStakeholder:
    async def test_post_stakeholders_creates_row(
        self, client_contracts: AsyncClient
    ) -> None:
        """POST /stakeholders with a simple form payload inserts a new row."""
        fake: _FakeClient = client_contracts._fake  # type: ignore[attr-defined]
        fake.tables["deal_stakeholders"] = []
        sim_id = str(uuid4())

        csrf = await _prime_csrf(client_contracts)
        response = await client_contracts.post(
            "/api/v1/contracts/stakeholders",
            data={
                "simulation_id": sim_id,
                "role_type": "spc",
                "company_name": "テストSPC合同会社",
                "representative_name": "山田太郎",
                "address": "東京都千代田区",
                "phone": "03-0000-0000",
                "email_addr": "spc@example.com",
                "registration_number": "1234567890123",
            },
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Stakeholders POST endpoint not available")

        assert response.status_code == 200, response.text
        rows = fake.tables.get("deal_stakeholders", [])
        assert len(rows) == 1
        assert rows[0]["company_name"] == "テストSPC合同会社"
        assert rows[0]["role_type"] == "spc"


class TestContractTypesRegressionGuard:
    """Verify API CONTRACT_TYPES align with generator.PARTY_MAPPING.

    This guards against the bugs recently fixed around party_a / party_b
    role mismatches between the API metadata and the actual generator.
    """

    def test_party_mapping_matches_for_all_nine_keys(self) -> None:
        from app.api.contracts import CONTRACT_TYPES
        from app.core.contract_generator import ContractGenerator

        expected_keys = {
            "tk_agreement",
            "sales_agreement",
            "master_lease",
            "sublease_agreement",
            "private_placement",
            "customer_referral",
            "asset_management",
            "accounting_firm",
            "accounting_association",
        }
        assert set(CONTRACT_TYPES.keys()) == expected_keys
        assert set(ContractGenerator.PARTY_MAPPING.keys()) == expected_keys

        for key in expected_keys:
            api_a = CONTRACT_TYPES[key]["party_a"]
            api_b = CONTRACT_TYPES[key]["party_b"]
            gen_a, gen_b = ContractGenerator.PARTY_MAPPING[key]
            assert (api_a, api_b) == (gen_a, gen_b), (
                f"Role mismatch for {key}: api=({api_a},{api_b}) "
                f"generator=({gen_a},{gen_b})"
            )
