"""Unit tests for corporate-to-retail reclassification in classifier.

Tests cover:
- Reclassification criteria: retail outranks corporate in the exposure class
  waterfall (CRR Art. 147(5)). Qualifying corporates are always reclassified
  to retail when eligibility conditions are met.
- Property collateral detection for mortgage vs other retail classification
- Approach routing: reclassified retail exposures get AIRB via model permissions
- FIRB LGD clearing applies only to FIRB (not AIRB) exposures
- Turnover threshold for SME definition per CRR Art. 501
- Negative cases: missing managed_as_retail, exceeding threshold, no LGD, etc.
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
    """Tests for corporate-to-retail reclassification eligibility.

    Retail outranks corporate in the exposure class waterfall (CRR Art. 147(5)).
    Corporates meeting all criteria (managed_as_retail, qualifies_as_retail,
    has LGD, SME turnover) are reclassified to retail. The approach is then
    determined by model_permissions in the subsequent phase.
    """

    def test_corporate_with_lgd_reclassified_to_retail(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate meeting all retail criteria is reclassified to retail_other.

        Retail outranks corporate in the waterfall. When managed_as_retail=True,
        qualifies_as_retail=True, lgd present, and SME turnover, the exposure
        is reclassified to retail_other and gets AIRB via model permissions.
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

        # Meets all reclassification criteria → reclassified to retail_other
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
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

    def test_sme_corporate_reclassified_to_retail(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """SME corporate meeting retail criteria is reclassified to retail_other.

        Retail outranks corporate in the waterfall. SME corporate with
        managed_as_retail + lgd + qualifying exposure is reclassified.
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

        # Meets all reclassification criteria → reclassified to retail_other
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# Property Collateral Tests
# =============================================================================


