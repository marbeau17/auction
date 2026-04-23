"""Unit tests for :mod:`app.db.repositories.finance_assessment_repo`.

Uses the same minimal dict-backed ``FakeClient`` pattern as
``tests/unit/test_privacy_repo.py`` but extended to support ``delete``,
``range`` (pagination), ``count="exact"``, ``.lt`` / ``.gte`` filters and
``.limit(n)`` as required by the repository's full API surface.

Seven scenarios covered:

1. ``create`` stores all supplied columns and returns the row with an id.
2. ``get_by_id`` returns ``None`` on miss and the record on hit.
3. ``get_by_hash`` dedup returns the (latest) matching record.
4. ``list_by_user`` paginates and returns the correct total count.
5. ``delete`` returns ``True`` the first time and ``False`` on re-run.
6. ``sum_cost_current_month`` sums this-month rows only (float tolerance).
7. ``purge_expired`` deletes only past-retention rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.db.repositories.finance_assessment_repo import (
    FinanceAssessmentRepository,
)


# =====================================================================
# Minimal dict-backed fake Supabase client (self-contained)
# =====================================================================


class FakeResponse:
    def __init__(self, data: Any, count: int | None = None) -> None:
        self.data = data
        self.count = count


class FakeQuery:
    """Chainable in-memory Supabase query builder.

    Supports select / insert / update / delete, ``eq``, ``lt``, ``gte``,
    ``order``, ``range``, ``limit``. Returns ``_FakeResponse`` with
    ``count`` populated when ``select(count="exact")`` was used.
    """

    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._mode = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, tuple]] = []
        self._ops: list[str] = []
        self._count_exact = False

    # -- Mode switches --------------------------------------------------
    def select(self, *_cols, count: str | None = None):
        self._mode = "select"
        self._ops.append("select")
        if count == "exact":
            self._count_exact = True
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def delete(self):
        self._mode = "delete"
        return self

    # -- Filters --------------------------------------------------------
    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def lt(self, column, value):
        self._filters.append(("lt", (column, value)))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", (column, value)))
        return self

    # -- Ops ------------------------------------------------------------
    def order(self, column, desc: bool = False):
        self._ops.append(f"order:{column}:{desc}")
        return self

    def range(self, start, end):
        self._ops.append(f"range:{start}:{end}")
        return self

    def limit(self, n):
        self._ops.append(f"limit:{n}")
        return self

    # -- Execute --------------------------------------------------------
    def _matches(self, row: dict) -> bool:
        for op, args in self._filters:
            if op == "eq":
                col, val = args
                if row.get(col) != val:
                    return False
            elif op == "lt":
                col, val = args
                v = row.get(col)
                if v is None or not (v < val):
                    return False
            elif op == "gte":
                col, val = args
                v = row.get(col)
                if v is None or not (v >= val):
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
                # Mirror Supabase defaults only when the caller didn't
                # supply them explicitly.
                row.setdefault("id", str(uuid4()))
                row.setdefault(
                    "created_at",
                    datetime.now(timezone.utc).isoformat(),
                )
                table_rows.append(row)
                inserted.append(row)
            return FakeResponse(inserted)

        if self._mode == "update":
            matched = [r for r in table_rows if self._matches(r)]
            for r in matched:
                r.update(self._payload)
            return FakeResponse(matched)

        if self._mode == "delete":
            matched = [r for r in table_rows if self._matches(r)]
            for r in matched:
                table_rows.remove(r)
            return FakeResponse(matched)

        # select
        result = [r for r in table_rows if self._matches(r)]
        total_before_range = len(result)

        for op in self._ops:
            if op.startswith("order:"):
                _, col, desc_s = op.split(":", 2)
                desc = desc_s == "True"
                try:
                    result = sorted(
                        result,
                        key=lambda r: (r.get(col) is None, r.get(col)),
                        reverse=desc,
                    )
                except TypeError:
                    pass

        for op in self._ops:
            if op.startswith("range:"):
                _, s, e = op.split(":", 2)
                result = result[int(s) : int(e) + 1]
            elif op.startswith("limit:"):
                _, n = op.split(":", 1)
                result = result[: int(n)]

        count = total_before_range if self._count_exact else None
        return FakeResponse(result, count=count)


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
def repo(fake_client: FakeClient) -> FinanceAssessmentRepository:
    # FakeClient duck-types Supabase Client well enough for this repo.
    return FinanceAssessmentRepository(fake_client)  # type: ignore[arg-type]


def _sample_payload(
    user_id: UUID,
    pdf_sha256: str = "abc123",
    cost_usd: float = 0.05,
    needs_vision: bool = False,
    model: str = "gemini-flash-latest@2026-04-23",
) -> dict[str, Any]:
    """A complete finance_assessments payload for create()."""
    return {
        "user_id": str(user_id),
        "fund_id": None,
        "pdf_sha256": pdf_sha256,
        "needs_vision": needs_vision,
        "extracted_input": {"売上高": 100_000_000},
        "diagnosis": {"grade": "B", "score": 72},
        "narrative": "良好な財務状況です。",
        "model": model,
        "cost_usd": cost_usd,
        "retention_until": (
            datetime.now(timezone.utc) + timedelta(days=365 * 7)
        ).isoformat(),
    }


# =====================================================================
# Tests
# =====================================================================


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_stores_all_fields_and_returns_record(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        user_id = uuid4()
        payload = _sample_payload(user_id)
        row = await repo.create(**payload)

        # Returned dict contains every supplied field plus a generated id.
        assert row["id"]
        for key, value in payload.items():
            assert row[key] == value

        # And the row landed in the fake's backing store.
        assert len(fake_client.tables["finance_assessments"]) == 1


class TestGetById:
    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_on_miss_and_record_on_hit(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        # Miss.
        missing = await repo.get_by_id(uuid4())
        assert missing is None

        # Insert + hit.
        user_id = uuid4()
        row = await repo.create(**_sample_payload(user_id))
        found = await repo.get_by_id(UUID(row["id"]))
        assert found is not None
        assert found["id"] == row["id"]
        assert found["user_id"] == str(user_id)


class TestGetByHash:
    @pytest.mark.asyncio
    async def test_get_by_hash_dedup_returns_first_record(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        user_id = uuid4()
        sha = "sha-test-001"

        # Simulate two inserts (as could happen transiently before the
        # unique index is live). The LATEST by created_at wins.
        older_ts = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        newer_ts = datetime.now(timezone.utc).isoformat()

        payload_old = _sample_payload(user_id, pdf_sha256=sha)
        payload_old["created_at"] = older_ts
        await repo.create(**payload_old)

        payload_new = _sample_payload(user_id, pdf_sha256=sha)
        payload_new["created_at"] = newer_ts
        created_new = await repo.create(**payload_new)

        hit = await repo.get_by_hash(user_id, sha)
        assert hit is not None
        assert hit["id"] == created_new["id"]

        # Different sha / different user → None.
        miss_sha = await repo.get_by_hash(user_id, "does-not-exist")
        assert miss_sha is None
        miss_user = await repo.get_by_hash(uuid4(), sha)
        assert miss_user is None


class TestListByUser:
    @pytest.mark.asyncio
    async def test_list_by_user_paginates(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        user_a = uuid4()
        user_b = uuid4()

        # 5 for A with staggered timestamps so order is stable.
        base = datetime.now(timezone.utc)
        for i in range(5):
            payload = _sample_payload(user_a, pdf_sha256=f"a-{i}")
            payload["created_at"] = (
                base - timedelta(minutes=i)
            ).isoformat()
            await repo.create(**payload)

        # 2 for B (should NOT appear in A's listing).
        for i in range(2):
            await repo.create(**_sample_payload(user_b, pdf_sha256=f"b-{i}"))

        rows, total = await repo.list_by_user(user_a, page=1, per_page=3)
        assert total == 5
        assert len(rows) == 3
        # All returned rows belong to A.
        for r in rows:
            assert r["user_id"] == str(user_a)

        rows2, total2 = await repo.list_by_user(user_a, page=2, per_page=3)
        assert total2 == 5
        assert len(rows2) == 2


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_true_when_row_existed_false_otherwise(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        user_id = uuid4()
        row = await repo.create(**_sample_payload(user_id))
        target = UUID(row["id"])

        first = await repo.delete(target)
        assert first is True
        # Already gone.
        second = await repo.delete(target)
        assert second is False

        # Table is empty.
        assert fake_client.tables["finance_assessments"] == []


class TestSumCostCurrentMonth:
    @pytest.mark.asyncio
    async def test_sum_cost_current_month(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        user_id = uuid4()
        now = datetime.now(timezone.utc)
        month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        # Three this-month rows: 1.5 + 2.3 + 4.0 = 7.8
        for idx, cost in enumerate((1.5, 2.3, 4.0)):
            payload = _sample_payload(
                user_id, pdf_sha256=f"curr-{idx}", cost_usd=cost
            )
            # Well inside the current month.
            payload["created_at"] = (
                month_start + timedelta(days=1, hours=idx)
            ).isoformat()
            await repo.create(**payload)

        # Last-month row that must be excluded.
        last_month = month_start - timedelta(days=2)
        payload_old = _sample_payload(
            user_id, pdf_sha256="last-month", cost_usd=99.0
        )
        payload_old["created_at"] = last_month.isoformat()
        await repo.create(**payload_old)

        total = await repo.sum_cost_current_month(user_id)
        assert total == pytest.approx(7.8, rel=1e-6)

        # Without user filter, still 7.8 (only this user has rows).
        total_all = await repo.sum_cost_current_month()
        assert total_all == pytest.approx(7.8, rel=1e-6)


class TestPurgeExpired:
    @pytest.mark.asyncio
    async def test_purge_expired_deletes_only_past_rows(
        self,
        fake_client: FakeClient,
        repo: FinanceAssessmentRepository,
    ):
        user_id = uuid4()
        now = datetime.now(timezone.utc)

        past = _sample_payload(user_id, pdf_sha256="past")
        past["retention_until"] = (now - timedelta(days=1)).isoformat()
        await repo.create(**past)

        future = _sample_payload(user_id, pdf_sha256="future")
        future["retention_until"] = (now + timedelta(days=1)).isoformat()
        future_row = await repo.create(**future)

        deleted = await repo.purge_expired()
        assert deleted == 1

        # Survivor is the future-retention row.
        remaining = fake_client.tables["finance_assessments"]
        assert len(remaining) == 1
        assert remaining[0]["id"] == future_row["id"]

        # Listing + id-lookup confirm the past row is gone.
        rows, total = await repo.list_by_user(user_id)
        assert total == 1
        assert rows[0]["pdf_sha256"] == "future"
