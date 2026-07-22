"""
Integration test (R14): the CRR Art. 148 ``is_under_irb_rollout`` input flag
survives the FULL pipeline — loader -> hierarchy (unify + facility_undrawn) ->
classifier -> CRM -> calc branch -> aggregator — and lands on the sealed
aggregator-exit ledger with its supplied value, so COREP C 08.07 col 0040 can
read it. A flag dropped anywhere on that path would silently collapse genuine
roll-out exposures into permanent partial use (col 0030), so this pins the
carriage end to end rather than trusting the per-edge declarations alone.

References:
- CRR Art. 148 (sequential IRB implementation / roll-out plans).
- tests/contracts/test_r14_rollout_plan_edge.py (the per-edge declaration).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator

from .conftest import make_counterparty, make_facility, make_loan, make_raw_data_bundle


def _run_rollout_pipeline() -> pl.DataFrame:
    """Run a CRR SA pipeline with a roll-out-flagged loan + facility and a plain
    loan, returning the collected aggregator-exit results frame."""
    bundle = make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference="CP001")],
        loans=[
            make_loan(
                loan_reference="LN_ROLLOUT",
                counterparty_reference="CP001",
                is_under_irb_rollout=True,
            ),
            make_loan(loan_reference="LN_PLAIN", counterparty_reference="CP001"),
        ],
        facilities=[
            make_facility(
                facility_reference="FAC_ROLLOUT",
                counterparty_reference="CP001",
                limit=3_000_000.0,
                is_under_irb_rollout=True,
            ),
        ],
    )
    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = PipelineOrchestrator().run_with_data(bundle, config)
    assert result.results is not None
    return result.results.collect()


def test_carrier_column_reaches_the_aggregator_exit() -> None:
    """The flag survives to the sealed results frame."""
    df = _run_rollout_pipeline()
    assert "is_under_irb_rollout" in df.columns


def test_flagged_loan_carries_true() -> None:
    """The roll-out-flagged loan's legs all carry True (not lost / reset to False)."""
    df = _run_rollout_pipeline()
    legs = df.filter(pl.col("source_exposure_reference") == "LN_ROLLOUT")
    assert legs.height >= 1
    assert legs["is_under_irb_rollout"].to_list() == [True] * legs.height


def test_plain_loan_carries_false() -> None:
    """The unflagged loan defaults to False (the loader's Boolean default)."""
    df = _run_rollout_pipeline()
    legs = df.filter(pl.col("source_exposure_reference") == "LN_PLAIN")
    assert legs.height >= 1
    assert legs["is_under_irb_rollout"].to_list() == [False] * legs.height


def test_facility_undrawn_row_carries_the_flag() -> None:
    """The synthetic facility_undrawn row of a flagged facility keeps True, proving
    the carriage on the facility_undrawn path (not only on drawn loan legs)."""
    df = _run_rollout_pipeline()
    undrawn = df.filter(
        (pl.col("source_exposure_reference") == "FAC_ROLLOUT")
        & (pl.col("exposure_type") == "facility_undrawn")
    )
    assert undrawn.height == 1
    assert undrawn["is_under_irb_rollout"][0] is True
