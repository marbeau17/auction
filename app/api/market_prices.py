"""Market prices API router.

Provides CRUD operations, search, statistics, CSV import/export for
commercial vehicle market price data.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, StreamingResponse
from supabase import Client

from app.dependencies import get_current_user, get_supabase_client, require_role
from app.main import templates
from app.models.common import PaginatedResponse, PaginationMeta, SuccessResponse
from app.models.vehicle import VehicleCreate, VehicleResponse, VehicleSearchParams

router = APIRouter(prefix="/api/v1/market-prices", tags=["market_prices"])

# ---------------------------------------------------------------------------
# Table name constant
# ---------------------------------------------------------------------------

TABLE = "vehicles"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_htmx(request: Request) -> bool:
    """Return ``True`` when the request originates from htmx."""
    return request.headers.get("HX-Request", "").lower() == "true"


def _apply_search_filters(
    query: Any,
    params: VehicleSearchParams,
) -> Any:
    """Apply common search filters to a Supabase query builder."""
    if params.maker:
        query = query.ilike("maker", f"%{params.maker}%")
    if params.model_name:
        query = query.ilike("model_name", f"%{params.model_name}%")
    if params.year_from is not None:
        query = query.gte("model_year", params.year_from)
    if params.year_to is not None:
        query = query.lte("model_year", params.year_to)
    if params.mileage_from is not None:
        query = query.gte("mileage_km", params.mileage_from)
    if params.mileage_to is not None:
        query = query.lte("mileage_km", params.mileage_to)
    if params.body_type:
        query = query.ilike("body_type", f"%{params.body_type}%")
    if params.price_from is not None:
        query = query.gte("price_yen", params.price_from)
    if params.price_to is not None:
        query = query.lte("price_yen", params.price_to)
    return query


def _compute_stats(prices: list[int]) -> dict[str, float | int]:
    """Compute summary statistics for a list of prices."""
    if not prices:
        return {"count": 0, "avg": 0, "median": 0, "min": 0, "max": 0, "std": 0.0}
    return {
        "count": len(prices),
        "avg": round(statistics.mean(prices)),
        "median": round(statistics.median(prices)),
        "min": min(prices),
        "max": max(prices),
        "std": round(statistics.stdev(prices), 2) if len(prices) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# 1. GET / — Search & list market price data
# ---------------------------------------------------------------------------


@router.get("/")
async def list_market_prices(
    request: Request,
    maker: Optional[str] = Query(default=None, description="Filter by maker name"),
    model: Optional[str] = Query(default=None, alias="model", description="Filter by model name"),
    year_from: Optional[int] = Query(default=None, ge=1970, description="Minimum model year"),
    year_to: Optional[int] = Query(default=None, le=2100, description="Maximum model year"),
    mileage_from: Optional[int] = Query(default=None, ge=0, description="Minimum mileage (km)"),
    mileage_to: Optional[int] = Query(default=None, ge=0, description="Maximum mileage (km)"),
    body_type: Optional[str] = Query(default=None, description="Filter by body type"),
    price_from: Optional[int] = Query(default=None, ge=0, description="Minimum price (yen)"),
    price_to: Optional[int] = Query(default=None, ge=0, description="Maximum price (yen)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Results per page"),
    sort: str = Query(default="scraped_at", description="Sort field"),
    order: str = Query(default="desc", description="Sort order (asc|desc)"),
    supabase: Client = Depends(get_supabase_client),
) -> Any:
    """Search and list market price data with pagination and stats summary.

    When the ``HX-Request`` header is present the endpoint returns an HTML
    table fragment instead of JSON.
    """
    params = VehicleSearchParams(
        maker=maker,
        model_name=model,
        year_from=year_from,
        year_to=year_to,
        mileage_from=mileage_from,
        mileage_to=mileage_to,
        body_type=body_type,
        price_from=price_from,
        price_to=price_to,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )

    # --- count query -------------------------------------------------------
    count_query = supabase.table(TABLE).select("id", count="exact").eq("is_active", True)
    count_query = _apply_search_filters(count_query, params)
    count_result = count_query.execute()
    total_count: int = count_result.count or 0

    # --- data query --------------------------------------------------------
    offset = (params.page - 1) * params.per_page
    data_query = (
        supabase.table(TABLE)
        .select("*")
        .eq("is_active", True)
        .order(params.sort, desc=(params.order == "desc"))
        .range(offset, offset + params.per_page - 1)
    )
    data_query = _apply_search_filters(data_query, params)
    data_result = data_query.execute()
    vehicles: list[dict[str, Any]] = data_result.data or []

    # --- stats (from all matching, not just current page) ------------------
    stats_query = (
        supabase.table(TABLE)
        .select("price_yen")
        .eq("is_active", True)
        .not_.is_("price_yen", "null")
    )
    stats_query = _apply_search_filters(stats_query, params)
    stats_result = stats_query.execute()
    prices = [row["price_yen"] for row in (stats_result.data or []) if row.get("price_yen") is not None]
    summary = _compute_stats(prices)

    total_pages = math.ceil(total_count / params.per_page) if total_count else 0

    # --- HTMX response ----------------------------------------------------
    if _is_htmx(request):
        return templates.TemplateResponse(
            "partials/market_prices_table.html",
            {
                "request": request,
                "vehicles": vehicles,
                "meta": {
                    "total_count": total_count,
                    "page": params.page,
                    "per_page": params.per_page,
                    "total_pages": total_pages,
                },
                "stats": summary,
            },
        )

    # --- JSON response -----------------------------------------------------
    pagination = PaginationMeta(
        total_count=total_count,
        page=params.page,
        per_page=params.per_page,
        total_pages=total_pages,
    )

    return {
        "status": "success",
        "data": vehicles,
        "meta": pagination.model_dump(),
        "stats": summary,
    }


# ---------------------------------------------------------------------------
# 2. GET /statistics — Market statistics
# ---------------------------------------------------------------------------


@router.get("/statistics")
async def get_statistics(
    maker: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    year: Optional[int] = Query(default=None, ge=1970, le=2100),
    body_type: Optional[str] = Query(default=None),
    supabase: Client = Depends(get_supabase_client),
) -> SuccessResponse:
    """Return statistical summary for matching vehicles."""
    params = VehicleSearchParams(
        maker=maker,
        model_name=model,
        year_from=year,
        year_to=year,
    )
    if body_type:
        params.body_type = body_type

    query = (
        supabase.table(TABLE)
        .select("price_yen")
        .eq("is_active", True)
        .not_.is_("price_yen", "null")
    )
    query = _apply_search_filters(query, params)
    result = query.execute()

    prices = [row["price_yen"] for row in (result.data or []) if row.get("price_yen") is not None]
    summary = _compute_stats(prices)

    return SuccessResponse(data=summary)


# ---------------------------------------------------------------------------
# 3. GET /export — CSV export
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "id",
    "source_site",
    "source_url",
    "source_id",
    "maker",
    "model_name",
    "body_type",
    "model_year",
    "mileage_km",
    "price_yen",
    "price_tax_included",
    "tonnage",
    "transmission",
    "fuel_type",
    "location_prefecture",
    "listing_status",
    "scraped_at",
    "created_at",
    "updated_at",
]


@router.get("/export")
async def export_csv(
    maker: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    year_from: Optional[int] = Query(default=None, ge=1970),
    year_to: Optional[int] = Query(default=None, le=2100),
    mileage_from: Optional[int] = Query(default=None, ge=0),
    mileage_to: Optional[int] = Query(default=None, ge=0),
    body_type: Optional[str] = Query(default=None),
    price_from: Optional[int] = Query(default=None, ge=0),
    price_to: Optional[int] = Query(default=None, ge=0),
    sort: str = Query(default="scraped_at"),
    order: str = Query(default="desc"),
    supabase: Client = Depends(get_supabase_client),
) -> StreamingResponse:
    """Export matching vehicles as a CSV file."""
    params = VehicleSearchParams(
        maker=maker,
        model_name=model,
        year_from=year_from,
        year_to=year_to,
        mileage_from=mileage_from,
        mileage_to=mileage_to,
        body_type=body_type,
        price_from=price_from,
        price_to=price_to,
        sort=sort,
        order=order,
    )

    query = (
        supabase.table(TABLE)
        .select("*")
        .eq("is_active", True)
        .order(params.sort, desc=(params.order == "desc"))
    )
    query = _apply_search_filters(query, params)
    result = query.execute()
    vehicles: list[dict[str, Any]] = result.data or []

    def _generate() -> Any:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for vehicle in vehicles:
            writer.writerow(vehicle)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"market_prices_{timestamp}.csv"

    return StreamingResponse(
        _generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# 4. POST /import — CSV import (legacy, column-exact format)
# ---------------------------------------------------------------------------

_REQUIRED_IMPORT_FIELDS = {
    "source_site",
    "source_url",
    "source_id",
    "maker",
    "model_name",
    "body_type",
    "model_year",
    "mileage_km",
    "price_tax_included",
    "listing_status",
    "scraped_at",
}


@router.post("/import")
async def import_csv(
    file: UploadFile = File(..., description="CSV file to import"),
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Import vehicle records from a CSV file.

    The CSV must include at least the required fields. Rows are upserted by
    ``source_id`` so re-importing is safe.
    """
    if file.content_type and file.content_type not in (
        "text/csv",
        "application/octet-stream",
        "application/vnd.ms-excel",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported content type: {file.content_type}. Expected text/csv.",
        )

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("shift_jis")

    reader = csv.DictReader(io.StringIO(text))

    success_count = 0
    error_count = 0
    errors: list[dict[str, Any]] = []

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        # --- validate required fields -------------------------------------
        missing = _REQUIRED_IMPORT_FIELDS - {k for k, v in row.items() if v}
        if missing:
            error_count += 1
            errors.append({"row": row_num, "message": f"Missing required fields: {', '.join(sorted(missing))}"})
            continue

        # --- coerce types --------------------------------------------------
        try:
            record: dict[str, Any] = {
                "source_site": row["source_site"].strip(),
                "source_url": row["source_url"].strip(),
                "source_id": row["source_id"].strip(),
                "maker": row["maker"].strip(),
                "model_name": row["model_name"].strip(),
                "body_type": row["body_type"].strip(),
                "model_year": int(row["model_year"]),
                "mileage_km": int(row["mileage_km"]),
                "price_yen": int(row["price_yen"]) if row.get("price_yen") else None,
                "price_tax_included": row["price_tax_included"].strip().lower() in ("true", "1", "yes"),
                "tonnage": float(row["tonnage"]) if row.get("tonnage") else None,
                "transmission": row.get("transmission", "").strip() or None,
                "fuel_type": row.get("fuel_type", "").strip() or None,
                "location_prefecture": row.get("location_prefecture", "").strip() or None,
                "listing_status": row["listing_status"].strip(),
                "scraped_at": row["scraped_at"].strip(),
                "is_active": True,
            }
        except (ValueError, KeyError) as exc:
            error_count += 1
            errors.append({"row": row_num, "message": f"Data conversion error: {exc}"})
            continue

        # --- upsert -------------------------------------------------------
        try:
            supabase.table(TABLE).upsert(record, on_conflict="source_id").execute()
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            errors.append({"row": row_num, "message": f"Database error: {exc}"})

    return SuccessResponse(
        data={
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors,
        }
    )


