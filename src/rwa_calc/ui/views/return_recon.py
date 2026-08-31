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
5. **The exposures behind a cell are PAIRED, and ranked on what they
   contribute.** One row per comparison key - the exposure, not the leg - with
   both sides on it, ordered by ``|delta|``. Measured on a probe portfolio of
   30 agreeing loans and 7 drivers: two per-side listings ordered on
   ``|rwa_final|`` and capped at 25 each rendered 50 rows against a GBP 221,000
   difference, every one a loan that agreed to the penny, with every driver
   below the cap. Ranking on size answers "which is the biggest loan here",
   which is not the question the page is on.
6. **A side that holds no leg for an exposure says so.** That is a FIFTH kind
   of blank - the sheet is emitted, the column is populatable, the row is
   there, and this one contract is simply not in it - so it gets its own state
   in ``PAIR_STATE_DISPLAY`` rather than being folded into one of the four
   above. An empty cell there reads as agreement and ``0.00`` as a nil holding.
7. **The cap states what it hid.** ``CellPairTable.note`` carries the shown
   rows' money against the whole scope's and the count left off. A silent cap
   on a regulatory comparison is a silent zero by another name, and a refused
   or empty table carries its REASON for the same reason: ``rows == ()`` must
   never be readable as "no contract drives this difference".
8. **One cell's waterfall is not a scope check, and the page says so.**
   ``SheetConservation`` sums one column across the sheet's provable LEAF rows
   (parents, indistinguishable rows and rows with no addressable population are
   excluded and counted, because this axis overlaps and adding it up would
   double-count). A sheet that nets to zero holds the same money on both sides,
   so every difference in that column is a re-arrangement of one population. A
   sheet that does not net rules OUT a moved row — a move contributes to two
   cells of the same sheet with opposite signs — and says nothing on its own
   about which of the two remaining causes it is. Neither fact is derivable from
   a single cell's four-way split, which is a statement about that cell alone.

References:
- Regulation (EU) 2021/451, Annex II: C 07.00, C 08.01, C 08.03, C 08.06
- PRA PS1/26 Annex I/II: OF 07.00, OF 08.01, OF 08.03, OF 08.06
- docs/plans/return-reconciliation.md, Phase 3 (the template view)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.analysis.return_recon import (
    ABSENT_ROW,
    CELL_PAIRS_LIMIT,
    MIGRATION_MONEY_COLUMNS,
    PLACEMENT_ATTRIBUTION,
    RECON_TEMPLATE_IDS,
    TERM_NAMES,
    UNDECIDABLE_ROW,
    build_recon,
    cell_pairs,
    decompose_cell,
    diff_cells,
    migration_legs,
    row_migration,
)
from rwa_calc.observability import loggable
from rwa_calc.reporting import catalog
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.ui.views.report_templates import format_value

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rwa_calc.analysis.legacy_ledger import LedgerCoverage
    from rwa_calc.analysis.return_recon import (
        CellDecomposition,
        CellPair,
        CellPairs,
        LegPlacement,
        MigratedLeg,
        ReturnRecon,
        SideView,
        TermName,
    )
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

#: The pair table's fifth state: this side holds no leg for THIS exposure in
#: this cell. It is not any of the four above - the sheet was emitted, the
#: column is populatable and the row is present; one contract is missing from
#: it - so it renders as a word rather than as a glyph another state could be
#: mistaken for. A blank here reads as agreement and ``0.00`` as a nil holding.
NOT_HELD_STATE = "not_held"

