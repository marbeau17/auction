"""Tests for the Financial AI Diagnosis Engine.

Covers the ``FinancialAnalyzer`` class which evaluates transport company
financial health, producing a credit grade (A-D), risk assessment, lease
capacity, and advisory recommendations.
"""

from __future__ import annotations

import pytest

from app.core.financial_analyzer import FinancialAnalyzer, FinancialInput


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def analyzer() -> FinancialAnalyzer:
    return FinancialAnalyzer()


@pytest.fixture
def healthy_input() -> FinancialInput:
    """Grade-A company: high revenue, profitable, strong balance sheet."""
    return FinancialInput(
        company_name="優良運輸株式会社",
        revenue=500_000_000,
        operating_profit=40_000_000,
        ordinary_profit=38_000_000,
        total_assets=400_000_000,
        total_liabilities=200_000_000,
        equity=200_000_000,
        current_assets=120_000_000,
        current_liabilities=50_000_000,
        interest_bearing_debt=80_000_000,
        vehicle_count=50,
        vehicle_utilization_rate=0.90,
        existing_lease_monthly=200_000,
    )


@pytest.fixture
def struggling_input() -> FinancialInput:
    """Grade-D company: small, loss-making, overleveraged."""
    return FinancialInput(
        company_name="苦戦運輸株式会社",
        revenue=50_000_000,
        operating_profit=-5_000_000,
        ordinary_profit=-6_000_000,
        total_assets=80_000_000,
        total_liabilities=75_000_000,
        equity=5_000_000,
        current_assets=10_000_000,
        current_liabilities=20_000_000,
        interest_bearing_debt=60_000_000,
        vehicle_count=5,
        vehicle_utilization_rate=0.30,
        existing_lease_monthly=500_000,
    )


@pytest.fixture
def moderate_input() -> FinancialInput:
    """Middle-range company targeting grade B or C."""
    return FinancialInput(
        company_name="普通運輸株式会社",
        revenue=200_000_000,
        operating_profit=8_000_000,
        ordinary_profit=7_000_000,
        total_assets=180_000_000,
        total_liabilities=120_000_000,
        equity=60_000_000,
        current_assets=50_000_000,
        current_liabilities=35_000_000,
        interest_bearing_debt=70_000_000,
        vehicle_count=20,
        vehicle_utilization_rate=0.70,
        existing_lease_monthly=300_000,
    )


@pytest.fixture
def zero_revenue_input() -> FinancialInput:
    """Edge case: zero revenue (startup / dormant company).

    With no revenue the OP-margin score will be minimal, and the
    company has a weak balance sheet to reinforce a low grade.
    """
    return FinancialInput(
        company_name="ゼロ売上株式会社",
        revenue=0,
        operating_profit=0,
        ordinary_profit=0,
        total_assets=10_000_000,
        total_liabilities=9_000_000,
        equity=1_000_000,
        current_assets=2_000_000,
        current_liabilities=5_000_000,
        interest_bearing_debt=8_000_000,
    )


# ===================================================================
# 1. Healthy company -> Grade A
# ===================================================================


class TestHealthyCompany:
    """A financially healthy company should receive grade A."""

    def test_healthy_company_gets_grade_a(
        self, analyzer: FinancialAnalyzer, healthy_input: FinancialInput
    ):
        result = analyzer.analyze(healthy_input)
        assert result.score == "A", (
            f"Expected grade A but got {result.score} "
            f"(numeric={result.score_numeric})"
        )
        assert result.risk_level == "推奨"
        assert result.max_monthly_lease > 0


# ===================================================================
# 2. Struggling company -> Grade D
# ===================================================================


class TestStrugglingCompany:
    """A loss-making, overleveraged company should receive grade D."""

    def test_struggling_company_gets_grade_d(
        self, analyzer: FinancialAnalyzer, struggling_input: FinancialInput
    ):
        result = analyzer.analyze(struggling_input)
        assert result.score == "D", (
            f"Expected grade D but got {result.score} "
            f"(numeric={result.score_numeric})"
        )
        assert result.risk_level == "非推奨"
        # Max lease should be zero or very low given negative EBITDA
        # and large existing obligations.
        assert result.max_monthly_lease == 0 or result.max_monthly_lease < 50_000


