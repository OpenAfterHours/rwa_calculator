"""
Return-reconciliation template view — one return template, ours against theirs.

Pipeline position:
    ReconciliationResponse {calculation, legacy_ledger, legacy_ledger_coverage}
        -> analysis.return_recon.build_recon (ONCE per reconciliation)
        -> ui.views.return_recon (this module) -> recon_templates.html

Key responsibilities:
- Render one scoped template sheet as an ours / theirs / delta grid in which a
  FIGURE, an EMPTY cell, an UNAVAILABLE cell and an ABSENT row are four
  visibly different things — never four spellings of zero.
- Rank the worst cells under a materiality threshold set ONCE per compare, and
  keep the cells that carry no delta at all on a SEPARATE list, so a cell the
  legacy mapping cannot populate cannot vanish for want of a number to sort on.
- Cross-tabulate one predicate group's legs by our row against their row (the
  migration matrix), with ``PLACEMENT_ATTRIBUTION`` carried verbatim beside it.
- Render one cell's four-way waterfall, or the REFUSAL saying why the four
  terms do not apply to that cell.

NO UI-FRAMEWORK IMPORTS. Everything here is plain frozen dataclasses over
``analysis.return_recon``, exactly as ``ui.views.reconciliation`` is over
``analysis.reconciliation`` — which is what makes the rendering rules below
unit-testable without a request.

THE RULES THIS MODULE EXISTS TO ENFORCE. Each is a wrong number on a regulatory
comparison if broken, and each has been measured in this codebase:

1. **Four blanks, four meanings.** ``analysis.return_recon`` publishes a
   per-side ``CellState``; this module maps each to its OWN glyph, CSS class and
   title (see ``STATE_DISPLAY``) and never to ``0``. A missing row, an emitted
   empty row, a cell no mapping can populate and a reported zero are four
   different findings.
2. **A coverage-unavailable cell never shows a figure or a delta.** When either
   side is ``unavailable`` the diff's ``status`` is ``unmeasurable`` and its
   ``delta`` is NULL; the cell renders ``n/a`` with the REMEDY off
   ``LedgerCoverage`` ("map ``provisions`` to unlock …"). Rendering ``0.00``
   there manufactures the largest delta on the sheet, and it is a figure the
   generator really does print — ``ensure_gross_side_carriers`` injects an
   all-null column and ``sum`` returns 0.0 over it.
3. **A refused decomposition is never a zero waterfall.** ``decompose_cell``
   refuses non-additive cells (weighted averages, means, ratios, counts),
   formula / side-context / prior-period cells and cells built on an
   unavailable source. ``CellExplanation.refused`` carries the reason and NO
   steps. A four-way split of a weighted average would look entirely plausible
   and be fabricated.
4. **Never aggregate across ``predicate_key``, and never rebuild a total from
   ``~is_parent_row``.** A template row does not have one population. This
   module resolves the ONE group serving a cell through
   ``CellMembership.columns`` and reads that group's legs; every migration
   matrix is scoped to a single ``predicate_key`` and none is ever summed with
   another. Measured consequences of getting this wrong: 3.00x and 1.86x
   over-counts, and 0.00 against real money on four of ten sheets. A NULL
   parent flag is reported as "indistinguishable", never as a leaf.

References:
- Regulation (EU) 2021/451, Annex II: C 07.00, C 08.01, C 08.03
- PRA PS1/26 Annex I/II: OF 07.00, OF 08.01, OF 08.03
- docs/plans/return-reconciliation.md, Phase 3 (the template view)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.analysis.return_recon import (
    ABSENT_ROW,
    MIGRATION_MONEY_COLUMNS,
    PLACEMENT_ATTRIBUTION,
    RECON_TEMPLATE_IDS,
    UNDECIDABLE_ROW,
    build_recon,
    decompose_cell,
    diff_cells,
    row_migration,
)
from rwa_calc.observability import loggable
from rwa_calc.reporting import catalog
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.ui.views.report_templates import format_value

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rwa_calc.analysis.legacy_ledger import LedgerCoverage
    from rwa_calc.analysis.return_recon import CellDecomposition, ReturnRecon, SideView
    from rwa_calc.api.models import ReconciliationResponse
    from rwa_calc.reporting.metadata import ResultsSource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Display vocabulary
# ---------------------------------------------------------------------------

#: What each ``CellState`` renders as: ``(glyph, css class, title)``. The four
#: are deliberately distinct strings — a grid that shows three of them the same
#: way has thrown away the finding, which is rule 1 in the module docstring.
STATE_DISPLAY: dict[str, tuple[str, str, str]] = {
    "figure": ("", "is-figure", "a reported figure"),
    "empty": ("—", "is-null", "emitted with no population — nothing to report here"),
    "unavailable": ("n/a", "is-unavailable", "cannot be computed from this side's sources"),
    "absent": ("·", "is-absent", "not emitted on this side — the row or column is missing"),
}

#: The delta glyph for a cell nobody can measure. NEVER ``0`` and never ``0.00``.
UNMEASURABLE_DISPLAY = "n/a"

#: The delta glyph for a pair the template binds NO cell at, on either side.
#: Distinct from both a reported ``0`` and the unmeasurable ``n/a`` above,
#: because "there is nothing here to compare" is a third statement.
NO_CELL_DISPLAY = "·"

#: Readable digest of the two sides' states.
STATUS_LABELS: dict[str, str] = {
    "both": "both sides",
    "ours_only": "ours only",
    "theirs_only": "theirs only",
    "neither": "neither side",
    "unmeasurable": "not measurable",
}

#: Waterfall term labels, in ``return_recon.TERM_NAMES`` order.
TERM_LABELS: dict[str, str] = {
    "population_ours_only": "population — in ours only",
    "population_theirs_only": "population — in theirs only",
    "row_placement": "row placement — moved band",
    "sheet_placement": "sheet placement — moved class",
    "measurement": "measurement — same row, different value",
}

#: The four refusals, and the FIRST LINE each one puts on the page. They are
#: written to produce four different next actions: fix the mapping, read the
#: figures but not a split, follow the references, or nothing is instrumented
#: here. Rendering them alike gives the wrong action three times in four.
REFUSAL_HEADLINES: dict[str, str] = {
    "coverage": (
        "This is not a difference. Your mapping cannot populate this column, so "
        "there is no legacy figure to compare — map what is named below."
    ),
    "non_additive": (
        "Both figures are real and comparable; only the four-way split does not "
        "apply. This column is an average, not a total, so a population that "
        "moved shows up in it as a MIX effect rather than as a rate difference."
    ),
    "not_row_backed": (
        "This cell has no exposure population of its own — it is derived from "
        "other cells. Explain those instead."
    ),
    "unbound": "This template or cell is not instrumented, so it has no addressable population.",
}

#: Migration-matrix cell classes, and what each one means to a reader.
BASIS_LABELS: dict[str, str] = {
    "agreed": "same row on both sides",
    "value_driven": "moved row — their value differs from ours",
    "ours_only": "we hold this leg in this group, they do not",
    "theirs_only": "they hold this leg in this group, we do not",
    "undecidable": "held, but no single provable leaf row — money kept, not placed",
}

#: The template's regulatory code under each framework. The three scoped
#: templates are one set of generators under both regimes — PS1/26 renames them
#: OF NN.NN — so the picker labels them from the run's OWN framework rather than
#: from the CRR-flavoured catalogue title.
TEMPLATE_CODES: dict[str, dict[str, str]] = {
    "c07_00": {"CRR": "C 07.00", "BASEL_3_1": "OF 07.00"},
    "c08_01": {"CRR": "C 08.01", "BASEL_3_1": "OF 08.01"},
    "c08_03": {"CRR": "C 08.03", "BASEL_3_1": "OF 08.03"},
}

#: How many worst cells / unmeasurable cells / legs a page lists.
WORST_CELLS_LIMIT = 25
UNMEASURABLE_LIMIT = 25
CELL_LEGS_LIMIT = 25

#: Default materiality. A firm's return is rounded to GBP 000s, so an absolute
#: floor removes rounding noise; the relative floor removes float dust on a
#: cell of hundreds of millions. BOTH must be exceeded — either alone still
#: produces noise rather than findings.
DEFAULT_MATERIALITY_ABSOLUTE = 1_000.0
DEFAULT_MATERIALITY_PERCENT = 0.1

#: Below this a delta is float dust, not a difference. Two sums that agree to
#: this margin agreed exactly and the residue is the order of arithmetic —
#: the same convention, and the same magnitude, as the reconciliation engine's
#: own exact-match epsilon. An exact ``== 0.0`` would also make the zero-base
#: branch below reachable for a delta that is only nominally non-zero.
_ZERO_DELTA = 1e-9

#: The honest limits of this path, shown on the page rather than in a docstring
#: nobody reads. Every one of them changes how a number should be read.
COMPARE_LIMITS: tuple[str, ...] = (
    "Their side is aggregated OUR way: a weighted-average column uses our "
    "weighting, our distinct-count rule and our sign convention. A difference "
    "here is a DATA difference; a column their return aggregates differently is "
    "invisible until their filed return is supplied.",
    "Only the instrumented templates are compared. A template with no "
    "membership has no addressable populations, so it gets no decomposition.",
    "A cell one side cannot populate is reported as unavailable, never as a "
    "zero — the mapping, not the book, is what is missing.",
)

#: Cap on the number of live comparisons memoised. A ``ReturnRecon`` holds two
#: generated template bundles and two membership frames, so this is deliberately
#: small; the oldest entry is evicted.
_CACHE_LIMIT = 4

_CACHE: dict[str, ReturnRecon] = {}

_THOUSAND = 1000.0


# =============================================================================
# Main entry point
# =============================================================================


@dataclass(frozen=True)
class Materiality:
    """The one threshold a compare is read under, set ONCE for the whole page.

    A cell is material only when it clears BOTH floors: ``absolute`` (their
    return is rounded, so a small money delta is rounding) and ``percent`` of
    the larger side (so float dust on a large cell is not a finding). A cell
    with no delta at all is never material — it is unmeasurable, which is a
    different and separately reported thing.
    """

    absolute: float = DEFAULT_MATERIALITY_ABSOLUTE
    percent: float = DEFAULT_MATERIALITY_PERCENT

    def is_material(self, delta: float | None, ours: float | None, theirs: float | None) -> bool:
        """Whether one cell's delta clears both floors."""
        if delta is None or abs(delta) < _ZERO_DELTA:
            return False
        if abs(delta) < self.absolute:
            return False
        base = max(abs(ours or 0.0), abs(theirs or 0.0))
        if not base:
            # A delta against a zero base is all of the cell: relatively infinite.
            return True
        return (abs(delta) / base) * 100.0 >= self.percent