#: The per-side vocabulary of the PAIR table: the four ``CellState`` renderings
#: verbatim, plus ``NOT_HELD_STATE``. Built FROM ``STATE_DISPLAY`` rather than
#: beside it, so the four cell states cannot come to mean one thing in the grid
#: and another two panels down.
PAIR_STATE_DISPLAY: dict[str, tuple[str, str, str]] = {
    **STATE_DISPLAY,
    NOT_HELD_STATE: (
        "not held",
        "is-unheld",
        "this side holds no leg for this exposure in this cell - not a nil value",
    ),
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
    "sheet_placement": "sheet placement — moved sheet",
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

#: Migration-matrix cell classes, and what each one means to a reader. Asserted
#: against ``return_recon.MOVEMENT_BASES`` rather than kept in step by hand: an
#: unlabelled basis renders as its own raw string, which is the quietest way for
#: a new class of finding to reach a screen unexplained.
#:
#: The three ABSENT-bucket classes per side are the point of the vocabulary. The
#: scope wording ("their extract has no such exposure") was applied to every
#: split leg on the sheet, because our ledger reports one exposure as several
#: legs and the matrix's grain is the leg. It now says that only where it is
#: true, which is what makes it worth reading.
BASIS_LABELS: dict[str, str] = {
    "agreed": "same row on both sides",
    "value_driven": "moved row — their value differs from ours",
    "same_base_ours": "we report this exposure as several legs, or on another sheet — their "
    "extract holds it elsewhere on this template, not nowhere",
    "same_base_theirs": "their extract holds this exposure whole, or on another sheet — we "
    "hold it elsewhere on this template, not nowhere",
    "mixed_base_ours": "BOTH: some of these legs sit elsewhere on their template, some are "
    "genuinely not on their side at all — the list below splits them",
    "mixed_base_theirs": "BOTH: some of these legs sit elsewhere on our template, some are "
    "genuinely not on our side at all — the list below splits them",
    "ours_only": "we hold this exposure and their extract does not hold it anywhere on this "
    "template",
    "theirs_only": "their extract holds this exposure and we do not hold it anywhere on this "
    "template",
    "undecidable": "held, but no single provable leaf row — money kept, not placed",
}

#: What the matrix's two sentinel axis buckets are CALLED on the page. A ref with
#: no name beside eighteen that have one reads as a rendering defect, and the
#: bare word "absent" reads as "the exposure is missing" — which is exactly the
#: reading the ``same_base_*`` classes exist to stop.
SENTINEL_ROW_NAMES: dict[str, str] = {
    ABSENT_ROW: "no leg under this key in this population",
    UNDECIDABLE_ROW: "held, but no single provable leaf row",
}

#: The template's regulatory code under each framework. The three scoped
#: templates are one set of generators under both regimes — PS1/26 renames them
#: OF NN.NN — so the picker labels them from the run's OWN framework rather than
#: from the CRR-flavoured catalogue title.
TEMPLATE_CODES: dict[str, dict[str, str]] = {
    "c07_00": {"CRR": "C 07.00", "BASEL_3_1": "OF 07.00"},
    "c08_01": {"CRR": "C 08.01", "BASEL_3_1": "OF 08.01"},
    "c08_03": {"CRR": "C 08.03", "BASEL_3_1": "OF 08.03"},
    "c08_06": {"CRR": "C 08.06", "BASEL_3_1": "OF 08.06"},
}

#: How many worst cells / unmeasurable cells a page lists. The pair table's own
#: cap is ``return_recon.CELL_PAIRS_LIMIT``, imported rather than restated: the
#: cap and the ``hidden_keys`` arithmetic that reports what it hid must be
#: computed against ONE number, and a second copy here would be free to drift
#: from it - a cap that hides more than it admits to is the failure this table
#: exists to close.
WORST_CELLS_LIMIT = 25
UNMEASURABLE_LIMIT = 25

#: How many legs one matrix cell's drill-down lists. Same magnitude as the pair
#: table's cap and reported the same way — what a cap hid is stated, never
#: implied, because a silent cap on a regulatory comparison is a silent zero.
MIGRATION_MOVERS_LIMIT = 25

#: What a placement carrier says when the side holds nothing to say it with.
#: Never blank: a blank beside a populated side reads as "the same as ours".
NO_PLACEMENT = "holds no leg for this exposure anywhere in the template"

#: The label for a pair table showing every cause rather than one of them. Named
#: rather than left blank so the cap note reads the same either way, and so an
#: unrecognised filter that fell back to the whole table SAYS it did.
EVERY_CAUSE = "every cause"

#: A comparison key that resolved to null on every rung of the ladder. Such legs
#: share one bucket and can pair only with each other, so the row is shown and
#: labelled but NOT linked: a loan link on an empty key dead-ends on a page that
#: looks exactly like a missing loan.
UNIDENTIFIED_KEY = "unidentified exposure"

#: Relative slack on the sheet-conservation sum, applied to the summed
#: magnitude. Mirrors ``analysis.return_recon``'s own additivity tolerance:
#: eighteen rows of nine-figure money do not agree to 1e-9 absolute.
_CONSERVATION_RELATIVE = 1e-9

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
    """The matrix's money by movement class. Each leg falls in exactly one.

    NINE classes, not five, and the four added ones carry money that used to be
    reported as scope. ``ours_only`` / ``theirs_only`` now hold only exposures
    the other side does not hold ANYWHERE on the template; an exposure we report
    as several legs, or that the two books put on different sheets, is a
    ``same_base_*`` (or ``mixed_base_*``) figure instead. Measured on the split
    fixture: 100,000 of ``rwa_final`` moved out of each scope class, against two
    books agreeing to the penny.
    """

    agreed: float
    moved: float
    same_base_ours: float
    same_base_theirs: float
    mixed_base_ours: float
    mixed_base_theirs: float
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
class MigrationMover:
    """One LEG behind one matrix cell, with both sides on the same row.

    The unit is the leg, matching the matrix above it. ``base_key`` is the
    exposure the leg was split from, so a split is visible as such rather than
    inferred from a naming convention, and ``split`` is true where the two
    differ.

    ``ours`` / ``theirs`` are ``SideFigure``s over ``PAIR_STATE_DISPLAY``, so a
    side holding no leg under this key renders the explicit NOT-HELD state —
    never blank (which reads as agreement) and never ``0.00`` (a nil holding).

    ``same_base`` is the per-leg fact the cell's own label aggregates, and it is
    published per row because a ``mixed_base_*`` cell holds both kinds at once:
    the label says "both", and this column is what says WHICH.
    """

    key: str
    key_display: str
    identified: bool
    base_key: str
    split: bool
    ours: SideFigure
    theirs: SideFigure
    same_base: bool
    same_base_note: str


@dataclass(frozen=True)
class MigrationMovers:
    """The legs behind one ``(our row, their row)`` cell, named and priced.

    THE ROW NAMES ARE THE FINDING. "0.15 to <0.25" against "0.25 to <0.50" IS
    the band boundary crossed, read straight off the matrix's own axis labels —
    so this panel states what moved and where to without quoting a PD at all.
    That is not modesty: ``reporting/membership.py::_LEG_COLUMNS`` publishes two
    identity columns, three placement carriers and two money columns and no PD,
    so quoting one would mean widening ``MEMBERSHIP_SCHEMA``.

    ``note`` is never empty and states which of three cases the table is: a cap
    that hid rows, a complete list, or a pair no leg occupies. An empty table
    that does not say why can be read as "nothing moved here", which for a
    hand-edited URL naming the wrong pair would be false.

    ``attribution`` is ``return_recon.PLACEMENT_ATTRIBUTION`` verbatim and must
    be rendered beside the list, for exactly the reason the matrix carries it:
    both sides are banded by our generators from each side's own value, so a
    move is VALUE-driven by construction and this list is not evidence about
    their banding RULE.
    """

    our_row_ref: str
    our_row_name: str
    their_row_ref: str
    their_row_name: str
    basis: str
    basis_label: str
    money_column: str
    rows: tuple[MigrationMover, ...]
    shown: int
    total: int
    hidden: int
    note: str
    attribution: str = PLACEMENT_ATTRIBUTION


@dataclass(frozen=True)
class WaterfallStep:
    """One signed cause of a cell delta, and the exposures under it.

    ``keys`` is the term's POPULATION and ``drivers`` the subset whose own delta
    is not zero. They are different questions and the gap is not cosmetic:
    ``measurement`` holds every key BOTH sides report, agreeing ones included,
    so a cell of 35 shared exposures behind a difference driven by 4 reads 35 in
    one column and 4 in the other. Showing only the first invites "35 exposures
    are wrong"; showing only the second loses the term's scope.

    ``selected`` is whether the pair table below is currently filtered to this
    cause. It is the join between the two halves of the panel.
    """

    name: str
    label: str
    amount: float
    display: str
    keys: int
    drivers: int
    share: float
    selected: bool = False


@dataclass(frozen=True)
class PairRow:
    """One EXPOSURE behind a cell delta, with both sides on the same row.

    Replaces two independently-ranked per-side leg listings, which could not
    show that a row on one list and a row on the other were the same contract.

    ``ours`` and ``theirs`` are ``SideFigure``s over ``PAIR_STATE_DISPLAY``, so
    a side that holds no leg for this exposure renders as an explicit fifth
    state - never blank (which reads as agreement) and never ``0.00`` (which
    reads as a nil holding). ``delta`` is the SIGNED contribution published by
    ``analysis.return_recon.CellPair``, not a subtraction of the two fields: a
    one-sided key contributes its whole money with that side's sign.

    ``identified`` is false for a key that resolved to null on every rung of the
    comparison ladder. Those keys share one bucket and can pair only with each
    other, so the row is shown and labelled but NOT linked - a loan link built
    on an empty key dead-ends on a page that looks like a missing loan.
    """

    key: str
    key_display: str
    identified: bool
    term: str
    term_label: str
    ours: SideFigure
    theirs: SideFigure
    delta: float
    delta_display: str
    placement: str


@dataclass(frozen=True)
class CellPairTable:
    """The exposures behind one cell, ranked - or the reason there are none.

    ``note`` is load-bearing and is never empty. When rows were capped it states
    what the cap hid ("the 25 shown carry X of the Y difference; N more carry
    Z"); when there are no rows at all it says WHY, so an empty table can never
    be read as "no contract drives this difference". A silent cap on a
    regulatory comparison is a silent zero by another name.

    ``refused`` mirrors the cell's own refusal verbatim from
    ``analysis.return_recon.CellPairs.refusal``, which is the string
    ``decompose_cell`` produced rather than a re-derivation - so the waterfall's
    refusal and this table's can never say different things.
    """

    term: str
    term_label: str
    rows: tuple[PairRow, ...]
    shown_delta: float
    shown_display: str
    total_delta: float
    total_display: str
    hidden_keys: int
    hidden_delta: float
    hidden_display: str
    keys: int
    limit: int | None
    refused: bool
    refusal: str
    note: str

    @property
    def filtered(self) -> bool:
        """Whether one cause is selected rather than the whole cell."""
        return bool(self.term)


@dataclass(frozen=True)
class SheetConservation:
    """Whether one column nets to zero across the WHOLE sheet.

    A single cell's four-way split is a statement about that cell. It cannot say
    whether the sheet holds the same money on both sides, and the two findings
    demand different work: a sheet that NETS has one population arranged
    differently, so every cell difference in the column is a re-arrangement and
    the migration matrix is where to look.

    What a NON-netting sheet proves, exactly and no more: a leg that moved row
    cannot produce it, because a move contributes to two cells of the same sheet
    with opposite signs and cancels. It does NOT prove a scope gap on its own —
    measured on the probe portfolio, a leaf total of +11,000 was 3,000 of money
    one side did not hold and 8,000 of money both sides held and valued
    differently. Which of the two it is comes from the per-cell split, not from
    here; this line's job is to rule the move OUT.

    Summed over PROVABLE LEAF rows only. This row axis is hierarchical - a PD
    band row is contained in its parent's - so summing every row double-counts
    every leg reported under both. ``excluded_rows`` counts what was left out
    (a parent, a row indistinguishable from another, or a row with no
    addressable population) and is published rather than dropped, because
    "excluded" must never be readable as "none".

    ``decidable`` is false when a leaf row in this column is not measurable on
    one side, or when there is no provable leaf row at all. A total built over
    part of a column is not a statement about the column, and reporting one as
    if it were is how a mapping gap passes for a tie-out.

    Not built at all for a NON-ADDITIVE column — an average, a mean, a ratio, a
    count. A sheet total is a sum, and a sum down a column of averages is a
    number with no referent. See ``sheet_conservation``.
    """

    col_ref: str
    col_name: str
    delta: float | None
    display: str
    conserves: bool
    decidable: bool
    leaf_rows: int
    excluded_rows: int
    unmeasurable_rows: int
    note: str


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

    ``pairs`` is the drill-down and ``conservation`` the panel's one statement
    about the SHEET. Both are always present - a refused cell gets a pair table
    carrying the refusal rather than no table at all, because a page that simply
    omits the section leaves "no contract drives this difference" as the only
    available reading.
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
    pairs: CellPairTable
    conservation: SheetConservation | None
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
    movers: MigrationMovers | None = None
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
    term: str = "",
    predicate_key: str = "",
    money_column: str = "rwa_final",
    moved_from: str = "",
    moved_to: str = "",
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

    ``term`` narrows the cell's pair table to one waterfall cause, which is what
    a click on a waterfall row does. An unrecognised one falls back to the whole
    table the same way, and the page states which filter it is showing - a wider
    table silently standing in for a narrower one is the only way this fallback
    could mislead.

    ``moved_from`` / ``moved_to`` are one cell of the migration matrix, which is
    what a click on that matrix sends. BOTH are required — a half-named pair is
    not a cell — and an unknown pair renders the empty panel WITH its reason
    rather than nothing at all, so a hand-edited URL cannot look like a matrix
    cell nobody's exposures reached.
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
    movers = (
        migration_movers(recon, selected.id, chosen_sheet, matrix, moved_from, moved_to)
        if matrix is not None and moved_from and moved_to
        else None
    )
    explanation = (
        explain_cell(
            recon, selected.id, chosen_sheet, row_ref, col_ref, coverage=coverage, term=term
        )
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
        movers=movers,
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


def migration_movers(  # noqa: PLR0913 - the sheet's address plus the matrix and the pair
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    matrix: MigrationMatrix,
    our_row_ref: str,
    their_row_ref: str,
    *,
    limit: int | None = MIGRATION_MOVERS_LIMIT,
) -> MigrationMovers:
    """The exposures behind ONE cell of the migration matrix, named.

    The panel the matrix was built for and never got: a cell reporting money
    that moved between two rows says WHICH exposures moved, and the two rows'
    own names say what boundary they crossed.

    Everything here comes from ``analysis.return_recon.migration_legs``, which
    filters the very frame ``row_migration`` aggregates into the matrix. This
    function renders; it does not re-derive. A separately-derived listing is how
    the pair table beneath a cell came to show 50 rows of exact agreement behind
    a 221,000 difference, and the matrix would be free to make the same mistake.

    THE MATRIX IS TAKEN AS AN ARGUMENT rather than the group and the price. It
    is on screen already, so passing it costs nothing — and it removes the two
    ways this panel could describe a different question from the one above it: a
    predicate group it was not drawn for, and a money column it was not priced
    on. The movement class is read off the matrix's own cell for the same reason
    (a second derivation of a label is a second chance to disagree with it).

    Built for ANY pair the caller names, including one no leg occupies: the note
    carries the reason, so an empty table is never readable as "nothing moved
    between these rows" when the truth is "that is not a cell".
    """
    legs = migration_legs(
        recon,
        template_id,
        sheet,
        matrix.predicate_key,
        our_row_ref,
        their_row_ref,
        money_column=matrix.money_column,
    )
    shown = legs if limit is None else legs[:limit]
    names = _row_names(recon, template_id, sheet)
    cell = next(
        (
            found
            for row in matrix.cells
            for found in row
            if found is not None
            and found.our_row_ref == our_row_ref
            and found.their_row_ref == their_row_ref
        ),
        None,
    )
    return MigrationMovers(
        our_row_ref=our_row_ref,
        our_row_name=_row_label(names, our_row_ref),
        their_row_ref=their_row_ref,
        their_row_name=_row_label(names, their_row_ref),
        basis=cell.basis if cell else "",
        basis_label=cell.basis_label if cell else "",
        money_column=matrix.money_column,
        rows=tuple(_mover_row(leg) for leg in shown),
        shown=len(shown),
        total=len(legs),
        hidden=len(legs) - len(shown),
        note=_movers_note(len(shown), len(legs) - len(shown)),
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
    term: str = "",
    limit: int | None = CELL_PAIRS_LIMIT,
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

    ``term`` narrows the PAIR TABLE to one of the waterfall's causes - the join
    between the two halves of the panel - and is echoed on every step as
    ``selected``. It never narrows the waterfall itself: the steps are the whole
    cell's, so a filtered table is always read against the full split.

    The pair table and the waterfall come out of ONE pass in
    ``analysis.return_recon`` (``_decompose``), so a cause's amount and the rows
    beneath it cannot disagree. ``conservation`` is the panel's one statement
    about the sheet rather than the cell, and it is computed for every cell
    including a refused one: a cell nobody can decompose sits on a sheet whose
    population is still a question worth answering.
    """
    decomposition = decompose_cell(recon, template_id, sheet, row_ref, col_ref)
    names = _row_names(recon, template_id, sheet)
    heads = {head.ref: head for head in _column_heads(recon, template_id, sheet, (col_ref,))}
    remedy = _remedies(coverage, template_id).get(col_ref, "")
    predicate_key = _cell_predicate_key(recon, template_id, sheet, row_ref, col_ref)
    parent = _parent_flag(recon, template_id, sheet, row_ref, predicate_key)
    selected = _selected_term(term)
    pairs = _pair_table(recon, template_id, sheet, row_ref, col_ref, term=selected, limit=limit)
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
        steps=_steps(decomposition, selected),
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
        pairs=pairs,
        conservation=sheet_conservation(recon, template_id, sheet, decomposition),
    )


def sheet_conservation(
    recon: ReturnRecon, template_id: str, sheet: str | None, cell: CellDecomposition
) -> SheetConservation | None:
    """Whether one column nets to zero across the whole sheet's LEAF rows.

    Takes the CELL rather than a bare column ref so the column and the
    additivity test cannot come apart: a sheet total is a SUM, and summing a
    weighted average, a mean, a ratio or a count down a column of rows produces
    exactly the fabricated number ``decompose_cell`` refuses to produce for the
    same reason. Measured before this guard existed: C 08.03 col 0050, an
    exposure-weighted average PD, reported "the sheet total is +0.0000" and
    "column 0050 NETS across this sheet".

    ``None`` therefore means one of two things, and both are honest refusals
    rather than verdicts: the column is not an additive money column, or neither
    side publishes it on this sheet. Neither is "it nets".

    Summed over provable leaves only, because this row axis is hierarchical: a
    PD band row is contained in its parent's, so a sum over every row
    double-counts every leg reported under both. Rows excluded for that reason
    (or for having no addressable population at all) are COUNTED into
    ``excluded_rows``, and a leaf that either side cannot measure makes the
    whole column ``decidable=False`` rather than being quietly summed as zero -
    a total over part of a column is not a statement about the column.

    See ``SheetConservation`` for why the page needs this at all: one cell's
    four-way split says nothing about whether the sheet holds the same money on
    both sides, and the two findings send an analyst to different places.
    """
    if cell.kind != "rows" or cell.metric != "sum":
        return None
    col_ref = cell.col_ref
    frame = diff_cells(recon, template_id, sheet).filter(pl.col("col_ref") == col_ref)
    if not frame.height:
        return None
    total = 0.0
    magnitude = 0.0
    leaves = excluded = unmeasurable = 0
    for record in frame.iter_rows(named=True):
        row_ref = str(record["row_ref"])
        group = _cell_predicate_key(recon, template_id, sheet, row_ref, col_ref)
        if _parent_flag(recon, template_id, sheet, row_ref, group) is not False:
            excluded += 1
            continue
        leaves += 1
        delta = _leaf_delta(record)
        if delta is None:
            unmeasurable += 1
            continue
        total += delta
        magnitude += abs(delta)
    decidable = leaves > 0 and unmeasurable == 0
    conserves = decidable and abs(total) <= max(_ZERO_DELTA, magnitude * _CONSERVATION_RELATIVE)
    heads = _column_heads(recon, template_id, sheet, (col_ref,))
    return SheetConservation(
        col_ref=col_ref,
        col_name=heads[0].name if heads else col_ref,
        delta=total if decidable else None,
        display=_signed(total) if decidable else UNMEASURABLE_DISPLAY,
        conserves=conserves,
        decidable=decidable,
        leaf_rows=leaves,
        excluded_rows=excluded,
        unmeasurable_rows=unmeasurable,
        note=_conservation_note(
            col_ref=col_ref,
            delta=total,
            decidable=decidable,
            conserves=conserves,
            leaves=leaves,
            excluded=excluded,
            unmeasurable=unmeasurable,
        ),
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


def _steps(
    decomposition: CellDecomposition, selected: TermName | None
) -> tuple[WaterfallStep, ...]:
    """The waterfall's steps — EMPTY for a refused cell, by construction.

    ``selected`` marks the step the pair table is currently filtered to. It does
    NOT filter the steps: a narrowed table read against a narrowed waterfall
    would lose the one thing that makes the number legible, which is the size of
    this cause against the other four.
    """
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
            drivers=term.differing_keys,
            share=(abs(term.amount) / total) if total else 0.0,
            selected=term.name == selected,
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
        same_base_ours=total("same_base_ours", "money_ours"),
        same_base_theirs=total("same_base_theirs", "money_theirs"),
        mixed_base_ours=total("mixed_base_ours", "money_ours"),
        mixed_base_theirs=total("mixed_base_theirs", "money_theirs"),
        ours_only=total("ours_only", "money_ours"),
        theirs_only=total("theirs_only", "money_theirs"),
        undecidable=total("undecidable", "money_ours"),
    )


def _mover_row(leg: MigratedLeg) -> MigrationMover:
    """One leg of a matrix cell rendered — an absent side kept visibly absent."""
    identified = bool(leg.key)
    base = leg.base_key or ""
    return MigrationMover(
        key=leg.key or "",
        key_display=leg.key if identified and leg.key else UNIDENTIFIED_KEY,
        identified=identified,
        base_key=base,
        split=bool(base) and base != leg.key,
        ours=_pair_side(leg.money_ours),
        theirs=_pair_side(leg.money_theirs),
        same_base=leg.same_base,
        same_base_note=_same_base_note(leg),
    )


def _same_base_note(leg: MigratedLeg) -> str:
    """What this ONE leg's base test found — the question a mixed cell raises.

    Blank where the question does not arise (both sides hold the leg in this
    group), and otherwise one of the two answers spelt out. Never blank on an
    absent leg: a blank in that column beside a populated one reads as "the same
    as the row above", which is the one thing it must not say in a mixed cell.
    """
    if ABSENT_ROW not in (leg.our_row_ref, leg.their_row_ref):
        return ""
    if leg.same_base:
        return f"the other side holds {leg.base_key} elsewhere on this template"
    return "the other side does not hold this exposure anywhere on this template"


def _movers_note(shown: int, hidden: int) -> str:
    """What the list shows and what it does not. NEVER empty.

    Three different statements and the page must not render them alike: a pair
    no leg occupies (most of a cross-tabulation), a complete list, and a capped
    one. The last is why this exists — an unstated cap hides exposures exactly
    as a silent zero hides money.
    """
    if not shown and not hidden:
        return (
            "No leg sits in this cell of the matrix. Most of a cross-tabulation is "
            "empty — this is our whole row axis against theirs — so this is 'not a "
            "cell', not 'nothing moved'."
        )
    if not hidden:
        return f"All {shown:,} leg(s) in this cell are shown."
    return (
        f"{shown:,} of {shown + hidden:,} leg(s) in this cell are shown, ranked on their "
        f"own money; {hidden:,} more are not on this page."
    )


def _row_label(names: Mapping[str, str], row_ref: str) -> str:
    """A row's name for the movers panel, sentinels included.

    The two sentinel buckets have no template row and therefore no name, and a
    ref rendered bare beside eighteen named ones reads as a defect. Falls back to
    the ref itself for a row neither side emitted a name for.
    """
    if row_ref in SENTINEL_ROW_NAMES:
        return SENTINEL_ROW_NAMES[row_ref]
    return names.get(row_ref, row_ref)


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


def _selected_term(term: str) -> TermName | None:
    """The requested waterfall filter, or ``None`` for every cause.

    An unrecognised term falls back to the WHOLE table rather than raising.
    ``cell_pairs`` rejects one with a ``ValueError`` — correctly, because
    filtering to an empty table is a silent zero — but a hand-edited URL must
    render the default view rather than 500, exactly as an unknown template or
    sheet does. The fallback is logged, and the page names the filter it is
    showing, so a wider table cannot pass for the narrower one it replaced.
    """
    if not term:
        return None
    match = next((name for name in TERM_NAMES if name == term), None)
    if match is None:
        logger.info("return-recon compare: unknown waterfall cause requested — showing all")
    return match


def _pair_table(  # noqa: PLR0913 - the cell's full address plus the filter and cap
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
    *,
    term: TermName | None,
    limit: int | None,
) -> CellPairTable:
    """One row per EXPOSURE behind a cell, ranked on what each contributes.

    Everything here — the pairing, the ranking, the cap arithmetic and the
    refusal — comes from ``analysis.return_recon.cell_pairs``, which derives it
    from the same classified record set the waterfall aggregates. This function
    renders; it does not re-derive, because a second reader of membership is how
    the waterfall and the listing beneath it came to disagree in the first place.
    """
    table = cell_pairs(recon, template_id, sheet, row_ref, col_ref, limit=limit, term=term)
    label = TERM_LABELS.get(term or "", EVERY_CAUSE) if term else EVERY_CAUSE
    return CellPairTable(
        term=term or "",
        term_label=label,
        rows=tuple(_pair_row(pair) for pair in table.pairs),
        shown_delta=table.shown_delta,
        shown_display=_signed(table.shown_delta),
        total_delta=table.total_delta,
        total_display=_signed(table.total_delta),
        hidden_keys=table.hidden_keys,
        hidden_delta=table.hidden_delta,
        hidden_display=_signed(table.hidden_delta),
        keys=table.keys,
        limit=limit,
        refused=table.refusal is not None,
        refusal=table.refusal or "",
        note=_pair_note(table, label),
    )


def _pair_row(pair: CellPair) -> PairRow:
    """One pair rendered — with an absent side kept visibly absent."""
    identified = bool(pair.key)
    return PairRow(
        key=pair.key or "",
        key_display=pair.key if identified and pair.key else UNIDENTIFIED_KEY,
        identified=identified,
        term=pair.term,
        term_label=TERM_LABELS.get(pair.term, pair.term),
        ours=_pair_side(pair.ours),
        theirs=_pair_side(pair.theirs),
        delta=pair.delta,
        delta_display=_signed(pair.delta),
        placement=_placement_note(pair.ours_placement, pair.theirs_placement),
    )


def _pair_side(value: float | None) -> SideFigure:
    """One side of a pair. ``None`` is NOT HELD — never blank, never ``0.00``."""
    state = "figure" if value is not None else NOT_HELD_STATE
    glyph, css, title = PAIR_STATE_DISPLAY[state]
    if value is None:
        return SideFigure(value=None, state=state, display=glyph, css=css, title=title)
    return SideFigure(value=value, state=state, display=_figure(value), css=css, title=title)


def _pair_note(table: CellPairs, label: str) -> str:
    """What the table shows and what it does not. NEVER empty.

    The four cases are four different statements and the page must not render
    them alike: a refusal (there is no population to pair), an empty population
    (there is one and this cause holds none of it), a complete table, and a
    capped one. The last is the reason this exists — an unstated cap on a
    regulatory comparison hides money exactly as a silent zero does.
    """
    if table.refusal is not None:
        return (
            "No exposures are paired for this cell, and that is a REFUSAL rather than "
            f"an empty population: {table.refusal}"
        )
    if not table.pairs:
        return (
            f"No exposure falls under {label} for this cell. That is an empty population "
            "rather than an unanswered question — the cell's other causes still hold "
            "theirs, and the waterfall above prices them."
        )
    shown = len(table.pairs)
    if not table.hidden_keys:
        return (
            f"All {shown:,} exposure(s) under {label} are shown, and together they carry "
            f"{_signed(table.shown_delta)} — the whole of this cause's "
            f"{_signed(table.total_delta)}."
        )
    return (
        f"The {shown:,} shown carry {_signed(table.shown_delta)} of the "
        f"{_signed(table.total_delta)} under {label}; {table.hidden_keys:,} further "
        f"exposure(s) carry {_signed(table.hidden_delta)} and are not on this page."
    )


def _leaf_delta(record: Mapping[str, object]) -> float | None:
    """One leaf cell's contribution to the sheet total, or ``None`` for none.

    A separate function with one caller on purpose. "This cell cannot be
    measured, so the column's total is not a statement about the column" is the
    decision that stands between a partial sum and a confident one, and a
    partial sum reads exactly like a complete one — so the decision has to be
    isolatable, not a condition buried in a loop.

    Both limbs are needed and neither implies the other: an ``unmeasurable``
    status is the coverage guard's verdict, and a NULL delta is what
    ``cell_diff`` publishes for it. Never a zero: filling one here is the
    banned Float null-fill, and it would turn "nobody can say" into "they agree".
    """
    if str(record["status"]) == "unmeasurable":
        return None
    return _as_float(record["delta"])


def _placement_note(ours: LegPlacement, theirs: LegPlacement) -> str:
    """Where each side put this exposure, as one line."""
    return f"ours — {_placement_side(ours)}; theirs — {_placement_side(theirs)}"


def _placement_side(placement: LegPlacement) -> str:
    """One side's placement, with each MISSING carrier naming what is missing.

    ``row_refs`` is scoped to the cell's own sheet while the other four are
    template-wide (``LegPlacement``), so "no row on this sheet" beside a present
    class is not a contradiction — it is precisely the shape of a leg they put
    on another sheet. Each empty carrier is spelt out rather than dropped: a
    blank beside a populated side reads as "the same as ours".
    """
    if not (
        placement.row_refs
        or placement.sheets
        or placement.class_origins
        or placement.approach_origins
        or placement.leg_roles
    ):
        return NO_PLACEMENT
    return " · ".join(
        (
            f"rows {', '.join(placement.row_refs)}"
            if placement.row_refs
            else "no row on this sheet",
            f"sheet {', '.join(placement.sheets)}" if placement.sheets else "no sheet carrier",
            f"class {', '.join(placement.class_origins)}"
            if placement.class_origins
            else "no class carrier",
            f"approach {', '.join(placement.approach_origins)}"
            if placement.approach_origins
            else "no approach carrier",
            f"role {', '.join(placement.leg_roles)}" if placement.leg_roles else "no leg role",
        )
    )


def _conservation_note(  # noqa: PLR0913 - the verdict plus every count behind it
    *,
    col_ref: str,
    delta: float,
    decidable: bool,
    conserves: bool,
    leaves: int,
    excluded: int,
    unmeasurable: int,
) -> str:
    """The sheet verdict in words, with the scope of the sum always stated."""
    scope = (
        f" Summed over {leaves:,} provable leaf row(s); {excluded:,} row(s) excluded as a "
        "parent, as indistinguishable from another row, or as having no addressable "
        "population — this axis overlaps, so adding every row would double-count."
    )
    if not leaves:
        return (
            f"Column {col_ref} has no provable leaf row on this sheet, so no sheet total "
            f"can be stated for it at all.{scope}"
        )
    if not decidable:
        return (
            f"Column {col_ref} cannot be netted across this sheet: {unmeasurable:,} of its "
            "leaf rows are not measurable on one side, so any total would cover part of "
            f"the column and read as if it covered all of it.{scope}"
        )
    if conserves:
        return (
            f"Column {col_ref} NETS across this sheet: the two sides' leaf-row totals are "
            "equal, so nothing entered or left on balance and every difference you find "
            "cell by cell is a re-arrangement of one population. It is a statement about "
            "the TOTAL — exactly offsetting differences would net too — so read it as "
            f"'no net gap' rather than as 'no differences'.{scope}"
        )
    return (
        f"Column {col_ref} does NOT net across this sheet: the two sides' leaf-row totals "
        f"differ by {_signed(delta)}. A leg that merely moved row cannot produce that — a "
        "move nets out across the sheet — so this is money one side does not hold at all, "
        "money the two sides value differently, or both. The per-cell split above is what "
        f"tells those two apart.{scope}"
    )


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
        c08_06=frames if template_id == "c08_06" else empty,
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
