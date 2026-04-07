"""
Unit tests for CRM error propagation (P6.19).

Verifies that CRM processing errors are properly accumulated as
CalculationError objects and propagated through:
- get_crm_adjusted_bundle() → CRMAdjustedBundle.crm_errors
- get_crm_unified_bundle() → CRMAdjustedBundle.crm_errors
- apply_crm() → LazyFrameResult.errors

Why: CRM errors were previously silently discarded — apply_crm() returned
an empty errors list and CRMError objects (now removed) were never converted
to CalculationError. This meant CRM data quality issues were invisible to
callers and the audit trail. See IMPLEMENTATION_PLAN.md P6.19.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_INELIGIBLE_COLLATERAL,
    ERROR_INVALID_GUARANTEE,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.crm.processor import CRMProcessor


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crm_processor() -> CRMProcessor:
    return CRMProcessor()


def _minimal_exposures() -> pl.LazyFrame:
    """Minimal exposure data for CRM processing."""
    return pl.LazyFrame(
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


def _bundle_with_bad_collateral() -> ClassifiedExposuresBundle:
    """Bundle with collateral that is missing required columns."""
    return ClassifiedExposuresBundle(
        all_exposures=_minimal_exposures(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=None,
        equity_exposures=None,
        ciu_holdings=None,
        collateral=pl.LazyFrame({"some_column": [1.0]}),  # missing required cols
        guarantees=None,
        provisions=None,
        counterparty_lookup=None,
    )


def _bundle_with_bad_guarantees() -> ClassifiedExposuresBundle:
    """Bundle with guarantee data that is missing required columns."""
    return ClassifiedExposuresBundle(
        all_exposures=_minimal_exposures(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=None,
        equity_exposures=None,
        ciu_holdings=None,
        collateral=None,
        guarantees=pl.LazyFrame({"some_column": [1.0]}),  # missing required cols
        provisions=None,
        counterparty_lookup=None,
    )


def _bundle_with_no_counterparty_lookup() -> ClassifiedExposuresBundle:
    """Bundle with valid guarantees but missing counterparty lookup."""
    return ClassifiedExposuresBundle(
        all_exposures=_minimal_exposures(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=None,
        equity_exposures=None,
        ciu_holdings=None,
        collateral=None,
        guarantees=pl.LazyFrame({
            "beneficiary_reference": ["EXP001"],
            "amount_covered": [500_000.0],
            "guarantor": ["GUAR001"],
        }),
        provisions=None,
        counterparty_lookup=None,  # missing
    )


def _bundle_no_crm_data() -> ClassifiedExposuresBundle:
    """Bundle with no CRM data — no errors expected."""
    return ClassifiedExposuresBundle(
        all_exposures=_minimal_exposures(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=None,
        equity_exposures=None,
        ciu_holdings=None,
        collateral=None,
        guarantees=None,
        provisions=None,
        counterparty_lookup=None,
    )


class TestCRMErrorPropagationAdjustedBundle:
    """Test errors propagate through get_crm_adjusted_bundle."""

    def test_bad_collateral_emits_warning(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Collateral with missing columns should emit CRM001 warning."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_with_bad_collateral(), crr_config
        )

        assert len(bundle.crm_errors) == 1
        error = bundle.crm_errors[0]
        assert error.code == ERROR_INELIGIBLE_COLLATERAL
        assert error.severity == ErrorSeverity.WARNING
        assert error.category == ErrorCategory.CRM
        assert "missing required columns" in error.message

    def test_bad_guarantees_emits_warning(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Guarantees with missing columns should emit CRM005 warning."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_with_bad_guarantees(), crr_config
        )

        assert len(bundle.crm_errors) == 1
        error = bundle.crm_errors[0]
        assert error.code == ERROR_INVALID_GUARANTEE
        assert error.severity == ErrorSeverity.WARNING
        assert "missing required columns" in error.message

    def test_missing_counterparty_lookup_emits_warning(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Valid guarantees but missing counterparty lookup should emit CRM005."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_with_no_counterparty_lookup(), crr_config
        )

        assert len(bundle.crm_errors) == 1
        error = bundle.crm_errors[0]
        assert error.code == ERROR_INVALID_GUARANTEE
        assert "counterparty lookup is missing" in error.message

    def test_no_crm_data_no_errors(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """No CRM data means no errors."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_no_crm_data(), crr_config
        )

        assert len(bundle.crm_errors) == 0


