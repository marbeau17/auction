"""Integration tests for /api/v1/privacy.

Covers the regression where a filename containing non-ASCII characters
crashed Starlette's latin-1-encoded Content-Disposition header.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


def _make_noop_supabase() -> MagicMock:
    """Supabase client that returns empty data for every query."""
    client = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.single.return_value = query
    query.maybe_single.return_value = query
    response = MagicMock()
    response.data = None
    query.execute.return_value = response
    client.table.return_value = query
    return client


def _install_repo_stub(app, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace PrivacyRepository methods with no-op async stubs."""
    import app.api.privacy as privacy_module

    class _StubRepo:
        def __init__(self, client: Any) -> None:  # noqa: ARG002
            pass

        async def fetch_user_row(self, _user_id):  # noqa: ANN001
            return {}

        async def fetch_table_for_user(self, *_args, **_kwargs):  # noqa: ANN001
            return []

    monkeypatch.setattr(privacy_module, "PrivacyRepository", _StubRepo)


@pytest.mark.asyncio
async def test_privacy_export_content_disposition_uses_rfc5987(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/v1/privacy/export emits an RFC 5987 filename*=UTF-8'' header.

    The real filename uses the ASCII user_id, but the helper always includes
    the RFC 5987 form — asserting it is present confirms the helper is wired
    in, which prevents the latin-1 crash for any future non-ASCII name.
    """
    app = create_app()
    _install_repo_stub(app, monkeypatch)

    user_id = "00000000-0000-0000-0000-000000000001"
    app.dependency_overrides[get_current_user] = lambda: {
        "id": user_id,
        "email": "user@example.com",
        "role": "admin",
    }
    app.dependency_overrides[get_supabase_client] = lambda: _make_noop_supabase()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get("/api/v1/privacy/export")

    # Must NOT be a 500 due to header encoding.
    assert resp.status_code == 200, resp.text
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "filename*=UTF-8''" in cd
    # The actual bug: header must be latin-1 encodable.
    cd.encode("latin-1")


@pytest.mark.asyncio
async def test_privacy_export_japanese_filename_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force a Japanese filename and prove the response does not 500."""
    import app.api.privacy as privacy_module

    app = create_app()
    _install_repo_stub(app, monkeypatch)

    # Patch the helper call site to inject a Japanese filename directly.
    original_helper = privacy_module.content_disposition

    def _force_japanese(_filename: str) -> str:
        return original_helper("プライバシー-エクスポート.zip")

    monkeypatch.setattr(privacy_module, "content_disposition", _force_japanese)

    app.dependency_overrides[get_current_user] = lambda: {
        "id": "00000000-0000-0000-0000-000000000002",
        "email": "jp@example.com",
        "role": "admin",
    }
    app.dependency_overrides[get_supabase_client] = lambda: _make_noop_supabase()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get("/api/v1/privacy/export")

    assert resp.status_code == 200, resp.text
    cd = resp.headers.get("content-disposition", "")
    assert "filename*=UTF-8''" in cd
    cd.encode("latin-1")
