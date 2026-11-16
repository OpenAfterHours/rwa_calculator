"""
OF 07.00 reports transitional equity against its Article 133 weight, and on sheet 0016 only.

Pipeline position:
    hand-built sealed-exit frame -> LedgerShimCorepGenerator -> c07_00["equity" | "ciu"]

The rule (PS1/26 Annex II, ps1-26-annex-ii-reporting-instructions.pdf):

- p.95, rows 0140-0280: "Equity exposures (including higher risk equity
  exposures) in the exposure class 'subordinated debt, equity and other own
  funds instruments' subject to the transitional provisions in Rules 4.1 to
  4.10 of the Credit Risk General Provisions (CRR) Part shall be reported
  against the risk weights set out in Article 133 of the Credit Risk:
  Standardised Approach (CRR) Part disregarding the transitional provisions.
  However, the RWEA shall still reflect the transitional provisions."
- p.96, row 0250 / row 0261: such exposures "should be reported in this row
  during the transitional period" if they are an equity exposure under
  Article 133(1) and (2) / a higher risk equity exposure.
- p.79, ¶55A: "Firms shall only report the memorandum items in rows 0371-0374
  for the following exposure class: (a) subordinated debt, equity and other own
  funds instruments"; p.98: "The reporting of the memorandum items in rows 0371
  to 0374 shall not affect their reporting in rows 0250 and 0261."

So the band row is read off ``risk_weight_pre_equity_transitional`` (the
Article 133 weight the equity calculator replaced) where it is set, and off
``risk_weight`` everywhere else; col 0220 keeps the transitional RWEA. The
weights here are the rules 4.2 / 4.3 2027 weights (160% / 220%) and the rule
4.6 higher-of for an IRB firm (max(290%, 160%), max(370%, 220%)); none of them
is a row of the template, which is the whole point — banded on the applied
weight every one falls to row 0280 "Other risk weights".

References:
- PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.1-4.6
- PS1/26 Art. 133(3)-(5)
- PS1/26 Annex II OF 07.00 rows 0240-0280, 0371-0374; ¶55A-55D
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import get_sa_risk_weight_bands, get_sa_row_sections
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

#: The equity calculator's carrier: the Article 133 weight rules 4.2 / 4.3 replaced.
_EQUITY_ART133_RW_COL = "risk_weight_pre_equity_transitional"

# leg: (reference, class, EAD, applied RW, Art. 133 RW replaced, transitional label, higher risk)
_LEGS: tuple[tuple[str, str, float, float, float | None, str | None, bool | None], ...] = (
    ("EQ_SA_OTHER", "equity", 1000.0, 1.60, 2.50, "sa_transitional", False),  # rule 4.2(1)
    ("EQ_SA_HIGHER", "equity", 500.0, 2.20, 4.00, "sa_transitional", True),  # rule 4.3(1)
    ("EQ_IRB_OTHER", "equity", 300.0, 2.90, 2.50, "irb_transitional", False),  # rule 4.6
    ("EQ_IRB_HIGHER", "equity", 200.0, 3.70, 4.00, "irb_transitional", True),  # rule 4.6
    ("EQ_SUB_DEBT", "equity", 700.0, 1.50, None, None, None),  # Art. 133(5)
    ("EQ_END_STATE", "equity", 400.0, 2.50, None, None, None),  # Art. 133(3), not transitional
)

#: The leg in row 0250 that is not under the transitional rules.
_UNLABELLED_IN_ROW_0250: float = 400.0


def _results(legs: tuple[tuple, ...] = _LEGS, *, with_carrier: bool = True) -> pl.LazyFrame:
    n = len(legs)
    frame: dict[str, object] = {
        "exposure_reference": [leg[0] for leg in legs],
        "approach_applied": ["standardised"] * n,
        "exposure_class": [leg[1] for leg in legs],
        "drawn_amount": [leg[2] for leg in legs],
        "undrawn_amount": [0.0] * n,
        "ead_final": [leg[2] for leg in legs],
        "risk_weight": [leg[3] for leg in legs],
        "rwa_final": [leg[2] * leg[3] for leg in legs],
        "scra_provision_amount": [0.0] * n,
        "gcra_provision_amount": [0.0] * n,
        "collateral_adjusted_value": [0.0] * n,
        "guaranteed_portion": [0.0] * n,
        "sa_cqs": pl.Series([None] * n, dtype=pl.Int32),
        "counterparty_reference": [f"CP_{i}" for i in range(n)],
        "equity_transitional_approach": pl.Series([leg[5] for leg in legs], dtype=pl.String),
        "equity_higher_risk": pl.Series([leg[6] for leg in legs], dtype=pl.Boolean),
    }
    if with_carrier:
        frame[_EQUITY_ART133_RW_COL] = pl.Series([leg[4] for leg in legs], dtype=pl.Float64)
    return pl.LazyFrame(frame)


def _sheet(framework: str, sheet: str, results: pl.LazyFrame | None = None) -> pl.DataFrame:
    frame = _results() if results is None else results
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=framework)
    assert sheet in bundle.c07_00, f"sheet {sheet!r} not emitted; got {sorted(bundle.c07_00)}"
    return bundle.c07_00[sheet]


def _cell(sheet: pl.DataFrame, row_ref: str, column: str) -> float | None:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"expected one row {row_ref}, got {row.height}"
    return row[column][0]


@pytest.fixture(scope="module")
def equity_sheet() -> pl.DataFrame:
    return _sheet("BASEL_3_1", "equity")


# ---------------------------------------------------------------------------
# The band rows (section 2): the Article 133 row, the transitional RWEA
# ---------------------------------------------------------------------------


def test_the_frame_holds_legs_whose_applied_weight_is_no_row_of_the_template() -> None:
    """Adequacy (LESSONS C11): without an off-ladder weight the band tests prove nothing."""
    ladder = {round(rw, 4) for rw, _label in get_sa_risk_weight_bands("BASEL_3_1")}
    off_ladder = [leg[0] for leg in _LEGS if round(leg[3], 4) not in ladder]

    assert len(off_ladder) == 4, off_ladder


def test_transitional_equity_is_reported_in_the_250_percent_row(
    equity_sheet: pl.DataFrame,
) -> None:
    # 1,000 (rule 4.2 at 160%) + 300 (rule 4.6 at 290%) + 400 (Art. 133(3) at 250%)
    assert _cell(equity_sheet, "0250", "0200") == pytest.approx(1700.0)
    # "the RWEA shall still reflect the transitional provisions": 1,600 + 870 + 1,000
    assert _cell(equity_sheet, "0250", "0220") == pytest.approx(3470.0)


def test_transitional_higher_risk_equity_is_reported_in_the_400_percent_row(
    equity_sheet: pl.DataFrame,
) -> None:
    assert _cell(equity_sheet, "0261", "0200") == pytest.approx(700.0)  # 500 + 200
    assert _cell(equity_sheet, "0261", "0220") == pytest.approx(1840.0)  # 1,100 + 740


def test_no_equity_is_reported_against_other_risk_weights(equity_sheet: pl.DataFrame) -> None:
    """Row 0280 on sheet 0016 is a cell the Bank's ``boe_b0458`` requires empty."""
    assert _cell(equity_sheet, "0280", "0200") is None
    assert _cell(equity_sheet, "0280", "0220") is None


