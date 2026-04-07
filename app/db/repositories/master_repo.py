"""Repository for master data access (makers, models, body types, etc.)."""

from __future__ import annotations

from typing import Any, Optional

import structlog
from supabase import Client

logger = structlog.get_logger()


class MasterRepository:
    """Data access layer for master reference tables."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Makers
    # ------------------------------------------------------------------

    async def list_makers(self) -> list[dict[str, Any]]:
        """List all vehicle makers.

        Returns:
            List of maker dicts.
        """
        try:
            response = (
                self._client.table("manufacturers")
                .select("*")
                .order("name")
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception("list_makers_failed")
            raise

    async def create_maker(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new maker record.

        Args:
            data: Dict with maker fields (e.g. name, name_en).

        Returns:
            The created maker record.
        """
        try:
            response = (
                self._client.table("manufacturers")
                .insert(data)
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
            raise RuntimeError("Maker insert returned no data")
        except Exception:
            logger.exception("create_maker_failed", data=data)
            raise

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    async def list_models_by_maker(
        self, maker_id: str
    ) -> list[dict[str, Any]]:
        """List all vehicle models belonging to a maker.

        Args:
            maker_id: The UUID of the maker.

        Returns:
            List of model dicts.
        """
        try:
            response = (
                self._client.table("vehicle_models")
                .select("*")
                .eq("manufacturer_id", maker_id)
                .order("name")
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception(
                "list_models_by_maker_failed", maker_id=maker_id
            )
            raise

    async def create_model(
        self, maker_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new model record under a maker.

        Args:
            maker_id: The UUID of the parent maker.
            data: Dict with model fields (e.g. name, name_en).

        Returns:
            The created model record.
        """
        try:
            record = {**data, "manufacturer_id": maker_id}
            response = (
                self._client.table("vehicle_models")
                .insert(record)
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
            raise RuntimeError("Model insert returned no data")
        except Exception:
            logger.exception(
                "create_model_failed", maker_id=maker_id, data=data
            )
            raise

    # ------------------------------------------------------------------
    # Body Types
    # ------------------------------------------------------------------

    async def list_body_types(self) -> list[dict[str, Any]]:
        """List all body types.

        Returns:
            List of body type dicts.
        """
        try:
            response = (
                self._client.table("body_types")
                .select("*")
                .order("name")
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception("list_body_types_failed")
            raise

    async def create_body_type(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new body type record.

        Args:
            data: Dict with body type fields (e.g. name).

        Returns:
            The created body type record.
        """
        try:
            response = (
                self._client.table("body_types")
                .insert(data)
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
            raise RuntimeError("Body type insert returned no data")
        except Exception:
            logger.exception("create_body_type_failed", data=data)
            raise

    async def update_body_type(
        self, id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an existing body type record.

        Args:
            id: The UUID of the body type to update.
            data: Dict with fields to update.

        Returns:
            The updated body type record.
        """
        try:
            response = (
                self._client.table("body_types")
                .update(data)
                .eq("id", id)
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
            raise RuntimeError(f"Body type {id} not found for update")
        except Exception:
            logger.exception(
                "update_body_type_failed", id=id, data=data
            )
            raise

    async def soft_delete_body_type(self, id: str) -> dict[str, Any]:
        """Soft-delete a body type by setting is_active=False.

        Args:
            id: The UUID of the body type to deactivate.

        Returns:
            The updated body type record.
        """
        try:
            response = (
                self._client.table("body_types")
                .update({"is_active": False})
                .eq("id", id)
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
            raise RuntimeError(f"Body type {id} not found for deletion")
        except Exception:
            logger.exception("soft_delete_body_type_failed", id=id)
            raise

    # ------------------------------------------------------------------
    # Vehicle Categories
    # ------------------------------------------------------------------

    async def list_vehicle_categories(self) -> list[dict[str, Any]]:
        """List all vehicle categories.

        Returns:
            List of vehicle category dicts.
        """
        try:
            response = (
                self._client.table("vehicle_categories")
                .select("*")
                .order("name")
                .execute()
            )
            return response.data or []
        except Exception:
            logger.exception("list_vehicle_categories_failed")
            raise

    # ------------------------------------------------------------------
    # Depreciation Curves
    # ------------------------------------------------------------------

    async def list_depreciation_curves(
        self, category_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List depreciation curves, optionally filtered by category.

        Args:
            category_id: If provided, filter curves by this category UUID.

        Returns:
            List of depreciation curve dicts.
        """
        try:
            query = (
                self._client.table("depreciation_curves")
                .select("*")
            )

            if category_id is not None:
                query = query.eq("category_id", category_id)

            query = query.order("year")

            response = query.execute()
            return response.data or []
        except Exception:
            logger.exception(
                "list_depreciation_curves_failed",
                category_id=category_id,
            )
            raise

    async def upsert_depreciation_curve(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or update a depreciation curve point.

        Uses upsert on (category_id, year) to allow idempotent updates.

        Args:
            data: Dict with curve fields (category_id, year, rate, etc.).

        Returns:
            The created or updated curve record.
        """
        try:
            response = (
                self._client.table("depreciation_curves")
                .upsert(data, on_conflict="category_id,year")
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
            raise RuntimeError("Depreciation curve upsert returned no data")
        except Exception:
            logger.exception(
                "upsert_depreciation_curve_failed", data=data
            )
            raise
