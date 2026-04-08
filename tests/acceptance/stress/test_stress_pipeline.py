"""
Stress tests for pipeline correctness at scale.

These tests validate that the RWA pipeline produces correct results with
large datasets (10K+ counterparties, 30K+ exposures). Unlike benchmarks
that measure timing, these tests assert on correctness properties:

- Row count preservation (input exposures == output rows)
- Numerical stability (no NaN/inf, finite sums)
- Risk weight regulatory bounds (0% to 1250%)
- Approach distribution matches entity type mix
- Output floor works correctly at portfolio level
- Error accumulation is bounded and non-destructive
- Column completeness in output frames

References:
- CRR Art. 92: Own funds requirements
- PRA PS1/26 Art. 92 para 2A-5: Output floor
"""

from __future__ import annotations

import tracemalloc
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode

from .conftest import run_pipeline

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle


# ---------------------------------------------------------------------------
# Required output columns that every pipeline result must contain
# ---------------------------------------------------------------------------

REQUIRED_OUTPUT_COLUMNS = {
    "exposure_reference",
    "exposure_class",
    "risk_weight",
    "ead_final",
    "rwa_final",
    "approach_applied",
}


# =============================================================================
# Row Count Preservation
# =============================================================================


class TestRowCountPreservation:
    """Every input exposure must produce exactly one output row.

    Why: Silent data loss at scale (from failed joins, dropped nulls, or filter
    errors) is the most dangerous pipeline bug — rows vanish without error.

    Note: The pipeline creates three exposure types in the output:
    - "loan" (from loans table)
    - "contingent" (from contingents table)
    - "facility_undrawn" (undrawn portions of committed facilities)
    So output rows = n_loans + n_contingents + n_facility_undrawn.
    """

    def _get_expected_counts(
        self, dataset: dict[str, pl.LazyFrame]
    ) -> tuple[int, int]:
        """Return (n_loans, n_contingents) from dataset."""
        n_loans = dataset["loans"].select(pl.len()).collect().item()
        n_contingents = dataset["contingents"].select(pl.len()).collect().item()
        return n_loans, n_contingents

    def test_crr_sa_loans_preserved(
        self,
        crr_sa_result_10k: AggregatedResultBundle,
        stress_dataset_10k: dict[str, pl.LazyFrame],
    ):
        """CRR SA: all input loans appear in output."""
        n_loans, _ = self._get_expected_counts(stress_dataset_10k)
        df = crr_sa_result_10k.results.collect()
        output_loans = df.filter(pl.col("exposure_type") == "loan").height
        assert output_loans == n_loans, (
            f"Loan count mismatch: {output_loans} output vs {n_loans} input"
        )

    def test_crr_sa_contingents_preserved(
        self,
        crr_sa_result_10k: AggregatedResultBundle,
        stress_dataset_10k: dict[str, pl.LazyFrame],
    ):
        """CRR SA: all input contingents appear in output."""
        _, n_contingents = self._get_expected_counts(stress_dataset_10k)
        df = crr_sa_result_10k.results.collect()
        output_contingents = df.filter(pl.col("exposure_type") == "contingent").height
        assert output_contingents == n_contingents, (
            f"Contingent count mismatch: {output_contingents} output vs {n_contingents} input"
        )

    def test_crr_sa_no_unknown_types(self, crr_sa_result_10k: AggregatedResultBundle):
        """CRR SA: all exposure types are known."""
        df = crr_sa_result_10k.results.collect()
        known_types = {"loan", "contingent", "facility_undrawn"}
        actual_types = set(df["exposure_type"].unique().to_list())
        unknown = actual_types - known_types
        assert not unknown, f"Unknown exposure types: {unknown}"

    def test_crr_irb_loans_preserved(
        self,
        crr_irb_result_10k: AggregatedResultBundle,
        stress_dataset_10k: dict[str, pl.LazyFrame],
    ):
        """CRR IRB: all input loans appear in output."""
        n_loans, _ = self._get_expected_counts(stress_dataset_10k)
        df = crr_irb_result_10k.results.collect()
        output_loans = df.filter(pl.col("exposure_type") == "loan").height
        assert output_loans == n_loans

    def test_b31_sa_loans_preserved(
        self,
        b31_sa_result_10k: AggregatedResultBundle,
        stress_dataset_10k: dict[str, pl.LazyFrame],
    ):
        """Basel 3.1 SA: all input loans appear in output."""
        n_loans, _ = self._get_expected_counts(stress_dataset_10k)
        df = b31_sa_result_10k.results.collect()
        output_loans = df.filter(pl.col("exposure_type") == "loan").height
        assert output_loans == n_loans

    def test_b31_irb_loans_preserved(
        self,
        b31_irb_result_10k: AggregatedResultBundle,
        stress_dataset_10k: dict[str, pl.LazyFrame],
    ):
        """Basel 3.1 IRB: all input loans appear in output."""
        n_loans, _ = self._get_expected_counts(stress_dataset_10k)
        df = b31_irb_result_10k.results.collect()
        output_loans = df.filter(pl.col("exposure_type") == "loan").height
        assert output_loans == n_loans

    def test_b31_irb_contingents_preserved(
        self,
        b31_irb_result_10k: AggregatedResultBundle,
        stress_dataset_10k: dict[str, pl.LazyFrame],
    ):
        """Basel 3.1 IRB: all input contingents appear in output."""
        _, n_contingents = self._get_expected_counts(stress_dataset_10k)
        df = b31_irb_result_10k.results.collect()
        output_contingents = df.filter(pl.col("exposure_type") == "contingent").height
        assert output_contingents == n_contingents

    def test_facility_undrawn_rows_created(self, crr_sa_result_10k: AggregatedResultBundle):
        """Committed facilities should generate undrawn exposure rows."""
        df = crr_sa_result_10k.results.collect()
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn").height
        assert undrawn > 0, "No facility_undrawn rows — committed facilities should create them"


