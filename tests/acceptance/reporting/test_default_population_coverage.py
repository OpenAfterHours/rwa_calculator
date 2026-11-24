"""
Defaulted standardised populations in the registered estate: C 07.00 rows 0015 / 0300 / 0320.

Pipeline position:
    tests/acceptance/reporting/test_supervisory_validations.py::RUNS
        -> PipelineOrchestrator -> COREPGenerator -> C 07.00 / OF 07.00
        -> filing.checks.evaluate_all (the register's template-level engine)
        -> scripts/filing_mapping_report.py::file_on_gateway (the Bank's rules, Basel 3.1)

Why this file exists (P5.80, LESSONS B5): the 2026-11-16 OF 07.00 default fixes
(O-05 row 0015, O-15 memo rows on the class before default, O-16 / ``63c3b5c`` a
covered part at the obligor's own weight) were reached by unit tests on synthetic
frames and by two unregistered books only. The registered matrix held one defaulted
standardised leg — ``rich``'s corporate at 150%, unprovisioned and unguaranteed — so
row 0300 was null everywhere, c0030 on the memo rows was never a figure
(``boe_b0733_1`` and the CRR ``v2040_s`` VACUOUS on every run), and the Basel 3.1
high-risk sheet, ``boe_b0264`` and the guaranteed loan split never ran. A green gate
there said nothing about them.

The rule text, read from the PDFs (pymupdf):

- PS1/26 Annex II ¶52 (p.78): "Those memorandum items in rows 0300 and 0320 shall
  only be reported for the following exposure classes: (a) central governments ...
  (g) real estate". ¶54: "Exposures shall be reported in these rows where the
  obligors would have been reported in the exposure classes [...] if those exposures
  were not assigned to the exposure classes 'in default'." ¶55: "... reported in OF CR
  SA, row 0320 in the total and in the exposure class 'in default'. If this exposure,
  before it defaulted, was an exposure to an institution, then that information shall
  also be reported in row 0320 of exposure class 'institutions'." Row 0300 (p.97):
  "subject to Article 127(1)(b) and (3)"; row 0320: "subject to Article 127(1)(a)".
- Table OF07.00.01.03 (taxonomy v4.1.1) carries rows 0300 / 0320 on sheets 0001-0004
  and 0007-0009 only — ``of07_published_cells.get_c07_memo_default_sheet_keys`` holds
  that set, tested against the taxonomy — and the Bank's known-issues log (November
  2026, #27): "report exposures assigned to the real estate exposure class in the
  total sheet s0001 for rows 0300 and 0320 but do not report such exposures
  separately to this".
- PS1/26 Art. 127(1) (ps126app1.pdf p.59): "(a) 150%, where the amount of specific
  credit risk adjustments ... is less than 20% of the outstanding amount ...; or
  (b) 100%, where ... equal to or greater than 20%". Art. 127(3): "A residential real
  estate exposure which is a defaulted exposure and is not materially dependent on
  the cash-flows of the property shall be assigned a risk weight of 100%."
- PS1/26 Annex II row 0015 (p.88): "Only exposures in exposure classes 'exposures
  associated with particularly high risk', ... shall be reported in this row if they
  are in default." Art. 128(1): 150%; Art. 112(2) Table A2 ranks the class (row 4)
  above "in default" (row 5).
- CRR Annex II ¶52-55 (pp.79-80): the same memo rows for six classes; ¶55 puts row
  0320 "in the total and in the exposure class 'in default'" as well. The engine
  still keys the CRR rows on the applied class (the open CRR half of P1.377), so no
  CRR class-sheet placement is asserted here — only the Total and the "in default"
  sheet, which ¶55 names in both regimes' CRR text. CRR Art. 127(3) (watchfire
  snapshot; ``crr.pdf`` is empty here): 100% on "exposures fully and completely
  secured by mortgages on residential property in accordance with Article 125".
- PS1/26 Annex II ¶54 / CRR Annex II ¶54: "The figures reported, however, are the
  same as used to calculate the risk weighted exposure amounts in the exposure class
  'in default'". A covered part's exposure value and RWEA are the protection
  provider's, so the memo row's c0200 / c0220 exclude them. The covered defaulted
  corporate's protector is a CQS 2 institution at a non-zero weight, so the RWEA
  that crosses is a figure in both regimes and a memo row that wrongly kept it would
  read differently (LESSONS C2: a 0% protector cannot tell the two apart).

Two parts:

1. **The registered estate** — the fail-first limbs. Each searches the runs of
   ``RUNS`` for the population, newest registration first: the order only decides how
   many runs are evaluated before the search stops, never the verdict. Red before the
   ``default-populations`` book was registered, in each regime separately.
2. **Where each population lands** — on that registered book's own run, against
   figures derived from the fixture's inputs and the resolved pack.

References:
- PS1/26 Art. 112(2), 124F, 127, 128; Annex II OF 07.00 ¶51-55, rows 0015 / 0300 / 0320
- CRR Art. 112, 127; COREP Annex II C 07.00 ¶51-55, rows 0300 / 0320
- tests/fixtures/reporting_default_populations_portfolio.py
- src/rwa_calc/reporting/corep/c07_sheet_scope.py; reporting/kernel/rw_parts.py
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.reporting_default_populations_portfolio import (
    B31_MEMO_ORIGIN_CLASS,
    CRR_LOANS,
    DRAWN,
    GUARANTEED_SHARE,
    GUARANTOR,
    GUARANTOR_CQS,
    LN_CORP_GTD_DEF,
    LN_HR_DEF,
    LN_HR_PERF,
    LN_RRE_DEF,
    LN_RRE_GTD,
    PROVISION_SHARE,
)

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.of07_published_cells import get_c07_memo_default_sheet_keys
from rwa_calc.reporting.corep.templates import (
    C07_00_SA_SHEET_MAP,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)
from rwa_calc.reporting.filing.checks import evaluate_all
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_calc.rulebook.resolve import resolve
from rwa_filer.boe.engine import STATUS_NOT_EVALUATED as GATEWAY_NOT_EVALUATED
from rwa_filer.boe.engine import STATUS_PASS as GATEWAY_PASS
from rwa_filer.validate.evaluate import STATUS_PASS

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from tests.acceptance.reporting.test_supervisory_validations import GateInput

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.boe.engine import RuleResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTFOLIO: str = "default-populations"
_FRAMEWORKS: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

ROW_TOTAL: str = "0010"
ROW_DEFAULTED: str = "0015"
ROW_MEMO_100: str = "0300"  # Art. 127(1)(b) and (3)
ROW_MEMO_150: str = "0320"  # Art. 127(1)(a)
MEMO_ROWS: tuple[str, str] = (ROW_MEMO_100, ROW_MEMO_150)
ROW_OTHER_RW: str = "0280"

COL_ORIGINAL: str = "0010"
COL_VALUE_ADJUSTMENT: str = "0030"
COL_EXPOSURE_VALUE: str = "0200"
COL_RWEA: str = "0220"

# The published z-codes the rows are asserted on (resolved through SHEET_INDEX_MAPS).
Z_TOTAL: str = "0001"
Z_CGCB: str = "0002"
Z_INSTITUTION: str = "0007"
Z_REAL_ESTATE: str = "0010"
Z_DEFAULTED: str = "0011"
Z_HIGH_RISK: str = "0012"

#: The memo-sign rule over c0030 / c0035 of rows 0300 / 0320, per regime
#: (``{OF07.00.01.03} <= 0`` / ``{C 07.00.d} <= 0``).
MEMO_SIGN_RULE: dict[str, str] = {"crr": "v2040_s", "b31": "boe_b0733_1"}
#: OF 07.00 r0015 c0010 on z0012 = OF 09.01 r0110 c0020 — the high-risk tie.
HIGH_RISK_TIE_RULE: str = "boe_b0264"

#: The weight band section of ``get_sa_row_sections`` (rows 0140-0280).
_RW_SECTION: int = 2

#: The rated-institution weight table each regime's pack keys on CQS (CRR Art. 120
#: Table 3; PS1/26 Art. 120 Table 3, ECRA) — the covered corporate's protector.
_INSTITUTION_RW_TABLE: dict[str, str] = {
    "crr": "institution_rw_crr",
    "b31": "institution_rw_b31_ecra",
}


class _Run(NamedTuple):
    """One registered run, evaluated."""

    portfolio: str
    ledger: pl.DataFrame
    corep: COREPTemplateBundle


# ---------------------------------------------------------------------------
# 1. The registered estate
# ---------------------------------------------------------------------------


def test_registered_b31_runs_report_each_memo_row_on_every_published_class_sheet() -> None:
    """Rows 0300 and 0320 are each reported on a class sheet, and every class sheet the
    taxonomy publishes them on carries one: 0002-0004 and 0007-0009 (Annex II ¶52-54)."""
    # Arrange
    sheets = sorted(get_c07_memo_default_sheet_keys("BASEL_3_1"))
    goal = frozenset({*(f"sheet {key}" for key in sheets), *(f"row {r}" for r in MEMO_ROWS)})

    def memo_figures(run: _Run) -> frozenset[str]:
        found: set[str] = set()
        for key in sheets:
            frame = run.corep.c07_00.get(key)
            rows = {r for r in MEMO_ROWS if frame is not None and _cell(frame, r, COL_ORIGINAL)}
            found |= {f"row {r}" for r in rows} | ({f"sheet {key}"} if rows else set())
        return frozenset(found)

    # Act
    found = _search("b31", memo_figures, goal)

    # Assert
    assert goal <= found, f"no registered Basel 3.1 run reports {sorted(goal - found)}"


def test_registered_crr_runs_report_both_memo_rows_on_the_total_and_in_default_sheets() -> None:
    """CRR Annex II ¶55: row 0320 (and 0300) "in the total and in the exposure class 'in
    default'". The class-sheet half is the open CRR half of P1.377 and is not asserted."""
    # Arrange
    goal = frozenset(f"{z} {r}" for z in (Z_TOTAL, Z_DEFAULTED) for r in MEMO_ROWS)

    def memo_figures(run: _Run) -> frozenset[str]:
        return frozenset(
            f"{z} {r}"
            for z in (Z_TOTAL, Z_DEFAULTED)
            if (frame := _sheet_or_none(run.corep, "crr", z)) is not None
            for r in MEMO_ROWS
            if _cell(frame, r, COL_ORIGINAL)
        )

    # Act
    found = _search("crr", memo_figures, goal)

    # Assert
    assert goal <= found, f"no registered CRR run reports {sorted(goal - found)}"


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_registered_runs_report_a_value_adjustment_in_both_memo_rows(regime: str) -> None:
    """A provisioned default on each side of the Art. 127(1) 20% threshold: c0030 is a
    figure in row 0300 AND row 0320 (LESSONS B5 fourth form — one leg cannot tell a row
    scoped correctly from one zeroed)."""
    # Arrange
    goal = frozenset(MEMO_ROWS)

    def adjusted_rows(run: _Run) -> frozenset[str]:
        total = _sheet_or_none(run.corep, regime, Z_TOTAL)
        if total is None:
            return frozenset()
        return frozenset(r for r in MEMO_ROWS if _cell(total, r, COL_VALUE_ADJUSTMENT))

    # Act
    found = _search(regime, adjusted_rows, goal)

    # Assert
    assert found == goal, f"[{regime}] no registered run adjusts {sorted(goal - found)}"


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_the_memo_sign_rule_reaches_a_real_verdict_on_a_registered_run(regime: str) -> None:
    """``boe_b0733_1`` / ``v2040_s`` held only at ``0 <= 0`` (VACUOUS) on every run."""
    # Arrange
    rule = MEMO_SIGN_RULE[regime]

    # Act
    portfolio = _first(regime, lambda index: _template_verdicts(regime, index).get(rule))

    # Assert
    assert portfolio is not None, f"[{regime}] {rule} passes on no registered run"