# ===================================================================
# 3. Moderate company -> Grade B or C
# ===================================================================


class TestModerateCompany:
    """A company with middle-range indicators should land in B or C."""

    def test_moderate_company_gets_grade_b_or_c(
        self, analyzer: FinancialAnalyzer, moderate_input: FinancialInput
    ):
        result = analyzer.analyze(moderate_input)
        assert result.score in ("B", "C"), (
            f"Expected grade B or C but got {result.score} "
            f"(numeric={result.score_numeric})"
        )
        assert result.risk_level in ("推奨", "要注意")


# ===================================================================
# 4. Existing obligations reduce max lease
# ===================================================================


class TestExistingObligations:
    """Large existing lease payments should reduce the affordable cap."""

    def test_max_lease_respects_existing_obligations(
        self, analyzer: FinancialAnalyzer, healthy_input: FinancialInput
    ):
        # First: baseline with low existing obligations
        result_low = analyzer.analyze(healthy_input)

        # Second: same company but burdened with high existing lease
        heavy_input = FinancialInput(
            company_name=healthy_input.company_name,
            revenue=healthy_input.revenue,
            operating_profit=healthy_input.operating_profit,
            ordinary_profit=healthy_input.ordinary_profit,
            total_assets=healthy_input.total_assets,
            total_liabilities=healthy_input.total_liabilities,
            equity=healthy_input.equity,
            current_assets=healthy_input.current_assets,
            current_liabilities=healthy_input.current_liabilities,
            interest_bearing_debt=healthy_input.interest_bearing_debt,
            vehicle_count=healthy_input.vehicle_count,
            vehicle_utilization_rate=healthy_input.vehicle_utilization_rate,
            existing_lease_monthly=1_500_000,  # much higher
        )
        result_high = analyzer.analyze(heavy_input)

        assert result_high.max_monthly_lease < result_low.max_monthly_lease


# ===================================================================
# 5. Recommended term varies by grade
# ===================================================================


class TestRecommendedTerms:
    """Term ranges should differ by grade."""

    def test_recommended_term_varies_by_grade(
        self,
        analyzer: FinancialAnalyzer,
        healthy_input: FinancialInput,
        struggling_input: FinancialInput,
    ):
        result_a = analyzer.analyze(healthy_input)
        result_d = analyzer.analyze(struggling_input)

        # Grade A: wide band (12-84)
        assert result_a.recommended_lease_term_min == 12
        assert result_a.recommended_lease_term_max == 84

        # Grade D: single point (36-36)
        assert result_d.recommended_lease_term_min == 36
        assert result_d.recommended_lease_term_max == 36


# ===================================================================
# 6. Recommendations generated
# ===================================================================


class TestRecommendations:
    """Advisory notes should trigger on specific financial weaknesses."""

    def test_low_equity_triggers_recommendation(
        self, analyzer: FinancialAnalyzer
    ):
        """Equity ratio < 20% should produce a recommendation about
        自己資本比率."""
        inp = FinancialInput(
            company_name="低自己資本株式会社",
            revenue=100_000_000,
            operating_profit=5_000_000,
            ordinary_profit=4_000_000,
            total_assets=100_000_000,
            total_liabilities=85_000_000,
            equity=15_000_000,           # 15% equity ratio
            current_assets=30_000_000,
            current_liabilities=20_000_000,
            interest_bearing_debt=30_000_000,
        )
        result = analyzer.analyze(inp)
        combined = result.recommendations + result.warnings
        assert any("自己資本比率" in msg for msg in combined), (
            f"Expected 自己資本比率 recommendation, got: {combined}"
        )

    def test_high_debt_triggers_warning(
        self, analyzer: FinancialAnalyzer
    ):
        """High interest-bearing debt ratio should produce a warning
        about 有利子負債."""
        inp = FinancialInput(
            company_name="高負債株式会社",
            revenue=100_000_000,
            operating_profit=5_000_000,
            ordinary_profit=4_000_000,
            total_assets=100_000_000,
            total_liabilities=80_000_000,
            equity=20_000_000,
            current_assets=30_000_000,
            current_liabilities=20_000_000,
            interest_bearing_debt=75_000_000,  # 75% debt ratio
        )
        result = analyzer.analyze(inp)
        combined = result.recommendations + result.warnings
        assert any("有利子負債" in msg for msg in combined), (
            f"Expected 有利子負債 warning, got: {combined}"
        )


