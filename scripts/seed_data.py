"""Seed master data into Supabase database."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.supabase_client import get_supabase_client


async def seed():
    client = get_supabase_client(service_role=True)

    # Seed vehicle categories
    categories = [
        {"name": "大型トラック", "code": "LARGE", "display_order": 1},
        {"name": "中型トラック", "code": "MEDIUM", "display_order": 2},
        {"name": "小型トラック", "code": "SMALL", "display_order": 3},
        {"name": "トレーラーヘッド", "code": "TRAILER_HEAD", "display_order": 4},
        {"name": "トレーラーシャシー", "code": "TRAILER_CHASSIS", "display_order": 5},
    ]
    for cat in categories:
        client.table("vehicle_categories").upsert(
            cat, on_conflict="code"
        ).execute()
    print(f"  Inserted {len(categories)} vehicle categories.")

    # Seed manufacturers
    makers = [
        {"name": "いすゞ", "name_en": "Isuzu", "code": "ISZ", "display_order": 1},
        {"name": "日野", "name_en": "Hino", "code": "HNO", "display_order": 2},
        {
            "name": "三菱ふそう",
            "name_en": "Mitsubishi Fuso",
            "code": "MFU",
            "display_order": 3,
        },
        {
            "name": "UDトラックス",
            "name_en": "UD Trucks",
            "code": "UDT",
            "display_order": 4,
        },
    ]
    for maker in makers:
        client.table("manufacturers").upsert(
            maker, on_conflict="code"
        ).execute()
    print(f"  Inserted {len(makers)} manufacturers.")

    # Seed body types
    body_types = [
        {"name": "ウイング", "code": "WING", "display_order": 1},
        {"name": "バン", "code": "VAN", "display_order": 2},
        {"name": "平ボディ", "code": "FLAT", "display_order": 3},
        {"name": "冷凍冷蔵車", "code": "REFR", "display_order": 4},
        {"name": "ダンプ", "code": "DUMP", "display_order": 5},
        {"name": "クレーン付き", "code": "CRAN", "display_order": 6},
        {"name": "タンクローリー", "code": "TANK", "display_order": 7},
        {"name": "塵芥車", "code": "TRSH", "display_order": 8},
        {"name": "ミキサー", "code": "MIXR", "display_order": 9},
        {"name": "キャリアカー", "code": "CARR", "display_order": 10},
    ]
    for bt in body_types:
        client.table("body_types").upsert(
            bt, on_conflict="code"
        ).execute()
    print(f"  Inserted {len(body_types)} body types.")

    # Seed model series linked to manufacturers
    models = [
        # いすゞ
        {"name": "ギガ", "name_en": "Giga", "maker_code": "ISZ", "category_code": "LARGE"},
        {"name": "フォワード", "name_en": "Forward", "maker_code": "ISZ", "category_code": "MEDIUM"},
        {"name": "エルフ", "name_en": "Elf", "maker_code": "ISZ", "category_code": "SMALL"},
        # 日野
        {"name": "プロフィア", "name_en": "Profia", "maker_code": "HNO", "category_code": "LARGE"},
        {"name": "レンジャー", "name_en": "Ranger", "maker_code": "HNO", "category_code": "MEDIUM"},
        {"name": "デュトロ", "name_en": "Dutro", "maker_code": "HNO", "category_code": "SMALL"},
        # 三菱ふそう
        {"name": "スーパーグレート", "name_en": "Super Great", "maker_code": "MFU", "category_code": "LARGE"},
        {"name": "ファイター", "name_en": "Fighter", "maker_code": "MFU", "category_code": "MEDIUM"},
        {"name": "キャンター", "name_en": "Canter", "maker_code": "MFU", "category_code": "SMALL"},
        # UDトラックス
        {"name": "クオン", "name_en": "Quon", "maker_code": "UDT", "category_code": "LARGE"},
        {"name": "コンドル", "name_en": "Condor", "maker_code": "UDT", "category_code": "MEDIUM"},
    ]
    for model in models:
        client.table("model_series").upsert(
            model, on_conflict="name,maker_code"
        ).execute()
    print(f"  Inserted {len(models)} model series.")

    # Seed depreciation curves (residual value % by age in years)
    # These represent typical market residual values for commercial vehicles
    depreciation_curves = [
        # Large trucks - slower depreciation due to high rebuild value
        {"category_code": "LARGE", "age_years": 0, "residual_rate": 1.00},
        {"category_code": "LARGE", "age_years": 1, "residual_rate": 0.85},
        {"category_code": "LARGE", "age_years": 2, "residual_rate": 0.75},
        {"category_code": "LARGE", "age_years": 3, "residual_rate": 0.65},
        {"category_code": "LARGE", "age_years": 4, "residual_rate": 0.55},
        {"category_code": "LARGE", "age_years": 5, "residual_rate": 0.47},
        {"category_code": "LARGE", "age_years": 6, "residual_rate": 0.40},
        {"category_code": "LARGE", "age_years": 7, "residual_rate": 0.34},
        {"category_code": "LARGE", "age_years": 8, "residual_rate": 0.29},
        {"category_code": "LARGE", "age_years": 9, "residual_rate": 0.25},
        {"category_code": "LARGE", "age_years": 10, "residual_rate": 0.21},
        {"category_code": "LARGE", "age_years": 12, "residual_rate": 0.16},
        {"category_code": "LARGE", "age_years": 15, "residual_rate": 0.10},
        # Medium trucks
        {"category_code": "MEDIUM", "age_years": 0, "residual_rate": 1.00},
        {"category_code": "MEDIUM", "age_years": 1, "residual_rate": 0.82},
        {"category_code": "MEDIUM", "age_years": 2, "residual_rate": 0.70},
        {"category_code": "MEDIUM", "age_years": 3, "residual_rate": 0.60},
        {"category_code": "MEDIUM", "age_years": 4, "residual_rate": 0.50},
        {"category_code": "MEDIUM", "age_years": 5, "residual_rate": 0.42},
        {"category_code": "MEDIUM", "age_years": 6, "residual_rate": 0.35},
        {"category_code": "MEDIUM", "age_years": 7, "residual_rate": 0.29},
        {"category_code": "MEDIUM", "age_years": 8, "residual_rate": 0.24},
        {"category_code": "MEDIUM", "age_years": 9, "residual_rate": 0.20},
        {"category_code": "MEDIUM", "age_years": 10, "residual_rate": 0.17},
        {"category_code": "MEDIUM", "age_years": 12, "residual_rate": 0.12},
        {"category_code": "MEDIUM", "age_years": 15, "residual_rate": 0.07},
        # Small trucks - faster depreciation
        {"category_code": "SMALL", "age_years": 0, "residual_rate": 1.00},
        {"category_code": "SMALL", "age_years": 1, "residual_rate": 0.78},
        {"category_code": "SMALL", "age_years": 2, "residual_rate": 0.65},
        {"category_code": "SMALL", "age_years": 3, "residual_rate": 0.54},
        {"category_code": "SMALL", "age_years": 4, "residual_rate": 0.44},
        {"category_code": "SMALL", "age_years": 5, "residual_rate": 0.36},
        {"category_code": "SMALL", "age_years": 6, "residual_rate": 0.29},
        {"category_code": "SMALL", "age_years": 7, "residual_rate": 0.24},
        {"category_code": "SMALL", "age_years": 8, "residual_rate": 0.19},
        {"category_code": "SMALL", "age_years": 9, "residual_rate": 0.16},
        {"category_code": "SMALL", "age_years": 10, "residual_rate": 0.13},
        {"category_code": "SMALL", "age_years": 12, "residual_rate": 0.08},
        {"category_code": "SMALL", "age_years": 15, "residual_rate": 0.04},
    ]
    for curve in depreciation_curves:
        client.table("depreciation_curves").upsert(
            curve, on_conflict="category_code,age_years"
        ).execute()
    print(f"  Inserted {len(depreciation_curves)} depreciation curve data points.")

    print("\nSeed data inserted successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
