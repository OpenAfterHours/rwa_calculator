"""
C 07.00 row 0040 — the row-level EXPOSURE-CLASS scope, on a portfolio that can
violate it.

Pipeline position:
    build_reporting_row_scope_bundle() -> PipelineOrchestrator
        -> COREPGenerator -> COREPTemplateBundle.c07_00 -> evaluate_all

What this file is for. COREP Annex II scopes row 0040 to one exposure class, in a
sentence of its own:

    0040  of which: Secured by mortgages on immovable property - Residential
          property.  Article 125 CRR
          Only reported in exposure class 'Secured by mortgages on immovable
          property'

Rows are evaluated PER SHEET, so the engine carries that sentence as a term
beside the row's data term (``corep/c07.py::_SHEET_KEY_COL``). On the eight
registered reporting portfolios the term is UNOBSERVABLE: stripping it changes no
published figure, because none of them puts a residential-property-secured leg on
a sheet other than ``real_estate``. A green suite was therefore not evidence the
scope worked — the code was right and unreachable, which is indistinguishable
from right and untested, and is exactly the state this file ends.

The three assertions that carry the file, in order of how much they prove:

1. **Row 0310 is populated on the same sheet where row 0040 is null.** 0310 is
   the CRR memorandum twin — the SAME ``property_type == "residential"``
   predicate, with no class scope, because Annex II words it differently ("This
   is a memorandum item only. Independent from the calculation of risk exposure
   amounts ... the exposures shall be broken down and reported in this row if the
   exposures are secured by real estate property", row 0310, and no "Only
   reported in exposure class" sentence). So on the ``corporate`` sheet the
   predicate MATCHES 2,000,000 and row 0040 still publishes nothing. Nothing else
   in this file separates "the scope is doing work" from "the predicate found
   nothing to report" — a null row is the same shape either way.
2. **Row 0040 survives on the real-estate sheet**, at 400,000 / 140,000. A test
   that only asserted the null could not tell a working scope from a row zeroed
   everywhere (``.claude/LESSONS.md`` B5's two-leg pattern).
3. **The published rule agrees.** ``{r0040} = empty`` is evaluated over the
   generated bundle and asserted not-FAIL, with the family enumerated from the
   rule catalogue by its formula rather than from the two ids a brief named
   (LESSONS C6). Stripping the scope turns both members FAIL, which is the
   measured discrimination recorded in ``tests/mutations/README.md`` and
   reproducible with ``-p mutate_row_0040_is_not_sheet_scoped``.

**The Basel 3.1 half (P2.57) is asserted here too.** PS1/26 Annex II gives OF
07.00 rows 0330 and 0331 the identical sentence ("Only reported in exposure class
'real estate exposures' (Article 112(1)(i) ...)"), with 0332 the other half of
0330's "Sum of rows 0331-0332". P2.57 was filed as latent on "0 out-of-scope
populated cells across 26 runs", and this fixture is what made that false: before
the scope reached ``_re_terms``, rows 0330 and 0332 each published **2,000,000**
on the ``corporate`` sheet here. ``TestBasel31RowScope`` carries the assertions,
including which members of the wider 0330-0360 family this fixture can and cannot
place out of scope, and why.

Note what the CRR half has and the Basel 3.1 half does not: **a published rule.**
There is no ``{r0330} = empty`` in either extract, so the supervisory register can
never catch a regression on those rows and ``TestBasel31RowScope`` is the only
gate they will ever have. That is why each of its assertions is stated over every
money column rather than over the total alone, and why the isolating mutation
(``tests/mutations/mutate_row_0040_is_not_sheet_scoped``) is part of the evidence
rather than a nicety.

Two things deliberately NOT asserted, both because a correct fix elsewhere would
have to undo them:

- **Rows 0290 / 0300 / 0310 / 0320 are not asserted as a family, and nothing here
  says where they must NOT appear.** They are Annex II ¶51-55 memorandum items
  with their own class list, which genuinely differs by regime, and rows
  0300/0320 on the ``defaulted`` sheet are *required* by ¶55's worked example.
  That is P1.377. The one exception is the single 0310 assertion in
  ``TestRowScopeUnderCRR``, which is safe because ¶52 lists ``(e) Corporates``
  explicitly — see that test's own docstring.
- **Row 0040 == row 0310 on the real-estate sheet.** It holds today, and ¶52 does
  *not* list class (i), so a P1.377 regime split could legitimately take 0310 off
  that sheet. The figures are asserted against the fixture's own amounts instead.

References:
- COREP Annex II ¶51-55 and C 07.00 rows 0040 / 0290 / 0310
  (crr-annex-ii-reporting-instructins.pdf, 0-indexed pp. 78-79, 90, 93-94)
- PRA PS1/26 Annex II, OF 07.00 rows 0330 / 0331 / 0332 (0-indexed p. 89)
- CRR Art. 124(1), Art. 125(1)(a), Art. 125(2)(b), Art. 125(2)(d)
- PS1/26 Art. 124F / 124G / 124I; Art. 126(2) (the commercial mirror image)
- EBA v7477_m (C 07.00.a) / v7478_m (C 07.00.b): ``{r0040} = empty``, live WARNING
- reporting/validations/scope.py::SHEET_INDEX_MAPS — the published z-axis
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl
import pytest
from tests.fixtures.reporting_row_scope_portfolio import (
    CORPORATE_SHEET_TOTAL,
    DRAWN_CORP_IPRE,
    DRAWN_RRE,
    LN_CORP_IPRE,
    LTV_RRE,
    VALUE_RRE,
    build_reporting_row_scope_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa.b31_risk_weight_tables import (
    B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO,
    B31_RESIDENTIAL_GENERAL_SECURED_RW,
)
from rwa_calc.engine.sa.crr_risk_weight_tables import RESIDENTIAL_MORTGAGE_PARAMS
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.validations import (
    SHEET_INDEX_MAPS,
    STATUS_FAIL,
    evaluate_all,
)

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

#: The row under test, and its unscoped memorandum twin.
_ROW_SCOPED: str = "0040"
_ROW_MEMO_RESIDENTIAL: str = "0310"
_ROW_TOTAL: str = "0010"

#: The Basel 3.1 rows this fixture can place on an out-of-scope sheet. The wider
#: scoped family is 0330-0344 / 0350-0354 / 0360; see ``TestBasel31RowScope`` for
#: which members are unreachable here and the measured reason for each.
_B31_SCOPED_ROWS: tuple[str, ...] = ("0330", "0332")

#: The formula every member of the scope's rule family carries, verbatim from the
#: published extract. The family is enumerated by this rather than by rule id:
#: ``v7477_m`` and ``v7478_m`` are two members (one per DPM column variant) and a
#: brief that named only one would have built to half the family (LESSONS C6).
_SCOPE_RULE_FORMULA: str = "{r0040} = empty"

#: The money spine, as ``test_re_split_template_coverage`` and
#: ``test_c07_art112_class_axis`` use it: 0010 original exposure, 0040 net of
#: value adjustments, 0110 after CRM substitution, 0200 exposure value, 0220 RWEA.
_MONEY_COLS: tuple[str, ...] = ("0010", "0040", "0110", "0200", "0220")

#: Art. 125(1)(a) / 125(2)(d), read back from the rulepack through the SA
#: risk-weight shim rather than typed — a hand-written 0.35 here would be a second
#: home for a regulatory value (``.claude/LESSONS.md`` A4).
_RRE_LOW_LTV_RW: float = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"])
_RRE_LTV_THRESHOLD: float = float(RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"])

#: PS1/26 Art. 124F, likewise read back from the pack through the Basel 3.1 SA
#: shim: the 20% weight on the secured portion and the 55%-of-property-value cap
#: that portion is measured against.
_B31_SECURED_RW = B31_RESIDENTIAL_GENERAL_SECURED_RW
_B31_MAX_SECURED_RATIO = B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO


@lru_cache(maxsize=len(_REGIMES))
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """The row-scope portfolio under one regime, memoised.

    ``PermissionMode.STANDARDISED`` with no model permissions in the bundle, so
    there is no path by which a leg could route IRB and quietly report nothing on
    an SA template.
    """
    config = (
        CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
        if regime_key == "crr"
        else CalculationConfig.basel_3_1(
            reporting_date=date(2027, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_row_scope_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=_REGIMES[regime_key])
    return result.results.collect(), corep


def _real_estate_sheet() -> str:
    """The one bundle key the published z-axis gives Art. 112(1)(i).

    Resolved through ``SHEET_INDEX_MAPS`` — the cited z-code -> bundle-key map
    that the supervisory rules index — and NOT through
    ``templates.C07_00_SA_SHEET_MAP``, which is what the code under test reads.
    A test that anchored on the same map as the implementation would share its
    assumption and prove nothing about it (``.claude/LESSONS.md`` B3).
    """
    in_scope = [
        entry.bundle_keys[0]
        for entry in SHEET_INDEX_MAPS["c07"].values()
        if "Art. 112(1)(i)" in entry.label and entry.bundle_keys
    ]
    assert len(in_scope) == 1, (
        f"the published C 07.00 z-axis binds Art. 112(1)(i) to {in_scope}; row 0040's "
        "scope is only meaningful against exactly one in-scope sheet"
    )
    return in_scope[0]


def _cell(corep: COREPTemplateBundle, sheet: str, row_ref: str, column: str) -> float | None:
    """One cell, with the sheet's and the row's presence asserted first.

    Both matter here and they are different claims: an absent SHEET and an absent
    ROW both read as "no figure", and so does a declared row rendered null — which
    is the state this file is about. Distinguishing them is the point
    (``.claude/LESSONS.md`` B4).
    """
    assert sheet in corep.c07_00, (
        f"C 07.00 sheet {sheet!r} not emitted; the axis holds {sorted(corep.c07_00)}"
    )
    matched = corep.c07_00[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, (
        f"{sheet}: expected exactly one row {row_ref}, got {matched.height} — a row the "
        "template does not declare cannot be 'scoped away', it is simply absent"
    )
    return matched[column][0]


class TestTheScopeHasSomethingToScope:
    """LESSONS C11 — the fixture's adequacy, asserted before any outcome.

    Every assertion below this class is about a row being null on one sheet and
    populated on another. All of them pass trivially on a portfolio whose
    residential-property legs all sit on the real-estate sheet — which is the
    state of all eight registered reporting portfolios, and the reason the scope
    was unobservable before this file existed.
    """

    def test_a_residential_property_leg_is_reported_off_the_real_estate_sheet(self) -> None:
        """The crossing leg exists, carries the row's predicate, and is NOT class (i).

        This is the reachability claim the whole file rests on. LESSONS C2's
        instruction for a scope/basis test — measure the crossing amount — in its
        row-scope form: if this leg were absent, or worth 0.00, the scope could
        not be distinguished from no scope at all.
        """
        # Arrange / Act
        results, _corep = _run("crr")
        leg = results.filter(pl.col("exposure_reference") == LN_CORP_IPRE)

        # Assert
        assert leg.height == 1, f"{LN_CORP_IPRE} did not survive the pipeline"
        assert leg["property_type"][0] == "residential", (
            "the crossing leg carries no residential property_type, so row 0040's "
            "predicate does not match it and its null says nothing about the scope"
        )
        assert leg["reporting_class_origin"][0] != "retail_mortgage"
        assert leg["ead_final"][0] == pytest.approx(DRAWN_CORP_IPRE), (
            "the crossing amount is the whole test; a zeroed leg would make the "
            "scoped and unscoped outputs agree"
        )

    def test_that_leg_lands_on_a_sheet_row_0040_is_out_of_scope_for(self) -> None:
        """...and the sheet it lands on is not the in-scope one.

        Asserted against the published z-axis rather than against the literal
        ``"corporate"``: if the engine's class assignment for a
        property-secured-but-not-Art.-125 exposure ever moves, what this file
        needs is still "some sheet other than Art. 112(1)(i)", and that is what
        fails here if the fixture stops providing it.
        """
        # Arrange / Act
        _results, corep = _run("crr")
        real_estate = _real_estate_sheet()

        # Assert
        other_sheets = [sheet for sheet in corep.c07_00 if sheet != real_estate]
        assert other_sheets, (
            "every sheet this portfolio opens is the Art. 112(1)(i) sheet, so row "
            "0040 is in scope everywhere and the scope term is unexercised"
        )
        carrying = [
            sheet
            for sheet in other_sheets
            if _cell(corep, sheet, _ROW_MEMO_RESIDENTIAL, "0010") is not None
        ]
        assert carrying, (
            "no out-of-scope sheet reports the unscoped residential memorandum row "
            f"0310, so none of them holds a leg row 0040's predicate matches; "
            f"sheets checked: {other_sheets}"
        )

    def test_the_out_of_scope_sheet_holds_more_than_the_crossing_leg(self) -> None:
        """The sheet total differs from the crossing leg, so "row 0040 is null"
        cannot be satisfied by the sheet being empty — and row 0310's figure
        cannot be mistaken for the sheet's own total."""
        # Arrange / Act
        _results, corep = _run("crr")

        # Assert
        total = _cell(corep, "corporate", _ROW_TOTAL, "0010")
        assert total == pytest.approx(CORPORATE_SHEET_TOTAL)
        assert total != pytest.approx(DRAWN_CORP_IPRE)