DEFAULT_MATERIALITY = Materiality()


@dataclass(frozen=True)
class ColumnHead:
    """One compared column: its regulatory ref, readable name and header band."""

    ref: str
    name: str
    group: str = ""


@dataclass(frozen=True)
class SideFigure:
    """One side of one cell: what it says, and WHY it says nothing when it does."""

    value: float | None
    state: str
    display: str
    css: str
    title: str


@dataclass(frozen=True)
class CompareCell:
    """One cell, both sides and the delta — with every blank still explained."""

    row_ref: str
    row_name: str
    col_ref: str
    col_name: str
    ours: SideFigure
    theirs: SideFigure
    delta: float | None
    delta_display: str
    status: str
    status_label: str
    is_material: bool
    heat: float
    note: str

    @property
    def measurable(self) -> bool:
        """Whether a delta exists for this cell at all."""
        return self.status != "unmeasurable"


@dataclass(frozen=True)
class CompareRow:
    """One template row of the compared grid."""

    row_ref: str
    row_name: str
    cells: tuple[CompareCell, ...]


@dataclass(frozen=True)
class SheetCompare:
    """One template sheet compared end to end.

    ``worst`` ranks the MATERIAL cells by |delta|. ``unmeasurable`` is a
    SEPARATE list rather than the tail of the same one: those cells have no
    delta to sort on, so a single ranked list would silently drop them — and
    they are the cells whose remedy is actionable.
    """

    template_id: str
    template_label: str
    sheet: str | None
    columns: tuple[ColumnHead, ...]
    rows: tuple[CompareRow, ...]
    worst: tuple[CompareCell, ...]
    unmeasurable: tuple[CompareCell, ...]
    max_abs_delta: float
    material_count: int
    unmeasurable_count: int
    cell_count: int


@dataclass(frozen=True)
class MigrationGroup:
    """One addressable population on a sheet, and the columns it serves.

    A row does not have one population — this is the unit that does. Named by
    its anchor column ref, which is what ``reporting.membership`` keys on.
    """

    predicate_key: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class MigrationCell:
    """One (our row, their row) cell of the matrix, priced."""

    our_row_ref: str
    their_row_ref: str
    legs: int
    money_ours: float | None
    money_theirs: float | None
    money: float | None
    display: str
    basis: str
    basis_label: str
    is_diagonal: bool
    heat: float


@dataclass(frozen=True)
class MigrationTotals:
    """The matrix's money by movement class. Each leg falls in exactly one."""

    agreed: float
    moved: float
    ours_only: float
    theirs_only: float
    undecidable: float


@dataclass(frozen=True)
class MigrationMatrix:
    """Our row down, their row across, priced — for ONE predicate group.

    ``attribution`` is ``return_recon.PLACEMENT_ATTRIBUTION`` verbatim and must
    be rendered next to the matrix: both sides are banded by our generators from
    their own values, so an off-diagonal cell is VALUE-driven by construction. A
    rule-driven banding difference is structurally invisible here.
    """

    predicate_key: str
    columns: tuple[str, ...]
    money_column: str
    our_rows: tuple[str, ...]
    their_rows: tuple[str, ...]
    cells: tuple[tuple[MigrationCell | None, ...], ...]
    totals: MigrationTotals
    axis_is_partition: bool
    attribution: str = PLACEMENT_ATTRIBUTION


@dataclass(frozen=True)
class WaterfallStep:
    """One signed cause of a cell delta."""

    name: str
    label: str
    amount: float
    display: str
    keys: int
    share: float


@dataclass(frozen=True)
class CellLeg:
    """One exposure leg behind a cell, in the group that cell actually reads."""

    key: str
    exposure_reference: str
    source_exposure_reference: str
    ead: float | None
    rwa: float | None
    side: str


