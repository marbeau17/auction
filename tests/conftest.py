"""Shared pytest fixtures for the Commercial Vehicle Leaseback Pricing Optimizer."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Environment variables for testing (set before any app imports)
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "true")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")

from app.config import Settings  # noqa: E402
from app.models.simulation import (  # noqa: E402
    MonthlyScheduleItem,
    SimulationInput,
    SimulationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_supabase_client() -> MagicMock:
    """Return a mocked Supabase client with chainable query builder."""
    client = MagicMock()

    # Build a chainable query mock
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.gte.return_value = query
    query.lte.return_value = query
    query.not_.is_.return_value = query

    # Default: return empty result
    response = MagicMock()
    response.data = []
    query.execute.return_value = response

    client.table.return_value = query
    return client


@pytest.fixture
def sample_vehicle_data() -> dict:
    """Realistic vehicle data for a 2020 Isuzu Elf flatbed truck."""
    return {
        "maker": "いすゞ",
        "model": "エルフ",
        "model_code": "TRG-NMR85AN",
        "body_type": "平ボディ",
        "model_year": 2020,
        "mileage_km": 85_000,
        "price_yen": 3_500_000,
        "registration_year_month": "2020-04",
        "acquisition_price": 6_000_000,
        "book_value": 3_200_000,
        "vehicle_class": "小型",
        "payload_ton": 2.0,
        "category": "普通貨物",
    }


@pytest.fixture
def sample_simulation_input() -> SimulationInput:
    """Realistic SimulationInput for a small truck leaseback."""
    return SimulationInput(
        maker="いすゞ",
        model="エルフ",
        model_code="TRG-NMR85AN",
        registration_year_month="2020-04",
        mileage_km=85_000,
        acquisition_price=6_000_000,
        book_value=3_200_000,
        vehicle_class="小型",
        payload_ton=2.0,
        body_type="平ボディ",
        body_option_value=500_000,
        target_yield_rate=0.08,
        lease_term_months=36,
        residual_rate=0.10,
        insurance_monthly=15_000,
        maintenance_monthly=10_000,
    )


@pytest.fixture
def sample_market_data() -> dict:
    """Market data for hybrid residual value prediction."""
    return {
        "median_price": 3_200_000,
        "sample_count": 15,
        "volatility": 0.12,
    }
