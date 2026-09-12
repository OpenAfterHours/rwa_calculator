"""
P2.54 — Article 112(1)(o) CIUs are their own exposure class, in BOTH regimes.

Pipeline position:
    build_reporting_bundle() / build_reporting_offbs_bundle()
        -> PipelineOrchestrator -> COREPGenerator / Pillar3Generator
        -> c07_00["ciu"], c_02_00 r0200, c09_01["TOTAL"] r0140, OV1 rows 12-14

**The class exists under CRR as well as Basel 3.1, and there is no pack Feature.**
SI 2021/1078 reg. 6(3)(b)-(d) omitted CRR Arts. 132 / 132a / 152 from the onshored
statute; the ruling this file is written to is that those provisions were
RELOCATED into the PRA Rulebook for CRR firms rather than abolished, so the class
stamp in ``engine/aggregator/_equity_prep.py`` is regime-blind and keys only
``equity_type == "ciu"``. Both halves of that ruling are exercised here, on two
portfolios, because a regime-blind stamp whose CRR arm is never executed is a
claim and not a test:

- ``rich`` holds three equity-table legs (one class (p) listed + two class (o)
  CIUs) and runs ``PermissionMode.IRB`` in both regimes. Under CRR that routes
  every equity-table leg to Art. 155(2) and ``c07.py::_equity_admission`` excludes
  it from C 07.00 (COREP Annex II ¶50 scopes the template to Chapter 2 of Title II
  of Part Three CRR), so ``rich`` is the **CRR negative control**: no (o) sheet,
  no (p) sheet, and the RWEA in C 02.00 r0420 "Equity IRB".
- ``off-bs`` holds one mandate-based CIU and runs ``PermissionMode.STANDARDISED``,
  so its CIU is SA-method and IS admitted. It is the **CRR positive control**, and
  without it the CRR arm of the ruling would ship unexecuted: every CRR assertion
  on ``rich`` passes equally well under an implementation that has no CIU class at
  all.

Measured figures, reproduced rather than re-derived (see ``_equity_exposures`` in
each fixture for the provenance of every input):

    portfolio  leg                      EAD         B31 RW   B31 RWEA     CRR RWEA
    rich       RP-EQ-LISTED        1,000,000          2.50   2,500,000    2,900,000
    rich       RP-EQ-CIU-FALLBACK  2,000,000         12.50  25,000,000    7,400,000
    rich       RP-EQ-CIU-MANDATE   4,000,000          0.75   3,000,000   14,800,000
    off-bs     OBS-EQ-CIU          8,000,000          0.35   2,800,000    2,800,000

``rich`` CIU subtotal: 6,000,000 EAD / 28,000,000 RWEA (B31). The two regime
columns differ for a reason that is NOT the Art. 132 ladder: under CRR the
Art. 155(2) simple-risk-weight path has no CIU branch, so both CIU legs fall to
its Art. 155(2)(c) 370% residual. ``off-bs`` is identical in both regimes because
a mandate weight is read verbatim from the input.

Risk-weight provenance: 2.50 and 12.50 are the pack entry
``equity_sa_risk_weights`` under b31 — ``[LISTED]`` (PS1/26 Art. 133(3)-(5)) and
``[CIU]`` (Art. 132(2) fall-back) — read from ``rulebook/packs/b31.py``, not from
prose. 0.75 and 0.35 are Art. 132A(2) firm-reported weighted averages and are
fixture INPUTS (``CIU_MANDATE_RW_INPUT`` / ``CIU_MANDATE_RW``), not pack values.

Deliberately NOT asserted, each for a stated reason:
- rows 0284 / 0285 "of which: exposures to relevant CIUs" as populated. No
  "relevant CIU" carrier exists anywhere in the input domain, and BOTH published
  summation rules over this block (``boe_b0728`` / ``v09743_m``,
  ``{r0010} = {r0281} + {r0282} + {r0283}``) exclude them, so leaving them dark
  breaks no named identity. They are pinned NULL below so a later reader does not
  read the gap as an oversight.
- Pillar 3 CR4 / CR5 row 14 as populated. CR4/CR5 never admitted the equity
  population at all — row 15 "Equity" publishes a hard 0.00 against 30,500,000 of
  equity-origin RWEA — so binding row 14 to ``("ciu",)`` could not make it
  publish. That is a pre-existing defect filed separately; its current state is
  pinned below so the filing has something to point at.
- the CIU's own risk weight. ``engine/equity/calculator.py`` computed it before
  this item and is unchanged by it; ``tests/acceptance/basel31`` owns Art. 132.

References:
- CRR Art. 112(1)(o) / PRA PS1/26 Art. 112(1)(o): the CIU exposure class
- PS1/26 Art. 132 (fall-back), Art. 132A(1)/(2) (look-through, mandate-based),
  Art. 132B (exclusions — no election carrier exists, assumed not elected)
- PS1/26 Annex II (OF 07.00) rows 0281-0285: "These rows shall only be reported
  for the exposure class Collective investment undertakings (CIU)"; 0281 =
  Art. 132A(1), 0282 = Art. 132A(2), 0283 = Art. 132(2)
- PS1/26 Annex II (OF 09.01) row 0140 "Sum of rows 0141 to 0143"
- PS1/26 Annex II (UKB OV1) rows 12-14; (UKB CMS1) row 0070; (UKB CMS2) row 0070
- COREP Annex II ¶50, ¶61-¶62 and the CR SA decision tree
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.acceptance.reporting.test_reporting_offbs_golden import _config as _offbs_config
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.reporting_offbs_portfolio import (
    CARRYING_CIU,
    CIU_RWEA,
    EQ_CIU,
    build_reporting_offbs_bundle,
)
from tests.fixtures.reporting_portfolio import (
    ALL_EQUITY_REFERENCES,
    EQ_CIU_FALLBACK,
    EQ_CIU_MANDATE,
    EQ_LISTED,
    build_reporting_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
    LOAN_SCHEMA,
    VALID_CIU_APPROACHES,
)
from rwa_calc.domain.enums import ExposureClass, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    C02_00_SA_CLASS_MAP,
    C07_00_SA_SHEET_MAP,
    C09_01_SA_CLASS_MAP,
)

# ``ov1`` as a MODULE, not ``from ... import _EQUITY_SUBAPPROACH_REFS``: the module
# attribute is what production reads, and a name bound here at import time keeps
# pointing at the original dict however the module is later rebound — measured, it
# left the row->approach pairing assertion green under the mutation that shifts it.
from rwa_calc.reporting.pillar3 import ov1
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle
from rwa_calc.reporting.pillar3.templates import (
    CMS2_SA_CLASS_MAP,
    CMS2_TOTAL_CLASSES,
    SA_DISCLOSURE_CLASSES,
)
from rwa_calc.reporting.validations.checker import evaluate_all
from rwa_calc.reporting.validations.scope import SHEET_INDEX_MAPS

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_calc.contracts.bundles import RawDataBundle
    from rwa_calc.reporting.validations.checker import ValidationReport

# Group-by float sums are not bit-reproducible (Phase 2 parity convention).
_REL = 1e-9
_ABS = 1e-6

#: The bundle key Article 112(1)(o) is published under, read off ``scope.py``
#: rather than spelled ``"ciu"`` here: the sheet name is whatever
#: ``SheetCode.bundle_keys`` says it is, and a test that hard-coded it would share
#: ``corep/c07.py``'s assumption instead of checking it (``.claude/LESSONS.md`` B3).
_Z_CODE_112_O: str = "0015"
_Z_CODE_112_P: str = "0016"

#: (portfolio, regime) -> (bundle builder, config factory, framework string).
_CASES: dict[
    tuple[str, str], tuple[Callable[[], RawDataBundle], Callable[[], CalculationConfig], str]
] = {
    ("rich", "crr"): (build_reporting_bundle, _crr_config, "CRR"),
    ("rich", "b31"): (build_reporting_bundle, _b31_config, "BASEL_3_1"),
    ("off-bs", "crr"): (build_reporting_offbs_bundle, lambda: _offbs_config("crr"), "CRR"),
    ("off-bs", "b31"): (build_reporting_offbs_bundle, lambda: _offbs_config("b31"), "BASEL_3_1"),
}

# ---------------------------------------------------------------------------
# rich — Basel 3.1 figures
# ---------------------------------------------------------------------------

#: ``RP-EQ-CIU-MANDATE`` 4,000,000 + ``RP-EQ-CIU-FALLBACK`` 2,000,000. No CCF on
#: an equity holding, so this is both col 0010 (original exposure pre-conversion)
#: and col 0200 (exposure value) on the (o) sheet.
_RICH_CIU_EAD: float = 6_000_000.0

#: 4,000,000 x 75% (Art. 132A(2) mandate input) = 3,000,000.
_RICH_CIU_MANDATE_RWEA: float = 3_000_000.0
#: 2,000,000 x 1,250% (pack ``equity_sa_risk_weights[CIU]``, Art. 132(2)) = 25,000,000.
_RICH_CIU_FALLBACK_RWEA: float = 25_000_000.0
_RICH_CIU_RWEA: float = _RICH_CIU_MANDATE_RWEA + _RICH_CIU_FALLBACK_RWEA  # 28,000,000

#: ``RP-EQ-LISTED`` 1,000,000 x 250% — the class (p) sheet, which must FALL to
#: this once (o) takes its own. Equal to the pre-P2.54 whole-equity figure, which
#: is the point: if (o) were double-counted, (p) would still read 30,500,000.
_RICH_LISTED_EAD: float = 1_000_000.0
_RICH_LISTED_RWEA: float = 2_500_000.0

#: The whole equity table, class (o) + class (p). The two sheets must partition it.
_RICH_EQUITY_TABLE_EAD: float = _RICH_CIU_EAD + _RICH_LISTED_EAD  # 7,000,000
_RICH_EQUITY_TABLE_RWEA: float = _RICH_CIU_RWEA + _RICH_LISTED_RWEA  # 30,500,000

#: C 02.00 r0010 / r0050 (TREA) and r0060 (of which: SA) on ``b31/rich``. Pinned
#: because the class move must not touch either: the totals are keyed on the
#: APPROACH, which is why they could not have caught the 28,000,000 going missing.
#: Both grew when master's P1.373 supporting-factor overlap pair (RP-LN-SME-INFRA,
#: RP-LN-AIRB-INFRA) merged in — those are loans carrying no Basel 3.1 relief, and
#: they move the approach totals without touching the equity table below, so the
#: CIU constants are deliberately unchanged.
_RICH_B31_TREA: float = 168_185_313.4668259
_RICH_B31_SA_TOTAL: float = 51_355_833.33333333

#: CMS2 row 0070 column c on ``b31/rich`` — the whole ledger LESS the CIU, which
#: is what ``CMS2_TOTAL_CLASSES`` carves out. Still exactly
#: ``_RICH_B31_TREA - _RICH_CIU_RWEA`` (168,185,313.47 - 28,000,000).
_RICH_CMS2_TOTAL_C: float = 140_185_313.4668259

#: The whole equity table's CRR RWEA: 2,900,000 (listed, Art. 155(2) 290%) +
#: 7,400,000 + 14,800,000 (both CIU legs at the Art. 155(2)(c) 370% residual).
_RICH_CRR_EQUITY_TABLE_RWEA: float = 25_100_000.0
_RICH_CRR_CIU_RWEA: float = 22_200_000.0

#: C 09.01 row 0170's published decomposition: "Sum of rows 0010 to 0120, 0140,
#: 0150 and 0160" (``boe_b0730``). 0100/0120 of-which children are excluded by the
#: rule itself and 0130 is not in its term list.
_C09_01_TOTAL_TERMS: tuple[str, ...] = (
    "0010",
    "0020",
    "0030",
    "0040",
    "0050",
    "0060",
    "0070",
    "0080",
    "0090",
    "0100",
    "0110",
    "0120",
    "0140",
    "0150",
    "0160",
)

#: The C 07.00 / OF 07.00 CIU approach rows, and the ``ciu_approach`` value each
#: is defined over. Written from the PUBLISHED instruction (PS1/26 Annex II,
#: rows 0281-0285: 0281 = Art. 132A(1) look-through, 0282 = Art. 132A(2)
#: mandate-based, 0283 = Art. 132(2) fall-back), NOT copied from
#: ``corep/c07.py::_CIU_ROW_APPROACH`` — a test written from the same sentence as
#: the code it checks proves nothing (``.claude/LESSONS.md`` B3).
_CIU_APPROACH_ROWS: dict[str, str] = {
    "0281": "look_through",
    "0282": "mandate_based",
    "0283": "fallback",
}

#: The C 09.01 twins of the three rows above (PS1/26 Annex II, OF 09.01 row 0141:
#: "Same definition as for row 0281 of OF CR SA template").
_CIU_APPROACH_ROWS_C09: dict[str, str] = {
    "0141": "look_through",
    "0142": "mandate_based",
    "0143": "fallback",
}

#: Rows that carry no carrier at all — see the module docstring.
_RELEVANT_CIU_ROWS: tuple[str, ...] = ("0284", "0285")

#: The three COREP class->row / class->sheet maps, held by REFERENCE so the key set
#: is read when the test runs rather than when it is collected.
_CLASS_MAPS: dict[str, dict[str, str]] = {
    "C02_00_SA_CLASS_MAP": C02_00_SA_CLASS_MAP,
    "C07_00_SA_SHEET_MAP": C07_00_SA_SHEET_MAP,
    "C09_01_SA_CLASS_MAP": C09_01_SA_CLASS_MAP,
}

#: The money columns the CIU rows are asserted across: original exposure
#: pre-conversion, net of adjustments, post-CRM, fully adjusted, exposure value,
#: RWEA. Several columns rather than one because a mis-bound breakdown can agree
#: with its parent on the exposure columns and not on the RWEA.
_MONEY_COLUMNS: tuple[str, ...] = ("0010", "0040", "0110", "0150", "0200", "0220")

#: Rows COREP Annex II reserves for the "particularly high risk" and "equity"
#: classes, so a CIU sheet must leave them EMPTY. Row 0040 exists in the CRR
#: layout only.
_MUST_BE_EMPTY_ROWS: tuple[str, ...] = ("0015", "0040")

#: The four live EBA guards over those two rows — ``{r0015} = empty``,
#: ``{r0015} = 0``, ``{r0040} = empty`` twice, across C 07.00.a and .b. None of
#: them carries a z-code scope, so each applies to EVERY emitted sheet.
_EMPTY_GUARD_RULES: tuple[str, ...] = ("v4721_m", "v4722_m", "v7477_m", "v7478_m")

#: The EBA twin of ``boe_b0728``: ``{r0010} = {r0281} + {r0282} + {r0283}``, scoped
#: to z0015 alone and therefore unevaluable until a CRR run emits a CIU sheet.
_CIU_DECOMPOSITION_RULE: str = "v09743_m"

#: The (portfolio, regime) pairs that emit an Article 112(1)(o) sheet at all.
_CIU_SHEET_CASES: tuple[tuple[str, str], ...] = (
    ("rich", "b31"),
    ("off-bs", "crr"),
    ("off-bs", "b31"),
)

# ---------------------------------------------------------------------------
# The self-contained CRR control book (``TestTheCrrArmOnABookThisFileOwns``)
# ---------------------------------------------------------------------------

#: A plain SA corporate loan, so the control book is not equity-only.
_CONTROL_LOAN_EAD: float = 5_000_000.0
_CONTROL_CIU_REF: str = "P254-EQ-CIU"
_CONTROL_CIU_EAD: float = 2_000_000.0
#: An Art. 132A(2) mandate weight. Chosen UNLIKE both estate fixtures (0.75 on
#: ``rich``, 0.35 on ``off-bs``) so a figure copied from either would be visible,
#: and unlike the 1,250% fall-back, which is also what a null or misspelled
#: ``ciu_approach`` produces and so cannot show the approach was read.
_CONTROL_CIU_RW: float = 0.60


# ---------------------------------------------------------------------------
# Shared runs
# ---------------------------------------------------------------------------


@lru_cache(maxsize=len(_CASES))
def _run(
    portfolio: str, regime: str
) -> tuple[pl.DataFrame, COREPTemplateBundle, Pillar3TemplateBundle]:
    """One pipeline run plus both template bundles, memoised on the pair."""
    builder, config_factory, framework = _CASES[(portfolio, regime)]
    result = PipelineOrchestrator().run_with_data(builder(), config_factory())
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep, pillar3


@lru_cache(maxsize=len(_CASES))
def _validation_report(portfolio: str, regime: str) -> ValidationReport:
    """The supervisory verdicts for one run, over the memoised bundles."""
    _results, corep, pillar3 = _run(portfolio, regime)
    return evaluate_all(corep, pillar3, _CASES[(portfolio, regime)][2])


def _outcome(portfolio: str, regime: str, rule_id: str) -> object:
    matched = [o for o in _validation_report(portfolio, regime).outcomes if o.rule_id == rule_id]
    assert len(matched) == 1, (
        f"[{portfolio}/{regime}] expected exactly one {rule_id} outcome, got {len(matched)}; "
        "the rule may have been withdrawn from the enforced set"
    )
    return matched[0]


def _sheet_key(regime: str, z_code: str) -> str:
    """The single bundle key a published z-code names, from ``validations/scope.py``."""
    index = SHEET_INDEX_MAPS["c07" if regime == "crr" else "of07"]
    keys = index[z_code].bundle_keys
    assert len(keys) == 1, (
        f"z{z_code} binds {keys} — arch_check check 22 holds a publisher sheet code to "
        "exactly one bundle key, because the evaluator sums a multi-key code across all "
        "of them and a wrong axis then reads as a PASS"
    )
    return keys[0]


def _sheet(corep: COREPTemplateBundle, regime: str, z_code: str) -> pl.DataFrame:
    """The C 07.00 sheet a published z-code names, with its absence diagnosed.

    Indexing ``corep.c07_00`` directly raises a bare ``KeyError: 'ciu'`` when the
    class is unstamped — measured under the isolating mutation that reverts the
    stamp — which names neither the axis nor the cause. Every sheet lookup in this
    file goes through here so a failure reads as the finding it is.
    """
    key = _sheet_key(regime, z_code)
    assert key in corep.c07_00, (
        f"[{regime}] C 07.00 emits no z{z_code} [{key}] sheet. The axis holds "
        f"{sorted(corep.c07_00)} — the class is not reaching the sheet key, so every "
        "cell assertion below it is unreachable"
    )
    return corep.c07_00[key]


def _cell(frame: pl.DataFrame | None, row_ref: str, column: str) -> float | None:
    """One cell, with the row's existence asserted rather than assumed."""
    assert frame is not None
    row = frame.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"expected exactly one row {row_ref!r}, got {row.height}"
    assert column in row.columns, f"row {row_ref} has no column {column!r}"
    return row[column][0]


