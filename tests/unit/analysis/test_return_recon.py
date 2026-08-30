"""
Unit tests: cell-delta decomposition (analysis.return_recon).

Pins the properties the four-way waterfall has to have before an analyst may
read it as an explanation of a cell:

- **The four terms sum to the cell delta.** Not on a sample: on EVERY additive
  money cell of all three scoped templates under both frameworks, over a
  portfolio built so that all four causes are live at once. The census counts
  its own denominator and every refusal reason, so a narrowed scope cannot hide
  behind a good ratio.
- **Each term is isolated.** One single-cause pair per term — a leg only on our
  side, a leg only on theirs, a leg that moves PD band, a leg that moves
  exposure class, a leg whose EAD/RWA differs — each asserted to move ITS term
  and leave the other four at zero. A fixture where three terms are zero proves
  almost nothing, so the combined portfolio is asserted to have none.
- **Refusal is real.** A weighted-average / ratio / count cell is refused rather
  than decomposed, detected from the binding's own metric; and a deliberately
  broken decomposition reports ``reconciles=False`` rather than a plausible
  waterfall.
- **Absence stays absence.** A cell emitted on one side only is distinguishable
  from a cell that is zero on both, and a NULL ``is_parent_row`` is never
  treated as a leaf.

References:
- Regulation (EU) 2021/451, Annex II: C 07.00, C 08.01, C 08.03
- docs/plans/return-reconciliation.md (Phase 4 — the four-way waterfall)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from functools import lru_cache

import polars as pl
import pytest
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.analysis import return_recon as recon_module
from rwa_calc.analysis.legacy_ledger import LegacyLedgerSource, ledger_coverage
from rwa_calc.analysis.return_recon import (
    ABSENT_ROW,
    CELL_DIFF_SCHEMA,
    CELL_PAIRS_LIMIT,
    KEY_COLUMNS,
    MOVEMENT_BASES,
    PLACEMENT_ATTRIBUTION,
    RECON_TEMPLATE_IDS,
    TERM_NAMES,
    UNDECIDABLE_ROW,
    CellDecomposition,
    CellTerm,
    ReturnRecon,
    SideView,
    build_recon,
    cell_diff,
    cell_pairs,
    decompose_cell,
    diff_cells,
    migration_legs,
    row_migration,
)
from rwa_calc.reporting.membership import MEMBERSHIP_TEMPLATE_IDS

FRAMEWORKS = ("CRR", "BASEL_3_1")

#: The identity rung a frame with no base reference falls back to. Read off the
#: module rather than typed, so the fixtures cannot drift from the ladder.
_FALLBACK_IDENTITY = recon_module._FALLBACK_KEY_COLUMN

# The corporate IRB sheet is where every cause is planted, so the isolation
# tests all address one cell family on it.
CORPORATE = "corporate"

# Two PD bands that are distinct under BOTH frameworks (Basel 3.1 splits the
# first CRR band at 0.05%, so a mover must not straddle that boundary):
# 0.12% sits in "0.05 to <0.15" / "0.00 to <0.15", 2.00% in "0.75 to <2.50".
PD_BAND_A = 0.0012
PD_BAND_B = 0.0200


class _FrameSource:
    """A minimal ``ResultsSource`` over a hand-built sealed ledger."""

    def __init__(self, frame: pl.LazyFrame, framework: str = "CRR") -> None:
        self._frame = frame
        self.framework = framework

    def scan_results(self) -> pl.LazyFrame:
        return self._frame


# =============================================================================
# The portfolio
# =============================================================================


@dataclass(frozen=True)
class _Leg:
    """One exposure leg, in the raw shape the sealed ledger is derived from."""

    reference: str
    exposure_class: str = CORPORATE
    approach: str = "foundation_irb"
    exposure_type: str = "loan"
    ead: float = 1_000_000.0
    rwa: float = 300_000.0
    pd: float | None = PD_BAND_A
    lgd: float = 0.45
    undrawn: float = 0.0
    cqs: int = 0
    #: The PRE-SPLIT base exposure this leg belongs to. ``None`` means the leg
    #: is unsplit and is therefore its own base — the shape every other fixture
    #: in this file has. A guarantee split (``engine/hierarchy/unify.py``), a
    #: real-estate split or a facility-undrawn split emits several legs under
    #: one base, and that is the case nothing here could express before.
    source: str | None = None
    #: ``False`` mirrors the PROJECTED LEGACY SIDE, which supplies no
    #: ``source_exposure_reference`` at all: it is neither a component nor a
    #: carrier in ``recon_registry``, so ``legacy_ledger._projection_exprs``
    #: never emits it and it arrives as a typed NULL through
    #: ``MEMBERSHIP_SCHEMA``. Modelled rather than assumed away, because a fix
    #: that keyed on the base reference ALONE would pass a fixture that
    #: populated it on both sides and drop every legacy leg in production.
    supplies_source_ref: bool = True

    def row(self) -> dict[str, object]:
        drawn = self.ead if self.exposure_type == "loan" else 0.0
        base = self.source or self.reference
        return {
            "exposure_reference": self.reference,
            "source_exposure_reference": base if self.supplies_source_ref else None,
            "counterparty_reference": f"CP_{base}",
            "exposure_class": self.exposure_class,
            "exposure_class_applied": self.exposure_class,
            "exposure_class_post_crm": self.exposure_class,
            "approach_applied": self.approach,
            "approach_post_crm": self.approach,
            "exposure_type": self.exposure_type,
            "drawn_amount": drawn,
            "undrawn_amount": self.undrawn,
            "nominal_amount": 0.0,
            "interest": 0.0,
            "ead_final": self.ead,
            "rwa_final": self.rwa,
            "risk_weight": self.rwa / self.ead if self.ead else 0.0,
            "ccf": 1.0,
            "pd": self.pd,
            "pd_floored": self.pd,
            "lgd_floored": self.lgd if self.pd is not None else None,
            "irb_maturity_m": 2.5 if self.pd is not None else None,
            "expected_loss": (self.pd * self.lgd * self.ead) if self.pd is not None else 0.0,
            "scra_provision_amount": 0.0,
            "gcra_provision_amount": 0.0,
            "sa_cqs": self.cqs,
            "is_defaulted": False,
            "reporting_leg_role": "whole",
        }


#: The only corporate leg in PD band 2.5-<10%, so its parent row 0100 and its
#: child row 0110 hold exactly the same legs and both come back
#: ``is_parent_row = None``. It therefore reaches NO decidable leaf row — the
#: live case for the ``UNDECIDABLE_ROW`` bucket, and the money a
#: ``~is_parent_row`` filter would silently lose.
_BASE_NULL_PARENT = _Leg("BASE_NULL_PARENT", pd=0.0300, ead=1_400_000.0, rwa=980_000.0)


def _base_legs() -> list[_Leg]:
    """Legs identical on both sides — the agreeing backbone of every pair.

    The corporate PDs are chosen so the C 08.03 parent flag is DERIVABLE.
    ``is_parent_row`` is measured, not listed, so a parent band with a single
    populated child is indistinguishable from a leaf and comes back NULL. So
    parent 0010 gets two populated children (0.05% and 0.12%) and parent 0070
    two (1.00% and 2.00%), while parent 0100 is deliberately left with ONE
    (``_BASE_NULL_PARENT``, 3.00%) so a genuine NULL survives
    for the tri-state guard to be tested against.

    Plus an IRB institution leg (so the sheet the class mover lands on exists on
    both sides), an A-IRB retail mortgage sheet and two standardised legs (so
    C 07.00 is populated too).
    """
    return [
        _Leg("BASE_A0", pd=0.0005, ead=900_000.0, rwa=270_000.0),
        _Leg("BASE_A1", pd=PD_BAND_A, ead=1_000_000.0, rwa=300_000.0),
        _Leg("BASE_A2", pd=PD_BAND_A, ead=1_100_000.0, rwa=330_000.0),
        _Leg("BASE_B0", pd=0.0100, ead=1_800_000.0, rwa=720_000.0),
        _Leg("BASE_B1", pd=PD_BAND_B, ead=2_000_000.0, rwa=800_000.0),
        _BASE_NULL_PARENT,
        _Leg(
            "BASE_OFF",
            exposure_type="facility_undrawn",
            ead=600_000.0,
            rwa=180_000.0,
            undrawn=1_200_000.0,
            pd=PD_BAND_A,
        ),
        _Leg(
            "BASE_INST", exposure_class="institution", ead=1_500_000.0, rwa=225_000.0, pd=PD_BAND_A
        ),
        _Leg(
            "BASE_RETM",
            exposure_class="retail_mortgage",
            approach="advanced_irb",
            ead=3_000_000.0,
            rwa=450_000.0,
            pd=0.0080,
            lgd=0.15,
        ),
        _Leg("BASE_SA", approach="standardised", ead=1_500_000.0, rwa=1_500_000.0, pd=None, cqs=3),
        _Leg(
            "BASE_SA_INST",
            exposure_class="institution",
            approach="standardised",
            ead=800_000.0,
            rwa=160_000.0,
            pd=None,
            cqs=2,
        ),
    ]


# The five single-cause legs. Each is added to, removed from, or mutated
# between the two sides so that exactly one decomposition term moves.
_ONLY_OURS = _Leg("ONLY_OURS", ead=500_000.0, rwa=150_000.0, pd=PD_BAND_A)
_ONLY_THEIRS = _Leg("ONLY_THEIRS", ead=400_000.0, rwa=120_000.0, pd=PD_BAND_A)
_BAND_MOVER = _Leg("BAND_MOVER", ead=700_000.0, rwa=210_000.0, pd=PD_BAND_A)
_CLASS_MOVER = _Leg("CLASS_MOVER", ead=900_000.0, rwa=270_000.0, pd=PD_BAND_A)
_MEASURED = _Leg("MEASURED", ead=1_200_000.0, rwa=360_000.0, pd=PD_BAND_A)
# C 08.01 has no PD-band axis, so ``_BAND_MOVER`` cannot move a row there and
# ``row_placement`` — the headline term of this slice — measured 0.00 on it in
# both frameworks. C 08.01 DOES place rows on the on/off-balance-sheet split
# (rows 0020 / 0030), so a leg that is drawn on our side and a commitment on
# theirs exercises it: 15,681,728 (CRR) / 17,921,728 (B31) once added.
_BS_MOVER = _Leg("BS_MOVER", ead=1_600_000.0, rwa=480_000.0, pd=PD_BAND_A)

# The same five causes on STANDARDISED legs. Without them C 07.00's half of the
# additivity contract is vacuous: measured at moved=0 of 804 (CRR) / 1598 (B31)
# cells, every one of them reconciling 0.0 against 0.0. A template whose cells
# never differ cannot test a decomposition of a difference.
_SA_ONLY_OURS = _Leg(
    "SA_ONLY_OURS", approach="standardised", pd=None, ead=650_000.0, rwa=650_000.0, cqs=3
)
_SA_ONLY_THEIRS = _Leg(
    "SA_ONLY_THEIRS", approach="standardised", pd=None, ead=550_000.0, rwa=550_000.0, cqs=3
)
# Same EAD, different RISK WEIGHT: moves the C 07.00 risk-weight band row while
# leaving every exposure-value column at the same figure.
_SA_RW_MOVER = _Leg(
    "SA_RW_MOVER", approach="standardised", pd=None, ead=1_000_000.0, rwa=500_000.0, cqs=3
)
_SA_CLASS_MOVER = _Leg(
    "SA_CLASS_MOVER", approach="standardised", pd=None, ead=1_300_000.0, rwa=1_300_000.0, cqs=3
)
_SA_MEASURED = _Leg(
    "SA_MEASURED", approach="standardised", pd=None, ead=1_700_000.0, rwa=1_700_000.0, cqs=3
)


def _ledger(legs: list[_Leg]) -> pl.LazyFrame:
    """The sealed reporting ledger for a list of legs."""
    raw = pl.LazyFrame(
        [leg.row() for leg in legs],
        schema_overrides={
            "pd": pl.Float64,
            "pd_floored": pl.Float64,
            "lgd_floored": pl.Float64,
            "irb_maturity_m": pl.Float64,
            "sa_cqs": pl.Int8,
            # Pinned so a side whose legs ALL omit the base reference still
            # carries the column as a typed NULL String, exactly as the sealed
            # membership schema declares it, rather than as pl.Null.
            "source_exposure_reference": pl.String,
        },
    )
    return with_reporting_ledger(raw)


def _sources(
    ours: list[_Leg], theirs: list[_Leg], framework: str
) -> tuple[_FrameSource, _FrameSource]:
    return _FrameSource(_ledger(ours), framework), _FrameSource(_ledger(theirs), framework)


@lru_cache(maxsize=16)
def _combined(framework: str) -> ReturnRecon:
    """The SHARED combined portfolio — cached, so never mutate what it returns.

    A ``ReturnRecon`` carries memo dictionaries, so a test that corrupts the
    module under it would hand every later test a poisoned engine. Anything
    doing that must call ``_uncached_combined`` instead.
    """
    return _uncached_combined(framework)


def _uncached_combined(framework: str) -> ReturnRecon:
    """Both sides of a portfolio where ALL FOUR causes are live at once.

    A pair exercising three of four terms would leave the fourth unproven while
    the additivity assertion still passed, so the combined portfolio is the one
    the census runs on and every term is asserted non-zero on it. The five
    causes are planted twice — once on IRB legs (C 08.01 / C 08.03) and once on
    standardised legs (C 07.00) — because C 07.00 excludes IRB legs entirely and
    without its own causes its half of the contract ties 0.0 to 0.0 throughout.
    """
    ours = [
        *_base_legs(),
        _ONLY_OURS,
        _BAND_MOVER,
        _CLASS_MOVER,
        _MEASURED,
        _BS_MOVER,
        _SA_ONLY_OURS,
        _SA_RW_MOVER,
        _SA_CLASS_MOVER,
        _SA_MEASURED,
    ]
    theirs = [
        *_base_legs(),
        _ONLY_THEIRS,
        replace(_BAND_MOVER, pd=PD_BAND_B),
        replace(_CLASS_MOVER, exposure_class="institution"),
        replace(_MEASURED, ead=1_000_000.0, rwa=300_000.0),
        replace(_BS_MOVER, exposure_type="facility_undrawn", undrawn=3_200_000.0),
        _SA_ONLY_THEIRS,
        replace(_SA_RW_MOVER, rwa=1_000_000.0),
        replace(_SA_CLASS_MOVER, exposure_class="institution"),
        replace(_SA_MEASURED, ead=1_400_000.0, rwa=1_400_000.0),
    ]
    our_source, their_source = _sources(ours, theirs, framework)
    return build_recon(our_source, their_source)


@lru_cache(maxsize=32)
def _single_cause(cause: str, framework: str) -> ReturnRecon:
    """A pair differing by exactly ONE leg-level cause."""
    base = _base_legs()
    ours = [*base]
    theirs = [*base]
    if cause == "population_ours_only":
        ours.append(_ONLY_OURS)
    elif cause == "population_theirs_only":
        theirs.append(_ONLY_THEIRS)
    elif cause == "row_placement":
        ours.append(_BAND_MOVER)
        theirs.append(replace(_BAND_MOVER, pd=PD_BAND_B))
    elif cause == "sheet_placement":
        ours.append(_CLASS_MOVER)
        theirs.append(replace(_CLASS_MOVER, exposure_class="institution"))
    elif cause == "measurement":
        ours.append(_MEASURED)
        theirs.append(replace(_MEASURED, ead=1_000_000.0, rwa=300_000.0))
    else:  # pragma: no cover - a typo in a parametrisation, not a data case
        raise AssertionError(f"unknown cause {cause!r}")
    our_source, their_source = _sources(ours, theirs, framework)
    return build_recon(our_source, their_source)


# =============================================================================
# Helpers
# =============================================================================


def _leaf_row_of(recon: ReturnRecon, *, ours: bool, reference: str) -> str:
    """The C 08.03 corporate leaf row one leg landed in, on the named side.

    Read off the membership rather than hard-coded: the CRR and Basel 3.1 row
    axes differ (18 rows against 17), so a literal ref would pin one framework.
    """
    side = recon.ours if ours else recon.theirs
    rows = side.membership.legs.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == CORPORATE)
        & (pl.col("exposure_reference") == reference)
        & (pl.col("is_parent_row").eq(other=False))
    )
    assert rows.height == 1, f"{reference} is in {rows.height} leaf rows, expected 1"
    return rows["row_ref"][0]


def _terms(result: CellDecomposition) -> dict[str, float]:
    return {term.name: term.amount for term in result.terms}


def _term_keys(result: CellDecomposition) -> dict[str, int]:
    """How many reconciliation keys each term counted.

    Separate from the amounts because a term at ``0.00`` says two different
    things depending on this: no keys at all means the bucket is empty, one key
    means two sides paired on it and agreed.
    """
    return {term.name: term.keys for term in result.terms}


@dataclass(frozen=True)
class _Census:
    """The additivity census over one template under one framework.

    ``moved`` is the non-vacuous denominator: cells whose delta is actually
    non-zero. ``checked`` alone can be inflated by cells neither side reports,
    which reconcile at 0 == 0 and prove nothing about the identity.
    """

    cells: int
    checked: int
    reconciled: int
    moved: int
    failures: list[str]
    refusals: dict[str, int]


def _census(recon: ReturnRecon, template_id: str) -> _Census:
    """Decompose EVERY published cell of a template and score the identity."""
    diff = cell_diff(recon.ours.source, recon.theirs.source, template_id)
    checked = 0
    reconciled = 0
    moved = 0
    failures: list[str] = []
    refusals: dict[str, int] = {}
    for row in diff.iter_rows(named=True):
        result = decompose_cell(recon, template_id, row["sheet"], row["row_ref"], row["col_ref"])
        if not result.decomposable:
            reason = (result.refusal or "").split(":")[0]
            refusals[reason] = refusals.get(reason, 0) + 1
            continue
        checked += 1
        moved += int(abs(result.delta or 0.0) > 1e-9)
        if result.reconciles:
            reconciled += 1
        else:
            failures.append(
                f"{row['sheet']}/{row['row_ref']}/{row['col_ref']} "
                f"delta={result.delta} explained={result.explained} "
                f"residual={result.residual}"
            )
    return _Census(
        cells=diff.height,
        checked=checked,
        reconciled=reconciled,
        moved=moved,
        failures=failures,
        refusals=refusals,
    )


# =============================================================================
# The additivity contract
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_four_terms_sum_to_the_cell_delta_on_every_additive_cell(
    template_id: str, framework: str
) -> None:
    # Arrange
    recon = _combined(framework)

    # Act
    census = _census(recon, template_id)

    # Assert — every decomposable cell reconciles, over a denominator that is
    # not merely large: a cell neither side reports ties at 0 == 0 and proves
    # nothing, so the moved subset must be substantial in its own right.
    assert census.failures == []
    assert census.reconciled == census.checked
    assert census.moved >= 20, f"only {census.moved} of {census.checked} cells actually differ"


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_the_combined_portfolio_leaves_no_term_at_zero(template_id: str, framework: str) -> None:
    """A term that is structurally zero on a template is untested on it.

    Parametrised over EVERY scoped template, not just C 08.03. Pinned to one
    template this passed while ``row_placement`` — the headline term of the
    slice — measured 0.00 on C 08.01 in both frameworks, because C 08.01 has no
    PD-band axis for ``_BAND_MOVER`` to move. ``_BS_MOVER`` supplies the
    on/off-balance-sheet move that template does place rows on.
    """
    # Arrange
    recon = _combined(framework)
    totals = dict.fromkeys(TERM_NAMES, 0.0)

    # Act
    diff = cell_diff(recon.ours.source, recon.theirs.source, template_id)
    for row in diff.iter_rows(named=True):
        result = decompose_cell(recon, template_id, row["sheet"], row["row_ref"], row["col_ref"])
        for term in result.terms:
            totals[term.name] += abs(term.amount)

    # Assert
    assert all(totals[name] > 0.0 for name in TERM_NAMES), totals


# =============================================================================
# One term at a time
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("cause", TERM_NAMES)
def test_a_single_cause_pair_moves_only_its_own_term(cause: str, framework: str) -> None:
    """Each cause, alone, moves ITS term on the cell its leg lands in."""
    # Arrange
    recon = _single_cause(cause, framework)
    reference = {
        "population_ours_only": ("ONLY_OURS", True),
        "population_theirs_only": ("ONLY_THEIRS", False),
        "row_placement": ("BAND_MOVER", True),
        "sheet_placement": ("CLASS_MOVER", True),
        "measurement": ("MEASURED", True),
    }[cause]
    row_ref = _leaf_row_of(recon, ours=reference[1], reference=reference[0])

    # Act — column 0040 is C 08.03's EAD, a plain additive Sum.
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0040")
    terms = _terms(result)

    # Assert — the named term is the only live one, and it explains the delta.
    assert result.decomposable, result.refusal
    assert result.reconciles
    assert terms[cause] != 0.0, terms
    assert [name for name, amount in terms.items() if amount != 0.0] == [cause]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_row_placement_prices_the_band_move_at_its_own_ead(framework: str) -> None:
    """The moved money is the leg's EAD, signed by the direction of travel."""
    # Arrange
    recon = _single_cause("row_placement", framework)
    our_row = _leaf_row_of(recon, ours=True, reference="BAND_MOVER")
    their_row = _leaf_row_of(recon, ours=False, reference="BAND_MOVER")
    assert our_row != their_row, "the mover did not change row — the fixture is vacuous"

    # Act
    left = decompose_cell(recon, "c08_03", CORPORATE, our_row, "0040")
    right = decompose_cell(recon, "c08_03", CORPORATE, their_row, "0040")

    # Assert — it leaves our band and arrives in theirs, at the same EAD.
    assert _terms(left)["row_placement"] == pytest.approx(_BAND_MOVER.ead)
    assert _terms(right)["row_placement"] == pytest.approx(-_BAND_MOVER.ead)


