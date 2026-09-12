"""
P1.373 — the two CRR supporting-factor "(-)" columns must describe DISJOINT rows.

Pipeline position:
    build_reporting_bundle() -> PipelineOrchestrator -> COREPGenerator
        -> {C 07.00, C 08.01, C 08.02, C 09.01, C 09.02}

The defect. Five COREP templates carry the same RWEA block — pre-supporting-
factor RWEA, an Art. 501 "(-)" SME adjustment, an Art. 501a "(-)" infrastructure
adjustment, post-supporting-factor RWEA — fed by one ``_sf_adjustment_cell``
shape written out three times: ``reporting/corep/c07.py``, ``c08.py`` (whose
``_value_cells`` serves BOTH C 08.01 and C 08.02) and ``c09.py`` (twice, once
per geographical template). Every one of them predicated the SME column on
``is_sme AND supporting_factor_applied`` and the infrastructure column on
``is_infrastructure AND supporting_factor_applied``.

The engine grants ONE relief. ``engine/supporting_factors.py::apply_factors``
emits ``supporting_factor = min_horizontal(sme_factor, infra_factor)`` and a
single generic ``supporting_factor_applied`` — there is no per-factor applied
flag on the sealed ledger. So a row eligible for both had its single relief
counted in BOTH columns, and the published footing identity
``0215 + 0216 + 0217 = 0220`` (EBA ``v09747_m``, and its C 08.01/02 and
C 09.01/02 siblings) broke by exactly the overlap row's relief.

Which column the whole relief belongs to. On a row eligible for both, the
infrastructure factor always wins the minimum — measured on this estate, the SME
blend lands at 0.7619 on the SA leg and 0.84038 on the A-IRB leg against a flat
Art. 501a 0.75 — so the relief is attributable to Art. 501a alone and the SME
column must report nothing for that row.

What each class here can and cannot see, stated per LESSONS C10 rather than
quantified over all five templates:

- ``TestTheReliefIsPartitioned`` is the assertion that discriminates on ALL
  FIVE templates independently, and it needs no amounts: the two columns must
  each claim strictly less than the row's total relief and together claim
  exactly it. Pre-fix they jointly claim MORE than the engine granted.
- ``TestThePopulationsDiverge`` is the same guard read off the output SHAPE —
  the two columns are no longer live on one row set. It discriminates on
  C 07.00, the only template with an infrastructure-specific of-which row
  (0035); on C 08.01/02 and C 09.01/02 both columns are live on the same rows
  in either state, so the partition class above is what covers them.
- ``TestTheAttributedAmounts`` pins the absolute figures, because an
  implementation that zeroed the SME column entirely would satisfy the
  partition identity (LESSONS B5's two-leg rule: the estate keeps a SURVIVING
  SME-only contributor on every template so "attribution corrected" is
  distinguishable from "cell zeroed").

Column references are DERIVED from the template declarations by their Annex II
labels rather than transcribed from the reporting code, so a test that shared
the implementation's assumption about which ref is which cannot arise
(LESSONS B3).

References:
- CRR Art. 501 (SME supporting factor), Art. 501a (infrastructure)
- COREP Annex II: C 07.00 cols 0215-0217/0220, C 08.01/02 cols 0255-0257/0260,
  C 09.01 cols 0080-0082/0090, C 09.02 cols 0110/0121/0122/0125
- EBA ``v09747_m`` / ``v0329_m`` (C 07.00), ``v0341_m`` / ``v0348_m``
  (C 08.01/02), ``v0407_m`` (C 09.01), ``v4785_m`` (C 09.02)
- ``src/rwa_calc/reporting/corep/supporting_factors.py`` (the shared resolution)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.reporting_portfolio import (
    LN_AIRB,
    LN_AIRB_INFRA,
    LN_SME,
    LN_SME_INFRA,
    build_reporting_bundle,
)

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    COREPColumn,
    get_c07_columns,
    get_c08_02_columns,
    get_c08_columns,
    get_c09_01_columns,
    get_c09_02_columns,
)

# Phase 2 parity convention: group-by float sums are not bit-reproducible.
_REL = 1e-9
_ABS = 1e-6

#: The Annex II column names the four RWEA blocks share. Matching on the label
#: is what lets this file enumerate the refs from the template declaration
#: instead of from ``corep/c07.py`` — the code under test.
_LBL_PRE = "RWEA pre supporting factors"
_LBL_SME = "(-) SME supporting factor adjustment"
_LBL_INFRA = "(-) Infrastructure supporting factor adjustment"
_LBL_POST = "RWEA after supporting factors"

#: The two overlap legs (SME AND infrastructure) and the two SME-ONLY legs that
#: survive beside them, one pair per approach. ``reporting_portfolio.py``
#: documents why they are four separate exposures and not two.
_SA_OVERLAP, _SA_SME_ONLY = LN_SME_INFRA, LN_SME
_IRB_OVERLAP, _IRB_SME_ONLY = LN_AIRB_INFRA, LN_AIRB

#: Both overlap legs and both SME-only legs, for the relief lookup.
_BOTH_LEGS: tuple[str, ...] = (_SA_OVERLAP, _SA_SME_ONLY, _IRB_OVERLAP, _IRB_SME_ONLY)


@dataclass(frozen=True)
class _Block:
    """One template's supporting-factor RWEA block, resolved against a run."""

    label: str
    sheets: dict[str, pl.DataFrame]
    pre: str
    sme: str
    infra: str
    post: str
    #: The sheet the SME/infrastructure legs land on, its whole-population row,
    #: and the exposures behind its two "(-)" columns.
    home_sheet: str
    total_row: str
    sme_leg: str
    infra_leg: str

    def cell(self, sheet: str, row_ref: str, column: str) -> float | None:
        frame = self.sheets[sheet]
        matched = frame.filter(pl.col("row_ref") == row_ref)
        assert matched.height == 1, (
            f"{self.label}/{sheet}: expected exactly one row {row_ref!r}, got {matched.height}"
        )
        return matched[column][0]

    def rows(self, sheet: str) -> list[str]:
        return self.sheets[sheet]["row_ref"].to_list()


