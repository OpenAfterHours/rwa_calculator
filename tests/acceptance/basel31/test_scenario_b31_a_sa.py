"""
B31 Group A: Standardised Approach (Revised) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for Basel 3.1 SA exposures when given the same fixture data as CRR tests
but processed under the Basel 3.1 framework configuration.

Why these tests matter:
    Basel 3.1 changes SA risk weights for several exposure types. Running the
    same portfolio under both CRR and Basel 3.1 configs validates that the
    framework toggle correctly switches between regulatory treatments. Key
    changes tested: LTV-band residential RE weights, SME corporate 85%,
    removal of supporting factors.

Regulatory References:
- CRE20.7: Sovereign risk weights (unchanged from CRR)
- CRE20.16: Institution ECRA/SCRA (UK deviation preserved)
- CRE20.22-26: Corporate risk weights (CQS 3→75%, CQS 5→100%, SME→85%)
- CRE20.47-49: Investment-grade 65%, SME corporate 85%
- CRE20.65: Retail risk weight 75% (unchanged)
- CRE20.73: Residential RE whole-loan LTV bands (7 bands: 20%-70%)
- CRE20.86: Income-producing commercial RE LTV bands (3 bands: 70%/90%/110%)
- PRA PS9/24: Removal of SME and infrastructure supporting factors
"""

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    assert_risk_weight_match,
    assert_rwa_within_tolerance,
    assert_supporting_factor_match,
    get_sa_result_for_exposure,
)


