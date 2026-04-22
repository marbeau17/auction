"""Vehicle fixture data for the Inventory page.

Provides ~20 representative vehicles (subset of the claimed 142-vehicle fleet)
plus a matching aggregate KPI dict. The first 5 entries are wireframe-verbatim
rows from ``docs/CVLPOS_松プラン_ワイヤーフレーム.html`` L981-1041.

Owner: Agent #5 (2026-04-22 wave).
"""
from __future__ import annotations


# Wireframe-verbatim rows (first 5) plus ~15 variations.
# Funds span 11-15; statuses mix 稼働中/要注意/延滞; fuel types include 軽油 (default),
# EV (x2), HV (x2) to support Inventory filter + ESG service.
_VEHICLES: list[dict] = [
    # ---- Wireframe verbatim (L981-1041) ----
    {
        "id": "T-1524", "plate": "T-1524",
        "make": "日野", "model": "レンジャー 2022", "year": 2022,
        "vin": "HNO-24-...-5122", "fund_id": "f15",
        "ltv_pct": 54, "months_elapsed": 7,
        "monthly_revenue_yen": 3_802_700,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1523", "plate": "T-1523",
        "make": "いすゞ", "model": "フォワード 2021", "year": 2021,
        "vin": "ISZ-21-...-8812", "fund_id": "f15",
        "ltv_pct": 62, "months_elapsed": 12,
        "monthly_revenue_yen": 2_480_000,
        "status_label": "要注意", "status_kind": "warn",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1510", "plate": "T-1510",
        "make": "三菱ふそう", "model": "SG 2023", "year": 2023,
        "vin": "MFS-23-...-0014", "fund_id": "f14",
        "ltv_pct": 48, "months_elapsed": 5,
        "monthly_revenue_yen": 4_950_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1498", "plate": "T-1498",
        "make": "いすゞ", "model": "エルフ 2020", "year": 2020,
        "vin": "ISZ-20-...-2290", "fund_id": "f14",
        "ltv_pct": 71, "months_elapsed": 18,
        "monthly_revenue_yen": 1_120_000,
        "status_label": "延滞", "status_kind": "bad",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1455", "plate": "T-1455",
        "make": "日野", "model": "プロフィア 2022", "year": 2022,
        "vin": "HNO-22-...-7731", "fund_id": "f13",
        "ltv_pct": 52, "months_elapsed": 9,
        "monthly_revenue_yen": 3_640_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    # ---- Additional variations (funds 11-15, statuses mix, ESG fuel mix) ----
    {
        "id": "T-1442", "plate": "T-1442",
        "make": "日野", "model": "デュトロ EV 2023", "year": 2023,
        "vin": "HNO-23-...-3301", "fund_id": "f15",
        "ltv_pct": 46, "months_elapsed": 4,
        "monthly_revenue_yen": 2_880_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "EV",
    },
    {
        "id": "T-1431", "plate": "T-1431",
        "make": "いすゞ", "model": "ギガ 2022", "year": 2022,
        "vin": "ISZ-22-...-1188", "fund_id": "f15",
        "ltv_pct": 50, "months_elapsed": 8,
        "monthly_revenue_yen": 5_240_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1420", "plate": "T-1420",
        "make": "三菱ふそう", "model": "キャンター HV 2022", "year": 2022,
        "vin": "MFS-22-...-7042", "fund_id": "f14",
        "ltv_pct": 44, "months_elapsed": 10,
        "monthly_revenue_yen": 1_890_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "HV",
    },
    {
        "id": "T-1408", "plate": "T-1408",
        "make": "日野", "model": "レンジャー 2021", "year": 2021,
        "vin": "HNO-21-...-4418", "fund_id": "f14",
        "ltv_pct": 58, "months_elapsed": 14,
        "monthly_revenue_yen": 3_120_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1395", "plate": "T-1395",
        "make": "いすゞ", "model": "フォワード 2020", "year": 2020,
        "vin": "ISZ-20-...-6624", "fund_id": "f13",
        "ltv_pct": 63, "months_elapsed": 16,
        "monthly_revenue_yen": 2_240_000,
        "status_label": "要注意", "status_kind": "warn",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1382", "plate": "T-1382",
        "make": "トヨタ", "model": "ダイナ EV 2023", "year": 2023,
        "vin": "TYT-23-...-5509", "fund_id": "f13",
        "ltv_pct": 42, "months_elapsed": 3,
        "monthly_revenue_yen": 1_560_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "EV",
    },
    {
        "id": "T-1370", "plate": "T-1370",
        "make": "日野", "model": "プロフィア 2021", "year": 2021,
        "vin": "HNO-21-...-9110", "fund_id": "f13",
        "ltv_pct": 55, "months_elapsed": 11,
        "monthly_revenue_yen": 3_420_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1355", "plate": "T-1355",
        "make": "三菱ふそう", "model": "ファイター 2020", "year": 2020,
        "vin": "MFS-20-...-2871", "fund_id": "f12",
        "ltv_pct": 66, "months_elapsed": 20,
        "monthly_revenue_yen": 2_050_000,
        "status_label": "要注意", "status_kind": "warn",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1340", "plate": "T-1340",
        "make": "いすゞ", "model": "エルフ HV 2022", "year": 2022,
        "vin": "ISZ-22-...-7733", "fund_id": "f12",
        "ltv_pct": 49, "months_elapsed": 9,
        "monthly_revenue_yen": 1_380_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "HV",
    },
    {
        "id": "T-1327", "plate": "T-1327",
        "make": "日野", "model": "デュトロ 2021", "year": 2021,
        "vin": "HNO-21-...-5540", "fund_id": "f12",
        "ltv_pct": 57, "months_elapsed": 13,
        "monthly_revenue_yen": 1_620_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1315", "plate": "T-1315",
        "make": "トヨタ", "model": "ダイナ 2020", "year": 2020,
        "vin": "TYT-20-...-0812", "fund_id": "f12",
        "ltv_pct": 60, "months_elapsed": 17,
        "monthly_revenue_yen": 1_480_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1298", "plate": "T-1298",
        "make": "いすゞ", "model": "ギガ 2019", "year": 2019,
        "vin": "ISZ-19-...-1122", "fund_id": "f11",
        "ltv_pct": 68, "months_elapsed": 22,
        "monthly_revenue_yen": 4_720_000,
        "status_label": "要注意", "status_kind": "warn",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1281", "plate": "T-1281",
        "make": "三菱ふそう", "model": "スーパーグレート 2020", "year": 2020,
        "vin": "MFS-20-...-9904", "fund_id": "f11",
        "ltv_pct": 53, "months_elapsed": 15,
        "monthly_revenue_yen": 4_310_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1266", "plate": "T-1266",
        "make": "日野", "model": "プロフィア 2019", "year": 2019,
        "vin": "HNO-19-...-3377", "fund_id": "f11",
        "ltv_pct": 59, "months_elapsed": 24,
        "monthly_revenue_yen": 3_180_000,
        "status_label": "稼働中", "status_kind": "ok",
        "fuel_type": "軽油",
    },
    {
        "id": "T-1252", "plate": "T-1252",
        "make": "いすゞ", "model": "フォワード 2019", "year": 2019,
        "vin": "ISZ-19-...-5619", "fund_id": "f11",
        "ltv_pct": 61, "months_elapsed": 26,
        "monthly_revenue_yen": 2_340_000,
        "status_label": "要注意", "status_kind": "warn",
        "fuel_type": "軽油",
    },
]


def get_vehicles(limit: int | None = None) -> list[dict]:
    """Return sample vehicles (≥20 rows, first 5 are wireframe-verbatim).

    Args:
        limit: Optional cap. ``None`` returns all rows.
    """
    if limit is None:
        return list(_VEHICLES)
    return _VEHICLES[: max(0, int(limit))]


def get_fleet_kpi() -> dict:
    """Return Inventory KPI hero aggregate (wireframe-verbatim totals).

    Matches ``docs/CVLPOS_松プラン_ワイヤーフレーム.html`` L992-1001: 142台,
    稼働率 97.9%, 平均車齢 3.2年, 平均LTV 55%, 簿価 ¥6.8億, 取得価 ¥12.2億,
    償却率 44%, +6台 MoM.
    """
    return {
        "total_count": 142,
        "active_count": 138,
        "warn_count": 3,
        "overdue_count": 1,
        "amortizing_count": 0,
        "avg_age_years": 3.2,
        "avg_ltv_pct": 55,
        "fleet_book_value_yen": 680_000_000,
        "acquisition_total_yen": 1_220_000_000,
        "depreciation_rate_pct": 44,
        "mom_delta_count": 6,
        "utilization_pct": 97.9,
    }