# =============================================================================
# Refusals
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("col_ref", ["0030", "0050", "0070", "0080"])
def test_non_additive_cells_are_refused_not_decomposed(col_ref: str, framework: str) -> None:
    """C 08.03's averaged columns carry no four-way split — and say so."""
    # Arrange
    recon = _combined(framework)
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, col_ref)

    # Assert
    assert not result.decomposable
    assert result.terms == ()
    assert not result.reconciles
    assert result.metric in {"weighted_avg", "mean", "ratio", "count"}
    assert "non-additive" in (result.refusal or "")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_formula_cell_is_refused_for_having_no_population(framework: str) -> None:
    # Arrange — C 07.00 col 0040 is Formula(0010 - 0030), not a row sum.
    recon = _combined(framework)

    # Act
    result = decompose_cell(recon, "c07_00", CORPORATE, "0010", "0040")

    # Assert
    assert not result.decomposable
    assert result.kind != "rows"
    assert "population" in (result.refusal or "")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_broken_decomposition_reports_reconciles_false(
    framework: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal must be observable, not theoretical.

    Corrupting the per-key money changes the terms without touching the reported
    figures, which is exactly the shape of a decomposition bug: a plausible
    waterfall that does not add up. ``reconciles`` has to catch it.

    Runs on its OWN recon, never the shared cached one — a decomposition under
    the broken function writes into ``SideView.money``, and leaving that behind
    would hand every later test a silently halved engine.
    """
    # Arrange
    import rwa_calc.analysis.return_recon as module

    recon = _uncached_combined(framework)
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")
    healthy = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0040")
    assert healthy.reconciles

    original = module._key_money

    def _broken(*args: object, **kwargs: object) -> dict[str, float]:
        money = original(*args, **kwargs)  # type: ignore[arg-type]
        return {key: value * 0.5 for key, value in money.items()}

    monkeypatch.setattr(module, "_key_money", _broken)
    recon.ours.money.clear()
    recon.theirs.money.clear()

    # Act
    broken = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0040")

    # Assert
    assert not broken.reconciles
    assert broken.residual is not None
    assert abs(broken.residual) > 0.0


# =============================================================================
# The diff frame
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_cell_diff_distinguishes_one_sided_cells_from_zero_on_both(framework: str) -> None:
    """A missing row is not a zero, and the frame must never let them look alike."""
    # Arrange — only ours carries a leg in a band nothing on their side reaches.
    base = _base_legs()
    lone = _Leg("LONE_BAND", ead=750_000.0, rwa=225_000.0, pd=0.5000)
    our_source, their_source = _sources([*base, lone], base, framework)

    # Act
    diff = cell_diff(our_source, their_source, "c08_03", sheet=CORPORATE)

    # Assert — the lone band's row is ours-only; a shared zero cell is "both".
    assert diff.schema == CELL_DIFF_SCHEMA
    ours_only = diff.filter(pl.col("status") == "ours_only")
    assert ours_only.height > 0
    assert set(ours_only["theirs_state"].to_list()) == {"absent"}
    both_zero = diff.filter(
        (pl.col("status") == "both") & (pl.col("ours") == 0.0) & (pl.col("theirs") == 0.0)
    )
    assert both_zero.height > 0
    assert set(both_zero["ours_state"].to_list()) == {"figure"}


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_cell_diff_enumerates_rows_only_THEIR_side_emits(framework: str) -> None:
    """The mirror of the test above, and it guards a different thing.

    Every other one-sided test plants its lone band on OUR side, and
    ``_ONLY_THEIRS`` sits in a band we populate too — so nothing exercised a row
    that exists ONLY on theirs, and the union enumeration in ``_ordered_union``
    was unguarded. Measured: restricting the enumeration to our own axes emits
    88 cells instead of 110 and ZERO ``theirs_only`` rows, with the whole of
    their band silently absent from the comparison rather than reported.
    """
    # Arrange — only THEIRS carries a leg in a band nothing on our side reaches.
    base = _base_legs()
    lone = _Leg("LONE_BAND_THEIRS", ead=750_000.0, rwa=225_000.0, pd=0.5000)
    our_source, their_source = _sources(base, [*base, lone], framework)

    # Act
    diff = cell_diff(our_source, their_source, "c08_03", sheet=CORPORATE)

    # Assert — their band is enumerated, and reads as theirs-only.
    theirs_only = diff.filter(pl.col("status") == "theirs_only")
    assert theirs_only.height > 0
    assert set(theirs_only["ours_state"].to_list()) == {"absent"}
    assert theirs_only["theirs"].max() > 0.0
    # And the delta is signed towards them, not dropped.
    assert theirs_only["delta"].min() < 0.0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_one_sided_cell_on_a_static_row_axis_is_not_unmeasurable(framework: str) -> None:
    """C 07.00 emits its whole row axis, so a one-sided cell reads as an EMPTY
    counterpart rather than a missing row — and must still decompose.

    Conflating that ``empty`` with the ``unavailable`` null (no metric source at
    all) refuses the finding outright: measured at 996 cells refused on this very
    portfolio, taking every one of C 07.00's one-sided cells with them.
    """
    # Arrange
    recon = _combined(framework)

    # Act
    diff = cell_diff(recon.ours.source, recon.theirs.source, "c07_00")
    one_sided = diff.filter(pl.col("status").is_in(["ours_only", "theirs_only"]))

    # Assert — they exist, they read as empty (not unavailable), and every one
    # of them that is an additive money cell carries a decomposed delta.
    assert one_sided.height > 0
    states = set(one_sided["ours_state"].to_list()) | set(one_sided["theirs_state"].to_list())
    assert "empty" in states
    assert "unavailable" not in states
    decomposed = [
        decompose_cell(recon, "c07_00", row["sheet"], row["row_ref"], row["col_ref"])
        for row in one_sided.iter_rows(named=True)
    ]
    additive = [result for result in decomposed if result.decomposable]
    assert additive, "no one-sided C 07.00 cell decomposed — the finding is invisible"
    assert all(result.reconciles for result in additive)
    # A one-sided cell can legitimately be a measured 0.0 against an empty
    # counterpart; what must not happen is that NONE of them prices anything.
    assert any(abs(result.delta or 0.0) > 0.0 for result in additive)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_cell_whose_metric_source_one_side_lacks_is_refused(framework: str) -> None:
    """An unmapped carrier is 'cannot compute', never a legacy zero.

    C 08.03 column 0100 sums ``expected_loss``. A legacy mapping that does not
    supply it leaves the whole column blank; reporting that blank as 0.0 against
    our real EL would manufacture the largest delta on the sheet.
    """
    # Arrange
    base = _base_legs()
    our_source, _ = _sources(base, base, framework)
    their_source = _FrameSource(_ledger(base).drop("expected_loss"), framework)
    recon = build_recon(our_source, their_source)
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0100")

    # Assert
    assert result.theirs_state == "unavailable"
    assert result.ours_state == "figure"
    assert not result.decomposable
    assert "unavailable on theirs" in (result.refusal or "")
    assert result.delta is None
    diff = cell_diff(our_source, their_source, "c08_03", sheet=CORPORATE)
    unmeasurable = diff.filter((pl.col("row_ref") == row_ref) & (pl.col("col_ref") == "0100"))
    assert unmeasurable["status"][0] == "unmeasurable"
    assert unmeasurable["delta"][0] is None


# =============================================================================
# The false zero: a cell coverage says the mapping could not populate
# =============================================================================

# The sealed gross-side carriers AND every raw amount the generator could derive
# them from. Strip all of these and ``ensure_gross_side_carriers`` injects an
# all-null column, which ``col_sum`` sums to a confident 0.00.
_GROSS_SOURCES = (
    "reporting_gross_on_bs",
    "reporting_gross_off_bs",
    "reporting_gross_drawn",
    "reporting_gross_nominal",
    "reporting_gross_undrawn",
    "reporting_gross_interest",
    "drawn_amount",
    "interest",
    "nominal_amount",
    "undrawn_amount",
)


def _unmapped_gross(framework: str) -> tuple[_FrameSource, _FrameSource, object]:
    """Ours, theirs-without-any-gross-source, and theirs' coverage record."""
    base = _base_legs()
    our_source = _FrameSource(_ledger(base), framework)
    full = _ledger(base)
    present = set(full.collect_schema().names())
    stripped = full.drop([col for col in _GROSS_SOURCES if col in present])
    coverage = ledger_coverage(set(stripped.collect_schema().names()), framework=framework)
    return our_source, _FrameSource(stripped, framework), coverage


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_an_unpopulatable_cell_prints_a_zero_that_is_not_a_zero(framework: str) -> None:
    """The trap this guard exists for, measured on the generator itself.

    With neither the sealed gross carrier nor any raw source,
    ``ensure_gross_side_carriers`` injects an all-null column and ``col_sum``
    sums it to 0.00 rather than to null. So the legacy side prints a confident
    figure that means "not mapped". If this ever stops being true the guard
    below is testing nothing, so it is asserted here rather than assumed.
    """
    # Arrange
    our_source, their_source, coverage = _unmapped_gross(framework)

    # Act — no coverage passed: the raw, undefended comparison.
    naive = cell_diff(our_source, their_source, "c08_03", sheet=CORPORATE)
    cell = naive.filter((pl.col("col_ref") == "0010") & (pl.col("status") == "both"))

    # Assert — a printed 0.00 on their side against our real gross, and the
    # coverage record names exactly that column.
    assert cell.height > 0
    assert set(cell["theirs"].to_list()) == {0.0}
    assert cell["ours"].max() > 0.0
    assert "0010" in coverage.unavailable_refs("c08_03")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_coverage_makes_an_unpopulatable_cell_unavailable_not_zero(framework: str) -> None:
    """With the coverage record, the false zero becomes an honest blank."""
    # Arrange
    our_source, their_source, coverage = _unmapped_gross(framework)

    # Act
    diff = cell_diff(our_source, their_source, "c08_03", sheet=CORPORATE, theirs_coverage=coverage)
    guarded = diff.filter(pl.col("col_ref") == "0010")

    # Assert — unavailable on theirs, no figure carried, no delta computed.
    assert guarded.height > 0
    assert set(guarded["theirs_state"].to_list()) == {"unavailable"}
    assert set(guarded["status"].to_list()) == {"unmeasurable"}
    assert guarded["theirs"].null_count() == guarded.height
    assert guarded["delta"].null_count() == guarded.height
    # Our own side is untouched: the guard is about THEIR mapping.
    assert "figure" in set(guarded["ours_state"].to_list())


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_an_unpopulatable_cell_is_refused_not_attributed_to_measurement(framework: str) -> None:
    """The wrong answer this prevents is confident, and it is MEASUREMENT.

    Not a population term, which is the plausible guess and was wrong in this
    file's own prose until it was measured. Their side prints ``0.0`` for the
    very SAME keys we hold, so ``key in theirs`` is satisfied and every leg is
    classed present-on-both-with-a-different-value. That is the worse of the two
    wrong answers: ``measurement`` reads as "the same loans, valued
    differently" and sends an analyst hunting a modelling difference that does
    not exist, where a population term would at least have pointed at scope.

    The guard-OFF behaviour is asserted here rather than assumed, so neither
    assertion can go vacuous if the misattribution ever moves to another term.
    """
    # Arrange
    our_source, their_source, coverage = _unmapped_gross(framework)
    unguarded = build_recon(our_source, their_source)
    row_ref = _leaf_row_of(unguarded, ours=True, reference="BASE_A1")
    our_gross = unguarded.ours.frames["c08_03"][CORPORATE].filter(pl.col("row_ref") == row_ref)[
        "0010"
    ][0]
    assert our_gross > 0.0, "our own gross is zero here — the guard would be vacuous"

    # Act — the same cell, without the coverage record and then with it.
    wrong = decompose_cell(unguarded, "c08_03", CORPORATE, row_ref, "0010")
    guarded = build_recon(our_source, their_source, theirs_coverage=coverage)
    result = decompose_cell(guarded, "c08_03", CORPORATE, row_ref, "0010")

    # Assert — unguarded, the whole cell is a confident MEASUREMENT difference
    # against a printed zero that means "not mapped".
    assert wrong.decomposable
    assert wrong.theirs == 0.0
    assert wrong.amount("measurement") == pytest.approx(our_gross)
    assert wrong.amount("population_ours_only") == 0.0

    # Assert — guarded, refused with the mapping named and NOTHING attributed.
    assert result.theirs_state == "unavailable"
    assert not result.decomposable
    assert "cannot populate this column" in (result.refusal or "")
    assert result.terms == ()
    assert result.delta is None
    assert result.amount("measurement") == 0.0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_coverage_guards_every_named_cell_not_just_the_gross_carriers(framework: str) -> None:
    """The rule is "whatever coverage names", never a special case.

    The same stripped mapping takes out C 07.00 cols 0010/0020/0130/0140 and
    C 08.01's gross columns too; every one of them must read unavailable.
    """
    # Arrange
    our_source, their_source, coverage = _unmapped_gross(framework)
    recon = build_recon(our_source, their_source, theirs_coverage=coverage)

    # Act / Assert
    for template_id in ("c07_00", "c08_01", "c08_03"):
        named = set(coverage.unavailable_refs(template_id))
        assert named, f"{template_id} names no unavailable column — the check is vacuous"
        diff = diff_cells(recon, template_id)
        guarded = diff.filter(pl.col("col_ref").is_in(list(named)))
        assert guarded.height > 0
        assert set(guarded["theirs_state"].to_list()) == {"unavailable"}
        assert guarded["delta"].null_count() == guarded.height


def test_an_unarmed_legacy_projection_warns(caplog: pytest.LogCaptureFixture) -> None:
    """The guard is opt-in, so the one shape that silently reproduces the false
    zero — a projected legacy side with no coverage passed — must be loud.

    Pinned because ``build_recon`` cannot refuse it: a caller may legitimately
    hold no coverage record, and raising would break them. A WARNING is the
    strongest available move.
    """
    # Arrange — a real LegacyLedgerSource, which is what the isinstance keys on.
    base = _base_legs()
    legacy = LegacyLedgerSource(framework="CRR", ledger=_ledger(base))
    ours = _FrameSource(_ledger(base), "CRR")

    # Act
    with caplog.at_level(logging.WARNING, logger="rwa_calc.analysis.return_recon"):
        build_recon(ours, legacy, ["c08_03"])
    unarmed = [r for r in caplog.records if "no theirs_coverage" in r.message]

    # Assert — warned when unarmed, silent when armed.
    assert unarmed
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="rwa_calc.analysis.return_recon"):
        build_recon(
            ours,
            legacy,
            ["c08_03"],
            theirs_coverage=ledger_coverage(
                set(legacy.scan_results().collect_schema().names()), framework="CRR"
            ),
        )
    assert not [r for r in caplog.records if "no theirs_coverage" in r.message]


