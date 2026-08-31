"""
Unit tests: cell membership (reporting.membership).

Pins the properties a membership frame has to have before anything may compare
two sides of a return with it:

- **Every summable cell ties out.** Not a sample: for EVERY (row, column) pair
  carrying a row-backed ``Sum``/``SafeSum`` binding, summing the membership
  group that serves that column reproduces the figure production reported —
  all four templates, both frameworks. A row does NOT have one population, so
  a per-row membership would tie out only for whichever group it happened to
  select (measured: 80% of C 08.01's summable cells).
- **It is not vacuous.** The portfolio carries a guarantee that moves a leg to
  another sheet on the post-substitution basis, so the origin and post groups
  genuinely differ and the two-basis split is really exercised.
- **The hierarchy is measured and correct.** The empirically-derived parent set
  reproduces the published C 08.03 parent rows, parents equal the union of
  their children, and a leg lands in exactly one LEAF row per sheet per group.
- **Absence stays absence.** An uninstrumented template is skipped, an empty run
  yields the full typed schemas, and an unsupplied leg carrier is null — never a
  zero, and never a dropped column.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP template row/column layouts)
- docs/plans/return-reconciliation.md (Phase 1 — cell membership)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import polars as pl
import pytest

from rwa_calc.reporting.cellspec import CellSpec, RowPredicate, Sum, TemplateSpec
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS
from rwa_calc.reporting.kernel import available_columns, ensure_gross_side_carriers
from rwa_calc.reporting.lineage import LINEAGE_PLANS, _Provider, describe_cell
from rwa_calc.reporting.membership import (
    MEMBERSHIP_COLUMN_SCHEMA,
    MEMBERSHIP_SCHEMA,
    MEMBERSHIP_TEMPLATE_IDS,
    CellMembership,
    cell_membership,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan
from tests.fixtures.recon_ledger import with_reporting_ledger

FRAMEWORKS = ("CRR", "BASEL_3_1")

# The sealed per-side gross carriers — dropped to build the frame shape where
# the generator path and the lineage path can diverge.
GROSS_CARRIERS = ("reporting_gross_on_bs", "reporting_gross_off_bs")

# The guaranteed legs. Each originates in `corporate` and is substituted onto
# the `institution` sheet, so the origin and post-substitution groups of the
# two-basis templates hold genuinely different populations.
SUBSTITUTED_SA_RWEA = 400_000.0
SUBSTITUTED_IRB_RWEA = 540_000.0


class _FrameSource:
    """A minimal ResultsSource over a hand-built sealed ledger."""

    def __init__(self, frame: pl.LazyFrame, framework: str = "CRR") -> None:
        self._frame = frame
        self.framework = framework

    def scan_results(self) -> pl.LazyFrame:
        return self._frame


@dataclass(frozen=True)
class _Row:
    """A structural TemplateRow for a synthetic spec."""

    ref: str
    name: str


# =============================================================================
# The portfolio
# =============================================================================


def _sa_legs() -> list[dict[str, object]]:
    """Standardised legs across four obligor classes, both balance-sheet sides,
    one defaulted and one guaranteed onto the institution sheet."""
    return [
        _leg("SA_CORP_ON", "corporate", "standardised", "loan", 1_000_000.0, 1_000_000.0, cqs=3),
        _leg(
            "SA_CORP_OFF",
            "corporate",
            "standardised",
            "facility_undrawn",
            400_000.0,
            400_000.0,
            undrawn=800_000.0,
            ccf=0.5,
        ),
        _leg(
            "SA_CORP_DEF",
            "corporate",
            "standardised",
            "loan",
            500_000.0,
            750_000.0,
            defaulted=True,
        ),
        _leg(
            "SA_CORP_GTD",
            "corporate",
            "standardised",
            "loan",
            2_000_000.0,
            SUBSTITUTED_SA_RWEA,
            post_class="institution",
        ),
        _leg("SA_INST_ON", "institution", "standardised", "loan", 3_000_000.0, 600_000.0, cqs=2),
        _leg("SA_RET_ON", "retail_other", "standardised", "loan", 250_000.0, 187_500.0),
        _leg(
            "SA_RET_OFF",
            "retail_other",
            "standardised",
            "contingent",
            300_000.0,
            225_000.0,
            nominal=600_000.0,
            ccf=0.5,
        ),
        _leg(
            "SA_SOV_ON",
            "central_govt_central_bank",
            "standardised",
            "loan",
            5_000_000.0,
            0.0,
            cqs=1,
        ),
    ]


def _irb_legs() -> list[dict[str, object]]:
    """IRB legs whose PDs populate BOTH children of every C 08.03 parent band
    the corporate sheet emits — the parent flag is derived from the data, so a
    parent with a single populated child would be indistinguishable from a leaf.
    """
    corporate = [
        ("IRB_CORP_A", 0.0005, 1_000_000.0, 200_000.0),
        ("IRB_CORP_B", 0.0012, 1_100_000.0, 264_000.0),
        ("IRB_CORP_C", 0.0020, 1_200_000.0, 336_000.0),
        ("IRB_CORP_D", 0.0100, 1_300_000.0, 520_000.0),
        ("IRB_CORP_E", 0.0200, 1_400_000.0, 700_000.0),
        ("IRB_CORP_G", 0.0600, 1_600_000.0, 1_120_000.0),
        ("IRB_CORP_H", 0.1500, 1_700_000.0, 1_360_000.0),
    ]
    legs = [
        _leg(ref, "corporate", "foundation_irb", "loan", ead, rwa, pd=pd_value)
        for ref, pd_value, ead, rwa in corporate
    ]
    legs.append(
        _leg(
            "IRB_CORP_F",
            "corporate",
            "foundation_irb",
            "facility_undrawn",
            1_500_000.0,
            900_000.0,
            undrawn=3_000_000.0,
            ccf=0.5,
            pd=0.0300,
        )
    )
    legs.append(
        _leg(
            "IRB_CORP_GTD",
            "corporate",
            "foundation_irb",
            "loan",
            1_800_000.0,
            SUBSTITUTED_IRB_RWEA,
            post_class="institution",
            pd=0.2500,
        )
    )
    # Both institution PDs sit under parent band 0070, in DIFFERENT children —
    # so the parent-refs comparison is non-vacuous on this sheet too. With a
    # parentless pair here the assertion reduced to the empty set on both sides.
    legs.extend(
        _leg(ref, "institution", "foundation_irb", "loan", ead, rwa, pd=pd_value)
        for ref, pd_value, ead, rwa in (
            ("IRB_INST_A", 0.0100, 2_000_000.0, 300_000.0),
            ("IRB_INST_B", 0.0200, 2_100_000.0, 378_000.0),
        )
    )
    legs.extend(
        _leg(ref, "retail_mortgage", "advanced_irb", "loan", ead, rwa, pd=pd_value, lgd=0.15)
        for ref, pd_value, ead, rwa in (
            ("IRB_RETM_A", 0.0080, 3_000_000.0, 450_000.0),
            ("IRB_RETM_B", 0.0200, 3_100_000.0, 620_000.0),
            ("IRB_RETM_C", 0.0040, 3_200_000.0, 800_000.0),
        )
    )
    return legs


def _slotting_legs() -> list[dict[str, object]]:
    """Slotting legs spanning real sheet, category and maturity predicates."""
    return [
        _leg(
            "SL_PF_STRONG_SHORT",
            "specialised_lending",
            "slotting",
            "loan",
            1_000_000.0,
            500_000.0,
            sl_type="project_finance",
            slotting_category="strong",
            is_short_maturity=True,
        ),
        _leg(
            "SL_PF_GOOD_LONG",
            "specialised_lending",
            "slotting",
            "facility_undrawn",
            2_000_000.0,
            1_800_000.0,
            undrawn=4_000_000.0,
            ccf=0.5,
            sl_type="project_finance",
            slotting_category="good",
            is_short_maturity=False,
        ),
        _leg(
            "SL_PF_SAT_SHORT",
            "specialised_lending",
            "slotting",
            "loan",
            700_000.0,
            805_000.0,
            sl_type="project_finance",
            slotting_category="satisfactory",
            is_short_maturity=True,
        ),
        _leg(
            "SL_PF_WEAK_LONG",
            "specialised_lending",
            "slotting",
            "loan",
            400_000.0,
            1_000_000.0,
            sl_type="project_finance",
            slotting_category="weak",
            is_short_maturity=False,
        ),
        _leg(
            "SL_IPRE_SAT_SHORT",
            "specialised_lending",
            "slotting",
            "loan",
            500_000.0,
            575_000.0,
            sl_type="ipre",
            slotting_category="satisfactory",
            is_short_maturity=True,
        ),
        _leg(
            "SL_HVCRE_WEAK_LONG",
            "specialised_lending",
            "slotting",
            "loan",
            300_000.0,
            750_000.0,
            sl_type="hvcre",
            slotting_category="weak",
            is_short_maturity=False,
            is_hvcre=True,
        ),
    ]


def _leg(  # noqa: PLR0913 - one exposure row of the synthetic portfolio
    reference: str,
    exposure_class: str,
    approach: str,
    exposure_type: str,
    ead: float,
    rwa: float,
    *,
    post_class: str | None = None,
    undrawn: float = 0.0,
    nominal: float = 0.0,
    ccf: float = 1.0,
    cqs: int = 0,
    pd: float | None = None,
    lgd: float = 0.45,
    defaulted: bool = False,
    sl_type: str | None = None,
    slotting_category: str | None = None,
    is_short_maturity: bool | None = None,
    is_hvcre: bool = False,
) -> dict[str, object]:
    """One exposure row, in the raw shape the sealed ledger is derived from."""
    drawn = ead if exposure_type == "loan" else 0.0
    return {
        "exposure_reference": reference,
        "source_exposure_reference": reference,
        "counterparty_reference": f"CP_{reference}",
        "exposure_class": exposure_class,
        "exposure_class_applied": exposure_class,
        "exposure_class_post_crm": post_class or exposure_class,
        "approach_applied": approach,
        "approach_post_crm": approach,
        "exposure_type": exposure_type,
        "drawn_amount": drawn,
        "undrawn_amount": undrawn,
        "nominal_amount": nominal,
        "interest": 0.0,
        "ead_final": ead,
        "rwa_final": rwa,
        "risk_weight": rwa / ead if ead else 0.0,
        "ccf": ccf,
        "pd": pd,
        "pd_floored": pd,
        "lgd_floored": lgd if pd is not None else None,
        "irb_maturity_m": 2.5 if pd is not None else None,
        "expected_loss": (pd * lgd * ead) if pd is not None else 0.0,
        "scra_provision_amount": 0.0,
        "gcra_provision_amount": 0.0,
        "sa_cqs": cqs,
        "is_defaulted": defaulted,
        "reporting_leg_role": "whole",
        "sl_type": sl_type,
        "slotting_category": slotting_category,
        "is_short_maturity": is_short_maturity,
        "is_hvcre": is_hvcre,
    }


def _ledger(*, stripped: bool = False) -> pl.LazyFrame:
    """The sealed reporting ledger for the synthetic portfolio.

    Built through ``with_reporting_ledger`` so the frame stays shape-identical
    to the sealed aggregator exit the generators actually consume. ``stripped``
    drops the sealed per-side gross carriers, keeping their raw sources — the
    shape where the generator and lineage paths can diverge.
    """
    rows = _sa_legs() + _irb_legs() + _slotting_legs()
    raw = pl.LazyFrame(
        rows,
        schema_overrides={
            "pd": pl.Float64,
            "pd_floored": pl.Float64,
            "lgd_floored": pl.Float64,
            "irb_maturity_m": pl.Float64,
            "sa_cqs": pl.Int8,
            "is_short_maturity": pl.Boolean,
        },
    )
    ledger = with_reporting_ledger(raw)
    return ledger.drop(*GROSS_CARRIERS) if stripped else ledger


@lru_cache(maxsize=8)
def _bundle(framework: str, *, stripped: bool = False) -> COREPTemplateBundle:
    """The PRODUCTION COREP bundle — the figures the analyst actually sees.

    Deliberately not the lineage-path ``provider.generate``: only this path
    applies ``ensure_gross_side_carriers``, so anchoring the tie-outs here
    compares membership against the frame production really executed. Cached —
    one bundle build serves every parametrisation.
    """
    return COREPGenerator().generate_from_lazyframe(_ledger(stripped=stripped), framework=framework)


def _cell(
    frames: dict[str, pl.DataFrame], sheet: str | None, row_ref: str, col: str
) -> float | None:
    """One reported cell, or None where the row/column carries no figure."""
    key = sheet if sheet is not None else next(iter(frames))
    frame = frames.get(key)
    if frame is None or col not in frame.columns:
        return None
    match = frame.filter(pl.col("row_ref") == row_ref)
    if match.height == 0:
        return None
    value = match[col][0]
    return None if value is None else float(value)


# =============================================================================
# The tie-out — EVERY summable cell, against the group that serves it
# =============================================================================


@dataclass(frozen=True)
class _TieOut:
    """The census of one template's summable cells under one framework."""

    tied: int
    mismatches: list[str]
    unmapped: list[str]


