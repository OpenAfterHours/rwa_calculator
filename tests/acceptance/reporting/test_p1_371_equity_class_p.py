"""
P1.371 — Article 112(1)(p) equity must reach C 07.00 / OF 07.00, under ONE regime.

Pipeline position:
    build_reporting_bundle() -> PipelineOrchestrator -> COREPGenerator
        -> COREPTemplateBundle.c07_00["equity"] -> evaluate_all()

**Presence is not the claim.** An assertion that the equity sheet is emitted
passes the exact broken state this file exists to forbid: ``c07_population``
admitting the equity leg while the leg still carries NULL for every gross
carrier. Measured on ``b31/rich`` in that half-fixed state, row 0010 publishes

    cols 0010 / 0040 / 0110 / 0150 = 0.00   against   0200 = 1,000,000
                                                      0220 = 2,500,000

— the Annex II waterfall inverted, with the exposure value arriving from
nowhere — and the existing contract
(``test_c07_art112_sheet_axis.py::test_every_emitted_sheet_carries_a_populated_total_row``)
stays GREEN on it, because ``0.00 is not None``. So every money assertion below
is an absolute figure or an internal identity, never "is emitted" and never
"is non-null" alone.

The regime asymmetry is the subtle part, and it is not symmetry at all:

- **Basel 3.1 — ALL equity is in scope.** PS1/26 Annex II ¶48 puts only two
  things outside OF CR SA: class (m) securitisation positions and "exposures
  deducted from own funds". ¶49(a) scopes the template to "credit risk in
  accordance with Credit Risk: Standardised Approach (CRR) Part", which under
  Art. 147A is where ALL equity now is — the pack Feature
  ``equity_irb_approaches_available`` is False under B31, so every equity leg is
  stamped ``equity_method == "sa"``. ¶55C goes further and says class (p)
  "shall include exposures subject to the IRB Transitional Approach described in
  Rules 4.4 to 4.8".
- **CRR — only Art. 133 SA-method equity is in scope.** COREP Annex II ¶50:
  "The template shall include all exposures for which the own funds requirements
  are calculated in accordance with **Chapter 2 of Title II of Part Three CRR**
  in conjunction with Chapters 4 and 6". Chapter 2 is the Standardised Approach;
  Art. 155(2) simple-risk-weight and Art. 155(3) PD/LGD equity are Chapter 3
  (IRB) and are therefore CORRECTLY EXCLUDED. The live EBA ERROR rule
  ``v4244_i`` (``{C 02.00, r0210, c0010} == {C 07.00.a, r0010, c0220, s0016}``)
  is what makes that a hard boundary rather than a preference.

The estate's ``crr/rich`` equity leg is ``equity_method == "irb_simple"``, so
CRR is a live NEGATIVE CONTROL and not a vacuous one — measured, an
implementation admitting equity without consulting the method emits a CRR
equity sheet carrying c0220 = 2,900,000 against C 02.00 r0210 = 0.00 and
``v4244_i`` FAILS on it. ``TestCrrExcludesIrbMethodEquity`` is that measurement
turned into assertions.

Deliberately NOT asserted here:
- any ``reporting_gross_*`` carrier by name. Two implementations reach the same
  submission — sealing the side carriers on the equity leg, or widening
  ``c07.py``'s own ``c07_ccr_gross`` fallback — and the regulation constrains
  the template, not the carrier. Every assertion is on the rendered cell.
- OF 07.00 memorandum rows 0371-0374 as POPULATED. They are declared and they
  stay dark; ``TestEquityTransitionalMemoRowsStayDark`` records why.

References:
- CRR Art. 112(1)(p) equity exposures; Art. 133 (SA); Art. 155(2)/(3) (IRB)
- COREP Annex II ¶48, ¶50 (scope of CR SA); ¶56 (sequential class assignment)
- PRA PS1/26 Annex II ¶48, ¶49, ¶55A-¶55E (scope of OF CR SA; class (p) memo rows)
- PRA PS1/26 Art. 133(3)-(5) (pack ``equity_sa_risk_weights``: listed 250%)
- CRR Art. 155(2) (pack ``equity_irb_simple_risk_weights``: listed 290%)
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.reporting_portfolio import EQ_LISTED, build_reporting_bundle

from rwa_calc.domain.enums import EquityApproach
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.c02 import _EQUITY_IRB_METHODS
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import EQUITY_IRB_METHODS
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.validations.checker import evaluate_all
from rwa_calc.reporting.validations.scope import SHEET_INDEX_MAPS

if TYPE_CHECKING:
    from rwa_calc.reporting.validations.checker import ValidationReport

#: regime key -> (framework string, the ``SHEET_INDEX_MAPS`` entry for its C 07.00)
_REGIMES: dict[str, tuple[str, str]] = {"crr": ("CRR", "c07"), "b31": ("BASEL_3_1", "of07")}

#: The published z-code for Article 112(1)(p). Read off ``validations/scope.py``
#: below rather than hard-coded as a sheet NAME: the bundle key is whatever
#: ``SheetCode.bundle_keys`` says it is, and a test that spelled ``"equity"``
#: itself would share ``corep/c07.py``'s assumption instead of checking it
#: (``.claude/LESSONS.md`` B3).
_Z_CODE_112_P: str = "0016"

#: ``RP-EQ-LISTED`` carrying value / fair value — ``tests/fixtures/reporting_portfolio.py``.
#: There is no CCF on an equity holding, so this is simultaneously the original
#: exposure pre-conversion (col 0010) and the exposure value (col 0200).
_EQUITY_EXPOSURE: float = 1_000_000.0

#: 1,000,000 x 250%. Pack ``equity_sa_risk_weights[LISTED] = 2.50`` under Basel
#: 3.1 (PS1/26 Art. 133(3)-(5)).
_B31_EQUITY_RWEA: float = 2_500_000.0

#: 1,000,000 x 290%. Pack ``equity_irb_simple_risk_weights[LISTED] = 2.90``
#: (CRR Art. 155(2)) — the figure that must NOT appear on any CRR C 07.00 sheet.
_CRR_EQUITY_RWEA: float = 2_900_000.0

#: The three supervisory rules the half-fixed state (population widened, gross
#: carriers still null) breaks. Named so a future regression points straight at
#: the cause rather than at "some reporting rule". Measured, in that state, on
#: ``b31/rich``: all three FAIL on 2 coordinates with lhs 1,000,000 / rhs 0.00.
#:
#: - ``boe_b0471`` ERROR   c0200 = c0150 - the CCF-bucket complement
#: - ``boe_b0556`` WARNING c0200 <= c0150
#: - ``boe_b0717`` WARNING r0010 = sum(r0070; 0080; 0090; 0110; 0130) on c0200/c0220
#:
#: Their z-scopes all include z:0016; their ``_1`` / ``_2`` / ``_3`` family
#: members are scoped to the memo rows 0300/0320/0380, whose z-lists do NOT
#: include 0016, so the family is enumerated and this is all of it
#: (``.claude/LESSONS.md`` C6).
_RULES_BROKEN_BY_HALF_A_FIX: tuple[str, ...] = ("boe_b0471", "boe_b0556", "boe_b0717")

#: The EBA ERROR rule that fixes the CRR boundary: C 02.00 r0210 (SA equity)
#: against the C 07.00 s0016 RWEA.
_CRR_SA_EQUITY_TIE_RULE: str = "v4244_i"

#: Annex II exposure-type rows row 0010 must foot to, exactly ``boe_b0717``'s
#: right-hand side. 0100 / 0120 are "of which: QCCP" of 0090 / 0110 and are
#: deliberately absent — including them would double-count.
_EXPOSURE_TYPE_ROWS: tuple[str, ...] = ("0070", "0080", "0090", "0110", "0130")


# ---------------------------------------------------------------------------
# Shared run
# ---------------------------------------------------------------------------


@lru_cache(maxsize=len(_REGIMES))
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle, ValidationReport]:
    """The golden reporting estate under one regime, memoised.

    Uses ``test_reporting_golden``'s own config factories so this file cannot
    drift onto a different estate than the goldens and the supervisory register
    describe.
    """
    framework, _sheet_map = _REGIMES[regime_key]
    config = _crr_config() if regime_key == "crr" else _b31_config()
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    report = evaluate_all(corep, pillar3, framework)
    return result.results.collect(), corep, report


def _equity_sheet_key(regime_key: str) -> str:
    """The bundle key the published z-code 0016 names, from ``scope.py``.

    The single source of truth for "which sheet is Article 112(1)(p)", and it is
    not this file. ``arch_check`` check 22 holds that a ``SheetCode`` carries at
    most one bundle key, so the cardinality assertion here is a contract, not a
    convenience.
    """
    _framework, sheet_map = _REGIMES[regime_key]
    keys = SHEET_INDEX_MAPS[sheet_map][_Z_CODE_112_P].bundle_keys
    assert len(keys) == 1, f"{sheet_map} z:{_Z_CODE_112_P} names {keys}, expected exactly one key"
    return keys[0]


def _cell(corep: COREPTemplateBundle, sheet: str, row_ref: str, column: str) -> float | None:
    """One cell, with the sheet's presence asserted first and a message.

    Indexing the dict would raise ``KeyError`` for a sheet that was never
    emitted, and an absent sheet is the defect this file describes — so it gets
    an assertion naming the axis that WAS emitted, not a traceback.
    """
    assert sheet in corep.c07_00, (
        f"C 07.00 sheet {sheet!r} not emitted; the axis holds {sorted(corep.c07_00)}"
    )
    matched = corep.c07_00[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected exactly one row {row_ref}, got {matched.height}"
    return matched[column][0]


def _magnitude(value: float | None) -> float:
    """A deduction cell as the positive magnitude the Annex II waterfall uses.

    ``corep/postpass.py::negate_deduction_cols`` applies the Annex II §1.3 "(-)"
    sign convention AFTER the template executes, negating {0030, 0035, 0050,
    0060, 0070, 0080, 0090, 0130, 0140}. The intra-row formulas are defined over
    positive magnitudes, so a test restating them has to undo that. Null reads
    as zero here and only here — the non-null claims are made separately.
    """
    return abs(value or 0.0)


def _outcome(report: ValidationReport, rule_id: str) -> object:
    matched = [outcome for outcome in report.outcomes if outcome.rule_id == rule_id]
    assert len(matched) == 1, f"expected exactly one {rule_id} outcome, got {len(matched)}"
    return matched[0]


# ---------------------------------------------------------------------------
# Adequacy — LESSONS C11 / C2
# ---------------------------------------------------------------------------


class TestTheEstateCanTellTheTwoRegimesApart:
    """The fixture is a claim; these are its terms.

    Every assertion downstream rests on ONE equity leg whose ``equity_method``
    differs by regime. If it did not differ, ``TestCrrExcludesIrbMethodEquity``
    would pass under an implementation that admits all equity regardless of
    method — the exact over-wide fix this file exists to reject — and nothing
    would say so.
    """

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_estate_carries_exactly_one_equity_leg(self, regime_key: str) -> None:
        results, _corep, _report = _run(regime_key)

        legs = results.filter(pl.col("reporting_approach_origin") == "equity")
        assert legs.height == 1, (
            f"{regime_key}: expected one equity leg, got {legs.height} — the absolute "
            "figures below are derived from RP-EQ-LISTED alone"
        )
        assert legs["source_exposure_reference"][0] == EQ_LISTED

    def test_the_same_leg_is_sa_method_under_b31_and_irb_method_under_crr(self) -> None:
        """The asymmetry, measured rather than assumed. ``equity_method`` is the
        only thing that differs, so it is the only thing the two regimes'
        opposite verdicts can turn on."""
        crr_results, _crr_corep, _crr_report = _run("crr")
        b31_results, _b31_corep, _b31_report = _run("b31")

        crr_method = crr_results.filter(pl.col("reporting_approach_origin") == "equity")[
            "equity_method"
        ][0]
        b31_method = b31_results.filter(pl.col("reporting_approach_origin") == "equity")[
            "equity_method"
        ][0]
        assert crr_method == EquityApproach.IRB_SIMPLE.value, (
            "the CRR equity leg is not IRB-method, so excluding it from C 07.00 is "
            f"not what this estate tests; got {crr_method!r}"
        )
        assert b31_method == EquityApproach.SA.value, (
            "the Basel 3.1 equity leg is not SA-method, so admitting it is not what "
            f"PS1/26 Art. 147A implies; got {b31_method!r}"
        )

    def test_both_regimes_put_a_non_zero_rwea_on_the_equity_leg(self) -> None:
        """``.claude/LESSONS.md`` C2 applied to a scope boundary: a 0%-weighted
        equity leg would make the CRR tie ``C 02.00 r0210 == C 07.00 c0220``
        hold at 0.00 == 0.00 whether the sheet were emitted or not, and the
        negative control would prove nothing. Measure the amount that crosses."""
        for regime_key, expected in (("crr", _CRR_EQUITY_RWEA), ("b31", _B31_EQUITY_RWEA)):
            results, _corep, _report = _run(regime_key)
            rwea = results.filter(pl.col("reporting_approach_origin") == "equity")["rwa_final"][0]
            assert rwea == pytest.approx(expected), (
                f"{regime_key}: equity RWEA {rwea} is not the pack's listed-equity weight "
                f"on 1,000,000 — the scope assertions below would not discriminate"
            )

    def test_the_excluded_method_set_is_the_enum_minus_the_sa_limb(self) -> None:
        """Anchored on ``domain.enums.EquityApproach``, which cannot drift with
        either reporting module, and asserted over BOTH consumers of the shared
        constant.

        ``templates.EQUITY_IRB_METHODS`` is the single definition of "equity
        reported under the IRB umbrella": C 02.00 routes row 0420 / the IRB total
        by it and C 07.00's admission is its complement. Asserting it against the
        ENUM rather than against a hand-written list is the point — a test and a
        predicate written from the same sentence validate nothing
        (``.claude/LESSONS.md`` B3). The enum's cardinality is asserted too, so a
        FOURTH method cannot be silently admitted to C 07.00 by a predicate
        spelled "not the two IRB ones".

        ``c02.py``'s module-private alias is read as well, because ``corep/c07.py``
        records that the two copies of this list must not drift — one import is
        what makes that executable rather than a comment.
        """
        assert {member.value for member in EquityApproach} == {"sa", "irb_simple", "pd_lgd"}
        assert set(EQUITY_IRB_METHODS) == {
            EquityApproach.IRB_SIMPLE.value,
            EquityApproach.PD_LGD.value,
        }
        assert _EQUITY_IRB_METHODS is EQUITY_IRB_METHODS, (
            "C 02.00 and C 07.00 no longer read one definition of IRB-method equity"
        )


# ---------------------------------------------------------------------------
# Basel 3.1 — the class is reported, and the waterfall holds
# ---------------------------------------------------------------------------


class TestBasel31ReportsArticle112P:
    """PS1/26 Annex II ¶48/¶49: every equity leg is SA under Art. 147A, and only
    securitisation and own-funds deductions are outside OF CR SA."""

    def test_the_equity_sheet_is_emitted_and_addressable_by_the_published_z_axis(self) -> None:
        """The weakest claim in the file, and it is here only so the stronger
        ones have something to index. A sheet no ``SheetCode`` names resolves to
        ``sheet_not_emitted`` and every rule scoped to z:0016 scores
        NOT_EVALUATED — the gate fails OPEN, which is how this was invisible."""
        _results, corep, _report = _run("b31")

        assert _equity_sheet_key("b31") in corep.c07_00, (
            f"OF 07.00 emits no Article 112(1)(p) sheet; the axis holds {sorted(corep.c07_00)}"
        )

    def test_row_0010_reports_the_equity_carrying_value_not_zero(self) -> None:
        """Col 0010 is ORIGINAL EXPOSURE PRE-CONVERSION FACTORS. The half-fixed
        state publishes 0.00 here — a sheet that claims it looked at the book
        and found no exposure, beside a col 0200 of 1,000,000. An absolute
        figure is the only assertion that separates the two."""
        value = _cell(_run("b31")[1], _equity_sheet_key("b31"), "0010", "0010")

        assert value is not None, "row 0010 col 0010 is NULL"
        assert value == pytest.approx(_EQUITY_EXPOSURE)

    def test_every_money_column_on_row_0010_is_non_null(self) -> None:
        """``.claude/LESSONS.md`` B4: the portfolio HAS equity exposure, so a
        null in the spine is a cell that published nothing, not a zero someone
        measured. Asserted per column so the failure names which one."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]

        for column in ("0010", "0040", "0110", "0150", "0200", "0220"):
            assert _cell(corep, sheet, "0010", column) is not None, (
                f"row 0010 col {column} is NULL on the Article 112(1)(p) sheet"
            )

    def test_the_annex_ii_intra_row_waterfall_holds(self) -> None:
        """0040 = 0010 - 0030; 0110 = 0040 - 0090 + 0100; 0150 = max(0, 0110 -
        0130). Stated over the rendered cells rather than over the carriers, so
        it holds whichever way the gross side is sealed — and it is exactly what
        a population widened without its gross carriers breaks: the half-fixed
        state satisfies this trivially at 0 = 0 - 0 while col 0200 carries
        1,000,000, which is why the absolute tests above exist alongside it."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]
        cells = {
            ref: _cell(corep, sheet, "0010", ref)
            for ref in ("0010", "0030", "0040", "0090", "0100", "0110", "0130", "0150")
        }

        assert cells["0040"] == pytest.approx(cells["0010"] - _magnitude(cells["0030"]))
        assert cells["0110"] == pytest.approx(
            cells["0040"] - _magnitude(cells["0090"]) + (cells["0100"] or 0.0)
        )
        assert cells["0150"] == pytest.approx(max(0.0, cells["0110"] - _magnitude(cells["0130"])))

    def test_the_exposure_value_does_not_exceed_the_fully_adjusted_value(self) -> None:
        """``boe_b0556``'s own identity, restated so it is asserted on THIS
        sheet rather than inferred from an aggregated rule outcome. 0200 is the
        post-conversion exposure value and 0150 the fully adjusted value it is
        derived from; an equity holding has no CCF, so for this leg they are
        equal — an inequality that passes as an exact equality, which
        ``.claude/LESSONS.md`` C7 says to check rather than celebrate. Here
        nothing cancelled: equity carries no off-balance-sheet side at all."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]

        fully_adjusted = _cell(corep, sheet, "0010", "0150")
        exposure_value = _cell(corep, sheet, "0010", "0200")
        assert exposure_value is not None
        assert fully_adjusted is not None
        assert exposure_value <= fully_adjusted + 1e-6
        assert fully_adjusted == pytest.approx(_EQUITY_EXPOSURE)
        assert exposure_value == pytest.approx(_EQUITY_EXPOSURE)

    def test_the_rwea_is_the_art_133_listed_equity_weight(self) -> None:
        """1,000,000 x 250% (pack ``equity_sa_risk_weights[LISTED]``, PS1/26
        Art. 133(3)-(5))."""
        value = _cell(_run("b31")[1], _equity_sheet_key("b31"), "0010", "0220")

        assert value == pytest.approx(_B31_EQUITY_RWEA)

    def test_the_rwea_ties_to_of_02_00_row_0210(self) -> None:
        """The cross-template identity, against the SIBLING template rather than
        a literal. OF 02.00 row 0210 is "See OF CR SA template" for Article
        112(1)(p), and it already reported 2,500,000 while no sheet existed to
        tie it to — that orphaned total IS the defect, stated as an identity."""
        _results, corep, _report = _run("b31")
        assert corep.c_02_00 is not None

        row = corep.c_02_00.filter(pl.col("row_ref") == "0210")
        assert row.height == 1
        assert _cell(corep, _equity_sheet_key("b31"), "0010", "0220") == pytest.approx(
            row["0010"][0]
        )


