"""Repository for finance_assessments — persistence layer for LLM-extracted
決算書 diagnoses.

Privacy note: never log the raw ``extracted_input`` / ``diagnosis`` /
``narrative`` payloads — they contain customer financial data subject to
APPI and the 7-year tax-law retention window (法人税法 施行規則 第59条).
Only ids, user_ids, hashes, model names, counts, and costs are safe to log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from supabase import Client

logger = structlog.get_logger()

TABLE = "finance_assessments"


class FinanceAssessmentRepository:
    """CRUD + dedup + cost-aggregation for ``finance_assessments``.

    All methods are ``async`` for API uniformity; the underlying Supabase
    client is synchronous, but thin wrappers let the API layer ``await``
    consistently (same convention as ``privacy_repo``/``invoice_repo``).
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Create / read
    # ------------------------------------------------------------------

    async def create(self, **fields: Any) -> dict[str, Any]:
        """Insert a single assessment row and return it.

        ``fields`` is the full column payload (``user_id``, ``pdf_sha256``,
        ``extracted_input`` dict, ``diagnosis`` dict, ``model``,
        ``cost_usd``, optionally ``fund_id`` / ``narrative`` /
        ``needs_vision`` / ``retention_until``).
        """
        try:
            response = (
                self._client.table(TABLE).insert(fields).execute()
            )
            data = response.data or []
            if not data:
                raise RuntimeError(
                    "finance_assessment insert returned no data"
                )
            row = data[0]
            # PII-safe log: no payload, no narrative.
            logger.info(
                "finance_assessment_created",
                id=row.get("id"),
                user_id=str(fields.get("user_id")) if fields.get("user_id") else None,
                pdf_sha256=fields.get("pdf_sha256"),
                needs_vision=fields.get("needs_vision", False),
                model=fields.get("model"),
                cost_usd=float(fields.get("cost_usd", 0) or 0),
            )
            return row
        except Exception:
            logger.exception(
                "finance_assessment_create_failed",
                user_id=str(fields.get("user_id")) if fields.get("user_id") else None,
                pdf_sha256=fields.get("pdf_sha256"),
            )
            raise

    async def get_by_id(
        self, assessment_id: UUID
    ) -> Optional[dict[str, Any]]:
        """Fetch one assessment by id, or ``None`` if missing."""
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", str(assessment_id))
                .execute()
            )
            rows = response.data or []
            return rows[0] if rows else None
        except Exception:
            logger.exception(
                "finance_assessment_get_failed",
                assessment_id=str(assessment_id),
            )
            raise

    async def get_by_hash(
        self, user_id: UUID, pdf_sha256: str
    ) -> Optional[dict[str, Any]]:
        """Dedup lookup: find the user's cached diagnosis for this PDF.

        Returns the most-recently-created match (there should be at most
        one thanks to ``uq_finance_assessments_user_hash``; the
        ``order + limit(1)`` shape is defensive in case the unique index
        is temporarily absent during a rollout).
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("user_id", str(user_id))
                .eq("pdf_sha256", pdf_sha256)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            return rows[0] if rows else None
        except Exception:
            logger.exception(
                "finance_assessment_get_by_hash_failed",
                user_id=str(user_id),
                pdf_sha256=pdf_sha256,
            )
            raise

    async def list_by_user(
        self,
        user_id: UUID,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated listing for a single user, newest first.

        Returns ``(rows, total_count)`` matching the
        ``InvoiceRepository.list_invoices`` convention.
        """
        try:
            offset = (page - 1) * per_page
            response = (
                self._client.table(TABLE)
                .select("*", count="exact")
                .eq("user_id", str(user_id))
                .order("created_at", desc=True)
                .range(offset, offset + per_page - 1)
                .execute()
            )
            rows = response.data or []
            total = response.count or 0
            return rows, total
        except Exception:
            logger.exception(
                "finance_assessment_list_failed",
                user_id=str(user_id),
                page=page,
                per_page=per_page,
            )
            raise

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, assessment_id: UUID) -> bool:
        """Delete one assessment by id. Returns True iff a row was removed."""
        try:
            response = (
                self._client.table(TABLE)
                .delete()
                .eq("id", str(assessment_id))
                .execute()
            )
            deleted = bool(response.data)
            logger.info(
                "finance_assessment_deleted",
                assessment_id=str(assessment_id),
                deleted=deleted,
            )
            return deleted
        except Exception:
            logger.exception(
                "finance_assessment_delete_failed",
                assessment_id=str(assessment_id),
            )
            raise

    # ------------------------------------------------------------------
    # Cost aggregation
    # ------------------------------------------------------------------

    async def sum_cost_current_month(
        self, user_id: Optional[UUID] = None
    ) -> float:
        """Sum ``cost_usd`` for rows created this calendar month (UTC).

        When ``user_id`` is given, restrict to that user's rows; otherwise
        aggregate across all users (admin budget dashboard).

        MVP aggregation in Python (≤hundreds of rows/month). Move to a
        server-side RPC (e.g. ``rpc_sum_finance_cost_month``) if monthly
        volume exceeds ~5k rows — the column is indexed on
        ``created_at`` so a SQL ``sum()`` would be trivial.
        """
        try:
            now = datetime.now(timezone.utc)
            month_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            query = (
                self._client.table(TABLE)
                .select("cost_usd,created_at")
                .gte("created_at", month_start.isoformat())
            )
            if user_id is not None:
                query = query.eq("user_id", str(user_id))
            response = query.execute()
            rows = response.data or []
            total = 0.0
            for r in rows:
                try:
                    total += float(r.get("cost_usd") or 0)
                except (TypeError, ValueError):
                    continue
            return total
        except Exception:
            logger.exception(
                "finance_assessment_sum_cost_failed",
                user_id=str(user_id) if user_id else None,
            )
            raise

    # ------------------------------------------------------------------
    # Retention / purge
    # ------------------------------------------------------------------

    async def purge_expired(self) -> int:
        """Delete every row whose ``retention_until`` has elapsed.

        Returns the count of rows deleted (0 when nothing aged out).
        Called nightly by ``scripts/cron/purge_expired_assessments.py``.
        """
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            response = (
                self._client.table(TABLE)
                .delete()
                .lt("retention_until", now_iso)
                .execute()
            )
            count = len(response.data or [])
            logger.info("finance_assessments_purged", count=count)
            return count
        except Exception:
            logger.exception("finance_assessment_purge_failed")
            raise
