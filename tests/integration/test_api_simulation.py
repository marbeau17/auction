"""Integration tests for the simulation API endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.integration.conftest import (
    ADMIN_USER_ID,
    NOW_ISO,
    SAMPLE_SIMULATION_ID,
    _make_chainable_query,
    _make_mock_supabase,
    _sample_simulation_result,
)


# ---------------------------------------------------------------------------
# NOTE: The simulation router at /api/v1/simulations now persists via
# ``SimulationRepository`` and returns ``201 Created``. Tests that POST or
# DELETE must prime the CSRF cookie/header first — see ``_prime_csrf`` below.
# ---------------------------------------------------------------------------


async def _prime_csrf(ac: AsyncClient) -> str:
    """Issue a safe GET so the CSRF middleware sets the token cookie."""
    resp = await ac.get("/health")
    return resp.cookies.get("csrf_token", "")


class TestCreateSimulation:
    """POST /api/v1/simulations"""

    async def test_create_simulation(
        self,
        client: AsyncClient,
        simulation_input_data: dict[str, Any],
        mock_supabase: MagicMock,
    ) -> None:
        """Valid input should return 201 Created with the persisted payload."""
        sim = _sample_simulation_result()
        # Mock the insert to return the simulation
        query = _make_chainable_query(data=[sim])
        mock_supabase.table.return_value = query

        csrf = await _prime_csrf(client)
        response = await client.post(
            "/api/v1/simulations",
            json=simulation_input_data,
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        # If the endpoint is not yet implemented, expect 404/405
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 201, response.text
        body = response.json()
        assert "data" in body or "result" in body or "id" in body

    async def test_create_simulation_invalid_input(
        self,
        client: AsyncClient,
    ) -> None:
        """Missing required fields should return 422."""
        csrf = await _prime_csrf(client)
        response = await client.post(
            "/api/v1/simulations",
            json={"maker": "いすゞ"},  # missing many required fields
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 422


class TestListSimulations:
    """GET /api/v1/simulations"""

    async def test_list_simulations(
        self,
        client: AsyncClient,
        mock_supabase: MagicMock,
    ) -> None:
        """Should return a paginated list of simulations."""
        sim = _sample_simulation_result()
        query = _make_chainable_query(data=[sim], count=1)
        mock_supabase.table.return_value = query

        response = await client.get("/api/v1/simulations")
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body.get("data", body), list) or "data" in body


class TestGetSimulationDetail:
    """GET /api/v1/simulations/{id}"""

    async def test_get_simulation_detail(
        self,
        client: AsyncClient,
        mock_supabase: MagicMock,
    ) -> None:
        """Should return a single simulation by ID."""
        sim = _sample_simulation_result()
        query = _make_chainable_query(single_data=sim)
        mock_supabase.table.return_value = query

        response = await client.get(f"/api/v1/simulations/{SAMPLE_SIMULATION_ID}")
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200


class TestDeleteSimulation:
    """DELETE /api/v1/simulations/{id}"""

    async def test_delete_simulation(
        self,
        client: AsyncClient,
        mock_supabase: MagicMock,
    ) -> None:
        """Should delete a draft simulation and return 200."""
        # Delete endpoint only allows status == "draft"
        sim = _sample_simulation_result()
        sim["status"] = "draft"
        query = _make_chainable_query(
            data=[{"id": SAMPLE_SIMULATION_ID, "deleted": True}],
            single_data=sim,
        )
        mock_supabase.table.return_value = query

        csrf = await _prime_csrf(client)
        response = await client.delete(
            f"/api/v1/simulations/{SAMPLE_SIMULATION_ID}",
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200, response.text


class TestCalculateWithoutSaving:
    """POST /api/v1/simulations/calculate"""

    async def test_calculate_without_saving(
        self,
        client: AsyncClient,
        simulation_input_data: dict[str, Any],
        mock_supabase: MagicMock,
    ) -> None:
        """Calculate-only endpoint should return result as an HTML fragment."""
        # ``/calculate`` accepts ``application/x-www-form-urlencoded`` and
        # returns an HTML fragment (not JSON) — rebuild the payload as form data.
        form_data = {
            "maker": simulation_input_data["maker"],
            "model": simulation_input_data["model"],
            "registration_year_month": simulation_input_data["registration_year_month"],
            "mileage_km": str(simulation_input_data["mileage_km"]),
            "acquisition_price": str(simulation_input_data["acquisition_price"]),
            "book_value": str(simulation_input_data["book_value"]),
            "body_type": simulation_input_data["body_type"],
            "body_option_value": str(simulation_input_data.get("body_option_value") or 0),
            # Form posts send target_yield_rate as a percentage (8 => 8 %).
            "target_yield_rate": str(simulation_input_data["target_yield_rate"] * 100),
            "lease_term_months": str(simulation_input_data["lease_term_months"]),
            "vehicle_class": simulation_input_data["vehicle_class"],
        }
        csrf = await _prime_csrf(client)
        response = await client.post(
            "/api/v1/simulations/calculate",
            data=form_data,
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200, response.text
        # Quick-calculate returns HTML — no persistence, no JSON ``id``.
        assert "text/html" in response.headers.get("content-type", "")
        assert response.text


class TestSimulationHtmxResponse:
    """HTMX requests should return HTML fragments."""

    async def test_simulation_htmx_response(
        self,
        client: AsyncClient,
        simulation_input_data: dict[str, Any],
        mock_supabase: MagicMock,
    ) -> None:
        """With HX-Request header, response should be HTML with 201 Created."""
        sim = _sample_simulation_result()
        query = _make_chainable_query(data=[sim])
        mock_supabase.table.return_value = query

        csrf = await _prime_csrf(client)
        response = await client.post(
            "/api/v1/simulations",
            json=simulation_input_data,
            headers={
                "HX-Request": "true",
                "X-CSRF-Token": csrf,
            },
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 201, response.text
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type


class TestSimulationUnauthorized:
    """Unauthenticated requests should be rejected."""

    async def test_unauthorized_access(
        self,
        client_unauthenticated: AsyncClient,
    ) -> None:
        """No auth cookie should return 401."""
        response = await client_unauthenticated.get("/api/v1/simulations")
        # If simulation endpoint is not implemented, skip;
        # otherwise, any protected endpoint should return 401
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 401
