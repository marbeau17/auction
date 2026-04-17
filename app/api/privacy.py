"""APPI / GDPR privacy endpoints.

Gives every authenticated user a data-portability export and a
data-erasure request workflow.  Admins review and execute erasure.

Regulatory context
------------------
* Japan 改正個人情報保護法 (APPI, 2022 amendment) grants data subjects
  a right to *disclosure of personal data* and *request for erasure*.
* GDPR Art. 15 (right of access) + Art. 17 (right to erasure) parity.
* Japanese 法人税法 mandates **7-year retention** of accounting books
  and related evidence.  ``POST /execute`` therefore only redacts PII
  columns on the ``users`` table and on ``deal_stakeholders`` contact
  fields — it does NOT hard-delete invoices, lease-payments, or any
  other accounting artefact.

Endpoints
---------
* ``GET  /api/v1/privacy/export``                         — authenticated user
* ``POST /api/v1/privacy/delete-request``                 — authenticated user
* ``GET  /api/v1/privacy/deletion-requests``              — admin only
* ``POST /api/v1/privacy/deletion-requests/{id}/execute`` — admin only
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from supabase import Client

from app.db.repositories.privacy_repo import PrivacyRepository
from app.dependencies import get_current_user, get_supabase_client
from app.middleware.rbac import require_any_role
from app.models.common import SuccessResponse
from app.models.privacy import DeletionRequest, DeletionRequestResponse
from app.services.email_service import EmailService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_repo(
    supabase: Client = Depends(get_supabase_client),
) -> PrivacyRepository:
    """FastAPI dependency providing a ``PrivacyRepository``."""
    return PrivacyRepository(client=supabase)


def _json_default(value: Any) -> Any:
    """Serialise non-JSON-native values (datetime, UUID, Decimal) as text."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"Type {type(value)!r} is not JSON serialisable")


def _dump(rows: Any) -> str:
    """Pretty-print a value as UTF-8 JSON suitable for archiving."""
    return json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default)