class TestRowScopeUnderCRR:
    """Row 0040: null off the Art. 112(1)(i) sheet, populated on it."""

    def test_row_0040_is_declared_on_both_sheets(self) -> None:
        """Absence and null are different failures and only one of them is this
        row's behaviour. The template declares row 0040 on every CRR SA sheet; the
        scope acts by leaving it EMPTY, not by dropping it from the layout."""
        # Arrange / Act
        _results, corep = _run("crr")

        # Assert
        for sheet in ("corporate", _real_estate_sheet()):
            frame = corep.c07_00[sheet]
            assert frame.filter(pl.col("row_ref") == _ROW_SCOPED).height == 1, (
                f"{sheet}: row {_ROW_SCOPED} is not declared at all"
            )

    def test_row_0040_is_null_on_every_out_of_scope_sheet(self) -> None:
        """The scope itself, on every money column rather than on one.

        ``v7477_m`` governs twenty-one columns, so a scope applied to the
        exposure-value column and not to RWEA would satisfy a single-column
        assertion and still publish a figure where the publisher forbids one.
        """
        # Arrange / Act
        _results, corep = _run("crr")
        real_estate = _real_estate_sheet()

        # Assert
        for sheet in corep.c07_00:
            if sheet == real_estate:
                continue
            for column in _MONEY_COLS:
                value = _cell(corep, sheet, _ROW_SCOPED, column)
                assert value is None, (
                    f"{sheet}: row {_ROW_SCOPED} col {column} reports {value}; Annex II "
                    "reports it only in exposure class 'Secured by mortgages on "
                    "immovable property'"
                )

    def test_row_0040_is_non_null_on_the_in_scope_sheet(self) -> None:
        """The survivor. A null and a legitimate zero are different claims and
        this asserts neither — it asserts the figure."""
        # Arrange / Act
        _results, corep = _run("crr")
        real_estate = _real_estate_sheet()

        # Assert
        for column in _MONEY_COLS:
            assert _cell(corep, real_estate, _ROW_SCOPED, column) is not None, (
                f"{real_estate}: row {_ROW_SCOPED} col {column} is NULL — the scope has "
                "zeroed the row it exists to place"
            )
        assert _cell(corep, real_estate, _ROW_SCOPED, "0010") == pytest.approx(DRAWN_RRE)

    def test_the_unscoped_memorandum_twin_reports_the_crossing_leg(self) -> None:
        """THE discriminating assertion: same predicate, same sheet, no scope.

        Row 0310 keys ``property_type == "residential"`` and nothing else, because
        Annex II words it as a memorandum item reported "Independent from the
        calculation of risk exposure amounts ... if the exposures are secured by
        real estate property" — no "Only reported in exposure class" sentence. So
        it publishes the crossing leg on the corporate sheet while row 0040,
        keying the same column plus the sheet, publishes nothing there.

        Without this, every null above is equally consistent with the predicate
        simply not matching anything, and the scope term would still be untested.

        Safe against the P1.377 regime split, and positively REQUIRED by the
        instruction rather than merely tolerated by it. Annex II ¶52 lists the six
        classes the memorandum rows are reported for and ``(e) Corporates (point
        (g) of Article 112 CRR)`` is one of them; ¶54 gives the reason — the rows
        "provide additional information about the obligor structure", reporting
        exposures "where the obligors would have been reported in the exposure
        classes ... 'Corporates' ... if those exposures were not assigned to the
        exposure classes 'in default' or 'secured by immovable property'". A
        property-secured corporate exposure on the corporate sheet is precisely
        that case.
        """
        # Arrange / Act
        _results, corep = _run("crr")

        # Assert
        memo = _cell(corep, "corporate", _ROW_MEMO_RESIDENTIAL, "0010")
        scoped = _cell(corep, "corporate", _ROW_SCOPED, "0010")
        assert memo == pytest.approx(DRAWN_CORP_IPRE), (
            "the unscoped memorandum row reports nothing on the corporate sheet, so "
            "row 0040's null there is not attributable to the scope"
        )
        assert scoped is None


