"""Repository for pricing master parameters."""

from __future__ import annotations

from typing import Any, Optional

import structlog
from supabase import Client

logger = structlog.get_logger()

TABLE = "pricing_masters"
HISTORY_TABLE = "pricing_parameter_history"


class PricingMasterRepository:
    """Data access layer for the pricing_masters table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_all(
        self, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """List all pricing masters.

        Args:
            active_only: If True, return only active records.

        Returns:
            List of pricing master dicts.
        """
        try:
            query = self._client.table(TABLE).select("*")

            if active_only:
                query = query.eq("is_active", True)

            response = query.order("created_at", desc=True).execute()
            return response.data or []

        except Exception:
            logger.exception("pricing_master_list_all_failed")
            raise

    async def get_by_id(
        self, master_id: str
    ) -> dict[str, Any] | None:
        """Fetch a single pricing master by ID.

        Args:
            master_id: The pricing master UUID.

        Returns:
            Pricing master dict or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", master_id)
                .maybe_single()
                .execute()
            )
            return response.data

        except Exception:
            logger.exception(
                "pricing_master_get_by_id_failed",
                master_id=master_id,
            )
            raise

    async def get_by_fund_id(
        self, fund_id: str
    ) -> dict[str, Any] | None:
        """Get the active pricing master for a specific fund.

        Args:
            fund_id: The fund UUID.

        Returns:
            Pricing master dict or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("fund_id", fund_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            data = response.data or []
            return data[0] if data else None

        except Exception:
            logger.exception(
                "pricing_master_get_by_fund_id_failed",
                fund_id=fund_id,
            )
            raise

    async def get_default(self) -> dict[str, Any] | None:
        """Get the default (no fund) pricing master.

        Returns:
            Default pricing master dict or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .is_("fund_id", "null")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            data = response.data or []
            return data[0] if data else None

        except Exception:
            logger.exception("pricing_master_get_default_failed")
            raise

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new pricing master.

        Args:
            data: Column values for the new record.

        Returns:
            The created pricing master record.
        """
        try:
            response = (
                self._client.table(TABLE)
                .insert(data)
                .execute()
            )

            result = response.data
            if result and len(result) > 0:
                return result[0]

            raise RuntimeError("Pricing master insert returned no data")

        except Exception:
            logger.exception("pricing_master_create_failed")
            raise

    async def update(
        self,
        master_id: str,
        data: dict[str, Any],
        *,
        changed_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update a pricing master and record parameter change history.

        For every changed field the previous and new values are written to
        the ``pricing_parameter_history`` table so that auditors can trace
        pricing adjustments over time.

        Args:
            master_id: The pricing master UUID.
            data: Column values to update.
            changed_by: Optional user UUID who made the change.

        Returns:
            The updated pricing master record.
        """
        try:
            # Snapshot current values so we can diff for history
            current = await self.get_by_id(master_id)

            if current:
                for key, new_value in data.items():
                    old_value = current.get(key)
                    if old_value != new_value and key not in ("updated_at",):
                        history_record: dict[str, Any] = {
                            "pricing_master_id": master_id,
                            "parameter_key": key,
                            "old_value": {"value": old_value},
                            "new_value": {"value": new_value},
                        }
                        if changed_by:
                            history_record["changed_by"] = changed_by

                        self._client.table(HISTORY_TABLE).insert(
                            history_record
                        ).execute()

            response = (
                self._client.table(TABLE)
                .update(data)
                .eq("id", master_id)
                .execute()
            )

            result = response.data
            if result and len(result) > 0:
                return result[0]

            raise RuntimeError(
                f"Pricing master {master_id} not found for update"
            )

        except Exception:
            logger.exception(
                "pricing_master_update_failed",
                master_id=master_id,
            )
            raise

    async def delete(self, master_id: str) -> bool:
        """Soft-delete a pricing master by setting is_active to False.

        Args:
            master_id: The pricing master UUID.

        Returns:
            True if a record was updated, False if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .update({"is_active": False})
                .eq("id", master_id)
                .execute()
            )
            deleted = response.data or []
            return len(deleted) > 0

        except Exception:
            logger.exception(
                "pricing_master_delete_failed",
                master_id=master_id,
            )
            raise

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def get_history(
        self, master_id: str
    ) -> list[dict[str, Any]]:
        """Get parameter change history for a pricing master.

        Args:
            master_id: The pricing master UUID.

        Returns:
            List of history records ordered by most recent first.
        """
        try:
            response = (
                self._client.table(HISTORY_TABLE)
                .select("*")
                .eq("pricing_master_id", master_id)
                .order("changed_at", desc=True)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "pricing_master_get_history_failed",
                master_id=master_id,
            )
            raise
