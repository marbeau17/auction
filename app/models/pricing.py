"""Pricing-related Pydantic models for the acquisition price pipeline
and integrated 3-step pricing engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AcquisitionPriceResult(BaseModel):
    """Result of Step 1 acquisition-price calculation."""

    recommended_price: int = Field(
        ...,
        description="Recommended acquisition price in yen",
        examples=[3500000],
    )
    max_price: int = Field(
        ...,
        description="Maximum allowable acquisition price in yen",
        examples=[3800000],
    )
    price_range_low: int = Field(
        ...,
        description="Lower bound of acceptable price range in yen",
        examples=[3325000],
    )
    price_range_high: int = Field(
        ...,
        description="Upper bound of acceptable price range in yen",
        examples=[3990000],
    )
    market_median: int = Field(
        ...,
        description="Weighted median market price in yen",
        examples=[3700000],
    )
    trend_factor: float = Field(
        ...,
        description="Market trend multiplier applied (clamped 0.80-1.20)",
        examples=[0.98],
    )
    safety_margin_rate: float = Field(
        ...,
        description="Safety margin rate applied (0.03-0.20)",
        examples=[0.07],
    )
    body_option_value: int = Field(
        ...,
        description="Body/option value added in yen",
        examples=[500000],
    )
    sample_count: int = Field(
        ...,
        description="Number of comparable vehicles used",
        ge=0,
        examples=[12],
    )
    confidence: str = Field(
        ...,
        description="Confidence level based on sample count",
        examples=["high"],
    )
    trend_direction: str = Field(
        ...,
        description="Market trend direction (up / stable / down)",
        examples=["stable"],
    )
    comparable_stats: Optional[dict] = Field(
        default=None,
        description="Statistical summary of comparable vehicle prices",
    )


# ------------------------------------------------------------------ #
# Step 2: Residual value scenario analysis
# ------------------------------------------------------------------ #


class ScenarioValue(BaseModel):
    """A single scenario outcome (bull / base / bear)."""

    label: str = Field(
        ..., description="Scenario label", examples=["bull"]
    )
    multiplier: float = Field(
        ..., description="Multiplier applied to base residual", examples=[1.15]
    )
    residual_value: int = Field(
        ...,
        description="Residual value under this scenario (yen)",
        examples=[1_150_000],
    )


class ResidualValueResult(BaseModel):
    """Result of residual value calculation with scenario analysis."""

    base_residual_value: int = Field(
        ..., description="Base-case residual value (yen)", examples=[1_000_000]
    )
    scenarios: list[ScenarioValue] = Field(
        ..., description="Bull / Base / Bear scenario outcomes"
    )
    depreciation_method: str = Field(
        ..., description="Depreciation method used", examples=["declining_200"]
    )
    body_type: str = Field(
        ..., description="Body type used for retention lookup", examples=["ウイング"]
    )
    body_retention_rate: float = Field(
        ..., description="Body retention rate applied", examples=[0.80]
    )
    mileage_adjustment: float = Field(
        ..., description="Mileage adjustment factor applied", examples=[1.0]
    )
    useful_life_years: int = Field(
        ...,
        description="Useful life in years for the vehicle class",
        examples=[9],
    )
    elapsed_years: float = Field(
        ..., description="Elapsed years since registration", examples=[3.5]
    )
    remaining_useful_life_years: float = Field(
        ..., description="Remaining useful life in years", examples=[5.5]
    )


# ------------------------------------------------------------------ #
# Step 3: Lease price calculation
# ------------------------------------------------------------------ #


class LeaseFeeBreakdown(BaseModel):
    """Monthly lease fee breakdown by component (all amounts in JPY)."""

    depreciation_portion: int = Field(
        ...,
        description="Monthly depreciation recovery: (acquisition - residual) / months",
        examples=[83334],
    )
    investor_dividend_portion: int = Field(
        ...,
        description="Monthly investor dividend: acquisition * yield_rate / 12",
        examples=[33334],
    )
    am_fee_portion: int = Field(
        ...,
        description="Monthly AM fee: acquisition * am_fee_rate / 12",
        examples=[8334],
    )
    placement_fee_portion: int = Field(
        ...,
        description="Amortised placement fee: acquisition * placement_rate / months",
        examples=[5000],
    )
    accounting_fee_portion: int = Field(
        ...,
        description="Fixed monthly accounting fee",
        examples=[50000],
    )
    operator_margin_portion: int = Field(
        ...,
        description="Operator margin: (acquisition - residual) * margin_rate / months",
        examples=[1667],
    )
    total_monthly_fee: int = Field(
        ...,
        description="Sum of all monthly fee components",
        examples=[181669],
    )


class LeasePriceResult(BaseModel):
    """Complete lease pricing result."""

    monthly_lease_fee: int = Field(
        ...,
        description="Monthly lease fee (tax-exclusive) in JPY",
        examples=[181669],
    )
    monthly_lease_fee_tax_incl: int = Field(
        ...,
        description="Monthly lease fee (tax-inclusive, 10%) in JPY",
        examples=[199836],
    )
    annual_lease_fee: int = Field(
        ...,
        description="Annual lease fee (tax-exclusive) in JPY",
        examples=[2180028],
    )
    total_lease_fee: int = Field(
        ...,
        description="Total lease fee over the full term (tax-exclusive) in JPY",
        examples=[6540084],
    )
    fee_breakdown: LeaseFeeBreakdown = Field(
        ...,
        description="Monthly fee breakdown by component",
    )
    effective_yield_rate: float = Field(
        ...,
        description="Effective annual yield rate for the investor (decimal)",
        examples=[0.0823],
    )
    breakeven_month: Optional[int] = Field(
        default=None,
        description="Month at which cumulative income exceeds net investment",
        ge=1,
        examples=[24],
    )


# ------------------------------------------------------------------ #
# Step 4: NAV (Net Asset Value) curve points
# ------------------------------------------------------------------ #


class NAVPoint(BaseModel):
    """A single month's snapshot on the NAV curve."""

    month: int = Field(
        ..., description="Month number (1-based)", ge=1, examples=[12]
    )
    asset_book_value: int = Field(
        ...,
        description="Depreciated book value of the asset at this month (yen)",
        examples=[2_800_000],
    )
    cumulative_lease_income: int = Field(
        ...,
        description="Total lease income received up to this month (yen)",
        examples=[1_200_000],
    )
    cumulative_costs: int = Field(
        ...,
        description="Total costs incurred up to this month (yen)",
        examples=[600_000],
    )
    cumulative_profit: int = Field(
        ...,
        description="Cumulative profit = income - costs (yen)",
        examples=[600_000],
    )
    nav: int = Field(
        ...,
        description="Net Asset Value = book_value + cumulative_income - cumulative_costs (yen)",
        examples=[3_400_000],
    )
    termination_value: int = Field(
        ...,
        description="Recovery value if the deal is terminated at this month (yen)",
        examples=[2_980_000],
    )


