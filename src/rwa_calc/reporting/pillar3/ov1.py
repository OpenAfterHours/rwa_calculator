"""
Pillar 3 OV1 — Overview of RWEAs, as a declarative TemplateSpec.

Pipeline position:
    sealed aggregator-exit ledger + ReportingContext
        -> build_ov1_spec(framework) -> cellspec.execute() -> OV1 DataFrame

Cell semantics (golden-gated):

- Row 29 (Total): Sum of ``rwa_final`` over the WHOLE ledger — an
  all-risk-type total; column c takes the generic 8% own-funds shim.
- Row 1 ("Credit risk (EXCLUDING CCR)"): Sum of ``rwa_final`` over the
  NON-CCR legs. The instructions are explicit — "RWEAs ... for CCR are
  excluded and disclosed in rows 6 and 16 of this template" — so rows 1-5
  are cut by ``risk_type``, NEVER by the approach label: under CRR the CCR
  legs carry ``reporting_approach_origin == "standardised"``, so an
  approach-keyed exclusion no-ops exactly where the defect lives (recorded
  fix 2026-07-14, docs/plans/c07-ccr-derivatives.md §4 D1/D4; before it,
  row 1 was the whole ledger and equalled row 29 on a book with CCR).
- Row 2 (SA incl. equity) and the per-approach rows (3 F-IRB, 4 slotting,
  UK4a equity, 5 A-IRB): Sum of ``rwa_final`` over the ORIGIN approach
  (``reporting_approach_origin`` — the recorded pre-substitution basis;
  the post-substitution retarget is the plan's F-decision family),
  conjoined with the same non-CCR cut — they are "of which" rows of row 1
  and inherit its exclusion. These cells report 0.0 for an absent approach
  (per-cell zero override on the Pillar 3 null template).
- The CCR block (6 / 7 / 8 / UK8a / 9), keyed on the module-owned derived
  Booleans below:
    * 6 (Chapter 6) is a POPULATION — ``risk_type`` in the CCR set — and
      NOT ``Formula(7 + 8 + UK8a + 9)``. That choice does NOT turn the
      "children partition the parent" tie-out into a real assertion: row 9
      is DEFINED as the residual (``is_ccr & ~is_sa_ccr & ~is_ccp``), so
      ``6 == 7 + UK8a + 9`` holds algebraically whichever way row 6 is
      bound. What it does buy is smaller and worth stating honestly — the
      tie-out exercises the executor's population plumbing end to end, and
      it catches a MIS-KEYED row-6 population (a CCR risk type missing from
      ``_CCR_RISK_TYPES``, say) that a Formula parent would silently absorb.
    * 7 (Section 3, SA-CCR) is a CCR derivative NOT faced to a CCP; UK8a
      (Section 9) is the CCP-faced leg, whatever its risk type; 9 is the
      explicit residual ("CCR RWEAs ... that are not disclosed under rows 7,
      8 and UK 8a") — the CCR legs that are neither SA-CCR-against-a-non-CCP
      (row 7), nor IMM (row 8), nor faced to a CCP (row UK8a). Today that is
      exactly the SFTs faced to a NON-CCP counterparty: an SFT faced to a CCP
      is inside Section 9's scope (Art. 301(1)(b)) and routes to UK8a, and so
      does a default-fund contribution (Art. 307-309, also inside Section 9).
    * 8 (Section 6, IMM) is bound to NOTHING and stays null: IMM is not
      implemented, and null is not the same claim as 0.0 (CCR1 row 2 is
      the precedent).
  Rows 6/7/UK8a/9 zero-fill — "this book has no CCR" is a claim the
  calculator can make.
- Row 24: the Art. 48(4) threshold-item 250%-RW memo. UKB OV1 row 24
  ("Amounts below the thresholds for deduction (subject to 250% risk weight)")
  is NOT "any leg risk-weighted at 250%" — it is specifically the items subject
  to a 250% risk weight under Art. 48(4) CRR: deferred-tax assets that arise
  from temporary differences and significant investments in a financial-sector
  entity's CET1, each below the 10%-of-CET1 deduction threshold of Art. 48(1)
  (PS1/26 Annex II, "Template UKB OV1", row 24, pp. 4-5). It is disclosed "for
  information purposes only as the amount included here is also included in
  row 1". The sealed ledger carries no flag that positively identifies an
  Art. 48(4) item, so this is a RECORDED APPROXIMATION: the cell sums
  ``rwa_final`` over legs whose ORIGIN class is the SA "Other items" bucket
  (``reporting_class_origin == "other"`` — the CR4/CR5 row-16 class under which
  the codebase files "items below deduction thresholds") AND whose
  ``reporting_rw`` is in the [2.495, 2.505] band. Restricting to "other items"
  is what excludes the equity holdings that carry an exactly-250% SA risk weight
  under Basel 3.1 (Art. 133): equity exposures are definitionally NOT Art. 48(4)
  threshold-deduction items, so the earlier unrestricted 250%-RW predicate
  MIS-STATED row 24 by the whole equity RWEA (the rich B31 book's 2.5M holding).
  The residual — we cannot distinguish, within the "other" class, a genuine
  Art. 48(4) item from a hypothetical non-threshold "other item" that happens to
  carry a 250% RW — is pinned in test_r16_ov1_row24_threshold.py. The
  approximation also UNDER-includes: a significant investment in a
  financial-sector entity's CET1 held as shares would classify as an equity
  exposure, not "other", and is silently excluded here.
- Rows 11-14 (Basel 3.1 equity sub-approaches): equity-origin legs narrowed
  by the presence-TOLERANT discriminators (``equity_transitional_approach``
  / ``ciu_approach`` — F6 columns the seal strips today, so these cells are
  recorded permanently-null in production).
- Row 26: output-floor multiplier (first non-null ``output_floor_pct``).
- Row 27: OF-ADJ from the output-floor summary (SideContext).
- Column b (T-1) stays null throughout; column c = a x 0.08 except the
  floor rows 26/27 (the no-shim set).

Lineage-instrumented (R21): ``ov1_plans`` exposes the single (no sheet axis)
execution plan — its frame is the full sealed ledger with the derived CCR
discriminators (``ov1_is_ccr`` and its three-way partition) — so
``reporting.lineage`` can drill into a reported cell. The plan carries NO
output-floor summary (the current-period / no-side view). Because the REPORTED
template is generated WITH the run's summary (api/rest.py get_template_bundles),
row 27's OF-ADJ (a ``SideContext``) would render null on this plan — a figure
that contradicts the screen — so the resolver REFUSES that cell (a distinct 404,
mirroring the treatment of CR8's prior-period rows) rather than serving the
null. Row 26's multiplier (a ``FirstNonNull``) reads the sealed
``output_floor_pct`` and drills down normally. ``generate_ov1`` keeps its
distinct signature (it threads the summary) and is NOT the provider generator —
``ov1_frames`` is.

References:
- CRR Part 8 Art. 438; Art. 48(4) (row 24 threshold items); PRA PS1/26
  Annex II ("Template UKB OV1", incl. rows 11-14 Art. 132-132C CIU
  sub-approaches and the floor rows 26/27)
- CRR Art. 274-280f (SA-CCR, Chapter 6 Section 3); Art. 283 (IMM,
  Section 6); Art. 300-311 (exposures to CCPs, Section 9 — including
  Art. 301(1)(b), which puts SFTs faced to a CCP in Section 9's scope, and
  Art. 307-309, the default-fund-contribution charge)
- docs/plans/phase7-declarative-reporting.md §3.2 (S8 — Pillar 3 first)
- docs/plans/c07-ccr-derivatives.md §4 D1 (the CCR block this adds)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    FirstNonNull,
    Formula,
    RowPredicate,
    SideContext,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import OV1_COLUMNS, get_ov1_rows
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.contracts.bundles import OutputFloorSummary

# Single-frame lineage key: OV1 has no sheet axis, so its one plan keys under a
# canonical name (see reporting.plans / _resolve_sheet_key single_frame path).
_SHEET_KEY = "ov1"

# Rows whose column ``a`` sums one origin approach (0.0 when absent).
_APPROACH_REFS: dict[str, tuple[str, ...]] = {
    "2": ("standardised", "equity"),
    "3": ("foundation_irb",),
    "4": ("slotting",),
    "UK4a": ("equity",),
    "5": ("advanced_irb",),
}

# Basel 3.1 equity sub-approach memo rows: origin equity legs narrowed by a
# presence-tolerant discriminator column == value (F6-stripped today).
_EQUITY_SUBAPPROACH_REFS: dict[str, tuple[str, str]] = {
    "11": ("equity_transitional_approach", "irb_transitional"),
    "12": ("ciu_approach", "look_through"),
    "13": ("ciu_approach", "mandate_based"),
    "14": ("ciu_approach", "fallback"),
}

# Floor rows whose column ``a`` is a multiplier (26) or RWA adjustment (27).
_FLOOR_NO_SHIM_REFS: frozenset[str] = frozenset({"26", "27"})

# The CCR population (Chapter 6). Keyed by ``risk_type``, NEVER by the approach
# label: under CRR the CCR legs carry ``standardised`` and under Basel 3.1
# ``standardised_ccr`` (the output-floor relabel), so an approach-based rule
# no-ops exactly where the CRR defect lives (§4 D4). THREE risk types, not two:
# CCP default-fund contributions (Art. 307-309) are a Chapter 6 charge carrying
# ``rwa_final``, so they belong in row 6 — and in row UK8a, NOT in the row-9
# residual: Art. 307-309 sits INSIDE Section 9 (Art. 300-311), so a default-fund
# contribution IS an "exposure to a CCP" in the disclosure taxonomy (the CCR8
# template carries explicit pre-funded / unfunded default-fund rows under both
# its QCCP and non-QCCP blocks). That is already what the code does, with no
# special-casing: the CCR stage gives the synthetic default-fund row the CCP as
# its counterparty (``counterparty_reference = ccp_reference``), enrichment
# stamps ``cp_entity_type == "ccp"``, and ``_IS_CCP`` fires. No fixture carries
# one today — latent, not a reason to drop it.
#
# Deliberately LOCAL to OV1 (the of02.py / cms1.py precedent): each template owns
# its own tuple, so one template's recorded basis cannot leak into another's
# (docs/plans/c07-ccr-derivatives.md §4 D4).
_CCR_RISK_TYPES: tuple[str, ...] = ("CCR_DERIVATIVE", "CCR_SFT", "CCR_DEFAULT_FUND")

# Module-owned derived discriminator columns (the cms1.py / of02.py pattern):
# RowPredicate carries no negation and no risk-type field, so the CCR cut and its
# three-way partition are derived in ``_prepare`` as Boolean flags and matched
# with tolerant ``equals``.
_IS_CCR: str = "ov1_is_ccr"
_IS_SA_CCR: str = "ov1_is_sa_ccr"
_IS_CCP: str = "ov1_is_ccp"
_IS_OTHER_CCR: str = "ov1_is_other_ccr"

# The CCR block's populated rows -> the derived flag each one selects. Row 8
# (IMM, Section 6) is absent on purpose: it binds NO CellSpec and stays null.
_CCR_ROW_FLAGS: dict[str, str] = {
    "6": _IS_CCR,
    "7": _IS_SA_CCR,
    "UK8a": _IS_CCP,
    "9": _IS_OTHER_CCR,
}

# Rows 1-5 are "Credit risk (excluding CCR)" and its "of which" rows: the CCR
# legs are excluded here and disclosed in the block above.
_NON_CCR: RowPredicate = RowPredicate(equals=((_IS_CCR, False),))


def _own_funds_shim(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column c = a x 0.08 (own-funds requirement) when a is populated."""
    a = cells["a"]
    return a * 0.08 if a is not None else None


