"""
OF 07.00 / C 07.00 for unrated covered bonds — the Art. 129(5) rows, on the registered book.

Pipeline position:
    build_reporting_unrated_covered_bond_bundle() -> PipelineOrchestrator
        (PermissionMode.STANDARDISED) -> COREPGenerator
        -> C 07.00 / OF 07.00 covered-bond sheet (z0013) and Total sheet (z0001)
        -> filing.build_canonical_return -> rwa_filer.boe (Basel 3.1, the Bank's rules)

What is asserted, and the text it is asserted from:

- PLACEMENT. Each "Breakdown by risk weights" row 0140-0280 holds exactly the
  legs whose applied weight is the row's (PS1/26 Annex II p.95; COREP Annex II
  C 07.00 rows). PS1/26 adds rows 0171 (15%) and 0181 (25%) to the covered-bond
  sheet for Art. 129(5)(aa) and (b), and 0190 (35%) carries (ba). ``rw-ladder``
  also reaches 0171 / 0181 on that sheet, through the issuer ECAI step alone;
  this book adds the SCRA route into 0171, and it is the only registered run
  that puts a figure on covered-bond-sheet rows 0190, 0200 and 0230 (Basel 3.1)
  and 0200 and 0230 (CRR) — measured over ``RUNS`` when it was registered.
- THE ROW'S OWN WEIGHT. On a row named by a weight, RWEA is exposure value times
  that weight — the identity the Bank writes as ``boe_b0493`` (r0171: c0220 =
  c0200 x 0.15) and ``boe_b0494`` (r0181: x 0.25), ERROR, over sheets z0002-0008,
  z0011-0013 and z0015-0017 (so z0013, not the Total sheet), and as
  ``boe_b1018`` / ``boe_b1019`` (c0220 >= c0200 x 0.15 / x 0.25), scoped to
  z0001 / z0009 / z0010 (so the Total sheet, not z0013).
- NEGATIVE SPACE (``.claude/LESSONS.md`` B4). ``boe_b0450`` (WARNING, z0013)
  requires rows 0140, 0150, 0160, 0182, 0191, 0192, 0201, 0202, 0210, 0220, ...
  to be empty on the covered-bond sheet. The institution anchor puts a 30%
  figure in row 0182 of the Total sheet, so "0182 is empty on z0013" is about
  where the row is reported, not about a return with no 30% figure in it.

The Bank's rules are read from the gateway engine (``rwa_filer.boe`` on this
book's own canonical return), where each must reach a real verdict: PASS with
at least one satisfied evaluation, never a vacuous or unevaluated one. They are
not vacuous estate-wide without this book (``rw-ladder`` reaches them). On this
return they are identities over whatever legs a row holds, so a leg that moves
OUT of row 0171 leaves them passing — the placement tests are what see a moved
leg. They fail here when a row empties: measured, replacing the
``institution_cqs`` lift with a typed null fails ``boe_b0494`` / ``boe_b1019``
(row 0181's only leg leaves it), and routing the Basel 3.1 arm to the CRR
derivation fails all four.

The CRR arm holds the same legs on C 07.00's four covered-bond rungs (10 / 20 /
50 / 100%): CRR Art. 129(5) has no (aa), (ab), (b)-at-25% or (ba).

References:
- UK CRR Art. 129(5); PRA PS1/26 Art. 129(5)
- PRA PS1/26 Annex II, OF 07.00 rows 0140-0280 (p.95), para. 70 (covered-bond class)
- BoE v4.1.1 rules boe_b0450, boe_b0493, boe_b0494, boe_b1018, boe_b1019
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.reporting_unrated_covered_bond_portfolio import (
    COVERED_BOND_REFERENCES,
    DRAWN,
    EXPECTED_ROW,
    EXPECTED_RW,
    LN_INSTITUTION_ANCHOR,
    build_reporting_unrated_covered_bond_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")
_INDEX: dict[str, int] = {"CRR": 0, "BASEL_3_1": 1}
_SHEET_MAP: dict[str, str] = {"CRR": "c07", "BASEL_3_1": "of07"}

#: Published sheet codes: Art. 112(1)(l) covered bonds, and the Total.
_COVERED_BOND_Z: str = "0013"
_TOTAL_Z: str = "0001"

#: The PS1/26-only rows this book exists to light, and the weight each row names.
_PS126_ROWS: dict[str, float] = {"0171": 0.15, "0181": 0.25, "0190": 0.35}

#: "Breakdown by risk weights" rows: every ref from 0140 up to and including 0280.
_FIRST_RW_ROW, _LAST_RW_ROW = "0140", "0280"

#: A checksum-valid LEI, as the filing-mapping ratchet uses; the rules do not depend on it.
_ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"


# ---------------------------------------------------------------------------
# Runs and readers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _run(framework: str) -> tuple[COREPTemplateBundle, object]:
    """The registered book through the pipeline, C/OF 07.00 and (Basel 3.1) the gateway."""
    if framework == "CRR":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(
        build_reporting_unrated_covered_bond_bundle(), config
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    report = None
    if framework == "BASEL_3_1":
        header = ReturnHeader(_ENTITY_IDENTIFIER, date(2027, 3, 31), FILING_MODULE)
        pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
        mapping = build_canonical_return(corep, header, pack=pack)
        report = validate_return(mapping.canonical, pack).report
    return corep, report


def _sheet(framework: str, z_code: str) -> str:
    """The bundle key a published z-code names (LESSONS B3: not spelled here)."""
    keys = SHEET_INDEX_MAPS[_SHEET_MAP[framework]][z_code].bundle_keys
    assert len(keys) == 1, f"{framework} z:{z_code} names {keys}"
    return keys[0]


def _cell(framework: str, z_code: str, row_ref: str, column: str) -> float | None:
    corep = _run(framework)[0]
    sheet = _sheet(framework, z_code)
    assert sheet in corep.c07_00, f"sheet {sheet!r} not emitted; got {sorted(corep.c07_00)}"
    matched = corep.c07_00[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected one row {row_ref}, got {matched.height}"
    return matched[column][0]


def _risk_weight_rows(framework: str, z_code: str) -> list[str]:
    frame = _run(framework)[0].c07_00[_sheet(framework, z_code)]
    return [ref for ref in frame["row_ref"].to_list() if _FIRST_RW_ROW <= ref <= _LAST_RW_ROW]


def _expected_rows(framework: str, z_code: str) -> dict[str, tuple[float, float]]:
    """Row -> (exposure value, RWEA) from the fixture's leg table, per sheet.

    The covered-bond sheet holds the covered-bond legs; the Total sheet every leg.
    """
    index = _INDEX[framework]
    legs = COVERED_BOND_REFERENCES if z_code == _COVERED_BOND_Z else tuple(DRAWN)
    expected: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for reference in legs:
        row = EXPECTED_ROW[reference][index]
        expected[row][0] += DRAWN[reference]
        expected[row][1] += DRAWN[reference] * EXPECTED_RW[reference][index]
    return {row: (pair[0], pair[1]) for row, pair in expected.items()}


def _gateway_result(rule_id: str) -> object:
    report = _run("BASEL_3_1")[1]
    matched = [outcome for outcome in report.results if outcome.rule_id == rule_id]
    assert len(matched) == 1, f"expected one {rule_id} result, got {len(matched)}"
    return matched[0]


_PLACEMENT_CASES: list[tuple[str, str, str]] = [
    (framework, z_code, row)
    for framework in _FRAMEWORKS
    for z_code in (_COVERED_BOND_Z, _TOTAL_Z)
    for row in sorted({rows[_INDEX[framework]] for rows in EXPECTED_ROW.values()})
]


# ---------------------------------------------------------------------------
# Registration (LESSONS B5): the book is in the gate, with the config it needs
# ---------------------------------------------------------------------------


def test_the_book_is_registered_in_the_gate_under_both_regimes_without_irb_permission() -> None:
    """An unregistered book leaves the SCRA arm and rows 0190 / 0200 / 0230 unreached.

    No other registered run holds a covered bond whose issuer carries an SCRA
    grade, or puts a figure on those covered-bond-sheet rows. And a book
    registered under an IRB permission would pin open item P1.322 (covered bonds
    forced onto the Standardised Approach under IRB) rather than test Art. 129(5)
    — LESSONS B5's third form: registered with the wrong config.
    """
    # Arrange
    runs = [
        run
        for run in RUNS
        if getattr(run.build_bundle, "func", run.build_bundle)
        is build_reporting_unrated_covered_bond_bundle
    ]

    # Assert
    assert sorted(run.framework for run in runs) == ["BASEL_3_1", "CRR"]
    for run in runs:
        assert run.build_config().permission_mode is PermissionMode.STANDARDISED, run.regime
        assert run.build_prior_config is None, run.regime


# ---------------------------------------------------------------------------
# Placement: every risk-weight row holds exactly its legs, both sheets, both regimes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("framework", "z_code", "row_ref"), _PLACEMENT_CASES)
def test_each_risk_weight_row_holds_exactly_the_legs_whose_weight_it_names(
    framework: str, z_code: str, row_ref: str
) -> None:
    # Arrange
    expected = _expected_rows(framework, z_code).get(row_ref)

    # Act
    exposure = _cell(framework, z_code, row_ref, "0200")
    rwea = _cell(framework, z_code, row_ref, "0220")

    # Assert — an expected row is non-null (B4); an unexpected one is empty, not zero
    if expected is None:
        assert exposure is None, f"{framework} z{z_code} r{row_ref}: {exposure}"
        assert rwea is None, f"{framework} z{z_code} r{row_ref}: {rwea}"
        return
    assert exposure == pytest.approx(expected[0])
    assert rwea == pytest.approx(expected[1])


@pytest.mark.parametrize("framework", _FRAMEWORKS)
@pytest.mark.parametrize("z_code", [_COVERED_BOND_Z, _TOTAL_Z])
def test_no_risk_weight_row_outside_the_leg_table_carries_a_figure(
    framework: str, z_code: str
) -> None:
    """The negative space of the placement test: every other rung is empty."""
    expected = _expected_rows(framework, z_code)

    populated = [
        row
        for row in _risk_weight_rows(framework, z_code)
        if row not in expected and _cell(framework, z_code, row, "0200") is not None
    ]

    assert populated == [], f"{framework} z{z_code}: unexpected rungs {populated}"


@pytest.mark.parametrize("framework", _FRAMEWORKS)
@pytest.mark.parametrize("column", ["0200", "0220"])
def test_the_covered_bond_sheets_rungs_foot_to_row_0010(framework: str, column: str) -> None:
    banded = sum(
        float(_cell(framework, _COVERED_BOND_Z, row, column) or 0.0)
        for row in _risk_weight_rows(framework, _COVERED_BOND_Z)
    )

    expected_total = sum(
        pair[0 if column == "0200" else 1]
        for pair in _expected_rows(framework, _COVERED_BOND_Z).values()
    )
    assert _cell(framework, _COVERED_BOND_Z, "0010", column) == pytest.approx(expected_total)
    assert banded == pytest.approx(expected_total)


# ---------------------------------------------------------------------------
# Basel 3.1: the PS1/26-only rows carry their own weight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("z_code", [_COVERED_BOND_Z, _TOTAL_Z])
@pytest.mark.parametrize(("row_ref", "row_weight"), list(_PS126_ROWS.items()))
def test_each_ps1_26_row_is_live_and_holds_its_own_weight(
    z_code: str, row_ref: str, row_weight: float
) -> None:
    """Rows 0171 / 0181 / 0190: non-null, and RWEA = exposure value x the row's weight."""
    exposure = _cell("BASEL_3_1", z_code, row_ref, "0200")
    rwea = _cell("BASEL_3_1", z_code, row_ref, "0220")

    assert exposure is not None and exposure > 0.0, f"z{z_code} r{row_ref} is dead"
    assert rwea == pytest.approx(exposure * row_weight)


