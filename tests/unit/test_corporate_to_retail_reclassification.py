"""Unit tests for corporate-to-retail reclassification in classifier.

Tests cover:
- Reclassification criteria under full_irb(): with AIRB available for corporates,
  reclassification is short-circuited (corporates get AIRB directly)
- Property collateral detection for mortgage classification
- Approach routing: exposures with internal_pd + lgd → AIRB, without lgd → FIRB
- FIRB LGD clearing applies only to FIRB (not AIRB) exposures
- Turnover threshold for SME definition per CRR Art. 501

Note: Under PermissionMode.IRB (which maps to full_irb()), AIRB is permitted for
both corporate and retail classes. The corporate-to-retail reclassification only
triggers when AIRB is NOT permitted for corporate but IS permitted for retail
(a hybrid configuration no longer available via PermissionMode).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier

_TEST_MODEL_ID = "TEST_MODEL"


def _full_model_permissions(model_id: str = _TEST_MODEL_ID) -> pl.LazyFrame:
    """Model permissions granting all IRB approaches for all exposure classes."""
    rows = []
    for ec in ExposureClass:
        for approach in ["advanced_irb", "foundation_irb", "slotting"]:
            rows.append({"model_id": model_id, "exposure_class": ec.value, "approach": approach})
    return pl.DataFrame(rows).lazy()


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> ExposureClassifier:
    """Return an ExposureClassifier instance."""
    return ExposureClassifier()


@pytest.fixture
def irb_config() -> CalculationConfig:
    """Return CRR config with full IRB permissions (AIRB + FIRB for all classes).

    Under PermissionMode.IRB, AIRB is permitted for both corporate and retail,
    so corporate-to-retail reclassification is short-circuited. Exposures with
    internal_pd + lgd get AIRB; those with internal_pd only get FIRB.
    """
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


def create_test_bundle(
    exposures_data: dict,
    counterparties_data: dict,
) -> ResolvedHierarchyBundle:
    """Create a test ResolvedHierarchyBundle from data dicts."""
    # Default internal_pd for IRB classification (tests can override with None)
    if "internal_pd" not in exposures_data:
        n = len(next(iter(exposures_data.values())))
        exposures_data = {**exposures_data, "internal_pd": [0.005] * n}
    # Default model_id and book_code for model permissions resolution
    if "model_id" not in exposures_data:
        n = len(next(iter(exposures_data.values())))
        exposures_data = {**exposures_data, "model_id": [_TEST_MODEL_ID] * n}
    if "book_code" not in exposures_data:
        n = len(next(iter(exposures_data.values())))
        exposures_data = {**exposures_data, "book_code": ["CORP"] * n}
    exposures = pl.DataFrame(exposures_data).lazy()
    counterparties = pl.DataFrame(counterparties_data).lazy()

    # Create empty lending group totals
    lending_group_totals = pl.DataFrame(
        {
            "lending_group": pl.Series([], dtype=pl.String),
            "total_exposure": pl.Series([], dtype=pl.Float64),
        }
    ).lazy()

    # Create CounterpartyLookup with all required fields
    counterparty_lookup = CounterpartyLookup(
        counterparties=counterparties,
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
    )

    return ResolvedHierarchyBundle(
        exposures=exposures,
        collateral=pl.DataFrame().lazy(),
        guarantees=pl.DataFrame().lazy(),
        provisions=pl.DataFrame().lazy(),
        counterparty_lookup=counterparty_lookup,
        lending_group_totals=lending_group_totals,
        model_permissions=_full_model_permissions(),
        hierarchy_errors=[],
    )


# =============================================================================
# Reclassification Eligibility Tests
# =============================================================================


class TestReclassificationEligibility:
    """Tests for corporate classification and approach routing under full_irb.

    Under PermissionMode.IRB (full_irb()), AIRB is permitted for corporate classes,
    so reclassification to retail is short-circuited. These tests verify that
    corporates with lgd + internal_pd get AIRB directly, and those without lgd
    but managed_as_retail + qualifies_as_retail fall to SA.
    """

    def test_corporate_with_lgd_gets_airb_directly(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with internal_pd + LGD gets AIRB directly (no reclassification needed).

        Under full_irb(), AIRB is permitted for corporate classes, so reclassification
        to retail is short-circuited. The exposure stays corporate with AIRB approach.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],  # Has modelled LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],  # < EUR 1m
                "exposure_for_retail_threshold": [500000.0],
                "internal_pd": [0.005],  # Internal rating required for IRB
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],  # GBP 10m
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, corporate gets AIRB directly — no reclassification
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_not_reclassified_when_not_managed_as_retail(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate without managed_as_retail flag should NOT be reclassified."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],  # NOT managed as retail
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Should stay as corporate with AIRB (has lgd + internal_pd under full_irb)
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_not_reclassified_when_exceeds_threshold(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate > EUR 1m should NOT be reclassified even if managed as retail."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [1500000.0],  # > EUR 1m (GBP 880k threshold)
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [1500000.0],  # > threshold
                "exposure_for_retail_threshold": [1500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail, but exceeds threshold
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Should stay as corporate with AIRB (has lgd + internal_pd under full_irb)
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_not_reclassified_when_no_lgd(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate without modelled LGD should NOT be reclassified and must use SA."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [None],  # No modelled LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Should stay as corporate due to missing LGD
        # Must use SA (not FIRB) because managed as retail without own LGD models
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.SA.value

    def test_corporate_not_reclassified_when_turnover_exceeds_sme_threshold(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with turnover >= EUR 50m should NOT be reclassified.

        Per CRR Art. 501, SME definition requires turnover < EUR 50m.
        Large corporates cannot be reclassified to retail even if they meet
        all other conditions (managed_as_retail, < EUR 1m, has LGD).
        """
        # EUR 50m = GBP 44m at 0.88 FX rate
        # Annual revenue of GBP 50m exceeds this threshold
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],  # < EUR 1m threshold
                "nominal_amount": [0.0],
                "lgd": [0.45],  # Has modelled LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [50000000.0],  # GBP 50m - exceeds SME threshold
                "total_assets": [100000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Should stay as CORPORATE (not CORPORATE_SME since > EUR 50m)
        # and NOT be reclassified to retail. Gets AIRB under full_irb (has lgd + internal_pd).
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_not_reclassified_when_turnover_is_zero(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with zero/missing turnover should NOT be reclassified.

        Missing revenue data means we cannot verify SME status,
        so the exposure should not qualify for retail reclassification.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],  # Has modelled LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [0.0],  # Zero revenue
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Should stay as CORPORATE and NOT be reclassified.
        # Gets AIRB under full_irb (has lgd + internal_pd).
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_sme_corporate_gets_airb_directly_under_full_irb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """SME corporate with lgd + internal_pd gets AIRB directly under full_irb.

        Under full_irb(), reclassification to retail is short-circuited because
        AIRB is permitted for corporate classes. The exposure stays CORPORATE_SME
        with AIRB approach.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],  # Has modelled LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [40000000.0],  # GBP 40m - below EUR 50m threshold
                "total_assets": [30000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, stays as CORPORATE_SME with AIRB (no reclassification)
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# Property Collateral Tests
# =============================================================================


class TestPropertyCollateralReclassification:
    """Tests for property collateral detection on corporate exposures.

    Under full_irb(), reclassification to retail is short-circuited because
    AIRB is available for corporate classes directly. These tests verify that
    corporates stay corporate with AIRB regardless of property collateral.
    """

    def test_corporate_with_residential_property_stays_corporate_airb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with residential property collateral stays CORPORATE_SME with AIRB."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [400000.0],  # Has property collateral
                "lending_group_adjusted_exposure": [100000.0],
                "exposure_for_retail_threshold": [100000.0],
                "collateral_type": ["residential"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, stays corporate with AIRB — no reclassification
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_with_commercial_property_stays_corporate_airb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with COMMERCIAL property collateral stays CORPORATE_SME with AIRB.

        Under full_irb, property collateral type does not trigger reclassification
        because AIRB is already available for corporate classes.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],  # Not a mortgage product type
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],  # No residential property
                "property_collateral_value": [400000.0],  # But has commercial property
                "lending_group_adjusted_exposure": [500000.0],  # Full exposure for threshold
                "exposure_for_retail_threshold": [500000.0],
                "collateral_type": ["commercial"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, stays corporate with AIRB — no reclassification
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_without_property_collateral_stays_corporate_airb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate without property collateral stays CORPORATE_SME with AIRB."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],  # No residential property
                "property_collateral_value": [0.0],  # No property collateral at all
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
                "collateral_type": ["financial"],  # Not property
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, stays corporate with AIRB — no reclassification
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# IRB Permission Context Tests
# =============================================================================


class TestReclassificationIRBContext:
    """Tests for reclassification behavior under different IRB permissions."""

    def test_no_reclassification_with_full_irb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """With full IRB, corporates don't need reclassification (AIRB available)."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Would qualify, but not needed
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # With full IRB, corporate stays as corporate but gets AIRB directly
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_no_reclassification_with_irb_mode_has_lgd(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Under IRB mode with lgd, corporate gets AIRB directly (no reclassification).

        Previously this tested FIRB-only permissions, but PermissionMode.IRB maps
        to full_irb() which permits AIRB for all classes. Since AIRB is available
        for corporates, reclassification is not triggered.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # With full IRB, corporate stays corporate and gets AIRB (has lgd + internal_pd)
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# Mixed Portfolio Tests
# =============================================================================


class TestMixedPortfolioReclassification:
    """Tests for mixed portfolios with various reclassification scenarios."""

    def test_mixed_portfolio_correct_classification(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Mixed portfolio should have correct classification for each exposure.

        Under full_irb(), reclassification to retail is short-circuited, so all
        corporates with lgd + internal_pd get AIRB directly. Corporates without
        lgd but managed_as_retail + qualifies_as_retail get SA.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": [
                    "CORP_WITH_PROP",  # Has residential property — stays CORPORATE_SME, AIRB
                    "CORP_WITH_COMM",  # Has commercial property — stays CORPORATE_SME, AIRB
                    "CORP_NO_PROP",  # No property — stays CORPORATE_SME, AIRB
                    "CORP_NO_LGD",  # No LGD, managed_as_retail — SA
                    "CORP_LARGE",  # > threshold, has LGD — AIRB
                    "CORP_NOT_MANAGED",  # Not managed as retail, has LGD — AIRB
                ],
                "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005", "CP006"],
                "drawn_amount": [300000.0, 350000.0, 400000.0, 500000.0, 1500000.0, 600000.0],
                "nominal_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "lgd": [0.35, 0.40, 0.45, None, 0.40, 0.45],
                "product_type": [
                    "MORTGAGE",
                    "TERM_LOAN",
                    "TERM_LOAN",
                    "TERM_LOAN",
                    "TERM_LOAN",
                    "TERM_LOAN",
                ],
                "value_date": [date(2024, 1, 1)] * 6,
                "maturity_date": [date(2029, 1, 1)] * 6,
                "currency": ["GBP"] * 6,
                "residential_collateral_value": [250000.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "property_collateral_value": [250000.0, 300000.0, 0.0, 0.0, 0.0, 0.0],
                "lending_group_adjusted_exposure": [
                    50000.0,
                    350000.0,
                    400000.0,
                    500000.0,
                    1500000.0,
                    600000.0,
                ],
                "exposure_for_retail_threshold": [
                    50000.0,
                    350000.0,
                    400000.0,
                    500000.0,
                    1500000.0,
                    600000.0,
                ],
                "collateral_type": [
                    "residential",
                    "commercial",
                    "financial",
                    "financial",
                    "financial",
                    "financial",
                ],
            },
            counterparties_data={
                "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005", "CP006"],
                "entity_type": ["corporate"] * 6,
                "country_code": ["GB"] * 6,
                "annual_revenue": [10000000.0] * 6,
                "total_assets": [5000000.0] * 6,
                "default_status": [False] * 6,
                "apply_fi_scalar": [True] * 6,
                "is_managed_as_retail": [True, True, True, True, True, False],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Sort by exposure_reference for consistent ordering
        df = df.sort("exposure_reference")

        # CORP_LARGE: has lgd + internal_pd → AIRB (reclassification short-circuited)
        row = df.filter(pl.col("exposure_reference") == "CORP_LARGE")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_NOT_MANAGED: has lgd + internal_pd → AIRB
        row = df.filter(pl.col("exposure_reference") == "CORP_NOT_MANAGED")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_NO_LGD: managed_as_retail + qualifies_as_retail + no lgd → SA
        row = df.filter(pl.col("exposure_reference") == "CORP_NO_LGD")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.SA.value

        # CORP_NO_PROP: has lgd + internal_pd → AIRB, stays CORPORATE_SME
        row = df.filter(pl.col("exposure_reference") == "CORP_NO_PROP")
        assert row["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_WITH_PROP: has lgd + internal_pd → AIRB, stays CORPORATE_SME
        row = df.filter(pl.col("exposure_reference") == "CORP_WITH_PROP")
        assert row["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_WITH_COMM: has lgd + internal_pd → AIRB, stays CORPORATE_SME
        row = df.filter(pl.col("exposure_reference") == "CORP_WITH_COMM")
        assert row["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# FIRB LGD Clearing Tests
# =============================================================================


class TestLGDHandlingByApproach:
    """Tests for LGD handling based on approach assignment.

    Under full_irb(), AIRB is permitted for all corporate classes. Exposures
    with internal_pd + lgd get AIRB (LGD preserved). FIRB LGD clearing only
    applies when an exposure is assigned FIRB (no AIRB permission or no lgd),
    but under full_irb there are no FIRB-only classes.
    """

    def test_airb_corporate_keeps_lgd(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with lgd + internal_pd gets AIRB — LGD preserved."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [1500000.0],  # > EUR 1m threshold
                "nominal_amount": [0.0],
                "lgd": [0.20],  # Internal LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [1500000.0],
                "exposure_for_retail_threshold": [1500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],  # Managed as retail but exceeds threshold
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, AIRB is available for corporate — LGD is NOT cleared
        assert df["approach"][0] == ApproachType.AIRB.value
        assert df["lgd"][0] == pytest.approx(0.20, abs=1e-10)

    def test_airb_sme_corporate_keeps_lgd(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """SME corporate with lgd + internal_pd gets AIRB — LGD preserved."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],  # < EUR 1m threshold
                "nominal_amount": [0.0],
                "lgd": [0.20],  # Internal LGD
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [500000.0],
                "exposure_for_retail_threshold": [500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Under full_irb, AIRB is available — stays CORPORATE_SME with LGD preserved
        assert df["approach"][0] == ApproachType.AIRB.value
        assert df["reclassified_to_retail"][0] is False
        assert df["lgd"][0] == pytest.approx(0.20, abs=1e-10)

    def test_individual_exceeding_threshold_gets_airb_lgd_preserved(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Retail individual exceeding EUR 1M gets AIRB (LGD preserved) under full_irb.

        The individual exceeds the retail threshold, so it gets reclassified to
        corporate. Under full_irb, AIRB is available for corporate classes, so
        the exposure gets AIRB and LGD is NOT cleared.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["RETAIL001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [1500000.0],  # > EUR 1m threshold
                "nominal_amount": [0.0],
                "lgd": [0.25],  # Internal retail LGD
                "product_type": ["TERM_LOAN"],  # Not a mortgage
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],  # No residential property
                "property_collateral_value": [0.0],  # No property collateral
                "lending_group_adjusted_exposure": [1500000.0],
                "exposure_for_retail_threshold": [1500000.0],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["individual"],  # Retail individual
                "country_code": ["GB"],
                "annual_revenue": [100000.0],  # Low revenue (individual)
                "total_assets": [2000000.0],
                "default_status": [False],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Reclassified from retail to corporate due to exceeding threshold
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        # Under full_irb, AIRB available for corporate — LGD preserved
        assert df["approach"][0] == ApproachType.AIRB.value
        assert df["lgd"][0] == pytest.approx(0.25, abs=1e-10)