@dataclass(frozen=True)
class CellExplanation:
    """One cell's four-way waterfall — or the refusal that replaces it.

    ``refused`` is the load-bearing field. When it is true there are NO steps
    and ``refusal`` says why: rendering a zero waterfall for a weighted average
    would be a fabricated number wearing an explanation's clothes.

    ``refusal_kind`` is what makes the page say the RIGHT thing, because the
    four reasons demand four different next actions from the analyst:

    - ``coverage``      — their mapping cannot populate this column. Not a
      difference at all; the remedy is in ``remedy``, and this cell must never
      appear in a ranked list of differences.
    - ``non_additive``  — a weighted average, mean, ratio, count or
      first-non-null. The figures are real and comparable; only the four-way
      SPLIT does not apply to them.
    - ``not_row_backed``— a formula, side context, prior period or constant. It
      has no exposure population at all; read the cells it references.
    - ``unbound``       — this template or cell is not instrumented here.

    The classification mirrors ``return_recon._refusal_reason``'s own order, so
    ``refusal_kind`` and ``refusal`` can never contradict one another; ``remedy``
    is carried independently, so a coverage-blocked weighted average still names
    what to map.
    """

    template_id: str
    sheet: str | None
    row_ref: str
    row_name: str
    col_ref: str
    col_name: str
    kind: str
    metric: str | None
    predicate_key: str
    row_is_parent: bool | None
    parent_note: str
    ours: SideFigure
    theirs: SideFigure
    delta: float | None
    delta_display: str
    steps: tuple[WaterfallStep, ...]
    refused: bool
    refusal: str
    refusal_kind: str
    refusal_headline: str
    remedy: str
    reconciles: bool
    residual: float | None
    residual_display: str
    our_legs: tuple[CellLeg, ...]
    their_legs: tuple[CellLeg, ...]
    our_leg_count: int
    their_leg_count: int
    attribution: str = PLACEMENT_ATTRIBUTION


@dataclass(frozen=True)
class TemplateOption:
    """One template offered by the picker, and WHY it may carry nothing.

    ``reachable`` and ``populated`` are INDEPENDENT facts and telling the
    analyst the wrong one sends them after a fix that does not exist:

    - ``reachable`` false — *their mapping* cannot produce this template. The
      remedy is in ``blocked_reason``: map these columns, or add these
      ``value_map`` entries. This is a mapping defect.
    - ``populated`` false — the mapping is fine and *their book* simply holds no
      such exposures. An all-standardised firm legitimately has no C 08.01.
      There is nothing to fix, and saying "your mapping is broken" here would be
      wrong. Its cells are ordinary empties, not unavailable ones.
    - ``populated`` ``None`` — the projection did not measure the vocabulary, so
      the question was never asked. Never rendered as either answer.
    """

    id: str
    label: str
    sheets: tuple[str, ...]
    reachable: bool
    blocked_reason: str
    populated: bool | None = None
    population_note: str = ""

    @property
    def state(self) -> str:
        """``comparable`` / ``unreachable`` / ``unpopulated`` — one of three."""
        if not self.reachable:
            return "unreachable"
        if self.populated is False:
            return "unpopulated"
        return "comparable"


@dataclass(frozen=True)
class TemplateComparePage:
    """Everything ``recon_templates.html`` renders.

    ``available`` false is the DEGRADED page: a reconciliation whose mapping was
    too thin to project carries no legacy ledger, and that is an explanation
    with a remedy, not an error.
    """

    recon_id: str
    framework: str
    available: bool
    unavailable_reason: str
    remedies: tuple[str, ...]
    warnings: tuple[str, ...]
    templates: tuple[TemplateOption, ...]
    selected: TemplateOption | None
    sheet: str | None
    compare: SheetCompare | None
    materiality: Materiality
    groups: tuple[MigrationGroup, ...]
    matrix: MigrationMatrix | None
    money_column: str
    money_columns: tuple[str, ...] = MIGRATION_MONEY_COLUMNS
    explanation: CellExplanation | None = None
    limits: tuple[str, ...] = COMPARE_LIMITS
    absent_row_ref: str = ABSENT_ROW
    undecidable_row_ref: str = UNDECIDABLE_ROW


def template_page(  # noqa: PLR0913 - the page's full address is its signature
    recon: ReturnRecon | None,
    *,
    recon_id: str,
    framework: str,
    coverage: LedgerCoverage | None = None,
    unavailable_reason: str = "",
    warnings: Sequence[str] = (),
    template_id: str | None = None,
    sheet: str | None = None,
    row_ref: str = "",
    col_ref: str = "",
    predicate_key: str = "",
    money_column: str = "rwa_final",
    materiality: Materiality = DEFAULT_MATERIALITY,
) -> TemplateComparePage:
    """Build the whole template-compare page for one reconciliation.

    ``recon`` is ``None`` on the degraded path — the mapping produced no legacy
    ledger, so there is no second side to compare against. The page then carries
    ``unavailable_reason`` plus whatever ``coverage`` names as the remedy, and
    renders an explanation rather than an error.

    ``template_id`` and ``sheet`` default to the first template and sheet that
    exist, so the page is reachable without knowing what a run produced. An
    unknown id or sheet falls back the same way rather than raising: what a run
    produced is data, not a contract.
    """
    if recon is None:
        return TemplateComparePage(
            recon_id=recon_id,
            framework=framework,
            available=False,
            unavailable_reason=unavailable_reason or _NO_LEDGER,
            remedies=_remedy_lines(coverage),
            warnings=tuple(warnings),
            templates=(),
            selected=None,
            sheet=None,
            compare=None,
            materiality=materiality,
            groups=(),
            matrix=None,
            money_column=money_column,
        )

    options = template_options(recon, coverage)
    selected = _select_template(options, template_id)
    if selected is None:
        return TemplateComparePage(
            recon_id=recon_id,
            framework=recon.framework,
            available=False,
            unavailable_reason=_NO_TEMPLATES,
            remedies=_remedy_lines(coverage),
            warnings=tuple(warnings),
            templates=options,
            selected=None,
            sheet=None,
            compare=None,
            materiality=materiality,
            groups=(),
            matrix=None,
            money_column=money_column,
        )

    # Take the element FROM the template's own sheet list rather than the string the
    # request supplied. The two compare equal, so the behaviour and the fallback are
    # unchanged — but only one of them has a provenance a reader can trust, and a
    # value that never came from the request cannot forge anything downstream.
    chosen_sheet = next(
        (known for known in selected.sheets if known == sheet),
        selected.sheets[0] if selected.sheets else None,
    )
    compare = sheet_compare(
        recon, selected.id, chosen_sheet, coverage=coverage, materiality=materiality
    )
    groups = migration_groups(recon, selected.id, chosen_sheet)
    group_key = _select_group(groups, predicate_key, recon, selected.id, chosen_sheet, col_ref)
    price = next((known for known in MIGRATION_MONEY_COLUMNS if known == money_column), "rwa_final")
    matrix = (
        migration_matrix(recon, selected.id, chosen_sheet, group_key, money_column=price)
        if group_key
        else None
    )
    explanation = (
        explain_cell(recon, selected.id, chosen_sheet, row_ref, col_ref, coverage=coverage)
        if row_ref and col_ref
        else None
    )
    return TemplateComparePage(
        recon_id=recon_id,
        framework=recon.framework,
        available=True,
        unavailable_reason="",
        remedies=_remedy_lines(coverage, selected.id),
        warnings=tuple(warnings),
        templates=options,
        selected=selected,
        sheet=chosen_sheet,
        compare=compare,
        materiality=materiality,
        groups=groups,
        matrix=matrix,
        money_column=price,
        explanation=explanation,
    )


