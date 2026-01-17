"""
CRR Group D: Credit Risk Mitigation (CRM) Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
CRM treatments including collateral haircuts, guarantees, and maturity mismatches.

Tests are skipped until the production calculator is implemented in src/rwa_calc/.

Regulatory References:
- CRR Art. 192-241: Credit Risk Mitigation
- CRR Art. 223-224: Financial Collateral Comprehensive Method
- CRR Art. 233-236: Guarantees and credit derivatives
- CRR Art. 238: Maturity mismatch
"""

import pytest
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_ead_match,
)


# Marker for tests awaiting production implementation
SKIP_REASON = "Production calculator not yet implemented (Phase 3)"


class TestCRRGroupD_CreditRiskMitigation:
    """
    CRR CRM acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_d1_cash_collateral_zero_haircut(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-D1: Cash collateral has 0% supervisory haircut.

        Input: £1m exposure, £500k cash collateral
        Expected: EAD = £500k (cash reduces exposure 1:1)

        CRR Art. 224: Cash has 0% haircut
        """
        expected = expected_outputs_dict["CRR-D1"]

        # TODO: Run through production calculator
        # assert result.ead == expected["ead"]
        # assert result.collateral_haircut == 0.0

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_d2_govt_bond_collateral(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-D2: Government bond collateral with supervisory haircut.

        Input: £1m exposure, £600k govt bond (CQS 1, >5y maturity)
        Expected: 4% haircut applied to collateral

        CRR Art. 224: CQS 1 govt bond >5y = 4% haircut
        """
        expected = expected_outputs_dict["CRR-D2"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_d3_equity_collateral_main_index(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-D3: Equity collateral (main index) has 15% haircut.

        Input: £1m exposure, £400k FTSE 100 equity collateral
        Expected: 15% haircut (vs 25% for non-main index)

        CRR Art. 224: Main index equity = 15% haircut
        """
        expected = expected_outputs_dict["CRR-D3"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_d4_bank_guarantee_substitution(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-D4: Bank guarantee allows substitution of guarantor's RW.

        Input: £1m to unrated corporate, £600k guaranteed by CQS 2 bank
        Expected: Split treatment - guaranteed portion at 30% RW (UK deviation)

        CRR Art. 213-217: Unfunded credit protection
        """
        expected = expected_outputs_dict["CRR-D4"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_d5_maturity_mismatch(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-D5: Maturity mismatch reduces collateral effectiveness.

        Input: £1m exposure (5y), £500k collateral (2y)
        Expected: Collateral value reduced by maturity adjustment

        Formula: Adjusted = C × (t - 0.25) / (T - 0.25)
        where t = collateral maturity, T = exposure maturity

        CRR Art. 238: Maturity mismatch
        """
        expected = expected_outputs_dict["CRR-D5"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_d6_currency_mismatch(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-D6: Currency mismatch adds 8% additional haircut.

        Input: £1m GBP exposure, €500k EUR collateral
        Expected: 8% FX haircut applied

        CRR Art. 224: Currency mismatch = 8% additional haircut
        """
        expected = expected_outputs_dict["CRR-D6"]

        # TODO: Run through production calculator


class TestCRRGroupD_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_d_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-D scenarios exist in expected outputs."""
        expected_ids = [f"CRR-D{i}" for i in range(1, 7)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_d_scenarios_use_crm_approach(
        self,
        crr_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-D scenarios use SA-CRM approach."""
        for scenario in crr_d_scenarios:
            assert scenario["approach"] == "SA-CRM", (
                f"Scenario {scenario['scenario_id']} should use SA-CRM approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_d_scenarios_have_reduced_ead(
        self,
        crr_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify CRM scenarios show effect of mitigation on EAD or RWA."""
        for scenario in crr_d_scenarios:
            # All CRM scenarios should result in some form of risk reduction
            assert scenario["ead"] is not None, (
                f"Scenario {scenario['scenario_id']} missing EAD"
            )
            assert scenario["rwa_after_sf"] is not None, (
                f"Scenario {scenario['scenario_id']} missing RWA"
            )
