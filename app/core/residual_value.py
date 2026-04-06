"""Residual value prediction module for commercial vehicles.

Provides multiple depreciation models (straight-line, declining-balance)
and a hybrid prediction that blends theoretical values with actual market
data for more accurate residual value estimation.
"""

from __future__ import annotations

from typing import Any, Optional


class ResidualValueCalculator:
    """Calculates vehicle residual values using multiple depreciation models."""

    # Legal useful life in Japan (税法上の法定耐用年数)
    LEGAL_USEFUL_LIFE: dict[str, int] = {
        "普通貨物": 5,
        "ダンプ": 4,
        "小型貨物": 3,
        "特種自動車": 4,
        "被けん引車": 4,
    }

    # Average annual mileage assumptions (km) by category
    _ANNUAL_MILEAGE_NORM: dict[str, int] = {
        "普通貨物": 40_000,
        "ダンプ": 30_000,
        "小型貨物": 25_000,
        "特種自動車": 20_000,
        "被けん引車": 50_000,
    }

    # Body-type value retention multiplier (架装の価値残存率係数)
    _BODY_RETENTION: dict[str, float] = {
        "平ボディ": 0.85,
        "バン": 0.90,
        "冷凍冷蔵": 0.75,
        "ウイング": 0.80,
        "ダンプ": 0.88,
        "タンク": 0.70,
        "クレーン": 0.65,
        "塵芥車": 0.60,
    }

    # ------------------------------------------------------------------ #
    # 中古車耐用年数 (簡便法)
    # ------------------------------------------------------------------ #

    def calculate_used_vehicle_useful_life(
        self, legal_life: int, elapsed_years: int
    ) -> int:
        """中古車の耐用年数簡便法 (Simplified method for used vehicles).

        Parameters
        ----------
        legal_life:
            法定耐用年数 for the vehicle category.
        elapsed_years:
            Number of full years since first registration.

        Returns
        -------
        int
            Useful life in years (minimum 2).
        """
        if legal_life <= 0:
            return 2
        if elapsed_years < 0:
            elapsed_years = 0

        remaining = legal_life - elapsed_years
        if remaining > 0:
            return max(remaining, 2)
        return max(int(elapsed_years * 0.2), 2)

    # ------------------------------------------------------------------ #
    # Depreciation models
    # ------------------------------------------------------------------ #

    def straight_line(
        self,
        purchase_price: float,
        salvage_value: float,
        useful_life: int,
        elapsed_years: int,
    ) -> float:
        """Straight-line depreciation (定額法).

        Parameters
        ----------
        purchase_price:
            Original acquisition cost.
        salvage_value:
            Estimated value at end of useful life.
        useful_life:
            Total useful life in years.
        elapsed_years:
            Years elapsed since acquisition.

        Returns
        -------
        float
            Remaining book value after *elapsed_years*.
        """
        if useful_life <= 0:
            return salvage_value
        if elapsed_years < 0:
            elapsed_years = 0
        if elapsed_years >= useful_life:
            return salvage_value

        annual_depreciation = (purchase_price - salvage_value) / useful_life
        value = purchase_price - annual_depreciation * elapsed_years
        return max(value, salvage_value)

    def declining_balance_200(
        self,
        purchase_price: float,
        useful_life: int,
        elapsed_years: int,
    ) -> float:
        """200% declining-balance depreciation (200%定率法).

        Uses the Japanese tax-code 200%-DB method introduced in 2012.
        When the annual depreciation under DB falls below the straight-line
        equivalent of the remaining balance, switches to straight-line for
        the remaining period (改定償却率).

        Parameters
        ----------
        purchase_price:
            Original acquisition cost.
        useful_life:
            Useful life in years.
        elapsed_years:
            Years elapsed since acquisition.

        Returns
        -------
        float
            Remaining book value after *elapsed_years*.
        """
        if useful_life <= 0:
            return 1.0  # Minimum book value (備忘価額)
        if elapsed_years < 0:
            elapsed_years = 0

        rate = 2.0 / useful_life  # 200%-DB rate
        # Guarantee amount: the threshold to switch to SL
        sl_switch_rate = 1.0 / useful_life
        guarantee_amount = purchase_price * (sl_switch_rate * 0.9)

        value = float(purchase_price)
        switched_to_sl = False
        sl_depreciation = 0.0

        for year in range(1, elapsed_years + 1):
            if year > useful_life:
                break

            if switched_to_sl:
                value -= sl_depreciation
            else:
                depreciation = value * rate
                if depreciation < guarantee_amount:
                    # Switch to straight-line for remaining years
                    remaining_years = useful_life - (year - 1)
                    if remaining_years > 0:
                        sl_depreciation = value / remaining_years
                    else:
                        sl_depreciation = value - 1.0
                    switched_to_sl = True
                    value -= sl_depreciation
                else:
                    value -= depreciation

        return max(value, 1.0)  # 備忘価額 (memorandum value)

    # ------------------------------------------------------------------ #
    # Hybrid prediction
    # ------------------------------------------------------------------ #

    def hybrid_prediction(
        self,
        theoretical_value: float,
        market_data: dict[str, Any],
        params: Optional[dict[str, float]] = None,
    ) -> float:
        """Blend theoretical depreciation with market observations.

        Parameters
        ----------
        theoretical_value:
            Value derived from depreciation models.
        market_data:
            Must contain at least ``median_price`` (float).  Optionally
            ``sample_count`` (int) and ``volatility`` (float, 0-1).
        params:
            Optional tuning parameters:
            - ``market_weight_base`` (default 0.6): base weight for market data
            - ``min_samples`` (default 3): minimum samples to trust market data
            - ``volatility_penalty`` (default 0.5): reduce market weight when
              volatility is high

        Returns
        -------
        float
            Blended predicted value.
        """
        if params is None:
            params = {}

        market_weight_base: float = params.get("market_weight_base", 0.6)
        min_samples: int = int(params.get("min_samples", 3))
        volatility_penalty: float = params.get("volatility_penalty", 0.5)

        median_price = market_data.get("median_price")
        if median_price is None or median_price <= 0:
            return theoretical_value

        sample_count = market_data.get("sample_count", 0)
        volatility = market_data.get("volatility", 0.0)

        if sample_count < min_samples:
            # Not enough market data -- lean toward theoretical
            market_weight = market_weight_base * (sample_count / min_samples)
        else:
            market_weight = market_weight_base

        # Penalise high-volatility market data
        market_weight *= max(0.0, 1.0 - volatility * volatility_penalty)
        market_weight = min(max(market_weight, 0.0), 1.0)

        theory_weight = 1.0 - market_weight
        blended = theory_weight * theoretical_value + market_weight * median_price
        return max(blended, 1.0)

    # ------------------------------------------------------------------ #
    # Mileage adjustment
    # ------------------------------------------------------------------ #

    def _mileage_adjustment_factor(
        self, mileage_km: int, elapsed_months: int, category: str
    ) -> float:
        """Return a multiplier (0.5 .. 1.1) based on mileage vs norm.

        Vehicles driven less than average retain more value; those driven
        more lose value faster.
        """
        if elapsed_months <= 0:
            return 1.0

        elapsed_years = elapsed_months / 12.0
        annual_norm = self._ANNUAL_MILEAGE_NORM.get(category, 30_000)
        expected_km = annual_norm * elapsed_years

        if expected_km <= 0:
            return 1.0

        ratio = mileage_km / expected_km  # >1 means over-mileage

        if ratio <= 0.5:
            return 1.10
        elif ratio <= 0.8:
            return 1.05
        elif ratio <= 1.0:
            return 1.00
        elif ratio <= 1.3:
            return 0.93
        elif ratio <= 1.5:
            return 0.85
        elif ratio <= 2.0:
            return 0.75
        else:
            return 0.60

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def predict(
        self,
        purchase_price: float,
        category: str,
        body_type: str,
        elapsed_months: int,
        mileage: int,
        market_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Predict residual value for a commercial vehicle.

        Parameters
        ----------
        purchase_price:
            Original purchase price (円).
        category:
            Vehicle category key (e.g. ``"普通貨物"``).
        body_type:
            Body/superstructure type (e.g. ``"ウイング"``).
        elapsed_months:
            Months since first registration.
        mileage:
            Odometer reading in km.
        market_data:
            Optional dict with ``median_price``, ``sample_count``,
            ``volatility`` for hybrid blending.

        Returns
        -------
        dict
            ``residual_value`` -- predicted value (int, rounded to 10,000 yen)
            ``method_used``    -- description of the method applied
            ``confidence``     -- float 0-1
            ``breakdown``      -- chassis / body / mileage_adj components
        """
        if purchase_price <= 0:
            return {
                "residual_value": 0,
                "method_used": "none",
                "confidence": 0.0,
                "breakdown": {
                    "chassis": 0.0,
                    "body": 0.0,
                    "mileage_adj": 1.0,
                },
            }

        # ---- Determine useful life ---- #
        legal_life = self.LEGAL_USEFUL_LIFE.get(category, 5)
        elapsed_years = elapsed_months // 12
        useful_life = self.calculate_used_vehicle_useful_life(
            legal_life, elapsed_years
        )

        # ---- Salvage value (備忘価額 or 10%) ---- #
        salvage_value = max(purchase_price * 0.10, 1.0)

        # ---- Chassis value via two methods ---- #
        sl_value = self.straight_line(
            purchase_price, salvage_value, legal_life, elapsed_years
        )
        db_value = self.declining_balance_200(
            purchase_price, legal_life, elapsed_years
        )
        # Use the average of both as the theoretical chassis value
        chassis_value = (sl_value + db_value) / 2.0

        # ---- Body retention ---- #
        body_retention = self._BODY_RETENTION.get(body_type, 0.80)
        # Body depreciates faster; assume body is ~30% of purchase price
        body_ratio = 0.30
        chassis_ratio = 1.0 - body_ratio

        body_value = purchase_price * body_ratio * (
            body_retention ** (elapsed_years / max(legal_life, 1))
        )
        chassis_component = chassis_value * chassis_ratio / (
            chassis_ratio + body_ratio
        )

        theoretical_value = chassis_component + body_value

        # ---- Mileage adjustment ---- #
        mileage_adj = self._mileage_adjustment_factor(
            mileage, elapsed_months, category
        )
        theoretical_value *= mileage_adj

        # ---- Blend with market data if available ---- #
        method_used: str
        confidence: float

        if market_data and market_data.get("median_price", 0) > 0:
            predicted = self.hybrid_prediction(
                theoretical_value, market_data
            )
            sample_count = market_data.get("sample_count", 0)
            volatility = market_data.get("volatility", 0.5)

            method_used = "hybrid"
            # Confidence rises with sample count, falls with volatility
            sample_conf = min(sample_count / 20.0, 1.0)
            vol_conf = max(1.0 - volatility, 0.2)
            confidence = round(sample_conf * vol_conf, 3)
        else:
            predicted = theoretical_value
            method_used = "theoretical"
            confidence = 0.4  # lower confidence without market data

        # Round to nearest 万円 (10,000 yen)
        residual_value = int(round(predicted / 10_000) * 10_000)
        residual_value = max(residual_value, 0)

        return {
            "residual_value": residual_value,
            "method_used": method_used,
            "confidence": confidence,
            "breakdown": {
                "chassis": round(chassis_component, 2),
                "body": round(body_value, 2),
                "mileage_adj": round(mileage_adj, 4),
            },
        }
