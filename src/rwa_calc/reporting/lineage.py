"""
Report-cell lineage — which exposures and rules produced this reported figure.

Pipeline position:
    sealed aggregator-exit ledger -> <template>_plans() -> TemplateSpec + frame
        -> lineage (this module) -> {api/rest, ui/views}

Key responsibilities:
- Describe a cell: read its ``CellSpec`` off the template's own ``TemplateSpec``
  and report what it MEANS — the metric, the filter criteria, the scope of the
  population, the sign convention, and which of the six cell kinds it is.
- Drill into a cell: return the ledger legs that fed it, by running that same
  ``RowPredicate`` over the same prepared frame the generator executed.

**Lineage is a query, never a stored index.** A cell's lineage IS its spec:
``spec.predicate`` conjoined with ``spec.cells[(row, col)].predicate``. So this
module reads the specs the generators execute rather than declaring its own —
a second copy of a template's row selection could silently disagree with the
figure actually reported, which is the one thing a lineage feature may never do.
Materialising cell -> row-id memberships would also multiply the ledger by the
cell count per template, for no gain.

Two honesty rules follow from the module post-passes (``_null_empty_rows``,
``_negate_deduction_cols``), which run AFTER ``execute()``:
1. ``cell_value`` is read from the GENERATED template — the number the user
   clicked is ground truth and is never recomputed here.
2. ``contribution_total`` is the sum over the returned rows, and
   ``CellQuery.sign`` records the Annex II §1.3 negation, so the two can be
   reconciled explicitly instead of appearing to disagree.

Coverage: templates whose execution plan is exposed (``LINEAGE_PLANS``). A
template that is not instrumented resolves to ``None`` — a clean "no lineage",
never a re-derived guess.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP); CRR Part 8 (Pillar 3)
- docs/plans/report-cell-lineage.md §4 (Phase B)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import polars as pl

from rwa_calc.reporting.cellspec import (
    Count,
    FirstNonNull,
    Formula,
    Mean,
    PriorPeriod,
    Ratio,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    WeightedAvg,
)
from rwa_calc.reporting.corep.c07 import c07_plans, generate_c07
from rwa_calc.reporting.corep.c08 import (
    c08_04_frames,
    c08_04_plans,
    c08_07_frames,
    c08_07_plans,
)
from rwa_calc.reporting.corep.of02 import of_02_01_frames, of_02_01_plans
from rwa_calc.reporting.kernel import available_columns
from rwa_calc.reporting.pillar3.cms1 import cms1_plans, generate_cms1
from rwa_calc.reporting.pillar3.cms2 import cms2_plans, generate_cms2
from rwa_calc.reporting.pillar3.cr4 import cr4_plans, generate_cr4
from rwa_calc.reporting.pillar3.cr5 import cr5_plans, generate_cr5
from rwa_calc.reporting.pillar3.cr6a import cr6a_plans, generate_cr6a
from rwa_calc.reporting.pillar3.cr7 import cr7_plans, generate_cr7
from rwa_calc.reporting.pillar3.cr7a import cr7a_plans, generate_cr7a
from rwa_calc.reporting.pillar3.cr8 import cr8_frames, cr8_plans
from rwa_calc.reporting.pillar3.ov1 import ov1_frames, ov1_plans

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rwa_calc.reporting.cellspec import CellSpec, TemplateSpec, ValueBinding
    from rwa_calc.reporting.metadata import ResultsSource
    from rwa_calc.reporting.plans import SheetPlan

logger = logging.getLogger(__name__)

# The sealed edge every lineage query runs on.
BASIS = "aggregator_exit"

# What a contributing leg is shown with: identity, the two-leg guarantee ledger
# (a guaranteed exposure is physically split, so a "row" is a LEG), and the
# figures a reviewer checks the cell against. Projected where present.
_ROW_COLUMNS: tuple[str, ...] = (
    "exposure_reference",
    "source_exposure_reference",
    "reporting_leg_role",
    "reporting_class",
    "reporting_class_origin",
    "reporting_method",
    "reporting_ead",
    "risk_weight",
    "rwa_final",
    "guarantee_rwa_benefit",
)

type CellKind = Literal["rows", "formula", "side_context", "prior_period", "constant", "unbound"]


@dataclass(frozen=True)
class FilterTerm:
    """One row-selection criterion, in the terms a reviewer can check.

    ``source`` says whether the column is a sealed ledger fact (``ledger``) or a
    discriminator the template derives for its own row structure (``derived`` —
    e.g. C 07.00's risk-weight band or CCF bucket).
    """

    column: str
    op: Literal["eq", "in", "between", "any_of"]
    value: object
    source: Literal["ledger", "derived"]


@dataclass(frozen=True)
class CellQuery:
    """What a cell MEANS — read off the template spec; independent of any run."""

    template_id: str
    sheet: str | None
    row_ref: str
    col_ref: str
    row_name: str
    kind: CellKind
    metric: str | None
    metric_columns: tuple[str, ...]
    filter_terms: tuple[FilterTerm, ...]
    scope: tuple[str, ...]
    refs: tuple[str, ...] = ()
    basis: str = BASIS
    sign: Literal["positive", "negated"] = "positive"
    # Metric columns the ledger does not carry. When this is the WHOLE of
    # ``metric_columns``, the cell sums a source the engine never produces — so
    # its reported 0.0 is a structural artefact of the COREP zero policy, not a
    # measured zero (the Phase 7 F6 permanently-null cells). Saying so is the
    # difference between "we computed zero" and "we cannot compute this".
    missing_columns: tuple[str, ...] = ()
    # Whether this cell's value derives from the PRIOR period (a PriorPeriod
    # binding, or a Formula whose refs resolve to one — CR8 row 1 opening and
    # row 8 residual). Statically knowable from the spec. The drill-down runs on
    # the CURRENT-period ledger only, so it cannot reproduce the reported figure
    # for such a cell (its cell_value would be a null that contradicts the screen
    # once a comparative period is supplied); the resolver declines it instead
    # (see ``SheetLineage.cell``) and the surfaces give a distinct refusal.
    derives_from_prior_period: bool = False
    # Whether this cell reads an out-of-frame ``SideContext`` value the plan's
    # OWN ``ReportingContext`` does not carry (``side_value(key) is None``). The
    # lineage plan is the current-period / no-side-input view: OV1's
    # ``ov1_plans`` threads NO output-floor summary, so row 27's OF-ADJ (a
    # ``SideContext("of_adj")``) reads null HERE while the reported template —
    # generated WITH the run's summary (api/rest.py get_template_bundles) — shows
    # a real figure. So the resolver declines such a cell exactly as it declines
    # a prior-period one, keeping honesty rule 1 (a drill-down never contradicts
    # the screen). CONDITIONAL, never kind-blanket: a SideContext the plan DOES
    # thread (C 07.00's per-sheet substitution inflow, threaded by ``c07_plans``)
    # has a non-None value and stays drillable, tying out to its real figure.
    reads_unavailable_side_value: bool = False

    @property
    def is_source_backed(self) -> bool:
        """Whether any metric column this cell sums actually reaches the ledger."""
        return self.kind != "rows" or bool(set(self.metric_columns) - set(self.missing_columns))


@dataclass(frozen=True)
class CellLineage:
    """The lineage of one cell for one run."""

    query: CellQuery
    run_id: str
    cell_value: float | None
    contribution_total: float | None
    total_rows: int
    rows: pl.DataFrame


@dataclass(frozen=True)
class _Provider:
    """How one template exposes its execution plans, and what its scope is.

    ``single_frame`` marks a template with no sheet axis (cr4, cr7, cr8, ov1,
    cms1/2, c08_07, of_02_01, …): its ``plans()`` / ``generate()`` return a
    one-entry dict under a canonical key, and its lineage always reports
    ``sheet = None`` (see ``_resolve_sheet_key``). Multi-sheet templates (C
    07.00 by obligor class, C 08.0x by class, C 09.0x by country) resolve a
    sheet by name.
    """

    plans: Callable[[pl.LazyFrame, set[str], str, list[str]], dict[str, SheetPlan]]
    generate: Callable[[pl.LazyFrame, set[str], str, list[str]], dict[str, pl.DataFrame]]
    scope: tuple[str, ...]
    sheet_label: str
    single_frame: bool = False


# Instrumented templates. Adding one = expose its `<t>_plans()` (the same
# plan/generate extraction c07 made, returning `dict[str, SheetPlan]`) and
# register a `_Provider` here — set `single_frame=True` for a template with no
# sheet axis. Templates absent from this map have no lineage — including C 34.x
# / CCR1-8, which are still imperative and have no TemplateSpec to read.
LINEAGE_PLANS: dict[str, _Provider] = {
    "c07_00": _Provider(
        plans=c07_plans,
        generate=generate_c07,
        scope=(
            "Standardised-approach legs, plus BOTH counterparty-credit-risk "
            "populations — FCCM SFT rows and SA-CCR derivative netting sets. The CCR "
            "rows are admitted by risk type (not by the approach label, which the "
            "output floor relabels), and Annex II breaks them out in rows 0090-0130",
            "Specialised lending is merged into corporate (Art. 112(1)(g): under the "
            "standardised approach SL is a corporate sub-type)",
        ),
        sheet_label="obligor class",
    ),
    # CR4 — SA exposure and CRM effects (single frame; R20). generate_cr4 is the
    # dict-returning generator; the dispatch router unwraps the one frame.
    "cr4": _Provider(
        plans=cr4_plans,
        generate=generate_cr4,
        scope=(
            "Standardised-approach legs by ORIGIN approach "
            "(reporting_approach_origin == standardised), narrowed to SA CREDIT risk "
            "only: the counterparty-credit-risk netting sets, CCP default-fund "
            "contributions and settlement failed-trade synthetic legs are dropped (they "
            "disclose on CCR1-CCR8) — over ALL columns, so a row's RWEA never covers "
            "exposure the on/off-balance-sheet columns omit",
            "The facility_undrawn commitment leg (which the sealed "
            "reporting_on_balance_sheet leaves null) is reclassified to off-balance-sheet "
            "so it lands on exactly one side (CRR Art. 111 off-balance-sheet CCF item)",
            "Pre-CRM columns a/b key the obligor's origination Art. 112 class "
            "(reporting_class_origin); post-CRM columns c-f key the post-substitution "
            "class (reporting_class) — the recorded F3 two-basis split",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CR6-A — scope of IRB and SA use (single frame; R20).
    "cr6a": _Provider(
        plans=cr6a_plans,
        generate=generate_cr6a,
        scope=(
            "The full sealed per-leg ledger — CR6-A rows key on the raw ORIGINATION "
            "class (exposure_class), deliberately NOT the applied Art. 112 basis, so an "
            "SA-treated defaulted obligor still counts under its origination-class row "
            "(Art. 452(b) discloses the extent of IRB use across the obligor population)",
            "Column a narrows to the IRB-family origin approaches (foundation_irb / "
            "advanced_irb / slotting); column b spans all approaches — the two subsets "
            "partition the row",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CR7 — effect of credit derivatives on RWEA (single frame; R20).
    "cr7": _Provider(
        plans=cr7_plans,
        generate=generate_cr7,
        scope=(
            "The full sealed per-leg ledger — CR7 has no population pre-filter; each row "
            "selects by ORIGIN approach x the obligor's applied Art. 147 class "
            "(reporting_approach_origin x reporting_class_origin), and Annex XXII keeps "
            "the credit-derivative substitution as an a->b column effect, never a row move",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CR8 — RWEA flow statement for IRB (single frame; R20). cr8_frames is the
    # lineage-facing generator: the CURRENT-period view (no prior frame), so the
    # opening (row 1, prior_period) and residual (row 8, formula) rows are null —
    # neither is row-backed. generate_cr8 (the prior-aware dispatch entry) keeps
    # its distinct signature and is NOT the provider generator.
    "cr8": _Provider(
        plans=cr8_plans,
        generate=cr8_frames,
        scope=(
            "Internal-ratings-based credit-risk legs on the F-IRB and A-IRB approaches; "
            "slotting (supervisory-slotting specialised lending) is excluded — it "
            "discloses on CR10 (approach_applied in {foundation_irb, advanced_irb})",
            "Row 9 (closing RWEA) sums the current period; the opening (row 1) and "
            "residual (row 8) rows need a prior-period frame the drill-down does not "
            "carry, so they are out of the current-period view",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # OV1 — overview of RWEAs (single frame; R21). ov1_frames is the
    # lineage-facing generator (no output-floor summary): row 27's OF-ADJ
    # SideContext reads null, matching the drill-down's no-side view.
    "ov1": _Provider(
        plans=ov1_plans,
        generate=ov1_frames,
        scope=(
            "The full sealed per-leg ledger — OV1 has no population pre-filter (row 29 "
            "Total sums the whole book). Rows 1-5 (credit risk EXCLUDING counterparty "
            "credit risk) and their per-approach 'of which' rows are cut by the derived "
            "ov1_is_ccr flag (risk_type in the CCR set), NEVER by the approach label the "
            "output floor relabels; the CCR block (rows 6/7/UK8a/9) selects the derived "
            "CCR partition flags by risk type and whether the leg faces a CCP",
            "Row 24 (Art. 48(4) below-threshold 250%-RW memo) is a RECORDED "
            "APPROXIMATION: the sealed ledger carries no positive Art. 48(4) flag, so it "
            "sums the SA 'Other items' origin class (reporting_class_origin == other) at "
            "a 250% risk weight — over-including any non-threshold other-item at 250% and "
            "under-including a threshold item held as equity",
            "Row 26 (output-floor multiplier) reads the sealed output_floor_pct; row 27 "
            "(OF-ADJ) is an out-of-frame SideContext from the output-floor summary the "
            "drill-down does not carry, so the resolver REFUSES it (a distinct 404) "
            "rather than serving a null against a report generated WITH the summary",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CR5 — SA risk-weight allocation (single frame; R21).
    "cr5": _Provider(
        plans=cr5_plans,
        generate=generate_cr5,
        scope=(
            "Standardised-approach legs by ORIGIN approach "
            "(reporting_approach_origin == standardised), narrowed to SA CREDIT risk "
            "only: the counterparty-credit-risk netting sets, CCP default-fund "
            "contributions and settlement failed-trade synthetic legs are dropped (they "
            "disclose on CCR1-CCR8), and the facility_undrawn commitment leg is "
            "reclassified off-balance-sheet — so every band, total and on/off-BS column "
            "reports over one population",
            "Class rows key uniformly on the post-substitution reporting_class (CR5 "
            "carries only post-CF/post-CRM figures; the covered leg of a guaranteed "
            "exposure bands in the protection provider's row); the risk-weight band "
            "columns allocate reporting_ead on the derived cr5_rw_bucket, which for an "
            "Art. 123B currency-mismatch leg is the PRE-multiplier risk weight "
            "(PS1/26 Annex XX reporting override)",
            "The 'of which: unrated' column keys the derived cr5_unrated flag "
            "(external_cqs is null — the leg carries no own nominated-ECAI assessment), "
            "an input-availability fact applied uniformly across every class row. "
            "RECORDED LIMITATION: a guarantee-substituted leg keeps the OBLIGOR's "
            "external_cqs while banding in the guarantor's row, so a rated-guarantor leg "
            "from an unrated obligor counts as unrated there",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CMS1 — modelled vs standardised RWEA by risk type (single frame; R21).
    # Basel 3.1 only: cms1_plans yields {} under CRR, so lineage returns a clean
    # no-lineage rather than crashing.
    "cms1": _Provider(
        plans=cms1_plans,
        generate=generate_cms1,
        scope=(
            "The full sealed per-leg ledger (Basel 3.1 only — CMS1 is not produced under "
            "CRR). Rows 0010 (credit risk excl. CCR) and 0020 (CCR) partition the book "
            "by the derived cms1_is_ccr flag (risk_type in the CCR set), never by the "
            "approach label; 0080 Total is the whole book",
            "Column a sums the MODELLED approaches (derived cms1_is_modelled: "
            "foundation_irb / advanced_irb / slotting); column b is their COMPLEMENT "
            "(every non-modelled leg, including equity and the standardised_ccr relabel), "
            "so a + b = column c is the row's whole actual RWA; column d recomputes "
            "sa_rwa over the row's whole population",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CMS2 — modelled vs standardised RWEA by asset class (single frame; R21).
    # Basel 3.1 only: cms2_plans yields {} under CRR.
    "cms2": _Provider(
        plans=cms2_plans,
        generate=generate_cms2,
        scope=(
            "The full sealed per-leg ledger (Basel 3.1 only — CMS2 is not produced under "
            "CRR). Rows key the raw ORIGINATION class (exposure_class) via tolerant "
            "per-value limbs — the Art. 147-shaped axis with no defaulted sink, so "
            "substitution moves no row (column b recomputes the SA-equivalent of the "
            "SAME population reported in column a)",
            "Column a sums the actual rwa_final of the MODELLED origin approaches "
            "(foundation_irb / advanced_irb / slotting) within the row's classes; column "
            "c is the row's TOTAL actual RWA across ALL approaches; column d recomputes "
            "sa_rwa over the row's SA-mapped classes. Sub-rows 0041 (of-which F-IRB) / "
            "0042 (of-which A-IRB) narrow the corporate classes by origin approach",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # C 08.04 — IRB RWEA flow (per exposure class; R22). The CR8-clone flow:
    # c08_04_frames is the lineage-facing generator (the CURRENT-period view, no
    # prior frame), so the opening (row 0010, prior_period) and residual (row
    # 0080, formula) rows are refused — as CR8's rows 1/8 are. generate_c08_04
    # (the prior-aware dispatch entry) keeps threading the prior frame and is NOT
    # the provider generator. First multi-sheet instrumentation since C 07.00.
    "c08_04": _Provider(
        plans=c08_04_plans,
        generate=c08_04_frames,
        scope=(
            "Internal-ratings-based credit-risk legs on the F-IRB and A-IRB "
            "approaches; slotting (supervisory-slotting specialised lending) is "
            "excluded — it discloses on C 08.06 (reporting_approach_origin in "
            "{foundation_irb, advanced_irb})",
            "Row 0090 (closing RWEA) sums the current period's rwa_final; the "
            "opening (row 0010) and residual (row 0080) rows need a prior-period "
            "frame the drill-down does not carry, so they are out of the "
            "current-period view",
        ),
        sheet_label="exposure class",
    ),
    # C 08.07 — IRB scope of use (single frame, full population; R22). Its two
    # post-execute passes (col-0040 rescale, fixed-null structural rows) live on
    # the reported frame (c08_07_frames), which the drill-down reads a cell's
    # value from; the plan is the pre-post-pass full-population view.
    "c08_07": _Provider(
        plans=c08_07_plans,
        generate=c08_07_frames,
        scope=(
            "The FULL results population — SA and IRB both enter every "
            "denominator (a null approach falls to SA; slotting counts as IRB via "
            "approach membership in C08_07_IRB_APPROACHES), keyed on the RAW "
            "origination class (exposure_class — the Art. 147 taxonomy has no "
            "defaulted sink)",
            "Col 0010 sums the IRB EAD (derived c0807_irb), col 0020 the row "
            "total EAD; the coverage percentages 0030/0050 are intra-row formulas "
            "guarding a zero denominator to 0.0. Col 0040 (% subject to an Art. "
            "148 roll-out plan) sums the SA-treated legs flagged by the optional "
            "is_under_irb_rollout input (derived c0807_rollout) and is rescaled to "
            "a percentage of the row total post-execute; absent the input the "
            "slice is empty (0.0). RECORDED LIMITATION: on a book that DID carry "
            "roll-out legs, col 0040's drill-down legs would sum to the raw EAD, "
            "not the reported percentage — no fixture carries the input today",
            "The structural-null rows are a FIXED set (CRR 0060/0100/0130) — rows "
            "with neither a class binding nor an aggregate rule render all-null "
            "(an unbound cell), while empty real-class rows stay 0.0 (the opposite "
            "of C 07.00's empty-subset rule); the B31 materiality columns "
            "0160-0180 are always null",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # OF 02.01 — output-floor comparison (single frame; R22). Basel 3.1 only:
    # of_02_01_plans yields {} under CRR (like CMS1/CMS2), so a CRR lineage
    # request degrades to a clean no-lineage. Its _null_fixed_rows post-pass
    # lives on the reported frame (of_02_01_frames); generate_of_02_01 keeps its
    # OutputFloorConfig-gated signature and is NOT the provider generator.
    "of_02_01": _Provider(
        plans=of_02_01_plans,
        generate=of_02_01_frames,
        scope=(
            "The full sealed per-leg ledger (Basel 3.1 only — OF 02.01 is not "
            "produced under CRR). Rows 0010 (credit risk excl. CCR) and 0020 "
            "(CCR) partition the book by the derived of02_is_ccr flag (risk_type "
            "in the CCR set), never by the approach label the output floor "
            "relabels; row 0080 (Total) is the whole book and hence their sum",
            "The columns PARTITION each row's population (Annex II): col 0010 sums "
            "rwa_pre_floor over the MODELLED approaches (derived of02_is_modelled: "
            "foundation_irb / advanced_irb / slotting), col 0020 is their "
            "COMPLEMENT (every non-modelled leg), so col 0030 = 0010 + 0020 is the "
            "complete portfolio; col 0040 (S-TREA) sums sa_rwa over the row's "
            "whole population, modelled or not (equity's sa_rwa carries its own "
            "pre-floor RWA)",
            "Rows 0030-0070 (CVA / securitisation / market / op-risk / other) are "
            "a FIXED all-null set — out of scope for a credit-risk calculator, and "
            "null is not the same claim as 0.0. The OutputFloorConfig entity gate "
            "stays with the reported generator; the drill-down plan is the "
            "no-config view",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CR7-A — extent of IRB CRM techniques (per origin approach; R22). No prep and
    # no post-execute pass beyond the in-spec Formula (column c), so generate_cr7a
    # is the provider generator directly. Multi-sheet (sheet = origin approach).
    "cr7a": _Provider(
        plans=cr7a_plans,
        generate=generate_cr7a,
        scope=(
            "The full sealed per-leg ledger; each sheet is one ORIGIN approach "
            "(reporting_approach_origin foundation_irb / advanced_irb — an "
            "approach with no rows produces no sheet), and rows key the obligor's "
            "applied Art. 147 class (reporting_class_origin), disclosing exposures "
            "under the obligor class WITHOUT substitution effects (Annex XXII "
            "column a)",
            "Column a sums reporting_ead; the FCP/UFCP percentage columns (b "
            "financial, d immovable property, e receivables, f other physical, k "
            "guarantees) divide each collateral-allocation sum by the row EAD "
            "x100, and c = d + e + f. Columns m ('without substitution effects') "
            "and n ('with substitution effects') are BOTH the actual Sum of "
            "rwa_final — the recorded m == n approximation (the ledger carries no "
            "hypothetical no-substitution RWEA)",
            "Columns g/h/i/j (other-funded-CP sub-splits), l (credit derivatives) "
            "and the B31 slotting pair o/p stay unbound — the recorded "
            "not-separately-tracked cells",
        ),
        sheet_label="approach",
    ),
}


def is_instrumented(template_id: str) -> bool:
    """Whether this template's cells can be explained.

    A template is instrumented when it exposes its execution plans, so lineage
    can read the very spec the generator executes. Consumers use this to offer a
    drill-down only where there is a truthful answer to give.
    """
    return template_id in LINEAGE_PLANS


@dataclass(frozen=True)
class SheetLineage:
    """A lineage resolver bound to one run and one template sheet.

    Holds the sheet's execution plan and its RENDERED frame, so explaining many
    cells of a sheet costs one plan build and one generation — not one per cell.
    """

    template_id: str
    sheet: str | None
    _provider: _Provider
    _plan: SheetPlan
    _rendered: pl.DataFrame | None
    _sealed: set[str]

    def has_cell(self, row_ref: str, col_ref: str) -> bool:
        """Whether the cell is on this template at all."""
        spec = self._plan.spec
        return any(row.ref == row_ref for row in spec.rows) and col_ref in spec.column_refs

    def query(self, row_ref: str, col_ref: str) -> CellQuery | None:
        """What the cell MEANS — read off the spec the generator executes."""
        if not self.has_cell(row_ref, col_ref):
            return None
        return describe_cell(
            self._provider,
            self._plan,
            self.template_id,
            self.sheet,
            row_ref,
            col_ref,
            sealed=self._sealed,
        )

    def cell(
        self, row_ref: str, col_ref: str, *, run_id: str = "", offset: int = 0, limit: int = 50
    ) -> CellLineage | None:
        """The cell's full lineage: its meaning, its reported value, its legs.

        Declines (``None``) a cell whose reported value this resolver cannot
        reproduce without contradicting the screen (honesty rule 1); the
        surfaces map each refusal to a distinct reason. Two cases:

        - a PRIOR-PERIOD-derived cell — this resolver holds only the
          CURRENT-period ledger, so its ``cell_value`` is always null, which
          would contradict a comparative-period figure once one is supplied;
        - a cell that reads an out-of-frame ``SideContext`` value the plan does
          not carry (``reads_unavailable_side_value`` — OV1's row-27 OF-ADJ on
          the no-summary lineage plan): the reported template is generated WITH
          the run's output-floor summary, so a 200 here would show a null
          against a real figure on the screen.
        """
        query = self.query(row_ref, col_ref)
        if query is None or query.derives_from_prior_period or query.reads_unavailable_side_value:
            return None
        plan = self._plan
        matched = _matching_rows(plan, plan.spec.cells.get((row_ref, col_ref)), query)
        return CellLineage(
            query=query,
            run_id=run_id,
            cell_value=_rendered_value(self._rendered, row_ref, col_ref),
            contribution_total=_contribution(matched, query.metric, query.metric_columns),
            total_rows=matched.height,
            rows=_project(matched, query.metric_columns, offset=offset, limit=limit),
        )


def sheet_lineage(
    source: ResultsSource, template_id: str, sheet: str | None = None
) -> SheetLineage | None:
    """Bind a lineage resolver to one template sheet of one run.

    ``sheet`` defaults to the template's first sheet (and is always ``None`` for
    a single-frame template). Returns ``None`` when the template is not
    instrumented, produced nothing for this run, or has no such sheet — never a
    fallback computation.
    """
    provider = LINEAGE_PLANS.get(template_id)
    if provider is None:
        return None

    results = source.scan_results()
    cols = available_columns(results)
    errors: list[str] = []
    plans = provider.plans(results, cols, source.framework, errors)
    if not plans:
        return None

    resolved = _resolve_sheet_key(plans, sheet, single_frame=provider.single_frame)
    if resolved is None:
        return None
    key, reported_sheet = resolved

    # The REPORTED frame — the figures the user actually saw. Generated once and
    # reused for every cell of this sheet; a cell's value is read from it, never
    # recomputed (the two post-execute passes live here).
    generated = provider.generate(results, cols, source.framework, errors)
    if set(generated) != set(plans):
        # plans() and generate() MUST key identically — a cell's spec (from
        # plans) and its reported value (from generate) are looked up by the
        # same key. A mismatch injects a null value silently; log it so the
        # drift degrades loudly instead.
        logger.warning(
            "lineage %s: plan/generate sheet keys disagree (plans=%s, generated=%s)",
            template_id,
            sorted(plans),
            sorted(generated),
        )
    return SheetLineage(
        template_id=template_id,
        sheet=reported_sheet,
        _provider=provider,
        _plan=plans[key],
        _rendered=generated.get(key),
        _sealed=cols,
    )


def drilldown(
    source: ResultsSource,
    template_id: str,
    row_ref: str,
    col_ref: str,
    *,
    run_id: str = "",
    sheet: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> CellLineage | None:
    """Explain one reported cell: what it means, and which legs produced it.

    Convenience over ``sheet_lineage`` for a single cell. Returns ``None`` when
    the template is not instrumented, the sheet is unknown, or the cell is not on
    the template — never a fallback computation.
    """
    resolver = sheet_lineage(source, template_id, sheet)
    if resolver is None:
        return None
    return resolver.cell(row_ref, col_ref, run_id=run_id, offset=offset, limit=limit)


def describe_cell(  # noqa: PLR0913 - the cell's full identity plus its two sources
    provider: _Provider,
    plan: SheetPlan,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
    *,
    sealed: set[str],
) -> CellQuery:
    """Read one cell's meaning off the template spec the generator executes."""
    cell = plan.spec.cells.get((row_ref, col_ref))
    binding = cell.binding if cell is not None else None
    kind, metric, metric_columns, refs = _binding_facts(binding)

    terms: list[FilterTerm] = []
    if kind == "rows":
        for predicate in (plan.spec.predicate, cell.predicate if cell is not None else None):
            terms.extend(_terms(predicate, sealed))

    scope = provider.scope
    if sheet is not None:
        scope = (*scope, f"Sheet: {provider.sheet_label} = {sheet}")

    # The executor resolves a binding against the PREPARED frame's columns, so
    # that frame — not the raw sealed set — decides whether a source is present.
    present = set(plan.frame.columns)
    missing = tuple(col for col in metric_columns if col not in present) if kind == "rows" else ()

    # A SideContext cell whose value the plan's OWN ctx does not carry (the OV1
    # row-27 OF-ADJ on the no-summary lineage plan): the drill-down would render
    # null against a reported figure. Conditional — a threaded SideContext
    # (C 07.00's substitution inflow) reads a real value and stays drillable.
    reads_unavailable_side_value = isinstance(binding, SideContext) and (
        plan.ctx.side_value(binding.key) is None
    )

    row_name = next((row.name for row in plan.spec.rows if row.ref == row_ref), "")
    return CellQuery(
        template_id=template_id,
        sheet=sheet,
        row_ref=row_ref,
        col_ref=col_ref,
        row_name=row_name,
        kind=kind,
        metric=metric,
        metric_columns=metric_columns,
        filter_terms=tuple(terms),
        scope=scope,
        refs=refs,
        sign="negated" if col_ref in plan.negative_cols else "positive",
        missing_columns=missing,
        derives_from_prior_period=_derives_from_prior_period(plan.spec, row_ref, col_ref),
        reads_unavailable_side_value=reads_unavailable_side_value,
    )


