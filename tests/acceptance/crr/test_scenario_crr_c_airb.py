"""
CRR Group C: Advanced IRB (A-IRB) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for A-IRB exposures when given fixture data as input.

Tests are skipped until the production calculator is implemented in src/rwa_calc/.

Key CRR A-IRB Features:
- Bank provides own estimates for PD, LGD, EAD
- NO LGD floors under CRR (unlike Basel 3.1 which has 25% unsecured floor)
- Single PD floor: 0.03% for all exposure classes
- 1.06 scaling factor applied
- Full scope permitted for all exposure classes

Regulatory References:
- CRR Art. 143: Permission to use IRB
- CRR Art. 153: IRB risk weight formula for non-retail
- CRR Art. 154: IRB risk weight formula for retail
- CRR Art. 163: PD floor (0.03% - single floor for all classes)
"""

import pytest
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_risk_weight_match,
)


# Marker for tests awaiting production implementation
SKIP_REASON = "Production calculator not yet implemented (Phase 3)"


class TestCRRGroupC_AdvancedIRB:
    """
    CRR A-IRB acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_c1_corporate_airb_own_lgd(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-C1: Corporate A-IRB with bank's own LGD estimate.

        Input: £5m loan, PD 1.00%, internal LGD 35%
        Expected: Lower RWA than F-IRB due to better LGD estimate

        Key: CRR A-IRB has NO LGD floor (Basel 3.1 would floor at 25%)
        """
        expected = expected_outputs_dict["CRR-C1"]

        # TODO: Run through production calculator
        # Verify own LGD estimate is used
        # assert result.lgd == 0.35  # Not floored

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_c2_retail_airb_own_estimates(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-C2: Retail A-IRB with bank's own estimates.

        Input: £100k loan, PD 0.30%, internal LGD 15%
        Expected: Retail IRB calculation with no maturity adjustment

        Key: Retail MUST use A-IRB (F-IRB not available for retail)
        """
        expected = expected_outputs_dict["CRR-C2"]

        # TODO: Run through production calculator
        # Verify no maturity adjustment for retail

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_c3_specialised_lending_airb(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-C3: Specialised Lending A-IRB (Project Finance).

        Input: £10m project finance loan, PD 1.50%, internal LGD 25%
        Expected: A-IRB calculation for specialised lending

        Alternative: Slotting approach (tested in CRR-E)
        """
        expected = expected_outputs_dict["CRR-C3"]

        # TODO: Run through production calculator


class TestCRRGroupC_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_c_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-C scenarios exist in expected outputs."""
        expected_ids = ["CRR-C1", "CRR-C2", "CRR-C3"]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_c_scenarios_use_airb_approach(
        self,
        crr_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-C scenarios use A-IRB approach."""
        for scenario in crr_c_scenarios:
            assert scenario["approach"] == "A-IRB", (
                f"Scenario {scenario['scenario_id']} should use A-IRB approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_c_scenarios_have_no_supporting_factor(
        self,
        crr_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify CRR-C scenarios have supporting factor of 1.0."""
        for scenario in crr_c_scenarios:
            assert scenario["supporting_factor"] == pytest.approx(1.0), (
                f"Scenario {scenario['scenario_id']} should have SF=1.0"
            )

    def test_crr_c_scenarios_use_internal_lgd(
        self,
        crr_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify A-IRB scenarios can use LGD below F-IRB supervisory values."""
        for scenario in crr_c_scenarios:
            lgd = scenario["lgd"]
            # A-IRB allows own estimates - some should be below 45%
            assert lgd is not None, (
                f"Scenario {scenario['scenario_id']} missing LGD"
            )
        # At least one scenario should have LGD < 45%
        lgds = [s["lgd"] for s in crr_c_scenarios]
        assert any(lgd < 0.45 for lgd in lgds), (
            "At least one A-IRB scenario should demonstrate LGD below F-IRB 45%"
        )
