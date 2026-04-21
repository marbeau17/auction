from __future__ import annotations

import math
import statistics
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings

logger = structlog.get_logger()

router = APIRouter(tags=["pages"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _render(request: Request, template: str, context: dict | None = None):
    from app.main import templates

    ctx = context or {}
    token = getattr(request.state, "csrf_token", None) or request.cookies.get("csrf_token", "")
    ctx.setdefault("csrf_token", token)
    # Auto-detect active page from URL path for sidebar highlighting
    path = request.url.path
    if path.startswith("/simulation"):
        ctx.setdefault("active_page", "simulation")
    elif path.startswith("/market"):
        ctx.setdefault("active_page", "market_data")
    elif path.startswith("/integrated-pricing"):
        ctx.setdefault("active_page", "integrated_pricing")
    elif path.startswith("/financial-analysis"):
        ctx.setdefault("active_page", "financial_analysis")
    elif path.startswith("/yayoi"):
        ctx.setdefault("active_page", "yayoi")
    elif path.startswith("/lease-contracts"):
        ctx.setdefault("active_page", "lease_contracts")
    elif path.startswith("/invoices"):
        ctx.setdefault("active_page", "invoices")
    else:
        ctx.setdefault("active_page", "dashboard")
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
    except Exception as exc:
        logger.debug("user_auth_token_invalid", error=str(exc))
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

    kpi = {"simulation_count": 0, "avg_yield": 0.0, "active_vehicle_count": 0}
    recent_sims: list[dict[str, Any]] = []
    error_banner: str | None = None
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        # Count simulations
        sims = client.table("simulations").select("id", count="exact").execute()
        kpi["simulation_count"] = sims.count or 0
        # Active vehicles currently in the catalog (label: 稼働車両数)
        vehs = client.table("vehicles").select("id", count="exact").eq("is_active", True).execute()
        kpi["active_vehicle_count"] = vehs.count or 0
        # Avg yield
        all_sims = client.table("simulations").select("expected_yield_rate").not_.is_("expected_yield_rate", "null").execute()
        yields = [r["expected_yield_rate"] for r in (all_sims.data or []) if r.get("expected_yield_rate")]
        kpi["avg_yield"] = (sum(yields) / len(yields) * 100) if yields else 0.0
        # Recent simulations
        recent = client.table("simulations").select("*").order("created_at", desc=True).limit(5).execute()
        recent_sims = recent.data or []
    except Exception:
        logger.exception("dashboard_data_fetch_failed", handler="dashboard_page")
        recent_sims = []
        error_banner = "ダッシュボードデータの取得に失敗しました。表示されている数値は不完全な可能性があります。"

    context = {
        "user": user,
        "kpi": kpi,
        "recent_simulations": recent_sims,
        "stats": kpi,
        "error_banner": error_banner,
        "error_message": error_banner,
        "kpi_json_url": "/api/v1/dashboard/kpi/json",
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
    models: list[dict[str, Any]] = []
    equipment_options: list[dict[str, Any]] = []
    error_banner: str | None = None
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        makers_resp = client.table("manufacturers").select("*").order("name").execute()
        makers = makers_resp.data or []
        bt_resp = client.table("body_types").select("*").order("name").execute()
        body_types = bt_resp.data or []
        cat_resp = client.table("vehicle_categories").select("*").order("name").execute()
        categories = cat_resp.data or []
        models_resp = client.table("vehicle_models").select("id,name,manufacturer_id,category_code").eq("is_active", True).order("display_order").execute()
        models = models_resp.data or []
        options_resp = client.table("equipment_options").select("*").eq("is_active", True).order("category,display_order").execute()
        equipment_options = options_resp.data or []
    except Exception:
        logger.exception("simulation_new_form_data_failed", handler="simulation_new_page")
        error_banner = "マスタデータの取得に失敗しました。一部のドロップダウンが空になっている可能性があります。"

    return _render(request, "pages/simulation.html", {
        "user": user,
        "makers": makers,
        "body_types": body_types,
        "categories": categories,
        "models": models,
        "equipment_options": equipment_options,
        "error_banner": error_banner,
        "error_message": error_banner,
    })


@router.get("/simulation/{simulation_id}/result", response_class=HTMLResponse)
async def simulation_result_page(request: Request, simulation_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    simulation: dict[str, Any] | None = None
    chart_data: dict[str, str] = {}
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

        if simulation:
            # Merge result_summary_json into top-level for template access.
            # rsj is the canonical engine result blob; older quick-calc rows
            # store a flatter shape, so try both spellings for each field.
            rsj = simulation.get("result_summary_json") or {}
            simulation["maker"] = rsj.get("maker", "")
            simulation["model"] = rsj.get("model", "")
            simulation["body_type_display"] = rsj.get("body_type", "")
            simulation["vehicle_class"] = rsj.get("vehicle_class", "")
            simulation["max_price"] = rsj.get("max_price") or rsj.get("max_purchase_price", 0)
            simulation["residual_value"] = (
                rsj.get("residual_value") or rsj.get("estimated_residual_value", 0)
            )
            simulation["residual_rate"] = (
                rsj.get("residual_rate") or rsj.get("residual_rate_result", 0)
            )
            simulation["assessment"] = rsj.get("assessment", "")
            simulation["breakeven_months"] = rsj.get("breakeven_months")
            simulation["actual_yield_rate"] = (
                rsj.get("actual_yield_rate") or rsj.get("effective_yield_rate", 0)
            )
            simulation["equipment"] = rsj.get("equipment", [])

            # Resolve canonical inputs, allowing engine-result fallbacks for
            # rows persisted via the JSON API (which only fills the JSON blob).
            purchase = (
                simulation.get("purchase_price_yen")
                or rsj.get("recommended_purchase_price")
                or 0
            )
            monthly = (
                simulation.get("lease_monthly_yen")
                or rsj.get("monthly_lease_fee")
                or 0
            )
            term = (
                simulation.get("lease_term_months")
                or (rsj.get("input_data") or {}).get("lease_term_months")
                or 36
            )

            saved_schedule = rsj.get("monthly_schedule")
            has_schedule = (
                isinstance(saved_schedule, list) and len(saved_schedule) > 0
            )

            if has_schedule or (purchase > 0 and monthly > 0 and term > 0):
                months: list[str] = []
                asset_values: list[int] = []
                cumulative_incomes: list[int] = []
                nav_ratios: list[float] = []
                monthly_profits: list[int] = []
                cumulative_profits: list[int] = []

                if has_schedule:
                    # Primary path: use the engine-emitted monthly_schedule
                    # (incorporates body depreciation tables, mileage adj, etc.)
                    for row in saved_schedule:
                        m = row.get("month", 0)
                        asset = row.get("asset_value", row.get("book_value", 0))
                        cum_income = row.get("cumulative_income", 0)
                        profit = row.get("monthly_profit", row.get("net_profit", 0))
                        cum_profit = row.get("cumulative_profit", 0)
                        nav = row.get("nav_ratio")
                        if nav is None:
                            nav = (asset + cum_income) / purchase * 100 if purchase > 0 else 0
                        else:
                            nav = nav * 100 if nav <= 1 else nav

                        months.append(f"{m}月")
                        asset_values.append(int(asset))
                        cumulative_incomes.append(int(cum_income))
                        nav_ratios.append(round(nav, 1))
                        monthly_profits.append(int(profit))
                        cumulative_profits.append(int(cum_profit))
                    term = len(saved_schedule)
                else:
                    # Legacy fallback: straight-line approx for old rows that
                    # were saved before monthly_schedule was persisted.
                    residual_rate_val = (
                        rsj.get("residual_rate")
                        or rsj.get("residual_rate_result")
                        or (0.20 if term <= 36 else 0.10)
                    )
                    residual = int(purchase * residual_rate_val)
                    dep_per_month = (purchase - residual) / term if term else 0
                    mr = (rsj.get("target_yield_rate", 8) / 100) / 12

                    cum_income = 0
                    cum_profit = 0
                    for m in range(1, term + 1):
                        asset = max(int(purchase - dep_per_month * m), residual)
                        cum_income += monthly
                        prev_asset = purchase - dep_per_month * (m - 1)
                        dep_exp = int(prev_asset - asset)
                        fin_cost = int(prev_asset * mr)
                        profit = int(monthly - 15000 - 10000 - dep_exp - fin_cost)
                        cum_profit += profit
                        nav = (asset + cum_income) / purchase * 100 if purchase > 0 else 0

                        months.append(f"{m}月")
                        asset_values.append(asset)
                        cumulative_incomes.append(int(cum_income))
                        nav_ratios.append(round(nav, 1))
                        monthly_profits.append(profit)
                        cumulative_profits.append(int(cum_profit))

                import json
                chart_data = {
                    "months": json.dumps(months, ensure_ascii=False),
                    "asset_values": json.dumps(asset_values),
                    "cumulative_incomes": json.dumps(cumulative_incomes),
                    "nav_ratios": json.dumps(nav_ratios),
                    "nav_60_line": json.dumps([60] * term),
                    "monthly_profits": json.dumps(monthly_profits),
                    "cumulative_profits": json.dumps(cumulative_profits),
                }
    except Exception as exc:
        logger.warning("simulation_result_fetch_failed", simulation_id=simulation_id, error=str(exc))
        error_message = "データの取得に失敗しました。しばらくしてから再度お試しください。"

    context = {
        "user": user,
        "simulation_id": simulation_id,
        "simulation": simulation,
        "chart_data": chart_data,
        "error_message": locals().get("error_message"),
    }
    return _render(request, "pages/simulation_result.html", context)


@router.get("/simulation/{simulation_id}/contracts", response_class=HTMLResponse)
async def contract_mapper_page(request: Request, simulation_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    # The actual content is loaded via HTMX from the contracts API
    return _render(request, "pages/contract_mapper.html", {
        "user": user,
        "simulation_id": simulation_id,
    })


@router.get("/proposals/preview/{simulation_id}", response_class=HTMLResponse)
async def proposal_preview_page(request: Request, simulation_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    simulation: dict[str, Any] | None = None
    error_banner: str | None = None
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

        if simulation:
            # Ensure input_data is accessible as an object for template dot notation
            input_data = simulation.get("input_data") or simulation.get("result_summary_json") or {}
            if not simulation.get("input_data"):
                simulation["input_data"] = input_data
    except Exception:
        logger.exception(
            "proposal_preview_fetch_failed",
            handler="proposal_preview_page",
            simulation_id=simulation_id,
        )
        error_banner = "提案書データの取得に失敗しました。しばらくしてから再度お試しください。"

    return _render(request, "pages/proposal_preview.html", {
        "user": user,
        "simulation_id": simulation_id,
        "simulation": simulation,
        "error_banner": error_banner,
        "error_message": error_banner,
    })


@router.get("/simulations", response_class=HTMLResponse)
async def simulation_list_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    simulations: list[dict[str, Any]] = []
    error_banner: str | None = None
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        result = client.table("simulations").select("*").order("created_at", desc=True).limit(50).execute()
        simulations = result.data or []
    except Exception:
        logger.exception("simulation_list_fetch_failed", handler="simulation_list_page")
        error_banner = "シミュレーション一覧の取得に失敗しました。しばらくしてから再度お試しください。"

    return _render(request, "pages/simulation_list.html", {
        "user": user,
        "simulations": simulations,
        "total_count": len(simulations),
        "error_banner": error_banner,
        "error_message": error_banner,
    })


_MARKET_DATA_FILTER_KEYS = (
    "maker",
    "body_type",
    "year_from",
    "year_to",
    "price_from",
    "price_to",
    "keyword",
)


def _market_data_filter_query_string(filters: dict[str, Any]) -> str:
    from urllib.parse import urlencode

    pairs = [
        (key, filters[key])
        for key in _MARKET_DATA_FILTER_KEYS
        if filters.get(key) not in (None, "")
    ]
    return urlencode(pairs)


def _fetch_market_data(
    *,
    maker: Optional[str],
    body_type: Optional[str],
    year_from: Optional[int],
    year_to: Optional[int],
    price_from: Optional[int],
    price_to: Optional[int],
    keyword: Optional[str],
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], int, int, dict[str, Any]]:
    from app.db.supabase_client import get_supabase_client

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
            query = query.gte("price_yen", price_from * 10000)
        if price_to is not None:
            query = query.lte("price_yen", price_to * 10000)
        if keyword:
            query = query.or_(
                f"model_name.ilike.%{keyword}%,maker.ilike.%{keyword}%"
            )
        return query

    client = get_supabase_client(service_role=True)
    offset = (page - 1) * per_page

    data_query = (
        client.table("vehicles")
        .select("*", count="exact")
        .eq("is_active", True)
        .order("scraped_at", desc=True)
        .range(offset, offset + per_page - 1)
    )
    data_query = _apply_filters(data_query)
    data_result = data_query.execute()
    vehicles = data_result.data or []
    total_count: int = data_result.count or 0

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
    return vehicles, total_count, total_pages, summary


@router.get("/market-data", response_class=HTMLResponse)
async def market_data_list_page(
    request: Request,
    maker: Optional[str] = Query(default=None),
    body_type: Optional[str] = Query(default=None),
    year_from: Optional[int] = Query(default=None),
    year_to: Optional[int] = Query(default=None),
    price_from: Optional[int] = Query(default=None),
    price_to: Optional[int] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    per_page = 20

    vehicles: list[dict[str, Any]] = []
    total_count = 0
    total_pages = 0
    summary: dict[str, Any] = {"count": 0, "avg": 0, "median": 0}
    makers: list[dict[str, Any]] = []
    body_types: list[dict[str, Any]] = []

    filters = {
        "maker": maker,
        "body_type": body_type,
        "year_from": year_from,
        "year_to": year_to,
        "price_from": price_from,
        "price_to": price_to,
        "keyword": keyword,
    }

    try:
        vehicles, total_count, total_pages, summary = _fetch_market_data(
            **filters,
            page=page,
            per_page=per_page,
        )

        from app.db.supabase_client import get_supabase_client

        client = get_supabase_client(service_role=True)
        makers_resp = client.table("manufacturers").select("*").order("name").execute()
        makers = makers_resp.data or []
        bt_resp = client.table("body_types").select("*").order("name").execute()
        body_types = bt_resp.data or []
    except Exception as exc:
        logger.warning("market_data_list_fetch_failed", error=str(exc))
        error_message = "データの取得に失敗しました。しばらくしてから再度お試しください。"

    meta = {
        "total_count": total_count,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }

    return _render(
        request,
        "pages/market_data_list.html",
        {
            "user": user,
            "vehicles": vehicles,
            "makers": makers,
            "body_types": body_types,
            "total_count": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "stats": summary,
            "meta": meta,
            "filter": filters,
            "query_string": _market_data_filter_query_string(filters),
            "base_url": "/market-data/table",
            "hx_target": "#vehicle-table-container",
            "error_message": locals().get("error_message"),
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

    filters = {
        "maker": maker,
        "body_type": body_type,
        "year_from": year_from,
        "year_to": year_to,
        "price_from": price_from,
        "price_to": price_to,
        "keyword": keyword,
    }

    try:
        vehicles, total_count, total_pages, summary = _fetch_market_data(
            **filters,
            page=page,
            per_page=per_page,
        )
    except Exception as exc:
        logger.warning("market_data_table_fetch_failed", error=str(exc))
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
            "filter": filters,
            "query_string": _market_data_filter_query_string(filters),
            "base_url": "/market-data/table",
            "hx_target": "#vehicle-table-container",
        },
    )


@router.get("/market-data/import", response_class=HTMLResponse)
async def market_data_import_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    return _render(request, "pages/market_data_import.html", {"user": user})


@router.get("/integrated-pricing", response_class=HTMLResponse)
async def integrated_pricing_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    return _render(request, "pages/integrated_pricing.html", {"user": user})


@router.get("/financial-analysis", response_class=HTMLResponse)
async def financial_analysis_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    return _render(request, "pages/financial_analysis.html", {"user": user})


@router.get("/invoices", response_class=HTMLResponse)
async def invoice_list_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    invoices: list[dict[str, Any]] = []
    error_banner: str | None = None
    try:
        from app.db.supabase_client import get_supabase_client

        client = get_supabase_client(service_role=True)
        result = (
            client.table("invoices")
            .select("*")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        invoices = result.data or []
    except Exception:
        logger.exception("invoice_list_fetch_failed", handler="invoice_list_page")
        error_banner = "請求書データの取得に失敗しました。しばらくしてから再度お試しください。"

    return _render(request, "pages/invoice_list.html", {
        "user": user,
        "invoices": invoices,
        "total_count": len(invoices),
        "error_banner": error_banner,
        "error_message": error_banner,
    })


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail_page(request: Request, invoice_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    invoice: dict[str, Any] | None = None
    error_banner: str | None = None
    try:
        from app.db.supabase_client import get_supabase_client

        client = get_supabase_client(service_role=True)
        result = (
            client.table("invoices")
            .select("*")
            .eq("id", invoice_id)
            .maybe_single()
            .execute()
        )
        invoice = result.data
    except Exception:
        logger.exception(
            "invoice_detail_fetch_failed",
            handler="invoice_detail_page",
            invoice_id=invoice_id,
        )
        error_banner = "請求書詳細の取得に失敗しました。しばらくしてから再度お試しください。"

    return _render(request, "pages/invoice_detail.html", {
        "user": user,
        "invoice_id": invoice_id,
        "invoice": invoice,
        "error_banner": error_banner,
        "error_message": error_banner,
    })


@router.get("/market-data/{item_id}", response_class=HTMLResponse)
async def market_data_detail_page(request: Request, item_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    vehicle: dict[str, Any] | None = None
    similar_vehicles: list[dict[str, Any]] = []
    error_banner: str | None = None
    try:
        from app.db.supabase_client import get_supabase_client
        client = get_supabase_client(service_role=True)
        result = client.table("vehicles").select("*").eq("id", item_id).single().execute()
        vehicle = result.data

        if vehicle:
            # Fetch similar vehicles (same maker or body_type)
            similar_query = (
                client.table("vehicles")
                .select("*")
                .eq("is_active", True)
                .neq("id", item_id)
            )
            if vehicle.get("maker"):
                similar_query = similar_query.eq("maker", vehicle["maker"])
            elif vehicle.get("body_type"):
                similar_query = similar_query.eq("body_type", vehicle["body_type"])
            similar_result = similar_query.limit(5).execute()
            similar_vehicles = similar_result.data or []
    except Exception:
        logger.exception(
            "market_data_detail_fetch_failed",
            handler="market_data_detail_page",
            item_id=item_id,
        )
        error_banner = "車両データの取得に失敗しました。しばらくしてから再度お試しください。"

    return _render(request, "pages/market_data_detail.html", {
        "user": user,
        "vehicle": vehicle,
        "similar_vehicles": similar_vehicles,
        "error_banner": error_banner,
        "error_message": error_banner,
    })


@router.get("/financial-analysis", response_class=HTMLResponse)
async def financial_analysis_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    return _render(request, "pages/financial_analysis.html", {"user": user})


@router.get("/yayoi/status", response_class=HTMLResponse)
async def yayoi_status_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    return _render(request, "pages/yayoi_status.html", {"user": user})


@router.get("/lease-contracts/import", response_class=HTMLResponse)
async def lease_contract_import_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect

    return _render(request, "pages/lease_contract_import.html", {"user": user})
