"""LTV (Loan-to-Value) valuation engine.

Implements the covenant-level LTV calculation described in
``docs/ltv_valuation_spec.md`` §4.3 (LTV-maintenance verification).

Two distinct LTV concepts coexist in the spec:

* **Origination LTV** (fixed 0.60): governs the *maximum purchase price*
  relative to B2B wholesale floor at acquisition time.  This lives in
  ``app/core/acquisition_price.py`` / ``app/core/integrated_pricing.py``.

* **Covenant LTV** (this module): ongoing ratio of ``outstanding lease
  principal`` to ``current book value``.  Used for monthly covenant
  monitoring, fund-level reporting and stress testing.

The defaults in this module (warning 0.75, breach 0.85) are the covenant
thresholds — conservative ceilings well below 100% that preserve
collateral headroom while letting the origination 60% LTV amortise.

Data sources
------------
* ``vehicle_nav_history``     — latest ``book_value`` (or ``market_value``)
* ``lease_contracts`` + ``lease_payments`` — remaining unpaid principal
* ``secured_asset_blocks``    — ``fund_id`` linkage for each vehicle

All monetary values are in JPY (bigint).  Ratios are ``float`` in
``[0.0, +inf)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Covenant thresholds (defaults)
# ---------------------------------------------------------------------------

DEFAULT_WARNING_THRESHOLD: float = 0.75  # LTV ≥ 75% → yellow alert
DEFAULT_BREACH_THRESHOLD: float = 0.85   # LTV ≥ 85% → covenant breach

STATUS_HEALTHY = "HEALTHY"
STATUS_WARNING = "WARNING"
STATUS_BREACH = "BREACH"


# ---------------------------------------------------------------------------
# Lightweight internal dataclasses (models/ltv.py hosts the Pydantic ones)
# ---------------------------------------------------------------------------


@dataclass
class _VehicleValuation:
    vehicle_id: str
    fund_id: Optional[str]
    book_value: int
    outstanding_principal: int


# ---------------------------------------------------------------------------
# LTVValuator
# ---------------------------------------------------------------------------


class LTVValuator:
    """Computes per-vehicle and per-fund LTV ratios and runs stress tests.

    Parameters
    ----------
    client :
        A Supabase-like client (or dict-backed fake in tests).  Must
        support ``client.table(name).select(...).eq(...).execute()``.
    warning_threshold :
        LTV ratio at which a warning is raised.  Default 0.75.
    breach_threshold :
        LTV ratio at which a covenant is considered breached.  Default 0.85.
    """

    # Table names
    TABLE_NAV = "vehicle_nav_history"
    TABLE_SAB = "secured_asset_blocks"
    TABLE_LEASES = "lease_contracts"
    TABLE_PAYMENTS = "lease_payments"

    def __init__(
        self,
        client: Any,
        warning_threshold: float = DEFAULT_WARNING_THRESHOLD,
        breach_threshold: float = DEFAULT_BREACH_THRESHOLD,
    ) -> None:
        if not (0.0 < warning_threshold < breach_threshold <= 2.0):
            raise ValueError(
                "warning_threshold must be > 0 and < breach_threshold "
                f"(got {warning_threshold}, {breach_threshold})"
            )
        self._client = client
        self.warning_threshold = warning_threshold
        self.breach_threshold = breach_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_vehicle_ltv(
        self,
        vehicle_id: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        """Calculate LTV for a single vehicle as of ``as_of_date``.

        Returns a dict matching ``LTVVehicleResult``'s shape (ready to
        feed into the Pydantic model).
        """
        val = self._load_vehicle_valuation(vehicle_id, as_of_date)
        return self._build_vehicle_result(val, as_of_date)

    def calculate_fund_ltv(
        self,
        fund_id: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        """Aggregate LTV across all vehicles belonging to a fund.

        Returns a dict matching ``LTVFundResult``'s shape.
        """
        vehicle_valuations = self._load_fund_vehicle_valuations(fund_id, as_of_date)

        vehicle_results: list[dict[str, Any]] = [
            self._build_vehicle_result(v, as_of_date) for v in vehicle_valuations
        ]

        book_total = sum(v.book_value for v in vehicle_valuations)
        principal_total = sum(v.outstanding_principal for v in vehicle_valuations)
        ltv_ratio = self._safe_ratio(principal_total, book_total)

        warning_count = sum(1 for r in vehicle_results if r["warning_flag"])
        breach_count = sum(1 for r in vehicle_results if r["breach_flag"])

        status, warning_flag, breach_flag = self._classify(ltv_ratio)

        result = {
            "fund_id": fund_id,
            "as_of_date": as_of_date,
            "vehicles_count": len(vehicle_valuations),
            "book_value_total": book_total,
            "outstanding_principal_total": principal_total,
            "ltv_ratio": round(ltv_ratio, 6),
            "collateral_headroom": book_total - principal_total,
            "warning_count": warning_count,
            "breach_count": breach_count,
            "warning_flag": warning_flag,
            "breach_flag": breach_flag,
            "status": status,
            "warning_threshold": self.warning_threshold,
            "breach_threshold": self.breach_threshold,
            "vehicles": vehicle_results,
        }
        return result

    def stress_test(
        self,
        fund_id: str,
        shock_percentages: Iterable[float],
        as_of_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """Apply a list of book-value shocks and return stressed LTVs.

        Each shock ``s`` (in ``[0.0, 1.0)``) reduces every vehicle's
        book value to ``book_value × (1 - s)``.  Outstanding principal
        is unchanged (principal is not market-sensitive).

        Returns a list of dicts matching ``StressTestResult``.
        """
        if as_of_date is None:
            as_of_date = date.today()

        vehicle_valuations = self._load_fund_vehicle_valuations(fund_id, as_of_date)
        baseline_book = sum(v.book_value for v in vehicle_valuations)
        baseline_principal = sum(v.outstanding_principal for v in vehicle_valuations)
        baseline_ltv = self._safe_ratio(baseline_principal, baseline_book)

        results: list[dict[str, Any]] = []

        for shock in shock_percentages:
            if not 0.0 <= shock < 1.0:
                raise ValueError(
                    f"shock_pct must be in [0.0, 1.0) (got {shock})"
                )

            scale = 1.0 - shock
            # Stressed per-vehicle LTVs (floor at 0; principal unchanged)
            vehicles_in_warning = 0
            vehicles_in_breach = 0
            stressed_book_total = 0

            for v in vehicle_valuations:
                stressed_bv = int(round(v.book_value * scale))
                stressed_book_total += stressed_bv
                per_vehicle_ltv = self._safe_ratio(
                    v.outstanding_principal, stressed_bv
                )
                status, warn, breach = self._classify(per_vehicle_ltv)
                if warn:
                    vehicles_in_warning += 1
                if breach:
                    vehicles_in_breach += 1

            stressed_fund_ltv = self._safe_ratio(
                baseline_principal, stressed_book_total
            )
            status, _warn, breach_flag = self._classify(stressed_fund_ltv)

            results.append({
                "fund_id": fund_id,
                "as_of_date": as_of_date,
                "shock_pct": shock,
                "label": self._default_label(shock),
                "stressed_book_value_total": stressed_book_total,
                "outstanding_principal_total": baseline_principal,
                "fund_ltv": round(stressed_fund_ltv, 6),
                "fund_ltv_baseline": round(baseline_ltv, 6),
                "vehicles_in_breach": vehicles_in_breach,
                "vehicles_in_warning": vehicles_in_warning,
                "breach_flag": breach_flag,
                "status": status,
            })

        return results

    # ------------------------------------------------------------------
    # Internal: classification
    # ------------------------------------------------------------------

    def _classify(self, ltv_ratio: float) -> tuple[str, bool, bool]:
        """Return (status, warning_flag, breach_flag) for an LTV ratio."""
        if ltv_ratio >= self.breach_threshold:
            return STATUS_BREACH, True, True
        if ltv_ratio >= self.warning_threshold:
            return STATUS_WARNING, True, False
        return STATUS_HEALTHY, False, False

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        """``numerator / denominator`` with zero-safe handling.

        * If ``denominator == 0`` and ``numerator > 0`` → ``inf``-like
          behaviour is useless for thresholds; we return a large sentinel
          (``1e12``) that trivially trips the breach threshold.
        * If both zero → ``0.0``.
        """
        if denominator <= 0:
            return 0.0 if numerator <= 0 else 1e12
        return float(numerator) / float(denominator)

    @staticmethod
    def _default_label(shock: float) -> str:
        pct = int(round(shock * 100))
        if pct == 0:
            return "base"
        if pct <= 10:
            return f"mild_-{pct}%"
        if pct <= 20:
            return f"moderate_-{pct}%"
        return f"severe_-{pct}%"

    # ------------------------------------------------------------------
    # Internal: data loading
    # ------------------------------------------------------------------

    def _build_vehicle_result(
        self,
        val: _VehicleValuation,
        as_of_date: date,
    ) -> dict[str, Any]:
        ltv = self._safe_ratio(val.outstanding_principal, val.book_value)
        status, warn, breach = self._classify(ltv)
        return {
            "vehicle_id": val.vehicle_id,
            "fund_id": val.fund_id,
            "as_of_date": as_of_date,
            "book_value": val.book_value,
            "outstanding_principal": val.outstanding_principal,
            "ltv_ratio": round(ltv, 6),
            "collateral_headroom": val.book_value - val.outstanding_principal,
            "warning_flag": warn,
            "breach_flag": breach,
            "status": status,
        }

    def _load_vehicle_valuation(
        self,
        vehicle_id: str,
        as_of_date: date,
    ) -> _VehicleValuation:
        """Load latest book value and outstanding principal for one vehicle."""
        book_value, fund_id = self._fetch_latest_book_value(vehicle_id, as_of_date)
        lease_ids = self._fetch_vehicle_lease_ids(vehicle_id)
        principal = sum(
            self._fetch_outstanding_principal(lid, as_of_date) for lid in lease_ids
        )
        return _VehicleValuation(
            vehicle_id=vehicle_id,
            fund_id=fund_id,
            book_value=book_value,
            outstanding_principal=principal,
        )

    def _load_fund_vehicle_valuations(
        self,
        fund_id: str,
        as_of_date: date,
    ) -> list[_VehicleValuation]:
        """Load per-vehicle valuations for every vehicle in a fund."""
        # 1) Find all SABs (i.e. vehicles) under the fund
        sab_resp = (
            self._client.table(self.TABLE_SAB)
            .select("id, vehicle_id, fund_id, lease_contract_id")
            .eq("fund_id", fund_id)
            .execute()
        )
        sabs = sab_resp.data or []

        valuations: list[_VehicleValuation] = []
        for sab in sabs:
            vehicle_id = sab.get("vehicle_id")
            if not vehicle_id:
                continue

            book_value, _ = self._fetch_latest_book_value(vehicle_id, as_of_date)

            # Outstanding principal: prefer the SAB's linked lease; otherwise
            # scan all leases for this vehicle (edge case).
            lease_ids: list[str] = []
            if sab.get("lease_contract_id"):
                lease_ids.append(sab["lease_contract_id"])
            else:
                lease_ids = self._fetch_vehicle_lease_ids(vehicle_id)

            principal = sum(
                self._fetch_outstanding_principal(lid, as_of_date)
                for lid in lease_ids
            )

            valuations.append(
                _VehicleValuation(
                    vehicle_id=vehicle_id,
                    fund_id=fund_id,
                    book_value=book_value,
                    outstanding_principal=principal,
                )
            )

        return valuations

    # ---- raw fetchers --------------------------------------------------

    def _fetch_latest_book_value(
        self,
        vehicle_id: str,
        as_of_date: date,
    ) -> tuple[int, Optional[str]]:
        """Return ``(book_value, fund_id)`` from the latest NAV row <= as_of_date.

        Falls back to 0 book_value and None fund_id when no history exists.
        """
        resp = (
            self._client.table(self.TABLE_NAV)
            .select("book_value, market_value, fund_id, recording_date")
            .eq("vehicle_id", vehicle_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return 0, None

        # Filter to recording_date <= as_of_date, keep latest
        filtered = [
            r for r in rows
            if _as_date(r.get("recording_date")) is not None
            and _as_date(r["recording_date"]) <= as_of_date
        ]
        if not filtered:
            return 0, None
        latest = max(filtered, key=lambda r: _as_date(r["recording_date"]))

        # Prefer book_value; fall back to market_value when book_value is missing
        bv = latest.get("book_value")
        if bv is None:
            bv = latest.get("market_value") or 0
        return int(bv or 0), latest.get("fund_id")

    def _fetch_vehicle_lease_ids(self, vehicle_id: str) -> list[str]:
        """Return lease_contract_ids linked to this vehicle via SAB."""
        resp = (
            self._client.table(self.TABLE_SAB)
            .select("lease_contract_id")
            .eq("vehicle_id", vehicle_id)
            .execute()
        )
        rows = resp.data or []
        return [r["lease_contract_id"] for r in rows if r.get("lease_contract_id")]

    def _fetch_outstanding_principal(
        self,
        lease_contract_id: str,
        as_of_date: date,
    ) -> int:
        """Outstanding = total scheduled principal − total paid, as of date.

        Scheduled and paid amounts come from the ``lease_payments`` table.
        """
        resp = (
            self._client.table(self.TABLE_PAYMENTS)
            .select("scheduled_amount, actual_amount, status, scheduled_date")
            .eq("lease_contract_id", lease_contract_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            # Fall back to contract's total undiscounted principal
            return self._fetch_contract_total_principal(lease_contract_id)

        total_scheduled = sum(int(r.get("scheduled_amount") or 0) for r in rows)
        total_paid = sum(
            int(r.get("actual_amount") or 0)
            for r in rows
            if r.get("status") == "paid"
            and _as_date(r.get("actual_payment_date") or r.get("scheduled_date"))
            is not None
            and _as_date(r.get("actual_payment_date") or r.get("scheduled_date"))
            <= as_of_date
        )
        remaining = max(0, total_scheduled - total_paid)
        return remaining

    def _fetch_contract_total_principal(self, lease_contract_id: str) -> int:
        """Fallback: (monthly_lease_amount × lease_term_months) when no payments rows."""
        resp = (
            self._client.table(self.TABLE_LEASES)
            .select("monthly_lease_amount, lease_term_months")
            .eq("id", lease_contract_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return 0
        row = rows[0]
        monthly = int(row.get("monthly_lease_amount") or 0)
        term = int(row.get("lease_term_months") or 0)
        return monthly * term


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _as_date(value: Any) -> Optional[date]:
    """Parse a date or ISO string into ``date``.  Returns None if not parseable."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None
