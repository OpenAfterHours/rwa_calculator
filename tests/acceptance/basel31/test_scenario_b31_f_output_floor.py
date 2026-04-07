"""
B31 Group F: Output Floor Acceptance Tests.

These tests validate the Basel 3.1 output floor mechanism, which ensures that
total IRB RWA cannot fall below a percentage of total SA-equivalent RWA at
portfolio level.

Why these tests matter:
    The output floor is the single most impactful Basel 3.1 change for IRB banks.
    TREA = max(U-TREA, x * S-TREA) at portfolio level. When the floor binds,
    the shortfall is distributed pro-rata across floor-eligible exposures
    proportional to each exposure's SA-equivalent RWA. Getting this wrong
    produces materially incorrect capital numbers.

Regulatory References:
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ)
- PRA PS1/26 Art. 92(5): Transitional schedule: 60% (2027), 65% (2028), 70% (2029), 72.5% (2030+)
"""

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

    1. Floor binding: portfolio floor binds when low-PD corporates dominate
    2. Per-exposure invariant: high-PD exposure's IRB RWA > its floor RWA
    3. Transitional: 2027 floor (60%) is lower than fully-phased floor (72.5%)
    """

    def test_b31_f1_output_floor_binding_low_pd(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-F1: Output floor should bind for low-PD corporate.

        Input: £1,000,000 corporate loan (LOAN_CORP_UK_003), CQS 2, PD=0.15%
        Expected: Floor binds because SA RWA × 72.5% > IRB RWA
        Rationale: CQS 2 corporates get 50% SA RW. The 72.5% floor
            (72.5% × 50% = 36.25% effective) exceeds the IRB risk weight
            (~24.8% for PD=0.15%), making the floor binding.
        """
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_CORP_UK_003")

        assert result is not None, "Exposure LOAN_CORP_UK_003 not found in B31 IRB results"

        # Verify this exposure was processed as IRB
        approach = str(result.get("approach", "")).upper()
        assert "IRB" in approach or "FIRB" in approach, (
            f"B31-F1: Expected IRB approach, got {approach}"
        )

        # The output floor should be binding for this low-PD exposure
        rwa_final = result.get("rwa_final", result.get("rwa", 0))
        assert rwa_final is not None and rwa_final > 0, "B31-F1: RWA should be positive"

        # Verify floor binding
        if "is_floor_binding" in result:
            assert result["is_floor_binding"] is True, (
                "B31-F1: Output floor should bind for low-PD corporate "
                f"(PD=0.15%, SA RW=50%). is_floor_binding={result['is_floor_binding']}"
            )

        if "sa_rwa" in result and "floor_rwa" in result:
            sa_rwa = result["sa_rwa"]
            floor_rwa = result["floor_rwa"]
            assert sa_rwa > 0, "B31-F1: SA RWA should be positive (CQS 2 corporate)"
            assert floor_rwa > 0, "B31-F1: Floor RWA should be positive"
            # Floor RWA should be approximately 72.5% of SA RWA
            assert floor_rwa == pytest.approx(sa_rwa * 0.725, rel=0.01), (
                f"B31-F1: Floor RWA ({floor_rwa:,.0f}) should be ~72.5% of SA RWA ({sa_rwa:,.0f})"
            )

    def test_b31_f2_high_pd_irb_exceeds_per_exposure_floor(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-F2: High-PD corporate's IRB RWA exceeds its per-exposure floor RWA.

        Input: £5,000,000 corporate loan (LOAN_CORP_UK_005), CQS 5, PD=5.00%
        Expected: This exposure's pre-floor IRB RWA > floor_rwa (SA × 72.5%)
        Rationale: High-PD corporates have very high IRB risk weights (>130%).
            CQS 5 corporates get 150% SA RW under Basel 3.1. The 72.5% floor
            (72.5% × 150% = 108.75% effective) is below the IRB risk weight.

        Note: is_floor_binding is now a portfolio-level flag per Art. 92 para 2A.
            Even if the portfolio floor binds (due to other low-PD exposures),
            this high-PD exposure's individual IRB RWA still exceeds its own
            floor RWA — the structural invariant holds regardless.
        """
        result = get_result_for_exposure(irb_pipeline_results_df, "LOAN_CORP_UK_005")

        assert result is not None, "Exposure LOAN_CORP_UK_005 not found in B31 IRB results"

        approach = str(result.get("approach", "")).upper()
        assert "IRB" in approach or "FIRB" in approach, (
            f"B31-F2: Expected IRB approach, got {approach}"
        )

        rwa_final = result.get("rwa_final", result.get("rwa", 0))
        assert rwa_final is not None and rwa_final > 0, "B31-F2: RWA should be positive"

        # Structural invariant: this exposure's pre-floor IRB RWA exceeds its
        # per-exposure floor RWA (sa_rwa × 72.5%). Under portfolio-level floor,
        # is_floor_binding is a portfolio-level flag, so we check the per-exposure
        # RWA comparison instead.
        if "sa_rwa" in result and "floor_rwa" in result:
            irb_rwa = result.get("rwa_pre_floor", result.get("rwa", 0))
            floor_rwa = result["floor_rwa"]
            assert irb_rwa > floor_rwa, (
                f"B31-F2: IRB RWA ({irb_rwa:,.0f}) should exceed "
                f"floor RWA ({floor_rwa:,.0f}) for high-PD exposure"
            )

    def test_b31_f3_transitional_floor_2027_60pct(
        self,
        transitional_results_df: pl.DataFrame,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-F3: Transitional floor in 2027 should be 60% (vs 72.5% fully-phased).

        Input: Same low-PD corporate as B31-F1 (LOAN_CORP_UK_003) with 2027 date
        Expected: Floor at 60% produces lower floored RWA than 72.5%
        Rationale: PRA PS1/26 Art. 92(5) phases in the floor gradually
            (60% in 2027 → 72.5% in 2030+), reducing the capital impact
            of the floor in the early years.
        """
        result_transitional = get_result_for_exposure(transitional_results_df, "LOAN_CORP_UK_003")
        result_full = get_result_for_exposure(irb_pipeline_results_df, "LOAN_CORP_UK_003")

        assert result_transitional is not None, (
            "Exposure LOAN_CORP_UK_003 not found in transitional results"
        )
        assert result_full is not None, "Exposure LOAN_CORP_UK_003 not found in full-phase results"

        # Both should be IRB
        for label, result in [("transitional", result_transitional), ("full", result_full)]:
            approach = str(result.get("approach", "")).upper()
            assert "IRB" in approach or "FIRB" in approach, (
                f"B31-F3 ({label}): Expected IRB approach, got {approach}"
            )

        # Verify transitional floor is lower
        if "floor_rwa" in result_transitional and "floor_rwa" in result_full:
            transitional_floor_rwa = result_transitional["floor_rwa"]
            full_floor_rwa = result_full["floor_rwa"]

            # Transitional (50%) should produce lower floor than full (72.5%)
            assert transitional_floor_rwa < full_floor_rwa, (
                f"B31-F3: Transitional floor RWA ({transitional_floor_rwa:,.0f}) "
                f"should be lower than fully-phased ({full_floor_rwa:,.0f})"
            )

            # Verify approximate ratio: transitional/full ≈ 60/72.5 ≈ 0.828
            if full_floor_rwa > 0:
                ratio = transitional_floor_rwa / full_floor_rwa
                assert ratio == pytest.approx(60.0 / 72.5, rel=0.05), (
                    f"B31-F3: Floor ratio ({ratio:.3f}) should be ~{60 / 72.5:.3f} (60% / 72.5%)"
                )

        # RWA under transitional should be lower or equal to full-phase RWA
        rwa_transitional = result_transitional.get("rwa_final", result_transitional.get("rwa", 0))
        rwa_full = result_full.get("rwa_final", result_full.get("rwa", 0))
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
        assert negative.height == 0, f"Found {negative.height} IRB exposures with negative RWA"

    def test_output_floor_never_reduces_rwa(
        self,
        irb_pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Output floor should only increase RWA, never decrease it.

        Portfolio-level: TREA = max(U-TREA, x × S-TREA).
        The pro-rata add-on is always >= 0, so rwa_final >= rwa_pre_floor.
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
