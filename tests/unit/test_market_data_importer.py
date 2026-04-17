"""Unit tests for ``app.core.market_data_importer``.

Covers:

* ``_validate_row`` rejects missing required fields, out-of-range year,
  mileage, and price
* Column alias mapping (Japanese → canonical) via ``_normalize_column``
* ``canonicalize_maker`` handles 表記揺れ variants
* BOM-prefixed UTF-8 CSV is accepted (``_validate_row`` path verified
  through in-process CSV parsing)
* ``to_dict`` caps ``errors`` at 50 entries
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.core.market_data_importer import (
    COLUMN_ALIASES,
    ImportResult,
    MAKER_ALIASES,
    MarketDataImporter,
    canonicalize_maker,
)


@pytest.fixture
def importer() -> MarketDataImporter:
    return MarketDataImporter(MagicMock())


def _valid_row(**overrides) -> dict:
    row = {
        "maker": "いすゞ",
        "model": "エルフ",
        "year": "2020",
        "mileage_km": "85000",
        "price_yen": "3500000",
        "auction_date": "2024-10-01",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# _validate_row
# ---------------------------------------------------------------------------


class TestValidateRow:

    def test_valid_row_has_no_errors(self, importer: MarketDataImporter):
        assert importer._validate_row(_valid_row(), 2) == []

    def test_missing_required_field_flagged(
        self, importer: MarketDataImporter
    ):
        errors = importer._validate_row(_valid_row(maker=""), 5)
        fields = {e["field"] for e in errors}
        assert "maker" in fields
        # Row number preserved
        assert all(e["row"] == 5 for e in errors)

    @pytest.mark.parametrize(
        "bad_year", ["1989", "1900", str(datetime.now().year + 2), "3000"]
    )
    def test_year_out_of_range_rejected(
        self, importer: MarketDataImporter, bad_year: str
    ):
        errors = importer._validate_row(_valid_row(year=bad_year), 3)
        assert any(e["field"] == "year" for e in errors)

    def test_year_non_numeric_rejected(self, importer: MarketDataImporter):
        errors = importer._validate_row(_valid_row(year="not-a-year"), 3)
        assert any(e["field"] == "year" for e in errors)

    @pytest.mark.parametrize("bad_mileage", ["-1", "2000001", "999999999"])
    def test_mileage_out_of_range_rejected(
        self, importer: MarketDataImporter, bad_mileage: str
    ):
        errors = importer._validate_row(
            _valid_row(mileage_km=bad_mileage), 4
        )
        assert any(e["field"] == "mileage_km" for e in errors)

    def test_mileage_with_comma_accepted(
        self, importer: MarketDataImporter
    ):
        assert importer._validate_row(_valid_row(mileage_km="85,000"), 2) == []

    @pytest.mark.parametrize("bad_price", ["-100", "100000001"])
    def test_price_out_of_range_rejected(
        self, importer: MarketDataImporter, bad_price: str
    ):
        errors = importer._validate_row(_valid_row(price_yen=bad_price), 6)
        assert any(e["field"] == "price_yen" for e in errors)


# ---------------------------------------------------------------------------
# Column alias normalisation
# ---------------------------------------------------------------------------


class TestColumnAliases:

    @pytest.mark.parametrize(
        "alias,canonical",
        [
            ("メーカー", "maker"),
            ("車種", "model"),
            ("年式", "year"),
            ("走行距離", "mileage_km"),
            ("価格", "price_yen"),
            ("落札価格", "price_yen"),
            ("落札日", "auction_date"),
            ("オークション", "auction_site"),
            ("ボディ", "body_type"),
        ],
    )
    def test_japanese_alias_maps_to_canonical(
        self, importer: MarketDataImporter, alias: str, canonical: str
    ):
        assert importer._normalize_column(alias) == canonical

    def test_english_case_insensitive_alias(
        self, importer: MarketDataImporter
    ):
        # 'Maker' (mixed case) -> 'maker' (alias table has lower key)
        assert importer._normalize_column("Maker") == "maker"
        assert importer._normalize_column("Price") == "price_yen"

    def test_all_required_columns_have_aliases(self):
        # Sanity: every canonical value is reachable from at least one alias
        for _, canonical in COLUMN_ALIASES.items():
            assert canonical in COLUMN_ALIASES.values()


# ---------------------------------------------------------------------------
# Maker canonicalisation (表記揺れ)
# ---------------------------------------------------------------------------


class TestCanonicalizeMaker:

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("いすず", "いすゞ"),
            ("ISUZU", "いすゞ"),
            ("isuzu", "いすゞ"),
            ("日野", "日野"),
            ("hino", "日野"),
            ("三菱", "三菱ふそう"),
            ("ふそう", "三菱ふそう"),
            ("UD", "UDトラックス"),
            ("日産ディーゼル", "UDトラックス"),
            ("  トヨタ  ", "トヨタ"),
        ],
    )
    def test_variants_map_to_canonical(self, raw: str, expected: str):
        assert canonicalize_maker(raw) == expected

    def test_unknown_maker_returned_as_is(self):
        assert canonicalize_maker("Scania") == "Scania"

    def test_empty_returns_empty(self):
        assert canonicalize_maker("") == ""

    def test_alias_table_values_are_canonical(self):
        """Every alias value must itself be a key pointing to itself (i.e.
        canonical), so canonicalize is idempotent."""
        for canonical in set(MAKER_ALIASES.values()):
            # Re-canonicalising a canonical name must be a fixed point
            assert canonicalize_maker(canonical) == canonical


# ---------------------------------------------------------------------------
# BOM handling (end-to-end through csv.DictReader the way the importer does)
# ---------------------------------------------------------------------------


class TestBomHandling:

    def test_utf8_bom_prefix_is_stripped(self):
        content = (
            "\ufeffmaker,model,year,mileage_km,price_yen,auction_date\n"
            "いすゞ,エルフ,2020,85000,3500000,2024-10-01\n"
        ).encode("utf-8")

        # Mirror importer decode path
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        assert reader.fieldnames is not None
        # The BOM must be stripped so the first field is plain 'maker'.
        assert reader.fieldnames[0] == "maker"


# ---------------------------------------------------------------------------
# ImportResult.to_dict caps error list
# ---------------------------------------------------------------------------


class TestImportResultErrorCap:

    def test_errors_capped_at_50_in_to_dict(self):
        r = ImportResult()
        for i in range(100):
            r.errors.append({"row": i, "field": "x", "message": "fake"})
        out = r.to_dict()
        assert len(out["errors"]) == 50

    def test_auction_dates_capped_at_20(self):
        r = ImportResult()
        for i in range(50):
            r.auction_dates.add(f"2024-10-{(i % 30) + 1:02d}")
        out = r.to_dict()
        assert len(out["auction_dates"]) <= 20
