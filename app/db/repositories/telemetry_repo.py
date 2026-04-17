"""Repository for vehicle telemetry events and daily aggregates.

Phase-3a foundation:
* ``insert_event`` / ``insert_events`` — persist raw samples (non-monotonic
  odometer readings are logged as warnings, not rejected).
* ``list_recent`` — most-recent N events for a vehicle.
* ``daily_aggregate`` — READ pre-computed rollups for a date range. The
  actual rollup *writer* is future work (see docs/telemetry_roadmap.md).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from supabase import Client

logger = structlog.get_logger()

TELEMETRY_TABLE = "vehicle_telemetry"
AGGREGATES_TABLE = "telemetry_aggregates"


class TelemetryRepository:
    """CRUD operations for telemetry and aggregate tables."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def insert_event(
        self, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Insert a single telemetry event.

        Emits a structured warning when ``odometer_km`` regresses relative
        to the most recent event for the same vehicle (odometer resets are
        valid but worth surfacing). Returns the inserted row.
        """
        payload = self._serialize(event)

        # --- Odometer monotonicity check (warning only) ------------------
        odo = payload.get("odometer_km")
        vehicle_id = payload.get("vehicle_id")
        if odo is not None and vehicle_id is not None:
            try:
                prev = (
                    self._client.table(TELEMETRY_TABLE)
                    .select("odometer_km", "recorded_at")
                    .eq("vehicle_id", vehicle_id)
                    .order("recorded_at", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = prev.data or []
                if rows and rows[0].get("odometer_km") is not None:
                    if odo < int(rows[0]["odometer_km"]):
                        logger.warning(
                            "telemetry_odometer_regression",
                            vehicle_id=vehicle_id,
                            previous=rows[0]["odometer_km"],
                            incoming=odo,
                        )
            except Exception:
                # Monotonicity lookup failures must never block ingest.
                logger.exception(
                    "telemetry_monotonicity_check_failed",
                    vehicle_id=vehicle_id,
                )

        try:
            response = (
                self._client.table(TELEMETRY_TABLE)
                .insert(payload)
                .execute()
            )
            data = response.data
            if not data:
                raise RuntimeError("Telemetry insert returned no data")
            return data[0]
        except Exception:
            logger.exception(
                "telemetry_insert_failed",
                vehicle_id=vehicle_id,
                device_id=payload.get("device_id"),
            )
            raise

    async def insert_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Bulk insert without the per-event monotonicity lookup."""
        if not events:
            return []
        payloads = [self._serialize(e) for e in events]
        try:
            response = (
                self._client.table(TELEMETRY_TABLE)
                .insert(payloads)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception(
                "telemetry_batch_insert_failed",
                count=len(payloads),
            )
            raise

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def list_recent(
        self,
        vehicle_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the ``limit`` most-recent events for a vehicle."""
        try:
            response = (
                self._client.table(TELEMETRY_TABLE)
                .select("*")
                .eq("vehicle_id", str(vehicle_id))
                .order("recorded_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception(
                "telemetry_list_recent_failed",
                vehicle_id=str(vehicle_id),
            )
            raise

    async def daily_aggregate(
        self,
        vehicle_id: UUID,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Read pre-computed daily rollups within ``[start, end]`` (inclusive).

        This is a READ-only method; the corresponding write-side rollup job
        is out of scope for the Phase-3a foundation.
        """
        if end < start:
            raise ValueError("daily_aggregate: end must be >= start")
        try:
            response = (
                self._client.table(AGGREGATES_TABLE)
                .select("*")
                .eq("vehicle_id", str(vehicle_id))
                .gte("agg_date", start.isoformat())
                .lte("agg_date", end.isoformat())
                .order("agg_date", desc=False)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception(
                "telemetry_daily_aggregate_failed",
                vehicle_id=str(vehicle_id),
                start=start.isoformat(),
                end=end.isoformat(),
            )
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(event: dict[str, Any]) -> dict[str, Any]:
        """Coerce UUID / datetime values into JSON-friendly strings."""
        out: dict[str, Any] = {}
        for key, value in event.items():
            if isinstance(value, UUID):
                out[key] = str(value)
            elif isinstance(value, datetime):
                out[key] = value.astimezone(timezone.utc).isoformat()
            elif isinstance(value, date):
                out[key] = value.isoformat()
            else:
                out[key] = value
        return out