def _tie_out_census(  # noqa: C901 - one walk over every (row, column) of a template
    template_id: str, framework: str, membership: CellMembership, *, stripped: bool
) -> _TieOut:
    """Sum each row-backed ``Sum``/``SafeSum`` cell's OWN group and compare.

    The reported side is the production bundle; the summed side reads the
    metric columns off the plan frame (which carries the template's derived
    carriers), narrowed to the legs the membership group holds. Cells whose
    metric column the frame does not carry are skipped — the generator renders
    those structurally, with no population to sum.
    """
    ledger = _ledger(stripped=stripped)
    # Ensured exactly as ``cell_membership`` and the generator both ensure it,
    # so all three sides read one frame.
    results = ensure_gross_side_carriers(ledger, available_columns(ledger))
    cols = available_columns(results)
    provider = LINEAGE_PLANS[template_id]
    plans = provider.plans(results, cols, framework, [])
    frames: dict[str, pl.DataFrame] = getattr(_bundle(framework, stripped=stripped), template_id)

    legs = membership.legs.filter(pl.col("template_id") == template_id)
    mapping = membership.columns.filter(pl.col("template_id") == template_id)
    tied = 0
    mismatches: list[str] = []
    unmapped: list[str] = []
    for sheet, plan in plans.items():
        sheet_map = mapping.filter(pl.col("sheet") == sheet)
        sheet_legs = legs.filter(pl.col("sheet") == sheet)
        for row in plan.spec.rows:
            for col_ref in plan.spec.column_refs:
                cell = plan.spec.cells.get((row.ref, col_ref))
                if cell is None:
                    continue
                query = describe_cell(
                    provider, plan, template_id, sheet, row.ref, col_ref, sealed=cols
                )
                if query.kind != "rows" or query.metric != "sum":
                    continue
                served = sheet_map.filter(
                    (pl.col("row_ref") == row.ref) & (pl.col("col_ref") == col_ref)
                )
                if served.height == 0:
                    unmapped.append(f"{sheet}/{row.ref}/{col_ref}")
                    continue
                key = served["predicate_key"][0]
                refs = sheet_legs.filter(
                    (pl.col("row_ref") == row.ref) & (pl.col("predicate_key") == key)
                )["exposure_reference"].to_list()
                subset = (
                    plan.frame.filter(pl.col("exposure_reference").is_in(refs))
                    if refs
                    else plan.frame.clear()
                )
                present = [c for c in query.metric_columns if c in subset.columns]
                if not present:
                    continue
                total = sum(float(subset[c].fill_null(0.0).sum() or 0.0) for c in present)
                if col_ref in plan.negative_cols:
                    total = -total
                reported = _cell(frames, sheet, row.ref, col_ref)
                agrees = abs(total) < 1e-9 if reported is None else abs(reported - total) <= 1e-6
                if agrees:
                    tied += 1
                else:
                    mismatches.append(
                        f"{sheet}/{row.ref}/{col_ref} [{key}] reported={reported} group={total}"
                    )
    return _TieOut(tied=tied, mismatches=mismatches, unmapped=unmapped)


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_every_summable_cell_ties_out_to_its_own_group(template_id: str, framework: str) -> None:
    # Arrange
    membership = cell_membership(_FrameSource(_ledger(), framework), [template_id])

    # Act
    census = _tie_out_census(template_id, framework, membership, stripped=False)

    # Assert — every cell mapped, every cell tied, over a real population.
    assert census.unmapped == []
    assert census.mismatches == []
    assert census.tied > 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_every_summable_cell_ties_out_without_the_gross_carriers(
    template_id: str, framework: str
) -> None:
    """The census on the frame shape where the two build paths can diverge.

    Only the generator entry applies ``ensure_gross_side_carriers``; the lineage
    path does not. **This IS the detector for that call.** Replacing it with the
    identity in ``cell_membership`` fails this test on ``c07_00`` under both
    frameworks: ``census.unmapped`` grows to 528 entries (CRR) and 1,220 (Basel
    3.1), first ``central_govt_central_bank/0010/0160``.

    Note WHICH limb fires, because it is not the obvious one.
    ``census.mismatches`` stays EMPTY — the tie-out is untouched, since these
    templates' row axes key ``exposure_type`` / ``bs_type`` / PD / class and
    never a gross carrier. What breaks is **mapping completeness**: C 07.00's
    CCF-bucket cells are bound as ``Sum(reporting_gross_off_bs)`` only when that
    carrier is present and fall back to a ``Formula`` constant otherwise, so
    without the ensure the module classifies them as not row-backed and they
    join no group — while this census, which ensures the frame itself, still
    expects every row-backed cell to be served. ``assert census.unmapped == []``
    is therefore the load-bearing assertion here, not the tie-out.

    Separately, and still true: the divergence the ensure call forecloses at the
    GENERATOR level is larger and lives one layer up — on this frame the
    lineage-path and production generators disagree on 141 (CRR) / 151 (Basel
    3.1) cells, which no test in this module can reach.
    """
    # Arrange
    ledger = _ledger(stripped=True)
    membership = cell_membership(_FrameSource(ledger, framework), [template_id])

    # Act
    census = _tie_out_census(template_id, framework, membership, stripped=True)

    # Assert
    assert census.unmapped == []
    assert census.mismatches == []
    assert census.tied > 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_row_carries_one_group_per_distinct_predicate(framework: str) -> None:
    """The measured fact the grain exists for: a row is not one population.

    C 08.03 is uniform (one group), but C 07.00 and C 08.01 split every row
    across the recorded two-basis boundary and its per-column narrowings. A
    single-population grain reproduced 80% of C 08.01's summable cells.
    """
    # Arrange / Act
    membership = cell_membership(_FrameSource(_ledger(), framework))
    groups = membership.columns.group_by(["template_id", "sheet", "row_ref"]).agg(
        pl.col("predicate_key").n_unique().alias("groups")
    )

    # Assert — C 08.03 uniform; the two-basis templates never are.
    uniform = groups.filter(pl.col("template_id") == "c08_03")
    assert uniform.height > 0
    assert uniform["groups"].max() == 1
    for template_id in ("c07_00", "c08_01"):
        split = groups.filter(pl.col("template_id") == template_id)
        assert split.height > 0
        assert split["groups"].min() > 1, template_id


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_two_basis_groups_hold_different_populations(framework: str) -> None:
    """The tie-out spans a priced crossing, in BOTH directions.

    Without it the origin and post groups coincide and every tie-out above
    would hold whichever group served the cell.
    """
    # Arrange / Act
    membership = cell_membership(_FrameSource(_ledger(), framework))

    # Assert — the guaranteed leg is on the obligor's sheet under one group and
    # the guarantor's under another, for real money.
    for template_id, reference, rwea in (
        ("c07_00", "SA_CORP_GTD", SUBSTITUTED_SA_RWEA),
        ("c08_01", "IRB_CORP_GTD", SUBSTITUTED_IRB_RWEA),
    ):
        crossed = membership.legs.filter(
            (pl.col("template_id") == template_id) & (pl.col("exposure_reference") == reference)
        )
        assert set(crossed["sheet"].to_list()) == {"corporate", "institution"}, template_id
        assert set(crossed["reporting_class_origin"].to_list()) == {"corporate"}
        assert crossed["rwa_final"][0] == pytest.approx(rwea)
        # ... and the two sheets reach it through DIFFERENT groups.
        by_sheet = {
            sheet: set(crossed.filter(pl.col("sheet") == sheet)["predicate_key"].to_list())
            for sheet in ("corporate", "institution")
        }
        assert by_sheet["corporate"].isdisjoint(by_sheet["institution"]), template_id


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_scoped_template_contributes_membership(framework: str) -> None:
    # Arrange / Act
    membership = cell_membership(_FrameSource(_ledger(), framework))

    # Assert — absence is this estate's dominant defect, so assert presence.
    assert set(membership.legs["template_id"].unique().to_list()) == set(MEMBERSHIP_TEMPLATE_IDS)
    assert membership.legs["is_parent_row"].any()
    assert not membership.legs["is_parent_row"].all()