def _row_a_cell(ref: str) -> CellSpec | None:
    """The column-``a`` binding for one OV1 row ref (None = stays null)."""
    if ref == "29":
        return CellSpec(Sum("rwa_final"))
    if ref == "1":
        return CellSpec(Sum("rwa_final"), predicate=_NON_CCR)
    if ref in _CCR_ROW_FLAGS:
        return CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(equals=((_CCR_ROW_FLAGS[ref], True),)),
            empty_cell="zero",
        )
    if ref == "24":
        # Art. 48(4) threshold items only: the SA "Other items" class (the row-16
        # bucket where "items below deduction thresholds" are filed) at a 250% RW.
        # The "other" restriction excludes the Basel 3.1 Art. 133 equity holdings
        # that also weight exactly 250% but are NOT threshold-deduction items — a
        # recorded approximation (see module docstring; pins in
        # test_r16_ov1_row24_threshold.py).
        return CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(classes_origin=("other",), rw_between=(2.495, 2.505)),
        )
    if ref in _EQUITY_SUBAPPROACH_REFS:
        return CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(
                approaches_origin=("equity",), equals=(_EQUITY_SUBAPPROACH_REFS[ref],)
            ),
        )
    if ref == "26":
        return CellSpec(FirstNonNull("output_floor_pct"))
    if ref == "27":
        return CellSpec(SideContext("of_adj"))
    if ref in _APPROACH_REFS:
        # An "of which" of row 1 inherits row 1's CCR exclusion.
        return CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(approaches_origin=_APPROACH_REFS[ref], equals=_NON_CCR.equals),
            empty_cell="zero",
        )
    return None


