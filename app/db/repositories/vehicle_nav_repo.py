"""Repository for vehicle NAV (Net Asset Value) history data access."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from supabase import Client

logger = structlog.get_logger()

TABLE = "vehicle_nav_history"
SAB_TABLE = "secured_asset_blocks"


class VehicleNavRepository:
    """Data access layer for the vehicle_nav_history table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def record_monthly_nav(
        self,
        vehicle_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert a monthly NAV snapshot for a single vehicle.

        Args:
            vehicle_id: The UUID of the vehicle.
            data: NAV data including recording_date, acquisition_price,
                  book_value, market_value, depreciation_cumulative,
                  lease_income_cumulative, nav, ltv_ratio, etc.

        Returns:
            The inserted record dict.
        """
        try:
            record = {
                "vehicle_id": vehicle_id,
                **data,
            }
            response = (
                self._client.table(TABLE)
                .upsert(record, on_conflict="vehicle_id,recording_date")
                .execute()
            )
            result = response.data[0] if response.data else {}
            logger.info(
                "vehicle_nav_recorded",
                vehicle_id=vehicle_id,
                recording_date=data.get("recording_date"),
            )
            return result

        except Exception:
            logger.exception(
                "vehicle_nav_record_failed",
                vehicle_id=vehicle_id,
            )
            raise

    async def get_nav_history(
        self,
        vehicle_id: str,
        limit: int = 120,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get full NAV history for a vehicle, ordered by recording_date desc.

        Args:
            vehicle_id: The UUID of the vehicle.
            limit: Maximum number of records to return.
            offset: Number of records to skip.

        Returns:
            List of NAV history dicts.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("vehicle_id", vehicle_id)
                .order("recording_date", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "vehicle_nav_history_fetch_failed",
                vehicle_id=vehicle_id,
            )
            raise

    async def get_latest_nav(
        self,
        vehicle_id: str,
    ) -> dict[str, Any] | None:
        """Get the most recent NAV snapshot for a vehicle.

        Args:
            vehicle_id: The UUID of the vehicle.

        Returns:
            Latest NAV dict or None if no history exists.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("vehicle_id", vehicle_id)
                .order("recording_date", desc=True)
                .limit(1)
                .maybe_single()
                .execute()
            )
            return response.data

        except Exception:
            logger.exception(
                "vehicle_nav_latest_fetch_failed",
                vehicle_id=vehicle_id,
            )
            raise

    async def batch_record_monthly(
        self,
        fund_id: str,
        recording_month: date,
    ) -> dict[str, int]:
        """Record NAV for all vehicles in a fund for a given month.

        Fetches all SABs (secured asset blocks) in the fund, computes
        NAV from their current state, and inserts/upserts snapshots.

        Args:
            fund_id: The UUID of the fund.
            recording_month: The month-end date for recording.

        Returns:
            Stats dict with keys: recorded, skipped, errors.
        """
        stats = {"recorded": 0, "skipped": 0, "errors": 0}

        try:
            # Fetch all active SABs in the fund with linked vehicles
            sab_response = (
                self._client.table(SAB_TABLE)
                .select("*")
                .eq("fund_id", fund_id)
                .in_("status", ["held", "leased"])
                .execute()
            )
            sabs = sab_response.data or []

            if not sabs:
                logger.info(
                    "batch_record_monthly_no_sabs",
                    fund_id=fund_id,
                    recording_month=str(recording_month),
                )
                return stats

            # Fetch cumulative lease payments for the fund up to recording_month
            lease_payments = await self._get_fund_lease_income(
                fund_id, recording_month
            )

            for sab in sabs:
                vehicle_id = sab.get("vehicle_id")
                if not vehicle_id:
                    stats["skipped"] += 1
                    continue

                try:
                    acquisition_price = sab["acquisition_price"]
                    market_value = sab.get("adjusted_valuation") or sab.get(
                        "b2b_wholesale_valuation"
                    )
                    ltv_ratio = sab.get("ltv_ratio")

                    # Calculate depreciation as difference from acquisition
                    book_value = market_value if market_value else acquisition_price
                    depreciation = max(0, acquisition_price - book_value)

                    # Lease income for this vehicle's SAB
                    lease_income = lease_payments.get(sab["id"], 0)

                    # NAV = book_value + cumulative lease income
                    nav = book_value + lease_income

                    record = {
                        "vehicle_id": vehicle_id,
                        "fund_id": fund_id,
                        "sab_id": sab["id"],
                        "recording_date": str(recording_month),
                        "acquisition_price": acquisition_price,
                        "book_value": book_value,
                        "market_value": market_value,
                        "depreciation_cumulative": depreciation,
                        "lease_income_cumulative": lease_income,
                        "nav": nav,
                        "ltv_ratio": ltv_ratio,
                    }

                    self._client.table(TABLE).upsert(
                        record, on_conflict="vehicle_id,recording_date"
                    ).execute()

                    stats["recorded"] += 1

                except Exception:
                    logger.exception(
                        "batch_record_vehicle_failed",
                        vehicle_id=vehicle_id,
                        sab_id=sab.get("id"),
                    )
                    stats["errors"] += 1

            logger.info(
                "batch_record_monthly_complete",
                fund_id=fund_id,
                recording_month=str(recording_month),
                **stats,
            )
            return stats

        except Exception:
            logger.exception(
                "batch_record_monthly_failed",
                fund_id=fund_id,
            )
            raise

    async def get_fund_nav_summary(
        self,
        fund_id: str,
        recording_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """Aggregate NAV statistics for all vehicles in a fund.

        If recording_date is provided, returns stats for that specific date.
        Otherwise returns stats for the most recent recording date.

        Args:
            fund_id: The UUID of the fund.
            recording_date: Optional specific date to query.

        Returns:
            Dict with total_nav, total_book_value, total_market_value,
            total_depreciation, total_lease_income, vehicle_count,
            avg_ltv_ratio, and recording_date.
        """
        try:
            query = (
                self._client.table(TABLE)
                .select("*")
                .eq("fund_id", fund_id)
            )

            if recording_date:
                query = query.eq("recording_date", str(recording_date))
            else:
                # Find the latest recording date for this fund
                latest = (
                    self._client.table(TABLE)
                    .select("recording_date")
                    .eq("fund_id", fund_id)
                    .order("recording_date", desc=True)
                    .limit(1)
                    .maybe_single()
                    .execute()
                )
                if not latest.data:
                    return {
                        "fund_id": fund_id,
                        "recording_date": None,
                        "vehicle_count": 0,
                        "total_nav": 0,
                        "total_book_value": 0,
                        "total_market_value": 0,
                        "total_acquisition_price": 0,
                        "total_depreciation": 0,
                        "total_lease_income": 0,
                        "avg_ltv_ratio": None,
                    }
                query = query.eq(
                    "recording_date", latest.data["recording_date"]
                )

            response = query.execute()
            rows = response.data or []

            if not rows:
                return {
                    "fund_id": fund_id,
                    "recording_date": str(recording_date) if recording_date else None,
                    "vehicle_count": 0,
                    "total_nav": 0,
                    "total_book_value": 0,
                    "total_market_value": 0,
                    "total_acquisition_price": 0,
                    "total_depreciation": 0,
                    "total_lease_income": 0,
                    "avg_ltv_ratio": None,
                }

            total_nav = sum(r["nav"] for r in rows)
            total_book = sum(r["book_value"] for r in rows)
            total_market = sum(
                r["market_value"] for r in rows if r.get("market_value")
            )
            total_acq = sum(r["acquisition_price"] for r in rows)
            total_dep = sum(r["depreciation_cumulative"] for r in rows)
            total_lease = sum(r["lease_income_cumulative"] for r in rows)

            ltv_values = [
                float(r["ltv_ratio"])
                for r in rows
                if r.get("ltv_ratio") is not None
            ]
            avg_ltv = (
                round(sum(ltv_values) / len(ltv_values), 4)
                if ltv_values
                else None
            )

            return {
                "fund_id": fund_id,
                "recording_date": rows[0]["recording_date"],
                "vehicle_count": len(rows),
                "total_nav": total_nav,
                "total_book_value": total_book,
                "total_market_value": total_market,
                "total_acquisition_price": total_acq,
                "total_depreciation": total_dep,
                "total_lease_income": total_lease,
                "avg_ltv_ratio": avg_ltv,
            }

        except Exception:
            logger.exception(
                "fund_nav_summary_failed",
                fund_id=fund_id,
            )
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_fund_lease_income(
        self,
        fund_id: str,
        up_to_date: date,
    ) -> dict[str, int]:
        """Fetch cumulative paid lease income per SAB for a fund.

        Args:
            fund_id: The UUID of the fund.
            up_to_date: Sum payments up to this date.

        Returns:
            Dict mapping sab_id -> cumulative lease income (JPY).
        """
        try:
            # Get lease contracts for the fund
            contracts_response = (
                self._client.table("lease_contracts")
                .select("id")
                .eq("fund_id", fund_id)
                .execute()
            )
            contract_ids = [
                c["id"] for c in (contracts_response.data or [])
            ]

            if not contract_ids:
                return {}

            # Get paid payments up to the recording date
            payments_response = (
                self._client.table("lease_payments")
                .select("lease_contract_id, actual_amount")
                .in_("lease_contract_id", contract_ids)
                .eq("status", "paid")
                .lte("actual_payment_date", str(up_to_date))
                .execute()
            )

            # Map contract -> SAB for income attribution
            sab_response = (
                self._client.table(SAB_TABLE)
                .select("id, lease_contract_id")
                .eq("fund_id", fund_id)
                .not_.is_("lease_contract_id", "null")
                .execute()
            )
            contract_to_sab: dict[str, str] = {
                s["lease_contract_id"]: s["id"]
                for s in (sab_response.data or [])
            }

            income_by_sab: dict[str, int] = {}
            for payment in payments_response.data or []:
                contract_id = payment["lease_contract_id"]
                sab_id = contract_to_sab.get(contract_id)
                if sab_id:
                    amount = payment.get("actual_amount") or 0
                    income_by_sab[sab_id] = income_by_sab.get(sab_id, 0) + amount

            return income_by_sab

        except Exception:
            logger.exception(
                "fund_lease_income_fetch_failed",
                fund_id=fund_id,
            )
            raise
