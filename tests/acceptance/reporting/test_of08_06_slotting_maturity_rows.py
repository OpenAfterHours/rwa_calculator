"""
C 08.06 / OF 08.06 and CR10 short-maturity rows on the registered slotting-maturity book.

Pipeline position:
    registered ``slotting-maturity`` runs (``RUNS``) -> PipelineOrchestrator
        -> COREPGenerator (C 08.06 / OF 08.06) and Pillar3Generator (CR10)

The book (``tests/fixtures/reporting_slotting_maturity_portfolio.py``) holds a
short-dated Strong, Good and Satisfactory project-finance leg and a long-dated
Strong one. It is run in the three states the short-maturity band has:

- CRR — UK CRR Art. 153(5) Table 1: the "less than 2,5 years" row is a "shall"
  for every grade, so each short leg sits on its < 2.5-year row.
- Basel 3.1 with the PS1/26 Art. 153(5)(d) election — column A / C for the short
  Strong / Good legs, so the same rows as CRR.
- Basel 3.1 without it (the default) — Art. 153(5)(c) column B / D for the short
  Strong / Good legs, so they sit on the long rows beside the long Strong leg.
  Table A gives 'Satisfactory' one column, so the short Satisfactory leg stays on
  its < 2.5-year row and the Total < 2.5-year row is never empty.

Two legs move and two must not, so an emptied row is distinguishable from a moved
leg (``.claude/LESSONS.md`` B5). Expected figures are the portfolio docstring's
hand calculation, typed here, not read from the engine.

References:
- PRA PS1/26 Art. 153(5)(c)-(d) Table A; Art. 158(6) Table B
- UK CRR Art. 153(5) Table 1
- PRA PS1/26 Annex II OF 08.06 rows 0010-0120; Annex XXIV UKB CR10 column c
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.reporting_slotting_maturity_portfolio import LEGS, MOVING_LEGS

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle

_SHEET = "project_finance"


class _Sheets(NamedTuple):
    result: AggregatedResultBundle
    c0806: pl.DataFrame
    cr10: pl.DataFrame


@cache
def _sheets(regime: str, portfolio: str) -> _Sheets:
    """One registered run, exactly as the supervisory gate builds it."""
    (run,) = [r for r in RUNS if r.regime == regime and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=run.framework)
    return _Sheets(result, corep.c08_06[_SHEET], pillar3.cr10[_SHEET])


def _cell(frame: pl.DataFrame, row_ref: str, column: str) -> float:
    values = frame.filter(pl.col("row_ref") == row_ref)[column].to_list()
    assert len(values) == 1, f"row {row_ref} missing from the {_SHEET} sheet"
    return values[0] or 0.0


#: The three registered runs of the book. Per state: C 08.06 row -> (exposure
#: value 0040, RWEA 0080, EL 0090), and CR10 row -> exposure value d. Rows not
#: listed must be empty.
_SHORT_ROWS_STATE = (
    {
        "0010": (10_000_000.0, 5_000_000.0, 0.0),
        "0020": (8_000_000.0, 5_600_000.0, 32_000.0),
        "0030": (6_000_000.0, 4_200_000.0, 24_000.0),
        "0050": (4_000_000.0, 4_600_000.0, 112_000.0),
        "0110": (20_000_000.0, 13_800_000.0, 136_000.0),
        "0120": (8_000_000.0, 5_600_000.0, 32_000.0),
    },
    {"1": 10_000_000.0, "2": 8_000_000.0, "3": 6_000_000.0, "5": 4_000_000.0},
    {"11": 20_000_000.0, "12": 8_000_000.0},
)
_DEFAULT_STATE = (
    {
        "0020": (18_000_000.0, 12_600_000.0, 72_000.0),
        "0040": (6_000_000.0, 5_400_000.0, 48_000.0),
        "0050": (4_000_000.0, 4_600_000.0, 112_000.0),
        "0110": (4_000_000.0, 4_600_000.0, 112_000.0),
        "0120": (24_000_000.0, 18_000_000.0, 120_000.0),
    },
    {"2": 18_000_000.0, "4": 6_000_000.0, "5": 4_000_000.0},
    {"11": 4_000_000.0, "12": 24_000_000.0},
)
STATES = [
    pytest.param("crr", "slotting-maturity", *_SHORT_ROWS_STATE, id="crr"),
    pytest.param("b31", "slotting-maturity-elected", *_SHORT_ROWS_STATE, id="b31-elected"),
    pytest.param("b31", "slotting-maturity", *_DEFAULT_STATE, id="b31-default"),
]
_C0806_CATEGORY_ROWS = ("0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080")
_CR10_CATEGORY_ROWS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")


@pytest.mark.parametrize("portfolio", ["slotting-maturity", "slotting-maturity-elected"])
def test_the_book_is_registered_and_holds_short_dated_slotting_legs(portfolio: str) -> None:
    """Adequacy: without a short-dated leg on the slotting branch nothing below tests (d)."""
    # Arrange / Act
    ledger = _sheets("b31", portfolio).result.results.collect()
    legs = ledger.filter(pl.col("source_exposure_reference").is_in(list(LEGS)))

    # Assert
    assert legs.height == len(LEGS), "a leg did not survive the pipeline"
    assert set(legs["approach_applied"].to_list()) == {"slotting"}
    short = legs.filter(pl.col("is_short_maturity"))["source_exposure_reference"].to_list()
    assert set(MOVING_LEGS) <= set(short), "a moving leg is not short-dated"
    assert len(short) == len(LEGS) - 1, "expected exactly one long-dated leg"


@pytest.mark.parametrize(("regime", "portfolio", "c0806", "cr10", "cr10_totals"), STATES)
def test_c08_06_rows_follow_the_short_maturity_band(
    regime: str,
    portfolio: str,
    c0806: dict[str, tuple[float, float, float]],
    cr10: dict[str, float],
    cr10_totals: dict[str, float],
) -> None:
    # Arrange
    sheet = _sheets(regime, portfolio).c0806

    rows = (*_C0806_CATEGORY_ROWS, "0090", "0100", "0110", "0120")
    columns = ("0040", "0080", "0090")

    # Act
    measured = {f"{row}/{column}": _cell(sheet, row, column) for row in rows for column in columns}

    # Assert
    expected = {
        f"{row}/{column}": c0806.get(row, (0.0, 0.0, 0.0))[index]
        for row in rows
        for index, column in enumerate(columns)
    }
    assert measured == pytest.approx(expected)


@pytest.mark.parametrize(("regime", "portfolio", "c0806", "cr10", "cr10_totals"), STATES)
def test_cr10_rows_follow_the_short_maturity_band(
    regime: str,
    portfolio: str,
    c0806: dict[str, tuple[float, float, float]],
    cr10: dict[str, float],
    cr10_totals: dict[str, float],
) -> None:
    # Arrange
    sheet = _sheets(regime, portfolio).cr10

    # Act
    measured = {row: _cell(sheet, row, "d") for row in (*_CR10_CATEGORY_ROWS, "11", "12")}

    # Assert
    expected = {row: {**cr10, **cr10_totals}.get(row, 0.0) for row in measured}
    assert measured == pytest.approx(expected)


@pytest.mark.parametrize(
    ("portfolio", "u_trea", "of_adj", "threshold"),
    [
        pytest.param("slotting-maturity", 22_600_000.0, -2_900_000.0, 13_900_000.0, id="default"),
        pytest.param(
            "slotting-maturity-elected", 19_400_000.0, -2_100_000.0, 14_700_000.0, id="elected"
        ),
    ],
)
def test_basel_3_1_output_floor_of_the_book(
    portfolio: str, u_trea: float, of_adj: float, threshold: float
) -> None:
    """S-TREA 28,000,000 (100% operational PF), x = 60%, OF-ADJ = -12.5 x EL."""
    # Arrange
    summary = _sheets("b31", portfolio).result.output_floor_summary
    assert summary is not None, "the output floor did not run"

    # Act / Assert
    assert summary.u_trea == pytest.approx(u_trea)
    assert summary.s_trea == pytest.approx(28_000_000.0)
    assert summary.of_adj == pytest.approx(of_adj)
    assert summary.floor_threshold == pytest.approx(threshold)
    assert summary.portfolio_floor_binding is False
