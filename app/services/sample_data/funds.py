"""Fixture fallback for fund-level portfolio data (Dashboard / Portfolio / Fund).

Called from route handlers (see ``app/api/pages.py::dashboard_page`` and the
Phase 3 ``/portfolio`` + ``/fund`` stubs) when Supabase is unreachable or the
``funds`` / NAV tables are empty. Shapes here mirror what the three page
templates consume — see ``app/templates/pages/dashboard.html``,
``portfolio.html``, and ``fund.html`` for the canonical reference.

Target numbers are taken from the wireframe (
``docs/CVLPOS_松プラン_ワイヤーフレーム.html`` lines 568-822). IDs are stable
strings so repeated restarts stay referentially consistent.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------
# Five カーチスファンド (15号 → 11号). Ordered newest-first (15号 at top) to
# match the Dashboard + Portfolio tables in the wireframe. ``aum_yen`` is in
# raw yen; templates are free to format to "¥XXXM" or "¥X.X億".

_FUNDS: list[dict] = [
    {
        "id": "fund-15",
        "name": "カーチスファンド15号",
        "color": "#C9A24A",  # gold
        "aum_yen": 320_000_000,
        "yield_pct": 8.1,
        "nfav_pct": 104.2,
        "ltv_pct": 58,
        "vehicle_count": 28,
        "status_label": "稼働中",
        "status_kind": "ok",
    },
    {
        "id": "fund-14",
        "name": "カーチスファンド14号",
        "color": "#7E9DBF",  # blue
        "aum_yen": 280_000_000,
        "yield_pct": 7.6,
        "nfav_pct": 106.8,
        "ltv_pct": 62,
        "vehicle_count": 24,
        "status_label": "稼働中",
        "status_kind": "ok",
    },
    {
        "id": "fund-13",
        "name": "カーチスファンド13号",
        "color": "#3E8E5A",  # green
        "aum_yen": 230_000_000,
        "yield_pct": 7.2,
        "nfav_pct": 109.1,
        "ltv_pct": 54,
        "vehicle_count": 22,
        "status_label": "稼働中",
        "status_kind": "ok",
    },
    {
        "id": "fund-12",
        "name": "カーチスファンド12号",
        "color": "#B5443A",  # red
        "aum_yen": 160_000_000,
        "yield_pct": 6.8,
        "nfav_pct": 108.5,
        "ltv_pct": 51,
        "vehicle_count": 18,
        "status_label": "償還準備",
        "status_kind": "warn",
    },
    {
        "id": "fund-11",
        "name": "カーチスファンド11号",
        "color": "#6E6A5C",  # gray
        "aum_yen": 130_000_000,
        "yield_pct": 6.5,
        "nfav_pct": 110.4,
        "ltv_pct": 47,
        "vehicle_count": 16,
        "status_label": "運用中",
        "status_kind": "ok",
    },
]


def get_funds() -> list[dict]:
    """Return a shallow copy of the 5-fund fixture list (newest-first)."""
    return [dict(f) for f in _FUNDS]


# ---------------------------------------------------------------------------
# NAV series (36-month)
# ---------------------------------------------------------------------------
# Curve shape per the wireframe:
#   physical       : 320M → 130M linear down
#   cash_recovered : 0    → 220M linear up
#   nfav           : ~320 → ~350 over 36 months with a parabolic mid-cycle dip
#                    (trough ~M12–M15, magnitude ~40M)
#
# When ``fund_id`` is provided, we scale the series by that fund's AUM ratio
# vs. the 15号 baseline (320M). When None, the returned series represents the
# weighted average across all funds (the AUM-weighted composite).


def _nav_points_for_scale(scale: float) -> list[dict]:
    out: list[dict] = []
    for i in range(36):
        t = i / 35 if 35 else 0  # 0 → 1
        physical = (320 - (320 - 130) * t) * scale
        cash_recovered = (220 * t) * scale
        # Parabolic dip (trough near M12–M15) then recovery to ~350
        dip = -40 * math.sin(math.pi * t)
        trend = 320 + (350 - 320) * t
        nfav = (trend + dip) * scale
        out.append({
            "month": f"M{i + 1:02d}",
            "physical": round(physical, 1),
            "cash_recovered": round(cash_recovered, 1),
            "nfav": round(nfav, 1),
        })
    return out


def get_nav_series(fund_id: str | None = None) -> list[dict]:
    """Return a 36-month NAV series.

    If ``fund_id`` matches a known fund, scale the baseline curve to that
    fund's AUM. Otherwise return the AUM-weighted average across all funds
    (equivalent to scale=1.0 for the composite view).
    """
    if fund_id:
        match = next((f for f in _FUNDS if f["id"] == fund_id), None)
        if match:
            scale = match["aum_yen"] / 320_000_000  # 15号 = baseline (320M)
            return _nav_points_for_scale(scale)
    # Composite / weighted-average view: the baseline curve is already
    # calibrated to the wireframe's "total portfolio" numbers, so scale=1.0.
    return _nav_points_for_scale(1.0)


# ---------------------------------------------------------------------------
# Monthly cashflow (Dashboard Variant B chart)
# ---------------------------------------------------------------------------
# Wireframe target (¥M):
#   11月 152 / 12  ·  12月 162 / 13  ·  1月 168 / 13
#   2月  175 / 14  ·  3月  178 / 14  ·  4月 182 / 15

_CASHFLOW_12M: list[dict] = [
    {"label": "5月",  "lease_income": 131, "maintenance_insurance": 11},
    {"label": "6月",  "lease_income": 135, "maintenance_insurance": 11},
    {"label": "7月",  "lease_income": 138, "maintenance_insurance": 11},
    {"label": "8月",  "lease_income": 142, "maintenance_insurance": 12},
    {"label": "9月",  "lease_income": 145, "maintenance_insurance": 12},
    {"label": "10月", "lease_income": 148, "maintenance_insurance": 12},
    {"label": "11月", "lease_income": 152, "maintenance_insurance": 12},
    {"label": "12月", "lease_income": 162, "maintenance_insurance": 13},
    {"label": "1月",  "lease_income": 168, "maintenance_insurance": 13},
    {"label": "2月",  "lease_income": 175, "maintenance_insurance": 14},
    {"label": "3月",  "lease_income": 178, "maintenance_insurance": 14},
    {"label": "4月",  "lease_income": 182, "maintenance_insurance": 15},
]


def get_monthly_cashflow(months: int = 6) -> list[dict]:
    """Return the most recent ``months`` months of CF (default 6).

    Shape per row: ``{label, lease_income, maintenance_insurance}`` with the
    two numeric fields in ¥M (百万円). Ordered oldest-first so charts can
    plot directly left-to-right.
    """
    if months <= 0:
        return []
    n = min(months, len(_CASHFLOW_12M))
    return [dict(row) for row in _CASHFLOW_12M[-n:]]
