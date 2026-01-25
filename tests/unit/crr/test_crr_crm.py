"""Unit tests for the CRM (Credit Risk Mitigation) processor module.

Tests cover:
- Collateral haircut application
- CRM processor pipeline
- Guarantee processing (placeholder)
- Provision deduction (placeholder)

Note: CCF tests are in tests/unit/test_ccf.py as CCF is part of
exposure measurement, not credit risk mitigation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.crm import (
    CRMProcessor,
    HaircutCalculator,
    create_crm_processor,
    create_haircut_calculator,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crm_processor() -> CRMProcessor:
    """Return a CRMProcessor instance."""
    return CRMProcessor()


@pytest.fixture
def haircut_calculator() -> HaircutCalculator:
    """Return a HaircutCalculator instance."""
    return HaircutCalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crr_config_with_irb() -> CalculationConfig:
    """Return a CRR configuration with full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def basic_exposures() -> pl.LazyFrame:
    """Basic exposures for CRM testing."""
    return pl.DataFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003", "EXP004"],
        "exposure_type": ["loan", "loan", "contingent", "contingent"],
        "product_type": ["TERM_LOAN", "MORTGAGE", "LC", "GUARANTEE"],
        "book_code": ["CORP", "RETAIL", "CORP", "CORP"],
        "counterparty_reference": ["CP001", "CP002", "CP003", "CP004"],
        "value_date": [date(2023, 1, 1)] * 4,
        "maturity_date": [date(2028, 1, 1)] * 4,
        "currency": ["GBP", "GBP", "GBP", "GBP"],
        "drawn_amount": [1000000.0, 500000.0, 0.0, 0.0],
        "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
        "nominal_amount": [0.0, 0.0, 500000.0, 250000.0],
        "lgd": [0.45, 0.15, 0.45, 0.45],
        "seniority": ["senior", "senior", "senior", "senior"],
        "risk_type": [None, None, "MR", "FR"],  # MR = 50% CCF, FR = 100% CCF
        "approach": ["standardised", "standardised", "standardised", "standardised"],
        "exposure_class": ["corporate", "retail_mortgage", "corporate", "corporate"],
        "is_sme": [False, False, False, False],
        "is_mortgage": [False, True, False, False],
        "is_defaulted": [False, False, False, False],
        "qualifies_as_retail": [False, True, False, False],
        "exposure_class_for_sa": ["corporate", "retail_mortgage", "corporate", "corporate"],
        "firb_permitted": [False, False, False, False],
        "airb_permitted": [False, False, False, False],
        "classification_reason": ["test"] * 4,
    }).lazy()


@pytest.fixture
def basic_collateral() -> pl.LazyFrame:
    """Basic collateral for haircut testing."""
    return pl.DataFrame({
        "collateral_reference": ["COLL001", "COLL002", "COLL003", "COLL004"],
        "collateral_type": ["cash", "govt_bond", "equity", "corp_bond"],
        "currency": ["GBP", "GBP", "GBP", "EUR"],  # EUR = FX mismatch
        "maturity_date": [None, date(2026, 6, 30), None, date(2027, 12, 31)],
        "market_value": [500000.0, 600000.0, 400000.0, 300000.0],
        "nominal_value": [500000.0, 600000.0, 400000.0, 300000.0],
        "beneficiary_type": ["loan", "loan", "loan", "loan"],
        "beneficiary_reference": ["EXP001", "EXP001", "EXP002", "EXP003"],
        "issuer_cqs": [None, 1, None, 2],
        "issuer_type": [None, "sovereign", None, "corporate"],
        "residual_maturity_years": [None, 2.5, None, 3.0],
        "is_eligible_financial_collateral": [True, True, True, True],
        "is_eligible_irb_collateral": [True, True, True, True],
    }).lazy()


def create_classified_bundle(
    exposures: pl.LazyFrame,
) -> ClassifiedExposuresBundle:
    """Helper to create a ClassifiedExposuresBundle for testing."""
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=exposures.filter(pl.col("approach") == ApproachType.SA.value),
        irb_exposures=exposures.filter(
            (pl.col("approach") == ApproachType.FIRB.value) |
            (pl.col("approach") == ApproachType.AIRB.value)
        ),
        slotting_exposures=None,
        equity_exposures=None,
        classification_audit=None,
        classification_errors=[],
    )


# =============================================================================
# Haircut Calculator Tests (CRR Art. 224)
# =============================================================================