# =============================================================================
# Column Completeness
# =============================================================================


class TestColumnCompleteness:
    """Pipeline output must contain all required analytical columns.

    Why: Missing columns indicate a broken pipeline stage — downstream
    COREP reporting and Pillar III disclosures depend on these fields.
    """

    def test_crr_sa_columns(self, crr_sa_result_10k: AggregatedResultBundle):
        """CRR SA output contains all required columns."""
        results_df = crr_sa_result_10k.results.collect()
        missing = REQUIRED_OUTPUT_COLUMNS - set(results_df.columns)
        assert not missing, f"Missing output columns: {missing}"

    def test_crr_irb_columns(self, crr_irb_result_10k: AggregatedResultBundle):
        """CRR IRB output contains all required columns."""
        results_df = crr_irb_result_10k.results.collect()
        missing = REQUIRED_OUTPUT_COLUMNS - set(results_df.columns)
        assert not missing, f"Missing output columns: {missing}"

    def test_b31_sa_columns(self, b31_sa_result_10k: AggregatedResultBundle):
        """B31 SA output contains all required columns."""
        results_df = b31_sa_result_10k.results.collect()
        missing = REQUIRED_OUTPUT_COLUMNS - set(results_df.columns)
        assert not missing, f"Missing output columns: {missing}"

    def test_b31_irb_columns(self, b31_irb_result_10k: AggregatedResultBundle):
        """B31 IRB output contains all required columns."""
        results_df = b31_irb_result_10k.results.collect()
        missing = REQUIRED_OUTPUT_COLUMNS - set(results_df.columns)
        assert not missing, f"Missing output columns: {missing}"


# =============================================================================
# Numerical Stability
# =============================================================================


