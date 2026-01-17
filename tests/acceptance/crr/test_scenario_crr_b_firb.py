"""
CRR Group B: Foundation IRB (F-IRB) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for F-IRB exposures when given fixture data as input.

Tests are skipped until the production calculator is implemented in src/rwa_calc/.

Regulatory References:
- CRR Art. 153: IRB risk weight formula
- CRR Art. 161: Supervisory LGD values (45% senior, 75% subordinated)
- CRR Art. 162: Maturity (1-5 year floor/cap)
- CRR Art. 163: PD floor (0.03% single floor)
- CRR Art. 153(4): SME firm size adjustment
- CRR Art. 501: SME supporting factor (0.7619)
"""

import pytest
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_risk_weight_match,
)


# Marker for tests awaiting production implementation
SKIP_REASON = "Production calculator not yet implemented (Phase 3)"


class TestCRRGroupB_FoundationIRB:
    """
    CRR F-IRB acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.

    Note: F-IRB only applies to wholesale exposures (corporate, institution,
    sovereign). Retail exposures require A-IRB or Standardised Approach.
    """

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_b1_corporate_firb_low_pd(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-B1: Corporate F-IRB with low PD.

        Input: £25m loan, PD 0.10%, LGD 45% (supervisory), M 2.5y
        Expected: Calculated using IRB formula with 1.06 scaling factor
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-B1"]

        loan = fixtures.get_loan("LOAN_CORP_UK_001")
        counterparty = fixtures.get_counterparty("CORP_UK_001")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_b2_corporate_firb_high_pd(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-B2: Corporate F-IRB with high PD.

        Input: £5m loan, PD 5.00%, LGD 45%, M 3.0y
        Expected: Higher RWA due to high PD, lower correlation

        Note: Higher PD leads to lower asset correlation (0.130 vs 0.24 at low PD)
        """
        expected = expected_outputs_dict["CRR-B2"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_b3_subordinated_exposure(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-B3: Subordinated exposure uses 75% supervisory LGD.

        Input: £2m subordinated loan, PD 1.00%, LGD 75%, M 4.0y
        Expected: Higher RWA due to 75% LGD vs 45% for senior

        CRR Art. 161: Subordinated claims have 75% LGD
        """
        expected = expected_outputs_dict["CRR-B3"]

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_b4_sme_corporate_firm_size_adjustment(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-B4: SME Corporate F-IRB with firm size adjustment.

        Input: £3m loan, PD 1.50%, turnover EUR 25m
        Expected: Reduced correlation due to firm size adjustment

        CRR Art. 153(4): R_SME = R - 0.04 × (1 - (S-5)/45)
        where S = turnover in EUR millions, capped at 5-50 range
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-B4"]

        loan = fixtures.get_loan("LOAN_CORP_SME_002")
        counterparty = fixtures.get_counterparty("CORP_SME_002")

        # TODO: Run through production calculator

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_b5_sme_corporate_both_adjustments(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-B5: SME Corporate F-IRB with BOTH adjustments.

        Input: £2m loan, PD 2.00%, turnover EUR 15m
        Expected: Both firm size correlation adjustment AND SME supporting factor

        This demonstrates the dual benefit for SME corporates under CRR:
        1. Lower correlation (Art. 153(4))
        2. 0.7619 RWA multiplier (Art. 501)

        Note: Neither adjustment available under Basel 3.1
        """
        fixtures = load_test_fixtures
        expected = expected_outputs_dict["CRR-B5"]

        loan = fixtures.get_loan("LOAN_CORP_SME_003")
        counterparty = fixtures.get_counterparty("CORP_SME_003")

        # TODO: Run through production calculator
        # Verify supporting factor is applied
        # assert result.supporting_factor == pytest.approx(0.7619, rel=0.001)

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_b6_corporate_at_sme_threshold(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-B6: Corporate at EUR 50m SME threshold boundary.

        Input: £4m loan, PD 1.00%, turnover EUR 50m
        Expected: No firm size adjustment (at boundary)

        Threshold: Turnover < EUR 50m qualifies for adjustment
        At exactly EUR 50m: No adjustment applies
        """
        expected = expected_outputs_dict["CRR-B6"]

        # TODO: Run through production calculator


class TestCRRGroupB_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_b_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios exist in expected outputs."""
        expected_ids = [f"CRR-B{i}" for i in range(1, 7)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_b_scenarios_use_firb_approach(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios use F-IRB approach."""
        for scenario in crr_b_scenarios:
            assert scenario["approach"] == "F-IRB", (
                f"Scenario {scenario['scenario_id']} should use F-IRB approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_b_scenarios_have_irb_parameters(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios have required IRB parameters."""
        for scenario in crr_b_scenarios:
            assert scenario["pd"] is not None, (
                f"Scenario {scenario['scenario_id']} missing PD"
            )
            assert scenario["lgd"] is not None, (
                f"Scenario {scenario['scenario_id']} missing LGD"
            )

    def test_crr_b_scenarios_have_expected_loss(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios have expected loss calculated."""
        for scenario in crr_b_scenarios:
            assert scenario["expected_loss"] is not None, (
                f"Scenario {scenario['scenario_id']} missing expected loss"
            )
            # EL = PD × LGD × EAD
            expected_el = scenario["pd"] * scenario["lgd"] * scenario["ead"]
            assert scenario["expected_loss"] == pytest.approx(expected_el, rel=0.01), (
                f"Scenario {scenario['scenario_id']} EL mismatch"
            )

    def test_crr_b_supervisory_lgd_values(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify F-IRB scenarios use correct supervisory LGD values."""
        for scenario in crr_b_scenarios:
            lgd = scenario["lgd"]
            # F-IRB uses supervisory LGDs: 45% or 75%
            assert lgd in [0.45, 0.75], (
                f"Scenario {scenario['scenario_id']} has non-supervisory LGD: {lgd}"
            )

    def test_crr_b5_has_sme_supporting_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-B5 (SME with both adjustments) has supporting factor."""
        scenario = expected_outputs_dict["CRR-B5"]
        assert scenario["supporting_factor"] == pytest.approx(0.7619, rel=0.001), (
            "CRR-B5 should have SME supporting factor 0.7619"
        )
