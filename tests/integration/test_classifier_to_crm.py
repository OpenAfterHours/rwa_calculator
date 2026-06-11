"""
Integration tests: ExposureClassifier → CRMProcessor.

Validates that classified exposures flow correctly into CRM processing:
- Approach-specific CRM treatment (SA CCF, FIRB supervisory LGD, AIRB modelled LGD)
- Provision column initialisation
- CCF application for on- and off-balance sheet items
- Approach split correctness (filtering the unified frame on `approach`)

Why Priority 2: The classifier→CRM boundary is where approach assignment
meets EAD/LGD adjustment. Misrouted exposures here silently get wrong
risk parameters, corrupting all downstream RWA calculations.

Components wired: HierarchyResolver (real) → ExposureClassifier (real) → CRMProcessor (real)
No mocking. LazyFrames passed between stages as in production.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import ColumnSpec, dtypes_of
from rwa_calc.data.schemas import RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.irb_test_helpers import (
    create_firb_only_model_permissions,
    create_full_irb_model_permissions,
    enrich_ratings_with_model_id,
)

from .conftest import (
    make_contingent,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================

_RATING_DATE = date(2024, 6, 1)


def _make_internal_rating(
    counterparty_reference: str = "CP001",
    pd: float = 0.01,
    **overrides: Any,
) -> dict[str, Any]:
    """Single internal rating row with defaults."""
    base: dict[str, Any] = {
        "rating_reference": f"RAT_{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": 4,
        "pd": pd,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
    }
    base.update(overrides)
    return base


def _rows_to_lazyframe(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.LazyFrame:
    """Convert row dicts to a LazyFrame, casting to the target schema.

    Accepts either a plain dtype dict or a ColumnSpec schema.
    """
    dtype_schema = (
        dtypes_of(schema) if any(isinstance(v, ColumnSpec) for v in schema.values()) else schema
    )
    if not rows:
        return pl.LazyFrame(schema=dtype_schema)
    df = pl.DataFrame(rows)
    cast_exprs = []
    for col_name, col_type in dtype_schema.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.lazy().select(cast_exprs)


def _bundle_with_ratings(
    bundle: RawDataBundle,
    ratings: list[dict[str, Any]],
    model_permissions: pl.LazyFrame | None = None,
) -> RawDataBundle:
    """Add ratings data to an existing RawDataBundle.

    When model_permissions is provided, ratings are enriched with model_id
    so the classifier can match them against the permissions table.
    """
    ratings_lf = _rows_to_lazyframe(ratings, RATINGS_SCHEMA)
    if model_permissions is not None:
        ratings_lf = enrich_ratings_with_model_id(ratings_lf)
    return replace(bundle, ratings=ratings_lf, model_permissions=model_permissions)


def _run_pipeline(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    crm_processor: CRMProcessor,
    config: CalculationConfig,
    bundle: RawDataBundle,
) -> CRMAdjustedBundle:
    """Run hierarchy + classifier + CRM and return the CRMAdjustedBundle."""
    resolved = resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    return crm_processor.get_crm_unified_bundle(classified, config)


# =============================================================================
# Approach-specific CRM (5 tests)
# =============================================================================


class TestApproachSpecificCRM:
    """Verify each approach gets the correct CRM treatment."""

    def test_sa_classified_exposure_gets_sa_ccf(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """SA corporate with contingent (risk_type=full_risk) -> CCF=1.0 applied."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            facilities=[make_facility()],
            contingents=[make_contingent(risk_type="full_risk")],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        cont_row = df.filter(pl.col("exposure_type") == "contingent")
        assert cont_row.height >= 1
        assert cont_row["approach"][0] == ApproachType.SA.value
        assert cont_row["ccf"][0] == pytest.approx(1.0)

    def test_firb_classified_exposure_gets_supervisory_lgd(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """FIRB corporate (senior) -> lgd_post_crm ~ 0.45 (CRR supervisory LGD)."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[make_counterparty(entity_type="corporate")],
                loans=[make_loan(seniority="senior", lgd=None)],
                facilities=[make_facility()],
            ),
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.01)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.FIRB.value
        assert loan_row["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_airb_classified_exposure_keeps_modelled_lgd(
        self, hierarchy_resolver, classifier, crm_processor, crr_full_irb_config
    ):
        """AIRB corporate with lgd=0.30 on loan -> lgd preserved through CRM."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[make_counterparty(entity_type="corporate")],
                loans=[make_loan(lgd=0.30)],
                facilities=[make_facility(lgd=0.30)],
            ),
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.01)],
            model_permissions=create_full_irb_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_full_irb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.AIRB.value
        # AIRB keeps modelled LGD — lgd_pre_crm should reflect the 0.30 input
        assert loan_row["lgd_pre_crm"][0] == pytest.approx(0.30)
        # Without collateral, lgd_post_crm should equal lgd_pre_crm for AIRB
        assert loan_row["lgd_post_crm"][0] == pytest.approx(0.30)

    def test_slotting_classified_exposure_passes_through_crm(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """When no slotting exposures exist, the slotting filter is empty."""
        # Standard corporate does not trigger slotting classification
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            facilities=[make_facility()],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )

        # No specialised lending -> slotting filter should be empty
        slotting_df = crm_bundle.exposures.filter(
            pl.col("approach") == ApproachType.SLOTTING.value
        ).collect()
        assert slotting_df.height == 0

    def test_mixed_approaches_in_single_portfolio(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """Portfolio with SA + FIRB exposures -> each gets correct CRM treatment.

        Corporate with internal rating gets FIRB; institution without internal
        rating gets SA (IRB requires internal PD).
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP_CORP",
                        entity_type="corporate",
                        annual_revenue=100_000_000.0,
                    ),
                    make_counterparty(
                        counterparty_reference="CP_INST",
                        entity_type="institution",
                        total_assets=500_000_000.0,
                    ),
                ],
                loans=[
                    make_loan(loan_reference="LN_CORP", counterparty_reference="CP_CORP"),
                    make_loan(loan_reference="LN_INST", counterparty_reference="CP_INST"),
                ],
                facilities=[
                    make_facility(facility_reference="FAC_CORP", counterparty_reference="CP_CORP"),
                    make_facility(facility_reference="FAC_INST", counterparty_reference="CP_INST"),
                ],
            ),
            # Only corporate has internal rating -> gets FIRB
            # Institution has no internal rating -> falls to SA
            ratings=[_make_internal_rating(counterparty_reference="CP_CORP", pd=0.02)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        corp_loan = df.filter(pl.col("exposure_reference") == "LN_CORP")
        inst_loan = df.filter(pl.col("exposure_reference") == "LN_INST")

        # Corporate should get FIRB approach with supervisory LGD
        assert corp_loan["approach"][0] == ApproachType.FIRB.value
        assert corp_loan["lgd_post_crm"][0] == pytest.approx(0.45)

        # Institution should get SA approach (no internal rating)
        assert inst_loan["approach"][0] == ApproachType.SA.value


# =============================================================================
# Provision handling (3 tests)
# =============================================================================


class TestProvisionHandling:
    """Verify provision columns are initialised correctly through the CRM pipeline."""

    def test_sa_provisions_default_to_zero_without_provision_data(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """SA exposure without provision data -> provision_deducted=0."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            facilities=[make_facility()],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["provision_deducted"][0] == pytest.approx(0.0)

    def test_irb_provisions_not_deducted(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """IRB exposure -> provision_deducted=0 (IRB uses EL comparison, not EAD deduction)."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[make_counterparty(entity_type="corporate")],
                loans=[make_loan()],
                facilities=[make_facility()],
            ),
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.01)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.FIRB.value
        assert loan_row["provision_deducted"][0] == pytest.approx(0.0)

    def test_provision_columns_exist_after_crm(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """All approaches have provision_allocated and provision_deducted columns."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            facilities=[make_facility()],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        schema_names = crm_bundle.exposures.collect_schema().names()

        assert "provision_allocated" in schema_names
        assert "provision_deducted" in schema_names


# =============================================================================
# CCF conversion (3 tests)
# =============================================================================


class TestCCFConversion:
    """Verify CCF is correctly applied to off- and on-balance sheet items."""

    def test_contingent_gets_ccf_from_risk_type(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Contingent with risk_type=full_risk -> ccf=1.0."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            facilities=[make_facility()],
            contingents=[make_contingent(risk_type="full_risk")],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        cont_row = df.filter(pl.col("exposure_type") == "contingent")
        assert cont_row.height >= 1
        assert cont_row["ccf"][0] == pytest.approx(1.0)
        # ead_from_ccf should be nominal_amount * ccf
        assert cont_row["ead_from_ccf"][0] > 0

    def test_facility_undrawn_gets_ccf(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Facility undrawn amount -> CCF applied based on facility's risk_type."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=500_000.0)],
            facilities=[make_facility(limit=2_000_000.0, risk_type="medium_risk")],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        undrawn_row = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_row.height >= 1
        # medium_risk SA CCF = 50%
        assert undrawn_row["ccf"][0] == pytest.approx(0.5)
        assert undrawn_row["ead_from_ccf"][0] > 0

    def test_drawn_loan_has_no_ccf_adjustment(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Drawn loan -> ead_from_ccf=0, EAD = drawn + interest."""
        drawn = 1_000_000.0
        interest = 5_000.0
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=drawn, interest=interest)],
            facilities=[make_facility()],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        # On-balance sheet: no CCF
        assert loan_row["ead_from_ccf"][0] == pytest.approx(0.0)
        # EAD should be drawn + interest
        assert loan_row["ead_pre_crm"][0] == pytest.approx(drawn + interest)

    def test_crr_d_ccf7_firb_mr_contingent_falls_to_50_via_art_166_10(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """CRR-D.CCF7: FIRB MR contingent (issued OBS item) -> 50% via Art. 166(10)(b).

        End-to-end check that the per-source-table default flowing through
        ``HierarchyResolver`` correctly tags a contingent row as
        ``is_obs_commitment=False``, routing it to the Art. 166(10) fallback
        rather than the Art. 166(8)(d) 75% commitment bucket.
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[make_counterparty(entity_type="corporate")],
                loans=[make_loan(drawn_amount=0.0)],
                facilities=[make_facility(limit=0.0)],
                contingents=[
                    make_contingent(
                        contingent_reference="CT_CCF7_PERFORMANCE_BOND",
                        product_type="PERFORMANCE_BOND",
                        risk_type="medium_risk",
                        nominal_amount=1_000_000.0,
                    )
                ],
            ),
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.01)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        cont_row = df.filter(pl.col("exposure_reference") == "CT_CCF7_PERFORMANCE_BOND")
        assert cont_row.height == 1
        assert cont_row["approach"][0] == ApproachType.FIRB.value
        assert cont_row["ccf"][0] == pytest.approx(0.50)
        assert cont_row["ead_from_ccf"][0] == pytest.approx(500_000.0)

    def test_crr_d_ccf8_firb_mlr_contingent_falls_to_20_via_art_166_10(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """CRR-D.CCF8: FIRB MLR contingent (non-trade-LC) -> 20% via Art. 166(10)(c).

        Distinct from the Art. 166(8)(b) trade LC carve-out: this contingent
        has ``is_short_term_trade_lc=False`` and is not a credit line, so it
        falls under the Art. 166(10) fallback rather than the 166(8)(b) 20%
        carve-out (which produces the same numerical result but for a
        different regulatory reason).
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[make_counterparty(entity_type="corporate")],
                loans=[make_loan(drawn_amount=0.0)],
                facilities=[make_facility(limit=0.0)],
                contingents=[
                    make_contingent(
                        contingent_reference="CT_CCF8_SHIPPING_GUARANTEE",
                        product_type="SHIPPING_GUARANTEE",
                        risk_type="medium_low_risk",
                        nominal_amount=500_000.0,
                        is_short_term_trade_lc=False,
                    )
                ],
            ),
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.01)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        cont_row = df.filter(pl.col("exposure_reference") == "CT_CCF8_SHIPPING_GUARANTEE")
        assert cont_row.height == 1
        assert cont_row["approach"][0] == ApproachType.FIRB.value
        assert cont_row["ccf"][0] == pytest.approx(0.20)
        assert cont_row["ead_from_ccf"][0] == pytest.approx(100_000.0)

    def test_firb_mr_facility_undrawn_keeps_75_via_art_166_8d(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """FIRB MR facility undrawn (commitment) keeps 75% per Art. 166(8)(d).

        Sibling to CRR-D.CCF7 — confirms that the per-source-table default
        keeps facility undrawn rows in the Art. 166(8)(d) bucket so
        commitments aren't accidentally swept into the Art. 166(10) fallback.
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[make_counterparty(entity_type="corporate")],
                loans=[make_loan(drawn_amount=200_000.0)],
                facilities=[
                    make_facility(
                        facility_reference="FAC_CCF_COMMITMENT",
                        limit=1_000_000.0,
                        risk_type="medium_risk",
                    )
                ],
            ),
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.01)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        undrawn_row = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_row.height >= 1
        assert undrawn_row["approach"][0] == ApproachType.FIRB.value
        assert undrawn_row["ccf"][0] == pytest.approx(0.75)


# =============================================================================
# Approach split correctness (3 tests)
# =============================================================================


class TestApproachSplit:
    """Verify the CRM bundle splits exposures correctly by approach."""

    def test_sa_exposures_only_contain_sa_approach(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """The unified frame's SA subset only has approach=standardised."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            facilities=[make_facility()],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        sa_df = crm_bundle.exposures.filter(
            pl.col("approach") == ApproachType.SA.value
        ).collect()

        assert sa_df.height > 0
        approaches = sa_df["approach"].unique().to_list()
        assert approaches == [ApproachType.SA.value]

    def test_irb_exposures_contain_firb_and_airb(
        self, hierarchy_resolver, classifier, crm_processor, crr_full_irb_config
    ):
        """The unified frame's IRB subset has FIRB and/or AIRB approaches."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP_FIRB",
                        entity_type="corporate",
                        annual_revenue=100_000_000.0,
                    ),
                    make_counterparty(
                        counterparty_reference="CP_AIRB",
                        entity_type="corporate",
                        annual_revenue=100_000_000.0,
                    ),
                ],
                loans=[
                    # No LGD -> classifier assigns FIRB
                    make_loan(
                        loan_reference="LN_FIRB",
                        counterparty_reference="CP_FIRB",
                        lgd=None,
                    ),
                    # With LGD -> classifier assigns AIRB
                    make_loan(
                        loan_reference="LN_AIRB",
                        counterparty_reference="CP_AIRB",
                        lgd=0.25,
                    ),
                ],
                facilities=[
                    make_facility(
                        facility_reference="FAC_FIRB",
                        counterparty_reference="CP_FIRB",
                        lgd=None,
                    ),
                    make_facility(
                        facility_reference="FAC_AIRB",
                        counterparty_reference="CP_AIRB",
                        lgd=0.25,
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(counterparty_reference="CP_FIRB", pd=0.01),
                _make_internal_rating(
                    counterparty_reference="CP_AIRB",
                    rating_reference="RAT_CP_AIRB",
                    pd=0.02,
                ),
            ],
            model_permissions=create_full_irb_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_full_irb_config, bundle
        )
        irb_df = crm_bundle.exposures.filter(
            pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        ).collect()

        assert irb_df.height > 0
        irb_approaches = set(irb_df["approach"].unique().to_list())
        # Should only contain FIRB and/or AIRB, never SA or slotting
        assert irb_approaches <= {ApproachType.FIRB.value, ApproachType.AIRB.value}
        # At least one IRB approach must be present
        assert len(irb_approaches) >= 1

    def test_all_exposures_accounted_for_in_splits(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """sa + irb + slotting count = total exposures count."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP_CORP",
                        entity_type="corporate",
                    ),
                    make_counterparty(
                        counterparty_reference="CP_INST",
                        entity_type="institution",
                        total_assets=500_000_000.0,
                    ),
                ],
                loans=[
                    make_loan(loan_reference="LN_CORP", counterparty_reference="CP_CORP"),
                    make_loan(loan_reference="LN_INST", counterparty_reference="CP_INST"),
                ],
                facilities=[
                    make_facility(facility_reference="FAC_CORP", counterparty_reference="CP_CORP"),
                    make_facility(facility_reference="FAC_INST", counterparty_reference="CP_INST"),
                ],
            ),
            # Corporate gets internal rating -> FIRB; institution has none -> SA
            ratings=[_make_internal_rating(counterparty_reference="CP_CORP", pd=0.01)],
            model_permissions=create_firb_only_model_permissions(),
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )

        unified = crm_bundle.exposures.collect()
        total = unified.height
        sa_count = unified.filter(pl.col("approach") == ApproachType.SA.value).height
        irb_count = unified.filter(
            pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        ).height
        slotting_count = unified.filter(
            pl.col("approach") == ApproachType.SLOTTING.value
        ).height

        assert sa_count + irb_count + slotting_count == total
