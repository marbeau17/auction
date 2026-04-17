"""Tests for integrated pricing engine components.

Covers the three pricing steps and the NAV curve generator:

- LeasePriceCalculator  (Step 3)
- ResidualValueCalculatorV2  (Step 2)
- NAVCalculator  (NAV curve & profit conversion)
- IntegratedPricingEngine  (end-to-end orchestration)
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.lease_price import LeasePriceCalculator
from app.core.nav_calculator import NAVCalculator
from app.core.residual_value_v2 import ResidualValueCalculatorV2
from app.models.pricing import (
    AcquisitionPriceResult,
    IntegratedPricingResult,
    LeaseFeeBreakdown,
    LeasePriceResult,
    NAVPoint,
    ResidualValueResult,
    ScenarioValue,
)


# ===================================================================
# LeasePriceCalculator
# ===================================================================


class TestLeasePriceCalculator:
    """Tests for Step 3: monthly sub-lease fee calculation."""

    @pytest.fixture
    def calc(self) -> LeasePriceCalculator:
        return LeasePriceCalculator()

    def test_basic_lease_calculation(self, calc: LeasePriceCalculator):
        """Given realistic inputs, monthly fee should exceed the pure
        depreciation portion (since it also covers investor yield, AM
        fee, placement, accounting, and operator margin)."""
        result = calc.calculate(
            acquisition_price=5_000_000,
            residual_value=500_000,
            lease_term_months=36,
        )
        depreciation_only = math.ceil(
            (5_000_000 - 500_000) / 36
        )
        assert result.monthly_lease_fee > depreciation_only
        # Sanity: fee should be positive and reasonable for a 5M truck
        assert result.monthly_lease_fee > 0
        assert result.monthly_lease_fee < 5_000_000  # less than acq per month

    def test_lease_breakdown_sums_to_total(self, calc: LeasePriceCalculator):
        """All six breakdown portions must sum exactly to total_monthly_fee."""
        result = calc.calculate(
            acquisition_price=6_000_000,
            residual_value=600_000,
            lease_term_months=36,
            investor_yield_rate=0.08,
            am_fee_rate=0.02,
            placement_fee_rate=0.03,
            accounting_fee_monthly=50_000,
            operator_margin_rate=0.02,
        )
        bd = result.fee_breakdown
        component_sum = (
            bd.depreciation_portion
            + bd.investor_dividend_portion
            + bd.am_fee_portion
            + bd.placement_fee_portion
            + bd.accounting_fee_portion
            + bd.operator_margin_portion
        )
        assert component_sum == bd.total_monthly_fee
        assert bd.total_monthly_fee == result.monthly_lease_fee

    def test_zero_residual(self, calc: LeasePriceCalculator):
        """Residual = 0 means more depreciation to recover, so the
        monthly fee should be higher than a case with positive residual."""
        kwargs = dict(
            acquisition_price=5_000_000,
            lease_term_months=36,
            investor_yield_rate=0.08,
            am_fee_rate=0.02,
            placement_fee_rate=0.03,
            accounting_fee_monthly=50_000,
            operator_margin_rate=0.02,
        )
        fee_with_residual = calc.calculate(
            residual_value=500_000, **kwargs
        ).monthly_lease_fee
        fee_zero_residual = calc.calculate(
            residual_value=0, **kwargs
        ).monthly_lease_fee
        assert fee_zero_residual > fee_with_residual

    def test_short_term_vs_long_term(self, calc: LeasePriceCalculator):
        """A shorter lease term (12 months) should produce a higher
        monthly fee than a longer term (60 months), since the same
        depreciation base is spread over fewer months."""
        kwargs = dict(
            acquisition_price=5_000_000,
            residual_value=500_000,
            investor_yield_rate=0.08,
            am_fee_rate=0.02,
            placement_fee_rate=0.03,
            accounting_fee_monthly=50_000,
            operator_margin_rate=0.02,
        )
        fee_12 = calc.calculate(
            lease_term_months=12, **kwargs
        ).monthly_lease_fee
        fee_60 = calc.calculate(
            lease_term_months=60, **kwargs
        ).monthly_lease_fee
        assert fee_12 > fee_60

    def test_breakeven_within_term(self, calc: LeasePriceCalculator):
        """For a typical deal, the breakeven month should be within the
        lease term (i.e. the deal reaches payback before contract end)."""
        result = calc.calculate(
            acquisition_price=5_000_000,
            residual_value=500_000,
            lease_term_months=36,
        )
        assert result.breakeven_month is not None
        assert result.breakeven_month <= 36

    def test_high_yield_increases_fee(self, calc: LeasePriceCalculator):
        """A higher investor yield rate should increase the monthly fee."""
        kwargs = dict(
            acquisition_price=5_000_000,
            residual_value=500_000,
            lease_term_months=36,
            am_fee_rate=0.02,
            placement_fee_rate=0.03,
            accounting_fee_monthly=50_000,
            operator_margin_rate=0.02,
        )
        fee_low = calc.calculate(
            investor_yield_rate=0.05, **kwargs
        ).monthly_lease_fee
        fee_high = calc.calculate(
            investor_yield_rate=0.12, **kwargs
        ).monthly_lease_fee
        assert fee_high > fee_low


# ===================================================================
# ResidualValueCalculatorV2
# ===================================================================


class TestResidualValueCalculatorV2:
    """Tests for Step 2: residual value with scenario analysis."""

    @pytest.fixture
    def calc(self) -> ResidualValueCalculatorV2:
        return ResidualValueCalculatorV2()

    def _base_kwargs(self) -> dict:
        """Realistic truck parameters for a 2-year-old medium-class wing body."""
        return dict(
            acquisition_price=6_000_000,
            vehicle_class="中型",
            body_type="ウイング",
            lease_term_months=36,
            current_mileage_km=80_000,
            registration_year_month="2024-04",
        )

    def test_basic_residual(self, calc: ResidualValueCalculatorV2):
        """Known inputs should produce a positive residual value."""
        result = calc.calculate(**self._base_kwargs())
        assert result.base_residual_value > 0
        assert result.base_residual_value < 6_000_000

    def test_scenarios(self, calc: ResidualValueCalculatorV2):
        """Bull scenario > Base > Bear scenario residual values."""
        result = calc.calculate(**self._base_kwargs())
        scenarios = {s.label: s.residual_value for s in result.scenarios}
        assert "bull" in scenarios
        assert "base" in scenarios
        assert "bear" in scenarios
        assert scenarios["bull"] > scenarios["base"]
        assert scenarios["base"] > scenarios["bear"]

    def test_longer_lease_lower_residual(self, calc: ResidualValueCalculatorV2):
        """A longer lease should produce a lower residual value since the
        body depreciates further."""
        kwargs = self._base_kwargs()
        kwargs["lease_term_months"] = 12
        result_short = calc.calculate(**kwargs)

        kwargs["lease_term_months"] = 84
        result_long = calc.calculate(**kwargs)

        assert result_short.base_residual_value > result_long.base_residual_value

    def test_body_type_affects_residual(self, calc: ResidualValueCalculatorV2):
        """Different body types should produce different residual values
        due to different retention rates in the depreciation table."""
        kwargs = self._base_kwargs()
        kwargs["body_type"] = "バン"
        result_van = calc.calculate(**kwargs)

        kwargs["body_type"] = "冷凍冷蔵"
        result_reefer = calc.calculate(**kwargs)

        # Van retains value better than reefer according to the table
        assert result_van.base_residual_value != result_reefer.base_residual_value


# ===================================================================
# NAVCalculator
# ===================================================================


class TestNAVCalculator:
    """Tests for NAV curve generation and profit conversion analysis."""

    @pytest.fixture
    def calc(self) -> NAVCalculator:
        return NAVCalculator()

    @pytest.fixture
    def nav_kwargs(self) -> dict:
        """Realistic NAV generation inputs for a 5M truck, 36-month lease."""
        return dict(
            acquisition_price=5_000_000,
            residual_value=500_000,
            monthly_lease_fee=200_000,
            lease_term_months=36,
            monthly_costs={
                "investor": 33_334,
                "am": 8_334,
                "placement": 4_167,
                "accounting": 50_000,
                "margin": 2_500,
            },
        )

    def test_nav_curve_length(self, calc: NAVCalculator, nav_kwargs: dict):
        """NAV curve must have exactly lease_term_months data points."""
        curve = calc.generate_nav_curve(**nav_kwargs)
        assert len(curve) == 36

    def test_nav_decreasing_book_value(
        self, calc: NAVCalculator, nav_kwargs: dict
    ):
        """Asset book value should decrease (or stay at residual) as the
        lease progresses."""
        curve = calc.generate_nav_curve(**nav_kwargs)
        for i in range(1, len(curve)):
            assert curve[i].asset_book_value <= curve[i - 1].asset_book_value

    def test_cumulative_income_increasing(
        self, calc: NAVCalculator, nav_kwargs: dict
    ):
        """Cumulative lease income should increase monotonically."""
        curve = calc.generate_nav_curve(**nav_kwargs)
        for i in range(1, len(curve)):
            assert (
                curve[i].cumulative_lease_income
                > curve[i - 1].cumulative_lease_income
            )

    def test_profit_conversion_exists(
        self, calc: NAVCalculator, nav_kwargs: dict
    ):
        """For reasonable inputs (monthly_fee > monthly_costs), profit
        should turn positive before the term ends."""
        curve = calc.generate_nav_curve(**nav_kwargs)
        profit_month = calc.find_profit_conversion_month(curve)
        assert profit_month is not None
        assert profit_month <= nav_kwargs["lease_term_months"]

    def test_termination_value_increases(self, calc: NAVCalculator):
        """Termination value should generally improve over time when
        net monthly cash flow (lease fee minus costs) comfortably
        exceeds the monthly decline in forced-sale proceeds."""
        # Use a high monthly fee relative to costs so that net cash
        # accumulation outpaces the forced-sale-proceeds decline.
        monthly_costs = {
            "investor": 20_000,
            "am": 5_000,
            "placement": 3_000,
            "accounting": 30_000,
            "margin": 2_000,
        }
        curve = calc.generate_nav_curve(
            acquisition_price=4_000_000,
            residual_value=1_000_000,
            monthly_lease_fee=250_000,
            lease_term_months=36,
            monthly_costs=monthly_costs,
        )
        # Compare early vs late -- late should have higher termination value
        early = curve[5].termination_value   # month 6
        late = curve[-1].termination_value   # month 36
        assert late > early


# ===================================================================
# IntegratedPricingEngine (integration with mocked Supabase)
# ===================================================================


class TestIntegratedPricingEngine:
    """Integration tests for the full 3-step pricing pipeline."""

    @pytest.fixture
    def mock_acquisition_result(self) -> AcquisitionPriceResult:
        """Pre-built Step 1 result to avoid hitting Supabase."""
        return AcquisitionPriceResult(
            recommended_price=5_000_000,
            max_price=5_500_000,
            price_range_low=4_750_000,
            price_range_high=5_250_000,
            market_median=4_800_000,
            trend_factor=1.00,
            safety_margin_rate=0.05,
            body_option_value=500_000,
            sample_count=10,
            confidence="high",
            trend_direction="stable",
            comparable_stats=None,
        )

    @pytest.fixture
    def pricing_input(self):
        from app.models.pricing import IntegratedPricingInput

        return IntegratedPricingInput(
            maker="いすゞ",
            model="エルフ",
            model_code="TRG-NMR85AN",
            registration_year_month="2024-04",
            mileage_km=80_000,
            vehicle_class="中型",
            body_type="ウイング",
            body_option_value=500_000,
            lease_term_months=36,
        )

    @pytest.mark.asyncio
    async def test_full_pipeline_runs(
        self,
        mock_supabase_client,
        mock_acquisition_result,
        pricing_input,
    ):
        """All 3 steps plus NAV curve generation should complete
        without raising an exception."""
        from app.core.integrated_pricing import IntegratedPricingEngine

        engine = IntegratedPricingEngine(mock_supabase_client)

        # Patch the acquisition calculator to return a canned result
        engine.acquisition_calc.calculate = AsyncMock(
            return_value=mock_acquisition_result
        )

        result = await engine.calculate(pricing_input)
        assert isinstance(result, IntegratedPricingResult)

    @pytest.mark.asyncio
    async def test_result_has_all_fields(
        self,
        mock_supabase_client,
        mock_acquisition_result,
        pricing_input,
    ):
        """The result must contain acquisition, residual, lease, and
        nav_curve sections with reasonable values."""
        from app.core.integrated_pricing import IntegratedPricingEngine

        engine = IntegratedPricingEngine(mock_supabase_client)
        engine.acquisition_calc.calculate = AsyncMock(
            return_value=mock_acquisition_result
        )

        result = await engine.calculate(pricing_input)

        # Step 1: acquisition
        assert result.acquisition.recommended_price > 0
        assert result.acquisition.sample_count >= 0

        # Step 2: residual
        assert result.residual.base_residual_value > 0
        assert len(result.residual.scenarios) == 3

        # Step 3: lease
        assert result.lease.monthly_lease_fee > 0
        assert result.lease.fee_breakdown.total_monthly_fee > 0
        assert result.lease.effective_yield_rate > 0

        # NAV curve
        assert len(result.nav_curve) == pricing_input.lease_term_months
        assert result.profit_conversion_month >= 1

        # Assessment
        assert result.assessment in ("推奨", "要検討", "非推奨")
        assert len(result.assessment_reasons) > 0