@pytest.mark.parametrize("row_ref", ["0182", "0191"])
def test_the_rows_the_bank_closes_on_the_covered_bond_sheet_stay_empty(row_ref: str) -> None:
    """``boe_b0450``: rows 0182 (30%) / 0191 (40%) are empty on z0013.

    30% and 40% are ISSUER weights here, never covered-bond weights; Art. 129(5)
    maps them to 15% / 20%. Row 0182 of the Total sheet carries the institution
    anchor's 30%, so the emptiness on z0013 is scope, not absence.
    """
    for column in ("0010", "0200", "0220"):
        assert _cell("BASEL_3_1", _COVERED_BOND_Z, row_ref, column) is None, column
    assert _cell("BASEL_3_1", _TOTAL_Z, "0182", "0200") == pytest.approx(
        DRAWN[LN_INSTITUTION_ANCHOR]
    )


# ---------------------------------------------------------------------------
# Basel 3.1: the Bank's rules over those rows reach a real verdict, on the gateway
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id",
    [
        "boe_b0493",  # z0013 r0171: c0220 = c0200 x 0.15 (ERROR)
        "boe_b0494",  # z0013 r0181: c0220 = c0200 x 0.25 (ERROR)
        "boe_b1018",  # z0001 r0171: c0220 >= c0200 x 0.15
        "boe_b1019",  # z0001 r0181: c0220 >= c0200 x 0.25
        "boe_b0450",  # z0013: the closed rungs are empty (WARNING)
        "boe_b0450_1",
    ],
)
def test_the_banks_rules_over_the_new_rows_hold_on_a_real_figure(rule_id: str) -> None:
    """Each rule PASSES with at least one satisfied evaluation — not vacuously."""
    result = _gateway_result(rule_id)

    assert result.status == STATUS_PASS, f"{rule_id}: {result.status} {result.reason}"
    assert result.satisfied >= 1, f"{rule_id}: no evaluation reached a figure"
    assert result.unsatisfied == 0
