"""
The C 07.00 "Breakdown by Risk Weights" rows are LIT, and lit non-trivially.

Pipeline position:
    reporting_sa_classes_portfolio -> PipelineOrchestrator -> COREPGenerator
        -> C 07.00 / OF 07.00 per-class sheets -> the row (y) axis

Why this exists — it is a vacuity gate, not a value gate
--------------------------------------------------------
C 07.00 rows 0140-0280 break each class sheet down by the exposure's own risk
weight, and Annex II writes a per-row identity over them: col 0220 (RWEA) equals
col 0200 (exposure value after CRM and CCF) times the weight the row's LABEL
names. 48 published supervisory rules are of that shape.

A rule of that shape over a row carrying NULL is reported VACUOUS: it "holds"
while asserting nothing, which is indistinguishable from a pass in every gate
that counts statuses. Measured on this portfolio before the four ``*_RW20`` /
``*_RW150`` rows existed, the CRR sheets lit four of the fifteen rungs — 0140,
0170, 0200, 0230 — so every rule scoped to 20% or 150% was vacuous on every
sheet, on the one portfolio built to cover the SA class axis.

The golden gate cannot replace this. A golden asserts that today's numbers equal
the numbers captured yesterday; it says nothing about whether a row carries a
figure at all, and a golden captured over a dark row freezes the darkness in.
That is the ``B5`` trap in its cell-granular form: registered portfolio, dead
cell, green suite.

What is asserted, and why each part is load-bearing
---------------------------------------------------
1. The row is live — ``c0200`` and ``c0220`` both carry a figure. Without this
   the remaining assertions are vacuous in exactly the way being guarded against.
2. The Annex II identity holds: ``c0220 == c0200 * rw``.
3. The identity is NON-TRIVIAL: ``c0200 != c0220``, so a defect that swapped,
   aliased or duplicated the two columns fails. At 100% the two are numerically
   equal and such a defect is invisible — which is precisely the state the
   ``corporate`` sheet was in when its only rung was 0230.
4. Each touched sheet foots as a genuine ADDITION: more than one rung is live, so
   ``r0010`` is a sum of several terms rather than a copy of one.

References:
- COREP Annex II, C 07.00: "Breakdown by risk weights"; col 0200 exposure value
  after CRM and CCF, col 0220 risk-weighted exposure amount
- CRR Art. 117(1) (MDB), Art. 116(2) (PSE), Art. 122(1) (corporate),
  Art. 129(4) (covered bonds); PRA PS1/26 counterparts
- tests/fixtures/reporting_sa_classes_portfolio.py: the portfolio and the
  ``SA_CLASS_EXPECTED_RW_ROW`` / ``SA_CLASS_EXPECTED_RW`` design tables
- .claude/LESSONS.md B5: a dead cell keeps a registered portfolio's gate green
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_sa_classes_portfolio import (
    SA_CLASS_EXPECTED_RW,
    SA_CLASS_EXPECTED_RW_ROW,
    SA_CLASS_EXPECTED_SHEET,
    build_reporting_sa_classes_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

#: regime key -> (framework string, index into the (CRR, B3.1) expectation pairs)
_REGIMES: dict[str, tuple[str, int]] = {"crr": ("CRR", 0), "b31": ("BASEL_3_1", 1)}

#: Exposure value and RWEA are sums of exact table products, so the only
#: tolerance needed is float addition noise on millions.
_MONEY_TOLERANCE: float = 1e-6


def _config(regime_key: str) -> CalculationConfig:
    """Match ``test_reporting_sa_classes_golden`` exactly — same runs, same cells."""
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


@pytest.fixture(scope="module")
def c07_sheets() -> dict[str, dict[str, pl.DataFrame]]:
    """regime key -> sheet key -> the C 07.00 frame, for both regimes.

    Module-scoped: two pipeline runs serve every test below.
    """
    built: dict[str, dict[str, pl.DataFrame]] = {}
    for regime_key, (framework, _index) in _REGIMES.items():
        result = PipelineOrchestrator().run_with_data(
            build_reporting_sa_classes_bundle(), _config(regime_key)
        )
        corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
        built[regime_key] = {
            sheet: frame for sheet, frame in corep.c07_00.items() if isinstance(frame, pl.DataFrame)
        }
    return built


def _cells(frame: pl.DataFrame, row_ref: str) -> dict[str, float | None]:
    """The one row's cells, keyed by column ref. Empty dict if the row is absent."""
    matched = frame.filter(pl.col("row_ref") == row_ref)
    if matched.height == 0:
        return {}
    return matched.row(0, named=True)


# =============================================================================
# The design tables' own coherence
# =============================================================================


