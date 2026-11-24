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
        Expected: Shortfall = EL - provisions, 100% deducted from CET1 (Art. 36(1)(d))

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
        Shortfall = 15,000 (100% deducted from CET1 per Art. 36(1)(d))
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
            f"CRR-G3: el_excess should be 38,750 (prov 50k - EL 11.25k), got {result['el_excess']}"
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
            f"CRR-G3: el_shortfall should be 0 (provisions > EL), got {result['el_shortfall']}"
        )


class TestCRRGroupG_PortfolioELSummary:
    """
    CRR-G Portfolio-level EL summary acceptance tests.

    Validates that the aggregator correctly computes the T2 credit cap
    per CRR Art. 62(d) and the 100% CET1 deduction per Art. 36(1)(d), Art. 159
    across all IRB exposures in the fixture portfolio.
    """

    def test_el_summary_populated(self, irb_pipeline_results) -> None:
        """The aggregated bundle should contain a portfolio-level EL summary."""
        assert irb_pipeline_results.el_summary is not None, (
            "el_summary should be populated when IRB results have EL columns"
        )

    def test_el_shortfall_nets_to_zero(self, irb_pipeline_results) -> None:
        """Portfolio EL shortfall is zero: the book nets to an excess (Art. 159(3)(d)).

        Derivation (from ``irb_pipeline_results.irb_results``, grouped by
        ``is_defaulted``, summing ``expected_loss`` (A/C) and
        ``provision_allocated`` (ava/other_own_funds_reductions are zero across
        the whole IRB fixture book). The one defaulted row carries specific CRA
        only, so 'D' is its whole provision; the book's 25,000 GCRA sits on
        non-defaulted rows and is in 'B' either way):

            Non-defaulted (80 rows): A = 807,797.0316109825
                                     B = 1,669,071.4285714286
            Defaulted (1 row, LOAN_DF_RTL_001 — LOAN_PROV_G2/G3 are both
            non-defaulted): C = 12,500.0, D = 11,250.0

            'A' > 'B' is false, so Art. 159(3) is NOT the two-branch case ->
            "in all other cases" one net figure:
            (B + D) - (A + C) = 1,680,321.4285714286 - 820,297.0316109825
                              = +860,024.3969604461 -> (d) excess, no shortfall.

        P1.210 re-pinned this from 1,250.00, which was the defaulted pool's gross
        'C' - 'D' reported beside a separate non-defaulted excess (no net).
        """
        el = irb_pipeline_results.el_summary
        if el is None:
            pytest.skip("el_summary not available")
        assert el.art_159_3_applies is False
        assert float(el.total_el_shortfall) == pytest.approx(0.0, abs=1e-6), (
            "Portfolio el_shortfall should be 0: (B + D) - (A + C) is positive, so "
            f"Art. 159(3)(d) reports an excess only, got {el.total_el_shortfall:,.2f}"
        )

    def test_el_excess_positive(self, irb_pipeline_results) -> None:
        """Portfolio EL excess is the Art. 159(3)(d) net (B + D) - (A + C).

        Derivation (same aggregate ingredients as ``test_el_shortfall_nets_to_zero``):

            (B + D) - (A + C) = (1,669,071.4285714286 + 11,250.0)
                              - (807,797.0316109825 + 12,500.0)
                              = 860,024.3969604461

        The non-defaulted surplus covers the defaulted pool's 1,250 gap: only
        defaulted SPECIFIC adjustments are ring-fenced, and only in the case
        'A' > 'B' and 'D' > 'C'. P1.210 re-pinned this from 861,274.3969604461
        ('B' - 'A' alone, reported beside a separate 1,250 shortfall).
        """
        el = irb_pipeline_results.el_summary
        if el is None:
            pytest.skip("el_summary not available")
        assert float(el.total_el_excess) == pytest.approx(860_024.3969604461, rel=1e-6), (
            "Portfolio el_excess should be the Art. 159(3)(d) net "
            f"860,024.40 ((B + D) - (A + C)), got {el.total_el_excess:,.2f}"
        )

    def test_t2_credit_cap_is_point_six_pct(self, irb_pipeline_results) -> None:
        """T2 credit cap should be 0.6% of total IRB RWA per CRR Art. 62(d)."""
        el = irb_pipeline_results.el_summary
        if el is None:
            pytest.skip("el_summary not available")
        expected_cap = float(el.total_irb_rwa) * 0.006
        assert float(el.t2_credit_cap) == pytest.approx(expected_cap, rel=1e-6), (
            f"T2 credit cap should be 0.6% of IRB RWA ({el.total_irb_rwa:.0f}), "
            f"expected {expected_cap:.2f}, got {el.t2_credit_cap:.2f}"
        )

    def test_t2_credit_capped_correctly(self, irb_pipeline_results) -> None:
        """T2 credit should be min(total_el_excess, t2_credit_cap)."""
        el = irb_pipeline_results.el_summary
        if el is None:
            pytest.skip("el_summary not available")
        expected_t2 = min(float(el.total_el_excess), float(el.t2_credit_cap))
        assert float(el.t2_credit) == pytest.approx(expected_t2, rel=1e-6), (
            f"T2 credit should be min(excess={el.total_el_excess:.2f}, "
            f"cap={el.t2_credit_cap:.2f}) = {expected_t2:.2f}, "
            f"got {el.t2_credit:.2f}"
        )

    def test_deduction_full_cet1(self, irb_pipeline_results) -> None:
        """EL shortfall deducted 100% from CET1 per Art. 36(1)(d), Art. 159."""
        el = irb_pipeline_results.el_summary
        if el is None:
            pytest.skip("el_summary not available")
        assert float(el.cet1_deduction) == pytest.approx(float(el.total_el_shortfall), rel=1e-6), (
            f"CET1 deduction should be 100% of shortfall ({el.total_el_shortfall:.2f})"
        )
        assert float(el.t2_deduction) == pytest.approx(0.0, abs=1e-6), (
            "T2 deduction should be 0 (no T2 shortfall deduction under CRR)"
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
