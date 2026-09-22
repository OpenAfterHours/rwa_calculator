"""
The Art. 112(1)(k) high-risk sheet is emitted under Basel 3.1 — and is addressable.

Pipeline position:
    high-risk obligor -> PipelineOrchestrator -> sealed ledger
        -> COREPGenerator -> COREPTemplateBundle.c07_00["high_risk"]
        -> validations/scope.py::resolve_sheet_codes("0012") -> the rules' coordinates

Why this file exists — the mechanism
------------------------------------
``SHEET_INDEX_MAPS['c07']`` and ``['of07']`` index the published C 07.00 /
OF 07.00 z-axis onto our sheet keys. An entry's ``bundle_keys`` being EMPTY is a
deliberate, documented state meaning "this code addresses nothing this project
models" — the Total sheet, or a regulatory class with no ``ExposureClass``
member. It is NOT a statement about a run or a regime.

z0012 (Art. 112(1)(k), particularly-high-risk items) carried that empty tuple
while ``high_risk`` is a legal ``ExposureClass`` member, a declared value of
``templates.C07_00_SA_SHEET_MAP``, and therefore a sheet key the C 07.00 builder
can emit. So ``resolve_sheet_codes(["0012"], ...)`` answered
``sheet_not_emitted`` — which is the SAME skip reason a declared-but-unexercised
code produces, and on a Basel 3.1 book holding a high-risk leg it is a FALSE
statement about observable state: the sheet is right there in the bundle.

The consequence is the one ``.claude/LESSONS.md`` B4 warns about. A skip is
``NOT_EVALUATED``, never a break, so the supervisory gate fails OPEN: the sheet
is absent from the coordinate grid of every live BoE rule scoped to z0012 and
those rules pass without having looked at it. Nothing anywhere reddens.

What each section proves, and which one would have caught the defect
-------------------------------------------------------------------
1. **The declared vocabulary** (no pipeline). Every sheet key the C 07.00 builder
   declares must be addressed by exactly one z-code. This is the limb that would
   have caught P2.55, and it is anchored on ``C07_00_SA_SHEET_KEYS`` — the
   builder's own vocabulary, maintained on the OTHER side of the boundary from
   ``scope.py`` — so it cannot be satisfied by a test written from the same
   sentence as the code under test (``LESSONS`` B3). The sibling direction
   (``bundle_keys`` ⊆ emittable) is already covered by
   ``tests/unit/reporting/validations/test_sheet_index_map.py``; the cardinality
   direction (at most one key per code) by
   ``tests/contracts/test_sheet_index_bundle_key_cardinality.py``. This file owns
   the COMPLETENESS direction, which neither checks.

2. **The distinction the defect is about** (no pipeline). An UNDECLARED code and
   a DECLARED-but-unexercised one are different states — a coverage hole versus a
   firm that simply holds none of that class — and ``resolve_sheet_codes``
   reports them under ONE skip reason. That conflation is why section 1 is the
   only available gate, and these tests pin it rather than assuming it.

3. **The Basel 3.1 book** (full pipeline). A high-risk obligor is classified
   ``high_risk``, emits a sheet carrying money, and that sheet resolves through
   z0012 into the coordinate grid of the live rules scoped to it.

4. **The CRR negative control** (full pipeline). Under CRR the class must NOT
   appear: Art. 128 was omitted from the onshored text by SI 2021/1078 and
   ``engine/classify/attributes.py`` demotes the class to ``other`` whenever the
   pack Feature ``b31_high_risk_class_applicable`` is off. Without this, the
   Basel 3.1 assertions above would be satisfied by an implementation that
   ignored the regime entirely.

Route note: this closes the gap WITHOUT a registered reporting portfolio. The
``tests/properties/portfolios.py`` helpers drive the real
``PipelineOrchestrator`` and the real ``COREPGenerator``, so the classifier ->
seal -> sheet-axis -> z-axis path is genuinely end to end, and
``resolve_sheet_codes`` is the same function the supervisory evaluator calls.

What registering a high-risk leg in ``tests/acceptance/reporting``'s ``RUNS``
would and would not add, measured rather than assumed. It would NOT add a
supervisory break: against the same portfolio with the high-risk obligor swapped
for a second corporate, the break set is identical (Basel 3.1 ``boe_b0703`` /
``boe_b0710`` / ``boe_b0778``, CRR ``v09796_m``) and only the executed count
moves, 173 -> 179 under Basel 3.1 and 110 -> 115 under CRR. What it WOULD do is
bank the P3.7 Pillar 3 stranding — a ``high_risk`` leg reaches no CR4/CR5 class
row, so 4,000,000 of exposure and 6,000,000 of RWEA break both templates' footing
identities — into the GOLDEN layer, where it is currently held as a strict xfail
(``tests/properties/test_template_row_axis.py::test_high_risk_leg_reaches_a_pillar3_class_row``).
Not into the register: no rule in either published extract addresses a Pillar 3
template (``scope.py::build_template_index``). That, plus a new golden directory
and a re-measured cell-coverage baseline, is a decision belonging with P3.7 rather
than with this addressability fix.

References:
- CRR Art. 112(1)(k) / PS1/26 Art. 112(1)(k), Art. 128 — particularly high risk
- SI 2021/1078 reg. 6(3)(a) — Art. 128 omitted from onshored UK CRR
- COREP Annex II C 07.00 z0012; PS1/26 Annex II OF 09.01 row 0110
- IMPLEMENTATION_PLAN.md P2.55 (and P3.7, the Pillar 3 half)
- ``.claude/LESSONS.md`` B3 / B4 / B9 / C2 / C11
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Final

import polars as pl
import pytest
from tests.properties.portfolios import ExposureSpec, corep_bundle, pillar3_bundle, results_df

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.corep.templates import C07_00_SA_SHEET_KEYS, C07_00_SA_SHEET_MAP
from rwa_calc.reporting.validations.evaluate import UnsupportedExpression, parse_expression
from rwa_calc.reporting.validations.rules import SCOPE_LIST, load_rules
from rwa_calc.reporting.validations.scope import (
    SHEET_INDEX_MAPS,
    SKIP_SHEET_NOT_EMITTED,
    build_template_index,
    expand_rule,
    resolve_sheet_codes,
)
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.validations.scope import SheetCode

# =============================================================================
# Subjects, all read from the module or pack that owns them
# =============================================================================

#: The publisher's z-code for Art. 112(1)(k). One string, used by every limb.
Z_HIGH_RISK: Final = "0012"

#: Our sheet key for it. Taken from the enum, never typed as a literal — a
#: class/row map keyed on an invented string zero-fills silently (``LESSONS`` B2).
HIGH_RISK_SHEET_KEY: Final = ExposureClass.HIGH_RISK.value

#: The two sheet maps that index the Art. 112(1) class list. The C 08.xx maps
#: index the FINER Art. 147(2) IRB axis and deliberately address only a subset of
#: the engine's classes, so the completeness property below is not stated over
#: them — it is a property of the SA axis, where our sheet keys and the
#: publisher's letters are in 1:1 correspondence by construction.
SA_MAP_NAMES: Final = ("c07", "of07")

#: regime label (``tests.properties.portfolios``) -> (framework, sheet map name).
REGIME_MAPS: Final[dict[str, tuple[str, str]]] = {
    "CRR": ("CRR", "c07"),
    "B31": ("BASEL_3_1", "of07"),
}

#: The publisher's table-code prefix for the CR SA template, per framework. Used
#: only to narrow a rule-scope search; the DPM variants (``C 07.00.a``..``.d``,
#: ``OF07.00.01.01``..``.05``) are row/column partitions of one template.
CR_SA_TABLE_PREFIXES: Final[dict[str, str]] = {"CRR": "C 07.00", "BASEL_3_1": "OF07.00"}

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

#: Art. 128's flat risk weight, single-sourced for both regimes in the common
#: pack. Read here rather than typed, so this file cannot drift from the engine.
HIGH_RISK_RW: Final[Decimal] = _B31_PACK.scalar_param("high_risk_rw").value

#: The portfolio. One high-risk obligor plus a corporate anchor, so the C 07.00
#: axis holds more than the single sheet under test and the footing identity in
#: ``test_the_sheet_totals_sum_to_the_standardised_exposure_value`` is a real sum.
#: Structurally identical to ``tests/properties/test_template_row_axis.py``'s
#: ``HIGH_RISK_OBLIGOR``, and ``ExposureSpec`` is frozen, so both files share one
#: ``lru_cache`` entry per regime rather than running the pipeline twice.
HIGH_RISK_OBLIGOR: Final[tuple[ExposureSpec, ...]] = (
    ExposureSpec(entity_type="high_risk", drawn=4_000_000.0, external_cqs=None),
    ExposureSpec(entity_type="corporate", drawn=5_000_000.0, external_cqs=3),
)

#: The high-risk leg's drawn amount, and the RWEA it must carry under Art. 128.
HIGH_RISK_EAD: Final = 4_000_000.00
HIGH_RISK_RWEA_B31: Final = float(Decimal("4000000.00") * HIGH_RISK_RW)

#: The corporate anchor's drawn amount; the C 07.00 exposure-value total is the
#: two together, both legs being fully drawn with no CRM and no provisions.
CORPORATE_EAD: Final = 5_000_000.00

#: Row 0010 is "Total exposures"; columns 0010 / 0200 / 0220 are original
#: exposure pre-conversion, exposure value, and risk-weighted exposure amount.
TOTAL_ROW: Final = "0010"
COL_ORIGINAL_EXPOSURE: Final = "0010"
COL_EXPOSURE_VALUE: Final = "0200"
COL_RWEA: Final = "0220"

MONEY_TOLERANCE: Final = 0.005


# =============================================================================
# Helpers
# =============================================================================


def _addressable(sheet_map: Mapping[str, SheetCode]) -> set[str]:
    """Every sheet key any z-code in ``sheet_map`` can resolve to."""
    return {key for entry in sheet_map.values() for key in entry.bundle_keys}


def _homes(sheet_map: Mapping[str, SheetCode]) -> dict[str, list[str]]:
    """``{our sheet key: [the z-codes that address it]}``, for declared keys only."""
    homes: dict[str, list[str]] = {key: [] for key in C07_00_SA_SHEET_KEYS}
    for code, entry in sheet_map.items():
        for key in entry.bundle_keys:
            if key in homes:
                homes[key].append(code)
    return homes


def _without_high_risk(sheet_map: Mapping[str, SheetCode]) -> dict[str, SheetCode]:
    """``sheet_map`` with z0012's ``bundle_keys`` emptied — the pre-fix declaration.

    The state this file exists to forbid, built by patching a COPY so no test can
    leak it into another. Used only by section 2, which is about what
    ``resolve_sheet_codes`` DOES with each state; the live map is held to the
    right state by section 1.
    """
    patched = dict(sheet_map)
    patched[Z_HIGH_RISK] = replace(patched[Z_HIGH_RISK], bundle_keys=())
    return patched


@lru_cache(maxsize=len(REGIME_MAPS))
def _sheet_keys(regime: str) -> tuple[str, ...]:
    """The C 07.00 sheet keys the run for ``regime`` actually emitted."""
    return tuple(sorted(corep_bundle(HIGH_RISK_OBLIGOR, regime).c07_00 or {}))


def _sealed_classes(regime: str) -> set[str]:
    """The distinct sealed ``exposure_class`` values the run produced."""
    frame = results_df(HIGH_RISK_OBLIGOR, regime)
    return {value for value in frame["exposure_class"].to_list() if value is not None}


def _leg_figures(regime: str, exposure_class: str) -> tuple[float, float, float]:
    """``(ead, rwea, max risk weight)`` for one sealed class in one regime."""
    frame = results_df(HIGH_RISK_OBLIGOR, regime).filter(pl.col("exposure_class") == exposure_class)
    return (
        float(frame["ead_final"].fill_null(0.0).sum()),
        float(frame["rwa_final"].fill_null(0.0).sum()),
        float(frame["risk_weight"].max() or 0.0),
    )


def _total_row_cell(regime: str, sheet_key: str, column: str) -> float | None:
    """One cell of row 0010 on one emitted sheet, ``None`` preserved as NULL."""
    frame = corep_bundle(HIGH_RISK_OBLIGOR, regime).c07_00[sheet_key]
    row = frame.filter(pl.col("row_ref") == TOTAL_ROW)
    if row.height == 0 or column not in row.columns:
        return None
    value = row[column][0]
    return None if value is None else float(value)


@lru_cache(maxsize=len(REGIME_MAPS))
def _rules_scoped_to_high_risk(framework: str) -> tuple[str, ...]:
    """Enforced rule ids whose CR SA sheet scope LISTS z0012.

    Enumerated from the loaded extract by scope, never from a quoted list of
    members — a family addressed by the two ids someone happened to name is
    ``.claude/LESSONS.md`` C6. Restricted to the CR SA template by the
    publisher's own table-code prefix: the same z-code means something entirely
    different on the Art. 147(2) IRB axis (``_C08_SHEETS`` z0012 is corporates
    A-IRB), so counting those would inflate the population with rules this sheet
    key could never reach.
    """
    prefixes = CR_SA_TABLE_PREFIXES[framework]
    found: list[str] = []
    for rule in load_rules(framework).enforced:
        for table_scope in rule.table_scopes:
            if not table_scope.table.startswith(prefixes):
                continue
            if table_scope.sheets.kind == SCOPE_LIST and Z_HIGH_RISK in table_scope.sheets.ids:
                found.append(rule.rule_id)
                break
    return tuple(sorted(found))


def _high_risk_coordinate_count(regime: str) -> tuple[int, int]:
    """``(cells, rules)`` the z0012-SCOPED rules address on the ``high_risk`` sheet.

    Expanded exactly as ``checker.py::_evaluate_rule`` does — parse the
    expression, then ``expand_rule`` with the axis flags it derived — so this
    counts the cells the supervisory gate would really visit rather than a
    reconstruction of them.

    Restricted to the rules whose sheet axis LISTS z0012, and that restriction is
    load-bearing rather than tidiness. A rule with an unscoped or ``(All)`` sheet
    axis iterates every EMITTED sheet (``_resolve_sheet_axis``), so it reaches the
    ``high_risk`` sheet whatever the z-axis map says — counting those made this
    measurement pass under the pre-fix declaration, which is
    ``.claude/LESSONS.md`` C12 mechanism 4: the probe agreed in both states
    because the population measured was not the one the defect silences.
    """
    framework, _map_name = REGIME_MAPS[regime]
    scoped = set(_rules_scoped_to_high_risk(framework))
    index = build_template_index(
        corep_bundle(HIGH_RISK_OBLIGOR, regime),
        pillar3_bundle(HIGH_RISK_OBLIGOR, regime),
        framework,
    )
    cells = 0
    rules = 0
    for rule in load_rules(framework).enforced:
        if rule.rule_id not in scoped or rule.precondition or rule.where:
            continue
        try:
            expression = parse_expression(rule.expression)
        except UnsupportedExpression:
            continue
        expansion = expand_rule(
            rule,
            index,
            needs_row_axis=expression.needs_row_axis,
            needs_column_axis=expression.needs_column_axis,
            needs_sheet_axis=expression.needs_sheet_axis,
        )
        on_sheet = sum(
            1
            for coordinate in expansion.coordinates
            if coordinate.sheet == HIGH_RISK_SHEET_KEY and not coordinate.sheet_is_representative
        )
        cells += on_sheet
        rules += 1 if on_sheet else 0
    return cells, rules


# =============================================================================
# 1. The declared vocabulary — the limb that would have caught this
# =============================================================================


class TestDeclaredVocabularyIsAddressable:
    """Every sheet key the C 07.00 builder declares has exactly one z-code."""

    def test_the_builder_still_declares_a_high_risk_sheet_key(self) -> None:
        """``LESSONS`` C11 — adequacy, before anything is asserted about z0012.

        If ``C07_00_SA_SHEET_MAP`` stopped declaring ``high_risk`` the assertions
        below would hold vacuously, and this whole file would pass while saying
        nothing. The subject has to be asserted present, not assumed.
        """
        assert HIGH_RISK_SHEET_KEY in C07_00_SA_SHEET_MAP, (
            f"{HIGH_RISK_SHEET_KEY!r} is no longer a C07_00_SA_SHEET_MAP key, so the "
            "C 07.00 builder declares no high-risk class and this file's subject is gone"
        )
        assert HIGH_RISK_SHEET_KEY in C07_00_SA_SHEET_KEYS, (
            f"{HIGH_RISK_SHEET_KEY!r} maps onto another Art. 112(1) letter's sheet key, "
            "so it is no longer a sheet of its own and z0012 addresses something else"
        )

    @pytest.mark.parametrize("map_name", SA_MAP_NAMES)
    def test_every_declared_sheet_key_is_addressable_by_the_published_z_axis(
        self, map_name: str
    ) -> None:
        """THE defect, stated positively and over the live map.

        A sheet key no ``SheetCode.bundle_keys`` names is unreachable: every
        published rule scoped to its z-code scores ``NOT_EVALUATED``, the
        supervisory gate fails OPEN, and the loss of coverage is invisible to the
        break ratchet because a skip is never a break.

        Anchored on ``C07_00_SA_SHEET_KEYS`` — the set of sheet keys
        ``corep/templates.py`` declares the builder can produce — which is
        maintained on the other side of this boundary from ``scope.py``. A
        hand-written list here would share production's assumption and prove
        nothing (``LESSONS`` B3).
        """
        # Arrange
        sheet_map = SHEET_INDEX_MAPS[map_name]

        # Act
        unaddressable = sorted(C07_00_SA_SHEET_KEYS - _addressable(sheet_map))

        # Assert
        assert unaddressable == [], (
            f"SHEET_INDEX_MAPS[{map_name!r}] names no z-code for sheet key(s) "
            f"{unaddressable}, which C07_00_SA_SHEET_MAP declares the C 07.00 builder "
            "can emit — every published rule scoped to their code silently scores "
            "NOT_EVALUATED the moment a portfolio carries one"
        )

    @pytest.mark.parametrize("map_name", SA_MAP_NAMES)
    def test_no_declared_sheet_key_is_addressed_by_two_z_codes(self, map_name: str) -> None:
        """The boundary on the fix above, not a detector for the defect.

        NOT A DETECTOR of P2.55 — it holds in both states. It exists so the
        completeness assertion cannot be satisfied the wrong way: declaring
        ``high_risk`` on a SECOND code as well would make the key addressable and
        put our sheet inside two different Art. 112(1) letters, which
        ``resolve_sheet_codes`` would then refuse as ``sheet_scope_not_closed``
        for every rule scoping only one of them. On the SA axis each of our sheet
        keys is one Art. 112(1) letter, so exactly one code may name it. (The
        converse shape — several z-codes onto one key — is legal on the finer IRB
        axis and is pinned in
        ``tests/contracts/test_sheet_index_bundle_key_cardinality.py``.)
        """
        # Arrange
        sheet_map = SHEET_INDEX_MAPS[map_name]

        # Act
        shared = {key: codes for key, codes in _homes(sheet_map).items() if len(codes) > 1}

        # Assert
        assert shared == {}, (
            f"SHEET_INDEX_MAPS[{map_name!r}] addresses one of our sheets from more than "
            f"one Art. 112(1) z-code: {shared}"
        )


# =============================================================================
# 2. Undeclared and unexercised are different states, under one skip reason
# =============================================================================


class TestUndeclaredIsNotUnexercised:
    """``resolve_sheet_codes`` under each state, with no pipeline run.

    The "undeclared" arm is a patched COPY; the "declared" arm is the LIVE map, so
    two of these three tests are detectors as well as specifications — they redden
    under the pre-fix declaration because the live map then supplies the wrong arm
    of the comparison. Measured on the pre-fix map: this class goes 2 red / 1
    green, the green one being the conflation test, which is green by design.

    Without this section, "z0012 has a key" reads as a tidiness rule rather than
    as the difference between a hole in our own z-axis and a firm that simply
    holds none of the class.
    """

    def test_the_patched_copy_really_differs_from_the_live_map(self) -> None:
        """``LESSONS`` C11 / C12 — prove the mutation applied before citing it.

        If ``_without_high_risk`` returned something equal to the live map, every
        comparison below would be comparing one state with itself and would pass
        by construction. Reading the live map makes this an adequacy guard that
        doubles as a detector: under the pre-fix declaration there is nothing left
        to patch and it fails on its own terms, naming the state the tree is in.
        """
        live = SHEET_INDEX_MAPS["of07"]
        patched = _without_high_risk(live)

        assert live[Z_HIGH_RISK].bundle_keys != patched[Z_HIGH_RISK].bundle_keys, (
            "the patched copy carries the same bundle_keys as the live map, so the "
            "undeclared state is not being exercised at all"
        )
        assert patched[Z_HIGH_RISK].bundle_keys == ()
        assert {code for code in live if code != Z_HIGH_RISK} == {
            code for code in patched if code != Z_HIGH_RISK
        }, "the patch changed more than z0012, so any difference below is confounded"

    def test_both_states_skip_under_the_same_reason_code(self) -> None:
        """The conflation, pinned. ``LESSONS`` B4.

        NOT A DETECTOR — green in both states by design. ``sheet_not_emitted``
        answers "no exposure in that class" and "no key was ever declared"
        identically, so no consumer of the reason code can tell a firm that holds
        none of the class from a hole in our own z-axis. That is precisely why the
        structural assertion in section 1 is the only available gate, and it is
        worth asserting rather than assuming: if a future reason code DID
        distinguish them, this test reddens and section 1 can lean on it.
        """
        # Arrange — an emitted set without the sheet: the unexercised case
        live = SHEET_INDEX_MAPS["of07"]
        emitted = ("corporate", "other")
        assert HIGH_RISK_SHEET_KEY not in emitted, "the fixture cannot express 'unexercised'"

        # Act
        declared = resolve_sheet_codes([Z_HIGH_RISK], live, emitted)
        undeclared = resolve_sheet_codes([Z_HIGH_RISK], _without_high_risk(live), emitted)

        # Assert
        assert declared.skip_reason == SKIP_SHEET_NOT_EMITTED
        assert undeclared.skip_reason == SKIP_SHEET_NOT_EMITTED
        assert declared.sheets == () and undeclared.sheets == ()

    def test_only_the_declared_state_names_the_sheet_of_ours_that_is_missing(self) -> None:
        """The one field that does carry the difference.

        A declared code reports the BUNDLE KEY it could not find — "we have a
        sheet for this letter; this run produced none". An undeclared one can only
        quote the regulation's own label, because it claims to address nothing of
        ours. Same reason code, materially different claim, and the detail is
        where a reader can see which one they are looking at.
        """
        # Arrange
        live = SHEET_INDEX_MAPS["of07"]
        emitted = ("corporate",)

        # Act
        declared = resolve_sheet_codes([Z_HIGH_RISK], live, emitted)
        undeclared = resolve_sheet_codes([Z_HIGH_RISK], _without_high_risk(live), emitted)

        # Assert
        assert HIGH_RISK_SHEET_KEY in declared.detail, (
            f"a declared z0012 skip does not name our sheet key: {declared.detail!r}"
        )
        assert HIGH_RISK_SHEET_KEY not in undeclared.detail, (
            "an undeclared z0012 skip names a sheet key, so the two states are no "
            f"longer distinguishable by the detail either: {undeclared.detail!r}"
        )
        assert undeclared.detail == live[Z_HIGH_RISK].label


# =============================================================================
# 3. The Basel 3.1 book — the class is reachable and the sheet is addressable
# =============================================================================


class TestBasel31HighRiskLegIsAddressable:
    """A real Basel 3.1 run through the real orchestrator and COREP generator."""

    def test_the_obligor_is_classified_high_risk_and_not_demoted(self) -> None:
        """PS1/26 Art. 128 re-introduces the class, so the seal must keep it.

        Asserted as absolute figures, never relative to the CRR arm: two tests
        compared against a baseline once let a 48% RWA movement through green
        (``LESSONS`` C1).
        """
        # Arrange / Act
        classes = _sealed_classes("B31")
        ead, rwea, risk_weight = _leg_figures("B31", HIGH_RISK_SHEET_KEY)

        # Assert
        assert HIGH_RISK_SHEET_KEY in classes, (
            f"the high-risk obligor sealed as {sorted(classes)} under Basel 3.1 — the "
            "Art. 128 class was demoted in the regime that re-introduces it"
        )
        assert ead == pytest.approx(HIGH_RISK_EAD, abs=MONEY_TOLERANCE)
        assert risk_weight == pytest.approx(float(HIGH_RISK_RW))
        assert rwea == pytest.approx(HIGH_RISK_RWEA_B31, abs=MONEY_TOLERANCE)

    def test_a_high_risk_c07_sheet_is_emitted_and_carries_money(self) -> None:
        """``LESSONS`` B4 — absence is this estate's dominant escape class.

        Three separate claims: the sheet key is emitted at all; its total row
        exists; and the cells that must carry money are NON-NULL. A null and a
        legitimate zero are different claims, and only the published value
        distinguishes them.
        """
        # Arrange / Act
        emitted = _sheet_keys("B31")

        # Assert
        assert HIGH_RISK_SHEET_KEY in emitted, (
            f"no high-risk C 07.00 sheet was emitted; the axis holds {list(emitted)}"
        )
        original = _total_row_cell("B31", HIGH_RISK_SHEET_KEY, COL_ORIGINAL_EXPOSURE)
        exposure = _total_row_cell("B31", HIGH_RISK_SHEET_KEY, COL_EXPOSURE_VALUE)
        rwea = _total_row_cell("B31", HIGH_RISK_SHEET_KEY, COL_RWEA)
        assert original is not None, "row 0010 col 0010 (original exposure) is NULL"
        assert exposure is not None, "row 0010 col 0200 (exposure value) is NULL"
        assert rwea is not None, "row 0010 col 0220 (RWEA) is NULL"
        assert original == pytest.approx(HIGH_RISK_EAD, abs=MONEY_TOLERANCE)
        assert exposure == pytest.approx(HIGH_RISK_EAD, abs=MONEY_TOLERANCE)
        assert rwea == pytest.approx(HIGH_RISK_RWEA_B31, abs=MONEY_TOLERANCE)

    def test_the_sheet_totals_sum_to_the_standardised_exposure_value(self) -> None:
        """The breakdown foots to its parent, so the new sheet is part of a whole.

        A sheet set that silently drops a class still looks plausible on its own
        face, so the conservation identity is stated over the WHOLE axis rather
        than over the high-risk sheet alone.
        """
        # Arrange
        frame = results_df(HIGH_RISK_OBLIGOR, "B31")
        expected = float(
            frame.filter(pl.col("reporting_approach") == "standardised")["ead_final"]
            .fill_null(0.0)
            .sum()
        )
        assert expected == pytest.approx(HIGH_RISK_EAD + CORPORATE_EAD, abs=MONEY_TOLERANCE)

        # Act
        published = sum(
            _total_row_cell("B31", key, COL_EXPOSURE_VALUE) or 0.0 for key in _sheet_keys("B31")
        )

        # Assert
        assert published == pytest.approx(expected, abs=MONEY_TOLERANCE), (
            f"{expected - published:,.2f} of standardised exposure value reaches no "
            "C 07.00 sheet under Basel 3.1"
        )

    def test_the_emitted_sheet_resolves_through_z0012(self) -> None:
        """The addressability claim, against the real emitted sheet set.

        Two limbs of one concept. The code must resolve to our sheet — and it must
        not answer ``sheet_not_emitted`` about a sheet that IS emitted, which is
        not merely an uninformative skip but a false statement about observable
        state.
        """
        # Arrange
        emitted = _sheet_keys("B31")
        assert HIGH_RISK_SHEET_KEY in emitted, "nothing emitted the sheet; see the test above"

        # Act
        resolution = resolve_sheet_codes([Z_HIGH_RISK], SHEET_INDEX_MAPS["of07"], emitted)

        # Assert
        assert resolution.skip_reason is None, (
            f"z0012 resolved to {resolution.skip_reason!r} ({resolution.detail!r}) while the "
            f"{HIGH_RISK_SHEET_KEY!r} sheet is in the bundle — every published rule scoped "
            "to the code scores NOT_EVALUATED and the supervisory gate fails open"
        )
        assert resolution.sheets == (HIGH_RISK_SHEET_KEY,)

    def test_the_sheet_enters_the_coordinate_grid_of_the_rules_scoped_to_z0012(self) -> None:
        """The payoff, measured in cells the supervisory gate would really visit.

        Addressability is only worth anything if it puts the sheet in front of the
        rules. The rule population is enumerated from the loaded extract by scope
        (``LESSONS`` C6 — never by the members someone quoted), asserted non-empty
        so the count below cannot be vacuous, and the coordinates are expanded
        through the same ``parse_expression`` + ``expand_rule`` pair
        ``checker.py`` uses.
        """
        # Arrange
        scoped = _rules_scoped_to_high_risk("BASEL_3_1")
        assert scoped, (
            "no enforced Basel 3.1 rule lists z0012 on an OF 07.00 table, so this test "
            "cannot show the fix buys any coverage"
        )

        # Act
        cells, rules = _high_risk_coordinate_count("B31")

        # Assert
        assert cells > 0, (
            f"{len(scoped)} enforced rule(s) list z0012 ({', '.join(scoped[:5])}, ...) and not "
            f"one addresses a single cell of the emitted {HIGH_RISK_SHEET_KEY!r} sheet — they "
            "pass without having looked at it"
        )
        assert rules > 0


# =============================================================================
# 4. The CRR negative control — the class must NOT appear
# =============================================================================


class TestCrrDemotesTheClass:
    """Under CRR the demotion to ``other`` is correct behaviour, not a bug.

    Without this section the Basel 3.1 assertions above would be satisfied by an
    implementation that ignored the regime entirely.
    """

    def test_the_pack_feature_disagrees_between_the_regimes(self) -> None:
        """``LESSONS`` C11 / C7 — the control's premise, asserted not assumed.

        Both arms of this file rest on one cited pack Feature. If it were enabled
        under CRR the demotion would not happen and the control below would be
        asserting the Basel 3.1 behaviour twice.
        """
        assert _B31_PACK.feature("b31_high_risk_class_applicable") is True
        assert _CRR_PACK.feature("b31_high_risk_class_applicable") is False, (
            "Art. 128 is enabled under CRR, but SI 2021/1078 reg. 6(3)(a) omitted it "
            "from the onshored text — the CRR control below is now vacuous"
        )

    def test_the_obligor_demotes_to_other_and_no_high_risk_sheet_is_emitted(self) -> None:
        """The class is absent, and the money moved rather than vanishing.

        Both halves matter. A future change re-introducing ``high_risk`` under CRR
        fails the first; one that dropped the leg instead of demoting it fails the
        second, and that failure is the silent kind — the C 07.00 axis would look
        entirely plausible without it.
        """
        # Arrange / Act
        classes = _sealed_classes("CRR")
        emitted = _sheet_keys("CRR")
        ead, _rwea, _rw = _leg_figures("CRR", ExposureClass.OTHER.value)

        # Assert
        assert HIGH_RISK_SHEET_KEY not in classes, (
            f"the sealed classes {sorted(classes)} include {HIGH_RISK_SHEET_KEY!r} under "
            "CRR, where SI 2021/1078 omitted Art. 128 — the demotion in "
            "engine/classify/attributes.py has stopped firing"
        )
        assert HIGH_RISK_SHEET_KEY not in emitted, (
            f"a high-risk C 07.00 sheet was emitted under CRR; the axis holds {list(emitted)}"
        )
        assert ead == pytest.approx(HIGH_RISK_EAD, abs=MONEY_TOLERANCE), (
            "the demoted leg's exposure is not on the 'other' class — it was dropped "
            "rather than reclassified"
        )

    def test_the_regime_difference_is_large_enough_to_discriminate(self) -> None:
        """``LESSONS`` C2 — measure the crossing amount before trusting a control.

        The CRR arm only proves anything if the two regimes produce materially
        different capital for the identical leg. Art. 128's 150% against the
        Art. 112(1)(q) residual 100% is that difference; were the two weights
        equal, a regime-blind implementation would satisfy both arms.
        """
        # Arrange / Act
        _b31_ead, b31_rwea, b31_rw = _leg_figures("B31", HIGH_RISK_SHEET_KEY)
        _crr_ead, crr_rwea, crr_rw = _leg_figures("CRR", ExposureClass.OTHER.value)

        # Assert
        assert b31_rw != crr_rw, (
            f"both regimes weight the leg at {b31_rw} — the class difference carries no "
            "capital and neither arm of this file can distinguish them"
        )
        assert b31_rwea - crr_rwea == pytest.approx(
            HIGH_RISK_RWEA_B31 - HIGH_RISK_EAD * crr_rw, abs=MONEY_TOLERANCE
        )
        assert abs(b31_rwea - crr_rwea) > MONEY_TOLERANCE

    def test_z0012_skips_naming_our_sheet_rather_than_the_regulations_label(self) -> None:
        """The declared-but-unexercised state, on the live map and a real run.

        This is the CRR half of the distinction section 2 specifies. The skip is
        correct here — the firm holds none of the class in this regime — and what
        the fix changes is the claim behind it: z0012 now reports that OUR
        ``high_risk`` sheet was not produced, rather than that the code addresses
        nothing of ours.
        """
        # Arrange
        emitted = _sheet_keys("CRR")
        assert HIGH_RISK_SHEET_KEY not in emitted, "the CRR run emitted the sheet; see above"

        # Act
        resolution = resolve_sheet_codes([Z_HIGH_RISK], SHEET_INDEX_MAPS["c07"], emitted)

        # Assert
        assert resolution.skip_reason == SKIP_SHEET_NOT_EMITTED
        assert resolution.detail == HIGH_RISK_SHEET_KEY, (
            f"z0012 skipped citing {resolution.detail!r} instead of our sheet key — a "
            "skip that quotes the regulation's label claims the code addresses nothing "
            "of ours, which is the state that makes an emitted sheet unreachable"
        )
