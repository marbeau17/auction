"""Unit tests for ``app.core.acquisition_price.AcquisitionPriceCalculator``.

Focuses on deterministic, mockable behaviour:

* Trend factor clamped to [TREND_FLOOR, TREND_CEILING]
* Dynamic safety margin clamped to [MIN_SAFETY_MARGIN, MAX_SAFETY_MARGIN]
* Body option value is additively applied to both recommended and max price
* Weighted median handles edge cases (empty, single, uniform weights,
  similarity-score weighted)
* Category resolution maps Japanese vehicle classes correctly
* Empty/no-data path returns a zeroed result
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.acquisition_price import AcquisitionPriceCalculator
from app.core import pricing_constants as _C
from app.models.pricing import AcquisitionPriceResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calculator() -> AcquisitionPriceCalculator:
    """Construct calculator with a dummy Supabase client (not called)."""
    return AcquisitionPriceCalculator(MagicMock())


def _comps(prices: list[float]) -> list[dict]:
    """Wrap prices in a list of comparable-like dicts (no similarity score)."""
    return [{"price": p} for p in prices]


# ---------------------------------------------------------------------------
# Weighted median
# ---------------------------------------------------------------------------


class TestWeightedMedian:

    def test_empty_returns_zero(self, calculator: AcquisitionPriceCalculator):
        assert calculator._weighted_median([], []) == 0.0

    def test_single_price_returned_as_is(
        self, calculator: AcquisitionPriceCalculator
    ):
        assert calculator._weighted_median([3_000_000.0], [{"price": 3_000_000}]) == 3_000_000.0

    def test_uniform_weights_recency_fallback(
        self, calculator: AcquisitionPriceCalculator
    ):
        # Without similarity_score, recency weighting is applied.
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        comps = _comps(prices)
        result = calculator._weighted_median(prices, comps)
        # Weighted median under linearly increasing weights should be >= unweighted.
        assert result >= 3.0
        assert result in prices

    def test_similarity_score_weighting(
        self, calculator: AcquisitionPriceCalculator
    ):
        # With dominating similarity score on the cheap comp, median should
        # lean toward that cheap value.
        prices = [100.0, 200.0, 300.0]
        comps = [
            {"price": 100, "similarity_score": 10.0},
            {"price": 200, "similarity_score": 0.1},
            {"price": 300, "similarity_score": 0.1},
        ]
        result = calculator._weighted_median(prices, comps)
        assert result == 100.0


# ---------------------------------------------------------------------------
# Category resolution
# ---------------------------------------------------------------------------


class TestResolveCategory:

    @pytest.mark.parametrize(
        "vehicle_class,expected",
        [
            ("小型", "SMALL"),
            ("中型", "MEDIUM"),
            ("大型", "LARGE"),
            ("トレーラヘッド", "TRAILER_HEAD"),
            ("トレーラーヘッド", "TRAILER_HEAD"),
            ("トレーラシャーシ", "TRAILER_CHASSIS"),
            ("トレーラーシャーシ", "TRAILER_CHASSIS"),
            ("unknown", "MEDIUM"),  # fallback
        ],
    )
    def test_vehicle_class_map(
        self, vehicle_class: str, expected: str
    ):
        got = AcquisitionPriceCalculator._resolve_category(
            {"vehicle_class": vehicle_class}
        )
        assert got == expected

    def test_category_override_wins_and_uppercased(self):
        got = AcquisitionPriceCalculator._resolve_category(
            {"category": "small", "vehicle_class": "大型"}
        )
        assert got == "SMALL"


# ---------------------------------------------------------------------------
# Clamp ranges (via pricing_constants)
# ---------------------------------------------------------------------------


class TestClampConstants:

    def test_trend_range_is_0_80_to_1_20(self):
        assert _C.TREND_FLOOR == pytest.approx(0.80)
        assert _C.TREND_CEILING == pytest.approx(1.20)

    def test_safety_margin_range_is_0_03_to_0_20(self):
        assert _C.MIN_SAFETY_MARGIN == pytest.approx(0.03)
        assert _C.MAX_SAFETY_MARGIN == pytest.approx(0.20)

    def test_calculator_class_attrs_match_constants(
        self, calculator: AcquisitionPriceCalculator
    ):
        # The class attributes must stay wired to pricing_constants so a
        # single-source-of-truth change propagates.
        assert calculator.TREND_FLOOR == _C.TREND_FLOOR
        assert calculator.TREND_CEILING == _C.TREND_CEILING
        assert calculator.MIN_SAFETY_MARGIN == _C.MIN_SAFETY_MARGIN
        assert calculator.MAX_SAFETY_MARGIN == _C.MAX_SAFETY_MARGIN


# ---------------------------------------------------------------------------
# Empty / fallback result
# ---------------------------------------------------------------------------


class TestEmptyResult:

    def test_empty_result_shape(self):
        r = AcquisitionPriceCalculator._empty_result()
        assert isinstance(r, AcquisitionPriceResult)
        assert r.recommended_price == 0
        assert r.max_price == 0
        assert r.sample_count == 0
        assert r.confidence == "low"
        assert r.trend_direction == "stable"
        assert r.trend_factor == 1.0


# ---------------------------------------------------------------------------
# Body option handling (end-to-end via calculate(), mocked backend)
# ---------------------------------------------------------------------------


class TestBodyOptionApplied:

    @pytest.mark.asyncio
    async def test_body_option_added_additively(
        self, monkeypatch, calculator: AcquisitionPriceCalculator
    ):
        """body_option_value should be added after trend/margin adjustment
        to BOTH recommended and max prices."""

        # Stub the async comparable fetch
        async def _fake_fetch(_input):
            # 5 identical comps so stats are well-defined
            return [{"price": 1_000_000} for _ in range(5)]

        monkeypatch.setattr(
            calculator, "_fetch_comparables", _fake_fetch
        )

        # Force trend = 1.0 (no change) so we can reason about exact body add
        calculator.market_analyzer.calculate_trend = MagicMock(
            return_value={"trend_factor": 1.0, "direction": "stable"}
        )

        base = await calculator.calculate(
            {
                "maker": "いすゞ",
                "model": "エルフ",
                "vehicle_class": "小型",
                "body_option_value": 0,
            },
            safety_margin_rate=0.05,
        )
        with_body = await calculator.calculate(
            {
                "maker": "いすゞ",
                "model": "エルフ",
                "vehicle_class": "小型",
                "body_option_value": 500_000,
            },
            safety_margin_rate=0.05,
        )

        # Exactly +500,000 on both recommended and max (additive).
        assert with_body.recommended_price - base.recommended_price == 500_000
        assert with_body.max_price - base.max_price == 500_000
        assert with_body.body_option_value == 500_000

    @pytest.mark.asyncio
    async def test_trend_factor_clamped_high(
        self, monkeypatch, calculator: AcquisitionPriceCalculator
    ):
        """If analyzer returns an extreme trend like 2.0, the calculator
        must clamp it to TREND_CEILING (1.20)."""

        async def _fake_fetch(_input):
            return [{"price": 1_000_000} for _ in range(5)]

        monkeypatch.setattr(calculator, "_fetch_comparables", _fake_fetch)
        calculator.market_analyzer.calculate_trend = MagicMock(
            return_value={"trend_factor": 2.0, "direction": "up"}
        )

        r = await calculator.calculate(
            {"maker": "いすゞ", "model": "エルフ", "vehicle_class": "小型"},
            safety_margin_rate=0.05,
        )
        assert r.trend_factor == pytest.approx(_C.TREND_CEILING)

    @pytest.mark.asyncio
    async def test_trend_factor_clamped_low(
        self, monkeypatch, calculator: AcquisitionPriceCalculator
    ):
        async def _fake_fetch(_input):
            return [{"price": 1_000_000} for _ in range(5)]

        monkeypatch.setattr(calculator, "_fetch_comparables", _fake_fetch)
        calculator.market_analyzer.calculate_trend = MagicMock(
            return_value={"trend_factor": 0.1, "direction": "down"}
        )

        r = await calculator.calculate(
            {"maker": "いすゞ", "model": "エルフ", "vehicle_class": "小型"},
            safety_margin_rate=0.05,
        )
        assert r.trend_factor == pytest.approx(_C.TREND_FLOOR)

    @pytest.mark.asyncio
    async def test_safety_margin_clamped_when_volatility_high(
        self, monkeypatch, calculator: AcquisitionPriceCalculator
    ):
        """Very volatile prices (big std) should still yield a margin
        clamped at MAX_SAFETY_MARGIN."""

        async def _fake_fetch(_input):
            # High dispersion: CV will be huge -> triggers max-clamp.
            return [
                {"price": 100_000},
                {"price": 10_000_000},
                {"price": 500_000},
                {"price": 9_000_000},
            ]

        monkeypatch.setattr(calculator, "_fetch_comparables", _fake_fetch)
        calculator.market_analyzer.calculate_trend = MagicMock(
            return_value={"trend_factor": 1.0, "direction": "stable"}
        )

        r = await calculator.calculate(
            {"maker": "いすゞ", "model": "エルフ", "vehicle_class": "小型"},
            safety_margin_rate=0.05,
        )
        assert r.safety_margin_rate == pytest.approx(_C.MAX_SAFETY_MARGIN)

    @pytest.mark.asyncio
    async def test_no_data_returns_empty_result(
        self, monkeypatch, calculator: AcquisitionPriceCalculator
    ):
        async def _fake_fetch(_input):
            return []

        monkeypatch.setattr(calculator, "_fetch_comparables", _fake_fetch)

        r = await calculator.calculate(
            {"maker": "いすゞ", "model": "エルフ", "vehicle_class": "小型"},
            safety_margin_rate=0.05,
        )
        assert r.recommended_price == 0
        assert r.sample_count == 0
        assert r.confidence == "low"
