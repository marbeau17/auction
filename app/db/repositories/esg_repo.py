"""Repository for ESG / transition-finance score storage."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog
from supabase import Client

from app.models.esg import FleetESGScore, VehicleESGScore

logger = structlog.get_logger()

VEHICLE_TABLE = "esg_vehicle_scores"
FLEET_TABLE = "esg_fleet_snapshots"


class ESGRepository:
    """Data access layer for ESG scores."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Vehicle scores
    # ------------------------------------------------------------------

    async def save_vehicle_score(self, score: VehicleESGScore) -> dict[str, Any]:
        """Persist a single vehicle ESG score row.

        Returns the inserted record.
        """
        try:
            payload = score.model_dump(mode="json")
            row = {
                "vehicle_id": str(score.vehicle_id),
                "scored_at": score.scored_at.isoformat(),
                "co2_intensity_g_km": score.co2_intensity_g_per_km,
                "grade": score.grade,
                "transition_eligible": score.transition_eligibility,
                "payload": payload,
            }
            resp = self._client.table(VEHICLE_TABLE).insert(row).execute()
            result = resp.data[0] if resp.data else {}
            logger.info(
                "esg_vehicle_score_saved",
                vehicle_id=str(score.vehicle_id),
                grade=score.grade,
                co2_g_km=score.co2_intensity_g_per_km,
            )
            return result
        except Exception:
            logger.exception(
                "esg_vehicle_score_save_failed",
                vehicle_id=str(score.vehicle_id),
            )
            raise

    async def get_vehicle_history(
        self,
        vehicle_id: str,
        limit: int = 120,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return ESG score history for a vehicle, newest first."""
        try:
            resp = (
                self._client.table(VEHICLE_TABLE)
                .select("*")
                .eq("vehicle_id", vehicle_id)
                .order("scored_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.exception(
                "esg_vehicle_history_fetch_failed",
                vehicle_id=vehicle_id,
            )
            raise

    # ------------------------------------------------------------------
    # Fleet snapshots
    # ------------------------------------------------------------------

    async def save_fleet_snapshot(self, snapshot: FleetESGScore) -> dict[str, Any]:
        """Upsert a fleet-level snapshot (unique on fund_id, as_of_date)."""
        try:
            row = {
                "fund_id": str(snapshot.fund_id),
                "as_of_date": snapshot.as_of_date.isoformat(),
                "avg_co2_intensity": snapshot.avg_co2_intensity_g_per_km,
                "total_tco2_year": snapshot.total_tco2_year,
                "transition_pct": snapshot.transition_pct,
                "vehicles_count": snapshot.vehicles_count,
                "payload": snapshot.model_dump(mode="json"),
            }
            resp = (
                self._client.table(FLEET_TABLE)
                .upsert(row, on_conflict="fund_id,as_of_date")
                .execute()
            )
            result = resp.data[0] if resp.data else {}
            logger.info(
                "esg_fleet_snapshot_saved",
                fund_id=str(snapshot.fund_id),
                as_of_date=str(snapshot.as_of_date),
                vehicles_count=snapshot.vehicles_count,
            )
            return result
        except Exception:
            logger.exception(
                "esg_fleet_snapshot_save_failed",
                fund_id=str(snapshot.fund_id),
            )
            raise

    async def get_fleet_trend(
        self,
        fund_id: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """Return fleet-snapshot time series for a fund, ascending by date."""
        try:
            query = (
                self._client.table(FLEET_TABLE)
                .select("*")
                .eq("fund_id", fund_id)
            )
            if start is not None:
                query = query.gte("as_of_date", start.isoformat())
            if end is not None:
                query = query.lte("as_of_date", end.isoformat())

            resp = query.order("as_of_date", desc=False).execute()
            return resp.data or []
        except Exception:
            logger.exception(
                "esg_fleet_trend_fetch_failed",
                fund_id=fund_id,
            )
            raise


__all__ = ["ESGRepository"]