# =============================================================================
# The hierarchy — derived from the data, checked against the published axis
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_c08_03_empirical_parents_reproduce_the_published_parent_refs(framework: str) -> None:
    """The strongest available evidence the parent derivation is right.

    The published C 08.03 row axis names its four hierarchical bands; the module
    never reads that list, deriving the flag from the leg sets alone.
    """
    # Arrange / Act
    membership = cell_membership(_FrameSource(_ledger(), framework), ["c08_03"])
    legs = membership.legs

    # Assert — per sheet, since only the emitted rows can be derived. Every
    # sheet must contribute a REAL parent: an equality that holds because both
    # sides are empty is not evidence, and one sheet used to pass that way.
    sheets = sorted(legs["sheet"].unique().to_list())
    assert sheets
    for sheet in sheets:
        rows = legs.filter(pl.col("sheet") == sheet)
        emitted = set(rows["row_ref"].unique().to_list())
        derived = set(rows.filter(pl.col("is_parent_row"))["row_ref"].unique().to_list())
        expected = C08_03_PD_PARENT_REFS & emitted
        assert expected, f"{sheet} emits no parent band -- the comparison would be vacuous"
        assert derived == expected, sheet


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_c08_03_parent_rows_equal_the_union_of_their_children(framework: str) -> None:
    # Arrange
    legs = cell_membership(_FrameSource(_ledger(), framework), ["c08_03"]).legs
    parents = legs.filter(pl.col("is_parent_row"))
    leaves = legs.filter(~pl.col("is_parent_row"))
    assert parents.height > 0

    # Act / Assert — a parent's legs are exactly its children's legs, and its
    # money is exactly their money (the published parent = sum of sub-bands).
    for sheet, row_ref in {
        (record["sheet"], record["row_ref"]) for record in parents.iter_rows(named=True)
    }:
        band = parents.filter((pl.col("sheet") == sheet) & (pl.col("row_ref") == row_ref))
        band_legs = set(band["exposure_reference"].to_list())
        children = leaves.filter(
            (pl.col("sheet") == sheet) & pl.col("exposure_reference").is_in(list(band_legs))
        )
        assert set(children["exposure_reference"].to_list()) == band_legs, f"{sheet}/{row_ref}"
        assert children["rwa_final"].sum() == pytest.approx(band["rwa_final"].sum())


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_leg_lands_in_exactly_one_c08_03_leaf_row_per_sheet(framework: str) -> None:
    # Arrange
    legs = cell_membership(_FrameSource(_ledger(), framework), ["c08_03"]).legs

    # Act
    leaves = legs.filter(~pl.col("is_parent_row"))
    per_leg = leaves.group_by(["sheet", "predicate_key", "exposure_reference"]).len()

    # Assert — the PD scale's LEAF bands partition; only its parents overlap.
    assert per_leg.height > 0
    assert per_leg["len"].max() == 1


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_non_parent_rows_never_exceed_their_group_total(template_id: str, framework: str) -> None:
    """The double-count guard, on EVERY template — not just the uniform one.

    A consumer that excludes parents and sums the rest must not exceed the
    group's own population. Scoping this to C 08.03 hid a 3x over-count on both
    two-basis templates, where several rows are DIFFERENT DECOMPOSITIONS of one
    total (C 08.01 row 0010 TOTAL, row 0020 on-balance-sheet, row 0070 obligor
    grades) and coincide whenever the sheet has no off-balance-sheet or slotting
    leg. A strict-superset test is false for all three, so all three read as
    leaves and the money counts three times.
    """
    # Arrange
    legs = cell_membership(_FrameSource(_ledger(), framework), [template_id]).legs
    assert legs.height > 0

    # Act / Assert — per group, non-parent EAD never exceeds the group's own.
    for (sheet, key), group in legs.group_by(["sheet", "predicate_key"]):
        non_parent = group.filter(~pl.col("is_parent_row"))
        total = group.unique(subset=["exposure_reference"])["ead_final"].sum() or 0.0
        assert (non_parent["ead_final"].sum() or 0.0) <= total + 1e-6, f"{sheet}/{key}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template_id", MEMBERSHIP_TEMPLATE_IDS)