# =============================================================================
# Building one comparison (memoised — generating both sides is expensive)
# =============================================================================


def build_comparison(  # noqa: PLR0913 - two sides, each with its own coverage
    recon_id: str,
    ours: ResultsSource,
    theirs: ResultsSource,
    *,
    ours_coverage: LedgerCoverage | None = None,
    theirs_coverage: LedgerCoverage | None = None,
    template_ids: Sequence[str] | None = None,
) -> ReturnRecon:
    """Both sides of one reconciliation's templates, generated ONCE and reused.

    Generating a template bundle is expensive and this page addresses one cell
    at a time, so the whole comparison is built once per ``recon_id`` and held.

    **``theirs_coverage`` IS NOT OPTIONAL IN PRACTICE, AND THE GUARD IT ARMS IS
    INERT WITHOUT IT.** ``build_recon`` defaults it to ``None``, and with it
    ``None`` a column the firm's mapping cannot populate prints a confident
    ``0.00``: ``ensure_gross_side_carriers`` injects an all-null column and
    ``sum`` returns 0.0 over it, not null. ``decompose_cell`` then returns a
    full waterfall that RECONCILES — and the fabricated money lands in
    **``measurement``**, not in a population term, because their side prints
    ``0.0`` for the very same keys. Measured on this slice's own integration
    fixture with the gross components dropped: C 08.03 corporate 0010/0010 shows
    ours 2,820,000 against theirs 0.00, ``reconciles=True``, with 2,190,000
    attributed to ``measurement``. "Same loans, different number" is the single
    worst thing that screen could say — it sends a migration team into the
    calculation hunting a modelling difference that does not exist.

    So the caller passes what the projection returned. ``ours_coverage`` is a
    parameter for the same reason and is normally ``None`` — our own side comes
    off a real pipeline run, not a mapping — but it is threaded rather than
    hardcoded, so an our-side projection would be guarded the moment one exists.
    """
    cached = _CACHE.get(recon_id)
    if cached is not None:
        return cached
    if theirs_coverage is None:
        logger.warning(
            "return-recon compare %s: the legacy side has NO coverage record — every "
            "column its mapping cannot populate will read as a measured figure, and an "
            "injected all-null column sums to 0.00",
            loggable(recon_id),
        )
    recon = build_recon(
        ours,
        theirs,
        template_ids,
        ours_coverage=ours_coverage,
        theirs_coverage=theirs_coverage,
    )
    while len(_CACHE) >= _CACHE_LIMIT:
        evicted = next(iter(_CACHE))
        del _CACHE[evicted]
        logger.info("return-recon compare cache full — evicted %s", evicted)
    _CACHE[recon_id] = recon
    return recon


def cached_comparison(recon_id: str) -> ReturnRecon | None:
    """The memoised comparison for *recon_id*, or ``None``. NEVER builds one.

    The read-only half of ``build_comparison``, for a caller that wants to
    *display* a comparison that already exists but must not pay for one that
    does not. The loan forensic's placement panel is that caller: generating
    both sides costs ~1.1 s at 10,000 exposures and ~4.9 s at 100,000 — growing
    linearly, so ~40 s at the 1M scale this project benchmarks — against a 20 ms
    page, and it is reached cold from a bookmarked URL or an explorer drill, not
    only from the compare page. It shows an offer to build instead.

    **A getter, deliberately, rather than an ``is_cached`` predicate.** A
    predicate makes the caller write "check, then ``build_comparison``", and
    those are two lookups with a gap: this memo evicts at ``_CACHE_LIMIT``
    entries, and sync FastAPI endpoints run on a threadpool, so a concurrent
    request can evict between them and the caller silently pays the build it
    checked in order to avoid. Returning the object closes that gap — one
    lookup, and what you tested is what you hold.

    What it still does not promise: the entry may be evicted the moment after
    this returns. That costs nothing but a rebuild on the next request, because
    the returned ``ReturnRecon`` is a live object the caller already holds — an
    evicted comparison is not a stale one. There is no reading of it that yields
    a WRONG panel, only a later one.
    """
    return _CACHE.get(recon_id)


def clear_comparison_cache() -> None:
    """Drop every memoised comparison (test hook; also frees the frames)."""
    _CACHE.clear()


@dataclass(frozen=True)
class ComparisonInputs:
    """The two sides of a reconciliation, each WITH its coverage record.

    The coverages travel with the sources rather than being fetched at the call
    site, because a call site that forgets one silently disarms the false-zero
    guard — see ``build_comparison``. ``reason`` is non-empty exactly when the
    compare cannot run.

    ``ours_coverage`` is ``None`` today and is threaded anyway: our own side is
    the sealed output of a real pipeline run, so it has no mapping and nothing
    to be unable to supply. It is a field rather than a hardcoded ``None`` at
    the call site so that an our-side projection — comparing two extracts, say —
    would be guarded the day one exists, instead of silently unguarded.
    """

    ours: ResultsSource | None
    theirs: ResultsSource | None
    theirs_coverage: LedgerCoverage | None
    reason: str
    ours_coverage: LedgerCoverage | None = None

    @property
    def comparable(self) -> bool:
        """Whether both sides are present and on the same framework."""
        return self.ours is not None and self.theirs is not None and not self.reason


def comparison_inputs(response: ReconciliationResponse) -> ComparisonInputs:
    """The two sides of a reconciliation, or the reason there is only one.

    A reconciliation whose mapping was too thin to project carries no legacy
    ledger at all; the page must then say so with the remedy rather than 500.
    """
    ours = response.calculation
    theirs = response.legacy_ledger
    coverage = response.legacy_ledger_coverage
    if ours is None:
        return ComparisonInputs(None, None, coverage, _NO_CALCULATION)
    if theirs is None:
        return ComparisonInputs(None, None, coverage, _NO_LEDGER)
    if ours.framework != theirs.framework:
        logger.warning(
            "return-recon compare: framework mismatch, ours=%s theirs=%s",
            ours.framework,
            theirs.framework,
        )
        return ComparisonInputs(None, None, coverage, _FRAMEWORK_MISMATCH)
    if coverage is None:
        logger.warning(
            "return-recon compare: the legacy ledger carries no coverage record; "
            "every column its mapping cannot populate will read as a measured figure"
        )
    return ComparisonInputs(ours, theirs, coverage, "")


# =============================================================================
# The picker
# =============================================================================


def template_options(
    recon: ReturnRecon, coverage: LedgerCoverage | None = None
) -> tuple[TemplateOption, ...]:
    """Every scoped template, labelled for the run's framework, with its sheets.

    A template neither side emitted is omitted. A template the legacy mapping
    cannot reach at all is still offered — with ``reachable`` false and the
    blocking columns named, because "map these three columns" is an answer and a
    silently missing template is not.

    A REACHABLE template their BOOK has no exposures for is a different answer
    again, and is labelled as one: nothing is broken and nothing is to be
    mapped. Reachability is decided on ``reachable_templates``, never on
    ``populated_templates`` — conflating them tells an all-standardised firm
    that its mapping is defective because it has no IRB book.
    """
    options: list[TemplateOption] = []
    for template_id in recon.template_ids:
        sheets = _sheets(recon, template_id)
        blocked = _template_block(coverage, template_id)
        populated = _populated(coverage, template_id)
        if not sheets and not blocked and populated is not False:
            continue
        options.append(
            TemplateOption(
                id=template_id,
                label=_template_label(recon, template_id),
                sheets=sheets,
                reachable=not blocked,
                blocked_reason=blocked,
                populated=populated,
                population_note=_population_note(populated),
            )
        )
    return tuple(options)


