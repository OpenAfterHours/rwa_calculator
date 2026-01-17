"""
CRR Group A: Standardised Approach Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for SA exposures when given fixture data as input.

Tests are skipped until the production calculator is implemented in src/rwa_calc/.

Regulatory References:
- CRR Art. 114: Sovereign risk weights
- CRR Art. 120-121: Institution risk weights (UK deviation)
- CRR Art. 122: Corporate risk weights
- CRR Art. 123: Retail risk weight (75%)
- CRR Art. 125: Residential mortgage (35%/75% split at 80% LTV)
- CRR Art. 126: Commercial real estate
- CRR Art. 501: SME supporting factor (0.7619)
"""

import pytest
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_risk_weight_match,
    assert_supporting_factor_match,
)


# Marker for tests awaiting production implementation
SKIP_REASON = "Production calculator not yet implemented (Phase 3)"


class TestCRRGroupA_StandardisedApproach:
    """
    CRR SA acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a1_uk_sovereign_zero_rw(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A1: UK Sovereign with CQS 1 should have 0% risk weight.

        Input: £1,000,000 loan to UK Government (CQS 1)
        Expected: RWA = £0 (0% RW per CRR Art. 114)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A1"]

        # Load fixture inputs
        loan = fixtures.get_loan("LOAN_SOV_UK_001")
        counterparty = fixtures.get_counterparty("SOV_UK_001")
        rating = fixtures.get_rating("SOV_UK_001")

        # TODO: Run through production calculator
        # from rwa_calc import calculate_rwa
        # result = calculate_rwa(loan, counterparty, rating, config=crr_config)

        # Validate against expected
        # assert_risk_weight_match(result.risk_weight, expected["risk_weight"], scenario_id="CRR-A1")
        # assert_rwa_within_tolerance(result.rwa, expected["rwa_after_sf"], scenario_id="CRR-A1")

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a2_unrated_corporate(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A2: Unrated corporate should have 100% risk weight.

        Input: £1,000,000 loan to unrated corporate
        Expected: RWA = £1,000,000 (100% RW per CRR Art. 122)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A2"]

        loan = fixtures.get_loan("LOAN_CORP_UR_001")
        counterparty = fixtures.get_counterparty("CORP_UR_001")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a3_rated_corporate_cqs2(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A3: Rated corporate CQS 2 should have 50% risk weight.

        Input: £1,000,000 loan to A-rated corporate (CQS 2)
        Expected: RWA = £500,000 (50% RW per CRR Art. 122)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A3"]

        loan = fixtures.get_loan("LOAN_CORP_UK_003")
        counterparty = fixtures.get_counterparty("CORP_UK_003")
        rating = fixtures.get_rating("CORP_UK_003")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a4_uk_institution_cqs2_deviation(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A4: UK Institution CQS 2 gets 30% RW (UK deviation from 50%).

        Input: £1,000,000 loan to UK bank with A rating (CQS 2)
        Expected: RWA = £300,000 (30% RW per UK deviation)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A4"]

        loan = fixtures.get_loan("LOAN_INST_UK_003")
        counterparty = fixtures.get_counterparty("INST_UK_003")
        rating = fixtures.get_rating("INST_UK_003")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a5_residential_mortgage_low_ltv(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A5: Residential mortgage with LTV <= 80% gets 35% RW.

        Input: £500,000 mortgage at 60% LTV
        Expected: RWA = £175,000 (35% RW per CRR Art. 125)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A5"]

        loan = fixtures.get_loan("LOAN_RTL_MTG_001")
        counterparty = fixtures.get_counterparty("RTL_MTG_001")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a6_residential_mortgage_high_ltv_split(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A6: Residential mortgage with LTV > 80% gets split treatment.

        Input: £850,000 mortgage at 85% LTV
        Expected: Split RW (35% up to 80% LTV, 75% on excess)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A6"]

        loan = fixtures.get_loan("LOAN_RTL_MTG_002")
        counterparty = fixtures.get_counterparty("RTL_MTG_002")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a7_commercial_re_low_ltv(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A7: Commercial RE with LTV <= 50% and income cover gets 50% RW.

        Input: £400,000 loan at 40% LTV with income cover
        Expected: RWA = £200,000 (50% RW per CRR Art. 126)
        """
        expected = expected_outputs_dict["CRR-A7"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a8_obs_commitment_ccf(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A8: Undrawn committed facility (>1 year) gets 50% CCF.

        Input: £1,000,000 undrawn commitment (2 year maturity)
        Expected: EAD = £500,000 (50% CCF per CRR Art. 111)
        """
        expected = expected_outputs_dict["CRR-A8"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a9_retail_exposure(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A9: Retail exposure gets 75% risk weight.

        Input: £50,000 personal loan
        Expected: RWA = £37,500 (75% RW per CRR Art. 123)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A9"]

        loan = fixtures.get_loan("LOAN_RTL_IND_001")
        counterparty = fixtures.get_counterparty("RTL_IND_001")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a10_sme_corporate_with_supporting_factor(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A10: SME corporate should have SME supporting factor applied.

        Input: £2,000,000 loan to SME (turnover £30m < £44m threshold)
        Expected: RWA = £1,523,800 (100% RW × 0.7619 SME factor)

        Note: SME supporting factor NOT available under Basel 3.1.
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A10"]

        loan = fixtures.get_loan("LOAN_CORP_SME_001")
        counterparty = fixtures.get_counterparty("CORP_SME_001")

        # TODO: Run through production calculator
        # Verify supporting factor is applied
        # assert_supporting_factor_match(result.supporting_factor, 0.7619, scenario_id="CRR-A10")

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a11_sme_retail_with_supporting_factor(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A11: SME retail should have SME supporting factor applied.

        Input: £500,000 loan to retail SME
        Expected: RWA = £285,712.50 (75% RW × 0.7619 SME factor)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A11"]

        loan = fixtures.get_loan("LOAN_RTL_SME_001")
        counterparty = fixtures.get_counterparty("RTL_SME_001")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_a12_large_corporate_no_supporting_factor(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-A12: Large corporate (turnover > threshold) gets no SME factor.

        Input: £25,000,000 loan to large corporate (turnover £500m)
        Expected: RWA = £25,000,000 (100% RW, no SME factor)
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-A12"]

        loan = fixtures.get_loan("LOAN_CORP_UK_001")
        counterparty = fixtures.get_counterparty("CORP_UK_001")

        # TODO: Run through production calculator
        # assert_supporting_factor_match(result.supporting_factor, 1.0, scenario_id="CRR-A12")


class TestCRRGroupA_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_a_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-A scenarios exist in expected outputs."""
        expected_ids = [f"CRR-A{i}" for i in range(1, 13)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_a_scenarios_use_sa_approach(
        self,
        crr_a_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-A scenarios use SA approach."""
        for scenario in crr_a_scenarios:
            assert scenario["approach"] == "SA", (
                f"Scenario {scenario['scenario_id']} should use SA approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_a_scenarios_have_valid_risk_weights(
        self,
        crr_a_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-A scenarios have valid risk weights."""
        for scenario in crr_a_scenarios:
            rw = scenario["risk_weight"]
            assert 0.0 <= rw <= 2.5, (
                f"Scenario {scenario['scenario_id']} has invalid RW: {rw}"
            )

    def test_crr_a_sme_scenarios_have_supporting_factor(
        self,
        crr_a_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify SME scenarios have correct supporting factor."""
        sme_scenarios = ["CRR-A10", "CRR-A11"]
        for scenario in crr_a_scenarios:
            if scenario["scenario_id"] in sme_scenarios:
                assert scenario["supporting_factor"] == pytest.approx(0.7619, rel=0.001), (
                    f"Scenario {scenario['scenario_id']} should have SME SF 0.7619"
                )
            else:
                assert scenario["supporting_factor"] == pytest.approx(1.0), (
                    f"Scenario {scenario['scenario_id']} should have SF 1.0"
                )
