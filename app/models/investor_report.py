"""Pydantic models for the monthly investor report feature (INV-004).

These mirror the schema defined in
``supabase/migrations/20260417000004_investor_reports.sql``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


RiskSeverity = Literal["info", "warning", "critical"]


class RiskFlag(BaseModel):
    """A single risk indicator attached to a monthly investor report.

    Typical codes (non-exhaustive):
    - ``nfav_below_60``     — Net Fund Asset Value dropped below the 60% floor.
    - ``ltv_breach``        — At least one vehicle has LTV > 60%.
    - ``overdue_payment``   — One or more lease payments are 30+ days late.
    - ``default_risk``      — Lessee entered 90+ day delinquency.
    - ``dividend_shortfall``— Scheduled dividend not fully funded by cash.
    """

    code: str = Field(..., description="Machine-readable risk code", examples=["nfav_below_60"])
    severity: RiskSeverity = Field(..., description="Severity tier", examples=["warning"])
    message: str = Field(..., description="Human-readable description (JP)",
                         examples=["NFAVが60%を下回りました"])
    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional payload (metrics, offending IDs) for drill-through.",
    )


class InvestorReportBase(BaseModel):
    """Fields common to create/response variants."""

    fund_id: UUID = Field(..., description="Fund (SPC) identifier")
    report_month: date = Field(..., description="Reporting period (first-of-month)",
                               examples=["2026-04-01"])
    storage_path: str = Field(..., description="Path within the investor-reports bucket")
    nav_total: int = Field(default=0, description="Total Net Asset Value at month end (JPY)", ge=0)
    dividend_paid: int = Field(default=0, description="Dividend paid this month (JPY)", ge=0)
    dividend_scheduled: int = Field(default=0, description="Dividend scheduled next month (JPY)", ge=0)
    risk_flags: list[RiskFlag] = Field(default_factory=list, description="Risk indicators")

    @field_validator("report_month")
    @classmethod
    def _must_be_first_of_month(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError("report_month must be the first day of a month (YYYY-MM-01)")
        return v


class InvestorReportCreate(InvestorReportBase):
    """Payload used when persisting a freshly generated report."""

    generated_by: Optional[UUID] = Field(
        default=None, description="User who triggered generation (None for scheduled runs)"
    )


class InvestorReport(InvestorReportBase):
    """Full investor report row as stored in the database."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Primary key")
    generated_at: datetime = Field(..., description="Timestamp the PDF was produced")
    generated_by: Optional[UUID] = Field(default=None)
    created_at: datetime
    updated_at: datetime


class InvestorReportResponse(InvestorReport):
    """API response wrapper — identical shape as :class:`InvestorReport`.

    Kept as a distinct class so we can diverge (e.g. add signed download URLs)
    without breaking internal repo typing.
    """

    download_url: Optional[str] = Field(
        default=None,
        description="Optional freshly-minted signed download URL (15-min TTL).",
    )


class InvestorReportGenerateRequest(BaseModel):
    """Body for POST /api/v1/investor-reports/generate."""

    fund_id: UUID = Field(..., description="Target fund")
    report_month: date = Field(..., description="Reporting month (first-of-month)")

    @field_validator("report_month")
    @classmethod
    def _normalize_first_of_month(cls, v: date) -> date:
        # Be lenient on input: any day in the target month is accepted, we
        # anchor to the first.
        return v.replace(day=1)


class SignedDownloadResponse(BaseModel):
    """Response body for the download-URL endpoint."""

    download_url: str = Field(..., description="Fully-qualified URL with token query parameter")
    expires_at: datetime = Field(..., description="Token expiry (UTC)")
