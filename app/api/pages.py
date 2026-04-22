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


# ---------------------------------------------------------------------------
# 松プラン redesign (2026-04-22): sidebar nav config
# ---------------------------------------------------------------------------
# Source of truth for the 11-item sidebar. Consumed by
# app/templates/partials/_sidebar.html via the template context key "nav_config".
# Phase 1: items that don't have a real page yet point to placeholders.
# Phase 3 agents replace those hrefs with the real routes.

NAV_CONFIG = {
    "groups": [
        {
            "label": "サマリー",
            "items": [
                {"id": "dashboard", "label": "統合ダッシュボード", "href": "/dashboard", "icon": "dash"},
                {"id": "portfolio", "label": "ポートフォリオ", "href": "/portfolio", "icon": "portfolio"},
            ],
        },
        {
            "label": "パフォーマンス",
            "items": [
                {"id": "fund", "label": "ファンドパフォーマンス", "href": "/fund", "icon": "fund"},
                {
                    "id": "risk",
                    "label": "リスクモニタリング",
                    "href": "/risk",
                    "icon": "risk",
                    "required_plan": "matsu",
                    "badge_count": 3,
                },
            ],
        },
        {
            "label": "オペレーション",
            "items": [
                {"id": "inventory", "label": "インベントリ管理", "href": "/inventory", "icon": "inv"},
                {"id": "integrated_pricing", "label": "統合プライシング", "href": "/integrated-pricing", "icon": "price"},
                # 個別シミュレーション — drill-down from Price for single-vehicle scenarios.
                # Kept per 2026-04-22 decision (spec §9.3): operators need per-vehicle
                # depth that the aggregated Price / Portfolio views don't expose.
                {"id": "simulation", "label": "個別シミュレーション", "href": "/simulation/new", "icon": "fund"},
                {"id": "contracts", "label": "契約書自動生成", "href": "/simulations", "icon": "contract"},
                {"id": "invoices", "label": "請求書管理・弥生連携", "href": "/invoices", "icon": "invoice"},
            ],
        },
        {
            "label": "松プラン限定",
            "items": [
                {"id": "scrape", "label": "自動価格収集", "href": "/scrape", "icon": "scrape", "required_plan": "matsu", "new": True},
                {"id": "esg", "label": "ESGレポート", "href": "/esg", "icon": "esg", "required_plan": "matsu", "new": True},
                {"id": "proposal", "label": "提案書PDF生成", "href": "/proposals", "icon": "proposal", "new": True},
            ],
        },
    ],
}

# URL path prefix -> active_page id (for sidebar highlighting)
_ACTIVE_PAGE_RULES = (
    ("/simulation", "simulation"),
    ("/market", "market_data"),
    ("/integrated-pricing", "integrated_pricing"),
    ("/financial-analysis", "fund"),
    ("/yayoi", "invoices"),
    ("/lease-contracts", "inventory"),
    ("/invoices", "invoices"),
    ("/portfolio", "portfolio"),
    ("/fund", "fund"),
    ("/risk", "risk"),
    ("/inventory", "inventory"),
    ("/scrape", "scrape"),
    ("/esg", "esg"),
    ("/proposals", "proposal"),
)


def _resolve_active_page(path: str) -> str:
    for prefix, page_id in _ACTIVE_PAGE_RULES:
        if path.startswith(prefix):
            return page_id
    return "dashboard"


def _resolve_page_title(active_page: str) -> str:
    for group in NAV_CONFIG["groups"]:
        for item in group["items"]:
            if item["id"] == active_page:
                return item["label"]
    return "ダッシュボード"


