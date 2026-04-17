"""
Unit tests for CDS restructuring exclusion haircut (Art. 233(2)).

When a credit derivative does not include restructuring as a credit event,
the protection value is reduced by 40% (capped at 60% of exposure value).
Regular guarantees are unaffected. Null includes_restructuring defaults to
True (no haircut) for backward compatibility.

References:
    CRR Art. 233(2): CDS restructuring exclusion
    PRA PS1/26 Art. 233(2): Same treatment under Basel 3.1
    Art. 216(1): Credit events for credit derivatives
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


def _make_exposure(
    ref: str = "LOAN_A",
    ead: float = 1_000_000.0,
    currency: str = "GBP",
) -> pl.LazyFrame:
    """Build a minimal SA exposure for guarantee testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [ref],
            "counterparty_reference": ["CP001"],
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
            "currency": [currency],
        }
    )


def _make_credit_derivative(
    beneficiary: str = "LOAN_A",
    guarantor: str = "GUAR001",
    amount: float = 500_000.0,
    currency: str = "GBP",
    includes_restructuring: bool | None = None,
) -> pl.LazyFrame:
    """Build a credit derivative guarantee with restructuring flag."""
    return pl.LazyFrame(
        {
            "beneficiary_reference": [beneficiary],
            "beneficiary_type": ["loan"],
            "amount_covered": [amount],
            "percentage_covered": [None],
            "guarantor": [guarantor],
            "guarantee_reference": [f"CDS_REF_{guarantor}"],
            "currency": [currency],
            "protection_type": ["credit_derivative"],
            "includes_restructuring": [includes_restructuring],
        }
    )


def _make_guarantee(
    beneficiary: str = "LOAN_A",
    guarantor: str = "GUAR001",
    amount: float = 500_000.0,
    currency: str = "GBP",
    includes_restructuring: bool | None = None,
) -> pl.LazyFrame:
    """Build a regular guarantee with optional restructuring flag."""
    return pl.LazyFrame(
        {
            "beneficiary_reference": [beneficiary],
            "beneficiary_type": ["loan"],
            "amount_covered": [amount],
            "percentage_covered": [None],
            "guarantor": [guarantor],
            "guarantee_reference": [f"GUAR_REF_{guarantor}"],
            "currency": [currency],
            "protection_type": ["guarantee"],
            "includes_restructuring": [includes_restructuring],
        }
    )


def _default_counterparties() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": ["CP001", "GUAR001"],
            "entity_type": ["corporate", "sovereign"],
        }
    )


def _default_rating_inheritance() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": ["CP001", "GUAR001"],
            "cqs": [3, 1],
            "pd": [0.01, 0.0001],
        }
    )


def _run_crm(
    crm_processor: CRMProcessor,
    config: CalculationConfig,
    exposures: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    counterparties: pl.LazyFrame | None = None,
    rating_inheritance: pl.LazyFrame | None = None,
) -> pl.DataFrame:
    """Helper: run CRM pipeline and collect results."""
    if counterparties is None:
        counterparties = _default_counterparties()
    if rating_inheritance is None:
        rating_inheritance = _default_rating_inheritance()

    classified_bundle = ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=exposures,
        irb_exposures=pl.LazyFrame(),
        guarantees=guarantees,
        counterparty_lookup=_counterparty_lookup(counterparties, rating_inheritance),
    )

    result = crm_processor.get_crm_adjusted_bundle(classified_bundle, config)
    collected = result.exposures.collect()
    assert isinstance(collected, pl.DataFrame)
    return collected