# =============================================================================
# The grid
# =============================================================================


def sheet_compare(
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    *,
    coverage: LedgerCoverage | None = None,
    materiality: Materiality = DEFAULT_MATERIALITY,
) -> SheetCompare | None:
    """One sheet's ours / theirs / delta grid, its worst cells and its blanks.

    Returns ``None`` when neither side emitted the sheet. Every cell carries its
    two per-side states, so the four kinds of blank stay four kinds of blank;
    ``heat`` is |delta| over the sheet's largest |delta|, and is 0.0 for a cell
    with no delta rather than being invented.
    """
    diff = diff_cells(recon, template_id, sheet)
    if diff.height == 0:
        return None
    names = _row_names(recon, template_id, sheet)
    heads = _column_heads(recon, template_id, sheet, _ordered(diff, "col_ref"))
    head_by_ref = {head.ref: head for head in heads}
    remedies = _remedies(coverage, template_id)
    template_block = _template_block(coverage, template_id)

    deltas = [abs(d) for d in diff.get_column("delta").to_list() if d is not None]
    largest = max(deltas) if deltas else 0.0

    cells: list[CompareCell] = []
    for record in diff.iter_rows(named=True):
        col_ref = str(record["col_ref"])
        row_ref = str(record["row_ref"])
        cells.append(
            _cell(
                record,
                row_name=names.get(row_ref, ""),
                col_name=head_by_ref[col_ref].name if col_ref in head_by_ref else col_ref,
                largest=largest,
                materiality=materiality,
                remedy=remedies.get(col_ref, ""),
                template_block=template_block,
            )
        )

    # Aligned to the header order, with an explicit ABSENT cell wherever the
    # diff emitted no pair at all. ``_sheet_diff`` drops a cell only when BOTH
    # sides are absent, and that is exactly the "missing row is not a zero"
    # case — leaving the gap out would shift every later cell one column left
    # and quietly relabel real figures.
    by_pair = {(cell.row_ref, cell.col_ref): cell for cell in cells}
    rows = tuple(
        CompareRow(
            row_ref=row_ref,
            row_name=names.get(row_ref, ""),
            cells=tuple(
                by_pair.get((row_ref, head.ref))
                or _absent_cell(row_ref, names.get(row_ref, ""), head)
                for head in heads
            ),
        )
        for row_ref in _ordered(diff, "row_ref")
    )

    material = [cell for cell in cells if cell.is_material]
    material.sort(key=lambda cell: abs(cell.delta or 0.0), reverse=True)
    unmeasurable = [cell for cell in cells if not cell.measurable]
    return SheetCompare(
        template_id=template_id,
        template_label=_template_label(recon, template_id),
        sheet=sheet,
        columns=heads,
        rows=rows,
        worst=tuple(material[:WORST_CELLS_LIMIT]),
        unmeasurable=tuple(unmeasurable[:UNMEASURABLE_LIMIT]),
        max_abs_delta=largest,
        material_count=len(material),
        unmeasurable_count=len(unmeasurable),
        cell_count=len(cells),
    )


# =============================================================================
# The migration matrix
# =============================================================================


def migration_groups(
    recon: ReturnRecon, template_id: str, sheet: str | None
) -> tuple[MigrationGroup, ...]:
    """The addressable populations on a sheet, and the columns each serves.

    One group per DISTINCT predicate on the sheet — the unit a cell's population
    is addressed by. They are BASES, not parts: summing across them double-counts
    every substituted leg, so this returns them as separate matrices to pick
    between and never as one.
    """
    served: dict[str, set[str]] = {}
    for side in (recon.ours, recon.theirs):
        frame = _group_columns(side, template_id, sheet)
        for record in frame.iter_rows(named=True):
            key = str(record["predicate_key"])
            served.setdefault(key, set()).add(str(record["col_ref"]))
    return tuple(
        MigrationGroup(predicate_key=key, columns=tuple(sorted(served[key])))
        for key in sorted(served)
    )


def migration_matrix(
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    predicate_key: str,
    *,
    money_column: str = "rwa_final",
) -> MigrationMatrix | None:
    """Our row down, their row across, priced — for ONE predicate group.

    Every leg of the group sits in exactly one matrix cell (``row_migration``
    keys on the reconciliation key and prices each leg once), so the class
    totals below are safe. They are NOT a row-sum of a ``~is_parent_row``
    filter, which over-counts a leg reported under both a parent band and its
    child and loses one entirely on a sheet with no decidable leaf.
    """
    frame = row_migration(recon, template_id, sheet, predicate_key, money_column=money_column)
    if frame.height == 0:
        return None
    our_rows = _axis(frame, "our_row_ref")
    their_rows = _axis(frame, "their_row_ref")
    money = [abs(v) for v in frame.get_column("money").to_list() if v is not None]
    largest = max(money) if money else 0.0

    by_pair: dict[tuple[str, str], MigrationCell] = {}
    for record in frame.iter_rows(named=True):
        our_ref = str(record["our_row_ref"])
        their_ref = str(record["their_row_ref"])
        basis = str(record["movement_basis"])
        value = record["money"]
        by_pair[(our_ref, their_ref)] = MigrationCell(
            our_row_ref=our_ref,
            their_row_ref=their_ref,
            legs=int(record["legs"]),
            money_ours=record["money_ours"],
            money_theirs=record["money_theirs"],
            money=value,
            display=_figure(value),
            basis=basis,
            basis_label=BASIS_LABELS.get(basis, basis),
            is_diagonal=our_ref == their_ref,
            heat=_heat(value, largest),
        )
    grid = tuple(
        tuple(by_pair.get((our_ref, their_ref)) for their_ref in their_rows) for our_ref in our_rows
    )
    groups = {
        group.predicate_key: group.columns for group in migration_groups(recon, template_id, sheet)
    }
    return MigrationMatrix(
        predicate_key=predicate_key,
        columns=groups.get(predicate_key, ()),
        money_column=money_column,
        our_rows=our_rows,
        their_rows=their_rows,
        cells=grid,
        totals=_migration_totals(frame),
        axis_is_partition=bool(frame.get_column("axis_is_partition").to_list()[0]),
    )


# =============================================================================
# The waterfall
# =============================================================================


