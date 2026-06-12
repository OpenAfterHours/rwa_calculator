"""Branch-path error accumulation — calculators surface warnings via ``errors=``.

Migration Phase 2 (docs/plans/target-architecture-migration.md): the production
pipeline runs ``calculate_branch`` on pre-split frames, but until this change
the SA and IRB branch entry points had no error channel — SA005 (equity in
main table), SA004 (due diligence), and SF001 (SME group aggregation) warnings
were generated only on the legacy bundle path and silently discarded in
production. These tests pin the restored channel per calculator.

References:
- CRR Art. 501 (SF001), PRA PS1/26 Art. 110A (SA004), CRR Art. 133 (SA005)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_DUE_DILIGENCE_NOT_PERFORMED,
    ERROR_EQUITY_IN_MAIN_TABLE,
    ERROR_SME_MISSING_COUNTERPARTY_REF,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _equity_in_main_table_frame() -> pl.LazyFrame:
    """One equity-approach row as routed into the SA branch by the pipeline."""
    return pl.DataFrame(
        {
            "exposure_reference": ["EQ_001"],
            "counterparty_reference": ["CP_001"],
            "exposure_class": ["equity"],
            "approach": ["equity"],
            "ead_final": [1_000_000.0],
            "ead_gross": [1_000_000.0],
            "cqs": [None],
            "cp_entity_type": ["equity"],
            "currency": ["GBP"],
        }
    ).lazy()


def _sa_corporate_frame() -> pl.LazyFrame:
    """Minimal SA corporate row (no due-diligence columns)."""
    return pl.DataFrame(
        {
            "exposure_reference": ["CORP_001"],
            "counterparty_reference": ["CP_001"],
            "exposure_class": ["corporate"],
            "approach": ["standardised"],
            "ead_final": [500_000.0],
            "ead_gross": [500_000.0],
            "cqs": [3],
            "currency": ["GBP"],
        }
    ).lazy()


def _irb_sme_frame_without_group_key() -> pl.LazyFrame:
    """IRB SME row carrying the contract columns the branch reads directly,
    but with neither counterparty nor lending-group key (SF001 trigger)."""
    return pl.DataFrame(
        {
            "exposure_reference": ["SINGLE"],
            "ead_final": [1_000_000.0],
            "pd": [0.01],
            "maturity": [2.5],
            "exposure_class": ["CORPORATE"],
            "seniority": ["senior"],
            "is_sme": [True],
            "lgd": [None],
            "lgd_post_crm": [0.45],
            "purchased_receivables_subtype": [None],
            "sme_size_metric_gbp": [None],
            "is_infrastructure": [False],
            "requires_fi_scalar": [False],
            "has_one_day_maturity_floor": [False],
            "is_defaulted": [False],
            "beel": [0.0],
            "provision_allocated": [0.0],
            "ava_amount": [0.0],
            "other_own_funds_reductions": [0.0],
        },
        schema_overrides={
            "lgd": pl.Float64,
            "purchased_receivables_subtype": pl.String,
            "sme_size_metric_gbp": pl.Float64,
        },
    ).lazy()


def _slotting_sme_frame_without_group_key() -> pl.LazyFrame:
    """Slotting SME row carrying the contract columns the branch reads
    directly, but with neither counterparty nor lending-group key."""
    return pl.DataFrame(
        {
            "exposure_reference": ["SINGLE"],
            "ead_final": [1_000_000.0],
            "approach": ["slotting"],
            "slotting_category": ["STRONG"],
            "is_hvcre": [False],
            "sl_type": ["project_finance"],
            "is_short_maturity": [False],
            "is_pre_operational": [False],
            "is_sme": [True],
            "is_infrastructure": [False],
            "maturity_date": [None],
            "provision_allocated": [0.0],
            "ava_amount": [0.0],
            "other_own_funds_reductions": [0.0],
        },
        schema_overrides={"maturity_date": pl.Date},
    ).lazy()


# ---------------------------------------------------------------------------
# SA — calculate_branch / calculate_unified
# ---------------------------------------------------------------------------


class TestSABranchErrorChannel:
    """SA branch warnings reach the caller-supplied accumulator."""

    def test_sa005_equity_in_main_table_accumulates(self, crr_config: CalculationConfig) -> None:
        errors: list[CalculationError] = []

        SACalculator().calculate_branch(_equity_in_main_table_frame(), crr_config, errors=errors)

        codes = [e.code for e in errors]
        assert ERROR_EQUITY_IN_MAIN_TABLE in codes
        assert all(e.severity == ErrorSeverity.WARNING for e in errors)

    def test_sa004_due_diligence_warning_under_b31(self, b31_config: CalculationConfig) -> None:
        """Frame without due_diligence_performed under B31 warns SA004."""
        errors: list[CalculationError] = []

        SACalculator().calculate_branch(_sa_corporate_frame(), b31_config, errors=errors)

        assert ERROR_DUE_DILIGENCE_NOT_PERFORMED in [e.code for e in errors]

    def test_no_errors_kwarg_still_returns_frame(self, crr_config: CalculationConfig) -> None:
        """The error channel is opt-in — bare calls keep working."""
        result = SACalculator().calculate_branch(_sa_corporate_frame(), crr_config)

        assert isinstance(result, pl.LazyFrame)
        assert result.collect().height == 1

    def test_no_warning_when_no_equity_rows(self, crr_config: CalculationConfig) -> None:
        errors: list[CalculationError] = []

        SACalculator().calculate_branch(_sa_corporate_frame(), crr_config, errors=errors)

        assert ERROR_EQUITY_IN_MAIN_TABLE not in [e.code for e in errors]


class TestSAUnifiedErrorChannel:
    """The output-floor path (calculate_unified) carries the same channel."""

    def test_sa004_due_diligence_warning_on_unified(self, b31_config: CalculationConfig) -> None:
        errors: list[CalculationError] = []

        SACalculator().calculate_unified(_sa_corporate_frame(), b31_config, errors=errors)

        assert ERROR_DUE_DILIGENCE_NOT_PERFORMED in [e.code for e in errors]


# ---------------------------------------------------------------------------
# IRB — calculate_branch
# ---------------------------------------------------------------------------


class TestIRBBranchErrorChannel:
    """IRB branch supporting-factor warnings reach the accumulator."""

    def test_sf001_missing_group_key_accumulates(self, crr_config: CalculationConfig) -> None:
        errors: list[CalculationError] = []

        IRBCalculator().calculate_branch(
            _irb_sme_frame_without_group_key(), crr_config, errors=errors
        )

        assert ERROR_SME_MISSING_COUNTERPARTY_REF in [e.code for e in errors]

    def test_no_errors_kwarg_still_returns_frame(self, crr_config: CalculationConfig) -> None:
        result = IRBCalculator().calculate_branch(_irb_sme_frame_without_group_key(), crr_config)

        assert isinstance(result, pl.LazyFrame)


# ---------------------------------------------------------------------------
# Slotting — calculate_branch (channel pre-existed; pinned here)
# ---------------------------------------------------------------------------


class TestSlottingBranchErrorChannel:
    """Slotting branch supporting-factor warnings reach the accumulator."""

    def test_sf001_missing_group_key_accumulates(self, crr_config: CalculationConfig) -> None:
        errors: list[CalculationError] = []

        SlottingCalculator().calculate_branch(
            _slotting_sme_frame_without_group_key(), crr_config, errors=errors
        )

        assert ERROR_SME_MISSING_COUNTERPARTY_REF in [e.code for e in errors]