def test_subordinated_debt_keeps_its_own_150_percent_row(equity_sheet: pl.DataFrame) -> None:
    assert _cell(equity_sheet, "0240", "0200") == pytest.approx(700.0)
    assert _cell(equity_sheet, "0240", "0220") == pytest.approx(1050.0)


@pytest.mark.parametrize("column", ["0200", "0220"])
def test_the_risk_weight_rows_still_foot_to_the_total(
    equity_sheet: pl.DataFrame, column: str
) -> None:
    banded = sum(
        float(_cell(equity_sheet, ref, column) or 0.0) for ref in ("0240", "0250", "0261", "0280")
    )

    assert banded == pytest.approx(_cell(equity_sheet, "0010", column))


def test_a_frame_without_the_carrier_bands_on_the_applied_weight() -> None:
    """Absent carrier (an equity-free or CRR run): the ladder reads ``risk_weight`` as before.

    The two Art. 133 legs keep their rows and the four transitional legs fall to
    the catch-all, which is the pre-carrier behaviour and the fail-safe one
    (reported, never dropped).
    """
    sheet = _sheet("BASEL_3_1", "equity", _results(with_carrier=False))

    assert _cell(sheet, "0250", "0200") == pytest.approx(_UNLABELLED_IN_ROW_0250)
    assert _cell(sheet, "0280", "0200") == pytest.approx(2000.0)  # 1,000 + 500 + 300 + 200


