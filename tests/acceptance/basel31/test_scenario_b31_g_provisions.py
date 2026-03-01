"""
Basel 3.1 Group G: Provisions & Impairments Acceptance Tests.

These tests validate that the production RWA calculator correctly handles
provisions under SA and EL shortfall/excess under F-IRB when running with
Basel 3.1 configuration (PRA PS9/24).

Key Basel 3.1 Differences for Provision Treatment:
- SA provision deduction: unchanged (SCRA reduces EAD before CCF)
- F-IRB supervisory LGD: 40% senior unsecured (was 45%, CRE32.9)
- Expected loss: PD x LGD x EAD — lower LGD reduces EL, changing shortfall/excess
- No 1.06 scaling factor: ~5.7% lower RWA on IRB exposures
- No supporting factor: SF=1.0 for all exposures

Why these tests matter:
    Provisions bridge credit loss accounting (IFRS 9) and capital requirements.
    Under Basel 3.1, the reduced F-IRB LGD (40% vs 45%) directly reduces
    expected loss, which changes the EL shortfall/excess calculation:
    - G2: EL drops from £45k (CRR) to £40k (B31), reducing shortfall from £15k to £10k
    - G3: EL drops from £11.25k (CRR) to £10k (B31), increasing excess from £38.75k to £40k
    The provision deduction mechanism itself (CRR Art 110) is unchanged.

Regulatory References:
- CRE20: SA exposure values (provision deduction unchanged)
- CRE31-32: IRB risk weight formula
- CRE32.9: Revised F-IRB supervisory LGD (40% senior unsecured)
- CRE35.1-3: Expected loss calculation
- CRR Art. 62(d): Excess provisions as T2 capital (capped at 0.6% IRB RWA)
- CRR Art. 110: Specific provisions reduce SA exposure value
- CRR Art. 158-159: EL shortfall treatment
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    assert_ead_match,
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references in fixtures
# Same exposures as CRR-G: the framework config drives different IRB results
SCENARIO_EXPOSURE_MAP = {
    "B31-G1": "LOAN_PROV_G1",
    "B31-G2": "LOAN_PROV_G2",
    "B31-G3": "LOAN_PROV_G3",
}


class TestB31GroupG_Provisions:
    """
    Basel 3.1 Provisions acceptance tests.

    Each test runs fixture data through the production calculator with
    Basel 3.1 config and compares output against expected values.
    """

    def test_b31_g1_sa_with_specific_provision(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-G1: SA exposure with specific provision reduces EAD.

        Input: £1M gross exposure, £50k specific provision (SCRA)
        Expected: Net EAD = £950k, RW = 100%, RWA = £950k

        Provision deduction mechanism is identical under CRR and Basel 3.1.
        The SCRA reduces EAD before CCF application (CRR Art 110).
        """
        expected = expected_outputs_dict["B31-G1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-G1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_ead_match(
            result["ead_final"],
            expected["ead"],
            scenario_id="B31-G1",
        )
        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="B31-G1",
        )

    def test_b31_g2_irb_el_shortfall(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-G2: F-IRB EL shortfall — provisions less than expected loss.

        Input: £5M exposure, PD 2%, LGD 40% (B31), provisions £30k
        Expected: EL = £40k (0.02 x 0.40 x 5M), shortfall = £10k

        Under CRR, EL was £45k (0.02 x 0.45 x 5M), shortfall was £15k.
        The Basel 3.1 LGD reduction directly reduces the EL shortfall,
        meaning less CET1/T2 deduction for the same provision level.
        """
        expected = expected_outputs_dict["B31-G2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-G2"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa"],
            expected["rwa_after_sf"],
            scenario_id="B31-G2",
        )

    def test_b31_g3_irb_el_excess(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-G3: F-IRB EL excess — provisions exceed expected loss.

        Input: £5M exposure, PD 0.5%, LGD 40% (B31), provisions £50k
        Expected: EL = £10k (0.005 x 0.40 x 5M), excess = £40k

        Under CRR, EL was £11.25k (0.005 x 0.45 x 5M), excess was £38.75k.
        T2 credit capped at 0.6% of IRB RWA = £13,919 (was £22,137 under CRR).
        The lower cap reflects the lower IRB RWA under Basel 3.1.
        """
        expected = expected_outputs_dict["B31-G3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-G3"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa"],
            expected["rwa_after_sf"],
            scenario_id="B31-G3",
        )


class TestB31GroupG_FrameworkDifferences:
    """
    Cross-framework structural validation tests.

    These tests verify Basel 3.1-specific behavioral changes for
    provision treatment without comparing exact values.
    """

    def test_b31_g1_provision_reduces_ead(
        self,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify SA provision deduction reduces EAD from £1M to £950k."""
        result = get_result_for_exposure(pipeline_results_df, "LOAN_PROV_G1")
        if result is None:
            pytest.skip("LOAN_PROV_G1 not in results")

        assert result["ead_final"] == pytest.approx(950_000.0, rel=0.001), (
            f"B31-G1: EAD should be 950k after 50k provision, got {result['ead_final']}"
        )
        assert result["provision_allocated"] == pytest.approx(50_000.0, rel=0.001), (
            f"B31-G1: Provision allocated should be 50k, got {result['provision_allocated']}"
        )

    def test_b31_g2_irb_expected_loss_uses_b31_lgd(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify F-IRB EL uses Basel 3.1 LGD (40%, not CRR 45%).

        EL = PD x LGD x EAD = 0.02 x 0.40 x 5M = £40,000
        Under CRR: 0.02 x 0.45 x 5M = £45,000
        """
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in F-IRB results")

        el = result.get("expected_loss", 0)
        assert el == pytest.approx(40_000.0, rel=0.01), (
            f"B31-G2: EL should be 40k (PD 2% × LGD 40% × 5M), got {el}"
        )

    def test_b31_g3_irb_expected_loss_uses_b31_lgd(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify F-IRB EL uses Basel 3.1 LGD for G3 scenario.

        EL = PD x LGD x EAD = 0.005 x 0.40 x 5M = £10,000
        Under CRR: 0.005 x 0.45 x 5M = £11,250
        """
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G3")
        if result is None:
            pytest.skip("LOAN_PROV_G3 not in F-IRB results")

        el = result.get("expected_loss", 0)
        assert el == pytest.approx(10_000.0, rel=0.01), (
            f"B31-G3: EL should be 10k (PD 0.5% × LGD 40% × 5M), got {el}"
        )

    def test_b31_g_irb_provisions_not_deducted_from_ead(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify IRB provisions are tracked but NOT deducted from EAD.

        Under both CRR and Basel 3.1, IRB provisions are compared to EL
        for capital adjustment — they don't reduce EAD directly.
        """
        for ref in ["LOAN_PROV_G2", "LOAN_PROV_G3"]:
            result = get_result_for_exposure(firb_results_df, ref)
            if result is None:
                continue
            assert result["ead_final"] == pytest.approx(5_000_000.0, rel=0.001), (
                f"{ref}: IRB EAD should be 5M (provisions don't reduce EAD), "
                f"got {result['ead_final']}"
            )
            assert result["provision_deducted"] == pytest.approx(0.0, abs=0.01), (
                f"{ref}: IRB provision_deducted should be 0 (tracked only), "
                f"got {result['provision_deducted']}"
            )

    def test_b31_g_no_supporting_factor(
        self,
        firb_results_df: pl.DataFrame,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify no supporting factor applied under Basel 3.1."""
        # Check SA exposure
        sa_result = get_result_for_exposure(pipeline_results_df, "LOAN_PROV_G1")
        if sa_result is not None:
            sf = sa_result.get("supporting_factor", 1.0)
            assert sf == pytest.approx(1.0, abs=0.0001), (
                f"B31-G1: SF should be 1.0, got {sf}"
            )
        # Check IRB exposures
        for ref in ["LOAN_PROV_G2", "LOAN_PROV_G3"]:
            result = get_result_for_exposure(firb_results_df, ref)
            if result is None:
                continue
            sf = result.get("supporting_factor", 1.0)
            assert sf == pytest.approx(1.0, abs=0.0001), (
                f"{ref}: SF should be 1.0 under Basel 3.1, got {sf}"
            )

    def test_b31_g2_supervisory_lgd_40pct(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify F-IRB supervisory LGD is 40% (Basel 3.1) not 45% (CRR)."""
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in F-IRB results")

        lgd = result.get("lgd")
        assert lgd is not None and lgd == pytest.approx(0.40, abs=0.01), (
            f"B31-G2: Senior unsecured LGD should be 40% under Basel 3.1, got {lgd}"
        )


class TestB31GroupG_ELShortfallExcess:
    """
    Basel 3.1 EL shortfall/excess column validation.

    Verifies that the production pipeline computes per-exposure
    el_shortfall and el_excess columns correctly under Basel 3.1.
    The lower LGD (40% vs 45%) reduces EL, changing the
    shortfall/excess balance compared to CRR.

    References:
    - CRE35.1-3: Expected loss calculation
    - CRE32.9: Revised F-IRB supervisory LGD (40%)
    - CRR Art. 159: EL shortfall treatment
    - CRR Art. 62(d): Excess provisions as T2 capital
    """

    def test_b31_g2_el_shortfall_column(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-G2: el_shortfall = max(0, EL - provisions) = 40k - 30k = 10k.

        EL = PD(2%) x LGD(40%) x EAD(5M) = 40,000 (CRR: 45,000)
        Provisions = 30,000
        Shortfall = 10,000 (CRR: 15,000) — 33% lower due to LGD reduction
        """
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in F-IRB results")

        assert "el_shortfall" in result, "el_shortfall column missing from IRB results"
        assert result["el_shortfall"] == pytest.approx(10_000.0, rel=0.01), (
            f"B31-G2: el_shortfall should be 10,000 (EL 40k - prov 30k), "
            f"got {result['el_shortfall']}"
        )

    def test_b31_g2_el_excess_is_zero(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """B31-G2: el_excess should be zero when EL > provisions."""
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in F-IRB results")

        assert "el_excess" in result, "el_excess column missing from IRB results"
        assert result["el_excess"] == pytest.approx(0.0, abs=0.01), (
            f"B31-G2: el_excess should be 0 (EL > provisions), got {result['el_excess']}"
        )

    def test_b31_g3_el_excess_column(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-G3: el_excess = max(0, provisions - EL) = 50k - 10k = 40k.

        EL = PD(0.5%) x LGD(40%) x EAD(5M) = 10,000 (CRR: 11,250)
        Provisions = 50,000
        Excess = 40,000 (CRR: 38,750) — higher excess due to lower EL
        """
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G3")
        if result is None:
            pytest.skip("LOAN_PROV_G3 not in F-IRB results")

        assert "el_excess" in result, "el_excess column missing from IRB results"
        assert result["el_excess"] == pytest.approx(40_000.0, rel=0.01), (
            f"B31-G3: el_excess should be 40,000 (prov 50k - EL 10k), "
            f"got {result['el_excess']}"
        )

    def test_b31_g3_el_shortfall_is_zero(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """B31-G3: el_shortfall should be zero when provisions > EL."""
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G3")
        if result is None:
            pytest.skip("LOAN_PROV_G3 not in F-IRB results")

        assert "el_shortfall" in result, "el_shortfall column missing from IRB results"
        assert result["el_shortfall"] == pytest.approx(0.0, abs=0.01), (
            f"B31-G3: el_shortfall should be 0 (provisions > EL), "
            f"got {result['el_shortfall']}"
        )

    def test_b31_g2_shortfall_lower_than_crr(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """B31-G2: Shortfall should be lower than CRR due to LGD 40% vs 45%.

        CRR shortfall: 45k - 30k = 15k
        B31 shortfall: 40k - 30k = 10k (33% lower)
        """
        result = get_result_for_exposure(firb_results_df, "LOAN_PROV_G2")
        if result is None:
            pytest.skip("LOAN_PROV_G2 not in F-IRB results")

        crr_shortfall = 15_000.0  # Known CRR value
        assert result["el_shortfall"] < crr_shortfall, (
            f"B31-G2: Shortfall ({result['el_shortfall']}) should be less than "
            f"CRR shortfall ({crr_shortfall}) due to lower LGD"
        )


class TestB31GroupG_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_b31_g_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-G scenarios exist in expected outputs."""
        expected_ids = ["B31-G1", "B31-G2", "B31-G3"]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_b31_g1_uses_sa_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify B31-G1 (SA provision) uses SA approach."""
        scenario = expected_outputs_dict["B31-G1"]
        assert scenario["approach"] == "SA", "B31-G1 should use SA approach"

    def test_b31_g2_g3_use_firb_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify B31-G2 and G3 (EL shortfall/excess) use F-IRB approach."""
        for scenario_id in ["B31-G2", "B31-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["approach"] == "F-IRB", (
                f"{scenario_id} should use F-IRB approach"
            )

    def test_b31_g_irb_scenarios_have_expected_loss(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify IRB provision scenarios have expected loss calculated."""
        for scenario_id in ["B31-G2", "B31-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["expected_loss"] is not None, (
                f"{scenario_id} should have expected loss"
            )
            assert scenario["expected_loss"] > 0, (
                f"{scenario_id} should have positive expected loss"
            )

    def test_b31_g_irb_lgd_is_40pct(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify F-IRB scenarios use Basel 3.1 supervisory LGD 40%."""
        for scenario_id in ["B31-G2", "B31-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["lgd"] == pytest.approx(0.40, abs=0.001), (
                f"{scenario_id}: LGD should be 0.40 (Basel 3.1 senior unsecured)"
            )

    def test_b31_g_supporting_factor_disabled(
        self,
        b31_g_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-G scenarios have SF=1.0 (disabled under Basel 3.1)."""
        for scenario in b31_g_scenarios:
            sf = scenario["supporting_factor"]
            assert sf == 1.0, (
                f"Scenario {scenario['scenario_id']}: SF should be 1.0, got {sf}"
            )
            assert scenario["rwa_before_sf"] == pytest.approx(
                scenario["rwa_after_sf"], rel=0.001
            ), (
                f"Scenario {scenario['scenario_id']}: RWA before/after SF "
                f"should be equal when SF=1.0"
            )
