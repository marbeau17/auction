"""Repository for investor-report rows and their access-log audit trail."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger()

TABLE = "investor_reports"
ACCESS_LOG_TABLE = "investor_report_access_logs"


class InvestorReportRepository:
    """CRUD + access-log helpers for the monthly investor report feature."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    async def create(self, report: dict[str, Any]) -> dict[str, Any]:
        """Persist a newly generated investor report row."""
        try:
            resp = self._client.table(TABLE).insert(report).execute()
            data = resp.data
            if not data:
                raise RuntimeError("investor_reports insert returned no data")
            return data[0]
        except Exception:
            logger.exception(
                "investor_report_create_failed",
                fund_id=report.get("fund_id"),
                report_month=report.get("report_month"),
            )
            raise

    async def get(self, report_id: UUID | str) -> Optional[dict[str, Any]]:
        try:
            resp = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", str(report_id))
                .maybe_single()
                .execute()
            )
            return resp.data
        except Exception:
            logger.exception("investor_report_get_failed", report_id=str(report_id))
            raise

    async def list_by_fund(
        self,
        fund_id: UUID | str,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """Return the most recent reports for a fund, newest first."""
        try:
            resp = (
                self._client.table(TABLE)
                .select("*")
                .eq("fund_id", str(fund_id))
                .order("report_month", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.exception("investor_report_list_failed", fund_id=str(fund_id))
            raise

    async def get_by_month(
        self,
        fund_id: UUID | str,
        month: date,
    ) -> Optional[dict[str, Any]]:
        """Look up the report for a specific (fund, first-of-month)."""
        try:
            month = month.replace(day=1)
            resp = (
                self._client.table(TABLE)
                .select("*")
                .eq("fund_id", str(fund_id))
                .eq("report_month", month.isoformat())
                .maybe_single()
                .execute()
            )
            return resp.data
        except Exception:
            logger.exception(
                "investor_report_get_by_month_failed",
                fund_id=str(fund_id),
                month=month.isoformat(),
            )
            raise

    async def upsert_for_month(
        self,
        fund_id: UUID | str,
        report_month: date,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create-or-replace the report for (fund, month)."""
        existing = await self.get_by_month(fund_id, report_month)
        if existing is None:
            return await self.create(payload)
        try:
            resp = (
                self._client.table(TABLE)
                .update(payload)
                .eq("id", existing["id"])
                .execute()
            )
            data = resp.data
            if data:
                return data[0]
            return {**existing, **payload}
        except Exception:
            logger.exception(
                "investor_report_update_failed", report_id=existing.get("id")
            )
            raise

    # ------------------------------------------------------------------
    # Access log (audit trail)
    # ------------------------------------------------------------------

    async def record_access(
        self,
        report_id: UUID | str,
        accessed_by: Optional[UUID | str],
        signed_url_hash: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        downloaded: bool = False,
    ) -> dict[str, Any]:
        """Insert a new access-log entry.

        ``downloaded=True`` is only set when this row represents an actual
        PDF redemption; otherwise the row records the signed-URL issuance.
        """
        row: dict[str, Any] = {
            "report_id": str(report_id),
            "signed_url_hash": signed_url_hash,
            "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
        }
        if accessed_by is not None:
            row["accessed_by"] = str(accessed_by)
        if ip_address:
            row["ip_address"] = ip_address
        if downloaded:
            row["downloaded_at"] = datetime.now(timezone.utc).isoformat()

        try:
            resp = self._client.table(ACCESS_LOG_TABLE).insert(row).execute()
            data = resp.data
            if not data:
                raise RuntimeError("investor_report_access_logs insert returned no data")
            return data[0]
        except Exception:
            logger.exception(
                "investor_report_access_log_create_failed",
                report_id=str(report_id),
            )
            raise

    async def mark_downloaded(
        self,
        signed_url_hash: str,
        ip_address: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Flip ``downloaded_at`` on the access-log row with the given hash."""
        try:
            update: dict[str, Any] = {
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            if ip_address:
                update["ip_address"] = ip_address
            resp = (
                self._client.table(ACCESS_LOG_TABLE)
                .update(update)
                .eq("signed_url_hash", signed_url_hash)
                .execute()
            )
            data = resp.data or []
            return data[0] if data else None
        except Exception:
            logger.exception(
                "investor_report_access_log_update_failed",
                signed_url_hash=signed_url_hash,
            )
            raise

    async def find_active_access(
        self, signed_url_hash: str
    ) -> Optional[dict[str, Any]]:
        """Find the (hopefully unique) access-log row for a token hash."""
        try:
            resp = (
                self._client.table(ACCESS_LOG_TABLE)
                .select("*")
                .eq("signed_url_hash", signed_url_hash)
                .limit(1)
                .execute()
            )
            data = resp.data or []
            return data[0] if data else None
        except Exception:
            logger.exception(
                "investor_report_access_lookup_failed",
                signed_url_hash=signed_url_hash,
            )
            raise