@pytest.mark.parametrize("column", ["0200", "0220"])
def test_under_crr_the_band_rows_still_foot_to_the_total(column: str) -> None:
    """CRR control: the ladder has no 400% row, so a 4.00 carrier must still land somewhere.

    Coalescing into the ladder (rather than writing a row name) keeps the
    catch-all: whatever the carrier says, every leg is on exactly one band row.
    """
    sheet = _sheet("CRR", "equity")
    band_refs = [
        row.ref for row in get_sa_row_sections("CRR")[2].rows if row.ref != "0010"
    ]  # section 2 = the risk-weight breakdown

    banded = sum(float(_cell(sheet, ref, column) or 0.0) for ref in band_refs)

    assert banded == pytest.approx(_cell(sheet, "0010", column))


@pytest.mark.parametrize(("weight", "row_ref"), [(2.50, "0250"), (4.00, "0261")])
def test_the_article_133_weights_are_rungs_of_the_basel_3_1_ladder(
    weight: float, row_ref: str
) -> None:
    """The carrier's two values name rows 0250 / 0261 in the published row sections.

    Anchored to the row section, not to the band list alone (LESSONS B3): the
    band label is what ``c07_rw_band`` keys and the row NAME is what the row
    predicate matches, so both must agree for the leg to land.
    """
    labels = dict(get_sa_risk_weight_bands("BASEL_3_1"))
    rows = {row.ref: row.name for row in get_sa_row_sections("BASEL_3_1")[2].rows}

    assert labels[weight] == rows[row_ref]


# ---------------------------------------------------------------------------
# The memorandum rows (section 5): the same legs, repeated, on sheet 0016 only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row_ref", "exposure", "rwea"),
    [
        ("0371", 500.0, 1100.0),
        ("0372", 1000.0, 1600.0),
        ("0373", 200.0, 740.0),
        ("0374", 300.0, 870.0),
    ],
)
def test_the_memorandum_rows_report_the_transitional_legs(
    equity_sheet: pl.DataFrame, row_ref: str, exposure: float, rwea: float
) -> None:
    assert _cell(equity_sheet, row_ref, "0200") == pytest.approx(exposure)
    assert _cell(equity_sheet, row_ref, "0220") == pytest.approx(rwea)


def test_the_memorandum_rows_do_not_move_the_legs_off_rows_0250_and_0261(
    equity_sheet: pl.DataFrame,
) -> None:
    """p.98: memo rows "shall not affect their reporting in rows 0250 and 0261"."""
    other = _cell(equity_sheet, "0372", "0200") + _cell(equity_sheet, "0374", "0200")
    higher = _cell(equity_sheet, "0371", "0200") + _cell(equity_sheet, "0373", "0200")

    assert other == pytest.approx(_cell(equity_sheet, "0250", "0200") - _UNLABELLED_IN_ROW_0250)
    assert higher == pytest.approx(_cell(equity_sheet, "0261", "0200"))


_CIU_LEGS: tuple[tuple, ...] = (
    ("EQ_LISTED", "equity", 1000.0, 1.60, 2.50, "sa_transitional", False),
    # A CIU carrying a transitional label: the calculator does not write one,
    # but nothing in the template may let a class (o) leg light a row that
    # ¶55A gives to class (p) alone and the Bank publishes on sheet 0016 only.
    ("CIU_FALLBACK", "ciu", 200.0, 12.50, None, "sa_transitional", False),
)


@pytest.mark.parametrize("row_ref", ["0371", "0372", "0373", "0374"])
@pytest.mark.parametrize("column", ["0010", "0200", "0220"])
def test_no_other_class_sheet_carries_an_equity_memorandum_row(row_ref: str, column: str) -> None:
    sheet = _sheet("BASEL_3_1", "ciu", _results(_CIU_LEGS))

    assert _cell(sheet, row_ref, column) is None


def test_the_equity_sheet_still_carries_its_memorandum_row() -> None:
    """The survivor beside the scoped-out CIU (LESSONS B5's two legs)."""
    sheet = _sheet("BASEL_3_1", "equity", _results(_CIU_LEGS))

    assert _cell(sheet, "0372", "0200") == pytest.approx(1000.0)
