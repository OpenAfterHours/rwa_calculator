"""
Integration tests: Model Permissions Pipeline.

Cross-cutting feature spanning HierarchyResolver → Classifier → CRMProcessor.
Validates end-to-end model permission resolution: model_id on internal rating
flows through rating inheritance pipeline into classifier where model_permissions
table drives per-row approach assignment, then CRM applies correct treatment.

Why Priority 4: Model permissions override org-wide IRB config at the
exposure level. A break here silently misroutes individual exposures to
the wrong approach, producing wrong LGD/RWA without any error signal.

Components wired: HierarchyResolver → ExposureClassifier → CRMProcessor (3 stages)
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
from rwa_calc.data.schemas import RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_model_permission,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================

_RATING_DATE = date(2024, 6, 1)


def _make_internal_rating(
    counterparty_reference: str = "CP001",
    pd: float = 0.02,
    model_id: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build an internal rating row for IRB eligibility."""
    defaults: dict[str, Any] = {
        "rating_reference": f"RAT_{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": None,
        "pd": pd,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
        "model_id": model_id,
    }
    defaults.update(overrides)
    return defaults


def _bundle_with_ratings(
    bundle: RawDataBundle,
    ratings: list[dict[str, Any]],
) -> RawDataBundle:
    """Add ratings data to an existing RawDataBundle."""
    return replace(bundle, ratings=_rows_to_lazyframe(ratings, RATINGS_SCHEMA))


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
    return crm_processor.get_crm_adjusted_bundle(classified, config)


def _run_to_classified(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    config: CalculationConfig,
    bundle: RawDataBundle,
) -> pl.DataFrame:
    """Run hierarchy + classifier and collect all_exposures."""
    resolved = resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    result: pl.DataFrame = classified.all_exposures.collect()
    return result


# =============================================================================
# Basic model resolution (4 tests)
# =============================================================================