class TestNumericalStability:
    """Verify numerical correctness properties at scale.

    Why: Floating point accumulation errors, NaN propagation from edge cases,
    and inf from division-by-zero are most likely to manifest at scale.
    """

    def test_no_nan_in_rwa_crr_sa(self, crr_sa_result_10k: AggregatedResultBundle):
        """No NaN values in rwa_final column."""
        df = crr_sa_result_10k.results.collect()
        nan_count = df.select(pl.col("rwa_final").is_nan().sum()).item()
        assert nan_count == 0, f"Found {nan_count} NaN values in rwa_final"

    def test_no_nan_in_rwa_b31_irb(self, b31_irb_result_10k: AggregatedResultBundle):
        """No NaN values in rwa_final under B31 IRB."""
        df = b31_irb_result_10k.results.collect()
        nan_count = df.select(pl.col("rwa_final").is_nan().sum()).item()
        assert nan_count == 0, f"Found {nan_count} NaN values in rwa_final"

    def test_no_inf_in_rwa(self, crr_sa_result_10k: AggregatedResultBundle):
        """No infinite values in rwa_final."""
        df = crr_sa_result_10k.results.collect()
        inf_count = df.select(pl.col("rwa_final").is_infinite().sum()).item()
        assert inf_count == 0, f"Found {inf_count} infinite values in rwa_final"

    def test_no_negative_rwa(self, crr_sa_result_10k: AggregatedResultBundle):
        """RWA must be non-negative (RW can be 0% but not negative)."""
        df = crr_sa_result_10k.results.collect()
        neg_count = df.filter(pl.col("rwa_final") < 0).height
        assert neg_count == 0, f"Found {neg_count} negative RWA values"

    def test_rwa_sum_is_finite_crr(self, crr_sa_result_10k: AggregatedResultBundle):
        """Total RWA sum is finite and positive."""
        df = crr_sa_result_10k.results.collect()
        total = df.select(pl.col("rwa_final").sum()).item()
        assert total > 0, "Total RWA should be positive for a non-trivial portfolio"
        assert total < float("inf"), "Total RWA must be finite"

    def test_rwa_sum_is_finite_b31(self, b31_irb_result_10k: AggregatedResultBundle):
        """Total RWA sum is finite and positive under Basel 3.1."""
        df = b31_irb_result_10k.results.collect()
        total = df.select(pl.col("rwa_final").sum()).item()
        assert total > 0
        assert total < float("inf")

    def test_no_null_rwa(self, crr_sa_result_10k: AggregatedResultBundle):
        """rwa_final should have no null values — every exposure gets an RWA."""
        df = crr_sa_result_10k.results.collect()
        null_count = df.select(pl.col("rwa_final").is_null().sum()).item()
        assert null_count == 0, f"Found {null_count} null rwa_final values"

    def test_no_null_risk_weight(self, crr_sa_result_10k: AggregatedResultBundle):
        """risk_weight should have no null values."""
        df = crr_sa_result_10k.results.collect()
        null_count = df.select(pl.col("risk_weight").is_null().sum()).item()
        assert null_count == 0, f"Found {null_count} null risk_weight values"

    def test_no_nan_in_ead(self, crr_sa_result_10k: AggregatedResultBundle):
        """No NaN values in ead_final."""
        df = crr_sa_result_10k.results.collect()
        nan_count = df.select(pl.col("ead_final").is_nan().sum()).item()
        assert nan_count == 0, f"Found {nan_count} NaN values in ead_final"

    def test_b31_no_negative_rwa(self, b31_irb_result_10k: AggregatedResultBundle):
        """Basel 3.1 IRB: no negative RWA."""
        df = b31_irb_result_10k.results.collect()
        neg_count = df.filter(pl.col("rwa_final") < 0).height
        assert neg_count == 0, f"Found {neg_count} negative RWA values"


# =============================================================================
# Risk Weight Bounds
# =============================================================================


