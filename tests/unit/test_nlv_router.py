"""Unit tests for ``app.core.nlv_router``.

Coverage goals:

* Each of the four routes (domestic_resale, export, auction, scrap) is
  individually priced.
* ``choose_best_route`` picks scrap only when every other route is below
  the scrap floor.
* Low-mileage heavy trucks favour export; aging sub-10-year midsize
  units favour domestic.
* Tie-breaking is deterministic (``domestic_resale`` first).
* Closure deadlines honour SLA days.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.nlv_router import (
    CLOSURE_SLA_DAYS,
    SCRAP_FLOOR_JPY,
    choose_best_route,
    estimate_nlv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _heavy_truck(**overrides) -> dict:
    """Baseline heavy-truck fixture."""
    base = {
        "body_type": "ウイング",
        "category": "大型トラック",
        "maker": "いすゞ",
        "model_name": "ギガ",
        "model_year": date.today().year - 4,  # 4-year-old unit
        "mileage_km": 250_000,
        "price_yen": 3_500_000,
        "curb_weight_kg": 8_500,
    }
    base.update(overrides)
    return base


def _small_worthless(**overrides) -> dict:
    """Worn-out light truck that should route to scrap."""
    base = {
        "body_type": "平ボディ",
        "category": "小型トラック",
        "model_year": date.today().year - 25,
        "mileage_km": 950_000,
        "price_yen": 80_000,
        "curb_weight_kg": 2_000,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Per-route estimation sanity
# ---------------------------------------------------------------------------


class TestEstimateNlv:
    def test_four_routes_all_produce_estimates(self):
        veh = _heavy_truck()
        seen = {}
        for route in ("domestic_resale", "export", "auction", "scrap"):
            est = estimate_nlv(veh, routing_option=route)
            assert est.route == route
            assert est.gross_proceeds_jpy > 0
            assert est.cost_deductions_jpy >= 0
            # Net can theoretically be negative for high-cost routes; assert
            # the identity gross - costs == net (allow ±1 JPY rounding).
            assert abs(
                est.gross_proceeds_jpy - est.cost_deductions_jpy - est.net_jpy
            ) <= 1
            seen[route] = est
        assert len(seen) == 4

    def test_unknown_route_raises(self):
        with pytest.raises(ValueError):
            estimate_nlv(_heavy_truck(), routing_option="mars_colony")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Scrap selection
# ---------------------------------------------------------------------------


class TestScrapChoice:
    def test_scrap_chosen_when_everything_else_below_floor(self):
        decision = choose_best_route(_small_worthless())
        # With an 80k base price, every non-scrap route nets well under the
        # 150k scrap floor, so scrap should win.
        assert decision.route == "scrap"
        assert decision.nlv_jpy > 0
        # Closure SLA is 31 days for scrap
        expected_deadline = date.today() + timedelta(days=CLOSURE_SLA_DAYS["scrap"])
        assert decision.closure_deadline == expected_deadline

    def test_scrap_not_chosen_when_other_route_clears_floor(self):
        decision = choose_best_route(_heavy_truck())
        assert decision.route != "scrap"
        # At least one alternative is scrap (included for audit).
        alt_routes = {a.route for a in decision.alternatives}
        assert "scrap" in alt_routes


# ---------------------------------------------------------------------------
# 3. Export vs Domestic crossover
# ---------------------------------------------------------------------------


class TestExportVsDomestic:
    def test_low_mileage_heavy_truck_favours_export(self):
        veh = _heavy_truck(mileage_km=120_000)  # low-mileage => export premium
        decision = choose_best_route(veh)
        assert decision.route == "export"

    def test_high_mileage_heavy_truck_does_not_receive_export_bonus(self):
        """Mileage >= 300k disables the low-mileage export bonus."""
        low = estimate_nlv(_heavy_truck(mileage_km=120_000), routing_option="export")
        high = estimate_nlv(_heavy_truck(mileage_km=400_000), routing_option="export")
        # The low-mileage bonus is +0.05 on the multiplier, so gross proceeds
        # must be strictly larger for the low-mileage case.
        assert low.gross_proceeds_jpy > high.gross_proceeds_jpy


# ---------------------------------------------------------------------------
# 4. Deterministic tie-breaking
# ---------------------------------------------------------------------------


class TestTieBreaking:
    def test_tie_broken_toward_domestic_resale(self, monkeypatch):
        """When every route returns the same NLV, domestic wins by tie-break."""
        from app.core import nlv_router as mod
        from app.models.liquidation import CostBreakdown, NLVEstimate

        def _flat_estimate(vehicle, market_data=None, routing_option="domestic_resale"):
            return NLVEstimate(
                route=routing_option,
                gross_proceeds_jpy=1_000_000,
                cost_deductions_jpy=100_000,
                net_jpy=900_000,
                cost_breakdown=CostBreakdown(transport=100_000),
                confidence=0.5,
                rationale="tied",
            )

        monkeypatch.setattr(mod, "estimate_nlv", _flat_estimate)

        decision = choose_best_route(_heavy_truck())
        assert decision.route == "domestic_resale"
        assert decision.nlv_jpy == 900_000

    def test_best_route_has_highest_net_vs_alternatives(self):
        decision = choose_best_route(_heavy_truck(mileage_km=120_000))
        # Chosen NLV must be >= every alternative.
        for alt in decision.alternatives:
            assert decision.nlv_jpy >= alt.net_jpy


# ---------------------------------------------------------------------------
# 5. SLA deadline plumbing
# ---------------------------------------------------------------------------


class TestSlaDeadlines:
    def test_closure_deadline_matches_sla_days(self):
        today = date(2026, 4, 17)
        decision = choose_best_route(_heavy_truck(mileage_km=120_000), today=today)
        expected = today + timedelta(days=CLOSURE_SLA_DAYS[decision.route])
        assert decision.closure_deadline == expected

    def test_sla_table_covers_all_four_routes(self):
        assert set(CLOSURE_SLA_DAYS.keys()) == {
            "domestic_resale",
            "export",
            "auction",
            "scrap",
        }
        assert CLOSURE_SLA_DAYS["export"] == 74
        assert CLOSURE_SLA_DAYS["domestic_resale"] == 31


# ---------------------------------------------------------------------------
# 6. Scrap-floor override
# ---------------------------------------------------------------------------


class TestScrapFloorOverride:
    def test_override_forces_non_scrap(self):
        """Raising the floor very high still cannot make scrap win when a
        non-scrap route exceeds it — confirms filter semantics."""
        decision = choose_best_route(
            _heavy_truck(), scrap_floor_jpy=10  # effectively disables scrap
        )
        assert decision.route != "scrap"

    def test_default_floor_constant(self):
        assert SCRAP_FLOOR_JPY == 150_000
