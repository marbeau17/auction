"""Tests for the residual value calculator (app.core.residual_value).

Covers useful life calculation, straight-line and declining-balance
depreciation, mileage adjustment, and hybrid prediction with market data.
"""

from __future__ import annotations

import pytest

from app.core.residual_value import ResidualValueCalculator


@pytest.fixture
def calc() -> ResidualValueCalculator:
    """Fresh calculator instance."""
    return ResidualValueCalculator()


# ===================================================================
# Used vehicle useful life
# ===================================================================


class TestUsedVehicleUsefulLife:
    """Tests for 中古車耐用年数簡便法."""

    def test_used_vehicle_useful_life_recent(self, calc: ResidualValueCalculator):
        """A 2-year-old truck with legal life 5: remaining = 5 - 2 = 3."""
        result = calc.calculate_used_vehicle_useful_life(
            legal_life=5, elapsed_years=2
        )
        assert result == 3

    def test_used_vehicle_useful_life_old(self, calc: ResidualValueCalculator):
        """A 10-year-old truck with legal life 5: exceeded -> int(10*0.2) = 2."""
        result = calc.calculate_used_vehicle_useful_life(
            legal_life=5, elapsed_years=10
        )
        assert result == 2

    def test_used_vehicle_useful_life_minimum(self, calc: ResidualValueCalculator):
        """Result is always at least 2 years."""
        result = calc.calculate_used_vehicle_useful_life(
            legal_life=3, elapsed_years=2
        )
        # remaining = 3 - 2 = 1 -> max(1, 2) = 2
        assert result == 2

    def test_used_vehicle_useful_life_zero_legal(self, calc: ResidualValueCalculator):
        """Zero legal life -> minimum 2."""
        result = calc.calculate_used_vehicle_useful_life(
            legal_life=0, elapsed_years=3
        )
        assert result == 2

    def test_used_vehicle_useful_life_negative_elapsed(
        self, calc: ResidualValueCalculator
    ):
        """Negative elapsed years treated as 0."""
        result = calc.calculate_used_vehicle_useful_life(
            legal_life=5, elapsed_years=-1
        )
        # remaining = 5 - 0 = 5
        assert result == 5


# ===================================================================
# Straight-line depreciation
# ===================================================================


class TestStraightLineDepreciation:
    def test_straight_line_depreciation(self, calc: ResidualValueCalculator):
        """5M purchase, 500K salvage, 5-year life, 2 years elapsed."""
        value = calc.straight_line(
            purchase_price=5_000_000,
            salvage_value=500_000,
            useful_life=5,
            elapsed_years=2,
        )
        # annual_depr = (5M - 500K) / 5 = 900K
        # value = 5M - 900K * 2 = 3_200_000
        assert value == 3_200_000.0

    def test_straight_line_at_end_of_life(self, calc: ResidualValueCalculator):
        """At end of useful life, value equals salvage."""
        value = calc.straight_line(
            purchase_price=5_000_000,
            salvage_value=500_000,
            useful_life=5,
            elapsed_years=5,
        )
        assert value == 500_000.0

    def test_straight_line_beyond_life(self, calc: ResidualValueCalculator):
        """Past useful life, value floors at salvage."""
        value = calc.straight_line(
            purchase_price=5_000_000,
            salvage_value=500_000,
            useful_life=5,
            elapsed_years=10,
        )
        assert value == 500_000.0


# ===================================================================
# 200% Declining-balance depreciation
# ===================================================================


class TestDecliningBalance200:
    def test_declining_balance_200(self, calc: ResidualValueCalculator):
        """5M purchase, 5-year life, 1 year elapsed."""
        value = calc.declining_balance_200(
            purchase_price=5_000_000,
            useful_life=5,
            elapsed_years=1,
        )
        # rate = 2/5 = 0.4
        # year 1: depr = 5M * 0.4 = 2M -> value = 3M
        assert value == 3_000_000.0

    def test_declining_balance_200_full_life(self, calc: ResidualValueCalculator):
        """After full useful life, value should be near memorandum value."""
        value = calc.declining_balance_200(
            purchase_price=5_000_000,
            useful_life=5,
            elapsed_years=5,
        )
        # Should be at or near 1.0 (memorandum value)
        assert value >= 1.0
        assert value < 500_000  # well below purchase

    def test_declining_balance_200_zero_life(self, calc: ResidualValueCalculator):
        """Zero useful life -> memorandum value 1.0."""
        value = calc.declining_balance_200(
            purchase_price=5_000_000,
            useful_life=0,
            elapsed_years=3,
        )
        assert value == 1.0


# ===================================================================
# Predict (hybrid entry point)
# ===================================================================


class TestPredict:
    def test_predict_with_market_data(self, calc: ResidualValueCalculator):
        """Hybrid method blends theoretical with market data."""
        result = calc.predict(
            purchase_price=5_000_000,
            category="普通貨物",
            body_type="ウイング",
            elapsed_months=36,
            mileage=120_000,
            market_data={
                "median_price": 2_800_000,
                "sample_count": 15,
                "volatility": 0.10,
            },
        )

        assert result["method_used"] == "hybrid"
        assert result["residual_value"] > 0
        assert result["confidence"] > 0
        assert "chassis" in result["breakdown"]
        assert "body" in result["breakdown"]
        assert "mileage_adj" in result["breakdown"]

    def test_predict_without_market_data(self, calc: ResidualValueCalculator):
        """Without market data, uses pure theoretical calculation."""
        result = calc.predict(
            purchase_price=5_000_000,
            category="普通貨物",
            body_type="平ボディ",
            elapsed_months=24,
            mileage=80_000,
            market_data=None,
        )

        assert result["method_used"] == "theoretical"
        assert result["confidence"] == 0.4
        assert result["residual_value"] > 0
        # Value should be rounded to nearest 万円
        assert result["residual_value"] % 10_000 == 0

    def test_predict_zero_purchase(self, calc: ResidualValueCalculator):
        """Zero purchase price returns zero residual."""
        result = calc.predict(
            purchase_price=0,
            category="普通貨物",
            body_type="平ボディ",
            elapsed_months=24,
            mileage=50_000,
        )
        assert result["residual_value"] == 0
        assert result["method_used"] == "none"
