"""Repository for liquidation cases and events (Phase-2C)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from supabase import Client

logger = structlog.get_logger()

CASES_TABLE = "liquidation_cases"
EVENTS_TABLE = "liquidation_events"


class LiquidationRepository:
    """Data access layer for ``liquidation_cases`` / ``liquidation_events``."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Case CRUD
    # ------------------------------------------------------------------

    async def create_case(
        self,
        *,
        vehicle_id: str,
        triggered_by: str,
        assessment_deadline: date,
        closure_deadline: date,
        sab_id: Optional[str] = None,
        fund_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert a new liquidation case in ``assessing`` status."""
        try:
            record: dict[str, Any] = {
                "vehicle_id": vehicle_id,
                "triggered_by": triggered_by,
                "status": "assessing",
                "assessment_deadline": assessment_deadline.isoformat(),
                "closure_deadline": closure_deadline.isoformat(),
                "cost_breakdown": {},
            }
            if sab_id:
                record["sab_id"] = sab_id
            if fund_id:
                record["fund_id"] = fund_id
            if notes:
                record["notes"] = notes

            response = self._client.table(CASES_TABLE).insert(record).execute()
            data = response.data
            if not data:
                raise RuntimeError("liquidation_case insert returned no data")
            logger.info(
                "liquidation_case_created",
                case_id=data[0].get("id"),
                vehicle_id=vehicle_id,
                triggered_by=triggered_by,
            )
            return data[0]
        except Exception:
            logger.exception(
                "liquidation_case_create_failed",
                vehicle_id=vehicle_id,
            )
            raise

    async def get_case(self, case_id: str) -> Optional[dict[str, Any]]:
        """Return a single case by id, or None."""
        try:
            response = (
                self._client.table(CASES_TABLE)
                .select("*")
                .eq("id", case_id)
                .maybe_single()
                .execute()
            )
            return response.data
        except Exception:
            logger.exception("liquidation_case_get_failed", case_id=case_id)
            raise

    async def list_cases(
        self,
        *,
        status: Optional[str] = None,
        fund_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List cases with optional status/fund filters."""
        try:
            query = self._client.table(CASES_TABLE).select("*")
            if status:
                query = query.eq("status", status)
            if fund_id:
                query = query.eq("fund_id", fund_id)
            query = query.order("detected_at", desc=True).range(
                offset, offset + limit - 1
            )
            response = query.execute()
            return response.data or []
        except Exception:
            logger.exception("liquidation_case_list_failed", status=status)
            raise

    async def update_status(
        self,
        case_id: str,
        *,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Update a case status plus optional fields (route, nlv_jpy, etc.)."""
        try:
            payload: dict[str, Any] = {"status": status}
            if extra:
                payload.update(extra)
            response = (
                self._client.table(CASES_TABLE)
                .update(payload)
                .eq("id", case_id)
                .execute()
            )
            data = response.data or []
            if not data:
                raise RuntimeError(f"liquidation_case {case_id} not found for update")
            logger.info(
                "liquidation_case_status_updated",
                case_id=case_id,
                status=status,
            )
            return data[0]
        except Exception:
            logger.exception(
                "liquidation_case_update_failed",
                case_id=case_id,
                status=status,
            )
            raise

    async def overdue_cases(
        self, *, as_of: Optional[date] = None
    ) -> list[dict[str, Any]]:
        """Cases whose closure deadline has passed and are not yet closed."""
        as_of = as_of or date.today()
        try:
            response = (
                self._client.table(CASES_TABLE)
                .select("*")
                .lt("closure_deadline", as_of.isoformat())
                .not_.in_("status", ["closed", "cancelled"])
                .order("closure_deadline", desc=False)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception("liquidation_overdue_query_failed")
            raise

    # ------------------------------------------------------------------
    # Events (append-only)
    # ------------------------------------------------------------------

    async def add_event(
        self,
        *,
        case_id: str,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        actor_user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append an event to the case audit log."""
        try:
            record: dict[str, Any] = {
                "case_id": case_id,
                "event_type": event_type,
                "payload": payload or {},
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            if actor_user_id:
                record["actor_user_id"] = actor_user_id
            response = self._client.table(EVENTS_TABLE).insert(record).execute()
            data = response.data
            if not data:
                raise RuntimeError("liquidation_event insert returned no data")
            return data[0]
        except Exception:
            logger.exception(
                "liquidation_event_add_failed",
                case_id=case_id,
                event_type=event_type,
            )
            raise

    async def list_events(
        self, case_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return ordered event log for a case (oldest first)."""
        try:
            response = (
                self._client.table(EVENTS_TABLE)
                .select("*")
                .eq("case_id", case_id)
                .order("occurred_at", desc=False)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception("liquidation_event_list_failed", case_id=case_id)
            raise
