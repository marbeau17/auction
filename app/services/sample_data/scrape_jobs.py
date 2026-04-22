"""Scrape job fixture data for the 自動価格収集 page.

Mirrors wireframe ``docs/CVLPOS_松プラン_ワイヤーフレーム.html`` L1048-1068:
4 KPI cards + 5 scrape jobs (AI-NET / トラックキングダム / USS / TAA / JU).

Owner: Agent #5 (2026-04-22 wave).
"""
from __future__ import annotations


_JOBS: list[dict] = [
    {
        "site": "AI-NET",
        "last_run_at": "2026/04/22 14:02",
        "records": 1_248,
        "status_label": "失敗",
        "status_kind": "bad",
        "next_run_at": "17:00",
    },
    {
        "site": "トラックキングダム",
        "last_run_at": "2026/04/22 12:30",
        "records": 842,
        "status_label": "成功",
        "status_kind": "ok",
        "next_run_at": "18:30",
    },
    {
        "site": "USS API",
        "last_run_at": "2026/04/22 13:15",
        "records": 3_520,
        "status_label": "成功",
        "status_kind": "ok",
        "next_run_at": "19:15",
    },
    {
        "site": "TAA API",
        "last_run_at": "2026/04/22 11:00",
        "records": 2_180,
        "status_label": "成功",
        "status_kind": "ok",
        "next_run_at": "17:00",
    },
    {
        "site": "JU連携",
        "last_run_at": "2026/04/22 09:40",
        "records": 604,
        "status_label": "成功",
        "status_kind": "ok",
        "next_run_at": "21:40",
    },
]


def get_scrape_jobs() -> list[dict]:
    """Return the 5 wireframe-verbatim scrape job rows (L277-281 of wireframe JSX)."""
    return list(_JOBS)


def get_scrape_kpi() -> dict:
    """Return scrape KPI row totals (wireframe L1049-1052)."""
    return {
        "today_records": 8_394,
        "failed_count": 1,
        "success_rate_pct_7d": 97.4,
        "proxy_healthy_numerator": 8,
        "proxy_healthy_denominator": 8,
    }
