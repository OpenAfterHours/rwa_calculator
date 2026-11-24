"""
OF 02.00 row 0036 (OF-ADJ) caps GCRA against the whole book (P1.212).

Pipeline position:
    registered irb-classes portfolio + a firm GCRA input -> PipelineOrchestrator
        -> OutputAggregator (gcra_cap_base -> compute_of_adj -> floor)
        -> COREPGenerator -> OF 02.00 rows 0010 (col 0030) / 0036

PS1/26 Art. 92(2A) caps GCRA at "1.25% of risk-weighted exposure amounts
calculated in accordance with paragraph 3A" - the whole book's credit and CCR
RWEA at its standardised value. Every registered portfolio sets
``gcra_amount = 0``, so no Tier 2 run could see the cap at all (LESSONS B5). This
file runs the registered irb-classes book (F-IRB, A-IRB, slotting and SA legs)
with a firm GCRA input in two legs - one SHORT of the whole-book cap but past
the old modelled-subset cap, one PAST the whole-book cap - and reads the
published OF-ADJ. The base is re-derived from the sealed ledger, not read from
the engine.

It is not a ``RUNS`` registration on purpose: a new or re-configured Basel 3.1
``RUNS`` entry changes a filed golden return, and the referee differential that
pins those returns needs Arelle and the Bank's package to re-bank, which the
repository does not hold. The run here re-uses the registered builder and
config, and differs only by the GCRA input.

CRR has no output floor and no OF-ADJ (C 02.00 has no row 0036), so the rule has
no CRR leg; ``tests/unit/test_of_adj.py::test_crr_no_of_adj`` pins the absence.

References:
- PRA PS1/26 Art. 92(2A), 92(3)(a), 92(3)(ca), 92(3A)
- PS1/26 Annex II OF 02.00 rows 0010 / 0036
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import _irb_config
from tests.fixtures.reporting_irb_classes_portfolio import build_reporting_irb_classes_bundle

from rwa_calc.engine.aggregator._schemas import FLOOR_ELIGIBLE_APPROACHES
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

_CAP = 0.0125
_REL = 1e-9


def _run(gcra_amount: float):  # noqa: ANN202
    base = _irb_config("BASEL_3_1")
    config = dataclasses.replace(
        base, output_floor=dataclasses.replace(base.output_floor, gcra_amount=gcra_amount)
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_irb_classes_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework="BASEL_3_1", output_floor_summary=result.output_floor_summary
    )
    return result, corep.c_02_00


def _cell(frame: pl.DataFrame, row_ref: str, col: str) -> float:
    rows = frame.filter(pl.col("row_ref") == row_ref)
    assert rows.height == 1, f"OF 02.00 row {row_ref} emitted {rows.height} times"
    value = rows[col][0]
    assert value is not None, f"OF 02.00 r{row_ref} c{col} is empty"
    return float(value)


def _ledger_bases(result) -> tuple[float, float]:  # noqa: ANN001
    """``(whole-book base, modelled-subset base)`` re-derived from the sealed ledger."""
    ledger = result.results.collect()
    modelled = pl.col("approach_applied").is_in(list(FLOOR_ELIGIBLE_APPROACHES))
    standardised = pl.when(modelled).then(pl.col("sa_rwa")).otherwise(pl.col("rwa_pre_floor"))
    totals = ledger.select(
        pl.when(standardised.is_finite()).then(standardised).otherwise(0.0).sum().alias("whole"),
        pl.when(modelled & pl.col("sa_rwa").is_finite())
        .then(pl.col("sa_rwa"))
        .otherwise(0.0)
        .sum()
        .alias("subset"),
    )
    return float(totals["whole"][0]), float(totals["subset"][0])


@pytest.fixture(scope="module")
def bases() -> tuple[float, float]:
    result, _of02 = _run(0.0)
    whole, subset = _ledger_bases(result)
    assert "risk_type" not in result.results.collect_schema().names() or (
        result.results.filter(pl.col("risk_type") == "SETTLEMENT_FAILED_TRADE").collect().height
        == 0
    ), "a DvP settlement line would leave the base; this book has none, so none is excluded"
    assert whole > subset * 1.2, (
        "the book's standardised legs must widen the base materially, or the two caps "
        "cannot be told apart"
    )
    return whole, subset


def test_gcra_between_the_two_caps_enters_whole(bases: tuple[float, float]) -> None:
    """
    A GCRA past the old subset cap but short of the whole-book cap is not capped.

    Arrange: the irb-classes book with GCRA set halfway between 1.25% of the
             modelled subset's SA-equivalent and 1.25% of the whole-book base.
    Act:     run the pipeline and generate OF 02.00.
    Assert:  the summary's capped GCRA is the full input, and r0036 c0030 is
             12.5 x (IRB T2 - IRB CET1 - GCRA). Before P1.212 the subset cap cut
             GCRA to 1.25% of the subset base.
    """
    # Arrange
    whole, subset = bases
    gcra = _CAP * (whole + subset) / 2

    # Act
    result, of02 = _run(gcra)
    summary = result.output_floor_summary
    assert summary is not None

    # Assert
    assert summary.gcra_amount == pytest.approx(gcra, rel=_REL)
    expected = 12.5 * (summary.irb_t2_credit - summary.irb_cet1_deduction - gcra)
    assert _cell(of02, "0036", "0030") == pytest.approx(expected, rel=_REL)
    assert _cell(of02, "0010", "0030") == pytest.approx(
        summary.floor_pct * summary.s_trea + expected, rel=_REL
    )


def test_gcra_past_the_whole_book_cap_is_capped_at_it(bases: tuple[float, float]) -> None:
    """
    A GCRA past the whole-book cap is capped at 1.25% of the whole-book base.

    Arrange: the irb-classes book with GCRA at twice the whole-book cap.
    Act:     run the pipeline and generate OF 02.00.
    Assert:  the capped GCRA is 1.25% of the ledger-derived whole-book base, and
             r0036 c0030 follows from it.
    """
    # Arrange
    whole, _subset = bases
    gcra = 2 * _CAP * whole

    # Act
    result, of02 = _run(gcra)
    summary = result.output_floor_summary
    assert summary is not None

    # Assert
    assert summary.gcra_amount == pytest.approx(_CAP * whole, rel=_REL)
    expected = 12.5 * (summary.irb_t2_credit - summary.irb_cet1_deduction - _CAP * whole)
    assert _cell(of02, "0036", "0030") == pytest.approx(expected, rel=_REL)
