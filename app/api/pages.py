from __future__ import annotations

import math
import statistics
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings

router = APIRouter(tags=["pages"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _render(request: Request, template: str, context: dict | None = None):
    from app.main import templates

    ctx = context or {}
    return templates.TemplateResponse(request, template, ctx)


async def _get_optional_user(request: Request) -> dict[str, Any] | None:
    """Try to get current user from JWT cookie. Returns None on failure."""
    settings = get_settings()
    access_token = request.cookies.get("access_token")
    if not access_token:
        return None
    try:
        from jose import jwt
        from app.dependencies import _get_jwks

        header = jwt.get_unverified_header(access_token)
        alg = header.get("alg", "HS256")

        if alg == "ES256":
            jwks = _get_jwks(settings.supabase_url)
            payload = jwt.decode(access_token, jwks, algorithms=["ES256"], audience="authenticated")
        else:
            payload = jwt.decode(access_token, settings.supabase_jwt_secret, algorithms=["HS256"], options={"verify_aud": False})

        user_id = payload.get("sub")
        if not user_id:
            return None
        user_meta = payload.get("user_metadata", {})
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": user_meta.get("role", payload.get("role", "authenticated")),
        }
    except Exception:
        return None


def _require_auth(user: dict | None, request: Request):
    if user is None:
        if _is_htmx(request):
            from fastapi.responses import Response

            resp = Response(status_code=200)
            resp.headers["HX-Redirect"] = "/login"
            return resp
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/", response_class=RedirectResponse)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render(request, "pages/login.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    kpi = {"simulation_count": 0, "avg_yield": 0.0, "price_alerts": 0}
    recent_sims: list[dict[str, Any]] = []
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        # Count simulations
        sims = client.table("simulations").select("id", count="exact").execute()
        kpi["simulation_count"] = sims.count or 0
        # Count active vehicles (price alerts)
        vehs = client.table("vehicles").select("id", count="exact").eq("is_active", True).execute()
        kpi["price_alerts"] = vehs.count or 0
        # Avg yield
        all_sims = client.table("simulations").select("expected_yield_rate").not_.is_("expected_yield_rate", "null").execute()
        yields = [r["expected_yield_rate"] for r in (all_sims.data or []) if r.get("expected_yield_rate")]
        kpi["avg_yield"] = (sum(yields) / len(yields) * 100) if yields else 0.0
        # Recent simulations
        recent = client.table("simulations").select("*").order("created_at", desc=True).limit(5).execute()
        recent_sims = recent.data or []
    except Exception:
        recent_sims = []

    context = {
        "user": user,
        "kpi": kpi,
        "recent_simulations": recent_sims,
        "stats": kpi,
    }
    return _render(request, "pages/dashboard.html", context)


@router.get("/simulation/new", response_class=HTMLResponse)
async def simulation_new_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    makers: list[dict[str, Any]] = []
    body_types: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        makers_resp = client.table("manufacturers").select("*").order("name").execute()
        makers = makers_resp.data or []
        bt_resp = client.table("body_types").select("*").order("name").execute()
        body_types = bt_resp.data or []
        cat_resp = client.table("vehicle_categories").select("*").order("name").execute()
        categories = cat_resp.data or []
    except Exception:
        pass

    return _render(request, "pages/simulation.html", {
        "user": user,
        "makers": makers,
        "body_types": body_types,
        "categories": categories,
    })


@router.get("/simulation/{simulation_id}/result", response_class=HTMLResponse)
async def simulation_result_page(request: Request, simulation_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    simulation: dict[str, Any] | None = None
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        result = (
            client.table("simulations")
            .select("*")
            .eq("id", simulation_id)
            .maybe_single()
            .execute()
        )
        simulation = result.data
    except Exception:
        simulation = None

    context = {
        "user": user,
        "simulation_id": simulation_id,
        "simulation": simulation,
    }
    return _render(request, "pages/simulation_result.html", context)


@router.get("/market-data", response_class=HTMLResponse)
async def market_data_list_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    # Pre-fetch vehicles for initial render
    vehicles: list[dict[str, Any]] = []
    total_count = 0
    stats: dict[str, Any] = {"total_count": 0, "avg_price": 0, "median_price": 0}
    makers: list[dict[str, Any]] = []
    body_types: list[dict[str, Any]] = []

    try:
        from app.db.supabase_client import get_supabase_client

        client = get_supabase_client(service_role=True)

        # Count
        count_result = (
            client.table("vehicles")
            .select("id", count="exact")
            .eq("is_active", True)
            .execute()
        )
        total_count = count_result.count or 0

        # Data (first page)
        result = (
            client.table("vehicles")
            .select("*")
            .eq("is_active", True)
            .order("scraped_at", desc=True)
            .limit(20)
            .execute()
        )
        vehicles = result.data or []

        # Stats
        stats_result = (
            client.table("vehicles")
            .select("price_yen")
            .eq("is_active", True)
            .not_.is_("price_yen", "null")
            .execute()
        )
        prices = [
            row["price_yen"]
            for row in (stats_result.data or [])
            if row.get("price_yen") is not None
        ]
        if prices:
            stats = {
                "total_count": total_count,
                "avg_price": round(statistics.mean(prices)),
                "median_price": round(statistics.median(prices)),
            }
        else:
            stats = {"total_count": total_count, "avg_price": 0, "median_price": 0}

        # Fetch makers and body_types for filter dropdowns
        makers_resp = client.table("manufacturers").select("*").order("name").execute()
        makers = makers_resp.data or []
        bt_resp = client.table("body_types").select("*").order("name").execute()
        body_types = bt_resp.data or []
    except Exception:
        pass

    return _render(
        request,
        "pages/market_data_list.html",
        {
            "user": user,
            "vehicles": vehicles,
            "makers": makers,
            "body_types": body_types,
            "total_count": total_count,
            "stats": stats,
        },
    )


@router.get("/market-data/table", response_class=HTMLResponse)
async def market_data_table_fragment(
    request: Request,
    maker: Optional[str] = Query(default=None),
    body_type: Optional[str] = Query(default=None),
    year_from: Optional[int] = Query(default=None),
    year_to: Optional[int] = Query(default=None),
    price_from: Optional[int] = Query(default=None),
    price_to: Optional[int] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """Return an HTML table fragment for HTMX requests from the market data page."""
    from app.main import templates
    from app.db.supabase_client import get_supabase_client

    try:
        client = get_supabase_client(service_role=True)

        # --- Build filtered query ---
        def _apply_filters(query: Any) -> Any:
            if maker:
                query = query.eq("manufacturer_id", maker)
            if body_type:
                query = query.ilike("body_type", f"%{body_type}%")
            if year_from is not None:
                query = query.gte("model_year", year_from)
            if year_to is not None:
                query = query.lte("model_year", year_to)
            if price_from is not None:
                # Price filter is in 万円 (10,000 yen units)
                query = query.gte("price_yen", price_from * 10000)
            if price_to is not None:
                query = query.lte("price_yen", price_to * 10000)
            if keyword:
                query = query.or_(
                    f"model_name.ilike.%{keyword}%,maker.ilike.%{keyword}%"
                )
            return query

        # Count
        count_query = (
            client.table("vehicles")
            .select("id", count="exact")
            .eq("is_active", True)
        )
        count_query = _apply_filters(count_query)
        count_result = count_query.execute()
        total_count: int = count_result.count or 0

        # Data
        offset = (page - 1) * per_page
        data_query = (
            client.table("vehicles")
            .select("*")
            .eq("is_active", True)
            .order("scraped_at", desc=True)
            .range(offset, offset + per_page - 1)
        )
        data_query = _apply_filters(data_query)
        data_result = data_query.execute()
        vehicles = data_result.data or []

        # Stats
        stats_query = (
            client.table("vehicles")
            .select("price_yen")
            .eq("is_active", True)
            .not_.is_("price_yen", "null")
        )
        stats_query = _apply_filters(stats_query)
        stats_result = stats_query.execute()
        prices = [
            row["price_yen"]
            for row in (stats_result.data or [])
            if row.get("price_yen") is not None
        ]
        if prices:
            summary = {
                "count": len(prices),
                "avg": round(statistics.mean(prices)),
                "median": round(statistics.median(prices)),
            }
        else:
            summary = {"count": 0, "avg": 0, "median": 0}

        total_pages = math.ceil(total_count / per_page) if total_count else 0

    except Exception:
        vehicles = []
        total_count = 0
        total_pages = 0
        summary = {"count": 0, "avg": 0, "median": 0}

    return templates.TemplateResponse(
        request,
        "partials/market_prices_table.html",
        {
            "vehicles": vehicles,
            "meta": {
                "total_count": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            },
            "stats": summary,
        },
    )


@router.get("/market-data/{item_id}", response_class=HTMLResponse)
async def market_data_detail_page(request: Request, item_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    vehicle = None
    similar_vehicles: list[dict[str, Any]] = []
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        result = client.table("vehicles").select("*").eq("id", item_id).single().execute()
        vehicle = result.data

        if vehicle:
            # Fetch similar vehicles (same body_type, different ID)
            similar = (
                client.table("vehicles")
                .select("*")
                .eq("is_active", True)
                .neq("id", item_id)
                .limit(5)
                .execute()
            )
            similar_vehicles = similar.data or []
    except Exception:
        pass

    return _render(request, "pages/market_data_detail.html", {
        "user": user,
        "vehicle": vehicle,
        "similar_vehicles": similar_vehicles,
    })