class TestTheArithmetic:
    """The figure row 0040 publishes, not only its presence."""

    def test_the_survivor_leg_is_inside_the_art_125_low_ltv_band(self) -> None:
        """Adequacy for the two assertions below: above the Art. 125(2)(d)
        threshold the weight is a blend of two bands, and the expected RWEA would
        not be a single multiplication."""
        assert LTV_RRE < _RRE_LTV_THRESHOLD

    # DELIBERATELY ABSENT: an assertion that row 0040 equals row 0310 on the
    # REAL-ESTATE sheet. It holds today (both read 400,000 / 140,000) and it is
    # the one equality a P1.377 regime-split would have to undo, because Annex II
    # ¶52 does not list class (i) among the classes the memorandum rows are
    # reported for — see the module docstring. Asserting it would pin 0310 onto a
    # sheet the published instruction may well take it off. The figures it would
    # have checked are asserted directly below against the fixture's own amounts,
    # which no rescope can move.

    def test_row_0040_rwea_is_the_art_125_weight_on_its_own_exposure(self) -> None:
        """400,000 x the pack's low-LTV residential weight. The multiplicand is
        read from the pack, so the expectation cannot drift from Art. 125(1)(a)
        without the pack moving too."""
        # Arrange / Act
        _results, corep = _run("crr")
        real_estate = _real_estate_sheet()

        # Assert
        exposure = _cell(corep, real_estate, _ROW_SCOPED, "0200")
        rwea = _cell(corep, real_estate, _ROW_SCOPED, "0220")
        assert exposure == pytest.approx(DRAWN_RRE)
        assert rwea == pytest.approx(DRAWN_RRE * _RRE_LOW_LTV_RW)