def test_a_leg_lands_in_at_most_one_non_parent_row_per_group(
    template_id: str, framework: str
) -> None:
    """The same defect stated on the legs rather than the money."""
    # Arrange
    legs = cell_membership(_FrameSource(_ledger(), framework), [template_id]).legs

    # Act
    per_leg = (
        legs.filter(~pl.col("is_parent_row"))
        .group_by(["sheet", "predicate_key", "exposure_reference"])
        .len()
    )

    # Assert
    assert per_leg.height > 0
    assert per_leg["len"].max() == 1


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_summing_across_predicate_groups_is_not_the_sheet_total(framework: str) -> None:
    """Pins BOTH documented consumer traps, so neither can be "corrected" away.

    ``test_non_parent_rows_never_exceed_their_group_total`` is one-sided: a
    group that lost every leg satisfies ``0.00 <= total`` and sits inside a
    green suite. This guard bounds the other side by asserting that each shape
    still OCCURS.

    - Cross-group sheet sums over-count, because the groups are bases and a
      substituted leg is on both: 3.00x on C 07.00 retail_other, 1.86x on
      C 08.01 corporate (and 0.82x on C 07.00 corporate, where only some rows
      are decidable). If this stops happening, someone has made
      ``predicate_key`` a partition, which it is not.
    - Some sheets have no decidable leaf at all and sum to 0.00 — four of ten
      here. If this stops happening, someone has turned the tri-state's ``None``
      back into ``False`` and reopened the 3x double-count.
    - A single-group template has nothing to sum across, so C 08.03 is exact.
    """
    # Arrange
    legs = cell_membership(_FrameSource(_ledger(), framework)).legs

    # Act — the naive per-sheet aggregation a reader would reach for.
    shapes: dict[tuple[str, str], tuple[float, float]] = {}
    for (template_id, sheet), group in legs.group_by(["template_id", "sheet"]):
        naive = group.filter(~pl.col("is_parent_row"))["ead_final"].sum() or 0.0
        total = group.unique(subset=["exposure_reference"])["ead_final"].sum() or 0.0
        shapes[(template_id, sheet)] = (float(naive), float(total))

    # Assert — both shapes occur, and the single-group template is exact.
    assert shapes
    over = {key for key, (naive, total) in shapes.items() if naive > total + 1e-6}
    leafless = {key for key, (naive, total) in shapes.items() if naive == 0.0 < total}
    assert over, "cross-group summing no longer over-counts -- is predicate_key a partition now?"
    assert leafless, "no sheet is leaf-less -- has None collapsed back to False?"
    for (template_id, sheet), (naive, total) in shapes.items():
        if template_id == "c08_03":
            assert naive == pytest.approx(total), sheet


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_indistinguishable_rows_report_null_not_false(framework: str) -> None:
    """The tri-state's null branch exists and is reached on real data.

    C 08.01's TOTAL / on-balance-sheet / obligor-grades rows are three
    decompositions of one book and coincide on a sheet with no
    off-balance-sheet or slotting leg. Containment cannot rank them, so each
    reports NULL. Asserting only True/False would let the null branch rot.
    """
    # Arrange / Act
    legs = cell_membership(_FrameSource(_ledger(), framework), ["c08_01"]).legs

    # Assert — the null state occurs, and every row carrying it shares its legs
    # with another row of the same group (which is what "cannot tell" means).
    unknown = legs.filter(pl.col("is_parent_row").is_null())
    assert unknown.height > 0
    for (sheet, key, row_ref), group in unknown.group_by(["sheet", "predicate_key", "row_ref"]):
        mine = set(group["exposure_reference"].to_list())
        siblings = legs.filter(
            (pl.col("sheet") == sheet)
            & (pl.col("predicate_key") == key)
            & (pl.col("row_ref") != row_ref)
        )
        twins = [
            set(siblings.filter(pl.col("row_ref") == other)["exposure_reference"].to_list())
            for other in siblings["row_ref"].unique().to_list()
        ]
        assert any(other == mine for other in twins), f"{sheet}/{key}/{row_ref}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_containment_is_measured_within_a_group_not_across_bases(framework: str) -> None:
    """A parent's children are in ITS group, never in the other basis's.

    The origin and post populations of a row differ by whatever substituted,
    which is a basis difference and not a hierarchy — deriving containment
    across them would flag a row as its own parent's child.
    """
    # Arrange / Act
    legs = cell_membership(_FrameSource(_ledger(), framework), ["c08_01"]).legs
    parents = legs.filter(pl.col("is_parent_row"))

    # Assert — every parent row is a strict superset of a sibling in the SAME
    # group on the SAME sheet.
    assert parents.height > 0
    for sheet, key, row_ref in {
        (r["sheet"], r["predicate_key"], r["row_ref"]) for r in parents.iter_rows(named=True)
    }:
        group = legs.filter((pl.col("sheet") == sheet) & (pl.col("predicate_key") == key))
        mine = set(group.filter(pl.col("row_ref") == row_ref)["exposure_reference"].to_list())
        siblings = [
            set(group.filter(pl.col("row_ref") == other)["exposure_reference"].to_list())
            for other in group["row_ref"].unique().to_list()
            if other != row_ref
        ]
        assert any(mine > other for other in siblings), f"{sheet}/{key}/{row_ref}"


