"""Repository for financial analysis results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from supabase import Client

logger = structlog.get_logger()

TABLE = "financial_analyses"
ALERTS_TABLE = "financial_analysis_alerts"


class FinancialAnalysisRepository:
    """Data access layer for financial analysis tables."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Analyses CRUD
    # ------------------------------------------------------------------

    async def save_analysis(
        self,
        company_name: str,
        input_data: dict[str, Any],
        result: dict[str, Any],
        user_id: Optional[str] = None,
        simulation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save a financial analysis result.

        Args:
            company_name: Name of the analysed company.
            input_data: Raw input parameters used for the analysis.
            result: Computed analysis result (scores, ratios, etc.).
            user_id: Optional user who triggered the analysis.
            simulation_id: Optional linked simulation ID.

        Returns:
            The created analysis record.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            record: dict[str, Any] = {
                "company_name": company_name,
                "input_data": input_data,
                "result": result,
                "overall_score": result.get("overall_score"),
                "created_at": now,
                "updated_at": now,
            }

            if user_id is not None:
                record["user_id"] = user_id
            if simulation_id is not None:
                record["simulation_id"] = simulation_id

            response = (
                self._client.table(TABLE)
                .insert(record)
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]

            raise RuntimeError("Financial analysis insert returned no data")

        except Exception:
            logger.exception(
                "financial_analysis_save_failed",
                company_name=company_name,
            )
            raise

    async def get_by_company(
        self,
        company_name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get analysis history for a company.

        Args:
            company_name: Company name to search for.
            limit: Maximum number of records to return.

        Returns:
            List of analysis dicts ordered by most recent first.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("company_name", company_name)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "financial_analysis_get_by_company_failed",
                company_name=company_name,
            )
            raise

    async def get_by_id(
        self, analysis_id: str
    ) -> dict[str, Any] | None:
        """Get a specific analysis.

        Returns:
            Analysis dict or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", analysis_id)
                .maybe_single()
                .execute()
            )
            return response.data

        except Exception:
            logger.exception(
                "financial_analysis_get_by_id_failed",
                analysis_id=analysis_id,
            )
            raise

    async def get_latest_by_company(
        self, company_name: str
    ) -> dict[str, Any] | None:
        """Get the most recent analysis for a company.

        Returns:
            Analysis dict or None if no analysis exists.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("company_name", company_name)
                .order("created_at", desc=True)
                .limit(1)
                .maybe_single()
                .execute()
            )
            return response.data

        except Exception:
            logger.exception(
                "financial_analysis_get_latest_failed",
                company_name=company_name,
            )
            raise

    async def list_all(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        score_filter: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List all analyses with optional filtering.

        Args:
            page: 1-based page number.
            per_page: Number of records per page.
            score_filter: Optional filter such as ``"high"`` (>= 70),
                ``"medium"`` (40-69), or ``"low"`` (< 40).

        Returns:
            A tuple of (list of analysis dicts, total count).
        """
        try:
            query = (
                self._client.table(TABLE)
                .select("*", count="exact")
            )

            if score_filter == "high":
                query = query.gte("overall_score", 70)
            elif score_filter == "medium":
                query = query.gte("overall_score", 40).lt("overall_score", 70)
            elif score_filter == "low":
                query = query.lt("overall_score", 40)

            query = query.order("created_at", desc=True)

            offset = (page - 1) * per_page
            query = query.range(offset, offset + per_page - 1)

            response = query.execute()

            data: list[dict[str, Any]] = response.data or []
            total_count: int = response.count or 0

            return data, total_count

        except Exception:
            logger.exception("financial_analysis_list_all_failed")
            raise

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def save_alerts(
        self,
        analysis_id: str,
        recommendations: list[str],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        """Save analysis alerts (recommendations + warnings).

        Args:
            analysis_id: The parent analysis ID.
            recommendations: List of recommendation messages.
            warnings: List of warning messages.

        Returns:
            List of created alert records.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            rows: list[dict[str, Any]] = []

            for text in recommendations:
                rows.append({
                    "analysis_id": analysis_id,
                    "alert_type": "recommendation",
                    "message": text,
                    "created_at": now,
                })

            for text in warnings:
                rows.append({
                    "analysis_id": analysis_id,
                    "alert_type": "warning",
                    "message": text,
                    "created_at": now,
                })

            if not rows:
                return []

            response = (
                self._client.table(ALERTS_TABLE)
                .insert(rows)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "financial_analysis_save_alerts_failed",
                analysis_id=analysis_id,
            )
            raise

    async def get_alerts(
        self, analysis_id: str
    ) -> list[dict[str, Any]]:
        """Get alerts for an analysis.

        Returns:
            List of alert dicts.
        """
        try:
            response = (
                self._client.table(ALERTS_TABLE)
                .select("*")
                .eq("analysis_id", analysis_id)
                .order("created_at", desc=False)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "financial_analysis_get_alerts_failed",
                analysis_id=analysis_id,
            )
            raise

    # ------------------------------------------------------------------
    # Trend
    # ------------------------------------------------------------------

    async def get_company_trend(
        self, company_name: str
    ) -> list[dict[str, Any]]:
        """Get score trend over time for a company.

        Returns a chronologically ordered list of records containing
        ``id``, ``overall_score``, and ``created_at``.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("id, overall_score, created_at")
                .eq("company_name", company_name)
                .order("created_at", desc=False)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "financial_analysis_get_trend_failed",
                company_name=company_name,
            )
            raise