class TestHaircutCalculator:
    """Tests for collateral haircut calculation."""

    def test_cash_zero_haircut(
        self,
        haircut_calculator: HaircutCalculator,
    ) -> None:
        """Cash collateral should have 0% haircut."""
        result = haircut_calculator.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("500000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )

        assert result.collateral_haircut == Decimal("0.00")
        assert result.adjusted_value == Decimal("500000")

    def test_gold_15_percent_haircut(
        self,
        haircut_calculator: HaircutCalculator,
    ) -> None:
        """Gold should have 15% haircut."""
        result = haircut_calculator.calculate_single_haircut(
            collateral_type="gold",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )

        assert result.collateral_haircut == Decimal("0.15")
        assert result.adjusted_value == Decimal("85000")

    def test_govt_bond_cqs1_haircut_by_maturity(
        self,
        haircut_calculator: HaircutCalculator,
    ) -> None:
        """Government bonds CQS1 should have maturity-based haircuts."""
        # 0-1 year maturity: 0.5%
        result_short = haircut_calculator.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=0.5,
        )
        assert result_short.collateral_haircut == Decimal("0.005")

        # 1-5 year maturity: 2%
        result_medium = haircut_calculator.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=3.0,
        )
        assert result_medium.collateral_haircut == Decimal("0.02")

        # 5+ year maturity: 4%
        result_long = haircut_calculator.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=7.0,
        )
        assert result_long.collateral_haircut == Decimal("0.04")

    def test_fx_mismatch_adds_8_percent(
        self,
        haircut_calculator: HaircutCalculator,
    ) -> None:
        """FX mismatch should add 8% haircut."""
        # Same currency - no FX haircut
        result_same = haircut_calculator.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result_same.fx_haircut == Decimal("0.00")

        # Different currency - 8% FX haircut
        result_diff = haircut_calculator.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("100000"),
            collateral_currency="EUR",
            exposure_currency="GBP",
        )
        assert result_diff.fx_haircut == Decimal("0.08")
        # Adjusted = 100k * (1 - 0 - 0.08) = 92k
        assert result_diff.adjusted_value == Decimal("92000")

    def test_equity_main_index_15_percent(
        self,
        haircut_calculator: HaircutCalculator,
    ) -> None:
        """Main index equity should have 15% haircut."""
        result = haircut_calculator.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("200000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
        )

        assert result.collateral_haircut == Decimal("0.15")
        # Adjusted = 200k * (1 - 0.15) = 170k
        assert result.adjusted_value == Decimal("170000")

    def test_equity_other_25_percent(
        self,
        haircut_calculator: HaircutCalculator,
    ) -> None:
        """Non-index equity should have 25% haircut."""
        result = haircut_calculator.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("200000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=False,
        )

        assert result.collateral_haircut == Decimal("0.25")
        # Adjusted = 200k * (1 - 0.25) = 150k
        assert result.adjusted_value == Decimal("150000")


# =============================================================================
# CRM Processor Tests
# =============================================================================