def test_the_risk_weight_row_table_agrees_with_the_other_design_tables() -> None:
    """Every ``SA_CLASS_EXPECTED_RW_ROW`` key is described by the other two tables.

    Found by probing this file's failability: pointing the row table at an
    exposure absent from ``SA_CLASS_EXPECTED_RW`` made four tests fail with a bare
    ``KeyError``, which reads as a broken test rather than as a broken fixture.
    Asserting the three tables share a vocabulary turns that into one legible
    failure, ahead of the tests that would otherwise raise.

    Arrange: the three fixture design tables.
    Act:     compare their key sets.
    Assert:  the row table's keys are described by both of the others.
    """
    # Arrange / Act
    row_keys = set(SA_CLASS_EXPECTED_RW_ROW)
    missing_rw = sorted(row_keys - set(SA_CLASS_EXPECTED_RW))
    missing_sheet = sorted(row_keys - set(SA_CLASS_EXPECTED_SHEET))

    # Assert
    assert not missing_rw, (
        f"SA_CLASS_EXPECTED_RW_ROW names exposure(s) with no expected risk weight: "
        f"{missing_rw} — add them to SA_CLASS_EXPECTED_RW"
    )
    assert not missing_sheet, (
        f"SA_CLASS_EXPECTED_RW_ROW names exposure(s) with no expected sheet: "
        f"{missing_sheet} — add them to SA_CLASS_EXPECTED_SHEET"
    )


