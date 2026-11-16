"""OF 08.01 reports a figure only where its published sheet has a cell.

The generator computes every column on every active row — a later cell is often
a formula over an earlier one — and until this change it reported them all.
Measured on the registered Basel 3.1 portfolios: 60 distinct non-zero figures in
cells the PRA001 taxonomy does not publish on that sheet, the largest family
column 0310 (RWEA pre credit derivatives) on the on-balance-sheet row 0020 and
the obligor-grade row 0070, which the template has on the Total row and the
counterparty-credit-risk rows 0040-0060 only (and on row 0017 of sheet 0010).

Which cells are grey is held to the Bank's taxonomy, sheet by sheet, by
``tests/contracts/test_of08_published_cells.py``; this file holds that the
generator honours the declaration — on the class sheets and on both Totals — and
that it does so AFTER the Totals are built. Order matters for one family: the
taxonomy greys r0017 / r0020 c0035 on sheet 0019 alone, and the Bank asks firms
to report that netting in the A-IRB Total and not separately (known-issues log
item 25), so blanking before the Totals would drop it from Total 0001 as well.

References:
- PRA PS1/26 Annex I (OF 08.01 template) and Annex II §3.3.2-§3.3.3
- Bank of England Banking Taxonomy v4.1.1, tables OF08.01.01.01 / .02;
  known-issues log (November 2026) item 25
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.corep.of08_published_cells import get_c08_01_unreported_cells
from rwa_calc.reporting.lineage import sheet_lineage
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator, with_reporting_ledger
from tests.unit.reporting.corep._c02_frames import MODELLED_LEGS, own
from tests.unit.reporting.corep._irb_sheet_frames import (
    FRAMEWORK,
    OF08_CORPORATE_NON_SME_FIRB,
    OF08_CORPORATE_SME_AIRB,
    OF08_RETAIL_COMMERCIAL_NON_SME,
    OF08_TOTAL_AIRB,
    cell,
    irb_book,
    legs_on,
)

#: Netting on the two A-IRB legs of the ordering test, by leg reference.
NETTING = {"A_COM": 100.0, "A_SME": 50.0}


class _FrameSource:
    """A ResultsSource over a hand-built frame."""

    def __init__(self, frame: pl.DataFrame, framework: str) -> None:
        self._frame = frame
        self.framework = framework

    def scan_results(self) -> pl.LazyFrame:
        return self._frame.lazy()


def _bundle(results: pl.LazyFrame, framework: str = FRAMEWORK) -> COREPTemplateBundle:
    return LedgerShimCorepGenerator().generate_from_lazyframe(results, framework=framework)


def _netted_book() -> pl.LazyFrame:
    """A retail commercial-property non-SME leg (sheet 0019) and a corporate SME
    leg (sheet 0023), both A-IRB and on balance sheet, each with netting."""
    legs = tuple(leg for leg in MODELLED_LEGS if leg.reference in NETTING)
    return irb_book(legs).with_columns(
        pl.col("exposure_reference").replace_strict(NETTING).alias("on_bs_netting_amount")
    )


def test_no_sheet_carries_a_figure_in_a_cell_its_published_sheet_lacks() -> None:
    # Arrange
    sheets = _bundle(irb_book()).c08_01
    assert OF08_TOTAL_AIRB in sheets, "no Total sheet generated: the Totals would go unchecked"

    # Act
    carried = [
        (key, row["row_ref"], column)
        for key, sheet in sheets.items()
        for row in sheet.iter_rows(named=True)
        for column in get_c08_01_unreported_cells(FRAMEWORK, key).get(row["row_ref"], ())
        if row.get(column) is not None
    ]

    # Assert
    assert carried == []


def test_the_published_cells_of_a_row_keep_their_figures() -> None:
    """Column 0310 is published on the Total row 0010 and not on row 0020; the
    on-balance-sheet row keeps its exposure value and RWEA."""
    # Arrange
    legs = legs_on("0012")

    # Act
    sheet = _bundle(irb_book()).c08_01[OF08_CORPORATE_NON_SME_FIRB]

    # Assert
    assert cell(sheet, "0010", "0310") == pytest.approx(own(legs))
    assert cell(sheet, "0020", "0310") is None
    assert cell(sheet, "0020", "0110") == pytest.approx(2.0 * own(legs))
    assert cell(sheet, "0020", "0260") == pytest.approx(own(legs))


def test_lineage_describes_a_cell_the_sheet_lacks_as_unreported() -> None:
    # Arrange — the sealed ledger the generator reads (the shim's projection).
    source = _FrameSource(with_reporting_ledger(irb_book()).collect(), FRAMEWORK)

    # Act
    resolver = sheet_lineage(source, "c08_01", OF08_CORPORATE_NON_SME_FIRB)

    # Assert
    assert resolver is not None
    assert resolver.query("0020", "0310").kind == "unreported"
    assert resolver.query("0010", "0310").kind == "rows"


def test_crr_sheets_are_left_as_they_were() -> None:
    """Nothing is declared under CRR: no EBA taxonomy is held to read its grey
    cells from (``corep/of08_published_cells.py``, Scope)."""
    # Arrange / Act
    sheet = _bundle(irb_book(), framework="CRR").c08_01["corporate"]

    # Assert
    assert cell(sheet, "0020", "0310") is not None


def test_the_netting_sheet_0019_lacks_is_still_in_the_airb_total() -> None:
    """Known-issues log item 25: OF08.01.01.01 r0017 / r0020 c0035 are
    "erroneously greyed out in sheet 0019 ... the PRA requests that firms report
    this data in the total AIRB sheet s0001 but do not report it separately". So
    the Total is built from the unblanked sheets and each sheet is blanked by its
    own grid afterwards."""
    # Arrange
    assert ("0020", "0035") not in {
        (row, col)
        for row, cols in get_c08_01_unreported_cells(FRAMEWORK, OF08_CORPORATE_SME_AIRB).items()
        for col in cols
    }, "sheet 0023 must report its netting, or the Total's sum cannot be told apart"

    # Act
    sheets = _bundle(_netted_book()).c08_01

    # Assert
    assert cell(sheets[OF08_RETAIL_COMMERCIAL_NON_SME], "0020", "0035") is None
    assert cell(sheets[OF08_CORPORATE_SME_AIRB], "0020", "0035") == pytest.approx(-50.0)
    assert cell(sheets[OF08_TOTAL_AIRB], "0020", "0035") == pytest.approx(-150.0)