def _ciu_legs(results: pl.DataFrame) -> pl.DataFrame:
    return results.filter(pl.col("reporting_class_origin") == ExposureClass.CIU.value)


# ---------------------------------------------------------------------------
# 1. The class — stamped off equity_type, in both regimes
# ---------------------------------------------------------------------------


class TestTheClassIsStamped:
    """``ExposureClass.CIU`` reaches the sealed ledger, and only the CIUs get it."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_the_two_rich_ciu_legs_seal_class_o_and_the_listed_leg_keeps_p(
        self, regime: str
    ) -> None:
        """The stamp is regime-blind, so it is asserted under both regimes.

        Parametrised rather than asserted once because the whole ruling this item
        rests on is that SI 2021/1078 relocated Arts. 132/132a rather than
        abolishing them: a ``config.is_crr`` branch creeping into the stamp would
        pass a Basel-3.1-only assertion.
        """
        results, _corep, _pillar3 = _run("rich", regime)

        by_reference = dict(
            results.filter(pl.col("source_exposure_reference").is_in(ALL_EQUITY_REFERENCES))
            .select("source_exposure_reference", "reporting_class_origin")
            .iter_rows()
        )
        assert by_reference == {
            EQ_LISTED: ExposureClass.EQUITY.value,
            EQ_CIU_FALLBACK: ExposureClass.CIU.value,
            EQ_CIU_MANDATE: ExposureClass.CIU.value,
        }, (
            f"[{regime}] the equity table's sealed classes are {by_reference}. "
            "Art. 112(1)(o) and (p) are disjoint in both regimes — the article that "
            "supplies the risk weight tells them apart (Arts. 132-132C vs Art. 133) — so "
            "a CIU on (p), or a listed holding on (o), is a class-stamp defect"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_the_offbs_ciu_seals_class_o_under_an_sa_config(self, regime: str) -> None:
        """The second portfolio, and the one whose CRR arm is not vacuous.

        ``off-bs`` runs ``PermissionMode.STANDARDISED``, so its CIU is SA-method
        under CRR as well as Basel 3.1 and every CRR assertion downstream is about
        a leg the template actually admits.
        """
        results, _corep, _pillar3 = _run("off-bs", regime)

        leg = results.filter(pl.col("exposure_reference") == EQ_CIU)
        assert leg.height == 1, f"[{regime}] off-bs lost its CIU leg ({leg.height} rows)"
        assert leg["reporting_class_origin"][0] == ExposureClass.CIU.value
        assert leg["equity_method"][0] == "sa", (
            f"[{regime}] the off-bs CIU seals equity_method {leg['equity_method'][0]!r}; it "
            "must be 'sa' or C 07.00 excludes it and this portfolio stops being the "
            "positive control for the CRR arm"
        )
        assert leg["rwa_final"][0] == pytest.approx(CIU_RWEA, rel=_REL, abs=_ABS)

    def test_the_class_is_not_stamped_from_the_counterpartys_entity_type(self) -> None:
        """A CIU wrapper's obligor is an ordinary corporate, and that is the point.

        The discriminator is ``equity_type`` on the equity table, never the
        counterparty's ``entity_type`` — which is why the class is NOT a pack
        ``CategoryMap`` entry. If the obligor drove it, ``CP_EQUITY``'s other legs
        would move with it; this asserts the two CIU legs and the listed leg share
        one obligor and still land on different classes.
        """
        results, _corep, _pillar3 = _run("rich", "b31")

        equity_table = results.filter(
            pl.col("source_exposure_reference").is_in(ALL_EQUITY_REFERENCES)
        )
        obligors = set(equity_table["counterparty_reference"].to_list())
        assert len(obligors) == 1, (
            f"the three equity-table legs no longer share one obligor ({obligors}); the "
            "class split below could then be an obligor effect and this test would be "
            "asserting nothing about equity_type"
        )
        assert set(equity_table["reporting_class_origin"].to_list()) == {
            ExposureClass.CIU.value,
            ExposureClass.EQUITY.value,
        }


# ---------------------------------------------------------------------------
# 2. The maps — anchored on the enum, never on a hand-written list
# ---------------------------------------------------------------------------


class TestEveryClassKeyedMapAdmitsTheNewClass:
    """``.claude/LESSONS.md`` B2: an unmatched class key zero-fills in silence.

    Each map below drops an exposure class it has no key for, while the
    independently-computed parent total still counts it — so the template looks
    internally plausible. Every assertion here is against
    ``{m.value for m in ExposureClass}``, which cannot drift with the reporting
    modules under test.
    """

    @pytest.mark.parametrize("name", list(_CLASS_MAPS))
    def test_the_class_map_covers_every_exposure_class(self, name: str) -> None:
        """Every enum member is a key, and every key is an enum member.

        Both directions: a missing key drops RWEA silently, and an invented key is
        dead code that looks like coverage.

        The key set is built in the test BODY, not in the ``parametrize`` argument.
        A ``set(MAP)`` evaluated at collection time snapshots the keys at import and
        cannot see a later change — measured: written that way, this assertion
        stayed GREEN under the isolating mutation that removes the ``ciu`` key from
        ``C09_01_SA_CLASS_MAP`` at session start, while every cell assertion
        downstream of that map went red.
        """
        keys = set(_CLASS_MAPS[name])
        enum_values = {member.value for member in ExposureClass}
        assert keys == enum_values, (
            f"{name} is not keyed on ExposureClass. Missing (their RWEA leaves the "
            f"breakdown silently): {sorted(enum_values - keys)}. Invented (matches "
            f"nothing the aggregator seals): {sorted(keys - enum_values)}"
        )

    def test_the_published_z_codes_bind_the_two_disjoint_equity_letters(self) -> None:
        """z0015 -> (o) and z0016 -> (p), in both regimes' sheet indexes.

        An empty ``bundle_keys`` is a SKIP, so leaving z0015 unbound makes every
        supervisory rule over the CIU sheet NOT_EVALUATED — indistinguishable from
        a clean estate. Asserted for both regimes because the class is regime-blind.
        """
        for regime in ("crr", "b31"):
            assert _sheet_key(regime, _Z_CODE_112_O) == ExposureClass.CIU.value, regime
            assert _sheet_key(regime, _Z_CODE_112_P) == ExposureClass.EQUITY.value, regime

    def test_the_cms2_total_population_is_the_enum_minus_the_ciu(self) -> None:
        """``CMS2_TOTAL_CLASSES`` is an allow-list, so it must be stated as one.

        PS1/26 puts "the RWA arising from equity investments in funds (rows 12 to
        14 in Template OV1)" in CMS1 row 0070, outside the rows 0010-0060 that
        CMS2 decomposes — so the CIU is the one class CMS2's Total excludes.
        Expressing that as ``enum - {ciu}`` rather than as a literal list is what
        makes a FUTURE class a decision rather than a silent omission: add a
        twentieth ``ExposureClass`` member and this fails until someone says where
        it belongs.
        """
        assert set(CMS2_TOTAL_CLASSES) == {member.value for member in ExposureClass} - {
            ExposureClass.CIU.value
        }, (
            "CMS2_TOTAL_CLASSES is no longer 'every exposure class except the CIU'. Either "
            "a new class was added without deciding its CMS2 home (its RWEA then leaves "
            "the Total and the breakdown stops footing), or the CIU carve-out moved"
        )

    def test_no_cms2_breakdown_row_claims_the_ciu(self) -> None:
        """The carve-out's other half: excluded from the Total AND from every row.

        A CIU in one of the six row tuples while the Total excludes it would make
        the breakdown exceed its parent — the opposite error, equally invisible.
        """
        claimed = {cls for classes in CMS2_SA_CLASS_MAP.values() for cls in classes}
        assert ExposureClass.CIU.value not in claimed, (
            "a CMS2 row now claims the CIU while CMS2_TOTAL_CLASSES excludes it from the "
            "Total — the breakdown would exceed row 0070"
        )

    def test_the_pillar3_sa_disclosure_row_14_binds_the_ciu(self) -> None:
        """CR4/CR5 row 14 is "Collective investment undertakings", and binds (o).

        Row 14 held an empty tuple, which binds nothing: a CIU was counted in row
        15 "Equity" and, once it became its own class, would have fallen out of
        row 15 and landed nowhere. This asserts the binding exists. Whether the
        row PUBLISHES is a different question, and the answer today is no — see
        ``TestCr4AndCr5DoNotAdmitEquityAtAll``.
        """
        row_14 = {ref: classes for ref, _label, classes in SA_DISCLOSURE_CLASSES if ref == "14"}
        assert row_14 == {"14": (ExposureClass.CIU.value,)}, (
            f"Pillar 3 SA_DISCLOSURE_CLASSES row 14 binds {row_14}; an unmapped class is "
            "silently dropped from every row of CR4 and CR5"
        )

    def test_the_ov1_sub_approach_rows_cover_every_ciu_approach_exactly_once(self) -> None:
        """OV1 rows 12-14 partition ``VALID_CIU_APPROACHES``.

        Anchored on the input vocabulary, which is the same set
        ``engine/equity/calculator.py`` dispatches on, so an approach the engine
        can produce cannot be missing a disclosure row. The row->approach pairing
        itself comes from the published instruction (row 12 look-through, 13
        mandate-based, 14 fall-back), not from the module under test.
        """
        ciu_rows = {
            ref: value
            for ref, (column, value) in ov1._EQUITY_SUBAPPROACH_REFS.items()
            if column == "ciu_approach"
        }
        assert ciu_rows == {"12": "look_through", "13": "mandate_based", "14": "fallback"}
        assert set(ciu_rows.values()) == set(VALID_CIU_APPROACHES), (
            f"OV1 rows 12-14 cover {sorted(ciu_rows.values())} against the input vocabulary "
            f"{sorted(VALID_CIU_APPROACHES)} — an approach with no row discloses nowhere"
        )


# ---------------------------------------------------------------------------
# 3. The sheet — emitted, and the (p) sheet falls by exactly what (o) gains
# ---------------------------------------------------------------------------


class TestTheCiuSheetIsEmittedAndTheEquitySheetFalls:
    """OF 07.00 opens the (o) sheet, and (p) drops to the listed leg alone.

    The second half is the load-bearing one. "A ``ciu`` sheet exists carrying
    28,000,000" is equally true of a correct implementation and of one that
    reports the CIU twice — on its own sheet AND on the equity sheet it used to
    sit on. Only the (p) figure falling distinguishes them.
    """

    def test_the_ciu_sheet_is_emitted_and_addressable_by_the_published_z_axis(self) -> None:
        _results, corep, _pillar3 = _run("rich", "b31")

        sheet = _sheet_key("b31", _Z_CODE_112_O)
        assert sheet in corep.c07_00, (
            f"OF 07.00 emits no Article 112(1)(o) sheet; the axis holds "
            f"{sorted(corep.c07_00)}. Every supervisory rule scoped to z0015 then reads "
            "NOT_EVALUATED, which is indistinguishable from a clean estate"
        )

    @pytest.mark.parametrize(
        ("column", "expected"),
        [("0010", _RICH_CIU_EAD), ("0200", _RICH_CIU_EAD), ("0220", _RICH_CIU_RWEA)],
    )
    def test_the_ciu_sheet_row_0010_reports_the_absolute_figures(
        self, column: str, expected: float
    ) -> None:
        """Absolute, not "greater than the old equity figure"."""
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)

        value = _cell(_sheet(corep, "b31", _Z_CODE_112_O), "0010", column)
        assert value == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"OF 07.00 [{sheet}] row 0010 column {column} reports {value}, expected {expected:,.2f}"
        )

    def test_every_money_column_on_the_ciu_total_row_is_non_null(self) -> None:
        """Absence, not wrongness, is this estate's dominant escape.

        A sheet admitted with null gross carriers publishes an inverted Annex II
        waterfall and the "is it emitted" contract stays green on it — measured on
        the (p) sheet when P1.371 half-landed. A null and a legitimate zero are
        different claims, and this portfolio has exposure on every one of these
        columns, so null is wrong on all of them.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)

        nulls = [
            column
            for column in _MONEY_COLUMNS
            if _cell(_sheet(corep, "b31", _Z_CODE_112_O), "0010", column) is None
        ]
        assert not nulls, (
            f"OF 07.00 [{sheet}] row 0010 publishes NULL for columns {nulls} on a sheet "
            f"carrying {_RICH_CIU_EAD:,.2f} of exposure"
        )

    @pytest.mark.parametrize(
        ("column", "expected"),
        [("0010", _RICH_LISTED_EAD), ("0200", _RICH_LISTED_EAD), ("0220", _RICH_LISTED_RWEA)],
    )
    def test_the_equity_sheet_falls_to_the_listed_leg_alone(
        self, column: str, expected: float
    ) -> None:
        """The half that distinguishes "moved" from "double-counted".

        Before P2.54 this cell read 7,000,000 / 30,500,000 — the whole equity
        table. If the CIU were reported on both sheets it would read that again
        while the (o) sheet also looked right.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_P)

        value = _cell(_sheet(corep, "b31", _Z_CODE_112_P), "0010", column)
        assert value == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"OF 07.00 [{sheet}] row 0010 column {column} reports {value}, expected the "
            f"listed leg alone ({expected:,.2f}). The (o) and (p) sheets must PARTITION "
            "the equity table, not overlap on it"
        )

    @pytest.mark.parametrize(
        ("column", "expected"),
        [
            ("0010", _RICH_EQUITY_TABLE_EAD),
            ("0200", _RICH_EQUITY_TABLE_EAD),
            ("0220", _RICH_EQUITY_TABLE_RWEA),
        ],
    )
    def test_the_two_sheets_sum_to_the_whole_equity_table(
        self, column: str, expected: float
    ) -> None:
        """The conservation the two cells above imply, stated as one assertion.

        Pinning (o) and (p) separately already forbids a double count; this
        forbids the other direction — a leg that leaves (p) and reaches neither
        sheet — without reading either figure as a baseline for the other.
        """
        _results, corep, _pillar3 = _run("rich", "b31")

        total = sum(
            _cell(_sheet(corep, "b31", z), "0010", column) or 0.0
            for z in (_Z_CODE_112_O, _Z_CODE_112_P)
        )
        assert total == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"OF 07.00 (o) + (p) row 0010 column {column} sums to {total}, but the equity "
            f"table carries {expected:,.2f}"
        )


# ---------------------------------------------------------------------------
# 4. Rows 0281-0285 — the approach decomposition
# ---------------------------------------------------------------------------


class TestTheCiuApproachRows:
    """Rows 0281-0283 decompose row 0010 by Art. 132 / 132A approach.

    These rows were declared and wired before P2.54 and published nothing at all,
    because ``ciu_approach`` was stripped at the aggregator seal: a wired row
    whose carrier column is ABSENT compiles to match-nothing and is nulled, with
    no exception, no error-list entry and no failing rule. That is the
    silent-null reporting cell in its purest form, which is why the rows are
    asserted as absolute figures here and not merely as non-null.
    """

    def test_the_book_carries_exactly_two_of_the_three_approaches(self) -> None:
        """Adequacy. ``r0010 = r0281 + r0282 + r0283`` is a tautology on one leg.

        Two legs on two DIFFERENT approaches is what makes the published identity
        a real sum — and what makes a row-to-approach mix-up detectable, since the
        two legs' figures are an order of magnitude apart (25,000,000 against
        3,000,000, from 1,250% and 75%).

        The carrier's PRESENCE is asserted before its values, because absent and
        null are different code paths and only one of them is a fixture question:
        ``ciu_approach`` is an ``inject=False`` edge column, so a regression in the
        seal removes it from the frame entirely and every reader silently compiles
        to match-nothing. Measured under the isolating mutation that strips it,
        reading the column first raised ``ColumnNotFoundError`` — an error, not a
        finding.
        """
        results, _corep, _pillar3 = _run("rich", "b31")

        assert "ciu_approach" in results.columns, (
            "the sealed ledger carries no ciu_approach column at all. It is declared "
            "inject=False on AGGREGATOR_EXIT_EDGE, so ABSENT means the seal stopped "
            "emitting it — C 07.00 rows 0281-0283, C 09.01 rows 0141-0143 and Pillar 3 "
            "OV1 rows 12-14 are all dark, and none of them raises"
        )
        approaches = sorted(
            value for value in _ciu_legs(results)["ciu_approach"].to_list() if value is not None
        )
        assert approaches == ["fallback", "mandate_based"], (
            f"the CIU legs carry approaches {approaches}; two distinct non-null values are "
            "what make the 0281-0283 identity a two-term sum instead of a tautology"
        )
        assert _RICH_CIU_FALLBACK_RWEA != _RICH_CIU_MANDATE_RWEA, (
            "the two CIU legs carry equal RWEA, so swapping rows 0282 and 0283 would be "
            "undetectable"
        )

    @pytest.mark.parametrize("column", _MONEY_COLUMNS)
    def test_the_mandate_based_row_reports_the_mandate_leg(self, column: str) -> None:
        """Row 0282 = Art. 132A(2). ``RP-EQ-CIU-MANDATE``: 4,000,000 at 75%."""
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)

        expected = _RICH_CIU_MANDATE_RWEA if column == "0220" else 4_000_000.0
        value = _cell(_sheet(corep, "b31", _Z_CODE_112_O), "0282", column)
        assert value == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"OF 07.00 [{sheet}] row 0282 ('Mandate-based approach', Art. 132A(2)) column "
            f"{column} reports {value}, expected {expected:,.2f}"
        )

    @pytest.mark.parametrize("column", _MONEY_COLUMNS)
    def test_the_fall_back_row_reports_the_fall_back_leg(self, column: str) -> None:
        """Row 0283 = Art. 132(2). ``RP-EQ-CIU-FALLBACK``: 2,000,000 at 1,250%."""
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)

        expected = _RICH_CIU_FALLBACK_RWEA if column == "0220" else 2_000_000.0
        value = _cell(_sheet(corep, "b31", _Z_CODE_112_O), "0283", column)
        assert value == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"OF 07.00 [{sheet}] row 0283 ('Fall-back approach', Art. 132(2)) column "
            f"{column} reports {value}, expected {expected:,.2f}"
        )

    @pytest.mark.parametrize("column", _MONEY_COLUMNS)
    def test_the_look_through_row_is_null_because_no_leg_takes_that_approach(
        self, column: str
    ) -> None:
        """Row 0281 publishes NULL, not 0.00 — "no look-through CIU in this book".

        Asserted as null rather than ignored so that the identity below is known
        to be a two-term sum measured on output, not an assumption about the
        fixture. Adding a look-through leg makes this red, which is the correct
        signal: re-derive the identity with three terms.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)

        assert _cell(_sheet(corep, "b31", _Z_CODE_112_O), "0281", column) is None, (
            f"OF 07.00 [{sheet}] row 0281 ('Look-through approach') publishes a figure in "
            f"column {column} on a book whose CIU legs are mandate-based and fall-back"
        )

    @pytest.mark.parametrize("column", _MONEY_COLUMNS)
    @pytest.mark.parametrize("row_ref", _RELEVANT_CIU_ROWS)
    def test_the_relevant_ciu_of_which_rows_stay_null_deliberately(
        self, row_ref: str, column: str
    ) -> None:
        """Rows 0284 / 0285 are declared, dark, and that is CORRECT today.

        Pinned rather than omitted. They are "of which: exposures to relevant
        CIUs" beneath 0281 and 0282, and no "relevant CIU" flag exists anywhere in
        the input domain — not as an input column, not as a pack entry, not as a
        ``VALID_*`` vocabulary. Both published summation rules over this block
        (``boe_b0728``, ``v09743_m``: ``{r0010} = {r0281} + {r0282} + {r0283}``)
        exclude them, so the gap breaks no named identity and deferring it is
        deliberate. They are Basel-3.1-only rows.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)

        assert _cell(_sheet(corep, "b31", _Z_CODE_112_O), row_ref, column) is None, (
            f"OF 07.00 [{sheet}] row {row_ref} now publishes in column {column}. A "
            "'relevant CIU' carrier has been added — wire both rows and re-read "
            "boe_b0728 / v09743_m, which do NOT include them in their sums"
        )

    @pytest.mark.parametrize("column", _MONEY_COLUMNS)
    def test_the_published_identity_row_0010_equals_the_approach_rows(self, column: str) -> None:
        """``boe_b0728`` / ``v09743_m``: ``{r0010} = {r0281} + {r0282} + {r0283}``.

        The footing, over the carrier its parent sums. Evaluated against the
        generated cells, so a breakdown bound to a plausible-but-different carrier
        cannot satisfy it by coincidence.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        sheet = _sheet_key("b31", _Z_CODE_112_O)
        frame = _sheet(corep, "b31", _Z_CODE_112_O)

        terms = {ref: _cell(frame, ref, column) for ref in _CIU_APPROACH_ROWS}
        parent = _cell(frame, "0010", column)
        assert sum(value or 0.0 for value in terms.values()) == pytest.approx(
            parent, rel=_REL, abs=_ABS
        ), (
            f"OF 07.00 [{sheet}] column {column}: rows 0281-0283 sum to "
            f"{sum(value or 0.0 for value in terms.values())} against row 0010 = {parent} "
            f"(terms {terms})"
        )
        populated = [ref for ref, value in terms.items() if value not in (None, 0.0)]
        assert len(populated) == 2, (
            f"the identity held with {len(populated)} populated term(s) {populated} — a "
            "one-term sum holds under any row mapping and asserts nothing"
        )