class TestRiskWeightBounds:
    """Risk weights must be within regulatory bounds.

    Why: Under both CRR and Basel 3.1, SA risk weights range from 0%
    (sovereign/central bank) to 1250% (deduction-equivalent). IRB risk weights
    are model-derived but must still be non-negative.

    References:
    - CRR Art. 114-134 (SA risk weights)
    - CRR Art. 153 (IRB risk weight formula)
    """

    def test_sa_rw_bounds_crr(self, crr_sa_result_10k: AggregatedResultBundle):
        """CRR SA risk weights within [0%, 1250%]."""
        df = crr_sa_result_10k.results.collect()
        rw_min = df.select(pl.col("risk_weight").min()).item()
        rw_max = df.select(pl.col("risk_weight").max()).item()
        assert rw_min >= 0.0, f"Risk weight below 0%: {rw_min}"
        assert rw_max <= 12.50, f"Risk weight above 1250%: {rw_max}"

    def test_sa_rw_bounds_b31(self, b31_sa_result_10k: AggregatedResultBundle):
        """Basel 3.1 SA risk weights within [0%, 1250%]."""
        df = b31_sa_result_10k.results.collect()
        rw_min = df.select(pl.col("risk_weight").min()).item()
        rw_max = df.select(pl.col("risk_weight").max()).item()
        assert rw_min >= 0.0, f"Risk weight below 0%: {rw_min}"
        assert rw_max <= 12.50, f"Risk weight above 1250%: {rw_max}"

    def test_irb_rw_non_negative(self, crr_irb_result_10k: AggregatedResultBundle):
        """CRR IRB risk weights must be non-negative."""
        df = crr_irb_result_10k.results.collect()
        neg_count = df.filter(pl.col("risk_weight") < 0).height
        assert neg_count == 0, f"Found {neg_count} negative IRB risk weights"

    def test_irb_rw_non_negative_b31(self, b31_irb_result_10k: AggregatedResultBundle):
        """Basel 3.1 IRB risk weights must be non-negative."""
        df = b31_irb_result_10k.results.collect()
        neg_count = df.filter(pl.col("risk_weight") < 0).height
        assert neg_count == 0, f"Found {neg_count} negative IRB risk weights"


# =============================================================================
# Approach Distribution
# =============================================================================


class TestApproachDistribution:
    """Verify exposure routing to correct calculation approaches.

    Why: Misrouting at scale (e.g., corporate to slotting, or retail to IRB when
    not permitted) produces systematically wrong capital numbers.
    """

    def test_sa_only_mode_all_sa(self, crr_sa_result_10k: AggregatedResultBundle):
        """In SA-only mode, all exposures should use SA approach."""
        df = crr_sa_result_10k.results.collect()
        approaches = df.select("approach_applied").unique()["approach_applied"].to_list()
        # SA-only mode: all approaches should be "standardised" or "equity" (equity is separate)
        for approach in approaches:
            assert approach in ("standardised", "equity", "slotting"), (
                f"Unexpected approach in SA mode: {approach}"
            )

    def test_irb_mode_has_irb_exposures(self, crr_irb_result_10k: AggregatedResultBundle):
        """In IRB mode, some exposures should use IRB approaches."""
        df = crr_irb_result_10k.results.collect()
        approaches = set(df.select("approach_applied").unique()["approach_applied"].to_list())
        # With mixed entity types, IRB mode should route some to FIRB/AIRB
        irb_approaches = approaches & {"foundation_irb", "advanced_irb"}
        assert len(irb_approaches) > 0, (
            f"No IRB exposures found in IRB mode. Approaches: {approaches}"
        )

    def test_irb_exposures_have_rwa(self, crr_irb_result_10k: AggregatedResultBundle):
        """IRB exposures should have positive RWA (not zero from miscalculation)."""
        df = crr_irb_result_10k.results.collect()
        irb_df = df.filter(pl.col("approach_applied").is_in(["advanced_irb", "foundation_irb"]))
        assert irb_df.height > 0, "No IRB exposures to check"
        irb_rwa = irb_df.select(pl.col("rwa_final").sum()).item()
        assert irb_rwa > 0, "Total IRB RWA should be positive"

    def test_approach_count_matches_total(self, crr_irb_result_10k: AggregatedResultBundle):
        """Sum of per-approach counts equals total row count."""
        df = crr_irb_result_10k.results.collect()
        approach_counts = df.group_by("approach_applied").len()
        total_from_approaches = approach_counts.select(pl.col("len").sum()).item()
        assert total_from_approaches == len(df)

    def test_b31_irb_has_mixed_approaches(self, b31_irb_result_10k: AggregatedResultBundle):
        """Basel 3.1 IRB should have SA, IRB and potentially slotting exposures."""
        df = b31_irb_result_10k.results.collect()
        approaches = set(df.select("approach_applied").unique()["approach_applied"].to_list())
        assert "standardised" in approaches, "B31 IRB should have SA exposures"