# =============================================================================
# The run
# =============================================================================


@lru_cache(maxsize=2)
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """The golden reporting estate under one regime, memoised.

    Uses ``test_reporting_golden``'s own config factories so this file cannot
    drift onto a different estate than the goldens and the supervisory register
    describe.
    """
    config = _crr_config() if regime_key == "crr" else _b31_config()
    framework = "CRR" if regime_key == "crr" else "BASEL_3_1"
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep


def _refs(columns: list[COREPColumn], label: str, template: str) -> str:
    """The single column ref carrying ``label``, or a hard failure.

    Exactly one, never zero and never several: a template that loses the column
    must break this file loudly rather than skip the block it declares.
    """
    matched = [column.ref for column in columns if column.name == label]
    assert len(matched) == 1, (
        f"{template}: expected exactly one column named {label!r} in the declared "
        f"surface, found {matched}. The refs this file asserts on are derived from "
        "corep/templates.py, so a renamed or re-numbered column fails here rather "
        "than silently dropping the block from the test."
    )
    return matched[0]


def _block(spec: _Spec, corep: COREPTemplateBundle) -> _Block:
    """Resolve one spec against a run, deriving its four refs from the labels."""
    columns = spec.columns()
    return _Block(
        label=spec.label,
        sheets=spec.sheets(corep),
        pre=_refs(columns, _LBL_PRE, spec.label),
        sme=_refs(columns, _LBL_SME, spec.label),
        infra=_refs(columns, _LBL_INFRA, spec.label),
        post=_refs(columns, _LBL_POST, spec.label),
        home_sheet=spec.home_sheet,
        total_row=spec.total_row,
        sme_leg=spec.sme_leg,
        infra_leg=spec.infra_leg,
    )