# ---------------------------------------------------------------------------
# 4b. The rows a CIU sheet must leave EMPTY, and the guards that say so
# ---------------------------------------------------------------------------


class TestTheCiuSheetLeavesTheReservedRowsEmpty:
    """Rows 0015 and 0040 belong to other classes, so the (o) sheet leaves them blank.

    COREP Annex II restricts row 0015 ("of which: items associated with
    particularly high risk") and row 0040 to the high-risk and equity classes, and
    four live EBA rules encode that as must-be-empty guards: ``v4721_m``
    (``{r0015} = empty``, C 07.00.a), ``v4722_m`` (``{r0015} = 0``, C 07.00.b),
    ``v7477_m`` and ``v7478_m`` (``{r0040} = empty``, .a and .b).

    **A must-be-empty guard can never score PASS**, and that is the point of
    asserting the cells here as well as the verdicts. It has no satisfiable
    operand: it is VACUOUS while the row is blank and FAIL the moment a figure
    appears, so "it went green" is not evidence of anything and "it stayed
    VACUOUS" is the positive result. Measured, none of the four carries a z-code
    scope at all, so each applies to EVERY emitted sheet — which is why
    ``v4721_m`` FAILs on ``crr/rich`` (the ``defaulted`` sheet publishes
    1,000,000 on row 0015, a banked break with nothing to do with the CIU) while
    all four are VACUOUS on ``crr/off-bs``. Reading the rule verdict alone would
    therefore tell you nothing about CIU placement; the cells do.
    """

    @pytest.mark.parametrize(("portfolio", "regime"), _CIU_SHEET_CASES)
    def test_the_reserved_rows_are_empty_on_the_ciu_sheet(
        self, portfolio: str, regime: str
    ) -> None:
        """Every money cell on rows 0015 / 0040 of the (o) sheet is null.

        Row 0040 is declared in the CRR layout only; its ABSENCE under Basel 3.1
        is asserted rather than skipped, so a layout change that adds it arrives
        with a decision rather than a silent blank row.
        """
        _results, corep, _pillar3 = _run(portfolio, regime)
        frame = _sheet(corep, regime, _Z_CODE_112_O)
        declared = set(frame["row_ref"].to_list())
        money = [c for c in frame.columns if c not in ("row_ref", "row_name")]

        for row_ref in _MUST_BE_EMPTY_ROWS:
            if row_ref not in declared:
                assert (row_ref, regime) == ("0040", "b31"), (
                    f"[{portfolio}/{regime}] the (o) sheet does not declare row {row_ref}; "
                    "only row 0040 under Basel 3.1 is expected to be absent"
                )
                continue
            populated = {
                column: _cell(frame, row_ref, column)
                for column in money
                if _cell(frame, row_ref, column) is not None
            }
            assert not populated, (
                f"[{portfolio}/{regime}] the Article 112(1)(o) sheet publishes on row "
                f"{row_ref}, which COREP Annex II reserves for the high-risk and equity "
                f"classes: {populated}. This is what v4721_m / v4722_m / v7477_m / "
                "v7478_m FAIL on"
            )

    @pytest.mark.parametrize("rule_id", _EMPTY_GUARD_RULES)
    def test_the_must_be_empty_guards_stay_vacuous_on_the_crr_ciu_book(self, rule_id: str) -> None:
        """VACUOUS, not PASS — and specifically not FAIL.

        ``crr/off-bs`` is the book to ask on: it emits the (o) sheet and has
        neither a ``defaulted`` nor a ``high_risk`` sheet, so the four guards see
        nothing but legitimately blank rows and their silence is attributable to
        the CIU sheet rather than to some other class.
        """
        outcome = _outcome("off-bs", "crr", rule_id)

        assert outcome.status == "VACUOUS", (
            f"{rule_id} scored {outcome.status}/{outcome.reason!r} on crr/off-bs at "
            f"{outcome.coordinates}. It is a must-be-empty guard: VACUOUS means the rows "
            "it reserves are blank, FAIL means a class has been placed on one of them, "
            "and PASS is unreachable"
        )

    def test_the_published_ciu_decomposition_rule_is_evaluated_under_crr(self) -> None:
        """``v09743_m`` is the coverage this item buys on the CRR side.

        Scoped to z0015 alone, so before a CRR run emitted an (o) sheet it could
        only score ``sheet_not_emitted`` — NOT_EVALUATED, which is
        indistinguishable from a clean estate. Both states are asserted: PASS on
        the SA-config book that emits the sheet, and ``sheet_not_emitted`` on the
        IRB-config book that correctly does not. Asserting only the first would
        not show that the rule's silence elsewhere is the scope boundary working.
        """
        emitted = _outcome("off-bs", "crr", _CIU_DECOMPOSITION_RULE)
        assert emitted.status == "PASS", (
            f"{_CIU_DECOMPOSITION_RULE} scored {emitted.status}/{emitted.reason!r} on "
            f"crr/off-bs at {emitted.coordinates} — the CRR r0010 = r0281 + r0282 + r0283 "
            "identity is the one the EBA publishes for this block"
        )
        absent = _outcome("rich", "crr", _CIU_DECOMPOSITION_RULE)
        assert absent.reason == "sheet_not_emitted", (
            f"{_CIU_DECOMPOSITION_RULE} scored {absent.status}/{absent.reason!r} on "
            "crr/rich, whose equity-table legs are Art. 155(2) IRB-method and therefore "
            "out of C 07.00's scope — the rule should find no sheet to evaluate"
        )