def test_cell_diff_refuses_two_sources_on_different_frameworks() -> None:
    # Arrange
    base = _base_legs()
    ours = _FrameSource(_ledger(base), "CRR")
    theirs = _FrameSource(_ledger(base), "BASEL_3_1")

    # Act / Assert
    with pytest.raises(ValueError, match="framework"):
        cell_diff(ours, theirs, "c08_03")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_identical_sides_diff_to_zero_everywhere(framework: str) -> None:
    """The identity case: same ledger both sides, nothing one-sided, no delta."""
    # Arrange
    base = _base_legs()
    our_source, their_source = _sources(base, base, framework)

    # Act
    diff = cell_diff(our_source, their_source, "c08_01")

    # Assert
    assert diff.height > 0
    assert diff.filter(pl.col("status").is_in(["ours_only", "theirs_only"])).height == 0
    assert diff.filter(pl.col("delta").abs() > 1e-9).height == 0


# =============================================================================
# The migration matrix
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_migration_diagonal_is_agreement_and_off_diagonal_is_the_moved_money(
    framework: str,
) -> None:
    # Arrange
    recon = _single_cause("row_placement", framework)
    predicate_key = _c08_03_predicate_key(recon)
    our_row = _leaf_row_of(recon, ours=True, reference="BAND_MOVER")
    their_row = _leaf_row_of(recon, ours=False, reference="BAND_MOVER")

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")

    # Assert — one off-diagonal cell, priced at the mover's EAD; the diagonal
    # holds every other leg and none of the moved money.
    off = matrix.filter(pl.col("movement_basis") == "value_driven")
    assert off.height == 1
    assert off["our_row_ref"][0] == our_row
    assert off["their_row_ref"][0] == their_row
    assert off["legs"][0] == 1
    assert off["money_ours"][0] == pytest.approx(_BAND_MOVER.ead)
    # Every other leg is on the diagonal or in the undecidable bucket; nothing
    # else moved. Bounded on BOTH sides so a lost leg cannot satisfy it.
    other = matrix.filter(pl.col("movement_basis").is_in(["agreed", "undecidable"]))
    assert other["legs"].sum() == matrix["legs"].sum() - 1
    diagonal = matrix.filter(pl.col("movement_basis") == "agreed")
    assert diagonal["money_ours"].sum() == pytest.approx(
        _distinct_leg_total(recon, ours=True, predicate_key=predicate_key)
        - _BAND_MOVER.ead
        - _BASE_NULL_PARENT.ead
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_migration_puts_one_sided_legs_in_the_absent_bucket(framework: str) -> None:
    # Arrange
    recon = _single_cause("population_ours_only", framework)
    predicate_key = _c08_03_predicate_key(recon)

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")

    # Assert
    absent = matrix.filter(pl.col("their_row_ref") == ABSENT_ROW)
    assert absent.height == 1
    assert absent["movement_basis"][0] == "ours_only"
    assert absent["money_ours"][0] == pytest.approx(_ONLY_OURS.ead)
    assert absent["money_theirs"][0] is None


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_leg_under_a_strict_parent_resolves_to_its_leaf_row(framework: str) -> None:
    """Excluding strict parents is what lets a leg RESOLVE to a row at all.

    Twice re-pointed, and both dead ends are worth recording because each looked
    like the obvious property:

    - "a NULL ``is_parent_row`` is never a leaf", citing ``fill_null(True)`` as
      the guard. Flipping ONLY that fill changes no membership group and reddens
      no test — ``_parent_flags`` emits ``None`` only for a row whose leg set
      another row holds exactly, so a NULL leg has zero or two-plus candidate
      leaves and routes to ``UNDECIDABLE_ROW`` either way.
    - "a strict parent row is never a placement". Also unfalsifiable: drop the
      parent filter entirely and legs land in ``UNDECIDABLE_ROW``, not on the
      parent, so the parent still never appears as a label.

    The property that DOES fail is this one. ``BASE_A1`` sits in parent row 0010
    and leaf row 0030; the parent exclusion is what leaves exactly one candidate,
    so it resolves to 0030. Without it the leg has two candidates and the matrix
    cannot place it at all — asserting PLACEMENT rather than absence is the whole
    point.

    Under the flag-ignored mutation (drop the ``is_parent_row`` filter, keep the
    single-leaf rule) seven parametrisations redden, and these are all of them —
    each name measured, not assumed:

    - ``test_a_leg_under_a_strict_parent_resolves_to_its_leaf_row`` (this one)
    - ``test_a_leg_with_no_decidable_leaf_row_is_bucketed_not_dropped``
    - ``test_migration_diagonal_is_agreement_and_off_diagonal_is_the_moved_money``
    - ``test_every_result_carries_the_placement_attribution_caveat``

    Note what is NOT in that list: ``parent_rows.isdisjoint(placed)`` below. It
    holds in both states, so it is a reader's aid and never the detector.
    """
    # Arrange
    recon = _combined(framework)
    predicate_key = _c08_03_predicate_key(recon)
    legs = recon.ours.membership.legs.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == CORPORATE)
        & (pl.col("predicate_key") == predicate_key)
        & (pl.col("exposure_reference") == "BASE_A1")
    )
    parents = set(legs.filter(pl.col("is_parent_row").fill_null(value=False))["row_ref"])
    leaf_row = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")
    placed = matrix.filter(pl.col("our_row_ref") == leaf_row)

    # Assert — the leg really is under a strict parent, and still resolves.
    assert parents, "BASE_A1 sits under no strict parent — the guard is vacuous"
    assert leaf_row not in parents
    assert placed.height > 0
    assert placed["movement_basis"].to_list() != [UNDECIDABLE_ROW]
    # A consequence of the single-leaf rule, not the detector: a parent row is
    # never a label. Kept for the reader, not relied on as a guard.
    assert parents.isdisjoint(set(matrix["our_row_ref"].to_list()))


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_migration_money_equals_the_groups_distinct_leg_total(framework: str) -> None:
    """The matrix conserves money — measured against DISTINCT LEGS, both sides.

    Deliberately NOT against a ``~is_parent_row`` row sum, which is the figure
    the matrix is built to be safe from: that sum over-counts a leg held by a
    parent and its child, and collapses to 0.00 on a group where no row is a
    decidable leaf. The independent figure is the group's distinct keys, which
    no parent flag can inflate or empty. Asserted as an EQUALITY on each side —
    a one-sided ``<=`` is satisfied by total loss.
    """
    # Arrange
    recon = _combined(framework)
    predicate_key = _c08_03_predicate_key(recon)

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")

    # Assert
    for ours in (True, False):
        column = "money_ours" if ours else "money_theirs"
        expected = _distinct_leg_total(recon, ours=ours, predicate_key=predicate_key)
        assert expected > 0.0, "the group holds no money — the conservation check is vacuous"
        assert matrix[column].sum() == pytest.approx(expected)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_leg_with_no_decidable_leaf_row_is_bucketed_not_dropped(framework: str) -> None:
    """The "total loss" mode: an empty filter is not a zero.

    ``BASE_NULL_PARENT`` is the only corporate leg in PD band 2.5-<10%, so its
    parent row 0100 and its child row 0110 hold exactly the same legs and BOTH
    come back ``is_parent_row = None``. A consumer filtering ``~is_parent_row``
    loses the leg outright — measured here at 1,400,000 silently missing before
    this bucket existed, and at 0.00 against whole sheets in the review fixture.
    """
    # Arrange
    recon = _combined(framework)
    predicate_key = _c08_03_predicate_key(recon)

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")
    undecidable = matrix.filter(pl.col("movement_basis") == "undecidable")

    # Assert — the leg is present, priced, labelled, and the axis says so.
    assert undecidable.height == 1
    assert undecidable["our_row_ref"][0] == UNDECIDABLE_ROW
    assert undecidable["their_row_ref"][0] == UNDECIDABLE_ROW
    assert undecidable["money_ours"][0] == pytest.approx(_BASE_NULL_PARENT.ead)
    assert not bool(matrix["axis_is_partition"][0])


def _distinct_leg_total(recon: ReturnRecon, *, ours: bool, predicate_key: str) -> float:
    """The group's money over DISTINCT legs — derived without any parent flag."""
    side = recon.ours if ours else recon.theirs
    legs = side.membership.legs.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == CORPORATE)
        & (pl.col("predicate_key") == predicate_key)
    ).unique(subset=["exposure_reference"])
    return float(legs["ead_final"].sum())


def test_migration_refuses_a_money_column_membership_does_not_carry() -> None:
    # Arrange
    recon = _combined("CRR")
    predicate_key = _c08_03_predicate_key(recon)

    # Act / Assert
    with pytest.raises(ValueError, match="money_column"):
        row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="pd_floored")


# =============================================================================
# Scope and hygiene
# =============================================================================


def test_an_uninstrumented_template_is_refused_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    base = _base_legs()
    our_source, their_source = _sources(base, base, "CRR")

    # Act
    with caplog.at_level(logging.WARNING, logger="rwa_calc.analysis.return_recon"):
        diff = cell_diff(our_source, their_source, "c99_99")

    # Assert
    assert diff.height == 0
    assert diff.schema == CELL_DIFF_SCHEMA
    assert any("not instrumented" in record.message for record in caplog.records)

    # And the decomposition refuses it rather than guessing a row set.
    recon = build_recon(our_source, their_source)
    refused = decompose_cell(recon, "c99_99", CORPORATE, "0010", "0040")
    assert not refused.decomposable
    assert "not instrumented" in (refused.refusal or "")


def test_every_result_carries_the_placement_attribution_caveat() -> None:
    """A value-driven matrix must never be readable as evidence about a RULE.

    Both sides are banded by our own generators, so the caveat is a property of
    the method, not of a portfolio — it therefore rides on the result itself and
    not only in a docstring a consumer will not read.
    """
    # Arrange
    recon = _combined("CRR")
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")
    predicate_key = _c08_03_predicate_key(recon)

    # Act
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0040")
    refused = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0050")
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")

    # Assert — on the decomposition (refusals included) and on every matrix row.
    assert result.attribution == PLACEMENT_ATTRIBUTION
    assert refused.attribution == PLACEMENT_ATTRIBUTION
    assert "RULE-driven" in PLACEMENT_ATTRIBUTION
    # Anchored on the module's own published vocabulary rather than on a list
    # typed here: a hand-written set has to be edited every time a basis is
    # added, and the edit that forgets is exactly the one nobody notices.
    assert set(matrix["movement_basis"].to_list()) <= set(MOVEMENT_BASES)
    assert "value_driven" in matrix["movement_basis"].to_list()


def _c08_03_predicate_key(recon: ReturnRecon) -> str:
    """The predicate group serving C 08.03 column 0040 on the corporate sheet."""
    served = recon.ours.membership.columns.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == CORPORATE)
        & (pl.col("col_ref") == "0040")
    )
    assert served.height > 0, "C 08.03 column 0040 is not row-backed on the corporate sheet"
    return str(served["predicate_key"][0])


# =============================================================================
# A split exposure against the legacy whole loan
# =============================================================================

#: C 08.03's RWEA column — ``Sum(rwa_col)``, the plainest additive money cell on
#: the sheet, so its figures are the leg amounts and nothing else.
RWEA_COL = "0090"

#: The PD band the split exposure is planted in. ``_split_base`` deliberately
#: leaves it empty, so the cell under test holds that exposure ALONE and its
#: reported figure can be read straight off the legs.
SPLIT_PD = 0.0100

#: One guaranteed loan as OUR sealed ledger holds it: a guarantee leg and a
#: remainder leg, each carrying the pre-split reference on
#: ``source_exposure_reference`` (``engine/hierarchy/unify.py``). Split 60/40 so
#: that neither leg alone can be mistaken for the whole.
_SPLIT_G_LEG = _Leg("L1__G_BANK", source="L1", pd=SPLIT_PD, ead=600_000.0, rwa=60_000.0)
_SPLIT_REM_LEG = _Leg("L1__REM", source="L1", pd=SPLIT_PD, ead=400_000.0, rwa=40_000.0)

#: The SAME loan as their extract holds it — one whole leg under the original
#: reference, worth exactly what our two legs are worth together.
_WHOLE_LOAN = _Leg("L1", pd=SPLIT_PD, ead=1_000_000.0, rwa=100_000.0)


def _split_base() -> list[_Leg]:
    """Agreeing legs whose bands make the split exposure's row a decidable leaf.

    ``is_parent_row`` is MEASURED, so a parent band with a single populated
    child is indistinguishable from a leaf and comes back NULL. Parent 0010 gets
    two populated children and parent 0070 gets one filler — which leaves 0070's
    OTHER child row for the split exposure, so that row holds the exposure under
    test and nothing else.
    """
    return [
        _Leg("SPLIT_FILL_A0", pd=0.0005, ead=900_000.0, rwa=270_000.0),
        _Leg("SPLIT_FILL_A1", pd=PD_BAND_A, ead=1_000_000.0, rwa=300_000.0),
        _Leg("SPLIT_FILL_B1", pd=PD_BAND_B, ead=2_000_000.0, rwa=800_000.0),
    ]


def _legacy(legs: list[_Leg]) -> list[_Leg]:
    """Their side with no base reference on any leg — the PRESENT-BUT-NULL form.

    That is the shape ``_side_keys`` sees in production, because
    ``MEMBERSHIP_SCHEMA`` always gives the membership legs the column and fills
    it with a typed null. It is NOT the shape ``_key_money`` sees: the plan
    frame is the projection's own columns and the base reference is absent from
    it outright. Use ``_legacy_frame`` for that half — the two are different
    branches of ``_key_rungs`` and both run on every real reconciliation.
    """
    return [replace(leg, supplies_source_ref=False) for leg in legs]


def _legacy_frame(legs: list[_Leg]) -> pl.LazyFrame:
    """Their side's FRAME as ``project_legacy_ledger`` really emits it: the base
    reference column is ABSENT, not null.

    ``_ledger`` pins ``source_exposure_reference`` into ``schema_overrides``, so
    every other fixture here supplies the column even when its value is null.
    A projection never does: ``_projection_exprs`` emits the join key, the
    mapped components and the mapped carriers, and the base reference is none of
    the three. Measured on a real ``project_legacy_ledger``, its ledger columns
    are the join key, the two sealed origin columns and the mapped money — no
    base reference anywhere.
    """
    return _ledger(legs).drop(recon_module._BASE_KEY_COLUMN, strict=False)


def _split_recon(
    ours: list[_Leg],
    theirs: list[_Leg],
    framework: str,
    *,
    key_column: str = "exposure_reference",
    theirs_supplies_base_ref: bool = False,
) -> ReturnRecon:
    """Both sides over the shared agreeing base, at the DEFAULT join key.

    ``key_column`` defaults to the setting production runs on —
    ``ui/views/return_recon.py::build_comparison`` never passes one — and is
    overridable only so the two members of ``KEY_COLUMNS`` can be compared.

    ``theirs_supplies_base_ref`` defaults to the shape a real projection emits
    (no base reference at all). Set it True to isolate the effect of
    ``key_column`` from the effect of that absence: they are different causes,
    and the equivalence test asserts over BOTH values precisely because the
    answer must not depend on either.
    """
    base = _split_base()
    their_legs = [*base, *theirs]
    our_source, their_source = _sources(
        [*base, *ours],
        their_legs if theirs_supplies_base_ref else _legacy(their_legs),
        framework,
    )
    return build_recon(our_source, their_source, key_column=key_column)