# =============================================================================
# Exposure Class Coverage
# =============================================================================


class TestExposureClassCoverage:
    """Verify all expected exposure classes appear in output.

    Why: Our synthetic data includes corporate, retail, institution, sovereign,
    and specialised lending. All should produce output rows with correct
    exposure class assignments.
    """

    def test_multiple_exposure_classes_crr(self, crr_sa_result_10k: AggregatedResultBundle):
        """CRR SA produces multiple exposure classes."""
        df = crr_sa_result_10k.results.collect()
        n_classes = df.select("exposure_class").n_unique()
        assert n_classes >= 3, f"Only {n_classes} exposure classes — expected at least 3"

    def test_multiple_exposure_classes_b31(self, b31_sa_result_10k: AggregatedResultBundle):
        """Basel 3.1 SA produces multiple exposure classes."""
        df = b31_sa_result_10k.results.collect()
        n_classes = df.select("exposure_class").n_unique()
        assert n_classes >= 3, f"Only {n_classes} exposure classes — expected at least 3"

    def test_corporate_class_exists(self, crr_sa_result_10k: AggregatedResultBundle):
        """Corporate exposure class should be present (35% of entities are corporate)."""
        df = crr_sa_result_10k.results.collect()
        classes = df.select("exposure_class").unique()["exposure_class"].to_list()
        corporate_classes = [c for c in classes if c and "corporate" in c.lower()]
        assert len(corporate_classes) > 0, f"No corporate class found. Classes: {classes}"

    def test_retail_class_exists(self, crr_sa_result_10k: AggregatedResultBundle):
        """Retail exposure class should be present (30% of entities are retail)."""
        df = crr_sa_result_10k.results.collect()
        classes = df.select("exposure_class").unique()["exposure_class"].to_list()
        retail_classes = [c for c in classes if c and "retail" in c.lower()]
        assert len(retail_classes) > 0, f"No retail class found. Classes: {classes}"


# =============================================================================
# Output Floor at Scale (Basel 3.1)
# =============================================================================


class TestOutputFloorAtScale:
    """Verify Basel 3.1 output floor works correctly at portfolio level.

    Why: The output floor (Art. 92 para 2A) applies at portfolio level, not
    per-exposure. At 10K+ scale, the portfolio-level aggregation must
    correctly compute U-TREA and S-TREA across all approaches.

    References:
    - PRA PS1/26 Art. 92 para 2A-5
    """

    def test_output_floor_summary_exists(self, b31_irb_result_10k: AggregatedResultBundle):
        """Basel 3.1 IRB result should have an output floor summary."""
        assert b31_irb_result_10k.output_floor_summary is not None

    def test_u_trea_positive(self, b31_irb_result_10k: AggregatedResultBundle):
        """U-TREA (unweighted total risk exposure) should be positive."""
        ofs = b31_irb_result_10k.output_floor_summary
        assert ofs is not None
        assert ofs.u_trea > 0, f"U-TREA should be positive, got {ofs.u_trea}"

    def test_s_trea_positive(self, b31_irb_result_10k: AggregatedResultBundle):
        """S-TREA (standardised total risk exposure) should be positive."""
        ofs = b31_irb_result_10k.output_floor_summary
        assert ofs is not None
        assert ofs.s_trea > 0, f"S-TREA should be positive, got {ofs.s_trea}"

    def test_floor_percentage_valid(self, b31_irb_result_10k: AggregatedResultBundle):
        """Floor percentage should be between 50% and 72.5%."""
        ofs = b31_irb_result_10k.output_floor_summary
        assert ofs is not None
        assert 0.50 <= ofs.floor_pct <= 0.725, f"Floor pct out of range: {ofs.floor_pct}"

    def test_total_rwa_post_floor_gte_u_trea(
        self, b31_irb_result_10k: AggregatedResultBundle
    ):
        """Post-floor RWA >= U-TREA (floor can only increase capital)."""
        ofs = b31_irb_result_10k.output_floor_summary
        assert ofs is not None
        assert ofs.total_rwa_post_floor >= ofs.u_trea - 1.0, (
            f"Post-floor {ofs.total_rwa_post_floor} < U-TREA {ofs.u_trea}"
        )

    def test_no_output_floor_for_crr(self, crr_irb_result_10k: AggregatedResultBundle):
        """CRR should not have an output floor summary."""
        assert crr_irb_result_10k.output_floor_summary is None

    def test_no_output_floor_for_sa_only(self, b31_sa_result_10k: AggregatedResultBundle):
        """SA-only mode should not apply output floor (no IRB to floor)."""
        # The floor compares modelled vs SA. In SA-only mode, U-TREA == S-TREA
        # and the floor is never binding. Summary may still exist but shortfall == 0.
        ofs = b31_sa_result_10k.output_floor_summary
        if ofs is not None:
            assert ofs.shortfall == pytest.approx(0.0, abs=1.0), (
                f"SA-only should have zero shortfall, got {ofs.shortfall}"
            )


