"""Repository for vehicle data access."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from supabase import Client

from app.models.vehicle import VehicleSearchParams

logger = structlog.get_logger()

TABLE = "vehicles"


class VehicleRepository:
    """Data access layer for the vehicles table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def search(
        self, params: VehicleSearchParams
    ) -> tuple[list[dict[str, Any]], int]:
        """Search vehicles with filters, pagination, and sorting.

        Args:
            params: Search/filter parameters.

        Returns:
            A tuple of (list of vehicle dicts, total count).
        """
        try:
            query = self._client.table(TABLE).select(
                "*", count="exact"
            )

            # Apply filters
            if params.maker:
                query = query.ilike("maker", f"%{params.maker}%")
            if params.model_name:
                query = query.ilike("model_name", f"%{params.model_name}%")
            if params.year_from is not None:
                query = query.gte("model_year", params.year_from)
            if params.year_to is not None:
                query = query.lte("model_year", params.year_to)
            if params.body_type:
                query = query.eq("body_type", params.body_type)
            if params.price_from is not None:
                query = query.gte("price_yen", params.price_from)
            if params.price_to is not None:
                query = query.lte("price_yen", params.price_to)
            if params.mileage_from is not None:
                query = query.gte("mileage_km", params.mileage_from)
            if params.mileage_to is not None:
                query = query.lte("mileage_km", params.mileage_to)

            # Sorting
            desc = params.order == "desc"
            query = query.order(params.sort, desc=desc)

            # Pagination
            offset = (params.page - 1) * params.per_page
            query = query.range(offset, offset + params.per_page - 1)

            response = query.execute()
            data: list[dict[str, Any]] = response.data or []
            total_count: int = response.count or 0

            return data, total_count

        except Exception:
            logger.exception("vehicle_search_failed", params=params.model_dump())
            raise

    async def get_by_id(self, vehicle_id: str) -> dict[str, Any] | None:
        """Fetch a single vehicle by its ID.

        Args:
            vehicle_id: The UUID of the vehicle.

        Returns:
            Vehicle dict or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", vehicle_id)
                .maybe_single()
                .execute()
            )
            return response.data
        except Exception:
            logger.exception("vehicle_get_by_id_failed", vehicle_id=vehicle_id)
            raise

    async def upsert_batch(
        self, vehicles: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Upsert a batch of vehicles using (source_site, source_id) as conflict key.

        Args:
            vehicles: List of vehicle dicts to upsert.

        Returns:
            Stats dict with keys: inserted, updated, skipped.
        """
        stats = {"inserted": 0, "updated": 0, "skipped": 0}

        if not vehicles:
            return stats

        try:
            # Collect existing records to determine insert vs update counts
            source_keys = [
                (v["source_site"], v["source_id"]) for v in vehicles
            ]
            source_sites = list({k[0] for k in source_keys})
            source_ids = list({k[1] for k in source_keys})

            existing_response = (
                self._client.table(TABLE)
                .select("source_site, source_id")
                .in_("source_site", source_sites)
                .in_("source_id", source_ids)
                .execute()
            )
            existing_keys = {
                (r["source_site"], r["source_id"])
                for r in (existing_response.data or [])
            }

            # Add updated_at timestamp
            now = datetime.now(timezone.utc).isoformat()
            for v in vehicles:
                v["updated_at"] = now

            # Perform upsert
            response = (
                self._client.table(TABLE)
                .upsert(
                    vehicles,
                    on_conflict="source_site,source_id",
                )
                .execute()
            )

            upserted = response.data or []
            for record in upserted:
                key = (record.get("source_site"), record.get("source_id"))
                if key in existing_keys:
                    stats["updated"] += 1
                else:
                    stats["inserted"] += 1

            logger.info("vehicle_upsert_batch_complete", **stats)
            return stats

        except Exception:
            logger.exception(
                "vehicle_upsert_batch_failed", batch_size=len(vehicles)
            )
            raise

    async def get_statistics(
        self,
        maker: Optional[str] = None,
        model: Optional[str] = None,
        year: Optional[int] = None,
        body_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Calculate price statistics for matching vehicles.

        Args:
            maker: Filter by maker name.
            model: Filter by model name.
            year: Filter by model year.
            body_type: Filter by body type.

        Returns:
            Dict with avg, median, min, max, std, count.
        """
        try:
            query = self._client.table(TABLE).select("price_yen")

            if maker:
                query = query.eq("maker", maker)
            if model:
                query = query.eq("model_name", model)
            if year is not None:
                query = query.eq("model_year", year)
            if body_type:
                query = query.eq("body_type", body_type)

            # Only include records with a price
            query = query.not_.is_("price_yen", "null")

            response = query.execute()
            rows = response.data or []

            if not rows:
                return {
                    "avg": None,
                    "median": None,
                    "min": None,
                    "max": None,
                    "std": None,
                    "count": 0,
                }

            prices = sorted(r["price_yen"] for r in rows)
            count = len(prices)
            total = sum(prices)
            avg = total / count
            min_val = prices[0]
            max_val = prices[-1]

            # Median
            mid = count // 2
            if count % 2 == 0:
                median = (prices[mid - 1] + prices[mid]) / 2
            else:
                median = prices[mid]

            # Standard deviation
            variance = sum((p - avg) ** 2 for p in prices) / count
            std = variance**0.5

            return {
                "avg": round(avg, 2),
                "median": round(median, 2),
                "min": min_val,
                "max": max_val,
                "std": round(std, 2),
                "count": count,
            }

        except Exception:
            logger.exception("vehicle_statistics_failed")
            raise

    async def mark_expired(
        self, source_site: str, active_ids: list[str]
    ) -> None:
        """Mark vehicles not in active_ids as expired for a given source site.

        Args:
            source_site: The source site name.
            active_ids: List of source_id values that are still active.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            # Find all vehicles from this source that are NOT in active_ids
            # and update their listing_status to 'expired'
            query = (
                self._client.table(TABLE)
                .update({
                    "listing_status": "expired",
                    "updated_at": now,
                })
                .eq("source_site", source_site)
                .eq("listing_status", "active")
            )

            if active_ids:
                # Exclude the active ones — mark only those NOT in the list
                query = query.not_.in_("source_id", active_ids)

            query.execute()
            logger.info(
                "vehicle_mark_expired_complete",
                source_site=source_site,
                active_count=len(active_ids),
            )

        except Exception:
            logger.exception(
                "vehicle_mark_expired_failed", source_site=source_site
            )
            raise
