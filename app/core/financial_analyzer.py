"""Financial AI Diagnosis Engine for transport company lease affordability analysis.

Evaluates a transport company's financial health and determines:

1. Lease affordability score (A–D rating)
2. Maximum sustainable monthly lease amount
3. Recommended lease term
4. Risk assessment

All monetary values are in Japanese Yen (JPY).  The module is
self-contained — no external API calls or paid-service dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()


# ====================================================================== #
# Data models
# ====================================================================== #


@dataclass
class FinancialInput:
    """Transport company financial indicators.

    Fields map to standard Japanese financial-statement line items so that
    data can be sourced directly from 決算書 (financial statements) or
    TDB / TSR credit reports.
    """

    company_name: str

    # -- P&L ----------------------------------------------------------
    revenue: int                    # 売上高 (年間, 円)
    operating_profit: int           # 営業利益 (年間, 円)
    ordinary_profit: int            # 経常利益 (年間, 円)

    # -- Balance Sheet ------------------------------------------------
    total_assets: int               # 総資産 (円)
    total_liabilities: int          # 総負債 (円)
    equity: int                     # 自己資本 (円)
    current_assets: int             # 流動資産 (円)
    current_liabilities: int        # 流動負債 (円)
    quick_assets: Optional[int] = None   # 当座資産 (円)

    # -- Debt ---------------------------------------------------------
    interest_bearing_debt: int = 0  # 有利子負債 (円)

    # -- Cash Flow ----------------------------------------------------
    operating_cf: Optional[int] = None   # 営業キャッシュフロー (年間, 円)
    free_cf: Optional[int] = None        # フリーキャッシュフロー (年間, 円)

    # -- Fleet --------------------------------------------------------
    vehicle_count: int = 0               # 保有車両台数
    vehicle_utilization_rate: float = 0.0  # 稼働率 (0–1)

    # -- Existing obligations -----------------------------------------
    existing_lease_monthly: int = 0  # 既存リース・ローン月額合計 (円)
    existing_loan_balance: int = 0   # 既存ローン残高 (円)


@dataclass
class FinancialDiagnosisResult:
    """Result of financial diagnosis.

    Consumers can rely on ``score`` / ``risk_level`` for quick decisions,
    or drill into ``detail_scores`` and ``recommendations`` for the full
    picture.
    """

    # -- Overall grade ------------------------------------------------
    score: str                       # A / B / C / D
    score_numeric: float             # 0–100
    risk_level: str                  # 推奨 / 要注意 / 非推奨

    # -- Affordability ------------------------------------------------
    max_monthly_lease: int           # 耐えうる月額リース料上限 (円)
    recommended_lease_term_min: int  # 推奨リース期間 (最短, 月)
    recommended_lease_term_max: int  # 推奨リース期間 (最長, 月)

    # -- Financial indicators -----------------------------------------
    equity_ratio: float              # 自己資本比率
    current_ratio: float             # 流動比率
    quick_ratio: Optional[float]     # 当座比率
    debt_ratio: float                # 有利子負債比率
    operating_profit_margin: float   # 営業利益率
    ebitda: int                      # EBITDA 推定
    lease_to_revenue_ratio: float    # リース料 / 売上高比率

    # -- Advisory -----------------------------------------------------
    recommendations: list[str] = field(default_factory=list)  # 改善提案
    warnings: list[str] = field(default_factory=list)         # 警告事項
    detail_scores: dict[str, float] = field(default_factory=dict)  # 個別スコア


# ====================================================================== #
# Analyzer
# ====================================================================== #


class FinancialAnalyzer:
    """Analyzes transport company financial health for lease affordability.

    Scoring is built from six weighted pillars (max 100 points):

    ==============================  ====
    Pillar                          Max
    ==============================  ====
    自己資本比率 (Equity ratio)       25
    流動比率 (Current ratio)          15
    営業利益率 (OP margin)            15
    有利子負債比率 (Debt ratio)       15
    キャッシュフロー (CF coverage)    15
    車両稼働率 (Fleet utilisation)    15
    ==============================  ====

    Grade mapping:

    * **A** (≥ 80): 優良 – 長期リース可
    * **B** (≥ 60): 良好 – 標準条件で契約可
    * **C** (≥ 40): 要注意 – 短期・制限付き
    * **D** (< 40): 非推奨 – 契約見送り推奨
    """

    # ------------------------------------------------------------------
    # Scoring thresholds
    # ------------------------------------------------------------------
    #   Each list is ``[(lower_bound, score), ...]`` sorted descending.
    #   The first match (value >= lower_bound) wins.
    EQUITY_RATIO_THRESHOLDS: list[tuple[float, int]] = [
        (0.40, 25), (0.30, 20), (0.20, 15), (0.10, 10), (0.0, 5),
    ]
    CURRENT_RATIO_THRESHOLDS: list[tuple[float, int]] = [
        (2.0, 15), (1.5, 12), (1.2, 9), (1.0, 6), (0.0, 3),
    ]
    OP_MARGIN_THRESHOLDS: list[tuple[float, int]] = [
        (0.08, 15), (0.05, 12), (0.03, 9), (0.01, 6), (-999.0, 3),
    ]
    # Debt ratio: *lower* is better → matched via _score_threshold_inverse.
    DEBT_RATIO_THRESHOLDS: list[tuple[float, int]] = [
        (0.3, 15), (0.5, 12), (0.7, 9), (1.0, 6), (999.0, 3),
    ]

    # ------------------------------------------------------------------
    # Lease affordability caps
    # ------------------------------------------------------------------
    MAX_LEASE_TO_OCF_RATIO: float = 0.30   # 30 % of operating CF (via EBITDA)
    MAX_LEASE_TO_REVENUE_RATIO: float = 0.05  # 5 % of revenue

    # ------------------------------------------------------------------
    # Grade map: ``(min_score, grade)``
    # ------------------------------------------------------------------
    GRADE_MAP: list[tuple[int, str]] = [
        (80, "A"), (60, "B"), (40, "C"), (0, "D"),
    ]

    # ------------------------------------------------------------------
    # Depreciation rate used to approximate EBITDA from OP
    # ------------------------------------------------------------------
    DEPRECIATION_RATE: float = 0.08  # 8 % of total assets

    # ================================================================== #
    # Public API
    # ================================================================== #

    def analyze(self, input_data: FinancialInput) -> FinancialDiagnosisResult:
        """Run a full financial diagnosis.

        Parameters
        ----------
        input_data:
            Populated ``FinancialInput`` with the target company's figures.

        Returns
        -------
        FinancialDiagnosisResult
            Comprehensive diagnosis including grade, affordability cap,
            recommended terms, and advisory notes.

        Raises
        ------
        ValueError
            If critical inputs (``total_assets``, ``revenue``) are negative.
        """
        self._validate(input_data)

        # -- Ratio computation ----------------------------------------
        equity_ratio = self._safe_div(input_data.equity, input_data.total_assets)
        current_ratio = self._safe_div(input_data.current_assets, input_data.current_liabilities)
        quick_ratio: Optional[float] = (
            round(input_data.quick_assets / input_data.current_liabilities, 4)
            if input_data.quick_assets is not None and input_data.current_liabilities
            else None
        )
        debt_ratio = self._safe_div(input_data.interest_bearing_debt, input_data.total_assets)
        op_margin = self._safe_div(input_data.operating_profit, input_data.revenue)

        # -- EBITDA estimate (OP + depreciation approximation) --------
        depreciation_estimate = int(input_data.total_assets * self.DEPRECIATION_RATE)
        ebitda = input_data.operating_profit + depreciation_estimate

        logger.debug(
            "財務指標算出",
            company=input_data.company_name,
            equity_ratio=round(equity_ratio, 4),
            current_ratio=round(current_ratio, 4),
            debt_ratio=round(debt_ratio, 4),
            op_margin=round(op_margin, 4),
            ebitda=ebitda,
        )

        # -- Pillar scores --------------------------------------------
        detail_scores: dict[str, float] = {}

        detail_scores["自己資本比率"] = self._score_threshold(
            equity_ratio, self.EQUITY_RATIO_THRESHOLDS,
        )
        detail_scores["流動比率"] = self._score_threshold(
            current_ratio, self.CURRENT_RATIO_THRESHOLDS,
        )
        detail_scores["営業利益率"] = self._score_threshold(
            op_margin, self.OP_MARGIN_THRESHOLDS,
        )
        detail_scores["有利子負債比率"] = self._score_threshold_inverse(
            debt_ratio, self.DEBT_RATIO_THRESHOLDS,
        )
        detail_scores["キャッシュフロー"] = self._score_cf(input_data)
        detail_scores["車両稼働率"] = self._score_fleet(input_data)

        total_score = sum(detail_scores.values())

        # -- Grade & risk label ---------------------------------------
        grade = self._grade_from_score(total_score)
        risk_level = self._risk_label(grade)

        # -- Maximum affordable monthly lease -------------------------
        max_monthly = self._calc_max_monthly_lease(input_data, ebitda)

        # -- Recommended lease term -----------------------------------
        term_min, term_max = self._recommended_term(grade)

        # -- Lease-to-revenue ratio (existing obligations only) -------
        lease_to_rev = (
            self._safe_div(input_data.existing_lease_monthly * 12, input_data.revenue)
        )

        # -- Advisory notes -------------------------------------------
        recommendations, warnings = self._build_advisory(
            input_data, equity_ratio, current_ratio, debt_ratio,
            op_margin, max_monthly, grade,
        )

        logger.info(
            "財務診断完了",
            company=input_data.company_name,
            score=total_score,
            grade=grade,
            risk=risk_level,
            max_monthly_lease=max_monthly,
        )

        return FinancialDiagnosisResult(
            score=grade,
            score_numeric=total_score,
            risk_level=risk_level,
            max_monthly_lease=max_monthly,
            recommended_lease_term_min=term_min,
            recommended_lease_term_max=term_max,
            equity_ratio=round(equity_ratio, 4),
            current_ratio=round(current_ratio, 4),
            quick_ratio=quick_ratio,
            debt_ratio=round(debt_ratio, 4),
            operating_profit_margin=round(op_margin, 4),
            ebitda=ebitda,
            lease_to_revenue_ratio=round(lease_to_rev, 4),
            recommendations=recommendations,
            warnings=warnings,
            detail_scores=detail_scores,
        )

    # ================================================================== #
    # Internal helpers – scoring
    # ================================================================== #

    @staticmethod
    def _score_threshold(value: float, thresholds: list[tuple[float, int]]) -> int:
        """Return the score for the first threshold whose lower bound is met.

        ``thresholds`` must be sorted descending by the bound value.
        """
        for bound, score in thresholds:
            if value >= bound:
                return score
        return thresholds[-1][1]

    @staticmethod
    def _score_threshold_inverse(value: float, thresholds: list[tuple[float, int]]) -> int:
        """Like ``_score_threshold`` but for metrics where *lower* is better.

        Matches the first threshold whose upper bound is **not exceeded**.
        """
        for bound, score in thresholds:
            if value <= bound:
                return score
        return thresholds[-1][1]

    @staticmethod
    def _score_cf(input_data: FinancialInput) -> int:
        """Cash-flow pillar score (max 15).

        Uses operating-CF-to-debt coverage when available; otherwise
        returns a neutral score.
        """
        if input_data.operating_cf is not None and input_data.interest_bearing_debt > 0:
            cf_to_debt = input_data.operating_cf / input_data.interest_bearing_debt
            return min(15, max(3, int(cf_to_debt * 7.5)))
        if input_data.operating_cf is not None and input_data.operating_cf > 0:
            return 12  # CF positive but no debt → favourable
        return 8  # data unavailable → neutral

    @staticmethod
    def _score_fleet(input_data: FinancialInput) -> int:
        """Fleet-utilisation pillar score (max 15).

        If utilisation data is not provided, returns a neutral score.
        """
        rate = input_data.vehicle_utilization_rate
        if rate > 0:
            return min(15, max(3, int(rate * 15)))
        return 8  # neutral

    # ================================================================== #
    # Internal helpers – grading
    # ================================================================== #

    def _grade_from_score(self, total: float) -> str:
        """Map numeric total to a letter grade."""
        for threshold, grade in self.GRADE_MAP:
            if total >= threshold:
                return grade
        return "D"

    @staticmethod
    def _risk_label(grade: str) -> str:
        """Human-readable risk label for the grade."""
        if grade in ("A", "B"):
            return "推奨"
        if grade == "C":
            return "要注意"
        return "非推奨"

    # ================================================================== #
    # Internal helpers – affordability
    # ================================================================== #

    def _calc_max_monthly_lease(
        self,
        input_data: FinancialInput,
        ebitda: int,
    ) -> int:
        """Determine the maximum monthly lease the company can sustain.

        Takes the lower of two caps (EBITDA-based and revenue-based) and
        subtracts existing lease/loan obligations.
        """
        max_from_ebitda = (
            int(ebitda * self.MAX_LEASE_TO_OCF_RATIO / 12) if ebitda > 0 else 0
        )
        max_from_revenue = int(input_data.revenue * self.MAX_LEASE_TO_REVENUE_RATIO / 12)

        cap = min(max_from_ebitda, max_from_revenue)
        net = cap - input_data.existing_lease_monthly
        return max(0, net)

    @staticmethod
    def _recommended_term(grade: str) -> tuple[int, int]:
        """Return ``(min_months, max_months)`` recommendation by grade."""
        terms: dict[str, tuple[int, int]] = {
            "A": (12, 84),
            "B": (24, 60),
            "C": (36, 48),
            "D": (36, 36),
        }
        return terms.get(grade, (36, 36))

    # ================================================================== #
    # Internal helpers – advisory
    # ================================================================== #

    @staticmethod
    def _build_advisory(
        input_data: FinancialInput,
        equity_ratio: float,
        current_ratio: float,
        debt_ratio: float,
        op_margin: float,
        max_monthly: int,
        grade: str,
    ) -> tuple[list[str], list[str]]:
        """Generate recommendation and warning lists."""
        recommendations: list[str] = []
        warnings: list[str] = []

        if equity_ratio < 0.20:
            recommendations.append(
                "自己資本比率が20%未満です。増資または内部留保の積み増しを推奨します"
            )
        if current_ratio < 1.2:
            recommendations.append(
                "流動比率が120%未満です。短期的な支払い能力に注意が必要です"
            )
        if debt_ratio > 0.7:
            warnings.append(
                "有利子負債比率が70%を超えています。追加借入は慎重に判断してください"
            )
        if op_margin < 0.03:
            warnings.append(
                "営業利益率が3%未満です。リース料負担が経営を圧迫する可能性があります"
            )

        util = input_data.vehicle_utilization_rate
        if 0 < util < 0.7:
            recommendations.append(
                "車両稼働率が70%未満です。既存車両の活用最適化を優先することを推奨します"
            )

        if input_data.existing_lease_monthly > max_monthly * 0.5 and max_monthly > 0:
            warnings.append(
                "既存リース・ローン負担が大きいため、追加リースの余地が限られています"
            )

        # Grade-specific notes
        if grade == "A":
            recommendations.append(
                "財務状態は良好です。長期リースも含め、柔軟な条件設定が可能です"
            )
        elif grade == "D":
            warnings.append(
                "現時点でのリースバック契約は推奨されません。"
                "財務体質の改善を優先してください"
            )

        return recommendations, warnings

    # ================================================================== #
    # Internal helpers – utilities
    # ================================================================== #

    @staticmethod
    def _safe_div(numerator: int | float, denominator: int | float) -> float:
        """Return ``numerator / denominator``, or ``0.0`` when denominator is zero."""
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def _validate(input_data: FinancialInput) -> None:
        """Raise ``ValueError`` on clearly invalid inputs."""
        if input_data.total_assets < 0:
            raise ValueError(
                f"total_assets must be >= 0, got {input_data.total_assets}"
            )
        if input_data.revenue < 0:
            raise ValueError(
                f"revenue must be >= 0, got {input_data.revenue}"
            )
