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
    c08_01_plans,
    c08_02_plans,
    c08_03_plans,
    c08_04_frames,
    c08_04_plans,
    c08_05_plans,
    c08_06_plans,
    c08_07_frames,
    c08_07_plans,
    generate_c08_01,
    generate_c08_02,
    generate_c08_03,
    generate_c08_05,
    generate_c08_06,
)
from rwa_calc.reporting.corep.c09 import (
    c09_01_plans,
    c09_02_plans,
    generate_c09_01,
    generate_c09_02,
)
from rwa_calc.reporting.corep.c34 import (
    c34_01_frames,
    c34_01_plans,
    c34_02_frames,
    c34_02_plans,
    c34_04_frames,
    c34_04_plans,
    c34_08_frames,
    c34_08_plans,
)
from rwa_calc.reporting.corep.of02 import of_02_01_frames, of_02_01_plans
from rwa_calc.reporting.kernel import available_columns
from rwa_calc.reporting.pillar3.ccr import (
    ccr1_frames,
    ccr1_plans,
    ccr2_frames,
    ccr2_plans,
    ccr3_frames,
    ccr3_plans,
    ccr8_frames,
    ccr8_plans,
)
from rwa_calc.reporting.pillar3.cms1 import cms1_plans, generate_cms1
from rwa_calc.reporting.pillar3.cms2 import cms2_plans, generate_cms2
from rwa_calc.reporting.pillar3.cr4 import cr4_plans, generate_cr4
from rwa_calc.reporting.pillar3.cr5 import cr5_plans, generate_cr5
from rwa_calc.reporting.pillar3.cr6 import cr6_plans, generate_cr6
from rwa_calc.reporting.pillar3.cr6a import cr6a_plans, generate_cr6a
from rwa_calc.reporting.pillar3.cr7 import cr7_plans, generate_cr7
from rwa_calc.reporting.pillar3.cr7a import cr7a_plans, generate_cr7a
from rwa_calc.reporting.pillar3.cr8 import cr8_frames, cr8_plans
from rwa_calc.reporting.pillar3.cr9 import (
    cr9_1_plans,
    cr9_plans,
    generate_cr9,
    generate_cr9_1,
)
from rwa_calc.reporting.pillar3.cr10 import cr10_plans, generate_cr10
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
# sheet axis. The ONLY template absent from this map is C 02.00 (a kernel-plus-
# thin-shell hybrid with no TemplateSpec to read); the whole COREP C 34 family
# (R27a/R27b) and the Pillar 3 CCR1/2/3/8 family (R27c) are now instrumented.
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
    # C 34.01 — SA-CCR analysis by approach (single frame; R27a). c34_01_frames is
    # the lineage-facing generator (the emission gate keyed under the single-frame
    # canonical key); the plan frame IS the pre-filtered SA-CCR netting-set
    # population (the CR8 pattern), so both cells sum the whole frame.
    "c34_01": _Provider(
        plans=c34_01_plans,
        generate=c34_01_frames,
        scope=(
            "The SA-CCR netting-set population — the synthetic ``ccr__``-prefixed "
            "rows, with FCCM SFTs EXCLUDED (they report on C 07.00 row 0090, not the "
            "SA-CCR templates; PS1/26 App. 17). Admitted by exposure reference (not "
            "the approach label the output floor relabels), and the plan frame IS "
            "that pre-filtered population, so both cells sum the whole frame",
            "The single SA-CCR row sums ead_final (col 0010) and rwa_final (col "
            "0020) over the population — CRR Art. 274(2) SA-CCR EAD = "
            "alpha * (RC + PFE), and the RWEA the netting sets carry. None when the "
            "portfolio has no such rows (a clean no-lineage, the reported None)",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # C 34.02 — SA-CCR EAD per netting set (per netting set; R27b). The FIRST
    # multi-sheet C 34 instrumentation: c34_02_plans keys one plan per netting
    # set (the c08_04 pattern), each plan's frame that netting set's slice of the
    # pre-filtered SA-CCR population, so the single Sum("ead_final") cell sums
    # exactly that set's legs. c34_02_frames is the lineage-facing generator,
    # IDENTICAL to the reported generate_c34_02 (no framework dependency, no prior
    # period, no post-execute pass), so a cell's value is a plain execute of its
    # plan and plans()/generate() key identically per netting set.
    "c34_02": _Provider(
        plans=c34_02_plans,
        generate=c34_02_frames,
        scope=(
            "The SA-CCR netting-set population — the synthetic ``ccr__``-prefixed "
            "rows, with FCCM SFTs EXCLUDED (they report on C 07.00 row 0090, not "
            "the SA-CCR templates; PS1/26 App. 17). Admitted by exposure reference "
            "(not the approach label the output floor relabels), partitioned into "
            "one sheet per netting set keyed on the netting_set_id stripped from "
            "the ``ccr__`` reference prefix",
            "Each sheet's single row (0010) sums ead_final (col 0010) over that "
            "netting set's legs — CRR Art. 274(2) SA-CCR EAD = alpha * (RC + PFE) "
            "per netting set (Art. 275 the netting-set boundary; Art. 278 the PFE "
            "multiplier folded into the sealed ead_final). None when the portfolio "
            "has no such rows (a clean no-lineage, the reported empty dict)",
        ),
        sheet_label="netting set",
    ),
    # C 34.04 — CVA capital (single frame, Basel 3.1 only; R27a). c34_04_plans
    # yields {} under CRR or a non-positive cva_rwa (a clean no-lineage). The cell
    # reads the portfolio BA-CVA roll-up as a broadcast constant (FirstNonNull, the
    # OV1 row-26 idiom), so it is row-backed but does NOT reconcile to a signed
    # total. No producing golden fixture — pinned by the CVA-A1 unit estate + a
    # seeded lineage unit pin, not an acceptance tie-out.
    "c34_04": _Provider(
        plans=c34_04_plans,
        generate=c34_04_frames,
        scope=(
            "The full sealed per-leg ledger (Basel 3.1 only — C 34.04 is not "
            "produced under CRR, and only when a positive cva_rwa is present). The "
            "single CVA row reads the portfolio BA-CVA roll-up (cva_rwa) as a "
            "broadcast per-row constant via FirstNonNull — the OV1 row-26 idiom; the "
            "drill-down shows the legs carrying that constant rather than a sum "
            "attributable to them",
            "cva_rwa is the BA-CVA own-funds requirement scaled to RWEA (PS1/26 "
            "App.1 Own Funds Part 4(b): RWEA_CVA = OFR_CVA * 12.5), a "
            "portfolio-level scalar and not a leg aggregate, so the cell does not "
            "reconcile to a signed total",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # C 34.08 — CCP exposures (single frame; R27a). c34_08_frames is the
    # lineage-facing generator (the R5 emission gate keyed under the single-frame
    # canonical key). The plan frame is the prepared FULL ledger (derived c34_is_ccr
    # / c34_qccp discriminators), and each cell's own predicate narrows it — rows
    # 0010/0020 to the CCP subset of the SA-CCR population, row 0030 to the
    # CCR_DEFAULT_FUND risk type (its OWN population).
    "c34_08": _Provider(
        plans=c34_08_plans,
        generate=c34_08_frames,
        scope=(
            "The SA-CCR netting-set population (the ``ccr__``-prefixed rows, FCCM "
            "SFTs excluded) RESTRICTED to CCP counterparties (cp_entity_type == ccp) "
            "for rows 0010/0020, plus the CCR_DEFAULT_FUND risk type for row 0030 — "
            "a book of purely bilateral derivatives has nothing to disclose here "
            "(the R5 emission gate and CCP restriction)",
            "Row 0010 (QCCP trade) and row 0020 (non-QCCP trade) partition the CCP "
            "subset by the derived c34_qccp flag (cp_is_qccp.fill_null(True) — a null "
            "CCP treated as qualifying, CRR Art. 306(1); a bilateral OTC "
            "counterparty is NEITHER row, disclosing on C 34.01/02 instead — the R5 "
            "fix). Row 0030 (default fund) keys the CCR_DEFAULT_FUND risk type "
            "(Art. 308/309), its OWN population, not the CCP subset",
            "Each row sums ead_final (col 0010) and rwa_final (col 0020) over its subset",
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
    # C 08.01 — IRB totals (per exposure class; R23). generate_c08_01 is the
    # provider generator directly (its four post-execute passes live on the
    # reported frame the drill-down reads). c08_01_plans threads the real per-class
    # substitution inflow, so the Total-row col 0080 (SideContext) drills to its
    # real value; the Annex II §1.3 "(-)" negation set is carried on the plan, so
    # the sign-aware reconciliation holds on the negated columns (0256 fires on the
    # corporate_sme sheet).
    "c08_01": _Provider(
        plans=c08_01_plans,
        generate=generate_c08_01,
        scope=(
            "Internal-ratings-based credit-risk legs — the F-IRB, A-IRB AND "
            "slotting approaches (reporting_approach_origin in {foundation_irb, "
            "advanced_irb, slotting}); C 08.01 reports the whole IRB book by "
            "obligor class, so unlike C 08.03/04/05 it does NOT exclude slotting",
            "Sheets key the sealed obligor origination class "
            "(reporting_class_origin — the Art. 147 taxonomy), with NO "
            "specialised-lending-into-corporate merge (unlike C 07.00) and no "
            "applied-class ladder",
            "The Total row (0010) carries the cross-sheet CRM substitution INFLOW "
            "(col 0080) — a per-destination-class scalar precomputed over the whole "
            "IRB population and threaded via ReportingContext.substitution_inflow; "
            "the sub-rows report 0.0. The deduction columns "
            "0035/0040/0050/0060/0070/0102/0103/0256/0257/0290 carry the Annex II "
            "§1.3 '(-)' sign, negated after the CRM waterfall (0090) consumes the "
            "positive magnitudes",
        ),
        sheet_label="exposure class",
    ),
    # C 08.02 — IRB by PD grade (per exposure class; R23). Data-driven rows (firm
    # grades else PD bands + Unassigned): each sheet has its OWN spec (c08_02_plans
    # builds per-sheet specs). The cross-class substitution inflow is deliberately
    # excluded (col 0080 a per-grade constant 0.0, R12); the string row label col
    # 0005 is injected post-execute and is skipped by the tie-out value-cols sweep.
    "c08_02": _Provider(
        plans=c08_02_plans,
        generate=generate_c08_02,
        scope=(
            "Internal-ratings-based credit-risk legs — the F-IRB, A-IRB AND "
            "slotting approaches (reporting_approach_origin in {foundation_irb, "
            "advanced_irb, slotting}); the whole IRB book keyed on the sealed "
            "obligor origination class (reporting_class_origin)",
            "Rows are DATA-DRIVEN: the distinct firm internal-rating grades "
            "(cp_internal_rating_grade) when present, else the populated fixed PD "
            "bands plus an 'Unassigned' residual — each row keys the derived "
            "c08_02_key label (the string label is also mirrored into col 0005 "
            "post-execute)",
            "The value surface is shared with C 08.01, but the cross-class CRM "
            "substitution INFLOW (col 0080) is DELIBERATELY excluded — a per-grade "
            "constant 0.0 (PS1/26 Annex XXII: obligor-basis reporting bars the "
            "guarantor's inflow from the origin-obligor's grade breakdown, R12). "
            "The deduction columns carry the Annex II §1.3 '(-)' sign (0256 fires "
            "on the corporate_sme sheet)",
        ),
        sheet_label="exposure class",
    ),
    # C 08.03 — IRB by PD range (per exposure class; R24). Sparse PD-range rows
    # (populated buckets + optional 9999 Unassigned) keyed on the derived
    # c08_pd_range band label. generate_c08_03 is the provider generator directly:
    # its one post-execute pass (the provisions ladder, col 0110) lives on the
    # reported frame the drill-down reads. Cols 0010/0020 Sum the sealed per-side
    # gross carriers (reporting_gross_on_bs / _off_bs) over the band with a
    # member-only predicate — row-level and null outside their side — so they need
    # no post-pass.
    "c08_03": _Provider(
        plans=c08_03_plans,
        generate=generate_c08_03,
        scope=(
            "Internal-ratings-based credit-risk legs on the F-IRB and A-IRB "
            "approaches; slotting (supervisory-slotting specialised lending) is "
            "excluded — it discloses on C 08.06 (reporting_approach_origin in "
            "{foundation_irb, advanced_irb}), keyed on the sealed obligor "
            "origination class (reporting_class_origin)",
            "Rows are the populated PD ranges (the derived c08_pd_range band on "
            "pd_floored under CRR, on the pre-input-floor pd under Basel 3.1; the "
            "reported PD is always post-floor) plus an optional 9999 'Unassigned' "
            "residual — sparse: only populated buckets emit a row",
            "Cols 0010 (on balance sheet) / 0020 (off balance sheet) Sum the "
            "sealed per-side gross carriers (reporting_gross_on_bs / "
            "reporting_gross_off_bs) over the band. The carriers are row-level and "
            "null outside their side, so a CCR / settlement leg (null on both "
            "sides) appears in the EAD/RWEA cells (0040/0090) but not in 0010/0020, "
            "and a band with no off-balance-sheet rows sums to 0.0 naturally",
        ),
        sheet_label="exposure class",
    ),
    # C 08.05 — IRB PD back-testing (per exposure class; R24). Shares the sparse
    # PD-range row axis with C 08.03; R13 deleted its rate postfix, so it is
    # execute-only — generate_c08_05 is a plain execute of each plan, the cleanest
    # of the R24 trio.
    "c08_05": _Provider(
        plans=c08_05_plans,
        generate=generate_c08_05,
        scope=(
            "Internal-ratings-based credit-risk legs on the F-IRB and A-IRB "
            "approaches; slotting is excluded (reporting_approach_origin in "
            "{foundation_irb, advanced_irb}), keyed on the sealed obligor "
            "origination class (reporting_class_origin)",
            "Rows are the populated PD ranges (the derived c08_pd_range band) plus "
            "an optional 9999 'Unassigned' residual — the same sparse axis as "
            "C 08.03",
            "Col 0010 is the arithmetic-mean assigned PD (weighted by a constant "
            "c08_one column); col 0020 the obligors at the start of the observation "
            "period, col 0030 those defaulted during it; cols 0040 (observed "
            "default rate) and 0050 (its historical-rate fallback) are intra-row "
            "formulas. No post-execute pass and no '(-)'-labelled deduction column",
        ),
        sheet_label="exposure class",
    ),
    # C 08.06 — IRB slotting specialised lending (per SL type; R24). Sheets key
    # the SL TYPE (CRR IPRE absorbs HVCRE; B31 splits HVCRE; empty SL types emit no
    # sheet), NOT the class. generate_c08_06 is the provider generator directly:
    # its three value-dependent post-passes live on the reported frame. Each sheet
    # gets its OWN spec — an EMPTY non-Total row's col 0070 is a fixed display risk
    # weight (a zero-fill artefact), left UNBOUND so the drill-down reports the
    # template's empty policy rather than a WeightedAvg with no legs.
    "c08_06": _Provider(
        plans=c08_06_plans,
        generate=generate_c08_06,
        scope=(
            "Internal-ratings-based SLOTTING specialised-lending legs only "
            "(reporting_approach_origin == slotting); every other IRB approach "
            "discloses on C 08.01-05",
            "Sheets key the SL type (the sealed sl_type — project finance, "
            "income-producing real estate, object finance, commodities finance; "
            "under CRR IPRE absorbs HVCRE, under Basel 3.1 HVCRE is its own sheet), "
            "NOT the exposure class; an SL type with no legs emits no sheet",
            "Rows are the supervisory slotting category (strong/good/satisfactory/"
            "weak/default) x maturity band (short/long via the derived "
            "is_short_maturity, with the asymmetric fallback: absent the maturity "
            "column the short band is empty and the long band absorbs the "
            "category), plus the two maturity-split Total rows",
            "An EMPTY non-Total row is hard zero-filled post-execute with the row "
            "definition's FIXED display risk weight in col 0070 — a template "
            "artefact, not a measured weighted average — so that one cell is left "
            "UNBOUND (the drill-down reports the empty policy and reads its value "
            "from the reported frame); live rows and Total rows compute normally, "
            "with the 0030 nominal / 0040 clamp / 0070 first-non-null live fixes "
            "and the provisions ladder applied on the reported frame",
        ),
        sheet_label="SL type",
    ),
    # C 09.01 — geographical breakdown, SA (per country; R25). The FIRST
    # C 09-family instrumentation and the first sign-aware C 09 sweep: c09_01_plans
    # passes _C09_NEGATIVE_COLS ({0081,0082,0121,0122}) explicitly, so the CRR
    # supporting-factor adjustment columns 0081/0082 reconcile against their legs'
    # positive magnitudes (0081 fires non-zero on the TOTAL sheet). generate_c09_01
    # is the provider generator directly (its all-null inert-row pass and the
    # Annex II §1.3 "(-)" negation live on the reported frame the drill-down reads).
    # TWO-BASIS row model: a PRIMARY cell drills the APPLIED class, the 0020 memo
    # the ORIGINAL class.
    "c09_01": _Provider(
        plans=c09_01_plans,
        generate=generate_c09_01,
        scope=(
            "The SHARED C 07.00 population — the standardised book plus BOTH "
            "counterparty-credit-risk populations (FCCM SFT synthetic rows and "
            "SA-CCR derivative netting sets), admitted by risk_type (not by the "
            "approach label, which the output floor relabels)",
            "Two-basis row model (Annex II C 09.1): the PRIMARY columns key the "
            "APPLIED Art. 112 class (reporting_class_origin — a defaulted SA "
            "exposure moves to row 0100, as C 07.00 assigns it), while the 0020 "
            "'Defaulted exposures' MEMORANDUM keys the raw ORIGINAL class "
            "(exposure_class) conjoined with the defaulted flag — the "
            "counterfactual 'would have been' row. A class row is emptied only "
            "when BOTH its applied-class and original-class subsets are empty",
            "Under Basel 3.1 the real-estate reporting classes (retail_mortgage / "
            "residential_mortgage / commercial_mortgage) key the 'Real estate "
            "exposures' row 0090 and its regulatory-RRE / regulatory-CRE / other-RE "
            "/ ADC / SME 'of which' sub-rows (0091-0095); the SA specialised-lending "
            "'of which' sub-rows (0071-0073) key sl_type. RECORDED DECISION (R7): "
            "income-producing CRE is sealed reporting_class_origin == corporate, so "
            "it deliberately stays in row 0070 rather than double-counting into row "
            "0090 — row 0090 follows automatically if the classifier's IPRE-CRE "
            "scoping changes",
            "The CRR 'RWEA pre supporting factors' column (0080) keys "
            "rwa_pre_factor (falling back to the post-SF ladder when unsealed); the "
            "SME / Infrastructure '(-)' supporting-factor adjustment columns "
            "(0081/0082) carry Σ(rwa_pre_factor − rwa) over each factor's applied "
            "subset, so 0080 + 0081 + 0082 = 0090 foots. Under Basel 3.1 none of "
            "these refs exist (supporting factors are CRR-only), so the change is "
            "scoped by column presence, not by regime branching",
        ),
        sheet_label="country",
    ),
    # C 09.02 — geographical breakdown, IRB (per country; R25). Keys the sealed
    # reporting_class_origin over the IRB book INCLUDING slotting. generate_c09_02
    # is the provider generator directly: its all-null inert-row pass, the
    # value-dependent unweighted-mean fallback (_c09_02_avg_postfix) and the
    # Annex II §1.3 "(-)" negation live on the reported frame the drill-down reads.
    "c09_02": _Provider(
        plans=c09_02_plans,
        generate=generate_c09_02,
        scope=(
            "The IRB book — F-IRB / A-IRB AND slotting "
            "(reporting_approach_origin in {foundation_irb, advanced_irb, "
            "slotting}); C 09.02 keeps slotting IN the population, keyed on the "
            "sealed reporting_class_origin (== raw exposure_class for the IRB book "
            "— the number-neutral obligor basis, no default row by design)",
            "The PD/LGD averages weight by ead_final and report RAW ratios (no "
            "x100 despite the '(%)' labels); a value-dependent module post-step "
            "preserves the retired UNWEIGHTED-mean fallback for cols 0080/0090/0100 "
            "when a subset carries a non-positive total EAD (the WeightedAvg verb "
            "has no such fallback). RECORDED LIMITATION: the fallback does not fire "
            "on this portfolio, so the reported average IS the declared "
            "WeightedAvg; if a future book made a subset's total EAD non-positive "
            "the drill-down's weighted_avg label would understate that the rendered "
            "value became an unweighted mean — the LEGS stay correct, and the "
            "sign-aware sweep does not reconcile a WeightedAvg cell, so it is not "
            "the tripwire it is for C 08.03's sum fallback",
            "The CRR 'RWEA pre supporting factors' column (0110) keys "
            "rwa_pre_factor (post-SF fallback); the SME / Infrastructure '(-)' "
            "supporting-factor adjustment columns (0121/0122) carry "
            "Σ(rwa_pre_factor − rwa) over each factor's applied subset (0121 fires "
            "non-zero and negative on the TOTAL sheet), so 0110 + 0121 + 0122 = "
            "0125 foots. B31 carries none of these refs (supporting factors are "
            "CRR-only)",
        ),
        sheet_label="country",
    ),
    # CR6 — IRB exposures by exposure class and PD range (per obligor class; R25).
    # The OBLIGOR basis (reporting_class_origin — Annex XXII bars substitution
    # effects), the OPPOSITE of CR4/CR5's post-substitution basis. generate_cr6 is
    # the provider generator directly: its empty-band all-null pass and the String
    # col 'a' label injection stay on the reported frame the drill-down reads (the
    # tie-out sweep skips col 'a' as a String column).
    "cr6": _Provider(
        plans=cr6_plans,
        generate=generate_cr6,
        scope=(
            "The ORIGIN F-IRB / A-IRB book (reporting_approach_origin in "
            "{foundation_irb, advanced_irb} — slotting is excluded from the PD "
            "scale); each sheet is one obligor class keyed on the sealed "
            "reporting_class_origin (the recorded F3 OBLIGOR basis — 'without "
            "considering any substitution effects due to CRM', Annex XXII column a; "
            "the opposite basis from CR4/CR5, number-neutral for the IRB book which "
            "has no defaulted class)",
            "PD-band rows allocate on the derived cr6_alloc_pd column, half-open "
            "[lower, upper): Basel 3.1 allocates on the PRE-input-floor pd, CRR on "
            "pd_floored (PS1/26 Annex XXII column a mandates pre-floor allocation). "
            "All defaulted exposures are forced into the 100% PD band (row 17) via "
            "the derived column, per Annex XXII ('All defaulted exposures shall be "
            "included in the bucket representing PD of 100%')",
            "Gross columns b/c sum the sealed per-side gross carriers over the "
            "band (reporting_gross_on_bs on-balance-sheet, reporting_gross_off_bs "
            "off-balance-sheet — the side is in the carrier, so the cells carry no "
            "on/off-BS predicate; the CCR legs are dropped and facility_undrawn is "
            "patched off-BS by irb_scope); f/h/i report the "
            "EAD-weighted post-floor pd_floored x100 / lgd_floored x100 / "
            "irb_maturity_m; k is the RWEA density; col m (SCRA provisions) is "
            "permanently null (never produced by the engine). Col a is the String "
            "PD-range label injected post-execute (not an addressable numeric cell)",
        ),
        sheet_label="exposure class",
    ),
    # CR9 — IRB PD back-testing per approach x leaf class (Basel 3.1 only; R26). The
    # FINAL instrumentation item. cr9_plans keys the COMPOUND "approach - leaf class"
    # sheet; generate_cr9 is the provider generator directly (its sparse
    # _drop_empty_bands filter and the String label injection stay on the reported
    # frame the drill-down reads — the sweep skips the String cols a/b). Basel 3.1
    # ONLY: plans() yields {} under CRR, so a CRR request degrades to a clean
    # no-lineage (the CMS pattern). Value cells are counts / weighted averages /
    # arithmetic means / intra-row formulas — NO Sum cell, so the sweep reconciles
    # each row-backed cell by predicate-match count rather than a signed total.
    "cr9": _Provider(
        plans=cr9_plans,
        generate=generate_cr9,
        scope=(
            "The ORIGIN F-IRB / A-IRB book (reporting_approach_origin in "
            "{foundation_irb, advanced_irb} — slotting has no PD scale), Basel 3.1 "
            "ONLY (CR9 has no CRR equivalent; a CRR run produces nothing). Each sheet "
            "is one origin approach x Annex XXII leaf class, keyed on the OBLIGOR "
            "basis (reporting_class_origin x reporting_approach_origin refined by the "
            "module-owned leaf taxonomy — is_sme / property_type / financial-large "
            "discriminators; Annex XXII bars substitution effects, so substitution "
            "never moves a sheet)",
            "PD-band rows reuse the 17 fixed CR6 ranges, allocated half-open on the "
            "derived cr9_alloc_pd (the pre-input-floor pd, falling back to pd_floored), "
            "with all defaulted exposures forced into the 100% band (row 17) via the "
            "normalized default flag — the CR6 fix. ONLY populated bands emit a row "
            "(plus the Total row 18) — the sparse-emission convention, dropped "
            "post-execute on the reported frame",
            "The value columns are single-run point-in-time PROXIES (the recorded "
            "F6-family follow-up — a true back-testing series needs prior-period "
            "carriers the engine does not produce): c counts distinct obligors (or "
            "sums prior_year_obligor_count when supplied), d the distinct defaulted "
            "obligors; e = d/c x100 and its historical-rate fallback h are intra-row "
            "formulas; f/g the EAD-weighted / arithmetic-mean post-floor PD x100. NO "
            "Sum cell and no '(-)'-labelled deduction column, so the sweep reconciles "
            "each row-backed cell by predicate-match count, not a signed total. Cols "
            "a (class label) and b (PD-range label) are String post-steps, not "
            "addressable numeric cells",
        ),
        sheet_label="approach and leaf class",
    ),
    # CR9.1 — IRB ECAI-mapping PD back-testing (Basel 3.1 only; R26). Same compound
    # sheet key as CR9 but a per-class DATA-DRIVEN grade spec (rows = the class's
    # distinct ECAI grades). The engine produces NEITHER ecai_pd_mapping NOR
    # external_rating_equivalent, so cr9_1_plans yields {} on the real portfolio
    # (both frameworks) — a lineage request degrades to a clean no-lineage, exactly
    # as CR9/CMS do under CRR. Instrumented for the seeded case; a seeded unit pin
    # guards the plan/generate parity in the absence of a portfolio tie-out.
    "cr9_1": _Provider(
        plans=cr9_1_plans,
        generate=generate_cr9_1,
        scope=(
            "The ORIGIN F-IRB / A-IRB book scoped to obligors flagged ecai_pd_mapping "
            "(Art. 180(1)(f) ECAI-based PD estimation), Basel 3.1 ONLY. Each sheet is "
            "one origin approach x Annex XXII leaf class (the CR9 taxonomy), keyed on "
            "the OBLIGOR basis (reporting_class_origin x reporting_approach_origin)",
            "Rows are DATA-DRIVEN — the class's distinct firm ECAI grades "
            "(external_rating_equivalent) plus a Total row — so each sheet carries its "
            "OWN spec (the C 08.02 pattern). The c-h value verbs are shared with CR9 "
            "(counts / weighted averages / arithmetic means / intra-row formulas), so "
            "there is no Sum cell and no '(-)'-labelled deduction column; cols a/b and "
            "the dynamic grade column are String post-steps",
            "RECORDED LIMITATION: the engine produces neither ecai_pd_mapping nor "
            "external_rating_equivalent, so CR9.1 is EMPTY on the real pipeline (the "
            "recorded S1 accept-empty decision) — plans() yields nothing and a lineage "
            "request degrades to a clean no-lineage. It comes alive only on a seeded "
            "frame, which the acceptance tie-out (the real portfolio) cannot exercise; "
            "a dedicated seeded unit pin guards the instrumentation instead",
        ),
        sheet_label="approach and leaf class",
    ),
    # CR10 — slotting specialised lending + CRR simple-RW equity (per subtemplate;
    # R26). cr10_plans keys each subtemplate by its sl_type (equity for the CRR
    # CR10.5 sheet); generate_cr10 is the provider generator directly (the fixed
    # col-c risk-weight post-step stays on the reported frame the drill-down reads).
    # The fixed col c is UNBOUND in both specs, so the drill-down reports it as the
    # template's empty policy (kind unbound, no legs) and reads the display weight
    # from the reported frame — never a binding that could disagree (the C 08.06
    # unbound-0070 precedent; col b on the equity sheet is unbound the same way).
    "cr10": _Provider(
        plans=cr10_plans,
        generate=generate_cr10,
        scope=(
            "Each subtemplate draws its OWN population. CR10.1-4 read the ORIGIN "
            "slotting book (reporting_approach_origin == slotting) — a guaranteed "
            "slotting exposure's covered leg leaves the slotting approach, so the "
            "origin basis IS the obligor basis; the sheet is narrowed by sl_type (CRR "
            "groups IPRE + HVCRE under CR10.2, Basel 3.1 splits HVCRE onto CR10.5). "
            "The CRR CR10.5 equity sheet reads the Art. 155(2) simple-RW equity legs "
            "(reporting_approach_origin == equity AND equity_method == irb_simple — "
            "Art. 133 SA and Art. 155(3) PD/LGD equity excluded) and is force-emitted "
            "even when empty",
            "Slotting rows are the five supervisory categories (matched on "
            "slotting_category) EACH split into two remaining-maturity bands (matched "
            "on the derived cr10_is_short — the C 08.06 asymmetric fallback: absent "
            "the maturity column the short band is empty and the long band absorbs the "
            "category), plus two maturity-split Total rows. Equity rows are the three "
            "fixed Art. 155(2) bands (a leg lands by its applied reporting_rw) plus "
            "Total; equity is on-balance-sheet, so col a mirrors col d and col b is "
            "left unbound (null)",
            "Column c is the FIXED regulatory risk weight ('This is a fixed column. "
            "It shall not be altered' — Art. 153(5) Table A / Art. 155(2)): it is left "
            "UNBOUND in both specs and injected post-execute from the template "
            "constants (the maturity-correct slotting weight per band, the equity band "
            "weight for CR10.5; Total rows null), so the drill-down reports it as the "
            "template's empty policy and reads the display value from the reported "
            "frame rather than a WeightedAvg with no legs (the C 08.06 unbound-0070 "
            "precedent). Cols a/b/d/e/f are Sum/SafeSum and reconcile against their "
            "legs; CR10 carries no '(-)'-labelled deduction column",
        ),
        sheet_label="subtemplate",
    ),
    # CCR1 — analysis of CCR exposure by approach (single frame; R27c). The plan
    # frame is the pre-filtered SA-CCR netting-set population (FCCM SFTs excluded)
    # carrying the derived ccr1_default_risk flag; col a sums the whole frame, col
    # b narrows to the non-QCCP-trade partition.
    "ccr1": _Provider(
        plans=ccr1_plans,
        generate=ccr1_frames,
        scope=(
            "The SA-CCR netting-set population — the synthetic ``ccr__``-prefixed "
            "rows, with FCCM SFTs EXCLUDED (an SFT uses FCCM under Art. 220-223, "
            "not the SA-CCR Art. 274 approach these templates analyse; it reports "
            "on SA template C 07.00 row 0090). Admitted by exposure reference (not "
            "the approach label the output floor relabels)",
            "The SA-CCR row (1) and the Total row (11) sum ead_final (col a) over "
            "the whole population — CRR Art. 274(2) SA-CCR EAD = alpha * (RC + "
            "PFE) — and rwa_final (col b) over the derived ccr1_default_risk "
            "partition (~((cp_entity_type == ccp) & cp_is_qccp.fill_null(True)) — "
            "the non-QCCP default-risk RWEA, CRR Art. 107(2)(a)). The IMM / "
            "Original-exposure rows are structural placeholders left null. None "
            "when the portfolio has no such rows",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CCR2 — CVA capital charge (single frame; R27c). Presence-gated on cva_rwa
    # (a CRR run carries none, so a CRR lineage request degrades to a clean
    # no-lineage). The cell reads the portfolio BA-CVA roll-up as a broadcast
    # constant (FirstNonNull, the OV1 row-26 / C 34.04 idiom); no producing golden
    # fixture, so it is pinned by the CVA-A1 unit estate + a seeded lineage pin.
    "ccr2": _Provider(
        plans=ccr2_plans,
        generate=ccr2_frames,
        scope=(
            "The full sealed per-leg ledger (presence-gated on cva_rwa — CCR2 is "
            "not produced when the portfolio carries no CVA charge, which is what "
            "makes it None under CRR). The BA-CVA row (4) and the Total row (6) "
            "read the portfolio BA-CVA roll-up (cva_rwa) as a broadcast per-row "
            "constant via FirstNonNull — the OV1 row-26 idiom; the drill-down "
            "shows the legs carrying that constant rather than a sum attributable "
            "to them",
            "cva_rwa is the BA-CVA own-funds requirement scaled to RWEA (PS1/26 "
            "App.1 Own Funds Part 4(b): RWEA_CVA = OFR_CVA * 12.5), a "
            "portfolio-level scalar and not a leg aggregate, so the cell does not "
            "reconcile to a signed total",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CCR3 — SA-CCR EAD by risk-weight band (single frame; R27c). The plan frame is
    # the pre-filtered SA-CCR population carrying the derived ccr3_band label; each
    # band row narrows to its matched band and the Total row sums the whole frame.
    "ccr3": _Provider(
        plans=ccr3_plans,
        generate=ccr3_frames,
        scope=(
            "The SA-CCR netting-set population (the ``ccr__``-prefixed rows, FCCM "
            "SFTs excluded — the CCR1 population) carrying the derived ccr3_band "
            "label (each row's risk_weight assigned to a CR5 risk-weight band "
            "within ±0.005, else 'other')",
            "Each band row (col a) sums ead_final over the rows whose ccr3_band "
            "matches the band; the 'Other' row keys the unmatched complement; the "
            "Total row sums the whole population (CRR Art. 444(e); Art. 120(1) "
            "Table 3 institution CQS bands). An empty band is a null cell (the "
            "Pillar 3 empty policy). None when no CCR rows exist or risk_weight is "
            "absent",
        ),
        sheet_label="",
        single_frame=True,
    ),
    # CCR8 — exposures to central counterparties (single frame; R27c). The plan
    # frame is the include_sft=True SA-CCR population carrying the derived
    # ccr8_qccp flag; each cell's predicate narrows to the CCP subset. The R5 CCP
    # restriction (a bilateral counterparty is NEITHER row) is preserved exactly —
    # CCR8 is the disclosure counterpart of the OV1 UK8a QCCP memo row.
    "ccr8": _Provider(
        plans=ccr8_plans,
        generate=ccr8_frames,
        scope=(
            "The SA-CCR netting-set population with FCCM SFTs INCLUDED "
            "(``include_sft=True`` — a CCP-faced SFT IS a CCP exposure, CRR Art. "
            "301(1)(b)) RESTRICTED to CCP counterparties (cp_entity_type == ccp) — "
            "a book of purely bilateral derivatives / SFTs has nothing to disclose "
            "here (the R5 emission gate and CCP restriction)",
            "Row 1 (QCCPs) and row 2 (non-QCCPs) partition the CCP subset by the "
            "derived ccr8_qccp flag (cp_is_qccp.fill_null(True) — a null CCP "
            "treated as qualifying, CRR Art. 306(1); a bilateral OTC counterparty "
            "is NEITHER row, disclosing on CCR1/CCR3 instead — the R5 fix). Row 21 "
            "(Total) is the whole CCP population. Each row sums rwa_final (col a) "
            "and ead_final (col b) over its subset",
        ),
        sheet_label="",
        single_frame=True,
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