# =============================================================================
# Error Accumulation
# =============================================================================


class TestErrorAccumulation:
    """Verify error handling is bounded and non-destructive.

    Why: At scale, data quality issues accumulate. The error list must not
    grow unboundedly (memory) or cause pipeline failure (correctness).
    """

    def test_errors_is_list(self, crr_sa_result_10k: AggregatedResultBundle):
        """Errors should be a list, not None."""
        assert isinstance(crr_sa_result_10k.errors, list)

    def test_errors_bounded(self, crr_sa_result_10k: AggregatedResultBundle):
        """Error count should be reasonable (not one per row)."""
        n_errors = len(crr_sa_result_10k.errors)
        # Errors are typically per-class or per-column, not per-row
        assert n_errors < 1000, f"Too many errors ({n_errors}) — likely per-row error emission"

    def test_pipeline_succeeds_with_errors(self, crr_sa_result_10k: AggregatedResultBundle):
        """Pipeline should produce results even with data quality warnings."""
        df = crr_sa_result_10k.results.collect()
        assert len(df) > 0, "Pipeline produced no results despite having input data"

    def test_b31_errors_bounded(self, b31_irb_result_10k: AggregatedResultBundle):
        """Basel 3.1 IRB error count should be bounded."""
        n_errors = len(b31_irb_result_10k.errors)
        assert n_errors < 1000, f"Too many errors ({n_errors})"


# =============================================================================
# Summary Consistency
# =============================================================================


class TestSummaryConsistency:
    """Verify pipeline summaries are consistent with detailed results.

    Why: Summary aggregates (total RWA, count by class) must match the
    detailed per-exposure results. Discrepancies indicate aggregation bugs.
    """

    def test_summary_by_class_total_matches(self, crr_sa_result_10k: AggregatedResultBundle):
        """RWA sum from summary_by_class should approximate results total."""
        if crr_sa_result_10k.summary_by_class is None:
            pytest.skip("No summary_by_class available")

        summary_df = crr_sa_result_10k.summary_by_class
        if isinstance(summary_df, pl.LazyFrame):
            summary_df = summary_df.collect()

        results_df = crr_sa_result_10k.results.collect()

        if "rwa_final" in summary_df.columns:
            summary_total = summary_df.select(pl.col("rwa_final").sum()).item()
            results_total = results_df.select(pl.col("rwa_final").sum()).item()
            assert summary_total == pytest.approx(results_total, rel=0.01), (
                f"Summary RWA {summary_total} != results RWA {results_total}"
            )

    def test_summary_by_approach_covers_all(self, crr_irb_result_10k: AggregatedResultBundle):
        """summary_by_approach should cover all approaches in results."""
        if crr_irb_result_10k.summary_by_approach is None:
            pytest.skip("No summary_by_approach available")

        summary_df = crr_irb_result_10k.summary_by_approach
        if isinstance(summary_df, pl.LazyFrame):
            summary_df = summary_df.collect()

        results_df = crr_irb_result_10k.results.collect()
        result_approaches = set(results_df["approach_applied"].unique().to_list())

        if "approach_applied" in summary_df.columns:
            summary_approaches = set(summary_df["approach_applied"].unique().to_list())
            missing = result_approaches - summary_approaches
            assert not missing, f"Approaches in results but not summary: {missing}"


