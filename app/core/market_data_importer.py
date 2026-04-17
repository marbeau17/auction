"""Market data (auction results) CSV/Excel importer.

Schema mapping notes
--------------------
The ``public.vehicles`` table uses foreign keys (``manufacturer_id``,
``category_id``, ``body_type_id``) rather than raw text columns, and does
NOT have dedicated ``auction_date`` / ``auction_site`` columns.  We therefore
apply the following explicit mapping:

* ``maker``        -> look up (or insert) ``manufacturers`` and store its UUID
                     in ``manufacturer_id``.  Maker text is canonicalised
                     through :data:`MAKER_ALIASES` to absorb common 表記揺れ
                     (e.g. ``いすず`` -> ``いすゞ``).
* ``auction_date`` -> stored in ``scraped_at`` (timestamptz) since the table
                     has no dedicated auction date column.
* ``auction_site`` -> stored in ``source_site`` since the table has no
                     dedicated auction site column.
* ``body_type``    -> resolved to ``body_type_id`` when a matching row exists
                     in ``body_types``; otherwise left NULL.
* category        -> defaults to ``MEDIUM`` when none can be inferred, because
                     ``vehicles.category_id`` is NOT NULL.

Both raw ``auction_date`` and ``auction_site`` values are echoed back in the
:class:`ImportResult` summary so the operator can see the data was preserved
even though the columns themselves are reused.
"""

from __future__ import annotations
import csv
import io
from datetime import date, datetime
from typing import Optional

import structlog

logger = structlog.get_logger()

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


class ImportResult:
    """Result of a market data import operation."""

    def __init__(self):
        self.total_rows = 0
        self.imported_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.errors: list[dict] = []  # [{row: int, field: str, message: str}]
        # Track preserved auction metadata for user visibility.
        self.auction_dates: set[str] = set()
        self.auction_sites: set[str] = set()
        # Manufacturers that were created on-the-fly (warnings).
        self.created_manufacturers: list[str] = []

    def to_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "errors": self.errors[:50],  # Limit error list
            "auction_dates": sorted(self.auction_dates)[:20],
            "auction_sites": sorted(self.auction_sites)[:20],
            "created_manufacturers": self.created_manufacturers,
        }


REQUIRED_COLUMNS = ['maker', 'model', 'year', 'mileage_km', 'price_yen', 'auction_date']
OPTIONAL_COLUMNS = ['auction_site', 'body_type', 'tonnage', 'transmission', 'fuel_type', 'location']

COLUMN_ALIASES = {
    'メーカー': 'maker',
    'maker': 'maker',
    '車種': 'model',
    'model': 'model',
    '年式': 'year',
    'year': 'year',
    '走行距離': 'mileage_km',
    'mileage': 'mileage_km',
    'mileage_km': 'mileage_km',
    '価格': 'price_yen',
    '落札価格': 'price_yen',
    'price': 'price_yen',
    'price_yen': 'price_yen',
    '落札日': 'auction_date',
    'auction_date': 'auction_date',
    'date': 'auction_date',
    'オークション': 'auction_site',
    'auction_site': 'auction_site',
    'site': 'auction_site',
    'ボディ': 'body_type',
    'body_type': 'body_type',
    '積載量': 'tonnage',
    'tonnage': 'tonnage',
}


# ---------------------------------------------------------------------------
# Manufacturer canonicalisation (表記揺れ)
#
# Keys are lowercased variants seen in the wild; values are the canonical
# Japanese name that should match ``manufacturers.name`` in the DB.
# ---------------------------------------------------------------------------
MAKER_ALIASES: dict[str, str] = {
    # いすゞ
    "いすゞ": "いすゞ",
    "いすず": "いすゞ",
    "イスズ": "いすゞ",
    "イスゞ": "いすゞ",
    "isuzu": "いすゞ",
    "五十鈴": "いすゞ",
    # 日野
    "日野": "日野",
    "ひの": "日野",
    "ヒノ": "日野",
    "hino": "日野",
    # 三菱ふそう
    "三菱ふそう": "三菱ふそう",
    "三菱フソウ": "三菱ふそう",
    "ふそう": "三菱ふそう",
    "フソウ": "三菱ふそう",
    "三菱": "三菱ふそう",
    "mitsubishi": "三菱ふそう",
    "mitsubishi fuso": "三菱ふそう",
    "fuso": "三菱ふそう",
    # UDトラックス
    "udトラックス": "UDトラックス",
    "ud": "UDトラックス",
    "ud trucks": "UDトラックス",
    "udtrucks": "UDトラックス",
    "日産ディーゼル": "UDトラックス",
    # トヨタ
    "トヨタ": "トヨタ",
    "とよた": "トヨタ",
    "toyota": "トヨタ",
    "豊田": "トヨタ",
    # 日産
    "日産": "日産",
    "にっさん": "日産",
    "ニッサン": "日産",
    "nissan": "日産",
    # マツダ
    "マツダ": "マツダ",
    "まつだ": "マツダ",
    "mazda": "マツダ",
    "松田": "マツダ",
}


