"""Pydantic models for Phase-2C Global Liquidation system.

Covers the liquidation case state machine, append-only event log, NLV
estimates across the four disposal routes (domestic_resale, export,
auction, scrap), and the routing decision record.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enumerations (as Literal types so they serialize nicely to JSON/DB CHECKs)
# ---------------------------------------------------------------------------

TriggeredBy = Literal["default", "maturity", "voluntary"]
CaseStatus = Literal["assessing", "routing", "listed", "sold", "closed", "cancelled"]
Route = Literal["domestic_resale", "export", "auction", "scrap"]


# ---------------------------------------------------------------------------
# Cost breakdown
# ---------------------------------------------------------------------------


class CostBreakdown(BaseModel):
    """Per-route cost components (JPY)."""

    transport: int = Field(default=0, ge=0, description="Transport / freight cost")
    customs: int = Field(default=0, ge=0, description="Customs duty / import tariff")
    inspection: int = Field(default=0, ge=0, description="JEVIC / inspection fees")
    yard: int = Field(default=0, ge=0, description="Yard storage fees")
    commission: int = Field(default=0, ge=0, description="Broker / auction commission")

    @property
    def total(self) -> int:
        return self.transport + self.customs + self.inspection + self.yard + self.commission


# ---------------------------------------------------------------------------
# NLV estimate & routing decision
# ---------------------------------------------------------------------------


class NLVEstimate(BaseModel):
    """Net Liquidation Value estimate for a single disposal route."""

    route: Route = Field(..., description="Disposal channel being evaluated")
    gross_proceeds_jpy: int = Field(..., description="Estimated gross sale proceeds (JPY)")
    cost_deductions_jpy: int = Field(..., ge=0, description="Total cost deductions (JPY)")
    net_jpy: int = Field(..., description="Net Liquidation Value = gross - costs (JPY)")
    cost_breakdown: CostBreakdown = Field(
        default_factory=CostBreakdown,
        description="Itemised cost components",
    )
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Confidence score 0-1 (higher = more reliable estimate)",
    )
    rationale: Optional[str] = Field(
        default=None, description="Human-readable reasoning for this estimate"
    )


class RoutingDecision(BaseModel):
    """Final committed routing decision for a liquidation case."""

    route: Route = Field(..., description="Committed disposal channel")
    nlv_jpy: int = Field(..., description="Committed NLV estimate (JPY)")
    cost_breakdown: CostBreakdown = Field(
        default_factory=CostBreakdown, description="Cost breakdown used"
    )
    closure_deadline: date = Field(..., description="Deadline to close this case")
    alternatives: list[NLVEstimate] = Field(
        default_factory=list,
        description="All other routes considered (audit trail)",
    )
    rationale: Optional[str] = Field(
        default=None, description="Why this route was chosen over alternatives"
    )


# ---------------------------------------------------------------------------
# Case create / read models
# ---------------------------------------------------------------------------


class LiquidationCaseCreate(BaseModel):
    """Request body for creating a liquidation case."""

    vehicle_id: UUID = Field(..., description="Vehicle under liquidation")
    sab_id: Optional[UUID] = Field(default=None, description="Optional SAB link")
    fund_id: Optional[UUID] = Field(default=None, description="Optional fund link")
    triggered_by: TriggeredBy = Field(..., description="Why liquidation was triggered")
    notes: Optional[str] = Field(default=None, description="Free-form notes")


class LiquidationCase(BaseModel):
    """Full liquidation case record."""

    id: UUID
    vehicle_id: UUID
    sab_id: Optional[UUID] = None
    fund_id: Optional[UUID] = None
    triggered_by: TriggeredBy
    status: CaseStatus
    detected_at: datetime
    assessed_by: Optional[UUID] = None
    assessment_deadline: date
    closure_deadline: date
    route: Optional[Route] = None
    nlv_jpy: Optional[int] = None
    realized_price_jpy: Optional[int] = None
    cost_breakdown: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


class LiquidationEvent(BaseModel):
    """Append-only liquidation event."""

    id: Optional[UUID] = None
    case_id: UUID
    event_type: str = Field(
        ...,
        description=(
            "Event category — e.g. case_created, nlv_estimated, "
            "route_committed, listed, sold, closed, cancelled, note"
        ),
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_user_id: Optional[UUID] = None
    occurred_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CaseWithEvents(BaseModel):
    """Case detail view including its event history."""

    case: LiquidationCase
    events: list[LiquidationEvent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Request bodies for status-transition endpoints
# ---------------------------------------------------------------------------


class RouteCommitRequest(BaseModel):
    """POST /cases/{id}/route body."""

    route: Route
    nlv_jpy: int
    cost_breakdown: CostBreakdown = Field(default_factory=CostBreakdown)
    rationale: Optional[str] = None


class CloseCaseRequest(BaseModel):
    """POST /cases/{id}/close body."""

    realized_price_jpy: int = Field(..., ge=0)
    cost_breakdown: Optional[CostBreakdown] = None
    notes: Optional[str] = None