@dataclass(frozen=True)
class _Spec:
    """Where one template's block lives, and which legs feed its two columns."""

    label: str
    sheets: Callable[[COREPTemplateBundle], dict[str, pl.DataFrame]]
    columns: Callable[[], list[COREPColumn]]
    home_sheet: str
    #: The whole-population row of ``home_sheet`` — C 08.02 and C 09.0x key
    #: their rows on a PD band / a row label rather than on ``0010``.
    total_row: str
    sme_leg: str
    infra_leg: str


#: The five call sites of the one ``_sf_adjustment_cell`` shape. C 08.01 and
#: C 08.02 are separate entries because ``c08.py`` serves both from one call.
_BLOCK_SPECS: tuple[_Spec, ...] = (
    _Spec(
        "C 07.00",
        lambda b: b.c07_00,
        lambda: get_c07_columns("CRR"),
        "corporate",
        "0010",
        _SA_SME_ONLY,
        _SA_OVERLAP,
    ),
    _Spec(
        "C 08.01",
        lambda b: b.c08_01,
        lambda: get_c08_columns("CRR"),
        "corporate_sme",
        "0010",
        _IRB_SME_ONLY,
        _IRB_OVERLAP,
    ),
    _Spec(
        "C 08.02",
        lambda b: b.c08_02,
        lambda: get_c08_02_columns("CRR"),
        "corporate_sme",
        "0.75% - 2.50%",
        _IRB_SME_ONLY,
        _IRB_OVERLAP,
    ),
    _Spec(
        "C 09.01",
        lambda b: b.c09_01,
        lambda: get_c09_01_columns("CRR"),
        "TOTAL",
        "0170",
        _SA_SME_ONLY,
        _SA_OVERLAP,
    ),
    _Spec(
        "C 09.02",
        lambda b: b.c09_02,
        lambda: get_c09_02_columns("CRR"),
        "TOTAL",
        "0150",
        _IRB_SME_ONLY,
        _IRB_OVERLAP,
    ),
)

_BLOCK_LABELS: tuple[str, ...] = tuple(spec.label for spec in _BLOCK_SPECS)


@lru_cache(maxsize=1)
def _blocks() -> dict[str, _Block]:
    """The five supporting-factor blocks on the CRR run, keyed by template."""
    _ledger, corep = _run("crr")
    return {spec.label: _block(spec, corep) for spec in _BLOCK_SPECS}


def _relief(ledger: pl.DataFrame, reference: str) -> float:
    """The RWEA the engine actually gave up on one exposure.

    Read off the sealed ledger (``rwa_pre_factor - rwa_final``), which is the
    engine's own output and cannot drift with the reporting code the "(-)"
    columns live in.
    """
    matched = ledger.filter(pl.col("source_exposure_reference") == reference)
    assert matched.height == 1, (
        f"{reference}: expected exactly one ledger row, got {matched.height}"
    )
    return float(matched["rwa_pre_factor"][0] - matched["rwa_final"][0])


# =============================================================================
# Adequacy — LESSONS C11: the fixture is a claim, so assert it
# =============================================================================