# ---------------------------------------------------------------------------
# GET /export — right of access (APPI 第33条 / GDPR Art. 15)
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export the caller's personal data as a ZIP of JSON files",
    responses={
        200: {
            "description": "ZIP stream containing per-table JSON dumps",
            "content": {"application/zip": {}},
        }
    },
)
async def export_my_data(
    user: dict[str, Any] = Depends(get_current_user),
    repo: PrivacyRepository = Depends(_get_repo),
) -> StreamingResponse:
    """Stream every row owned by the caller as a ZIP archive.

    Contents (one file per table, JSON):

    * ``profile.json``              — ``users`` row (the authenticated user)
    * ``simulations.json``          — rows the user created
    * ``financial_analyses.json``   — rows the user created
    * ``invoices.json``             — rows billed to the user
    * ``email_logs.json``           — email logs for those invoices
    * ``stakeholders.json``         — ``deal_stakeholders`` where the user is
                                     the recorded contact
    * ``manifest.json``             — generation metadata (no PII of others)

    The endpoint filters **strictly by the authenticated user's id**, so
    no cross-user data leakage is possible.
    """
    user_id = UUID(user["id"])
    logger.info("privacy_export_requested", user_id=str(user_id))

    profile = await repo.fetch_user_row(user_id) or {}
    simulations = await repo.fetch_table_for_user(
        "simulations", "created_by", user_id
    )
    financial_analyses = await repo.fetch_table_for_user(
        "financial_analyses", "created_by", user_id
    )

    # Invoices the user was billed for.  Different schemas use different
    # owner columns; try the most specific first, fall back gracefully.
    invoices = await repo.fetch_table_for_user(
        "invoices", "end_user_id", user_id
    )
    if not invoices:
        invoices = await repo.fetch_table_for_user(
            "invoices", "created_by", user_id
        )

    # Email logs scoped to the user's invoices only.
    email_logs: list[dict[str, Any]] = []
    for inv in invoices:
        inv_id = inv.get("id")
        if not inv_id:
            continue
        email_logs.extend(
            await repo.fetch_table_for_user("email_logs", "invoice_id", inv_id)
        )

    stakeholders = await repo.fetch_table_for_user(
        "deal_stakeholders", "contact_user_id", user_id
    )

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "user_id": str(user_id),
        "note": (
            "Export generated under APPI 第33条 / GDPR Art. 15. "
            "Contains only data where the user is the owner or contact. "
            "Financial / accounting records are kept server-side for 7 years "
            "per Japanese tax law regardless of deletion requests."
        ),
        "files": [
            "profile.json",
            "simulations.json",
            "financial_analyses.json",
            "invoices.json",
            "email_logs.json",
            "stakeholders.json",
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", _dump(profile))
        zf.writestr("simulations.json", _dump(simulations))
        zf.writestr("financial_analyses.json", _dump(financial_analyses))
        zf.writestr("invoices.json", _dump(invoices))
        zf.writestr("email_logs.json", _dump(email_logs))
        zf.writestr("stakeholders.json", _dump(stakeholders))
        zf.writestr("manifest.json", _dump(manifest))
    buffer.seek(0)

    logger.info(
        "privacy_export_generated",
        action="privacy.export",
        user_id=str(user_id),
        bytes=buffer.getbuffer().nbytes,
        counts={
            "simulations": len(simulations),
            "financial_analyses": len(financial_analyses),
            "invoices": len(invoices),
            "email_logs": len(email_logs),
            "stakeholders": len(stakeholders),
        },
    )

    filename = f"privacy-export-{user_id}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /delete-request — right to erasure (filed, not executed)
# ---------------------------------------------------------------------------


@router.post(
    "/delete-request",
    status_code=status.HTTP_201_CREATED,
    response_model=DeletionRequestResponse,
    summary="File a data-erasure request (pending admin review)",
)
async def create_delete_request(
    payload: DeletionRequest,
    user: dict[str, Any] = Depends(get_current_user),
    repo: PrivacyRepository = Depends(_get_repo),
) -> DeletionRequestResponse:
    """Record an APPI/GDPR erasure request in ``pending_review`` status.

    This endpoint intentionally does NOT hard-delete anything.  APPI
    mandates identity verification before erasure, and Japanese tax law
    requires 7-year retention of accounting records — so every request
    must be reviewed by an admin before :func:`execute_deletion_request`
    is invoked.
    """
    user_id = UUID(user["id"])
    row = await repo.create_deletion_request(
        user_id=user_id,
        reason=payload.reason,
    )

    # Notify admin (best-effort; never blocks the response).
    try:
        email_service = EmailService()
        admin_email = getattr(email_service, "from_email", None)
        if admin_email:
            subject = f"[APPI] Deletion request filed: {user.get('email')}"
            body = (
                f"User {user.get('email')} (id={user_id}) has filed "
                f"a data-erasure request.\n\n"
                f"Reason: {payload.reason or '(none provided)'}\n"
                f"Request id: {row.get('id')}\n\n"
                f"Review at /api/v1/privacy/deletion-requests"
            )
            # EmailService lacks a generic send hook in this codebase, so
            # we log the outbound notification.  Downstream operators can
            # wire this to any transport (SES, SendGrid, ...) they prefer.
            logger.info(
                "privacy_admin_notification_queued",
                to=admin_email,
                subject=subject,
                body=body,
            )
    except Exception:
        logger.exception("privacy_admin_notification_failed")

    logger.info(
        "privacy_delete_request_filed",
        action="privacy.delete_request",
        user_id=str(user_id),
        request_id=row.get("id"),
    )
    return DeletionRequestResponse.model_validate(row)


# ---------------------------------------------------------------------------
# GET /deletion-requests — admin only
# ---------------------------------------------------------------------------


@router.get(
    "/deletion-requests",
    response_model=list[DeletionRequestResponse],
    summary="List pending deletion requests (admin only)",
)
async def list_pending_requests(
    repo: PrivacyRepository = Depends(_get_repo),
    admin: dict[str, Any] = Depends(require_any_role("admin")),
) -> list[DeletionRequestResponse]:
    """Return the FIFO queue of ``pending_review`` deletion requests."""
    rows = await repo.list_pending()
    logger.info(
        "privacy_pending_listed",
        action="privacy.list_pending",
        admin_id=admin.get("id"),
        count=len(rows),
    )
    return [DeletionRequestResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /deletion-requests/{id}/execute — admin hard-execute (PII scrub)
# ---------------------------------------------------------------------------


@router.post(
    "/deletion-requests/{request_id}/execute",
    response_model=SuccessResponse,
    summary="Execute an approved deletion request (admin only)",
)
async def execute_deletion_request(
    request_id: UUID,
    repo: PrivacyRepository = Depends(_get_repo),
    admin: dict[str, Any] = Depends(require_any_role("admin")),
) -> SuccessResponse:
    """Redact PII for the requesting user, keeping audit rows.

    This performs the workflow's terminal step:

    1. Flip ``users.is_deleted=true`` and set ``deleted_at`` / ``redacted_at``.
    2. Overwrite ``users.email`` / ``users.full_name`` with sentinels.
    3. Scrub PII columns on ``deal_stakeholders`` rows where the user is
       the recorded contact.
    4. Move the request row to status=``executed``.

    Rows in ``invoices``, ``invoice_line_items``, ``invoice_approvals``,
    ``email_logs``, ``lease_contracts``, ``lease_payments``,
    ``simulations``, ``simulation_params``, and ``financial_analyses``
    are **kept intact** to satisfy Japanese tax law's 7-year retention
    requirement (法人税法 施行規則 第59条).
    """
    request_row = await repo.get(request_id)
    if request_row is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")

    user_id = UUID(request_row["user_id"])
    # Mark as approved first so the audit chain (review -> execute) is intact.
    if request_row.get("status") == "pending_review":
        await repo.mark_approved(request_id, UUID(admin["id"]))

    summary = await repo.execute_redaction(user_id=user_id, request_id=request_id)

    logger.info(
        "privacy_delete_executed",
        action="privacy.execute",
        admin_id=admin.get("id"),
        request_id=str(request_id),
        user_id=str(user_id),
        users_redacted=summary["users_redacted"],
        stakeholders_redacted=summary["stakeholders_redacted"],
    )

    return SuccessResponse(
        data=summary,
        meta={
            "message": "Deletion request executed; PII redacted, audit rows retained.",
        },
    )