class TestThePublishedRule:
    """The supervisor's own check, run on the generated bundle.

    A hand-written null assertion and the published rule are different oracles,
    and only one of them is what a filer is measured against
    (``.claude/LESSONS.md`` C3). Both are here because the rule alone cannot see
    the survivor: ``{r0040} = empty`` says nothing about the sheet where the row
    IS reported.
    """

    def test_the_scope_rule_family_is_evaluated_and_unbroken(self) -> None:
        # Arrange / Act
        _results, corep = _run("crr")
        report = evaluate_all(corep, None, _REGIMES["crr"])
        family = [
            outcome for outcome in report.outcomes if outcome.expression == _SCOPE_RULE_FORMULA
        ]

        # Assert
        assert family, (
            f"no enforced CRR rule carries the formula {_SCOPE_RULE_FORMULA!r}; the "
            "published scope check is not reaching this bundle, so its verdict below "
            "would be vacuous"
        )
        broken = [outcome.rule_id for outcome in family if outcome.status == STATUS_FAIL]
        assert not broken, (
            f"{broken} report a figure in row 0040 where the publisher forbids one; "
            f"coordinates: {[c for o in family for c in o.coordinates]}"
        )


class TestBasel31DeclaresNoRow0040:
    """PS1/26 drops row 0040 from OF 07.00 entirely, so there is nothing to scope.

    Asserted rather than assumed: "the row is null under Basel 3.1" and "the row
    does not exist under Basel 3.1" are different facts, and only the second one
    means a Basel 3.1 regression cannot reach this row. Basel 3.1's own scoped
    rows are 0330-0360, and they are ``TestBasel31RowScope``'s subject.
    """

    def test_of_07_00_does_not_declare_row_0040(self) -> None:
        # Arrange / Act
        _results, corep = _run("b31")

        # Assert
        assert corep.c07_00, "OF 07.00 emitted no sheets at all"
        for sheet, frame in corep.c07_00.items():
            assert frame.filter(pl.col("row_ref") == _ROW_SCOPED).height == 0, (
                f"{sheet}: OF 07.00 declares row {_ROW_SCOPED}, which PS1/26 Annex II "
                "does not — the CRR scope term would then need a Basel 3.1 twin"
            )