class TestTheEstateCanExpressTheOverlap:
    """Every assertion below is vacuous unless the estate carries, per approach,
    a row eligible for BOTH factors and a row eligible for the SME factor ALONE
    — with different, non-zero reliefs."""

    def test_each_approach_carries_an_overlap_leg_and_a_surviving_sme_only_leg(self) -> None:
        # Arrange
        ledger, _corep = _run("crr")
        applied = ledger.filter(pl.col("supporting_factor_applied").eq_missing(True))

        # Act
        overlap = set(
            applied.filter(pl.col("is_infrastructure").eq_missing(True))[
                "source_exposure_reference"
            ].to_list()
        )
        sme_only = set(
            applied.filter(~pl.col("is_infrastructure").eq_missing(True))[
                "source_exposure_reference"
            ].to_list()
        )

        # Assert — EXACT sets, not subsets. Every amount asserted below is the
        # relief of a named leg, so a sixth exposure picking up a supporting
        # factor has to fail here rather than quietly move a column.
        assert overlap == {_SA_OVERLAP, _IRB_OVERLAP}, (
            "the estate's SME-and-infrastructure population is not the two legs "
            "this file is written against, so no column here can distinguish a "
            f"disjoint attribution from a double-counted one; got {sorted(overlap)}"
        )
        assert sme_only == {_SA_SME_ONLY, _IRB_SME_ONLY}, (
            "the estate's SME-ONLY population is not the two surviving legs this "
            "file is written against; without one per approach a correct fix and an "
            "implementation that simply zeroed the SME column would look identical "
            f"(LESSONS B5); got {sorted(sme_only)}"
        )

    def test_the_overlap_and_sme_only_reliefs_are_non_zero_and_unequal(self) -> None:
        """The crossing-amount check, in its supporting-factor form.

        A zero overlap relief makes the two columns agree whatever the
        attribution, and equal reliefs make them indistinguishable if swapped —
        either way the amounts below would prove nothing (LESSONS C2).
        """
        # Arrange
        ledger, _corep = _run("crr")

        # Act
        reliefs = {ref: _relief(ledger, ref) for ref in _BOTH_LEGS}

        # Assert
        for ref, value in reliefs.items():
            assert value > 0.0, f"{ref} gave up no RWEA at all ({value}) — nothing to attribute"
        assert reliefs[_SA_OVERLAP] != reliefs[_SA_SME_ONLY], (
            "the two SA legs give up the same RWEA, so swapping the columns would "
            "leave every amount below unchanged"
        )
        assert reliefs[_IRB_OVERLAP] != reliefs[_IRB_SME_ONLY], (
            "the two A-IRB legs give up the same RWEA, so swapping the columns "
            "would leave every amount below unchanged"
        )

    def test_the_infrastructure_factor_binds_on_both_overlap_legs(self) -> None:
        """The premise the attribution rests on: ``min(sme, infra)`` picks infra.

        Asserted as the INEQUALITY rather than against a transcribed pack value
        — an SME blend that fell below the flat Art. 501a factor would invert
        which article the relief belongs to, and that has to fail here.
        """
        # Arrange
        ledger, _corep = _run("crr")

        def factor(reference: str) -> float:
            matched = ledger.filter(pl.col("source_exposure_reference") == reference)
            return float(matched["supporting_factor"][0])

        # Act + Assert
        for overlap, sme_only in ((_SA_OVERLAP, _SA_SME_ONLY), (_IRB_OVERLAP, _IRB_SME_ONLY)):
            assert factor(overlap) < factor(sme_only), (
                f"{overlap} kept a factor of {factor(overlap)} against {sme_only}'s "
                f"{factor(sme_only)}: the SME factor is binding on the overlap row, so "
                "the whole relief is NOT attributable to Art. 501a and the SME column "
                "excluding it would be an under-count"
            )
        assert factor(_SA_OVERLAP) == pytest.approx(factor(_IRB_OVERLAP)), (
            "the Art. 501a factor is flat, so the SA and A-IRB overlap legs must "
            "carry the same factor; a difference means one of them is not on the "
            "infrastructure limb at all"
        )

    @pytest.mark.parametrize("label", _BLOCK_LABELS)
    def test_each_template_emits_its_supporting_factor_block(self, label: str) -> None:
        """LESSONS B4 — the sheet is emitted and the four columns exist on it.

        Absence, not wrongness, is this estate's dominant escape: a block that
        was never emitted would make every identity below trivially true.
        """
        # Arrange + Act
        block = _blocks()[label]

        # Assert
        assert block.sheets, f"{label}: no sheet emitted at all"
        assert block.home_sheet in block.sheets, (
            f"{label}: sheet {block.home_sheet!r} not emitted; the axis holds "
            f"{sorted(block.sheets)}"
        )
        frame = block.sheets[block.home_sheet]
        for ref in (block.pre, block.sme, block.infra, block.post):
            assert ref in frame.columns, (
                f"{label}/{block.home_sheet}: declared column {ref} is missing from the "
                f"emitted frame, which holds {sorted(frame.columns)}"
            )