# =============================================================================
# Absence — skipped templates, empty runs, unsupplied carriers
# =============================================================================


def test_an_uninstrumented_template_id_is_skipped_and_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange — c02_00 is the one COREP template with no execution plan to read.
    source = _FrameSource(_ledger())

    # Act
    with caplog.at_level(logging.WARNING, logger="rwa_calc.reporting.membership"):
        membership = cell_membership(source, ["c02_00", "not_a_template", "c08_03"])

    # Assert — skipped and named, never resolved to a guessed row set.
    assert set(membership.legs["template_id"].unique().to_list()) == {"c08_03"}
    assert "c02_00" in caplog.text
    assert "not_a_template" in caplog.text


def test_empty_results_yield_empty_frames_with_the_full_typed_schemas() -> None:
    # Arrange — a zero-row ledger of the right shape (no template produces).
    source = _FrameSource(_ledger().head(0))

    # Act
    membership = cell_membership(source)

    # Assert — the full schemas, not bare empty frames a consumer cannot join.
    assert membership.legs.height == 0
    assert membership.columns.height == 0
    assert dict(membership.legs.schema) == MEMBERSHIP_SCHEMA
    assert dict(membership.columns.schema) == MEMBERSHIP_COLUMN_SCHEMA


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_an_unsupplied_leg_carrier_is_null_never_zero(framework: str) -> None:
    # Arrange — a ledger carrying neither the leg role nor the source reference.
    ledger = _ledger().drop("reporting_leg_role", "source_exposure_reference")

    # Act
    legs = cell_membership(_FrameSource(ledger, framework), ["c08_03"]).legs

    # Assert — the columns survive, typed, and hold nulls rather than a value
    # the run never produced.
    assert legs.height > 0
    assert legs.schema["reporting_leg_role"] == pl.String
    assert legs["reporting_leg_role"].null_count() == legs.height
    assert legs["source_exposure_reference"].null_count() == legs.height