class TestBasel31RowScope:
    """The same scope sentence on OF 07.00, where NO published rule enforces it.

    PS1/26 Annex II gives rows 0330 and 0331 the sentence verbatim — "Only
    reported in exposure class 'real estate exposures' (Article 112(1)(i) of the
    Credit Risk: Standardised Approach (CRR) Part" — and 0332 sits under the same
    0330 heading as its materially-dependent half ("Sum of rows 0331-0332").

    Why this class is stricter than its CRR sibling rather than a copy of it:
    **there is no ``v7477_m`` here.** Grepping both published extracts for a
    ``{r0330|r0331|r0332} = empty`` rule returns nothing, so the supervisory
    register cannot catch a regression on these rows however the portfolio is
    registered. These assertions are the only gate, which is why each one is
    stated over every money column rather than over the total alone.

    Reachability, measured on this fixture — the rows it CAN place on an
    out-of-scope sheet, and the ones it cannot:

        0330, 0332   REACHED on the ``corporate`` sheet. 0332 rather than 0331
                     because ``c07_md`` falls back to ``has_income_cover``
                     (``corep/c07.py`` ladder), and the leg is income-producing.
        0331         not reachable out of scope: it needs ``c07_md`` False, i.e.
                     a non-income-producing residential leg — which is exactly a
                     loan-split candidate, so the splitter reclassifies it onto
                     the real-estate sheet.
        0340-0344    NOT REACHABLE, and the reason is regulatory rather than
        0353, 0354   incidental. Measured by building the leg: a corporate loan
                     on income-producing COMMERCIAL property is reclassified to
                     ``commercial_mortgage`` in both regimes (CRR RW 0.50 /
                     Basel 3.1 RW 1.50) and lands on the real-estate sheet,
                     because Art. 126(2) / Art. 124I make income production the
                     CONDITION of the preferential commercial treatment — the
                     mirror image of Art. 125(2)(b), which makes it a
                     disqualifier for residential. Drop the income flag and
                     Basel 3.1 removes the CRR rental-coverage gate, so the leg
                     becomes a split candidate and is reclassified anyway. Every
                     remaining escape from the candidate gate (``is_adc``,
                     defaulted, equity, covered bond, high risk) either moves the
                     leg to a different sheet for an unrelated reason or pins a
                     class assignment that is itself questionable.
        0350-0352    not reached: they need ``is_qualifying_re`` False, which this
                     fixture does not set. See the module docstring for why
                     setting it on the existing leg is not a free win.
        0360         not reached: needs ``is_adc``, per above.

    References:
    - PRA PS1/26 Annex II, OF 07.00 rows 0330 / 0331 / 0332
    - PS1/26 Art. 124F (general residential, 20% on the secured portion up to 55%
      of property value) and Art. 124G (income-producing residential)
    """

    def test_the_scoped_residential_rows_are_declared_on_both_sheets(self) -> None:
        """Absence and null are different failures, as for row 0040."""
        # Arrange / Act
        _results, corep = _run("b31")

        # Assert
        for sheet in ("corporate", _real_estate_sheet()):
            frame = corep.c07_00[sheet]
            for row_ref in _B31_SCOPED_ROWS:
                assert frame.filter(pl.col("row_ref") == row_ref).height == 1, (
                    f"{sheet}: OF 07.00 row {row_ref} is not declared at all"
                )

    def test_the_scoped_residential_rows_are_null_off_the_real_estate_sheet(self) -> None:
        """The scope, and the P2.57 defect it closes.

        Before the scope reached ``_re_terms`` this reported 2,000,000 in BOTH rows
        0330 and 0332 on the ``corporate`` sheet — published cells in rows the
        instruction reports only in exposure class (i). Asserted per money column
        because a scope applied to the exposure-value column and not to RWEA would
        satisfy a total-only check, and no published rule will ever second it.
        """
        # Arrange / Act
        _results, corep = _run("b31")
        real_estate = _real_estate_sheet()

        # Assert
        for sheet in corep.c07_00:
            if sheet == real_estate:
                continue
            for row_ref in _B31_SCOPED_ROWS:
                for column in _MONEY_COLS:
                    value = _cell(corep, sheet, row_ref, column)
                    assert value is None, (
                        f"{sheet}: row {row_ref} col {column} reports {value}; PS1/26 "
                        "Annex II reports it only in exposure class 'real estate "
                        "exposures' (Article 112(1)(i))"
                    )

    def test_the_residential_rows_survive_on_the_real_estate_sheet(self) -> None:
        """The survivor half — what distinguishes a scope from a deletion.

        0330 is the parent and 0331 its not-materially-dependent half; the
        survivor leg is a plain owner-occupier mortgage, so it lands in 0331 and
        0332 stays null. A null and a zero are different claims and this asserts
        neither — it asserts the figure.
        """
        # Arrange / Act
        _results, corep = _run("b31")
        real_estate = _real_estate_sheet()

        # Assert
        for row_ref in ("0330", "0331"):
            for column in _MONEY_COLS:
                assert _cell(corep, real_estate, row_ref, column) is not None, (
                    f"{real_estate}: row {row_ref} col {column} is NULL — the scope has "
                    "zeroed the rows it exists to place"
                )
            assert _cell(corep, real_estate, row_ref, "0010") == pytest.approx(DRAWN_RRE)

    def test_the_survivor_leg_sits_inside_the_art_124f_secured_portion(self) -> None:
        """Adequacy for the RWEA below: above the Art. 124F(2) 55%-of-value cap the
        weight blends the secured 20% with an Art. 124L residual, and the expected
        figure would not be a single multiplication. The margin is deliberately
        narrow (400,000 against 440,000), so a later change to the fixture's
        amounts fails here rather than silently turning the figure into a blend."""
        assert float(_B31_MAX_SECURED_RATIO) * VALUE_RRE >= DRAWN_RRE

    def test_the_residential_rwea_is_the_art_124f_secured_weight(self) -> None:
        """400,000 x the pack's Art. 124F secured weight, read from the pack."""
        # Arrange / Act
        _results, corep = _run("b31")
        real_estate = _real_estate_sheet()

        # Assert
        assert _cell(corep, real_estate, "0331", "0200") == pytest.approx(DRAWN_RRE)
        assert _cell(corep, real_estate, "0331", "0220") == pytest.approx(
            DRAWN_RRE * float(_B31_SECURED_RW)
        )
