"""
Unit tests for P1.145: deterministic dedup of conflicting model_permissions rows.

SA wins over IRB on the same (model_id, exposure_class) when both a
standardised and an advanced_irb row exist for the same model.  The result
must be byte-identical regardless of which physical ordering of the
model_permissions parquet is presented to the classifier.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (_resolve_model_permissions) -> CRMProcessor

Defect (pre-fix):
    classifier.py line 1268:
        pl.col("_airb_match").max().over("exposure_reference").alias("model_airb_permitted")
    When both an AIRB and an SA row exist, .max() returns True (because the AIRB
    row's _airb_match=True dominates), ignoring the SA row entirely.  The
    SA-precedence rule (CRR Art. 150(1) PPU carve-out) is never applied.

Post-fix assertion:
    For EXP-DUP-001 with model_id="UK_CORP_DUP_01":
    - model_airb_permitted = False  (SA-precedence blocks AIRB)
    - model_firb_permitted = False  (no FIRB row in fixture)
    - model_slotting_permitted = False
    - approach = ApproachType.SA.value ("standardised")
    Result is identical for both the AIRB-first and SA-first orderings.

References:
    - CRR Art. 143 (IRB permission scope)
    - CRR Art. 150(1) (PPU carve-out — SA wins over IRB on conflict)
    - src/rwa_calc/engine/classifier.py:1150-1314 (_resolve_model_permissions)
    - tests/fixtures/p1_145/p1_145.py (fixture builders)
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from tests.fixtures.p1_145.p1_145 import (
    EXPOSURE_REF,
    INTERNAL_PD,
    MODEL_ID,
    build_model_permissions_airb_first,
    build_model_permissions_sa_first,
    create_p1145_counterparty,
    create_p1145_loan,
)

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Bundle construction helpers
# ---------------------------------------------------------------------------


def _make_resolved_bundle(
    model_permissions: pl.LazyFrame,
) -> ResolvedHierarchyBundle:
    """
    Build a minimal ResolvedHierarchyBundle for P1.145 dedup tests.

    Constructs the exposures LazyFrame from the p1_145 fixture data
    (counterparty + loan), enriches the counterparty with hierarchy
    columns the classifier expects, and wires model_permissions in.

    This pattern mirrors test_model_permissions_null_book_code.py.
    """
    # Counterparty — add hierarchy columns the classifier join expects
    counterparties = create_p1145_counterparty().lazy()
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
    )

    # Exposures from loan fixture — add the extra columns the classifier pipeline
    # needs but that the raw loan parquet does not carry.
    # IMPORTANT: model_id must be added here because in the full pipeline it is
    # propagated by the HierarchyResolver's rating-inheritance join; in this
    # unit test we inject it directly (mirrors test_model_permissions_null_book_code.py).
    loan_df = create_p1145_loan()
    exposures = (
        loan_df.lazy()
        .rename({"loan_reference": "exposure_reference"})
        .with_columns(
            [
                pl.lit("loan").alias("exposure_type"),
                pl.lit("TERM_LOAN").alias("product_type"),
                pl.lit(0.0).alias("undrawn_amount"),
                pl.lit(0.0).alias("nominal_amount"),
                pl.lit(False).alias("exposure_has_parent"),
                pl.lit(None).cast(pl.String).alias("root_facility_reference"),
                pl.lit(1).cast(pl.Int32).alias("facility_hierarchy_depth"),
                pl.lit(False).alias("counterparty_has_parent"),
                pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
                pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
                pl.lit(1).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
                pl.lit(None).cast(pl.String).alias("lending_group_reference"),
                pl.lit(0.0).alias("lending_group_total_exposure"),
                pl.lit(INTERNAL_PD).alias("internal_pd"),
                # model_id is normally propagated by HierarchyResolver rating inheritance;
                # inject directly here to reach _resolve_model_permissions in the classifier.
                pl.lit(MODEL_ID).alias("model_id"),
            ]
        )
    )

    # Enrich exposures with residential_collateral_value and derived fields
    exposures = exposures.with_columns(
        pl.lit(0.0).alias("residential_collateral_value"),
    ).with_columns(
        (
            pl.col("drawn_amount")
            + pl.col("nominal_amount")
            - pl.col("residential_collateral_value")
        ).alias("exposure_for_retail_threshold"),
        pl.col("lending_group_total_exposure").alias("lending_group_adjusted_exposure"),
    )

    return ResolvedHierarchyBundle(
        exposures=exposures,
        counterparty_lookup=CounterpartyLookup(
            counterparties=enriched_cp,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        ),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        specialised_lending=None,
        model_permissions=model_permissions,
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_drawn": pl.Float64,
                "total_nominal": pl.Float64,
                "total_exposure": pl.Float64,
                "adjusted_exposure": pl.Float64,
                "total_residential_coverage": pl.Float64,
                "exposure_count": pl.UInt32,
            }
        ),
    )


def _classify_and_get_row(
    ordering: str,
    classifier: ExposureClassifier,
    config: CalculationConfig,
) -> pl.DataFrame:
    """
    Run the classifier for the given model_permissions ordering and return
    the single row for EXPOSURE_REF from all_exposures.

    ordering must be "airb_first" or "sa_first".
    """
    if ordering == "airb_first":
        mp = build_model_permissions_airb_first()
    else:
        mp = build_model_permissions_sa_first()

    bundle = _make_resolved_bundle(mp)
    result: ClassifiedExposuresBundle = classifier.classify(bundle, config)
    df = result.all_exposures.collect()
    row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
    return row


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier() -> ExposureClassifier:
    """Return an ExposureClassifier instance."""
    return ExposureClassifier()


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR config with model-level IRB permission mode."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSAPrecedenceAirbFirstOrdering:
    """
    P1.145 — SA must block AIRB when the AIRB permission row appears before
    the SA row in the model_permissions table (AIRB-first ordering).

    Pre-fix: .max().over("exposure_reference") returns model_airb_permitted=True
    because the AIRB row's _airb_match=True is the maximum.  The SA row is
    completely ignored.

    Post-fix: the SA-precedence rule sets model_airb_permitted=False.
    """

    def test_sa_blocks_airb_under_airb_first_ordering(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        model_airb_permitted must be False when AIRB and SA rows coexist
        (AIRB-first physical ordering) — SA-precedence rule applies.

        This test fails pre-fix because .max().over() returns True from
        the AIRB row without considering the blocking SA row.
        """
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_airb_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
        assert len(row) == 1, f"Expected exactly one row for {EXPOSURE_REF!r}, got {len(row)}"

        actual_airb = row["model_airb_permitted"][0]
        assert actual_airb is False, (
            f"Expected model_airb_permitted=False for {EXPOSURE_REF!r} "
            f"(UK_CORP_DUP_01 has coexisting SA + AIRB rows; SA-precedence must block AIRB), "
            f"but got model_airb_permitted={actual_airb!r}. "
            f"AIRB-first ordering — pre-fix bug: .max().over() returns True from AIRB row."
        )

    def test_model_firb_permitted_false_under_airb_first_ordering(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """model_firb_permitted must be False (no FIRB row in fixture) — AIRB-first."""
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_airb_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
        assert len(row) == 1

        actual_firb = row["model_firb_permitted"][0]
        assert actual_firb is False, (
            f"Expected model_firb_permitted=False for {EXPOSURE_REF!r} "
            f"(no FIRB row for UK_CORP_DUP_01), but got {actual_firb!r}."
        )

    def test_model_slotting_permitted_false_under_airb_first_ordering(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """model_slotting_permitted must be False (no slotting row) — AIRB-first."""
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_airb_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
        assert len(row) == 1

        actual_slotting = row["model_slotting_permitted"][0]
        assert actual_slotting is False, (
            f"Expected model_slotting_permitted=False for {EXPOSURE_REF!r}, "
            f"but got {actual_slotting!r}."
        )

    def test_approach_is_standardised_under_airb_first_ordering(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """approach must be 'standardised' after SA-precedence blocks AIRB — AIRB-first."""
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_airb_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
        assert len(row) == 1

        actual_approach = row["approach"][0]
        assert actual_approach == ApproachType.SA.value, (
            f"Expected approach={ApproachType.SA.value!r} for {EXPOSURE_REF!r} "
            f"(all IRB permissions blocked by SA-precedence rule), "
            f"but got {actual_approach!r}. AIRB-first ordering."
        )


class TestSAPrecedenceSaFirstOrdering:
    """
    P1.145 — SA must block AIRB when the SA row appears before the AIRB row
    in the model_permissions table (SA-first ordering).

    The result should be identical to the AIRB-first ordering — that is the
    order-stability invariant.
    """

    def test_sa_blocks_airb_under_sa_first_ordering(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        model_airb_permitted must be False when AIRB and SA rows coexist
        (SA-first physical ordering) — SA-precedence rule applies.
        """
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_sa_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
        assert len(row) == 1, f"Expected exactly one row for {EXPOSURE_REF!r}, got {len(row)}"

        actual_airb = row["model_airb_permitted"][0]
        assert actual_airb is False, (
            f"Expected model_airb_permitted=False for {EXPOSURE_REF!r} "
            f"(UK_CORP_DUP_01 has coexisting SA + AIRB rows; SA-precedence must block AIRB), "
            f"but got model_airb_permitted={actual_airb!r}. SA-first ordering."
        )

    def test_approach_is_standardised_under_sa_first_ordering(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """approach must be 'standardised' after SA-precedence blocks AIRB — SA-first."""
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_sa_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EXPOSURE_REF)
        assert len(row) == 1

        actual_approach = row["approach"][0]
        assert actual_approach == ApproachType.SA.value, (
            f"Expected approach={ApproachType.SA.value!r} for {EXPOSURE_REF!r} "
            f"(all IRB permissions blocked by SA-precedence rule), "
            f"but got {actual_approach!r}. SA-first ordering."
        )


class TestOrderStabilityInvariant:
    """
    P1.145 — the core order-stability invariant: the post-classifier frame
    for EXP-DUP-001 must be byte-identical regardless of which physical
    ordering of model_permissions is presented to the classifier.

    This test pins the regression surface: if the engine ever reverts to
    order-dependent behaviour the two DataFrames will diverge and this
    assertion will catch it.
    """

    def test_classifier_output_is_byte_identical_across_orderings(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        Both orderings must produce identical values for all observable
        permission and approach columns.

        Compares a projection of the two collected frames using
        pl.testing.assert_frame_equal so the diff is clear on failure.
        """
        # Arrange
        bundle_airb_first = _make_resolved_bundle(build_model_permissions_airb_first())
        bundle_sa_first = _make_resolved_bundle(build_model_permissions_sa_first())

        # Act
        result_airb_first: ClassifiedExposuresBundle = classifier.classify(
            bundle_airb_first, crr_irb_config
        )
        result_sa_first: ClassifiedExposuresBundle = classifier.classify(
            bundle_sa_first, crr_irb_config
        )

        compare_cols = [
            "exposure_reference",
            "model_airb_permitted",
            "model_firb_permitted",
            "model_slotting_permitted",
            "approach",
        ]

        df_airb_first = (
            result_airb_first.all_exposures.collect()
            .filter(pl.col("exposure_reference") == EXPOSURE_REF)
            .select(compare_cols)
        )
        df_sa_first = (
            result_sa_first.all_exposures.collect()
            .filter(pl.col("exposure_reference") == EXPOSURE_REF)
            .select(compare_cols)
        )

        # Assert — identical frames mean the engine is order-stable
        assert_frame_equal(
            df_airb_first,
            df_sa_first,
            check_row_order=True,
        )


class TestDiagnosticFilterRejected:
    """
    P1.145 (optional) — the classifier emits a CLS006 'filter_rejected' warning
    for EXP-DUP-001 because the SA-precedence rule blocks all IRB approaches.

    Under the current engine (pre-fix), when AIRB-first ordering is presented,
    model_airb_permitted=True and no diagnostic is emitted (the happy path).
    Under SA-first ordering, model_airb_permitted may still be True (non-
    deterministic) or False depending on Polars row order.

    Post-fix: both orderings produce model_airb_permitted=False, so the
    diagnostic code path emits exactly one 'filter_rejected' CLS006 warning.
    """

    def test_diagnostic_filter_rejected_emitted_for_airb_first(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        A CLS006 'filter_rejected' warning must be emitted for the AIRB-first
        ordering because the SA row blocks all IRB approaches.

        Pre-fix: model_airb_permitted=True (AIRB wins), no diagnostic emitted.
        Post-fix: model_airb_permitted=False, CLS006 'filter_rejected' emitted.
        """
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_airb_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert — at least one CLS006 warning must exist
        cls006_errors = [e for e in result.classification_errors if e.code == "CLS006"]
        assert len(cls006_errors) >= 1, (
            f"Expected at least one CLS006 'filter_rejected' diagnostic for "
            f"{EXPOSURE_REF!r} (SA-precedence blocks AIRB), "
            f"but classification_errors = {result.classification_errors!r}. "
            f"Pre-fix bug: AIRB wins so no diagnostic is emitted."
        )
        # The warning message must mention 'filter_rejected' semantics
        filter_rejected_msgs = [
            e
            for e in cls006_errors
            if "scope" in e.message.lower() or "filter" in e.message.lower()
        ]
        assert len(filter_rejected_msgs) >= 1, (
            f"Expected a CLS006 with 'filter_rejected' cause, "
            f"but got: {[e.message for e in cls006_errors]!r}"
        )

    def test_diagnostic_filter_rejected_emitted_for_sa_first(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        A CLS006 'filter_rejected' warning must be emitted for the SA-first
        ordering because the SA row blocks all IRB approaches.
        """
        # Arrange
        bundle = _make_resolved_bundle(build_model_permissions_sa_first())

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        cls006_errors = [e for e in result.classification_errors if e.code == "CLS006"]
        assert len(cls006_errors) >= 1, (
            f"Expected at least one CLS006 'filter_rejected' diagnostic for "
            f"{EXPOSURE_REF!r} (SA-precedence blocks AIRB), "
            f"but classification_errors = {result.classification_errors!r}. "
            f"SA-first ordering."
        )
        filter_rejected_msgs = [
            e
            for e in cls006_errors
            if "scope" in e.message.lower() or "filter" in e.message.lower()
        ]
        assert len(filter_rejected_msgs) >= 1, (
            f"Expected a CLS006 with 'filter_rejected' cause, "
            f"but got: {[e.message for e in cls006_errors]!r}"
        )