# =============================================================================
# The partition — the guard that discriminates on all five call sites
# =============================================================================


class TestTheReliefIsPartitioned:
    """The two "(-)" columns partition the row's relief: neither claims all of
    it, and together they claim exactly it.

    This needs no hand-derived amount. Pre-fix, ``|sme| + |infra|`` EXCEEDS the
    relief the engine granted by the overlap leg's own relief, on every one of
    the five call sites — which is also why the published footing rules
    (``v09747_m`` and siblings) broke."""

    @pytest.mark.parametrize("label", _BLOCK_LABELS)
    def test_pre_plus_both_adjustments_foots_to_post_on_every_populated_row(
        self, label: str
    ) -> None:
        """``0215 + 0216 + 0217 = 0220`` and its three analogues, every sheet."""
        # Arrange
        block = _blocks()[label]
        checked = 0

        # Act + Assert
        for sheet in sorted(block.sheets):
            for row_ref in block.rows(sheet):
                pre = block.cell(sheet, row_ref, block.pre)
                post = block.cell(sheet, row_ref, block.post)
                if pre is None or post is None:
                    continue
                sme = block.cell(sheet, row_ref, block.sme)
                infra = block.cell(sheet, row_ref, block.infra)
                assert sme is not None and infra is not None, (
                    f"{label}/{sheet} row {row_ref}: pre={pre} and post={post} are "
                    f"reported but an adjustment column is NULL (sme={sme}, "
                    f"infra={infra}). A null and a legitimate 0.00 are different claims."
                )
                assert pre + sme + infra == pytest.approx(post, rel=_REL, abs=_ABS), (
                    f"{label}/{sheet} row {row_ref}: {pre} + {sme} + {infra} = "
                    f"{pre + sme + infra}, not {post}. The two '(-)' columns must "
                    "PARTITION the relief; a row eligible for Art. 501 and Art. 501a at "
                    "once carries ONE relief and it is attributable to Art. 501a alone."
                )
                checked += 1

        assert checked, f"{label}: no populated row was checked — the block is dead"

    @pytest.mark.parametrize("label", _BLOCK_LABELS)
    def test_neither_column_claims_the_whole_relief_on_the_home_sheet(self, label: str) -> None:
        """Both columns are strictly inside the relief, and sum to it.

        The strict inequalities are the population statement: the SME column
        cannot swallow the infrastructure row's relief (the defect), and the
        infrastructure column cannot swallow the SME-only row's."""
        # Arrange
        block = _blocks()[label]
        sheet, row_ref = block.home_sheet, block.total_row

        # Act
        pre = float(block.cell(sheet, row_ref, block.pre) or 0.0)
        post = float(block.cell(sheet, row_ref, block.post) or 0.0)
        sme = abs(float(block.cell(sheet, row_ref, block.sme) or 0.0))
        infra = abs(float(block.cell(sheet, row_ref, block.infra) or 0.0))
        relief = pre - post

        # Assert
        assert relief > 0.0, (
            f"{label}/{sheet} row {row_ref}: the row gave up no RWEA at all, so the "
            "partition below is vacuous"
        )
        assert 0.0 < sme < relief, (
            f"{label}/{sheet} row {row_ref}: the SME column claims {sme} of a {relief} "
            "relief — 0.0 means the column was zeroed rather than narrowed, and the "
            "whole relief means it still swallows the infrastructure row's"
        )
        assert 0.0 < infra < relief, (
            f"{label}/{sheet} row {row_ref}: the infrastructure column claims {infra} "
            f"of a {relief} relief"
        )
        assert sme + infra == pytest.approx(relief, rel=_REL, abs=_ABS), (
            f"{label}/{sheet} row {row_ref}: the two columns claim {sme + infra} "
            f"between them against a {relief} relief actually granted"
        )