def _population_offenders(
    recon: ReturnRecon, template_id: str = "c08_03", sheet: str | None = CORPORATE
) -> list[str]:
    """Every cell of one template (or one sheet of it) reporting a population term."""
    diff = cell_diff(recon.ours.source, recon.theirs.source, template_id, sheet=sheet)
    offenders: list[str] = []
    for row in diff.iter_rows(named=True):
        result = decompose_cell(recon, template_id, row["sheet"], row["row_ref"], row["col_ref"])
        if not result.decomposable:
            continue
        terms = _terms(result)
        ours_only = terms["population_ours_only"]
        theirs_only = terms["population_theirs_only"]
        if ours_only or theirs_only:
            offenders.append(
                f"{row['sheet']}/{row['row_ref']}/{row['col_ref']} "
                f"ours_only={ours_only:,.2f} theirs_only={theirs_only:,.2f}"
            )
    return offenders


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_split_exposure_pairs_against_the_legacy_whole_loan(framework: str) -> None:
    """Two legs of one loan are ONE exposure and must pair with their whole loan.

    Our sealed ledger splits a guaranteed loan into ``L1__G_BANK`` and
    ``L1__REM``, each carrying the pre-split reference on
    ``source_exposure_reference``. Their extract carries the original loan under
    ``L1`` and supplies no base reference at all, because
    ``source_exposure_reference`` is neither a component nor a carrier in
    ``recon_registry`` — the projection never emits it and it arrives as a typed
    NULL.

    Keyed on ``exposure_reference`` alone the two sides therefore share NO key,
    and a cell where both engines agree TO THE PENNY reports GBP 100,000 of
    exposures missing from each side. The additivity contract cannot see it: the
    four buckets partition each side's population, so two equal and opposite
    population terms sum to the same 0.00 as no terms at all and
    ``reconciles`` stays true. This assertion is the only thing on the path
    that can distinguish them, so it is stated on the terms and NOT on the
    residual.
    """
    # Arrange
    recon = _split_recon([_SPLIT_G_LEG, _SPLIT_REM_LEG], [_WHOLE_LOAN], framework)
    row_ref = _leaf_row_of(recon, ours=False, reference=_WHOLE_LOAN.reference)
    assert row_ref == _leaf_row_of(recon, ours=True, reference=_SPLIT_G_LEG.reference)
    assert row_ref == _leaf_row_of(recon, ours=True, reference=_SPLIT_REM_LEG.reference)

    # Act
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    terms = _terms(result)
    keys = _term_keys(result)

    # Assert — the sheet is emitted on both sides and the cell carries a real
    # figure on each: a null and a legitimate zero are different claims.
    assert CORPORATE in recon.ours.frames["c08_03"]
    assert CORPORATE in recon.theirs.frames["c08_03"]
    assert result.decomposable, result.refusal
    assert (result.ours_state, result.theirs_state) == ("figure", "figure")
    assert result.ours == pytest.approx(_SPLIT_G_LEG.rwa + _SPLIT_REM_LEG.rwa)
    assert result.theirs == pytest.approx(_WHOLE_LOAN.rwa)
    assert result.delta == pytest.approx(0.0)

    # Assert — the agreement is REPORTED as agreement: nothing missing on
    # either side, and the one exposure paired on a single shared key.
    assert terms["population_ours_only"] == 0.0
    assert terms["population_theirs_only"] == 0.0
    assert keys["population_ours_only"] == 0
    assert keys["population_theirs_only"] == 0
    assert keys["measurement"] == 1
    assert result.reconciles

    # Assert — and it does not leak anywhere else: on a portfolio the two sides
    # agree about exactly, NO cell of the sheet may report a population at all.
    assert _population_offenders(recon) == []


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_split_exposures_legs_are_summed_not_picked(framework: str) -> None:
    """When the money genuinely differs, the whole difference is MEASUREMENT.

    The same split loan, worth 60,000 + 40,000 on our side against 130,000 on
    theirs. Pairing the legs is not enough — the pair has to be priced as the
    SUM of our legs: picking either one alone would report -70,000 or -90,000,
    and collapsing one leg while leaving the other behind would put money back
    into a population term. Only -30,000 with both population terms empty is
    consistent with summing.
    """
    # Arrange
    recon = _split_recon(
        [_SPLIT_G_LEG, _SPLIT_REM_LEG], [replace(_WHOLE_LOAN, rwa=130_000.0)], framework
    )
    row_ref = _leaf_row_of(recon, ours=False, reference=_WHOLE_LOAN.reference)

    # Act
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    terms = _terms(result)
    keys = _term_keys(result)

    # Assert
    assert result.decomposable, result.refusal
    assert result.delta == pytest.approx(-30_000.0)
    assert terms["measurement"] == pytest.approx(-30_000.0)
    assert keys["measurement"] == 1
    assert terms["population_ours_only"] == 0.0
    assert terms["population_theirs_only"] == 0.0
    assert keys["population_ours_only"] == 0
    assert keys["population_theirs_only"] == 0
    assert result.reconciles


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_split_legs_in_different_rows_are_not_merged_across_them(framework: str) -> None:
    """Pairing collapses legs WITHIN a group, never across rows.

    A two-leg substitution can send the two halves of one exposure to different
    rows — here the guarantee leg keeps the borrower's band while the remainder
    leg moves. If the pairing merged them, our 60,000 row would price the whole
    100,000 and the cell's four terms would stop summing to its reported delta,
    so ``reconciles`` is asserted alongside the amounts rather than left to the
    additivity census on another portfolio.

    The exposure is then correctly BOTH things at once: a measurement
    difference in the row both sides use, and a row placement in the row only we
    use. The two net to zero across the sheet — the loan's money is neither
    created nor destroyed by being split.
    """
    # Arrange
    ours = [
        replace(_SPLIT_G_LEG, reference="L2__G_BANK", source="L2"),
        replace(_SPLIT_REM_LEG, reference="L2__REM", source="L2", pd=PD_BAND_B),
    ]
    recon = _split_recon(ours, [replace(_WHOLE_LOAN, reference="L2")], framework)
    shared_row = _leaf_row_of(recon, ours=False, reference="L2")
    our_other_row = _leaf_row_of(recon, ours=True, reference="L2__REM")
    assert shared_row == _leaf_row_of(recon, ours=True, reference="L2__G_BANK")
    assert our_other_row != shared_row, "both legs are in one row — the fixture is vacuous"

    # Act
    shared = decompose_cell(recon, "c08_03", CORPORATE, shared_row, RWEA_COL)
    other = decompose_cell(recon, "c08_03", CORPORATE, our_other_row, RWEA_COL)

    # Assert — the row both sides use prices OUR LEG ONLY against their whole
    # loan; the merged reading would have made this term 0.00 and broken the
    # identity against the reported -40,000.
    assert shared.ours == pytest.approx(_SPLIT_G_LEG.rwa)
    assert _terms(shared)["measurement"] == pytest.approx(_SPLIT_G_LEG.rwa - _WHOLE_LOAN.rwa)
    assert _terms(shared)["row_placement"] == 0.0
    assert _terms(shared)["population_ours_only"] == 0.0
    assert _terms(shared)["population_theirs_only"] == 0.0
    assert shared.reconciles

    # Assert — the row only we use is a PLACEMENT, not a population: the leg is
    # elsewhere on their sheet, which is a different finding from absent.
    assert _terms(other)["row_placement"] == pytest.approx(_SPLIT_REM_LEG.rwa)
    assert _terms(other)["population_ours_only"] == 0.0
    assert _terms(other)["population_theirs_only"] == 0.0
    assert other.reconciles

    # Assert — and the two together conserve the exposure.
    assert sum(_terms(shared).values()) + sum(_terms(other).values()) == pytest.approx(0.0)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_an_unsplit_exposure_still_pairs_on_its_own_reference(framework: str) -> None:
    """The ordinary case, and the reason the base reference cannot be the key.

    This one is green today and must STAY green. It is what rules out keying on
    ``source_exposure_reference`` alone: their side has none — the projection
    supplies no such column — so that reading would drop every legacy leg and
    turn every cell on the sheet into two equal and opposite population terms,
    trading the defect under test for a larger one.
    """
    # Arrange — one whole loan on each side, ours 100,000 against theirs 130,000.
    unsplit = _Leg("U1", pd=SPLIT_PD, ead=1_000_000.0, rwa=100_000.0)
    recon = _split_recon([unsplit], [replace(unsplit, rwa=130_000.0)], framework)
    row_ref = _leaf_row_of(recon, ours=True, reference="U1")

    # Act
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    terms = _terms(result)

    # Assert
    assert result.decomposable, result.refusal
    assert terms["measurement"] == pytest.approx(-30_000.0)
    assert _term_keys(result)["measurement"] == 1
    assert terms["population_ours_only"] == 0.0
    assert terms["population_theirs_only"] == 0.0
    assert result.reconciles


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_migration_matrix_conserves_a_split_exposures_money(framework: str) -> None:
    """The conservation invariant, on a portfolio that actually HAS split legs.

    ``test_migration_money_equals_the_groups_distinct_leg_total`` states this
    same equality and CANNOT detect the hazard it exists for. It runs on
    ``_combined``, where every leg is its own base — ``_base_legs`` and all five
    cause legs leave ``source`` unset — so collapsing the matrix's key there is a
    no-op and the assertion holds either way. Measured: keying ``_group_legs`` on
    the base reference reddens NOTHING across either suite. The fixture was the
    gap, not the test.

    The hazard is specific and one-directional. ``_group_legs`` prices each key
    with ``pl.col(money_column).first()``, because one leg legitimately appears
    on several ROWS of a group and summing would count it once per row. Collapse
    two DISTINCT legs onto one base key and ``.first()`` keeps one leg's money
    and silently discards the other's: the matrix still balances internally,
    still renders, and is short by the discarded leg. Only an equality against a
    figure derived WITHOUT the key can see it — which is what
    ``_distinct_leg_total`` is, anchored on ``exposure_reference`` and never
    reading ``recon.key_column``.

    Stated as an equality on EACH side; a one-sided ``<=`` is satisfied by total
    loss.
    """
    # Arrange
    recon = _split_recon([_SPLIT_G_LEG, _SPLIT_REM_LEG], [_WHOLE_LOAN], framework)
    predicate_key = _c08_03_predicate_key(recon)
    our_legs = recon.ours.membership.legs.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == CORPORATE)
        & (pl.col("predicate_key") == predicate_key)
    ).unique(subset=["exposure_reference"])

    # Assert the premise, because its ABSENCE is what made the sibling vacuous:
    # the group must hold two distinct legs of one base exposure, priced
    # differently, so that keeping either one alone is detectable.
    bases = our_legs["source_exposure_reference"].to_list()
    assert bases.count(_WHOLE_LOAN.reference) == 2, (
        f"the group holds no split exposure ({bases}) — collapsing the key would "
        "be a no-op and this test would prove nothing"
    )
    assert _SPLIT_G_LEG.ead != _SPLIT_REM_LEG.ead, "equal legs make .first() undetectable"

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")

    # Assert — the matrix's money is the group's distinct-leg total, each side.
    for ours in (True, False):
        column = "money_ours" if ours else "money_theirs"
        expected = _distinct_leg_total(recon, ours=ours, predicate_key=predicate_key)
        assert expected > 0.0, "the group holds no money — the check is vacuous"
        assert matrix[column].sum() == pytest.approx(expected), column


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_side_whose_frame_omits_the_base_reference_can_still_be_keyed(framework: str) -> None:
    """A projected legacy frame does not CARRY the base-reference column at all.

    Null and absent are different claims, and only one of them is what a
    projection produces. ``MEMBERSHIP_SCHEMA`` gives the membership legs a typed
    NULL, so ``_side_keys`` never notices; but the PLAN frame is the projection's
    own columns, and ``source_exposure_reference`` is simply not among them —
    ``_projection_exprs`` emits the join key, the mapped components and the
    mapped carriers, and that column is none of the three.

    So the ladder must be narrowed to the columns a frame actually has. Without
    that filter ``_key_money``'s ``group_by`` raises ``ColumnNotFoundError`` on
    every legacy comparison — measured, and it is a RAISE rather than a silent
    degradation, so the whole cell comparison dies rather than reporting a wrong
    number.

    Nothing else in this file reaches the absent case: ``_Leg.row`` always writes
    the column and ``_ledger`` pins its dtype, so every other fixture supplies it
    even when the value is null. **Both shapes are live on the same side at
    once** — instrumenting a real reconciliation records the column PRESENT at
    ``_side_keys`` and ABSENT at ``_key_money``, per legacy-side call — so this
    is not an exotic variant but the ordinary production configuration, and it
    is also where the split exposure has to pair for the batch's own fix to
    reach production at all.
    """
    # Arrange — their frame WITHOUT the column, as a real projection is.
    base = _split_base()
    their_legs = _legacy([*base, _WHOLE_LOAN])
    our_source, _ = _sources([*base, _SPLIT_G_LEG, _SPLIT_REM_LEG], their_legs, framework)
    their_source = _FrameSource(_legacy_frame(their_legs), framework)

    # Assert the premise: absent from the frame, present-but-null on membership.
    their_columns = their_source.scan_results().collect_schema().names()
    assert recon_module._BASE_KEY_COLUMN not in their_columns
    assert _FALLBACK_IDENTITY in their_columns, "their frame carries no identity at all"
    recon = build_recon(our_source, their_source)
    their_membership = recon.theirs.membership.legs
    assert recon_module._BASE_KEY_COLUMN in their_membership.columns
    assert their_membership[recon_module._BASE_KEY_COLUMN].null_count() == their_membership.height

    # Act — this is the call that raises when the ladder is not filtered.
    row_ref = _leaf_row_of(recon, ours=False, reference=_WHOLE_LOAN.reference)
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)

    # Assert — the comparison completes, and the split exposure still pairs on
    # the rung their frame does carry.
    assert result.decomposable, result.refusal
    assert _terms(result)["population_ours_only"] == 0.0
    assert _terms(result)["population_theirs_only"] == 0.0
    assert _term_keys(result)["measurement"] == 1
    assert result.reconciles


# =============================================================================
# The same, on the STANDARDISED template
# =============================================================================
#
# C 07.00 excludes IRB legs entirely, so every test above is silent about it:
# the split fixtures are all ``foundation_irb``, and the before/after census of
# the fix measured 0.00 on every term of ``c07_00`` under both frameworks —
# vacuous, not clean. That is the same escape class as the defect itself, one
# level down: the gate ran and no exposure reached the code. These tests put a
# STANDARDISED split exposure on the sheet so it is measured there too.

#: C 07.00's post-substitution RWEA — ``Sum(rwa_col)``, an additive money cell.
#: The post basis is the one a split exposure's money actually lands on.
C07_RWEA_COL = "0220"

#: A neutral third sheet, so neither split scenario is measured on a
#: single-sheet portfolio.
_SA_FILL_INST = _Leg(
    "SA_FILL_INST",
    exposure_class="institution",
    approach="standardised",
    pd=None,
    cqs=2,
    ead=800_000.0,
    rwa=160_000.0,
)

#: A corporate leg both sides hold, present only so BOTH sides emit the
#: corporate sheet in the real-estate scenario — where the residual leg is the
#: only corporate exposure we hold and they hold none at all. Without it the
#: half of that exposure we report on the corporate sheet would be measured
#: against an unemitted sheet, which is a different finding.
_SA_FILL_CORP = _Leg(
    "SA_FILL_CORP", approach="standardised", pd=None, cqs=3, ead=1_500_000.0, rwa=1_500_000.0
)

#: The canonical SA split, in its SINGLE-COMPONENT form — one property, so the
#: splitter emits a ``_sec`` leg and a ``_res`` leg (``re_split/splitter.py``
#: :713 and :757). The MIXED form suffixes ``_rre`` / ``_cre`` instead (:712)
#: and emits a pair of secured legs; it is a different scenario and these names
#: would be wrong for it. ``splitter.py`` reclassifies the secured portion to
#: ``RESIDENTIAL_MORTGAGE`` and leaves the residual on the counterparty's own
#: class, so ONE exposure legitimately lands on TWO C 07.00 sheets. Their
#: extract reports the whole loan on the mortgage sheet at the blended weight;
#: the legs are worth exactly what it is worth.
_RE_SECURED = _Leg(
    "M1_sec",
    source="M1",
    exposure_class="residential_mortgage",
    approach="standardised",
    pd=None,
    cqs=3,
    ead=600_000.0,
    rwa=210_000.0,
)
_RE_RESIDUAL = _Leg(
    "M1_res", source="M1", approach="standardised", pd=None, cqs=3, ead=400_000.0, rwa=400_000.0
)
_RE_WHOLE = _Leg(
    "M1",
    exposure_class="residential_mortgage",
    approach="standardised",
    pd=None,
    cqs=3,
    ead=1_000_000.0,
    rwa=610_000.0,
)

#: A facility split (``engine/hierarchy/facility_undrawn.py``): same obligor,
#: same class, same risk weight, so both legs share the mortgage-free corporate
#: sheet AND its 100% band row. This is the shape that gives C 07.00 the
#: single-cell claim the real-estate split cannot.
_FAC_DRAWN = _Leg("FAC1", approach="standardised", pd=None, cqs=3, ead=700_000.0, rwa=700_000.0)
_FAC_UNDRAWN = _Leg(
    "FAC1_UNDRAWN",
    source="FAC1",
    approach="standardised",
    exposure_type="facility_undrawn",
    pd=None,
    cqs=3,
    undrawn=600_000.0,
    ead=300_000.0,
    rwa=300_000.0,
)
_FAC_WHOLE = _Leg("FAC1", approach="standardised", pd=None, cqs=3, ead=1_000_000.0, rwa=1_000_000.0)


def _sa_recon(ours: list[_Leg], theirs: list[_Leg], framework: str) -> ReturnRecon:
    """Both sides of a STANDARDISED portfolio, at the default join key."""
    our_source, their_source = _sources(
        [_SA_FILL_INST, *ours], _legacy([_SA_FILL_INST, *theirs]), framework
    )
    return build_recon(our_source, their_source)


def _c07_populations(
    recon: ReturnRecon, sheet: str, col_ref: str, *, ours: bool
) -> dict[str, frozenset[str]]:
    """``row_ref -> the leg references one side's population for that cell holds``.

    Addressed through ``CellMembership.columns``, never by row: a C 07.00 row
    carries several populations at once — the origin basis, the
    post-substitution basis, the CCF buckets — and only the column says which
    one a given cell reads.
    """
    side = recon.ours if ours else recon.theirs
    served = side.membership.columns.filter(
        (pl.col("template_id") == "c07_00")
        & (pl.col("sheet") == sheet)
        & (pl.col("col_ref") == col_ref)
    )
    assert served.height > 0, f"C 07.00 {sheet} col {col_ref} is not row-backed"
    legs = side.membership.legs.filter(
        (pl.col("template_id") == "c07_00") & (pl.col("sheet") == sheet)
    )
    populations: dict[str, frozenset[str]] = {}
    for row_ref, predicate_key in served.select("row_ref", "predicate_key").unique().iter_rows():
        group = legs.filter(
            (pl.col("row_ref") == row_ref) & (pl.col("predicate_key") == predicate_key)
        )
        populations[row_ref] = frozenset(group["exposure_reference"].to_list())
    return populations


