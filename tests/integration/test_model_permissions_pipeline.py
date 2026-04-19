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
from rwa_calc.contracts.errors import ERROR_MODEL_PERMISSION_UNMATCHED
from rwa_calc.data.schemas import RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.pipeline import PipelineOrchestrator

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


def _make_external_rating(
    counterparty_reference: str = "CP001",
    cqs: int = 2,
    agency: str = "SP",
    **overrides: Any,
) -> dict[str, Any]:
    """Build an external (ECAI) rating row for SA risk-weight lookup."""
    defaults: dict[str, Any] = {
        "rating_reference": f"RAT_EXT_{counterparty_reference}_{agency}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": agency,
        "rating_value": "A",
        "cqs": cqs,
        "pd": None,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
        "model_id": None,
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

        # SA is the correct result for STANDARDISED config — no spurious CLS006.
        resolved = hierarchy_resolver.resolve(bundle, crr_config)
        classified = classifier.classify(resolved, crr_config)
        assert not any(
            e.code == ERROR_MODEL_PERMISSION_UNMATCHED for e in classified.classification_errors
        )

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


# =============================================================================
# Diagnostic warnings: silent SA fallback made visible (4 tests)
# =============================================================================


class TestModelPermissionsDiagnostics:
    """Bug #2 coverage: silent SA fallback now emits CLS006 warnings.

    When ``model_permissions`` is provided but an IRB-eligible exposure
    (internal_pd non-null) fails to match a permission row, the classifier
    must surface a targeted ``classification_warning`` explaining the cause
    so the user can remediate — instead of silently routing to SA.
    """

    def test_null_model_id_emits_diagnostic(self, hierarchy_resolver, classifier, crr_firb_config):
        """Internal rating with model_id=None → SA + CLS006 'no model_id' warning."""
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
                        model_id="MODEL_X",
                        exposure_class="corporate",
                        approach="advanced_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id=None,
                )
            ],
        )

        resolved = hierarchy_resolver.resolve(bundle, crr_firb_config)
        classified = classifier.classify(resolved, crr_firb_config)

        df = classified.all_exposures.collect()
        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.SA.value

        cls006_warnings = [
            e
            for e in classified.classification_errors
            if e.code == ERROR_MODEL_PERMISSION_UNMATCHED
        ]
        assert len(cls006_warnings) == 1
        assert "no model_id" in cls006_warnings[0].message

    def test_unmatched_model_id_emits_diagnostic(
        self, hierarchy_resolver, classifier, crr_firb_config
    ):
        """Rating model_id not in permissions table → SA + CLS006 'does not appear'."""
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
                        model_id="MODEL_A",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_B",
                )
            ],
        )

        resolved = hierarchy_resolver.resolve(bundle, crr_firb_config)
        classified = classifier.classify(resolved, crr_firb_config)

        df = classified.all_exposures.collect()
        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["approach"][0] == ApproachType.SA.value

        cls006_warnings = [
            e
            for e in classified.classification_errors
            if e.code == ERROR_MODEL_PERMISSION_UNMATCHED
        ]
        assert len(cls006_warnings) == 1
        assert "does not appear" in cls006_warnings[0].message

    def test_filter_rejected_emits_diagnostic(
        self, hierarchy_resolver, classifier, crr_firb_config
    ):
        """model_id matches but country filter rejects → SA + CLS006 'filtered out'."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                        country_code="DE",
                    )
                ],
                loans=[make_loan()],
                facilities=[make_facility()],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_A",
                        exposure_class="corporate",
                        approach="foundation_irb",
                        country_codes="GB",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_A",
                )
            ],
        )

        resolved = hierarchy_resolver.resolve(bundle, crr_firb_config)
        classified = classifier.classify(resolved, crr_firb_config)

        df = classified.all_exposures.collect()
        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row["approach"][0] == ApproachType.SA.value

        cls006_warnings = [
            e
            for e in classified.classification_errors
            if e.code == ERROR_MODEL_PERMISSION_UNMATCHED
        ]
        assert len(cls006_warnings) == 1
        assert "filtered out" in cls006_warnings[0].message

    def test_no_diagnostic_when_successfully_routed(
        self, hierarchy_resolver, classifier, crr_firb_config
    ):
        """Happy path: exposure routes to IRB → no CLS006 warnings emitted."""
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

        resolved = hierarchy_resolver.resolve(bundle, crr_firb_config)
        classified = classifier.classify(resolved, crr_firb_config)

        cls006_warnings = [
            e
            for e in classified.classification_errors
            if e.code == ERROR_MODEL_PERMISSION_UNMATCHED
        ]
        assert len(cls006_warnings) == 0


# =============================================================================
# Pipeline-level: IRB without model_permissions preserves routing (1 test)
# =============================================================================


class TestPipelineIRBWithoutModelPermissions:
    """IRB mode without a model_permissions file falls back to SA.

    When ``permission_mode=IRB`` but no ``model_permissions`` table is
    provided, no exposure can be granted IRB — the classifier forces all
    permission expressions to False. A pipeline-level error is emitted so
    the user can see that per-model gating is off and all exposures route
    to SA.
    """

    def test_irb_mode_without_permissions_file_falls_back_to_sa(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        equity_calculator,
        crr_firb_config,
    ):
        """Full pipeline: IRB mode + no model_permissions → exposure routes to SA."""
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
                # No model_permissions — triggers SA fallback.
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id=None,
                )
            ],
        )

        pipeline = PipelineOrchestrator(
            hierarchy_resolver=hierarchy_resolver,
            classifier=classifier,
            crm_processor=crm_processor,
            sa_calculator=sa_calculator,
            irb_calculator=irb_calculator,
            slotting_calculator=slotting_calculator,
            equity_calculator=equity_calculator,
        )
        result = pipeline.run_with_data(bundle, crr_firb_config)

        # Without model_permissions, IRB mode falls back to SA.
        all_results = result.results.collect()
        loan_row = all_results.filter(pl.col("exposure_reference") == "LN001")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.SA.value

        # Pipeline emits an error explaining that model_permissions is missing.
        assert any("model_permissions" in str(e) for e in result.errors)


# =============================================================================
# IRB-denied exposures must still use counterparty's external ECAI rating on SA
# =============================================================================


class TestIRBDeniedUsesExternalRatingOnSA:
    """When model_permissions deny IRB for an exposure whose counterparty also
    carries an external ECAI rating, the classifier correctly routes the
    exposure to Standardised Approach — and the SA calculator MUST use the
    external CQS for its risk-weight lookup. Defaulting to "unrated" here
    materially over-states RWA (CRR Art. 112–134; PRA PS1/26 Art. 120–122).

    Covered: (a) filter_rejected cause (exposure_class mismatch on model perm),
    (b) unmatched_model_id cause (stale model reference).
    """

    def test_filter_rejected_irb_uses_external_cqs_for_sa_rw(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        equity_calculator,
        crr_firb_config,
    ):
        """IRB denied by permission scope → SA uses counterparty's CQS 2 = 50% RW."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                        country_code="GB",
                    )
                ],
                loans=[make_loan(lgd=0.30)],
                facilities=[make_facility(lgd=0.30)],
                # Permission row matches model_id but NOT exposure_class →
                # filter_rejected. Internal rating is unusable; the counterparty's
                # external ECAI rating is the only usable signal for SA.
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_CORP",
                        exposure_class="residential_mortgage",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_CORP",
                ),
                _make_external_rating(
                    counterparty_reference="CP001",
                    cqs=2,
                    agency="SP",
                ),
            ],
        )

        pipeline = PipelineOrchestrator(
            hierarchy_resolver=hierarchy_resolver,
            classifier=classifier,
            crm_processor=crm_processor,
            sa_calculator=sa_calculator,
            irb_calculator=irb_calculator,
            slotting_calculator=slotting_calculator,
            equity_calculator=equity_calculator,
        )
        result = pipeline.run_with_data(bundle, crr_firb_config)

        all_results = result.results.collect()
        loan_row = all_results.filter(pl.col("exposure_reference") == "LN001")
        assert loan_row.height >= 1

        # IRB is correctly denied → SA.
        assert loan_row["approach"][0] == ApproachType.SA.value
        # The external ECAI rating must reach the SA calculator.
        assert loan_row["cqs"][0] == 2
        # And must drive the risk-weight lookup (CRR Art. 122 corporate CQS2 = 50%),
        # NOT the 100% unrated fallback.
        assert loan_row["risk_weight"][0] == pytest.approx(0.50)

    def test_basel31_sovereign_forced_sa_uses_external_cqs_for_sa_rw(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        equity_calculator,
        basel31_full_irb_config,
    ):
        """Basel 3.1 Art. 147A(1)(a) forces sovereign SA despite IRB permission.

        The counterparty also has an external ECAI rating. SA risk weight must
        come from the external CQS, not the unrated fallback.
        """
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP_SOV",
                        entity_type="sovereign",
                        country_code="US",  # non-domestic → not forced to 0%
                        annual_revenue=None,
                        is_financial_sector_entity=None,
                    )
                ],
                loans=[make_loan(counterparty_reference="CP_SOV", lgd=0.35)],
                facilities=[
                    make_facility(
                        counterparty_reference="CP_SOV",
                        risk_type="sovereign",
                        lgd=0.35,
                    )
                ],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_SOV",
                        exposure_class="central_govt_central_bank",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP_SOV",
                    pd=0.001,
                    model_id="MODEL_SOV",
                ),
                _make_external_rating(
                    counterparty_reference="CP_SOV",
                    cqs=2,  # A+ to A- sovereign under B31 Art. 114 = 20%
                    agency="SP",
                ),
            ],
        )

        pipeline = PipelineOrchestrator(
            hierarchy_resolver=hierarchy_resolver,
            classifier=classifier,
            crm_processor=crm_processor,
            sa_calculator=sa_calculator,
            irb_calculator=irb_calculator,
            slotting_calculator=slotting_calculator,
            equity_calculator=equity_calculator,
        )
        result = pipeline.run_with_data(bundle, basel31_full_irb_config)

        all_results = result.results.collect()
        loan_row = all_results.filter(pl.col("exposure_reference") == "LN001")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.SA.value
        assert loan_row["cqs"][0] == 2
        # Sovereign CQS 2 under B31 Art. 114 / Table 1 = 20%.
        assert loan_row["risk_weight"][0] == pytest.approx(0.20)

    def test_unmatched_model_id_uses_external_cqs_for_sa_rw(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        equity_calculator,
        crr_firb_config,
    ):
        """Stale internal model_id → SA + external CQS 1 corporate = 20%."""
        bundle = _bundle_with_ratings(
            make_raw_data_bundle(
                counterparties=[
                    make_counterparty(
                        counterparty_reference="CP001",
                        entity_type="corporate",
                        country_code="GB",
                    )
                ],
                loans=[make_loan(lgd=0.30)],
                facilities=[make_facility(lgd=0.30)],
                model_permissions=[
                    make_model_permission(
                        model_id="MODEL_LIVE",
                        exposure_class="corporate",
                        approach="foundation_irb",
                    ),
                ],
            ),
            ratings=[
                _make_internal_rating(
                    counterparty_reference="CP001",
                    pd=0.02,
                    model_id="MODEL_STALE",  # not in model_permissions → SA
                ),
                _make_external_rating(
                    counterparty_reference="CP001",
                    cqs=1,
                    agency="SP",
                ),
            ],
        )

        pipeline = PipelineOrchestrator(
            hierarchy_resolver=hierarchy_resolver,
            classifier=classifier,
            crm_processor=crm_processor,
            sa_calculator=sa_calculator,
            irb_calculator=irb_calculator,
            slotting_calculator=slotting_calculator,
            equity_calculator=equity_calculator,
        )
        result = pipeline.run_with_data(bundle, crr_firb_config)

        all_results = result.results.collect()
        loan_row = all_results.filter(pl.col("exposure_reference") == "LN001")
        assert loan_row.height >= 1
        assert loan_row["approach"][0] == ApproachType.SA.value
        assert loan_row["cqs"][0] == 1
        assert loan_row["risk_weight"][0] == pytest.approx(0.20)