class TestCDSRestructuringExclusionHaircut:
    """Art. 233(2): CDS without restructuring → 40% reduction in protection."""

    def test_cds_without_restructuring_reduces_guaranteed_portion(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """CDS excluding restructuring → guaranteed_portion reduced by 40%."""
        exposures = _make_exposure()
        guarantees = _make_credit_derivative(amount=500_000.0, includes_restructuring=False)

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # G* = 500,000 × (1 - 0.40) = 300,000
        assert df["guaranteed_portion"].sum() == pytest.approx(300_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(700_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.40, rel=1e-6)

    def test_cds_with_restructuring_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """CDS including restructuring → no reduction applied."""
        exposures = _make_exposure()
        guarantees = _make_credit_derivative(amount=500_000.0, includes_restructuring=True)

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        assert df["guaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_regular_guarantee_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Regular guarantee (not credit derivative) → no restructuring haircut."""
        exposures = _make_exposure()
        guarantees = _make_guarantee(amount=500_000.0, includes_restructuring=False)

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # Restructuring exclusion only applies to credit derivatives
        assert df["guaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_null_includes_restructuring_defaults_to_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Null includes_restructuring → assumes restructuring IS included (no haircut)."""
        exposures = _make_exposure()
        guarantees = _make_credit_derivative(amount=500_000.0, includes_restructuring=None)

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # Null defaults to True → no haircut applied
        assert df["guaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_missing_includes_restructuring_column_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Guarantee data without includes_restructuring column → backward compatible."""
        exposures = _make_exposure()
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["LOAN_A"],
                "beneficiary_type": ["loan"],
                "amount_covered": [500_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
                "guarantee_reference": ["CDS_REF_001"],
                "currency": ["GBP"],
                "protection_type": ["credit_derivative"],
                # No includes_restructuring column
            }
        )

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # Without the column, no haircut applied (backward compatible)
        assert df["guaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_full_cds_coverage_without_restructuring(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Full CDS coverage without restructuring → capped at 60% of EAD."""
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead)
        guarantees = _make_credit_derivative(amount=ead, includes_restructuring=False)

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # Full CDS: 1M capped at EAD, then reduced to 60%: 1M × 0.60 = 600k
        assert df["guaranteed_portion"].sum() == pytest.approx(600_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(400_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.40, rel=1e-6)

    def test_cds_without_restructuring_rwa_impact(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Verify RWA correctness: 40% reduction means more unguaranteed EAD."""
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead)
        guarantees = _make_credit_derivative(amount=ead, includes_restructuring=False)

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # Guaranteed: 600k at guarantor RW; Unguaranteed: 400k at borrower RW
        guaranteed = df["guaranteed_portion"].sum()
        unguaranteed = df["unguaranteed_portion"].sum()
        assert guaranteed + unguaranteed == pytest.approx(ead, rel=1e-6)

    def test_cds_without_restructuring_under_basel31(
        self,
        crm_processor: CRMProcessor,
        basel31_config: CalculationConfig,
    ) -> None:
        """40% restructuring exclusion applies identically under Basel 3.1."""
        exposures = _make_exposure()
        guarantees = _make_credit_derivative(amount=500_000.0, includes_restructuring=False)

        df = _run_crm(crm_processor, basel31_config, exposures, guarantees)

        # Same 40% haircut under Basel 3.1
        assert df["guaranteed_portion"].sum() == pytest.approx(300_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.40, rel=1e-6)


class TestCombinedFXAndRestructuringHaircuts:
    """Both FX mismatch and restructuring exclusion haircuts applied together."""

    def test_both_fx_and_restructuring_haircuts_compound(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Cross-currency CDS without restructuring → both haircuts compound."""
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead, currency="GBP")
        guarantees = _make_credit_derivative(
            amount=500_000.0, currency="EUR", includes_restructuring=False
        )

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # FX first: 500k × (1 - 0.08) = 460k
        # Then restructuring: 460k × (1 - 0.40) = 276k
        assert df["guaranteed_portion"].sum() == pytest.approx(276_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(724_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.40, rel=1e-6)

    def test_fx_haircut_only_when_restructuring_included(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Cross-currency CDS with restructuring → only FX haircut."""
        exposures = _make_exposure(currency="GBP")
        guarantees = _make_credit_derivative(
            amount=500_000.0, currency="EUR", includes_restructuring=True
        )

        df = _run_crm(crm_processor, crr_config, exposures, guarantees)

        # Only FX haircut: 500k × 0.92 = 460k
        assert df["guaranteed_portion"].sum() == pytest.approx(460_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)
        assert guar_row["guarantee_restructuring_haircut"][0] == pytest.approx(0.0, rel=1e-6)


class TestNoGuaranteeRestructuringColumn:
    """Exposure with no guarantee → restructuring haircut column present and zero."""

    def test_no_guarantee_has_zero_restructuring_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposure with no guarantee → guarantee_restructuring_haircut = 0."""
        exposures = _make_exposure()

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=None,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        assert df["guarantee_restructuring_haircut"][0] == pytest.approx(0.0, rel=1e-6)


class TestRestructuringHaircutConstant:
    """Verify the RESTRUCTURING_EXCLUSION_HAIRCUT constant value."""

    def test_constant_value(self) -> None:
        from decimal import Decimal

        from rwa_calc.data.tables.haircuts import RESTRUCTURING_EXCLUSION_HAIRCUT

        assert Decimal("0.40") == RESTRUCTURING_EXCLUSION_HAIRCUT
