"""Repository for persisted LTV snapshots (``ltv_snapshots`` table)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

TABLE = "ltv_snapshots"


class LTVRepository:
    """Data access layer for fund-level LTV snapshot history."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def snapshot_ltv(
        self,
        fund_id: str,
        as_of_date: date,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a fund-level LTV result for a given date.

        ``result`` is the dict shape returned by
        ``LTVValuator.calculate_fund_ltv``.  The full structure is stored
        in ``payload`` JSONB; headline metrics are promoted to top-level
        columns for querying.

        Upserts on ``(fund_id, as_of_date)``.
        """
        record = {
            "fund_id": fund_id,
            "as_of_date": str(as_of_date),
            "ltv_ratio": result.get("ltv_ratio"),
            "book_value_total": result.get("book_value_total"),
            "outstanding_principal_total": result.get("outstanding_principal_total"),
            "vehicles_count": result.get("vehicles_count"),
            "breach_count": result.get("breach_count"),
            "payload": _serialize_payload(result),
        }
        try:
            response = (
                self._client.table(TABLE)
                .upsert(record, on_conflict="fund_id,as_of_date")
                .execute()
            )
            row = (response.data or [{}])[0]
            logger.info(
                "ltv_snapshot_persisted",
                fund_id=fund_id,
                as_of_date=str(as_of_date),
                ltv_ratio=record["ltv_ratio"],
                breach_count=record["breach_count"],
            )
            return row
        except Exception:
            logger.exception(
                "ltv_snapshot_persist_failed",
                fund_id=fund_id,
                as_of_date=str(as_of_date),
            )
            raise

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_history(
        self,
        fund_id: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return LTV snapshots for a fund within [start, end], newest first."""
        try:
            query = (
                self._client.table(TABLE)
                .select("*")
                .eq("fund_id", fund_id)
            )
            if start is not None:
                query = query.gte("as_of_date", str(start))
            if end is not None:
                query = query.lte("as_of_date", str(end))

            response = (
                query.order("as_of_date", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception(
                "ltv_history_fetch_failed",
                fund_id=fund_id,
                start=str(start) if start else None,
                end=str(end) if end else None,
            )
            raise

    async def get_latest(
        self,
        fund_id: str,
    ) -> Optional[dict[str, Any]]:
        """Return the most recent snapshot for a fund (or None)."""
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("fund_id", fund_id)
                .order("as_of_date", desc=True)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            return rows[0] if rows else None
        except Exception:
            logger.exception("ltv_latest_fetch_failed", fund_id=fund_id)
            raise


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _serialize_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Convert non-JSON-serialisable values (date, UUID) to primitives."""
    import json
    from uuid import UUID
    from datetime import date as _date

    def default(o: Any) -> Any:
        if isinstance(o, (UUID,)):
            return str(o)
        if isinstance(o, _date):
            return o.isoformat()
        raise TypeError(f"Unserialisable type: {type(o)}")

    # Round-trip through JSON to force primitive types
    return json.loads(json.dumps(result, default=default))
