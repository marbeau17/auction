"""Unit tests for the ESG / transition-finance scorer (Phase-3c)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.esg_scorer import (
    CO2_KG_PER_LITER,
    DEFAULT_ANNUAL_KM,
    FUEL_EFFICIENCY_TABLE,
    TRANSITION_CO2_THRESHOLD_G_PER_KM,
    estimate_co2_kg,
    grade_from_co2_intensity,
    lookup_fuel_efficiency,
    score_fleet,
    score_vehicle,
)
from app.models.esg import FuelType


# ==========================================================================
# CO2 math
# ==========================================================================


def test_estimate_co2_diesel_math_is_correct():
    """60,000 km ÷ 4.0 km/L × 2.58 kg/L ≈ 38,700 kg CO2."""
    est = estimate_co2_kg(
        km_driven=60_000,
        vehicle_class="大型",
        body_type="ウイング",
        fuel_type="diesel",
    )
    expected_liters = 60_000 / 4.0
    expected_co2 = expected_liters * CO2_KG_PER_LITER[FuelType.DIESEL]

    assert est.fuel_liters == pytest.approx(expected_liters, rel=1e-3)
    assert est.co2_kg == pytest.approx(expected_co2, rel=1e-3)
    assert "km/L" in est.methodology_note


def test_estimate_co2_gasoline_uses_gasoline_factor():
    est = estimate_co2_kg(
        km_driven=10_000,
        vehicle_class="小型",
        body_type="平ボディ",
        fuel_type="gasoline",
    )
    # 10,000 / 8.0 = 1,250 L × 2.32 = 2,900 kg
    assert est.co2_kg == pytest.approx(1_250 * 2.32, rel=1e-3)


def test_estimate_co2_ev_is_zero():
    est = estimate_co2_kg(
        km_driven=50_000,
        vehicle_class="小型",
        body_type="バンボディ",
        fuel_type="ev",
    )
    assert est.co2_kg == 0.0
    assert est.fuel_liters == 0.0
    assert "EV" in est.methodology_note


# ==========================================================================
# Grade thresholds
# ==========================================================================


@pytest.mark.parametrize(
    "intensity,expected",
    [
        (50.0, "A"),
        (150.0, "A"),      # boundary — inclusive
        (150.01, "B"),
        (399.9, "B"),
        (400.0, "B"),      # boundary
        (500.0, "C"),
        (700.0, "C"),      # boundary
        (900.0, "D"),
        (1_000.0, "D"),    # boundary
        (1_200.0, "E"),
    ],
)
def test_grade_thresholds(intensity: float, expected: str):
    assert grade_from_co2_intensity(intensity) == expected


# ==========================================================================
# Transition eligibility
# ==========================================================================


def test_ev_vehicle_is_transition_eligible():
    vehicle = {
        "id": str(uuid4()),
        "vehicle_class": "小型",
        "body_type": "バンボディ",
        "fuel_type": "ev",
    }
    score = score_vehicle(vehicle, annual_km=40_000)
    assert score.fuel_type == FuelType.EV
    assert score.co2_kg_year == 0.0
    assert score.transition_eligibility is True
    assert score.grade == "A"


def test_large_diesel_truck_not_transition_eligible():
    """大型ウイング @ 60,000 km/year: ~645 g CO2/km — above 600 g/km threshold."""
    vehicle = {
        "id": str(uuid4()),
        "vehicle_class": "大型",
        "body_type": "ウイング",
        "fuel_type": "diesel",
    }
    score = score_vehicle(vehicle, annual_km=60_000)
    assert score.fuel_type == FuelType.DIESEL
    assert score.co2_intensity_g_per_km > TRANSITION_CO2_THRESHOLD_G_PER_KM
    assert score.transition_eligibility is False
    assert score.grade in {"C", "D", "E"}


def test_hybrid_is_always_transition_eligible():
    vehicle = {
        "id": str(uuid4()),
        "vehicle_class": "大型",
        "body_type": "ウイング",
        "fuel_type": "hybrid",
    }
    score = score_vehicle(vehicle, annual_km=60_000)
    assert score.fuel_type == FuelType.HYBRID
    assert score.transition_eligibility is True


# ==========================================================================
# Unknown body_type fallback
# ==========================================================================


def test_unknown_body_type_falls_back_to_class_default():
    km_per_l, note = lookup_fuel_efficiency("中型", "宇宙船ボディ")
    # 中型 class fallback
    assert km_per_l == 6.0
    assert "fallback" in note.lower()


def test_completely_unknown_uses_global_default():
    km_per_l, note = lookup_fuel_efficiency(None, None)
    assert km_per_l == 6.0  # DEFAULT_KM_PER_L
    assert "fallback" in note.lower()


def test_known_table_entry_hits_reference():
    km_per_l, note = lookup_fuel_efficiency("小型", "平ボディ")
    assert km_per_l == FUEL_EFFICIENCY_TABLE[("小型", "平ボディ")]
    assert km_per_l == 8.0
    assert "reference" in note.lower()


def test_unknown_body_type_still_produces_a_score():
    vehicle = {
        "id": str(uuid4()),
        "vehicle_class": "中型",
        "body_type": "特殊架装",
        "fuel_type": "diesel",
    }
    score = score_vehicle(vehicle)
    # Should produce a finite CO2 estimate using the 中型 class fallback
    assert score.co2_kg_year > 0
    assert score.grade in {"A", "B", "C", "D", "E"}
    assert score.annual_km == DEFAULT_ANNUAL_KM


# ==========================================================================
# Fleet aggregation
# ==========================================================================


class _FakeSupabaseQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def execute(self):
        return MagicMock(data=self._data)


class _FakeSupabase:
    def __init__(self, sab_rows, vehicles_rows):
        self._sab_rows = sab_rows
        self._vehicles_rows = vehicles_rows

    def table(self, name: str):
        if name == "secured_asset_blocks":
            return _FakeSupabaseQuery(self._sab_rows)
        if name == "vehicles":
            return _FakeSupabaseQuery(self._vehicles_rows)
        return _FakeSupabaseQuery([])


def test_score_fleet_aggregates_vehicles_and_transition_pct():
    v1_id, v2_id, v3_id = uuid4(), uuid4(), uuid4()

    sab_rows = [
        {"vehicle_id": str(v1_id)},
        {"vehicle_id": str(v2_id)},
        {"vehicle_id": str(v3_id)},
    ]
    vehicles_rows = [
        {
            "id": str(v1_id),
            "vehicle_class": "小型",
            "body_type": "バンボディ",
            "fuel_type": "ev",
        },
        {
            "id": str(v2_id),
            "vehicle_class": "大型",
            "body_type": "ウイング",
            "fuel_type": "diesel",
        },
        {
            "id": str(v3_id),
            "vehicle_class": "小型",
            "body_type": "平ボディ",
            "fuel_type": "hybrid",
        },
    ]

    fake_sb = _FakeSupabase(sab_rows, vehicles_rows)
    fund_id = uuid4()

    snapshot = score_fleet(fund_id=str(fund_id), supabase=fake_sb, annual_km=60_000)

    # 3 vehicles, 2 are transition-eligible (EV + hybrid)
    assert snapshot.vehicles_count == 3
    assert snapshot.transition_eligible_count == 2
    assert snapshot.transition_pct == pytest.approx(2 / 3 * 100, rel=1e-3)
    assert snapshot.total_tco2_year > 0  # diesel truck contributes
    assert snapshot.avg_co2_intensity_g_per_km > 0
    assert snapshot.weighted_avg_grade in {"A", "B", "C", "D", "E"}
    assert len(snapshot.vehicles_scored) == 3


def test_score_fleet_with_no_vehicles_returns_zero_metrics():
    fake_sb = _FakeSupabase(sab_rows=[], vehicles_rows=[])
    snapshot = score_fleet(fund_id=str(uuid4()), supabase=fake_sb)

    assert snapshot.vehicles_count == 0
    assert snapshot.transition_eligible_count == 0
    assert snapshot.transition_pct == 0.0
    assert snapshot.total_tco2_year == 0.0
    assert snapshot.avg_co2_intensity_g_per_km == 0.0
