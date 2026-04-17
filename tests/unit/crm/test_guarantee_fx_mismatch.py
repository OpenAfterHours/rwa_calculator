"""
Unit tests for FX mismatch haircut on guarantees (Art. 233(3-4)).

When a guarantee or credit derivative is denominated in a different currency
from the exposure, the guaranteed amount is reduced: G* = G × (1 − H_fx)
where H_fx = 8% (Art. 224 Table 4, 10-day liquidation period).

References:
    CRR Art. 233(3-4): FX mismatch haircut for unfunded credit protection
    PRA PS1/26 Art. 233(3-4): Same treatment under Basel 3.1
    Art. 224 Table 4: H_fx = 8% at 10-day liquidation period
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


def _make_guarantee(
    beneficiary: str = "LOAN_A",
    guarantor: str = "GUAR001",
    amount: float = 500_000.0,
    currency: str = "GBP",
) -> pl.LazyFrame:
    """Build a guarantee with specified currency."""
    return pl.LazyFrame(
        {
            "beneficiary_reference": [beneficiary],
            "beneficiary_type": ["loan"],
            "amount_covered": [amount],
            "percentage_covered": [None],
            "guarantor": [guarantor],
            "guarantee_reference": [f"GUAR_REF_{guarantor}"],
            "currency": [currency],
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


class TestGuaranteeFXMismatchHaircut:
    """Art. 233(3-4): FX mismatch haircut reduces guaranteed portion by 8%."""

    def test_cross_currency_guarantee_reduces_guaranteed_portion(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """EUR guarantee on GBP exposure → guaranteed_portion reduced by 8%."""
        exposures = _make_exposure(currency="GBP")
        guarantees = _make_guarantee(amount=500_000.0, currency="EUR")

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # G* = 500,000 × (1 - 0.08) = 460,000
        assert df["guaranteed_portion"].sum() == pytest.approx(460_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(540_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)

    def test_same_currency_guarantee_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """GBP guarantee on GBP exposure → no FX haircut applied."""
        exposures = _make_exposure(currency="GBP")
        guarantees = _make_guarantee(amount=500_000.0, currency="GBP")

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        assert df["guaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(500_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_fx_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_no_guarantee_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposure with no guarantee → guarantee_fx_haircut = 0."""
        exposures = _make_exposure(currency="GBP")

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

        assert df["guaranteed_portion"][0] == pytest.approx(0.0, rel=1e-6)
        assert df["guarantee_fx_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_full_guarantee_cross_currency(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Full guarantee in different currency → 8% of exposure becomes unguaranteed."""
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead, currency="GBP")
        guarantees = _make_guarantee(amount=ead, currency="USD")

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # Full guarantee capped at EAD, then reduced by 8%
        # G* = 1,000,000 × (1 - 0.08) = 920,000
        assert df["guaranteed_portion"].sum() == pytest.approx(920_000.0, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(80_000.0, rel=1e-6)

    def test_large_guarantee_cross_currency_still_fully_covers(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Guarantee >> EAD with FX mismatch: haircut on G, then cap at EAD.

        Art. 233/235: G* = G × (1 - H_fx) = 200M × 0.92 = 184M.
        Since 184M > 1M EAD, guaranteed_portion = 1M (fully covered).

        Previously the code applied haircut AFTER capping, yielding
        1M × 0.92 = 920K (incorrectly reducing coverage).
        """
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead, currency="GBP")
        # Guarantee vastly exceeds exposure — should still fully cover after haircut
        guarantees = _make_guarantee(amount=200_000_000.0, currency="EUR")

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # G* = 200M × 0.92 = 184M → min(184M, 1M) = 1M (fully covered)
        assert df["guaranteed_portion"].sum() == pytest.approx(ead, rel=1e-6)
        assert df["unguaranteed_portion"].sum() == pytest.approx(0.0, abs=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)

    def test_cross_currency_guarantee_under_basel31(
        self,
        crm_processor: CRMProcessor,
        basel31_config: CalculationConfig,
    ) -> None:
        """FX haircut applies identically under Basel 3.1 (8% unchanged)."""
        exposures = _make_exposure(currency="GBP")
        guarantees = _make_guarantee(amount=500_000.0, currency="EUR")

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, basel31_config)
        df = result.exposures.collect()

        # Same 8% haircut under Basel 3.1
        assert df["guaranteed_portion"].sum() == pytest.approx(460_000.0, rel=1e-6)
        guar_row = df.filter(pl.col("guaranteed_portion") > 0)
        assert guar_row["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)

    def test_guarantee_without_currency_no_haircut(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Guarantee with no currency column → conservative: no haircut applied."""
        exposures = _make_exposure(currency="GBP")
        # Build guarantee without currency column (backward compatibility)
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["LOAN_A"],
                "beneficiary_type": ["loan"],
                "amount_covered": [500_000.0],
                "percentage_covered": [None],
                "guarantor": ["GUAR001"],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # No currency on guarantee → guarantee_currency is null → no haircut
        assert df["guaranteed_portion"][0] == pytest.approx(500_000.0, rel=1e-6)
        assert df["guarantee_fx_haircut"][0] == pytest.approx(0.0, rel=1e-6)

    def test_percentage_covered_cross_currency(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Percentage-based guarantee with FX mismatch → haircut applied."""
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead, currency="GBP")
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["LOAN_A"],
                "beneficiary_type": ["loan"],
                "amount_covered": [0.0],
                "percentage_covered": [0.50],  # 50% coverage
                "guarantor": ["GUAR001"],
                "guarantee_reference": ["GUAR_REF_001"],
                "currency": ["EUR"],
            }
        )

        classified_bundle = ClassifiedExposuresBundle(
            all_exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
            guarantees=guarantees,
            counterparty_lookup=_counterparty_lookup(
                _default_counterparties(), _default_rating_inheritance()
            ),
        )

        result = crm_processor.get_crm_adjusted_bundle(classified_bundle, crr_config)
        df = result.exposures.collect()

        # 50% of 1M = 500k, then reduced by 8%: 500k × 0.92 = 460k
        assert df["guaranteed_portion"][0] == pytest.approx(460_000.0, rel=1e-6)
        assert df["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)


class TestMultiGuarantorFXMismatch:
    """FX mismatch with multiple guarantors in different currencies."""

    def test_mixed_currency_guarantors(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Two guarantors: one same currency, one cross-currency."""
        ead = 1_000_000.0
        exposures = _make_exposure(ead=ead, currency="GBP")

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR_GBP", "GUAR_EUR"],
                "entity_type": ["corporate", "sovereign", "sovereign"],
            }
        )
        rating_inheritance = pl.LazyFrame(
            {
                "counterparty_reference": ["CP001", "GUAR_GBP", "GUAR_EUR"],
                "cqs": [3, 1, 1],
                "pd": [0.01, 0.0001, 0.0001],
            }
        )

        # Two guarantors: 300k GBP (same ccy) + 400k EUR (cross ccy)
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["LOAN_A", "LOAN_A"],
                "beneficiary_type": ["loan", "loan"],
                "amount_covered": [300_000.0, 400_000.0],
                "percentage_covered": [None, None],
                "guarantor": ["GUAR_GBP", "GUAR_EUR"],
                "guarantee_reference": ["GUAR_REF_GBP", "GUAR_REF_EUR"],
                "currency": ["GBP", "EUR"],
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

        # Multi-guarantor split produces: LOAN_A__G_GUAR_EUR, LOAN_A__G_GUAR_GBP, LOAN_A__REM
        eur_row = df.filter(pl.col("exposure_reference") == "LOAN_A__G_GUAR_EUR")
        gbp_row = df.filter(pl.col("exposure_reference") == "LOAN_A__G_GUAR_GBP")
        rem_row = df.filter(pl.col("exposure_reference") == "LOAN_A__REM")

        # EUR guarantor: haircut applied before split → 400k × 0.92 = 368k
        # Sub-row EAD = 368k, fully covered by guarantor
        assert eur_row["guaranteed_portion"][0] == pytest.approx(368_000.0, rel=1e-6)
        assert eur_row["unguaranteed_portion"][0] == pytest.approx(0.0, rel=1e-6)
        assert eur_row["guarantee_fx_haircut"][0] == pytest.approx(0.08, rel=1e-6)

        # GBP guarantor: same currency → 300k guaranteed, 0 unguaranteed
        assert gbp_row["guaranteed_portion"][0] == pytest.approx(300_000.0, rel=1e-6)
        assert gbp_row["unguaranteed_portion"][0] == pytest.approx(0.0, rel=1e-6)
        assert gbp_row["guarantee_fx_haircut"][0] == pytest.approx(0.0, rel=1e-6)

        # Remainder: 1M - 368k - 300k = 332k (includes 32k from FX haircut)
        assert rem_row["guaranteed_portion"][0] == pytest.approx(0.0, rel=1e-6)
        assert rem_row["unguaranteed_portion"][0] == pytest.approx(332_000.0, rel=1e-6)
        assert rem_row["guarantee_fx_haircut"][0] == pytest.approx(0.0, rel=1e-6)