class TestPropertyCollateralReclassification:
    """Tests for property collateral detection during corporate-to-retail reclassification.

    When a corporate meets retail reclassification criteria, property collateral
    determines whether the reclassified class is RETAIL_MORTGAGE or RETAIL_OTHER.
    """

    def test_corporate_with_residential_property_reclassified_to_mortgage(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with residential property collateral reclassified to RETAIL_MORTGAGE."""
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

        # Residential property → reclassified to retail_mortgage
        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_with_commercial_property_reclassified_to_mortgage(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with commercial property collateral reclassified to RETAIL_MORTGAGE.

        Property collateral (residential or commercial) routes the reclassified
        exposure to RETAIL_MORTGAGE rather than RETAIL_OTHER.
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

        # Commercial property → reclassified to retail_mortgage
        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_without_property_reclassified_to_retail_other(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate without property collateral reclassified to RETAIL_OTHER."""
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

        # No property collateral → reclassified to retail_other
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# IRB Permission Context Tests
# =============================================================================


class TestReclassificationIRBContext:
    """Tests for reclassification behavior under IRB permissions.

    Reclassification is an exposure-class decision, independent of approach
    permissions. Corporate exposures meeting retail criteria are always
    reclassified regardless of whether AIRB is available for corporate.
    """

    def test_qualifying_corporate_reclassified_under_full_irb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate meeting retail criteria is reclassified even under full IRB."""
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

        # Retail outranks corporate — reclassified to retail_other with AIRB
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_qualifying_corporate_with_lgd_reclassified_under_irb_mode(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with LGD meeting retail criteria is reclassified under IRB mode.

        Reclassification is an exposure-class decision independent of approach.
        The exposure is reclassified to retail and gets AIRB via model permissions.
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

        # Retail outranks corporate — reclassified to retail_other with AIRB
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
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
        """Mixed portfolio: qualifying corporates reclassified, others stay corporate.

        Reclassification criteria: managed_as_retail + qualifies_as_retail + lgd + SME
        turnover. Exposures failing any condition stay corporate.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": [
                    "CORP_WITH_PROP",  # Residential property → RETAIL_MORTGAGE, AIRB
                    "CORP_WITH_COMM",  # Commercial property → RETAIL_MORTGAGE, AIRB
                    "CORP_NO_PROP",  # No property → RETAIL_OTHER, AIRB
                    "CORP_NO_LGD",  # No LGD → stays corporate, SA
                    "CORP_LARGE",  # > threshold → stays corporate (qualifies_as_retail=False)
                    "CORP_NOT_MANAGED",  # Not managed as retail → stays corporate, AIRB
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

        # CORP_WITH_PROP: residential property → reclassified to RETAIL_MORTGAGE
        row = df.filter(pl.col("exposure_reference") == "CORP_WITH_PROP")
        assert row["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert row["reclassified_to_retail"][0] is True
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_WITH_COMM: commercial property → reclassified to RETAIL_MORTGAGE
        row = df.filter(pl.col("exposure_reference") == "CORP_WITH_COMM")
        assert row["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert row["reclassified_to_retail"][0] is True
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_NO_PROP: no property → reclassified to RETAIL_OTHER
        row = df.filter(pl.col("exposure_reference") == "CORP_NO_PROP")
        assert row["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert row["reclassified_to_retail"][0] is True
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_NO_LGD: no lgd → stays corporate, SA
        row = df.filter(pl.col("exposure_reference") == "CORP_NO_LGD")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.SA.value

        # CORP_LARGE: exceeds retail threshold → stays corporate, AIRB
        row = df.filter(pl.col("exposure_reference") == "CORP_LARGE")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_NOT_MANAGED: not managed as retail → stays corporate, AIRB
        row = df.filter(pl.col("exposure_reference") == "CORP_NOT_MANAGED")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# FIRB LGD Clearing Tests
# =============================================================================


class TestLGDHandlingByApproach:
    """Tests for LGD handling based on approach assignment.

    LGD is preserved for AIRB exposures (including reclassified retail).
    FIRB LGD clearing only applies when an exposure is assigned FIRB.
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

    def test_reclassified_retail_keeps_lgd(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """SME corporate reclassified to retail keeps LGD (AIRB, not FIRB)."""
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

        # Reclassified to retail_other with AIRB — LGD preserved
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value
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


# =============================================================================
# Model Permission Reclassification Tests
# =============================================================================


def _hybrid_model_permissions(model_id: str = _TEST_MODEL_ID) -> pl.LazyFrame:
    """Model permissions with FIRB for corporate and AIRB for retail classes.

    Simulates a model approved for FIRB on corporate exposures but AIRB
    on retail classes — the scenario where corporate-to-retail reclassification
    enables the exposure to receive retail AIRB treatment.
    """
    return pl.DataFrame(
        [
            {"model_id": model_id, "exposure_class": "corporate", "approach": "foundation_irb"},
            {"model_id": model_id, "exposure_class": "corporate_sme", "approach": "foundation_irb"},
            {"model_id": model_id, "exposure_class": "retail_other", "approach": "advanced_irb"},
            {"model_id": model_id, "exposure_class": "retail_mortgage", "approach": "advanced_irb"},
            {"model_id": model_id, "exposure_class": "retail_qrre", "approach": "advanced_irb"},
        ]
    ).lazy()


class TestModelPermissionReclassification:
    """Tests for corporate-to-retail reclassification with model-level permissions.

    When model_permissions grant only FIRB for corporate but AIRB for retail,
    reclassified exposures should match the retail AIRB permission and get AIRB
    instead of being stuck on corporate FIRB.
    """

    def test_reclassified_corporate_gets_retail_airb_via_model_permissions(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with hybrid model perms: reclassified to retail, gets AIRB.

        Model has FIRB for corporate, AIRB for retail. Exposure meets retail
        reclassification criteria. After reclassification, the retail AIRB
        model permission matches and the exposure gets AIRB.
        """
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [100000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [100000.0],
                "exposure_for_retail_threshold": [100000.0],
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
        # Override the bundle's model_permissions with hybrid permissions
        bundle = ResolvedHierarchyBundle(
            exposures=bundle.exposures,
            collateral=bundle.collateral,
            guarantees=bundle.guarantees,
            provisions=bundle.provisions,
            counterparty_lookup=bundle.counterparty_lookup,
            lending_group_totals=bundle.lending_group_totals,
            model_permissions=_hybrid_model_permissions(),
            hierarchy_errors=bundle.hierarchy_errors,
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value
        assert df["lgd"][0] == pytest.approx(0.45, abs=1e-10)

    def test_reclassified_corporate_to_mortgage_gets_airb(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with property collateral and hybrid perms → RETAIL_MORTGAGE, AIRB."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [100000.0],
                "nominal_amount": [0.0],
                "lgd": [0.35],
                "product_type": ["MORTGAGE"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [200000.0],
                "property_collateral_value": [200000.0],
                "collateral_type": ["residential"],
                "lending_group_adjusted_exposure": [100000.0],
                "exposure_for_retail_threshold": [100000.0],
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
        bundle = ResolvedHierarchyBundle(
            exposures=bundle.exposures,
            collateral=bundle.collateral,
            guarantees=bundle.guarantees,
            provisions=bundle.provisions,
            counterparty_lookup=bundle.counterparty_lookup,
            lending_group_totals=bundle.lending_group_totals,
            model_permissions=_hybrid_model_permissions(),
            hierarchy_errors=bundle.hierarchy_errors,
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_stays_firb_when_no_retail_model_permission(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate with only FIRB model perms (no retail): stays corporate FIRB.

        When model_permissions only have FIRB for corporate and no retail entries,
        the exposure is reclassified to retail but model permissions don't match
        any retail class, so it falls back to SA.
        """
        firb_only_perms = pl.DataFrame(
            [
                {
                    "model_id": _TEST_MODEL_ID,
                    "exposure_class": "corporate",
                    "approach": "foundation_irb",
                },
                {
                    "model_id": _TEST_MODEL_ID,
                    "exposure_class": "corporate_sme",
                    "approach": "foundation_irb",
                },
            ]
        ).lazy()

        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [100000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [100000.0],
                "exposure_for_retail_threshold": [100000.0],
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
        bundle = ResolvedHierarchyBundle(
            exposures=bundle.exposures,
            collateral=bundle.collateral,
            guarantees=bundle.guarantees,
            provisions=bundle.provisions,
            counterparty_lookup=bundle.counterparty_lookup,
            lending_group_totals=bundle.lending_group_totals,
            model_permissions=firb_only_perms,
            hierarchy_errors=bundle.hierarchy_errors,
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Reclassified to retail, but no retail model permission → SA fallback
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.SA.value

    def test_corporate_not_reclassified_when_conditions_not_met(
        self,
        classifier: ExposureClassifier,
        irb_config: CalculationConfig,
    ) -> None:
        """Corporate not managed as retail stays corporate even with hybrid perms."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": ["CORP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [100000.0],
                "nominal_amount": [0.0],
                "lgd": [0.45],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "residential_collateral_value": [0.0],
                "lending_group_adjusted_exposure": [100000.0],
                "exposure_for_retail_threshold": [100000.0],
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
        bundle = ResolvedHierarchyBundle(
            exposures=bundle.exposures,
            collateral=bundle.collateral,
            guarantees=bundle.guarantees,
            provisions=bundle.provisions,
            counterparty_lookup=bundle.counterparty_lookup,
            lending_group_totals=bundle.lending_group_totals,
            model_permissions=_hybrid_model_permissions(),
            hierarchy_errors=bundle.hierarchy_errors,
        )

        result = classifier.classify(bundle, irb_config)
        df = result.all_exposures.collect()

        # Not managed as retail → stays corporate, gets FIRB from model perms
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.FIRB.value
