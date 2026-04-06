"""Integration tests for the masters API endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.integration.conftest import (
    SAMPLE_BODY_TYPE_ID,
    SAMPLE_CATEGORY_ID,
    SAMPLE_MAKER_ID,
    _sample_body_type,
    _sample_category,
    _sample_maker,
)


# ---------------------------------------------------------------------------
# Helpers: patch the MasterRepository methods
# ---------------------------------------------------------------------------


def _patch_repo(method_name: str, return_value: Any) -> Any:
    """Return a context manager that patches a MasterRepository method."""
    return patch(
        f"app.api.masters.MasterRepository.{method_name}",
        new_callable=AsyncMock,
        return_value=return_value,
    )


# ===================================================================
# Makers
# ===================================================================


class TestListMakers:
    """GET /api/v1/masters/makers"""

    async def test_list_makers(self, client: AsyncClient) -> None:
        """Should return a list of makers."""
        makers = [_sample_maker()]
        with _patch_repo("list_makers", makers):
            response = await client.get("/api/v1/masters/makers")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert isinstance(body["data"], list)
        assert len(body["data"]) == 1
        assert body["data"][0]["name"] == "いすゞ"

    async def test_list_makers_empty(self, client: AsyncClient) -> None:
        """Empty list should still return 200."""
        with _patch_repo("list_makers", []):
            response = await client.get("/api/v1/masters/makers")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []


class TestCreateMaker:
    """POST /api/v1/masters/makers"""

    async def test_create_maker_admin(self, client: AsyncClient) -> None:
        """Admin should be able to create a maker."""
        created = _sample_maker()
        with _patch_repo("create_maker", created):
            response = await client.post(
                "/api/v1/masters/makers",
                json={"name": "いすゞ", "name_en": "Isuzu", "code": "ISUZU"},
            )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["name"] == "いすゞ"

    async def test_create_maker_unauthorized(
        self,
        client_unauthenticated: AsyncClient,
    ) -> None:
        """Unauthenticated user should get 401."""
        response = await client_unauthenticated.post(
            "/api/v1/masters/makers",
            json={"name": "テスト", "code": "TEST"},
        )
        assert response.status_code == 401

    async def test_create_maker_sales_forbidden(
        self,
        client_sales: AsyncClient,
    ) -> None:
        """Sales role should get 403 when trying to create a maker."""
        response = await client_sales.post(
            "/api/v1/masters/makers",
            json={"name": "テスト", "code": "TEST"},
        )
        assert response.status_code == 403


# ===================================================================
# Body Types
# ===================================================================


class TestListBodyTypes:
    """GET /api/v1/masters/body-types"""

    async def test_list_body_types(self, client: AsyncClient) -> None:
        """Should return a list of body types."""
        body_types = [_sample_body_type()]
        with _patch_repo("list_body_types", body_types):
            response = await client.get("/api/v1/masters/body-types")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert isinstance(body["data"], list)
        assert body["data"][0]["name"] == "平ボディ"


# ===================================================================
# Categories
# ===================================================================


class TestListCategories:
    """GET /api/v1/masters/categories"""

    async def test_list_categories(self, client: AsyncClient) -> None:
        """Should return a list of vehicle categories."""
        categories = [_sample_category()]
        with _patch_repo("list_vehicle_categories", categories):
            response = await client.get("/api/v1/masters/categories")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert isinstance(body["data"], list)
        assert body["data"][0]["name"] == "小型トラック"


# ===================================================================
# HTMX <option> responses
# ===================================================================


class TestHtmxOptionsResponse:
    """HTMX requests should return <option> HTML elements."""

    async def test_htmx_makers_options(self, client: AsyncClient) -> None:
        """GET /api/v1/masters/makers with HX-Request should return <option> HTML."""
        makers = [_sample_maker()]
        with _patch_repo("list_makers", makers):
            response = await client.get(
                "/api/v1/masters/makers",
                headers={"HX-Request": "true"},
            )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type
        text = response.text
        assert "<option" in text
        assert "いすゞ" in text

    async def test_htmx_body_types_options(self, client: AsyncClient) -> None:
        """GET /api/v1/masters/body-types with HX-Request should return <option> HTML."""
        body_types = [_sample_body_type()]
        with _patch_repo("list_body_types", body_types):
            response = await client.get(
                "/api/v1/masters/body-types",
                headers={"HX-Request": "true"},
            )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type
        text = response.text
        assert "<option" in text
        assert "平ボディ" in text

    async def test_htmx_options_include_placeholder(
        self,
        client: AsyncClient,
    ) -> None:
        """HTMX option lists should include a placeholder option."""
        with _patch_repo("list_makers", []):
            response = await client.get(
                "/api/v1/masters/makers",
                headers={"HX-Request": "true"},
            )

        assert response.status_code == 200
        text = response.text
        assert '<option value="">' in text
