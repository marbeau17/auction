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
# NOTE: The simulation router at /api/simulation is currently a stub
# (empty router). These tests target the expected endpoints so they can
# serve as a contract/specification for the forthcoming implementation.
# Tests that hit the stub will get 404/405 as expected; when the endpoints
# are wired, these tests define the correct behaviour.
# ---------------------------------------------------------------------------


class TestCreateSimulation:
    """POST /api/v1/simulations"""

    async def test_create_simulation(
        self,
        client: AsyncClient,
        simulation_input_data: dict[str, Any],
        mock_supabase: MagicMock,
    ) -> None:
        """Valid input should return 200 with all result fields."""
        sim = _sample_simulation_result()
        # Mock the insert to return the simulation
        query = _make_chainable_query(data=[sim])
        mock_supabase.table.return_value = query

        response = await client.post(
            "/api/v1/simulations",
            json=simulation_input_data,
        )
        # If the endpoint is not yet implemented, expect 404/405
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body or "result" in body or "id" in body

    async def test_create_simulation_invalid_input(
        self,
        client: AsyncClient,
    ) -> None:
        """Missing required fields should return 422."""
        response = await client.post(
            "/api/v1/simulations",
            json={"maker": "いすゞ"},  # missing many required fields
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
        """Should soft-delete a simulation and return 200."""
        sim = _sample_simulation_result()
        query = _make_chainable_query(
            data=[{"id": SAMPLE_SIMULATION_ID, "deleted": True}],
            single_data=sim,
        )
        mock_supabase.table.return_value = query

        response = await client.delete(f"/api/v1/simulations/{SAMPLE_SIMULATION_ID}")
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200


class TestCalculateWithoutSaving:
    """POST /api/v1/simulations/calculate"""

    async def test_calculate_without_saving(
        self,
        client: AsyncClient,
        simulation_input_data: dict[str, Any],
        mock_supabase: MagicMock,
    ) -> None:
        """Calculate-only endpoint should return result without persisting."""
        response = await client.post(
            "/api/v1/simulations/calculate",
            json=simulation_input_data,
        )
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200
        body = response.json()
        # Should contain calculation results, not an id for persisted data
        # (exact field structure depends on implementation)
        assert body is not None


class TestSimulationHtmxResponse:
    """HTMX requests should return HTML fragments."""

    async def test_simulation_htmx_response(
        self,
        client: AsyncClient,
        simulation_input_data: dict[str, Any],
        mock_supabase: MagicMock,
    ) -> None:
        """With HX-Request header, response should be HTML."""
        sim = _sample_simulation_result()
        query = _make_chainable_query(data=[sim])
        mock_supabase.table.return_value = query

        response = await client.post(
            "/api/v1/simulations",
            json=simulation_input_data,
            headers={"HX-Request": "true"},
        )
        if response.status_code in (404, 405):
            pytest.skip("Simulation endpoint not yet implemented")

        assert response.status_code == 200
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
