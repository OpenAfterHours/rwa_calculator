"""
Unit tests for multi-guarantor row splitting in CRM processor.

When an exposure has multiple guarantors, each guarantor's covered portion
should be split into a separate sub-row so that downstream SA/IRB calculators
apply the correct risk weight per guarantor.

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


def _make_exposure(
    exposure_reference: str = "EXP001",
    counterparty_reference: str = "CP001",
    ead: float = 150_000.0,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": [exposure_reference],
            "counterparty_reference": [counterparty_reference],
            "parent_facility_reference": ["FAC_001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["SA"],
            "ead_pre_crm": [ead],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            "drawn_amount": [ead],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
        }
    )


class TestMultiGuarantorSplit:
    """When multiple guarantors cover a single exposure, each gets its own sub-row."""

    def test_two_guarantors_partial_coverage(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Exposure 150k (CQS 3), Guarantor 1 covers 100k (CQS 1),
        Guarantor 2 covers 30k (CQS 2). Should produce 3 sub-rows:
        100k guaranteed by G1, 30k guaranteed by G2, 20k remainder.
        """
        # Arrange
        exposures = _make_exposure(ead=150_000.0)

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "entity_type": ["corporate", "corporate", "corporate"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP001"],
                "beneficiary_type": ["loan", "loan"],
                "amount_covered": [100_000.0, 30_000.0],
                "percentage_covered": [None, None],
                "guarantor": ["GUAR001", "GUAR002"],
                "guarantee_reference": ["G_REF_1", "G_REF_2"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "cqs": [3, 1, 2],
                "pd": [0.01, 0.0001, 0.001],
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
        df = result.exposures.collect()

        # Assert: should have 3 sub-rows
        assert len(df) == 3, f"Expected 3 rows (2 guarantors + remainder), got {len(df)}"

        # All sub-rows should link back to the original exposure
        assert (df["parent_exposure_reference"] == "EXP001").all()

        # Guarantor 1 sub-row: 100k guaranteed at CQS 1
        g1_rows = df.filter(pl.col("guarantor_reference") == "GUAR001")
        assert len(g1_rows) == 1
        assert g1_rows["guaranteed_portion"][0] == pytest.approx(100_000.0, rel=1e-6)
        assert g1_rows["guarantor_cqs"][0] == 1

        # Guarantor 2 sub-row: 30k guaranteed at CQS 2
        g2_rows = df.filter(pl.col("guarantor_reference") == "GUAR002")
        assert len(g2_rows) == 1
        assert g2_rows["guaranteed_portion"][0] == pytest.approx(30_000.0, rel=1e-6)
        assert g2_rows["guarantor_cqs"][0] == 2

        # Remainder sub-row: 20k unguaranteed
        remainder_rows = df.filter(pl.col("guaranteed_portion") == 0)
        assert len(remainder_rows) == 1
        assert remainder_rows["unguaranteed_portion"][0] == pytest.approx(20_000.0, rel=1e-6)
        assert remainder_rows["is_guaranteed"][0] is False

    def test_over_coverage_pro_rata_capping(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """When guarantors cover more than EAD, cap pro-rata so total = EAD."""
        # Arrange
        exposures = _make_exposure(ead=100_000.0)

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "entity_type": ["corporate", "sovereign", "institution"],
            }
        )

        # Total coverage = 80k + 60k = 140k > 100k EAD
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP001"],
                "beneficiary_type": ["loan", "loan"],
                "amount_covered": [80_000.0, 60_000.0],
                "percentage_covered": [None, None],
                "guarantor": ["GUAR001", "GUAR002"],
                "guarantee_reference": ["G_REF_1", "G_REF_2"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "cqs": [3, 1, 2],
                "pd": [0.01, 0.0001, 0.001],
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
        df = result.exposures.collect()

        # Total guaranteed should not exceed EAD
        total_guaranteed = df["guaranteed_portion"].sum()
        total_unguaranteed = df["unguaranteed_portion"].sum()
        assert total_guaranteed == pytest.approx(100_000.0, rel=1e-6)
        assert total_unguaranteed == pytest.approx(0.0, abs=1e-6)

        # Pro-rata: GUAR001 gets 80/140 * 100k, GUAR002 gets 60/140 * 100k
        g1_rows = df.filter(pl.col("guarantor_reference") == "GUAR001")
        g2_rows = df.filter(pl.col("guarantor_reference") == "GUAR002")
        assert g1_rows["guaranteed_portion"][0] == pytest.approx(
            80_000 / 140_000 * 100_000, rel=1e-6
        )
        assert g2_rows["guaranteed_portion"][0] == pytest.approx(
            60_000 / 140_000 * 100_000, rel=1e-6
        )

    def test_single_guarantor_splits_into_two_rows(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Single guarantor should produce 2 sub-rows: guaranteed + remainder."""
        # Arrange
        exposures = _make_exposure(ead=150_000.0)

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
                "amount_covered": [100_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
                "guarantee_reference": ["G_REF_1"],
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
        df = result.exposures.collect()

        # Assert: 2 rows (1 guarantor + remainder)
        assert len(df) == 2, f"Expected 2 rows (guarantor + remainder), got {len(df)}"

        # Both sub-rows link back to the original exposure
        assert (df["parent_exposure_reference"] == "EXP001").all()

        # Guarantor sub-row: 100k guaranteed
        g_rows = df.filter(pl.col("guarantor_reference") == "GUAR001")
        assert len(g_rows) == 1
        assert g_rows["exposure_reference"][0] == "EXP001__G_GUAR001"
        assert g_rows["guaranteed_portion"][0] == pytest.approx(100_000.0, rel=1e-6)
        assert g_rows["unguaranteed_portion"][0] == pytest.approx(0.0, abs=1e-6)

        # Remainder sub-row: 50k unguaranteed
        rem_rows = df.filter(pl.col("exposure_reference").str.ends_with("__REM"))
        assert len(rem_rows) == 1
        assert rem_rows["guaranteed_portion"][0] == pytest.approx(0.0, abs=1e-6)
        assert rem_rows["unguaranteed_portion"][0] == pytest.approx(50_000.0, rel=1e-6)

        # Total EAD sums to original
        assert df["ead_final"].sum() == pytest.approx(150_000.0, rel=1e-6)

    def test_no_guarantors_unchanged(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposures without guarantees should pass through unchanged."""
        # Arrange
        exposures = _make_exposure(ead=150_000.0)

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
            }
        )

        # Empty guarantees
        guarantees = pl.LazyFrame(
            schema={
                "beneficiary_reference": pl.String,
                "beneficiary_type": pl.String,
                "amount_covered": pl.Float64,
                "percentage_covered": pl.Float64,
                "guarantor": pl.String,
                "guarantee_reference": pl.String,
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(counterparties),
        )

        # Act
        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # Assert: single row unchanged
        assert len(df) == 1
        assert df["exposure_reference"][0] == "EXP001"

    def test_multi_guarantor_ead_columns_split_proportionally(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Sub-row EAD columns should sum to the original exposure's EAD."""
        # Arrange
        exposures = _make_exposure(ead=150_000.0)

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "entity_type": ["corporate", "corporate", "corporate"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP001"],
                "beneficiary_type": ["loan", "loan"],
                "amount_covered": [100_000.0, 30_000.0],
                "percentage_covered": [None, None],
                "guarantor": ["GUAR001", "GUAR002"],
                "guarantee_reference": ["G_REF_1", "G_REF_2"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "cqs": [3, 1, 2],
                "pd": [0.01, 0.0001, 0.001],
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
        df = result.exposures.collect()

        # Assert: total ead_final across sub-rows should equal original EAD
        assert df["ead_final"].sum() == pytest.approx(150_000.0, rel=1e-6)

    def test_multi_guarantor_post_crm_counterparty(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Each guarantor sub-row should report the correct post-CRM counterparty."""
        # Arrange
        exposures = _make_exposure(ead=150_000.0)

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "entity_type": ["corporate", "corporate", "corporate"],
            }
        )

        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP001"],
                "beneficiary_type": ["loan", "loan"],
                "amount_covered": [100_000.0, 30_000.0],
                "percentage_covered": [None, None],
                "guarantor": ["GUAR001", "GUAR002"],
                "guarantee_reference": ["G_REF_1", "G_REF_2"],
            }
        )

        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR001", "GUAR002"],
                "cqs": [3, 1, 2],
                "pd": [0.01, 0.0001, 0.001],
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
        df = result.exposures.collect()

        # Assert: each guarantor sub-row has the correct post-CRM counterparty
        g1_rows = df.filter(pl.col("guarantor_reference") == "GUAR001")
        assert g1_rows["post_crm_counterparty_guaranteed"][0] == "GUAR001"

        g2_rows = df.filter(pl.col("guarantor_reference") == "GUAR002")
        assert g2_rows["post_crm_counterparty_guaranteed"][0] == "GUAR002"

        # Remainder has original counterparty
        remainder = df.filter(pl.col("guaranteed_portion") == 0)
        assert remainder["post_crm_counterparty_guaranteed"][0] == "CP001"
