"""Sample-data fixtures for the 松プラン pages.

Each submodule owns one domain. Routes call these when Supabase returns
empty / unreachable so the UI stays useful for demos + local dev.

Ownership map (2026-04-22 wave, docs/simulation_contract_usage.md §5):
  - masters.py     : Agent #2 (simulation dropdowns)
  - funds.py       : Agent #4 (Dashboard / Portfolio / Fund)
  - vehicles.py    : Agent #5 (Inventory cards + fleet KPIs)
  - invoices.py    : Agent #5 (Invoice table)
  - risk_alerts.py : Agent #5 (Risk page alerts)
  - scrape_jobs.py : Agent #5 (Scrape page jobs)

Each module exposes a public `get_*()` function returning plain lists/dicts
that templates consume. Signatures are fixed here so cross-module reads
(e.g. Dashboard KPI reading from vehicles.py) are stable.
"""

from __future__ import annotations

from .masters import get_makers, get_models_by_maker, get_body_types, get_categories
from .funds import get_funds, get_nav_series, get_monthly_cashflow
from .vehicles import get_vehicles, get_fleet_kpi
from .invoices import get_invoices, get_invoice_kpi
from .risk_alerts import get_risk_alerts, get_risk_kpi
from .scrape_jobs import get_scrape_jobs, get_scrape_kpi

__all__ = [
    "get_makers",
    "get_models_by_maker",
    "get_body_types",
    "get_categories",
    "get_funds",
    "get_nav_series",
    "get_monthly_cashflow",
    "get_vehicles",
    "get_fleet_kpi",
    "get_invoices",
    "get_invoice_kpi",
    "get_risk_alerts",
    "get_risk_kpi",
    "get_scrape_jobs",
    "get_scrape_kpi",
]