# ===================================================================
# 7. Detail scores sum correctly
# ===================================================================


class TestDetailScores:
    """The individual pillar scores must sum to the total numeric score."""

    def test_detail_scores_sum_correctly(
        self, analyzer: FinancialAnalyzer, healthy_input: FinancialInput
    ):
        result = analyzer.analyze(healthy_input)
        assert sum(result.detail_scores.values()) == result.score_numeric

    def test_detail_scores_sum_correctly_struggling(
        self, analyzer: FinancialAnalyzer, struggling_input: FinancialInput
    ):
        result = analyzer.analyze(struggling_input)
        assert sum(result.detail_scores.values()) == result.score_numeric


# ===================================================================
# 8. Zero revenue -> no crash, grade D
# ===================================================================


class TestZeroRevenue:
    """Zero revenue must not cause a division-by-zero error."""

    def test_zero_revenue_no_division_error(
        self, analyzer: FinancialAnalyzer, zero_revenue_input: FinancialInput
    ):
        result = analyzer.analyze(zero_revenue_input)
        # Should not raise; grade should be D given no revenue.
        assert result.score == "D"
        assert result.max_monthly_lease == 0


# ===================================================================
# 9. EBITDA estimation
# ===================================================================


class TestEbitdaEstimation:
    """EBITDA should equal operating_profit + ~8% of total_assets."""

    def test_ebitda_estimation(
        self, analyzer: FinancialAnalyzer, healthy_input: FinancialInput
    ):
        result = analyzer.analyze(healthy_input)
        expected_depreciation = int(
            healthy_input.total_assets * FinancialAnalyzer.DEPRECIATION_RATE
        )
        expected_ebitda = healthy_input.operating_profit + expected_depreciation
        assert result.ebitda == expected_ebitda

    def test_ebitda_with_zero_assets(self, analyzer: FinancialAnalyzer):
        """When total_assets is zero, EBITDA equals operating_profit."""
        inp = FinancialInput(
            company_name="無資産株式会社",
            revenue=50_000_000,
            operating_profit=3_000_000,
            ordinary_profit=2_500_000,
            total_assets=0,
            total_liabilities=0,
            equity=0,
            current_assets=0,
            current_liabilities=0,
        )
        result = analyzer.analyze(inp)
        assert result.ebitda == 3_000_000


# ===================================================================
# 10. Vehicle utilization affects score
# ===================================================================


class TestVehicleUtilization:
    """Higher fleet utilization should yield a better total score."""

    def test_vehicle_utilization_affects_score(
        self, analyzer: FinancialAnalyzer
    ):
        base_kwargs = dict(
            company_name="稼働率テスト株式会社",
            revenue=200_000_000,
            operating_profit=10_000_000,
            ordinary_profit=9_000_000,
            total_assets=180_000_000,
            total_liabilities=100_000_000,
            equity=80_000_000,
            current_assets=60_000_000,
            current_liabilities=40_000_000,
            interest_bearing_debt=50_000_000,
            vehicle_count=30,
        )

        result_low = analyzer.analyze(
            FinancialInput(**base_kwargs, vehicle_utilization_rate=0.20)
        )
        result_high = analyzer.analyze(
            FinancialInput(**base_kwargs, vehicle_utilization_rate=0.95)
        )

        assert result_high.score_numeric > result_low.score_numeric
        assert (
            result_high.detail_scores["車両稼働率"]
            > result_low.detail_scores["車両稼働率"]
        )
