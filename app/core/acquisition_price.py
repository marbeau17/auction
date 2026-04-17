"""Step 1: Acquisition price calculation for commercial vehicle leaseback.

Calculates the appropriate purchase/acquisition price by analysing
comparable market data, applying trend and safety adjustments, and
returning a recommended price range.

All monetary values are in Japanese Yen (JPY) unless otherwise noted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import structlog
from supabase import Client

from app.core.market_analysis import MarketAnalyzer
from app.core import pricing_constants as _C
from app.models.pricing import AcquisitionPriceResult

logger = structlog.get_logger()

# ------------------------------------------------------------------
# Vehicle-class mapping (Japanese → internal code)
# ------------------------------------------------------------------
_VEHICLE_CLASS_MAP: dict[str, str] = {
    "小型": "SMALL",
    "中型": "MEDIUM",
    "大型": "LARGE",
    "トレーラヘッド": "TRAILER_HEAD",
    "トレーラーヘッド": "TRAILER_HEAD",
    "トレーラシャーシ": "TRAILER_CHASSIS",
    "トレーラーシャーシ": "TRAILER_CHASSIS",
}

_SAFETY_MARGINS_BY_CATEGORY = _C.SAFETY_MARGINS_BY_CATEGORY


class AcquisitionPriceCalculator:
    """Step 1: Calculate appropriate acquisition price from market data.

    This calculator fetches comparable vehicles from the database,
    performs statistical analysis via :class:`MarketAnalyzer`, applies
    trend and safety-margin adjustments, and produces a recommended
    acquisition-price range.
    """

    DEFAULT_VOLATILITY_PREMIUM = _C.DEFAULT_VOLATILITY_PREMIUM
    TREND_FLOOR = _C.TREND_FLOOR
    TREND_CEILING = _C.TREND_CEILING
    MIN_SAFETY_MARGIN = _C.MIN_SAFETY_MARGIN
    MAX_SAFETY_MARGIN = _C.MAX_SAFETY_MARGIN
    COMPARABLE_MAX_RESULTS = _C.COMPARABLE_MAX_RESULTS
    COMPARABLE_YEAR_RANGE = _C.COMPARABLE_YEAR_RANGE
    COMPARABLE_MILEAGE_RATIO = _C.COMPARABLE_MILEAGE_RATIO

    def __init__(self, supabase_client: Client) -> None:
        self.supabase = supabase_client
        self.market_analyzer = MarketAnalyzer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def calculate(
        self,
        input_data: dict[str, Any],
        safety_margin_rate: float = 0.05,
    ) -> AcquisitionPriceResult:
        """Calculate recommended and maximum acquisition prices.

        Parameters
        ----------
        input_data:
            Dict describing the target vehicle.  Expected keys:
            ``maker``, ``model``, ``year`` (or ``registration_year_month``),
            ``mileage`` (or ``mileage_km``), ``vehicle_class`` (or
            ``category``), ``body_option_value`` (optional, yen).
        safety_margin_rate:
            Base safety-margin rate.  The actual margin is adjusted
            upward when price volatility is high.

        Returns
        -------
        AcquisitionPriceResult
        """
        log = logger.bind(
            maker=input_data.get("maker"),
            model=input_data.get("model"),
        )
        log.info("acquisition_price.calculate.start")

        # --- 1. Fetch comparable vehicles --------------------------------
        comparables = await self._fetch_comparables(input_data)
        prices = [float(v["price"]) for v in comparables if v.get("price")]
        log.info(
            "acquisition_price.comparables_found",
            count=len(comparables),
            price_count=len(prices),
        )

        # If no comparable data, fall back to a supplied reference price
        if not prices:
            fallback = float(
                input_data.get("acquisition_price", 0)
                or input_data.get("book_value", 0)
            )
            if fallback > 0:
                prices = [fallback]
                log.warn("acquisition_price.using_fallback", fallback=fallback)
            else:
                log.error("acquisition_price.no_data")
                return self._empty_result()

        # --- 2. Weighted median ------------------------------------------
        market_median = self._weighted_median(prices, comparables)

        # --- 3. Trend factor (clamp 0.80-1.20) ---------------------------
        price_history = self._build_price_history(comparables)
        trend_info = self.market_analyzer.calculate_trend(
            price_history,
            recent_days=30,
            baseline_days=180,
        )
        trend_factor = float(trend_info["trend_factor"])
        trend_factor = max(self.TREND_FLOOR, min(self.TREND_CEILING, trend_factor))
        trend_direction: str = trend_info["direction"]

        # --- 4. Dynamic safety margin ------------------------------------
        stats = self.market_analyzer.calculate_statistics(prices)
        std_dev = float(stats["std"])
        median_val = float(stats["median"])

        category = self._resolve_category(input_data)
        base_safety = safety_margin_rate or _SAFETY_MARGINS_BY_CATEGORY.get(
            category, 0.05
        )
        volatility_premium = self.DEFAULT_VOLATILITY_PREMIUM

        if median_val > 0 and len(prices) >= 2:
            cv = std_dev / median_val
            dynamic_margin = base_safety + volatility_premium * cv
        else:
            dynamic_margin = base_safety

        dynamic_margin = max(self.MIN_SAFETY_MARGIN, min(self.MAX_SAFETY_MARGIN, dynamic_margin))

        # --- 5. Body option adjustment -----------------------------------
        body_option_value = int(input_data.get("body_option_value", 0) or 0)

        # --- 6. Final prices ---------------------------------------------
        recommended_price = (
            market_median * trend_factor * (1.0 - dynamic_margin)
            + body_option_value
        )
        max_price = (
            market_median * trend_factor * (1.0 - base_safety)
            + body_option_value
        )
        price_range_low = recommended_price * 0.95
        price_range_high = max_price * 1.05

        # Confidence based on sample size
        sample_count = len(prices)
        if sample_count >= 10:
            confidence = "high"
        elif sample_count >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        result = AcquisitionPriceResult(
            recommended_price=int(round(recommended_price)),
            max_price=int(round(max_price)),
            price_range_low=int(round(price_range_low)),
            price_range_high=int(round(price_range_high)),
            market_median=int(round(market_median)),
            trend_factor=round(trend_factor, 4),
            safety_margin_rate=round(dynamic_margin, 4),
            body_option_value=body_option_value,
            sample_count=sample_count,
            confidence=confidence,
            trend_direction=trend_direction,
            comparable_stats=stats,
        )

        log.info(
            "acquisition_price.calculate.done",
            recommended=result.recommended_price,
            max=result.max_price,
            sample_count=sample_count,
            confidence=confidence,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_comparables(
        self, input_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Fetch comparable vehicles from the database.

        Filters on maker (exact), model (ilike), year (±2), and returns
        up to ``COMPARABLE_MAX_RESULTS`` rows sorted by recency.
        """
        maker = input_data.get("maker", "")
        model = input_data.get("model", "")

        # Resolve target year
        year = input_data.get("year")
        if year is None:
            reg = str(input_data.get("registration_year_month", ""))
            if reg and "-" in reg:
                try:
                    year = int(reg.split("-")[0])
                except (ValueError, IndexError):
                    year = None
            elif reg and reg.isdigit():
                year = int(reg)

        if not maker:
            logger.warn("acquisition_price.fetch.no_maker")
            return []

        try:
            query = (
                self.supabase.table("market_prices")
                .select("*")
                .eq("maker", maker)
            )

            if model:
                query = query.ilike("model", f"%{model}%")

            if year is not None:
                query = query.gte("year", int(year) - self.COMPARABLE_YEAR_RANGE)
                query = query.lte("year", int(year) + self.COMPARABLE_YEAR_RANGE)

            query = query.order("created_at", desc=True)
            query = query.limit(self.COMPARABLE_MAX_RESULTS)

            response = query.execute()
            rows = response.data or []
        except Exception:
            logger.exception("acquisition_price.fetch.error")
            return []

        # Post-filter on mileage proximity if target mileage is known
        target_mileage = input_data.get("mileage") or input_data.get("mileage_km")
        if target_mileage is not None:
            try:
                target_mileage = int(target_mileage)
            except (TypeError, ValueError):
                target_mileage = None

        if target_mileage and target_mileage > 0:
            filtered: list[dict[str, Any]] = []
            for row in rows:
                row_mileage = row.get("mileage") or row.get("mileage_km")
                if row_mileage is None:
                    filtered.append(row)  # keep rows without mileage data
                    continue
                try:
                    ratio = abs(int(row_mileage) - target_mileage) / target_mileage
                except (TypeError, ValueError, ZeroDivisionError):
                    filtered.append(row)
                    continue
                if ratio <= self.COMPARABLE_MILEAGE_RATIO:
                    filtered.append(row)
            return filtered

        return rows

    def _weighted_median(
        self,
        prices: list[float],
        comparables: list[dict[str, Any]],
    ) -> float:
        """Calculate a similarity-weighted median of prices.

        If comparables carry a ``similarity_score`` from
        :class:`MarketAnalyzer`, it is used as the weight.  Otherwise
        recency is used: more-recent records get higher weight.

        Parameters
        ----------
        prices:
            Price values (aligned 1:1 with *comparables*).
        comparables:
            Comparable vehicle dicts from the database.

        Returns
        -------
        float
            Weighted median price.
        """
        if not prices:
            return 0.0

        if len(prices) == 1:
            return prices[0]

        arr = np.array(prices, dtype=np.float64)
        n = len(arr)

        # Build weight vector
        weights = np.ones(n, dtype=np.float64)
        has_scores = any(
            c.get("similarity_score") is not None for c in comparables
        )

        if has_scores and len(comparables) == n:
            for i, comp in enumerate(comparables):
                score = comp.get("similarity_score")
                if score is not None:
                    weights[i] = max(float(score), 0.1)
        else:
            # Recency weighting: linearly increasing (oldest=1, newest=n)
            weights = np.arange(1, n + 1, dtype=np.float64)

        # Sort by price and compute weighted median
        sorted_idx = np.argsort(arr)
        sorted_prices = arr[sorted_idx]
        sorted_weights = weights[sorted_idx]

        cumulative = np.cumsum(sorted_weights)
        total = cumulative[-1]
        median_idx = np.searchsorted(cumulative, total / 2.0)
        median_idx = min(median_idx, n - 1)

        return float(sorted_prices[median_idx])

    @staticmethod
    def _build_price_history(
        comparables: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build a price-history list from comparable records.

        Extracts ``date`` and ``price`` from each record for
        :meth:`MarketAnalyzer.calculate_trend`.
        """
        history: list[dict[str, Any]] = []
        for comp in comparables:
            price = comp.get("price") or comp.get("price_yen")
            date = (
                comp.get("sold_date")
                or comp.get("auction_date")
                or comp.get("created_at")
            )
            if price is not None and date is not None:
                history.append({"date": date, "price": price})
        return history

    @staticmethod
    def _resolve_category(input_data: dict[str, Any]) -> str:
        """Map ``vehicle_class`` (Japanese) or ``category`` to internal code."""
        if "category" in input_data:
            return str(input_data["category"]).upper()
        vc = str(input_data.get("vehicle_class", "")).strip()
        return _VEHICLE_CLASS_MAP.get(vc, "MEDIUM")

    @staticmethod
    def _empty_result() -> AcquisitionPriceResult:
        """Return a zeroed-out result when no data is available."""
        return AcquisitionPriceResult(
            recommended_price=0,
            max_price=0,
            price_range_low=0,
            price_range_high=0,
            market_median=0,
            trend_factor=1.0,
            safety_margin_rate=0.0,
            body_option_value=0,
            sample_count=0,
            confidence="low",
            trend_direction="stable",
            comparable_stats=None,
        )
