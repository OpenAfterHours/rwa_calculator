"""
C / OF 08.01 row 0010 against both of its breakdowns, in both regimes.

Pipeline position:
    registered IRB portfolio (``RUNS``) -> PipelineOrchestrator -> COREPGenerator
    off-balance-sheet inflow book (synthetic ledger) -> LedgerShimCorepGenerator
        -> every C / OF 08.01 sheet, Totals included -> row 0010 minus each breakdown

Annex II breaks row 0010 "TOTAL EXPOSURES" down twice over the same columns, in
both regimes:

- By balance-sheet side, rows 0020-0060 ("BREAKDOWN OF TOTAL EXPOSURES BY
  EXPOSURE CATEGORIES", PS1/26 Annex II p.115; "... BY EXPOSURE TYPES", CRR
  Annex II p.106): row 0020 the on-balance-sheet items, row 0030 the
  off-balance-sheet items, and "Exposures that are subject to counterparty
  credit risk shall be reported in rows 0040-0060 and, therefore, shall not be
  reported in this row."
- By IRB treatment, rows 0070 (obligor grades or pools), 0080 (slotting), 0170
  and 0180 (dilution risk of purchased receivables), plus row 0160 (alternative
  treatment: secured by real estate) under CRR only (CRR Annex II p.107; the
  PS1/26 layout has no row 0160). The list is complete: row 0170 takes "any
  other exposure subject to risk weights not included in any other row", and
  dilution risk "shall not be reported by obligor grades or pools and shall be
  reported in row 0180" (PS1/26 Annex II pp.116-117).

Rows 0015 / 0016 (CRR) and 0017 (PS1/26) are "of which" rows of row 0010, and
PS1/26 row 0175 (purchased receivables) overlaps row 0070, which the row 0070
instruction sends purchased receivables to. None of them is in either sum:
adding row 0175 would count a purchased receivable twice.

Why the check lives here. Bank of England taxonomy v4.0.0 published both
identities as ERROR rules, ``boe_b0744`` and ``boe_b0745``; v4.1.1 withdrew both
and gave no reason (``docs/rwa-filer/publisher-issues.md``, PI-07). The EBA set
covers part of the CRR side only: ``v0338_m`` (ERROR) the treatment split on
columns 0020, 0090, 0110, 0260 and 0290, and ``v0337_m`` (WARNING) the
balance-sheet split, on none of columns 0020-0100. ``corep/c08_01_rows.py::
INFLOW_KEYS`` puts the CRM substitution inflow in column 0080 of row 0010, of
row 0020 or 0030 by the side of the covered leg, and of row 0070 or 0080 by its
treatment. So in neither regime did a published rule tie row 0010 to either
breakdown in column 0080, or to the balance-sheet breakdown in column 0090, the
waterfall that adds the inflow in; and in Basel 3.1 no published rule ties row
0010 to either breakdown in any column (LESSONS C7).

The columns. Never the ones that do not add across rows: 0010 (PD), 0230 / 0240
(LGD), 0250 (maturity) and 0300 (number of obligors). Two of them, 0250 and
0300, are why the Bank's live ``boe_b0742`` fails correct returns (PI-07),
which also records that the withdrawn ``boe_b0744`` / ``boe_b0745`` had both in
scope. Beyond that:

- Basel 3.1: per sheet, read from the PRA001 taxonomy pack, never listed by
  hand. A row with no cell for a column reports nothing there (the gateway's
  ``emptySequence`` default; the generator blanks the cell). The balance-sheet
  split covers the columns the sheet publishes on BOTH row 0010 and row 0020:
  every on-balance-sheet leg outside counterparty credit risk must reach row
  0020, and row 0030 publishes every column row 0020 does except on-balance-
  sheet netting (0035), which no off-balance-sheet item carries. That leaves out
  the "of which" columns (0030, 0100, 0120, 0125, 0130, 0140, 0265, 0270), the
  RWEA pre credit derivatives (0310) and, on sheet 0019 only, 0035 (known-issues
  log item 25). The treatment split covers the columns published on row 0010
  and row 0070, which leaves out 0125 and 0310. On a sheet whose row 0080 holds
  slotting exposure it also leaves out the output-floor columns 0275 / 0276, on
  those sheets only. Both take the slotting legs ("all credit risk exposures
  within the scope of the output floor", PS1/26 Annex II p.113), but row 0080
  has no cell for either, so row 0010 carries the slotting legs' figure, no
  treatment row does, and the template states no counterpart that figure must
  equal. In particular it is not row 0080's exposure value: column 0275 is a
  standardised-basis exposure value ("Article 111 ... for exposures to which
  risk weights are assigned in accordance with Article 113 to 134", p.112),
  which the generator still builds from the IRB exposure value
  (``corep/c08.py``; open plan items P2.27 / P1.474). Pinning the residual to
  column 0110 would lock that construction in and go red on its correction.
  Every other column row 0080 lacks stays in scope, and a residual there is a
  finding to read, not a column to drop. Column 0080 in particular is in scope
  on every sheet: the taxonomy has no inflow cell on row 0080, so an inflow
  routed there would sit on row 0010 and on no breakdown row.
- CRR: every column of the layout except the non-additive ones. No EBA taxonomy
  is held to read a grid from, and the CRR layout blanks no cell.

Adequacy (LESSONS B5 / C11). An identity is only exercised on the rows that
carry money in the population it runs on, so two tests assert where that money
is, per regime:

- ``crm-substitution`` is the only registered portfolio with an IRB-to-IRB
  substitution inflow, and all of it is on-balance-sheet: its row 0010 column
  0080 must carry the fixture's whole C 08.01 inflow, which reaches rows 0020
  and 0070. Across the registered runs, row 0030 (off-balance-sheet items) and
  row 0080 (slotting) must carry exposure value (column 0110).
- No registered run has an off-balance-sheet inflow (row 0030 column 0080 is
  empty on every one), so the off-balance-sheet half of the inflow's split runs
  on a synthetic book instead: ``test_c08_01_ccf_rows._book``, whose one
  guarantee moves 1,000 of an off-balance-sheet F-IRB corporate facility to an
  F-IRB institution, run through ``LedgerShimCorepGenerator`` in each regime.
  Its row 0030 column 0080 must carry the 1,000. The book's conversion factors
  are Basel 3.1's; neither identity reads them.

Known gaps, deliberately not loosened:

- Rows 0040-0060, 0160, 0170 and 0180 are empty in every population here, so
  their place in the sums is unexercised. An IRB-routed counterparty-credit-risk
  leg would sit in row 0010 and in no balance-sheet row, and the balance-sheet
  split would go red, correctly; no registered portfolio routes one to
  C 08.01 today.
- No population has a slotting-origin substitution inflow (``INFLOW_KEYS`` row
  0080). PRA001 has no row-0080 column-0080 cell, so on Basel 3.1 that inflow
  would sit on row 0010 and on no treatment row, and the treatment split would
  go red in column 0080, correctly.
- On a Basel 3.1 sheet holding slotting exposure, columns 0275 / 0276 are not
  checked on the treatment split (above).
- The off-balance-sheet inflow is checked on a synthetic ledger, not on a
  registered portfolio through ``PipelineOrchestrator``. A guaranteed
  off-balance-sheet IRB leg in a ``RUNS`` portfolio is owed fixture coverage.
- An inflow booked on the wrong one of rows 0020 / 0030 still adds up to row
  0010, so these identities cannot see it. The Basel 3.1 off-balance-sheet
  placement is checked directly by ``test_c08_01_ccf_rows``.
- The same holds on the treatment axis. An inflow booked on the wrong one of
  rows 0070 / 0080 still adds up to row 0010 under CRR, so neither identity
  sees it there. Under Basel 3.1 rebooking a graded inflow as slotting goes
  red in column 0080, but only because PRA001 has no row-0080 column-0080
  cell, so the generator blanks it and the money is on no treatment row (the
  slotting-origin gap above). The identity does not see the misplacement
  itself.

References:
- PRA PS1/26 Annex II §3.3.3, OF 08.01 rows 0010-0180 (pp.115-117) and columns
  0275 / 0276 (pp.112-113)
- CRR Annex II (Reg (EU) 2021/451), C 08.01 rows 0010-0180 (pp.106-107)
- Bank of England taxonomy v4.0.0 ``boe_b0744`` / ``boe_b0745`` (withdrawn in
  v4.1.1); EBA ``v0337_m``, ``v0338_m``
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.fixtures.reporting_crm_substitution_portfolio import SUBSTITUTION_INFLOW_DESIGN
from tests.unit.reporting.corep.test_c08_01_ccf_rows import (
    GUARANTEED_AMOUNT as OFF_BALANCE_SHEET_INFLOW,
)
from tests.unit.reporting.corep.test_c08_01_ccf_rows import _book as _off_balance_sheet_book

from rwa_calc.contracts.config import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.c08_sheets import c08_class_sheets
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.irb_sheets import B31_SHEET_KEYS
from rwa_calc.reporting.corep.templates import get_c08_columns
from rwa_calc.reporting.filing.canonical import FILING_MODULE, FILING_TAXONOMY
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from collections.abc import Mapping

MONEY_TOLERANCE = 0.005

CRR = "CRR"
B31 = "BASEL_3_1"
FRAMEWORKS: tuple[str, ...] = (CRR, B31)

TOTAL_ROW = "0010"
ON_BALANCE_SHEET_ROW = "0020"
OFF_BALANCE_SHEET_ROW = "0030"
GRADES_ROW = "0070"
SLOTTING_ROW = "0080"

BALANCE_SHEET = "balance-sheet"
TREATMENT = "treatment"

#: The breakdown rows of row 0010, per split and framework (module docstring).
BREAKDOWN_ROWS: dict[str, dict[str, tuple[str, ...]]] = {
    BALANCE_SHEET: dict.fromkeys(FRAMEWORKS, ("0020", "0030", "0040", "0050", "0060")),
    TREATMENT: {
        CRR: ("0070", "0080", "0160", "0170", "0180"),
        B31: ("0070", "0080", "0170", "0180"),
    },
}

#: Columns that do not add across rows: PD (0010), exposure-weighted LGD (0230)
#: and its large-financial-sector twin (0240), exposure-weighted maturity (0250)
#: and the number of obligors (0300). The same codes in both layouts.
NON_ADDITIVE: frozenset[str] = frozenset({"0010", "0230", "0240", "0250", "0300"})

#: "Non-modelled approaches exposure value" (0275) and "... risk-weighted exposure
#: amount" (0276): "This column applies to all credit risk exposures within the
#: scope of the output floor" (PS1/26 Annex II p.113), slotting exposures
#: included, but row 0080 has a cell for neither (module docstring).
FLOOR_COLUMNS: tuple[str, ...] = ("0275", "0276")
EXPOSURE_VALUE_COLUMN = "0110"

#: The substitution inflow column, and the waterfall column that adds it in.
INFLOW_COLUMN = "0080"
WATERFALL_COLUMN = "0090"

OF08_01_TABLE_PREFIX = "OF08.01.01."
CODE_BY_KEY: dict[str, str] = {key: code for code, key in B31_SHEET_KEYS.items()}

CRM_SUBSTITUTION = "crm-substitution"

#: The synthetic population whose substitution inflow is off-balance-sheet
#: (module docstring, Adequacy).
OFF_BALANCE_SHEET_INFLOW_BOOK = "off-bs-inflow-book"

#: The fixture's IRB-to-IRB inflow: every guarantee whose covered part lands on
#: C / OF 08.01 (``destination_template``), summed over its destination sheets.
C08_01_INFLOW = sum(
    float(design["guaranteed_amount"])  # type: ignore[arg-type]
    for design in SUBSTITUTION_INFLOW_DESIGN.values()
    if design["destination_template"] == "c08_01"
)

#: Every registered run with an IRB permission: the runs that emit C / OF 08.01.
IRB_RUNS: tuple[tuple[str, str], ...] = tuple(
    (run.framework, run.portfolio)
    for run in RUNS
    if run.build_config().permission_mode is PermissionMode.IRB
)

#: The populations each identity runs on: the registered IRB runs, then the book.
POPULATIONS: tuple[tuple[str, str], ...] = (
    *IRB_RUNS,
    *((framework, OFF_BALANCE_SHEET_INFLOW_BOOK) for framework in FRAMEWORKS),
)

CASES = [
    pytest.param(framework, population, split, id=f"{framework}-{population}-{split}")
    for framework, population in POPULATIONS
    for split in (BALANCE_SHEET, TREATMENT)
]


@pytest.mark.parametrize(("framework", "population", "split"), CASES)
def test_row_0010_equals_the_sum_of_its_breakdown(
    framework: str, population: str, split: str
) -> None:
    """Row 0010 minus the split's breakdown rows is 0.00 on every in-scope column.

    Arrange: the population's C / OF 08.01 sheets, Totals included.
    Act: the residual row 0010 minus the breakdown rows, per sheet and column.
    Assert: every residual is 0.00 - an amount on row 0010 that no breakdown row
    reports, or one reported twice, is a break.
    """
    # Arrange
    sheets = _sheets(framework, population)
    assert sheets, f"{framework} {population}: no C / OF 08.01 sheet generated"

    # Act
    breaks = [
        line
        for key, frame in sorted(sheets.items())
        for line in _breaks(framework, key, frame, split)
    ]

    # Assert
    assert breaks == [], f"{framework} {population} {split} split:\n  " + "\n  ".join(breaks)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_breakdowns_are_checked_where_money_moves(framework: str) -> None:
    """Adequacy on the registered runs: which breakdown rows carry money.

    Arrange: every registered IRB run of one framework.
    Act: total the inflow on row 0010 of ``crm-substitution``'s class sheets,
    and the exposure value on rows 0030 and 0080 across all runs.
    Assert: the inflow is the fixture's whole C 08.01 inflow and both splits
    check column 0080 / 0090 wherever it lands; native off-balance-sheet items
    and slotting exposure both exist. The off-balance-sheet INFLOW is not
    here - no registered run has one - and is the next test's.
    """
    # Arrange
    substitution = c08_class_sheets(_sheets(framework, CRM_SUBSTITUTION))
    every_sheet = [
        (key, frame)
        for run_framework, portfolio in IRB_RUNS
        if run_framework == framework
        for key, frame in _sheets(framework, portfolio).items()
    ]

    # Act
    inflow = {
        key: _cell(frame, TOTAL_ROW, INFLOW_COLUMN)
        for key, frame in substitution.items()
        if _cell(frame, TOTAL_ROW, INFLOW_COLUMN)
    }
    off_balance_sheet = sum(
        _cell(frame, OFF_BALANCE_SHEET_ROW, EXPOSURE_VALUE_COLUMN) for _, frame in every_sheet
    )
    slotting = sum(_cell(frame, SLOTTING_ROW, EXPOSURE_VALUE_COLUMN) for _, frame in every_sheet)

    # Assert
    assert C08_01_INFLOW > 0, "the fixture routes no guarantee to C / OF 08.01"
    assert sum(inflow.values()) == pytest.approx(C08_01_INFLOW, abs=MONEY_TOLERANCE)
    for key in inflow:
        _assert_inflow_columns_in_scope(framework, key, substitution[key])
    assert off_balance_sheet > 0, "no registered IRB run reports an off-balance-sheet item"
    assert slotting > 0, "no registered IRB run reports slotting exposure"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_off_balance_sheet_inflow_is_checked_on_row_0030(framework: str) -> None:
    """Adequacy on the book: its inflow is on row 0030, and checked there.

    Arrange: the off-balance-sheet inflow book's class sheets, one framework.
    Act: row 0030 column 0080 on each sheet.
    Assert: row 0030 carries the book's whole guaranteed amount, and both
    splits check column 0080 / 0090 on every sheet that holds it - so the
    balance-sheet split above sees an off-balance-sheet inflow in each regime.
    """
    # Arrange
    sheets = c08_class_sheets(_sheets(framework, OFF_BALANCE_SHEET_INFLOW_BOOK))

    # Act
    on_row_0030 = {
        key: _cell(frame, OFF_BALANCE_SHEET_ROW, INFLOW_COLUMN)
        for key, frame in sheets.items()
        if _cell(frame, OFF_BALANCE_SHEET_ROW, INFLOW_COLUMN)
    }

    # Assert
    assert OFF_BALANCE_SHEET_INFLOW > 0, "the book guarantees no off-balance-sheet item"
    assert sum(on_row_0030.values()) == pytest.approx(
        OFF_BALANCE_SHEET_INFLOW, abs=MONEY_TOLERANCE
    ), f"{framework}: row 0030 column 0080 is {on_row_0030}"
    for key in on_row_0030:
        _assert_inflow_columns_in_scope(framework, key, sheets[key])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sheets(framework: str, population: str) -> dict[str, pl.DataFrame]:
    """The population's C / OF 08.01 sheets, keyed by sheet."""
    if population == OFF_BALANCE_SHEET_INFLOW_BOOK:
        return _book_sheets(framework)
    return _registered_sheets(framework, population)