def test_a_registered_b31_run_reports_a_real_estate_origin_default_on_the_total_alone() -> None:
    """Known issue #27: the Total's row 0300 carries a real-estate-origin default that no
    class sheet carries, so it exceeds the class sheets' sum."""

    # Arrange
    def total_only(index: int) -> bool:
        run = _evaluate("b31", index)
        return _real_estate_origin_defaults(run.ledger) > 0 and _total_only_memo(run.corep) > 0

    # Act
    portfolio = _first("b31", total_only)

    # Assert
    assert portfolio is not None, "no registered Basel 3.1 run reports one"


def test_a_registered_b31_run_reports_a_defaulted_high_risk_leg_beside_a_performing_one() -> None:
    """Sheet 0012 row 0015 carries the defaulted leg and row 0010 more than it: a row
    blanked everywhere and one scoped to the defaulted leg read differently."""

    # Arrange
    def survivor_pair(index: int) -> bool:
        frame = _sheet_or_none(_evaluate("b31", index).corep, "b31", Z_HIGH_RISK)
        if frame is None:
            return False
        defaulted = _cell(frame, ROW_DEFAULTED, COL_ORIGINAL) or 0.0
        return 0.0 < defaulted < (_cell(frame, ROW_TOTAL, COL_ORIGINAL) or 0.0)

    # Act
    portfolio = _first("b31", survivor_pair)

    # Assert
    assert portfolio is not None, "no registered Basel 3.1 run emits the high-risk pair"