# =============================================================================
# Group construction on a synthetic spec
# =============================================================================


def _synthetic_provider(
    cells: dict[tuple[str, str], CellSpec], row_refs: tuple[str, ...] = ("0010",)
) -> _Provider:
    """A two-column single-frame template over two disjoint obligor classes."""
    frame = pl.DataFrame(
        {
            "reporting_class_origin": ["corporate", "institution"],
            "exposure_reference": ["E1", "E2"],
            "ead_final": [10.0, 20.0],
            "rwa_final": [5.0, 6.0],
        }
    )
    spec = TemplateSpec(
        name="t_split",
        rows=tuple(_Row(ref, f"Row {ref}") for ref in row_refs),
        column_refs=("0040", "0050"),
        cells=cells,
        empty_cell="zero",
    )
    plan = SheetPlan(spec=spec, frame=frame, ctx=ReportingContext(), negative_cols=frozenset())

    def _plans(
        _results: pl.LazyFrame, _cols: set[str], _framework: str, _errors: list[str]
    ) -> dict[str, SheetPlan]:
        return {"__single__": plan}

    def _generate(
        _results: pl.LazyFrame, _cols: set[str], _framework: str, _errors: list[str]
    ) -> dict[str, pl.DataFrame]:
        return {}

    return _Provider(
        plans=_plans,
        generate=_generate,
        scope=("synthetic",),
        sheet_label="",
        single_frame=True,
    )


