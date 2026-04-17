"""Unit tests for ``app.db.repositories.invoice_repo.InvoiceRepository``.

Uses a minimal dict-backed fake Supabase client instead of heavy mocks.

Focuses on:

* ``update_invoice_status`` auto-sets ``sent_at`` for ``sent`` and
  ``paid_at`` for ``paid``, and always bumps ``updated_at``
* ``update_email_status`` sets ``sent_at`` only for ``sent`` and
  records ``error_message`` when supplied
* ``create_invoice`` nests line items with ``invoice_id`` + ``display_order``
* ``get_overdue_invoices`` uses ``lt(due_date, today)`` and excludes
  paid/cancelled statuses (predicate inspection)
* ``generate_invoice_number`` formats ``INV-YYYYMM-NNNN``
* ``create_approval`` auto-transitions invoice status based on action
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

import pytest

from app.db.repositories.invoice_repo import InvoiceRepository


# =====================================================================
# Minimal dict-backed fake Supabase client
# =====================================================================


class FakeResponse:
    def __init__(self, data: Any, count: int | None = None) -> None:
        self.data = data
        self.count = count


class FakeQuery:
    """Chainable fake query builder.

    Captures every filter predicate in ``self.filters`` so tests can
    inspect what was called (e.g. to verify ``lt('due_date', today)`` in
    ``get_overdue_invoices``).
    """

    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._mode: str = "select"  # select | insert | update
        self._payload: Any = None
        self._filters: list[tuple[str, tuple]] = []
        self._ops: list[str] = []
        self._maybe_single: bool = False

    # -- Selection / write mode switches ----------------------------
    def select(self, *_cols, count: str | None = None):
        self._mode = "select"
        self._ops.append("select")
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        self._ops.append("insert")
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        self._ops.append("update")
        return self

    # -- Filters -----------------------------------------------------
    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def lt(self, column, value):
        self._filters.append(("lt", (column, value)))
        return self

    def like(self, column, value):
        self._filters.append(("like", (column, value)))
        return self

    def order(self, column, desc: bool = False):
        self._ops.append(f"order:{column}:{desc}")
        return self

    def range(self, start, end):
        self._ops.append(f"range:{start}:{end}")
        return self

    def limit(self, n):
        self._ops.append(f"limit:{n}")
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    @property
    def not_(self):
        parent = self
        outer = self

        class _Not:
            def in_(self, column, values):
                outer._filters.append(("not_in", (column, tuple(values))))
                return outer

        return _Not()

    # -- Terminal ---------------------------------------------------
    def execute(self) -> FakeResponse:
        table_rows = self._client.tables.setdefault(self._table, [])

        if self._mode == "insert":
            items = (
                list(self._payload)
                if isinstance(self._payload, list)
                else [self._payload]
            )
            inserted = []
            for item in items:
                row = dict(item)
                row.setdefault("id", str(uuid4()))
                table_rows.append(row)
                inserted.append(row)
            self._client.last_insert[self._table] = inserted
            return FakeResponse(inserted)

        if self._mode == "update":
            matched = [r for r in table_rows if self._matches_filters(r)]
            for r in matched:
                r.update(self._payload)
            self._client.last_update[self._table] = {
                "payload": self._payload,
                "filters": list(self._filters),
            }
            return FakeResponse(matched)

        # select
        result = [r for r in table_rows if self._matches_filters(r)]
        self._client.last_select[self._table] = {
            "filters": list(self._filters),
            "ops": list(self._ops),
        }
        if self._maybe_single:
            return FakeResponse(result[0] if result else None)
        return FakeResponse(result, count=len(result))

    def _matches_filters(self, row: dict) -> bool:
        for op, args in self._filters:
            if op == "eq":
                col, val = args
                if row.get(col) != val:
                    return False
            elif op == "lt":
                col, val = args
                if not (row.get(col) is not None and row[col] < val):
                    return False
            elif op == "not_in":
                col, values = args
                if row.get(col) in values:
                    return False
            elif op == "like":
                col, pattern = args
                # Trivial LIKE: support '%' wildcard at end only
                if pattern.endswith("%"):
                    prefix = pattern[:-1]
                    if not str(row.get(col, "")).startswith(prefix):
                        return False
                else:
                    if str(row.get(col)) != pattern:
                        return False
        return True


class FakeClient:
    """In-memory Supabase substitute."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}
        self.last_select: dict[str, dict] = {}
        self.last_insert: dict[str, list] = {}
        self.last_update: dict[str, dict] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def repo(fake_client: FakeClient) -> InvoiceRepository:
    return InvoiceRepository(fake_client)