def test_boe_b0264_reaches_a_gateway_verdict_on_a_registered_run() -> None:
    """The OF 07.00 / OF 09.01 high-risk tie ran on no registered return."""

    # Arrange
    def evaluated(index: int) -> bool:
        return _gateway(index)[HIGH_RISK_TIE_RULE].status != GATEWAY_NOT_EVALUATED

    # Act
    portfolio = _first("b31", evaluated)

    # Assert
    assert portfolio is not None, f"{HIGH_RISK_TIE_RULE} is evaluated on no registered return"
    result = _gateway(_index_of("b31", portfolio))[HIGH_RISK_TIE_RULE]
    assert (result.status, result.unsatisfied) == (GATEWAY_PASS, 0), _describe(result)


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_a_registered_run_holds_a_beneficially_covered_defaulted_leg(regime: str) -> None:
    """The ``63c3b5c`` memorandum composition applies in both regimes."""

    # Arrange
    def covered_default(index: int) -> bool:
        covered = _covered_legs(_evaluate(regime, index).ledger)
        return covered.filter(pl.col("is_defaulted").fill_null(value=False)).height > 0

    # Act / Assert
    assert _first(regime, covered_default) is not None, f"[{regime}] none registered"


def test_a_registered_b31_run_holds_a_beneficially_covered_loan_split_leg() -> None:
    """The ``rw_parts`` substituted route: a covered leg carrying the Art. 124F split."""

    # Arrange
    def covered_split(index: int) -> bool:
        covered = _covered_legs(_evaluate("b31", index).ledger)
        if "sa_loan_split_secured_share" not in covered.columns:
            return False
        split = pl.col("sa_loan_split_secured_share").is_between(0.0, 1.0, closed="none")
        return covered.filter(split).height > 0

    # Act / Assert
    assert _first("b31", covered_split) is not None, "none registered"


