"""Repository for simulation data access."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from supabase import Client

logger = structlog.get_logger()

TABLE = "simulations"


class SimulationRepository:
    """Data access layer for the simulations table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_title(input_data: dict[str, Any]) -> str:
        """Generate a default title from input parameters."""
        maker = input_data.get("maker", "")
        model = input_data.get("model", "")
        ym = input_data.get("registration_year_month", "")
        return f"{maker} {model} {ym} シミュレーション"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        user_id: str,
        input_data: dict[str, Any],
        result: dict[str, Any],
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new simulation record.

        Args:
            user_id: The ID of the user creating the simulation.
            input_data: The input parameters for the simulation.
            result: The computed simulation result.
            title: Optional custom title. Auto-generated if omitted.

        Returns:
            The created simulation record.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            record = {
                "user_id": user_id,
                "title": title or self._build_title(input_data),
                "input_data": input_data,
                "result": result,
                "status": "completed",
                "created_at": now,
                "updated_at": now,
            }

            response = (
                self._client.table(TABLE)
                .insert(record)
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]

            raise RuntimeError("Simulation insert returned no data")

        except Exception:
            logger.exception("simulation_create_failed", user_id=user_id)
            raise

    async def list_by_user(
        self,
        user_id: str,
        *,
        page: int = 1,
        per_page: int = 20,
        sort: str = "created_at",
        order: str = "desc",
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List simulations for a user with pagination, sorting, and date filters.

        Returns:
            A tuple of (list of simulation dicts, total count).
        """
        try:
            query = (
                self._client.table(TABLE)
                .select("*", count="exact")
                .eq("user_id", user_id)
            )

            if date_from is not None:
                query = query.gte("created_at", date_from.isoformat())
            if date_to is not None:
                query = query.lte("created_at", date_to.isoformat())

            desc = order.lower() != "asc"
            query = query.order(sort, desc=desc)

            offset = (page - 1) * per_page
            query = query.range(offset, offset + per_page - 1)

            response = query.execute()

            data: list[dict[str, Any]] = response.data or []
            total_count: int = response.count or 0

            return data, total_count

        except Exception:
            logger.exception(
                "simulation_list_by_user_failed", user_id=user_id
            )
            raise

    async def get_by_id(
        self, simulation_id: str
    ) -> dict[str, Any] | None:
        """Fetch a single simulation by ID.

        Returns:
            Simulation dict or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", simulation_id)
                .maybe_single()
                .execute()
            )
            return response.data
        except Exception:
            logger.exception(
                "simulation_get_by_id_failed",
                simulation_id=simulation_id,
            )
            raise

    async def get_multiple(
        self, simulation_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch multiple simulations by their IDs.

        Returns:
            List of simulation dicts (order not guaranteed).
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .in_("id", simulation_ids)
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception(
                "simulation_get_multiple_failed",
                ids=simulation_ids,
            )
            raise

    async def delete(self, simulation_id: str, user_id: str) -> bool:
        """Delete a simulation owned by the specified user.

        Returns:
            True if a record was deleted, False if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .delete()
                .eq("id", simulation_id)
                .eq("user_id", user_id)
                .execute()
            )
            deleted = response.data or []
            return len(deleted) > 0

        except Exception:
            logger.exception(
                "simulation_delete_failed",
                simulation_id=simulation_id,
                user_id=user_id,
            )
            raise

    async def update_status(
        self, simulation_id: str, status: str
    ) -> dict[str, Any]:
        """Update the status of a simulation.

        Returns:
            The updated simulation record.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            response = (
                self._client.table(TABLE)
                .update({
                    "status": status,
                    "updated_at": now,
                })
                .eq("id", simulation_id)
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]

            raise RuntimeError(
                f"Simulation {simulation_id} not found for status update"
            )

        except Exception:
            logger.exception(
                "simulation_update_status_failed",
                simulation_id=simulation_id,
                status=status,
            )
            raise
