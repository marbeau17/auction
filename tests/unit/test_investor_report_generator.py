"""Unit tests for ``app.core.investor_report_generator.InvestorReportGenerator``.

These tests use a minimal dict-backed fake Supabase client (same shape as
``tests/unit/test_invoice_repo.py``) and assert the generator runs
end-to-end on realistic fund data without raising, plus that the returned
metrics / risk flags line up with the inputs. We intentionally do NOT
assert anything about PDF binary content — only that bytes come back.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from app.core.investor_report_generator import InvestorReportGenerator


# =====================================================================
# Minimal dict-backed fake Supabase client
# =====================================================================


class FakeResponse:
    def __init__(self, data: Any, count: int | None = None) -> None:
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self._table = table
        self._filters: list[tuple[str, tuple]] = []
        self._maybe_single = False
        self._limit: int | None = None

    def select(self, *_cols, count: str | None = None):
        return self

    def insert(self, payload):
        rows = self._client.tables.setdefault(self._table, [])
        items = list(payload) if isinstance(payload, list) else [payload]
        inserted = []
        for item in items:
            row = dict(item)
            row.setdefault("id", str(uuid4()))
            rows.append(row)
            inserted.append(row)
        self._pending_insert = inserted
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def eq(self, column, value):
        self._filters.append(("eq", (column, value)))
        return self

    def order(self, column, desc: bool = False):
        self._order = (column, desc)
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def execute(self) -> FakeResponse:
        if hasattr(self, "_pending_insert"):
            return FakeResponse(self._pending_insert)
        if hasattr(self, "_pending_update"):
            rows = self._client.tables.get(self._table, [])
            matched = [r for r in rows if self._matches(r)]
            for r in matched:
                r.update(self._pending_update)
            return FakeResponse(matched)

        rows = self._client.tables.get(self._table, [])
        matched = [r for r in rows if self._matches(r)]
        if hasattr(self, "_order"):
            col, desc = self._order
            matched = sorted(matched, key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._maybe_single:
            return FakeResponse(matched[0] if matched else None)
        return FakeResponse(matched, count=len(matched))

    def _matches(self, row: dict) -> bool:
        for op, args in self._filters:
            if op == "eq":
                col, val = args
                if str(row.get(col)) != str(val):
                    return False
        return True


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def fund_id() -> str:
    return str(uuid4())


@pytest.fixture
def fund_row(fund_id) -> dict:
    return {
        "id": fund_id,
        "fund_name": "Test Fund A-2026",
        "fund_code": "TF-A-2026",
        "status": "active",
        "establishment_date": "2026-01-01",
        "target_yield_rate": 0.08,
        "total_fundraise_amount": 100_000_000,
    }


@pytest.fixture
def populated_client(fund_id, fund_row) -> FakeClient:
    client = FakeClient()
    client.tables["funds"] = [fund_row]
    client.tables["vehicle_nav_history"] = [
        {
            "id": str(uuid4()),
            "fund_id": fund_id,
            "vehicle_id": str(uuid4()),
            "recording_date": "2026-04-30",
            "acquisition_price": 10_000_000,
            "book_value": 9_500_000,
            "market_value": 9_200_000,
            "depreciation_cumulative": 500_000,
            "lease_income_cumulative": 300_000,
            "nav": 9_800_000,
            "ltv_ratio": 0.55,
        },
        {
            "id": str(uuid4()),
            "fund_id": fund_id,
            "vehicle_id": str(uuid4()),
            "recording_date": "2026-03-31",
            "acquisition_price": 10_000_000,
            "book_value": 9_700_000,
            "market_value": 9_400_000,
            "depreciation_cumulative": 300_000,
            "lease_income_cumulative": 200_000,
            "nav": 9_900_000,
            "ltv_ratio": 0.52,
        },
    ]
    client.tables["fund_distributions"] = [
        {
            "id": str(uuid4()),
            "fund_id": fund_id,
            "investor_id": str(uuid4()),
            "distribution_date": "2026-04-25",
            "distribution_type": "monthly",
            "distribution_amount": 650_000,
            "annualized_yield": 0.078,
        },
        {
            "id": str(uuid4()),
            "fund_id": fund_id,
            "investor_id": str(uuid4()),
            "distribution_date": "2026-05-25",
            "distribution_type": "monthly",
            "distribution_amount": 650_000,
            "annualized_yield": 0.078,
        },
    ]
    client.tables["secured_asset_blocks"] = [
        {
            "id": str(uuid4()),
            "fund_id": fund_id,
            "sab_number": "SAB-001",
            "acquisition_price": 5_000_000,
            "adjusted_valuation": 4_800_000,
            "b2b_wholesale_valuation": 4_700_000,
            "ltv_ratio": 0.52,
            "status": "leased",
        },
        {
            "id": str(uuid4()),
            "fund_id": fund_id,
            "sab_number": "SAB-002",
            "acquisition_price": 5_000_000,
            "adjusted_valuation": 4_900_000,
            "b2b_wholesale_valuation": 4_800_000,
            "ltv_ratio": 0.58,
            "status": "held",
        },
    ]
    client.tables["lease_payments"] = []
    return client


# =====================================================================
# Tests
# =====================================================================


class TestGenerate:

    def test_returns_pdf_bytes_and_metrics(self, populated_client, fund_id):
        gen = InvestorReportGenerator(client=populated_client)
        pdf_bytes, metrics = gen.generate(fund_id, date(2026, 4, 15))

        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF"), "expected a valid PDF byte stream"
        assert metrics["nav_total"] == 9_800_000, "NAV sum should only cover April rows"
        assert metrics["dividend_paid"] == 650_000
        assert metrics["dividend_scheduled"] == 650_000
        assert isinstance(metrics["risk_flags"], list)

    def test_empty_fund_still_produces_pdf(self):
        """Missing NAV / dividends / SABs: generator must not crash."""
        client = FakeClient()
        fid = str(uuid4())
        client.tables["funds"] = [{"id": fid, "fund_name": "Empty Fund"}]
        gen = InvestorReportGenerator(client=client)
        pdf_bytes, metrics = gen.generate(fid, date(2026, 4, 1))

        assert pdf_bytes.startswith(b"%PDF")
        assert metrics["nav_total"] == 0
        assert metrics["dividend_paid"] == 0
        assert metrics["dividend_scheduled"] == 0
        # No data -> no risk flags either (no NFAV denominator)
        assert metrics["risk_flags"] == []

    def test_ltv_breach_raises_flag(self, fund_id, fund_row):
        client = FakeClient()
        client.tables["funds"] = [fund_row]
        client.tables["vehicle_nav_history"] = []
        client.tables["fund_distributions"] = []
        client.tables["secured_asset_blocks"] = [
            {
                "id": str(uuid4()),
                "fund_id": fund_id,
                "sab_number": "SAB-LTV-HIGH",
                "acquisition_price": 5_000_000,
                "adjusted_valuation": 5_000_000,
                "b2b_wholesale_valuation": 5_000_000,
                "ltv_ratio": 0.85,  # above critical threshold
                "status": "leased",
            }
        ]
        client.tables["lease_payments"] = []

        gen = InvestorReportGenerator(client=client)
        _, metrics = gen.generate(fund_id, date(2026, 4, 1))

        codes = [f.get("code") for f in metrics["risk_flags"]]
        severities = [f.get("severity") for f in metrics["risk_flags"]]
        assert "ltv_breach" in codes
        assert "critical" in severities

    def test_nfav_below_60_raises_critical_flag(self, fund_id, fund_row):
        client = FakeClient()
        client.tables["funds"] = [fund_row]
        # NAV is 40% of acquisition — NFAV floor breached.
        client.tables["vehicle_nav_history"] = [
            {
                "id": str(uuid4()),
                "fund_id": fund_id,
                "vehicle_id": str(uuid4()),
                "recording_date": "2026-04-30",
                "acquisition_price": 10_000_000,
                "book_value": 4_000_000,
                "market_value": 4_000_000,
                "depreciation_cumulative": 6_000_000,
                "lease_income_cumulative": 0,
                "nav": 4_000_000,
                "ltv_ratio": 0.40,
            }
        ]
        client.tables["fund_distributions"] = []
        client.tables["secured_asset_blocks"] = [
            {
                "id": str(uuid4()),
                "fund_id": fund_id,
                "sab_number": "SAB-X",
                "acquisition_price": 10_000_000,
                "adjusted_valuation": 4_000_000,
                "b2b_wholesale_valuation": 4_000_000,
                "ltv_ratio": 0.40,
                "status": "leased",
            }
        ]
        client.tables["lease_payments"] = []

        gen = InvestorReportGenerator(client=client)
        _, metrics = gen.generate(fund_id, date(2026, 4, 1))

        codes = [f.get("code") for f in metrics["risk_flags"]]
        assert "nfav_below_60" in codes

    def test_report_month_normalised_to_first_of_month(self, populated_client, fund_id):
        """Passing any day in April must still anchor to April 1st logic."""
        gen = InvestorReportGenerator(client=populated_client)
        pdf_mid, metrics_mid = gen.generate(fund_id, date(2026, 4, 30))
        pdf_first, metrics_first = gen.generate(fund_id, date(2026, 4, 1))

        # Both invocations should surface the same metrics.
        assert metrics_mid["nav_total"] == metrics_first["nav_total"]
        assert metrics_mid["dividend_paid"] == metrics_first["dividend_paid"]
        assert pdf_mid.startswith(b"%PDF")
        assert pdf_first.startswith(b"%PDF")