# ---------------------------------------------------------------------------
# 4b. POST /import/csv — Smart CSV import (Japanese alias support)
# ---------------------------------------------------------------------------


@router.post("/import/csv")
async def import_csv_smart(
    request: Request,
    file: UploadFile = File(..., description="CSV file to import (supports Japanese column names)"),
    source_name: str = Query(default="csv_import", description="Source name for imported records"),
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> Any:
    """Import auction market data from a CSV file.

    Supports both English and Japanese column names via alias mapping.
    Required columns: maker, model, year, mileage_km, price_yen, auction_date.
    Returns an HTML fragment when called via HTMX; otherwise JSON.
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

    from app.core.market_data_importer import MarketDataImporter

    content = await file.read()
    importer = MarketDataImporter(supabase)
    result = await importer.import_csv(content, source_name=source_name)

    if _is_htmx(request):
        return templates.TemplateResponse(
            "partials/import_result.html",
            {"request": request, "result": result.to_dict(), "source_name": source_name},
        )

    return SuccessResponse(data=result.to_dict())


# ---------------------------------------------------------------------------
# 4c. POST /import/excel — Excel import
# ---------------------------------------------------------------------------


@router.post("/import/excel")
async def import_excel(
    request: Request,
    file: UploadFile = File(..., description="Excel (.xlsx) file to import"),
    source_name: str = Query(default="excel_import", description="Source name for imported records"),
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> Any:
    """Import auction market data from an Excel (.xlsx) file.

    Supports both English and Japanese column names via alias mapping.
    Required columns: maker, model, year, mileage_km, price_yen, auction_date.
    Returns an HTML fragment when called via HTMX; otherwise JSON.
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

    from app.core.market_data_importer import MarketDataImporter

    content = await file.read()
    importer = MarketDataImporter(supabase)
    result = await importer.import_excel(content, source_name=source_name)

    if _is_htmx(request):
        return templates.TemplateResponse(
            "partials/import_result.html",
            {"request": request, "result": result.to_dict(), "source_name": source_name},
        )

    return SuccessResponse(data=result.to_dict())


# ---------------------------------------------------------------------------
# 4d. GET /import/template — Download CSV import template
# ---------------------------------------------------------------------------

_TEMPLATE_COLUMNS = [
    "maker", "model", "year", "mileage_km", "price_yen", "auction_date",
    "auction_site", "body_type", "tonnage", "transmission", "fuel_type", "location",
]

_TEMPLATE_EXAMPLE = {
    "maker": "いすゞ",
    "model": "エルフ",
    "year": "2020",
    "mileage_km": "85000",
    "price_yen": "3500000",
    "auction_date": "2025-12-01",
    "auction_site": "USS東京",
    "body_type": "平ボディ",
    "tonnage": "2.0",
    "transmission": "AT",
    "fuel_type": "軽油",
    "location": "東京都",
}


@router.get("/import/template")
async def download_import_template() -> StreamingResponse:
    """Download a CSV template file for market data import.

    The template includes all supported columns with a sample row.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_TEMPLATE_COLUMNS)
    writer.writeheader()
    writer.writerow(_TEMPLATE_EXAMPLE)

    content = buf.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": 'attachment; filename="market_data_import_template.csv"'},
    )


# ---------------------------------------------------------------------------
# 5. GET /{id} — Single vehicle detail
# ---------------------------------------------------------------------------


@router.get("/{vehicle_id}")
async def get_vehicle(
    vehicle_id: UUID,
    request: Request,
    supabase: Client = Depends(get_supabase_client),
) -> Any:
    """Return a single vehicle record by ID."""
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("id", str(vehicle_id))
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )

    if result.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle {vehicle_id} not found",
        )

    if _is_htmx(request):
        return templates.TemplateResponse(
            "partials/market_price_detail.html",
            {"request": request, "vehicle": result.data},
        )

    return SuccessResponse(data=result.data)


# ---------------------------------------------------------------------------
# 6. POST / — Create vehicle record (admin only)
# ---------------------------------------------------------------------------


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    payload: VehicleCreate,
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Create a new vehicle record manually."""
    data = payload.model_dump(mode="json")
    data["is_active"] = True

    result = supabase.table(TABLE).insert(data).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create vehicle record",
        )

    return SuccessResponse(data=result.data[0])