# =============================================================================
# EAD Consistency
# =============================================================================


class TestEADConsistency:
    """Verify EAD values are reasonable at scale.

    Why: EAD drives RWA. At scale, CCF miscalculation or join errors
    can produce zero EAD or wildly inflated EAD for off-balance items.
    """

    def test_no_negative_ead(self, crr_sa_result_10k: AggregatedResultBundle):
        """EAD must be non-negative."""
        df = crr_sa_result_10k.results.collect()
        neg = df.filter(pl.col("ead_final") < 0).height
        assert neg == 0, f"Found {neg} negative EAD values"

    def test_ead_sum_positive(self, crr_sa_result_10k: AggregatedResultBundle):
        """Total EAD should be positive for a non-trivial portfolio."""
        df = crr_sa_result_10k.results.collect()
        total_ead = df.select(pl.col("ead_final").sum()).item()
        assert total_ead > 0, "Total EAD should be positive"

    def test_no_null_ead(self, crr_sa_result_10k: AggregatedResultBundle):
        """ead_final should have no null values."""
        df = crr_sa_result_10k.results.collect()
        null_count = df.select(pl.col("ead_final").is_null().sum()).item()
        assert null_count == 0, f"Found {null_count} null ead_final values"

    def test_ead_no_nan(self, b31_irb_result_10k: AggregatedResultBundle):
        """No NaN in ead_final under B31 IRB."""
        df = b31_irb_result_10k.results.collect()
        nan_count = df.select(pl.col("ead_final").is_nan().sum()).item()
        assert nan_count == 0


# =============================================================================
# Determinism
# =============================================================================


class TestDeterminism:
    """Pipeline must produce identical results given identical input.

    Why: Non-determinism (from hash ordering, parallel execution, or
    floating-point reordering) means results cannot be audited.
    """

    def test_crr_sa_deterministic(self, stress_dataset_10k: dict[str, pl.LazyFrame]):
        """Two runs of the same CRR SA pipeline produce identical RWA totals."""
        config = CalculationConfig.crr(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.STANDARDISED,
        )
        result_a = run_pipeline(stress_dataset_10k, config)
        result_b = run_pipeline(stress_dataset_10k, config)

        total_a = result_a.results.collect().select(pl.col("rwa_final").sum()).item()
        total_b = result_b.results.collect().select(pl.col("rwa_final").sum()).item()

        assert total_a == pytest.approx(total_b, rel=1e-10), (
            f"Non-deterministic results: {total_a} vs {total_b}"
        )


# =============================================================================
# Framework Comparison
# =============================================================================


class TestFrameworkComparison:
    """Verify cross-framework properties at scale.

    Why: Basel 3.1 introduces higher SA weights (equity 250%, currency mismatch 1.5x)
    and output floor. At scale, these should manifest as measurable differences.
    """

    def test_b31_sa_rwa_differs_from_crr(
        self,
        crr_sa_result_10k: AggregatedResultBundle,
        b31_sa_result_10k: AggregatedResultBundle,
    ):
        """B31 SA total RWA should differ from CRR SA (different risk weights)."""
        crr_total = crr_sa_result_10k.results.collect().select(pl.col("rwa_final").sum()).item()
        b31_total = b31_sa_result_10k.results.collect().select(pl.col("rwa_final").sum()).item()
        # B31 generally produces higher RWA due to higher equity weights, etc.
        assert crr_total != pytest.approx(b31_total, rel=0.01), (
            f"CRR and B31 SA should differ: CRR={crr_total:.0f}, B31={b31_total:.0f}"
        )


