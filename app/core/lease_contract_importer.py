"""Importer for existing car lease contract data into CVLPOS.

Imports active lease contracts from CSV/Excel into the lease_contracts table
and optionally creates corresponding secured_asset_blocks (SAB) entries.
"""

from __future__ import annotations

import csv
import io
import math
import uuid
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
    """Result of a lease contract import operation."""

    def __init__(self):
        self.total_rows = 0
        self.imported_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.sab_created_count = 0
        self.errors: list[dict] = []  # [{row: int, field: str, message: str}]

    def to_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "sab_created_count": self.sab_created_count,
            "errors": self.errors[:50],  # Limit error list
        }


REQUIRED_COLUMNS = [
    'contract_number', 'lessee_company_name', 'contract_start_date',
    'contract_end_date', 'monthly_lease_amount', 'vehicle_description',
]

OPTIONAL_COLUMNS = [
    'lessee_contact_person', 'lessee_contact_email', 'lessee_contact_phone',
    'tax_rate', 'residual_value', 'payment_day', 'vehicle_maker',
    'vehicle_model', 'vehicle_year', 'vehicle_mileage', 'acquisition_price',
]

COLUMN_ALIASES = {
    # Japanese aliases
    '契約番号': 'contract_number',
    'リース先': 'lessee_company_name',
    '開始日': 'contract_start_date',
    '終了日': 'contract_end_date',
    '月額リース料': 'monthly_lease_amount',
    '車両情報': 'vehicle_description',
    '担当者': 'lessee_contact_person',
    'メール': 'lessee_contact_email',
    '電話': 'lessee_contact_phone',
    '税率': 'tax_rate',
    '残価': 'residual_value',
    '支払日': 'payment_day',
    'メーカー': 'vehicle_maker',
    '車種': 'vehicle_model',
    '年式': 'vehicle_year',
    '走行距離': 'vehicle_mileage',
    '取得価格': 'acquisition_price',
    # English aliases (passthrough)
    'contract_number': 'contract_number',
    'lessee_company_name': 'lessee_company_name',
    'contract_start_date': 'contract_start_date',
    'contract_end_date': 'contract_end_date',
    'monthly_lease_amount': 'monthly_lease_amount',
    'vehicle_description': 'vehicle_description',
    'lessee_contact_person': 'lessee_contact_person',
    'lessee_contact_email': 'lessee_contact_email',
    'lessee_contact_phone': 'lessee_contact_phone',
    'tax_rate': 'tax_rate',
    'residual_value': 'residual_value',
    'payment_day': 'payment_day',
    'vehicle_maker': 'vehicle_maker',
    'vehicle_model': 'vehicle_model',
    'vehicle_year': 'vehicle_year',
    'vehicle_mileage': 'vehicle_mileage',
    'acquisition_price': 'acquisition_price',
}

# Template columns and example row for CSV template download
TEMPLATE_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

TEMPLATE_EXAMPLE = {
    'contract_number': 'LC-2026-0001',
    'lessee_company_name': '東京運輸株式会社',
    'contract_start_date': '2025-04-01',
    'contract_end_date': '2028-03-31',
    'monthly_lease_amount': '350000',
    'vehicle_description': 'いすゞ エルフ 2t 平ボディ',
    'lessee_contact_person': '田中太郎',
    'lessee_contact_email': 'tanaka@example.com',
    'lessee_contact_phone': '03-1234-5678',
    'tax_rate': '0.10',
    'residual_value': '500000',
    'payment_day': '25',
    'vehicle_maker': 'いすゞ',
    'vehicle_model': 'エルフ',
    'vehicle_year': '2022',
    'vehicle_mileage': '45000',
    'acquisition_price': '4500000',
}


