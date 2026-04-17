"""Step 2: Residual value calculator with scenario analysis.

Extends the original :class:`ResidualValueCalculator` with bull / base / bear
scenario modelling for integration into the CVLPOS pricing engine pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Tuple

from app.core.residual_value import ResidualValueCalculator
from app.models.pricing import ResidualValueResult, ScenarioValue


# ------------------------------------------------------------------ #
# Vehicle-class useful life (経済的耐用年数) — longer than the
# tax-code legal life used in the base calculator.
# ------------------------------------------------------------------ #

VEHICLE_CLASS_USEFUL_LIFE: Dict[str, int] = {
    "SMALL": 7,
    "MEDIUM": 9,
    "LARGE": 10,
    "TRAILER_HEAD": 10,
    "TRAILER_CHASSIS": 12,
}

# Japanese label aliases
_JP_ALIASES: Dict[str, str] = {
    "小型": "SMALL",
    "中型": "MEDIUM",
    "大型": "LARGE",
    "トレーラヘッド": "TRAILER_HEAD",
    "トレーラシャシ": "TRAILER_CHASSIS",
}

# ------------------------------------------------------------------ #
# Body depreciation table — retention rate by body type and lease
# duration in years.  Values represent the fraction of body-related
# value retained after *n* years of lease operation.
# ------------------------------------------------------------------ #

BODY_DEPRECIATION_TABLE: Dict[str, Dict[int, float]] = {
    "平ボディ": {1: 0.90, 2: 0.82, 3: 0.74, 4: 0.67, 5: 0.60, 6: 0.54, 7: 0.49},
    "バン": {1: 0.92, 2: 0.85, 3: 0.78, 4: 0.72, 5: 0.66, 6: 0.61, 7: 0.56},
    "冷凍冷蔵": {1: 0.85, 2: 0.73, 3: 0.62, 4: 0.53, 5: 0.45, 6: 0.38, 7: 0.32},
    "ウイング": {1: 0.88, 2: 0.78, 3: 0.69, 4: 0.61, 5: 0.54, 6: 0.48, 7: 0.42},
    "ダンプ": {1: 0.91, 2: 0.83, 3: 0.76, 4: 0.69, 5: 0.63, 6: 0.57, 7: 0.52},
    "タンク": {1: 0.82, 2: 0.68, 3: 0.56, 4: 0.47, 5: 0.39, 6: 0.33, 7: 0.28},
    "クレーン": {1: 0.80, 2: 0.65, 3: 0.53, 4: 0.43, 5: 0.35, 6: 0.28, 7: 0.23},
    "塵芥車": {1: 0.78, 2: 0.62, 3: 0.49, 4: 0.39, 5: 0.31, 6: 0.25, 7: 0.20},
}

# Scenario multipliers
SCENARIO_MULTIPLIERS: Dict[str, float] = {
    "bull": 1.15,
    "base": 1.00,
    "bear": 0.85,
}


class ResidualValueCalculatorV2:
    """Step 2: Calculate residual value with scenario analysis.

    Extends the original :class:`ResidualValueCalculator` with:

    - Bull / Base / Bear scenarios
    - Integration with pricing master parameters
    - Enhanced mileage adjustment using the base calculator's logic
    - Body depreciation table keyed by lease term in years
    """

    def __init__(self) -> None:
        self._base_calculator = ResidualValueCalculator()

    # -------------------------------------------------------------- #
    # Internal helpers
    # -------------------------------------------------------------- #

    @staticmethod
    def _resolve_vehicle_class(vehicle_class: str) -> str:
        """Map a Japanese or English vehicle class label to a canonical key."""
        upper = vehicle_class.upper()
        if upper in VEHICLE_CLASS_USEFUL_LIFE:
            return upper
        alias = _JP_ALIASES.get(vehicle_class)
        if alias is not None:
            return alias
        return "MEDIUM"  # safe default

    @staticmethod
    def _elapsed_years_from_registration(registration_year_month: str) -> float:
        """Return fractional elapsed years from *registration_year_month* to today.

        Accepts ``"YYYY-MM"`` format.
        """
        try:
            reg_date = datetime.strptime(registration_year_month, "%Y-%m").date()
        except (ValueError, TypeError):
            return 0.0
        today = date.today()
        delta_days = (today - reg_date).days
        return max(delta_days / 365.25, 0.0)

    def _lookup_body_retention(
        self, body_type: str, lease_term_years: int
    ) -> float:
        """Look up body retention rate from :data:`BODY_DEPRECIATION_TABLE`.

        If the exact *lease_term_years* is not in the table, the closest
        available key is used.  Unknown body types fall back to 0.70.
        """
        table = BODY_DEPRECIATION_TABLE.get(body_type)
        if table is None:
            # Unknown body type — conservative default
            return 0.70

        if lease_term_years in table:
            return table[lease_term_years]

        # Clamp to nearest available key
        keys = sorted(table.keys())
        if lease_term_years <= keys[0]:
            return table[keys[0]]
        if lease_term_years >= keys[-1]:
            return table[keys[-1]]

        # Linear interpolation between surrounding keys
        for i in range(len(keys) - 1):
            if keys[i] < lease_term_years < keys[i + 1]:
                lo, hi = keys[i], keys[i + 1]
                ratio = (lease_term_years - lo) / (hi - lo)
                return table[lo] + ratio * (table[hi] - table[lo])

        return 0.70  # fallback

    def _mileage_adjustment(
        self,
        current_mileage_km: int,
        elapsed_months: int,
        vehicle_class_key: str,
    ) -> float:
        """Compute mileage adjustment factor via the base calculator.

        Maps the CVLPOS vehicle-class key to the base calculator's
        Japanese category key for norm lookup.
        """
        _class_to_category = {
            "SMALL": "小型貨物",
            "MEDIUM": "普通貨物",
            "LARGE": "普通貨物",
            "TRAILER_HEAD": "被けん引車",
            "TRAILER_CHASSIS": "被けん引車",
        }
        category = _class_to_category.get(vehicle_class_key, "普通貨物")
        return self._base_calculator._mileage_adjustment_factor(
            current_mileage_km, elapsed_months, category
        )

    @staticmethod
    def _round_yen(value: float) -> int:
        """Round to nearest 10,000 yen (万円) and ensure non-negative."""
        return max(int(round(value / 10_000) * 10_000), 0)

    # -------------------------------------------------------------- #
    # Main entry point
    # -------------------------------------------------------------- #

    def calculate(
        self,
        acquisition_price: int,
        vehicle_class: str,
        body_type: str,
        lease_term_months: int,
        current_mileage_km: int,
        registration_year_month: str,
        depreciation_method: str = "declining_200",
    ) -> ResidualValueResult:
        """Calculate residual value with bull / base / bear scenarios.

        Parameters
        ----------
        acquisition_price:
            Original acquisition price in yen.
        vehicle_class:
            Vehicle class key — English (``"SMALL"``, ``"LARGE"``, ...)
            or Japanese (``"小型"``, ``"大型"``, ...).
        body_type:
            Body / superstructure type (e.g. ``"ウイング"``).
        lease_term_months:
            Lease duration in months.
        current_mileage_km:
            Current odometer reading in km.
        registration_year_month:
            First registration date as ``"YYYY-MM"``.
        depreciation_method:
            ``"declining_200"`` (default) or ``"straight_line"``.

        Returns
        -------
        ResidualValueResult
            Contains base residual value, three scenario outcomes, and
            the intermediate parameters used.

        Calculation steps
        -----------------
        1. Resolve useful life from *vehicle_class*.
        2. Compute elapsed years from *registration_year_month* to today.
        3. Compute remaining useful life.
        4. Look up body retention from :data:`BODY_DEPRECIATION_TABLE`.
        5. Use the base calculator's depreciation model for chassis value.
        6. Combine: ``base_residual = acquisition_price * body_retention * mileage_adj``.
        7. Generate three scenarios: bull (x1.15), base (x1.00), bear (x0.85).
        """
        # 1. Resolve useful life
        class_key = self._resolve_vehicle_class(vehicle_class)
        useful_life = VEHICLE_CLASS_USEFUL_LIFE[class_key]

        # 2. Elapsed years
        elapsed = self._elapsed_years_from_registration(registration_year_month)
        elapsed_years_int = int(elapsed)
        elapsed_months = int(elapsed * 12)

        # 3. Remaining useful life (floored at 0)
        remaining = max(useful_life - elapsed, 0.0)

        # 4. Body retention rate
        lease_years = max(lease_term_months // 12, 1)
        body_retention = self._lookup_body_retention(body_type, lease_years)

        # 5. Chassis depreciation via base calculator
        if depreciation_method == "straight_line":
            salvage = max(acquisition_price * 0.10, 1.0)
            _chassis_value = self._base_calculator.straight_line(
                acquisition_price, salvage, useful_life, elapsed_years_int
            )
        else:
            _chassis_value = self._base_calculator.declining_balance_200(
                acquisition_price, useful_life, elapsed_years_int
            )

        # 6. Mileage adjustment
        mileage_adj = self._mileage_adjustment(
            current_mileage_km, elapsed_months, class_key
        )

        # Combine: base residual = acquisition_price * body_retention * mileage_adj
        base_residual_raw = acquisition_price * body_retention * mileage_adj
        base_residual = self._round_yen(base_residual_raw)

        # 7. Scenarios
        scenarios: list[ScenarioValue] = []
        for label, multiplier in SCENARIO_MULTIPLIERS.items():
            scenario_value = self._round_yen(base_residual_raw * multiplier)
            scenarios.append(
                ScenarioValue(
                    label=label,
                    multiplier=multiplier,
                    residual_value=scenario_value,
                )
            )

        return ResidualValueResult(
            base_residual_value=base_residual,
            scenarios=scenarios,
            depreciation_method=depreciation_method,
            body_type=body_type,
            body_retention_rate=round(body_retention, 4),
            mileage_adjustment=round(mileage_adj, 4),
            useful_life_years=useful_life,
            elapsed_years=round(elapsed, 2),
            remaining_useful_life_years=round(remaining, 2),
        )