# ---------------------------------------------------------------------------
# 5. C 02.00 — the class breakdown, which the approach totals cannot police
# ---------------------------------------------------------------------------


class TestC0200ReportsTheCiuUnderItsOwnRow:
    """Row 0200 takes the CIU RWEA and row 0210 falls by exactly that amount.

    C 02.00's parent totals are keyed on the APPROACH, not the class, so they do
    not move when a class loses its row — measured: 28,000,000 left the breakdown
    and landed nowhere while r0010, r0050 and r0060 were bit-identical. The
    breakdown footing is therefore the only assertion here that could have caught
    it, and it is stated over every SA class row rather than over the two that
    moved.
    """

    def test_row_0200_reports_the_ciu_rwea(self) -> None:
        _results, corep, _pillar3 = _run("rich", "b31")

        value = _cell(corep.c_02_00, "0200", "0010")
        assert value == pytest.approx(_RICH_CIU_RWEA, rel=_REL, abs=_ABS), (
            f"C 02.00 r0200 ('Collective investments undertakings (CIU)') reports {value}, "
            f"expected {_RICH_CIU_RWEA:,.2f}"
        )

    def test_row_0210_falls_to_the_listed_leg_alone(self) -> None:
        """Pre-P2.54 this row carried 30,500,000 — the whole equity table."""
        _results, corep, _pillar3 = _run("rich", "b31")

        value = _cell(corep.c_02_00, "0210", "0010")
        assert value == pytest.approx(_RICH_LISTED_RWEA, rel=_REL, abs=_ABS), (
            f"C 02.00 r0210 ('Equity') reports {value}, expected the listed leg alone "
            f"({_RICH_LISTED_RWEA:,.2f}). Rows 0200 and 0210 are disjoint classes, not a "
            "parent and an of-which"
        )

    def test_the_sa_class_breakdown_foots_to_the_standardised_total(self) -> None:
        """Every SA class row sums to r0060 — the identity that sees a lost class.

        Keyed on ``C02_00_SA_CLASS_MAP``'s own row set so a class added without a
        row cannot hide: its RWEA stays in r0060, which has no class predicate,
        and the sum of the rows falls short by exactly that amount.
        """
        _results, corep, _pillar3 = _run("rich", "b31")

        rows = sorted(set(C02_00_SA_CLASS_MAP.values()))
        breakdown = sum(_cell(corep.c_02_00, ref, "0010") or 0.0 for ref in rows)
        sa_total = _cell(corep.c_02_00, "0060", "0010")
        assert breakdown == pytest.approx(sa_total, rel=_REL, abs=_ABS), (
            f"C 02.00 SA class rows {rows} sum to {breakdown} against r0060 "
            f"('Of which: Standardised Approach') = {sa_total}. The shortfall is RWEA "
            "counted in the approach total and absent from every class row"
        )
        assert sa_total == pytest.approx(_RICH_B31_SA_TOTAL, rel=_REL, abs=_ABS)

    def test_the_portfolio_totals_do_not_move(self) -> None:
        """The class move is a disclosure re-split, not a capital change.

        Pinned absolutely against the ledger as well as against the figure: an
        implementation that moved the CIU's RWEA rather than its row would satisfy
        the breakdown footing above and fail here.
        """
        results, corep, _pillar3 = _run("rich", "b31")

        ledger_total = float(results["rwa_final"].sum())
        assert ledger_total == pytest.approx(_RICH_B31_TREA, rel=_REL, abs=_ABS)
        for ref in ("0010", "0050"):
            value = _cell(corep.c_02_00, ref, "0010")
            assert value == pytest.approx(_RICH_B31_TREA, rel=_REL, abs=_ABS), (
                f"C 02.00 r{ref} reports {value} against a ledger carrying {ledger_total}"
            )