def canonicalize_maker(raw: str) -> str:
    """Return the canonical manufacturer name for a raw maker string."""
    if not raw:
        return ""
    key = raw.strip().lower()
    # try exact lowercase, then original-case exact, then as-is
    return (
        MAKER_ALIASES.get(key)
        or MAKER_ALIASES.get(raw.strip())
        or raw.strip()
    )


class MarketDataImporter:
    """Imports auction market data from CSV or Excel files."""

    def __init__(self, supabase_client):
        self.supabase = supabase_client
        # Cache: canonical maker name -> manufacturer uuid
        self._manufacturer_cache: dict[str, str] = {}
        # Cache: body type name -> body_type uuid
        self._body_type_cache: dict[str, str] = {}
        # Lazy-loaded default category id (vehicles.category_id is NOT NULL)
        self._default_category_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Master-data lookups
    # ------------------------------------------------------------------

    def _get_default_category_id(self) -> Optional[str]:
        """Return the default category id (code='MEDIUM') for rows lacking
        explicit category information.  Cached per importer instance.
        """
        if self._default_category_id is not None:
            return self._default_category_id

        try:
            res = (
                self.supabase.table("vehicle_categories")
                .select("id")
                .eq("code", "MEDIUM")
                .limit(1)
                .execute()
            )
            if res.data:
                self._default_category_id = res.data[0]["id"]
                return self._default_category_id
            # fallback: any active category
            res2 = (
                self.supabase.table("vehicle_categories")
                .select("id")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if res2.data:
                self._default_category_id = res2.data[0]["id"]
                return self._default_category_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("default_category_lookup_failed", error=str(exc))
        return None

    def _resolve_manufacturer_id(
        self,
        raw_maker: str,
        result: ImportResult,
    ) -> Optional[str]:
        """Look up a ``manufacturer_id`` by (canonical) name, creating the row
        if missing.  Uses a per-importer cache to avoid repeated queries.
        Returns ``None`` if resolution ultimately fails.
        """
        if not raw_maker:
            return None

        canonical = canonicalize_maker(raw_maker)
        if canonical in self._manufacturer_cache:
            return self._manufacturer_cache[canonical]

        try:
            # Query by canonical name first, then by the raw string for safety.
            # Assumed query: SELECT id FROM manufacturers
            #                 WHERE name IN (:canonical, :raw) LIMIT 1
            names_to_try = [canonical]
            if raw_maker.strip() and raw_maker.strip() != canonical:
                names_to_try.append(raw_maker.strip())

            res = (
                self.supabase.table("manufacturers")
                .select("id,name")
                .in_("name", names_to_try)
                .limit(1)
                .execute()
            )
            if res.data:
                mid = res.data[0]["id"]
                self._manufacturer_cache[canonical] = mid
                return mid

            # Not found -> insert a new manufacturer row (warning).
            code = canonical[:3].upper() if canonical else "UNK"
            try:
                ins = (
                    self.supabase.table("manufacturers")
                    .insert({
                        "name": canonical,
                        "code": f"X_{code}_{abs(hash(canonical)) % 10000:04d}",
                        "country": "JP",
                        "is_active": True,
                    })
                    .execute()
                )
                if ins.data:
                    mid = ins.data[0]["id"]
                    self._manufacturer_cache[canonical] = mid
                    result.created_manufacturers.append(canonical)
                    logger.warning("manufacturer_auto_created", name=canonical)
                    return mid
            except Exception as exc:  # noqa: BLE001
                logger.warning("manufacturer_insert_failed", name=canonical, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("manufacturer_lookup_failed", name=raw_maker, error=str(exc))

        return None

    def _resolve_body_type_id(self, body_type: str) -> Optional[str]:
        """Look up body_type_id by name. Returns None when missing (nullable FK)."""
        if not body_type:
            return None
        key = body_type.strip()
        if key in self._body_type_cache:
            return self._body_type_cache[key]
        try:
            res = (
                self.supabase.table("body_types")
                .select("id")
                .eq("name", key)
                .limit(1)
                .execute()
            )
            if res.data:
                bid = res.data[0]["id"]
                self._body_type_cache[key] = bid
                return bid
        except Exception as exc:  # noqa: BLE001
            logger.debug("body_type_lookup_failed", name=key, error=str(exc))
        return None

    # ------------------------------------------------------------------
    # Import entry points
    # ------------------------------------------------------------------

    async def import_csv(self, file_content: bytes, source_name: str = "csv_import") -> ImportResult:
        """Import market data from CSV content."""
        result = ImportResult()

        try:
            text = file_content.decode('utf-8-sig')  # Handle BOM
        except UnicodeDecodeError:
            text = file_content.decode('shift_jis')  # Japanese encoding fallback

        reader = csv.DictReader(io.StringIO(text))

        # Normalize column names
        if reader.fieldnames:
            normalized_fields = {self._normalize_column(f): f for f in reader.fieldnames}
        else:
            result.errors.append({"row": 0, "field": "", "message": "No headers found"})
            return result

        # Check required columns
        missing = [c for c in REQUIRED_COLUMNS if c not in normalized_fields]
        if missing:
            result.errors.append({"row": 0, "field": ",".join(missing), "message": f"Missing required columns: {missing}"})
            return result

        rows_to_insert = []
        for i, row in enumerate(reader, start=2):  # 2 because row 1 is header
            result.total_rows += 1

            # Normalize row keys
            norm_row = {}
            for norm_key, orig_key in normalized_fields.items():
                norm_row[norm_key] = row.get(orig_key, "").strip()

            # Validate
            errors = self._validate_row(norm_row, i)
            if errors:
                result.error_count += 1
                result.errors.extend(errors)
                continue

            # Track auction metadata for reporting
            if norm_row.get("auction_date"):
                result.auction_dates.add(norm_row["auction_date"])
            if norm_row.get("auction_site"):
                result.auction_sites.add(norm_row["auction_site"])

            # Transform to vehicle record (resolves FKs)
            vehicle = self._transform_row(norm_row, source_name, i, result)
            if vehicle:
                rows_to_insert.append(vehicle)

        # Bulk insert
        if rows_to_insert:
            batch_size = 100
            for start in range(0, len(rows_to_insert), batch_size):
                batch = rows_to_insert[start:start + batch_size]
                try:
                    self.supabase.table("vehicles").insert(batch).execute()
                    result.imported_count += len(batch)
                except Exception as e:
                    result.error_count += len(batch)
                    result.errors.append({"row": start, "field": "", "message": f"Batch insert failed: {str(e)}"})

        logger.info("market_data_import_complete",
                     total=result.total_rows,
                     imported=result.imported_count,
                     errors=result.error_count,
                     created_manufacturers=result.created_manufacturers)

        return result

    async def import_excel(self, file_content: bytes, source_name: str = "excel_import") -> ImportResult:
        """Import market data from Excel content."""
        if not HAS_OPENPYXL:
            result = ImportResult()
            result.errors.append({"row": 0, "field": "", "message": "openpyxl not installed"})
            return result

        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
        ws = wb.active

        # Convert to list of dicts
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            result = ImportResult()
            result.errors.append({"row": 0, "field": "", "message": "Empty spreadsheet"})
            return result

        headers = [str(h).strip() if h else "" for h in rows[0]]

        # Convert to CSV-like format and reuse CSV import
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for row in rows[1:]:
            writer.writerow([str(cell) if cell is not None else "" for cell in row])

        return await self.import_csv(output.getvalue().encode('utf-8'), source_name)

    def _normalize_column(self, col_name: str) -> str:
        """Normalize a column name using aliases."""
        clean = col_name.strip().lower()
        return COLUMN_ALIASES.get(clean, COLUMN_ALIASES.get(col_name.strip(), clean))

    def _validate_row(self, row: dict, row_num: int) -> list[dict]:
        """Validate a data row. Returns list of error dicts."""
        errors = []

        # Required fields
        for field in REQUIRED_COLUMNS:
            if not row.get(field):
                errors.append({"row": row_num, "field": field, "message": f"Required field '{field}' is empty"})

        # Type validations
        if row.get("year"):
            try:
                year = int(row["year"])
                if year < 1990 or year > datetime.now().year + 1:
                    errors.append({"row": row_num, "field": "year", "message": f"Invalid year: {year}"})
            except ValueError:
                errors.append({"row": row_num, "field": "year", "message": f"Invalid year format: {row['year']}"})

        if row.get("mileage_km"):
            try:
                km = int(row["mileage_km"].replace(",", ""))
                if km < 0 or km > 2000000:
                    errors.append({"row": row_num, "field": "mileage_km", "message": f"Invalid mileage: {km}"})
            except ValueError:
                errors.append({"row": row_num, "field": "mileage_km", "message": f"Invalid mileage format"})

        if row.get("price_yen"):
            try:
                price = int(row["price_yen"].replace(",", "").replace("¥", ""))
                if price < 0 or price > 100000000:
                    errors.append({"row": row_num, "field": "price_yen", "message": f"Invalid price: {price}"})
            except ValueError:
                errors.append({"row": row_num, "field": "price_yen", "message": f"Invalid price format"})

        return errors

    def _transform_row(
        self,
        row: dict,
        source_name: str,
        row_num: int,
        result: ImportResult,
    ) -> Optional[dict]:
        """Transform a validated row into a vehicle record."""
        try:
            price_str = row.get("price_yen", "0").replace(",", "").replace("¥", "")
            mileage_str = row.get("mileage_km", "0").replace(",", "")

            # Resolve maker -> manufacturer_id (REQUIRED)
            manufacturer_id = self._resolve_manufacturer_id(row.get("maker", ""), result)
            if not manufacturer_id:
                result.error_count += 1
                result.errors.append({
                    "row": row_num,
                    "field": "maker",
                    "message": f"Could not resolve manufacturer: '{row.get('maker', '')}'",
                })
                return None

            category_id = self._get_default_category_id()
            if not category_id:
                result.error_count += 1
                result.errors.append({
                    "row": row_num,
                    "field": "category",
                    "message": "No default vehicle category available",
                })
                return None

            body_type_id = self._resolve_body_type_id(row.get("body_type", ""))

            # auction_site overrides source_name for source_site, when provided.
            # This is an explicit mapping: vehicles table has no dedicated
            # auction_site column; source_site is re-used.
            site = row.get("auction_site") or source_name

            # auction_date maps to scraped_at (see module docstring).
            auction_date = row.get("auction_date", "")

            record = {
                "source_site": site,
                "source_id": (
                    f"{site}_{auction_date}_{row.get('maker', '')}"
                    f"_{row.get('model', '')}_{row.get('year', '')}"
                    f"_{mileage_str}"
                ),
                "category_id": category_id,
                "manufacturer_id": manufacturer_id,
                "body_type_id": body_type_id,
                "model_name": row.get("model", ""),
                "model_year": int(row.get("year", 0)),
                "mileage_km": int(mileage_str),
                "price_yen": int(price_str),
                "price_tax_included": False,
                "tonnage": float(row["tonnage"]) if row.get("tonnage") else None,
                "transmission": row.get("transmission") or None,
                "fuel_type": row.get("fuel_type") or None,
                "location_prefecture": row.get("location") or None,
                "scraped_at": auction_date or datetime.now().isoformat(),
                "is_active": True,
            }
            return record
        except (ValueError, KeyError) as e:
            logger.warning("row_transform_failed", error=str(e), row=row)
            result.error_count += 1
            result.errors.append({
                "row": row_num,
                "field": "",
                "message": f"Row transform failed: {e}",
            })
            return None