# =============================================================================
# Large Scale (100K) — excluded from normal runs
# =============================================================================


@pytest.mark.slow
class TestLargeScale100K:
    """100K counterparty tests (~300K+ exposures).

    Why: Some bugs only manifest at scale — hash collisions in joins,
    memory pressure causing silent truncation, or O(n^2) operations
    becoming observable. These tests catch scale-dependent failures.
    """

    def test_row_count_100k(
        self,
        stress_dataset_100k: dict[str, pl.LazyFrame],
    ):
        """100K: all input loans preserved in output."""
        config = CalculationConfig.crr(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.STANDARDISED,
        )
        result = run_pipeline(stress_dataset_100k, config)

        n_loans = stress_dataset_100k["loans"].select(pl.len()).collect().item()
        results_df = result.results.collect()
        output_loans = results_df.filter(pl.col("exposure_type") == "loan").height
        assert output_loans == n_loans, (
            f"Loan count: {output_loans} output vs {n_loans} input"
        )

    def test_numerical_stability_100k(
        self,
        stress_dataset_100k: dict[str, pl.LazyFrame],
    ):
        """100K: no NaN or inf in RWA."""
        config = CalculationConfig.crr(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.STANDARDISED,
        )
        result = run_pipeline(stress_dataset_100k, config)
        df = result.results.collect()

        nan_count = df.select(pl.col("rwa_final").is_nan().sum()).item()
        inf_count = df.select(pl.col("rwa_final").is_infinite().sum()).item()
        assert nan_count == 0, f"Found {nan_count} NaN values at 100K scale"
        assert inf_count == 0, f"Found {inf_count} inf values at 100K scale"

    def test_memory_bounded_100k(
        self,
        stress_dataset_100k: dict[str, pl.LazyFrame],
    ):
        """100K: pipeline peak memory stays under 4 GB."""
        config = CalculationConfig.crr(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.STANDARDISED,
        )

        tracemalloc.start()
        result = run_pipeline(stress_dataset_100k, config)
        # Force materialisation to capture peak memory
        _ = result.results.collect()
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak_bytes / (1024 * 1024)
        assert peak_mb < 4000, f"Peak memory {peak_mb:.0f} MB exceeds 4 GB limit"

    def test_b31_output_floor_100k(
        self,
        stress_dataset_100k: dict[str, pl.LazyFrame],
    ):
        """100K: Basel 3.1 output floor produces valid summary."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.IRB,
        )
        result = run_pipeline(stress_dataset_100k, config)

        ofs = result.output_floor_summary
        assert ofs is not None, "Output floor summary should exist for B31 IRB"
        assert ofs.u_trea > 0
        assert ofs.s_trea > 0
        assert ofs.total_rwa_post_floor >= ofs.u_trea - 1.0


# =============================================================================
# Unique Exposure References
# =============================================================================


class TestExposureReferenceUniqueness:
    """Verify no duplicate exposure references in output.

    Why: Duplicate references cause double-counting in COREP aggregations
    and misleading exposure-level audit trails.
    """

    def test_unique_references_crr(self, crr_sa_result_10k: AggregatedResultBundle):
        """All exposure_reference values should be unique in output."""
        df = crr_sa_result_10k.results.collect()
        total = len(df)
        unique = df.select("exposure_reference").n_unique()
        assert unique == total, (
            f"Duplicate exposure references: {total - unique} duplicates in {total} rows"
        )

    def test_unique_references_b31(self, b31_irb_result_10k: AggregatedResultBundle):
        """Basel 3.1: all exposure_reference values unique."""
        df = b31_irb_result_10k.results.collect()
        total = len(df)
        unique = df.select("exposure_reference").n_unique()
        assert unique == total