class LeaseContractImporter:
    """Imports existing lease contracts from CSV or Excel files."""

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def import_csv(
        self,
        file_content: bytes,
        fund_id: str,
        source_name: str = "csv_import",
    ) -> ImportResult:
        """Import lease contracts from CSV content."""
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
            result.errors.append({
                "row": 0,
                "field": ",".join(missing),
                "message": f"Missing required columns: {missing}",
            })
            return result

        contracts_to_insert = []
        sabs_to_insert = []

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

            # Check for duplicate contract_number
            contract_number = norm_row.get("contract_number", "")
            try:
                existing = (
                    self.supabase.table("lease_contracts")
                    .select("id")
                    .eq("contract_number", contract_number)
                    .maybe_single()
                    .execute()
                )
                if existing.data:
                    result.skipped_count += 1
                    result.errors.append({
                        "row": i,
                        "field": "contract_number",
                        "message": f"Contract '{contract_number}' already exists, skipped",
                    })
                    continue
            except Exception:
                pass  # If check fails, proceed with insert (DB constraint will catch dupes)

            # Transform to lease_contract record
            contract = self._transform_to_lease_contract(norm_row, fund_id)
            if contract:
                contract_id = contract["id"]
                contracts_to_insert.append(contract)

                # Optionally create SAB entry
                sab = self._transform_to_sab(norm_row, fund_id, contract_id)
                if sab:
                    sabs_to_insert.append(sab)

        # Bulk insert lease contracts
        if contracts_to_insert:
            batch_size = 100
            for start in range(0, len(contracts_to_insert), batch_size):
                batch = contracts_to_insert[start:start + batch_size]
                try:
                    self.supabase.table("lease_contracts").insert(batch).execute()
                    result.imported_count += len(batch)
                except Exception as e:
                    result.error_count += len(batch)
                    result.errors.append({
                        "row": start,
                        "field": "",
                        "message": f"Batch insert failed: {str(e)}",
                    })

        # Bulk insert SABs
        if sabs_to_insert:
            batch_size = 100
            for start in range(0, len(sabs_to_insert), batch_size):
                batch = sabs_to_insert[start:start + batch_size]
                try:
                    self.supabase.table("secured_asset_blocks").insert(batch).execute()
                    result.sab_created_count += len(batch)
                except Exception as e:
                    result.errors.append({
                        "row": start,
                        "field": "",
                        "message": f"SAB batch insert failed: {str(e)}",
                    })

        logger.info(
            "lease_contract_import_complete",
            source=source_name,
            fund_id=fund_id,
            total=result.total_rows,
            imported=result.imported_count,
            skipped=result.skipped_count,
            sab_created=result.sab_created_count,
            errors=result.error_count,
        )

        return result

    async def import_excel(
        self,
        file_content: bytes,
        fund_id: str,
        source_name: str = "excel_import",
    ) -> ImportResult:
        """Import lease contracts from Excel content."""
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

        return await self.import_csv(output.getvalue().encode('utf-8'), fund_id, source_name)

    def _normalize_column(self, col_name: str) -> str:
        """Normalize a column name using aliases."""
        clean = col_name.strip().lower()
        return COLUMN_ALIASES.get(clean, COLUMN_ALIASES.get(col_name.strip(), clean))

    def _validate_row(self, row: dict, row_num: int) -> list[dict]:
        """Validate a contract data row. Returns list of error dicts."""
        errors = []

        # Required fields must be non-empty
        for field in REQUIRED_COLUMNS:
            if not row.get(field):
                errors.append({
                    "row": row_num,
                    "field": field,
                    "message": f"Required field '{field}' is empty",
                })

        # Date validations
        for date_field in ('contract_start_date', 'contract_end_date'):
            val = row.get(date_field, "")
            if val:
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    errors.append({
                        "row": row_num,
                        "field": date_field,
                        "message": f"Invalid date format '{val}', expected YYYY-MM-DD",
                    })

        # End date must be after start date
        start_str = row.get("contract_start_date", "")
        end_str = row.get("contract_end_date", "")
        if start_str and end_str:
            try:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d")
                end_dt = datetime.strptime(end_str, "%Y-%m-%d")
                if end_dt <= start_dt:
                    errors.append({
                        "row": row_num,
                        "field": "contract_end_date",
                        "message": "contract_end_date must be after contract_start_date",
                    })
            except ValueError:
                pass  # Already caught above

        # Monthly lease amount must be a positive integer
        amount_str = row.get("monthly_lease_amount", "")
        if amount_str:
            try:
                amount = int(amount_str.replace(",", "").replace("¥", ""))
                if amount <= 0:
                    errors.append({
                        "row": row_num,
                        "field": "monthly_lease_amount",
                        "message": f"monthly_lease_amount must be positive, got {amount}",
                    })
            except ValueError:
                errors.append({
                    "row": row_num,
                    "field": "monthly_lease_amount",
                    "message": f"Invalid amount format: {amount_str}",
                })

        # Optional: tax_rate
        tax_str = row.get("tax_rate", "")
        if tax_str:
            try:
                tax = float(tax_str)
                if tax < 0 or tax > 1:
                    errors.append({
                        "row": row_num,
                        "field": "tax_rate",
                        "message": f"tax_rate must be between 0 and 1, got {tax}",
                    })
            except ValueError:
                errors.append({
                    "row": row_num,
                    "field": "tax_rate",
                    "message": f"Invalid tax_rate format: {tax_str}",
                })

        # Optional: residual_value
        rv_str = row.get("residual_value", "")
        if rv_str:
            try:
                rv = int(rv_str.replace(",", "").replace("¥", ""))
                if rv < 0:
                    errors.append({
                        "row": row_num,
                        "field": "residual_value",
                        "message": f"residual_value must be non-negative, got {rv}",
                    })
            except ValueError:
                errors.append({
                    "row": row_num,
                    "field": "residual_value",
                    "message": f"Invalid residual_value format: {rv_str}",
                })

        # Optional: payment_day
        pd_str = row.get("payment_day", "")
        if pd_str:
            try:
                pd_val = int(pd_str)
                if pd_val < 1 or pd_val > 31:
                    errors.append({
                        "row": row_num,
                        "field": "payment_day",
                        "message": f"payment_day must be between 1 and 31, got {pd_val}",
                    })
            except ValueError:
                errors.append({
                    "row": row_num,
                    "field": "payment_day",
                    "message": f"Invalid payment_day format: {pd_str}",
                })

        # Optional: acquisition_price
        ap_str = row.get("acquisition_price", "")
        if ap_str:
            try:
                ap = int(ap_str.replace(",", "").replace("¥", ""))
                if ap <= 0:
                    errors.append({
                        "row": row_num,
                        "field": "acquisition_price",
                        "message": f"acquisition_price must be positive, got {ap}",
                    })
            except ValueError:
                errors.append({
                    "row": row_num,
                    "field": "acquisition_price",
                    "message": f"Invalid acquisition_price format: {ap_str}",
                })

        # Optional: vehicle_year
        vy_str = row.get("vehicle_year", "")
        if vy_str:
            try:
                vy = int(vy_str)
                if vy < 1990 or vy > datetime.now().year + 1:
                    errors.append({
                        "row": row_num,
                        "field": "vehicle_year",
                        "message": f"Invalid vehicle_year: {vy}",
                    })
            except ValueError:
                errors.append({
                    "row": row_num,
                    "field": "vehicle_year",
                    "message": f"Invalid vehicle_year format: {vy_str}",
                })

        return errors

    def _transform_to_lease_contract(self, row: dict, fund_id: str) -> Optional[dict]:
        """Transform a validated row into a lease_contracts table record."""
        try:
            start_date = datetime.strptime(row["contract_start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(row["contract_end_date"], "%Y-%m-%d").date()

            # Calculate lease term in months
            lease_term_months = (
                (end_date.year - start_date.year) * 12
                + (end_date.month - start_date.month)
            )
            if lease_term_months <= 0:
                lease_term_months = 1

            monthly_amount = int(
                row["monthly_lease_amount"].replace(",", "").replace("¥", "")
            )

            tax_rate = float(row["tax_rate"]) if row.get("tax_rate") else 0.10
            # Round to a cent before ceiling so 350_000 * 1.10 doesn't drift to 385_000.0000000001.
            monthly_amount_tax_incl = math.ceil(round(monthly_amount * (1 + tax_rate), 2))

            residual_value = (
                int(row["residual_value"].replace(",", "").replace("¥", ""))
                if row.get("residual_value")
                else 0
            )
            payment_day = int(row["payment_day"]) if row.get("payment_day") else 25

            contract_id = str(uuid.uuid4())

            return {
                "id": contract_id,
                "fund_id": fund_id,
                "contract_number": row["contract_number"],
                "lessee_company_name": row["lessee_company_name"],
                "lessee_contact_person": row.get("lessee_contact_person") or None,
                "lessee_contact_email": row.get("lessee_contact_email") or None,
                "lessee_contact_phone": row.get("lessee_contact_phone") or None,
                "contract_start_date": start_date.isoformat(),
                "contract_end_date": end_date.isoformat(),
                "lease_term_months": lease_term_months,
                "monthly_lease_amount": monthly_amount,
                "monthly_lease_amount_tax_incl": monthly_amount_tax_incl,
                "tax_rate": tax_rate,
                "residual_value": residual_value,
                "payment_day": payment_day,
                "status": "active",
            }
        except (ValueError, KeyError) as e:
            logger.warning("lease_contract_transform_failed", error=str(e), row=row)
            return None

    def _transform_to_sab(
        self,
        row: dict,
        fund_id: str,
        lease_contract_id: str,
    ) -> Optional[dict]:
        """If vehicle info is present, create a secured_asset_block entry.

        Requires at least acquisition_price and vehicle_description to create
        a SAB record. Returns None if insufficient data.
        """
        acquisition_price_str = row.get("acquisition_price", "")
        vehicle_description = row.get("vehicle_description", "")

        if not acquisition_price_str or not vehicle_description:
            return None

        try:
            acquisition_price = int(
                acquisition_price_str.replace(",", "").replace("¥", "")
            )
            if acquisition_price <= 0:
                return None

            # Build description from component fields if available
            parts = []
            if row.get("vehicle_maker"):
                parts.append(row["vehicle_maker"])
            if row.get("vehicle_model"):
                parts.append(row["vehicle_model"])
            if row.get("vehicle_year"):
                parts.append(f"{row['vehicle_year']}年式")
            full_description = " ".join(parts) if parts else vehicle_description

            contract_number = row.get("contract_number", "")
            sab_number = f"SAB-{contract_number}"

            start_date_str = row.get("contract_start_date", "")
            acquisition_date = start_date_str if start_date_str else datetime.now().date().isoformat()

            return {
                "fund_id": fund_id,
                "lease_contract_id": lease_contract_id,
                "sab_number": sab_number,
                "vehicle_description": full_description,
                "acquisition_price": acquisition_price,
                "acquisition_date": acquisition_date,
                "status": "leased",
            }
        except (ValueError, KeyError) as e:
            logger.warning("sab_transform_failed", error=str(e), row=row)
            return None
