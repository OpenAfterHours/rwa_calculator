"""OF 02.00 IRB class rows are reported only where their OF 08.01 sheet is.

Fourteen of the fifteen Basel 3.1 OF 02.00 IRB class rows are, in the PRA001
taxonomy, the SAME data point as the total of an OF 08.01 class sheet (row 0010,
column 0260 for OF 02.00 column 0010, column 0276 for column 0020). OF 08 emits
no sheet for a class with no legs. A zero written in the OF 02.00 row therefore
files two facts on a sheet the return otherwise leaves unreported, and the
gateway evaluates every per-sheet rule on it: ``boe_b1055`` (ERROR) compared the
OF 09.02 country total with that phantom zero and failed on five registered
portfolios.

The Bank of England XBRL Filing Manual v1.0.1, rule 2.19: a missing numeric
fact of a reported template "is treated as equivalent to zero ... by the
recipient", "inapplicable facts MAY be omitted", and "uninteresting zeros"
SHOULD NOT be reported. So the row is empty where the sheet has no legs and
carries its sum - a genuine zero included - where it has.

What stays reported: row 0290 (sheet 0010's total also counts slotting, so the
row is not that sheet's data point; ``boe_b0618`` and ``boe_b2290`` read it),
the approach totals (the tie-outs read rows 0050 and 0240), and every CRR row.

The invariant test is anchored to the taxonomy pack and to OF 08's own emission,
not to the grouping ``c02.py`` computes, so it cannot share the generator's
assumption about which rows are sheet totals.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.reporting.corep import irb_sheets
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import (
    MODELLED_LEGS,
    SA_LEGS,
    Leg,
    crr_frame,
)
from tests.unit.reporting.corep._irb_sheet_frames import FRAMEWORK, cell, irb_book

OF02_TABLE = "OF02.00.01.01"
OF08_TABLE = "OF08.01.01.01"
CLASS_SHEET_CODES = sorted(sheet.code for sheet in irb_sheets.B31_CLASS_SHEETS)
HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)

#: OF 02.00 rows that are stated whether or not any leg reaches them: the F-IRB
#: specialised-lending row (sheet 0010 is no OF 02.00 data point) and the totals.
ALWAYS_STATED_ROWS = ("0050", "0060", "0240", "0250", "0290", "0310", "0411")


def _legs(*references: str) -> tuple[Leg, ...]:
    by_reference = {leg.reference: leg for leg in (*SA_LEGS, *MODELLED_LEGS)}
    return tuple(by_reference[reference] for reference in references)


def _bundle(legs: tuple[Leg, ...]) -> COREPTemplateBundle:
    return LedgerShimCorepGenerator().generate_from_lazyframe(irb_book(legs), framework=FRAMEWORK)


def _of02(legs: tuple[Leg, ...]) -> pl.DataFrame:
    frame = _bundle(legs).c_02_00
    assert frame is not None, "OF 02.00 was not generated"
    return frame


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


def test_an_irb_class_row_whose_sheet_has_no_legs_is_not_reported() -> None:
    """Row 0356 is OF 08.01 sheet 0011's total; with no A-IRB non-SME corporate,
    OF 08 reports no sheet 0011, and a zero here would file one (``boe_b1055``)."""
    # Arrange - F-IRB non-SME corporates and nothing under A-IRB
    (leg,) = _legs("F_OTH")

    # Act
    of02 = _of02((leg,))

    # Assert - the row with legs survives (a fix that blanks every row fails here)
    assert cell(of02, "0297", "0010") == leg.own
    assert cell(of02, "0297", "0020") == leg.standardised
    # ... and its A-IRB twin, which has no legs, is empty in both columns
    assert cell(of02, "0356", "0010") is None
    assert cell(of02, "0356", "0020") is None


@pytest.mark.parametrize(
    ("references", "has_tied_class_sheet"),
    [
        pytest.param(("F_OTH",), True, id="firb-non-sme-corporate"),
        pytest.param(("F_INST", "F_OTH"), True, id="firb-institution-and-corporate"),
        pytest.param(("A_OTH", "A_QRRE"), True, id="airb-corporate-and-qrre"),
        pytest.param(("F_OTH", "A_OTH"), True, id="both-non-sme-corporate-sheets"),
        pytest.param(("F_SL", "SL_PF"), False, id="firb-sl-and-slotting"),
        pytest.param(("SL_PF",), False, id="slotting-only"),
        pytest.param(tuple(leg.reference for leg in MODELLED_LEGS), True, id="every-modelled-leg"),
    ],
)
def test_of02_files_no_data_point_of_an_of08_class_sheet_of08_does_not_report(
    references: tuple[str, ...], has_tied_class_sheet: bool
) -> None:
    """Every OF 02.00 fact that is one data point with a cell of an OF 08.01 CLASS
    sheet names a sheet the same return's OF 08.01 facts report.

    The every-leg book reports every sheet, so it is green whatever OF 02.00 does:
    it is the control that the return's facts reach the shared data points.
    ``has_tied_class_sheet`` says, from the legs alone, whether the book has legs
    on a class sheet whose total IS an OF 02.00 row (every one but the slotting
    sheet 0010, which F-IRB specialised lending shares with slotting): such a book
    must place at least one shared fact, or a return that stopped placing the
    class rows would leave no orphan to find and pass on nothing."""
    # Arrange
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    of02_cells = pack.cells.filter(pl.col("table") == OF02_TABLE).select(
        "row", "column", "datapoint"
    )
    class_sheet_cells = pack.cells.filter(
        (pl.col("table") == OF08_TABLE) & pl.col("sheet").is_in(CLASS_SHEET_CODES)
    ).select("datapoint", pl.col("sheet").alias("of08_sheet"))
    # Adequacy: the taxonomy does tie OF 02.00 cells to OF 08.01 class sheets.
    assert of02_cells.join(class_sheet_cells, on="datapoint").height > 0
    facts = build_canonical_return(_bundle(_legs(*references)), HEADER, pack=pack).canonical.facts
    of02 = facts.filter(pl.col("table") == OF02_TABLE).join(of02_cells, on=["row", "column"])
    shared = of02.join(class_sheet_cells, on="datapoint")
    reported_sheets = set(facts.filter(pl.col("table") == OF08_TABLE)["sheet"].to_list())
    assert of02.height > 0, "OF 02.00 was not placed"
    if has_tied_class_sheet:
        assert shared.height > 0, "no OF 02.00 class-row fact was placed - nothing to check"

    # Act
    orphans = sorted(
        (row, column, sheet)
        for row, column, sheet in shared.select("row", "column", "of08_sheet").iter_rows()
        if sheet not in reported_sheets
    )

    # Assert
    assert orphans == [], f"OF 02.00 facts on an OF 08.01 sheet OF 08 does not report: {orphans}"


# ---------------------------------------------------------------------------
# What must not change
# ---------------------------------------------------------------------------


def test_a_class_with_legs_and_no_rwea_still_reports_a_zero() -> None:
    """The row follows the LEGS, not the amount: a class whose exposures weigh
    nothing has a sheet, and its total is a reported zero - never empty."""
    # Arrange - an F-IRB institution leg with no RWEA under either measure
    weightless = Leg("F_ZERO", "foundation_irb", "institution", 0.0, 0.0)

    # Act
    of02 = _of02((weightless, *_legs("F_OTH")))

    # Assert
    assert cell(of02, "0271", "0010") == 0.0
    assert cell(of02, "0271", "0020") == 0.0


def test_the_firb_specialised_lending_row_is_a_zero_beside_slotting_alone() -> None:
    """Row 0290 is NOT sheet 0010's total - that sheet also counts the slotting
    legs - so it stays a reported zero where only slotting reaches the sheet;
    ``boe_b0618`` and ``boe_b2290`` read it."""
    # Arrange - slotting and no F-IRB specialised lending
    legs = _legs("SL_PF", "F_OTH")

    # Act
    of02 = _of02(legs)

    # Assert
    assert cell(of02, "0290", "0010") == 0.0
    assert cell(of02, "0290", "0020") == 0.0


def test_the_approach_totals_are_stated_with_no_legs() -> None:
    """The totals are always stated: ``tieouts.credit_risk_rollup_c02`` skips
    silently on an empty row 0050 or 0240, and SA, A-IRB and slotting have no
    legs in this book."""
    # Arrange
    legs = _legs("F_OTH")

    # Act
    of02 = _of02(legs)

    # Assert
    empty = [row for row in ALWAYS_STATED_ROWS if cell(of02, row, "0010") is None]
    assert empty == []


def test_crr_class_rows_still_report_zero_with_no_legs() -> None:
    """CRR C 02.00 keeps zero-filling: the EBA rules read a missing cell as zero
    and the CRR sheets are not on a published taxonomy axis."""
    # Arrange
    legs = _legs("F_OTH")

    # Act
    c02 = LedgerShimCorepGenerator().generate_from_lazyframe(crr_frame(legs), framework="CRR")

    # Assert - A-IRB corporates other, which has no legs
    assert c02.c_02_00 is not None
    assert cell(c02.c_02_00, "0360", "0010") == 0.0
