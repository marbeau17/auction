"""Dashboard API router.

Provides KPI HTML fragments for the dashboard page loaded via HTMX.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db.supabase_client import get_supabase_client

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/kpi")
async def get_dashboard_kpi(request: Request):
    """Return KPI HTML fragment for dashboard."""
    try:
        client = get_supabase_client(service_role=True)

        # Count simulations this month
        from datetime import datetime

        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        sims = (
            client.table("simulations")
            .select("id", count="exact")
            .gte("created_at", month_start.isoformat())
            .execute()
        )
        sim_count = sims.count or 0

        # Average yield
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

        # Vehicle count as proxy for market data size
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
