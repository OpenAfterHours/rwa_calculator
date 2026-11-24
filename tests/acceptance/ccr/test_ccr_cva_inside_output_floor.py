"""
P1.367: the BA-CVA RWEA sits inside both legs of the Basel 3.1 output floor.

Pipeline position:
    Loader -> ... -> CCRAdapter -> SACalculator -> BA-CVA (engine/stages/aggregate.py)
    -> OutputAggregator (floor) -> AggregatedResultBundle

PS1/26 Art. 92(3)(d) puts "the own funds requirements calculated in accordance
with the Credit Valuation Adjustment Risk Part" in U-TREA, paragraph 4(b)
multiplies them by 12.5, and paragraph 3A builds S-TREA from the same points
with no CVA approach on its exclusion list. So the CVA RWEA is in both legs of
``max{U-TREA; x . S-TREA + OF-ADJ}``. Before P1.367 the aggregate stage computed
BA-CVA only AFTER the floor had been taken, so it sat outside the max.

The CVA-A1 book (one SA-CCR netting set, one BA-CVA counterparty) is run end to
end: the floor summary must carry the same CVA RWEA the bundle reports, and its
U-TREA must be the credit-risk ledger plus that RWEA. The book is SA-only, so the
floor does not bind and the credit-risk ledger is untouched - this is the wiring
check; the arithmetic of a binding floor with CVA is pinned on hand-built frames
in ``tests/unit/engine/aggregator/test_output_floor_whole_book.py``.

References:
- PRA PS1/26 Art. 92(2A), 92(3)(d), 92(3A), 92(4)(b)
- PRA PS1/26 Credit Valuation Adjustment Risk Part 4.2-4.4 (BA-CVA reduced)
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p8_60.cva_a1_builder import (
    build_raw_data_bundle_cva_a1,
    create_cva_a1_counterparty_frame,
)


def _run(config: CalculationConfig) -> AggregatedResultBundle:
    bundle = dataclasses.replace(
        build_raw_data_bundle_cva_a1(),
        cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def b31_result() -> AggregatedResultBundle:
    return _run(
        CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 15), permission_mode=PermissionMode.STANDARDISED
        )
    )


def test_floor_summary_carries_the_bundle_cva_rwea(b31_result: AggregatedResultBundle) -> None:
    """
    The CVA RWEA that entered the floor is the one the bundle reports.

    Arrange: the CVA-A1 book with its BA-CVA counterparty, Basel 3.1.
    Act:     run the pipeline.
    Assert:  ``output_floor_summary.cva_rwa`` equals ``cva_rwa`` and is positive.
    """
    # Arrange / Act
    summary = b31_result.output_floor_summary
    assert summary is not None
    assert b31_result.cva_rwa is not None
    assert b31_result.cva_rwa > 0.0, "a zero CVA RWEA cannot show it entered the max"

    # Assert
    assert summary.cva_rwa == pytest.approx(b31_result.cva_rwa, rel=1e-12)


def test_u_trea_and_s_trea_include_the_cva_rwea(b31_result: AggregatedResultBundle) -> None:
    """
    Both legs carry the CVA RWEA beside the credit-risk book.

    Arrange: the CVA-A1 book, Basel 3.1.
    Act:     run the pipeline; sum ``rwa_pre_floor`` over the results ledger.
    Assert:  U-TREA = ledger + CVA RWEA; S-TREA = ledger + CVA RWEA (an SA-CCR
             row's standardised RWEA is its own); the floor does not bind, and
             the credit-risk ledger equals ``total_rwa_post_floor``.
    """
    # Arrange
    summary = b31_result.output_floor_summary
    assert summary is not None
    assert b31_result.cva_rwa is not None
    ledger = b31_result.results.collect()
    own = float(ledger["rwa_pre_floor"].sum())
    assert own > 0.0, "the CCR book must carry RWEA or the legs cannot be told apart"

    # Act / Assert
    assert summary.u_trea == pytest.approx(own + b31_result.cva_rwa, rel=1e-9)
    assert summary.s_trea == pytest.approx(own + b31_result.cva_rwa, rel=1e-9)
    assert summary.portfolio_floor_binding is False
    assert summary.total_rwa_post_floor == pytest.approx(float(ledger["rwa_final"].sum()), rel=1e-9)


def test_crr_has_no_floor_and_keeps_its_cva_scope() -> None:
    """
    CRR: no output floor, and BA-CVA is out of scope (the Feature is disabled).

    A regression guard: neither the floor nor the CVA ordering change can reach
    a CRR run, which must keep ``output_floor_summary`` and ``cva_rwa`` None.
    """
    # Arrange / Act
    result = _run(
        CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    )

    # Assert
    assert result.output_floor_summary is None
    assert result.cva_rwa is None
