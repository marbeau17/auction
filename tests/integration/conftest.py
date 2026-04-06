"""Shared fixtures for integration tests.

Provides a mock Supabase client, JWT tokens for auth, and an httpx AsyncClient
wired to the FastAPI application with dependency overrides.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

# Ensure test env vars are set before app imports
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "true")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")

from app.config import get_settings  # noqa: E402
from app.dependencies import get_current_user, get_supabase_client  # noqa: E402
from app.main import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JWT_SECRET = "test-jwt-secret"
ADMIN_USER_ID = str(uuid4())
SALES_USER_ID = str(uuid4())
ADMIN_EMAIL = "admin@example.com"
SALES_EMAIL = "sales@example.com"

SAMPLE_VEHICLE_ID = str(uuid4())
SAMPLE_SIMULATION_ID = str(uuid4())
SAMPLE_MAKER_ID = str(uuid4())
SAMPLE_BODY_TYPE_ID = str(uuid4())
SAMPLE_CATEGORY_ID = str(uuid4())

NOW_ISO = datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_jwt(user_id: str, email: str, role: str) -> str:
    """Create a signed JWT for testing."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(datetime.now(tz=timezone.utc).timestamp()),
        "exp": int(datetime.now(tz=timezone.utc).timestamp()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# Mock Supabase helpers
# ---------------------------------------------------------------------------


def _make_chainable_query(
    data: list[dict[str, Any]] | None = None,
    count: int | None = None,
    single_data: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a chainable Supabase query mock that returns realistic data."""
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
    response.data = data if data is not None else []
    response.count = count
    query.execute.return_value = response

    # maybe_single support
    single_response = MagicMock()
    single_response.data = single_data
    single_query = MagicMock()
    single_query.execute.return_value = single_response
    query.maybe_single.return_value = single_query

    return query


def _make_mock_supabase(
    vehicles: list[dict[str, Any]] | None = None,
    vehicle_count: int = 0,
    single_vehicle: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a full mock Supabase client."""
    client = MagicMock()

    if vehicles is None:
        vehicles = []

    query = _make_chainable_query(
        data=vehicles,
        count=vehicle_count,
        single_data=single_vehicle,
    )

    client.table.return_value = query

    # Auth mocks
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
# Sample data factories
# ---------------------------------------------------------------------------


def _sample_vehicle(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a realistic vehicle dict."""
    base = {
        "id": SAMPLE_VEHICLE_ID,
        "source_site": "truckmarket",
        "source_url": "https://example.com/listing/12345",
        "source_id": "TM-12345",
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
    }
    if overrides:
        base.update(overrides)
    return base


def _sample_simulation_result() -> dict[str, Any]:
    """Return a realistic simulation result dict."""
    return {
        "id": SAMPLE_SIMULATION_ID,
        "user_id": ADMIN_USER_ID,
        "title": "いすゞ エルフ 2020年式 シミュレーション",
        "input_data": {
            "maker": "いすゞ",
            "model": "エルフ",
            "registration_year_month": "2020-04",
            "mileage_km": 85000,
            "acquisition_price": 6000000,
            "book_value": 3200000,
            "vehicle_class": "小型",
            "body_type": "平ボディ",
            "target_yield_rate": 0.08,
            "lease_term_months": 36,
        },
        "result": {
            "max_purchase_price": 3800000,
            "recommended_purchase_price": 3500000,
            "estimated_residual_value": 350000,
            "residual_rate_result": 0.10,
            "monthly_lease_fee": 120000,
            "total_lease_fee": 4320000,
            "breakeven_months": 24,
            "effective_yield_rate": 0.082,
            "market_median_price": 3600000,
            "market_sample_count": 15,
            "market_deviation_rate": -0.028,
            "assessment": "推奨",
            "monthly_schedule": [
                {
                    "month": i,
                    "asset_value": 3200000 - i * 80000,
                    "lease_income": 120000,
                    "cumulative_income": 120000 * i,
                    "depreciation_expense": 80000,
                    "financing_cost": 20000,
                    "monthly_profit": 20000,
                    "cumulative_profit": 20000 * i,
                    "termination_loss": max(-500000 + i * 20000, -500000),
                }
                for i in range(1, 37)
            ],
        },
        "status": "completed",
        "created_at": NOW_ISO,
        "updated_at": NOW_ISO,
    }


def _sample_maker() -> dict[str, Any]:
    return {
        "id": SAMPLE_MAKER_ID,
        "name": "いすゞ",
        "name_en": "Isuzu",
        "code": "ISUZU",
        "display_order": 1,
        "is_active": True,
    }


def _sample_body_type() -> dict[str, Any]:
    return {
        "id": SAMPLE_BODY_TYPE_ID,
        "name": "平ボディ",
        "code": "FLATBODY",
        "category_id": SAMPLE_CATEGORY_ID,
        "display_order": 1,
        "is_active": True,
    }


def _sample_category() -> dict[str, Any]:
    return {
        "id": SAMPLE_CATEGORY_ID,
        "name": "小型トラック",
        "code": "SMALL_TRUCK",
        "display_order": 1,
        "is_active": True,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_token() -> str:
    """JWT for an admin user."""
    return _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")


@pytest.fixture
def sales_token() -> str:
    """JWT for a sales user."""
    return _make_jwt(SALES_USER_ID, SALES_EMAIL, "sales")


@pytest.fixture
def admin_user() -> dict[str, Any]:
    """Decoded admin user dict."""
    return {"id": ADMIN_USER_ID, "email": ADMIN_EMAIL, "role": "admin"}


@pytest.fixture
def sales_user() -> dict[str, Any]:
    """Decoded sales user dict."""
    return {"id": SALES_USER_ID, "email": SALES_EMAIL, "role": "sales"}


@pytest.fixture
def mock_supabase() -> MagicMock:
    """Default mock Supabase with sample vehicles."""
    vehicles = [_sample_vehicle()]
    return _make_mock_supabase(
        vehicles=vehicles,
        vehicle_count=1,
        single_vehicle=vehicles[0],
    )


@pytest.fixture
def sample_vehicles() -> list[dict[str, Any]]:
    """A list of sample vehicle dicts."""
    return [
        _sample_vehicle(),
        _sample_vehicle(
            {
                "id": str(uuid4()),
                "maker": "日野",
                "model_name": "プロフィア",
                "body_type": "ウイング",
                "model_year": 2019,
                "mileage_km": 150000,
                "price_yen": 8500000,
                "vehicle_class": "大型",
            }
        ),
        _sample_vehicle(
            {
                "id": str(uuid4()),
                "maker": "三菱ふそう",
                "model_name": "スーパーグレート",
                "body_type": "冷凍車",
                "model_year": 2021,
                "mileage_km": 60000,
                "price_yen": 12000000,
                "vehicle_class": "大型",
            }
        ),
    ]


@pytest.fixture
async def client(admin_token: str, mock_supabase: MagicMock) -> AsyncClient:
    """Authenticated httpx AsyncClient with mocked dependencies."""
    app = create_app()

    async def _override_current_user() -> dict[str, Any]:
        return {"id": ADMIN_USER_ID, "email": ADMIN_EMAIL, "role": "admin"}

    def _override_supabase() -> MagicMock:
        return mock_supabase

    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": admin_token},
    ) as ac:
        yield ac


@pytest.fixture
async def client_unauthenticated() -> AsyncClient:
    """httpx AsyncClient with NO auth and NO dependency overrides for auth."""
    app = create_app()

    def _override_supabase() -> MagicMock:
        return _make_mock_supabase()

    app.dependency_overrides[get_supabase_client] = _override_supabase
    # Do NOT override get_current_user -- let it check cookies normally

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def client_sales(sales_token: str, mock_supabase: MagicMock) -> AsyncClient:
    """Authenticated httpx AsyncClient with sales role."""
    app = create_app()

    async def _override_current_user() -> dict[str, Any]:
        return {"id": SALES_USER_ID, "email": SALES_EMAIL, "role": "sales"}

    def _override_supabase() -> MagicMock:
        return mock_supabase

    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": sales_token},
    ) as ac:
        yield ac


@pytest.fixture
def simulation_input_data() -> dict[str, Any]:
    """Valid simulation input as a JSON-serialisable dict."""
    return {
        "maker": "いすゞ",
        "model": "エルフ",
        "model_code": "TRG-NMR85AN",
        "registration_year_month": "2020-04",
        "mileage_km": 85000,
        "acquisition_price": 6000000,
        "book_value": 3200000,
        "vehicle_class": "小型",
        "payload_ton": 2.0,
        "body_type": "平ボディ",
        "body_option_value": 500000,
        "target_yield_rate": 0.08,
        "lease_term_months": 36,
        "residual_rate": 0.10,
        "insurance_monthly": 15000,
        "maintenance_monthly": 10000,
    }


@pytest.fixture
def simulation_result_data() -> dict[str, Any]:
    """A complete simulation result dict for mock responses."""
    return _sample_simulation_result()


@pytest.fixture
def sample_maker_data() -> dict[str, Any]:
    return _sample_maker()


@pytest.fixture
def sample_body_type_data() -> dict[str, Any]:
    return _sample_body_type()


@pytest.fixture
def sample_category_data() -> dict[str, Any]:
    return _sample_category()