# ---------------------------------------------------------------------------
# 6. C 09.01 — the geographical breakdown, and the TOTAL/GB trap
# ---------------------------------------------------------------------------


class TestC0901ReportsTheCiuOnTheTotalSheet:
    """Row 0140 takes the CIU, row 0150 falls, and row 0170 still foots.

    ⚠ Every assertion here is on the ``TOTAL`` sheet. **Measured: the equity-table
    legs reach no country sheet at all** — on ``[GB]`` rows 0140-0143 and 0150 are
    null in every regime and on both portfolios, despite the obligor carrying
    ``country_code="GB"``. A ``[GB]`` assertion would therefore pass VACUOUSLY
    against a null, which is why ``test_the_country_sheet_carries_no_equity_table_leg``
    asserts that state explicitly instead of leaving it unexamined.
    """

    def test_row_0140_reports_the_ciu_and_row_0150_falls_to_the_listed_leg(self) -> None:
        _results, corep, _pillar3 = _run("rich", "b31")
        total = corep.c09_01["TOTAL"]

        for column, ciu, listed in (
            ("0010", _RICH_CIU_EAD, _RICH_LISTED_EAD),
            ("0075", _RICH_CIU_EAD, _RICH_LISTED_EAD),
            ("0090", _RICH_CIU_RWEA, _RICH_LISTED_RWEA),
        ):
            assert _cell(total, "0140", column) == pytest.approx(ciu, rel=_REL, abs=_ABS), (
                f"C 09.01 [TOTAL] r0140 (CIU) column {column}"
            )
            assert _cell(total, "0150", column) == pytest.approx(listed, rel=_REL, abs=_ABS), (
                f"C 09.01 [TOTAL] r0150 (equity) column {column} did not fall to the "
                "listed leg — (o) and (p) are disjoint rows"
            )

    @pytest.mark.parametrize("column", ["0010", "0075", "0090"])
    def test_the_published_total_identity_holds(self, column: str) -> None:
        """``boe_b0730`` — the only ERROR-severity rule this item's absence broke.

        ``{r0170} = sum({r0010..0120; 0140; 0150; 0160})``. Without a ``ciu`` key in
        ``C09_01_SA_CLASS_MAP`` the CIU's exposure and RWEA left row 0150 and had
        no row to land in, while row 0170 — which has no class predicate — still
        counted them, so the identity broke by 6,000,000 and 28,000,000.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        total = corep.c09_01["TOTAL"]

        terms = sum(_cell(total, ref, column) or 0.0 for ref in _C09_01_TOTAL_TERMS)
        parent = _cell(total, "0170", column)
        assert terms == pytest.approx(parent, rel=_REL, abs=_ABS), (
            f"C 09.01 [TOTAL] column {column}: rows {_C09_01_TOTAL_TERMS} sum to {terms} "
            f"against r0170 = {parent}"
        )
        assert (_cell(total, "0140", column) or 0.0) > 0.0, (
            f"C 09.01 [TOTAL] r0140 contributes nothing to column {column}, so this "
            "identity would hold with the CIU row unbound and asserts nothing"
        )

    @pytest.mark.parametrize("column", ["0010", "0075", "0090"])
    def test_the_approach_rows_0141_0143_decompose_row_0140(self, column: str) -> None:
        """PS1/26 Annex II, OF 09.01 row 0140: "Sum of rows 0141 to 0143".

        The C 09.01 twin of rows 0281-0283, keyed on the same ``ciu_approach``
        carrier. Two populated terms, for the same reason.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        total = corep.c09_01["TOTAL"]

        terms = {ref: _cell(total, ref, column) for ref in _CIU_APPROACH_ROWS_C09}
        parent = _cell(total, "0140", column)
        assert sum(value or 0.0 for value in terms.values()) == pytest.approx(
            parent, rel=_REL, abs=_ABS
        ), f"C 09.01 [TOTAL] rows 0141-0143 column {column}: {terms} against r0140 = {parent}"
        assert terms["0141"] is None, (
            "C 09.01 [TOTAL] r0141 (look-through) publishes a figure on a book with no "
            "look-through leg"
        )
        assert len([v for v in terms.values() if v not in (None, 0.0)]) == 2, (
            f"the identity held with fewer than two populated terms ({terms})"
        )

    def test_the_ciu_approach_rows_agree_with_their_c07_twins(self) -> None:
        """``boe_b0996``-``boe_b1001``: each OF 09.01 row against its OF 07.00 twin.

        Six live cross-template rules pair (r0142, r0143) x (c0010, c0075, c0090)
        with (r0282, r0283) x (c0010, c0200, c0220) on z0015. Asserted here as one
        test because the two templates read the same carrier through two different
        row axes, and agreeing with each other is a stronger claim than either
        matching a constant.
        """
        _results, corep, _pillar3 = _run("rich", "b31")
        total = corep.c09_01["TOTAL"]
        c07 = _sheet(corep, "b31", _Z_CODE_112_O)

        for c09_row, c07_row in (("0142", "0282"), ("0143", "0283")):
            for c09_col, c07_col in (("0010", "0010"), ("0075", "0200"), ("0090", "0220")):
                left = _cell(total, c09_row, c09_col)
                right = _cell(c07, c07_row, c07_col)
                assert left == pytest.approx(right, rel=_REL, abs=_ABS), (
                    f"C 09.01 [TOTAL] r{c09_row} c{c09_col} = {left} against OF 07.00 "
                    f"[ciu] r{c07_row} c{c07_col} = {right}"
                )

    @pytest.mark.parametrize(("portfolio", "regime"), [("rich", "b31"), ("off-bs", "crr")])
    def test_the_country_sheet_carries_no_equity_table_leg(
        self, portfolio: str, regime: str
    ) -> None:
        """The trap, asserted rather than avoided.

        The equity table never reaches a country sheet, so a CIU assertion aimed
        at ``[GB]`` would compare ``None`` against ``None`` and pass while the
        class was still unbound. This states the absence AND quantifies it: the
        whole gap between the two sheets' row 0170 is exactly the equity table, so
        if a leg ever does reach ``[GB]`` both halves move and this goes red.
        """
        results, corep, _pillar3 = _run(portfolio, regime)
        gb, total = corep.c09_01["GB"], corep.c09_01["TOTAL"]

        for ref in ("0140", "0141", "0142", "0143", "0150"):
            cells = [_cell(gb, ref, column) for column in ("0010", "0075", "0090")]
            assert all(value is None for value in cells), (
                f"[{portfolio}/{regime}] C 09.01 [GB] r{ref} now publishes {cells}. An "
                "equity-table leg has reached a country sheet — re-point the TOTAL-sheet "
                "assertions in this class, which were written because it could not"
            )

        equity_table = results.filter(pl.col("reporting_approach_origin") == "equity")
        for column, ledger_column in (("0010", "ead_final"), ("0090", "rwa_final")):
            gap = (_cell(total, "0170", column) or 0.0) - (_cell(gb, "0170", column) or 0.0)
            assert gap == pytest.approx(
                float(equity_table[ledger_column].sum()), rel=_REL, abs=_ABS
            ), (
                f"[{portfolio}/{regime}] C 09.01 TOTAL - GB on r0170 c{column} is {gap}, "
                f"which is not the equity table's {ledger_column}. The geographies differ "
                "by something other than the equity book"
            )


