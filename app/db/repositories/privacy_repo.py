"""Repository for APPI / GDPR privacy workflows.

This module implements the data-access side of the right-to-erasure /
data-portability endpoints exposed by :mod:`app.api.privacy`.

Regulatory note (IMPORTANT):

    Japanese tax law (法人税法 施行規則 第59条) requires businesses to
    retain accounting books and related evidence (invoices, payment
    records, lease contracts, ...) for **7 years**.  This is a hard
    retention obligation that supersedes an APPI right-to-erasure
    request.

    Consequently :meth:`PrivacyRepository.execute_redaction` DOES NOT
    hard-delete any rows from ``invoices``, ``invoice_line_items``,
    ``lease_payments``, ``lease_contracts``, ``simulations``,
    ``financial_analyses``, ``email_logs`` etc.

    Instead it redacts *personal-identifier* columns on the ``users``
    table (email, full_name) and on ``deal_stakeholders`` rows where
    the user is the registered contact (contact_name, contact_email,
    address_line).  A soft-delete flag ``is_deleted`` plus a
    ``redacted_at`` timestamp are recorded for audit purposes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from supabase import Client

logger = structlog.get_logger()


TABLE_REQUESTS = "privacy_deletion_requests"
TABLE_USERS = "users"
TABLE_STAKEHOLDERS = "deal_stakeholders"

# PII replacement sentinel.  We keep the row but overwrite PII columns
# so that accounting audits still reference a stable surrogate id.
REDACTED_EMAIL = "redacted@redacted.local"
REDACTED_NAME = "[REDACTED]"


class PrivacyRepository:
    """CRUD + workflow helpers for ``privacy_deletion_requests``.

    All methods are async for API uniformity; the underlying Supabase
    client is synchronous, but thin wrappers let the API layer ``await``
    consistently.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Deletion-request workflow
    # ------------------------------------------------------------------

    async def create_deletion_request(
        self,
        user_id: UUID,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert a new ``pending_review`` deletion request.

        Returns the inserted row.  Raises ``RuntimeError`` if Supabase
        returned no data.
        """
        payload = {
            "user_id": str(user_id),
            "reason": reason,
            "status": "pending_review",
        }
        response = (
            self._client.table(TABLE_REQUESTS).insert(payload).execute()
        )
        data = response.data or []
        if not data:
            raise RuntimeError("privacy_deletion_request insert returned no data")
        logger.info(
            "privacy_deletion_request_created",
            user_id=str(user_id),
            request_id=data[0].get("id"),
        )
        return data[0]

    async def list_pending(self) -> list[dict[str, Any]]:
        """Return all requests with status ``pending_review``.

        Sorted oldest-first so reviewers work a FIFO queue.
        """
        response = (
            self._client.table(TABLE_REQUESTS)
            .select("*")
            .eq("status", "pending_review")
            .order("requested_at", desc=False)
            .execute()
        )
        return response.data or []

    async def get(self, request_id: UUID) -> Optional[dict[str, Any]]:
        """Fetch one request by id (or ``None`` if missing)."""
        response = (
            self._client.table(TABLE_REQUESTS)
            .select("*")
            .eq("id", str(request_id))
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    async def mark_approved(
        self,
        request_id: UUID,
        reviewer_id: UUID,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Mark a request as ``approved`` (pre-execution).

        Separate from :meth:`execute_redaction` so an admin can approve
        without immediately performing the data scrub (two-step review).
        """
        now = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "status": "approved",
            "reviewed_by": str(reviewer_id),
            "reviewed_at": now,
        }
        if notes is not None:
            payload["notes"] = notes

        response = (
            self._client.table(TABLE_REQUESTS)
            .update(payload)
            .eq("id", str(request_id))
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise RuntimeError(
                f"privacy_deletion_request {request_id} not found"
            )
        return rows[0]

    async def mark_rejected(
        self,
        request_id: UUID,
        reviewer_id: UUID,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Reject a request (e.g. identity verification failed)."""
        now = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "status": "rejected",
            "reviewed_by": str(reviewer_id),
            "reviewed_at": now,
        }
        if notes is not None:
            payload["notes"] = notes
        response = (
            self._client.table(TABLE_REQUESTS)
            .update(payload)
            .eq("id", str(request_id))
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise RuntimeError(
                f"privacy_deletion_request {request_id} not found"
            )
        return rows[0]

    # ------------------------------------------------------------------
    # Redaction (hard execution)
    # ------------------------------------------------------------------

    async def execute_redaction(
        self,
        user_id: UUID,
        request_id: Optional[UUID] = None,
    ) -> dict[str, Any]:
        """Perform PII redaction for ``user_id`` in a single logical batch.

        Tables touched (PII-redacted, NOT deleted):

        * ``users``              — set ``email``, ``full_name`` to
                                  redacted sentinels; ``is_active`` ->
                                  false, ``is_deleted`` -> true,
                                  ``deleted_at`` + ``redacted_at`` set.
        * ``deal_stakeholders`` — rows where the user is the recorded
                                  contact have ``contact_name``,
                                  ``contact_email``, ``phone``,
                                  ``address_line`` cleared (kept for
                                  contractual audit trail).

        Tables explicitly NOT touched (retained per Japanese tax law):

        * ``invoices``, ``invoice_line_items``, ``invoice_approvals``
        * ``email_logs``
        * ``lease_contracts``, ``lease_payments``
        * ``simulations``, ``simulation_params``
        * ``financial_analyses``

        The deletion request (if provided) is transitioned to
        ``executed``.  Returns a summary dict with counts for logging.

        Idempotency: running twice is safe.  Re-running sets the same
        sentinels and increments no counters past the first pass, because
        the update predicate uses ``user_id`` / ``contact_user_id`` and
        the target values are constant.
        """
        now = datetime.now(timezone.utc).isoformat()
        summary: dict[str, Any] = {
            "user_id": str(user_id),
            "executed_at": now,
            "users_redacted": 0,
            "stakeholders_redacted": 0,
            "retained_tables": [
                "invoices",
                "invoice_line_items",
                "invoice_approvals",
                "email_logs",
                "lease_contracts",
                "lease_payments",
                "simulations",
                "simulation_params",
                "financial_analyses",
            ],
        }

        # 1) Redact the users row ---------------------------------------
        users_payload = {
            "email": REDACTED_EMAIL,
            "full_name": REDACTED_NAME,
            "is_active": False,
            "is_deleted": True,
            "deleted_at": now,
            "redacted_at": now,
        }
        users_resp = (
            self._client.table(TABLE_USERS)
            .update(users_payload)
            .eq("id", str(user_id))
            .execute()
        )
        summary["users_redacted"] = len(users_resp.data or [])

        # 2) Redact stakeholder contact columns -------------------------
        # The stakeholder table uses ``contact_user_id`` to link to a
        # user.  Only PII columns are cleared; company_name / role_type
        # are preserved because they are contractual metadata.
        stakeholder_payload = {
            "contact_name": REDACTED_NAME,
            "contact_email": REDACTED_EMAIL,
            "phone": None,
            "address_line": None,
        }
        try:
            stake_resp = (
                self._client.table(TABLE_STAKEHOLDERS)
                .update(stakeholder_payload)
                .eq("contact_user_id", str(user_id))
                .execute()
            )
            summary["stakeholders_redacted"] = len(stake_resp.data or [])
        except Exception:
            # Older schemas may not have contact_user_id; degrade gracefully.
            logger.warning(
                "stakeholder_redaction_skipped",
                user_id=str(user_id),
                reason="contact_user_id column missing or query failed",
            )
            summary["stakeholders_redacted"] = 0

        # 3) Flip the request row to executed ---------------------------
        if request_id is not None:
            self._client.table(TABLE_REQUESTS).update(
                {"status": "executed", "executed_at": now}
            ).eq("id", str(request_id)).execute()

        logger.info(
            "privacy_redaction_executed",
            user_id=str(user_id),
            request_id=str(request_id) if request_id else None,
            users_redacted=summary["users_redacted"],
            stakeholders_redacted=summary["stakeholders_redacted"],
        )
        return summary

    # ------------------------------------------------------------------
    # Export helpers (used by GET /privacy/export)
    # ------------------------------------------------------------------

    async def fetch_user_row(self, user_id: UUID) -> Optional[dict[str, Any]]:
        resp = (
            self._client.table(TABLE_USERS)
            .select("*")
            .eq("id", str(user_id))
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    async def fetch_table_for_user(
        self,
        table: str,
        column: str,
        user_id: UUID,
    ) -> list[dict[str, Any]]:
        """Generic ``SELECT * FROM <table> WHERE <column> = user_id``.

        Used by the export endpoint to gather per-table dumps.
        """
        try:
            resp = (
                self._client.table(table)
                .select("*")
                .eq(column, str(user_id))
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.warning(
                "privacy_export_table_unavailable",
                table=table,
                column=column,
            )
            return []
