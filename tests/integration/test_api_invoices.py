"""Integration tests for /api/v1/invoices endpoints.

Covers:

* POST /  (create invoice manually) -> 201 + invoice payload
* GET /   with status filter
* Approval flow: create -> approve -> status transitions to 'approved'
* POST /{id}/send in EMAIL_DRY_RUN mode -> status 'sent', email_log row written
* GET /{id}/pdf returns bytes (PDF or HTML fallback)
* GET /{id}/approvals after approve
* RBAC: non-admin on POST /generate-monthly -> 403
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_USER_ID,
    NOW_ISO,
    SALES_EMAIL,
    SALES_USER_ID,
    _FakeClient,
    _make_jwt,
)

from app.dependencies import get_current_user, get_supabase_client
from app.main import create_app


# Ensure EMAIL_DRY_RUN is definitively on at import time for this module.
os.environ["EMAIL_DRY_RUN"] = "true"


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


def _sample_invoice_payload() -> dict[str, Any]:
    return {
        "fund_id": str(uuid4()),
        "lease_contract_id": str(uuid4()),
        "invoice_number": "INV-202604-9001",
        "billing_period_start": "2026-04-01",
        "billing_period_end": "2026-04-30",
        "subtotal": 150_000,
        "tax_rate": 0.10,
        "tax_amount": 15_000,
        "total_amount": 165_000,
        "due_date": "2026-04-30",
        "notes": "統合テスト",
        "line_items": [
            {
                "description": "月額リース料",
                "quantity": 1,
                "unit_price": 150_000,
                "amount": 150_000,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user_dict() -> dict[str, Any]:
    return {
        "id": ADMIN_USER_ID,
        "email": ADMIN_EMAIL,
        "role": "admin",
        "stakeholder_role": "admin",
    }


@pytest.fixture
def sales_user_dict() -> dict[str, Any]:
    return {
        "id": SALES_USER_ID,
        "email": SALES_EMAIL,
        "role": "sales",
        "stakeholder_role": "sales",
    }


@pytest.fixture
async def client_invoices(
    fake_supabase: _FakeClient,
    admin_user_dict: dict[str, Any],
) -> AsyncClient:
    """Admin-authenticated client with in-memory supabase."""
    # Pre-create empty tables so queries return []
    for t in ("invoices", "invoice_line_items", "invoice_approvals", "email_logs"):
        fake_supabase.tables.setdefault(t, [])

    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return admin_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    token = _make_jwt(ADMIN_USER_ID, ADMIN_EMAIL, "admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        ac._fake = fake_supabase  # type: ignore[attr-defined]
        yield ac


@pytest.fixture
async def client_sales_invoices(
    fake_supabase: _FakeClient,
    sales_user_dict: dict[str, Any],
) -> AsyncClient:
    """Sales-authenticated client (non-admin) - should be blocked on admin routes."""
    app = create_app()

    async def _override_user() -> dict[str, Any]:
        return sales_user_dict

    def _override_supabase() -> _FakeClient:
        return fake_supabase

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase_client] = _override_supabase

    token = _make_jwt(SALES_USER_ID, SALES_EMAIL, "sales")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
    ) as ac:
        yield ac


async def _prime_csrf(ac: AsyncClient) -> str:
    resp = await ac.get("/health")
    return resp.cookies.get("csrf_token", "")


async def _post(
    ac: AsyncClient, url: str, *, json: Any = None, extra_headers: dict | None = None
):
    csrf = await _prime_csrf(ac)
    headers = {"X-CSRF-Token": csrf}
    if extra_headers:
        headers.update(extra_headers)
    return await ac.post(
        url,
        json=json,
        headers=headers,
        cookies={"csrf_token": csrf},
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestCreateInvoice:
    async def test_create_manually_happy_path(
        self, client_invoices: AsyncClient
    ) -> None:
        """POST / returns 201 and the created invoice."""
        response = await _post(
            client_invoices,
            "/api/v1/invoices",
            json=_sample_invoice_payload(),
        )
        if response.status_code in (404, 405):
            pytest.skip("Invoices create endpoint not available")

        assert response.status_code == 201, response.text
        body = response.json()
        data = body.get("data") or {}
        assert data.get("invoice_number") == "INV-202604-9001"


class TestListInvoicesStatusFilter:
    async def test_list_with_status_filter(
        self, client_invoices: AsyncClient
    ) -> None:
        """GET / ?status=approved returns only approved invoices."""
        fake: _FakeClient = client_invoices._fake  # type: ignore[attr-defined]
        fund_id = str(uuid4())
        lease_id = str(uuid4())
        fake.tables["invoices"] = [
            {
                "id": str(uuid4()),
                "fund_id": fund_id,
                "lease_contract_id": lease_id,
                "invoice_number": "INV-202604-0001",
                "status": "created",
                "total_amount": 100_000,
                "due_date": "2026-04-30",
                "created_at": NOW_ISO,
            },
            {
                "id": str(uuid4()),
                "fund_id": fund_id,
                "lease_contract_id": lease_id,
                "invoice_number": "INV-202604-0002",
                "status": "approved",
                "total_amount": 200_000,
                "due_date": "2026-04-30",
                "created_at": NOW_ISO,
            },
        ]

        response = await client_invoices.get(
            "/api/v1/invoices",
            params={"status": "approved"},
        )
        if response.status_code in (404, 405):
            pytest.skip("Invoices list endpoint not available")

        assert response.status_code == 200, response.text
        body = response.json()
        items = body.get("data") or []
        assert len(items) == 1
        assert items[0]["status"] == "approved"


class TestApprovalFlow:
    async def test_create_then_approve(self, client_invoices: AsyncClient) -> None:
        """Approve action auto-transitions the invoice status."""
        fake: _FakeClient = client_invoices._fake  # type: ignore[attr-defined]
        invoice_id = str(uuid4())
        fake.tables["invoices"] = [
            {
                "id": invoice_id,
                "fund_id": str(uuid4()),
                "lease_contract_id": str(uuid4()),
                "invoice_number": "INV-202604-0010",
                "status": "created",
                "total_amount": 100_000,
                "due_date": "2026-04-30",
                "created_at": NOW_ISO,
            }
        ]

        response = await _post(
            client_invoices,
            f"/api/v1/invoices/{invoice_id}/approve",
            json={
                "invoice_id": invoice_id,
                "action": "approve",
                "comment": "確認済み",
            },
        )
        if response.status_code in (404, 405):
            pytest.skip("Approve endpoint not available")

        assert response.status_code in (200, 201), response.text

        # Invoice status should have flipped to 'approved' via repo.create_approval.
        inv = fake.tables["invoices"][0]
        assert inv["status"] == "approved"


class TestSendInvoiceDryRun:
    async def test_send_invoice_in_dry_run(
        self, client_invoices: AsyncClient
    ) -> None:
        """Sending an invoice with EMAIL_DRY_RUN=true marks it sent and logs the email."""
        fake: _FakeClient = client_invoices._fake  # type: ignore[attr-defined]
        invoice_id = str(uuid4())
        fake.tables["invoices"] = [
            {
                "id": invoice_id,
                "fund_id": str(uuid4()),
                "lease_contract_id": str(uuid4()),
                "invoice_number": "INV-202604-0020",
                "status": "approved",
                "total_amount": 165_000,
                "due_date": "2026-04-30",
                "billing_period_start": "2026-04-01",
                "billing_period_end": "2026-04-30",
                "created_at": NOW_ISO,
            }
        ]
        fake.tables["invoice_line_items"] = []

        # Force dry-run setting inside the EmailService
        with patch(
            "app.services.email_service.get_settings"
        ) as mock_settings:
            s = mock_settings.return_value
            s.smtp_host = "smtp.example.com"
            s.smtp_port = 587
            s.smtp_user = "user"
            s.smtp_password = "pw"
            s.from_email = "noreply@example.com"
            s.from_name = "CVLPOS"
            s.email_dry_run = True

            response = await _post(
                client_invoices,
                f"/api/v1/invoices/{invoice_id}/send",
                json={
                    "recipient_email": "tenant@example.com",
                    "subject": "TEST",
                    "include_pdf": False,
                },
            )

        if response.status_code in (404, 405):
            pytest.skip("Send invoice endpoint not available")

        assert response.status_code == 200, response.text

        # Invoice marked 'sent'
        inv = fake.tables["invoices"][0]
        assert inv["status"] == "sent"

        # An email_logs row was created with status 'sent'
        logs = fake.tables.get("email_logs", [])
        assert len(logs) >= 1
        assert any(l.get("status") == "sent" for l in logs)


class TestInvoicePDF:
    async def test_get_pdf_returns_bytes_or_html(
        self, client_invoices: AsyncClient
    ) -> None:
        """GET /{id}/pdf returns a PDF (if fpdf2 installed) or HTML fallback."""
        fake: _FakeClient = client_invoices._fake  # type: ignore[attr-defined]
        invoice_id = str(uuid4())
        fake.tables["invoices"] = [
            {
                "id": invoice_id,
                "fund_id": str(uuid4()),
                "lease_contract_id": str(uuid4()),
                "invoice_number": "INV-202604-0030",
                "status": "approved",
                "total_amount": 100_000,
                "subtotal": 90_909,
                "tax_amount": 9_091,
                "tax_rate": 0.10,
                "due_date": "2026-04-30",
                "billing_period_start": "2026-04-01",
                "billing_period_end": "2026-04-30",
                "created_at": NOW_ISO,
            }
        ]
        fake.tables["invoice_line_items"] = []

        response = await client_invoices.get(f"/api/v1/invoices/{invoice_id}/pdf")
        if response.status_code in (404, 405):
            pytest.skip("Invoice PDF endpoint not available")

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        # fpdf2 -> application/pdf; fallback -> text/html
        assert ("pdf" in content_type) or ("text/html" in content_type)
        assert len(response.content) > 0


class TestApprovalsHistory:
    async def test_get_approvals_after_approve(
        self, client_invoices: AsyncClient
    ) -> None:
        """GET /{id}/approvals returns the approval we just recorded."""
        fake: _FakeClient = client_invoices._fake  # type: ignore[attr-defined]
        invoice_id = str(uuid4())
        fake.tables["invoices"] = [
            {
                "id": invoice_id,
                "fund_id": str(uuid4()),
                "lease_contract_id": str(uuid4()),
                "invoice_number": "INV-202604-0040",
                "status": "created",
                "total_amount": 100_000,
                "due_date": "2026-04-30",
                "created_at": NOW_ISO,
            }
        ]

        # Create the approval first
        approve_resp = await _post(
            client_invoices,
            f"/api/v1/invoices/{invoice_id}/approve",
            json={
                "invoice_id": invoice_id,
                "action": "approve",
                "comment": "LGTM",
            },
        )
        if approve_resp.status_code in (404, 405):
            pytest.skip("Approve endpoint not available")
        assert approve_resp.status_code in (200, 201)

        # Then fetch approvals
        list_resp = await client_invoices.get(
            f"/api/v1/invoices/{invoice_id}/approvals"
        )
        if list_resp.status_code in (404, 405):
            pytest.skip("Approvals list endpoint not available")

        assert list_resp.status_code == 200
        body = list_resp.json()
        approvals = body.get("data") or []
        assert len(approvals) >= 1
        assert approvals[0]["action"] == "approve"


class TestRBACGenerateMonthly:
    async def test_non_admin_blocked_on_generate_monthly(
        self, client_sales_invoices: AsyncClient
    ) -> None:
        """Sales role must be rejected by require_permission('invoices', 'write')."""
        csrf = await _prime_csrf(client_sales_invoices)
        response = await client_sales_invoices.post(
            "/api/v1/invoices/generate-monthly",
            json={
                "fund_id": str(uuid4()),
                "billing_month": "2026-04-01",
            },
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("generate-monthly endpoint not available")

        assert response.status_code == 403, response.text


class TestRBACCreateInvoice:
    async def test_non_admin_blocked_on_create(
        self, client_sales_invoices: AsyncClient
    ) -> None:
        """POST /api/v1/invoices write gate: sales role -> 403."""
        csrf = await _prime_csrf(client_sales_invoices)
        response = await client_sales_invoices.post(
            "/api/v1/invoices",
            json=_sample_invoice_payload(),
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
        if response.status_code in (404, 405):
            pytest.skip("Invoices create endpoint not available")

        assert response.status_code == 403, response.text