# ---------------------------------------------------------------------------
# 7. Pillar 3 OV1 — the sub-approach memo rows
# ---------------------------------------------------------------------------


class TestPillar3Ov1SubApproachRows:
    """OV1 rows 12-14 publish once ``ciu_approach`` is sealed.

    The rows were wired before P2.54 and recorded as permanently null, because the
    discriminator they key on was stripped at the aggregator exit. Declaring it as
    a conditional edge column lights them and OF 07.00 rows 0281-0283 from the
    same one-line change, which is why both are asserted: one carrier, two
    consumers, and a regression in the seal darkens both at once.
    """

    @pytest.mark.parametrize(
        ("row_ref", "expected"),
        [
            ("13", _RICH_CIU_MANDATE_RWEA),
            ("14", _RICH_CIU_FALLBACK_RWEA),
        ],
    )
    def test_the_populated_sub_approach_rows_report_their_legs(
        self, row_ref: str, expected: float
    ) -> None:
        """Row 13 = mandate-based, row 14 = fall-back, per the published labels.

        Column c is own funds at 8% of column a — asserted because a memo row
        whose RWEA is right and whose requirement is null is still an unfiled
        disclosure.
        """
        _results, _corep, pillar3 = _run("rich", "b31")

        rwea = _cell(pillar3.ov1, row_ref, "a")
        own_funds = _cell(pillar3.ov1, row_ref, "c")
        assert rwea == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"Pillar 3 OV1 row {row_ref} ('Equity investments in funds') reports {rwea}, "
            f"expected {expected:,.2f}"
        )
        assert own_funds == pytest.approx(expected * 0.08, rel=_REL, abs=_ABS), (
            f"OV1 row {row_ref} column c must be 8% of column a, got {own_funds}"
        )

    def test_the_look_through_row_stays_null(self) -> None:
        """Row 12 — no look-through leg, so nothing to report, so null."""
        _results, _corep, pillar3 = _run("rich", "b31")

        assert _cell(pillar3.ov1, "12", "a") is None
        assert _cell(pillar3.ov1, "12", "c") is None

    def test_the_offbs_book_lights_only_its_own_approach_row(self) -> None:
        """A second portfolio on the same rows, with only ONE approach present.

        ``off-bs`` holds a single mandate-based CIU, so row 13 carries its whole
        RWEA and rows 12 and 14 are null. A row-mapping error that happened to be
        self-consistent on the rich book's two legs has to survive a book whose
        only leg sits on the middle row.
        """
        _results, _corep, pillar3 = _run("off-bs", "b31")

        assert _cell(pillar3.ov1, "13", "a") == pytest.approx(CIU_RWEA, rel=_REL, abs=_ABS)
        assert _cell(pillar3.ov1, "12", "a") is None
        assert _cell(pillar3.ov1, "14", "a") is None

    def test_row_1_still_counts_the_ciu_rwea_it_is_told_to_exclude(self) -> None:
        """RECORDED GAP, pinned so it is visible rather than assumed away.

        PS1/26 Annex II, UKB OV1 row 1: "RWEAs for equity positions that shall be
        reported in rows 11-14 of this template are excluded." Row 1 is an
        unpredicated total, so the CIU's 28,000,000 is disclosed TWICE — inside
        row 1 (and its "of which: SA" row 2) and again in rows 13-14 — while row
        29 counts it once. Pre-existing in shape and newly reachable: before these
        legs the estate had no row 11-14 population at all, so nothing could
        double-count.

        **If this test goes red, the exclusion has been implemented.** Check row 2
        and the of-which partition (rows 2+3+4+5 == row 1) in the same change:
        narrowing row 1 without narrowing row 2 breaks that footing by the same
        28,000,000. Do not widen this test to keep it green.
        """
        results, _corep, pillar3 = _run("rich", "b31")

        row_1 = _cell(pillar3.ov1, "1", "a")
        sub_approach = sum(_cell(pillar3.ov1, ref, "a") or 0.0 for ref in ("11", "12", "13", "14"))
        assert row_1 == pytest.approx(float(results["rwa_final"].sum()), rel=_REL, abs=_ABS), (
            f"OV1 row 1 reports {row_1}, no longer the whole ledger — the rows 11-14 "
            "exclusion may have landed; see this test's docstring before editing it"
        )
        assert sub_approach == pytest.approx(_RICH_CIU_RWEA, rel=_REL, abs=_ABS), (
            f"OV1 rows 11-14 sum to {sub_approach}, expected the CIU RWEA "
            f"{_RICH_CIU_RWEA:,.2f} — without that this test says nothing about a "
            "double count"
        )