# =============================================================================
# Private helpers
# =============================================================================


def _derives_from_prior_period(spec: TemplateSpec, row_ref: str, col_ref: str) -> bool:
    """Whether this cell's value derives from the PRIOR period, statically.

    True for a ``PriorPeriod`` binding, and for a ``Formula`` whose refs resolve
    to a prior-period cell (CR8 row 8 = row 9 − row 1, where row 1 is
    ``PriorPeriod``). Knowable from the spec alone — no run needed. The drill-down
    runs on the current-period ledger only, so it cannot honour honesty rule 1
    (``cell_value`` == the reported figure) for such a cell.
    """
    cell = spec.cells.get((row_ref, col_ref))
    if cell is None:
        return False
    binding = cell.binding
    if isinstance(binding, PriorPeriod):
        return True
    if isinstance(binding, Formula):
        return any(_ref_is_prior_period(spec, row_ref, col_ref, ref) for ref in binding.refs)
    return False


def _ref_is_prior_period(spec: TemplateSpec, row_ref: str, col_ref: str, ref: str) -> bool:
    """Resolve a ``Formula`` ref (own-row column first, then own-column row — the
    executor's resolution rule) and report whether it lands on a ``PriorPeriod``
    cell. The executor bars a formula referencing another formula, so one level
    of resolution suffices.

    The formula's OWN cell ``(row_ref, col_ref)`` is skipped: the executor
    resolves refs against the cells computed so far, which never include the
    formula's own (not-yet-computed) cell, so an own-row-column key that equals
    the formula's own address falls through to the own-column row. This only
    bites where a template's row and column ref namespaces collide — C 08.04's
    residual ``(0080, 0010)`` references row ``0010`` while its single column is
    also ``0010``, so ``(0080, 0010)`` would otherwise resolve to the residual
    itself (a Formula, not the PriorPeriod opening it must find)."""
    for key in ((row_ref, ref), (ref, col_ref)):
        if key == (row_ref, col_ref):
            continue
        target = spec.cells.get(key)
        if target is not None:
            return isinstance(target.binding, PriorPeriod)
    return False


