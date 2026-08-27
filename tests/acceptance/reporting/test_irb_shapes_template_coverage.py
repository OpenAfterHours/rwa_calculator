"""
IRB exposure-shape template coverage — the off-BS, LFSE, defaulted-RWEA and
Art. 200(1)(b) protection columns, all the way to COREP and Pillar 3.

Pipeline position:
    build_reporting_irb_shapes_bundle() -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why this exists. Measured on the 28-run matrix before this portfolio existed
(``scripts/check_template_cell_coverage.py``), **29** template columns carried a
value in no run of the estate for want of an IRB exposure SHAPE — not a class, not
a PD band, a shape. Registering the portfolio in ``RUNS`` puts those columns inside
the supervisory register and the cell-coverage ratchet; this file is what pins the
*placement*, which neither of those can see: a column can be non-null estate-wide
while landing on the wrong sheet, the wrong row, or the wrong subset.

The assertions are ordered so a failure is diagnosable:

1. **The fixture actually has the shapes.** Off-BS legs with a non-zero
   ``reporting_gross_off_bs``, exactly one LFSE obligor, a defaulted row with a
   POSITIVE RWEA, and a non-defaulted control. Without this every template
   assertion below could pass vacuously on a portfolio that had quietly stopped
   producing them.
2. **Every "of which" sub-split is TWO-SIDED.** ``LESSONS.md`` B5's 2026-08-08
   recurrence: a sub-split cell that equals its parent total proves nothing, and
   neither does one that is zero. Each is asserted strictly between 0 and the
   parent, with the control leg's contribution provably OUTSIDE it.
3. **The regime divergence is pinned where it lives** — the undrawn commitment's
   IRB conversion factor, 75% under CRR and 40% under Basel 3.1.

Deliberately NOT asserted here: exact RWEA values for every row. Those belong to a
golden, and this portfolio has none yet (the same position as ``crm-substitution``,
``re-split`` and ``art199`` — see P5.48). What this file adds is the per-sheet and
per-subset placement a golden diff would not explain even when it caught it.

References:
- CRR Art. 166(8)/(10), Art. 166C/166D: IRB conversion factors on off-BS items
- CRR Art. 153(2): the large-financial-sector-entity multiplier and its sub-split
- PS1/26 Art. 154(1)(a): defaulted A-IRB K = max(0, LGD - BEEL)
- CRR Art. 200(1)(b): life policies as other funded credit protection
- COREP Annex II, C 08.01/02 cols 0030-0270; C 08.03 cols 0020-0030; C 08.06
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl
import pytest
from tests.fixtures.reporting_irb_shapes_portfolio import (
    BEEL_RET_DEF,
    DRAWN_LFSE,
    DRAWN_RET_DEF,
    IRB_SHAPES_EXPECTED_APPROACH,
    LGD_RETAIL,
    LIFE_SURRENDER_VALUE,
    LN_LFSE,
    LN_LIFE,
    LN_RET_CTRL,
    LN_RET_DEF,
    NOMINAL_CORP_GTEE,
    NOMINAL_SL,
    build_reporting_irb_shapes_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

#: The undrawn commitment's headroom: limit 7,500,000 less the 4,100,000 drawn.
_UNDRAWN_HEADROOM: float = 3_400_000.0

#: The IRB conversion factor applied to that headroom, per regime. This is the
#: one number in this portfolio that MOVES between regimes, so it is the single
#: sharpest guard that both arms are really running their own rulepack.
_EXPECTED_UNDRAWN_CCF: dict[str, float] = {"crr": 0.75, "b31": 0.40}

#: ``rwa_final`` for the defaulted leg: EAD x (LGD - BEEL) x 12.5. Written as the
#: arithmetic rather than the literal so a change to either input shows up here as
#: a deliberate edit and not as a mystery constant.
_EXPECTED_DEF_RWEA: float = DRAWN_RET_DEF * (LGD_RETAIL - BEEL_RET_DEF) * 12.5

_TOTAL_ROW: str = "0010"


def _config(regime_key: str) -> CalculationConfig:
    """IRB configuration at the same reference dates as the registered runs.

    Mirrors ``_irb_config`` in ``test_supervisory_validations.py`` rather than
    importing it, for the reason that module states about its own duplication: a
    change made for one portfolio's runs must not silently re-point another's.
    """
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


@lru_cache(maxsize=4)
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle, Pillar3TemplateBundle]:
    """Run the portfolio through one regime and generate both template sets.

    Memoised: template generation costs an order of magnitude more than the
    pipeline run, and every test below reads the same two runs.
    """
    framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_irb_shapes_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep, pillar3


def _row(sheet: pl.DataFrame, row_ref: str = _TOTAL_ROW) -> dict[str, object]:
    matched = sheet.filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"expected exactly one row {row_ref!r}, got {matched.height}"
    return matched.row(0, named=True)


def _cell(sheet: pl.DataFrame, column: str, row_ref: str = _TOTAL_ROW) -> float:
    assert column in sheet.columns, (
        f"column {column!r} is not emitted at all; emitted: {sorted(sheet.columns)}"
    )
    value = _row(sheet, row_ref)[column]
    assert value is not None, (
        f"column {column!r} is emitted but NULL — every published rule over it "
        f"reports NOT_EVALUATED, which reads exactly like a clean estate"
    )
    return float(value)  # type: ignore[arg-type]


def _leg(results: pl.DataFrame, reference: str) -> dict[str, object]:
    matched = results.filter(pl.col("exposure_reference") == reference)
    assert matched.height == 1, f"expected exactly one row for {reference!r}: got {matched.height}"
    return matched.row(0, named=True)


class TestFixtureActuallyHasTheShapes:
    """The guard every template assertion below rests on.

    Each of these four shapes is the sole source of a cluster of columns. If one
    silently stopped being produced, the template assertions would keep passing on
    a smaller book and the coverage would be lost without any gate turning red —
    the exact failure mode ``LESSONS.md`` B5 records twice.
    """

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_row_routes_to_its_designed_approach(self, regime_key: str) -> None:
        results, _corep, _p3 = _run(regime_key)

        index = 0 if regime_key == "crr" else 1
        actual = dict(zip(results["exposure_reference"], results["approach_applied"], strict=False))
        for reference, expected in IRB_SHAPES_EXPECTED_APPROACH.items():
            assert actual.get(reference) == expected[index], (
                f"{reference} routed {actual.get(reference)!r}, designed for "
                f"{expected[index]!r} — the shape is present but on the wrong template"
            )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_estate_gains_off_balance_sheet_irb_and_slotting_legs(
        self, regime_key: str
    ) -> None:
        """The cluster of 11 columns exists only because these legs do."""
        results, _corep, _p3 = _run(regime_key)

        off_bs = results.filter(pl.col("reporting_gross_off_bs") > 0.0)
        gross = dict(
            zip(off_bs["exposure_reference"], off_bs["reporting_gross_off_bs"], strict=True)
        )

        assert gross, "no off-balance-sheet leg at all — the whole off-BS cluster goes dark"
        assert any("CT-CORP-GTEE" in ref for ref in gross), "the IRB issued item is gone"
        assert any("UNDRAWN" in ref for ref in gross), "the undrawn commitment leg is gone"
        assert any("CT-SL" in ref for ref in gross), (
            "the SLOTTING off-BS leg is gone — C 08.06 and CR10 col b are a "
            "separate population from the IRB ones and nothing else feeds them"
        )
        assert sum(gross.values()) == pytest.approx(
            NOMINAL_CORP_GTEE + NOMINAL_SL + _UNDRAWN_HEADROOM
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_exactly_one_obligor_is_flagged_a_large_financial_sector_entity(
        self, regime_key: str
    ) -> None:
        """Exactly one, not at least one: the LFSE cells are asserted BELOW their
        parent totals, which only discriminates while a non-LFSE corporate shares
        the sheet."""
        results, _corep, _p3 = _run(regime_key)

        flagged = results.filter(pl.col("cp_apply_fi_scalar"))
        assert flagged.height == 1
        assert flagged["exposure_reference"][0] == LN_LFSE

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_defaulted_leg_carries_a_positive_rwea(self, regime_key: str) -> None:
        """The correction this portfolio exists for.

        The estate's other defaulted IRB row (``IRC-LN-RRE-DEF``) has BEEL == LGD,
        so Art. 154(1)(a) gives K = 0 and its RWEA is exactly 0.00 — which is why
        the defaulted RWEA sub-splits were dead despite a defaulted IRB obligor
        existing. This leg sets BEEL strictly below LGD so K = 0.25.
        """
        results, _corep, _p3 = _run(regime_key)

        defaulted = _leg(results, LN_RET_DEF)
        assert defaulted["is_defaulted"] is True
        assert float(defaulted["rwa_final"]) == pytest.approx(_EXPECTED_DEF_RWEA)
        assert float(defaulted["rwa_final"]) > 0.0, (
            "a defaulted subset with zero RWEA cannot light an RWEA sub-split — "
            "this is the exact condition that kept cols 0265 / 0120 dead"
        )

        control = _leg(results, LN_RET_CTRL)
        assert control["is_defaulted"] is False
        assert float(control["rwa_final"]) > 0.0, (
            "the control leg must carry RWEA of its own, or the 'strictly less "
            "than the total' assertions below cannot discriminate"
        )


class TestOffBalanceSheetColumnsArePopulated:
    """C 08.01/02 cols 0100/0120, C 08.03 cols 0020/0030, C 08.06, CR6, CR10."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c08_01_off_balance_sheet_columns_carry_the_expected_nominals(
        self, regime_key: str
    ) -> None:
        """Asserted against the arithmetic, not against a parent column.

        The "of which" parent for original exposure is REGIME-DEPENDENT on this
        template (C 08.01 corporate emits col 0010 under CRR and starts at col
        0020 under Basel 3.1), so a strict-subset assertion against a fixed
        parent ref tests the template layout rather than the off-BS coverage.
        The nominals are exact and hand-checkable, which is stronger.
        """
        _results, corep, _p3 = _run(regime_key)

        sheet = corep.c08_01["corporate"]
        pre_ccf = _cell(sheet, "0100")
        post_ccf = _cell(sheet, "0120")

        assert pre_ccf == pytest.approx(NOMINAL_CORP_GTEE + _UNDRAWN_HEADROOM), (
            "col 0100 is the PRE-conversion off-BS nominal: the issued guarantee "
            "plus the undrawn headroom, unconverted"
        )
        assert post_ccf == pytest.approx(
            NOMINAL_CORP_GTEE + _UNDRAWN_HEADROOM * _EXPECTED_UNDRAWN_CCF[regime_key]
        ), (
            "col 0120 is the POST-conversion value: the guarantee at its 100% "
            "full-risk CCF plus the headroom at the regime's IRB conversion factor"
        )
        assert 0.0 < post_ccf < pre_ccf, (
            "conversion must strictly reduce the off-BS figure here — equal would "
            "mean no CCF was applied at all"
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c08_03_average_ccf_is_the_exposure_weighted_blend(self, regime_key: str) -> None:
        """C 08.03's rows are PD BANDS, not a total row, so the populated band is
        located rather than assumed — and the average CCF is checked as the exact
        EAD-weighted blend of the two off-BS legs, which is what makes this column
        a real assertion rather than a non-null check."""
        _results, corep, _p3 = _run(regime_key)

        sheet = corep.c08_03["corporate"]
        populated = sheet.filter(pl.col("0020") > 0.0)
        assert populated.height > 0, (
            "no PD band carries an off-BS pre-conversion nominal — col 0020 is dark"
        )
        assert float(populated["0020"][0]) == pytest.approx(NOMINAL_CORP_GTEE + _UNDRAWN_HEADROOM)

        ccf = _EXPECTED_UNDRAWN_CCF[regime_key]
        expected_blend = (NOMINAL_CORP_GTEE * 1.0 + _UNDRAWN_HEADROOM * ccf) / (
            NOMINAL_CORP_GTEE + _UNDRAWN_HEADROOM
        )
        average_ccf = float(populated["0030"][0])
        assert average_ccf == pytest.approx(expected_blend), (
            f"average CCF {average_ccf} is not the EAD-weighted blend "
            f"{expected_blend} of a 100% issued item and a {ccf:.0%} commitment"
        )
        assert 0.0 < average_ccf <= 1.0, (
            "the column is a FRACTION, not a percentage — a value above 1.0 means "
            "the scale changed underneath this assertion"
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_slotting_sheet_carries_its_own_off_balance_sheet_leg(
        self, regime_key: str
    ) -> None:
        """C 08.06 is a separate population from the IRB templates: before this
        portfolio no slotting obligor in the estate had an off-BS leg at all.

        The figure sits on the slotting-CATEGORY row (``strong``), not on a total
        row, so the row carrying it is located by value rather than by ref — the
        category row refs differ between the two regimes' layouts.
        """
        _results, corep, _p3 = _run(regime_key)

        assert corep.c08_06, "C 08.06 is not emitted — the slotting sheet went dark"
        sheet = corep.c08_06["project_finance"]

        for column in ("0030", "0050"):
            values = [v for v in sheet[column].to_list() if v]
            assert values, f"C 08.06 col {column} is dark — the slotting off-BS leg is gone"
            # The scale is hierarchical: the figure appears on the slotting-CATEGORY
            # row ('strong') and again on the total that spans it. Asserting a count
            # would pin the layout; asserting every non-zero occurrence is the same
            # nominal catches a leak into a second category without doing that.
            for value in values:
                assert value == pytest.approx(NOMINAL_SL), (
                    f"C 08.06 col {column} carries {value}, not the slotting off-BS "
                    f"nominal {NOMINAL_SL} — a second category picked the leg up"
                )
            # No total-row assertion: C 08.06's row axis is slotting CATEGORY x
            # remaining maturity, and row 0010 is a category rather than a total,
            # so there is no single "0010 is the total" convention to lean on here
            # the way there is on C 08.01.

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_undrawn_commitment_takes_its_regime_conversion_factor(
        self, regime_key: str
    ) -> None:
        """The one figure that MOVES between regimes — 75% CRR, 40% Basel 3.1.

        A guard that both arms are running their own rulepack rather than one
        being a copy of the other, which no per-regime cell count can show.
        """
        results, _corep, _p3 = _run(regime_key)

        undrawn = results.filter(pl.col("exposure_reference").str.contains("UNDRAWN"))
        assert undrawn.height == 1
        row = undrawn.row(0, named=True)

        assert float(row["reporting_gross_off_bs"]) == pytest.approx(_UNDRAWN_HEADROOM)
        assert float(row["ead_final"]) == pytest.approx(
            _UNDRAWN_HEADROOM * _EXPECTED_UNDRAWN_CCF[regime_key]
        )


class TestOfWhichSubSplitsAreTwoSided:
    """Every sub-split strictly between zero and its parent — B5's two-leg rule."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_lfse_sub_split_excludes_the_non_lfse_corporate(self, regime_key: str) -> None:
        _results, corep, _p3 = _run(regime_key)

        sheet = corep.c08_01["corporate"]

        # The original-exposure sub-split is exact: one obligor, one drawn leg.
        assert _cell(sheet, "0030") == pytest.approx(DRAWN_LFSE), (
            "col 0030 must be exactly the LFSE obligor's drawn amount — anything "
            "else means the sub-split is picking up a different population"
        )

        # The value and RWEA sub-splits are asserted as STRICT subsets, which is
        # what the non-LFSE corporates on the same sheet make discriminating.
        for sub, parent in (("0140", "0110"), ("0270", "0260")):
            if sub not in sheet.columns or parent not in sheet.columns:
                continue
            lfse = _cell(sheet, sub)
            total = _cell(sheet, parent)
            assert 0.0 < lfse < total, (
                f"C 08.01 col {sub} ({lfse}) must be a STRICT subset of col "
                f"{parent} ({total}): equal means the non-LFSE corporates leaked "
                f"into the sub-split, zero means the LFSE obligor did not reach it"
            )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_defaulted_rwea_sub_split_excludes_the_live_control(self, regime_key: str) -> None:
        """C 08.01 col 0265 must equal the defaulted leg's RWEA exactly, and the
        non-defaulted control's RWEA must be in the sheet total but not in it."""
        _results, corep, _p3 = _run(regime_key)

        sheet = corep.c08_01.get("retail_other")
        if sheet is None or "0265" not in sheet.columns:
            pytest.skip("C 08.01 col 0265 is a Basel 3.1 column; absent under CRR")

        defaulted_rwea = _cell(sheet, "0265")
        total_rwea = _cell(sheet, "0260")

        assert defaulted_rwea == pytest.approx(_EXPECTED_DEF_RWEA)
        assert 0.0 < defaulted_rwea < total_rwea, (
            "the defaulted sub-split must sit strictly inside the sheet total — "
            "equal means the live control leaked in, zero means the defaulted "
            "leg did not reach the subset at all"
        )


class TestOtherFundedProtectionColumns:
    """CRR Art. 200(1)(b) — the life policy, and the CR7-A collateral diagnostic."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_life_policy_takes_exactly_one_route_and_it_is_regime_dependent(
        self, regime_key: str
    ) -> None:
        """Art. 200(1) protection is routed EXCLUSIVELY, and the regimes differ.

        ``engine/crm/ofcp_routing.py`` splits the same pledge between the Art. 232
        SUBSTITUTION block (col 0060) and the PS1/26 Art. 169A LGD-Modelling block
        (cols 0171-0173) on one boolean, so a positive figure in one implies zero
        in the other "structurally, not by a convention a consumer must uphold".
        Measured, this portfolio's single life policy takes a DIFFERENT route in
        each regime — substitution under CRR, LGD-modelling under Basel 3.1 — so
        asserting only the Basel 3.1 carrier would have read as a CRR defect.

        Both routes are asserted together because the exclusivity is the invariant;
        checking one column alone cannot see it break.
        """
        results, _corep, _p3 = _run(regime_key)

        life = _leg(results, LN_LIFE)
        in_lgd = float(life["reporting_ofcp_lgd_life_insurance"])
        in_substitution = float(life["reporting_ofcp_substitution"])

        assert in_lgd + in_substitution == pytest.approx(LIFE_SURRENDER_VALUE), (
            f"the surrender value must be recognised on exactly one route; got "
            f"LGD={in_lgd}, substitution={in_substitution}"
        )
        assert min(in_lgd, in_substitution) == 0.0, (
            f"the two routes are MUTUALLY EXCLUSIVE by construction "
            f"(engine/crm/ofcp_routing.py): one of them must be exactly zero, but "
            f"got LGD={in_lgd}, substitution={in_substitution}"
        )
        expected_route = "substitution" if regime_key == "crr" else "lgd"
        actual_route = "lgd" if in_lgd > 0.0 else "substitution"
        assert actual_route == expected_route, (
            f"under {regime_key} the policy should take the {expected_route} route"
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_financial_collateral_reaches_the_carrier_cr7a_reads(self, regime_key: str) -> None:
        """The resolved CR7-A col b diagnostic.

        The banked baseline predicted that if a fixture pledging eligible
        financial collateral to an IRB obligor could not light col b then "the
        binding is the defect". It can — but only with NON-CASH collateral: cash
        is recognised and lands in ``collateral_cash_value``, a sibling of the
        ``collateral_financial_value`` col b reads. Both are pledged on this leg
        so the distinction is asserted rather than assumed.
        """
        results, _corep, _p3 = _run(regime_key)

        fincoll = results.filter(pl.col("exposure_reference").str.contains("FINCOLL"))
        assert fincoll.height == 1
        row = fincoll.row(0, named=True)

        assert float(row["collateral_cash_value"]) > 0.0, "the cash pledge stopped being recognised"
        assert float(row["collateral_financial_value"]) > 0.0, (
            "collateral_financial_value is zero — CR7-A col b goes dark again. "
            "Cash alone cannot hold this up; it needs the non-cash pledge."
        )
