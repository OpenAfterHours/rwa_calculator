"""
Unit tests for Pre/Post CRM attribute tracking in CRM processor.

Tests the implementation of Tasks 1.1-1.4 from the pre-post-crm-counterparty-plan:
- Pre-CRM attribute preservation
- Guarantor exposure class derivation
- Post-CRM composite attributes
- SA and IRB pre-CRM risk weight tracking
"""

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.processor import CRMProcessor


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Create CRR configuration for tests."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crm_processor() -> CRMProcessor:
    """Create CRM processor instance."""
    return CRMProcessor()


class TestPreCRMAttributePreservation:
    """Tests for Task 1.1: Pre-CRM attribute preservation."""

    def test_pre_crm_counterparty_reference_preserved(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Pre-CRM counterparty should be original borrower."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["SA"],
            "ead_pre_crm": [1_000_000.0],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            # CCF-required columns
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
        })

        counterparties = pl.LazyFrame({
            "counterparty_reference": ["CP001"],
            "entity_type": ["corporate"],
        })

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=CounterpartyLookup(
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
                }),
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        assert "pre_crm_counterparty_reference" in df.columns
        assert df["pre_crm_counterparty_reference"][0] == "CP001"

    def test_pre_crm_exposure_class_preserved(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Pre-CRM exposure class should be original classification."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["SA"],
            "ead_pre_crm": [1_000_000.0],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            # CCF-required columns
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
        })

        counterparties = pl.LazyFrame({
            "counterparty_reference": ["CP001"],
            "entity_type": ["corporate"],
        })

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=CounterpartyLookup(
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
                }),
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        assert "pre_crm_exposure_class" in df.columns
        assert df["pre_crm_exposure_class"][0] == "CORPORATE"


class TestGuarantorExposureClassDerivation:
    """Tests for Task 1.2: Guarantor exposure class derivation."""

    def test_sovereign_guarantor_maps_to_sovereign_class(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Sovereign guarantor should map to SOVEREIGN exposure class."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["SA"],
            "ead_pre_crm": [1_000_000.0],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            # CCF-required columns
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
        })

        counterparties = pl.LazyFrame({
            "counterparty_reference": ["CP001", "GUAR001"],
            "entity_type": ["corporate", "sovereign"],
        })

        guarantees = pl.LazyFrame({
            "beneficiary_reference": ["EXP001"],
            "amount_covered": [600_000.0],
            "percentage_covered": [None],
            "guarantor": ["GUAR001"],
        })

        rating_inheritance = pl.LazyFrame({
            "counterparty_reference": ["CP001", "GUAR001"],
            "cqs": [3, 1],
            "pd": [0.01, 0.0001],
        })

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=CounterpartyLookup(
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
                rating_inheritance=rating_inheritance,
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        assert "post_crm_exposure_class_guaranteed" in df.columns
        # Entity type mapping produces lowercase class names
        assert df["post_crm_exposure_class_guaranteed"][0] == "central_govt_central_bank"

    def test_institution_guarantor_maps_to_institution_class(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Institution guarantor should map to INSTITUTION exposure class."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["SA"],
            "ead_pre_crm": [1_000_000.0],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            # CCF-required columns
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
        })

        counterparties = pl.LazyFrame({
            "counterparty_reference": ["CP001", "BANK001"],
            "entity_type": ["corporate", "institution"],
        })

        guarantees = pl.LazyFrame({
            "beneficiary_reference": ["EXP001"],
            "amount_covered": [600_000.0],
            "percentage_covered": [None],
            "guarantor": ["BANK001"],
        })

        rating_inheritance = pl.LazyFrame({
            "counterparty_reference": ["CP001", "BANK001"],
            "cqs": [3, 2],
            "pd": [0.01, 0.001],
        })

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=CounterpartyLookup(
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
                rating_inheritance=rating_inheritance,
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # Entity type mapping produces lowercase class names
        assert df["post_crm_exposure_class_guaranteed"][0] == "institution"


class TestPostCRMCompositeAttributes:
    """Tests for Task 1.3: Post-CRM composite attributes."""

    def test_is_guaranteed_flag_set_correctly(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """is_guaranteed flag should be True for guaranteed exposures."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001", "EXP002"],
            "counterparty_reference": ["CP001", "CP002"],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "approach": ["SA", "SA"],
            "ead_pre_crm": [1_000_000.0, 500_000.0],
            "lgd": [0.45, 0.45],
            "cqs": [3, 3],
            "product_type": ["LOAN", "LOAN"],
            # CCF-required columns
            "drawn_amount": [1_000_000.0, 500_000.0],
            "undrawn_amount": [0.0, 0.0],
            "nominal_amount": [0.0, 0.0],
            "risk_type": [None, None],
        })

        counterparties = pl.LazyFrame({
            "counterparty_reference": ["CP001", "CP002", "GUAR001"],
            "entity_type": ["corporate", "corporate", "sovereign"],
        })

        guarantees = pl.LazyFrame({
            "beneficiary_reference": ["EXP001"],  # Only EXP001 is guaranteed
            "amount_covered": [600_000.0],
            "percentage_covered": [None],
            "guarantor": ["GUAR001"],
        })

        rating_inheritance = pl.LazyFrame({
            "counterparty_reference": ["CP001", "CP002", "GUAR001"],
            "cqs": [3, 3, 1],
            "pd": [0.01, 0.01, 0.0001],
        })

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=CounterpartyLookup(
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
                rating_inheritance=rating_inheritance,
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect().sort("exposure_reference")

        assert "is_guaranteed" in df.columns
        assert df["is_guaranteed"][0] is True  # EXP001 is guaranteed
        assert df["is_guaranteed"][1] is False  # EXP002 is not guaranteed

    def test_no_guarantee_pre_post_same(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-guaranteed exposures have identical pre/post CRM attributes."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["SA"],
            "ead_pre_crm": [1_000_000.0],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            # CCF-required columns
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
        })

        counterparties = pl.LazyFrame({
            "counterparty_reference": ["CP001"],
            "entity_type": ["corporate"],
        })

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=CounterpartyLookup(
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
                }),
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # For non-guaranteed exposures, post-CRM = pre-CRM
        assert df["pre_crm_counterparty_reference"][0] == df["post_crm_counterparty_guaranteed"][0]
        assert df["pre_crm_exposure_class"][0] == df["post_crm_exposure_class_guaranteed"][0]
        assert df["is_guaranteed"][0] is False
