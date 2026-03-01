"""
Basel 3.1 Group D: Credit Risk Mitigation (CRM) Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
CRM treatments under the Basel 3.1 framework, including revised collateral
haircuts, guarantee substitution, and maturity/FX mismatch adjustments.

Why these tests matter:
    Basel 3.1 (CRE22.52-53) revises supervisory haircut tables from CRR's
    3 maturity bands to 5 bands, and increases equity haircuts (main index
    15% → 25%, other 25% → 35%). Long-dated corporate bond haircuts increase
    significantly (>5yr). Running the same CRM portfolio under both frameworks
    validates that the framework toggle correctly selects the right haircut
    table and produces the expected capital impact.

Key Basel 3.1 CRM differences from CRR:
- 5 maturity bands (0-1y, 1-3y, 3-5y, 5-10y, 10y+) vs CRR's 3 (0-1y, 1-5y, 5y+)
- Main index equity haircut: 25% (was 15%)
- Other listed equity haircut: 35% (was 25%)
- Sovereign CQS 2-3 10y+: 12% (was 6%)
- FX mismatch haircut: 8% (unchanged)
- Maturity mismatch formula: unchanged
- Guarantee substitution mechanism: unchanged

Regulatory References:
- CRE22.52-53: Basel 3.1 supervisory haircuts
- CRE22.54: Currency mismatch haircut
- CRE22.65-66: Maturity mismatch
- CRE22.70-71: Unfunded credit protection (guarantees)
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    assert_rwa_within_tolerance,
    get_sa_result_for_exposure,
)

# Mapping of scenario IDs to exposure references in fixtures
# Same exposures as CRR-D: the framework config drives different haircut tables
SCENARIO_EXPOSURE_MAP = {
    "B31-D1": "LOAN_CRM_D1",
    "B31-D2": "LOAN_CRM_D2",
    "B31-D3": "LOAN_CRM_D3",
    "B31-D4": "LOAN_CRM_D4",
    "B31-D5": "LOAN_CRM_D5",
    "B31-D6": "LOAN_CRM_D6",
}


class TestB31GroupD_CreditRiskMitigation:
    """
    Basel 3.1 CRM acceptance tests.

    Each test runs fixture data through the production calculator with
    CalculationConfig.basel_3_1() and SA-only permissions, then compares
    the output against hand-calculated expected values.
    """

    def test_b31_d1_cash_collateral_zero_haircut(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-D1: Cash collateral has 0% supervisory haircut.

        Input: £1M corporate exposure, £500k cash collateral
        Expected: EAD = £500k (cash reduces exposure 1:1)

        Cash haircut is 0% under both CRR and Basel 3.1.
        No change in capital requirement.
        """
        expected = expected_outputs_dict["B31-D1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-D1"]

        result = get_sa_result_for_exposure(sa_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_post_factor"],
            expected["rwa_after_sf"],
            scenario_id="B31-D1",
        )

    def test_b31_d2_govt_bond_collateral_5_10yr_band(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-D2: Government bond collateral with Basel 3.1 5-maturity-band haircut.

        Input: £1M exposure, £600k UK gilt (CQS 1, 6yr residual maturity)
        Expected: 4% haircut (5-10yr band), EAD = £424k

        Basel 3.1 splits CRR's single >5yr band into 5-10yr and 10y+.
        For CQS 1 sovereign at 6yr, the 5-10yr haircut (4%) happens to
        match CRR's >5yr haircut (4%). Divergence occurs at 10y+.
        """
        expected = expected_outputs_dict["B31-D2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-D2"]

        result = get_sa_result_for_exposure(sa_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_post_factor"],
            expected["rwa_after_sf"],
            scenario_id="B31-D2",
        )

    def test_b31_d3_equity_collateral_increased_haircut(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-D3: Equity collateral (main index) — 25% haircut (was CRR 15%).

        Input: £1M exposure, £400k FTSE 100 equity collateral
        Expected: EAD = £700k, RWA = £700k

        This is the key Basel 3.1 CRM change: main index equity haircut
        increases from 15% to 25%. Adjusted collateral = £400k × 0.75 = £300k
        (was £340k under CRR). RWA increases by £40k (+6%) to £700k.
        """
        expected = expected_outputs_dict["B31-D3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-D3"]

        result = get_sa_result_for_exposure(sa_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_post_factor"],
            expected["rwa_after_sf"],
            scenario_id="B31-D3",
        )

    def test_b31_d4_bank_guarantee_substitution(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-D4: Bank guarantee substitution — blended risk weight.

        Input: £1M unrated corporate, 60% guaranteed by CQS 2 UK bank (30% RW)
        Expected: Blended RW = 60%×30% + 40%×100% = 58%, RWA = £580k

        Guarantee substitution mechanism is unchanged under Basel 3.1.
        The guarantor risk weight (Metro Bank CQS 2 = 30% UK ECRA deviation)
        is also unchanged.
        """
        expected = expected_outputs_dict["B31-D4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-D4"]

        result = get_sa_result_for_exposure(sa_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_post_factor"],
            expected["rwa_after_sf"],
            scenario_id="B31-D4",
        )

    def test_b31_d5_maturity_mismatch(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-D5: Maturity mismatch reduces collateral effectiveness.

        Input: £1M exposure (5yr), £500k bond collateral (2yr residual)
        Expected: Adj factor = (2-0.25)/(5-0.25) = 0.3684, RWA = £815,789

        The maturity mismatch formula C_adj = C × (t-0.25)/(T-0.25) is
        unchanged between CRR and Basel 3.1. The bond base haircut for
        CQS 1 sovereign at 2yr is 2% under both frameworks.
        """
        expected = expected_outputs_dict["B31-D5"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-D5"]

        result = get_sa_result_for_exposure(sa_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_post_factor"],
            expected["rwa_after_sf"],
            scenario_id="B31-D5",
        )

    def test_b31_d6_currency_mismatch(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-D6: Currency mismatch adds 8% FX haircut.

        Input: £1M GBP exposure, €500k EUR cash collateral
        Expected: 8% FX haircut, adj collateral = £460k, RWA = £540k

        FX mismatch haircut (8%) is unchanged between CRR (Art. 224) and
        Basel 3.1 (CRE22.54).
        """
        expected = expected_outputs_dict["B31-D6"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-D6"]

        result = get_sa_result_for_exposure(sa_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_post_factor"],
            expected["rwa_after_sf"],
            scenario_id="B31-D6",
        )


class TestB31GroupD_FrameworkDifferences:
    """
    Cross-framework structural validation tests for CRM.

    These tests verify Basel 3.1-specific CRM properties that differ from CRR.
    """

    def test_b31_d3_equity_rwa_higher_than_crr(
        self,
        sa_results_df: pl.DataFrame,
    ) -> None:
        """
        Verify D3 equity scenario produces higher RWA under Basel 3.1.

        Basel 3.1 equity haircut (25%) > CRR (15%), so less collateral
        protection → higher RWA. Expected: B31 RWA 700k > CRR RWA 660k.
        """
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_CRM_D3")
        if result is None:
            pytest.skip("LOAN_CRM_D3 not found in B31 SA results")

        # Under Basel 3.1, equity haircut 25% → EAD = 1M - 400k×0.75 = 700k
        # Under CRR, equity haircut 15% → EAD = 1M - 400k×0.85 = 660k
        crr_expected_rwa = 660_000.0
        assert result["rwa_post_factor"] > crr_expected_rwa, (
            f"B31 equity collateral RWA ({result['rwa_post_factor']:,.0f}) should be > "
            f"CRR RWA ({crr_expected_rwa:,.0f}) due to higher haircut"
        )

    def test_b31_d_no_supporting_factors(
        self,
        sa_results_df: pl.DataFrame,
    ) -> None:
        """Verify no CRM scenarios have supporting factors under Basel 3.1."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_sa_result_for_exposure(sa_results_df, ref)
            if result is None:
                continue
            assert result["supporting_factor"] == pytest.approx(1.0), (
                f"{ref}: Supporting factor should be 1.0 under Basel 3.1, "
                f"got {result['supporting_factor']}"
            )

    def test_b31_d1_d6_unchanged_from_crr(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        Verify D1, D2, D4, D5, D6 produce same RWA as CRR.

        These scenarios use CRM features whose parameters are unchanged:
        - D1: Cash haircut 0% (unchanged)
        - D2: CQS 1 sovereign 6yr haircut 4% (5-10yr = old 5y+)
        - D4: Guarantee substitution (mechanism unchanged)
        - D5: Maturity mismatch formula (unchanged)
        - D6: FX haircut 8% (unchanged)
        """
        # CRR expected RWA values from CRR acceptance tests
        crr_expected_rwa = {
            "B31-D1": 500_000.0,
            "B31-D2": 424_000.0,
            "B31-D4": 580_000.0,
            "B31-D5": 815_789.47,
            "B31-D6": 540_000.0,
        }
        for scenario_id, crr_rwa in crr_expected_rwa.items():
            b31_expected = expected_outputs_dict[scenario_id]
            assert b31_expected["rwa_after_sf"] == pytest.approx(crr_rwa, rel=0.001), (
                f"{scenario_id}: B31 expected RWA ({b31_expected['rwa_after_sf']:,.2f}) "
                f"should match CRR ({crr_rwa:,.2f}) — parameters unchanged"
            )

    def test_b31_d_all_exposures_are_corporate(
        self,
        sa_results_df: pl.DataFrame,
    ) -> None:
        """Verify all D-group exposures are classified as corporate."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_sa_result_for_exposure(sa_results_df, ref)
            if result is None:
                continue
            exp_class = result.get("exposure_class", "")
            assert "CORPORATE" in str(exp_class).upper(), (
                f"{ref}: Expected CORPORATE exposure class, got {exp_class}"
            )


class TestB31GroupD_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_b31_d_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-D scenarios exist in expected outputs."""
        expected_ids = [f"B31-D{i}" for i in range(1, 7)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_b31_d_scenarios_use_crm_approach(
        self,
        b31_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-D scenarios use SA-CRM approach."""
        for scenario in b31_d_scenarios:
            assert scenario["approach"] == "SA-CRM", (
                f"Scenario {scenario['scenario_id']} should use SA-CRM approach, "
                f"got {scenario['approach']}"
            )

    def test_b31_d_scenarios_have_valid_ead(
        self,
        b31_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify CRM scenarios show effect of mitigation on EAD."""
        for scenario in b31_d_scenarios:
            assert scenario["ead"] is not None, f"Scenario {scenario['scenario_id']} missing EAD"
            assert scenario["rwa_after_sf"] is not None, (
                f"Scenario {scenario['scenario_id']} missing RWA"
            )
            # All CRM scenarios should have EAD ≤ gross exposure (£1M)
            assert scenario["ead"] <= 1_000_000.0, (
                f"Scenario {scenario['scenario_id']}: EAD {scenario['ead']:,.0f} "
                f"should be ≤ £1M gross exposure after CRM"
            )

    def test_b31_d_no_supporting_factors_in_expected(
        self,
        b31_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-D expected scenarios have SF = 1.0."""
        for scenario in b31_d_scenarios:
            assert scenario["supporting_factor"] == pytest.approx(1.0), (
                f"Scenario {scenario['scenario_id']}: SF should be 1.0 under Basel 3.1"
            )

    def test_b31_d_rwa_positive(
        self,
        b31_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRM scenarios produce positive RWA."""
        for scenario in b31_d_scenarios:
            assert scenario["rwa_after_sf"] > 0, (
                f"Scenario {scenario['scenario_id']}: RWA should be positive"
            )