# ---------------------------------------------------------------------------
# 2. Where each population lands, on the registered book
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_the_book_holds_provisioned_defaults_either_side_of_the_threshold(regime: str) -> None:
    """Adequacy (LESSONS C11): each provisioned leg's weight is the one Art. 127(1) gives
    its provision, and both limbs are held."""
    ledger = _book(regime).ledger
    threshold, high, low = _article_127_weights(regime)
    loans = [loan for loan in PROVISION_SHARE if loan in _book_loans(regime) and loan != LN_RRE_DEF]
    limbs: set[float] = set()

    for loan in loans:
        leg = _leg(ledger, loan)
        expected = high if PROVISION_SHARE[loan] >= threshold else low
        assert float(leg["risk_weight"]) == pytest.approx(expected), loan
        limbs.add(expected)

    assert limbs == {high, low}


@pytest.mark.parametrize("loan", sorted(B31_MEMO_ORIGIN_CLASS))
def test_b31_each_default_is_reported_on_the_sheet_of_its_class_before_default(loan: str) -> None:
    """Annex II ¶54: on the obligor's class sheet, in the row its Art. 127 limb names, at
    the figures used for the "in default" class; the other memo row stays empty there."""
    # Arrange
    run = _book("b31")
    legs = run.ledger.filter(_of_loan(loan))
    assert set(legs["reporting_class_pre_default"]) == {B31_MEMO_ORIGIN_CLASS[loan]}
    sheet = run.corep.c07_00[C07_00_SA_SHEET_MAP[B31_MEMO_ORIGIN_CLASS[loan]]]
    row, weight = _memo_row_and_weight("b31", loan)
    exposure_value = DRAWN[loan] * (1.0 - PROVISION_SHARE.get(loan, 0.0))
    exposure_value *= 1.0 - GUARANTEED_SHARE.get(loan, 0.0)
    other = ROW_MEMO_150 if row == ROW_MEMO_100 else ROW_MEMO_100

    # Act
    cells = {col: _cell(sheet, row, col) for col in (COL_ORIGINAL, COL_EXPOSURE_VALUE, COL_RWEA)}

    # Assert
    assert cells[COL_ORIGINAL] == pytest.approx(DRAWN[loan])
    assert cells[COL_EXPOSURE_VALUE] == pytest.approx(exposure_value)
    assert cells[COL_RWEA] == pytest.approx(exposure_value * weight)
    if loan in PROVISION_SHARE:
        assert _cell(sheet, row, COL_VALUE_ADJUSTMENT) == pytest.approx(
            -DRAWN[loan] * PROVISION_SHARE[loan]
        )
    assert _cell(sheet, other, COL_ORIGINAL) is None