class TestTheLegLandsOnARealRow:
    """A total row with no exposure-type row beneath it is the half-fixed state's
    signature: ``boe_b0717`` (r0010 = sum of the exposure-type rows) was one of
    the three rules it broke, because every one of those rows rendered ALL-NULL.
    """

    def test_the_equity_holding_is_reported_as_an_on_balance_sheet_exposure(self) -> None:
        """Row 0070 "On balance sheet exposures subject to credit risk". An
        equity holding is on the balance sheet; row 0080 (off-balance-sheet) must
        stay NULL rather than publish a zero it never measured."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]

        on_bs = _cell(corep, sheet, "0070", "0010")
        assert on_bs is not None, (
            "row 0070 'On balance sheet exposures' is NULL — the leg is on the sheet "
            "total but on no exposure-type row, so boe_b0717 cannot foot"
        )
        assert on_bs == pytest.approx(_EQUITY_EXPOSURE)
        assert _cell(corep, sheet, "0080", "0010") is None, (
            "row 0080 publishes a figure for off-balance-sheet equity, which the "
            "portfolio does not hold"
        )

    @pytest.mark.parametrize("column", ["0200", "0220"])
    def test_row_0010_foots_to_the_exposure_type_rows(self, column: str) -> None:
        """``boe_b0717``, on its own two columns. The breakdown sums to its
        parent — a sheet whose exposure-type rows are all null still looks
        plausible row by row, and only the footing shows it
        (``.claude/LESSONS.md`` E2)."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]

        total = _cell(corep, sheet, "0010", column)
        breakdown = sum(
            float(_cell(corep, sheet, row_ref, column) or 0.0) for row_ref in _EXPOSURE_TYPE_ROWS
        )
        assert total is not None
        assert breakdown == pytest.approx(total), (
            f"col {column}: row 0010 reports {total} but rows {_EXPOSURE_TYPE_ROWS} "
            f"sum to {breakdown}"
        )

    def test_the_leg_lands_in_the_250_percent_risk_weight_band(self) -> None:
        """Row 0250 is the declared 250% rung, and ``boe_b0491`` asserts
        ``c0220 == c0200 * 2.5`` on it for z:0016 among others — a rule that is
        VACUOUS on this estate until the equity sheet reports. Row 0280 "Other
        risk weights" must stay NULL: landing there would mean the band ladder
        did not recognise the Art. 133 weight (which is what happens under CRR,
        where 290% has no declared rung)."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]

        banded_ead = _cell(corep, sheet, "0250", "0200")
        banded_rwea = _cell(corep, sheet, "0250", "0220")
        assert banded_ead is not None, "the 250% risk-weight row 0250 is NULL"
        assert banded_ead == pytest.approx(_EQUITY_EXPOSURE)
        assert banded_rwea == pytest.approx(_B31_EQUITY_RWEA)
        assert banded_rwea == pytest.approx(banded_ead * 2.5)
        assert _cell(corep, sheet, "0280", "0220") is None, (
            "the equity leg landed in row 0280 'Other risk weights' — the 250% rung "
            "did not recognise the Art. 133 weight"
        )


class TestTheNamedSupervisoryRulesStayGreen:
    """The three rules the half-fixed state breaks, asserted by ID.

    Every identity they state is also asserted directly above, on the equity
    sheet's own cells — so this class is the cross-check that the evaluator
    agrees, not the only place the property is held. Without the direct
    assertions a PASS here could be a rule that never reached z:0016.
    """

    @pytest.mark.parametrize("rule_id", list(_RULES_BROKEN_BY_HALF_A_FIX))
    def test_the_rule_reaches_a_verdict_and_does_not_fail(self, rule_id: str) -> None:
        _results, _corep, report = _run("b31")

        outcome = _outcome(report, rule_id)
        assert outcome.status != "NOT_EVALUATED", (
            f"{rule_id} was not evaluated ({outcome.reason}) — this assertion would "
            "be vacuous, which is exactly how the missing sheet hid"
        )
        assert outcome.failed == 0, (
            f"{rule_id} fails on {outcome.failed} coordinate(s): {outcome.coordinates}"
        )


# ---------------------------------------------------------------------------
# CRR — the negative control
# ---------------------------------------------------------------------------


class TestCrrExcludesIrbMethodEquity:
    """COREP Annex II ¶50 scopes C 07.00 to Chapter 2 of Title II of Part Three
    CRR — the Standardised Approach. Art. 155(2) simple-risk-weight equity is
    Chapter 3, so it belongs on C 08.x, not here.

    This is the control that stops the Basel 3.1 half of this file being
    satisfied by "admit every equity leg". Measured: the over-wide version emits
    a CRR equity sheet carrying c0220 = 2,900,000 against C 02.00 r0210 = 0.00,
    and the live EBA ERROR rule ``v4244_i`` FAILS on it.
    """

    def test_no_article_112_p_sheet_is_emitted_under_crr(self) -> None:
        _results, corep, _report = _run("crr")

        assert _equity_sheet_key("crr") not in corep.c07_00, (
            "C 07.00 emits an Article 112(1)(p) sheet under CRR for an "
            "Art. 155(2) IRB-method equity leg; COREP Annex II para 50 scopes this "
            "template to Chapter 2 of Title II of Part Three CRR"
        )

    def test_c_02_00_row_0210_reports_no_sa_equity_under_crr(self) -> None:
        """The other side of the same boundary. ``c02.py`` routes an
        ``irb_simple`` leg away from row 0210 (the SA equity row) by design, so
        row 0210 is 0.00 while the book holds 2,900,000 of equity RWEA. A
        C 07.00 equity sheet would therefore have nothing on C 02.00 to tie to —
        which is what ``v4244_i`` detects."""
        results, corep, _report = _run("crr")
        assert corep.c_02_00 is not None

        row = corep.c_02_00.filter(pl.col("row_ref") == "0210")
        assert row.height == 1
        assert (row["0010"][0] or 0.0) == pytest.approx(0.0)

        book_equity_rwea = results.filter(pl.col("reporting_approach_origin") == "equity")[
            "rwa_final"
        ].sum()
        assert book_equity_rwea == pytest.approx(_CRR_EQUITY_RWEA), (
            "the CRR book holds no equity RWEA, so row 0210 being 0.00 is not evidence of anything"
        )

    def test_the_eba_sa_equity_tie_rule_does_not_fail_under_crr(self) -> None:
        """``v4244_i``: ``{C 02.00, r0210, c0010} == {C 07.00.a, r0010, c0220,
        s0016}``. With the sheet correctly absent it scores
        ``sheet_not_emitted`` — NOT_EVALUATED, not PASS, and that distinction is
        recorded here deliberately rather than asserted away: a 0.00-RWEA class
        with no sheet is the honest reading, and the rule firing at all would
        mean the boundary had moved."""
        _results, _corep, report = _run("crr")

        outcome = _outcome(report, _CRR_SA_EQUITY_TIE_RULE)
        assert outcome.status != "FAIL", (
            f"{_CRR_SA_EQUITY_TIE_RULE} fails on {outcome.coordinates} — an IRB-method "
            "equity leg has reached the CRR C 07.00 template"
        )
        assert outcome.reason == "sheet_not_emitted", (
            f"{_CRR_SA_EQUITY_TIE_RULE} resolved {outcome.status}/{outcome.reason!r}; "
            "under CRR the Article 112(1)(p) sheet is expected to be absent"
        )


# ---------------------------------------------------------------------------
# OF 07.00 rows 0371-0374 — declared, and still dark
# ---------------------------------------------------------------------------


class TestEquityTransitionalMemoRowsStayDark:
    """PS1/26 Annex II ¶55A-¶55D: rows 0371-0374 are reportable for class (p)
    ALONE, so they become reachable the moment this sheet exists — and they
    still cannot be filled.

    ¶55B scopes 0371/0372 to exposures under Rules 4.1-4.3 of the Credit Risk:
    General Provisions (CRR) Part and ¶55C scopes 0373/0374 to Rules 4.4-4.8
    (the IRB Transitional Approach). ``corep/c07.py`` already declares the rows
    and keys them on ``equity_transitional_approach`` / ``equity_higher_risk``,
    which ``engine/equity/calculator.py`` produces — but NEITHER is an
    ``AGGREGATOR_EXIT`` edge column, so neither survives to the reporting frame.
    The rows are therefore structurally null, not empty-because-measured, and
    the ERROR rule ``boe_b0710_2`` (scoped to r0371-0374, z:0016 alone) scores
    VACUOUS rather than PASS.

    Recorded as assertions so this is a known gap rather than an assumed fix.
    Sealing either carrier makes the last test below RED — when that happens,
    wire the rows; do not relax the assertion.
    """

    def test_the_rows_are_declared_on_the_sheet(self) -> None:
        """The template half IS done. Asserted separately from the values so a
        future reader does not read "null" as "not implemented"."""
        sheet = _equity_sheet_key("b31")
        corep = _run("b31")[1]

        assert sheet in corep.c07_00, (
            f"C 07.00 sheet {sheet!r} not emitted; the axis holds {sorted(corep.c07_00)}"
        )
        declared = set(corep.c07_00[sheet]["row_ref"].to_list())
        assert {"0371", "0372", "0373", "0374"} <= declared, (
            f"OF 07.00 declares no equity transitional memo rows; got {sorted(declared)}"
        )

    @pytest.mark.parametrize("row_ref", ["0371", "0372", "0373", "0374"])
    @pytest.mark.parametrize("column", ["0010", "0200", "0220"])
    def test_the_rows_publish_null_rather_than_a_measured_zero(
        self, row_ref: str, column: str
    ) -> None:
        sheet = _equity_sheet_key("b31")

        assert _cell(_run("b31")[1], sheet, row_ref, column) is None

    def test_neither_transitional_carrier_survives_to_the_reporting_frame(self) -> None:
        """The reason, stated where it can be checked rather than in prose.

        This is the gap that keeps rows 0371-0374 dark, and it is the one thing
        a future change can fix. If this test goes red, the carrier has been
        sealed — light the rows.
        """
        results, _corep, _report = _run("b31")

        absent = {"equity_transitional_approach", "equity_higher_risk"} - set(results.columns)
        assert absent == {"equity_transitional_approach", "equity_higher_risk"}, (
            "an equity transitional carrier now reaches the reporting frame; OF 07.00 "
            f"rows 0371-0374 are populatable and should be wired (present: {absent})"
        )
