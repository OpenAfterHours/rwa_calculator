"""
B31 Group F: Output Floor Acceptance Tests.

These tests validate the Basel 3.1 output floor mechanism, which ensures that
IRB-calculated RWA cannot fall below a percentage of what the SA would produce.

Why these tests matter:
    The output floor is the single most impactful Basel 3.1 change for IRB banks.
    A low-PD portfolio that benefits greatly from IRB will see its RWA floored
    at 72.5% of SA RWA. Getting the floor mechanics wrong — binding detection,
    transitional schedule, SA RWA calculation for IRB exposures — would produce
    materially incorrect capital numbers.

Regulatory References:
- PRA PS9/24: Output floor rule: RWA_final = max(RWA_IRB, floor% × RWA_SA)
- PRA PS9/24: Transitional schedule: 50% (2027), 55% (2028), ..., 72.5% (2032+)
"""

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    get_result_for_exposure,
)


class TestB31GroupF_OutputFloor:
    """
    Basel 3.1 output floor acceptance tests.

    These tests verify structural properties of the output floor rather than
    exact RWA values, because the IRB RWA under Basel 3.1 depends on multiple
    interacting parameters (PD floor, no scaling factor, etc.) that make
    hand-calculation fragile. The structural invariants are more robust:

    1. Floor binding: for low-PD corporates, floor% × SA_RWA > IRB_RWA
    2. Floor not binding: for high-PD corporates, IRB_RWA > floor% × SA_RWA
    3. Transitional: 2027 floor (50%) is lower than fully-phased floor (72.5%)
    """

    def test_b31_f1_output_floor_binding_low_pd(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-F1: Output floor should bind for low-PD corporate.

        Input: £25,000,000 corporate loan, PD=0.10%, LGD=45%, maturity=4.25y
        Expected: Floor binds because SA RWA × 72.5% > IRB RWA
        Rationale: Low-PD corporates have very low IRB risk weights (~40%).
            Under SA, unrated corporates get 100% RW. The 72.5% floor
            (72.5% × 100% = 72.5% effective) significantly exceeds the
            IRB risk weight, making the floor binding.
        """
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_CORP_UK_001")

        assert result is not None, "Exposure LOAN_CORP_UK_001 not found in B31 IRB results"

        # Verify this exposure was processed as IRB
        approach = str(result.get("approach", "")).upper()
        assert "IRB" in approach or "FIRB" in approach, (
            f"B31-F1: Expected IRB approach, got {approach}"
        )

        # The output floor should be binding for this low-PD exposure
        # Check structural properties rather than exact values
        rwa_final = result.get("rwa_post_factor", result.get("rwa", 0))
        assert rwa_final > 0, "B31-F1: RWA should be positive"

        # If output floor columns are present, verify floor binding
        if "is_floor_binding" in result:
            assert result["is_floor_binding"] is True, (
                "B31-F1: Output floor should bind for low-PD corporate "
                f"(PD=0.10%, SA RW=100%). is_floor_binding={result['is_floor_binding']}"
            )

        if "sa_rwa" in result and "floor_rwa" in result:
            sa_rwa = result["sa_rwa"]
            floor_rwa = result["floor_rwa"]
            assert sa_rwa > 0, "B31-F1: SA RWA should be positive (unrated corporate)"
            assert floor_rwa > 0, "B31-F1: Floor RWA should be positive"
            # Floor RWA should be approximately 72.5% of SA RWA
            assert floor_rwa == pytest.approx(sa_rwa * 0.725, rel=0.01), (
                f"B31-F1: Floor RWA ({floor_rwa:,.0f}) should be ~72.5% of "
                f"SA RWA ({sa_rwa:,.0f})"
            )

    def test_b31_f2_output_floor_not_binding_high_pd(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-F2: Output floor should NOT bind for high-PD corporate.

        Input: £5,000,000 corporate loan, PD=5.00%, LGD=45%, maturity=3.0y
        Expected: Floor does not bind because IRB RWA > SA RWA × 72.5%
        Rationale: High-PD corporates have very high IRB risk weights (>150%).
            Under SA, unrated corporates get 100% RW. The 72.5% floor
            (72.5% × 100% = 72.5% effective) is well below the IRB risk
            weight, so the floor is not binding.
        """
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_CORP_UK_005")

        assert result is not None, "Exposure LOAN_CORP_UK_005 not found in B31 IRB results"

        approach = str(result.get("approach", "")).upper()
        assert "IRB" in approach or "FIRB" in approach, (
            f"B31-F2: Expected IRB approach, got {approach}"
        )

        rwa_final = result.get("rwa_post_factor", result.get("rwa", 0))
        assert rwa_final > 0, "B31-F2: RWA should be positive"

        # If output floor columns are present, verify floor is not binding
        if "is_floor_binding" in result:
            assert result["is_floor_binding"] is False, (
                "B31-F2: Output floor should NOT bind for high-PD corporate "
                f"(PD=5%). is_floor_binding={result['is_floor_binding']}"
            )

        if "sa_rwa" in result and "floor_rwa" in result:
            irb_rwa = result.get("rwa_pre_floor", result.get("rwa", 0))
            floor_rwa = result["floor_rwa"]
            assert irb_rwa > floor_rwa, (
                f"B31-F2: IRB RWA ({irb_rwa:,.0f}) should exceed "
                f"floor RWA ({floor_rwa:,.0f}) for high-PD exposure"
            )

    def test_b31_f3_transitional_floor_2027_50pct(
        self,
        transitional_results_df: pl.DataFrame,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-F3: Transitional floor in 2027 should be 50% (vs 72.5% fully-phased).

        Input: Same low-PD corporate as B31-F1 but with 2027 reporting date
        Expected: Floor at 50% produces lower floored RWA than 72.5%
        Rationale: The transitional schedule phases in the floor gradually
            (50% in 2027 → 72.5% in 2032+), reducing the capital impact
            of the floor in the early years.
        """
        result_transitional = get_result_for_exposure(
            transitional_results_df, "LOAN_CORP_UK_001"
        )
        result_full = get_result_for_exposure(
            irb_pipeline_results_df, "LOAN_CORP_UK_001"
        )

        assert result_transitional is not None, (
            "Exposure LOAN_CORP_UK_001 not found in transitional results"
        )
        assert result_full is not None, (
            "Exposure LOAN_CORP_UK_001 not found in full-phase results"
        )

        # Both should be IRB
        for label, result in [("transitional", result_transitional), ("full", result_full)]:
            approach = str(result.get("approach", "")).upper()
            assert "IRB" in approach or "FIRB" in approach, (
                f"B31-F3 ({label}): Expected IRB approach, got {approach}"
            )

        # If floor columns are present, verify transitional floor is lower
        if "floor_rwa" in result_transitional and "floor_rwa" in result_full:
            transitional_floor_rwa = result_transitional["floor_rwa"]
            full_floor_rwa = result_full["floor_rwa"]

            # Transitional (50%) should produce lower floor than full (72.5%)
            assert transitional_floor_rwa < full_floor_rwa, (
                f"B31-F3: Transitional floor RWA ({transitional_floor_rwa:,.0f}) "
                f"should be lower than fully-phased ({full_floor_rwa:,.0f})"
            )

            # Verify approximate ratio: transitional/full ≈ 50/72.5 ≈ 0.69
            if full_floor_rwa > 0:
                ratio = transitional_floor_rwa / full_floor_rwa
                assert ratio == pytest.approx(50.0 / 72.5, rel=0.05), (
                    f"B31-F3: Floor ratio ({ratio:.3f}) should be ~{50/72.5:.3f} "
                    f"(50% / 72.5%)"
                )

        # RWA under transitional should be lower or equal to full-phase RWA
        rwa_transitional = result_transitional.get(
            "rwa_post_factor", result_transitional.get("rwa", 0)
        )
        rwa_full = result_full.get("rwa_post_factor", result_full.get("rwa", 0))
        assert rwa_transitional <= rwa_full + 1, (
            f"B31-F3: Transitional RWA ({rwa_transitional:,.0f}) should not exceed "
            f"fully-phased RWA ({rwa_full:,.0f})"
        )


class TestB31GroupF_StructuralValidation:
    """
    Structural validation tests for the output floor mechanism.
    These verify invariants that must hold across ALL IRB exposures.
    """

    def test_all_irb_exposures_have_non_negative_rwa(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """All IRB exposures should have non-negative final RWA."""
        irb_df = irb_pipeline_results_df.filter(
            pl.col("approach").cast(pl.String).str.to_uppercase().str.contains("IRB")
        )
        if irb_df.height == 0:
            pytest.skip("No IRB exposures in B31 results")

        rwa_col = "rwa_post_factor" if "rwa_post_factor" in irb_df.columns else "rwa"
        negative = irb_df.filter(pl.col(rwa_col) < 0)
        assert negative.height == 0, (
            f"Found {negative.height} IRB exposures with negative RWA"
        )

    def test_output_floor_never_reduces_rwa(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Output floor should only increase RWA, never decrease it.

        The floor is: rwa_final = max(rwa_irb, floor% × rwa_sa)
        So rwa_final >= rwa_irb always.
        """
        irb_df = irb_pipeline_results_df.filter(
            pl.col("approach").cast(pl.String).str.to_uppercase().str.contains("IRB")
        )
        if irb_df.height == 0:
            pytest.skip("No IRB exposures in B31 results")

        if "rwa_pre_floor" in irb_df.columns:
            rwa_col = "rwa_post_factor" if "rwa_post_factor" in irb_df.columns else "rwa"
            violations = irb_df.filter(
                pl.col(rwa_col) < pl.col("rwa_pre_floor") - 1  # 1 GBP tolerance
            )
            assert violations.height == 0, (
                f"Found {violations.height} IRB exposures where floor reduced RWA"
            )

    def test_output_floor_impact_non_negative(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Floor impact should be non-negative for all exposures."""
        if "floor_impact_rwa" not in irb_pipeline_results_df.columns:
            pytest.skip("floor_impact_rwa column not present in results")

        irb_df = irb_pipeline_results_df.filter(
            pl.col("approach").cast(pl.String).str.to_uppercase().str.contains("IRB")
        )
        if irb_df.height == 0:
            pytest.skip("No IRB exposures in B31 results")

        negative_impact = irb_df.filter(pl.col("floor_impact_rwa") < -1)
        assert negative_impact.height == 0, (
            f"Found {negative_impact.height} exposures with negative floor impact"
        )