# ---------------------------------------------------------------------------
# 7. PUT /{id} — Update vehicle record (admin only)
# ---------------------------------------------------------------------------


@router.put("/{vehicle_id}")
async def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleCreate,
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Update an existing vehicle record."""
    # Verify record exists
    existing = (
        supabase.table(TABLE)
        .select("id")
        .eq("id", str(vehicle_id))
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )
    if existing.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle {vehicle_id} not found",
        )

    data = payload.model_dump(mode="json")
    result = (
        supabase.table(TABLE)
        .update(data)
        .eq("id", str(vehicle_id))
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update vehicle record",
        )

    return SuccessResponse(data=result.data[0])


# ---------------------------------------------------------------------------
# 8. DELETE /{id} — Soft delete (admin only)
# ---------------------------------------------------------------------------


@router.delete("/{vehicle_id}", status_code=status.HTTP_200_OK)
async def delete_vehicle(
    vehicle_id: UUID,
    supabase: Client = Depends(get_supabase_client),
    current_user: dict[str, Any] = Depends(require_role(["admin", "service_role"])),
) -> SuccessResponse:
    """Soft-delete a vehicle record by setting ``is_active`` to ``False``."""
    existing = (
        supabase.table(TABLE)
        .select("id")
        .eq("id", str(vehicle_id))
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )
    if existing.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle {vehicle_id} not found",
        )

    supabase.table(TABLE).update({"is_active": False}).eq("id", str(vehicle_id)).execute()

    return SuccessResponse(data={"id": str(vehicle_id), "deleted": True})