class TestBasicModelResolution:
    """Verify model_permissions drive per-row approach assignment."""

    def test_model_airb_permission_routes_to_airb(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Internal rating with model_id and AIRB model permission → AIRB approach.

        Even with SA-only org config, model-level AIRB permission overrides.
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    )
                ],
                loans=[make_loan(lgd=0.30)],
                facilities=[make_facility(lgd=0.30)],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_AIRB",
                        exposure_class="corporate",
                        approach="advanced_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_AIRB",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.AIRB.value

    def test_model_firb_permission_routes_to_firb(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Internal rating with FIRB model permission → FIRB approach."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    )
                ],
                loans=[make_loan()],
                facilities=[make_facility()],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_FIRB",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_FIRB",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.FIRB.value

    def test_no_model_permission_falls_to_sa(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Rating without model_id → SA fallback (no org IRB permissions either)."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP001",
                    entity_type="corporate",
                )
            ],
            loans=[make_loan()],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.SA.value

    def test_model_permission_overrides_org_wide_irb(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """Org has FIRB, but model has AIRB → exposure gets AIRB.

        Model-level permissions take precedence over organisation-wide IRB config.
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    )
                ],
                loans=[make_loan(lgd=0.30)],
                facilities=[make_facility(lgd=0.30)],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_AIRB",
                        exposure_class="corporate",
                        approach="advanced_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_AIRB",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# Filtering (4 tests)
# =============================================================================


class TestModelPermissionFiltering:
    """Verify model permission filters correctly restrict approach assignment."""

    def test_model_permission_filters_by_exposure_class(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Permission for 'corporate' only → institution counterparty falls to SA."""
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
                    make_loan(
                        loan_reference="LN_CORP",
                        counterparty_reference="CP_CORP",
                    ),
                    make_loan(
                        loan_reference="LN_INST",
                        counterparty_reference="CP_INST",
                    ),
                ],
                facilities=[
                    make_facility(
                        facility_reference="FAC_CORP",
                        counterparty_reference="CP_CORP",
                    ),
                    make_facility(
                        facility_reference="FAC_INST",
                        counterparty_reference="CP_INST",
                    ),
                ],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_01",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP_CORP",
                    pd=0.02,
                    model_id="MODEL_01",
                ),
                _make_internal_rating(
                    counterparty_reference="CP_INST",
                    rating_reference="RAT_CP_INST",
                    pd=0.01,
                    model_id="MODEL_01",
                ),
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        corp_loan = df.filter(pl.col("exposure_reference") == "LN_CORP")
        inst_loan = df.filter(pl.col("exposure_reference") == "LN_INST")

        # Corporate gets FIRB via model permission
        assert corp_loan["approach"][0] == ApproachType.FIRB.value
        # Institution falls to SA — model permission is for corporate only
        assert inst_loan["approach"][0] == ApproachType.SA.value

    def test_model_permission_filters_by_geography(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """UK-only permission → non-UK counterparty falls to SA."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP_UK",
                        entity_type="corporate",
                        country_code="GB",
                    ),
                    make_counterparty(
                        counterparty_reference="CP_DE",
                        entity_type="corporate",
                        country_code="DE",
                    ),
                ],
                loans=[
                    make_loan(
                        loan_reference="LN_UK",
                        counterparty_reference="CP_UK",
                    ),
                    make_loan(
                        loan_reference="LN_DE",
                        counterparty_reference="CP_DE",
                    ),
                ],
                facilities=[
                    make_facility(
                        facility_reference="FAC_UK",
                        counterparty_reference="CP_UK",
                    ),
                    make_facility(
                        facility_reference="FAC_DE",
                        counterparty_reference="CP_DE",
                    ),
                ],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_GEO",
                        exposure_class="corporate",
                        approach="foundation_irb",
                        country_codes="GB",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP_UK",
                    pd=0.02,
                    model_id="MODEL_GEO",
                ),
                _make_internal_rating(
                    counterparty_reference="CP_DE",
                    rating_reference="RAT_CP_DE",
                    pd=0.02,
                    model_id="MODEL_GEO",
                ),
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        uk_loan = df.filter(pl.col("exposure_reference") == "LN_UK")
        de_loan = df.filter(pl.col("exposure_reference") == "LN_DE")

        # UK gets FIRB via model permission
        assert uk_loan["approach"][0] == ApproachType.FIRB.value
        # DE falls to SA — model permission restricts to GB only
        assert de_loan["approach"][0] == ApproachType.SA.value

    def test_model_permission_excludes_book_code(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Excluded book_code → SA treatment for exposures in that book."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    ),
                ],
                loans=[
                    make_loan(
                        loan_reference="LN_MAIN",
                        counterparty_reference="CP001",
                        book_code="MAIN",
                    ),
                    make_loan(
                        loan_reference="LN_EXCL",
                        counterparty_reference="CP001",
                        book_code="LEGACY",
                    ),
                ],
                facilities=[
                    make_facility(
                        facility_reference="FAC001",
                        counterparty_reference="CP001",
                    ),
                ],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_BOOK",
                        exposure_class="corporate",
                        approach="foundation_irb",
                        excluded_book_codes="LEGACY",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_BOOK",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        main_loan = df.filter(pl.col("exposure_reference") == "LN_MAIN")
        excl_loan = df.filter(pl.col("exposure_reference") == "LN_EXCL")

        # MAIN book gets FIRB
        assert main_loan["approach"][0] == ApproachType.FIRB.value
        # LEGACY book excluded → SA
        assert excl_loan["approach"][0] == ApproachType.SA.value

    def test_model_airb_requires_internal_pd(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """AIRB permission but no internal_pd → falls to SA.

        IRB approach requires internal PD from the ratings table. Without it,
        the classifier cannot assign IRB regardless of model permissions.
        """
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP001",
                    entity_type="corporate",
                )
            ],
            loans=[make_loan(lgd=0.30)],
            facilities=[make_facility(lgd=0.30)],
            model_permissions=[
                make_model_permission(
                    model_id="MODEL_AIRB",
                    exposure_class="corporate",
                    approach="advanced_irb",
                ),
            ],
        )
        # No ratings → no internal PD, no model_id

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        # Without internal PD, falls to SA
        assert loan_row["approach"][0] == ApproachType.SA.value


# =============================================================================
# End-to-end with CRM (4 tests)
# =============================================================================


class TestEndToEndWithCRM:
    """Verify model permissions → correct CRM treatment → correct LGD/output."""

    def test_model_firb_exposure_gets_supervisory_lgd(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Model permission → FIRB → CRM sets supervisory LGD (45% for senior)."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    )
                ],
                loans=[make_loan(seniority="senior", lgd=None)],
                facilities=[make_facility()],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_FIRB",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_FIRB",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.FIRB.value
        assert loan_row["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_model_airb_exposure_keeps_modelled_lgd(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Model permission → AIRB → CRM preserves modelled LGD from input."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    )
                ],
                loans=[make_loan(lgd=0.30)],
                facilities=[make_facility(lgd=0.30)],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_AIRB",
                        exposure_class="corporate",
                        approach="advanced_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_AIRB",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.AIRB.value
        # AIRB preserves modelled LGD
        assert loan_row["lgd_pre_crm"][0] == pytest.approx(0.30)
        assert loan_row["lgd_post_crm"][0] == pytest.approx(0.30)

    def test_mixed_model_permissions_in_portfolio(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """Two counterparties with different model permissions → each gets own approach.

        CP_AIRB has rating with model_id → AIRB permission + modelled LGD.
        CP_FIRB has rating with model_id → FIRB permission + no modelled LGD.
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP_AIRB",
                        entity_type="corporate",
                    ),
                    make_counterparty(
                        counterparty_reference="CP_FIRB",
                        entity_type="corporate",
                    ),
                ],
                loans=[
                    make_loan(
                        loan_reference="LN_AIRB",
                        counterparty_reference="CP_AIRB",
                        lgd=0.25,
                    ),
                    make_loan(
                        loan_reference="LN_FIRB",
                        counterparty_reference="CP_FIRB",
                    ),
                ],
                facilities=[
                    make_facility(
                        facility_reference="FAC_AIRB",
                        counterparty_reference="CP_AIRB",
                        lgd=0.25,
                    ),
                    make_facility(
                        facility_reference="FAC_FIRB",
                        counterparty_reference="CP_FIRB",
                    ),
                ],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_AIRB",
                        exposure_class="corporate",
                        approach="advanced_irb",
                    ),
                    make_model_permission(
                        model_id="MODEL_FIRB",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP_AIRB",
                    pd=0.02,
                    model_id="MODEL_AIRB",
                ),
                _make_internal_rating(
                    counterparty_reference="CP_FIRB",
                    rating_reference="RAT_CP_FIRB",
                    pd=0.02,
                    model_id="MODEL_FIRB",
                ),
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        airb_loan = df.filter(pl.col("exposure_reference") == "LN_AIRB")
        firb_loan = df.filter(pl.col("exposure_reference") == "LN_FIRB")

        # Model-permissioned AIRB
        assert airb_loan["approach"][0] == ApproachType.AIRB.value
        # Model-permissioned FIRB
        assert firb_loan["approach"][0] == ApproachType.FIRB.value

    def test_model_id_in_output_for_audit(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """model_id present in CRM output for traceability/audit."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                    )
                ],
                loans=[make_loan()],
                facilities=[make_facility()],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_AUDIT",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_AUDIT",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert "model_id" in df.columns
        assert loan_row["model_id"][0] == "MODEL_AUDIT"


# =============================================================================
# Optional columns absent (1 test)
# =============================================================================


class TestModelPermissionsMinimalSchema:
    """Verify model_permissions works without optional columns."""

    def test_model_permissions_minimal_schema_end_to_end(
        self, hierarchy_resolver, classifier, crm_processor, crr_config
    ):
        """model_permissions with only required columns → correct approach assignment.

        When country_codes and excluded_book_codes columns are absent from the
        input file, all geographies should be permitted and no books excluded.
        """
        # Build model_permissions LazyFrame with only the 3 required columns
        model_perms = pl.DataFrame(
            {
                "model_id": ["MODEL_MIN"],
                "exposure_class": ["corporate"],
                "approach": ["foundation_irb"],
            },
            schema={
                "model_id": pl.String,
                "exposure_class": pl.String,
                "approach": pl.String,
            },
        ).lazy()

        bundle = _bundle_with_ratings(
            replace(
                make_raw_data_bundle(
                    counterparties=[
                        make_counterparty(
                            counterparty_reference="CP001",
                            entity_type="corporate",
                            country_code="DE",
                        )
                    ],
                    loans=[make_loan(book_code="LEGACY")],
                    facilities=[make_facility()],
                ),
                model_permissions=model_perms,
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_MIN",
                )
            ],
        )

        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        df = crm_bundle.exposures.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.FIRB.value
