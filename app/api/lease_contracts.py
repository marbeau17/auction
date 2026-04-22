"""Lease contracts API router.

Provides CSV/Excel import endpoints for existing car lease contracts
and a template download endpoint.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from supabase import Client

from app.core.http import content_disposition
from app.dependencies import get_current_user, get_supabase_client, require_role
from app.models.common import SuccessResponse

router = APIRouter(prefix="/api/v1/lease-contracts", tags=["lease_contracts"])


# ---------------------------------------------------------------------------
# 1. POST /import/csv -- Import lease contracts from CSV
# ---------------------------------------------------------------------------


@router.post("/import/csv")
async def import_lease_contracts_csv(
    file: UploadFile = File(..., description="CSV file of lease contracts"),
    fund_id: str = Query(..., description="Target fund UUID to associate contracts with"),
    source_name: str = Query(
        default="csv_import",
        description="Source label for imported records",
    ),
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Import existing lease contracts from a CSV file.

    Supports both English and Japanese column names via alias mapping.

    Required columns: contract_number, lessee_company_name, contract_start_date,
    contract_end_date, monthly_lease_amount, vehicle_description.

    When ``acquisition_price`` is provided, a corresponding secured_asset_block
    (SAB) record is created automatically.
    """
    if file.content_type and file.content_type not in (
        "text/csv",
        "application/octet-stream",
        "application/vnd.ms-excel",
        "text/plain",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported content type: {file.content_type}. Expected text/csv.",
        )

    # Validate fund_id exists
    try:
        fund_check = (
            supabase.table("funds")
            .select("id")
            .eq("id", fund_id)
            .maybe_single()
            .execute()
        )
        if not fund_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fund {fund_id} not found",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid fund_id: {str(e)}",
        )

    from app.core.lease_contract_importer import LeaseContractImporter

    content = await file.read()
    importer = LeaseContractImporter(supabase)
    result = await importer.import_csv(content, fund_id=fund_id, source_name=source_name)

    return SuccessResponse(data=result.to_dict())


# ---------------------------------------------------------------------------
# 2. POST /import/excel -- Import lease contracts from Excel
# ---------------------------------------------------------------------------


@router.post("/import/excel")
async def import_lease_contracts_excel(
    file: UploadFile = File(..., description="Excel (.xlsx) file of lease contracts"),
    fund_id: str = Query(..., description="Target fund UUID to associate contracts with"),
    source_name: str = Query(
        default="excel_import",
        description="Source label for imported records",
    ),
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Import existing lease contracts from an Excel (.xlsx) file.

    Supports both English and Japanese column names via alias mapping.

    Required columns: contract_number, lessee_company_name, contract_start_date,
    contract_end_date, monthly_lease_amount, vehicle_description.

    When ``acquisition_price`` is provided, a corresponding secured_asset_block
    (SAB) record is created automatically.
    """
    if file.content_type and file.content_type not in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported content type: {file.content_type}. Expected Excel (.xlsx).",
        )

    # Validate fund_id exists
    try:
        fund_check = (
            supabase.table("funds")
            .select("id")
            .eq("id", fund_id)
            .maybe_single()
            .execute()
        )
        if not fund_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fund {fund_id} not found",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid fund_id: {str(e)}",
        )

    from app.core.lease_contract_importer import LeaseContractImporter

    content = await file.read()
    importer = LeaseContractImporter(supabase)
    result = await importer.import_excel(content, fund_id=fund_id, source_name=source_name)

    return SuccessResponse(data=result.to_dict())


# ---------------------------------------------------------------------------
# 3. GET /import/template -- Download CSV import template
# ---------------------------------------------------------------------------


from app.core.lease_contract_importer import TEMPLATE_COLUMNS, TEMPLATE_EXAMPLE


@router.get("/import/template")
async def download_lease_contract_template() -> StreamingResponse:
    """Download a CSV template file for lease contract import.

    The template includes all supported columns (required + optional) with a
    sample row demonstrating expected formats.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TEMPLATE_COLUMNS)
    writer.writeheader()
    writer.writerow(TEMPLATE_EXAMPLE)

    content = buf.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": content_disposition(
                "lease_contract_import_template.csv"
            ),
        },
    )