def test_b31_the_total_adds_the_real_estate_origin_default_to_row_0300_alone() -> None:
    """Known issue #27: on the Total, never on a class sheet, the real-estate sheet or the
    "in default" sheet (table OF07.00.01.03 has no cell on either)."""
    # Arrange
    corep = _book("b31").corep
    class_rows = {row: _memo_sheets_sum(corep, row) for row in MEMO_ROWS}
    total = _sheet(corep, "b31", Z_TOTAL)

    # Act
    reported = {row: _cell(total, row, COL_ORIGINAL) for row in MEMO_ROWS}

    # Assert
    assert reported[ROW_MEMO_100] == pytest.approx(class_rows[ROW_MEMO_100] + DRAWN[LN_RRE_DEF])
    assert reported[ROW_MEMO_150] == pytest.approx(class_rows[ROW_MEMO_150])
    for z_code in (Z_REAL_ESTATE, Z_DEFAULTED):
        frame = _sheet(corep, "b31", z_code)
        assert [_cell(frame, row, COL_ORIGINAL) for row in MEMO_ROWS] == [None, None], z_code


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_a_residential_default_takes_100_percent_whatever_its_provision(regime: str) -> None:
    """Art. 127(3), both regimes: the real-estate default takes 100% (row 0300) with a
    provision below 20%, which on its own would give 150% (row 0320)."""
    threshold, _high, low = _article_127_weights(regime)
    leg = _leg(_book(regime).ledger, LN_RRE_DEF)

    assert PROVISION_SHARE[LN_RRE_DEF] < threshold
    assert C07_00_SA_SHEET_MAP[str(leg["reporting_class_pre_default"])] == _sheet_key(
        regime, Z_REAL_ESTATE
    )
    assert float(leg["risk_weight"]) == pytest.approx(_article_127_3_weight(regime))
    assert _article_127_3_weight(regime) < low


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_the_covered_part_of_the_defaulted_corporate_is_weighted_on_the_guarantor_sheet(
    regime: str,
) -> None:
    """``63c3b5c`` and Annex II ¶54: the covered part's exposure value and RWEA are the
    institution's, on its own weight's row (c0220 = covered EV x the protector's weight);
    its original exposure stays with the obligor; and the obligor's memo row reports
    the "in default" RWEA, which excludes the covered part."""
    # Arrange
    run = _book(regime)
    weight = _protector_weight(regime, GUARANTOR[LN_CORP_GTD_DEF])
    covered_value = DRAWN[LN_CORP_GTD_DEF] * GUARANTEED_SHARE[LN_CORP_GTD_DEF]
    uncovered_value = DRAWN[LN_CORP_GTD_DEF] - covered_value
    _threshold, _high, defaulted_weight = _article_127_weights(regime)
    crossing = run.ledger.filter(
        pl.col("exposure_reference").str.starts_with(f"{LN_CORP_GTD_DEF}__G_")
    )
    # Adequacy (LESSONS C2 / C11): a 0% protector would make the crossing RWEA zero.
    assert 0.0 < weight < defaulted_weight
    assert crossing["rwa_final"].sum() == pytest.approx(covered_value * weight)
    protector_row = _band_ref(_FRAMEWORKS[regime], weight)
    guarantor = _sheet(run.corep, regime, Z_INSTITUTION)
    obligor = (
        run.corep.c07_00[C07_00_SA_SHEET_MAP[B31_MEMO_ORIGIN_CLASS[LN_CORP_GTD_DEF]]]
        if regime == "b31"
        else None
    )

    # Act
    inflow = {
        col: _cell(guarantor, protector_row, col)
        for col in (COL_ORIGINAL, COL_EXPOSURE_VALUE, COL_RWEA)
    }

    # Assert
    assert inflow[COL_EXPOSURE_VALUE] == pytest.approx(covered_value)
    assert inflow[COL_RWEA] == pytest.approx(covered_value * weight)
    assert (inflow[COL_ORIGINAL] or 0.0) == pytest.approx(0.0)
    if obligor is not None:  # Basel 3.1: the corporate sheet's row 0320 is the leg alone
        assert _cell(obligor, ROW_MEMO_150, COL_ORIGINAL) == pytest.approx(DRAWN[LN_CORP_GTD_DEF])
        assert _cell(obligor, ROW_MEMO_150, COL_EXPOSURE_VALUE) == pytest.approx(uncovered_value)
        assert _cell(obligor, ROW_MEMO_150, COL_RWEA) == pytest.approx(
            uncovered_value * defaulted_weight
        )
    else:  # CRR: the leg shares row 0320 of the Total / "in default" sheet (P1.377)
        for z_code in (Z_TOTAL, Z_DEFAULTED):
            memo = _sheet(run.corep, regime, z_code)
            value = _cell(memo, ROW_MEMO_150, COL_EXPOSURE_VALUE) or 0.0
            # Every row-0320 leg is at 150%: a covered part's RWEA, at the protector's
            # weight, left in the row would break the row's own weight.
            assert _cell(memo, ROW_MEMO_150, COL_RWEA) == pytest.approx(value * defaulted_weight), (
                z_code
            )


def test_b31_the_covered_part_of_the_loan_split_goes_to_the_sovereign_at_0_percent() -> None:
    """The loan split's protector is the CQS 1 UK sovereign: its exposure value is on the
    central-government sheet's 0% row, its original exposure is not."""
    corep = _book("b31").corep
    covered = DRAWN[LN_RRE_GTD] * GUARANTEED_SHARE[LN_RRE_GTD]
    zero_row = _band_ref("BASEL_3_1", 0.0)
    assert _protector_weight("b31", GUARANTOR[LN_RRE_GTD]) == pytest.approx(0.0)

    sheet = _sheet(corep, "b31", Z_CGCB)
    assert _cell(sheet, zero_row, COL_EXPOSURE_VALUE) == pytest.approx(covered)
    assert (_cell(sheet, zero_row, COL_ORIGINAL) or 0.0) == pytest.approx(0.0)


