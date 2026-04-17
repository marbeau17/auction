"""Centralized pricing constants for the integrated 3-step engine.

Re-exported here per spec (change_request_v2 §3.1.1) so the magic numbers
scattered across acquisition_price / residual_value_v2 / lease_price /
integrated_pricing have a single source of truth.

The individual calculator classes keep their own class attributes for
backwards compatibility; those are wired to these values so a change here
propagates everywhere.
"""

from __future__ import annotations


# ------------------------------------------------------------------ #
# Step 1: Acquisition price
# ------------------------------------------------------------------ #

# Market trend multiplier bounds (clamped to this range so outlier moves
# don't dominate the calculation).
TREND_FLOOR: float = 0.80
TREND_CEILING: float = 1.20

# Safety margin rate bounds applied on top of the category base margin.
MIN_SAFETY_MARGIN: float = 0.03
MAX_SAFETY_MARGIN: float = 0.20

# Volatility premium multiplier used when estimating safety margin from
# the standard-deviation-to-median ratio.
DEFAULT_VOLATILITY_PREMIUM: float = 1.5

# Category-level base safety margins.
SAFETY_MARGINS_BY_CATEGORY: dict[str, float] = {
    "SMALL": 0.05,
    "MEDIUM": 0.05,
    "LARGE": 0.07,
    "TRAILER_HEAD": 0.08,
    "TRAILER_CHASSIS": 0.06,
}

# Comparable-vehicle search bounds.
COMPARABLE_MAX_RESULTS: int = 30
COMPARABLE_YEAR_RANGE: int = 2
COMPARABLE_MILEAGE_RATIO: float = 0.30


# ------------------------------------------------------------------ #
# Step 2: Residual value scenarios
# ------------------------------------------------------------------ #

SCENARIO_MULTIPLIERS: dict[str, float] = {
    "bull": 1.15,
    "base": 1.00,
    "bear": 0.85,
}


# ------------------------------------------------------------------ #
# Step 3: Lease price / integrated defaults
# ------------------------------------------------------------------ #

# Consumption tax rate applied when producing tax-inclusive lease figures.
CONSUMPTION_TAX_RATE: float = 0.10

# Defaults used when neither a pricing_master nor input-level overrides
# supply a value. Mirrors IntegratedPricingEngine._DEFAULTS.
DEFAULT_PRICING_PARAMS: dict[str, float | int | str] = {
    "investor_yield_rate": 0.08,
    "am_fee_rate": 0.02,
    "placement_fee_rate": 0.03,
    "accounting_fee_monthly": 50_000,
    "operator_margin_rate": 0.02,
    "safety_margin_rate": 0.05,
    "depreciation_method": "declining_200",
}


# ------------------------------------------------------------------ #
# NAV / termination
# ------------------------------------------------------------------ #

# Discount applied when computing termination_value for forced-sale
# scenarios on the NAV curve.
FORCED_SALE_DISCOUNT: float = 0.85
