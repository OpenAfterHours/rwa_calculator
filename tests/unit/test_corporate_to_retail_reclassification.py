"""Unit tests for corporate-to-retail reclassification in classifier.

Tests cover:
- Reclassification criteria: managed_as_retail, < EUR 1m, has LGD, turnover < EUR 50m
- Property collateral detection → RETAIL_MORTGAGE vs RETAIL_OTHER
- QRRE exclusion (reclassified corporates never become QRRE)
- Reclassification only applies with hybrid IRB permissions
- Turnover threshold for SME definition per CRR Art. 501
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.contracts.bundles import (
    ResolvedHierarchyBundle,
    CounterpartyLookup,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> ExposureClassifier:
    """Return an ExposureClassifier instance."""
    return ExposureClassifier()


@pytest.fixture
def hybrid_config() -> CalculationConfig:
    """Return CRR config with hybrid retail AIRB / corporate FIRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.retail_airb_corporate_firb(),
    )


@pytest.fixture
def full_irb_config() -> CalculationConfig:
    """Return CRR config with full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def firb_only_config() -> CalculationConfig:
    """Return CRR config with FIRB only permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


def create_test_bundle(
    exposures_data: dict,
    counterparties_data: dict,
) -> ResolvedHierarchyBundle:
    """Create a test ResolvedHierarchyBundle from data dicts."""
    exposures = pl.DataFrame(exposures_data).lazy()
    counterparties = pl.DataFrame(counterparties_data).lazy()

    # Create empty lending group totals
    lending_group_totals = pl.DataFrame({
        "lending_group": pl.Series([], dtype=pl.String),
        "total_exposure": pl.Series([], dtype=pl.Float64),
    }).lazy()

    # Create CounterpartyLookup with all required fields
    counterparty_lookup = CounterpartyLookup(
        counterparties=counterparties,
        parent_mappings=pl.LazyFrame(schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }),
        ultimate_parent_mappings=pl.LazyFrame(schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }),
        rating_inheritance=pl.LazyFrame(schema={
            "counterparty_reference": pl.String,
            "cqs": pl.Int8,
            "pd": pl.Float64,
            "rating_value": pl.String,
            "inherited": pl.Boolean,
            "source_counterparty": pl.String,
            "inheritance_reason": pl.String,
        }),
    )

    return ResolvedHierarchyBundle(
        exposures=exposures,
        collateral=pl.DataFrame().lazy(),
        guarantees=pl.DataFrame().lazy(),
        provisions=pl.DataFrame().lazy(),
        counterparty_lookup=counterparty_lookup,
        lending_group_totals=lending_group_totals,
        hierarchy_errors=[],
    )


# =============================================================================
# Reclassification Eligibility Tests
# =============================================================================


class TestReclassificationEligibility:
    """Tests for corporate-to-retail reclassification eligibility criteria."""

    def test_corporate_reclassified_when_all_conditions_met(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
    ) -> None:
        """Corporate with managed_as_retail, < EUR 1m, and LGD should be reclassified."""
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
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],  # GBP 10m
                "total_assets": [5000000.0],
                "default_status": [False],
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_not_reclassified_when_not_managed_as_retail(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
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
                "is_regulated": [False],
                "is_managed_as_retail": [False],  # NOT managed as retail
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        # Should stay as corporate with FIRB
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_corporate_not_reclassified_when_exceeds_threshold(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Managed as retail, but exceeds threshold
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        # Should stay as corporate (qualifies_as_retail = False due to threshold)
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_corporate_not_reclassified_when_no_lgd(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, hybrid_config)
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
        hybrid_config: CalculationConfig,
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        # Should stay as CORPORATE (not CORPORATE_SME since > EUR 50m)
        # and NOT be reclassified to retail
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_corporate_not_reclassified_when_turnover_is_zero(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        # Should stay as CORPORATE and NOT be reclassified
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_sme_corporate_with_turnover_below_threshold_reclassified(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
    ) -> None:
        """SME corporate with turnover < EUR 50m should be reclassified when all conditions met.

        This confirms that the turnover check works correctly at the boundary.
        EUR 50m = GBP 44m at 0.88 FX rate.
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Managed as retail
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        # Should be reclassified to RETAIL_OTHER
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# Property Collateral Tests
# =============================================================================


class TestPropertyCollateralReclassification:
    """Tests for property collateral affecting reclassification target."""

    def test_corporate_with_property_collateral_becomes_retail_mortgage(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
    ) -> None:
        """Corporate with property collateral should become RETAIL_MORTGAGE."""
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["reclassified_to_retail"][0] is True
        assert df["has_property_collateral"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_with_commercial_property_becomes_retail_mortgage(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
    ) -> None:
        """Corporate with COMMERCIAL property collateral should become RETAIL_MORTGAGE.

        This tests that commercial property (not just residential) qualifies an
        exposure for retail_mortgage treatment, which has a fixed 0.15 correlation
        instead of the PD-dependent correlation for retail_other.
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["reclassified_to_retail"][0] is True
        assert df["has_property_collateral"][0] is True
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_corporate_without_property_collateral_becomes_retail_other(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
    ) -> None:
        """Corporate without property collateral should become RETAIL_OTHER."""
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert df["reclassified_to_retail"][0] is True
        assert df["has_property_collateral"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# IRB Permission Context Tests
# =============================================================================


class TestReclassificationIRBContext:
    """Tests for reclassification behavior under different IRB permissions."""

    def test_no_reclassification_with_full_irb(
        self,
        classifier: ExposureClassifier,
        full_irb_config: CalculationConfig,
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],  # Would qualify, but not needed
            },
        )

        result = classifier.classify(bundle, full_irb_config)
        df = result.all_exposures.collect()

        # With full IRB, corporate stays as corporate but gets AIRB directly
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_no_reclassification_with_firb_only(
        self,
        classifier: ExposureClassifier,
        firb_only_config: CalculationConfig,
    ) -> None:
        """With FIRB only, reclassification doesn't help (no AIRB for retail)."""
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
                "is_regulated": [False],
                "is_managed_as_retail": [True],
            },
        )

        result = classifier.classify(bundle, firb_only_config)
        df = result.all_exposures.collect()

        # With FIRB only, stays as corporate with FIRB (retail would only have SA)
        assert df["exposure_class"][0] in [
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        ]
        assert df["reclassified_to_retail"][0] is False
        assert df["approach"][0] == ApproachType.FIRB.value


