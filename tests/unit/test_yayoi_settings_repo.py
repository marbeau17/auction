"""Unit tests for Yayoi integration settings (``user_integration_settings``).

The settings "repo" is implemented inline in ``app/api/yayoi.py`` (GET/POST
``/settings``) for simplicity — these tests exercise the same Supabase
queries through a minimal in-memory fake client so we can assert:

1. First-access creates a default row.
2. Upsert returns the new values.
3. Only the row for ``user_id = auth.uid()`` is returned
   (RLS-equivalent filtering at the query layer).
4. Defaults match the migration: auto_sync=False, invoices=True,
   journals=True.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import yayoi as yayoi_api
from app.dependencies import get_current_user, get_supabase_client


# ---------------------------------------------------------------------------
# Fake Supabase client
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self.data = data


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._mode: str | None = None
        self._payload: Any = None
        self._filters: list[tuple[str, Any]] = []
        self._on_conflict: str | None = None
        self._limit: int | None = None
        self._order: tuple[str, bool] | None = None

    def select(self, *_cols):
        self._mode = "select"
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None):
        self._mode = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, column, desc: bool = False):
        self._order = (column, desc)
        return self

    def execute(self) -> FakeResponse:
        rows = self._client.tables.setdefault(self._table, [])

        if self._mode == "insert":
            new_row = {"id": str(uuid4()), **dict(self._payload)}
            rows.append(new_row)
            return FakeResponse([new_row])

        if self._mode == "upsert":
            payload = dict(self._payload)
            # Use on_conflict column as the match key.
            key = self._on_conflict or "id"
            for r in rows:
                if r.get(key) == payload.get(key):
                    r.update(payload)
                    return FakeResponse([r])
            new_row = {"id": str(uuid4()), **payload}
            rows.append(new_row)
            return FakeResponse([new_row])

        # select
        def matches(r: dict) -> bool:
            return all(r.get(c) == v for c, v in self._filters)

        result = [r for r in rows if matches(r)]
        if self._order:
            col, desc = self._order
            result = sorted(result, key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            result = result[: self._limit]
        return FakeResponse(result)


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


# ---------------------------------------------------------------------------
# Test app with overridden dependencies
# ---------------------------------------------------------------------------


def _build_app(fake_client: FakeClient, user_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(yayoi_api.router)

    def _fake_user() -> dict:
        return {"id": user_id, "email": "t@example.com", "role": "authenticated"}

    def _fake_supabase() -> FakeClient:
        return fake_client

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_supabase_client] = _fake_supabase
    return app


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def user_id() -> str:
    return str(uuid4())


@pytest.fixture
def client(fake_client: FakeClient, user_id: str) -> TestClient:
    return TestClient(_build_app(fake_client, user_id))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDefaultRowCreation:
    def test_first_get_creates_default_row(
        self, client: TestClient, fake_client: FakeClient, user_id: str
    ):
        assert fake_client.tables.get("user_integration_settings") in (None, [])
        resp = client.get("/api/v1/yayoi/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user_id
        # Migration defaults
        assert body["yayoi_auto_sync_monthly"] is False
        assert body["yayoi_sync_invoices"] is True
        assert body["yayoi_sync_journals"] is True
        # Row is now persisted
        assert len(fake_client.tables["user_integration_settings"]) == 1

    def test_second_get_returns_existing_row_without_duplicating(
        self, client: TestClient, fake_client: FakeClient
    ):
        client.get("/api/v1/yayoi/settings")
        resp = client.get("/api/v1/yayoi/settings")
        assert resp.status_code == 200
        # Still only one row — no duplicate default created.
        assert len(fake_client.tables["user_integration_settings"]) == 1


class TestUpsert:
    def test_post_settings_upserts_row(
        self, client: TestClient, fake_client: FakeClient, user_id: str
    ):
        payload = {
            "yayoi_auto_sync_monthly": True,
            "yayoi_sync_invoices": False,
            "yayoi_sync_journals": True,
        }
        resp = client.post("/api/v1/yayoi/settings", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user_id
        assert body["yayoi_auto_sync_monthly"] is True
        assert body["yayoi_sync_invoices"] is False
        assert body["yayoi_sync_journals"] is True
        # Row persisted exactly once
        rows = fake_client.tables["user_integration_settings"]
        assert len(rows) == 1
        assert rows[0]["yayoi_auto_sync_monthly"] is True

    def test_post_then_get_returns_saved_values(
        self, client: TestClient
    ):
        client.post(
            "/api/v1/yayoi/settings",
            json={
                "yayoi_auto_sync_monthly": True,
                "yayoi_sync_invoices": True,
                "yayoi_sync_journals": False,
            },
        )
        resp = client.get("/api/v1/yayoi/settings")
        body = resp.json()
        assert body["yayoi_auto_sync_monthly"] is True
        assert body["yayoi_sync_journals"] is False

    def test_repeated_upsert_does_not_duplicate_row(
        self, client: TestClient, fake_client: FakeClient
    ):
        for flag in (True, False, True):
            client.post(
                "/api/v1/yayoi/settings",
                json={
                    "yayoi_auto_sync_monthly": flag,
                    "yayoi_sync_invoices": True,
                    "yayoi_sync_journals": True,
                },
            )
        rows = fake_client.tables["user_integration_settings"]
        assert len(rows) == 1
        assert rows[0]["yayoi_auto_sync_monthly"] is True


class TestRLSEquivalentFiltering:
    def test_get_only_returns_current_users_row(
        self, fake_client: FakeClient
    ):
        """Simulates two users hitting the endpoint with the same DB.

        The query filter ``eq('user_id', <auth.uid()>)`` is what stands in
        for the RLS policy. User A must never see User B's row.
        """
        user_a = str(uuid4())
        user_b = str(uuid4())

        # Pre-seed B's row.
        fake_client.tables["user_integration_settings"] = [
            {
                "id": str(uuid4()),
                "user_id": user_b,
                "yayoi_auto_sync_monthly": True,
                "yayoi_sync_invoices": True,
                "yayoi_sync_journals": True,
            }
        ]

        # User A fetches — should get a freshly created default row, not B's.
        client_a = TestClient(_build_app(fake_client, user_a))
        resp = client_a.get("/api/v1/yayoi/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user_a
        assert body["yayoi_auto_sync_monthly"] is False  # default, not B's True

        # There should now be exactly two rows (one per user).
        rows = fake_client.tables["user_integration_settings"]
        assert len(rows) == 2
        owners = {r["user_id"] for r in rows}
        assert owners == {user_a, user_b}