class TestCRMProcessor:
    """Tests for the full CRM processor."""

    def test_apply_crm_returns_bundle(
        self,
        crm_processor: CRMProcessor,
        basic_exposures: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_crm should return LazyFrameResult."""
        bundle = create_classified_bundle(basic_exposures)
        result = crm_processor.apply_crm(bundle, crr_config)

        assert result.frame is not None
        assert isinstance(result.errors, list)

    def test_get_crm_adjusted_bundle_returns_bundle(
        self,
        crm_processor: CRMProcessor,
        basic_exposures: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """get_crm_adjusted_bundle should return CRMAdjustedBundle."""
        bundle = create_classified_bundle(basic_exposures)
        result = crm_processor.get_crm_adjusted_bundle(bundle, crr_config)

        assert result.exposures is not None
        assert result.sa_exposures is not None
        assert result.irb_exposures is not None

    def test_loan_ead_equals_drawn_amount(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Loan EAD should equal drawn amount (no CCF for drawn items)."""
        exposures = pl.DataFrame({
            "exposure_reference": ["LOAN001"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "drawn_amount": [1000000.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "risk_type": [None],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
            "is_sme": [False],
            "is_mortgage": [False],
            "is_defaulted": [False],
            "qualifies_as_retail": [False],
            "exposure_class_for_sa": ["corporate"],
            "firb_permitted": [False],
            "airb_permitted": [False],
            "classification_reason": ["test"],
        }).lazy()

        bundle = create_classified_bundle(exposures)
        result = crm_processor.get_crm_adjusted_bundle(bundle, crr_config)

        df = result.exposures.collect()
        assert df["ead_gross"][0] == pytest.approx(1000000.0)
        assert df["ead_final"][0] == pytest.approx(1000000.0)

    def test_contingent_ead_includes_ccf(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Contingent EAD should apply CCF to nominal amount."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CONT001"],
            "exposure_type": ["contingent"],
            "product_type": ["LC"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "drawn_amount": [0.0],
            "nominal_amount": [500000.0],
            "lgd": [0.45],
            "risk_type": ["MR"],  # MR = 50% CCF
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
            "is_sme": [False],
            "is_mortgage": [False],
            "is_defaulted": [False],
            "qualifies_as_retail": [False],
            "exposure_class_for_sa": ["corporate"],
            "firb_permitted": [False],
            "airb_permitted": [False],
            "classification_reason": ["test"],
        }).lazy()

        bundle = create_classified_bundle(exposures)
        result = crm_processor.get_crm_adjusted_bundle(bundle, crr_config)

        df = result.exposures.collect()
        # EAD = nominal * CCF = 500k * 0.5 = 250k
        assert df["ead_gross"][0] == pytest.approx(250000.0)

    def test_crm_audit_trail_populated(
        self,
        crm_processor: CRMProcessor,
        basic_exposures: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """CRM audit trail should be populated."""
        bundle = create_classified_bundle(basic_exposures)
        result = crm_processor.get_crm_adjusted_bundle(bundle, crr_config)

        audit_df = result.crm_audit.collect()

        assert "exposure_reference" in audit_df.columns
        assert "ead_gross" in audit_df.columns
        assert "ead_final" in audit_df.columns
        assert "crm_calculation" in audit_df.columns

    def test_sa_irb_split_correct(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposures should be correctly split into SA and IRB."""
        exposures = pl.DataFrame({
            "exposure_reference": ["SA001", "SA002"],
            "exposure_type": ["loan", "loan"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP002"],
            "drawn_amount": [1000000.0, 500000.0],
            "nominal_amount": [0.0, 0.0],
            "lgd": [0.45, 0.45],
            "risk_type": [None, None],
            "approach": ["standardised", "standardised"],
            "exposure_class": ["corporate", "corporate"],
            "is_sme": [False, False],
            "is_mortgage": [False, False],
            "is_defaulted": [False, False],
            "qualifies_as_retail": [False, False],
            "exposure_class_for_sa": ["corporate", "corporate"],
            "firb_permitted": [False, False],
            "airb_permitted": [False, False],
            "classification_reason": ["test", "test"],
        }).lazy()

        bundle = create_classified_bundle(exposures)
        result = crm_processor.get_crm_adjusted_bundle(bundle, crr_config)

        sa_df = result.sa_exposures.collect()
        irb_df = result.irb_exposures.collect()

        assert len(sa_df) == 2
        assert len(irb_df) == 0  # SA-only config


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCRMFactoryFunctions:
    """Tests for CRM factory functions."""

    def test_create_crm_processor(self) -> None:
        """Factory should create CRMProcessor."""
        processor = create_crm_processor()
        assert isinstance(processor, CRMProcessor)

    def test_create_haircut_calculator(self) -> None:
        """Factory should create HaircutCalculator."""
        calculator = create_haircut_calculator()
        assert isinstance(calculator, HaircutCalculator)


# =============================================================================
# Integration Tests
# =============================================================================


class TestCRMIntegration:
    """Integration tests for CRM processing."""

    def test_mixed_exposure_types(
        self,
        crm_processor: CRMProcessor,
        basic_exposures: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Mixed loans and contingents should be processed correctly."""
        bundle = create_classified_bundle(basic_exposures)
        result = crm_processor.get_crm_adjusted_bundle(bundle, crr_config)

        df = result.exposures.collect()

        # Loans should have EAD = drawn amount
        loan1 = df.filter(pl.col("exposure_reference") == "EXP001")
        assert loan1["ead_gross"][0] == pytest.approx(1000000.0)

        loan2 = df.filter(pl.col("exposure_reference") == "EXP002")
        assert loan2["ead_gross"][0] == pytest.approx(500000.0)

        # Contingents should have CCF applied
        cont1 = df.filter(pl.col("exposure_reference") == "EXP003")
        # 500k * 50% = 250k
        assert cont1["ead_gross"][0] == pytest.approx(250000.0)

        cont2 = df.filter(pl.col("exposure_reference") == "EXP004")
        # 250k * 100% = 250k
        assert cont2["ead_gross"][0] == pytest.approx(250000.0)