def test_crr_the_memo_rows_of_the_total_and_in_default_sheets_carry_every_default() -> None:
    """CRR Annex II ¶54-55 and the ``63c3b5c`` composition: original exposure whole (the
    covered part included); exposure value and RWEA net of provisions and of the covered
    part, at the row's weight — the residential default in row 0300 by Art. 127(3)."""
    # Arrange
    corep = _book("crr").corep
    rows: dict[str, list[str]] = {ROW_MEMO_100: [], ROW_MEMO_150: []}
    weights: dict[str, float] = {}
    for loan in CRR_LOANS:
        row, weights[loan] = _memo_row_and_weight("crr", loan)
        rows[row].append(loan)
    assert LN_RRE_DEF in rows[ROW_MEMO_100]  # adequacy: the Art. 127(3) route is held

    def exposure_value(loan: str) -> float:
        return (
            DRAWN[loan]
            * (1.0 - PROVISION_SHARE.get(loan, 0.0))
            * (1.0 - GUARANTEED_SHARE.get(loan, 0.0))
        )

    for z_code in (Z_TOTAL, Z_DEFAULTED):
        sheet = _sheet(corep, "crr", z_code)
        for row, loans in rows.items():
            # Act
            original = _cell(sheet, row, COL_ORIGINAL)
            adjustment = _cell(sheet, row, COL_VALUE_ADJUSTMENT)
            value = _cell(sheet, row, COL_EXPOSURE_VALUE)
            rwea = _cell(sheet, row, COL_RWEA)

            # Assert
            assert original == pytest.approx(sum(DRAWN[loan] for loan in loans)), (z_code, row)
            assert adjustment == pytest.approx(
                -sum(DRAWN[loan] * PROVISION_SHARE.get(loan, 0.0) for loan in loans)
            ), (z_code, row)
            assert value == pytest.approx(sum(exposure_value(loan) for loan in loans)), (
                z_code,
                row,
            )
            assert rwea == pytest.approx(
                sum(exposure_value(loan) * weights[loan] for loan in loans)
            ), (z_code, row)


def test_b31_the_high_risk_sheet_reports_its_defaulted_leg_in_row_0015() -> None:
    """Row 0015 on sheet 0012 and the Total: the defaulted leg only; row 0010 both legs;
    the "in default" sheet has no row 0015 figure (the class is kept, Table A2 row 4)."""
    corep = _book("b31").corep
    weight = float(resolve("b31", _reporting_date("b31")).scalar("high_risk_rw"))
    high_risk = _sheet(corep, "b31", Z_HIGH_RISK)

    assert _cell(high_risk, ROW_DEFAULTED, COL_ORIGINAL) == pytest.approx(DRAWN[LN_HR_DEF])
    assert _cell(high_risk, ROW_DEFAULTED, COL_RWEA) == pytest.approx(DRAWN[LN_HR_DEF] * weight)
    assert _cell(high_risk, ROW_TOTAL, COL_ORIGINAL) == pytest.approx(
        DRAWN[LN_HR_DEF] + DRAWN[LN_HR_PERF]
    )
    total = _sheet(corep, "b31", Z_TOTAL)
    assert _cell(total, ROW_DEFAULTED, COL_ORIGINAL) == pytest.approx(DRAWN[LN_HR_DEF])
    assert _cell(_sheet(corep, "b31", Z_DEFAULTED), ROW_DEFAULTED, COL_ORIGINAL) is None


def test_b31_the_covered_loan_split_is_reported_in_its_two_parts() -> None:
    """Annex II p.94 "in two parts", on the origin basis for the original exposure and on
    the uncovered part for the exposure value; nothing in "Other risk weights"."""
    # Arrange
    run = _book("b31")
    covered = run.ledger.filter(
        pl.col("exposure_reference").str.starts_with(f"{LN_RRE_GTD}__G_")
    ).row(0, named=True)
    assert covered["is_guarantee_beneficial"] is True  # adequacy (LESSONS C11)
    share = float(covered["sa_loan_split_secured_share"])
    secured_row = _band_ref("BASEL_3_1", float(covered["sa_loan_split_secured_rw"]))
    residual_row = _band_ref("BASEL_3_1", float(covered["sa_loan_split_residual_rw"]))
    uncovered = DRAWN[LN_RRE_GTD] * (1.0 - GUARANTEED_SHARE[LN_RRE_GTD])
    sheet = _sheet(run.corep, "b31", Z_REAL_ESTATE)

    # Act
    parts = {
        row: (_cell(sheet, row, COL_ORIGINAL), _cell(sheet, row, COL_EXPOSURE_VALUE))
        for row in (secured_row, residual_row)
    }

    # Assert
    assert 0.0 < share < 1.0
    assert parts[secured_row] == pytest.approx((DRAWN[LN_RRE_GTD] * share, uncovered * share))
    assert parts[residual_row] == pytest.approx(
        (DRAWN[LN_RRE_GTD] * (1.0 - share), uncovered * (1.0 - share))
    )
    assert _cell(sheet, ROW_OTHER_RW, COL_ORIGINAL) is None


@pytest.mark.parametrize(
    "rule_id",
    ["boe_b0733_1", HIGH_RISK_TIE_RULE, "boe_b0431", "boe_b1069", "boe_b0441", "boe_b0445"],
)
def test_b31_the_banks_rules_on_the_defaulted_populations_hold(rule_id: str) -> None:
    """``boe_b0733_1`` memo c0030 / c0035 <= 0; ``boe_b0264`` the high-risk tie;
    ``boe_b0431`` / ``boe_b1069`` row 0015 only where Annex II names; ``boe_b0441`` /
    ``boe_b0445`` the risk-weight rows a covered or split leg must not light."""
    result = _gateway(_index_of("b31", PORTFOLIO))[rule_id]

    assert result.status == GATEWAY_PASS, _describe(result)
    assert (result.satisfied > 0, result.unsatisfied) == (True, 0), _describe(result)