# =============================================================================
# The shape guard — the two columns stop sharing one row set
# =============================================================================


class TestThePopulationsDiverge:
    """The defect read off the output SHAPE, without knowing a single amount.

    One flag drove both columns, so they were live on identically the same cells
    — which is why a census of dead cells scored the SME and infrastructure
    columns as an exact pairwise tie. Once the SME column excludes
    infrastructure rows the two populations must come apart.

    Scope, stated rather than implied (LESSONS C10): the divergence is
    observable on C 07.00, the only template of the five with an
    infrastructure-specific of-which row (0035). On C 08.01/02 and C 09.01/02
    both columns are live on the same rows before AND after, so
    ``TestTheReliefIsPartitioned`` is what discriminates there. Measured on this
    estate: 22 == 22 live cells pre-fix, 21 SME against 22 infrastructure after,
    the one difference being C 07.00 / corporate / 0035.
    """

    def test_the_live_cell_sets_of_the_two_columns_are_not_identical(self) -> None:
        # Arrange
        blocks = _blocks()

        # Act
        sme_cells = {
            (label, sheet, row)
            for label, block in blocks.items()
            for sheet in block.sheets
            for row in block.rows(sheet)
            if _is_live(block.cell(sheet, row, block.sme))
        }
        infra_cells = {
            (label, sheet, row)
            for label, block in blocks.items()
            for sheet in block.sheets
            for row in block.rows(sheet)
            if _is_live(block.cell(sheet, row, block.infra))
        }

        # Assert
        assert sme_cells, "no SME adjustment cell is live anywhere in the estate"
        assert infra_cells, "no infrastructure adjustment cell is live anywhere"
        assert sme_cells != infra_cells, (
            "the SME and infrastructure '(-)' columns are live on identically the "
            f"same {len(sme_cells)} cells. That is the shape one flag driving both "
            "columns produces: whichever rows carry a supporting factor, both "
            "columns claim them. They must come apart on the rows scoped to "
            "infrastructure alone."
        )

    def test_the_c07_infrastructure_of_which_row_reports_no_sme_relief(self) -> None:
        """C 07.00 row 0035 is scoped to infrastructure rows by definition, so
        its SME adjustment is 0.00 — a claim, not a null — while its
        infrastructure adjustment carries the whole relief."""
        # Arrange
        block = _blocks()["C 07.00"]
        sheet, row_ref = "corporate", "0035"

        # Act
        sme = block.cell(sheet, row_ref, block.sme)
        infra = block.cell(sheet, row_ref, block.infra)

        # Assert
        assert sme is not None, (
            f"C 07.00/{sheet} row {row_ref} col {block.sme} is NULL — the row has "
            "exposure, so 'no SME-attributable relief' has to be published as 0.00"
        )
        assert sme == pytest.approx(0.0, abs=_ABS), (
            f"C 07.00/{sheet} row {row_ref} col {block.sme} reports {sme}. Every row in "
            "this of-which is an infrastructure row; attributing any of its relief to "
            "Art. 501 is the double-count, and here it is visible without any amount "
            "at all — the same figure appears in both columns."
        )
        assert _is_live(infra), (
            f"C 07.00/{sheet} row {row_ref} col {block.infra} reports {infra}: the "
            "infrastructure of-which row must carry the relief the SME column gave up"
        )


# =============================================================================
# The amounts — an implementation that zeroed a column satisfies the identity
# =============================================================================