def _resolve_sheet_key(
    plans: dict[str, SheetPlan], sheet: str | None, *, single_frame: bool
) -> tuple[str, str | None] | None:
    """Resolve a lineage request to ``(plan key, reported sheet)``.

    A single-frame template keys its one plan under a canonical key and always
    reports ``sheet = None`` — its cells carry no sheet axis, so a supplied
    ``sheet`` is ignored. A multi-sheet template resolves by name, defaulting to
    the first sheet so a caller can address a template without knowing its keys;
    an unknown sheet is unresolvable (a clean no-lineage, never a wrong sheet).

    ``plans`` is always non-empty here (the caller returns early otherwise).
    """
    if single_frame:
        return next(iter(plans)), None
    if sheet is None:
        first = next(iter(plans))
        return first, first
    if sheet not in plans:
        return None
    return sheet, sheet


def _binding_facts(
    binding: ValueBinding | None,
) -> tuple[CellKind, str | None, tuple[str, ...], tuple[str, ...]]:
    """(kind, metric, metric columns, formula refs) for one value binding.

    The six kinds fall straight out of the binding vocabulary — which is what
    lets the drill-down answer honestly for EVERY cell, not just the summable
    ones. A ``Formula`` with no refs is a constant (the recorded structural-null
    and fixed-zero cells: sources the engine never produces), so it is reported
    as ``constant`` rather than as a derivation of nothing.
    """
    if binding is None:
        return "unbound", None, (), ()
    if isinstance(binding, Formula):
        return ("formula" if binding.refs else "constant", None, (), binding.refs)
    if isinstance(binding, SideContext):
        return "side_context", "side_context", (binding.key,), ()
    if isinstance(binding, PriorPeriod):
        _kind, metric, columns, _refs = _binding_facts(binding.binding)
        return "prior_period", metric, columns, ()
    if isinstance(binding, Sum):
        return "rows", "sum", (binding.col,), ()
    if isinstance(binding, SafeSum):
        return "rows", "sum", binding.cols, ()
    if isinstance(binding, Mean):
        return "rows", "mean", (binding.col,), ()
    if isinstance(binding, WeightedAvg):
        return "rows", "weighted_avg", (binding.col, binding.weight), ()
    if isinstance(binding, Ratio):
        return "rows", "ratio", (binding.numerator, binding.denominator), ()
    if isinstance(binding, Count):
        return "rows", "count", (binding.col,) if binding.distinct else (), ()
    if isinstance(binding, FirstNonNull):
        return "rows", "first_non_null", (binding.col,), ()
    raise TypeError(f"unknown value binding: {type(binding).__name__}")