def explain_cell(  # noqa: PLR0913 - the cell's full address plus its coverage
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
    *,
    coverage: LedgerCoverage | None = None,
    limit: int = CELL_LEGS_LIMIT,
) -> CellExplanation:
    """One cell's four-way waterfall, or the refusal that replaces it.

    A REFUSED cell carries no steps at all, and ``refusal_kind`` says which of
    the four refusals it is — they demand different next actions, and a page
    that renders them alike gives the wrong one three times out of four. See
    ``CellExplanation``.

    Term LABELS are looked up from the names on the returned ``CellTerm``s, not
    from any list of what the terms are believed to be; an unrecognised name
    renders as itself rather than being dropped.

    A cell that decomposes but does NOT reconcile keeps its steps and carries
    ``reconciles=False`` with the residual: the terms explain part of the
    reported delta and the page must say which part.
    """
    decomposition = decompose_cell(recon, template_id, sheet, row_ref, col_ref)
    names = _row_names(recon, template_id, sheet)
    heads = {head.ref: head for head in _column_heads(recon, template_id, sheet, (col_ref,))}
    remedy = _remedies(coverage, template_id).get(col_ref, "")
    predicate_key = _cell_predicate_key(recon, template_id, sheet, row_ref, col_ref)
    parent = _parent_flag(recon, template_id, sheet, row_ref, predicate_key)
    our_legs, our_total = _cell_legs(
        recon.ours, recon, template_id, sheet, row_ref, predicate_key, "ours", limit
    )
    their_legs, their_total = _cell_legs(
        recon.theirs, recon, template_id, sheet, row_ref, predicate_key, "theirs", limit
    )
    kind = _refusal_kind(decomposition)
    unavailable = "unavailable" in (decomposition.ours_state, decomposition.theirs_state)
    return CellExplanation(
        template_id=template_id,
        sheet=sheet,
        row_ref=row_ref,
        row_name=names.get(row_ref, ""),
        col_ref=col_ref,
        col_name=heads[col_ref].name if col_ref in heads else col_ref,
        kind=decomposition.kind,
        metric=decomposition.metric,
        predicate_key=predicate_key,
        row_is_parent=parent,
        parent_note=_parent_note(parent),
        ours=_side_figure(decomposition.ours, decomposition.ours_state, remedy),
        theirs=_side_figure(decomposition.theirs, decomposition.theirs_state, remedy),
        delta=decomposition.delta,
        delta_display=_delta_display(
            decomposition.delta, decomposition.ours_state, decomposition.theirs_state
        ),
        steps=_steps(decomposition),
        refused=not decomposition.decomposable,
        refusal=decomposition.refusal or "",
        refusal_kind=kind,
        refusal_headline=REFUSAL_HEADLINES.get(kind, ""),
        # The mapping remedy travels independently of the refusal KIND, so a
        # coverage-blocked weighted average — refused as non-additive, because
        # that test comes first — still names what to map.
        remedy=remedy if unavailable else "",
        reconciles=decomposition.reconciles,
        residual=decomposition.residual,
        residual_display=_signed(decomposition.residual),
        our_legs=our_legs,
        their_legs=their_legs,
        our_leg_count=our_total,
        their_leg_count=their_total,
    )


# =============================================================================
# Private helpers
# =============================================================================

_NO_LEDGER = (
    "This reconciliation has no legacy ledger, so there is no second side to "
    "compare a return against. The legacy extract is projected into the "
    "reporting ledger from the components your mapping declares — re-run the "
    "reconciliation with the exposure class, approach and the money components "
    "mapped, and the templates below become comparable."
)
_NO_CALCULATION = (
    "This reconciliation carries no calculation results, so our own side of a "
    "return cannot be generated. Re-run the reconciliation."
)
_FRAMEWORK_MISMATCH = (
    "The two sides were produced under different frameworks, so their templates "
    "are not the same templates. Re-run the reconciliation with one framework."
)
_NO_TEMPLATES = "Neither side produced any of the compared templates for this portfolio."


def _cell(  # noqa: PLR0913 - one cell's record plus everything it renders against
    record: Mapping[str, object],
    *,
    row_name: str,
    col_name: str,
    largest: float,
    materiality: Materiality,
    remedy: str,
    template_block: str,
) -> CompareCell:
    """One diff record rendered — with every blank still carrying its reason."""
    ours_state = str(record["ours_state"])
    theirs_state = str(record["theirs_state"])
    status = str(record["status"])
    ours = _as_float(record["ours"])
    theirs = _as_float(record["theirs"])
    delta = _as_float(record["delta"])
    note = ""
    if "unavailable" in (ours_state, theirs_state):
        note = (
            remedy
            or template_block
            or (
                "this side carries none of the cell's metric sources, so its blank "
                "means 'cannot compute' — not zero"
            )
        )
    return CompareCell(
        row_ref=str(record["row_ref"]),
        row_name=row_name,
        col_ref=str(record["col_ref"]),
        col_name=col_name,
        ours=_side_figure(ours, ours_state, remedy),
        theirs=_side_figure(theirs, theirs_state, remedy),
        delta=delta,
        delta_display=_delta_display(delta, ours_state, theirs_state),
        status=status,
        status_label=STATUS_LABELS.get(status, status),
        is_material=materiality.is_material(delta, ours, theirs),
        heat=_heat(delta, largest),
        note=note,
    )


def _absent_cell(row_ref: str, row_name: str, head: ColumnHead) -> CompareCell:
    """A pair neither side emitted. Rendered as ABSENT — never as a zero.

    The diff omits a cell only when both sides are absent, so this is the grid's
    rendering of "this template binds no cell here, or neither side reached it".
    It carries no delta, because there is nothing to subtract.
    """
    blank = _side_figure(None, "absent", "")
    return CompareCell(
        row_ref=row_ref,
        row_name=row_name,
        col_ref=head.ref,
        col_name=head.name,
        ours=blank,
        theirs=blank,
        delta=None,
        delta_display=NO_CELL_DISPLAY,
        status="neither",
        status_label=STATUS_LABELS["neither"],
        is_material=False,
        heat=0.0,
        note="",
    )


def _side_figure(value: float | None, state: str, remedy: str) -> SideFigure:
    """One side's rendering. A non-``figure`` state NEVER renders as a number."""
    glyph, css, title = STATE_DISPLAY.get(state, ("?", "is-absent", "unknown state"))
    if state == "figure":
        return SideFigure(value=value, state=state, display=_figure(value), css=css, title=title)
    detail = f"{title} — {remedy}" if remedy and state == "unavailable" else title
    return SideFigure(value=None, state=state, display=glyph, css=css, title=detail)


def _delta_display(delta: float | None, ours_state: str, theirs_state: str) -> str:
    """The delta glyph. An unavailable side has no delta, and never shows 0.00."""
    if "unavailable" in (ours_state, theirs_state) or delta is None:
        return UNMEASURABLE_DISPLAY
    return _signed(delta)


def _steps(decomposition: CellDecomposition) -> tuple[WaterfallStep, ...]:
    """The waterfall's steps — EMPTY for a refused cell, by construction."""
    if not decomposition.decomposable:
        return ()
    total = sum(abs(term.amount) for term in decomposition.terms)
    return tuple(
        WaterfallStep(
            name=term.name,
            label=TERM_LABELS.get(term.name, term.name),
            amount=term.amount,
            display=_signed(term.amount),
            keys=term.keys,
            share=(abs(term.amount) / total) if total else 0.0,
        )
        for term in decomposition.terms
    )


def _refusal_kind(decomposition: CellDecomposition) -> str:
    """Which of the four refusals this is, or ``""`` when the cell decomposed.

    Classified from the decomposition's OWN kind, metric and per-side states —
    never by matching the refusal prose, which would drift the moment that
    wording changed. The order mirrors ``return_recon._refusal_reason`` exactly,
    so the kind and the reason text can never say different things.
    """
    if decomposition.decomposable:
        return ""
    if decomposition.kind == "unbound":
        return "unbound"
    if decomposition.kind != "rows":
        return "not_row_backed"
    if decomposition.metric != "sum":
        return "non_additive"
    if "unavailable" in (decomposition.ours_state, decomposition.theirs_state):
        return "coverage"
    return "unbound"


