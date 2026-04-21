"""Leaseback simulation Pydantic models."""

import re
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_YEAR_MONTH_RE = re.compile(r"^\s*(\d{4})(?:[-/](\d{1,2}))?\s*$")


class SimulationInput(BaseModel):
    """Input parameters for leaseback simulation."""

    maker: str = Field(..., description="Vehicle manufacturer", examples=["いすゞ"])
    model: str = Field(..., description="Vehicle model name", examples=["エルフ"])
    model_code: Optional[str] = Field(
        default=None, description="Vehicle model code", examples=["TRG-NMR85AN"]
    )
    registration_year_month: str = Field(
        ...,
        description="First registration year and month (YYYY-MM)",
        examples=["2020-04"],
    )
    mileage_km: int = Field(
        ..., description="Current mileage in km", ge=0, examples=[85000]
    )
    acquisition_price: int = Field(
        ..., description="Original acquisition price in yen", ge=0, examples=[6000000]
    )
    book_value: int = Field(
        ..., description="Current book value in yen", ge=0, examples=[3200000]
    )
    vehicle_class: str = Field(
        ..., description="Vehicle class (small/medium/large)", examples=["小型"]
    )
    payload_ton: Optional[float] = Field(
        default=None, description="Payload capacity in tons", ge=0, examples=[2.0]
    )
    body_type: str = Field(
        ..., description="Vehicle body type", examples=["平ボディ"]
    )
    body_option_value: Optional[int] = Field(
        default=None,
        description="Body/option additional value in yen",
        ge=0,
        examples=[500000],
    )
    target_yield_rate: float = Field(
        ...,
        description="Target yield rate (annual, decimal)",
        ge=0,
        le=1,
        examples=[0.08],
    )
    lease_term_months: int = Field(
        ..., description="Lease term in months", ge=1, le=120, examples=[36]
    )
    residual_rate: Optional[float] = Field(
        default=None,
        description="Residual value rate at lease end (decimal)",
        ge=0,
        le=1,
        examples=[0.10],
    )
    insurance_monthly: Optional[int] = Field(
        default=None,
        description="Monthly insurance cost in yen",
        ge=0,
        examples=[15000],
    )
    maintenance_monthly: Optional[int] = Field(
        default=None,
        description="Monthly maintenance cost in yen",
        ge=0,
        examples=[10000],
    )
    remarks: Optional[str] = Field(
        default=None, description="Additional remarks", examples=["特記事項なし"]
    )

    @field_validator("registration_year_month", mode="before")
    @classmethod
    def _normalize_registration_year_month(cls, v: object) -> str:
        # Form posts can come in as int (year-only select) or string. Accept both
        # YYYY and YYYY-MM (also YYYY/MM) and normalize to YYYY-MM with month
        # defaulting to 01 when omitted.
        if v is None:
            raise ValueError("registration_year_month is required")
        s = str(v).strip()
        match = _YEAR_MONTH_RE.match(s)
        if not match:
            raise ValueError(
                "registration_year_month must be 'YYYY' or 'YYYY-MM'"
            )
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else 1
        if not (1 <= month <= 12):
            raise ValueError("month component must be between 1 and 12")
        return f"{year:04d}-{month:02d}"


class MonthlyScheduleItem(BaseModel):
    """Monthly breakdown item in the lease schedule."""

    month: int = Field(..., description="Month number (1-based)", ge=1, examples=[1])
    asset_value: int = Field(
        ..., description="Asset book value at this month in yen", examples=[3100000]
    )
    lease_income: int = Field(
        ..., description="Lease income for this month in yen", examples=[120000]
    )
    cumulative_income: int = Field(
        ..., description="Cumulative lease income in yen", examples=[120000]
    )
    depreciation_expense: int = Field(
        ..., description="Depreciation expense for this month in yen", examples=[80000]
    )
    financing_cost: int = Field(
        ..., description="Financing cost for this month in yen", examples=[20000]
    )
    monthly_profit: int = Field(
        ..., description="Net profit for this month in yen", examples=[20000]
    )
    cumulative_profit: int = Field(
        ..., description="Cumulative net profit in yen", examples=[20000]
    )
    termination_loss: int = Field(
        ...,
        description="Estimated loss if lease is terminated at this month in yen",
        examples=[-500000],
    )


class SimulationResult(BaseModel):
    """Output result of a leaseback simulation."""

    max_purchase_price: int = Field(
        ..., description="Maximum allowable purchase price in yen", examples=[3800000]
    )
    recommended_purchase_price: int = Field(
        ..., description="Recommended purchase price in yen", examples=[3500000]
    )
    estimated_residual_value: int = Field(
        ...,
        description="Estimated residual value at lease end in yen",
        examples=[350000],
    )
    residual_rate_result: float = Field(
        ...,
        description="Resulting residual value rate (decimal)",
        ge=0,
        le=1,
        examples=[0.10],
    )
    monthly_lease_fee: int = Field(
        ..., description="Monthly lease fee in yen", examples=[120000]
    )
    total_lease_fee: int = Field(
        ..., description="Total lease fee over the full term in yen", examples=[4320000]
    )
    breakeven_months: Optional[int] = Field(
        default=None,
        description="Number of months to breakeven",
        ge=0,
        examples=[24],
    )
    effective_yield_rate: float = Field(
        ..., description="Effective yield rate (annual, decimal)", examples=[0.082]
    )
    market_median_price: int = Field(
        ...,
        description="Median market price for comparable vehicles in yen",
        examples=[3600000],
    )
    market_sample_count: int = Field(
        ..., description="Number of market samples used", ge=0, examples=[15]
    )
    market_deviation_rate: float = Field(
        ...,
        description="Deviation rate from market median (decimal)",
        examples=[-0.028],
    )
    assessment: Literal["推奨", "要検討", "非推奨"] = Field(
        ..., description="Overall deal assessment", examples=["推奨"]
    )
    monthly_schedule: list[MonthlyScheduleItem] = Field(
        ..., description="Month-by-month lease schedule"
    )


class SimulationResponse(BaseModel):
    """Full simulation response including metadata."""

    id: UUID = Field(..., description="Simulation record ID")
    user_id: UUID = Field(..., description="User who created the simulation")
    title: str = Field(
        ..., description="Simulation title", examples=["いすゞ エルフ 2020年式 シミュレーション"]
    )
    input_data: SimulationInput = Field(
        ..., description="Input parameters used for this simulation"
    )
    result: SimulationResult = Field(..., description="Simulation result")
    status: str = Field(
        ..., description="Simulation status", examples=["completed"]
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = {"from_attributes": True}