# ---------------------------------------------------------------------------
# 8. Pillar 3 CMS1 / CMS2 — the output-floor comparison
# ---------------------------------------------------------------------------


class TestCms2CarvesTheCiuOutAndStillFoots:
    """CMS2 excludes the CIU from its Total, and its published identity holds.

    PS1/26 CMS2 §1: "As in row 1 of Template CMS1, it excludes counterparty credit
    risk, credit valuation adjustments and securitisation exposures in the banking
    book"; and CMS1 row 0070 is "RWA not captured within rows 0010 to 0060 (ie the
    RWA arising from equity investments in funds (rows 12 to 14 in Template
    OV1))". So the CIU is outside the population CMS2 decomposes — it gets no row,
    and it must not be in the Total either, while CMS1 reports it in row 0070.

    This is the template pair where getting it half-right is worst: CMS2's Total
    is the output-floor comparison, so a population in the Total and in no row
    understates the breakdown against the floor by exactly that amount, in column
    d as well as column c.
    """

    @pytest.mark.parametrize("column", ["a", "b", "c", "d"])
    def test_the_total_equals_the_sum_of_its_breakdown_rows(self, column: str) -> None:
        """PS1/26: CMS2 row 0070 is "The sum of rows 0010, 0020, 0030, 0040, 0050
        and 0060".

        Asserted on all four columns, column d included: that is the
        full-standardised output-floor comparison, and an unpredicated Total there
        was over-stating the floor comparison against its own breakdown by the
        whole CIU RWEA.
        """
        _results, _corep, pillar3 = _run("rich", "b31")

        breakdown = sum(
            _cell(pillar3.cms2, ref, column) or 0.0
            for ref in ("0010", "0020", "0030", "0040", "0050", "0060")
        )
        total = _cell(pillar3.cms2, "0070", column)
        assert breakdown == pytest.approx(total, rel=_REL, abs=_ABS), (
            f"CMS2 column {column}: rows 0010-0060 sum to {breakdown} against row 0070 "
            f"= {total}. The Total counts a population no row decomposes"
        )

    def test_the_total_is_the_ledger_less_exactly_the_ciu(self) -> None:
        """The carve-out is the CIU and nothing else.

        The footing identity above is satisfied by ANY matching pair of
        populations, including one that dropped a second class by accident. This
        pins the magnitude: Total == whole ledger - CIU RWEA, measured on the
        ledger rather than on another cell.
        """
        results, _corep, pillar3 = _run("rich", "b31")

        ledger = float(results["rwa_final"].sum())
        ciu = float(_ciu_legs(results)["rwa_final"].sum())
        total = _cell(pillar3.cms2, "0070", "c")
        assert ciu == pytest.approx(_RICH_CIU_RWEA, rel=_REL, abs=_ABS)
        assert total == pytest.approx(ledger - ciu, rel=_REL, abs=_ABS), (
            f"CMS2 row 0070 column c reports {total}; the ledger carries {ledger} of which "
            f"{ciu} is Art. 112(1)(o). The carve-out is not exactly the CIU"
        )
        assert total == pytest.approx(_RICH_CMS2_TOTAL_C, rel=_REL, abs=_ABS)

    def test_cms1_puts_the_ciu_in_its_residual_row_and_agrees_with_cms2(self) -> None:
        """The CMS1 half of the same carve-out, and the tie it makes possible.

        PS1/26, UKB CMS1 row 0070: "RWA not captured within rows 0010 to 0060 (ie
        the RWA arising from equity investments in funds (rows 12 to 14 in Template
        OV1), settlement risk ...)". So the CIU leaves CMS1 row 0010 — which is
        exactly the population CMS2 decomposes — and lands in row 0070, which row
        0080's published formula (the sum of 0010/c to 0070/c) keeps.

        Three assertions, because each alone is satisfiable by a different wrong
        implementation: row 0070 carrying the figure (but row 0010 keeping it too
        would double-count), row 0010 shedding it (but with no row 0070 it would be
        lost), and the two templates agreeing on the shared scope. The footings
        themselves live in ``test_cms1_ccr.py``; this is the cross-template claim
        P2.54 is responsible for.
        """
        _results, _corep, pillar3 = _run("rich", "b31")

        residual = _cell(pillar3.cms1, "0070", "c")
        assert residual == pytest.approx(_RICH_CIU_RWEA, rel=_REL, abs=_ABS), (
            f"CMS1 row 0070 ('Residual RWA') reports {residual}, expected the "
            f"Art. 112(1)(o) CIU RWEA {_RICH_CIU_RWEA:,.2f} — the published home for "
            "equity investments in funds"
        )
        credit_risk = _cell(pillar3.cms1, "0010", "c")
        assert credit_risk == pytest.approx(_RICH_B31_TREA - _RICH_CIU_RWEA, rel=_REL, abs=_ABS), (
            f"CMS1 row 0010 ('Credit risk excluding CCR') reports {credit_risk}; it must "
            f"shed the CIU's {_RICH_CIU_RWEA:,.2f} into row 0070, not keep it as well"
        )
        assert credit_risk == pytest.approx(_cell(pillar3.cms2, "0070", "c"), rel=_REL, abs=_ABS), (
            "CMS1 row 0010 and CMS2 row 0070 disagree; CMS2's population is 'as in row 1 "
            "of Template CMS1', so on a book with no CCR they are the same number"
        )


# ---------------------------------------------------------------------------
# 9. Pillar 3 CR4 / CR5 — the pre-existing hole the new row lands beside
# ---------------------------------------------------------------------------


class TestCr4AndCr5DoNotAdmitEquityAtAll:
    """Binding row 14 does NOT make it publish, and row 15 shows why.

    Measured on ``b31/rich``: CR4 and CR5 rows 14 AND 15 publish a hard 0.00
    across every column against a book carrying 30,500,000 of equity-origin RWEA.
    The equity population never reached these templates, so the class map was
    never what kept row 14 dark. Filed separately; pinned here so the filing has
    evidence and so nobody reads the 0.00 as "this book has no CIU".
    """

    @pytest.mark.parametrize("template", ["cr4", "cr5"])
    @pytest.mark.parametrize("row_ref", ["14", "15"])
    def test_the_row_publishes_zero_against_a_book_that_has_exposure(
        self, template: str, row_ref: str
    ) -> None:
        results, _corep, pillar3 = _run("rich", "b31")
        frame = getattr(pillar3, template)

        equity_origin = float(
            results.filter(pl.col("reporting_approach_origin") == "equity")["rwa_final"].sum()
        )
        assert equity_origin == pytest.approx(_RICH_EQUITY_TABLE_RWEA, rel=_REL, abs=_ABS), (
            "the book must carry equity-origin RWEA for the zero below to be a finding"
        )
        assert _cell(frame, row_ref, "e") == pytest.approx(0.0, abs=_ABS), (
            f"Pillar 3 {template.upper()} row {row_ref} column e now reports "
            f"{_cell(frame, row_ref, 'e')} rather than 0.00. If the equity population has "
            f"been admitted to {template.upper()}, row 14 should carry "
            f"{_RICH_CIU_RWEA:,.2f} and row 15 {_RICH_LISTED_RWEA:,.2f} — assert those and "
            "delete this pin"
        )


# ---------------------------------------------------------------------------
# 10. The CRR arm — one negative control, one positive control
# ---------------------------------------------------------------------------


