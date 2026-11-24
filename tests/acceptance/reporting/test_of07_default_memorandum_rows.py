"""
OF 07.00 rows 0300 / 0320: an exposure in default, on the sheet of its class before default.

Pipeline position:
    build_reporting_bundle() -> PipelineOrchestrator (Basel 3.1, rich, as the
        supervisory gate runs it) -> sealed ``reporting_class_pre_default`` ->
        COREPGenerator -> OF 07.00 -> filing.build_canonical_return

What is asserted, and the text it is asserted from:

- PS1/26 Annex II (ps1-26-annex-ii-reporting-instructions.pdf) p.97, row 0320:
  "Exposures included in the exposure class 'exposures in default', subject to
  Article 127(1)(a) ..., which would otherwise have been assigned to the exposure
  class being reported on if they were not in default."
- p.79, ¶55: "If this exposure, before it defaulted, was an exposure to an
  institution, then that information shall also be reported in row 0320 of exposure
  class 'institutions'."
- PS1/26 Art. 127(1)(a) (ps126app1.pdf p.59): "150%, where the amount of specific
  credit risk adjustments ... is less than 20% of the outstanding amount".
- The Bank's taxonomy (v4.1.1, table OF07.00.01.03) carries the rows on the Total
  (sheet 0001) and on the class sheets 0002-0004 and 0007-0009, and on no other: the
  "in default" sheet 0011 has no cell, because the Total's data point already IS the
  "exposures in default" figure.

``RP-LN-DEFAULT`` (1,000,000 drawn, no provision, no guarantee) is ``rich``'s one
defaulted standardised exposure. (The provisioned, guaranteed, non-corporate and
real-estate-origin defaults are registered in ``default-populations`` since P5.80 and
asserted in ``test_default_population_coverage.py``.) Before this fix its row 0320 sat
on our "in default" sheet, where table OF07.00.01.03 has no cell (five unplaced
figures, which on their own stop the default filing export), and was absent from the
corporates sheet 0008, which the template does publish.

References:
- PS1/26 Art. 112(1)(g)/(j), Art. 127; Annex II §3.2.5 ¶52-55 (pp.78-79), rows
  0300 / 0320 (p.97)
- Bank of England Banking Taxonomy v4.1.1, table OF07.00.01.03; known-issues log
  (November 2026), issue #27
- src/rwa_calc/reporting/corep/c07_sheet_scope.py
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.reporting_portfolio import LN_DEFAULT, build_reporting_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.templates import C07_00_SA_SHEET_MAP
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    CanonicalMapping,
    build_canonical_return,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_calc.rulebook.resolve import resolve
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

_FRAMEWORK = "BASEL_3_1"
_REPORTING_DATE = date(2027, 6, 1)
_PRE_DEFAULT_COL = "reporting_class_pre_default"
_MEMO_TABLE = "OF07.00.01.03"
_ROW_150 = "0320"
_MEMO_ROWS = ("0300", "0320")
#: Cols 0010 / 0040 / 0150 / 0200 of a drawn, unprovisioned, uncollateralised loan
#: all equal its exposure (Annex II: 0040 = 0010 - 0030 - 0035; 0150 = 0110 - 0130).
_EXPOSURE_COLUMNS = ("0010", "0040", "0150", "0200")
_RWEA_COLUMN = "0220"

#: A checksum-valid LEI, as the filing-mapping ratchet uses; no rule depends on it.
_ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"


@cache
def _run() -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """The rich book through the Basel 3.1 pipeline and OF 07.00 (the gate's config)."""
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework=_FRAMEWORK, output_floor_summary=result.output_floor_summary
    )
    return result.results.collect(), corep


@cache
def _mapping() -> CanonicalMapping:
    header = ReturnHeader(_ENTITY_IDENTIFIER, date(2027, 3, 31), FILING_MODULE)
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    return build_canonical_return(_run()[1], header, pack=pack)


def _code(sheet_key: str) -> str:
    """The published z-code our sheet key is filed under (LESSONS B3: not spelled here)."""
    codes = [
        code
        for code, entry in SHEET_INDEX_MAPS["of07"].items()
        if entry.bundle_keys == (sheet_key,)
    ]
    assert len(codes) == 1, f"of07 sheet {sheet_key!r} has codes {codes}"
    return codes[0]


