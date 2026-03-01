"""
CRR Group G: Provisions & Impairments Acceptance Tests.

These tests validate that the production RWA calculator correctly handles
provisions under SA and EL shortfall/excess under IRB.

Regulatory References:
- CRR Art. 110: Provisions treatment under SA
- CRR Art. 158: Expected Loss calculation
- CRR Art. 159: Expected Loss shortfall treatment
- CRR Art. 62(d): Excess provisions as T2 capital (capped)
"""

from typing import Any

import polars as pl
import pytest
from tests.acceptance.crr.conftest import (
    assert_ead_match,
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-G1": "LOAN_PROV_G1",
    "CRR-G2": "LOAN_PROV_G2",
    "CRR-G3": "LOAN_PROV_G3",
}


class TestCRRGroupG_Provisions:
    """
    CRR Provisions acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    def test_crr_g1_sa_with_specific_provision(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-G1: SA exposure with specific provision reduces EAD.

        Input: Gross exposure, specific provision
        Expected: EAD = gross - provision (net of provision)

        CRR Art. 110: Specific provisions reduce exposure value
        """
        expected = expected_outputs_dict["CRR-G1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-G1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_ead_match(
            result["ead_final"],
            expected["ead"],
            scenario_id="CRR-G1",
        )

    def test_crr_g2_irb_el_shortfall(
        self,
        irb_pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-G2: IRB EL shortfall results in CET1/T2 deduction.

        Input: EL > Total provisions
        Expected: Shortfall = EL - provisions, 50% deducted from CET1, 50% from T2

        CRR Art. 159: Shortfall treatment
        """
        expected = expected_outputs_dict["CRR-G2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-G2"]

        result = get_result_for_exposure(irb_pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-G2",
        )

    def test_crr_g3_irb_el_excess(
        self,
        irb_pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-G3: IRB EL excess can be added to T2 capital (capped).

        Input: EL < Total provisions
        Expected: Excess = provisions - EL, T2 credit capped at 0.6% of IRB RWA

        CRR Art. 62(d): Excess provisions as T2 (capped at 0.6% IRB RWA)
        """
        expected = expected_outputs_dict["CRR-G3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-G3"]

        result = get_result_for_exposure(irb_pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-G3",
        )


class TestCRRGroupG_ELShortfallExcess:
    """
    CRR EL shortfall/excess column validation.

    Verifies that the production pipeline computes per-exposure
    el_shortfall and el_excess columns correctly.

    References:
    - CRR Art. 158: EL = PD x LGD x EAD
    - CRR Art. 159: EL shortfall reduces CET1/T2
    - CRR Art. 62(d): EL excess may be added to T2 (capped at 0.6% IRB RWA)
    """

    def test_crr_g2_el_shortfall_column(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-G2: el_shortfall = max(0, EL - provisions) = 45k - 30k = 15k.

        EL = PD(2%) x LGD(45%) x EAD(5M) = 45,000
        Provisions = 30,000
        Shortfall = 15,000 (50% deducted from CET1, 50% from T2)
        """
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in IRB pipeline results")

        assert "el_shortfall" in result, "el_shortfall column missing from IRB results"
        assert result["el_shortfall"] == pytest.approx(15_000.0, rel=0.01), (
            f"CRR-G2: el_shortfall should be 15,000 (EL 45k - prov 30k), "
            f"got {result['el_shortfall']}"
        )

    def test_crr_g2_el_excess_is_zero(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """CRR-G2: el_excess should be zero when EL > provisions."""
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in IRB pipeline results")

        assert "el_excess" in result, "el_excess column missing from IRB results"
        assert result["el_excess"] == pytest.approx(0.0, abs=0.01), (
            f"CRR-G2: el_excess should be 0 (EL > provisions), got {result['el_excess']}"
        )

    def test_crr_g3_el_excess_column(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-G3: el_excess = max(0, provisions - EL) = 50k - 11.25k = 38.75k.

        EL = PD(0.5%) x LGD(45%) x EAD(5M) = 11,250
        Provisions = 50,000
        Excess = 38,750 (T2 credit capped at 0.6% of IRB RWA)
        """
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_PROV_G3")
        if result is None:
            pytest.skip("LOAN_PROV_G3 not in IRB pipeline results")

        assert "el_excess" in result, "el_excess column missing from IRB results"
        assert result["el_excess"] == pytest.approx(38_750.0, rel=0.01), (
            f"CRR-G3: el_excess should be 38,750 (prov 50k - EL 11.25k), "
            f"got {result['el_excess']}"
        )

    def test_crr_g3_el_shortfall_is_zero(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """CRR-G3: el_shortfall should be zero when provisions > EL."""
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_PROV_G3")
        if result is None:
            pytest.skip("LOAN_PROV_G3 not in IRB pipeline results")

        assert "el_shortfall" in result, "el_shortfall column missing from IRB results"
        assert result["el_shortfall"] == pytest.approx(0.0, abs=0.01), (
            f"CRR-G3: el_shortfall should be 0 (provisions > EL), "
            f"got {result['el_shortfall']}"
        )


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
        assert scenario["approach"] == "SA", "CRR-G1 should use SA approach"

    def test_crr_g2_g3_use_firb_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-G2 and G3 (EL shortfall/excess) use F-IRB approach."""
        for scenario_id in ["CRR-G2", "CRR-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["approach"] == "F-IRB", f"{scenario_id} should use F-IRB approach"

    def test_crr_g_irb_scenarios_have_expected_loss(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify IRB provision scenarios have expected loss calculated."""
        for scenario_id in ["CRR-G2", "CRR-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["expected_loss"] is not None, f"{scenario_id} should have expected loss"
            assert scenario["expected_loss"] > 0, (
                f"{scenario_id} should have positive expected loss"
            )