# ---------------------------------------------------------------------------
# Helpers — the registered runs
# ---------------------------------------------------------------------------


def _registered(regime: str) -> tuple[GateInput, ...]:
    """The regime's runs of ``RUNS``, newest registration first (module docstring)."""
    return tuple(reversed([run for run in RUNS if run.regime == regime]))


@cache
def _evaluate(regime: str, index: int) -> _Run:
    run = _registered(regime)[index]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    return _Run(run.portfolio, result.results.collect(), corep)


def _search(
    regime: str, collect: Callable[[_Run], frozenset[str]], goal: frozenset[str]
) -> frozenset[str]:
    """What ``collect`` finds across the registered runs, stopping once ``goal`` is met."""
    found: frozenset[str] = frozenset()
    for index in range(len(_registered(regime))):
        found |= collect(_evaluate(regime, index))
        if goal <= found:
            break
    return found


def _first(regime: str, predicate: Callable[[int], object]) -> str | None:
    """The first registered run (newest first) on which ``predicate`` holds."""
    for index in range(len(_registered(regime))):
        if predicate(index):
            return _evaluate(regime, index).portfolio
    return None


def _index_of(regime: str, portfolio: str) -> int:
    indices = [i for i, run in enumerate(_registered(regime)) if run.portfolio == portfolio]
    assert len(indices) == 1, f"[{regime}] {portfolio!r} is registered {len(indices)} times"
    return indices[0]


@cache
def _template_verdicts(regime: str, index: int) -> dict[str, bool]:
    """Which rules the register's template-level engine PASSes on one run."""
    report = evaluate_all(_evaluate(regime, index).corep, None, _FRAMEWORKS[regime])
    return {outcome.rule_id: outcome.status == STATUS_PASS for outcome in report.outcomes}


@cache
def _gateway(index: int) -> dict[str, RuleResult]:
    """The Bank's rules on one registered Basel 3.1 return, filed as the gate files it."""
    # Imported here, as the gate imports it: the script imports RUNS from the gate.
    from scripts.filing_mapping_report import file_on_gateway

    _mapping, validation = file_on_gateway(_evaluate("b31", index).corep)
    assert validation.report is not None, "no PRA001 rule book is packaged"
    return {result.rule_id: result for result in validation.report.results}


@cache
def _book(regime: str) -> _Run:
    """The registered ``default-populations`` run of ``regime``."""
    return _evaluate(regime, _index_of(regime, PORTFOLIO))


def _book_loans(regime: str) -> set[str]:
    return set(_book(regime).ledger["exposure_reference"].to_list())


# ---------------------------------------------------------------------------
# Helpers — rule values and figures
# ---------------------------------------------------------------------------


def _reporting_date(regime: str) -> date:
    """The registered book's reporting date (fails as the other limbs do if unregistered)."""
    return _registered(regime)[_index_of(regime, PORTFOLIO)].build_config().reporting_date


def _article_127_weights(regime: str) -> tuple[float, float, float]:
    """(threshold, 100% weight, 150% weight), read from the resolved pack (LESSONS A4)."""
    pack = resolve(regime, _reporting_date(regime))
    return (
        float(pack.scalar(f"{regime}_defaulted_provision_threshold")),
        float(pack.scalar(f"{regime}_defaulted_rw_high_provision")),
        float(pack.scalar(f"{regime}_defaulted_rw_low_provision")),
    )


def _article_127_3_weight(regime: str) -> float:
    """The Art. 127(3) weight of a residential default, from the resolved pack.

    PS1/26 states it as its own entry; the CRR engine weights the Art. 125-secured share
    of a defaulted residential loan at the Art. 127(1)(b) entry
    (``crr_real_estate.py::crr_defaulted_re_secured_share_expr``), and this book's loan
    is secured whole (60% LTV, inside Art. 125's 80%).
    """
    pack = resolve(regime, _reporting_date(regime))
    name = {
        "b31": "b31_defaulted_resi_re_non_income_rw",
        "crr": "crr_defaulted_rw_high_provision",
    }[regime]
    return float(pack.scalar(name))


def _memo_row_and_weight(regime: str, loan: str) -> tuple[str, float]:
    """Row 0300 at 100% for an Art. 127(1)(b) or Art. 127(3) leg, else row 0320 at 150%."""
    threshold, high, low = _article_127_weights(regime)
    if loan == LN_RRE_DEF:
        return ROW_MEMO_100, _article_127_3_weight(regime)
    if PROVISION_SHARE.get(loan, 0.0) >= threshold:
        return ROW_MEMO_100, high
    return ROW_MEMO_150, low