def _sheet(key: str) -> str:
    """The bundle key a published OF 07.00 z-code names."""
    (bundle_key,) = SHEET_INDEX_MAPS["of07"][key].bundle_keys
    return bundle_key


def _cell(sheet: str, row_ref: str, column: str) -> float | None:
    sheets = _run()[1].c07_00
    assert sheet in sheets, f"sheet {sheet!r} not emitted; got {sorted(sheets)}"
    matched = sheets[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected one row {row_ref}, got {matched.height}"
    return matched[column][0]


def _loan() -> dict[str, object]:
    matched = _run()[0].filter(pl.col("exposure_reference") == LN_DEFAULT)
    assert matched.height == 1, f"{LN_DEFAULT}: expected one ledger row, got {matched.height}"
    return matched.row(0, named=True)


@pytest.fixture(scope="module")
def corporate() -> str:
    return C07_00_SA_SHEET_MAP["corporate"]


@pytest.fixture(scope="module")
def total() -> str:
    return _sheet("0001")


def test_the_ledger_holds_a_defaulted_leg_whose_class_before_default_is_corporates(
    corporate: str,
) -> None:
    """Adequacy (LESSONS C11): without such a leg every assertion below is vacuous.

    Also the guard that the sealed column survives the aggregator-exit seal, which
    strips an undeclared column without a word."""
    loan = _loan()

    assert loan["approach_applied"] == "standardised"
    assert loan["reporting_class_origin"] == C07_00_SA_SHEET_MAP["defaulted"]
    assert _PRE_DEFAULT_COL in loan, f"{_PRE_DEFAULT_COL} is not sealed on the ledger"
    assert C07_00_SA_SHEET_MAP[str(loan[_PRE_DEFAULT_COL])] == corporate
    assert float(loan["risk_weight"]) == pytest.approx(
        float(resolve("b31", _REPORTING_DATE).scalar("b31_defaulted_rw_low_provision"))
    )


@pytest.mark.parametrize("column", _EXPOSURE_COLUMNS)
def test_row_0320_of_the_corporates_sheet_carries_the_defaulted_corporate_loan(
    corporate: str, column: str
) -> None:
    loan = _loan()

    assert _cell(corporate, _ROW_150, column) == pytest.approx(float(loan["ead_final"]))


def test_row_0320_of_the_corporates_sheet_carries_its_rwea(corporate: str) -> None:
    loan = _loan()
    weight = float(resolve("b31", _REPORTING_DATE).scalar("b31_defaulted_rw_low_provision"))

    assert _cell(corporate, _ROW_150, _RWEA_COLUMN) == pytest.approx(
        float(loan["ead_final"]) * weight
    )


@pytest.mark.parametrize("column", ("0200", _RWEA_COLUMN))
def test_the_total_counts_the_loan_once(total: str, column: str) -> None:
    """Not twice: the Total adds the class sheets up, and the loan is both a leg of
    the "in default" sheet and the memorandum leg of the corporates sheet."""
    loan = _loan()
    expected = float(loan["ead_final"] if column == "0200" else loan["rwa_final"])

    assert _cell(total, _ROW_150, column) == pytest.approx(expected)


@pytest.mark.parametrize("row_ref", _MEMO_ROWS)
def test_nothing_is_reported_in_the_memorandum_rows_of_the_in_default_sheet(row_ref: str) -> None:
    in_default = C07_00_SA_SHEET_MAP["defaulted"]
    row = _run()[1].c07_00[in_default].filter(pl.col("row_ref") == row_ref)

    assert row.drop("row_ref", "row_name").null_count().row(0) == (1,) * (row.width - 2)


def test_every_of_07_figure_has_a_place_in_the_taxonomy() -> None:
    unplaced = _mapping().unplaced_figures.filter(pl.col("template") == "c07_00")

    assert unplaced.height == 0, unplaced


@pytest.mark.parametrize("sheet_key", ["corporate", "total"])
def test_the_return_files_row_0320_on_the_corporates_and_total_sheets(sheet_key: str) -> None:
    facts = _mapping().canonical.facts
    code = _code(sheet_key)

    filed = facts.filter(
        (pl.col("table") == _MEMO_TABLE)
        & (pl.col("sheet") == code)
        & (pl.col("row") == _ROW_150)
        & (pl.col("column") == "0200")
    )

    assert filed["value"].to_list() == [pytest.approx(float(_loan()["ead_final"]))]
