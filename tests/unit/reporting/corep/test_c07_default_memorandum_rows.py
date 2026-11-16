"""OF 07.00 memorandum rows 0300 / 0320: the "in default" class, split by the class before default.

What the rows are (PS1/26 Annex II, ps1-26-annex-ii-reporting-instructions.pdf):

- p.97, row 0320: "Exposures included in the exposure class 'exposures in default',
  subject to Article 127(1)(a) ..., which would otherwise have been assigned to the
  exposure class being reported on if they were not in default." Row 0300 is the same
  with Art. 127(1)(b) and (3).
- p.78-79, ¶54: "Exposures shall be reported in these rows where the obligors would
  have been reported in the exposure classes 'Central governments or central banks',
  'Regional governments or local authorities', 'Public sector entities',
  'Institutions', 'Corporates', 'Retail' and 'Real estate' ... if those exposures were
  not assigned to the exposure classes 'in default'. The figures reported, however,
  are the same as used to calculate the risk-weighted exposure amounts in the
  exposure class 'exposures in default'."

Where they are published: the Bank's taxonomy (v4.1.1, table OF07.00.01.03) carries the
rows on the Total (sheet 0001) and on six class sheets (0002-0004, 0007-0009), and on no
other. It has no real-estate sheet; the Bank's known-issues log (November 2026, issue
#27, 19.10.2026) says: "As a temporary solution, the PRA requests that firms report
exposures assigned to the real estate exposure class in the total sheet s0001 for rows
0300 and 0320 but do not report such exposures separately to this, until the missing
sheet 0010 is provided in the next taxonomy update."

So, on a sealed-shape frame (the aggregator's applied class ``defaulted`` plus the
sealed ``reporting_class_pre_default``): a class sheet's rows 0300 / 0320 are the
in-default legs whose class before default is that class; the Total is every in-default
leg once; nothing is reported on a sheet the template has no cell on. CRR is untouched.

The frames are sealed-shape on purpose. ``test_c07.py::TestC0700MemorandumRows`` builds
its defaulted legs as ``exposure_class == "corporate"`` with ``default_status`` set and no
applied-class overlay — a shape the aggregator cannot produce, because it moves every
defaulted standardised leg to the ``defaulted`` class (Art. 112(1)(j)).

References:
- PRA PS1/26 Annex II §3.2.5 ¶52-55 (pp.78-79) and rows 0300 / 0320 (p.97);
  Art. 112(1)(j), Art. 127
- Bank of England Banking Taxonomy v4.1.1, table OF07.00.01.03; known-issues log
  (November 2026), issue #27
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import (
    C07_00_SA_SHEET_MAP,
    C07_00_TOTAL_SHEET_KEY,
    get_sa_row_sections,
)
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

B31 = "BASEL_3_1"
PRE_DEFAULT_COL = "reporting_class_pre_default"
MEMO_ROWS = ("0300", "0320")
ROW_TOTAL = "0010"
ROW_ON_BALANCE_SHEET = "0070"
COL_ORIGINAL = "0010"
COL_EXPOSURE_VALUE = "0200"
COL_RWEA = "0220"

IN_DEFAULT = C07_00_SA_SHEET_MAP["defaulted"]
CORPORATE = C07_00_SA_SHEET_MAP["corporate"]
RETAIL = C07_00_SA_SHEET_MAP["retail_other"]
INSTITUTION = C07_00_SA_SHEET_MAP["institution"]
REAL_ESTATE = C07_00_SA_SHEET_MAP["residential_mortgage"]


def _leg(  # noqa: PLR0913 - one ledger row, every field named
    reference: str,
    routing_class: str,
    pre_default: str,
    risk_weight: float,
    amount: float,
    *,
    defaulted: bool = True,
) -> dict[str, object]:
    """One drawn, uncollateralised standardised leg as the aggregator seals it."""
    return {
        "exposure_reference": reference,
        "approach_applied": "standardised",
        "exposure_type": "loan",
        "exposure_class": routing_class,
        "exposure_class_applied": "defaulted" if defaulted else pre_default,
        PRE_DEFAULT_COL: pre_default,
        "is_defaulted": defaulted,
        "risk_weight": risk_weight,
        "drawn_amount": amount,
        "ead_final": amount,
        "rwa_final": amount * risk_weight,
    }


#: Five in-default legs, one performing corporate and one performing mortgage.
#: ``D-INST`` is the only institution exposure, so its sheet exists for the
#: memorandum row alone; ``LIVE-RRE`` opens the real-estate sheet, so the test
#: that nothing is reported there in rows 0300 / 0320 has a sheet to look at.
LEGS: tuple[dict[str, object], ...] = (
    _leg("D-CORP", "corporate", "corporate", 1.5, 1_000.0),
    _leg("D-RET", "corporate_sme", "retail_other", 1.0, 400.0),
    _leg("D-INST", "institution", "institution", 1.5, 300.0),
    _leg("D-RRE", "residential_mortgage", "residential_mortgage", 1.0, 200.0),
    _leg("D-CRE", "corporate", "commercial_mortgage", 1.5, 500.0),
    _leg("LIVE-CORP", "corporate", "corporate", 1.0, 2_000.0, defaulted=False),
    _leg("LIVE-RRE", "residential_mortgage", "residential_mortgage", 0.2, 600.0, defaulted=False),
)


def _frame(legs: tuple[dict[str, object], ...] = LEGS) -> pl.LazyFrame:
    return pl.LazyFrame(list(legs))


def _sheets(results: pl.LazyFrame, framework: str = B31) -> dict[str, pl.DataFrame]:
    return LedgerShimCorepGenerator().generate_from_lazyframe(results, framework=framework).c07_00


def _cell(sheets: dict[str, pl.DataFrame], sheet: str, row_ref: str, column: str) -> float | None:
    assert sheet in sheets, f"sheet {sheet!r} not emitted; got {sorted(sheets)}"
    matched = sheets[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected one row {row_ref}, got {matched.height}"
    return matched[column][0]


def _band_row(label: str) -> str:
    """The risk-weight row of ``label`` (section 2 of the layout), not spelled here."""
    rows = get_sa_row_sections(B31)[2].rows
    return next(row.ref for row in rows if row.name == label)


def _amount(*references: str) -> float:
    return sum(float(leg["ead_final"]) for leg in LEGS if leg["exposure_reference"] in references)


def _rwea(*references: str) -> float:
    return sum(float(leg["rwa_final"]) for leg in LEGS if leg["exposure_reference"] in references)


@pytest.mark.parametrize(
    ("sheet", "row_ref", "references"),
    [
        (CORPORATE, "0320", ("D-CORP",)),
        (RETAIL, "0300", ("D-RET",)),
        (INSTITUTION, "0320", ("D-INST",)),
    ],
)
@pytest.mark.parametrize("column", [COL_ORIGINAL, COL_EXPOSURE_VALUE])
def test_an_in_default_leg_is_reported_on_the_sheet_of_its_class_before_default(
    sheet: str, row_ref: str, references: tuple[str, ...], column: str
) -> None:
    # Arrange / Act
    sheets = _sheets(_frame())

    # Assert
    assert _cell(sheets, sheet, row_ref, column) == pytest.approx(_amount(*references))
    assert _cell(sheets, sheet, row_ref, COL_RWEA) == pytest.approx(_rwea(*references))


@pytest.mark.parametrize("sheet", [CORPORATE, RETAIL, INSTITUTION])
def test_a_class_sheet_does_not_carry_the_other_memorandum_row(sheet: str) -> None:
    """D-RET is the only 100% leg and sits on retail; the other two are 150%."""
    # Arrange
    other = {CORPORATE: "0300", RETAIL: "0320", INSTITUTION: "0300"}[sheet]

    # Act
    sheets = _sheets(_frame())

    # Assert
    assert _cell(sheets, sheet, other, COL_EXPOSURE_VALUE) is None


@pytest.mark.parametrize("sheet", [IN_DEFAULT, REAL_ESTATE])
@pytest.mark.parametrize("row_ref", MEMO_ROWS)
def test_nothing_is_reported_on_a_sheet_the_template_publishes_no_memorandum_row_on(
    sheet: str, row_ref: str
) -> None:
    """The 'in default' sheet (its figure IS the Total's data point) and real estate
    (no sheet 0010 in table OF07.00.01.03; known-issues log #27)."""
    # Arrange / Act
    sheets = _sheets(_frame())

    # Assert
    assert sheet in sheets, f"sheet {sheet!r} not emitted - nothing to assert on"
    row = sheets[sheet].filter(pl.col("row_ref") == row_ref).drop("row_ref", "row_name")
    assert row.null_count().row(0) == (1,) * row.width, f"{sheet} r{row_ref}: {row}"


@pytest.mark.parametrize(("risk_weight", "row_ref"), [(1.0, "0300"), (1.5, "0320")])
def test_a_defaulted_high_risk_leg_is_in_neither_memorandum_row(
    risk_weight: float, row_ref: str
) -> None:
    """A defaulted high-risk exposure stays in class (k): it is not in "exposures in default".

    Art. 112(2) Table A2 ranks items of particularly high risk above exposures in
    default, so the aggregator keeps such a leg's applied class ``high_risk``. Rows
    0300 / 0320 report exposures "included in the exposure class 'exposures in
    default'" (p.97), and the Total's data point is that class, so the leg is in
    neither row on its own sheet nor on the Total — although it is defaulted and
    weighted at an Art. 127 rung. (Row 0015, "of which: defaulted", is where it
    does show, on the high-risk sheet.)
    """
    # Arrange
    high_risk = {
        **_leg("D-HR", "high_risk", "high_risk", risk_weight, 700.0),
        "exposure_class_applied": "high_risk",
    }
    in_default = ("D-RET", "D-RRE") if row_ref == "0300" else ("D-CORP", "D-INST", "D-CRE")

    # Act
    sheets = _sheets(_frame((*LEGS, high_risk)))

    # Assert
    assert _cell(sheets, "high_risk", ROW_TOTAL, COL_EXPOSURE_VALUE) == pytest.approx(700.0)
    assert _cell(sheets, "high_risk", "0015", COL_EXPOSURE_VALUE) == pytest.approx(700.0)
    assert _cell(sheets, "high_risk", row_ref, COL_EXPOSURE_VALUE) is None
    assert _cell(sheets, C07_00_TOTAL_SHEET_KEY, row_ref, COL_EXPOSURE_VALUE) == pytest.approx(
        _amount(*in_default)
    )


@pytest.mark.parametrize(
    ("row_ref", "references"),
    [
        ("0300", ("D-RET", "D-RRE")),
        ("0320", ("D-CORP", "D-INST", "D-CRE")),
    ],
)
@pytest.mark.parametrize("column", [COL_ORIGINAL, COL_EXPOSURE_VALUE])
def test_the_total_is_every_in_default_leg_once(
    row_ref: str, references: tuple[str, ...], column: str
) -> None:
    """Real-estate-origin defaults (D-RRE, D-CRE) are on the Total and nowhere else."""
    # Arrange / Act
    sheets = _sheets(_frame())

    # Assert
    total = sheets[C07_00_TOTAL_SHEET_KEY]
    assert _cell({"t": total}, "t", row_ref, column) == pytest.approx(_amount(*references))
    assert _cell({"t": total}, "t", row_ref, COL_RWEA) == pytest.approx(_rwea(*references))


@pytest.mark.parametrize("row_ref", [ROW_ON_BALANCE_SHEET, _band_row("150%"), _band_row("100%")])
def test_a_memorandum_leg_does_not_populate_the_sheets_other_rows(row_ref: str) -> None:
    """The institution sheet holds nothing but D-INST's memorandum row, so every other
    constrained row is empty there — null, not a row of zeros."""
    # Arrange / Act
    sheets = _sheets(_frame())

    # Assert
    row = sheets[INSTITUTION].filter(pl.col("row_ref") == row_ref).drop("row_ref", "row_name")
    assert row.null_count().row(0) == (1,) * row.width, f"r{row_ref}: {row}"


def test_a_class_with_no_live_exposure_still_opens_its_sheet_for_the_memorandum_row() -> None:
    # Arrange / Act
    sheets = _sheets(_frame())

    # Assert
    assert INSTITUTION in sheets
    assert _cell(sheets, INSTITUTION, ROW_TOTAL, COL_EXPOSURE_VALUE) == pytest.approx(0.0)


def test_the_corporate_sheet_keeps_its_own_risk_weight_rows() -> None:
    """LIVE-CORP is the corporate sheet's own leg; D-CORP is a memorandum leg there."""
    # Arrange / Act
    sheets = _sheets(_frame())

    # Assert
    assert _cell(sheets, CORPORATE, _band_row("100%"), COL_EXPOSURE_VALUE) == pytest.approx(
        _amount("LIVE-CORP")
    )
    assert _cell(sheets, CORPORATE, _band_row("150%"), COL_EXPOSURE_VALUE) is None
    assert _cell(sheets, CORPORATE, ROW_TOTAL, COL_EXPOSURE_VALUE) == pytest.approx(
        _amount("LIVE-CORP")
    )


def test_without_the_sealed_column_the_in_default_sheet_still_reports_no_memorandum_row() -> None:
    """A frame with no ``reporting_class_pre_default`` cannot split the class, so the
    rows stay on the legs' own sheet — but the 'in default' sheet has no cell for them
    whatever the frame holds, and the Total still carries every in-default leg."""
    # Arrange
    results = _frame().drop(PRE_DEFAULT_COL)

    # Act
    sheets = _sheets(results)

    # Assert
    assert _cell(sheets, IN_DEFAULT, "0320", COL_EXPOSURE_VALUE) is None
    assert _cell(sheets, C07_00_TOTAL_SHEET_KEY, "0320", COL_EXPOSURE_VALUE) == pytest.approx(
        _amount("D-CORP", "D-INST", "D-CRE")
    )
    assert _cell(sheets, CORPORATE, "0320", COL_EXPOSURE_VALUE) is None


def test_crr_ignores_the_class_before_default() -> None:
    """CRR's C 07.00 rows 0300 / 0320 are another question (the CRR half of P1.377):
    the sealed column changes nothing there."""
    # Arrange
    with_column = _sheets(_frame(), "CRR")

    # Act
    without_column = _sheets(_frame().drop(PRE_DEFAULT_COL), "CRR")

    # Assert
    assert set(with_column) == set(without_column)
    for key, sheet in with_column.items():
        assert sheet.equals(without_column[key]), key
    assert _cell(with_column, IN_DEFAULT, "0320", COL_EXPOSURE_VALUE) == pytest.approx(
        _amount("D-CORP", "D-INST", "D-CRE")
    )
