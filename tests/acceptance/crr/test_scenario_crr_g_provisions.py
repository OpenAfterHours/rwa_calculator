"""
CRR Group G: Provisions & Impairments Acceptance Tests.

These tests validate that the production RWA calculator correctly handles
provisions under SA and EL shortfall/excess under IRB.

Tests are skipped until the production calculator is implemented in src/rwa_calc/.

Regulatory References:
- CRR Art. 110: Provisions treatment under SA
- CRR Art. 158: Expected Loss calculation
- CRR Art. 159: Expected Loss shortfall treatment
- CRR Art. 62(d): Excess provisions as T2 capital (capped)
"""

import pytest
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_ead_match,
)


# Marker for tests awaiting production implementation
SKIP_REASON = "Production calculator not yet implemented (Phase 3)"


class TestCRRGroupG_Provisions:
    """
    CRR Provisions acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_g1_sa_with_specific_provision(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-G1: SA exposure with specific provision reduces EAD.

        Input: £1m gross exposure, £50k specific provision
        Expected: EAD = £950k (net of provision)

        CRR Art. 110: Specific provisions reduce exposure value
        """
        expected = expected_outputs_dict["CRR-G1"]

        # TODO: Run through production calculator
        # assert result.ead == 950000.0
        # assert result.gross_exposure == 1000000.0
        # assert result.provision == 50000.0

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_g2_irb_el_shortfall(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-G2: IRB EL shortfall results in CET1/T2 deduction.

        Input: EL = £45k, Total provisions = £30k
        Expected: Shortfall = £15k, 50% deducted from CET1, 50% from T2

        CRR Art. 159: Shortfall treatment
        """
        expected = expected_outputs_dict["CRR-G2"]

        # TODO: Run through production calculator
        # el = expected["expected_loss"]
        # shortfall = el - provisions
        # assert result.el_shortfall == 15000.0
        # assert result.cet1_deduction == 7500.0  # 50%

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_g3_irb_el_excess(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-G3: IRB EL excess can be added to T2 capital (capped).

        Input: EL = £11,250, Total provisions = £50,000
        Expected: Excess = £38,750, T2 credit capped at 0.6% of IRB RWA

        CRR Art. 62(d): Excess provisions as T2 (capped at 0.6% IRB RWA)
        """
        expected = expected_outputs_dict["CRR-G3"]

        # TODO: Run through production calculator
        # excess = provisions - el
        # t2_cap = rwa * 0.006
        # t2_credit = min(excess, t2_cap)


class TestCRRGroupG_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_g_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-G scenarios exist in expected outputs."""
        expected_ids = ["CRR-G1", "CRR-G2", "CRR-G3"]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_crr_g1_uses_sa_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-G1 (SA provision) uses SA approach."""
        scenario = expected_outputs_dict["CRR-G1"]
        assert scenario["approach"] == "SA", (
            "CRR-G1 should use SA approach"
        )

    def test_crr_g2_g3_use_firb_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-G2 and G3 (EL shortfall/excess) use F-IRB approach."""
        for scenario_id in ["CRR-G2", "CRR-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["approach"] == "F-IRB", (
                f"{scenario_id} should use F-IRB approach"
            )

    def test_crr_g_irb_scenarios_have_expected_loss(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify IRB provision scenarios have expected loss calculated."""
        for scenario_id in ["CRR-G2", "CRR-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["expected_loss"] is not None, (
                f"{scenario_id} should have expected loss"
            )
            assert scenario["expected_loss"] > 0, (
                f"{scenario_id} should have positive expected loss"
            )