@cache
def _registered_sheets(framework: str, portfolio: str) -> dict[str, pl.DataFrame]:
    """The registered run's C / OF 08.01 sheets."""
    (run,) = [r for r in RUNS if r.framework == framework and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    return (
        COREPGenerator()
        .generate_from_lazyframe(
            result.results,
            framework=framework,
            output_floor_summary=result.output_floor_summary,
        )
        .c08_01
    )


@cache
def _book_sheets(framework: str) -> dict[str, pl.DataFrame]:
    """The off-balance-sheet inflow book's C / OF 08.01 sheets."""
    return (
        LedgerShimCorepGenerator()
        .generate_from_lazyframe(_off_balance_sheet_book(), framework=framework)
        .c08_01
    )


def _breaks(framework: str, key: str, frame: pl.DataFrame, split: str) -> list[str]:
    """One line per in-scope column whose residual is not 0.00."""
    rows = BREAKDOWN_ROWS[split][framework]
    columns = _columns_in_scope(framework, key, frame, split)
    return [
        f"{key} c{column}: r{TOTAL_ROW}={_cell(frame, TOTAL_ROW, column):,.2f} vs "
        f"{'+'.join('r' + row for row in rows)}="
        f"{sum(_cell(frame, row, column) for row in rows):,.2f} (residual {residual:,.2f})"
        for column, residual in _residuals(frame, rows, columns).items()
        if abs(residual) > MONEY_TOLERANCE
    ]


@cache
def _published(code: str) -> Mapping[str, frozenset[str]]:
    """Row -> the columns PRA001 sheet ``code`` of OF 08.01 has a data point for."""
    cells = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack.cells.filter(
        pl.col("table").str.starts_with(OF08_01_TABLE_PREFIX) & (pl.col("sheet") == code)
    )
    by_row: dict[str, set[str]] = {}
    for row, column in cells.select("row", "column").iter_rows():
        by_row.setdefault(row, set()).add(column)
    return {row: frozenset(columns) for row, columns in by_row.items()}


def _columns_in_scope(framework: str, key: str, frame: pl.DataFrame, split: str) -> list[str]:
    """The columns a split is checked on, for one sheet (module docstring)."""
    if framework == CRR:
        return [c.ref for c in get_c08_columns(framework) if c.ref not in NON_ADDITIVE]
    assert key in CODE_BY_KEY, f"sheet {key!r} has no published OF 08.01 code"
    published = _published(CODE_BY_KEY[key])
    if split == BALANCE_SHEET:
        scope = published[TOTAL_ROW] & published[ON_BALANCE_SHEET_ROW]
    else:
        scope = published[TOTAL_ROW] & published[GRADES_ROW]
        scope -= {c for c in FLOOR_COLUMNS if _slotting_has_no_cell(framework, key, frame, c)}
    return sorted(scope - NON_ADDITIVE)


def _slotting_has_no_cell(framework: str, key: str, frame: pl.DataFrame, column: str) -> bool:
    """Whether row 0080 holds slotting exposure the sheet gives no ``column`` cell."""
    if framework == CRR or not _holds_money(frame, SLOTTING_ROW):
        return False
    return column not in _published(CODE_BY_KEY[key]).get(SLOTTING_ROW, frozenset())


def _assert_inflow_columns_in_scope(framework: str, key: str, frame: pl.DataFrame) -> None:
    """Both splits check the inflow and waterfall columns on ``key``."""
    for split in (BALANCE_SHEET, TREATMENT):
        scope = _columns_in_scope(framework, key, frame, split)
        assert {INFLOW_COLUMN, WATERFALL_COLUMN} <= set(scope), (key, split, scope)


def _residuals(frame: pl.DataFrame, rows: tuple[str, ...], columns: list[str]) -> dict[str, float]:
    """Column -> row 0010 minus the sum of ``rows``, an empty cell read as 0."""
    return {
        column: _cell(frame, TOTAL_ROW, column) - sum(_cell(frame, row, column) for row in rows)
        for column in columns
    }


def _holds_money(frame: pl.DataFrame, row: str) -> bool:
    """Whether ``row`` reports a non-zero figure in any column."""
    matched = frame.filter(pl.col("row_ref") == row)
    return any(
        value not in (None, 0.0)
        for column in matched.columns
        if column not in ("row_ref", "row_name")
        for value in matched[column].to_list()
    )


def _cell(frame: pl.DataFrame, row: str, column: str) -> float:
    """One cell's amount; a row or cell that reports nothing reads as 0."""
    matched = frame.filter(pl.col("row_ref") == row)
    if matched.height == 0:
        return 0.0
    value = matched[column][0]
    return 0.0 if value is None else float(value)
