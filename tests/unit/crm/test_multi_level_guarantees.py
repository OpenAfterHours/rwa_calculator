"""
Unit tests for multi-level guarantee application in CRM processor.

Tests that guarantees applied at facility and counterparty levels are correctly
expanded and allocated pro-rata to individual exposures, matching the existing
multi-level patterns for collateral and provisions.

References:
    CRR Art. 213-217: Unfunded credit protection
    CRE22.70-85: Basel 3.1 guarantee substitution
"""

from __future__ import annotations

from datetime import date

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
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


@pytest.fixture
def crm_processor() -> CRMProcessor:
    return CRMProcessor()


def _counterparty_lookup(
    counterparties: pl.LazyFrame,
    rating_inheritance: pl.LazyFrame | None = None,
) -> CounterpartyLookup:
    if rating_inheritance is None:
        rating_inheritance = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
            }
        )
    return CounterpartyLookup(
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
        rating_inheritance=rating_inheritance,
    )


class TestFacilityLevelGuarantee:
    """Guarantees with beneficiary_type='facility' should apply to all child exposures."""

    def test_facility_guarantee_allocated_pro_rata_by_ead(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility-level guarantee should be split pro-rata across child exposures."""
        # Arrange: two loans under one facility, guarantee at facility level
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A", "LOAN_B"],
                "counterparty_reference": ["CP001", "CP001"],
                "parent_facility_reference": ["FAC_001", "FAC_001"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach": ["SA", "SA"],
                "ead_pre_crm": [600_000.0, 400_000.0],
                "lgd": [0.45, 0.45],
                "cqs": [3, 3],
                "product_type": ["LOAN", "LOAN"],
                "drawn_amount": [600_000.0, 400_000.0],
                "undrawn_amount": [0.0, 0.0],
                "nominal_amount": [0.0, 0.0],
                "risk_type": [None, None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "sovereign"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["FAC_001"],
                "beneficiary_type": ["facility"],
                "amount_covered": [500_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 1],
                "pd": [0.01, 0.0001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        # Act
        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect().sort("exposure_reference")

        # Assert: guarantee allocated pro-rata (60/40 split on 500k)
        # Each exposure produces 2 sub-rows (guarantor + remainder)
        loan_a = df.filter(pl.col("parent_exposure_reference") == "LOAN_A")
        loan_b = df.filter(pl.col("parent_exposure_reference") == "LOAN_B")

        # LOAN_A: 600k / 1000k * 500k = 300k guaranteed
        assert loan_a["guaranteed_portion"].sum() == pytest.approx(300_000.0, rel=1e-6)
        # LOAN_B: 400k / 1000k * 500k = 200k guaranteed
        assert loan_b["guaranteed_portion"].sum() == pytest.approx(200_000.0, rel=1e-6)

    def test_facility_guarantee_with_percentage_covered(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Percentage-based facility guarantee should apply to each child's EAD."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A", "LOAN_B"],
                "counterparty_reference": ["CP001", "CP001"],
                "parent_facility_reference": ["FAC_001", "FAC_001"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach": ["SA", "SA"],
                "ead_pre_crm": [600_000.0, 400_000.0],
                "lgd": [0.45, 0.45],
                "cqs": [3, 3],
                "product_type": ["LOAN", "LOAN"],
                "drawn_amount": [600_000.0, 400_000.0],
                "undrawn_amount": [0.0, 0.0],
                "nominal_amount": [0.0, 0.0],
                "risk_type": [None, None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "institution"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["FAC_001"],
                "beneficiary_type": ["facility"],
                "amount_covered": [0.0],
                "percentage_covered": [0.60],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 2],
                "pd": [0.01, 0.001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect().sort("exposure_reference")

        loan_a = df.filter(pl.col("parent_exposure_reference") == "LOAN_A")
        loan_b = df.filter(pl.col("parent_exposure_reference") == "LOAN_B")

        # 60% of each child's EAD
        assert loan_a["guaranteed_portion"].sum() == pytest.approx(360_000.0, rel=1e-6)
        assert loan_b["guaranteed_portion"].sum() == pytest.approx(240_000.0, rel=1e-6)

    def test_facility_guarantee_guarantor_substitution(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility-level guarantee should substitute guarantor for post-CRM reporting."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": ["FAC_001"],
                "exposure_class": ["CORPORATE"],
                "approach": ["SA"],
                "ead_pre_crm": [1_000_000.0],
                "lgd": [0.45],
                "cqs": [3],
                "product_type": ["LOAN"],
                "drawn_amount": [1_000_000.0],
                "undrawn_amount": [0.0],
                "nominal_amount": [0.0],
                "risk_type": [None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "sovereign"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["FAC_001"],
                "beneficiary_type": ["facility"],
                "amount_covered": [1_000_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 1],
                "pd": [0.01, 0.0001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # Guarantor sub-row should have the substituted counterparty
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["post_crm_counterparty_guaranteed"][0] == "GUAR001"
        assert guar_row["post_crm_exposure_class_guaranteed"][0] == "central_govt_central_bank"


class TestCounterpartyLevelGuarantee:
    """Guarantees with beneficiary_type='counterparty' should apply to all exposures."""

    def test_counterparty_guarantee_allocated_pro_rata(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Counterparty-level guarantee should be split pro-rata across exposures."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A", "LOAN_B", "LOAN_C"],
                "counterparty_reference": ["CP001", "CP001", "CP001"],
                "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
                "approach": ["SA", "SA", "SA"],
                "ead_pre_crm": [500_000.0, 300_000.0, 200_000.0],
                "lgd": [0.45, 0.45, 0.45],
                "cqs": [3, 3, 3],
                "product_type": ["LOAN", "LOAN", "LOAN"],
                "drawn_amount": [500_000.0, 300_000.0, 200_000.0],
                "undrawn_amount": [0.0, 0.0, 0.0],
                "nominal_amount": [0.0, 0.0, 0.0],
                "risk_type": [None, None, None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "institution"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP001"],
                "beneficiary_type": ["counterparty"],
                "amount_covered": [400_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 2],
                "pd": [0.01, 0.001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect().sort("exposure_reference")

        # Pro-rata: 500/1000*400=200, 300/1000*400=120, 200/1000*400=80
        loan_a = df.filter(pl.col("parent_exposure_reference") == "LOAN_A")
        loan_b = df.filter(pl.col("parent_exposure_reference") == "LOAN_B")
        loan_c = df.filter(pl.col("parent_exposure_reference") == "LOAN_C")

        assert loan_a["guaranteed_portion"].sum() == pytest.approx(200_000.0, rel=1e-6)
        assert loan_b["guaranteed_portion"].sum() == pytest.approx(120_000.0, rel=1e-6)
        assert loan_c["guaranteed_portion"].sum() == pytest.approx(80_000.0, rel=1e-6)


class TestMixedLevelGuarantees:
    """Guarantees at multiple levels should combine correctly."""

    def test_direct_and_facility_guarantees_combine(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Direct + facility guarantees on same exposure should sum."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A", "LOAN_B"],
                "counterparty_reference": ["CP001", "CP001"],
                "parent_facility_reference": ["FAC_001", "FAC_001"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach": ["SA", "SA"],
                "ead_pre_crm": [500_000.0, 500_000.0],
                "lgd": [0.45, 0.45],
                "cqs": [3, 3],
                "product_type": ["LOAN", "LOAN"],
                "drawn_amount": [500_000.0, 500_000.0],
                "undrawn_amount": [0.0, 0.0],
                "nominal_amount": [0.0, 0.0],
                "risk_type": [None, None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "sovereign"],
            }
        )

        # Direct guarantee on LOAN_A (200k) + facility guarantee on FAC_001 (400k)
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["LOAN_A", "FAC_001"],
                "beneficiary_type": ["loan", "facility"],
                "amount_covered": [200_000.0, 400_000.0],
                "percentage_covered": [None, None],
                "guarantor": ["GUAR001", "GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 1],
                "pd": [0.01, 0.0001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect().sort("exposure_reference")

        loan_a = df.filter(pl.col("parent_exposure_reference") == "LOAN_A")
        loan_b = df.filter(pl.col("parent_exposure_reference") == "LOAN_B")

        # LOAN_A: 200k direct + 200k (50% of 400k facility) = 400k
        assert loan_a["guaranteed_portion"].sum() == pytest.approx(400_000.0, rel=1e-6)
        # LOAN_B: 200k (50% of 400k facility)
        assert loan_b["guaranteed_portion"].sum() == pytest.approx(200_000.0, rel=1e-6)


class TestLoanLevelGuaranteeUnchanged:
    """Existing loan-level guarantee behaviour must not regress."""

    def test_loan_level_guarantee_still_works(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Direct loan-level guarantee should still apply correctly."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "exposure_class": ["CORPORATE"],
                "approach": ["SA"],
                "ead_pre_crm": [1_000_000.0],
                "lgd": [0.45],
                "cqs": [3],
                "product_type": ["LOAN"],
                "drawn_amount": [1_000_000.0],
                "undrawn_amount": [0.0],
                "nominal_amount": [0.0],
                "risk_type": [None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "sovereign"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["loan"],
                "amount_covered": [600_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 1],
                "pd": [0.01, 0.0001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # Splits into guarantor sub-row + remainder
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        rem_row = df.filter(pl.col("exposure_reference").str.ends_with("__REM"))

        assert len(guar_row) == 1
        assert guar_row["guaranteed_portion"][0] == pytest.approx(600_000.0, rel=1e-6)
        assert rem_row["unguaranteed_portion"][0] == pytest.approx(400_000.0, rel=1e-6)
        assert guar_row["post_crm_counterparty_guaranteed"][0] == "GUAR001"

    def test_guarantee_without_beneficiary_type_treated_as_direct(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Guarantees without beneficiary_type should still match by exposure_reference."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "exposure_class": ["CORPORATE"],
                "approach": ["SA"],
                "ead_pre_crm": [1_000_000.0],
                "lgd": [0.45],
                "cqs": [3],
                "product_type": ["LOAN"],
                "drawn_amount": [1_000_000.0],
                "undrawn_amount": [0.0],
                "nominal_amount": [0.0],
                "risk_type": [None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "institution"],
            }
        )

        # No beneficiary_type column — all treated as direct
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [500_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 2],
                "pd": [0.01, 0.001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # Splits into guarantor sub-row + remainder
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert len(guar_row) == 1
        assert guar_row["is_guaranteed"][0] is True
        assert guar_row["guaranteed_portion"][0] == pytest.approx(500_000.0, rel=1e-6)


class TestBasel31FacilityGuarantee:
    """Facility-level guarantees should work under Basel 3.1 config too."""

    def test_facility_guarantee_applied_under_basel31(
        self,
        crm_processor: CRMProcessor,
        basel31_config: CalculationConfig,
    ) -> None:
        """Facility-level guarantee should apply under Basel 3.1 configuration."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A", "LOAN_B"],
                "counterparty_reference": ["CP001", "CP001"],
                "parent_facility_reference": ["FAC_001", "FAC_001"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach": ["SA", "SA"],
                "ead_pre_crm": [700_000.0, 300_000.0],
                "lgd": [0.45, 0.45],
                "cqs": [3, 3],
                "product_type": ["LOAN", "LOAN"],
                "drawn_amount": [700_000.0, 300_000.0],
                "undrawn_amount": [0.0, 0.0],
                "nominal_amount": [0.0, 0.0],
                "risk_type": [None, None],
            }
        )

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "entity_type": ["corporate", "sovereign"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["FAC_001"],
                "beneficiary_type": ["facility"],
                "amount_covered": [500_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001"],
                "cqs": [3, 1],
                "pd": [0.01, 0.0001],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, basel31_config)
        df = result.exposures.collect().sort("exposure_reference")

        loan_a = df.filter(pl.col("parent_exposure_reference") == "LOAN_A")
        loan_b = df.filter(pl.col("parent_exposure_reference") == "LOAN_B")

        # LOAN_A: 700/1000 * 500k = 350k
        assert loan_a["guaranteed_portion"].sum() == pytest.approx(350_000.0, rel=1e-6)
        # LOAN_B: 300/1000 * 500k = 150k
        assert loan_b["guaranteed_portion"].sum() == pytest.approx(150_000.0, rel=1e-6)