# ------------------------------------------------------------------ #
# Pricing master: parameter presets
# ------------------------------------------------------------------ #


class PricingMasterCreate(BaseModel):
    """Input for creating/updating pricing parameter master."""

    name: str = Field(..., description="Pricing master name", examples=["標準パラメータ"])
    description: Optional[str] = Field(
        default=None, description="Description", examples=["デフォルトのプライシングマスタ"]
    )
    fund_id: Optional[UUID] = Field(default=None, description="Associated fund ID")
    investor_yield_rate: float = Field(
        default=0.08,
        ge=0,
        le=1,
        description="Annual investor yield rate",
        examples=[0.08],
    )
    am_fee_rate: float = Field(
        default=0.02,
        ge=0,
        le=1,
        description="Annual AM fee rate",
        examples=[0.02],
    )
    placement_fee_rate: float = Field(
        default=0.03,
        ge=0,
        le=1,
        description="One-time placement fee rate",
        examples=[0.03],
    )
    accounting_fee_monthly: int = Field(
        default=50000,
        ge=0,
        description="Monthly accounting fee (JPY)",
        examples=[50000],
    )
    operator_margin_rate: float = Field(
        default=0.02,
        ge=0,
        le=1,
        description="Operator margin rate",
        examples=[0.02],
    )
    safety_margin_rate: float = Field(
        default=0.05,
        ge=0,
        le=0.5,
        description="Safety margin rate",
        examples=[0.05],
    )
    depreciation_method: Literal["declining_200", "straight_line"] = Field(
        default="declining_200",
        description="Depreciation method",
        examples=["declining_200"],
    )


class PricingMasterResponse(BaseModel):
    """Pricing master record response."""

    id: UUID = Field(..., description="Pricing master record ID")
    name: str = Field(..., description="Pricing master name")
    description: Optional[str] = Field(default=None, description="Description")
    fund_id: Optional[UUID] = Field(default=None, description="Associated fund ID")
    investor_yield_rate: float = Field(
        ..., description="Annual investor yield rate", examples=[0.08]
    )
    am_fee_rate: float = Field(
        ..., description="Annual AM fee rate", examples=[0.02]
    )
    placement_fee_rate: float = Field(
        ..., description="One-time placement fee rate", examples=[0.03]
    )
    accounting_fee_monthly: int = Field(
        ..., description="Monthly accounting fee (JPY)", examples=[50000]
    )
    operator_margin_rate: float = Field(
        ..., description="Operator margin rate", examples=[0.02]
    )
    safety_margin_rate: float = Field(
        ..., description="Safety margin rate", examples=[0.05]
    )
    depreciation_method: str = Field(
        ..., description="Depreciation method", examples=["declining_200"]
    )
    is_active: bool = Field(..., description="Whether this master is active")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------ #