# =====================================================================
# Status transition rules
# =====================================================================


class TestStatusTransitions:

    @pytest.mark.asyncio
    async def test_mark_as_sent_sets_sent_at(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        invoice_id = uuid4()
        fake_client.tables["invoices"] = [
            {
                "id": str(invoice_id),
                "status": "approved",
                "sent_at": None,
                "paid_at": None,
            }
        ]
        updated = await repo.update_invoice_status(invoice_id, "sent")
        assert updated["status"] == "sent"
        assert updated["sent_at"] is not None
        assert updated["paid_at"] is None
        assert updated["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_mark_as_paid_sets_paid_at(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        invoice_id = uuid4()
        fake_client.tables["invoices"] = [
            {
                "id": str(invoice_id),
                "status": "sent",
                "sent_at": "2025-01-01T00:00:00+00:00",
                "paid_at": None,
            }
        ]
        updated = await repo.update_invoice_status(invoice_id, "paid")
        assert updated["status"] == "paid"
        assert updated["paid_at"] is not None

    @pytest.mark.asyncio
    async def test_other_status_does_not_set_sent_or_paid(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        invoice_id = uuid4()
        fake_client.tables["invoices"] = [
            {
                "id": str(invoice_id),
                "status": "created",
                "sent_at": None,
                "paid_at": None,
            }
        ]
        updated = await repo.update_invoice_status(invoice_id, "approved")
        assert updated["status"] == "approved"
        assert updated.get("sent_at") is None
        assert updated.get("paid_at") is None

    @pytest.mark.asyncio
    async def test_update_nonexistent_invoice_raises(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        with pytest.raises(RuntimeError):
            await repo.update_invoice_status(uuid4(), "paid")


# =====================================================================
# Line item nesting on create
# =====================================================================


class TestCreateInvoice:

    @pytest.mark.asyncio
    async def test_line_items_get_invoice_id_and_order(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        invoice_data = {
            "fund_id": "f-1",
            "invoice_number": "INV-202601-0001",
            "status": "created",
        }
        line_items = [
            {"description": "A", "quantity": 1, "unit_price": 100, "amount": 100},
            {"description": "B", "quantity": 2, "unit_price": 50, "amount": 100},
        ]

        created = await repo.create_invoice(invoice_data, line_items)

        assert created is not None
        # Find the inserted invoice
        [invoice] = fake_client.tables["invoices"]
        items = fake_client.tables["invoice_line_items"]
        assert len(items) == 2
        for idx, item in enumerate(items):
            assert item["invoice_id"] == invoice["id"]
            assert item["display_order"] == idx
        # get_invoice returns embedded line items
        assert created["line_items"] and len(created["line_items"]) == 2

    @pytest.mark.asyncio
    async def test_create_invoice_without_line_items(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        created = await repo.create_invoice(
            {"fund_id": "f-1", "status": "created"}, []
        )
        assert created is not None
        assert "invoice_line_items" not in fake_client.tables or (
            fake_client.tables.get("invoice_line_items") == []
        )


# =====================================================================
# Overdue query predicate
# =====================================================================


class TestOverdueQuery:

    @pytest.mark.asyncio
    async def test_overdue_predicate_uses_lt_due_date_and_excludes_paid(
        self,
        fake_client: FakeClient,
        repo: InvoiceRepository,
    ):
        today = date.today()
        yesterday = today.replace(day=max(today.day - 1, 1))
        tomorrow = today.replace(day=min(today.day + 1, 28))

        fake_client.tables["invoices"] = [
            {
                "id": "a",
                "due_date": yesterday.isoformat(),
                "status": "sent",
            },
            {
                "id": "b",
                "due_date": yesterday.isoformat(),
                "status": "paid",  # excluded
            },
            {
                "id": "c",
                "due_date": yesterday.isoformat(),
                "status": "cancelled",  # excluded
            },
            {
                "id": "d",
                "due_date": tomorrow.isoformat(),
                "status": "sent",  # not overdue yet
            },
        ]

        result = await repo.get_overdue_invoices()
        ids = {r["id"] for r in result}
        assert ids == {"a"}

        # Also inspect the filter predicates that were applied.
        last = fake_client.last_select["invoices"]
        filter_ops = [op for op, _ in last["filters"]]
        assert "lt" in filter_ops
        assert "not_in" in filter_ops


# =====================================================================
# Invoice number generation
# =====================================================================


class TestInvoiceNumberGeneration:

    @pytest.mark.asyncio
    async def test_first_number_of_month(
        self, fake_client: FakeClient, repo: InvoiceRepository
    ):
        number = await repo.generate_invoice_number(
            fund_id=uuid4(), billing_date=date(2026, 4, 1)
        )
        assert number == "INV-202604-0001"

    @pytest.mark.asyncio
    async def test_sequential_numbering(
        self, fake_client: FakeClient, repo: InvoiceRepository
    ):
        # Pre-seed two existing invoices for the month
        fake_client.tables["invoices"] = [
            {"invoice_number": "INV-202604-0001"},
            {"invoice_number": "INV-202604-0002"},
        ]
        number = await repo.generate_invoice_number(
            fund_id=uuid4(), billing_date=date(2026, 4, 17)
        )
        assert number == "INV-202604-0003"


# =====================================================================
# Approval auto-transitions
# =====================================================================


class TestApprovalTransition:

    @pytest.mark.asyncio
    async def test_approve_action_transitions_to_approved(
        self, fake_client: FakeClient, repo: InvoiceRepository
    ):
        invoice_id = uuid4()
        fake_client.tables["invoices"] = [
            {
                "id": str(invoice_id),
                "status": "created",
            }
        ]
        await repo.create_approval(
            {
                "invoice_id": str(invoice_id),
                "action": "approve",
                "approver_id": "u-1",
            }
        )
        # status should flip to 'approved'
        [inv] = fake_client.tables["invoices"]
        assert inv["status"] == "approved"

    @pytest.mark.asyncio
    async def test_reject_action_reverts_to_created(
        self, fake_client: FakeClient, repo: InvoiceRepository
    ):
        invoice_id = uuid4()
        fake_client.tables["invoices"] = [
            {
                "id": str(invoice_id),
                "status": "approved",
            }
        ]
        await repo.create_approval(
            {
                "invoice_id": str(invoice_id),
                "action": "reject",
                "approver_id": "u-1",
            }
        )
        [inv] = fake_client.tables["invoices"]
        assert inv["status"] == "created"


# =====================================================================
# Email log status updates
# =====================================================================


class TestEmailLogStatus:

    @pytest.mark.asyncio
    async def test_sent_status_sets_sent_at(
        self, fake_client: FakeClient, repo: InvoiceRepository
    ):
        log_id = uuid4()
        fake_client.tables["email_logs"] = [
            {"id": str(log_id), "status": "queued"}
        ]
        updated = await repo.update_email_status(log_id, "sent")
        assert updated["status"] == "sent"
        assert updated["sent_at"] is not None

    @pytest.mark.asyncio
    async def test_failure_records_error_message(
        self, fake_client: FakeClient, repo: InvoiceRepository
    ):
        log_id = uuid4()
        fake_client.tables["email_logs"] = [
            {"id": str(log_id), "status": "queued"}
        ]
        updated = await repo.update_email_status(
            log_id, "failed", error_message="SMTP auth error"
        )
        assert updated["status"] == "failed"
        assert updated["error_message"] == "SMTP auth error"
        # sent_at must NOT be set on failure
        assert updated.get("sent_at") in (None, "")