def _migration_totals(frame: pl.DataFrame) -> MigrationTotals:
    """Money by movement class. Safe: each leg is in exactly one matrix cell."""

    def total(basis: str, column: str) -> float:
        rows = frame.filter(pl.col("movement_basis") == basis)
        return float(rows.get_column(column).fill_null(0.0).sum()) if rows.height else 0.0

    return MigrationTotals(
        agreed=total("agreed", "money_ours"),
        moved=total("value_driven", "money_ours"),
        ours_only=total("ours_only", "money_ours"),
        theirs_only=total("theirs_only", "money_theirs"),
        undecidable=total("undecidable", "money_ours"),
    )


def _cell_predicate_key(
    recon: ReturnRecon, template_id: str, sheet: str | None, row_ref: str, col_ref: str
) -> str:
    """The ONE membership group a cell reads, or ``""`` when it reads none.

    Resolved through ``CellMembership.columns`` — never guessed from the row.
    Several groups sit on one row (the origin basis and the post-substitution
    basis, plus per-column narrowings), and picking the wrong one is how a
    plausible wrong population reaches the screen.
    """
    for side in (recon.ours, recon.theirs):
        frame = _group_columns(side, template_id, sheet).filter(
            (pl.col("row_ref") == row_ref) & (pl.col("col_ref") == col_ref)
        )
        if frame.height:
            return str(frame.get_column("predicate_key").to_list()[0])
    return ""


def _parent_flag(
    recon: ReturnRecon, template_id: str, sheet: str | None, row_ref: str, predicate_key: str
) -> bool | None:
    """The tri-state hierarchy flag for one group's row, from OUR side first."""
    if not predicate_key:
        return None
    for side in (recon.ours, recon.theirs):
        frame = _membership_rows(side, template_id, sheet, row_ref, predicate_key)
        if frame.height:
            return frame.get_column("is_parent_row").to_list()[0]
    return None


def _parent_note(parent: bool | None) -> str:
    """What the tri-state flag means for anyone tempted to add rows up."""
    if parent is True:
        return (
            "This row is a PARENT: its legs contain another row's in the same "
            "group, so it double-counts against its children. Never add it to "
            "them."
        )
    if parent is None:
        return (
            "Whether this row is a parent is INDISTINGUISHABLE from the data — "
            "another row holds exactly the same legs. Treat it as 'may double "
            "count', never as a leaf."
        )
    return "This row provably contains and duplicates no other row in its group."


def _cell_legs(  # noqa: PLR0913 - the group's full address plus its side and cap
    side: SideView,
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    predicate_key: str,
    label: str,
    limit: int,
) -> tuple[tuple[CellLeg, ...], int]:
    """The legs of the ONE group a cell reads, largest first, capped.

    Scoped to a single ``(row_ref, predicate_key)`` group, which is the only
    grain at which membership legs may be read without double-counting: within
    one group each leg appears exactly once, whereas across groups a substituted
    leg is counted on both bases.
    """
    if not predicate_key:
        return (), 0
    frame = _membership_rows(side, template_id, sheet, row_ref, predicate_key)
    total = frame.height
    if not total:
        return (), 0
    ordered = frame.sort(pl.col("rwa_final").abs(), descending=True, nulls_last=True).head(limit)
    legs = tuple(
        CellLeg(
            key=str(record.get(recon.key_column) or ""),
            exposure_reference=str(record.get("exposure_reference") or ""),
            source_exposure_reference=str(record.get("source_exposure_reference") or ""),
            ead=_as_float(record.get("ead_final")),
            rwa=_as_float(record.get("rwa_final")),
            side=label,
        )
        for record in ordered.iter_rows(named=True)
    )
    return legs, total


def _membership_rows(
    side: SideView, template_id: str, sheet: str | None, row_ref: str, predicate_key: str
) -> pl.DataFrame:
    """One membership group's legs on one side."""
    return side.membership.legs.filter(
        (pl.col("template_id") == template_id)
        & _sheet_filter(sheet)
        & (pl.col("row_ref") == row_ref)
        & (pl.col("predicate_key") == predicate_key)
    )


def _group_columns(side: SideView, template_id: str, sheet: str | None) -> pl.DataFrame:
    """``(row_ref, predicate_key, col_ref)`` for one sheet on one side."""
    return side.membership.columns.filter(
        (pl.col("template_id") == template_id) & _sheet_filter(sheet)
    )


def _sheet_filter(sheet: str | None) -> pl.Expr:
    """Membership's sheet convention: NULL for a single-frame template."""
    return pl.col("sheet").is_null() if sheet is None else pl.col("sheet") == sheet


def _sheets(recon: ReturnRecon, template_id: str) -> tuple[str, ...]:
    """The union of the sheet keys the two sides emitted, in a stable order."""
    keys: list[str] = []
    for side in (recon.ours, recon.theirs):
        for key in sorted(side.frames.get(template_id, {})):
            if key not in keys:
                keys.append(key)
    return tuple(keys)


def _select_template(
    options: tuple[TemplateOption, ...], template_id: str | None
) -> TemplateOption | None:
    """The requested template, else the first with a sheet, else the first."""
    if template_id:
        match = next((option for option in options if option.id == template_id), None)
        if match is not None:
            return match
        logger.info("return-recon compare: unknown template requested — falling back")
    return next((option for option in options if option.sheets), options[0] if options else None)


def _select_group(  # noqa: PLR0913 - the sheet's address plus the two selectors
    groups: tuple[MigrationGroup, ...],
    predicate_key: str,
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    col_ref: str,
) -> str:
    """The group to draw the matrix for: the request, else the selected cell's.

    Falling back to the group serving the MOST published columns keeps the
    default matrix the one most of the sheet reads, rather than an arbitrary
    narrowing (a defaulted-only or off-balance-sheet-only population).
    """
    for group in groups:
        if group.predicate_key == predicate_key:
            return group.predicate_key
    if col_ref:
        for group in groups:
            if col_ref in group.columns:
                return group.predicate_key
    if not groups:
        logger.info(
            "return-recon compare: no membership groups for %s/%s",
            loggable(template_id),
            loggable(sheet),
        )
        return ""
    return max(groups, key=lambda group: (len(group.columns), group.predicate_key)).predicate_key


def _template_label(recon: ReturnRecon, template_id: str) -> str:
    """``"C 08.03 — IRB PD ranges"``, with the code taken from the framework."""
    code = TEMPLATE_CODES.get(template_id, {}).get(recon.framework, "")
    title = _catalogue_title(recon, template_id)
    description = title.split("—", 1)[1].strip() if "—" in title else title
    if not code:
        return title or template_id
    return f"{code} — {description}" if description else code


def _catalogue_title(recon: ReturnRecon, template_id: str) -> str:
    """The catalogue's own title for a template, or ``""`` when it has none."""
    for info in catalog.template_index(_bundle(recon, template_id), None):
        if info.id == template_id:
            return info.title
    return ""