class TestTheCrrArmOfTheRuling:
    """The class is regime-blind; the SHEET is not, and the cut is the method.

    ``rich`` (IRB permission) is the negative control: under CRR every
    equity-table leg is Art. 155(2) and COREP Annex II ¶50 keeps it out of
    C 07.00. ``off-bs`` (``PermissionMode.STANDARDISED``) is the positive control:
    its CIU is SA-method, so the CRR (o) sheet IS emitted. Both are needed — the
    negative control alone passes under an implementation with no CIU class at
    all, which is exactly how a both-regimes ruling ships with one arm unexecuted.
    """

    def test_neither_equity_letter_opens_a_crr_sheet_on_an_irb_book(self) -> None:
        """Negative control. Measured, and the RWEA is in C 02.00 r0420 instead."""
        results, corep, _pillar3 = _run("rich", "crr")

        for z_code in (_Z_CODE_112_O, _Z_CODE_112_P):
            sheet = _sheet_key("crr", z_code)
            assert sheet not in corep.c07_00, (
                f"C 07.00 emits the z{z_code} [{sheet}] sheet under CRR for an Art. 155(2) "
                "IRB-method book; COREP Annex II para 50 scopes this template to Chapter 2 "
                f"of Title II of Part Three CRR. Axis: {sorted(corep.c07_00)}"
            )
        assert _cell(corep.c_02_00, "0200", "0010") == pytest.approx(0.0, abs=_ABS)
        assert _cell(corep.c_02_00, "0420", "0010") == pytest.approx(
            _RICH_CRR_EQUITY_TABLE_RWEA, rel=_REL, abs=_ABS
        ), (
            "C 02.00 r0420 ('Equity IRB') must carry the whole equity table under CRR — "
            "otherwise r0200 reading 0.00 is consistent with the RWEA having been dropped"
        )
        assert float(_ciu_legs(results)["rwa_final"].sum()) == pytest.approx(
            _RICH_CRR_CIU_RWEA, rel=_REL, abs=_ABS
        ), (
            "the CIU legs carry no CRR RWEA, so their absence from C 07.00 is not evidence "
            "of a scope boundary"
        )

    def test_a_crr_ciu_sheet_is_emitted_for_an_sa_method_book(self) -> None:
        """Positive control — the arm the estate lacked.

        Without this, the ruling that SI 2021/1078 relocated rather than abolished
        Arts. 132/132a ships with its CRR half never executed: ``rich``'s CRR
        assertions are satisfied by an engine that has no CIU class, and so is
        every golden.
        """
        _results, corep, _pillar3 = _run("off-bs", "crr")

        sheet = _sheet_key("crr", _Z_CODE_112_O)
        assert sheet in corep.c07_00, (
            f"C 07.00 emits no Article 112(1)(o) sheet under CRR for an SA-method CIU. "
            f"Axis: {sorted(corep.c07_00)}. The class stamp is regime-blind, so this is "
            "the arm that proves it"
        )
        frame = _sheet(corep, "crr", _Z_CODE_112_O)
        assert _cell(frame, "0010", "0010") == pytest.approx(CARRYING_CIU, rel=_REL, abs=_ABS)
        assert _cell(frame, "0010", "0220") == pytest.approx(CIU_RWEA, rel=_REL, abs=_ABS)
        assert _cell(frame, "0282", "0220") == pytest.approx(CIU_RWEA, rel=_REL, abs=_ABS), (
            "the CRR CIU sheet's mandate-based row is unpopulated; rows 0281-0283 are "
            "declared in BOTH regimes and ciu_approach is sealed in both"
        )
        assert _cell(frame, "0281", "0220") is None
        assert _cell(frame, "0283", "0220") is None

    def test_the_crr_ciu_reaches_c_02_00_row_0200_and_c_09_01_row_0140(self) -> None:
        """The same two class maps, exercised on the CRR arm.

        ``C02_00_SA_CLASS_MAP`` and ``C09_01_SA_CLASS_MAP`` are shared by both
        regimes, so a CRR-only regression in either is unlikely — but "unlikely"
        is what made the CRR sheet axis dark for the whole of P1.371's life.
        """
        _results, corep, _pillar3 = _run("off-bs", "crr")

        assert _cell(corep.c_02_00, "0200", "0010") == pytest.approx(
            CIU_RWEA, rel=_REL, abs=_ABS
        ), "C 02.00 r0200 does not carry the CRR CIU RWEA"
        assert _cell(corep.c_02_00, "0210", "0010") == pytest.approx(0.0, abs=_ABS), (
            "C 02.00 r0210 ('Equity') carries a figure on a book whose only equity-table "
            "leg is a CIU — class (o) has leaked onto (p)"
        )
        total = corep.c09_01["TOTAL"]
        assert _cell(total, "0140", "0090") == pytest.approx(CIU_RWEA, rel=_REL, abs=_ABS)
        assert _cell(total, "0142", "0090") == pytest.approx(CIU_RWEA, rel=_REL, abs=_ABS)

    @pytest.mark.parametrize("row_ref", _RELEVANT_CIU_ROWS)
    def test_the_crr_sheet_declares_no_relevant_ciu_rows(self, row_ref: str) -> None:
        """Rows 0284 / 0285 are Basel-3.1-only — the one CIU row-axis difference.

        The regime difference in this block is the ROW AXIS and nothing else:
        ``get_sa_row_sections("CRR")`` declares 0281/0282/0283 and the Basel 3.1
        section interleaves 0284/0285 as of-which children. Asserting their
        ABSENCE under CRR is what stops a later "wire 0284/0285" change from
        quietly adding two rows to a CRR submission that has no such rows.
        """
        _results, corep, _pillar3 = _run("off-bs", "crr")

        frame = _sheet(corep, "crr", _Z_CODE_112_O)
        assert row_ref not in set(frame["row_ref"].to_list()), (
            f"C 07.00 declares row {row_ref} under CRR; the 'of which: exposures to "
            "relevant CIUs' rows exist only in the PS1/26 OF 07.00 layout"
        )


# ---------------------------------------------------------------------------
# 11. The CRR arm again, on a book this file builds itself
# ---------------------------------------------------------------------------


def _control_bundle() -> RawDataBundle:
    """One SA corporate loan plus one mandate-based CIU, sealed as the loader would.

    Built through ``tests.fixtures.raw_bundle.make_raw_bundle`` — the same sealing
    helper ``tests/properties/portfolios.py`` uses — rather than through
    ``props.build_bundle``, because ``ExposureSpec`` describes loans only and the
    equity input table has no representation in it. Every frame is sealed against
    its loader edge contract, so this is not a hand-shaped frame slipped past the
    input boundary.

    The loan is here so the book is not equity-only: a single-leg portfolio cannot
    show that the CIU opened its OWN sheet rather than the only sheet.
    """
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "P254-CP-CORP",
                "counterparty_name": "Control Corporate",
                "entity_type": "corporate",
                "country_code": "GB",
                "currency": "GBP",
                "annual_revenue": 200_000_000.0,
            },
            {
                "counterparty_reference": "P254-CP-FUND",
                "counterparty_name": "Control Fund Manager",
                "entity_type": "corporate",
                "country_code": "GB",
                "currency": "GBP",
                "annual_revenue": 200_000_000.0,
            },
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "exposure_reference": "P254-LN-CORP",
                "counterparty_reference": "P254-CP-CORP",
                "drawn_amount": _CONTROL_LOAN_EAD,
                "currency": "GBP",
                "value_date": date(2015, 1, 1),
                "maturity_date": date(2030, 1, 1),
                "product_type": "term_loan",
            }
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    equity = pl.DataFrame(
        [
            {
                "exposure_reference": _CONTROL_CIU_REF,
                "counterparty_reference": "P254-CP-FUND",
                "equity_type": "ciu",
                "currency": "GBP",
                "carrying_value": _CONTROL_CIU_EAD,
                "fair_value": _CONTROL_CIU_EAD,
                "ciu_approach": "mandate_based",
                "ciu_mandate_rw": _CONTROL_CIU_RW,
            }
        ],
        schema_overrides=dtypes_of(EQUITY_EXPOSURE_SCHEMA),
    )
    return make_raw_bundle(loans=loans, counterparties=counterparties, equity_exposures=equity)


@lru_cache(maxsize=1)
def _control_run() -> tuple[pl.DataFrame, COREPTemplateBundle, tuple[str, ...]]:
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
    )
    result = PipelineOrchestrator().run_with_data(_control_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework="CRR")
    return (
        result.results.collect(),
        corep,
        tuple(f"{error.error_code}: {error.message}" for error in result.errors),
    )


class TestTheCrrArmOnABookThisFileOwns:
    """The same CRR claim, on a portfolio no other test can re-scope out from under it.

    ``off-bs`` carries the registered CRR CIU leg and is the better control in
    every other respect — goldens, the supervisory register, the coverage census.
    This book exists because that leg is a FIXTURE decision: it was added to
    ``off-bs`` on the argument that the other four CRR SA-config portfolios each
    had a reason to refuse it, and a later re-scoping of that fixture would take
    the CRR arm of the both-regimes ruling with it silently. Here the inputs, the
    config and the expected figures are in one file, so the path is pinned
    independently of any registered portfolio.

    Kept deliberately small: it asserts the CRR (o) sheet exists and carries the
    right figures, and nothing that ``off-bs`` already covers in more detail.
    """

    def test_the_ciu_seals_class_o_under_a_crr_sa_config(self) -> None:
        results, _corep, errors = _control_run()

        assert not errors, (
            f"the control bundle did not load cleanly: {errors}. A hand-built bundle that "
            "trips the loader seal would make every figure below an artefact of the "
            "fixture rather than of the engine"
        )
        leg = results.filter(pl.col("source_exposure_reference") == _CONTROL_CIU_REF)
        assert leg.height == 1, f"the control CIU leg did not survive the pipeline: {leg.height}"
        assert leg["reporting_class_origin"][0] == ExposureClass.CIU.value
        assert leg["equity_method"][0] == "sa", (
            "PermissionMode.STANDARDISED must leave the CIU SA-method; otherwise "
            "c07.py::_equity_admission excludes it and this control tests nothing"
        )
        assert leg["rwa_final"][0] == pytest.approx(
            _CONTROL_CIU_EAD * _CONTROL_CIU_RW, rel=_REL, abs=_ABS
        )

    def test_the_crr_ciu_sheet_is_emitted_beside_the_corporate_sheet(self) -> None:
        """Two sheets, so the (o) sheet is its own and not merely the only one."""
        _results, corep, _errors = _control_run()

        sheet = _sheet_key("crr", _Z_CODE_112_O)
        assert set(corep.c07_00) == {sheet, ExposureClass.CORPORATE.value}, (
            f"C 07.00 opened {sorted(corep.c07_00)} under a CRR SA config; expected the "
            f"Article 112(1)(o) sheet beside the corporate one"
        )
        frame = corep.c07_00[sheet]
        assert _cell(frame, "0010", "0010") == pytest.approx(_CONTROL_CIU_EAD, rel=_REL, abs=_ABS)
        assert _cell(frame, "0010", "0220") == pytest.approx(
            _CONTROL_CIU_EAD * _CONTROL_CIU_RW, rel=_REL, abs=_ABS
        )
        assert _cell(frame, "0282", "0220") == pytest.approx(
            _CONTROL_CIU_EAD * _CONTROL_CIU_RW, rel=_REL, abs=_ABS
        ), "the mandate-based row is unpopulated on the CRR sheet"
        assert _cell(frame, "0281", "0220") is None
        assert _cell(frame, "0283", "0220") is None

    def test_the_crr_control_reaches_c_02_00_row_0200(self) -> None:
        _results, corep, _errors = _control_run()

        assert _cell(corep.c_02_00, "0200", "0010") == pytest.approx(
            _CONTROL_CIU_EAD * _CONTROL_CIU_RW, rel=_REL, abs=_ABS
        )
        assert _cell(corep.c_02_00, "0210", "0010") == pytest.approx(0.0, abs=_ABS), (
            "C 02.00 r0210 ('Equity') carries a figure on a book whose only equity-table "
            "leg is a CIU"
        )
