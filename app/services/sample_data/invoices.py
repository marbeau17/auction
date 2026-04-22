"""Invoice fixture data for the 請求書管理 page.

Mirrors wireframe ``docs/CVLPOS_松プラン_ワイヤーフレーム.html`` L955-970 (6 rows
visible) and the L936-941 KPI row (今月発行 142件 / 入金済 139 / 承認待 2 /
延滞 1).

Owner: Agent #5 (2026-04-22 wave).
"""
from __future__ import annotations


# First 6 rows are wireframe-verbatim (L260-265 of the wireframe JSX).
# Rows 7-10 are plausible fillers so `get_invoices(limit=10)` works when the
# table grows in a future iteration.
_INVOICES: list[dict] = [
    # ---- Wireframe verbatim ----
    {
        "number": "INV-202604-0001",
        "customer": "山田運送",
        "amount_yen": 450_000,
        "due_date": "2026/04/30",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0002",
        "customer": "佐藤物流",
        "amount_yen": 380_000,
        "due_date": "2026/04/30",
        "status_label": "承認待",
        "status_kind": "warn",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0003",
        "customer": "田中運輸",
        "amount_yen": 520_000,
        "due_date": "2026/04/30",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0004",
        "customer": "鈴木物流",
        "amount_yen": 410_000,
        "due_date": "2026/04/25",
        "status_label": "延滞",
        "status_kind": "bad",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0005",
        "customer": "高橋運送",
        "amount_yen": 495_000,
        "due_date": "2026/04/30",
        "status_label": "承認待",
        "status_kind": "warn",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0006",
        "customer": "中村物流",
        "amount_yen": 385_000,
        "due_date": "2026/04/30",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
    # ---- Additional fillers for larger `limit` values ----
    {
        "number": "INV-202604-0007",
        "customer": "小林運送",
        "amount_yen": 420_000,
        "due_date": "2026/05/10",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0008",
        "customer": "伊藤物流",
        "amount_yen": 365_000,
        "due_date": "2026/05/10",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0009",
        "customer": "渡辺運輸",
        "amount_yen": 478_000,
        "due_date": "2026/05/10",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
    {
        "number": "INV-202604-0010",
        "customer": "加藤運送",
        "amount_yen": 402_000,
        "due_date": "2026/05/10",
        "status_label": "送付済",
        "status_kind": "ok",
        "yayoi_synced": True,
    },
]


def get_invoices(limit: int = 6) -> list[dict]:
    """Return the 6 wireframe rows by default; cap at ``limit`` (≤10)."""
    if limit is None:
        return list(_INVOICES)
    return _INVOICES[: max(0, int(limit))]


def get_invoice_kpi() -> dict:
    """Return the KPI row shown at wireframe L936-941 (今月 / 入金 / 承認待 / 延滞)."""
    return {
        "issued_month_count": 142,
        "issued_month_yen": 182_000_000,
        "paid_count": 139,
        "paid_ratio_pct": 98,
        "pending_approval_count": 2,
        "pending_approval_yen": 875_000,
        "overdue_count": 1,
        "overdue_yen": 410_000,
    }
