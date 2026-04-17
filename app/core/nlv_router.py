"""NLV (Net Liquidation Value) routing engine.

Computes the Net Liquidation Value for a vehicle across the four disposal
routes defined in ``docs/global_liquidation_spec.md``:

    1. ``domestic_resale`` — Japanese auction / wholesale.
    2. ``export``          — Cross-border export to SEA / AFR / MDE / etc.
    3. ``auction``         — Dedicated domestic B2B auction channel (USS etc.).
    4. ``scrap``           — Parts / metal scrap fallback.

The ``choose_best_route`` routine compares all four estimates and returns
the one with the highest NLV. Heuristics (documented inline) favour
export for low-mileage heavy trucks and domestic resale for aging
sub-10-year units. Scrap is chosen only when every other route yields
an NLV below ``SCRAP_FLOOR_JPY``.

The engine deliberately keeps logic deterministic and dependency-free so
it can run in unit tests without hitting the database. Real market data
lookups (region premium tables, tariff DB, transport cost DB) will be
injected via the ``market_data`` argument in later phases; for now we
accept a simple dict shape and fall back to conservative defaults.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from app.core.market_analysis import MarketAnalyzer
from app.models.liquidation import (
    CostBreakdown,
    NLVEstimate,
    Route,
    RoutingDecision,
)

# ---------------------------------------------------------------------------
# Constants — tuned from the spec (will be data-driven in Phase-2D)
# ---------------------------------------------------------------------------

#: Threshold below which scrap becomes the recommended route.
SCRAP_FLOOR_JPY: int = 150_000

#: SLA closure deadlines (days from detection) per route.
CLOSURE_SLA_DAYS: dict[Route, int] = {
    "domestic_resale": 31,
    "auction": 45,
    "export": 74,
    "scrap": 31,
}

#: Gross-proceeds multipliers used when no live market data is available.
#: Values derived from spec §2.1 (price premium table — middle-of-range).
_DEFAULT_EXPORT_PREMIUM: float = 1.15  # SEA/AFR wing-truck price premium
_DEFAULT_AUCTION_DISCOUNT: float = 0.92  # auction vs. estimated retail
_DEFAULT_DOMESTIC_DISCOUNT: float = 0.95  # wholesale vs. estimated retail
_DEFAULT_SCRAP_RATE_PER_KG: int = 40  # JPY / kg of curb weight

#: Cost defaults (JPY) — conservative midpoints from spec §2.2.
_DOMESTIC_TRANSPORT_JPY: int = 60_000
_AUCTION_TRANSPORT_JPY: int = 45_000
_AUCTION_COMMISSION_JPY: int = 50_000
_EXPORT_OCEAN_FREIGHT_JPY: int = 350_000
_EXPORT_YARD_JPY: int = 60_000
_EXPORT_INSPECTION_JPY: int = 18_000  # JEVIC
_EXPORT_COMMISSION_JPY: int = 25_000  # broker
_SCRAP_TRANSPORT_JPY: int = 20_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Dict-or-attribute getter (supports both Pydantic models and raw dicts)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _base_price_jpy(vehicle: Any, market_data: Optional[dict[str, Any]]) -> int:
    """Estimate the baseline domestic retail price for the vehicle.

    Priority:
      1. ``market_data['estimated_retail_jpy']`` if provided.
      2. ``MarketAnalyzer`` median of ``market_data['comparable_prices']``.
      3. ``vehicle.price_yen`` fallback.
      4. Hard-coded ¥1,000,000 last-resort sentinel (so tests don't divide by zero).
    """
    if market_data:
        retail = market_data.get("estimated_retail_jpy")
        if retail:
            return int(retail)

        comps = market_data.get("comparable_prices") or []
        if comps:
            analyzer = MarketAnalyzer()
            stats = analyzer.calculate_statistics(list(comps))
            median = stats.get("median", 0.0)
            if median > 0:
                return int(median)

    price = _get(vehicle, "price_yen") or _get(vehicle, "price_jpy")
    if price:
        return int(price)
    return 1_000_000


def _is_heavy_truck(vehicle: Any) -> bool:
    """Rough classifier — used by export-favoring heuristic."""
    category = (_get(vehicle, "category") or _get(vehicle, "vehicle_category") or "").lower()
    body = (_get(vehicle, "body_type") or "").lower()
    # Japanese / English tokens: 大型 / heavy / large / trailer / tractor
    heavy_tokens = ("大型", "heavy", "large", "trailer", "tractor", "トレーラー")
    return any(tok in category for tok in heavy_tokens) or any(
        tok in body for tok in heavy_tokens
    )


def _curb_weight_kg(vehicle: Any) -> int:
    weight = _get(vehicle, "curb_weight_kg") or _get(vehicle, "weight_kg")
    if weight:
        return int(weight)
    # Fallback: crude lookup on category
    if _is_heavy_truck(vehicle):
        return 8_000
    return 3_500


def _vehicle_age_years(vehicle: Any, today: Optional[date] = None) -> int:
    model_year = _get(vehicle, "model_year")
    if not model_year:
        return 0
    today = today or date.today()
    return max(0, today.year - int(model_year))


# ---------------------------------------------------------------------------
# Per-route estimators
# ---------------------------------------------------------------------------


def _estimate_domestic(
    vehicle: Any, market_data: Optional[dict[str, Any]], base: int
) -> NLVEstimate:
    gross = int(base * _DEFAULT_DOMESTIC_DISCOUNT)
    costs = CostBreakdown(
        transport=_DOMESTIC_TRANSPORT_JPY,
        commission=int(gross * 0.03),  # 3 % wholesale commission
    )
    net = gross - costs.total
    return NLVEstimate(
        route="domestic_resale",
        gross_proceeds_jpy=gross,
        cost_deductions_jpy=costs.total,
        net_jpy=net,
        cost_breakdown=costs,
        confidence=0.8,
        rationale="Domestic wholesale at 95% of retail less 3% commission.",
    )


def _estimate_auction(
    vehicle: Any, market_data: Optional[dict[str, Any]], base: int
) -> NLVEstimate:
    gross = int(base * _DEFAULT_AUCTION_DISCOUNT)
    costs = CostBreakdown(
        transport=_AUCTION_TRANSPORT_JPY,
        commission=_AUCTION_COMMISSION_JPY,
    )
    net = gross - costs.total
    return NLVEstimate(
        route="auction",
        gross_proceeds_jpy=gross,
        cost_deductions_jpy=costs.total,
        net_jpy=net,
        cost_breakdown=costs,
        confidence=0.85,
        rationale="USS-style dealer auction at 92% of retail plus fixed commission.",
    )


def _estimate_export(
    vehicle: Any, market_data: Optional[dict[str, Any]], base: int
) -> NLVEstimate:
    premium = _DEFAULT_EXPORT_PREMIUM
    if market_data and "export_premium" in market_data:
        premium = float(market_data["export_premium"])

    # Heuristic: low-mileage heavy trucks earn additional premium (spec §5).
    mileage = int(_get(vehicle, "mileage_km") or 0)
    if _is_heavy_truck(vehicle) and mileage and mileage < 300_000:
        premium += 0.10

    gross = int(base * premium)

    customs = int(gross * 0.10)  # midpoint tariff 5-25 %
    costs = CostBreakdown(
        transport=_EXPORT_OCEAN_FREIGHT_JPY,
        customs=customs,
        inspection=_EXPORT_INSPECTION_JPY,
        yard=_EXPORT_YARD_JPY,
        commission=_EXPORT_COMMISSION_JPY,
    )
    net = gross - costs.total
    return NLVEstimate(
        route="export",
        gross_proceeds_jpy=gross,
        cost_deductions_jpy=costs.total,
        net_jpy=net,
        cost_breakdown=costs,
        confidence=0.65,
        rationale=(
            f"Export premium {premium:.2f}x domestic retail; "
            "heavy-truck low-mileage bonus applied when applicable."
        ),
    )


def _estimate_scrap(
    vehicle: Any, market_data: Optional[dict[str, Any]], base: int
) -> NLVEstimate:
    weight = _curb_weight_kg(vehicle)
    rate = _DEFAULT_SCRAP_RATE_PER_KG
    if market_data and "scrap_rate_per_kg" in market_data:
        rate = int(market_data["scrap_rate_per_kg"])
    gross = weight * rate
    costs = CostBreakdown(transport=_SCRAP_TRANSPORT_JPY)
    net = gross - costs.total
    return NLVEstimate(
        route="scrap",
        gross_proceeds_jpy=gross,
        cost_deductions_jpy=costs.total,
        net_jpy=net,
        cost_breakdown=costs,
        confidence=0.95,
        rationale=f"Scrap @ ¥{rate}/kg x {weight}kg curb weight.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def estimate_nlv(
    vehicle: Any,
    market_data: Optional[dict[str, Any]] = None,
    routing_option: Route = "domestic_resale",
) -> NLVEstimate:
    """Estimate NLV for a single route.

    Args:
        vehicle: Vehicle record (Pydantic model or dict). Fields used:
            ``price_yen``/``price_jpy``, ``model_year``, ``mileage_km``,
            ``body_type``, ``category`` / ``vehicle_category``,
            ``curb_weight_kg``.
        market_data: Optional dict with keys ``estimated_retail_jpy``,
            ``comparable_prices``, ``export_premium``,
            ``scrap_rate_per_kg``.
        routing_option: Which of the four routes to estimate.

    Returns:
        NLVEstimate for the requested route.
    """
    base = _base_price_jpy(vehicle, market_data)

    if routing_option == "domestic_resale":
        return _estimate_domestic(vehicle, market_data, base)
    if routing_option == "auction":
        return _estimate_auction(vehicle, market_data, base)
    if routing_option == "export":
        return _estimate_export(vehicle, market_data, base)
    if routing_option == "scrap":
        return _estimate_scrap(vehicle, market_data, base)

    raise ValueError(f"Unknown routing_option: {routing_option}")


# Deterministic tie-break order: when two routes score identically in
# ``choose_best_route`` we prefer the channel that (a) realises cash
# fastest, then (b) carries lowest execution risk.
_TIE_BREAK_ORDER: tuple[Route, ...] = (
    "domestic_resale",
    "auction",
    "export",
    "scrap",
)


def choose_best_route(
    vehicle: Any,
    market_data: Optional[dict[str, Any]] = None,
    *,
    scrap_floor_jpy: int = SCRAP_FLOOR_JPY,
    today: Optional[date] = None,
) -> RoutingDecision:
    """Compare all four routes and pick the highest-NLV option.

    Heuristics (documented inline):
      * Scrap is filtered out whenever any other route yields NLV
        >= ``scrap_floor_jpy``. Scrap wins only if every route is below
        that floor (i.e. vehicle is effectively worthless).
      * Low-mileage heavy trucks receive an export premium (handled in
        ``_estimate_export``) — this naturally tilts the comparison
        toward export for that segment.
      * Aging sub-10-year units: when export and domestic NLVs are
        within 5 %, we apply a small domestic bias (+2 %) because
        export logistics get harder on older units with emissions /
        year-restriction risk.
      * Ties are broken by ``_TIE_BREAK_ORDER`` (domestic first).
    """
    today = today or date.today()
    all_routes: list[Route] = ["domestic_resale", "auction", "export", "scrap"]
    estimates: dict[Route, NLVEstimate] = {
        r: estimate_nlv(vehicle, market_data, routing_option=r) for r in all_routes
    }

    # Apply aging-bias tweak: for aging (7-10 year) units that are
    # approaching destination-country year limits, domestic gets a +2 %
    # nudge when export/domestic NLVs are within 5 %. This reflects the
    # execution risk of exporting borderline-age units per spec §5.
    age = _vehicle_age_years(vehicle, today)
    if 7 <= age < 10:
        dom = estimates["domestic_resale"]
        exp = estimates["export"]
        if exp.net_jpy > 0 and dom.net_jpy > 0:
            spread = abs(exp.net_jpy - dom.net_jpy) / max(dom.net_jpy, 1)
            if spread < 0.05 and dom.net_jpy <= exp.net_jpy:
                bumped = int(dom.net_jpy * 1.02)
                estimates["domestic_resale"] = dom.model_copy(
                    update={
                        "net_jpy": bumped,
                        "rationale": (
                            (dom.rationale or "")
                            + " | +2% aging-bias applied (7-10 year unit)."
                        ),
                    }
                )

    # Scrap-floor filter: only allow scrap if every non-scrap route is worthless.
    non_scrap = {r: e for r, e in estimates.items() if r != "scrap"}
    best_non_scrap_net = max((e.net_jpy for e in non_scrap.values()), default=0)
    if best_non_scrap_net >= scrap_floor_jpy:
        candidates = non_scrap
    else:
        candidates = estimates

    # Pick highest net; break ties via fixed order.
    def _key(route: Route) -> tuple[int, int]:
        # primary: -net (so max via min-sort); secondary: tie-break index.
        return (-candidates[route].net_jpy, _TIE_BREAK_ORDER.index(route))

    best_route = min(candidates.keys(), key=_key)
    best_estimate = candidates[best_route]

    closure_deadline = today + timedelta(days=CLOSURE_SLA_DAYS[best_route])
    alternatives = [estimates[r] for r in all_routes if r != best_route]

    return RoutingDecision(
        route=best_route,
        nlv_jpy=best_estimate.net_jpy,
        cost_breakdown=best_estimate.cost_breakdown,
        closure_deadline=closure_deadline,
        alternatives=alternatives,
        rationale=best_estimate.rationale,
    )


__all__ = [
    "SCRAP_FLOOR_JPY",
    "CLOSURE_SLA_DAYS",
    "estimate_nlv",
    "choose_best_route",
]