# =============================================================================
# The vacuity gate
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
@pytest.mark.parametrize("exposure_ref", list(SA_CLASS_EXPECTED_RW_ROW))
def test_risk_weight_row_carries_a_figure(
    c07_sheets: dict[str, dict[str, pl.DataFrame]], regime_key: str, exposure_ref: str
) -> None:
    """The rung this exposure exists to light is not NULL.

    A NULL here sends every published ``c0220 = c0200 x RW`` rule over the row
    back to VACUOUS, which no status-counting gate distinguishes from a pass.

    Arrange: the SA quasi-sovereign portfolio under one regime.
    Act:     read the exposure's intended sheet and rung.
    Assert:  cols 0200 and 0220 both carry a figure.
    """
    # Arrange
    index = _REGIMES[regime_key][1]
    sheet_key = SA_CLASS_EXPECTED_SHEET[exposure_ref]
    row_ref = SA_CLASS_EXPECTED_RW_ROW[exposure_ref][index]

    # Act
    sheets = c07_sheets[regime_key]
    assert sheet_key in sheets, f"{regime_key}: C 07.00 never emitted sheet {sheet_key!r}"
    cells = _cells(sheets[sheet_key], row_ref)

    # Assert
    assert cells, f"{regime_key}/{sheet_key}: row {row_ref} is not even emitted"
    dark = [ref for ref in ("0200", "0220") if cells.get(ref) is None]
    assert not dark, (
        f"{regime_key}/{sheet_key} row {row_ref} "
        f"({SA_CLASS_EXPECTED_RW[exposure_ref][index]:.0%}): column(s) {dark} are NULL, so the "
        f"published identities over this rung are VACUOUS — {exposure_ref} did not reach it"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
@pytest.mark.parametrize("exposure_ref", list(SA_CLASS_EXPECTED_RW_ROW))
def test_risk_weight_row_satisfies_its_own_annex_ii_identity(
    c07_sheets: dict[str, dict[str, pl.DataFrame]], regime_key: str, exposure_ref: str
) -> None:
    """col 0220 == col 0200 x the weight the ROW LABEL names.

    The row's identity is checked against the row's own label rather than against
    the engine's ``risk_weight``, so a row that landed on the wrong rung fails
    here instead of agreeing with itself.

    Arrange: the portfolio under one regime, and the rung the row must occupy.
    Act:     read cols 0200 and 0220 off that rung.
    Assert:  0220 == 0200 x rw.
    """
    # Arrange
    index = _REGIMES[regime_key][1]
    sheet_key = SA_CLASS_EXPECTED_SHEET[exposure_ref]
    row_ref, expected_rw = (
        SA_CLASS_EXPECTED_RW_ROW[exposure_ref][index],
        SA_CLASS_EXPECTED_RW[exposure_ref][index],
    )

    # Act
    cells = _cells(c07_sheets[regime_key][sheet_key], row_ref)
    exposure_value, rwea = cells.get("0200"), cells.get("0220")

    # Assert
    assert exposure_value is not None, (
        f"{regime_key}/{sheet_key} row {row_ref}: cannot check the identity on a NULL row"
    )
    assert rwea is not None, (
        f"{regime_key}/{sheet_key} row {row_ref}: cannot check the identity on a NULL row"
    )
    assert abs(rwea - exposure_value * expected_rw) < _MONEY_TOLERANCE, (
        f"{regime_key}/{sheet_key} row {row_ref}: c0220 ({rwea:,.2f}) != c0200 "
        f"({exposure_value:,.2f}) x {expected_rw:.0%} ({exposure_value * expected_rw:,.2f})"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
@pytest.mark.parametrize("exposure_ref", list(SA_CLASS_EXPECTED_RW_ROW))
def test_risk_weight_row_identity_is_non_trivial(
    c07_sheets: dict[str, dict[str, pl.DataFrame]], regime_key: str, exposure_ref: str
) -> None:
    """cols 0200 and 0220 differ, so a column swap on this rung is detectable.

    This is the assertion that makes the rows worth adding rather than merely
    non-NULL. At a 100% weight the exposure-value and RWEA columns are
    numerically equal, and a defect that aliased, swapped or duplicated them
    produces byte-identical output — the state the ``corporate`` sheet was in
    when 0230 was its only live rung. Every row in
    ``SA_CLASS_EXPECTED_RW_ROW`` is deliberately away from 100%.

    Arrange: the portfolio under one regime.
    Act:     read cols 0200 and 0220 off the rung.
    Assert:  they are not equal, and the weight is not 100%.
    """
    # Arrange
    index = _REGIMES[regime_key][1]
    sheet_key = SA_CLASS_EXPECTED_SHEET[exposure_ref]
    row_ref = SA_CLASS_EXPECTED_RW_ROW[exposure_ref][index]
    expected_rw = SA_CLASS_EXPECTED_RW[exposure_ref][index]

    # Act
    cells = _cells(c07_sheets[regime_key][sheet_key], row_ref)
    exposure_value, rwea = cells.get("0200"), cells.get("0220")

    # Assert
    assert expected_rw != pytest.approx(1.0), (
        f"{exposure_ref} was re-pointed at a 100% weight, where c0200 == c0220 by "
        "arithmetic and this rung stops discriminating a column swap"
    )
    assert exposure_value is not None, (
        f"{regime_key}/{sheet_key} row {row_ref}: NULL row cannot be non-trivial"
    )
    assert rwea is not None, (
        f"{regime_key}/{sheet_key} row {row_ref}: NULL row cannot be non-trivial"
    )
    assert abs(rwea - exposure_value) > _MONEY_TOLERANCE, (
        f"{regime_key}/{sheet_key} row {row_ref}: c0200 and c0220 are both "
        f"{exposure_value:,.2f} at a {expected_rw:.0%} weight — arithmetically impossible "
        "unless one column is reading the other"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_touched_sheet_foots_as_an_addition_not_a_copy(
    c07_sheets: dict[str, dict[str, pl.DataFrame]], regime_key: str
) -> None:
    """Each sheet a risk-weight row touches has >= 2 live rungs.

    A sheet with one live rung makes its own ``r0010 = sum(risk-weight rows)``
    footing a tautology: the total equals the single row it is built from, so a
    rule asserting the footing cannot fail. Two live rungs make it an addition.

    Arrange: the sheets the ``*_RW20`` / ``*_RW150`` rows land on.
    Act:     count the rungs in the "Breakdown by Risk Weights" band that carry
             a figure in col 0200.
    Assert:  at least two per sheet, and r0010 equals their sum.
    """
    # Arrange
    index = _REGIMES[regime_key][1]
    touched = {SA_CLASS_EXPECTED_SHEET[ref] for ref in SA_CLASS_EXPECTED_RW_ROW}
    # The rung refs are the RW band; sheet totals (0010/0070) and the section-1
    # "of which" rows are deliberately excluded — only the breakdown band foots.
    band_refs = {SA_CLASS_EXPECTED_RW_ROW[ref][index] for ref in SA_CLASS_EXPECTED_RW_ROW} | {
        "0140",
        "0170",
        "0200",
        "0220",
        "0230",
        "0182",
    }

    # Act / Assert
    thin: dict[str, int] = {}
    misfooted: dict[str, tuple[float, float]] = {}
    for sheet_key in sorted(touched):
        frame = c07_sheets[regime_key][sheet_key]
        live = {
            str(row["row_ref"]): row["0200"]
            for row in frame.iter_rows(named=True)
            if str(row["row_ref"]) in band_refs and row["0200"] is not None
        }
        if len(live) < 2:
            thin[sheet_key] = len(live)
        total = _cells(frame, "0010").get("0200")
        if total is not None and abs(total - sum(live.values())) > _MONEY_TOLERANCE:
            misfooted[sheet_key] = (total, sum(live.values()))

    assert not thin, (
        f"{regime_key}: sheet(s) still have fewer than two live risk-weight rungs {thin} — "
        "their r0010 footing is a copy of one row, not an addition, so a rule over it "
        "cannot fail"
    )
    assert not misfooted, (
        f"{regime_key}: r0010 col 0200 does not equal the sum of the live rungs "
        f"(total, sum-of-rungs): {misfooted}"
    )
