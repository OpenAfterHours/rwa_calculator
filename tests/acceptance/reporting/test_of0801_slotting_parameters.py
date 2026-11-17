"""
C / OF 08.01 LGD (column 0230) and maturity (column 0250) on the slotting sheet of the registered portfolios.

Pipeline position:
    registered portfolio (``RUNS``) -> PipelineOrchestrator -> COREPGenerator
        -> filing.build_canonical_return (Basel 3.1)

A class sheet averaged LGD and maturity over every leg's exposure value, a leg
with no value counting as zero. A slotting leg carries neither, so the
specialised-lending sheet (Basel 3.1 sheet 0010 "Specialised Lending (FIRB
approach or slotting approach)", CRR ``specialised_lending``) filed 0.0 on every
row holding slotting exposure alone. Every registered portfolio with slotting
(``rich``, ``crm-substitution``, ``irb-shapes``) has such a sheet: eight 0.0
maturities and eight 0.0 LGDs filed on Basel 3.1 OF08.01.01.01 sheet 0010, rows
0010 / 0020 (and 0030 / 0034 on ``irb-shapes``).

The instruction, PS1/26 Annex II §3.3.3 (OF 08.01), p.111 - column 0250: "This
column shall therefore not be filled in for the exposure class 'retail' or for
exposures subject to the slotting approach"; column 0230: "Data shall not be
reported for specialised lending exposures subject to the slotting approach".
The CRR cells are empty for one definition in both regimes (the unit test
module records the CRR text and its difference for column 0250).

The FIRB-and-slotting Total (sheet 0002) already averaged only the legs that
carry the parameter and does not move; it is held here against the ledger.

The mixed case - F-IRB specialised lending beside slotting on one sheet, where
the defect filed a diluted figure rather than a zero - is in no registered
portfolio and is held by the unit test.

References:
- PRA PS1/26 Annex II §3.3.3 columns 0230 and 0250 (p.111)
- Reg (EU) 2021/451 Annex II C 08.01 columns 0230 (p.103) and 0250 (p.104)
- tests/unit/reporting/corep/test_c08_01_slotting_parameters.py
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.irb_sheets import SLOTTING_SHEET_KEY, TOTAL_FIRB_SLOTTING_KEY
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)
OF08_TABLE = "OF08.01.01.01"
SLOTTING_SHEET_CODE = "0010"

#: Column -> (the parameter carrier, the scale the column reports it at).
PARAMETERS: dict[str, tuple[str, float]] = {
    "0230": ("lgd_floored", 1.0),
    "0250": ("irb_maturity_m", 365.0),
}

#: The registered portfolios that hold supervisory slotting.
SLOTTING_PORTFOLIOS = ("rich", "crm-substitution", "irb-shapes")

#: The specialised-lending sheet a slotting leg reports on, by framework.
SLOTTING_SHEET = {"CRR": "specialised_lending", "BASEL_3_1": SLOTTING_SHEET_KEY}

CASES = [
    pytest.param(framework, portfolio, id=f"{framework}-{portfolio}")
    for framework in SLOTTING_SHEET
    for portfolio in SLOTTING_PORTFOLIOS
]


@cache
def _generated(framework: str, portfolio: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """The portfolio's sealed ledger and its COREP bundle."""
    (run,) = [r for r in RUNS if r.framework == framework and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    return result.results.collect(), corep


def _irb_legs(ledger: pl.DataFrame, *approaches: str) -> pl.DataFrame:
    return ledger.filter(pl.col("reporting_approach_origin").is_in(approaches))


@pytest.mark.parametrize(("framework", "portfolio"), CASES)
def test_the_slotting_sheet_reports_no_lgd_and_no_maturity(framework: str, portfolio: str) -> None:
    # Arrange
    ledger, corep = _generated(framework, portfolio)
    slotting = _irb_legs(ledger, "slotting")
    sheet = corep.c08_01[SLOTTING_SHEET[framework]]
    specialised = _irb_legs(ledger, "foundation_irb", "advanced_irb").filter(
        pl.col("reporting_class_origin") == "specialised_lending"
    )
    # Adequacy: the sheet holds exposure, all of it slotting legs with neither
    # parameter - else an empty cell could be an F-IRB leg's figure lost.
    assert slotting.height > 0 and specialised.height == 0, "the sheet is not slotting-only"
    assert slotting["reporting_class_origin"].unique().to_list() == ["specialised_lending"]
    assert slotting["lgd_floored"].is_null().all() and slotting["irb_maturity_m"].is_null().all()
    assert (sheet.filter(pl.col("row_ref") == "0010")["0110"][0] or 0.0) > 0

    # Act
    reported = {
        (row, column): value
        for row in sheet["row_ref"].to_list()
        for column in PARAMETERS
        if (value := sheet.filter(pl.col("row_ref") == row)[column][0]) is not None
    }

    # Assert
    assert reported == {}


@pytest.mark.parametrize("portfolio", SLOTTING_PORTFOLIOS)
def test_b31_files_no_lgd_and_no_maturity_on_the_slotting_sheet(portfolio: str) -> None:
    # Arrange
    _ledger, corep = _generated("BASEL_3_1", portfolio)

    # Act
    facts = build_canonical_return(
        corep, HEADER, pack=resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    ).canonical.facts.filter(pl.col("table") == OF08_TABLE)

    # Assert
    on_sheet = facts.filter(pl.col("sheet") == SLOTTING_SHEET_CODE)
    assert on_sheet.filter(pl.col("column") == "0110").height > 0, "no sheet 0010 filed"
    filed = on_sheet.filter(pl.col("column").is_in(list(PARAMETERS))).select("row", "column")
    assert set(filed.iter_rows()) == set()


@pytest.mark.parametrize("column", sorted(PARAMETERS))
@pytest.mark.parametrize("portfolio", SLOTTING_PORTFOLIOS)
def test_b31_firb_and_slotting_total_averages_the_legs_that_carry_the_parameter(
    portfolio: str, column: str
) -> None:
    """GUARD, green before and after the fix: the Total already left a leg with
    no value out of its average."""
    # Arrange
    carrier, scale = PARAMETERS[column]
    ledger, corep = _generated("BASEL_3_1", portfolio)
    legs = _irb_legs(ledger, "foundation_irb", "slotting").filter(pl.col(carrier).is_not_null())
    due = float((legs[carrier] * legs["ead_final"]).sum()) * scale / float(legs["ead_final"].sum())

    # Act
    total = corep.c08_01[TOTAL_FIRB_SLOTTING_KEY].filter(pl.col("row_ref") == "0010")

    # Assert
    assert total[column][0] == pytest.approx(due, rel=1e-9)
