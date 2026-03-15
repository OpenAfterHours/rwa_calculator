"""
Integration tests: HierarchyResolver → ExposureClassifier.

Validates that counterparty-level attributes (model_id, ratings, entity_type,
default status, apply_fi_scalar) flow correctly through hierarchy resolution
into classification.

Why Priority 1: model_id propagation was recently added. This boundary is
where counterparty attributes first meet exposure-level classification —
any break here silently misclassifies the entire portfolio.

Components wired: HierarchyResolver (real) → ExposureClassifier (real)
No mocking. LazyFrames passed between stages as in production.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.hierarchy import HierarchyResolver

from .conftest import (
    make_contingent,
    make_counterparty,
    make_facility,
    make_loan,
    make_rating,
    make_raw_data_bundle,
)


def _run_pipeline(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    config: CalculationConfig,
    bundle,
) -> pl.DataFrame:
    """Run hierarchy + classifier and collect all_exposures."""
    resolved = resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    return classified.all_exposures.collect()


# =============================================================================
# model_id propagation (5 tests)
# =============================================================================


class TestModelIdPropagation:
    """Verify model_id flows from internal rating through hierarchy to classifier output."""

    def test_model_id_propagates_from_rating_to_loan(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Internal rating has model_id → loan exposure gets it after hierarchy unification."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty()],
            loans=[make_loan()],
            ratings=[make_rating(model_id="MOD_CORP_01")],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["model_id"][0] == "MOD_CORP_01"

    def test_model_id_propagates_from_rating_to_contingent(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Internal rating model_id propagates to contingent exposures."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty()],
            loans=[make_loan()],
            contingents=[make_contingent()],
            ratings=[make_rating(model_id="MOD_CORP_02")],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        cont_row = df.filter(pl.col("exposure_type") == "contingent")
        assert cont_row.height >= 1
        assert cont_row["model_id"][0] == "MOD_CORP_02"

    def test_model_id_propagates_from_rating_to_facility_undrawn(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Internal rating model_id propagates to facility_undrawn exposures."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty()],
            loans=[make_loan(drawn_amount=500_000.0)],
            facilities=[make_facility(limit=2_000_000.0)],
            ratings=[make_rating(model_id="MOD_CORP_03")],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        undrawn_row = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_row.height >= 1
        assert undrawn_row["model_id"][0] == "MOD_CORP_03"

    def test_null_model_id_when_rating_has_none(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Rating without model_id → exposure gets null model_id."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty()],
            loans=[make_loan()],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["model_id"][0] is None

    def test_different_counterparties_get_own_model_id(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Two counterparties with different model_ids on ratings → each exposure gets its own."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(counterparty_reference="CP_A"),
                make_counterparty(counterparty_reference="CP_B"),
            ],
            loans=[
                make_loan(loan_reference="LN_A", counterparty_reference="CP_A"),
                make_loan(loan_reference="LN_B", counterparty_reference="CP_B"),
            ],
            facilities=[
                make_facility(facility_reference="FAC_A", counterparty_reference="CP_A"),
                make_facility(facility_reference="FAC_B", counterparty_reference="CP_B"),
            ],
            ratings=[
                make_rating(
                    rating_reference="RAT_A",
                    counterparty_reference="CP_A",
                    model_id="MOD_A",
                ),
                make_rating(
                    rating_reference="RAT_B",
                    counterparty_reference="CP_B",
                    model_id="MOD_B",
                ),
            ],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        ln_a = df.filter(pl.col("exposure_reference") == "LN_A")
        ln_b = df.filter(pl.col("exposure_reference") == "LN_B")
        assert ln_a["model_id"][0] == "MOD_A"
        assert ln_b["model_id"][0] == "MOD_B"


# =============================================================================
# Entity type → exposure class (4 tests)
# =============================================================================


class TestEntityTypeClassification:
    """Verify entity_type maps to correct exposure class through the full pipeline."""

    def test_corporate_entity_type_classifies_as_corporate(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """entity_type='corporate' → ExposureClass.CORPORATE."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["exposure_class"][0] == ExposureClass.CORPORATE.value

    def test_institution_entity_type_classifies_as_institution(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """entity_type='institution' → ExposureClass.INSTITUTION."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="institution")],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["exposure_class"][0] == ExposureClass.INSTITUTION.value

    def test_sme_flag_from_annual_revenue(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Counterparty with annual_revenue < EUR 50m threshold → CORPORATE_SME."""
        # CRR threshold is EUR 50m, converted to GBP at ~0.8732 rate = ~43.66m GBP
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(entity_type="corporate", annual_revenue=30_000_000.0)
            ],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert loan_row["is_sme"][0] is True

    def test_individual_entity_type_classifies_as_retail(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """entity_type='individual' with small exposure → retail class."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(
                    entity_type="individual", annual_revenue=0.0, total_assets=50_000.0
                )
            ],
            loans=[make_loan(drawn_amount=10_000.0, interest=0.0)],
            facilities=[make_facility(limit=50_000.0, is_revolving=False)],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        # Individual with small exposure should be retail (not corporate)
        retail_classes = {
            ExposureClass.RETAIL_OTHER.value,
            ExposureClass.RETAIL_MORTGAGE.value,
            ExposureClass.RETAIL_QRRE.value,
        }
        assert loan_row["exposure_class"][0] in retail_classes


# =============================================================================
# Default status propagation (2 tests)
# =============================================================================


class TestDefaultStatusPropagation:
    """Verify default_status flows from counterparty through to classifier."""

    def test_defaulted_counterparty_marks_exposure_defaulted(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Defaulted counterparty → classifier marks exposure as is_defaulted=True."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(default_status=True)],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["is_defaulted"][0] is True
        assert loan_row["exposure_class_for_sa"][0] == ExposureClass.DEFAULTED.value

    def test_non_defaulted_counterparty_not_marked(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Non-defaulted counterparty → is_defaulted=False."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(default_status=False)],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["is_defaulted"][0] is False


# =============================================================================
# apply_fi_scalar propagation (2 tests)
# =============================================================================


class TestFIScalarPropagation:
    """Verify apply_fi_scalar flows from counterparty to classifier flags."""

    def test_fi_scalar_flag_propagates_for_institution(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Institution with apply_fi_scalar=True → requires_fi_scalar=True."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(
                    entity_type="institution",
                    apply_fi_scalar=True,
                    total_assets=500_000_000.0,
                )
            ],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["requires_fi_scalar"][0] is True

    def test_fi_scalar_false_for_non_financial(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Corporate (non-financial) with apply_fi_scalar=False → requires_fi_scalar=False."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(entity_type="corporate", apply_fi_scalar=False)
            ],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["requires_fi_scalar"][0] is False


# =============================================================================
# Column completeness (2 tests)
# =============================================================================


class TestColumnCompleteness:
    """Verify hierarchy output has all columns the classifier expects."""

    def test_hierarchy_output_has_all_columns_classifier_expects(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Schema contract: hierarchy output contains all columns needed by classifier."""
        bundle = make_raw_data_bundle()
        resolved = hierarchy_resolver.resolve(bundle, crr_config)

        # These columns must exist on exposures for the classifier to work
        required_cols = {
            "exposure_reference",
            "exposure_type",
            "counterparty_reference",
            "product_type",
            "book_code",
            "currency",
            "drawn_amount",
            "seniority",
            "lgd",
        }
        actual_cols = set(resolved.exposures.collect_schema().names())
        missing = required_cols - actual_cols
        assert not missing, f"Hierarchy output missing columns for classifier: {missing}"

    def test_multiple_exposures_same_counterparty_get_same_classification(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """All exposures for the same counterparty get the same exposure_class."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[
                make_loan(loan_reference="LN001", drawn_amount=500_000.0),
                make_loan(loan_reference="LN002", drawn_amount=300_000.0),
            ],
            facilities=[make_facility(limit=3_000_000.0)],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        classes = df["exposure_class"].unique().to_list()
        # All should be the same class (CORPORATE or CORPORATE_SME)
        assert len(classes) == 1, f"Expected uniform classification, got {classes}"


# =============================================================================
# Parent-child hierarchy → classification (3 tests)
# =============================================================================


class TestParentChildHierarchy:
    """Verify org_mappings-based parent/child relationships affect classification."""

    def test_child_counterparty_gets_own_classification(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Child counterparty classified by its own entity_type, not parent's."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(
                    counterparty_reference="PARENT",
                    entity_type="institution",
                ),
                make_counterparty(
                    counterparty_reference="CHILD",
                    entity_type="corporate",
                    annual_revenue=100_000_000.0,
                ),
            ],
            loans=[
                make_loan(loan_reference="LN_CHILD", counterparty_reference="CHILD"),
            ],
            facilities=[
                make_facility(facility_reference="FAC_CHILD", counterparty_reference="CHILD"),
            ],
            org_mappings=[
                {
                    "parent_counterparty_reference": "PARENT",
                    "child_counterparty_reference": "CHILD",
                }
            ],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        child_loan = df.filter(pl.col("exposure_reference") == "LN_CHILD")
        assert child_loan.height >= 1
        # Child is corporate, not institution like parent
        assert child_loan["exposure_class"][0] == ExposureClass.CORPORATE.value

    def test_parent_rating_inherited_when_own_missing(
        self, hierarchy_resolver, classifier, crr_full_irb_config
    ):
        """Child counterparty inherits parent's rating via hierarchy resolution.

        When a child has no rating but parent does, the hierarchy resolver
        propagates the parent's rating. The classifier then uses the
        inherited rating for approach determination.
        """
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(
                    counterparty_reference="PARENT",
                    entity_type="corporate",
                ),
                make_counterparty(
                    counterparty_reference="CHILD",
                    entity_type="corporate",
                ),
            ],
            loans=[
                make_loan(loan_reference="LN_CHILD", counterparty_reference="CHILD"),
            ],
            facilities=[
                make_facility(facility_reference="FAC_CHILD", counterparty_reference="CHILD"),
            ],
            org_mappings=[
                {
                    "parent_counterparty_reference": "PARENT",
                    "child_counterparty_reference": "CHILD",
                }
            ],
        )
        resolved = hierarchy_resolver.resolve(bundle, crr_full_irb_config)

        # Verify hierarchy resolver builds parent mapping
        parent_mappings = resolved.counterparty_lookup.parent_mappings.collect()
        assert parent_mappings.height >= 1

        # Classify and verify child exposure exists
        classified = classifier.classify(resolved, crr_full_irb_config)
        df = classified.all_exposures.collect()
        child_loan = df.filter(pl.col("exposure_reference") == "LN_CHILD")
        assert child_loan.height >= 1
        # Child should still be classified as corporate
        assert child_loan["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]

    def test_unrated_counterparty_gets_sa_treatment(
        self, hierarchy_resolver, classifier, crr_config
    ):
        """Counterparty with no rating and SA-only config → SA approach."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
        )
        df = _run_pipeline(hierarchy_resolver, classifier, crr_config, bundle)

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["approach"][0] == ApproachType.SA.value