# =============================================================================
# Mixed Portfolio Tests
# =============================================================================


class TestMixedPortfolioReclassification:
    """Tests for mixed portfolios with various reclassification scenarios."""

    def test_mixed_portfolio_correct_classification(
        self,
        classifier: ExposureClassifier,
        hybrid_config: CalculationConfig,
    ) -> None:
        """Mixed portfolio should have correct classification for each exposure."""
        bundle = create_test_bundle(
            exposures_data={
                "exposure_reference": [
                    "CORP_RETAIL_PROP",   # Should become RETAIL_MORTGAGE (residential)
                    "CORP_RETAIL_COMM",   # Should become RETAIL_MORTGAGE (commercial)
                    "CORP_RETAIL_OTHER",  # Should become RETAIL_OTHER
                    "CORP_NO_LGD",        # Should stay CORPORATE (no LGD)
                    "CORP_LARGE",         # Should stay CORPORATE (> threshold)
                    "CORP_NOT_MANAGED",   # Should stay CORPORATE (not managed as retail)
                ],
                "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005", "CP006"],
                "drawn_amount": [300000.0, 350000.0, 400000.0, 500000.0, 1500000.0, 600000.0],
                "nominal_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "lgd": [0.35, 0.40, 0.45, None, 0.40, 0.45],
                "product_type": ["MORTGAGE", "TERM_LOAN", "TERM_LOAN", "TERM_LOAN", "TERM_LOAN", "TERM_LOAN"],
                "value_date": [date(2024, 1, 1)] * 6,
                "maturity_date": [date(2029, 1, 1)] * 6,
                "currency": ["GBP"] * 6,
                # residential_collateral_value only for residential property (threshold exclusion)
                "residential_collateral_value": [250000.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                # property_collateral_value for both residential AND commercial (mortgage classification)
                "property_collateral_value": [250000.0, 300000.0, 0.0, 0.0, 0.0, 0.0],
                "lending_group_adjusted_exposure": [50000.0, 350000.0, 400000.0, 500000.0, 1500000.0, 600000.0],
                "exposure_for_retail_threshold": [50000.0, 350000.0, 400000.0, 500000.0, 1500000.0, 600000.0],
                "collateral_type": ["residential", "commercial", "financial", "financial", "financial", "financial"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005", "CP006"],
                "entity_type": ["corporate"] * 6,
                "country_code": ["GB"] * 6,
                "annual_revenue": [10000000.0] * 6,
                "total_assets": [5000000.0] * 6,
                "default_status": [False] * 6,
                "is_regulated": [False] * 6,
                "is_managed_as_retail": [True, True, True, True, True, False],
            },
        )

        result = classifier.classify(bundle, hybrid_config)
        df = result.all_exposures.collect()

        # Sort by exposure_reference for consistent ordering
        df = df.sort("exposure_reference")

        # CORP_LARGE: stays CORPORATE (> threshold)
        row = df.filter(pl.col("exposure_reference") == "CORP_LARGE")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.FIRB.value

        # CORP_NOT_MANAGED: stays CORPORATE (not managed as retail)
        row = df.filter(pl.col("exposure_reference") == "CORP_NOT_MANAGED")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.FIRB.value

        # CORP_NO_LGD: stays CORPORATE (no modelled LGD) - must use SA
        row = df.filter(pl.col("exposure_reference") == "CORP_NO_LGD")
        assert row["reclassified_to_retail"][0] is False
        assert row["approach"][0] == ApproachType.SA.value

        # CORP_RETAIL_OTHER: becomes RETAIL_OTHER (no property collateral)
        row = df.filter(pl.col("exposure_reference") == "CORP_RETAIL_OTHER")
        assert row["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value
        assert row["reclassified_to_retail"][0] is True
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_RETAIL_PROP: becomes RETAIL_MORTGAGE (has residential property collateral)
        row = df.filter(pl.col("exposure_reference") == "CORP_RETAIL_PROP")
        assert row["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert row["reclassified_to_retail"][0] is True
        assert row["approach"][0] == ApproachType.AIRB.value

        # CORP_RETAIL_COMM: becomes RETAIL_MORTGAGE (has COMMERCIAL property collateral)
        # This verifies that commercial property also qualifies for retail_mortgage treatment
        row = df.filter(pl.col("exposure_reference") == "CORP_RETAIL_COMM")
        assert row["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert row["reclassified_to_retail"][0] is True
        assert row["has_property_collateral"][0] is True
        assert row["approach"][0] == ApproachType.AIRB.value
