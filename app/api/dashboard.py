"""Dashboard API router.

Provides KPI data and HTML fragments for the dashboard page loaded via HTMX.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.db.supabase_client import get_supabase_client
from app.middleware.rbac import require_permission

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _safe_query(fn):
    """Execute a query function, returning None on any error (e.g. table missing)."""
    try:
        return fn()
    except Exception:
        return None


@router.get("/kpi")
async def get_dashboard_kpi(
    request: Request,
    user=Depends(require_permission("dashboard", "read")),
):
    """Return KPI HTML fragment for dashboard (legacy endpoint)."""
    try:
        client = get_supabase_client(service_role=True)

        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        sims = (
            client.table("simulations")
            .select("id", count="exact")
            .gte("created_at", month_start.isoformat())
            .execute()
        )
        sim_count = sims.count or 0

        all_sims = (
            client.table("simulations")
            .select("expected_yield_rate")
            .not_.is_("expected_yield_rate", "null")
            .execute()
        )
        yields = [
            r["expected_yield_rate"]
            for r in (all_sims.data or [])
            if r.get("expected_yield_rate")
        ]
        avg_yield = sum(yields) / len(yields) * 100 if yields else 0

        vehicles = (
            client.table("vehicles")
            .select("id", count="exact")
            .eq("is_active", True)
            .execute()
        )
        vehicle_count = vehicles.count or 0

        html = f"""
        <div class="kpi-card">
            <div class="kpi-card__label">今月査定数</div>
            <div class="kpi-card__value">{sim_count}</div>
            <div class="kpi-card__sub">件</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-card__label">平均利回り</div>
            <div class="kpi-card__value">{avg_yield:.1f}%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-card__label">市場データ数</div>
            <div class="kpi-card__value">{vehicle_count}</div>
            <div class="kpi-card__sub">件</div>
        </div>
        """
        return HTMLResponse(content=html)
    except Exception:
        html = """
        <div class="kpi-card"><div class="kpi-card__label">今月査定数</div><div class="kpi-card__value">--</div></div>
        <div class="kpi-card"><div class="kpi-card__label">平均利回り</div><div class="kpi-card__value">--</div></div>
        <div class="kpi-card"><div class="kpi-card__label">市場データ数</div><div class="kpi-card__value">--</div></div>
        """
        return HTMLResponse(content=html)


@router.get("/kpi/json")
async def get_dashboard_kpi_json(
    request: Request,
    user=Depends(require_permission("dashboard", "read")),
):
    """Return comprehensive KPI data as JSON for the enhanced dashboard."""
    client = get_supabase_client(service_role=True)
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    data: dict = {}

    # --- Vehicles leased (secured_asset_blocks where status='leased') ---
    result = _safe_query(
        lambda: client.table("secured_asset_blocks")
        .select("id", count="exact")
        .eq("status", "leased")
        .execute()
    )
    data["total_vehicles_leased"] = (result.count if result and hasattr(result, "count") else 0) or 0

    # --- Total investment amount (sum of funds.total_fundraise_amount where active) ---
    result = _safe_query(
        lambda: client.table("funds")
        .select("total_fundraise_amount")
        .eq("status", "active")
        .execute()
    )
    if result and result.data:
        data["total_investment_amount"] = sum(
            r.get("total_fundraise_amount", 0) or 0 for r in result.data
        )
    else:
        data["total_investment_amount"] = 0

    # --- Profit conversion funds (funds where profit conversion achieved) ---
    result = _safe_query(
        lambda: client.table("funds")
        .select("id", count="exact")
        .eq("profit_converted", True)
        .execute()
    )
    data["profit_conversion_funds"] = (result.count if result and hasattr(result, "count") else 0) or 0

    # --- Monthly billing amount (sum of invoices for current month) ---
    result = _safe_query(
        lambda: client.table("invoices")
        .select("amount")
        .gte("issue_date", month_start.strftime("%Y-%m-%d"))
        .execute()
    )
    if result and result.data:
        data["monthly_billing_amount"] = sum(
            r.get("amount", 0) or 0 for r in result.data
        )
    else:
        data["monthly_billing_amount"] = 0

    # --- Collection rate (paid / total excluding cancelled) ---
    total_result = _safe_query(
        lambda: client.table("invoices")
        .select("id", count="exact")
        .neq("status", "cancelled")
        .execute()
    )
    paid_result = _safe_query(
        lambda: client.table("invoices")
        .select("id", count="exact")
        .eq("status", "paid")
        .execute()
    )
    total_inv = (total_result.count if total_result and hasattr(total_result, "count") else 0) or 0
    paid_inv = (paid_result.count if paid_result and hasattr(paid_result, "count") else 0) or 0
    data["collection_rate"] = round((paid_inv / total_inv * 100), 1) if total_inv > 0 else 0.0

    # --- Overdue count (invoices past due_date and not paid) ---
    today_str = now.strftime("%Y-%m-%d")
    result = _safe_query(
        lambda: client.table("invoices")
        .select("id", count="exact")
        .lt("due_date", today_str)
        .neq("status", "paid")
        .neq("status", "cancelled")
        .execute()
    )
    data["overdue_count"] = (result.count if result and hasattr(result, "count") else 0) or 0

    # --- Average yield rate (from simulations) ---
    result = _safe_query(
        lambda: client.table("simulations")
        .select("expected_yield_rate")
        .not_.is_("expected_yield_rate", "null")
        .execute()
    )
    if result and result.data:
        yields = [r["expected_yield_rate"] for r in result.data if r.get("expected_yield_rate")]
        data["average_yield_rate"] = round(sum(yields) / len(yields) * 100, 2) if yields else 0.0
    else:
        data["average_yield_rate"] = 0.0

    # --- Recent invoices (latest 5) ---
    result = _safe_query(
        lambda: client.table("invoices")
        .select("id,invoice_number,amount,status,due_date,issue_date,customer_name")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    data["recent_invoices"] = result.data if result and result.data else []

    # --- Monthly lease income trend (last 6 months) ---
    monthly_income = []
    for i in range(5, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        m_start = f"{y}-{m:02d}-01"
        if m == 12:
            m_end = f"{y + 1}-01-01"
        else:
            m_end = f"{y}-{m + 1:02d}-01"
        label = f"{y}/{m:02d}"
        result = _safe_query(
            lambda m_start=m_start, m_end=m_end: client.table("invoices")
            .select("amount")
            .gte("issue_date", m_start)
            .lt("issue_date", m_end)
            .eq("status", "paid")
            .execute()
        )
        total = 0
        if result and result.data:
            total = sum(r.get("amount", 0) or 0 for r in result.data)
        monthly_income.append({"month": label, "amount": total})
    data["monthly_income_trend"] = monthly_income

    # --- Invoice status breakdown ---
    status_counts: dict[str, int] = {}
    for st in ["paid", "pending", "overdue", "cancelled"]:
        result = _safe_query(
            lambda st=st: client.table("invoices")
            .select("id", count="exact")
            .eq("status", st)
            .execute()
        )
        status_counts[st] = (result.count if result and hasattr(result, "count") else 0) or 0
    data["invoice_status_breakdown"] = status_counts

    return JSONResponse(content=data)