@cites("PS1/26, paragraph 132")
def build_ov1_spec(framework: str) -> TemplateSpec:
    """Build the OV1 TemplateSpec for one framework's row set.

    Carries the Art. 132-132C citation for the Basel 3.1 equity sub-approach
    memo rows 11-14 (moved here with the semantics from the retired
    ``_ov1_equity_subapproach_rwa`` generator helper).
    """
    rows = tuple(get_ov1_rows(framework))
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        a_cell = _row_a_cell(row.ref)
        if a_cell is not None:
            cells[(row.ref, "a")] = a_cell
            if row.ref not in _FLOOR_NO_SHIM_REFS:
                cells[(row.ref, "c")] = CellSpec(Formula(refs=("a",), fn=_own_funds_shim))
    return TemplateSpec(
        name="ov1",
        rows=rows,
        column_refs=tuple(col.ref for col in OV1_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


_OV1_SPECS: dict[str, TemplateSpec] = {
    framework: build_ov1_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def ov1_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single OV1 execution plan (the lineage seam).

    OV1 has no sheet axis, so the one plan keys under the single-frame
    canonical key. The plan's frame is the full sealed ledger carrying the four
    derived CCR discriminator columns (``ov1_is_ccr`` and its three-way
    partition) the CCR-block cell predicates key off. NO output-floor summary is
    threaded — the current-period / no-side view — so the resolver REFUSES row
    27's OF-ADJ (a ``SideContext(of_adj)`` whose ``side_value`` is None here),
    rather than serving a null the summary-generated report would contradict.
    Preserves the imperative generator's error contract: a missing ``rwa_final``
    column records the OV1 error and yields no plan. There is no post-execute
    pass, so ``negative_cols`` is empty.
    """
    if "rwa_final" not in cols:
        errors.append("OV1: missing RWA column")
        return {}
    spec = _OV1_SPECS.get(framework) or build_ov1_spec(framework)
    return {
        _SHEET_KEY: SheetPlan(
            spec=spec,
            frame=_prepare(results, cols).collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def ov1_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the current-period OV1 frame for lineage (keyed like ``ov1_plans``).

    The lineage-facing generator: it mirrors ``ov1_plans`` and executes each
    plan under the same key, so a cell's reported value and its spec are looked
    up under the same key. The plan carries NO output-floor summary, so this
    frame renders row 27's OF-ADJ as null — which is exactly why the resolver
    REFUSES that cell rather than serving the null (the report is generated WITH
    the summary). ``generate_ov1`` is the dispatch entry that threads the summary
    (its extra parameter keeps it OUT of the 4-arg provider signature). OV1 has
    no post-execute pass, so this is a plain ``execute``.
    """
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in ov1_plans(results, cols, framework, errors).items()
    }


def generate_ov1(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    output_floor_summary: OutputFloorSummary | None,
) -> pl.DataFrame | None:
    """Execute OV1 over the full sealed ledger.

    The dispatch entry: it threads the EXTERNAL output-floor summary (which the
    current-period lineage view cannot carry) into row 27's OF-ADJ
    ``SideContext``, reusing ``ov1_plans`` for the spec and prepared frame so
    the reported frame and the lineage view differ ONLY by that side input.
    Preserves the imperative generator's contract: a missing ``rwa_final``
    column (impossible on the sealed ledger; reachable via direct invocation
    with synthetic frames) records the OV1 error and yields no template.
    """
    plans = ov1_plans(results, cols, framework, errors)
    if not plans:
        return None
    plan = plans[_SHEET_KEY]
    ctx = ReportingContext(output_floor_summary=output_floor_summary)
    return execute(plan.spec, plan.frame, ctx)


def _prepare(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Derive the four CCR discriminator columns the cell predicates key off.

    All four are ALWAYS derived — a missing source column yields a literal
    False, never an absent column. That matters: an absent column makes a
    tolerant ``equals`` term match NOTHING, which would drop the whole book out
    of row 1 rather than route it to the non-CCR side.

    Rows 7 / UK8a / 9 PARTITION row 6, so they are cut mutually exclusively:

    - 7 (Section 3, SA-CCR): a CCR derivative NOT faced to a CCP.
    - UK8a (Section 9): the CCP-faced legs. Section 9 (Art. 300-311) scopes
      "exposures to a CCP" — ALL CCPs, qualifying and non-qualifying — so this
      is the literal reading (``cp_entity_type == "ccp"``), NOT a QCCP-only cut.
      Our fixture carries only a QCCP, so the two readings are numerically
      identical today; the literal one is chosen and recorded here. (Contrast
      c07.py's ``c07_qccp``, whose rows are explicitly "of which: cleared
      through a QCCP" and so DO consult ``cp_is_qccp``.)
    - 9: the explicit residual — is-CCR and neither of the above. Today that is
      exactly the FCCM SFTs faced to a NON-CCP counterparty. It is NOT "the SFTs
      and the default-fund contributions": an SFT faced to a CCP is in Section
      9's scope (Art. 301(1)(b)) and so lands in UK8a, as does a default-fund
      contribution (Art. 307-309, also inside Section 9) — both by the plain
      ``cp_entity_type == "ccp"`` cut above, with no special-casing.
    """
    is_ccr = (
        pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
        if "risk_type" in cols
        else pl.lit(value=False)
    )
    is_derivative = (
        (pl.col("risk_type").fill_null("") == "CCR_DERIVATIVE")
        if "risk_type" in cols
        else pl.lit(value=False)
    )
    faces_ccp = (
        (pl.col("cp_entity_type").fill_null("") == "ccp")
        if "cp_entity_type" in cols
        else pl.lit(value=False)
    )
    is_sa_ccr = is_derivative & ~faces_ccp
    is_ccp = is_ccr & faces_ccp
    return results.with_columns(
        is_ccr.alias(_IS_CCR),
        is_sa_ccr.alias(_IS_SA_CCR),
        is_ccp.alias(_IS_CCP),
        (is_ccr & ~is_sa_ccr & ~is_ccp).alias(_IS_OTHER_CCR),
    )
