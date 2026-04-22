"""Integration tests for /api/v1/proposals.

Covers the regression where Japanese maker/model text crashed the
Content-Disposition header due to latin-1 encoding.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


def _make_sim_supabase(sim_row: dict) -> MagicMock:
    client = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.single.return_value = query
    response = MagicMock()
    response.data = sim_row
    query.execute.return_value = response
    client.table.return_value = query
    return client


def _sample_sim_row(sim_id: str) -> dict:
    return {
        "id": sim_id,
        "input_data": {
            "maker": "トヨタ",
            "model": "カローラ",
            "registration_year_month": "2022-04",
            "mileage_km": 50000,
            "vehicle_class": "小型",
            "body_type": "平ボディ",
            "lease_term_months": 36,
        },
        "result": {
            "max_purchase_price": 3_000_000,
            "recommended_purchase_price": 2_800_000,
            "estimated_residual_value": 300_000,
            "residual_rate_result": 0.10,
            "monthly_lease_fee": 90_000,
            "total_lease_fee": 3_240_000,
            "breakeven_months": 30,
            "effective_yield_rate": 0.08,
            "market_median_price": 2_900_000,
            "market_sample_count": 10,
            "market_deviation_rate": -0.03,
            "assessment": "推奨",
            "monthly_schedule": [],
        },
    }


@pytest.mark.asyncio
async def test_proposal_download_with_japanese_filename_uses_rfc5987():
    sim_id = str(uuid4())
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1",
        "email": "admin@example.com",
        "role": "admin",
    }
    app.dependency_overrides[get_supabase_client] = lambda: _make_sim_supabase(
        _sample_sim_row(sim_id)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.post(f"/api/v1/proposals/generate?simulation_id={sim_id}")

    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd
    # The actual bug: header must be latin-1 encodable.
    cd.encode("latin-1")