def _terms(predicate: RowPredicate | None, sealed: set[str]) -> list[FilterTerm]:
    """Flatten a row predicate into reviewable criteria."""
    if predicate is None:
        return []

    def term(
        column: str, op: Literal["eq", "in", "between", "any_of"], value: object
    ) -> FilterTerm:
        return FilterTerm(
            column=column,
            op=op,
            value=value,
            source="ledger" if column in sealed else "derived",
        )

    terms: list[FilterTerm] = []
    if predicate.classes:
        terms.append(term("reporting_class", "in", predicate.classes))
    if predicate.classes_origin:
        terms.append(term("reporting_class_origin", "in", predicate.classes_origin))
    if predicate.method is not None:
        terms.append(term("reporting_method", "eq", predicate.method))
    if predicate.approaches_origin:
        terms.append(term("reporting_approach_origin", "in", predicate.approaches_origin))
    if predicate.leg_role is not None:
        terms.append(term("reporting_leg_role", "eq", predicate.leg_role))
    if predicate.on_balance_sheet is not None:
        terms.append(term("reporting_on_balance_sheet", "eq", predicate.on_balance_sheet))
    if predicate.is_defaulted is not None:
        terms.append(term("is_defaulted", "eq", predicate.is_defaulted))
    if predicate.subclass is not None:
        terms.append(term("reporting_subclass", "eq", predicate.subclass))
    if predicate.rw_between is not None:
        terms.append(term("reporting_rw", "between", predicate.rw_between))
    terms.extend(term(column, "eq", value) for column, value in predicate.equals)
    terms.extend(term(column, "between", (low, high)) for column, low, high in predicate.between)
    if predicate.any_of:
        terms.append(
            term(
                "any_of",
                "any_of",
                tuple(tuple(_terms(limb, sealed)) for limb in predicate.any_of),
            )
        )
    return terms


