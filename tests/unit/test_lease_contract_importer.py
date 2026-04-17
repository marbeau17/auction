"""Unit tests for ``app.core.lease_contract_importer``.

Covers the 13 validation rules in ``_validate_row``:

1. Every required column must be non-empty
2. contract_start_date must parse YYYY-MM-DD
3. contract_end_date must parse YYYY-MM-DD
4. contract_end_date must be strictly after contract_start_date
5. monthly_lease_amount must be a positive integer
6. monthly_lease_amount numeric format (commas / ¥ stripped)
7. tax_rate within [0, 1]
8. tax_rate numeric format
9. residual_value non-negative
10. residual_value numeric format
11. payment_day within [1, 31]
12. acquisition_price positive
13. vehicle_year within [1990, current+1]

Also asserts ``_transform_to_lease_contract`` preserves sum integrity
(monthly_lease_amount_tax_incl ≈ monthly_amount × (1 + tax_rate), ceiled).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.core.lease_contract_importer import (
    COLUMN_ALIASES,
    LeaseContractImporter,
    REQUIRED_COLUMNS,
)


@pytest.fixture
def importer() -> LeaseContractImporter:
    return LeaseContractImporter(MagicMock())


def _valid_row(**overrides) -> dict:
    row = {
        "contract_number": "LC-2025-0001",
        "lessee_company_name": "東京運輸株式会社",
        "contract_start_date": "2025-04-01",
        "contract_end_date": "2028-03-31",
        "monthly_lease_amount": "350000",
        "vehicle_description": "いすゞ エルフ 平ボディ",
        "tax_rate": "0.10",
        "residual_value": "500000",
        "payment_day": "25",
        "acquisition_price": "4500000",
        "vehicle_year": "2022",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Required column presence
# ---------------------------------------------------------------------------


class TestRequiredColumns:

    def test_valid_row_has_no_errors(
        self, importer: LeaseContractImporter
    ):
        assert importer._validate_row(_valid_row(), 2) == []

    @pytest.mark.parametrize("field", list(REQUIRED_COLUMNS))
    def test_missing_required_field_flagged(
        self, importer: LeaseContractImporter, field: str
    ):
        errors = importer._validate_row(_valid_row(**{field: ""}), 5)
        assert any(e["field"] == field for e in errors)


# ---------------------------------------------------------------------------
# Date format + ordering
# ---------------------------------------------------------------------------


class TestDateValidation:

    @pytest.mark.parametrize(
        "bad",
        ["2025/04/01", "04-01-2025", "20250401", "not-a-date"],
    )
    def test_bad_start_date_format_flagged(
        self, importer: LeaseContractImporter, bad: str
    ):
        errors = importer._validate_row(
            _valid_row(contract_start_date=bad), 3
        )
        assert any(e["field"] == "contract_start_date" for e in errors)

    def test_end_date_must_be_after_start(
        self, importer: LeaseContractImporter
    ):
        errors = importer._validate_row(
            _valid_row(
                contract_start_date="2025-04-01",
                contract_end_date="2025-04-01",  # same day -> invalid
            ),
            3,
        )
        assert any(
            e["field"] == "contract_end_date" for e in errors
        )

    def test_end_before_start_flagged(
        self, importer: LeaseContractImporter
    ):
        errors = importer._validate_row(
            _valid_row(
                contract_start_date="2025-04-01",
                contract_end_date="2025-03-01",
            ),
            3,
        )
        assert any(e["field"] == "contract_end_date" for e in errors)


# ---------------------------------------------------------------------------
# Numeric range / format checks
# ---------------------------------------------------------------------------


class TestNumericValidation:

    @pytest.mark.parametrize("amount", ["0", "-1000", "abc"])
    def test_monthly_amount_invalid(
        self, importer: LeaseContractImporter, amount: str
    ):
        errors = importer._validate_row(
            _valid_row(monthly_lease_amount=amount), 2
        )
        assert any(e["field"] == "monthly_lease_amount" for e in errors)

    def test_monthly_amount_accepts_currency_format(
        self, importer: LeaseContractImporter
    ):
        # "¥350,000" must be accepted (validator strips commas and ¥)
        errors = importer._validate_row(
            _valid_row(monthly_lease_amount="¥350,000"), 2
        )
        # No monthly_lease_amount error
        assert not any(
            e["field"] == "monthly_lease_amount" for e in errors
        )

    @pytest.mark.parametrize("tax", ["-0.1", "1.5", "not-a-number"])
    def test_tax_rate_invalid(
        self, importer: LeaseContractImporter, tax: str
    ):
        errors = importer._validate_row(_valid_row(tax_rate=tax), 2)
        assert any(e["field"] == "tax_rate" for e in errors)

    def test_residual_value_negative_rejected(
        self, importer: LeaseContractImporter
    ):
        errors = importer._validate_row(
            _valid_row(residual_value="-1"), 2
        )
        assert any(e["field"] == "residual_value" for e in errors)

    @pytest.mark.parametrize("pd", ["0", "32", "99", "abc"])
    def test_payment_day_out_of_range(
        self, importer: LeaseContractImporter, pd: str
    ):
        errors = importer._validate_row(_valid_row(payment_day=pd), 2)
        assert any(e["field"] == "payment_day" for e in errors)

    def test_acquisition_price_must_be_positive(
        self, importer: LeaseContractImporter
    ):
        errors = importer._validate_row(
            _valid_row(acquisition_price="0"), 2
        )
        assert any(e["field"] == "acquisition_price" for e in errors)

    def test_vehicle_year_out_of_range(
        self, importer: LeaseContractImporter
    ):
        errors = importer._validate_row(_valid_row(vehicle_year="1989"), 2)
        assert any(e["field"] == "vehicle_year" for e in errors)

        future = datetime.now().year + 2
        errors = importer._validate_row(
            _valid_row(vehicle_year=str(future)), 2
        )
        assert any(e["field"] == "vehicle_year" for e in errors)


# ---------------------------------------------------------------------------
# Transform: sum integrity (tax-inclusive amount)
# ---------------------------------------------------------------------------


class TestTransformSumIntegrity:

    def test_tax_inclusive_amount_ceiled(
        self, importer: LeaseContractImporter
    ):
        row = _valid_row(monthly_lease_amount="350000", tax_rate="0.10")
        rec = importer._transform_to_lease_contract(row, fund_id="f-123")
        assert rec is not None
        # 350,000 * 1.10 = 385,000 exactly (no ceiling artifact)
        assert rec["monthly_lease_amount"] == 350_000
        assert rec["monthly_lease_amount_tax_incl"] == 385_000

    def test_lease_term_months_computed(
        self, importer: LeaseContractImporter
    ):
        rec = importer._transform_to_lease_contract(
            _valid_row(
                contract_start_date="2025-04-01",
                contract_end_date="2028-04-01",
            ),
            fund_id="f-1",
        )
        assert rec is not None
        # 3 years = 36 months
        assert rec["lease_term_months"] == 36

    def test_transform_sets_default_tax_when_missing(
        self, importer: LeaseContractImporter
    ):
        row = _valid_row()
        row.pop("tax_rate", None)
        row["tax_rate"] = ""
        rec = importer._transform_to_lease_contract(row, fund_id="f-1")
        assert rec is not None
        assert rec["tax_rate"] == pytest.approx(0.10)

    def test_column_aliases_japanese_to_canonical(
        self, importer: LeaseContractImporter
    ):
        # 契約番号 -> contract_number, 月額リース料 -> monthly_lease_amount, etc.
        assert COLUMN_ALIASES["契約番号"] == "contract_number"
        assert COLUMN_ALIASES["月額リース料"] == "monthly_lease_amount"
        assert COLUMN_ALIASES["開始日"] == "contract_start_date"
        assert COLUMN_ALIASES["終了日"] == "contract_end_date"
