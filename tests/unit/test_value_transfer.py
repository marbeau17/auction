"""Unit tests for :class:`app.core.value_transfer.ValueTransferEngine`.

Uses a minimal dict-backed ``FakeClient`` that mirrors the Supabase
query-builder surface needed by the engine (``table().select()``,
``eq``, ``in_``, ``gte``, ``lte``, ``order``, ``maybe_single``,
``execute``).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.value_transfer import (
    DEFAULT_ACCOUNTING_FEE_MONTHLY,
    DEFAULT_AM_FEE_RATE,
    DEFAULT_INVESTOR_YIELD_RATE,
    DEFAULT_OPERATOR_MARGIN_RATE,
    DEFAULT_PLACEMENT_FEE_RATE,
    ValueTransferEngine,
)


# =====================================================================
# Dict-backed fake Supabase client
# =====================================================================


class _FakeResponse:
    def __init__(self, data: Any, count: int | None = None) -> None:
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._filters: list[tuple[str, tuple]] = []
        self._maybe_single = False

    def select(self, *_cols, count: str | None = None):
        return self

    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def in_(self, column, values):
        self._filters.append(("in", (column, tuple(values))))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", (column, value)))
        return self

    def lte(self, column, value):
        self._filters.append(("lte", (column, value)))
        return self

    def order(self, column, desc: bool = False):
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def execute(self) -> _FakeResponse:
        rows = self._client.tables.get(self._table, [])
        matched = [r for r in rows if self._match(r)]
        if self._maybe_single:
            return _FakeResponse(matched[0] if matched else None)
        return _FakeResponse(matched, count=len(matched))

    def _match(self, row: dict) -> bool:
        for op, args in self._filters:
            col, val = args
            if op == "eq":
                if row.get(col) != val:
                    return False
            elif op == "in":
                if row.get(col) not in val:
                    return False
            elif op == "gte":
                rv = row.get(col)
                if rv is None or rv < val:
                    return False
            elif op == "lte":
                rv = row.get(col)
                if rv is None or rv > val:
                    return False
        return True


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


# =====================================================================
# Fixtures
# =====================================================================


FUND_ID = UUID("11111111-1111-1111-1111-111111111111")


def _seed(
    client: FakeClient,
    *,
    invoice_subtotals: list[int],
    invoice_status: str = "paid",
    acquisition_price: int = 3_600_000,
    lease_term_months: int = 36,
    pricing_override: dict[str, Any] | None = None,
) -> None:
    """Seed the fake client with a minimal dataset for the fund."""
    # invoices
    client.tables["invoices"] = [
        {
            "id": str(uuid4()),
            "fund_id": str(FUND_ID),
            "subtotal": subtotal,
            "status": invoice_status,
            "billing_period_start": "2026-04-01",
            "billing_period_end": "2026-04-30",
        }
        for subtotal in invoice_subtotals
    ]

    # pricing_masters
    pm: dict[str, Any] = {
        "id": str(uuid4()),
        "fund_id": str(FUND_ID),
        "is_active": True,
        "accounting_fee_monthly": DEFAULT_ACCOUNTING_FEE_MONTHLY,
        "operator_margin_rate": DEFAULT_OPERATOR_MARGIN_RATE,
        "placement_fee_rate": DEFAULT_PLACEMENT_FEE_RATE,
        "am_fee_rate": DEFAULT_AM_FEE_RATE,
        "investor_yield_rate": DEFAULT_INVESTOR_YIELD_RATE,
    }
    if pricing_override:
        pm.update(pricing_override)
    client.tables["pricing_masters"] = [pm]

    # lease_contracts
    client.tables["lease_contracts"] = [
        {
            "id": str(uuid4()),
            "fund_id": str(FUND_ID),
            "status": "active",
            "acquisition_price": acquisition_price,
            "lease_term_months": lease_term_months,
            "monthly_lease_amount": 180_000,
        }
    ]


@pytest.fixture
def engine() -> tuple[ValueTransferEngine, FakeClient]:
    client = FakeClient()
    return ValueTransferEngine(client=client), client


# =====================================================================
# Tests
# =====================================================================


def test_deterministic_split_sums_to_gross(engine):
    """Happy-path: sum of per-stakeholder shares == gross_income."""
    eng, client = engine
    _seed(client, invoice_subtotals=[200_000, 250_000, 300_000])

    allocation = eng.compute_period_allocation(
        fund_id=FUND_ID,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    assert allocation.gross_income == 750_000
    total = sum(s.amount_jpy for s in allocation.shares)
    assert total == allocation.gross_income
    assert allocation.reconciliation_diff == 0

    # Canonical roles present in order
    roles = [s.role for s in allocation.shares]
    assert roles == [
        "accountant",
        "operator",
        "placement_agent",
        "asset_manager",
        "investor",
        "spc",
    ]


def test_am_fee_is_capped(engine):
    """The am_fee share can never exceed gross_income * am_fee_rate."""
    eng, client = engine
    _seed(client, invoice_subtotals=[1_000_000])

    allocation = eng.compute_period_allocation(
        fund_id=FUND_ID,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    am_share = next(s for s in allocation.shares if s.role == "asset_manager")
    # Annual cap on a 1-month period
    hard_cap = int(1_000_000 * DEFAULT_AM_FEE_RATE)
    assert am_share.amount_jpy <= hard_cap


def test_placement_fee_amortization(engine):
    """placement_fee_amortized == floor(acq * rate / term) × months."""
    eng, client = engine
    _seed(
        client,
        invoice_subtotals=[500_000],
        acquisition_price=3_600_000,
        lease_term_months=36,
    )

    allocation = eng.compute_period_allocation(
        fund_id=FUND_ID,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),  # 1 month
    )

    placement = next(
        s for s in allocation.shares if s.role == "placement_agent"
    )
    # 3_600_000 * 0.03 / 36 = 3_000 per month
    assert placement.amount_jpy == 3_000


def test_reconciliation_diff_zero_on_happy_path(engine):
    """Any rounding slack is absorbed by residual_to_spc."""
    eng, client = engine
    # Choose an amount that forces some rounding in the fee components.
    _seed(client, invoice_subtotals=[333_333])

    allocation = eng.compute_period_allocation(
        fund_id=FUND_ID,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    assert allocation.reconciliation_diff == 0
    assert sum(s.amount_jpy for s in allocation.shares) == 333_333


def test_zero_income_edge_case(engine):
    """No paid/sent invoices => every stakeholder gets zero."""
    eng, client = engine
    _seed(client, invoice_subtotals=[], invoice_status="paid")

    allocation = eng.compute_period_allocation(
        fund_id=FUND_ID,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    assert allocation.gross_income == 0
    assert allocation.net_income == 0
    assert allocation.reconciliation_diff == 0
    assert all(s.amount_jpy == 0 for s in allocation.shares)

    plan = eng.generate_distribution_plan(allocation)
    # Zero-amount instructions are filtered out of the plan
    assert plan.instructions == []
    assert plan.total_planned == 0


def test_distribution_plan_matches_allocation(engine):
    """generate_distribution_plan produces one leg per non-zero share
    and the total planned equals gross_income."""
    eng, client = engine
    _seed(client, invoice_subtotals=[500_000])

    allocation = eng.compute_period_allocation(
        fund_id=FUND_ID,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    plan = eng.generate_distribution_plan(allocation)

    non_zero = [s for s in allocation.shares if s.amount_jpy > 0]
    assert len(plan.instructions) == len(non_zero)
    assert plan.total_planned == allocation.gross_income
    assert all(i.from_account == "spc_cash" for i in plan.instructions)
    assert all(i.status == "planned" for i in plan.instructions)