def _c07_whole_sheet_rows(recon: ReturnRecon, sheet: str, col_ref: str) -> list[str]:
    """The rows on which BOTH sides report their whole population of a sheet.

    Derived, never a literal: C 07.00's row axis is 33 groups under CRR and 61
    under Basel 3.1, and a hard-coded ref would pin one of them. A row holding
    everything both sides hold is where two portfolios that agree in total must
    agree in the cell — the Total row and, when every leg shares a weight, its
    risk-weight band too. Returned as a list and asserted on all of them, so the
    claim is not quietly narrowed to whichever row happened to be first.
    """
    ours = _c07_populations(recon, sheet, col_ref, ours=True)
    theirs = _c07_populations(recon, sheet, col_ref, ours=False)
    all_ours = frozenset().union(*ours.values()) if ours else frozenset()
    all_theirs = frozenset().union(*theirs.values()) if theirs else frozenset()
    assert all_ours, f"we report nothing on {sheet} — the scenario is vacuous"
    assert all_theirs, f"they report nothing on {sheet} — the scenario is vacuous"
    return sorted(
        row_ref
        for row_ref, members in ours.items()
        if members == all_ours and theirs.get(row_ref) == all_theirs
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_standardised_re_split_pairs_against_the_legacy_whole_loan(framework: str) -> None:
    """The canonical SA split, on the SA template — and it spans two sheets.

    Modelled on the SINGLE-COMPONENT case (``_sec`` + ``_res``), not the mixed
    RRE+CRE one (``_rre`` + ``_cre``) — see ``_RE_SECURED``.
    ``engine/re_split/splitter.py`` reclassifies the secured portion to
    ``RESIDENTIAL_MORTGAGE`` and leaves the residual on the counterparty's own
    class, so one exposure lands on the mortgage sheet AND the corporate sheet.
    Their extract reports it whole, on one sheet, under the original reference.

    So the honest answer here is NOT "wholly in measurement" — half the money is
    on a sheet they do not use it on, which is a placement, and asserting
    otherwise would be asserting the wrong thing. What must be true is that
    NEITHER half reports a population: the exposure is on both returns, and
    saying it is missing from each is the wrong number this closes. The two
    halves must then net to zero, because our legs are worth exactly what their
    whole loan is worth.
    """
    # Arrange — the fixture's own premise, stated before it is relied on.
    assert _RE_SECURED.rwa + _RE_RESIDUAL.rwa == pytest.approx(_RE_WHOLE.rwa)
    recon = _sa_recon(
        [_SA_FILL_CORP, _RE_SECURED, _RE_RESIDUAL], [_SA_FILL_CORP, _RE_WHOLE], framework
    )
    mortgage_rows = _c07_whole_sheet_rows(recon, "residential_mortgage", C07_RWEA_COL)
    corporate_rows = _c07_whole_sheet_rows(recon, CORPORATE, C07_RWEA_COL)
    assert mortgage_rows and corporate_rows

    # Assert — both sheets are EMITTED on both sides. A split exposure measured
    # against a sheet one side never emits is a different finding.
    assert {"residential_mortgage", CORPORATE} <= set(recon.ours.frames["c07_00"])
    assert {"residential_mortgage", CORPORATE} <= set(recon.theirs.frames["c07_00"])

    for row_ref in mortgage_rows:
        # Act — the half they report the whole loan on.
        secured = decompose_cell(recon, "c07_00", "residential_mortgage", row_ref, C07_RWEA_COL)
        terms = _terms(secured)

        # Assert — a figure on each side, paired on one key, nothing missing.
        assert secured.decomposable, secured.refusal
        assert (secured.ours_state, secured.theirs_state) == ("figure", "figure")
        assert secured.ours == pytest.approx(_RE_SECURED.rwa)
        assert secured.theirs == pytest.approx(_RE_WHOLE.rwa)
        assert terms["population_ours_only"] == 0.0
        assert terms["population_theirs_only"] == 0.0
        assert _term_keys(secured)["measurement"] == 1
        assert secured.reconciles

    for row_ref in corporate_rows:
        # Act — the half only we report there.
        residual = decompose_cell(recon, "c07_00", CORPORATE, row_ref, C07_RWEA_COL)
        terms = _terms(residual)

        # Assert — a PLACEMENT, priced at the residual leg, not a population.
        assert residual.decomposable, residual.refusal
        assert (residual.ours_state, residual.theirs_state) == ("figure", "figure")
        assert terms["sheet_placement"] == pytest.approx(_RE_RESIDUAL.rwa)
        assert terms["population_ours_only"] == 0.0
        assert terms["population_theirs_only"] == 0.0
        assert residual.reconciles

    # Assert — the two halves net to zero, and no cell of the template anywhere
    # reports a population.
    left = _terms(
        decompose_cell(recon, "c07_00", "residential_mortgage", mortgage_rows[0], C07_RWEA_COL)
    )
    right = _terms(decompose_cell(recon, "c07_00", CORPORATE, corporate_rows[0], C07_RWEA_COL))
    assert sum(left.values()) + sum(right.values()) == pytest.approx(0.0)
    assert _population_offenders(recon, "c07_00", None) == []


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_standardised_split_sharing_one_c07_cell_reports_agreement(framework: str) -> None:
    """A facility split keeps both legs in ONE cell — so agreement is provable.

    Same obligor, same class, same risk weight: the drawn half and the undrawn
    half share the corporate sheet and its 100% band, which is the shape the
    real-estate split cannot give C 07.00. Their extract holds the facility
    whole and for the same money, so every term must be zero and the pairing
    must be VISIBLE — one key in ``measurement``, not an empty bucket, which is
    what distinguishes "paired and agreed" from "never compared".
    """
    # Arrange
    assert _FAC_DRAWN.rwa + _FAC_UNDRAWN.rwa == pytest.approx(_FAC_WHOLE.rwa)
    recon = _sa_recon([_FAC_DRAWN, _FAC_UNDRAWN], [_FAC_WHOLE], framework)
    shared_rows = _c07_whole_sheet_rows(recon, CORPORATE, C07_RWEA_COL)
    assert shared_rows, "no C 07.00 row holds both legs — the single-cell claim is untestable"

    # Assert — the sheet is emitted on both sides and every shared cell agrees.
    assert CORPORATE in recon.ours.frames["c07_00"]
    assert CORPORATE in recon.theirs.frames["c07_00"]
    for row_ref in shared_rows:
        # Act
        result = decompose_cell(recon, "c07_00", CORPORATE, row_ref, C07_RWEA_COL)
        terms = _terms(result)

        # Assert
        assert result.decomposable, result.refusal
        assert (result.ours_state, result.theirs_state) == ("figure", "figure")
        assert result.ours == pytest.approx(_FAC_DRAWN.rwa + _FAC_UNDRAWN.rwa)
        assert result.theirs == pytest.approx(_FAC_WHOLE.rwa)
        assert result.delta == pytest.approx(0.0)
        assert terms["population_ours_only"] == 0.0
        assert terms["population_theirs_only"] == 0.0
        assert _term_keys(result)["population_ours_only"] == 0
        assert _term_keys(result)["population_theirs_only"] == 0
        assert _term_keys(result)["measurement"] == 1
        assert result.reconciles


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_standardised_split_with_differing_money_is_wholly_measurement(framework: str) -> None:
    """The same cell when the two sides genuinely disagree: -300,000, one key.

    Their facility is worth 1,300,000 against our two legs' 1,000,000. Summing
    the legs is the only reading that gives -300,000: picking the drawn half
    alone gives -600,000, the undrawn half -1,000,000, and leaving either behind
    puts its money back into a population term.
    """
    # Arrange
    theirs = replace(_FAC_WHOLE, ead=1_300_000.0, rwa=1_300_000.0)
    recon = _sa_recon([_FAC_DRAWN, _FAC_UNDRAWN], [theirs], framework)
    shared_rows = _c07_whole_sheet_rows(recon, CORPORATE, C07_RWEA_COL)
    assert shared_rows

    for row_ref in shared_rows:
        # Act
        result = decompose_cell(recon, "c07_00", CORPORATE, row_ref, C07_RWEA_COL)
        terms = _terms(result)

        # Assert
        assert result.decomposable, result.refusal
        assert (result.ours_state, result.theirs_state) == ("figure", "figure")
        assert terms["measurement"] == pytest.approx(_FAC_DRAWN.rwa + _FAC_UNDRAWN.rwa - theirs.rwa)
        assert _term_keys(result)["measurement"] == 1
        assert terms["population_ours_only"] == 0.0
        assert terms["population_theirs_only"] == 0.0
        assert result.reconciles


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_standardised_splits_halves_are_not_merged_across_the_bs_rows(framework: str) -> None:
    """C 07.00 splits the facility across its on/off-balance-sheet rows.

    The drawn half is an on-balance-sheet exposure and the undrawn half an
    off-balance-sheet one, so those two rows hold one leg each while their
    extract reports the whole facility on the on-balance-sheet row. Pairing must
    not pull the undrawn half onto the on-balance-sheet row: if it did, that
    cell's population would price 1,000,000 against a reported 700,000 and the
    four terms would stop summing to the reported delta.
    """
    # Arrange
    recon = _sa_recon([_FAC_DRAWN, _FAC_UNDRAWN], [_FAC_WHOLE], framework)
    ours = _c07_populations(recon, CORPORATE, C07_RWEA_COL, ours=True)
    on_bs = sorted(row for row, members in ours.items() if members == frozenset({"FAC1"}))
    off_bs = sorted(row for row, members in ours.items() if members == frozenset({"FAC1_UNDRAWN"}))
    assert on_bs and off_bs, "the facility's halves share every row — the fixture is vacuous"
    assert not set(on_bs) & set(off_bs)

    # Act
    drawn = decompose_cell(recon, "c07_00", CORPORATE, on_bs[0], C07_RWEA_COL)
    undrawn = decompose_cell(recon, "c07_00", CORPORATE, off_bs[0], C07_RWEA_COL)

    # Assert — the on-BS row prices OUR DRAWN LEG ONLY against their whole
    # facility; a merged reading would have made this term 0.00 and broken the
    # identity against the reported delta.
    assert drawn.ours == pytest.approx(_FAC_DRAWN.rwa)
    assert _terms(drawn)["measurement"] == pytest.approx(_FAC_DRAWN.rwa - _FAC_WHOLE.rwa)
    assert _terms(drawn)["population_ours_only"] == 0.0
    assert _terms(drawn)["population_theirs_only"] == 0.0
    assert drawn.reconciles

    # Assert — the off-BS row is a row PLACEMENT, not an exposure they lack.
    assert _terms(undrawn)["row_placement"] == pytest.approx(_FAC_UNDRAWN.rwa)
    assert _terms(undrawn)["population_ours_only"] == 0.0
    assert _terms(undrawn)["population_theirs_only"] == 0.0
    assert undrawn.reconciles

    # Assert — and the two rows conserve the facility.
    assert sum(_terms(drawn).values()) + sum(_terms(undrawn).values()) == pytest.approx(0.0)


# =============================================================================
# The two things the comparison key rests on
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_recon_template_plan_frame_carries_the_base_reference(framework: str) -> None:
    """``_comparison_key``'s presence guard must never take its ``else`` branch.

    The guard reads ``source_exposure_reference`` where the frame supplies one
    and falls back to the leg's own reference where it does not. That fallback
    is right for a legacy side that never carried the column — and silently
    WRONG for one of our own plan frames, because a plan builder that projected
    the column away would degrade ``_key_money`` and ``_side_keys`` together, at
    both call sites at once, restoring exactly the two equal-and-opposite
    population terms this slice removed. ``reconciles`` is structurally
    incapable of seeing that: the four buckets partition each side's population,
    so +100,000 and -100,000 sum to the same 0.00 as no terms at all.

    Nothing else would fail. The split tests address C 08.03 and C 07.00, so a
    FOURTH template added to ``RECON_TEMPLATE_IDS`` with a projecting plan
    builder would be a no-op the whole suite reports as green — absence, not
    wrongness.

    Iterated over ``RECON_TEMPLATE_IDS`` itself rather than a copy of today's
    three ids: a hand-written list stops covering the template it was written
    for the moment the constant grows, which is the only case this guards.

    **OUR SIDE ONLY, AND THAT IS THE POINT OF THE TEST.** Asserting this of the
    legacy side would pin a property production does not have: a projected
    ledger's plan frame legitimately has NO base-reference column at all —
    ``_projection_exprs`` emits the join key, the mapped components and the
    mapped carriers, and the base reference is none of the three. Measured on a
    real projection, the column-absent branch of ``_key_rungs`` is taken on
    every legacy-side ``_key_money`` call of every reconciliation. That absence
    is legal and handled; see
    ``test_a_side_whose_frame_omits_the_base_reference_can_still_be_keyed``.
    What is NOT legal is OUR side losing it, because ours is the side whose legs
    are split and therefore the side with something to collapse.
    """
    # Arrange — a portfolio reaching every template: the base legs carry both
    # IRB and standardised exposures, and the split legs make the column
    # load-bearing rather than merely present.
    legs = [*_base_legs(), _SPLIT_G_LEG, _SPLIT_REM_LEG]
    our_source, their_source = _sources(legs, legs, framework)
    recon = build_recon(our_source, their_source)

    # Act / Assert — every sheet plan of every scoped template, our side.
    checked = 0
    for template_id in RECON_TEMPLATE_IDS:
        plans = recon.ours.plans.get(template_id, {})
        assert plans, f"{template_id} produced no sheet plan — vacuous"
        for sheet, plan in plans.items():
            assert recon_module._BASE_KEY_COLUMN in plan.frame.columns, (
                f"{template_id}/{sheet} projects away "
                f"{recon_module._BASE_KEY_COLUMN}: the comparison key would silently "
                "degrade to the leg reference"
            )
            checked += 1
    assert checked >= len(RECON_TEMPLATE_IDS)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_both_key_column_settings_name_the_same_grain(framework: str) -> None:
    """``key_column`` is a validated public parameter, and both members agree.

    ``build_recon`` raises on anything outside ``KEY_COLUMNS``, so the two
    members are the whole documented surface — and the claim that they name one
    grain rested on nothing executable. It holds because the comparison key is a
    LADDER ending in the leg's own reference: under ``source_exposure_reference``
    the first two rungs are the same column, and where that column is null the
    last rung still supplies the very reference our legs were split from.

    **Asserted on the PRODUCTION SHAPE — their side omitting the column — which
    is exactly where the equivalence used to be false.** Keyed on the base
    reference, a projected legacy side's legs all shared one null key, matched
    nothing, and the cell reported the whole exposure as missing from each side
    at once: +100,000 and -100,000, netting to a delta of 0.00 that
    ``reconciles`` waved through. That was this batch's own defect, reachable
    through a documented public parameter. Restricting this test to a fixture
    that populates the column on both sides would assert the equivalence exactly
    where it was never in doubt.

    Both shapes are covered anyway, so neither the setting nor the presence of
    the column may change the answer.
    """
    # Arrange
    assert len(KEY_COLUMNS) > 1, "one setting cannot disagree with itself"
    results: dict[tuple[str, bool], CellDecomposition] = {}
    for key_column in KEY_COLUMNS:
        for supplied in (False, True):
            recon = _split_recon(
                [_SPLIT_G_LEG, _SPLIT_REM_LEG],
                [_WHOLE_LOAN],
                framework,
                key_column=key_column,
                theirs_supplies_base_ref=supplied,
            )
            row_ref = _leaf_row_of(recon, ours=False, reference=_WHOLE_LOAN.reference)
            results[key_column, supplied] = decompose_cell(
                recon, "c08_03", CORPORATE, row_ref, RWEA_COL
            )

    # Assert — every combination pairs the split exposure on one key, reports no
    # population, and prices the cell identically.
    for case, result in results.items():
        assert result.decomposable, (case, result.refusal)
        assert _terms(result)["population_ours_only"] == 0.0, case
        assert _terms(result)["population_theirs_only"] == 0.0, case
        assert _term_keys(result)["measurement"] == 1, case
        assert result.reconciles, case
    deltas = {result.delta for result in results.values()}
    assert len(deltas) == 1, deltas


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_side_that_omits_the_base_reference_still_pairs_on_its_own(
    framework: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A leg carrying no base reference IS its own base — the ladder's last rung.

    ``legacy_ledger._projection_exprs`` emits no ``source_exposure_reference``,
    so on a projected side every leg's base reference is a typed NULL. The
    comparison key's final rung is the leg's own ``exposure_reference``, which is
    precisely the reference our legs were split FROM, so the two sides meet
    without their extract carrying anything it does not have.

    **Keyed on ``source_exposure_reference`` deliberately: that is the ONLY
    setting under which the last rung is observable.** Under the default the
    second rung is already ``exposure_reference``, so the sides pair whether a
    third rung exists or not, and a test on the default alone could not tell the
    two implementations apart. The premise is asserted rather than assumed —
    their legs really do carry a null base reference throughout, so nothing but
    the last rung can be doing the pairing.

    AND IT IS NOT WARNED ABOUT. ``_build_side`` counts unreconcilable legs on the
    RESOLVED key, so a null base reference — the ordinary shape of every
    projected legacy side — is silent, and the warning is kept for a leg with no
    usable identity on any rung. Counting on ``key_column`` alone instead would
    fire that warning on every legacy run under this setting, which is the kind
    of false alarm that teaches people to stop reading warnings. The SILENCE is
    asserted here because it is the property that would regress.
    """
    # Arrange — the production shape, keyed where only the last rung can help.
    with caplog.at_level(logging.WARNING, logger="rwa_calc.analysis.return_recon"):
        recon = _split_recon(
            [_SPLIT_G_LEG, _SPLIT_REM_LEG],
            [_WHOLE_LOAN],
            framework,
            key_column="source_exposure_reference",
        )
    their_legs = recon.theirs.membership.legs.filter(
        (pl.col("template_id") == "c08_03") & (pl.col("sheet") == CORPORATE)
    )

    # Assert the premise: their side offers the first two rungs nothing at all.
    assert their_legs.height > 0, "their side reports no corporate leg — vacuous"
    assert their_legs["source_exposure_reference"].null_count() == their_legs.height
    assert _WHOLE_LOAN.reference in set(their_legs["exposure_reference"].to_list())

    # Assert — and building that side raised no unreconcilable-leg warning.
    # Stated here, beside the build it describes, so it fails on its own rather
    # than behind the pairing assertions below.
    assert [
        record.getMessage()
        for record in caplog.records
        if "resolves" in record.getMessage() and "NULL" in record.getMessage()
    ] == []

    # Act
    row_ref = _leaf_row_of(recon, ours=False, reference=_WHOLE_LOAN.reference)
    result = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)

    # Assert — paired on one key, and nothing reported missing from either side.
    assert result.decomposable, result.refusal
    assert _terms(result)["population_ours_only"] == 0.0
    assert _terms(result)["population_theirs_only"] == 0.0
    assert _term_keys(result)["measurement"] == 1
    assert result.reconciles


# =============================================================================
# The per-key pair table
# =============================================================================

#: The probe portfolio's agreeing backbone. Every one of these is worth far more
#: than every driver below, and that is the whole point: a table ranked on SIZE
#: shows nothing but agreement, so the analyst who asks "which contracts?" is
#: handed a page of loans that tie to the penny.
_PROBE_AGREEING_LEGS = 30
_PROBE_AGREEING_RWA = 1_000_000.0

#: The four value breaks — the SAME exposure on both sides, priced differently.
#: ``(reference, our RWEA, their RWEA)``. The deltas (12k / 8k / 5k / 3k) are
#: distinct from each other and from every other driver's, so the ranked order
#: is fully determined and can be asserted as a LIST rather than as a set.
_PROBE_BREAKS: tuple[tuple[str, float, float], ...] = (
    ("PROBE_BREAK_1", 40_000.0, 28_000.0),
    ("PROBE_BREAK_2", 35_000.0, 27_000.0),
    ("PROBE_BREAK_3", 30_000.0, 25_000.0),
    ("PROBE_BREAK_4", 25_000.0, 22_000.0),
)

#: One exposure each side holds and the other does not, and one that moves PD
#: band between the sides. All three are small, like the breaks.
_PROBE_OURS_ONLY = _Leg("PROBE_OURS_ONLY", pd=PD_BAND_A, ead=60_000.0, rwa=20_000.0)
_PROBE_THEIRS_ONLY = _Leg("PROBE_THEIRS_ONLY", pd=PD_BAND_A, ead=45_000.0, rwa=15_000.0)
_PROBE_MOVER = _Leg("PROBE_MOVER", pd=PD_BAND_A, ead=90_000.0, rwa=30_000.0)

#: Every exposure the cell's difference actually lives in, in the order
#: ``|delta|`` puts them: 30k row placement, 20k ours-only, 15k theirs-only,
#: then the four breaks. Their signed deltas sum to the cell delta and nothing
#: else contributes.
_PROBE_DRIVERS: tuple[str, ...] = (
    "PROBE_MOVER",
    "PROBE_OURS_ONLY",
    "PROBE_THEIRS_ONLY",
    "PROBE_BREAK_1",
    "PROBE_BREAK_2",
    "PROBE_BREAK_3",
    "PROBE_BREAK_4",
)

#: The probe cell's delta: 30,000 + 20,000 - 15,000 + 12,000 + 8,000 + 5,000
#: + 3,000. Written out so a fixture edit that changes it fails loudly here
#: rather than silently weakening every assertion below.
_PROBE_DELTA = 63_000.0

#: The measurement term's own share of it — the four breaks and nothing else.
_PROBE_MEASUREMENT_DELTA = 28_000.0


def _probe_legs(*, ours: bool) -> list[_Leg]:
    """One side of the probe portfolio: 30 agreeing loans and 7 drivers."""
    agreeing = [
        _Leg(f"PROBE_AGREE_{index:02d}", pd=PD_BAND_A, ead=3_000_000.0, rwa=_PROBE_AGREEING_RWA)
        for index in range(_PROBE_AGREEING_LEGS)
    ]
    breaks = [
        _Leg(ref, pd=PD_BAND_A, ead=200_000.0, rwa=our_rwa if ours else their_rwa)
        for ref, our_rwa, their_rwa in _PROBE_BREAKS
    ]
    one_sided = _PROBE_OURS_ONLY if ours else _PROBE_THEIRS_ONLY
    mover = _PROBE_MOVER if ours else replace(_PROBE_MOVER, pd=PD_BAND_B)
    return [*_split_base(), *agreeing, *breaks, one_sided, mover]


@lru_cache(maxsize=8)
def _probe(framework: str) -> ReturnRecon:
    """The portfolio the size-ranked leg table was measured to be useless on.

    30 agreeing loans, 4 small value breaks, one exposure each side only and one
    band mover, all in ONE C 08.03 PD band so they share a single cell. Cached,
    so nothing may mutate what it returns.
    """
    our_source, their_source = _sources(_probe_legs(ours=True), _probe_legs(ours=False), framework)
    return build_recon(our_source, their_source)


def _probe_row(recon: ReturnRecon) -> str:
    """The C 08.03 corporate leaf row every probe driver shares on OUR side."""
    return _leaf_row_of(recon, ours=True, reference="PROBE_AGREE_00")


def _group_of(  # noqa: PLR0913 - the cell's full address plus the recon
    recon: ReturnRecon, template_id: str, sheet: str | None, row_ref: str, col_ref: str
) -> str:
    """The ONE membership group serving a cell, addressed by its full identity.

    ``_c08_03_predicate_key`` resolves a column across every row; this resolves
    the exact ``(row_ref, col_ref)`` cell, which is the grain a leg listing has
    to be scoped to.
    """
    served = recon.ours.membership.columns.filter(
        (pl.col("template_id") == template_id)
        & (pl.col("sheet") == sheet)
        & (pl.col("row_ref") == row_ref)
        & (pl.col("col_ref") == col_ref)
    )
    assert served.height > 0, f"{template_id}/{sheet}/{row_ref}/{col_ref} is not row-backed"
    return str(served["predicate_key"][0])


def _size_ranked_keys(  # noqa: PLR0913 - one side plus the group's full address
    side: SideView, template_id: str, sheet: str | None, row_ref: str, group: str, limit: int
) -> set[str]:
    """The table the compare page used to render: one side's legs, largest first.

    A local restatement of the ordering in
    ``ui/views/return_recon.py::_cell_legs`` — ``sort(|rwa_final|, descending)``
    then ``head(limit)``. Written out here rather than imported from the view so
    the defect being pinned is visible in the test that pins it, and so this
    file does not depend on a module another work item owns.
    """
    ordered = (
        _probe_group_legs(side, template_id, sheet, row_ref, group)
        .sort(pl.col("rwa_final").abs(), descending=True, nulls_last=True)
        .head(limit)
    )
    return set(ordered["exposure_reference"].to_list())


def _probe_group_legs(
    side: SideView, template_id: str, sheet: str | None, row_ref: str, group: str
) -> pl.DataFrame:
    """One membership group's legs on one side, at the cell's own grain."""
    return side.membership.legs.filter(
        (pl.col("template_id") == template_id)
        & (pl.col("sheet") == sheet)
        & (pl.col("row_ref") == row_ref)
        & (pl.col("predicate_key") == group)
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_pair_table_ranks_the_drivers_a_size_ranked_table_buries(framework: str) -> None:
    """The user-visible defect: ranked on SIZE, not one driver is on the page.

    Measured on this portfolio before the change: the compare page's leg table
    rendered 25 of our legs and 25 of theirs, every one of them a loan that
    agrees to the penny, because the ordering is ``|rwa_final|`` and the
    difference lives in the small loans. The size-ranked ordering is reproduced
    here and asserted to bury every driver, so the test cannot pass by the
    defect having been redefined.

    THE SECOND HALF PINS THE TIE-BREAK, WHICH DECIDES MOST OF THE PAGE. Only 7
    of the 38 keys have a delta at all; the other 31 tie at ``0.00``, so
    ``|delta|`` alone fixes 7 rows and the KEY fixes the remaining 18. Deleting
    the tie-break leaves Python's stable sort to preserve ``_classify``'s order,
    which is polars ``group_by`` order — implementation-defined and NOT stable
    across processes. Measured on this cell: 17 of the 25 rendered rows move,
    7 exposures appear that the correct ordering never shows (including
    ``SPLIT_FILL_A1``), and two separate processes produced two DIFFERENT wrong
    pages. Meanwhile ``shown_delta`` stays 63,000.00 and ``hidden_keys`` stays
    13 — every published figure ties out either way, which is exactly why
    nothing looked wrong and why no assertion caught it
    (``tests/mutations/mutate_rank_without_the_tie_break.py``: 132 passed,
    exit 0).
    """
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)
    group = _group_of(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    drivers = set(_PROBE_DRIVERS)

    # Assert the fixture's adequacy — BOTH halves, because either one failing
    # would leave the ranking assertion below true for the wrong reason.
    for side, label in ((recon.ours, "ours"), (recon.theirs, "theirs")):
        held = set(
            _probe_group_legs(side, "c08_03", CORPORATE, row_ref, group)[
                "exposure_reference"
            ].to_list()
        )
        present = held & drivers
        assert present, f"the {label} side of the cell holds no driver at all — vacuous"
        assert len(held - drivers) > len(present), (
            f"the {label} side holds {len(held - drivers)} agreeing legs against "
            f"{len(present)} drivers; unless the agreeing legs OUTNUMBER the drivers "
            "the cap cannot hide anything and this test would prove nothing"
        )
        buried = _size_ranked_keys(side, "c08_03", CORPORATE, row_ref, group, CELL_PAIRS_LIMIT)
        assert not (buried & drivers), (
            f"the size-ranked table already shows {sorted(buried & drivers)} on the "
            f"{label} side, so it never had the defect this test pins"
        )

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)

    # Assert — every driver is on the page, ranked, ahead of every agreeing key.
    assert table.refusal is None
    assert [pair.key for pair in table.pairs[: len(_PROBE_DRIVERS)]] == list(_PROBE_DRIVERS)
    assert drivers <= {pair.key for pair in table.pairs}

    # Act — the tied remainder, ranked by the KEY and by nothing else.
    full = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None)
    all_tied = sorted(pair.key for pair in full.pairs if pair.delta == 0.0)
    tied_shown = [pair.key for pair in table.pairs if pair.delta == 0.0]

    # Assert the adequacy of that, first: a page with no ties, or a cap that
    # does not bite on them, cannot tell the tie-break from its absence.
    assert len(tied_shown) > 1, "no ties on the page — the tie-break is not exercised"
    assert len(all_tied) > len(tied_shown), "the cap does not bite on the ties — vacuous"

    # Assert — the tied rows shown are the LEADING SLICE of the sorted tied
    # keys. Derived from the uncapped table's own keys and sorted independently,
    # so this is not a restatement of ``_rank``.
    assert tied_shown == all_tied[: len(tied_shown)]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_cap_states_what_it_hides(framework: str) -> None:
    """A silent cap on a regulatory comparison is a silent zero by another name.

    The shown rows' delta, the total and the count not shown are all published,
    so a caller can say "the 25 shown carry X of the Y difference; N more carry
    Z" instead of implying the page is the whole population.

    THE DEFAULT CAP CANNOT TEST THE MONEY CLAIM, AND THE SECOND HALF EXISTS FOR
    THAT. ``CELL_PAIRS_LIMIT`` is 25 against a 38-key probe whose seven drivers
    all rank above every agreeing key, so the hidden tail is EMPTY and
    ``shown_delta`` is indistinguishable from ``total_delta``. Measured over
    this whole file: 7,021 ``cell_pairs`` calls, ``shown_delta != total_delta``
    on ZERO of them. A mutation forcing ``shown_delta = total_delta`` scored
    132 passed, exit 0 — completely silent
    (``tests/mutations/mutate_cap_claims_it_showed_everything.py``).

    So the cap is tightened until the tail carries money. At ``limit=3`` the
    page's true sentence is "the 3 shown carry 35,000.00; 35 more carry
    28,000.00"; under that mutation it reads "the 3 shown carry 63,000.00 of
    the 63,000.00 difference; 35 more carry 0.00" — 44% of the difference
    silently attributed to rows the analyst can see. On a real book a non-zero
    hidden tail is the ORDINARY case: ``measurement`` holds thousands of keys
    and the drivers do not all fit in the top 25.
    """
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)

    # Assert the fixture's adequacy: an uncapped table would exercise nothing.
    assert table.hidden_keys > 0, "the cap is not engaged — the test would prove nothing"
    assert len(table.pairs) == CELL_PAIRS_LIMIT

    # Assert — the arithmetic of the cap, and the delta it is a cap on.
    assert table.keys == len(table.pairs) + table.hidden_keys
    assert table.shown_delta + table.hidden_delta == pytest.approx(table.total_delta)
    assert table.total_delta == pytest.approx(_PROBE_DELTA)
    assert table.total_delta == pytest.approx(decomposition.delta)
    # Every driver is shown, so the hidden remainder carries none of the money.
    assert table.shown_delta == pytest.approx(_PROBE_DELTA)
    assert table.hidden_delta == pytest.approx(0.0)

    # Act — the same cell under a cap that actually bites.
    tight = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=3)

    # Assert the adequacy of THAT, first and on its own: it is the limb that
    # keeps this test from going vacuous again if the probe or the default
    # limit changes, and every assertion below is worthless without it.
    assert tight.hidden_delta != 0.0, (
        "the cap hides no money, so this test cannot tell shown_delta from total_delta"
    )

    # Assert — the three rows shown are exactly the three non-measurement
    # drivers (30,000 + 20,000 - 15,000), so the tail is the measurement term
    # itself rather than a number that happens to match it.
    assert [pair.term for pair in tight.pairs] == [
        "row_placement",
        "population_ours_only",
        "population_theirs_only",
    ]
    assert tight.shown_delta == pytest.approx(35_000.0)
    assert tight.hidden_delta == pytest.approx(_PROBE_MEASUREMENT_DELTA)
    assert tight.shown_delta + tight.hidden_delta == pytest.approx(tight.total_delta)
    assert tight.total_delta == pytest.approx(_PROBE_DELTA)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_an_uncapped_table_hides_nothing(framework: str) -> None:
    """``limit=None`` is the census form: every key, nothing hidden."""
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)

    # Act
    capped = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    uncapped = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None)

    # Assert
    assert uncapped.hidden_keys == 0
    assert uncapped.hidden_delta == pytest.approx(0.0)
    assert len(uncapped.pairs) == uncapped.keys == capped.keys
    assert len(uncapped.pairs) > len(capped.pairs), "the cap changed nothing — vacuous"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_each_pair_carries_both_sides_placement_carriers(framework: str) -> None:
    """A pair says where EACH side put the exposure, and what each side calls it.

    Read off ``CellMembership.legs``, which carries all four
    (``reporting/membership.py::_LEG_COLUMNS``) as typed nulls when the plan
    frame lacks them — so an unsupplied carrier is an empty tuple, never a
    blank string and never a zero.

    ``row_refs`` is every row of THIS cell's sheet the side placed the key in,
    parents included: the C 08.03 PD scale is hierarchical, so a leg is
    legitimately in its band row and its parent band's row at once. It is not a
    leaf resolution — ``row_migration`` is what resolves a single placement row.
    """
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    by_key = {pair.key: pair for pair in table.pairs}

    # Assert — the mover is on our row and on a DIFFERENT row of their sheet.
    mover = by_key["PROBE_MOVER"]
    assert mover.term == "row_placement"
    assert row_ref in mover.ours_placement.row_refs
    assert mover.theirs_placement.row_refs, "their side places the mover nowhere — vacuous"
    assert row_ref not in mover.theirs_placement.row_refs

    # Assert — a one-sided exposure has an EMPTY placement on the side that does
    # not hold it, on every carrier, rather than a fabricated blank.
    theirs_only = by_key["PROBE_THEIRS_ONLY"]
    assert theirs_only.term == "population_theirs_only"
    assert theirs_only.ours_placement.row_refs == ()
    assert theirs_only.ours_placement.class_origins == ()
    assert theirs_only.ours_placement.approach_origins == ()
    assert theirs_only.ours_placement.leg_roles == ()
    assert theirs_only.theirs_placement.row_refs

    # Assert — the carriers themselves, on a pair both sides hold.
    both = by_key["PROBE_BREAK_1"]
    assert both.ours_placement.class_origins == (CORPORATE,)
    assert both.theirs_placement.class_origins == (CORPORATE,)
    assert both.ours_placement.approach_origins == ("foundation_irb",)
    assert both.ours_placement.leg_roles == ("whole",)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_pairs_money_is_signed_so_the_deltas_sum_to_the_cell(framework: str) -> None:
    """Each side's money, and the SIGNED contribution, per exposure.

    A side that does not hold the key in this cell carries ``None``, never
    ``0.0``: an unheld exposure and one held at zero are different claims and
    filling the null would make them look alike.
    """
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None)
    by_key = {pair.key: pair for pair in table.pairs}

    # Assert — a measurement pair carries both sides' money and their difference.
    ref, our_rwa, their_rwa = _PROBE_BREAKS[0]
    assert by_key[ref].ours == pytest.approx(our_rwa)
    assert by_key[ref].theirs == pytest.approx(their_rwa)
    assert by_key[ref].delta == pytest.approx(our_rwa - their_rwa)

    # Assert — a one-sided pair carries a NULL on the side that has nothing.
    assert by_key["PROBE_OURS_ONLY"].theirs is None
    assert by_key["PROBE_OURS_ONLY"].ours == pytest.approx(_PROBE_OURS_ONLY.rwa)
    assert by_key["PROBE_OURS_ONLY"].delta == pytest.approx(_PROBE_OURS_ONLY.rwa)
    assert by_key["PROBE_THEIRS_ONLY"].ours is None
    assert by_key["PROBE_THEIRS_ONLY"].delta == pytest.approx(-_PROBE_THEIRS_ONLY.rwa)

    # Assert — and a leg the other side placed elsewhere is null HERE, because
    # this cell is not where they put it.
    assert by_key["PROBE_MOVER"].theirs is None
    assert by_key["PROBE_MOVER"].delta == pytest.approx(_PROBE_MOVER.rwa)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_differing_keys_counts_the_keys_that_differ_not_the_population(framework: str) -> None:
    """``keys`` is the term's population; ``differing_keys`` is its drivers.

    Measured on this cell under both frameworks: ``measurement`` holds 35 keys
    and 4 of them differ, so a page reading ``keys`` says "35 exposures" about a
    difference driven by four — an 8.75x overstatement of the term an analyst is
    most likely to chase.

    The other four terms are equal on THIS cell because every one of their keys
    carries money. That is a property of the fixture, not of the terms: a key
    whose money is itself zero would count in ``keys`` and not in
    ``differing_keys`` in any term.
    """
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)

    # Act
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None)
    terms = {term.name: term for term in decomposition.terms}

    # Assert the fixture's adequacy: without agreeing keys inside the
    # measurement term the two counts cannot differ and the test is vacuous.
    measurement = terms["measurement"]
    assert measurement.keys > measurement.differing_keys, (
        f"measurement holds {measurement.keys} keys of which "
        f"{measurement.differing_keys} differ; unless it contains AGREEING keys "
        "this test cannot tell the two counts apart"
    )
    assert measurement.keys >= _PROBE_AGREEING_LEGS

    # Assert — the count is the drivers, and it is what the pairs say it is.
    assert measurement.differing_keys == len(_PROBE_BREAKS)
    assert measurement.keys == sum(1 for pair in table.pairs if pair.term == "measurement")
    assert measurement.differing_keys == sum(
        1 for pair in table.pairs if pair.term == "measurement" and pair.delta != 0.0
    )
    for name in ("population_ours_only", "population_theirs_only", "row_placement"):
        assert terms[name].keys == terms[name].differing_keys == 1, name


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_term_filter_selects_exactly_that_terms_keys(framework: str) -> None:
    """``term=`` is what links a waterfall row to the exposures behind it."""
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    live = [term for term in decomposition.terms if term.keys]

    # Assert the fixture's adequacy: one live term proves nothing about a filter.
    assert len(live) >= 4, f"only {len(live)} terms are live on this cell"

    for term in decomposition.terms:
        # Act
        table = cell_pairs(
            recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None, term=term.name
        )

        # Assert — that term's keys, that term's money, and nothing else.
        assert {pair.term for pair in table.pairs} <= {term.name}, term.name
        assert len(table.pairs) == term.keys, term.name
        assert table.total_delta == term.amount, term.name
        assert table.hidden_keys == 0, term.name


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_capped_term_filter_reports_the_keys_it_left_off(framework: str) -> None:
    """The measurement term is the one a cap actually bites on."""
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(recon)
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    measurement = next(term for term in decomposition.terms if term.name == "measurement")

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, term="measurement")

    # Assert
    assert measurement.keys > CELL_PAIRS_LIMIT, "the cap is not engaged — vacuous"
    assert len(table.pairs) == CELL_PAIRS_LIMIT
    assert table.hidden_keys == measurement.keys - CELL_PAIRS_LIMIT
    assert table.total_delta == pytest.approx(_PROBE_MEASUREMENT_DELTA)
    # All four breaks rank above every agreeing key, so the hidden tail is free
    # of money and the page can say so.
    assert table.shown_delta == pytest.approx(_PROBE_MEASUREMENT_DELTA)
    assert table.hidden_delta == pytest.approx(0.0)


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_every_terms_pairs_sum_to_that_term_on_every_additive_cell(
    template_id: str, framework: str
) -> None:
    """The contract that makes the drill-down trustworthy, on the whole census.

    A drill-down that does not sum to the waterfall it explains is worse than
    none. Asserted on EVERY published cell of all three scoped templates under
    both frameworks, over the portfolio where all five causes are live — not on
    a sample — and the census counts its own non-vacuous denominator so a
    narrowed scope cannot hide behind a good ratio.

    The pair sums are compared to within float reassociation: the pairs are
    ranked by ``|delta|`` and the terms accumulate in classification order, so
    the same addends arrive in a different order and IEEE addition is not
    associative. The tolerance is far below any difference an analyst could see.
    """
    # Arrange
    recon = _combined(framework)
    diff = cell_diff(recon.ours.source, recon.theirs.source, template_id)
    checked = 0
    refused = 0
    live: set[str] = set()

    for row in diff.iter_rows(named=True):
        # Act
        decomposition = decompose_cell(
            recon, template_id, row["sheet"], row["row_ref"], row["col_ref"]
        )
        table = cell_pairs(
            recon, template_id, row["sheet"], row["row_ref"], row["col_ref"], limit=None
        )
        where = f"{row['sheet']}/{row['row_ref']}/{row['col_ref']}"

        # Assert — a refused cell yields NO pairs, and the SAME refusal.
        if not decomposition.decomposable:
            refused += 1
            assert table.pairs == (), where
            assert table.refusal == decomposition.refusal, where
            continue

        checked += 1
        assert table.refusal is None, where
        assert table.total_delta == pytest.approx(decomposition.explained), where
        for term in decomposition.terms:
            pairs = [pair for pair in table.pairs if pair.term == term.name]
            assert sum(pair.delta for pair in pairs) == pytest.approx(
                term.amount, rel=1e-12, abs=1e-9
            ), f"{where} {term.name}"
            assert len(pairs) == term.keys, f"{where} {term.name}"
            assert sum(1 for pair in pairs if pair.delta != 0.0) == term.differing_keys, (
                f"{where} {term.name}"
            )
            if pairs:
                live.add(term.name)

    # Assert — the census is not vacuous, and every term was actually exercised.
    assert checked > 0, "no decomposable cell at all"
    assert refused > 0, "no refused cell at all — the refusal mirror is untested here"
    assert live == set(TERM_NAMES), f"terms never populated: {set(TERM_NAMES) - live}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("col_ref", ["0030", "0050"])
def test_a_non_additive_cell_yields_no_pairs(col_ref: str, framework: str) -> None:
    """A weighted average has no additive population, so it has no pair table.

    Rendering one would put rows of "theirs 0.00" under a number the identity
    does not apply to.
    """
    # Arrange
    recon = _combined(framework)
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, row_ref, col_ref)
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, col_ref)

    # Assert
    assert not decomposition.decomposable
    assert table.pairs == ()
    assert table.refusal == decomposition.refusal
    assert "non-additive" in (table.refusal or "")
    assert table.total_delta == 0.0
    assert table.hidden_keys == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_coverage_unavailable_cell_yields_no_pairs(framework: str) -> None:
    """The false zero must not come back as a table of "theirs 0.00" rows.

    Their side prints a confident ``0.00`` off an injected all-null column for
    the very keys we hold, so a pair table built without this guard would list
    every one of our exposures against a zero their mapping cannot populate —
    the exact false zero this module exists to prevent, restated one row per
    contract.
    """
    # Arrange
    our_source, their_source, coverage = _unmapped_gross(framework)
    recon = build_recon(our_source, their_source, theirs_coverage=coverage)
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, row_ref, "0010")
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, "0010")

    # Assert the premise: without the guard this cell prints a zero, not a blank.
    assert "0010" in coverage.unavailable_refs("c08_03")
    assert decomposition.theirs_state == "unavailable"
    assert not decomposition.decomposable

    # Assert — no pairs, and the refusal is the decomposition's own words.
    assert table.pairs == ()
    assert table.refusal == decomposition.refusal
    assert "cannot populate" in (table.refusal or "")


def test_an_unbound_cell_yields_no_pairs() -> None:
    """A cell on no template on either side is refused, not paired."""
    # Arrange
    recon = _combined("CRR")

    # Act
    decomposition = decompose_cell(recon, "c08_03", CORPORATE, "9999", "0040")
    table = cell_pairs(recon, "c08_03", CORPORATE, "9999", "0040")

    # Assert
    assert not decomposition.decomposable
    assert table.pairs == ()
    assert table.refusal == decomposition.refusal


def test_cell_pairs_refuses_a_term_that_is_not_a_term() -> None:
    """An unknown term would filter to an empty table — a silent zero."""
    # Arrange
    recon = _combined("CRR")
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act / Assert
    with pytest.raises(ValueError, match="term must be one of"):
        cell_pairs(recon, "c08_03", CORPORATE, row_ref, "0040", term="measuremnt")  # type: ignore[arg-type]


def test_cell_pairs_refuses_a_negative_limit() -> None:
    """A negative limit slices from the END, which would hide the drivers."""
    # Arrange
    recon = _combined("CRR")
    row_ref = _leaf_row_of(recon, ours=True, reference="BASE_A1")

    # Act / Assert
    with pytest.raises(ValueError, match="limit must not be negative"):
        cell_pairs(recon, "c08_03", CORPORATE, row_ref, "0040", limit=-1)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_sheet_placement_pair_names_the_class_the_other_side_moved_it_to(
    framework: str,
) -> None:
    """The two placement scopes are DIFFERENT, and each one is load-bearing.

    ``row_refs`` is scoped to the cell's own sheet, so a key the other side put
    on a different sheet reports an EMPTY row list — which is precisely what a
    ``sheet_placement`` finding is. The other three carriers are template-wide,
    so the same pair still names the class they moved it TO; scoping those to
    the sheet would blank the one fact the analyst needs.

    Measured on the single-cause fixture: our corporate leg against their
    institution one, ``their_rows=()`` with
    ``their_class=('institution',)``.
    """
    # Arrange
    recon = _single_cause("sheet_placement", framework)
    row_ref = _leaf_row_of(recon, ours=True, reference="CLASS_MOVER")

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None)
    pair = next(item for item in table.pairs if item.key == "CLASS_MOVER")

    # Assert the fixture's adequacy: identical classes on the two sides would
    # make the template-wide assertion below true under either scoping.
    assert pair.term == "sheet_placement"
    assert pair.ours_placement.class_origins != pair.theirs_placement.class_origins, (
        "both sides class the mover the same way, so this test could not tell "
        "a template-wide carrier from a sheet-scoped one"
    )

    # Assert — sheet-scoped rows, template-wide carriers.
    assert row_ref in pair.ours_placement.row_refs
    assert pair.theirs_placement.row_refs == ()
    assert pair.ours_placement.class_origins == (CORPORATE,)
    assert pair.theirs_placement.class_origins == ("institution",)
    assert pair.theirs_placement.approach_origins == ("foundation_irb",)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_split_exposures_pair_is_placed_on_the_key_it_paired_on(framework: str) -> None:
    """The placements are keyed on the COMPARISON key, not on the leg reference.

    Our sealed ledger holds this loan as ``L1__G_BANK`` and ``L1__REM``; the
    pair's key is the pre-split ``L1``. A placement lookup keyed on
    ``exposure_reference`` would therefore find nothing for it and every pair of
    every split exposure would render a blank placement — a silent one, because
    an empty placement is also the legitimate shape of a population term.
    """
    # Arrange
    recon = _split_recon([_SPLIT_G_LEG, _SPLIT_REM_LEG], [_WHOLE_LOAN], framework)
    row_ref = _leaf_row_of(recon, ours=False, reference=_WHOLE_LOAN.reference)
    our_legs = recon.ours.membership.legs.filter(
        (pl.col("template_id") == "c08_03") & (pl.col("sheet") == CORPORATE)
    )
    references = set(our_legs["exposure_reference"].to_list())

    # Assert the fixture's adequacy: our side must carry the base reference ONLY
    # as ``source_exposure_reference``, or the two keyings coincide here.
    assert {_SPLIT_G_LEG.reference, _SPLIT_REM_LEG.reference} <= references
    assert _WHOLE_LOAN.reference not in references, (
        f"our side carries {_WHOLE_LOAN.reference} as a leg reference, so a "
        "literal keying would find it too and this test would prove nothing"
    )

    # Act
    table = cell_pairs(recon, "c08_03", CORPORATE, row_ref, RWEA_COL, limit=None)
    pair = next(item for item in table.pairs if item.key == _WHOLE_LOAN.reference)

    # Assert — both sides place the pair, on the key they paired on.
    assert row_ref in pair.ours_placement.row_refs
    assert row_ref in pair.theirs_placement.row_refs
    assert pair.ours_placement.class_origins == (CORPORATE,)


def _row_group_members(
    side: SideView, template_id: str, sheet: str | None, row_ref: str
) -> dict[str, frozenset[str]]:
    """``predicate_key -> the legs it holds`` for every group on one row."""
    legs = side.membership.legs.filter(
        (pl.col("template_id") == template_id)
        & (pl.col("sheet") == sheet)
        & (pl.col("row_ref") == row_ref)
    )
    return {
        key: frozenset(legs.filter(pl.col("predicate_key") == key)["exposure_reference"].to_list())
        for key in legs["predicate_key"].unique().to_list()
    }


def _first_decomposable_col(  # noqa: PLR0913 - the group's full address plus the recon
    recon: ReturnRecon, template_id: str, sheet: str | None, row_ref: str, group: str
) -> str:
    """The first column of one group that carries a four-way split at all."""
    served = (
        recon.ours.membership.columns.filter(
            (pl.col("template_id") == template_id)
            & (pl.col("sheet") == sheet)
            & (pl.col("row_ref") == row_ref)
            & (pl.col("predicate_key") == group)
        )["col_ref"]
        .unique()
        .sort()
        .to_list()
    )
    for col_ref in served:
        if decompose_cell(recon, template_id, sheet, row_ref, col_ref).decomposable:
            return col_ref
    raise AssertionError(f"group {group} of {template_id}/{sheet}/{row_ref} has no additive cell")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_pairs_read_the_one_group_serving_the_cell(framework: str) -> None:
    """A ROW does not have one population, and the pair table must not act as if.

    C 08.01 row 0010 carries several predicate groups: the origin-basis columns
    read the whole book, while the off-balance-sheet column reads one narrow
    group. Listing the row's legs instead of the CELL's would report every
    exposure of the row against a column that describes two of them — measured
    here at 13 keys against 2, a 6.5x over-count on this fixture, and at 3.00x
    (C 07.00 ``retail_other``) and 1.86x (C 08.01 ``corporate``) on the review
    portfolio that first found it.

    The group refs differ between the frameworks, so they are resolved from the
    membership rather than typed.
    """
    # Arrange
    recon = _combined(framework)
    row_ref = "0010"
    ours = _row_group_members(recon.ours, "c08_01", CORPORATE, row_ref)
    theirs = _row_group_members(recon.theirs, "c08_01", CORPORATE, row_ref)
    narrow = min(ours, key=lambda key: len(ours[key]))
    wide = max(ours, key=lambda key: len(ours[key]))

    # Assert the fixture's adequacy: one population on the row would make the
    # narrow and wide cells identical and this test would prove nothing.
    assert len(ours[narrow]) < len(ours[wide]), (
        f"every group of the row holds the same {len(ours[narrow])} legs, so a "
        "cell reading its row rather than its group would look correct here"
    )

    # Act
    narrow_col = _first_decomposable_col(recon, "c08_01", CORPORATE, row_ref, narrow)
    wide_col = _first_decomposable_col(recon, "c08_01", CORPORATE, row_ref, wide)
    narrow_keys = {
        pair.key
        for pair in cell_pairs(recon, "c08_01", CORPORATE, row_ref, narrow_col, limit=None).pairs
    }
    wide_keys = {
        pair.key
        for pair in cell_pairs(recon, "c08_01", CORPORATE, row_ref, wide_col, limit=None).pairs
    }

    # Assert — the narrow cell lists its OWN group's exposures and no others.
    assert narrow_keys, f"the {narrow_col} cell lists no exposure at all"
    assert narrow_keys <= (ours[narrow] | theirs[narrow])
    assert narrow_keys < wide_keys, (
        f"{narrow_col} lists {sorted(narrow_keys)}, which is not a strict subset "
        f"of {wide_col}'s {len(wide_keys)} keys — the table aggregated across "
        "predicate groups"
    )


# =============================================================================
# The migration matrix's LABEL on an absent counterpart
# =============================================================================

#: A leg only OUR side holds, planted in the split exposure's own PD band so it
#: lands in the same matrix cell as the two split legs. The collision is the
#: point: one cell, two findings, and no single label true of both.
_SPLIT_ONLY_OURS = _Leg("SPLIT_ONLY_OURS", pd=SPLIT_PD, ead=300_000.0, rwa=30_000.0)

#: The same guarantee, crossing SHEETS. The guarantor is an institution, so our
#: guarantee leg is reported under the INSTITUTION class while the remainder and
#: their whole loan stay corporate. Nothing on the institution sheet can see the
#: base exposure at all, which is what makes the presence test's scope
#: measurable rather than a matter of taste.
_XSHEET_G_LEG = _Leg(
    "L2__G_INST",
    source="L2",
    exposure_class="institution",
    pd=SPLIT_PD,
    ead=700_000.0,
    rwa=70_000.0,
)
_XSHEET_REM_LEG = _Leg("L2__REM", source="L2", pd=SPLIT_PD, ead=300_000.0, rwa=30_000.0)
_XSHEET_WHOLE = _Leg("L2", pd=SPLIT_PD, ead=1_000_000.0, rwa=100_000.0)

#: The two absent buckets, by the side that HOLDS the legs. Named because every
#: assertion below is about which of the three labels one of these carries.
_ABSENT_BASES = ("ours_only", "theirs_only")


def _group_key_of(recon: ReturnRecon, template_id: str, sheet: str, col_ref: str) -> str:
    """The predicate group serving one column of one sheet, from either side.

    ``_c08_03_predicate_key`` reads OUR side of the corporate sheet only; the
    cross-sheet fixture below needs a sheet their side does not reach at all,
    which is precisely the case that helper cannot express.
    """
    for side in (recon.ours, recon.theirs):
        served = side.membership.columns.filter(
            (pl.col("template_id") == template_id)
            & (pl.col("sheet") == sheet)
            & (pl.col("col_ref") == col_ref)
        )
        if served.height:
            return str(served["predicate_key"][0])
    raise AssertionError(f"{template_id}/{sheet}/{col_ref} is row-backed on neither side")


def _template_keys(recon: ReturnRecon, *, ours: bool, template_id: str = "c08_03") -> set[str]:
    """One side's comparison keys across the WHOLE template, derived here.

    Anchored on the membership legs rather than on ``_side_keys``, which is the
    function under test's own helper: a test sharing the implementation's reader
    would agree with it whatever either did.
    """
    side = recon.ours if ours else recon.theirs
    legs = side.membership.legs.filter(pl.col("template_id") == template_id)
    references = legs["exposure_reference"].to_list()
    bases = legs["source_exposure_reference"].to_list()
    return {
        str(base if base is not None else reference)
        for reference, base in zip(references, bases, strict=True)
        if (base if base is not None else reference) is not None
    }


def _absent_cell(matrix: pl.DataFrame, *, ours: bool) -> dict[str, object]:
    """The one matrix cell whose counterpart side is ``ABSENT_ROW``."""
    column = "their_row_ref" if ours else "our_row_ref"
    cells = matrix.filter(pl.col(column) == ABSENT_ROW)
    assert cells.height == 1, f"expected one absent cell on the {column} axis, got {cells.height}"
    return next(cells.iter_rows(named=True))


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_split_exposures_absent_legs_are_a_decomposition_not_a_scope_finding(
    framework: str,
) -> None:
    """``ours_only`` said "their extract has no such exposure". It was false.

    Our sealed ledger splits one guaranteed loan into ``L1__G_BANK`` and
    ``L1__REM``; their projected extract holds the same loan whole under ``L1``.
    The matrix's grain is the LEG — deliberately, because a guarantee leg landing
    under the guarantor's class and band is what substitution MEANS for the
    return — so neither of our legs has a counterpart at that grain, and neither
    does their whole leg. Every one of them therefore lands in ``ABSENT_ROW``.

    Measured on this fixture before the labels existed: 100,000 of our money and
    100,000 of theirs under ``ours_only`` / ``theirs_only`` (1,000,000 each on
    ``ead_final``), against two books that agree to the penny. The same shape on
    a three-substitution review portfolio put 210,000 and 270,000 there.

    THE FALSEHOOD IS THE LABEL AND NOT THE PLACEMENT, so nothing about the money
    changes here — asserted, because a fix that moved it would satisfy the label
    assertions while breaking the conservation invariant two tests above.
    """
    # Arrange
    recon = _split_recon([_SPLIT_G_LEG, _SPLIT_REM_LEG], [_WHOLE_LOAN], framework)
    predicate_key = _c08_03_predicate_key(recon)
    our_legs = recon.ours.membership.legs.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == CORPORATE)
        & (pl.col("predicate_key") == predicate_key)
    ).unique(subset=["exposure_reference"])

    # Assert the premise. Without a real split in the group the labels cannot
    # differ from the old ones and this test would pass on the pre-fix code.
    bases = our_legs["source_exposure_reference"].to_list()
    assert bases.count(_WHOLE_LOAN.reference) == 2, (
        f"the group holds no split exposure ({bases}) - every leg would be its own "
        "base and the old labels would already be correct"
    )
    assert _WHOLE_LOAN.reference in _template_keys(recon, ours=False), (
        "their side does not hold the base exposure anywhere on this template, so "
        "the absent legs really ARE a scope finding and the new label is not owed"
    )

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="rwa_final")
    ours_side = _absent_cell(matrix, ours=True)
    theirs_side = _absent_cell(matrix, ours=False)

    # Assert — both absent buckets are decomposition findings, and NO money is
    # left under a scope label anywhere on the matrix.
    assert ours_side["movement_basis"] == "same_base_ours"
    assert theirs_side["movement_basis"] == "same_base_theirs"
    assert matrix.filter(pl.col("movement_basis").is_in(_ABSENT_BASES)).height == 0

    # Assert — and the money sat exactly where it sat before.
    assert ours_side["legs"] == 2
    assert ours_side["money_ours"] == pytest.approx(_SPLIT_G_LEG.rwa + _SPLIT_REM_LEG.rwa)
    assert ours_side["money_theirs"] is None
    assert theirs_side["money_theirs"] == pytest.approx(_WHOLE_LOAN.rwa)
    assert theirs_side["money_ours"] is None


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_base_presence_test_spans_the_template_not_the_group(framework: str) -> None:
    """A guarantee leg lands on the GUARANTOR's sheet, so scoping decides this.

    ``L2`` is guaranteed by an institution, so our guarantee leg is reported
    under the institution class and the remainder under the obligor's. Their
    extract holds the whole loan under ``corporate``. On the INSTITUTION sheet
    their side therefore holds nothing whatever — not the base, not a sibling
    leg, not a single row — and a group-scoped or sheet-scoped presence test
    reports the guarantee leg as ``ours_only``: "their extract has no such
    exposure", about a loan their extract holds in full one sheet over.

    Only a TEMPLATE-scoped test sees it, which is why ``_same_base`` reuses
    ``_side_keys`` with ``sheet=None`` rather than inventing a third convention.
    The assertion below is the discriminator: their institution-sheet membership
    is asserted EMPTY, and the label is asserted to be a decomposition anyway.
    """
    # Arrange
    recon = _split_recon([_XSHEET_G_LEG, _XSHEET_REM_LEG], [_XSHEET_WHOLE], framework)
    sheet = _XSHEET_G_LEG.exposure_class
    predicate_key = _group_key_of(recon, "c08_03", sheet, "0090")
    their_sheet_legs = recon.theirs.membership.legs.filter(
        (pl.col("template_id") == "c08_03") & (pl.col("sheet") == sheet)
    )

    # Assert the premise — the two scopes must actually disagree here.
    assert their_sheet_legs.height == 0, (
        "their side holds legs on the institution sheet, so a sheet-scoped test "
        "could have found the base too and this fixture discriminates nothing"
    )
    assert _XSHEET_WHOLE.reference in _template_keys(recon, ours=False)

    # Act
    matrix = row_migration(recon, "c08_03", sheet, predicate_key, money_column="rwa_final")

    # Assert — the cross-sheet guarantee leg is a decomposition finding.
    cell = _absent_cell(matrix, ours=True)
    assert cell["movement_basis"] == "same_base_ours"
    assert cell["money_ours"] == pytest.approx(_XSHEET_G_LEG.rwa)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_cell_holding_a_split_leg_and_a_one_sided_leg_is_labelled_as_both(
    framework: str,
) -> None:
    """One matrix cell, two findings — and no single label is true of both.

    The two absent buckets are per-CELL, so a split leg and a genuinely one-sided
    leg that share a row share a label. Calling that cell ``same_base_ours``
    would deny a real scope gap; calling it ``ours_only`` would restate the very
    falsehood this change removes. It is reported as ``mixed_base_ours``, and the
    drill-down is what splits it.

    NOT A HYPOTHETICAL. The pre-existing ``_combined`` portfolio already produces
    one: ``CLASS_MOVER`` (their side puts it on the institution sheet) and
    ``ONLY_OURS`` (their side does not hold it at all) share cell
    ``(0030, absent)`` at 900,000 and 500,000 of ``ead_final``. This fixture is
    the isolated form of that cell.
    """
    # Arrange
    recon = _split_recon([_SPLIT_G_LEG, _SPLIT_REM_LEG, _SPLIT_ONLY_OURS], [_WHOLE_LOAN], framework)
    predicate_key = _c08_03_predicate_key(recon)

    # Act
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="rwa_final")
    cell = _absent_cell(matrix, ours=True)
    legs = migration_legs(
        recon,
        "c08_03",
        CORPORATE,
        predicate_key,
        str(cell["our_row_ref"]),
        ABSENT_ROW,
        money_column="rwa_final",
    )
    same_base = {leg.key for leg in legs if leg.same_base}
    scope = {leg.key for leg in legs if not leg.same_base}

    # Assert the premise — the cell must really hold BOTH kinds, or the label
    # under test is unreachable and this asserts nothing.
    assert same_base == {_SPLIT_G_LEG.reference, _SPLIT_REM_LEG.reference}
    assert scope == {_SPLIT_ONLY_OURS.reference}

    # Assert — the cell says so, and the money is still all three legs'.
    assert cell["movement_basis"] == "mixed_base_ours"
    assert cell["legs"] == 3
    assert cell["money_ours"] == pytest.approx(
        _SPLIT_G_LEG.rwa + _SPLIT_REM_LEG.rwa + _SPLIT_ONLY_OURS.rwa
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_matrix_counts_and_the_drill_list_are_one_computation(framework: str) -> None:
    """Every cell of the matrix, against the legs listed under it.

    The matrix's counts and the drill-down are derived from ONE frame
    (``_migration_pairs``), so a cell reporting three exposures and a list
    showing two is not a state this API can reach. Asserted as a census over the
    whole matrix rather than on one cell, because the failure mode is a grain
    difference and a grain difference shows up on the cells nobody picked.

    This is the same defect a separately-derived listing already produced on this
    page: a cell reporting 221,000 rendered 50 rows that agreed to the penny.
    """
    # Arrange
    recon = _combined(framework)
    predicate_key = _c08_03_predicate_key(recon)
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")

    # Assert the premise — a matrix of singleton cells could not show a grain
    # difference, and one with no absent bucket could not show a label one.
    assert matrix.height > 1
    assert (matrix["legs"] > 1).any(), "every cell holds one leg — the counts cannot disagree"
    assert (matrix["their_row_ref"] == ABSENT_ROW).any()

    # Act / Assert — cell by cell.
    for record in matrix.iter_rows(named=True):
        legs = migration_legs(
            recon,
            "c08_03",
            CORPORATE,
            predicate_key,
            str(record["our_row_ref"]),
            str(record["their_row_ref"]),
            money_column="ead_final",
        )
        where = f"{record['our_row_ref']}/{record['their_row_ref']}"
        assert len(legs) == record["legs"], where
        assert sum(leg.money_ours or 0.0 for leg in legs) == pytest.approx(
            record["money_ours"] or 0.0
        ), where
        assert sum(leg.money_theirs or 0.0 for leg in legs) == pytest.approx(
            record["money_theirs"] or 0.0
        ), where
        # ... and the cell's label is the aggregate of the legs' own flag.
        if record["movement_basis"] in {"same_base_ours", "same_base_theirs"}:
            assert all(leg.same_base for leg in legs), where
        if record["movement_basis"] in _ABSENT_BASES:
            assert not any(leg.same_base for leg in legs), where


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_drill_list_ranks_on_money_and_names_the_exposure_behind_each_leg(
    framework: str,
) -> None:
    """A split cell's legs are listed separately, each naming its base exposure.

    The matrix places legs, so the list under it must too — collapsing the two
    legs here would put the drill-down at a different grain from the count above
    it. ``base_key`` is what makes the relationship readable without inferring
    it from a naming convention: both legs of ``L1`` say ``L1``.
    """
    # Arrange
    recon = _split_recon([_SPLIT_G_LEG, _SPLIT_REM_LEG], [_WHOLE_LOAN], framework)
    predicate_key = _c08_03_predicate_key(recon)
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")
    cell = _absent_cell(matrix, ours=True)

    # Assert the premise — the two legs must be priced DIFFERENTLY, or the
    # ranking below holds whatever order the function returns.
    assert _SPLIT_G_LEG.ead > _SPLIT_REM_LEG.ead

    # Act
    legs = migration_legs(
        recon,
        "c08_03",
        CORPORATE,
        predicate_key,
        str(cell["our_row_ref"]),
        ABSENT_ROW,
        money_column="ead_final",
    )

    # Assert — two legs, biggest first, both pointing at the one exposure.
    assert [leg.key for leg in legs] == [_SPLIT_G_LEG.reference, _SPLIT_REM_LEG.reference]
    assert [leg.base_key for leg in legs] == [_WHOLE_LOAN.reference] * 2
    assert [leg.money_ours for leg in legs] == [
        pytest.approx(_SPLIT_G_LEG.ead),
        pytest.approx(_SPLIT_REM_LEG.ead),
    ]
    # Their side holds no leg under either KEY, which is not the same claim as
    # holding no money — never a zero.
    assert [leg.money_theirs for leg in legs] == [None, None]
    assert [leg.money for leg in legs] == [
        pytest.approx(_SPLIT_G_LEG.ead),
        pytest.approx(_SPLIT_REM_LEG.ead),
    ]


def test_a_matrix_pair_no_leg_occupies_lists_nothing() -> None:
    """An empty cell of a cross-tabulation is empty, not a refusal.

    Most of a migration matrix is empty by construction — it is our whole row
    axis against theirs — and the page renders no cell there either. Asserted
    against a pair both of whose rows are REAL, so the empty answer cannot be
    coming from an unknown row ref.
    """
    # Arrange
    recon = _combined("CRR")
    predicate_key = _c08_03_predicate_key(recon)
    matrix = row_migration(recon, "c08_03", CORPORATE, predicate_key, money_column="ead_final")
    occupied = set(zip(matrix["our_row_ref"], matrix["their_row_ref"], strict=True))
    empty = next(
        (ours, theirs)
        for ours in matrix["our_row_ref"].unique().sort()
        for theirs in matrix["their_row_ref"].unique().sort()
        if (ours, theirs) not in occupied
    )

    # Act / Assert
    assert migration_legs(recon, "c08_03", CORPORATE, predicate_key, *empty) == ()


def test_migration_legs_refuses_a_money_column_membership_does_not_carry() -> None:
    """The same guard ``row_migration`` has, because it is the same frame.

    A drill-down that accepted a column the matrix refuses would answer a
    question the page above it could not have asked.
    """
    # Arrange
    recon = _combined("CRR")
    predicate_key = _c08_03_predicate_key(recon)

    # Act / Assert
    with pytest.raises(ValueError, match="money_column"):
        migration_legs(
            recon, "c08_03", CORPORATE, predicate_key, "0030", "0030", money_column="pd_floored"
        )


# =============================================================================
# The term's own key counts have to be coherent
# =============================================================================


@pytest.mark.parametrize(
    ("keys", "differing_keys", "why"),
    [
        (3, 5, "more keys differ than the term holds"),
        (3, -1, "a negative count of differing keys"),
        (0, 1, "a key differs in a term with no keys at all"),
        (-1, 0, "a negative population"),
    ],
)
def test_a_cell_term_refuses_a_key_count_that_describes_no_population(
    keys: int, differing_keys: int, why: str
) -> None:
    """Requiring ``differing_keys`` forces a caller to STATE a number, not a
    coherent one.

    Omission became a ``TypeError`` when the field was made required; a term
    claiming 5 of its 3 keys differ still constructed silently. The three
    incoherent shapes are one bound apart — more differing than held, a
    negative count, and a negative population, the last raising for any
    ``differing_keys`` because no value satisfies ``0 <= d <= keys`` when
    ``keys`` is negative.

    A ``ValueError``, not an accumulated ``CalculationError``: this is a
    programming error in a constructor, not a data-quality finding about a
    portfolio.
    """
    # Act
    with pytest.raises(ValueError) as caught:
        CellTerm(name="measurement", amount=0.0, keys=keys, differing_keys=differing_keys)

    # Assert — the message NAMES the offending values. "invalid CellTerm" is
    # not diagnosable from a traceback; the two numbers are.
    message = str(caught.value)
    assert f"differing_keys={differing_keys}" in message, (message, why)
    assert f"keys={keys}" in message, (message, why)
    assert "measurement" in message, message


@pytest.mark.parametrize(
    ("keys", "differing_keys"),
    [(0, 0), (1, 0), (1, 1), (3, 0), (3, 3), (35, 4)],
)
def test_a_cell_term_accepts_every_coherent_key_count(keys: int, differing_keys: int) -> None:
    """The other half, without which the guard could reject everything.

    Both boundaries are included — ``differing_keys == 0`` and
    ``differing_keys == keys`` are the ordinary shapes, not edge cases: the
    former is a term where both sides agree about every key, the latter one
    where none do. ``(35, 4)`` is the probe cell's own measurement term.
    """
    # Act
    term = CellTerm(name="measurement", amount=0.0, keys=keys, differing_keys=differing_keys)

    # Assert
    assert (term.keys, term.differing_keys) == (keys, differing_keys)


def test_every_term_the_engine_builds_satisfies_the_constructor_bound() -> None:
    """The bound is a property of ``_terms``, not only of hand-built doubles.

    A validator that only ever sees test data is a validator nobody has run.
    This walks the terms of every additive cell the probe portfolio publishes
    and asserts the invariant independently of the constructor, so the two
    cannot both be wrong in the same direction.
    """
    # Arrange
    recon = _probe("CRR")
    row_ref = _probe_row(recon)
    diff = cell_diff(recon.ours.source, recon.theirs.source, "c08_03")
    checked = 0

    # Act / Assert
    for row in diff.iter_rows(named=True):
        result = decompose_cell(recon, "c08_03", row["sheet"], row["row_ref"], row["col_ref"])
        for term in result.terms:
            checked += 1
            assert 0 <= term.differing_keys <= term.keys, (
                f"{row['sheet']}/{row['row_ref']}/{row['col_ref']} {term.name}: "
                f"differing_keys={term.differing_keys} keys={term.keys}"
            )

    # Assert the census is not vacuous, and that it reached the probe cell,
    # whose measurement term is the one with a real gap between the counts.
    assert checked > 0, "no term was examined at all"
    probe = decompose_cell(recon, "c08_03", CORPORATE, row_ref, RWEA_COL)
    measurement = next(term for term in probe.terms if term.name == "measurement")
    assert measurement.differing_keys < measurement.keys, (
        "the probe's measurement term has no agreeing keys, so this census "
        "never saw the two counts differ"
    )