def _matching_rows(plan: SheetPlan, cell: CellSpec | None, query: CellQuery) -> pl.DataFrame:
    """The legs the cell aggregates — the SAME predicate the generator ran.

    A cell that is not row-backed (formula / side context / constant / unbound)
    has no contributing legs; it returns an empty frame rather than a plausible
    but wrong row set.
    """
    if query.kind != "rows" or cell is None:
        return plan.frame.clear()
    frame = plan.frame
    for predicate in (plan.spec.predicate, cell.predicate):
        if predicate is not None:
            frame = predicate.apply(frame)
    return frame


def _contribution(
    rows: pl.DataFrame, metric: str | None, metric_cols: Sequence[str]
) -> float | None:
    """The rows' contribution, where the metric is a sum.

    Sums every PRESENT metric column (a ``SafeSum`` cell adds several — C 07.00
    col 0030 sums the SCRA and GCRA provisions), matching the executor's
    semantics. Only summed metrics reconcile row-by-row to the cell; an average
    or a ratio does not, and is left None rather than reported as a misleading
    total. None when no metric column reaches the ledger (a permanently-null
    cell), which is not the same as a total of zero.
    """
    if metric != "sum":
        return None
    present = [col for col in metric_cols if col in rows.columns]
    if not present:
        return None
    total = sum(float(rows[col].fill_null(0.0).sum() or 0.0) for col in present)
    return float(total)


def _project(
    rows: pl.DataFrame, metric_cols: Sequence[str], *, offset: int, limit: int
) -> pl.DataFrame:
    """The explanatory projection, biggest contributor first."""
    present = [col for col in metric_cols if col in rows.columns]
    wanted = dict.fromkeys(
        [col for col in _ROW_COLUMNS if col in rows.columns] + present,
    )
    projected = rows.select(list(wanted))
    if present:
        projected = projected.sort(present[0], descending=True, nulls_last=True)
    return projected.slice(max(0, offset), max(1, limit))


def _rendered_value(frame: pl.DataFrame | None, row_ref: str, col_ref: str) -> float | None:
    """The cell AS REPORTED — read from the generated template, never recomputed."""
    if frame is None or col_ref not in frame.columns:
        return None
    match = frame.filter(pl.col("row_ref") == row_ref)
    if match.height == 0:
        return None
    value = match[col_ref][0]
    return float(value) if value is not None else None
