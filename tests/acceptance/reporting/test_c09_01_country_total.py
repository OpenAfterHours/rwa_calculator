"""C 09.01 / OF 09.01: the country sheets add up to the all-countries sheet.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> sealed ledger -> COREPGenerator
        -> COREPTemplateBundle.c09_01 ("TOTAL" + one sheet per country)

Why this file exists: an equity or CIU holding reached the geographical
breakdown with NO country, although its counterparty has one in the input. The
equity path runs beside the main flow and never joined the counterparty's
attributes, so the leg was counted on the all-countries sheet and on no country
sheet. The Bank's rule ``boe_b0904`` (ERROR) says the country sheets add up to
the total, and it broke on every portfolio holding equity or CIU units.

The geographical breakdown is by "residence of the obligor", "the country of
incorporation of the obligor" (PS1/26 Annex II §3.4 ¶86) — and an equity
holding's obligor is its issuer, which the input names.

This is deliberately NOT fixed by routing such a leg to the "other countries"
area: the instructions reserve that for supranational organisations (¶85-86),
and a leg whose country is known is not one.

References:
- PRA PS1/26 Annex II §3.4 ¶85-87; Reg (EU) 2021/451 Annex II (C 09.01)
- Bank of England validation rule boe_b0904 (v4.1.1, OF09.01.01.01)
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_offbs_golden import _config
from tests.fixtures.reporting_offbs_portfolio import CP_CIU, build_reporting_offbs_bundle

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

_FRAMEWORK = {"crr": "CRR", "b31": "BASEL_3_1"}
_TOTAL_SHEET = "TOTAL"
_TOTAL_ROW = "0170"
#: Columns boe_b0904 names that this portfolio populates: original exposure,
#: exposure value and risk-weighted exposure amount.
_COLUMNS = ("0010", "0075", "0090")


@pytest.fixture(scope="module", params=["crr", "b31"])
def run(request: pytest.FixtureRequest) -> tuple[str, pl.DataFrame, dict[str, pl.DataFrame]]:
    """(regime, the sealed ledger, the C 09.01 sheets) for the off-balance-sheet book."""
    regime = request.param
    result = PipelineOrchestrator().run_with_data(build_reporting_offbs_bundle(), _config(regime))
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=_FRAMEWORK[regime])
    return regime, result.results.collect(), corep.c09_01


def _cell(sheet: pl.DataFrame, column: str) -> float:
    return float(sheet.filter(pl.col("row_ref") == _TOTAL_ROW)[column][0] or 0.0)


def test_an_equity_leg_carries_its_counterpartys_country(
    run: tuple[str, pl.DataFrame, dict[str, pl.DataFrame]],
) -> None:
    # Arrange
    _regime, ledger, _sheets = run

    # Act
    ciu_legs = ledger.filter(pl.col("counterparty_reference") == CP_CIU)

    # Assert — the fixture gives that counterparty country_code "GB".
    assert ciu_legs.height > 0
    assert ciu_legs["cp_country_code"].to_list() == ["GB"] * ciu_legs.height


@pytest.mark.parametrize("column", _COLUMNS)
def test_the_country_sheets_add_up_to_the_all_countries_sheet(
    run: tuple[str, pl.DataFrame, dict[str, pl.DataFrame]], column: str
) -> None:
    """boe_b0904, on the three money columns this book fills."""
    # Arrange
    regime, _ledger, sheets = run
    if column not in sheets[_TOTAL_SHEET].columns:
        pytest.skip(f"C 09.01 has no column {column} under {regime}")

    # Act
    total = _cell(sheets[_TOTAL_SHEET], column)
    countries = sum(_cell(sheet, column) for key, sheet in sheets.items() if key != _TOTAL_SHEET)

    # Assert
    assert total > 0.0
    assert countries == pytest.approx(total)
