"""Integration tests for /api/v1/investor-reports.

Covers the regression where a non-ASCII filename crashed Starlette's
latin-1-encoded Content-Disposition header on the download endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


def _make_noop_supabase() -> MagicMock:
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


def _install_repo_and_generator_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report_row: dict[str, Any],
) -> None:
    """Stub the repository and PDF generator so the endpoint has no DB deps."""
    import app.api.investor_reports as investor_reports_module

    class _StubRepo:
        def __init__(self, client: Any) -> None:  # noqa: ARG002
            pass

        async def get(self, _report_id):  # noqa: ANN001
            return report_row

        async def record_access(self, **_kwargs):  # noqa: ANN001
            return None

        async def mark_downloaded(self, **_kwargs):  # noqa: ANN001
            return None

    class _StubGenerator:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN001
            pass

        def generate(self, _fund_id, _month):  # noqa: ANN001
            return b"%PDF-1.4 stub", {}

    monkeypatch.setattr(investor_reports_module, "InvestorReportRepository", _StubRepo)
    monkeypatch.setattr(investor_reports_module, "InvestorReportGenerator", _StubGenerator)


def _mint_token(report_id: str, user_id: str) -> str:
    """Build a valid signed download token using the real minting helper."""
    from app.api.investor_reports import _mint_token as mint

    settings = get_settings()
    token, _exp = mint(report_id, user_id, settings)
    return token


@pytest.mark.asyncio
async def test_download_report_content_disposition_uses_rfc5987(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /download/{token} emits an RFC 5987 filename*=UTF-8'' header."""
    report_id = "00000000-0000-0000-0000-000000000100"
    fund_id = "00000000-0000-0000-0000-000000000200"
    report_row = {
        "id": report_id,
        "fund_id": fund_id,
        "report_month": "2026-04-01",
    }

    app = create_app()
    _install_repo_and_generator_stubs(monkeypatch, report_row=report_row)

    app.dependency_overrides[get_current_user] = lambda: {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "admin@example.com",
        "role": "admin",
    }
    app.dependency_overrides[get_supabase_client] = lambda: _make_noop_supabase()

    token = _mint_token(report_id, "00000000-0000-0000-0000-000000000001")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get(f"/api/v1/investor-reports/download/{token}")

    assert resp.status_code == 200, resp.text
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "filename*=UTF-8''" in cd
    cd.encode("latin-1")


@pytest.mark.asyncio
async def test_download_report_japanese_filename_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force a Japanese filename and prove the response does not 500."""
    import app.api.investor_reports as investor_reports_module

    report_id = "00000000-0000-0000-0000-000000000101"
    fund_id = "00000000-0000-0000-0000-000000000201"
    report_row = {
        "id": report_id,
        "fund_id": fund_id,
        "report_month": "2026-04-01",
    }

    app = create_app()
    _install_repo_and_generator_stubs(monkeypatch, report_row=report_row)

    # Wrap the helper to inject a Japanese filename.
    original_helper = investor_reports_module.content_disposition

    def _force_japanese(_filename: str) -> str:
        return original_helper("投資家レポート-2026年4月.pdf")

    monkeypatch.setattr(
        investor_reports_module, "content_disposition", _force_japanese
    )

    app.dependency_overrides[get_current_user] = lambda: {
        "id": "00000000-0000-0000-0000-000000000002",
        "email": "admin@example.com",
        "role": "admin",
    }
    app.dependency_overrides[get_supabase_client] = lambda: _make_noop_supabase()

    token = _mint_token(report_id, "00000000-0000-0000-0000-000000000002")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get(f"/api/v1/investor-reports/download/{token}")

    assert resp.status_code == 200, resp.text
    cd = resp.headers.get("content-disposition", "")
    assert "filename*=UTF-8''" in cd
    # The actual bug we're preventing: non-latin-1 chars in the header.
    cd.encode("latin-1")