def _protector_weight(regime: str, guarantor: str) -> float:
    """The guarantor's own SA weight at its CQS, from the resolved pack (LESSONS A4).

    The UK sovereign's comes from the CRR pack's Art. 114 Table 1 in both regimes:
    PS1/26 leaves that table unchanged, and the Basel 3.1 engine reads the same entry
    (``engine/sa/b31_risk_weight_tables.py``).
    """
    if guarantor == GUARANTOR[LN_RRE_GTD]:
        table = resolve("crr", _reporting_date("crr")).lookup("cgcb_risk_weights")
    else:
        table = resolve(regime, _reporting_date(regime)).lookup(_INSTITUTION_RW_TABLE[regime])
    return float(dict(table.entries)[CQS(GUARANTOR_CQS[guarantor])])


def _covered_legs(ledger: pl.DataFrame) -> pl.DataFrame:
    """The standardised legs whose protection the calculator applied (Art. 235).

    A ledger with no guarantee input carries no ``is_guarantee_beneficial`` column at all
    (measured on ``equity-transitional``) — ABSENT, not null (LESSONS B1) — and so no
    covered leg.
    """
    if "is_guarantee_beneficial" not in ledger.columns:
        return ledger.clear()
    return ledger.filter(
        pl.col("is_guarantee_beneficial").fill_null(value=False)
        & (pl.col("approach_applied") == "standardised")
    )


def _real_estate_origin_defaults(ledger: pl.DataFrame) -> int:
    real_estate = [
        k for k, v in C07_00_SA_SHEET_MAP.items() if v == _sheet_key("b31", Z_REAL_ESTATE)
    ]
    if "reporting_class_pre_default" not in ledger.columns:
        return 0
    return ledger.filter(
        pl.col("is_defaulted").fill_null(value=False)
        & pl.col("reporting_class_pre_default").is_in(real_estate)
    ).height


def _total_only_memo(corep: COREPTemplateBundle) -> float:
    """Total row 0300 c0010 less what the published class sheets carry in it."""
    total = _sheet_or_none(corep, "b31", Z_TOTAL)
    if total is None:
        return 0.0
    return (_cell(total, ROW_MEMO_100, COL_ORIGINAL) or 0.0) - _memo_sheets_sum(corep, ROW_MEMO_100)


def _memo_sheets_sum(corep: COREPTemplateBundle, row: str) -> float:
    return sum(
        _cell(corep.c07_00[key], row, COL_ORIGINAL) or 0.0
        for key in get_c07_memo_default_sheet_keys("BASEL_3_1")
        if key in corep.c07_00
    )


def _band_ref(framework: str, weight: float) -> str:
    """The row a weight is reported in, read off the template's band list (LESSONS B3)."""
    labels = [
        label
        for rung, label in get_sa_risk_weight_bands(framework)
        if round(rung, 4) == round(weight, 4)
    ]
    assert len(labels) == 1, f"{framework}: {weight} is on no published rung"
    refs = [
        row.ref for row in get_sa_row_sections(framework)[_RW_SECTION].rows if row.name == labels[0]
    ]
    assert len(refs) == 1, f"{framework}: band {labels[0]!r} names rows {refs}"
    return refs[0]


# ---------------------------------------------------------------------------
# Helpers — sheets and cells
# ---------------------------------------------------------------------------


def _sheet_key(regime: str, z_code: str) -> str:
    """The bundle key a published z-code names (LESSONS B3: never spelled here)."""
    keys = SHEET_INDEX_MAPS["c07" if regime == "crr" else "of07"][z_code].bundle_keys
    assert len(keys) == 1, f"z{z_code} names {keys}"
    return keys[0]


def _sheet_or_none(corep: COREPTemplateBundle, regime: str, z_code: str) -> pl.DataFrame | None:
    return corep.c07_00.get(_sheet_key(regime, z_code))


def _sheet(corep: COREPTemplateBundle, regime: str, z_code: str) -> pl.DataFrame:
    frame = _sheet_or_none(corep, regime, z_code)
    assert frame is not None, f"[{regime}] sheet z{z_code} not emitted: {sorted(corep.c07_00)}"
    return frame


def _cell(sheet: pl.DataFrame, row_ref: str, column: str) -> float | None:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"row {row_ref} appears {row.height} times"
    value = row[column][0]
    return None if value is None else float(value)


def _of_loan(loan: str) -> pl.Expr:
    """The ledger legs of one loan: itself, or its guarantee split (``__G_`` / ``__REM``)."""
    reference = pl.col("exposure_reference")
    return (reference == loan) | reference.str.starts_with(f"{loan}__")


def _leg(ledger: pl.DataFrame, reference: str) -> dict[str, object]:
    matched = ledger.filter(pl.col("exposure_reference") == reference)
    assert matched.height == 1, f"{reference}: expected one ledger row, got {matched.height}"
    return matched.row(0, named=True)


def _describe(result: RuleResult) -> str:
    return f"{result.rule_id}: {result.status} {result.satisfied}/{result.unsatisfied}"
