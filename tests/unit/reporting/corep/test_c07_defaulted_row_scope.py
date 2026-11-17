"""C 07.00 / OF 07.00 row 0015 is reported only on the sheets Annex II names.

Row 0015 is "of which: Defaulted exposures" in the exposure classes that KEEP a
defaulted exposure instead of moving it to the "exposures in default" class.

- CRR COREP Annex II (C 07.00, p.91): "This row shall only be reported in
  exposure classes 'Items associated with a particular high risk' and 'Equity
  exposures'."
- PS1/26 Annex II (OF 07.00, p.88): "Only exposures in exposure classes
  'exposures associated with particularly high risk', 'subordinated debt,
  equity and other own funds instruments', and 'exposures in the form of units
  or shares in collective investment undertakings ('CIUs')' shall be reported
  in this row if they are in default."

The published rules state the same scope as a must-be-blank list: EBA
``v4721_m`` / ``v4722_m`` (CRR) and the Bank's ``boe_b0431`` / ``boe_b1069``
(Basel 3.1). Until O-05 the row keyed on the defaulted flag alone, so it lit on
the "in default" sheet, on any sheet a defaulted leg landed on, and through them
on the Total.

The synthetic book gives EVERY sheet one defaulted and one performing leg, with a
different defaulted amount per sheet, so a blank row on a sheet outside the
regime's set is the scope and not an empty book, and the Total can tell which
sheets it added up. The expected sets are literals here, not read back from the
production getter: a test written from the same declaration proves nothing
(LESSONS B3). ``tests/contracts/test_c07_defaulted_row_published_sheets.py``
anchors the declaration to the published rules' own sheet lists.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import C07_00_TOTAL_SHEET_KEY
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

# Sheet key -> (exposure value, RWEA) of that sheet's one DEFAULTED leg.
_DEFAULTED: dict[str, tuple[float, float]] = {
    "corporate": (800.0, 1200.0),
    "defaulted": (700.0, 1050.0),
    "high_risk": (600.0, 900.0),
    "equity": (500.0, 1250.0),
    "ciu": (400.0, 600.0),
}
# Every sheet also holds one performing leg of this size at 100%.
_PERFORMING: float = 1000.0

# The classes each Annex II names for row 0015 (module docstring).
_ALLOWED: dict[str, frozenset[str]] = {
    "CRR": frozenset({"high_risk", "equity"}),
    "BASEL_3_1": frozenset({"high_risk", "equity", "ciu"}),
}
_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")
_LABEL_COLS: frozenset[str] = frozenset({"row_ref", "row_name"})


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_row_0015_is_blank_on_every_sheet_annex_ii_does_not_name(framework: str) -> None:
    # Arrange
    sheets = _c07(framework)
    outside = sorted(set(_DEFAULTED) - _ALLOWED[framework])

    # Act / Assert
    assert set(_DEFAULTED) <= set(sheets), sorted(sheets)
    for key in outside:
        assert _row(sheets[key], "0010")["0200"] == pytest.approx(
            _DEFAULTED[key][0] + _PERFORMING
        ), f"adequacy: the {key!r} sheet must hold its defaulted leg, or blank proves nothing"
        populated = _populated(_row(sheets[key], "0015"))
        assert not populated, f"[{framework}] row 0015 reports on the {key!r} sheet: {populated}"


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_row_0015_reports_the_defaulted_leg_on_the_sheets_annex_ii_names(framework: str) -> None:
    # Arrange
    sheets = _c07(framework)

    # Act / Assert - the leg that must SURVIVE the scope, which is what tells
    # a scoped row apart from one blanked everywhere.
    for key in sorted(_ALLOWED[framework]):
        row = _row(sheets[key], "0015")
        assert row["0200"] == pytest.approx(_DEFAULTED[key][0]), (framework, key)
        assert row["0220"] == pytest.approx(_DEFAULTED[key][1]), (framework, key)


@pytest.mark.parametrize(
    ("framework", "exposure_value", "rwea"),
    [
        ("CRR", 600.0 + 500.0, 900.0 + 1250.0),
        ("BASEL_3_1", 600.0 + 500.0 + 400.0, 900.0 + 1250.0 + 600.0),
    ],
)
def test_the_total_sheet_row_0015_adds_up_the_named_classes_only(
    framework: str, exposure_value: float, rwea: float
) -> None:
    # Arrange
    sheets = _c07(framework)

    # Act
    row = _row(sheets[C07_00_TOTAL_SHEET_KEY], "0015")

    # Assert
    assert row["0200"] == pytest.approx(exposure_value)
    assert row["0220"] == pytest.approx(rwea)


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_row_0015_stays_blank_on_a_named_sheet_without_a_default_carrier(framework: str) -> None:
    # Arrange - the same book with no default identification column at all
    frame = _frame().drop("default_status")

    # Act
    sheets = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=framework).c07_00

    # Assert
    assert _row(sheets["high_risk"], "0010")["0200"] == pytest.approx(600.0 + _PERFORMING)
    assert not _populated(_row(sheets["high_risk"], "0015"))


def _c07(framework: str) -> dict[str, pl.DataFrame]:
    return LedgerShimCorepGenerator().generate_from_lazyframe(_frame(), framework=framework).c07_00


def _frame() -> pl.LazyFrame:
    """One defaulted and one performing SA leg per sheet in ``_DEFAULTED``."""
    refs: list[str] = []
    classes: list[str] = []
    ead: list[float] = []
    rwa: list[float] = []
    flags: list[bool] = []
    for sheet, (exposure_value, rwea) in _DEFAULTED.items():
        refs += [f"{sheet}_DEF", f"{sheet}_PERF"]
        classes += [sheet, sheet]
        ead += [exposure_value, _PERFORMING]
        rwa += [rwea, _PERFORMING]
        flags += [True, False]
    n = len(refs)
    return pl.LazyFrame(
        {
            "exposure_reference": refs,
            "approach_applied": ["standardised"] * n,
            "exposure_class": classes,
            "exposure_class_applied": classes,
            "drawn_amount": ead,
            "undrawn_amount": [0.0] * n,
            "ead_final": ead,
            "rwa_final": rwa,
            "risk_weight": [r / e for e, r in zip(ead, rwa, strict=True)],
            "default_status": flags,
            "counterparty_reference": [f"CP_{i}" for i in range(n)],
        }
    )


def _row(frame: pl.DataFrame, ref: str) -> dict[str, object]:
    row = frame.filter(pl.col("row_ref") == ref)
    assert row.height == 1, f"row {ref} appears {row.height} times"
    return row.row(0, named=True)


def _populated(row: dict[str, object]) -> dict[str, object]:
    return {col: v for col, v in row.items() if col not in _LABEL_COLS and v is not None}
