"""Unit tests for ``app.core.contract_generator.ContractGenerator``.

Focuses on pure mapping/context logic so these tests run without docxtpl
or the real DOCX templates.

Checks:

* ``TEMPLATES`` covers all 9 contract types (spec §3.3.1)
* ``CONTRACT_NAMES`` covers the same 9 keys
* ``PARTY_MAPPING`` is consistent: keys match TEMPLATES, values are tuples
  of (party_a_role, party_b_role)
* ``_build_context`` returns the expected common / party / vehicle /
  pricing keys using a sample stakeholders dict
* Type-specific variables are injected correctly for
  ``private_placement`` / ``asset_management`` / ``accounting_firm``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.contract_generator import ContractGenerator


EXPECTED_CONTRACT_TYPES = {
    "tk_agreement",
    "sales_agreement",
    "master_lease",
    "sublease_agreement",
    "private_placement",
    "customer_referral",
    "asset_management",
    "accounting_firm",
    "accounting_association",
}


@pytest.fixture
def gen() -> ContractGenerator:
    # template_dir does not matter here; we never touch the filesystem.
    return ContractGenerator(template_dir=Path("/tmp/nonexistent"))


@pytest.fixture
def stakeholders() -> dict:
    """Minimal stakeholders dict covering every role used in PARTY_MAPPING."""
    return {
        "spc": {
            "company_name": "CVLPOS第1号SPC",
            "address": "東京都千代田区1-1-1",
            "representative_name": "代表太郎",
        },
        "investor": {
            "company_name": "匿名組合員A",
            "address": "東京都港区2-2-2",
            "representative_name": "投資花子",
        },
        "end_user": {
            "company_name": "運送株式会社",
            "address": "千葉県船橋市3-3-3",
            "representative_name": "運送次郎",
        },
        "operator": {
            "company_name": "オペレーター株式会社",
            "address": "東京都新宿区4-4-4",
            "representative_name": "運営三郎",
        },
        "private_placement_agent": {
            "company_name": "私募取扱業者",
            "address": "東京都中央区5-5-5",
            "representative_name": "私募四郎",
        },
        "asset_manager": {
            "company_name": "AM株式会社",
            "address": "東京都港区6-6-6",
            "representative_name": "AM五郎",
        },
        "accounting_firm": {
            "company_name": "会計事務所",
            "address": "東京都渋谷区7-7-7",
            "representative_name": "会計六郎",
        },
        "accounting_delegate": {
            "company_name": "一般社団法人CVLPOS",
            "address": "東京都千代田区8-8-8",
            "representative_name": "理事七郎",
        },
    }


@pytest.fixture
def pricing_result() -> dict:
    return {
        "maker": "いすゞ",
        "model": "エルフ",
        "body_type": "平ボディ",
        "vehicle_year": 2020,
        "target_mileage_km": 85_000,
        "vehicle_chassis_number": "NMR85-1234567",
        "vehicle_registration_number": "品川100あ1234",
        "purchase_price_yen": 3_500_000,
        "lease_monthly_yen": 180_000,
        "lease_term_months": 36,
        "total_lease_revenue_yen": 6_480_000,
        "target_yield_rate": "8.0%",
        "lease_start_date": "2026-01-01",
        "lease_end_date": "2028-12-31",
        "payment_day": "25",
        "placement_fee_rate": "3.0%",
        "am_fee_rate": "2.0%",
    }


@pytest.fixture
def fund_info() -> dict:
    return {"fund_name": "商用車リースバックファンド1号"}


# ---------------------------------------------------------------------------
# Mapping consistency
# ---------------------------------------------------------------------------


class TestMappingConsistency:

    def test_templates_covers_all_9_types(self):
        assert set(ContractGenerator.TEMPLATES.keys()) == EXPECTED_CONTRACT_TYPES
        assert len(ContractGenerator.TEMPLATES) == 9

    def test_contract_names_covers_all_9_types(self):
        assert set(ContractGenerator.CONTRACT_NAMES.keys()) == EXPECTED_CONTRACT_TYPES
        assert len(ContractGenerator.CONTRACT_NAMES) == 9

    def test_party_mapping_keys_match_templates(self):
        assert set(ContractGenerator.PARTY_MAPPING.keys()) == set(
            ContractGenerator.TEMPLATES.keys()
        )

    def test_party_mapping_values_are_tuples_of_two_roles(self):
        for k, v in ContractGenerator.PARTY_MAPPING.items():
            assert isinstance(v, tuple), f"{k} is not a tuple"
            assert len(v) == 2, f"{k} should be (party_a_role, party_b_role)"
            assert all(isinstance(role, str) and role for role in v), (
                f"{k} has empty/non-string role"
            )

    @pytest.mark.parametrize(
        "contract_type,expected",
        [
            ("tk_agreement", ("spc", "investor")),
            ("sales_agreement", ("end_user", "spc")),
            ("master_lease", ("spc", "operator")),
            ("sublease_agreement", ("operator", "end_user")),
            ("private_placement", ("spc", "private_placement_agent")),
            ("asset_management", ("spc", "asset_manager")),
            ("accounting_firm", ("spc", "accounting_firm")),
            ("accounting_association", ("spc", "accounting_delegate")),
        ],
    )
    def test_party_mapping_spec_3_3_1(
        self, contract_type: str, expected: tuple
    ):
        assert ContractGenerator.PARTY_MAPPING[contract_type] == expected


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


class TestBuildContext:

    def test_common_variables_present(
        self, gen, stakeholders, pricing_result, fund_info
    ):
        ctx = gen._build_context(
            "master_lease", stakeholders, pricing_result, fund_info
        )
        for key in ("contract_date", "effective_date", "fund_name"):
            assert key in ctx
        assert ctx["fund_name"] == "商用車リースバックファンド1号"

    def test_party_variables_match_mapping(
        self, gen, stakeholders, pricing_result, fund_info
    ):
        # master_lease -> (spc, operator)
        ctx = gen._build_context(
            "master_lease", stakeholders, pricing_result, fund_info
        )
        assert ctx["party_a_name"] == stakeholders["spc"]["company_name"]
        assert ctx["party_b_name"] == stakeholders["operator"]["company_name"]
        assert ctx["party_a_representative"] == "代表太郎"
        assert ctx["party_b_representative"] == "運営三郎"

    def test_vehicle_and_pricing_variables(
        self, gen, stakeholders, pricing_result, fund_info
    ):
        ctx = gen._build_context(
            "sales_agreement", stakeholders, pricing_result, fund_info
        )
        assert ctx["vehicle_maker"] == "いすゞ"
        assert ctx["vehicle_model"] == "エルフ"
        # Mileage should be a comma-formatted string with km suffix.
        assert ctx["vehicle_mileage"] == "85,000km"
        # Thousands separator formatting applied on purchase_price
        assert ctx["purchase_price"] == "3,500,000"
        assert ctx["purchase_price_num"] == 3_500_000
        assert ctx["monthly_lease_fee"] == "180,000"
        assert ctx["lease_term_months"] == 36

    def test_private_placement_fee_amount_computed(
        self, gen, stakeholders, pricing_result, fund_info
    ):
        ctx = gen._build_context(
            "private_placement", stakeholders, pricing_result, fund_info
        )
        # 3,500,000 * 3% = 105,000
        assert ctx["placement_fee_rate"] == "3.0%"
        assert ctx["placement_fee_amount"] == "105,000"
        assert ctx["total_placement_amount"] == "3,500,000"

    def test_asset_management_fee_amount_computed(
        self, gen, stakeholders, pricing_result, fund_info
    ):
        ctx = gen._build_context(
            "asset_management", stakeholders, pricing_result, fund_info
        )
        # 3,500,000 * 2% = 70,000
        assert ctx["am_fee_rate"] == "2.0%"
        assert ctx["am_fee_amount"] == "70,000"
        assert ctx["managed_assets_value"] == "3,500,000"

    def test_accounting_firm_defaults(
        self, gen, stakeholders, pricing_result, fund_info
    ):
        ctx = gen._build_context(
            "accounting_firm", stakeholders, pricing_result, fund_info
        )
        assert ctx["monthly_fee"] == "¥50,000"
        assert "記帳代行" in ctx["scope_of_work"]

    def test_fmt_mileage_handles_bad_input(self, gen):
        assert gen._fmt_mileage(None) == ""
        assert gen._fmt_mileage(0) == "0km"
        assert gen._fmt_mileage(100_000) == "100,000km"
        assert gen._fmt_mileage("abc") == "abc"

    def test_generate_contract_raises_for_unknown_type(self, gen):
        with pytest.raises(FileNotFoundError):
            gen.generate_contract("definitely_not_a_contract", {})
