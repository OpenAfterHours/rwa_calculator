"""C 07.00 / OF 07.00 carries a Total sheet alongside its exposure-class sheets.

Annex II asks for the template twice over: "The information in OF CR SA is
required for the total exposure across all exposure classes and individually
for each of the exposure classes under the Standardised Approach. The total
figures as well as the information of each exposure class shall be reported in
a separate dimension." (PS1/26 Annex II §3.2.2 ¶47; the EBA text for C 07.00
says the same.) Until 2026-11-13 the generator produced the class sheets only,
so the published sheet 0001 was empty in every return and the Bank's rule
``boe_b0713`` — sheet 0001 equals the sum of the class sheets — compared a
total against nothing.

The Total is the cell-by-cell sum of the class sheets. Every row of the template
is evaluated per sheet over that sheet's own population (the real-estate rows
exist only on the real-estate sheet, an inflow lands on the protection
provider's sheet), so the sum of the sheets is the only total consistent with
them — and it is what the published rule states.

References:
- PRA PS1/26 Annex II §3.2.2 ¶47; Reg (EU) 2021/451 Annex II (C 07.00)
- Bank of England validation rule boe_b0713 (v4.1.1, OF07.00.01.01)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.c07 import c07_class_sheets, c07_total_sheet
from rwa_calc.reporting.corep.templates import C07_00_TOTAL_SHEET_KEY
from rwa_calc.reporting.lineage import summed_sheet_reason
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _sa_results
from tests.unit.reporting.corep.test_c07_crm_substitution import _sa_results_with_substitution

_LABELS = ("row_ref", "row_name")
FRAMEWORKS = ("CRR", "BASEL_3_1")


def _sheets(results: pl.LazyFrame, framework: str) -> dict[str, pl.DataFrame]:
    return LedgerShimCorepGenerator().generate_from_lazyframe(results, framework=framework).c07_00


def _cell(sheet: pl.DataFrame, row_ref: str, column: str) -> float | None:
    return sheet.filter(pl.col("row_ref") == row_ref)[column][0]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_template_carries_a_total_sheet(framework: str) -> None:
    # Arrange / Act
    sheets = _sheets(_sa_results(), framework)

    # Assert
    assert C07_00_TOTAL_SHEET_KEY in sheets
    assert len(sheets) > 2  # the total and at least two classes to add up


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_total_sheet_has_the_layout_of_a_class_sheet(framework: str) -> None:
    # Arrange
    sheets = _sheets(_sa_results(), framework)
    total = sheets[C07_00_TOTAL_SHEET_KEY]

    # Act
    a_class = next(sheet for key, sheet in sheets.items() if key != C07_00_TOTAL_SHEET_KEY)

    # Assert
    assert total.columns == a_class.columns
    assert total["row_ref"].to_list() == a_class["row_ref"].to_list()
    assert total["row_name"].to_list() == a_class["row_name"].to_list()


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_cell_of_the_total_is_the_sum_of_the_class_sheets(framework: str) -> None:
    """boe_b0713, on every cell rather than the five columns the rule names."""
    # Arrange
    sheets = _sheets(_sa_results_with_substitution(), framework)
    total = sheets[C07_00_TOTAL_SHEET_KEY]
    classes = [sheet for key, sheet in sheets.items() if key != C07_00_TOTAL_SHEET_KEY]
    columns = [column for column in total.columns if column not in _LABELS]

    # Act
    mismatches = []
    for row_ref in total["row_ref"].to_list():
        for column in columns:
            parts = [_cell(sheet, row_ref, column) for sheet in classes]
            reported = [part for part in parts if part is not None]
            expected = sum(reported) if reported else None
            actual = _cell(total, row_ref, column)
            if expected is None or actual is None:
                agrees = expected is actual
            else:
                agrees = actual == pytest.approx(expected)
            if not agrees:
                mismatches.append((row_ref, column, expected, actual))

    # Assert
    assert mismatches == []


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_cell_no_class_reports_is_empty_on_the_total_not_zero(framework: str) -> None:
    """A sum over nothing is not a measured zero: col 0240 is produced on no
    sheet, so it is empty on the Total too."""
    # Arrange / Act
    total = _sheets(_sa_results(), framework)[C07_00_TOTAL_SHEET_KEY]

    # Assert
    assert _cell(total, "0010", "0240") is None


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_substitution_flows_net_to_nothing_across_the_template(framework: str) -> None:
    """500 leaves the corporate sheet and arrives on the institution sheet. On
    the Total the outflow (reported negative) and the inflow cancel, so the net
    exposure after substitution is the net exposure before it."""
    # Arrange / Act
    total = _sheets(_sa_results_with_substitution(), framework)[C07_00_TOTAL_SHEET_KEY]

    # Assert
    assert _cell(total, "0010", "0090") == pytest.approx(-500.0)
    assert _cell(total, "0010", "0100") == pytest.approx(500.0)
    assert _cell(total, "0010", "0110") == pytest.approx(_cell(total, "0010", "0040"))


def test_a_template_with_no_sheets_has_no_total() -> None:
    # Arrange — an IRB-only frame: nothing reports on C 07.00.
    irb_only = _sa_results().with_columns(pl.lit("foundation_irb").alias("approach_applied"))

    # Act
    sheets = _sheets(irb_only, "BASEL_3_1")

    # Assert
    assert sheets == {}


def _two_class_sheets() -> dict[str, pl.DataFrame]:
    """Two hand-built class sheets: an ordinary row, and an equity-transitional
    memorandum row (0371) that only the equity sheet carries."""
    schema = {"row_ref": pl.String, "row_name": pl.String, "0010": pl.Float64, "0220": pl.Float64}
    corporate = pl.DataFrame(
        {
            "row_ref": ["0010", "0371"],
            "row_name": ["TOTAL EXPOSURES", "Equity transitional: SA higher risk"],
            "0010": [100.0, None],
            "0220": [80.0, None],
        },
        schema=schema,
    )
    equity = pl.DataFrame(
        {
            "row_ref": ["0010", "0371"],
            "row_name": ["TOTAL EXPOSURES", "Equity transitional: SA higher risk"],
            "0010": [40.0, 40.0],
            "0220": [100.0, 100.0],
        },
        schema=schema,
    )
    return {"corporate": corporate, "equity": equity}


def test_the_basel_31_total_leaves_out_the_rows_published_for_the_equity_class_alone() -> None:
    """Annex II ¶55A publishes rows 0371-0374 for the equity exposure class only;
    the Total sheet has no cell for them, so the sum is not reported there. No
    registered portfolio fills these rows, which is why this is a hand-built frame."""
    # Arrange
    sheets = _two_class_sheets()

    # Act
    total = c07_total_sheet(sheets, "BASEL_3_1")

    # Assert
    assert total is not None
    assert _cell(total, "0010", "0010") == pytest.approx(140.0)
    assert _cell(total, "0371", "0010") is None
    assert _cell(total, "0371", "0220") is None


def test_the_crr_total_carries_every_row_a_class_sheet_carries() -> None:
    """Nothing is left off the CRR Total: no EBA template is held to say what is."""
    # Arrange
    sheets = _two_class_sheets()

    # Act
    total = c07_total_sheet(sheets, "CRR")

    # Assert
    assert total is not None
    assert _cell(total, "0371", "0010") == pytest.approx(40.0)


def test_the_class_view_is_everything_but_the_total() -> None:
    # Arrange
    sheets = _sheets(_sa_results(), "BASEL_3_1")

    # Act
    classes = c07_class_sheets(sheets)

    # Assert
    assert C07_00_TOTAL_SHEET_KEY not in classes
    assert set(classes) == set(sheets) - {C07_00_TOTAL_SHEET_KEY}


def test_a_cell_on_the_total_sheet_is_explained_as_a_sum_not_as_missing() -> None:
    # Arrange / Act
    reason = summed_sheet_reason("c07_00", C07_00_TOTAL_SHEET_KEY)

    # Assert
    assert reason is not None
    assert "sum of the exposure-class sheets" in reason
    assert summed_sheet_reason("c07_00", "corporate") is None
    assert summed_sheet_reason("c07_00", None) is None
    assert summed_sheet_reason("c08_01", C07_00_TOTAL_SHEET_KEY) is None
