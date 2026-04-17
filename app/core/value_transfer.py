"""Value Transfer Engine — per-period value allocation across stakeholders.

The engine sits on top of Epic 6 invoicing. For a given (fund, period)
it sums realised lease income, deducts stakeholder fees in a canonical
order, and emits a :class:`ValueAllocation` plus a
:class:`DistributionPlan` of :class:`TransferInstruction` rows.

Money is NEVER actually moved here — the engine is plan-only.

Fee deduction order (applied in this strict order so reconciliation is
deterministic):

1. **accounting_fee** — fixed monthly, from ``pricing_masters.accounting_fee_monthly``
2. **operator_margin** — ``gross_income * operator_margin_rate``
3. **placement_fee_amortized** — monthly amortised portion of the
   upfront placement fee: ``acquisition_price * placement_fee_rate /
   lease_term_months`` (prorated by the months covered in the period)
4. **am_fee** — ``gross_income * am_fee_rate / 12`` per month within
   the period, capped at ``gross_income * am_fee_rate / 12 * months``
5. **investor_dividend** — ``gross_income * investor_yield_rate / 12`` per
   month within the period
6. **residual_to_spc** — whatever is left (retained by the SPC for
   depreciation recovery and reserve buffer)

All intermediate amounts are integer JPY. Fee components use
``math.floor`` (the platform absorbs rounding residue in
``residual_to_spc`` so the reconciliation_diff is always zero).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional
from uuid import UUID

import structlog

from app.models.value_transfer import (
    DistributionPlan,
    StakeholderShare,
    TransferInstruction,
    ValueAllocation,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Default pricing parameters (fallback when no pricing_master row exists)
# Mirrors app.core.lease_price defaults.
# ---------------------------------------------------------------------------

DEFAULT_ACCOUNTING_FEE_MONTHLY = 50_000
DEFAULT_OPERATOR_MARGIN_RATE = 0.02
DEFAULT_PLACEMENT_FEE_RATE = 0.03
DEFAULT_AM_FEE_RATE = 0.02
DEFAULT_INVESTOR_YIELD_RATE = 0.08


@dataclass(frozen=True)
class _PricingParams:
    """Snapshot of the pricing parameters used for a computation."""

    accounting_fee_monthly: int
    operator_margin_rate: float
    placement_fee_rate: float
    am_fee_rate: float
    investor_yield_rate: float


@dataclass(frozen=True)
class _ContractContext:
    """Aggregated contract context needed for amortisation calculations."""

    total_acquisition_price: int
    # Representative lease term — when the fund has many contracts we use
    # the weighted average (rounded up) because the placement fee is
    # amortised over the per-contract term.
    representative_lease_term_months: int


class ValueTransferEngine:
    """Compute per-period value allocations and distribution plans.

    This class is stateless aside from the injected Supabase-like client.
    All methods are deterministic given identical inputs; the engine
    performs no side effects outside of the passed client.
    """

    #: Canonical fee-deduction order (see module docstring).
    FEE_DEDUCTION_ORDER: tuple[str, ...] = (
        "accounting_fee",
        "operator_margin",
        "placement_fee_amortized",
        "am_fee",
        "investor_dividend",
        "residual_to_spc",
    )

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_period_allocation(
        self,
        fund_id: UUID,
        period_start: date,
        period_end: date,
    ) -> ValueAllocation:
        """Compute the :class:`ValueAllocation` for a fund and period.

        Parameters
        ----------
        fund_id:
            Target fund (SPC) identifier.
        period_start:
            Inclusive start date of the reporting period.
        period_end:
            Inclusive end date of the reporting period.

        Returns
        -------
        ValueAllocation
            Unsaved allocation; persist via the repository layer.
        """
        if period_end < period_start:
            raise ValueError(
                f"period_end ({period_end}) must be >= period_start ({period_start})"
            )

        gross_income = self._sum_realised_income(fund_id, period_start, period_end)
        params = self._load_pricing_params(fund_id)
        ctx = self._load_contract_context(fund_id)
        months = self._months_in_period(period_start, period_end)

        shares = self._allocate(
            gross_income=gross_income,
            months=months,
            params=params,
            ctx=ctx,
        )

        total_allocated = sum(s.amount_jpy for s in shares)
        reconciliation_diff = gross_income - total_allocated

        # residual_to_spc absorbs rounding so diff is always zero in the
        # happy path. If caller somehow ended up with drift we surface
        # it as-is rather than silently masking it.
        net_income = next(
            (s.amount_jpy for s in shares if s.role == "spc"),
            0,
        )

        logger.info(
            "value_transfer_allocated",
            fund_id=str(fund_id),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            gross_income=gross_income,
            net_income=net_income,
            reconciliation_diff=reconciliation_diff,
        )

        return ValueAllocation(
            fund_id=fund_id,
            period_start=period_start,
            period_end=period_end,
            gross_income=gross_income,
            net_income=net_income,
            shares=shares,
            reconciliation_diff=reconciliation_diff,
            status="draft",
        )

    def generate_distribution_plan(
        self, allocation: ValueAllocation
    ) -> DistributionPlan:
        """Turn a ValueAllocation into a DistributionPlan (no side effects)."""
        instructions: list[TransferInstruction] = []
        period_label = f"{allocation.period_start.isoformat()}～{allocation.period_end.isoformat()}"

        for share in allocation.shares:
            if share.amount_jpy <= 0:
                continue
            instructions.append(
                TransferInstruction(
                    allocation_id=allocation.id,
                    from_account="spc_cash",
                    to_stakeholder_role=share.role,
                    amount_jpy=share.amount_jpy,
                    memo=f"{period_label} {share.basis}",
                    status="planned",
                )
            )

        return DistributionPlan(
            allocation_id=allocation.id,
            fund_id=allocation.fund_id,
            period_start=allocation.period_start,
            period_end=allocation.period_end,
            instructions=instructions,
            total_planned=sum(i.amount_jpy for i in instructions),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _allocate(
        self,
        *,
        gross_income: int,
        months: int,
        params: _PricingParams,
        ctx: _ContractContext,
    ) -> list[StakeholderShare]:
        """Apply the canonical fee-deduction order to ``gross_income``.

        The residual (what's left after deducting all stakeholder fees)
        is assigned to the SPC. All fees are floor-rounded so the
        residual always absorbs any rounding slack — this makes
        ``reconciliation_diff`` identically zero in the happy path.
        """
        if gross_income <= 0:
            # Zero-income edge case: every stakeholder gets zero.
            return [
                StakeholderShare(role="accountant", amount_jpy=0, basis="fixed_monthly"),
                StakeholderShare(role="operator", amount_jpy=0, basis="operator_margin_rate"),
                StakeholderShare(role="placement_agent", amount_jpy=0, basis="placement_fee_amortized"),
                StakeholderShare(role="asset_manager", amount_jpy=0, basis="am_fee_monthly"),
                StakeholderShare(role="investor", amount_jpy=0, basis="investor_yield_monthly"),
                StakeholderShare(role="spc", amount_jpy=0, basis="residual"),
            ]

        remaining = gross_income

        # 1. accounting_fee (fixed monthly × months, capped at remaining)
        accounting_fee = min(remaining, params.accounting_fee_monthly * months)
        remaining -= accounting_fee

        # 2. operator_margin = gross_income * operator_margin_rate
        operator_margin = min(
            remaining,
            math.floor(gross_income * params.operator_margin_rate),
        )
        remaining -= operator_margin

        # 3. placement_fee_amortized: prorated monthly share of the
        #    upfront placement fee amortised over the lease term.
        if ctx.representative_lease_term_months > 0:
            placement_monthly = math.floor(
                ctx.total_acquisition_price
                * params.placement_fee_rate
                / ctx.representative_lease_term_months
            )
        else:
            placement_monthly = 0
        placement_portion = min(remaining, placement_monthly * months)
        remaining -= placement_portion

        # 4. am_fee — capped at the annualised rate on gross_income
        am_fee_raw = math.floor(
            gross_income * params.am_fee_rate / 12 * months
        )
        am_cap = math.floor(gross_income * params.am_fee_rate)  # hard annual cap
        am_fee = min(remaining, am_fee_raw, am_cap)
        remaining -= am_fee

        # 5. investor_dividend
        investor_dividend = min(
            remaining,
            math.floor(gross_income * params.investor_yield_rate / 12 * months),
        )
        remaining -= investor_dividend

        # 6. residual_to_spc — absorbs rounding to guarantee reconciliation_diff == 0
        residual_to_spc = remaining

        return [
            StakeholderShare(
                role="accountant",
                amount_jpy=accounting_fee,
                basis="fixed_monthly",
            ),
            StakeholderShare(
                role="operator",
                amount_jpy=operator_margin,
                basis="operator_margin_rate",
            ),
            StakeholderShare(
                role="placement_agent",
                amount_jpy=placement_portion,
                basis="placement_fee_amortized",
            ),
            StakeholderShare(
                role="asset_manager",
                amount_jpy=am_fee,
                basis="am_fee_monthly",
            ),
            StakeholderShare(
                role="investor",
                amount_jpy=investor_dividend,
                basis="investor_yield_monthly",
            ),
            StakeholderShare(
                role="spc",
                amount_jpy=residual_to_spc,
                basis="residual",
            ),
        ]

    # ------------------------------------------------------------------
    # Supabase helpers (thin; repo layer is preferred for complex joins)
    # ------------------------------------------------------------------

    def _sum_realised_income(
        self, fund_id: UUID, period_start: date, period_end: date
    ) -> int:
        """Sum ``subtotal`` of paid/sent invoices in the period."""
        try:
            resp = (
                self._client.table("invoices")
                .select("subtotal,status,billing_period_start,billing_period_end")
                .eq("fund_id", str(fund_id))
                .in_("status", ["paid", "sent"])
                .gte("billing_period_start", period_start.isoformat())
                .lte("billing_period_end", period_end.isoformat())
                .execute()
            )
            rows: list[dict[str, Any]] = resp.data or []
            return sum(int(r.get("subtotal", 0) or 0) for r in rows)
        except Exception:
            logger.exception(
                "value_transfer_income_sum_failed",
                fund_id=str(fund_id),
            )
            raise

    def _load_pricing_params(self, fund_id: UUID) -> _PricingParams:
        """Fetch the active ``pricing_masters`` row for the fund.

        Falls back to platform defaults when no fund-specific row exists.
        """
        try:
            resp = (
                self._client.table("pricing_masters")
                .select("*")
                .eq("fund_id", str(fund_id))
                .eq("is_active", True)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                # Try global default
                resp = (
                    self._client.table("pricing_masters")
                    .select("*")
                    .eq("is_active", True)
                    .execute()
                )
                rows = resp.data or []

            if rows:
                row = rows[0]
                return _PricingParams(
                    accounting_fee_monthly=int(
                        row.get("accounting_fee_monthly")
                        or DEFAULT_ACCOUNTING_FEE_MONTHLY
                    ),
                    operator_margin_rate=float(
                        row.get("operator_margin_rate")
                        or DEFAULT_OPERATOR_MARGIN_RATE
                    ),
                    placement_fee_rate=float(
                        row.get("placement_fee_rate")
                        or DEFAULT_PLACEMENT_FEE_RATE
                    ),
                    am_fee_rate=float(
                        row.get("am_fee_rate") or DEFAULT_AM_FEE_RATE
                    ),
                    investor_yield_rate=float(
                        row.get("investor_yield_rate")
                        or DEFAULT_INVESTOR_YIELD_RATE
                    ),
                )
        except Exception:
            logger.exception(
                "value_transfer_pricing_load_failed",
                fund_id=str(fund_id),
            )

        return _PricingParams(
            accounting_fee_monthly=DEFAULT_ACCOUNTING_FEE_MONTHLY,
            operator_margin_rate=DEFAULT_OPERATOR_MARGIN_RATE,
            placement_fee_rate=DEFAULT_PLACEMENT_FEE_RATE,
            am_fee_rate=DEFAULT_AM_FEE_RATE,
            investor_yield_rate=DEFAULT_INVESTOR_YIELD_RATE,
        )

    def _load_contract_context(self, fund_id: UUID) -> _ContractContext:
        """Aggregate acquisition prices and lease terms across active contracts."""
        try:
            resp = (
                self._client.table("lease_contracts")
                .select("acquisition_price,lease_term_months,monthly_lease_amount")
                .eq("fund_id", str(fund_id))
                .eq("status", "active")
                .execute()
            )
            rows: list[dict[str, Any]] = resp.data or []
        except Exception:
            logger.exception(
                "value_transfer_contract_load_failed",
                fund_id=str(fund_id),
            )
            rows = []

        total_acq = 0
        weighted_term_num = 0
        weighted_term_den = 0
        for r in rows:
            acq = int(r.get("acquisition_price") or 0)
            term = int(r.get("lease_term_months") or 0)
            total_acq += acq
            if term > 0 and acq > 0:
                weighted_term_num += term * acq
                weighted_term_den += acq

        rep_term = (
            math.ceil(weighted_term_num / weighted_term_den)
            if weighted_term_den
            else 0
        )
        return _ContractContext(
            total_acquisition_price=total_acq,
            representative_lease_term_months=rep_term,
        )

    @staticmethod
    def _months_in_period(period_start: date, period_end: date) -> int:
        """Count inclusive month boundaries covered by the period.

        Any period overlapping a calendar month counts that month once.
        """
        if period_end < period_start:
            return 0
        months = (
            (period_end.year - period_start.year) * 12
            + (period_end.month - period_start.month)
            + 1
        )
        return max(months, 1)
