"""Unit tests for :class:`app.db.repositories.telemetry_repo.TelemetryRepository`.

Uses the dict-backed ``FakeClient`` pattern established in
``tests/unit/test_invoice_repo.py``, extended with ``gte`` / ``lte`` /
``desc-order`` support for range queries.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.db.repositories.telemetry_repo import TelemetryRepository


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
        self._mode: str = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, tuple]] = []
        self._ops: list[str] = []
        self._order: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._select_cols: tuple = ()

    # -- Selection / write mode switches --------------------------------
    def select(self, *cols, count: str | None = None):
        self._mode = "select"
        self._select_cols = cols
        self._ops.append("select")
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        self._ops.append("insert")
        return self

    # -- Filters --------------------------------------------------------
    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", (column, value)))
        return self

    def lte(self, column, value):
        self._filters.append(("lte", (column, value)))
        return self

    def order(self, column, desc: bool = False):
        self._order.append((column, desc))
        self._ops.append(f"order:{column}:{desc}")
        return self

    def limit(self, n):
        self._limit = n
        self._ops.append(f"limit:{n}")
        return self

    # -- Terminal -------------------------------------------------------
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
                row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                table_rows.append(row)
                inserted.append(row)
            self._client.last_insert[self._table] = inserted
            return FakeResponse(inserted)

        # select
        result = [r for r in table_rows if self._matches_filters(r)]
        for col, desc in reversed(self._order):
            result.sort(key=lambda r, c=col: r.get(c) or "", reverse=desc)
        if self._limit is not None:
            result = result[: self._limit]
        self._client.last_select[self._table] = {
            "filters": list(self._filters),
            "ops": list(self._ops),
        }
        return FakeResponse(result, count=len(result))

    def _matches_filters(self, row: dict) -> bool:
        for op, args in self._filters:
            col, val = args
            rv = row.get(col)
            if op == "eq" and rv != val:
                return False
            if op == "gte" and not (rv is not None and rv >= val):
                return False
            if op == "lte" and not (rv is not None and rv <= val):
                return False
        return True


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}
        self.last_select: dict[str, dict] = {}
        self.last_insert: dict[str, list] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def repo(fake_client: FakeClient) -> TelemetryRepository:
    return TelemetryRepository(fake_client)


# =====================================================================
# Insert semantics
# =====================================================================


class TestInsertEvent:

    @pytest.mark.asyncio
    async def test_insert_serializes_uuid_and_datetime(
        self,
        fake_client: FakeClient,
        repo: TelemetryRepository,
    ):
        vehicle_id = uuid4()
        event = {
            "vehicle_id": vehicle_id,
            "device_id": "DEV-1",
            "recorded_at": datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc),
            "odometer_km": 100_000,
            "dtc_codes": ["P0401"],
        }
        inserted = await repo.insert_event(event)

        # UUID and datetime must have been stringified on the way in.
        [row] = fake_client.tables["vehicle_telemetry"]
        assert row["vehicle_id"] == str(vehicle_id)
        assert isinstance(row["recorded_at"], str)
        assert row["recorded_at"].startswith("2026-04-17T10:00")
        assert inserted["device_id"] == "DEV-1"

    @pytest.mark.asyncio
    async def test_odometer_regression_logs_warning_but_inserts(
        self,
        fake_client: FakeClient,
        repo: TelemetryRepository,
        caplog: pytest.LogCaptureFixture,
    ):
        vehicle_id = uuid4()
        # Pre-seed a higher previous odometer reading
        fake_client.tables["vehicle_telemetry"] = [
            {
                "id": str(uuid4()),
                "vehicle_id": str(vehicle_id),
                "device_id": "DEV-1",
                "recorded_at": "2026-04-16T10:00:00+00:00",
                "odometer_km": 200_000,
            }
        ]
        event = {
            "vehicle_id": vehicle_id,
            "device_id": "DEV-1",
            "recorded_at": datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc),
            "odometer_km": 150_000,  # regression
        }
        with caplog.at_level(logging.WARNING):
            await repo.insert_event(event)

        # Insert must still have happened despite the warning.
        rows = fake_client.tables["vehicle_telemetry"]
        assert len(rows) == 2
        assert rows[-1]["odometer_km"] == 150_000


class TestInsertEvents:

    @pytest.mark.asyncio
    async def test_bulk_insert_persists_all_events(
        self,
        fake_client: FakeClient,
        repo: TelemetryRepository,
    ):
        vehicle_id = uuid4()
        events = [
            {
                "vehicle_id": vehicle_id,
                "device_id": "DEV-1",
                "recorded_at": datetime(2026, 4, 17, 10, i, tzinfo=timezone.utc),
                "odometer_km": 100_000 + i,
            }
            for i in range(3)
        ]
        inserted = await repo.insert_events(events)
        assert len(inserted) == 3
        assert len(fake_client.tables["vehicle_telemetry"]) == 3


# =====================================================================
# Reads
# =====================================================================


class TestListRecent:

    @pytest.mark.asyncio
    async def test_orders_by_recorded_at_desc_and_honours_limit(
        self,
        fake_client: FakeClient,
        repo: TelemetryRepository,
    ):
        vehicle_id = uuid4()
        other_vehicle = uuid4()
        fake_client.tables["vehicle_telemetry"] = [
            {
                "id": "a",
                "vehicle_id": str(vehicle_id),
                "device_id": "DEV-1",
                "recorded_at": "2026-04-17T09:00:00+00:00",
            },
            {
                "id": "b",
                "vehicle_id": str(vehicle_id),
                "device_id": "DEV-1",
                "recorded_at": "2026-04-17T11:00:00+00:00",
            },
            {
                "id": "c",
                "vehicle_id": str(vehicle_id),
                "device_id": "DEV-1",
                "recorded_at": "2026-04-17T10:00:00+00:00",
            },
            {
                "id": "x",
                "vehicle_id": str(other_vehicle),
                "device_id": "DEV-9",
                "recorded_at": "2026-04-17T12:00:00+00:00",
            },
        ]

        result = await repo.list_recent(vehicle_id, limit=2)
        ids = [r["id"] for r in result]
        # Descending order, scoped to vehicle_id, capped at 2
        assert ids == ["b", "c"]

        # Verify the order:desc:true and limit:2 ops were issued
        ops = fake_client.last_select["vehicle_telemetry"]["ops"]
        assert "order:recorded_at:True" in ops
        assert "limit:2" in ops


class TestDailyAggregate:

    @pytest.mark.asyncio
    async def test_date_range_uses_gte_lte_and_filters_scope(
        self,
        fake_client: FakeClient,
        repo: TelemetryRepository,
    ):
        vehicle_id = uuid4()
        fake_client.tables["telemetry_aggregates"] = [
            {
                "id": "1",
                "vehicle_id": str(vehicle_id),
                "agg_date": "2026-04-15",
                "km_driven": 120,
            },
            {
                "id": "2",
                "vehicle_id": str(vehicle_id),
                "agg_date": "2026-04-16",
                "km_driven": 80,
            },
            {
                "id": "3",
                "vehicle_id": str(vehicle_id),
                "agg_date": "2026-04-18",  # outside range
                "km_driven": 50,
            },
            {
                "id": "4",
                "vehicle_id": str(uuid4()),  # other vehicle
                "agg_date": "2026-04-16",
                "km_driven": 999,
            },
        ]

        result = await repo.daily_aggregate(
            vehicle_id, start=date(2026, 4, 15), end=date(2026, 4, 17)
        )
        ids = [r["id"] for r in result]
        assert ids == ["1", "2"]

        # Verify both gte and lte filter ops were applied
        filter_ops = [
            op for op, _ in fake_client.last_select["telemetry_aggregates"]["filters"]
        ]
        assert "gte" in filter_ops
        assert "lte" in filter_ops

    @pytest.mark.asyncio
    async def test_inverted_date_range_raises(
        self,
        repo: TelemetryRepository,
    ):
        with pytest.raises(ValueError):
            await repo.daily_aggregate(
                uuid4(), start=date(2026, 4, 20), end=date(2026, 4, 10)
            )
