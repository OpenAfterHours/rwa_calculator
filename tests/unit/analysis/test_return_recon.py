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

from rwa_calc.analysis.legacy_ledger import LegacyLedgerSource, ledger_coverage
from rwa_calc.analysis.return_recon import (
    ABSENT_ROW,
    CELL_DIFF_SCHEMA,
    PLACEMENT_ATTRIBUTION,
    TERM_NAMES,
    UNDECIDABLE_ROW,
    CellDecomposition,
    ReturnRecon,
    build_recon,
    cell_diff,
    decompose_cell,
    diff_cells,
    row_migration,
)
from rwa_calc.reporting.membership import MEMBERSHIP_TEMPLATE_IDS

FRAMEWORKS = ("CRR", "BASEL_3_1")

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

    def row(self) -> dict[str, object]:
        drawn = self.ead if self.exposure_type == "loan" else 0.0
        return {
            "exposure_reference": self.reference,
            "source_exposure_reference": self.reference,
            "counterparty_reference": f"CP_{self.reference}",
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
    assert set(matrix["movement_basis"].to_list()) <= {
        "agreed",
        "value_driven",
        "ours_only",
        "theirs_only",
        "undecidable",
    }
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
