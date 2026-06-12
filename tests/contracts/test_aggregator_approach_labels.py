"""
Contract tests: aggregator approach-label casing convention.

Verifies that the OutputAggregator emits lowercase ``approach_applied``
labels for equity rows — consistent with all other approaches
(``"standardised"``, ``"foundation_irb"``, ``"advanced_irb"``, ``"slotting"``).

Bug being tested (P6.16):
    ``engine/aggregator/_equity_prep.py:23`` emits ``pl.lit("EQUITY")``
    (uppercase) while every other approach emits lowercase.
    Canonical value: ``ApproachType.EQUITY.value == "equity"``.

These tests will fail until the engine is fixed to emit lowercase ``"equity"``.
"""

from __future__ import annotations

from datetime import date

import polars as pl
from tests.fixtures.contract_columns import (
    pad_irb_branch,
    pad_sa_branch,
    pad_slotting_branch,
)

# Import builder helpers from integration conftest — they are plain functions,
# not pytest fixtures, so a direct import is valid outside the conftest scope.
from tests.integration.conftest import make_equity_exposure
from tests.integration.test_equity_flow import _build_crm_adjusted_with_equity

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.aggregator._schemas import EQUITY_APPROACHES, SA_APPROACHES
from rwa_calc.engine.equity.calculator import EquityCalculator

# Padded zero-row branch frames mirroring the orchestrator's sealed branch
# collect — empty branches still carry the full edge schema in production.
EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SA = pad_sa_branch(EMPTY)
EMPTY_IRB = pad_irb_branch(EMPTY)
EMPTY_SLOTTING = pad_slotting_branch(EMPTY)


# =============================================================================
# Test 1 — aggregator emits lowercase "equity" in approach_applied
# =============================================================================


def test_aggregator_emits_lowercase_equity_approach() -> None:
    """OutputAggregator must tag equity rows with approach_applied == 'equity' (lowercase).

    The engine currently emits ``'EQUITY'`` (uppercase) which violates the
    convention that approach labels match ApproachType enum values.  This test
    is the load-bearing assertion for P6.16.
    """
    # Arrange
    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    crm_bundle = _build_crm_adjusted_with_equity(
        [make_equity_exposure(equity_type="listed", fair_value=100_000.0)]
    )
    equity_calculator = EquityCalculator()
    aggregator = OutputAggregator()

    # Act
    equity_result = equity_calculator.get_equity_result_bundle(crm_bundle, config)
    agg_result = aggregator.aggregate(
        sa_results=EMPTY_SA,
        irb_results=EMPTY_IRB,
        slotting_results=EMPTY_SLOTTING,
        equity_bundle=equity_result,
        config=config,
    )

    # Assert
    df = agg_result.results.collect()
    equity_rows = df.filter(pl.col("exposure_class") == "equity")

    assert len(equity_rows) == 1, f"Expected 1 equity row, got {len(equity_rows)}"

    actual = equity_rows["approach_applied"][0]
    expected = ApproachType.EQUITY.value  # "equity"

    assert actual == expected, (
        f"approach_applied should be lowercase '{expected}' "
        f"(ApproachType.EQUITY.value) but got '{actual}'"
    )
    assert actual == "equity", f"approach_applied must be lowercase 'equity', got '{actual}'"


# =============================================================================
# Test 2 — EQUITY_APPROACHES frozenset contains only the lowercase canonical value
# =============================================================================


def test_equity_approaches_frozenset_is_single_lowercase() -> None:
    """EQUITY_APPROACHES must equal frozenset({'equity'}) with no uppercase fallback.

    The current _schemas.py also contains ``'EQUITY'`` as a defensive entry;
    that entry should be removed once the engine is fixed.  SA_APPROACHES
    similarly should contain only ``'standardised'``, not ``'SA'``.

    Asserting the canonical state here ensures the cleanup is complete.
    """
    # Assert — equity set contains only lowercase canonical value
    assert frozenset({"equity"}) == EQUITY_APPROACHES, (
        f"EQUITY_APPROACHES should be frozenset({{'equity'}}) but is {EQUITY_APPROACHES!r}"
    )

    # Assert — SA set contains only lowercase canonical value
    assert frozenset({"standardised"}) == SA_APPROACHES, (
        f"SA_APPROACHES should be frozenset({{'standardised'}}) but is {SA_APPROACHES!r}"
    )