# Integrated pricing: input and orchestrated result
# ------------------------------------------------------------------ #


class IntegratedPricingInput(BaseModel):
    """Input parameters for the 3-step integrated pricing pipeline."""

    # Vehicle identification
    maker: str = Field(
        ..., description="Vehicle manufacturer", examples=["いすゞ"]
    )
    model: str = Field(
        ..., description="Vehicle model name", examples=["エルフ"]
    )
    model_code: Optional[str] = Field(
        default=None, description="Vehicle model code", examples=["TRG-NMR85AN"]
    )
    registration_year_month: str = Field(
        ...,
        description="First registration year-month (YYYY-MM)",
        examples=["2020-04"],
    )
    mileage_km: int = Field(
        ..., description="Current mileage in km", ge=0, examples=[85000]
    )
    vehicle_class: str = Field(
        ...,
        description="Vehicle class (小型 / 中型 / 大型 / トレーラーヘッド / 被けん引車)",
        examples=["小型"],
    )
    body_type: str = Field(
        ..., description="Body type", examples=["平ボディ"]
    )
    payload_ton: Optional[float] = Field(
        default=None, description="Payload capacity in tons", ge=0, examples=[2.0]
    )
    body_option_value: int = Field(
        default=0,
        description="Body/option value added (yen)",
        ge=0,
        examples=[500000],
    )

    # Lease parameters
    lease_term_months: int = Field(
        ..., description="Lease term in months", ge=1, le=120, examples=[36]
    )

    # Pricing master (optional - use defaults if not provided)
    pricing_master_id: Optional[UUID] = Field(
        default=None, description="Pricing master ID to use for calculation"
    )

    # Optional parameter overrides (take precedence over pricing_master)
    investor_yield_rate: Optional[float] = Field(
        default=None,
        description="Investor yield rate override (annual, decimal)",
        examples=[0.08],
    )
    am_fee_rate: Optional[float] = Field(
        default=None,
        description="AM fee rate override (annual, decimal)",
        examples=[0.02],
    )
    placement_fee_rate: Optional[float] = Field(
        default=None,
        description="Placement fee rate override (lump-sum, decimal)",
        examples=[0.03],
    )
    accounting_fee_monthly: Optional[int] = Field(
        default=None,
        description="Monthly accounting fee override (yen)",
        examples=[50000],
    )
    operator_margin_rate: Optional[float] = Field(
        default=None,
        description="Operator margin rate override (decimal)",
        examples=[0.02],
    )
    safety_margin_rate: Optional[float] = Field(
        default=None,
        description="Safety margin rate override (decimal)",
        examples=[0.05],
    )
    depreciation_method: Optional[str] = Field(
        default=None,
        description="Depreciation method override",
        examples=["declining_200"],
    )

    # Optional book value (used to cap acquisition price)
    book_value: Optional[int] = Field(
        default=None,
        description="Current book value (yen), used to cap acquisition price",
        ge=0,
        examples=[3200000],
    )


class IntegratedPricingResult(BaseModel):
    """Combined result from the 3-step integrated pricing pipeline + NAV curve."""

    # Step 1
    acquisition: AcquisitionPriceResult = Field(
        ..., description="Step 1: Acquisition price calculation result"
    )
    # Step 2
    residual: ResidualValueResult = Field(
        ..., description="Step 2: Residual value calculation result"
    )
    # Step 3
    lease: LeasePriceResult = Field(
        ..., description="Step 3: Lease price calculation result"
    )
    # NAV curve
    nav_curve: list[NAVPoint] = Field(
        ..., description="Month-by-month NAV curve"
    )
    profit_conversion_month: int = Field(
        ...,
        description="Month at which cumulative profit turns positive (利益転換月)",
        examples=[24],
    )
    # Deal assessment
    assessment: Literal["推奨", "要検討", "非推奨"] = Field(
        ..., description="Overall deal assessment", examples=["推奨"]
    )
    assessment_reasons: list[str] = Field(
        ...,
        description="Assessment reason strings (Japanese)",
        examples=[["損益分岐月がリース期間の60%以内", "実効利回りが6%以上"]],
    )


class IntegratedPricingResponse(BaseModel):
    """API response wrapper for integrated pricing."""

    id: UUID = Field(..., description="Pricing result record ID")
    simulation_id: Optional[UUID] = Field(
        default=None, description="Associated simulation ID"
    )
    input_data: IntegratedPricingInput = Field(
        ..., description="Input parameters used for this calculation"
    )
    result: IntegratedPricingResult = Field(
        ..., description="Integrated pricing result"
    )
    pricing_master_used: Optional[PricingMasterResponse] = Field(
        default=None, description="Pricing master record used for calculation"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")

    model_config = {"from_attributes": True}
