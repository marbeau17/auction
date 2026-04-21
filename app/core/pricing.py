"""Core pricing calculation engine for commercial vehicle leaseback optimization.

This module implements the full pricing pipeline: market price estimation,
residual value projection, lease payment structuring, and deal assessment.
All monetary values are in Japanese Yen (JPY) unless otherwise noted.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import datetime
from typing import Any, Optional

import numpy as np
import structlog
from supabase import Client

from app.models.simulation import (
    MonthlyScheduleItem,
    SimulationInput,
    SimulationResult,
)

logger = structlog.get_logger()


# Tiny variant table for common Japanese maker name spellings — kept small
# on purpose. Both directions are stored so a query containing either form
# can match a stored row containing the other.
_MAKER_VARIANTS: dict[str, list[str]] = {
    "いすゞ": ["いすず"],
    "いすず": ["いすゞ"],
    "日産自動車": ["日産"],
    "日産": ["日産自動車"],
    "三菱ふそう": ["ふそう"],
    "ふそう": ["三菱ふそう"],
}


def normalize_maker(name: str) -> list[str]:
    """Return the NFKC-normalized maker name plus any known spelling variants."""
    if not name:
        return []
    canonical = unicodedata.normalize("NFKC", name).strip()
    if not canonical:
        return []
    out = [canonical]
    for variant in _MAKER_VARIANTS.get(canonical, []):
        if variant not in out:
            out.append(variant)
    return out


class PricingEngine:
    """Core pricing calculation engine for leaseback optimization.

    Orchestrates market-price weighting, depreciation modelling, lease-payment
    structuring, and profitability assessment for commercial vehicle leaseback
    deals.
    """

    # ------------------------------------------------------------------
    # Default parameters (can be overridden per simulation)
    # ------------------------------------------------------------------
    DEFAULT_PARAMS: dict[str, Any] = {
        # Market price weighting
        "auction_weight": 0.70,
        "elevated_auction_weight": 0.85,
        "acceptable_deviation_threshold": 0.15,
        # Safety margin
        "base_safety_margin": 0.05,
        "volatility_premium": 1.5,
        "min_safety_margin": 0.03,
        "max_safety_margin": 0.20,
        # Trend factor clamps
        "trend_floor": 0.80,
        "trend_ceiling": 1.20,
        # Financing / cost rates (annual)
        "fund_cost_rate": 0.020,
        "credit_spread": 0.015,
        "liquidity_premium": 0.005,
        # Management & admin
        "monthly_management_fee_rate": 0.002,
        "fixed_monthly_admin_cost": 5000,
        # Profit
        "profit_margin_rate": 0.08,
        "target_annual_roi": 0.08,
        # Mileage adjustment
        "over_mileage_penalty_rate": 0.30,
        "under_mileage_bonus_rate": 0.15,
        "mileage_adj_floor": 0.70,
        "mileage_adj_ceiling": 1.10,
        # Early termination / forced sale
        "early_termination_penalty_months": 3,
        "forced_sale_discount": 0.85,
    }

    # ------------------------------------------------------------------
    # Category-level constants
    # ------------------------------------------------------------------
    SAFETY_MARGINS_BY_CATEGORY: dict[str, float] = {
        "SMALL": 0.05,
        "MEDIUM": 0.05,
        "LARGE": 0.07,
        "TRAILER_HEAD": 0.08,
        "TRAILER_CHASSIS": 0.06,
    }

    ANNUAL_STANDARD_MILEAGE: dict[str, int] = {
        "SMALL": 30000,
        "MEDIUM": 50000,
        "LARGE": 80000,
        "TRAILER_HEAD": 100000,
    }

    USEFUL_LIFE: dict[str, int] = {
        "SMALL": 7,
        "MEDIUM": 9,
        "LARGE": 10,
        "TRAILER_HEAD": 10,
        "TRAILER_CHASSIS": 12,
    }

    SALVAGE_RATIO: dict[str, float] = {
        "SMALL": 0.10,
        "MEDIUM": 0.08,
        "LARGE": 0.07,
        "TRAILER_HEAD": 0.06,
        "TRAILER_CHASSIS": 0.05,
    }

    # ------------------------------------------------------------------
    # Body depreciation tables
    # Key = body type code, Value = list of (elapsed_years, factor) tuples
    # sorted ascending by elapsed_years.  factor = 1.0 means no extra
    # depreciation beyond chassis depreciation.
    # ------------------------------------------------------------------
    BODY_DEPRECIATION_TABLES: dict[str, list[tuple[float, float]]] = {
        "FLAT": [
            (0, 1.00), (1, 0.95), (2, 0.90), (3, 0.85),
            (4, 0.80), (5, 0.75), (6, 0.70), (7, 0.65),
            (8, 0.60), (9, 0.55), (10, 0.50), (12, 0.40),
            (15, 0.30),
        ],
        "VAN": [
            (0, 1.00), (1, 0.93), (2, 0.86), (3, 0.80),
            (4, 0.74), (5, 0.68), (6, 0.62), (7, 0.56),
            (8, 0.51), (9, 0.46), (10, 0.42), (12, 0.34),
            (15, 0.25),
        ],
        "WING": [
            (0, 1.00), (1, 0.92), (2, 0.85), (3, 0.78),
            (4, 0.72), (5, 0.66), (6, 0.60), (7, 0.55),
            (8, 0.50), (9, 0.45), (10, 0.40), (12, 0.32),
            (15, 0.22),
        ],
        "REFR": [
            (0, 1.00), (1, 0.90), (2, 0.82), (3, 0.74),
            (4, 0.67), (5, 0.60), (6, 0.54), (7, 0.48),
            (8, 0.43), (9, 0.38), (10, 0.34), (12, 0.26),
            (15, 0.18),
        ],
        "DUMP": [
            (0, 1.00), (1, 0.94), (2, 0.88), (3, 0.82),
            (4, 0.76), (5, 0.71), (6, 0.66), (7, 0.61),
            (8, 0.56), (9, 0.52), (10, 0.48), (12, 0.40),
            (15, 0.30),
        ],
        "CRAN": [
            (0, 1.00), (1, 0.92), (2, 0.84), (3, 0.77),
            (4, 0.70), (5, 0.64), (6, 0.58), (7, 0.52),
            (8, 0.47), (9, 0.42), (10, 0.38), (12, 0.30),
            (15, 0.20),
        ],
        "TAIL_LIFT": [
            (0, 1.00), (1, 0.91), (2, 0.83), (3, 0.75),
            (4, 0.68), (5, 0.62), (6, 0.56), (7, 0.50),
            (8, 0.45), (9, 0.40), (10, 0.36), (12, 0.28),
            (15, 0.19),
        ],
        "MIXER": [
            (0, 1.00), (1, 0.90), (2, 0.81), (3, 0.73),
            (4, 0.66), (5, 0.59), (6, 0.53), (7, 0.47),
            (8, 0.42), (9, 0.37), (10, 0.33), (12, 0.25),
            (15, 0.17),
        ],
        "TANK": [
            (0, 1.00), (1, 0.91), (2, 0.83), (3, 0.76),
            (4, 0.69), (5, 0.63), (6, 0.57), (7, 0.51),
            (8, 0.46), (9, 0.41), (10, 0.37), (12, 0.29),
            (15, 0.20),
        ],
        "GARBAGE": [
            (0, 1.00), (1, 0.89), (2, 0.79), (3, 0.70),
            (4, 0.62), (5, 0.55), (6, 0.48), (7, 0.42),
            (8, 0.37), (9, 0.32), (10, 0.28), (12, 0.21),
            (15, 0.14),
        ],
    }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _median(values: list[float]) -> float:
        """Return the median of *values* using numpy."""
        return float(np.median(values))

    @staticmethod
    def _std(values: list[float]) -> float:
        """Return the population standard deviation of *values*."""
        return float(np.std(values))

    def _merge_params(self, overrides: dict | None) -> dict:
        """Merge caller-supplied overrides on top of DEFAULT_PARAMS."""
        params = dict(self.DEFAULT_PARAMS)
        if overrides:
            params.update(overrides)
        return params

    # ------------------------------------------------------------------
    # 1.  Main entry point
    # ------------------------------------------------------------------
    def calculate(
        self,
        input_data: dict,
        market_data: list[dict] | None = None,
        params: dict | None = None,
    ) -> dict:
        """Run a full leaseback simulation and return a SimulationResult dict.

        Parameters
        ----------
        input_data : dict
            Fields matching ``SimulationInput``.  Required keys include
            ``lease_term_months``, ``mileage_km``, ``target_yield_rate``,
            ``body_type``, ``registration_year_month``, and either a
            ``vehicle_class`` or a derived ``category``.
        market_data : list[dict] | None
            List of comparable-vehicle market records.  Each dict should
            carry at least ``price_yen`` and optionally ``source_site``
            (used to separate auction vs. retail).
        params : dict | None
            Optional parameter overrides (keys from ``DEFAULT_PARAMS``).

        Returns
        -------
        dict
            A dict whose keys match ``SimulationResult``.
        """
        p = self._merge_params(params)

        # --- Derive category from vehicle_class ---
        category = self._resolve_category(input_data)
        body_type = self._resolve_body_type(input_data.get("body_type", "FLAT"))
        lease_term = int(input_data["lease_term_months"])
        mileage_km = int(input_data["mileage_km"])
        target_yield = float(
            input_data.get("target_yield_rate", p["target_annual_roi"])
        )

        # --- Parse registration date to compute vehicle age ---
        reg_ym = str(input_data.get("registration_year_month", ""))
        if reg_ym:
            # Handle both "2024" (year-only) and "2024-01" (year-month) formats
            if "-" in reg_ym:
                reg_year, reg_month = (int(x) for x in reg_ym.split("-"))
            else:
                reg_year = int(reg_ym) if reg_ym.isdigit() else 2020
                reg_month = 1
            now = datetime.now()
            elapsed_months_at_start = (
                (now.year - reg_year) * 12 + (now.month - reg_month)
            )
        else:
            elapsed_months_at_start = 0

        # --- Market price analysis ---
        auction_prices: list[float] = []
        retail_prices: list[float] = []

        if market_data:
            for rec in market_data:
                price = rec.get("price_yen")
                if price is None or price <= 0:
                    continue
                source = str(rec.get("source_site", "")).lower()
                if "auction" in source:
                    auction_prices.append(float(price))
                else:
                    retail_prices.append(float(price))

        # Fall back: if no market data, use acquisition_price as a proxy
        if not auction_prices and not retail_prices:
            proxy = float(input_data.get("acquisition_price", 0))
            if proxy > 0:
                auction_prices = [proxy]
                retail_prices = [proxy]

        base_market_price = self.calculate_base_market_price(
            auction_prices, retail_prices, p
        )

        all_prices = auction_prices + retail_prices
        sample_count = len(all_prices)

        # --- Trend factor ---
        mid = max(1, len(all_prices) // 2)
        recent_prices = all_prices[-mid:] if all_prices else [base_market_price]
        baseline_prices = all_prices[:mid] if all_prices else [base_market_price]
        trend_factor = self.calculate_trend_factor(
            recent_prices, baseline_prices, p
        )

        # --- Safety margin ---
        safety_margin_rate = self.calculate_safety_margin(all_prices, category, p)

        # --- Condition factor (simplified: 1.0 = average) ---
        condition_factor = 1.0

        # --- Max purchase price ---
        max_purchase_price = self.calculate_max_purchase_price(
            base_market_price, condition_factor, trend_factor, safety_margin_rate
        )

        # --- Recommended purchase price (use book_value cap if available) ---
        book_value = float(input_data.get("book_value", 0))
        recommended_purchase_price = (
            min(max_purchase_price, book_value)
            if book_value > 0
            else max_purchase_price
        )

        # --- Residual value at lease end ---
        elapsed_at_end = elapsed_months_at_start + lease_term
        residual_value = self.calculate_residual_value(
            recommended_purchase_price,
            elapsed_at_end,
            category,
            body_type,
            mileage_km,
            method="straight_line",
            params=p,
        )

        # Honour explicit residual_rate override
        residual_rate_input = input_data.get("residual_rate")
        if residual_rate_input is not None:
            residual_value = recommended_purchase_price * float(residual_rate_input)

        residual_rate_result = (
            residual_value / recommended_purchase_price
            if recommended_purchase_price > 0
            else 0.0
        )

        # --- Monthly lease payment ---
        payment_detail = self.calculate_monthly_lease_payment(
            recommended_purchase_price, residual_value, lease_term, p
        )
        monthly_lease_fee = payment_detail["total"]
        total_lease_fee = monthly_lease_fee * lease_term

        # --- Monthly schedule ---
        schedule = self.calculate_monthly_schedule(
            recommended_purchase_price,
            monthly_lease_fee,
            lease_term,
            category,
            body_type,
            mileage_km,
            p,
        )

        # --- Breakeven ---
        asset_values = [item["asset_value"] for item in schedule]
        breakeven = self.calculate_breakeven_month(
            recommended_purchase_price, monthly_lease_fee, asset_values
        )

        # --- Effective yield ---
        total_income = monthly_lease_fee * lease_term
        total_cost = recommended_purchase_price - residual_value
        if recommended_purchase_price > 0 and lease_term > 0:
            effective_yield = (
                (total_income - total_cost) / recommended_purchase_price
            ) / (lease_term / 12)
        else:
            effective_yield = 0.0

        # --- Deviation from market ---
        deviation_rate = (
            (recommended_purchase_price - base_market_price) / base_market_price
            if base_market_price > 0
            else 0.0
        )

        # --- Assessment ---
        assessment = self.determine_assessment(
            effective_yield, breakeven, lease_term
        )

        return {
            "max_purchase_price": int(round(max_purchase_price)),
            "recommended_purchase_price": int(round(recommended_purchase_price)),
            "estimated_residual_value": int(round(residual_value)),
            "residual_rate_result": round(residual_rate_result, 4),
            "monthly_lease_fee": int(round(monthly_lease_fee)),
            "total_lease_fee": int(round(total_lease_fee)),
            "breakeven_months": breakeven,
            "effective_yield_rate": round(effective_yield, 4),
            "market_median_price": int(round(base_market_price)),
            "market_sample_count": sample_count,
            "market_deviation_rate": round(deviation_rate, 4),
            "assessment": assessment,
            "monthly_schedule": schedule,
        }

    # ------------------------------------------------------------------
    # 2.  Base market price
    # ------------------------------------------------------------------
    def calculate_base_market_price(
        self,
        auction_prices: list[float],
        retail_prices: list[float],
        params: dict,
    ) -> float:
        """Calculate the base market price from auction and retail samples.

        Uses a weighted average of the auction median and the retail median.
        If the deviation between the two exceeds the acceptable threshold the
        auction weight is elevated (because auction prices are considered more
        reliable for wholesale / leaseback purposes).

        Parameters
        ----------
        auction_prices : list[float]
            Observed auction transaction prices.
        retail_prices : list[float]
            Observed retail listing prices.
        params : dict
            Merged parameter dict.

        Returns
        -------
        float
            Weighted base market price.
        """
        if not auction_prices and not retail_prices:
            return 0.0

        if not auction_prices:
            return self._median(retail_prices)
        if not retail_prices:
            return self._median(auction_prices)

        auction_median = self._median(auction_prices)
        retail_median = self._median(retail_prices)

        # Deviation between the two medians
        mean_of_medians = (auction_median + retail_median) / 2
        deviation = (
            abs(auction_median - retail_median) / mean_of_medians
            if mean_of_medians > 0
            else 0.0
        )

        threshold = params.get("acceptable_deviation_threshold", 0.15)

        if deviation > threshold:
            w = params.get("elevated_auction_weight", 0.85)
        else:
            w = params.get("auction_weight", 0.70)

        return w * auction_median + (1 - w) * retail_median

    # ------------------------------------------------------------------
    # 3.  Max purchase price
    # ------------------------------------------------------------------
    def calculate_max_purchase_price(
        self,
        base_market_price: float,
        condition_factor: float,
        trend_factor: float,
        safety_margin_rate: float,
    ) -> float:
        """Derive the maximum allowable purchase price.

        Formula::

            max_price = base_market_price
                        * condition_factor
                        * trend_factor
                        * (1 - safety_margin_rate)

        Parameters
        ----------
        base_market_price : float
        condition_factor : float
            Vehicle condition multiplier (1.0 = average).
        trend_factor : float
            Market trend multiplier (>1 = appreciating).
        safety_margin_rate : float
            Safety-margin discount rate.

        Returns
        -------
        float
            Maximum purchase price in yen.
        """
        return (
            base_market_price
            * condition_factor
            * trend_factor
            * (1.0 - safety_margin_rate)
        )

    # ------------------------------------------------------------------
    # 4.  Trend factor
    # ------------------------------------------------------------------
    def calculate_trend_factor(
        self,
        recent_prices: list[float],
        baseline_prices: list[float],
        params: dict,
    ) -> float:
        """Calculate a market-trend multiplier.

        The factor is the ratio of the recent median to the baseline median,
        clamped between ``trend_floor`` and ``trend_ceiling``.

        Parameters
        ----------
        recent_prices : list[float]
            Prices from the more-recent observation window.
        baseline_prices : list[float]
            Prices from the earlier observation window.
        params : dict
            Merged parameter dict.

        Returns
        -------
        float
            Clamped trend factor.
        """
        if not recent_prices or not baseline_prices:
            return 1.0

        recent_median = self._median(recent_prices)
        baseline_median = self._median(baseline_prices)

        if baseline_median <= 0:
            return 1.0

        raw_factor = recent_median / baseline_median

        floor = params.get("trend_floor", 0.80)
        ceiling = params.get("trend_ceiling", 1.20)
        return max(floor, min(ceiling, raw_factor))

    # ------------------------------------------------------------------
    # 5.  Safety margin
    # ------------------------------------------------------------------
    def calculate_safety_margin(
        self,
        prices: list[float],
        category: str,
        params: dict,
    ) -> float:
        """Calculate a volatility-based dynamic safety margin.

        Formula::

            cv = std(prices) / mean(prices)          (coefficient of variation)
            dynamic = base_safety + cv * volatility_premium
            margin  = clamp(dynamic, min_safety, max_safety)

        If there are fewer than two price observations the category-level
        default from ``SAFETY_MARGINS_BY_CATEGORY`` is returned instead.

        Parameters
        ----------
        prices : list[float]
            All observed prices.
        category : str
            Vehicle category code (e.g. ``"SMALL"``).
        params : dict
            Merged parameter dict.

        Returns
        -------
        float
            Safety margin rate (0-1).
        """
        category_default = self.SAFETY_MARGINS_BY_CATEGORY.get(
            category, params.get("base_safety_margin", 0.05)
        )

        if len(prices) < 2:
            return category_default

        mean_price = float(np.mean(prices))
        if mean_price <= 0:
            return category_default

        cv = self._std(prices) / mean_price
        base = params.get("base_safety_margin", 0.05)
        premium = params.get("volatility_premium", 1.5)

        dynamic = base + cv * premium

        lo = params.get("min_safety_margin", 0.03)
        hi = params.get("max_safety_margin", 0.20)
        return max(lo, min(hi, dynamic))

    # ------------------------------------------------------------------
    # 6.  Residual value
    # ------------------------------------------------------------------
    def calculate_residual_value(
        self,
        purchase_price: float,
        elapsed_months: int,
        category: str,
        body_type: str,
        actual_mileage: int,
        method: str = "straight_line",
        params: dict | None = None,
    ) -> float:
        """Project the residual (asset) value of a vehicle.

        Supports two depreciation methods:

        * **straight_line** -- linear depreciation from purchase price down
          to salvage value over the useful life.
        * **declining_balance** -- double-declining-balance method with the
          same useful life and salvage floor.

        A body-type depreciation factor and a mileage adjustment are applied
        on top of the chassis depreciation.

        Parameters
        ----------
        purchase_price : float
        elapsed_months : int
            Total months since first registration (not since lease start).
        category : str
            Vehicle category code.
        body_type : str
            Body type code (key in ``BODY_DEPRECIATION_TABLES``).
        actual_mileage : int
            Odometer reading (km).
        method : str
            ``"straight_line"`` or ``"declining_balance"``.
        params : dict | None
            Optional parameter overrides.

        Returns
        -------
        float
            Projected residual value in yen (floored at zero).
        """
        p = self._merge_params(params)
        useful_life_years = self.USEFUL_LIFE.get(category, 10)
        salvage_ratio = self.SALVAGE_RATIO.get(category, 0.05)
        salvage_value = purchase_price * salvage_ratio

        elapsed_years = elapsed_months / 12.0
        total_months = useful_life_years * 12

        # --- Chassis depreciation ---
        if method == "declining_balance":
            # Double-declining-balance
            rate = 2.0 / useful_life_years  # annual rate
            chassis_value = purchase_price * ((1 - rate) ** elapsed_years)
            chassis_value = max(chassis_value, salvage_value)
        else:
            # Straight-line
            if total_months > 0:
                monthly_dep = (purchase_price - salvage_value) / total_months
                chassis_value = purchase_price - monthly_dep * elapsed_months
            else:
                chassis_value = purchase_price
            chassis_value = max(chassis_value, salvage_value)

        # --- Body depreciation factor ---
        body_factor = self.calculate_body_depreciation_factor(
            body_type, elapsed_years
        )

        # --- Mileage adjustment ---
        mileage_adj = self.calculate_mileage_adjustment(
            actual_mileage, elapsed_years, category, p
        )

        residual = chassis_value * body_factor * mileage_adj
        return max(residual, 0.0)

    # ------------------------------------------------------------------
    # 7.  Body depreciation factor
    # ------------------------------------------------------------------
    def calculate_body_depreciation_factor(
        self,
        body_type: str,
        elapsed_years: float,
    ) -> float:
        """Look up and linearly interpolate the body depreciation factor.

        If ``body_type`` is not found in ``BODY_DEPRECIATION_TABLES`` a
        factor of 1.0 (no extra depreciation) is returned.

        Parameters
        ----------
        body_type : str
            Body type code.
        elapsed_years : float
            Vehicle age in (fractional) years.

        Returns
        -------
        float
            Body depreciation factor in (0, 1].
        """
        table = self.BODY_DEPRECIATION_TABLES.get(body_type)
        if not table:
            return 1.0

        # Clamp to table range
        if elapsed_years <= table[0][0]:
            return table[0][1]
        if elapsed_years >= table[-1][0]:
            return table[-1][1]

        # Find bracketing entries and interpolate
        for i in range(len(table) - 1):
            y0, f0 = table[i]
            y1, f1 = table[i + 1]
            if y0 <= elapsed_years <= y1:
                t = (elapsed_years - y0) / (y1 - y0) if y1 != y0 else 0.0
                return f0 + t * (f1 - f0)

        return table[-1][1]

    # ------------------------------------------------------------------
    # 8.  Mileage adjustment
    # ------------------------------------------------------------------
    def calculate_mileage_adjustment(
        self,
        actual_mileage: int,
        elapsed_years: float,
        category: str,
        params: dict,
    ) -> float:
        """Calculate a mileage-based residual-value adjustment factor.

        * Over-mileage vehicles are penalised (factor < 1.0).
        * Under-mileage vehicles receive a modest bonus (factor > 1.0,
          capped at ``mileage_adj_ceiling``).
        * The result is clamped between ``mileage_adj_floor`` and
          ``mileage_adj_ceiling``.

        Parameters
        ----------
        actual_mileage : int
            Odometer reading (km).
        elapsed_years : float
            Vehicle age in years.
        category : str
            Vehicle category code.
        params : dict
            Merged parameter dict.

        Returns
        -------
        float
            Mileage adjustment multiplier.
        """
        annual_standard = self.ANNUAL_STANDARD_MILEAGE.get(category, 50000)

        if elapsed_years <= 0:
            return 1.0

        expected_mileage = annual_standard * elapsed_years

        if expected_mileage <= 0:
            return 1.0

        mileage_ratio = actual_mileage / expected_mileage
        deviation = mileage_ratio - 1.0

        if deviation > 0:
            # Over-mileage: penalise
            penalty_rate = params.get("over_mileage_penalty_rate", 0.30)
            factor = 1.0 - deviation * penalty_rate
        else:
            # Under-mileage: bonus
            bonus_rate = params.get("under_mileage_bonus_rate", 0.15)
            # deviation is negative so subtracting it adds a bonus
            factor = 1.0 - deviation * bonus_rate

        floor = params.get("mileage_adj_floor", 0.70)
        ceiling = params.get("mileage_adj_ceiling", 1.10)
        return max(floor, min(ceiling, factor))

    # ------------------------------------------------------------------
    # 9.  Monthly lease payment
    # ------------------------------------------------------------------
    def calculate_monthly_lease_payment(
        self,
        purchase_price: float,
        residual_value: float,
        lease_term_months: int,
        params: dict,
    ) -> dict:
        """Structure the monthly lease payment into its component parts.

        Components:

        * **principal_recovery** -- straight-line recovery of
          ``(purchase_price - residual_value)`` over the lease term.
        * **interest_charge** -- monthly interest on the average outstanding
          balance.  The annual interest rate is the sum of ``fund_cost_rate``,
          ``credit_spread``, and ``liquidity_premium``.
        * **management_fee** -- ``purchase_price * monthly_management_fee_rate``
          plus a fixed admin cost.
        * **profit_margin** -- ``profit_margin_rate`` applied to the sum of the
          above three components.

        Parameters
        ----------
        purchase_price : float
        residual_value : float
        lease_term_months : int
        params : dict

        Returns
        -------
        dict
            Keys: ``principal_recovery``, ``interest_charge``,
            ``management_fee``, ``profit_margin``, ``total``.
        """
        if lease_term_months <= 0:
            return {
                "principal_recovery": 0.0,
                "interest_charge": 0.0,
                "management_fee": 0.0,
                "profit_margin": 0.0,
                "total": 0.0,
            }

        # Principal recovery (straight-line)
        principal_recovery = (purchase_price - residual_value) / lease_term_months

        # Interest charge (average balance method)
        annual_rate = (
            params.get("fund_cost_rate", 0.020)
            + params.get("credit_spread", 0.015)
            + params.get("liquidity_premium", 0.005)
        )
        average_balance = (purchase_price + residual_value) / 2.0
        interest_charge = average_balance * annual_rate / 12.0

        # Management fee
        mgmt_rate = params.get("monthly_management_fee_rate", 0.002)
        fixed_admin = params.get("fixed_monthly_admin_cost", 5000)
        management_fee = purchase_price * mgmt_rate + fixed_admin

        # Profit margin on the above
        subtotal = principal_recovery + interest_charge + management_fee
        profit_margin_rate = params.get("profit_margin_rate", 0.08)
        profit_margin = subtotal * profit_margin_rate

        total = subtotal + profit_margin

        return {
            "principal_recovery": round(principal_recovery, 2),
            "interest_charge": round(interest_charge, 2),
            "management_fee": round(management_fee, 2),
            "profit_margin": round(profit_margin, 2),
            "total": round(total, 2),
        }

    # ------------------------------------------------------------------
    # 10. Calculate from target yield (PMT-equivalent)
    # ------------------------------------------------------------------
    def calculate_from_target_yield(
        self,
        purchase_price: float,
        residual_value: float,
        lease_term_months: int,
        target_yield: float,
    ) -> float:
        """Derive the monthly lease payment required to achieve a target yield.

        This is a PMT-equivalent calculation.  The monthly rate is derived
        from ``target_yield`` (annual), and the payment amortises the net
        investment ``(purchase_price - residual_value_pv)`` where the
        residual's present value is discounted back at the same rate.

        Formula (annuity PMT)::

            r = target_yield / 12
            PV_residual = residual_value / (1 + r)^n
            net = purchase_price - PV_residual
            PMT = net * r / (1 - (1 + r)^-n)

        Parameters
        ----------
        purchase_price : float
        residual_value : float
        lease_term_months : int
        target_yield : float
            Target annual yield (e.g. 0.08 for 8 %).

        Returns
        -------
        float
            Required monthly payment.
        """
        if lease_term_months <= 0 or purchase_price <= 0:
            return 0.0

        r = target_yield / 12.0
        n = lease_term_months

        if r == 0:
            # Zero-rate edge case: simple division
            return (purchase_price - residual_value) / n

        pv_residual = residual_value / ((1 + r) ** n)
        net = purchase_price - pv_residual

        pmt = net * r / (1.0 - (1.0 + r) ** (-n))
        return round(pmt, 2)

    # ------------------------------------------------------------------
    # 11. Breakeven month
    # ------------------------------------------------------------------
    def calculate_breakeven_month(
        self,
        purchase_price: float,
        monthly_payment: float,
        asset_values: list[float],
    ) -> int | None:
        """Determine the first month at which cumulative income covers the
        gap between the purchase price and the (depreciating) asset value.

        Breakeven occurs at month *m* when::

            cumulative_income(m) >= purchase_price - asset_value(m)

        Parameters
        ----------
        purchase_price : float
        monthly_payment : float
        asset_values : list[float]
            Asset book values per month (index 0 = month 1).

        Returns
        -------
        int | None
            1-based month number, or ``None`` if breakeven is never reached.
        """
        cumulative = 0.0
        for i, av in enumerate(asset_values):
            cumulative += monthly_payment
            gap = purchase_price - av
            if cumulative >= gap:
                return i + 1  # 1-based
        return None

    # ------------------------------------------------------------------
    # 12. Monthly schedule
    # ------------------------------------------------------------------
    def calculate_monthly_schedule(
        self,
        purchase_price: float,
        monthly_payment: float,
        lease_term_months: int,
        category: str,
        body_type: str,
        mileage: int,
        params: dict,
    ) -> list[dict]:
        """Generate a month-by-month lease schedule.

        Each item mirrors the ``MonthlyScheduleItem`` model.

        Parameters
        ----------
        purchase_price : float
        monthly_payment : float
        lease_term_months : int
        category : str
        body_type : str
        mileage : int
            Current odometer (used to extrapolate per-month mileage).
        params : dict

        Returns
        -------
        list[dict]
            One dict per month with keys matching ``MonthlyScheduleItem``.
        """
        useful_life_years = self.USEFUL_LIFE.get(category, 10)
        salvage_ratio = self.SALVAGE_RATIO.get(category, 0.05)
        salvage_value = purchase_price * salvage_ratio
        total_dep = purchase_price - salvage_value
        total_months = useful_life_years * 12

        annual_rate = (
            params.get("fund_cost_rate", 0.020)
            + params.get("credit_spread", 0.015)
            + params.get("liquidity_premium", 0.005)
        )
        monthly_rate = annual_rate / 12.0

        forced_sale_discount = params.get("forced_sale_discount", 0.85)
        penalty_months = params.get("early_termination_penalty_months", 3)

        schedule: list[dict] = []
        cumulative_income = 0.0
        cumulative_profit = 0.0
        remaining_balance = purchase_price

        for m in range(1, lease_term_months + 1):
            # Depreciation (straight-line, capped at salvage)
            if total_months > 0:
                dep_expense = total_dep / total_months
            else:
                dep_expense = 0.0
            asset_value = max(
                purchase_price - dep_expense * m, salvage_value
            )

            # Financing cost on remaining balance (declining)
            financing_cost = remaining_balance * monthly_rate

            # Lease income = the monthly payment
            lease_income = monthly_payment
            cumulative_income += lease_income

            # Monthly profit
            monthly_profit = lease_income - dep_expense - financing_cost
            cumulative_profit += monthly_profit

            # Termination loss estimate: if we had to sell now at forced-sale
            # price minus any early-term penalty
            forced_sale_value = asset_value * forced_sale_discount
            remaining_payments = (
                min(penalty_months, lease_term_months - m) * monthly_payment
            )
            termination_loss = (
                forced_sale_value + cumulative_income
                - purchase_price - remaining_payments
            )

            schedule.append(
                {
                    "month": m,
                    "asset_value": int(round(asset_value)),
                    "lease_income": int(round(lease_income)),
                    "cumulative_income": int(round(cumulative_income)),
                    "depreciation_expense": int(round(dep_expense)),
                    "financing_cost": int(round(financing_cost)),
                    "monthly_profit": int(round(monthly_profit)),
                    "cumulative_profit": int(round(cumulative_profit)),
                    "termination_loss": int(round(termination_loss)),
                }
            )

            # Update remaining balance
            remaining_balance -= lease_income - financing_cost
            remaining_balance = max(remaining_balance, 0.0)

        return schedule

    # ------------------------------------------------------------------
    # 13. Assessment determination
    # ------------------------------------------------------------------
    def determine_assessment(
        self,
        effective_yield: float,
        breakeven: int | None,
        lease_term: int,
    ) -> str:
        """Classify a deal as recommended, needs-review, or not-recommended.

        Rules:

        * **推奨** (recommended) -- effective yield >= 5 % AND breakeven is
          within the first 70 % of the lease term.
        * **非推奨** (not recommended) -- effective yield < 2 % OR breakeven
          is ``None`` (never reached) OR breakeven exceeds 90 % of the term.
        * **要検討** (needs review) -- everything else.

        Parameters
        ----------
        effective_yield : float
        breakeven : int | None
        lease_term : int

        Returns
        -------
        str
            One of ``"推奨"``, ``"要検討"``, or ``"非推奨"``.
        """
        if lease_term <= 0:
            return "非推奨"

        breakeven_ratio = (
            breakeven / lease_term if breakeven is not None else None
        )

        # Non-recommended conditions
        if effective_yield < 0.02:
            return "非推奨"
        if breakeven is None:
            return "非推奨"
        if breakeven_ratio is not None and breakeven_ratio > 0.90:
            return "非推奨"

        # Recommended conditions
        if (
            effective_yield >= 0.05
            and breakeven_ratio is not None
            and breakeven_ratio <= 0.70
        ):
            return "推奨"

        # Everything else
        return "要検討"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_category(input_data: dict) -> str:
        """Map ``vehicle_class`` (Japanese) to internal category code."""
        if "category" in input_data:
            return str(input_data["category"]).upper()

        mapping = {
            "小型": "SMALL",
            "中型": "MEDIUM",
            "大型": "LARGE",
            "トレーラヘッド": "TRAILER_HEAD",
            "トレーラーヘッド": "TRAILER_HEAD",
            "トレーラシャーシ": "TRAILER_CHASSIS",
            "トレーラーシャーシ": "TRAILER_CHASSIS",
        }
        vc = str(input_data.get("vehicle_class", "")).strip()
        return mapping.get(vc, "MEDIUM")


    @staticmethod
    def _resolve_body_type(body_type_raw: str) -> str:
        """Map Japanese body type names to internal codes."""
        mapping = {
            "平ボディ": "FLAT",
            "バン": "VAN",
            "ウイング": "WING",
            "冷凍・冷蔵": "REFR",
            "冷凍冷蔵": "REFR",
            "冷凍": "REFR",
            "冷蔵": "REFR",
            "ダンプ": "DUMP",
            "クレーン": "CRAN",
            "クレーン付": "CRAN",
            "テールリフト": "TAIL_LIFT",
            "テールゲートリフター": "TAIL_LIFT",
            "ミキサー": "MIXER",
            "タンク": "TANK",
            "タンクローリー": "TANK",
            "塵芥車": "GARBAGE",
            "パッカー": "GARBAGE",
        }
        bt = body_type_raw.strip()
        if bt.upper() in {
            "FLAT", "VAN", "WING", "REFR", "DUMP",
            "CRAN", "TAIL_LIFT", "MIXER", "TANK", "GARBAGE",
        }:
            return bt.upper()
        return mapping.get(bt, "FLAT")


# ---------------------------------------------------------------------------
# Legacy functional API (kept for backward compatibility with API layer)
# ---------------------------------------------------------------------------

_engine = PricingEngine()


async def _fetch_market_comparables(
    client: Client,
    maker: str,
    model: str,
    body_type: str,
    registration_year_month: str,
    mileage_km: int,
) -> tuple[int, int]:
    """Query the vehicles table for comparable listings.

    Returns ``(median_price, sample_count)``.  Falls back to ``(0, 0)`` when
    no comparables are found or on query failure.
    """
    # Handle both "2024" (year-only) and "2024-01" (year-month) formats
    if "-" in str(registration_year_month):
        year = int(str(registration_year_month).split("-")[0])
    else:
        year = int(registration_year_month) if str(registration_year_month).isdigit() else 2020
    year_low = year - 2
    year_high = year + 2
    mileage_low = max(0, mileage_km - 50_000)
    mileage_high = mileage_km + 50_000

    maker_variants = normalize_maker(maker) or [maker]

    try:
        query = client.table("vehicles").select("price_yen")
        # Use in_() when we have spelling variants so a single round-trip
        # covers いすゞ↔いすず etc. without `ilike` wildcard surprises.
        if len(maker_variants) > 1:
            query = query.in_("maker", maker_variants)
        else:
            query = query.eq("maker", maker_variants[0])
        response = (
            query
            .eq("body_type", body_type)
            .gte("model_year", year_low)
            .lte("model_year", year_high)
            .gte("mileage_km", mileage_low)
            .lte("mileage_km", mileage_high)
            .eq("listing_status", "active")
            .not_.is_("price_yen", "null")
            .execute()
        )
        prices = sorted(
            row["price_yen"] for row in response.data if row.get("price_yen")
        )
    except Exception:
        logger.exception(
            "market_comparable_query_failed",
            maker=maker,
            model=model,
            body_type=body_type,
        )
        prices = []

    if not prices:
        return (0, 0)

    n = len(prices)
    median = (
        (prices[n // 2 - 1] + prices[n // 2]) // 2
        if n % 2 == 0
        else prices[n // 2]
    )
    return (median, n)


async def calculate_simulation(
    input_data: SimulationInput,
    supabase: Client,
) -> SimulationResult:
    """Run a full leaseback pricing simulation and return the result.

    This is the legacy entry-point called by the API layer.  It delegates
    to ``PricingEngine.calculate`` internally while maintaining the same
    async signature and Supabase-based market data fetching.
    """
    ins_m = input_data.insurance_monthly or 0
    maint_m = input_data.maintenance_monthly or 0
    body_opt = input_data.body_option_value or 0

    # 1. Market comparables
    market_median, sample_count = await _fetch_market_comparables(
        client=supabase,
        maker=input_data.maker,
        model=input_data.model,
        body_type=input_data.body_type,
        registration_year_month=input_data.registration_year_month,
        mileage_km=input_data.mileage_km,
    )

    # 2. Build market_data list for the engine
    market_data_list: list[dict] = []
    if market_median > 0:
        # Represent the median as a single retail comparable
        market_data_list.append(
            {"price_yen": market_median, "source_site": "retail"}
        )

    # 3. Delegate to engine
    input_dict = input_data.model_dump()
    result = _engine.calculate(
        input_data=input_dict,
        market_data=market_data_list if market_data_list else None,
    )

    # 4. Build schedule as Pydantic models
    schedule_items = [
        MonthlyScheduleItem(**item) for item in result["monthly_schedule"]
    ]

    return SimulationResult(
        max_purchase_price=result["max_purchase_price"],
        recommended_purchase_price=result["recommended_purchase_price"],
        estimated_residual_value=result["estimated_residual_value"],
        residual_rate_result=result["residual_rate_result"],
        monthly_lease_fee=result["monthly_lease_fee"],
        total_lease_fee=result["total_lease_fee"],
        breakeven_months=result["breakeven_months"],
        effective_yield_rate=result["effective_yield_rate"],
        market_median_price=result["market_median_price"],
        market_sample_count=result["market_sample_count"],
        market_deviation_rate=result["market_deviation_rate"],
        assessment=result["assessment"],
        monthly_schedule=schedule_items,
    )


# ---------------------------------------------------------------------------
# Backward-compatible thin wrappers used by unit tests
# ---------------------------------------------------------------------------

_DEFAULT_RESIDUAL_RATES = {12: 0.50, 24: 0.30, 36: 0.20, 48: 0.15, 60: 0.10}


def _max_purchase_price(
    book_value: int, market_median: int, body_option_value: int = 0
) -> int:
    anchor = max(book_value, market_median)
    return int(anchor * 1.10) + body_option_value


def _residual_value(
    purchase_price: int, lease_term_months: int, residual_rate: float | None = None
) -> tuple[int, float]:
    if residual_rate is None:
        for threshold in sorted(_DEFAULT_RESIDUAL_RATES):
            if lease_term_months <= threshold:
                residual_rate = _DEFAULT_RESIDUAL_RATES[threshold]
                break
        else:
            residual_rate = 0.05
    return (int(purchase_price * residual_rate), residual_rate)


def _monthly_lease_fee(
    purchase_price: int,
    residual_value: int,
    lease_term_months: int,
    target_yield_rate: float,
    insurance_monthly: int = 0,
    maintenance_monthly: int = 0,
) -> int:
    depreciable = purchase_price - residual_value
    mr = target_yield_rate / 12
    if mr > 0 and lease_term_months > 0:
        factor = (mr * (1 + mr) ** lease_term_months) / (
            (1 + mr) ** lease_term_months - 1
        )
        base = int(depreciable * factor)
    elif lease_term_months > 0:
        base = depreciable // lease_term_months
    else:
        base = 0
    residual_cost = int(residual_value * mr) if mr > 0 else 0
    return base + residual_cost + insurance_monthly + maintenance_monthly


def _assessment(
    effective_yield: float, target_yield: float, market_deviation: float
) -> str:
    if effective_yield >= target_yield and abs(market_deviation) <= 0.05:
        return "推奨"
    if effective_yield < target_yield * 0.5 or abs(market_deviation) > 0.10:
        return "非推奨"
    return "要検討"


def _build_schedule(
    purchase_price: int,
    residual_value: int,
    lease_term_months: int,
    monthly_fee: int,
    target_yield_rate: float,
    insurance_monthly: int = 0,
    maintenance_monthly: int = 0,
) -> list:
    items = []
    dep_per_month = (purchase_price - residual_value) / lease_term_months
    cumulative = 0.0
    cumulative_profit = 0.0
    mr = target_yield_rate / 12
    for m in range(1, lease_term_months + 1):
        asset = max(int(purchase_price - dep_per_month * m), residual_value)
        cumulative += monthly_fee
        prev_asset = purchase_price - dep_per_month * (m - 1)
        dep_exp = prev_asset - asset
        fin_cost = int(prev_asset * mr)
        net_income = monthly_fee - insurance_monthly - maintenance_monthly
        profit = net_income - dep_exp - fin_cost
        cumulative_profit += profit
        term_loss = purchase_price - cumulative - asset
        items.append(
            MonthlyScheduleItem(
                month=m,
                asset_value=asset,
                lease_income=monthly_fee,
                cumulative_income=int(cumulative),
                depreciation_expense=int(dep_exp),
                financing_cost=fin_cost,
                monthly_profit=int(profit),
                cumulative_profit=int(cumulative_profit),
                termination_loss=int(term_loss),
            )
        )
    return items