class TestCRMErrorPropagationUnifiedBundle:
    """Test errors propagate through get_crm_unified_bundle."""

    def test_bad_collateral_emits_warning(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Collateral with missing columns should emit CRM001 warning."""
        bundle = crm_processor.get_crm_unified_bundle(
            _bundle_with_bad_collateral(), crr_config
        )

        assert len(bundle.crm_errors) == 1
        error = bundle.crm_errors[0]
        assert error.code == ERROR_INELIGIBLE_COLLATERAL
        assert error.severity == ErrorSeverity.WARNING
        assert error.category == ErrorCategory.CRM

    def test_bad_guarantees_emits_warning(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Guarantees with missing columns should emit CRM005 warning."""
        bundle = crm_processor.get_crm_unified_bundle(
            _bundle_with_bad_guarantees(), crr_config
        )

        assert len(bundle.crm_errors) == 1
        error = bundle.crm_errors[0]
        assert error.code == ERROR_INVALID_GUARANTEE
        assert "missing required columns" in error.message

    def test_missing_counterparty_lookup_emits_warning(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Valid guarantees but missing counterparty lookup should emit CRM005."""
        bundle = crm_processor.get_crm_unified_bundle(
            _bundle_with_no_counterparty_lookup(), crr_config
        )

        assert len(bundle.crm_errors) == 1
        error = bundle.crm_errors[0]
        assert error.code == ERROR_INVALID_GUARANTEE
        assert "counterparty lookup is missing" in error.message

    def test_no_crm_data_no_errors(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """No CRM data means no errors."""
        bundle = crm_processor.get_crm_unified_bundle(
            _bundle_no_crm_data(), crr_config
        )

        assert len(bundle.crm_errors) == 0


class TestApplyCRMErrorPropagation:
    """Test errors propagate through the apply_crm() interface."""

    def test_apply_crm_propagates_errors(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """apply_crm() should return errors from the CRM bundle."""
        result = crm_processor.apply_crm(
            _bundle_with_bad_collateral(), crr_config
        )

        assert len(result.errors) == 1
        assert result.errors[0].code == ERROR_INELIGIBLE_COLLATERAL
        assert result.errors[0].category == ErrorCategory.CRM

    def test_apply_crm_no_errors_when_clean(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """apply_crm() should return empty errors when no issues."""
        result = crm_processor.apply_crm(
            _bundle_no_crm_data(), crr_config
        )

        assert len(result.errors) == 0

    def test_apply_crm_multiple_errors(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """apply_crm() should propagate multiple errors."""
        # Bundle with both bad collateral and bad guarantees
        bundle = ClassifiedExposuresBundle(
            all_exposures=_minimal_exposures(),
            sa_exposures=pl.LazyFrame(),
            irb_exposures=pl.LazyFrame(),
            slotting_exposures=None,
            equity_exposures=None,
            ciu_holdings=None,
            collateral=pl.LazyFrame({"some_column": [1.0]}),
            guarantees=pl.LazyFrame({"some_column": [1.0]}),
            provisions=None,
            counterparty_lookup=None,
        )

        result = crm_processor.apply_crm(bundle, crr_config)

        assert len(result.errors) == 2
        codes = {e.code for e in result.errors}
        assert ERROR_INELIGIBLE_COLLATERAL in codes
        assert ERROR_INVALID_GUARANTEE in codes


class TestCRMErrorAttributes:
    """Test CRM error attributes are correctly set."""

    def test_collateral_error_has_regulatory_reference(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Collateral errors should reference CRR Art. 223-224."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_with_bad_collateral(), crr_config
        )

        assert bundle.crm_errors[0].regulatory_reference == "CRR Art. 223-224"

    def test_guarantee_error_has_regulatory_reference(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Guarantee errors should reference CRR Art. 213-217."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_with_bad_guarantees(), crr_config
        )

        assert bundle.crm_errors[0].regulatory_reference == "CRR Art. 213-217"

    def test_errors_are_warnings_not_hard_errors(
        self, crm_processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """CRM data issues should be warnings (pipeline continues)."""
        bundle = crm_processor.get_crm_adjusted_bundle(
            _bundle_with_bad_collateral(), crr_config
        )

        assert all(e.severity == ErrorSeverity.WARNING for e in bundle.crm_errors)
