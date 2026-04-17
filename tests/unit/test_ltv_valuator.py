"""Unit tests for ``app.core.ltv_valuator.LTVValuator``.

Uses a minimal dict-backed fake Supabase client (same pattern as
``test_invoice_repo``) to exercise:

* Per-vehicle LTV math & headroom
* WARNING / BREACH threshold classification (boundary values)
* Fund-level aggregation across multiple vehicles
* Stress test scale factor (book_value × (1 - shock))
* Vehicle-in-breach counting after stress
* Zero-book-value defensive handling
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

import pytest

from app.core.ltv_valuator import (
    DEFAULT_BREACH_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    LTVValuator,
)


# ===================================================================
# Dict-backed fake Supabase client
# ===================================================================


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self.data = data


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._filters: list[tuple[str, tuple]] = []
        self._mode = "select"
        self._payload: Any = None
        self._conflict: str | None = None

    def select(self, *_cols, **_kw):
        self._mode = "select"
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None):
        self._mode = "upsert"
        self._payload = payload
        self._conflict = on_conflict
        return self

    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", (column, value)))
        return self

    def lte(self, column, value):
        self._filters.append(("lte", (column, value)))
        return self

    def order(self, *_args, **_kw):
        return self

    def limit(self, *_args, **_kw):
        return self

    def execute(self) -> FakeResponse:
        rows = self._client.tables.setdefault(self._table, [])

        if self._mode == "upsert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for item in payload:
                rows.append(dict(item))
                out.append(dict(item))
            return FakeResponse(out)

        if self._mode == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            for item in payload:
                rows.append(dict(item))
            return FakeResponse(list(payload))

        # select
        result = [r for r in rows if self._matches(r)]
        return FakeResponse(result)

    def _matches(self, row: dict) -> bool:
        for op, args in self._filters:
            col, val = args
            cell = row.get(col)
            if op == "eq" and cell != val:
                return False
            if op == "gte" and (cell is None or cell < val):
                return False
            if op == "lte" and (cell is None or cell > val):
                return False
        return True


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


# ===================================================================
# Fixtures / helpers
# ===================================================================


FUND_A = "fund-aaaa-0001"
FUND_B = "fund-bbbb-0002"

V1 = "veh-1111-0001"
V2 = "veh-2222-0002"
V3 = "veh-3333-0003"

LEASE_1 = "lease-1111"
LEASE_2 = "lease-2222"
LEASE_3 = "lease-3333"


def _seed_vehicle(
    client: FakeClient,
    *,
    vehicle_id: str,
    fund_id: str,
    lease_id: str | None,
    book_value: int,
    scheduled_total: int,
    paid_total: int,
    recording_date: str = "2026-04-17",
) -> None:
    """Insert NAV history, SAB link, and lease_payments for a single vehicle."""
    # NAV history row
    client.tables.setdefault("vehicle_nav_history", []).append(
        {
            "vehicle_id": vehicle_id,
            "fund_id": fund_id,
            "book_value": book_value,
            "market_value": book_value,
            "recording_date": recording_date,
        }
    )
    # SAB linking the vehicle to fund and (optionally) a lease contract
    client.tables.setdefault("secured_asset_blocks", []).append(
        {
            "id": f"sab-{vehicle_id}",
            "vehicle_id": vehicle_id,
            "fund_id": fund_id,
            "lease_contract_id": lease_id,
        }
    )
    if lease_id is not None:
        # A single scheduled payment row summarises contract-wide principal
        # and payments for the purposes of these tests.
        client.tables.setdefault("lease_payments", []).append(
            {
                "lease_contract_id": lease_id,
                "scheduled_amount": scheduled_total,
                "actual_amount": paid_total,
                "status": "paid" if paid_total > 0 else "scheduled",
                "scheduled_date": "2026-01-31",
                "actual_payment_date": "2026-01-31" if paid_total > 0 else None,
            }
        )


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def valuator(client: FakeClient) -> LTVValuator:
    return LTVValuator(client)


# ===================================================================
# 1. Vehicle LTV & headroom math
# ===================================================================


class TestVehicleLTV:
    def test_vehicle_ltv_and_headroom(self, client: FakeClient, valuator: LTVValuator):
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=10_000_000,
            scheduled_total=8_000_000,
            paid_total=2_000_000,
        )
        # outstanding_principal = 8_000_000 - 2_000_000 = 6_000_000
        # ltv = 6_000_000 / 10_000_000 = 0.60
        result = valuator.calculate_vehicle_ltv(V1, date(2026, 4, 17))
        assert result["book_value"] == 10_000_000
        assert result["outstanding_principal"] == 6_000_000
        assert result["ltv_ratio"] == pytest.approx(0.60, abs=1e-6)
        assert result["collateral_headroom"] == 4_000_000
        assert result["status"] == "HEALTHY"
        assert result["warning_flag"] is False
        assert result["breach_flag"] is False


# ===================================================================
# 2. Threshold classification — boundary values
# ===================================================================


class TestThresholds:
    def test_exact_warning_threshold_triggers_warning(
        self, client: FakeClient, valuator: LTVValuator
    ):
        # LTV = 750 / 1000 = 0.75 → WARNING (inclusive)
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=1_000_000,
            scheduled_total=750_000,
            paid_total=0,
        )
        r = valuator.calculate_vehicle_ltv(V1, date(2026, 4, 17))
        assert r["ltv_ratio"] == pytest.approx(DEFAULT_WARNING_THRESHOLD, abs=1e-6)
        assert r["status"] == "WARNING"
        assert r["warning_flag"] is True
        assert r["breach_flag"] is False

    def test_exact_breach_threshold_triggers_breach(
        self, client: FakeClient, valuator: LTVValuator
    ):
        # LTV = 850 / 1000 = 0.85 → BREACH (inclusive)
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=1_000_000,
            scheduled_total=850_000,
            paid_total=0,
        )
        r = valuator.calculate_vehicle_ltv(V1, date(2026, 4, 17))
        assert r["ltv_ratio"] == pytest.approx(DEFAULT_BREACH_THRESHOLD, abs=1e-6)
        assert r["status"] == "BREACH"
        assert r["breach_flag"] is True
        # collateral_headroom = 1_000_000 - 850_000 = 150_000 (still positive)
        assert r["collateral_headroom"] == 150_000

    def test_zero_book_value_with_principal_forces_breach(
        self, client: FakeClient, valuator: LTVValuator
    ):
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=0,
            scheduled_total=500_000,
            paid_total=0,
        )
        r = valuator.calculate_vehicle_ltv(V1, date(2026, 4, 17))
        # Sentinel-large LTV must still classify as breach
        assert r["breach_flag"] is True
        assert r["status"] == "BREACH"
        assert r["collateral_headroom"] == -500_000


# ===================================================================
# 3. Fund aggregation across multiple vehicles
# ===================================================================


class TestFundAggregation:
    def test_fund_ltv_aggregates_across_vehicles(
        self, client: FakeClient, valuator: LTVValuator
    ):
        # Vehicle 1: book 10M, outstanding 6M
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=10_000_000,
            scheduled_total=8_000_000,
            paid_total=2_000_000,
        )
        # Vehicle 2: book 5M, outstanding 4M (LTV=0.80 → WARNING, not BREACH)
        _seed_vehicle(
            client,
            vehicle_id=V2,
            fund_id=FUND_A,
            lease_id=LEASE_2,
            book_value=5_000_000,
            scheduled_total=4_000_000,
            paid_total=0,
        )
        # Vehicle 3: different fund — must NOT be included
        _seed_vehicle(
            client,
            vehicle_id=V3,
            fund_id=FUND_B,
            lease_id=LEASE_3,
            book_value=1_000_000,
            scheduled_total=900_000,  # BREACH if it leaked in
            paid_total=0,
        )

        result = valuator.calculate_fund_ltv(FUND_A, date(2026, 4, 17))
        assert result["vehicles_count"] == 2
        assert result["book_value_total"] == 15_000_000
        assert result["outstanding_principal_total"] == 10_000_000
        # 10/15 = 0.6667
        assert result["ltv_ratio"] == pytest.approx(10 / 15, abs=1e-4)
        assert result["collateral_headroom"] == 5_000_000
        # V2 is at 0.80 → WARNING; V1 at 0.60 → HEALTHY
        assert result["warning_count"] == 1
        assert result["breach_count"] == 0
        assert result["status"] == "HEALTHY"  # aggregate under 0.75


# ===================================================================
# 4. Stress test scale factor
# ===================================================================


class TestStressTest:
    def test_stress_applies_scale_factor_to_book_value(
        self, client: FakeClient, valuator: LTVValuator
    ):
        # Book 10M, principal 6M → baseline LTV 0.60
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=10_000_000,
            scheduled_total=8_000_000,
            paid_total=2_000_000,
        )
        results = valuator.stress_test(
            FUND_A,
            shock_percentages=[0.0, 0.20, 0.50],
            as_of_date=date(2026, 4, 17),
        )
        assert len(results) == 3

        # shock=0 → stressed book == baseline book
        zero = results[0]
        assert zero["shock_pct"] == 0.0
        assert zero["stressed_book_value_total"] == 10_000_000
        assert zero["fund_ltv"] == pytest.approx(0.60, abs=1e-6)
        assert zero["fund_ltv_baseline"] == pytest.approx(0.60, abs=1e-6)

        # shock=0.20 → book = 8M, ltv = 6/8 = 0.75 → WARNING
        mid = results[1]
        assert mid["stressed_book_value_total"] == 8_000_000
        assert mid["fund_ltv"] == pytest.approx(0.75, abs=1e-6)
        assert mid["status"] == "WARNING"
        assert mid["breach_flag"] is False

        # shock=0.50 → book = 5M, ltv = 6/5 = 1.2 → BREACH
        severe = results[2]
        assert severe["stressed_book_value_total"] == 5_000_000
        assert severe["fund_ltv"] == pytest.approx(1.20, abs=1e-6)
        assert severe["status"] == "BREACH"
        assert severe["breach_flag"] is True
        assert severe["vehicles_in_breach"] == 1

    def test_stress_counts_vehicles_in_breach(
        self, client: FakeClient, valuator: LTVValuator
    ):
        # V1 healthy at baseline (LTV 0.50), V2 near breach (LTV 0.80)
        _seed_vehicle(
            client,
            vehicle_id=V1,
            fund_id=FUND_A,
            lease_id=LEASE_1,
            book_value=10_000_000,
            scheduled_total=5_000_000,
            paid_total=0,
        )
        _seed_vehicle(
            client,
            vehicle_id=V2,
            fund_id=FUND_A,
            lease_id=LEASE_2,
            book_value=5_000_000,
            scheduled_total=4_000_000,
            paid_total=0,
        )
        # 10% shock
        #   V1: book 9M, principal 5M → 0.5556 (HEALTHY)
        #   V2: book 4.5M, principal 4M → 0.8889 (BREACH)
        [res] = valuator.stress_test(
            FUND_A, shock_percentages=[0.10], as_of_date=date(2026, 4, 17)
        )
        assert res["vehicles_in_breach"] == 1
        assert res["vehicles_in_warning"] == 1
        assert res["fund_ltv"] == pytest.approx(9 / 13.5, abs=1e-4)


# ===================================================================
# 5. Constructor guards
# ===================================================================


class TestConstructorValidation:
    def test_invalid_thresholds_raise(self, client: FakeClient):
        with pytest.raises(ValueError):
            LTVValuator(client, warning_threshold=0.90, breach_threshold=0.80)
        with pytest.raises(ValueError):
            LTVValuator(client, warning_threshold=0.0, breach_threshold=0.85)

    def test_stress_rejects_out_of_range_shock(
        self, client: FakeClient, valuator: LTVValuator
    ):
        with pytest.raises(ValueError):
            valuator.stress_test(FUND_A, shock_percentages=[1.0])
        with pytest.raises(ValueError):
            valuator.stress_test(FUND_A, shock_percentages=[-0.1])


# ===================================================================
# 6. Empty fund returns zeroed aggregate
# ===================================================================


class TestEmptyFund:
    def test_fund_with_no_vehicles_returns_zero_ltv(
        self, client: FakeClient, valuator: LTVValuator
    ):
        result = valuator.calculate_fund_ltv(FUND_A, date(2026, 4, 17))
        assert result["vehicles_count"] == 0
        assert result["book_value_total"] == 0
        assert result["outstanding_principal_total"] == 0
        assert result["ltv_ratio"] == 0.0
        assert result["collateral_headroom"] == 0
        assert result["status"] == "HEALTHY"
        assert result["breach_flag"] is False
