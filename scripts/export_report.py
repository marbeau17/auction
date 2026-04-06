from __future__ import annotations
"""Export simulation history as CSV report."""
import argparse
import csv
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.supabase_client import get_supabase_client


def export_simulation_history(
    output_path: str,
    days: int = 30,
    category_code: str | None = None,
    maker_code: str | None = None,
):
    """Export simulation history records to a CSV file.

    Args:
        output_path: Path for the output CSV file.
        days: Number of days of history to export (default 30).
        category_code: Optional filter by vehicle category code.
        maker_code: Optional filter by manufacturer code.
    """
    client = get_supabase_client()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()

    query = (
        client.table("simulation_history")
        .select(
            "id, created_at, vehicle_category, manufacturer, model_series, "
            "body_type, model_year, mileage_km, purchase_price, "
            "lease_term_months, monthly_lease_amount, residual_value, "
            "total_lease_revenue, profit_margin, irr"
        )
        .gte("created_at", since)
        .order("created_at", desc=True)
    )

    if category_code:
        query = query.eq("vehicle_category", category_code)
    if maker_code:
        query = query.eq("manufacturer", maker_code)

    result = query.execute()
    rows = result.data

    if not rows:
        print("No simulation records found for the given criteria.")
        return

    fieldnames = [
        "id",
        "created_at",
        "vehicle_category",
        "manufacturer",
        "model_series",
        "body_type",
        "model_year",
        "mileage_km",
        "purchase_price",
        "lease_term_months",
        "monthly_lease_amount",
        "residual_value",
        "total_lease_revenue",
        "profit_margin",
        "irr",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"Exported {len(rows)} records to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export simulation history as CSV report."
    )
    parser.add_argument(
        "-o",
        "--output",
        default=f"simulation_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Output CSV file path (default: simulation_report_<timestamp>.csv)",
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=30,
        help="Number of days of history to export (default: 30)",
    )
    parser.add_argument(
        "-c",
        "--category",
        default=None,
        help="Filter by vehicle category code (e.g. LARGE, MEDIUM, SMALL)",
    )
    parser.add_argument(
        "-m",
        "--maker",
        default=None,
        help="Filter by manufacturer code (e.g. ISZ, HNO, MFU, UDT)",
    )

    args = parser.parse_args()
    export_simulation_history(
        output_path=args.output,
        days=args.days,
        category_code=args.category,
        maker_code=args.maker,
    )


if __name__ == "__main__":
    main()
