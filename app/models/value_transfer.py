"""Pydantic models for the Value Transfer Engine.

The Value Transfer Engine sits on top of Epic 6 invoicing. For every
billing period it:

1. Aggregates realised income (invoices whose ``status`` is ``paid`` or
   ``sent`` within the period).
2. Deducts stakeholder fees (mirroring ``app.core.lease_price`` but on
   realised — not planned — income).
3. Produces a plan of transfer instructions that downstream treasury
   systems execute. The engine itself NEVER moves money.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Roles used in both StakeholderShare and TransferInstruction
StakeholderRoleType = Literal[
    "accountant",
    "operator",
    "placement_agent",
    "asset_manager",
    "investor",
    "spc",
]

AllocationStatusType = Literal["draft", "approved", "executed"]
InstructionStatusType = Literal["planned", "sent", "failed"]


# ---------------------------------------------------------------------------
# Per-stakeholder amount
# ---------------------------------------------------------------------------


class StakeholderShare(BaseModel):
    """Amount assigned to a single stakeholder role for a period."""

    role: StakeholderRoleType = Field(
        ..., description="Stakeholder role receiving the distribution"
    )
    amount_jpy: int = Field(
        ..., description="Amount in JPY", ge=0
    )
    basis: str = Field(
        ...,
        description=(
            "Short label describing how the amount was derived "
            "(e.g. 'fixed_monthly', 'operator_margin_rate', "
            "'placement_fee_amortized', 'am_fee_monthly', "
            "'investor_yield_monthly', 'residual')"
        ),
    )


# ---------------------------------------------------------------------------
# Value allocation for a period
# ---------------------------------------------------------------------------


class ValueAllocation(BaseModel):
    """Per-period allocation of realised income across all stakeholders.

    The sum of all ``shares[*].amount_jpy`` must equal ``gross_income``
    on a happy path (``reconciliation_diff == 0``).
    """

    fund_id: UUID = Field(..., description="Target fund (SPC) identifier")
    period_start: date = Field(..., description="Inclusive start date of the period")
    period_end: date = Field(..., description="Inclusive end date of the period")

    gross_income: int = Field(
        ...,
        description="Sum of invoice subtotals (tax-excl.) for paid/sent invoices in the period",
        ge=0,
    )
    net_income: int = Field(
        ...,
        description="Gross income minus all fee deductions (retained by SPC)",
    )

    # Canonical deduction order — see ValueTransferEngine.FEE_DEDUCTION_ORDER.
    shares: list[StakeholderShare] = Field(
        default_factory=list,
        description="Per-role breakdown of the gross income",
    )

    reconciliation_diff: int = Field(
        default=0,
        description="gross_income - sum(share.amount_jpy). Expected 0 on happy path.",
    )

    # Persistence-layer fields (populated after DB write)
    id: Optional[UUID] = Field(default=None, description="DB identifier (None before persistence)")
    status: AllocationStatusType = Field(
        default="draft", description="Lifecycle status"
    )
    created_at: Optional[datetime] = Field(default=None, description="Row created at")
    approved_at: Optional[datetime] = Field(default=None, description="Row approved at")
    approved_by: Optional[UUID] = Field(default=None, description="Approver user id")


# ---------------------------------------------------------------------------
# Transfer instruction (plan-only; no money movement)
# ---------------------------------------------------------------------------


class TransferInstruction(BaseModel):
    """A single planned fund movement from the SPC account to a stakeholder.

    The ``from_account`` is always the SPC cash account for the fund;
    ``to_stakeholder_role`` identifies the recipient role. The actual
    bank destination is resolved by downstream treasury using the
    ``stakeholders`` address book.
    """

    id: Optional[UUID] = Field(default=None, description="DB identifier (None before persistence)")
    allocation_id: Optional[UUID] = Field(
        default=None, description="Parent value_allocation identifier"
    )
    from_account: str = Field(
        default="spc_cash",
        description="Logical source account (always 'spc_cash' in Phase 2)",
    )
    to_stakeholder_role: StakeholderRoleType = Field(
        ..., description="Recipient stakeholder role"
    )
    amount_jpy: int = Field(..., description="Amount in JPY", ge=0)
    memo: str = Field(
        ...,
        description="Human-readable memo (used on the wire / ledger line)",
    )
    status: InstructionStatusType = Field(
        default="planned", description="Execution status"
    )
    created_at: Optional[datetime] = Field(default=None, description="Row created at")
    executed_at: Optional[datetime] = Field(default=None, description="Row executed at")


# ---------------------------------------------------------------------------
# Full distribution plan
# ---------------------------------------------------------------------------


class DistributionPlan(BaseModel):
    """The complete plan derived from a ValueAllocation."""

    allocation_id: Optional[UUID] = Field(
        default=None, description="Parent value_allocation identifier"
    )
    fund_id: UUID = Field(..., description="Target fund identifier")
    period_start: date = Field(..., description="Inclusive start date of the period")
    period_end: date = Field(..., description="Inclusive end date of the period")

    instructions: list[TransferInstruction] = Field(
        default_factory=list,
        description="Ordered list of transfer instructions",
    )

    total_planned: int = Field(
        default=0,
        description="Sum of all instruction amounts (should equal gross_income)",
        ge=0,
    )
