"""Shared fixtures for end-to-end tests.

E2E tests exercise the full application stack with mocked external
dependencies (Supabase). They simulate real user workflows across
multiple endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

# Ensure test env vars
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "true")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")

from app.dependencies import get_current_user, get_supabase_client  # noqa: E402
from app.main import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JWT_SECRET = "test-jwt-secret"
ADMIN_USER_ID = str(uuid4())
ADMIN_EMAIL = "admin@example.com"
SALES_USER_ID = str(uuid4())
SALES_EMAIL = "sales@example.com"

NOW_ISO = datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(datetime.now(tz=timezone.utc).timestamp()),
        "exp": int(datetime.now(tz=timezone.utc).timestamp()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _build_mock_supabase(
    vehicles: list[dict[str, Any]] | None = None,
    makers: list[dict[str, Any]] | None = None,
    body_types: list[dict[str, Any]] | None = None,
    categories: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Create a comprehensive mock Supabase client for E2E flows."""
    client = MagicMock()

    if vehicles is None:
        vehicles = [
            {
                "id": str(uuid4()),
                "source_site": "truckmarket",
                "source_url": "https://example.com/listing/1",
                "source_id": "TM-0001",
                "maker": "いすゞ",
                "model_name": "エルフ",
                "body_type": "平ボディ",
                "model_year": 2020,
                "mileage_km": 85000,
                "price_yen": 3500000,
                "price_tax_included": True,
                "tonnage": 2.0,
                "transmission": "AT",
                "fuel_type": "軽油",
                "location_prefecture": "東京都",
                "listing_status": "active",
                "scraped_at": NOW_ISO,
                "is_active": True,
                "created_at": NOW_ISO,
                "updated_at": NOW_ISO,
            },
            {
                "id": str(uuid4()),
                "source_site": "truckmarket",
                "source_url": "https://example.com/listing/2",
                "source_id": "TM-0002",
                "maker": "日野",
                "model_name": "プロフィア",
                "body_type": "ウイング",
                "model_year": 2019,
                "mileage_km": 150000,
                "price_yen": 8500000,
                "price_tax_included": True,
                "tonnage": 10.0,
                "transmission": "MT",
                "fuel_type": "軽油",
                "location_prefecture": "大阪府",
                "listing_status": "active",
                "scraped_at": NOW_ISO,
                "is_active": True,
                "created_at": NOW_ISO,
                "updated_at": NOW_ISO,
            },
        ]

    # Chainable query builder
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.neq.return_value = query
    query.gte.return_value = query
    query.lte.return_value = query
    query.ilike.return_value = query
    query.not_.return_value = query
    query.not_.is_.return_value = query
    query.is_.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.limit.return_value = query
    query.insert.return_value = query
    query.update.return_value = query
    query.upsert.return_value = query
    query.delete.return_value = query

    response = MagicMock()
    response.data = vehicles
    response.count = len(vehicles)
    query.execute.return_value = response

    single_resp = MagicMock()
    single_resp.data = vehicles[0] if vehicles else None
    single_query = MagicMock()
    single_query.execute.return_value = single_resp
    query.maybe_single.return_value = single_query

    client.table.return_value = query

    # Auth
    session_mock = MagicMock()
    session_mock.access_token = _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")
    session_mock.refresh_token = "mock-refresh-token"
    auth_response = MagicMock()
    auth_response.session = session_mock
    client.auth.sign_in_with_password.return_value = auth_response
    client.auth.refresh_session.return_value = auth_response
    client.auth.sign_out.return_value = None

    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_supabase_e2e() -> MagicMock:
    return _build_mock_supabase()


@pytest.fixture
async def client(mock_supabase_e2e: MagicMock) -> AsyncClient:
    """Authenticated admin client for E2E tests."""
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return {"id": ADMIN_USER_ID, "email": ADMIN_EMAIL, "role": "admin"}

    def _override_supabase() -> MagicMock:
        return mock_supabase_e2e

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


@pytest.fixture
async def client_sales(mock_supabase_e2e: MagicMock) -> AsyncClient:
    """Authenticated sales client for E2E tests."""
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return {"id": SALES_USER_ID, "email": SALES_EMAIL, "role": "sales"}

    def _override_supabase() -> MagicMock:
        return mock_supabase_e2e

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