class TestB31GroupA_StandardisedApproach:
    """
    Basel 3.1 SA acceptance tests.

    Each test runs fixture data through the production calculator with
    CalculationConfig.basel_3_1() and compares against hand-calculated
    expected values verified against the regulatory text.
    """

    def test_b31_a1_sovereign_cqs1_zero_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A1: UK Sovereign with CQS 1 should have 0% risk weight.

        Input: £1,000,000 loan to UK Government (CQS 1)
        Expected: RWA = £0 (0% RW per CRE20.7 Table 1)
        Rationale: Sovereign risk weights are unchanged from CRR.
        """
        expected = expected_outputs_dict["B31-A1"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_SOV_UK_001")

        assert result is not None, "Exposure LOAN_SOV_UK_001 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A1"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A1"
        )

    def test_b31_a2_unrated_corporate_100pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A2: Unrated corporate should have 100% risk weight.

        Input: £1,000,000 loan to unrated corporate
        Expected: RWA = £1,000,000 (100% RW per CRE20.22 Table 8)
        Rationale: Unrated corporates remain at 100% under Basel 3.1.
        """
        expected = expected_outputs_dict["B31-A2"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_CORP_UR_001")

        assert result is not None, "Exposure LOAN_CORP_UR_001 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A2"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A2"
        )

    def test_b31_a3_rated_corporate_cqs2_50pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A3: Rated corporate CQS 2 should have 50% risk weight.

        Input: £1,000,000 loan to A-rated corporate (CQS 2)
        Expected: RWA = £500,000 (50% RW per CRE20.22 Table 8)
        Rationale: CQS 2 corporate RW is unchanged from CRR.
        """
        expected = expected_outputs_dict["B31-A3"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_CORP_UK_003")

        assert result is not None, "Exposure LOAN_CORP_UK_003 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A3"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A3"
        )

    def test_b31_a4_uk_institution_cqs2_30pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A4: UK Institution CQS 2 gets 30% RW (UK deviation preserved).

        Input: £1,000,000 loan to UK bank with A rating (CQS 2)
        Expected: RWA = £300,000 (30% RW, UK deviation from standard 50%)
        Rationale: ECRA for rated institutions preserved under Basel 3.1.
            UK deviation applies to both CRR and Basel 3.1.
        """
        expected = expected_outputs_dict["B31-A4"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_INST_UK_003")

        assert result is not None, "Exposure LOAN_INST_UK_003 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A4"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A4"
        )

    def test_b31_a5_residential_mortgage_60pct_ltv_25pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A5: Residential mortgage 60% LTV gets 25% RW (was CRR 35%).

        Input: £500,000 mortgage at 60% LTV (general, not income-producing)
        Expected: RWA = £125,000 (25% RW per CRE20.73 Table 15)
        Rationale: Basel 3.1 replaces the CRR binary 35%/75% split with
            granular LTV-band risk weights. At 60% LTV, the whole-loan
            approach assigns 25% (band >50%-60%), a significant reduction
            from the CRR 35% flat rate.
        """
        expected = expected_outputs_dict["B31-A5"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_RTL_MTG_001")

        assert result is not None, "Exposure LOAN_RTL_MTG_001 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A5"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A5"
        )

    def test_b31_a6_residential_mortgage_85pct_ltv_40pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A6: Residential mortgage 85% LTV gets 40% RW (was CRR ~37.35% split).

        Input: £850,000 mortgage at 85% LTV (general, not income-producing)
        Expected: RWA = £340,000 (40% RW per CRE20.73 Table 15)
        Rationale: Under CRR, 85% LTV got split treatment (35% up to 80%,
            75% on excess), yielding ~37.35% blended. Basel 3.1 whole-loan
            approach assigns a flat 40% from the >80%-90% LTV band.
        """
        expected = expected_outputs_dict["B31-A6"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_RTL_MTG_002")

        assert result is not None, "Exposure LOAN_RTL_MTG_002 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A6"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A6"
        )

    def test_b31_a7_commercial_re_income_producing_70pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A7: Income-producing commercial RE 40% LTV gets 70% RW (was CRR 50%).

        Input: £400,000 loan at 40% LTV with income dependence
        Expected: RWA = £280,000 (70% RW per CRE20.86 Table 18)
        Rationale: Basel 3.1 introduces LTV-banded treatment for income-producing
            commercial RE. At LTV ≤ 60%, the risk weight is 70%, higher than the
            CRR Art. 126 treatment (50% for LTV ≤ 50% with income cover).
        """
        expected = expected_outputs_dict["B31-A7"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_CRE_001")

        assert result is not None, "Exposure LOAN_CRE_001 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A7"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A7"
        )

    def test_b31_a8_retail_75pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A8: Retail exposure gets 75% risk weight (unchanged from CRR).

        Input: £50,000 personal loan
        Expected: RWA = £37,500 (75% RW per CRE20.65)
        Rationale: Retail risk weight is unchanged under Basel 3.1.
        """
        expected = expected_outputs_dict["B31-A8"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_RTL_IND_001")

        assert result is not None, "Exposure LOAN_RTL_IND_001 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A8"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A8"
        )

    def test_b31_a9_sme_retail_no_supporting_factor(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A9: SME retail gets 75% RW with NO supporting factor.

        Input: £500,000 loan to retail SME
        Expected: RWA = £375,000 (75% RW × 1.0 SF)
        Rationale: Under CRR, this exposure had SF=0.7619 yielding RWA=£285,713.
            Under Basel 3.1, supporting factors are removed (PRA PS9/24),
            so the same exposure produces RWA=£375,000 — a 31% increase.
        """
        expected = expected_outputs_dict["B31-A9"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_RTL_SME_001")

        assert result is not None, "Exposure LOAN_RTL_SME_001 not found in B31 SA results"
        assert_supporting_factor_match(
            result["supporting_factor"], expected["supporting_factor"], scenario_id="B31-A9"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A9"
        )

    def test_b31_a10_sme_corporate_85pct_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-A10: SME corporate gets 85% RW with NO supporting factor.

        Input: £2,000,000 loan to corporate with £30m turnover
        Expected: RWA = £1,700,000 (85% RW × 1.0 SF)
        Rationale: Basel 3.1 introduces a dedicated 85% RW for SME corporates
            (CRE20.47-49), down from CRR 100%. But the removal of the 0.7619
            supporting factor means effective capital increases for some SMEs:
            CRR: 100% × 0.7619 = 76.19% effective RW
            B31: 85% × 1.0 = 85% effective RW
        """
        expected = expected_outputs_dict["B31-A10"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_SME_TIER1")

        assert result is not None, "Exposure LOAN_SME_TIER1 not found in B31 SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="B31-A10"
        )
        assert_supporting_factor_match(
            result["supporting_factor"], expected["supporting_factor"], scenario_id="B31-A10"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="B31-A10"
        )


class TestB31GroupA_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_b31_a_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-A scenarios exist in expected outputs."""
        expected_ids = [f"B31-A{i}" for i in range(1, 11)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_b31_a_scenarios_use_sa_approach(
        self,
        b31_a_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-A scenarios use SA approach."""
        for scenario in b31_a_scenarios:
            assert scenario["approach"] == "SA", (
                f"Scenario {scenario['scenario_id']} should use SA approach, "
                f"got {scenario['approach']}"
            )

    def test_b31_a_scenarios_have_valid_risk_weights(
        self,
        b31_a_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-A scenarios have valid risk weights."""
        for scenario in b31_a_scenarios:
            rw = scenario["risk_weight"]
            if rw is not None:
                assert 0.0 <= rw <= 2.5, (
                    f"Scenario {scenario['scenario_id']} has invalid RW: {rw}"
                )

    def test_b31_a_no_supporting_factors(
        self,
        b31_a_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify NO Basel 3.1 SA scenarios have supporting factors < 1.0.

        Under Basel 3.1, all supporting factors (SME, infrastructure) are removed.
        Every scenario must have SF = 1.0.
        """
        for scenario in b31_a_scenarios:
            assert scenario["supporting_factor"] == pytest.approx(1.0), (
                f"Scenario {scenario['scenario_id']} has SF={scenario['supporting_factor']}, "
                f"but Basel 3.1 removes all supporting factors"
            )