def _render(request: Request, template: str, context: dict | None = None):
    from app.main import templates

    ctx = context or {}
    token = getattr(request.state, "csrf_token", None) or request.cookies.get("csrf_token", "")
    ctx.setdefault("csrf_token", token)
    active_page = ctx.get("active_page") or _resolve_active_page(request.url.path)
    ctx["active_page"] = active_page
    ctx.setdefault("nav_config", NAV_CONFIG)
    ctx.setdefault("current_page_title", _resolve_page_title(active_page))
    # current_plan comes from the authenticated user when present; otherwise
    # fall back to "matsu" so unauthenticated/login pages still render the
    # full 松プラン sidebar for design continuity.
    user = ctx.get("user") or {}
    ctx.setdefault("current_plan", user.get("plan") or "matsu")
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
        role = user_meta.get("role", payload.get("role", "authenticated"))
        # Plan tier for 松プラン UI gating (docs/uiux_migration_spec.md §5).
        # Source priority: JWT user_metadata.plan > heuristic by role.
        # The heuristic keeps existing admins on matsu so operator pages stay
        # accessible until a DB lookup / Supabase Auth hook populates the
        # claim for all users.
        plan = user_meta.get("plan") or payload.get("plan")
        if not plan:
            plan = "matsu" if role == "admin" else "take"
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": role,
            "plan": plan,
            "display_name": user_meta.get("full_name") or user_meta.get("display_name"),
            "stakeholder_role": user_meta.get("stakeholder_role"),
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

    # Portfolio fixtures (funds + NAV + monthly CF).
    # These drive the Dashboard's ファンド一覧 table and the Variant B/C charts.
    # We always attach them — the Dashboard KPI hero is hydrated from Supabase
    # above, but the per-fund table and NAV/CF series don't yet have a
    # real-data path, so the fixture is the canonical source for now.
    try:
        from app.services.sample_data import (
            get_funds as _fx_funds,
            get_nav_series as _fx_nav,
            get_monthly_cashflow as _fx_cf,
        )
        funds = _fx_funds()
        nav_series = _fx_nav()
        monthly_cf = _fx_cf(6)
    except Exception:
        logger.exception("dashboard_fixture_load_failed", handler="dashboard_page")
        funds = []
        nav_series = []
        monthly_cf = []

    context = {
        "user": user,
        "kpi": kpi,
        "recent_simulations": recent_sims,
        "stats": kpi,
        "error_banner": error_banner,
        "error_message": error_banner,
        "kpi_json_url": "/api/v1/dashboard/kpi/json",
        "funds": funds,
        "nav_series": nav_series,
        "monthly_cf": monthly_cf,
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
        # Fall through to fixture fallback below — swallow the exception so
        # the page still renders usable dropdowns in demo / unreachable-DB
        # environments.

    # Silent fixture fallback: if Supabase returned empty (or raised above),
    # populate the dropdowns from bundled sample data so the form is usable
    # in demo / local / empty-DB setups. The fallback is a no-op whenever the
    # Supabase query actually returned rows.
    if not makers or not body_types or not categories:
        from app.services.sample_data import (
            get_makers as _fx_makers,
            get_body_types as _fx_body_types,
            get_categories as _fx_categories,
        )
        if not makers:
            makers = _fx_makers()
        if not body_types:
            body_types = _fx_body_types()
        if not categories:
            categories = _fx_categories()
        # Clear the error banner — the fixture gives users a working form, so
        # showing a "failed to fetch" warning would be misleading.
        error_banner = None

    # Build prefill dict from query params (emitted by simulation_result "条件変更して再計算" link).
    # Keys mirror the template's existing input `name` attributes so binding is direct.
    prefill: dict[str, Any] = {}
    qp = request.query_params
    _prefill_keys = (
        "maker",
        "model",
        "mileage_km",
        "vehicle_class",
        "body_type",
        "acquisition_price",
        "book_value",
        "target_yield_rate",  # percentage form (e.g. "8" == 8%); form input also expects percentage → pass-through
        "lease_term_months",
    )
    for key in _prefill_keys:
        val = qp.get(key)
        if val is not None and val != "":
            prefill[key] = val

    # registration_year_month may arrive as "2020" or "2020-04". Split so year/month
    # selects bind independently. JS can default month to current if absent.
    rym = qp.get("registration_year_month")
    if rym:
        if "-" in rym:
            year_part, _, month_part = rym.partition("-")
            if year_part:
                prefill["registration_year"] = year_part
            if month_part:
                # Strip leading zero for select option matching (e.g. "04" → "4") but also keep raw.
                prefill["registration_month"] = month_part.lstrip("0") or month_part
                prefill["registration_month_raw"] = month_part
        else:
            prefill["registration_year"] = rym
        # Keep original combined value available for any downstream consumer.
        prefill["registration_year_month"] = rym

    prefill_from = qp.get("prefill_from")
    if prefill_from:
        prefill["prefill_from"] = prefill_from
        logger.info("simulation_prefill", source_id=prefill_from)

    return _render(request, "pages/simulation.html", {
        "user": user,
        "makers": makers,
        "body_types": body_types,
        "categories": categories,
        "models": models,
        "equipment_options": equipment_options,
        "error_banner": error_banner,
        "error_message": error_banner,
        "prefill": prefill or None,
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


@router.get("/simulation", response_class=RedirectResponse)
async def simulation_root_redirect(request: Request):
    # Legacy/bookmark compatibility: /simulation → /simulations list page.
    return RedirectResponse(url="/simulations", status_code=302)


@router.get("/proposals", response_class=HTMLResponse)
async def proposals_list_page(request: Request):
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
        logger.exception("proposals_list_fetch_failed", handler="proposals_list_page")
        error_banner = "提案書一覧の取得に失敗しました。しばらくしてから再度お試しください。"

    return _render(request, "pages/proposals_list.html", {
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

    # Bounded scan: full aggregation belongs in a scheduled job; capping the
    # window here keeps p95 acceptable as the vehicles table grows.
    stats_query = (
        client.table("vehicles")
        .select("price_yen")
        .eq("is_active", True)
        .not_.is_("price_yen", "null")
        .order("scraped_at", desc=True)
        .limit(5000)
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

    # Fallback: when Supabase returned zero rows (empty tenant / fresh install),
    # hand the template the 6-row wireframe fixture so the page still shows
    # representative data. The fixture is owned by Agent #5.
    invoice_kpi: dict[str, Any] = {}
    if not invoices:
        try:
            from app.services.sample_data import get_invoices, get_invoice_kpi
            invoices = get_invoices()
            invoice_kpi = get_invoice_kpi()
        except Exception:
            logger.exception("invoice_fixture_load_failed", handler="invoice_list_page")

    return _render(request, "pages/invoice_list.html", {
        "user": user,
        "invoices": invoices,
        "invoice_kpi": invoice_kpi,
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


# ---------------------------------------------------------------------------
# 松プラン redesign: Phase 3 stub pages
# ---------------------------------------------------------------------------
# The sidebar (nav_config) now advertises 6 new pages that Phase 3 agents
# will build out. Until then, each stub renders a "Coming soon" placeholder
# using the new base shell so the navigation works without 404s.

# Phase 3 routes. `required_plan=None` means any authenticated user;
# `required_plan="matsu"` restricts to 松限定 features (Risk/Scrape/ESG).
# Per spec §5, Inventory is 松強調 (enhanced for matsu) but accessible to all.
_PHASE3_ROUTES = [
    ("/portfolio", "portfolio.html", "portfolio", None),
    ("/fund", "fund.html", "fund", None),
    ("/risk", "risk.html", "risk", "matsu"),
    ("/inventory", "inventory.html", "inventory", None),
    ("/scrape", "scrape.html", "scrape", "matsu"),
    ("/esg", "esg.html", "esg", "matsu"),
]


def _make_page_route(path: str, template: str, active_page: str, required_plan: str | None):
    async def _handler(request: Request):
        user = await _get_optional_user(request)
        redirect = _require_auth(user, request)
        if redirect:
            return redirect
        if required_plan:
            from app.middleware.plan_gate import ensure_plan_or_redirect

            gate = ensure_plan_or_redirect(request, user, required_plan)
            if gate:
                return gate
        ctx = {"user": user, "active_page": active_page}
        # For ESG, attach computed metrics so the template doesn't have to
        # hardcode them. See app.services.esg_service.
        if active_page == "esg":
            from app.services.esg_service import compute_esg_snapshot

            ctx["esg"] = compute_esg_snapshot()
        # Portfolio / Fund pages read the 5-fund fixture for their tables and
        # NAV chart. The fixture is the canonical source until a Supabase
        # ``funds`` table lands; templates still keep their inline fallbacks
        # so a missing context var degrades gracefully.
        if active_page in ("portfolio", "fund"):
            try:
                from app.services.sample_data import (
                    get_funds as _fx_funds,
                    get_nav_series as _fx_nav,
                    get_monthly_cashflow as _fx_cf,
                )
                ctx["funds"] = _fx_funds()
                ctx["nav_series"] = _fx_nav()
                ctx["monthly_cf"] = _fx_cf(6)
            except Exception:
                logger.exception(
                    "page_fixture_load_failed",
                    handler=f"{active_page}_page",
                )
                ctx.setdefault("funds", [])
                ctx.setdefault("nav_series", [])
                ctx.setdefault("monthly_cf", [])
        # Risk / Inventory / Scrape pages read their respective fixtures so
        # the UI always has realistic numbers out of the box. Each fixture
        # is a wireframe-verbatim dataset owned by Agent #5.
        if active_page == "risk":
            try:
                from app.services.sample_data import (
                    get_risk_alerts as _fx_alerts,
                    get_risk_kpi as _fx_risk_kpi,
                )
                ctx["risk_alerts"] = _fx_alerts()
                ctx["risk_kpi"] = _fx_risk_kpi()
            except Exception:
                logger.exception("page_fixture_load_failed", handler="risk_page")
                ctx.setdefault("risk_alerts", [])
                ctx.setdefault("risk_kpi", {})
        elif active_page == "inventory":
            try:
                from app.services.sample_data import (
                    get_vehicles as _fx_vehicles,
                    get_fleet_kpi as _fx_fleet_kpi,
                )
                ctx["vehicles"] = _fx_vehicles()
                ctx["fleet_kpi"] = _fx_fleet_kpi()
            except Exception:
                logger.exception("page_fixture_load_failed", handler="inventory_page")
                ctx.setdefault("vehicles", [])
                ctx.setdefault("fleet_kpi", {})
        elif active_page == "scrape":
            try:
                from app.services.sample_data import (
                    get_scrape_jobs as _fx_jobs,
                    get_scrape_kpi as _fx_scrape_kpi,
                )
                ctx["scrape_jobs"] = _fx_jobs()
                ctx["scrape_kpi"] = _fx_scrape_kpi()
            except Exception:
                logger.exception("page_fixture_load_failed", handler="scrape_page")
                ctx.setdefault("scrape_jobs", [])
                ctx.setdefault("scrape_kpi", {})
        return _render(request, f"pages/{template}", ctx)

    _handler.__name__ = f"{active_page}_page"
    return _handler


for _path, _tpl, _page, _plan in _PHASE3_ROUTES:
    router.add_api_route(
        _path,
        _make_page_route(_path, _tpl, _page, _plan),
        methods=["GET"],
        response_class=HTMLResponse,
        name=f"{_page}_page",
    )


@router.get("/upgrade", response_class=HTMLResponse)
async def upgrade_page(request: Request):
    """Shown when a lower-tier user follows a 松限定 sidebar link."""
    user = await _get_optional_user(request)
    return _render(request, "pages/upgrade.html", {"user": user})
