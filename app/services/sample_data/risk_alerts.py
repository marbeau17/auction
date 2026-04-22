"""Risk alert fixture data for the リスクモニタリング page.

Mirrors wireframe ``docs/CVLPOS_松プラン_ワイヤーフレーム.html`` L830-850:
4 KPI cards + 3 alert rows.

Owner: Agent #5 (2026-04-22 wave).
"""
from __future__ import annotations


_ALERTS: list[dict] = [
    {
        "level": "CRITICAL",
        "kind": "LTV 超過",
        "target": "Fund14号 / T-1498",
        "detected_at": "本日 13:42",
        "threshold": "60%",
        "observed": "71%",
        "observed_color": "bad",
        "action_label": "対処",
        "action_href": "/inventory/T-1498",
    },
    {
        "level": "WARN",
        "kind": "延滞60日",
        "target": "㈱東西運輸",
        "detected_at": "本日 10:05",
        "threshold": "30日",
        "observed": "63日",
        "observed_color": "warn",
        "action_label": "督促",
        "action_href": "#",
    },
    {
        "level": "WARN",
        "kind": "JOB失敗",
        "target": "AI-NET scrape",
        "detected_at": "本日 14:02",
        "threshold": "3 retry",
        "observed": "3/3",
        "observed_color": "warn",
        "action_label": "再実行",
        "action_href": "/scrape",
    },
]


def get_risk_alerts() -> list[dict]:
    """Return the 3 wireframe-verbatim active alerts (L842-846)."""
    return list(_ALERTS)


def get_risk_kpi() -> dict:
    """Return Risk page KPI row totals (wireframe L831-834)."""
    return {
        "high_risk_count": 4,
        "overdue_count": 1,
        "nfav_warn_count": 0,
        "system_health_pct": 99.2,
    }
