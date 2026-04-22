"""Unit tests for app.services.esg_service.

Covers the definitive calculation methods introduced 2026-04-22 per
docs/uiux_migration_spec.md §9.4.
"""

from __future__ import annotations

import pytest

from app.services.esg_service import (
    CO2_FACTOR_KG_PER_KM,
    GovernanceInputs,
    co2_yoy_change_pct,
    compute_esg_snapshot,
    driver_training_rate_pct,
    governance_grade,
    low_emission_ratio_pct,
    serious_accident_count,
)


class TestCO2:
    def test_yoy_reduction_goes_negative(self) -> None:
        """A fleet that swapped diesel for EV should show a negative YoY delta."""
        prior = [{"fuel_type": "軽油", "avg_km_per_month": 1000}] * 10
        current = (
            [{"fuel_type": "EV", "avg_km_per_month": 1000}] * 2
            + [{"fuel_type": "軽油", "avg_km_per_month": 1000}] * 8
        )
        assert co2_yoy_change_pct(current, prior) < 0

    def test_yoy_no_change_is_zero(self) -> None:
        same = [{"fuel_type": "軽油", "avg_km_per_month": 1000}] * 5
        assert co2_yoy_change_pct(same, same) == 0.0

    def test_empty_prior_guards_divzero(self) -> None:
        assert co2_yoy_change_pct([], []) == 0.0

    def test_ev_is_zero_tailpipe(self) -> None:
        assert CO2_FACTOR_KG_PER_KM["EV"] == 0.0

    def test_low_emission_ratio(self) -> None:
        fleet = (
            [{"fuel_type": "EV"}] * 3
            + [{"fuel_type": "HV"}] * 2
            + [{"fuel_type": "軽油"}] * 5
        )
        assert low_emission_ratio_pct(fleet) == 50

    def test_low_emission_ratio_empty(self) -> None:
        assert low_emission_ratio_pct([]) == 0


class TestAccidents:
    def test_counts_only_major_and_fatal(self) -> None:
        reports = [
            {"severity": "minor"},
            {"severity": "major"},
            {"severity": "fatal"},
            {"severity": "near_miss"},
        ]
        assert serious_accident_count(reports) == 2

    def test_empty_is_zero(self) -> None:
        assert serious_accident_count([]) == 0


class TestTraining:
    def test_all_trained_is_100(self) -> None:
        drivers = [{"training_current": True}] * 10
        assert driver_training_rate_pct(drivers) == 100

    def test_mixed(self) -> None:
        drivers = (
            [{"training_current": True}] * 7
            + [{"training_current": False}] * 3
        )
        assert driver_training_rate_pct(drivers) == 70

    def test_empty_is_zero(self) -> None:
        assert driver_training_rate_pct([]) == 0


class TestGovernance:
    def test_perfect_score_is_a_plus(self) -> None:
        grade, score = governance_grade(
            GovernanceInputs(rbac_coverage=100, yayoi_sync_rate=100, audit_log_rate=100)
        )
        assert grade == "A+"
        assert score == 100.0

    def test_partial_score_drops_grade(self) -> None:
        grade, score = governance_grade(
            GovernanceInputs(rbac_coverage=80, yayoi_sync_rate=80, audit_log_rate=80)
        )
        assert grade == "B"
        assert score == 80.0

    def test_composite_weighting(self) -> None:
        # rbac*0.4 + yayoi*0.3 + audit*0.3 = 100*0.4 + 50*0.3 + 50*0.3 = 70
        grade, score = governance_grade(
            GovernanceInputs(rbac_coverage=100, yayoi_sync_rate=50, audit_log_rate=50)
        )
        assert score == 70.0
        assert grade == "C"

    def test_failing_grade(self) -> None:
        grade, _ = governance_grade(
            GovernanceInputs(rbac_coverage=40, yayoi_sync_rate=40, audit_log_rate=40)
        )
        assert grade == "D"


class TestSnapshot:
    def test_default_snapshot_shape(self) -> None:
        snap = compute_esg_snapshot()
        assert set(snap) == {"environment", "social", "governance"}
        assert snap["environment"]["co2_yoy_pct"] < 0  # wireframe target
        assert snap["social"]["serious_accidents"] == 0
        assert snap["governance"]["grade"] == "A+"

    def test_override_inputs(self) -> None:
        snap = compute_esg_snapshot(
            accidents=[{"severity": "fatal"}],
            drivers=[{"training_current": False}],
        )
        assert snap["social"]["serious_accidents"] == 1
        assert snap["social"]["driver_training_rate_pct"] == 0