def _column_heads(
    recon: ReturnRecon, template_id: str, sheet: str | None, refs: Sequence[str]
) -> tuple[ColumnHead, ...]:
    """Readable headers for ``refs``, merged over both sides' emitted columns.

    Both sides are consulted because a column emitted on only one of them still
    has a compared cell — falling back to the bare ref would leave that column
    the only unlabelled one on the sheet, which reads as a defect.
    """
    known: dict[str, catalog.ColumnHeader] = {}
    for side in (recon.ours, recon.theirs):
        view = catalog.template_sheet(_bundle(recon, template_id, side), None, template_id, sheet)
        if view is None:
            continue
        for header in view.columns:
            known.setdefault(header.ref, header)
    return tuple(
        ColumnHead(ref=ref, name=known[ref].name, group=known[ref].group)
        if ref in known
        else ColumnHead(ref=ref, name=ref)
        for ref in refs
    )


def _row_names(recon: ReturnRecon, template_id: str, sheet: str | None) -> dict[str, str]:
    """``row_ref -> row_name`` off the FRAMES' own axis columns, ours winning.

    Read from the generated frame rather than from a row-name table, because a
    row emitted on one side only still needs a label — and because the CRR and
    Basel 3.1 row axes differ (C 08.03 is 17 rows against OF 08.03's 18), so any
    literal list here would pin one framework.
    """
    names: dict[str, str] = {}
    for side in (recon.theirs, recon.ours):
        frame = _frame(side, template_id, sheet)
        if frame is None or "row_ref" not in frame.columns or "row_name" not in frame.columns:
            continue
        for record in frame.select("row_ref", "row_name").iter_rows(named=True):
            ref = record["row_ref"]
            if ref is not None:
                names[str(ref)] = str(record["row_name"] or "")
    return names


def _frame(side: SideView, template_id: str, sheet: str | None) -> pl.DataFrame | None:
    """One side's generated sheet frame. ``sheet`` is NULL for a single frame."""
    frames = side.frames.get(template_id, {})
    if sheet is not None:
        return frames.get(sheet)
    return next(iter(frames.values())) if len(frames) == 1 else None


def _bundle(
    recon: ReturnRecon, template_id: str, side: SideView | None = None
) -> COREPTemplateBundle:
    """A catalogue-shaped bundle over frames already generated.

    The catalogue resolves a template's readable column headers from its own
    frozen definitions plus the FRAME's column list, so it needs a bundle. This
    re-wraps the frames the comparison already holds — it never regenerates one.
    """
    sides = (side,) if side is not None else (recon.ours, recon.theirs)
    frames: dict[str, pl.DataFrame] = {}
    for source in sides:
        for key, frame in source.frames.get(template_id, {}).items():
            frames.setdefault(key, frame)
    empty: dict[str, pl.DataFrame] = {}
    return COREPTemplateBundle(
        c07_00=frames if template_id == "c07_00" else empty,
        c08_01=frames if template_id == "c08_01" else empty,
        c08_02=empty,
        c08_03=frames if template_id == "c08_03" else empty,
        framework=recon.framework,
    )


def _remedies(coverage: LedgerCoverage | None, template_id: str) -> dict[str, str]:
    """``col_ref -> what to map`` for the cells the legacy mapping cannot fill."""
    if coverage is None:
        return {}
    out: dict[str, str] = {}
    for entry in coverage.unavailable_cells.get(template_id, ()):
        ref, _sep, reason = entry.partition(":")
        out[ref.strip()] = f"not mapped: {reason.strip()}" if reason.strip() else "not mapped"
    return out


def _populated(coverage: LedgerCoverage | None, template_id: str) -> bool | None:
    """Does their BOOK carry exposures for this template? ``None`` = not measured.

    A separate question from reachability, and deliberately read off
    ``populated_templates`` rather than ``reachable_templates``. ``None`` when
    the projection did not measure the vocabulary — then the question was never
    asked and neither answer may be shown.
    """
    if coverage is None or coverage.populated_templates is None:
        return None
    return template_id in coverage.populated_templates


def _population_note(populated: bool | None) -> str:
    """What an unpopulated template means, in the firm's language.

    Emphatically NOT a mapping problem: an all-standardised firm legitimately
    has no C 08.01, and telling it to map something would send it chasing a fix
    that does not exist.
    """
    if populated is not False:
        return ""
    return (
        "Your mapping supports this template — your book simply has no exposures "
        "of this kind, so there is nothing to report on it and nothing to fix."
    )


def _template_block(coverage: LedgerCoverage | None, template_id: str) -> str:
    """Why the legacy mapping cannot produce a template AT ALL, or ``""``."""
    if coverage is None or template_id in coverage.reachable_templates:
        return ""
    columns = coverage.blocking_columns(template_id)
    if columns:
        return f"your mapping cannot produce this template — map {', '.join(columns)}"
    labels = coverage.blocking_labels(template_id)
    if labels:
        joined = ", ".join(labels)
        return (
            "your mapping cannot produce this template — its approach labels "
            f"({joined}) fall outside the population it reports"
        )
    return "your mapping cannot produce this template"


def _remedy_lines(
    coverage: LedgerCoverage | None, template_id: str | None = None
) -> tuple[str, ...]:
    """The actionable coverage lines to show above a compare.

    ``template_id`` scopes them to the selected template; ``None`` — the
    degraded page, which has no selection — enumerates every scoped template, so
    an analyst with no comparison at all still learns which columns would buy
    one back rather than being told only that something is missing.
    """
    if coverage is None:
        return ()
    scope = (template_id,) if template_id is not None else RECON_TEMPLATE_IDS
    lines: list[str] = []
    for scoped in scope:
        prefix = "" if template_id is not None else f"{scoped}: "
        block = _template_block(coverage, scoped)
        if block:
            lines.append(f"{prefix}{block}")
        for ref, remedy in sorted(_remedies(coverage, scoped).items()):
            lines.append(f"{prefix}column {ref}: {remedy}")
    for name, values in sorted(coverage.unmapped_labels.items()):
        lines.append(f"unmapped {name} value(s): {', '.join(values)}")
    return tuple(lines)


def _axis(frame: pl.DataFrame, column: str) -> tuple[str, ...]:
    """One matrix axis, real rows first and the two sentinels last."""
    refs = sorted({str(value) for value in frame.get_column(column).to_list()})
    real = [ref for ref in refs if ref not in {ABSENT_ROW, UNDECIDABLE_ROW}]
    tail = [ref for ref in (UNDECIDABLE_ROW, ABSENT_ROW) if ref in refs]
    return tuple(real + tail)


def _ordered(frame: pl.DataFrame, column: str) -> tuple[str, ...]:
    """The distinct values of a column, in first-seen order."""
    seen: list[str] = []
    for value in frame.get_column(column).to_list():
        text = str(value)
        if text not in seen:
            seen.append(text)
    return tuple(seen)


def _heat(value: float | None, largest: float) -> float:
    """|value| over the sheet's largest, clamped to ``[0, 1]``. Never invented."""
    if value is None or not largest:
        return 0.0
    return min(1.0, abs(value) / largest)


def _figure(value: float | None) -> str:
    """A reported figure, through the grid's own formatter (0 is not null)."""
    display, _is_null = format_value(value)
    return display


def _signed(value: float | None) -> str:
    """A delta, signed. ``None`` is not a zero and never renders as one."""
    if value is None:
        return UNMEASURABLE_DISPLAY
    if not value:
        return "0"
    magnitude = abs(value)
    if magnitude >= _THOUSAND:
        return f"{value:+,.0f}"
    if magnitude >= 1.0:
        return f"{value:+,.2f}"
    return f"{value:+.4f}"


def _as_float(value: object) -> float | None:
    """A frame value as a float, keeping ``None`` as ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None