class TestTheAttributedAmounts:
    """Each column against the relief its own legs gave up, read off the ledger.

    The expected value is the engine's own ``rwa_pre_factor - rwa_final`` for
    the named exposures, so it cannot drift with the reporting code under test;
    the absolute figures are recorded beside it so a move in either the engine
    or the template says which side moved."""

    #: exposure -> the RWEA it gives up, as measured on this estate. Recorded
    #: beside the ledger-derived assertion so a move says which side moved.
    _RELIEF: dict[str, float] = {
        LN_SME: 119_050.0,
        LN_SME_INFRA: 375_000.0,
        LN_AIRB: 2_584_368.949875377,
        LN_AIRB_INFRA: 404_778.8266672471,
    }

    @pytest.mark.parametrize("label", _BLOCK_LABELS)
    def test_each_column_reports_its_own_legs_relief(self, label: str) -> None:
        # Arrange
        ledger, _corep = _run("crr")
        block = _blocks()[label]
        sheet, row_ref = block.home_sheet, block.total_row
        want_sme = self._RELIEF[block.sme_leg]
        want_infra = self._RELIEF[block.infra_leg]

        # Act
        sme = block.cell(sheet, row_ref, block.sme)
        infra = block.cell(sheet, row_ref, block.infra)

        # Assert — against the ledger first, then against the recorded figure.
        assert sme == pytest.approx(-_relief(ledger, block.sme_leg), rel=_REL, abs=_ABS), (
            f"{label}/{sheet} row {row_ref} col {block.sme} reports {sme}; the SME "
            f"column's only leg is {block.sme_leg}, which gave up "
            f"{_relief(ledger, block.sme_leg)}. A larger magnitude means the "
            "infrastructure leg's relief is still being counted here too."
        )
        assert infra == pytest.approx(-_relief(ledger, block.infra_leg), rel=_REL, abs=_ABS), (
            f"{label}/{sheet} row {row_ref} col {block.infra} reports {infra} against "
            f"{block.infra_leg}'s {_relief(ledger, block.infra_leg)}"
        )
        assert sme == pytest.approx(-want_sme, rel=_REL, abs=_ABS)
        assert infra == pytest.approx(-want_infra, rel=_REL, abs=_ABS)

    def test_the_c07_sme_of_which_row_still_reports_both_articles(self) -> None:
        """Row 0030 ("of which: SME-supporting factor") scopes to ``is_sme``,
        which INCLUDES the overlap leg — so its infrastructure column is
        populated and its SME column is not the row's whole relief. Excluding
        infrastructure from the SME COLUMN is not the same as excluding it from
        the SME ROW, and confusing the two would empty row 0030."""
        # Arrange
        block = _blocks()["C 07.00"]

        # Act
        pre = block.cell("corporate", "0030", block.pre)
        sme = block.cell("corporate", "0030", block.sme)
        infra = block.cell("corporate", "0030", block.infra)
        post = block.cell("corporate", "0030", block.post)

        # Assert
        assert pre == pytest.approx(2_000_000.0, rel=_REL, abs=_ABS)
        assert sme == pytest.approx(-119_050.0, rel=_REL, abs=_ABS)
        assert infra == pytest.approx(-375_000.0, rel=_REL, abs=_ABS)
        assert post == pytest.approx(1_505_950.0, rel=_REL, abs=_ABS)

    def test_basel_31_declares_no_supporting_factor_columns(self) -> None:
        """Both factors are withdrawn under Basel 3.1, so the whole block is
        absent rather than zero — which is why every assertion above is
        CRR-only, and why a fix here cannot move a Basel 3.1 figure."""
        # Arrange
        _ledger, corep = _run("b31")

        # Act + Assert
        for spec in _BLOCK_SPECS:
            label = spec.label
            block = _blocks()[label]
            for sheet, frame in spec.sheets(corep).items():
                for ref in (block.pre, block.sme, block.infra):
                    assert ref not in frame.columns, (
                        f"{label}/{sheet} still declares column {ref} under Basel 3.1"
                    )


# =============================================================================
# Helpers
# =============================================================================


def _is_live(value: float | None) -> bool:
    """A cell that carries money — null and 0.00 are both "not live" here.

    Deliberately the census's own reading: a "(-)" column publishing 0.00 makes
    the claim "no relief under this article", which is what the SME column must
    say on an infrastructure-only row.
    """
    return value is not None and abs(float(value)) > _ABS
