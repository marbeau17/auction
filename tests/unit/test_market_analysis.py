"""Tests for the market analyzer (app.core.market_analysis).

Covers statistical summary, outlier detection, trend calculation,
volatility measurement, comparable vehicle search, and deviation rate.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.market_analysis import MarketAnalyzer


@pytest.fixture
def analyzer() -> MarketAnalyzer:
    """Fresh MarketAnalyzer instance."""
    return MarketAnalyzer()


# ===================================================================
# Statistical summary
# ===================================================================


class TestStatistics:
    def test_statistics_normal_data(self, analyzer: MarketAnalyzer):
        """Standard price list produces correct statistics."""
        prices = [
            2_500_000,
            2_800_000,
            3_000_000,
            3_200_000,
            3_500_000,
            3_000_000,
            2_900_000,
            3_100_000,
        ]
        stats = analyzer.calculate_statistics(prices)

        assert stats["count"] == 8
        assert stats["mean"] > 0
        assert stats["median"] > 0
        assert stats["min"] == 2_500_000.0
        assert stats["max"] == 3_500_000.0
        assert stats["std"] > 0
        assert stats["q25"] > 0
        assert stats["q75"] > 0
        assert stats["iqr"] == stats["q75"] - stats["q25"]

    def test_statistics_empty_list(self, analyzer: MarketAnalyzer):
        """Empty price list returns zeroed statistics."""
        stats = analyzer.calculate_statistics([])

        assert stats["count"] == 0
        assert stats["mean"] == 0.0
        assert stats["median"] == 0.0
        assert stats["std"] == 0.0

    def test_statistics_single_value(self, analyzer: MarketAnalyzer):
        """Single-element list: std should be 0."""
        stats = analyzer.calculate_statistics([3_000_000])
        assert stats["count"] == 1
        assert stats["mean"] == 3_000_000.0
        assert stats["std"] == 0.0


# ===================================================================
# Outlier detection
# ===================================================================


class TestOutlierDetection:
    def test_detect_outliers_iqr(self, analyzer: MarketAnalyzer):
        """Extreme values are flagged as outliers."""
        prices = [
            3_000_000,
            3_100_000,
            3_050_000,
            3_200_000,
            3_000_000,
            # Outlier: way above normal range
            15_000_000,
        ]
        outliers = analyzer.detect_outliers(prices, method="iqr", factor=1.5)
        # Index 5 (15M) should be an outlier
        assert 5 in outliers

    def test_detect_outliers_no_outliers(self, analyzer: MarketAnalyzer):
        """Tight cluster has no outliers."""
        prices = [3_000_000, 3_050_000, 3_100_000, 3_000_000, 3_080_000]
        outliers = analyzer.detect_outliers(prices, method="iqr", factor=1.5)
        assert len(outliers) == 0

    def test_detect_outliers_too_few(self, analyzer: MarketAnalyzer):
        """Fewer than 4 items -> empty outlier list."""
        prices = [1_000_000, 2_000_000, 3_000_000]
        outliers = analyzer.detect_outliers(prices)
        assert outliers == []


# ===================================================================
# Trend calculation
# ===================================================================


class TestTrend:
    def test_calculate_trend_upward(self, analyzer: MarketAnalyzer):
        """Recent prices higher than baseline -> upward trend."""
        now = datetime.utcnow()
        history = []
        # Baseline (60-180 days ago): ~3M
        for i in range(60, 180, 10):
            history.append({
                "date": (now - timedelta(days=i)).isoformat(),
                "price": 3_000_000,
            })
        # Recent (last 30 days): ~3.5M
        for i in range(0, 30, 5):
            history.append({
                "date": (now - timedelta(days=i)).isoformat(),
                "price": 3_500_000,
            })

        result = analyzer.calculate_trend(history)
        assert result["direction"] == "up"
        assert result["trend_factor"] > 1.0
        assert result["recent_avg"] > result["baseline_avg"]

    def test_calculate_trend_downward(self, analyzer: MarketAnalyzer):
        """Recent prices lower than baseline -> downward trend."""
        now = datetime.utcnow()
        history = []
        # Baseline: ~3.5M
        for i in range(60, 180, 10):
            history.append({
                "date": (now - timedelta(days=i)).isoformat(),
                "price": 3_500_000,
            })
        # Recent: ~2.8M
        for i in range(0, 30, 5):
            history.append({
                "date": (now - timedelta(days=i)).isoformat(),
                "price": 2_800_000,
            })

        result = analyzer.calculate_trend(history)
        assert result["direction"] == "down"
        assert result["trend_factor"] < 1.0

    def test_calculate_trend_empty(self, analyzer: MarketAnalyzer):
        """Empty history returns neutral trend."""
        result = analyzer.calculate_trend([])
        assert result["direction"] == "stable"
        assert result["trend_factor"] == 1.0


# ===================================================================
# Volatility
# ===================================================================


class TestVolatility:
    def test_calculate_volatility(self, analyzer: MarketAnalyzer):
        """Mixed prices produce positive volatility (CV)."""
        prices = [2_500_000, 3_000_000, 3_500_000, 2_800_000, 3_200_000]
        vol = analyzer.calculate_volatility(prices)
        assert vol > 0
        # CV for these values should be modest (< 0.15)
        assert vol < 0.20

    def test_calculate_volatility_constant(self, analyzer: MarketAnalyzer):
        """Constant prices -> zero volatility."""
        prices = [3_000_000, 3_000_000, 3_000_000]
        vol = analyzer.calculate_volatility(prices)
        assert vol == 0.0

    def test_calculate_volatility_empty(self, analyzer: MarketAnalyzer):
        """Empty list -> zero volatility."""
        vol = analyzer.calculate_volatility([])
        assert vol == 0.0


# ===================================================================
# Comparable vehicles
# ===================================================================


class TestComparableVehicles:
    def test_find_comparable_vehicles(self, analyzer: MarketAnalyzer):
        """Matching vehicles sorted by similarity score."""
        target = {
            "maker": "いすゞ",
            "model": "エルフ",
            "year": 2020,
            "mileage": 80_000,
            "body_type": "平ボディ",
        }
        vehicles = [
            {
                "maker": "いすゞ",
                "model": "エルフ",
                "year": 2020,
                "mileage": 85_000,
                "body_type": "平ボディ",
                "price": 3_200_000,
            },
            {
                "maker": "いすゞ",
                "model": "エルフ",
                "year": 2019,
                "mileage": 90_000,
                "body_type": "平ボディ",
                "price": 2_900_000,
            },
            {
                "maker": "日野",
                "model": "デュトロ",
                "year": 2020,
                "mileage": 80_000,
                "body_type": "平ボディ",
                "price": 3_100_000,
            },
        ]

        results = analyzer.find_comparable_vehicles(target, vehicles)
        # Only いすゞ vehicles should match (maker must be exact)
        assert len(results) == 2
        # First result should be the closest match
        assert results[0]["price"] == 3_200_000
        assert "similarity_score" in results[0]

    def test_find_comparable_vehicles_empty(self, analyzer: MarketAnalyzer):
        """Empty candidate pool -> empty result."""
        target = {"maker": "いすゞ", "model": "エルフ", "year": 2020, "mileage": 80_000}
        results = analyzer.find_comparable_vehicles(target, [])
        assert results == []


# ===================================================================
# Deviation rate
# ===================================================================


class TestDeviationRate:
    def test_deviation_rate(self, analyzer: MarketAnalyzer):
        """Deviation = (retail - auction) / retail."""
        deviation = analyzer.calculate_deviation_rate(
            auction_price=3_000_000, retail_price=3_500_000
        )
        expected = round((3_500_000 - 3_000_000) / 3_500_000, 4)
        assert deviation == expected
        assert deviation > 0  # auction < retail -> positive deviation

    def test_deviation_rate_zero_retail(self, analyzer: MarketAnalyzer):
        """Zero retail price -> 0.0 deviation."""
        deviation = analyzer.calculate_deviation_rate(
            auction_price=3_000_000, retail_price=0
        )
        assert deviation == 0.0

    def test_deviation_rate_equal(self, analyzer: MarketAnalyzer):
        """Auction == retail -> zero deviation."""
        deviation = analyzer.calculate_deviation_rate(
            auction_price=3_000_000, retail_price=3_000_000
        )
        assert deviation == 0.0
