"""Unit tests for :mod:`app.db.repositories.privacy_repo.PrivacyRepository`.

Built on the same minimal dict-backed ``FakeClient`` pattern used by
``tests/unit/test_invoice_repo.py``.

Scenarios covered (6):

1. ``create_deletion_request`` inserts a ``pending_review`` row.
2. ``list_pending`` returns only ``pending_review`` rows, FIFO-ordered.
3. ``execute_redaction`` scrubs the user row (email + full_name
   overwritten; ``is_deleted`` + ``redacted_at`` set).
4. ``execute_redaction`` preserves audit rows in retained tables
   (invoices, lease_payments, simulations, email_logs, ...).
5. ``execute_redaction`` is idempotent — a second run leaves the
   sentinel values unchanged and produces the same summary.
6. ``execute_redaction`` scrubs ``deal_stakeholders`` rows where the
   user is the registered contact and nothing else.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.db.repositories.privacy_repo import (
    PrivacyRepository,
    REDACTED_EMAIL,
    REDACTED_NAME,
)


# =====================================================================
# Minimal dict-backed fake Supabase client
# =====================================================================


class FakeResponse:
    def __init__(self, data: Any, count: int | None = None) -> None:
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._mode = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, tuple]] = []
        self._ops: list[str] = []

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

    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def order(self, column, desc: bool = False):
        self._ops.append(f"order:{column}:{desc}")
        return self

    def _matches(self, row: dict) -> bool:
        for op, (col, val) in self._filters:
            if op == "eq" and row.get(col) != val:
                return False
        return True

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
            return FakeResponse(inserted)

        if self._mode == "update":
            matched = [r for r in table_rows if self._matches(r)]
            for r in matched:
                r.update(self._payload)
            return FakeResponse(matched)

        # select
        result = [r for r in table_rows if self._matches(r)]
        # Honour a single order directive for list_pending's FIFO check.
        for op in self._ops:
            if op.startswith("order:"):
                _, col, desc = op.split(":")
                result = sorted(
                    result,
                    key=lambda r: r.get(col) or "",
                    reverse=(desc == "True"),
                )
        return FakeResponse(result, count=len(result))


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def repo(fake_client: FakeClient) -> PrivacyRepository:
    return PrivacyRepository(fake_client)


@pytest.fixture
def seeded_user(fake_client: FakeClient) -> UUID:
    """A user + stakeholder row + some retained audit rows."""
    user_id = uuid4()
    fake_client.tables["users"] = [
        {
            "id": str(user_id),
            "email": "alice@example.com",
            "full_name": "Alice Tanaka",
            "is_active": True,
            "is_deleted": False,
        }
    ]
    fake_client.tables["deal_stakeholders"] = [
        {
            "id": str(uuid4()),
            "contact_user_id": str(user_id),
            "company_name": "Acme KK",
            "role_type": "end_user",
            "contact_name": "Alice Tanaka",
            "contact_email": "alice@example.com",
            "phone": "+81-90-0000-0000",
            "address_line": "Tokyo",
        },
        {
            # Unrelated stakeholder — must NOT be touched.
            "id": str(uuid4()),
            "contact_user_id": str(uuid4()),
            "company_name": "Other Corp",
            "role_type": "operator",
            "contact_name": "Bob",
            "contact_email": "bob@example.com",
            "phone": "+81-90-1111-1111",
            "address_line": "Osaka",
        },
    ]
    # Retained-table rows that must survive redaction untouched.
    fake_client.tables["invoices"] = [
        {"id": "inv-1", "end_user_id": str(user_id), "total_amount": 165000}
    ]
    fake_client.tables["invoice_line_items"] = [
        {"id": "line-1", "invoice_id": "inv-1", "amount": 150000}
    ]
    fake_client.tables["email_logs"] = [
        {"id": "elog-1", "invoice_id": "inv-1", "status": "sent"}
    ]
    fake_client.tables["lease_payments"] = [
        {"id": "pay-1", "end_user_id": str(user_id), "amount": 150000}
    ]
    fake_client.tables["simulations"] = [
        {"id": "sim-1", "created_by": str(user_id), "status": "completed"}
    ]
    return user_id


# =====================================================================
# Tests
# =====================================================================


class TestCreateDeletionRequest:

    @pytest.mark.asyncio
    async def test_insert_default_status_pending_review(
        self, fake_client: FakeClient, repo: PrivacyRepository
    ):
        user_id = uuid4()
        row = await repo.create_deletion_request(
            user_id=user_id, reason="leaving the service"
        )
        assert row["user_id"] == str(user_id)
        assert row["status"] == "pending_review"
        assert row["reason"] == "leaving the service"
        assert len(fake_client.tables["privacy_deletion_requests"]) == 1


class TestListPending:

    @pytest.mark.asyncio
    async def test_only_pending_rows_returned_fifo(
        self, fake_client: FakeClient, repo: PrivacyRepository
    ):
        fake_client.tables["privacy_deletion_requests"] = [
            {
                "id": "r1",
                "user_id": str(uuid4()),
                "status": "pending_review",
                "requested_at": "2026-04-01T00:00:00+00:00",
            },
            {
                "id": "r2",
                "user_id": str(uuid4()),
                "status": "executed",
                "requested_at": "2026-03-01T00:00:00+00:00",
            },
            {
                "id": "r3",
                "user_id": str(uuid4()),
                "status": "pending_review",
                "requested_at": "2026-03-15T00:00:00+00:00",
            },
        ]
        rows = await repo.list_pending()
        ids = [r["id"] for r in rows]
        # Only pending rows, oldest-first.
        assert ids == ["r3", "r1"]


class TestExecuteRedaction:

    @pytest.mark.asyncio
    async def test_user_pii_scrubbed(
        self,
        fake_client: FakeClient,
        repo: PrivacyRepository,
        seeded_user: UUID,
    ):
        summary = await repo.execute_redaction(user_id=seeded_user)
        user = fake_client.tables["users"][0]
        assert user["email"] == REDACTED_EMAIL
        assert user["full_name"] == REDACTED_NAME
        assert user["is_active"] is False
        assert user["is_deleted"] is True
        assert user["deleted_at"] is not None
        assert user["redacted_at"] is not None
        assert summary["users_redacted"] == 1

    @pytest.mark.asyncio
    async def test_audit_rows_preserved(
        self,
        fake_client: FakeClient,
        repo: PrivacyRepository,
        seeded_user: UUID,
    ):
        await repo.execute_redaction(user_id=seeded_user)

        # Every retained-table row remains untouched.
        assert fake_client.tables["invoices"][0] == {
            "id": "inv-1",
            "end_user_id": str(seeded_user),
            "total_amount": 165000,
        }
        assert fake_client.tables["invoice_line_items"][0]["amount"] == 150000
        assert fake_client.tables["email_logs"][0]["status"] == "sent"
        assert fake_client.tables["lease_payments"][0]["amount"] == 150000
        assert fake_client.tables["simulations"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_stakeholder_contact_scrubbed_scoped(
        self,
        fake_client: FakeClient,
        repo: PrivacyRepository,
        seeded_user: UUID,
    ):
        await repo.execute_redaction(user_id=seeded_user)

        mine, other = fake_client.tables["deal_stakeholders"]
        # My stakeholder row: PII cleared, company_name / role_type kept.
        assert mine["contact_name"] == REDACTED_NAME
        assert mine["contact_email"] == REDACTED_EMAIL
        assert mine["phone"] is None
        assert mine["address_line"] is None
        assert mine["company_name"] == "Acme KK"
        assert mine["role_type"] == "end_user"

        # Unrelated stakeholder: totally untouched.
        assert other["contact_name"] == "Bob"
        assert other["contact_email"] == "bob@example.com"
        assert other["phone"] == "+81-90-1111-1111"

    @pytest.mark.asyncio
    async def test_redaction_is_idempotent(
        self,
        fake_client: FakeClient,
        repo: PrivacyRepository,
        seeded_user: UUID,
    ):
        first = await repo.execute_redaction(user_id=seeded_user)
        second = await repo.execute_redaction(user_id=seeded_user)

        # Sentinels stable across runs.
        user = fake_client.tables["users"][0]
        assert user["email"] == REDACTED_EMAIL
        assert user["full_name"] == REDACTED_NAME

        # Both runs report the same affected row-counts (still 1 each),
        # because the update predicate matches the same user/stakeholder.
        assert first["users_redacted"] == 1
        assert second["users_redacted"] == 1
        assert first["stakeholders_redacted"] == second["stakeholders_redacted"]


class TestRequestWorkflow:

    @pytest.mark.asyncio
    async def test_mark_approved_records_reviewer_and_timestamp(
        self, fake_client: FakeClient, repo: PrivacyRepository
    ):
        req_id = uuid4()
        reviewer = uuid4()
        fake_client.tables["privacy_deletion_requests"] = [
            {
                "id": str(req_id),
                "user_id": str(uuid4()),
                "status": "pending_review",
            }
        ]
        updated = await repo.mark_approved(
            request_id=req_id, reviewer_id=reviewer, notes="ID verified"
        )
        assert updated["status"] == "approved"
        assert updated["reviewed_by"] == str(reviewer)
        assert updated["reviewed_at"] is not None
        assert updated["notes"] == "ID verified"