def test_two_incomparable_cell_populations_become_two_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disjoint populations on one row are two memberships, not a contradiction.

    The single-population grain had to arbitrate this and could only be wrong;
    the group grain represents it directly.
    """
    # Arrange — two cells on one row over DISJOINT populations.
    provider = _synthetic_provider(
        {
            ("0010", "0040"): CellSpec(
                Sum("ead_final"), predicate=RowPredicate(classes_origin=("corporate",))
            ),
            ("0010", "0050"): CellSpec(
                Sum("ead_final"), predicate=RowPredicate(classes_origin=("institution",))
            ),
        }
    )
    monkeypatch.setitem(LINEAGE_PLANS, "t_split", provider)

    # Act
    membership = cell_membership(
        _FrameSource(pl.LazyFrame({"exposure_reference": ["E1"]})), ["t_split"]
    )

    # Assert — one group per column, each holding its own leg, and the mapping
    # names which column each serves.
    by_key = {
        record["predicate_key"]: record["exposure_reference"]
        for record in membership.legs.iter_rows(named=True)
    }
    assert by_key == {"0040": "E1", "0050": "E2"}
    served = {
        record["col_ref"]: record["predicate_key"]
        for record in membership.columns.iter_rows(named=True)
    }
    assert served == {"0040": "0040", "0050": "0050"}
    # The single-frame sheet axis is null.
    assert membership.legs["sheet"].null_count() == membership.legs.height


def test_cells_sharing_a_predicate_share_one_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The frame stays compact: identical predicates collapse to one group,
    anchored on the first published column that carries them."""
    # Arrange — both cells over the whole frame.
    provider = _synthetic_provider(
        {
            ("0010", "0040"): CellSpec(Sum("ead_final")),
            ("0010", "0050"): CellSpec(Sum("rwa_final")),
        }
    )
    monkeypatch.setitem(LINEAGE_PLANS, "t_split", provider)

    # Act
    membership = cell_membership(
        _FrameSource(pl.LazyFrame({"exposure_reference": ["E1"]})), ["t_split"]
    )

    # Assert — one group, two legs, both columns mapped to it.
    assert membership.legs["predicate_key"].unique().to_list() == ["0040"]
    assert membership.legs.height == 2
    assert set(membership.columns["col_ref"].to_list()) == {"0040", "0050"}
    assert membership.columns["predicate_key"].unique().to_list() == ["0040"]


def test_an_empty_row_does_not_make_its_siblings_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty set is a subset of every other, which is not a hierarchy.

    Counting an unpopulated row as a child would flag every populated row on the
    sheet as a parent — and a template whose every row is a parent is exactly the
    double-count ``is_parent_row`` exists to prevent.
    """
    # Arrange — row 0010 holds both legs; row 0020 matches a class with none.
    provider = _synthetic_provider(
        {
            ("0010", "0040"): CellSpec(Sum("ead_final")),
            ("0020", "0040"): CellSpec(
                Sum("ead_final"), predicate=RowPredicate(classes_origin=("retail_other",))
            ),
        },
        row_refs=("0010", "0020"),
    )
    monkeypatch.setitem(LINEAGE_PLANS, "t_split", provider)

    # Act
    membership = cell_membership(
        _FrameSource(pl.LazyFrame({"exposure_reference": ["E1"]})), ["t_split"]
    )

    # Assert — the empty row contributes no legs, and 0010 stays a leaf.
    assert set(membership.legs["row_ref"].to_list()) == {"0010"}
    assert not membership.legs["is_parent_row"].any()
