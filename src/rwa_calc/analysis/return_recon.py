"""
Cell-delta decomposition — WHY one template cell differs between two returns.

Pipeline position:
    {sealed aggregator exit, analysis.legacy_ledger.project_legacy_ledger}
        -> COREPGenerator + reporting.membership.cell_membership  (BOTH sides)
        -> return_recon (this module)
        -> the template view inside the reconciliation tab

Key responsibilities:
- Diff every published cell of a scoped template between two ``ResultsSource``
  objects, keeping "emitted on one side only" distinguishable from "zero on
  both" (``cell_diff``).
- Split an ADDITIVE money cell's delta into the four mutually exclusive causes
  the plan names — population, row placement, sheet placement, measurement —
  which sum EXACTLY to that delta, and refuse the cell outright rather than
  present a plausible waterfall when they do not (``decompose_cell``).
- Cross-tabulate one predicate group's legs by our row against their row, so a
  banding difference is priced rather than merely noticed (``row_migration``).

BOTH SIDES ARE THE SAME ENGINE. ``LegacyLedgerSource`` satisfies the same
two-member ``ResultsSource`` protocol as our own results, so each side's
templates come out of one ``COREPGenerator`` and each side's membership out of
one ``cell_membership``. There is no second reporting engine here and none may
be added: the two sides must be free to differ about the DATA and incapable of
differing about what a cell MEANS.

EVERY CELL'S POPULATION IS ADDRESSED BY ITS ``predicate_key``, never by its row.
A template row does not have one population. On C 07.00 and C 08.01 every row
carries several — the origin-basis columns read the obligor's own book, the
post-substitution columns read the guarantor's, and individual columns narrow
further (defaulted, off-balance sheet, CCF bucket, rated). Treating a row as one
population produced measured errors of GBP 540,000, GBP 1,800,000 and GBP
2,000,000 on real cells. So a cell is resolved through
``CellMembership.columns`` on ``(template_id, sheet, row_ref, col_ref)`` and only
then through ``CellMembership.legs``.

THE IDENTITY, AND WHY IT IS EXACT. For an additive money cell with metric column
group ``m``, let ``P_ours`` / ``P_theirs`` be the two sides' populations of that
exact cell and ``A_ours`` / ``A_theirs`` everything the same template holds on
each side. Every key of ``P_ours`` falls in exactly one of four buckets, tested
in this order — also in ``P_theirs`` (measurement), else on their side of the
SAME sheet (row placement), else somewhere else in their template (sheet
placement), else nowhere (population) — and symmetrically for ``P_theirs``. The
four buckets therefore PARTITION each side's population, so::

    delta = sigma_{P_ours} m_ours - sigma_{P_theirs} m_theirs
          = measurement + row placement + sheet placement + population

holds by construction rather than by arithmetic luck. What is NOT guaranteed is
that ``sigma_{P} m`` equals the figure the generator REPORTED — a post-execute
pass can overwrite a cell after the executor runs. That is the whole reason
``CellDecomposition.reconciles`` exists and is scored against the REPORTED
delta: a waterfall that does not add up to the number on the screen is a wrong
answer, and this module says so instead of rendering it.

ROW PLACEMENT HERE IS VALUE-DRIVEN BY CONSTRUCTION — READ NOTHING ELSE INTO IT.
Both sides are banded by OUR generators, from each side's own PD. So a leg
landing in a different row can only mean their PD differs from ours. The other
possibility the plan names — a RULE-driven difference, where the PDs agree but
their engine bands on a different basis (post- vs pre-input-floor; see
``corep/c08.py::_pd_alloc_col``) — is STRUCTURALLY INVISIBLE on this path,
because their extract carries one PD and says nothing about which floor was
applied to it. It becomes visible only from a mapped band/grade label on their
extract or from their filed return. Every result this module returns carries
``PLACEMENT_ATTRIBUTION`` (and the migration matrix a ``movement_basis`` column)
so a consumer cannot read a value-driven matrix as evidence about their banding
rule.

A KNOWN LABELLING LIMIT, RECORDED AS UNVERIFIED. ``_side_keys`` spans every
predicate group on a sheet, which is right for the question it asks ("is this
key anywhere on their sheet?") but means a leg that moves between GROUPS rather
than between rows — their guarantee substitution differs from ours, so the leg
sits in the origin-basis group on one side and the post-substitution group on
the other — is labelled ``row_placement`` rather than something nearer the
truth. The four-way IDENTITY is unaffected: the leg is on the same sheet on both
sides, so the same bucket receives it either way and the terms still sum to the
delta. Only the label misleads. The test fixture here carries no protection
columns, so this case is reasoned about rather than measured; it is stated as an
open limit rather than left for a consumer to discover.

NON-ADDITIVE CELLS ARE REFUSED, NOT DECOMPOSED. The identity above is a
statement about sums. A weighted average, a mean, a ratio, a distinct count and
a first-non-null are none of them additive over a population, so a four-way
split of one would be a fabricated number wearing a waterfall's clothes. The
kind and metric are read off the cell's own binding through
``reporting.lineage.describe_cell`` — never off a hard-coded column list, which
would drift the moment a template gained a column.

A MISSING ROW IS NOT A ZERO, AND THE TWO KINDS OF BLANK ARE NOT EACH OTHER.
``cell_diff`` carries a per-side STATE (``figure`` / ``empty`` / ``unavailable``
/ ``absent``, see ``CellState``) alongside each value plus a ``status`` digest,
and ``delta`` must never be rendered without them. The split that matters:

- An UNEMITTED cell and an EMPTY one both mean "no population here", and an
  empty population is genuinely zero money, so both contribute 0.0 to the delta
  and a figure opposite either is a one-sided finding. Which of the two a
  template produces is a presentation choice, not a fact about the data —
  C 08.03 omits the row, C 07.00 emits it blank — so conflating them with the
  case below silently refuses every one-sided C 07.00 cell. Measured on the
  test portfolio while that bug stood: 996 cells refused, including all 28 of
  the genuinely one-sided ones.
- An UNAVAILABLE cell is the different claim: this side cannot compute the
  figure at all. Reading it as a zero would manufacture the largest delta on the
  sheet. Diffed as ``status = "unmeasurable"`` with a NULL delta, and refused by
  ``decompose_cell``.

AND AN UNAVAILABLE CELL DOES NOT ALWAYS PRINT A BLANK — WHICH IS THE DANGEROUS
CASE. ``COREPGenerator`` calls ``ensure_gross_side_carriers``, which INJECTS an
all-null gross-side column when the frame has neither the sealed carrier nor a
raw source to derive it from; and ``kernel/sums.py::col_sum`` returns null only
for a WHOLLY ABSENT column, summing a present-but-all-null one to **0.0**
(``sums.py:49-50``). So a legacy side that mapped no gross exposure reports a
confident ``0.00`` on C 07.00 col 0010 and C 08.03 cols 0010/0020 — measured, on
a book holding 2,100,000 and 1,500,000 of real gross. Nothing about that figure
is distinguishable from a reported zero by looking at it, and it is the
generator's contract, not something ``analysis/`` can fix.

The defence is ``LedgerCoverage``, which names exactly those cells, and it is
taken as a PARAMETER (``build_recon(..., theirs_coverage=...)``) rather than
reached for, so this module stays pure and the guard stays testable. A cell that
coverage reports as unpopulatable is ``unavailable`` **whatever figure it
prints**, and its printed figure is deliberately not carried onto the diff —
rendering it would put the false zero back on the screen. The same rule applies
to every cell coverage names, not to the gross carriers alone, and to every cell
of a template the mapping cannot produce at all.

WITHOUT THE GUARD THE FALSE ZERO LANDS IN ``measurement``, NOT IN A POPULATION
TERM — measured, and worth naming precisely because the plausible guess is
wrong. Their side prints ``0.0`` for the very SAME keys we hold, so ``key in
theirs`` is satisfied and every leg is classed present-on-both-with-a-different
-value: 2,100,000 of ``measurement`` on the guard's own fixture, 4,500,000
through a real ``project_legacy_ledger``, with all four other terms at ``0.00``.
That is the WORSE of the two wrong answers. ``measurement`` reads as "the same
loans, valued differently", which sends an analyst into the calculation to hunt
a modelling difference that does not exist; a population term would at least
have pointed at scope. Hence the refusal: no waterfall at all beats a confident
one aimed at the wrong half of the problem.

THE GUARD IS OPT-IN, AND THAT IS ITS WEAKNESS. ``build_recon`` WARNS when the
legacy side ``isinstance`` a ``LegacyLedgerSource`` and no coverage was passed,
so the seam is loud however a caller behaves. But an ``isinstance`` tripwire is
necessary and NOT sufficient: a caller that wraps the projection in its own
``ResultsSource`` — which the two-member protocol makes trivial — passes the
check while still reading every false zero as a figure. There is no way to close
that from inside this module, because a coverage record cannot be invented for a
source that never produced one. So a caller supplying a projected legacy side
MUST pass its coverage, and a reviewer should check that at the call site rather
than trusting this warning to have fired.

References:
- Regulation (EU) 2021/451, Annex II: C 07.00, C 08.01, C 08.03
- PRA PS1/26 Annex I/II: OF 07.00, OF 08.01, OF 08.03
- docs/plans/return-reconciliation.md, Phase 4 (the four-way waterfall)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import polars as pl

from rwa_calc.analysis.legacy_ledger import LegacyLedgerSource
from rwa_calc.reporting.cellspec import subset_rows
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.kernel import available_columns, ensure_gross_side_carriers
from rwa_calc.reporting.lineage import LINEAGE_PLANS, describe_cell
from rwa_calc.reporting.membership import MEMBERSHIP_TEMPLATE_IDS, cell_membership

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from rwa_calc.analysis.legacy_ledger import LedgerCoverage
    from rwa_calc.reporting.lineage import CellQuery, _Provider
    from rwa_calc.reporting.membership import CellMembership
    from rwa_calc.reporting.metadata import ResultsSource
    from rwa_calc.reporting.plans import SheetPlan

logger = logging.getLogger(__name__)

#: The templates this slice covers, on both frameworks. Deliberately the same
#: ids ``reporting.membership`` is scoped to — a template with no membership has
#: no addressable populations and so no decomposition, only a diff.
RECON_TEMPLATE_IDS: tuple[str, ...] = MEMBERSHIP_TEMPLATE_IDS

#: The four causes, in waterfall order. Population splits into its two signed
#: halves because "17 exposures they hold and we do not" and "3 we hold and they
#: do not" are different findings that happen to net.
type TermName = Literal[
    "population_ours_only",
    "population_theirs_only",
    "row_placement",
    "sheet_placement",
    "measurement",
]

TERM_NAMES: tuple[TermName, ...] = (
    "population_ours_only",
    "population_theirs_only",
    "row_placement",
    "sheet_placement",
    "measurement",
)

#: Per-side presence of a cell, and the reason for it. The two null cases are
#: split because they are DIFFERENT CLAIMS and conflating them is how a real
#: finding disappears:
#:
#: - ``figure``      — a measured value, zero included.
#: - ``empty``       — emitted with no figure because the population is empty.
#:   C 07.00's row axis is static, so an unpopulated row is emitted null rather
#:   than omitted; on C 08.03 the same fact shows up as ``absent`` instead.
#:   Contributes 0.0 to the delta, because an empty population IS zero money.
#: - ``unavailable`` — this side cannot compute the figure. Either it carries
#:   NONE of the cell's metric sources (``CellQuery.is_source_backed``), or the
#:   side's ``LedgerCoverage`` names the cell as unpopulatable — the latter
#:   INCLUDING cells that print a confident 0.0 off an injected all-null column
#:   (see the module docstring). Never a zero, never decomposed, and the printed
#:   figure is not carried.
#: - ``absent``      — the sheet, row or column was not emitted at all, or the
#:   template binds no cell there.
type CellState = Literal["figure", "empty", "unavailable", "absent"]

#: The digest of the two states. ``unmeasurable`` wins over everything: an
#: unavailable side means the delta is not a number anyone should read.
type DiffStatus = Literal["both", "ours_only", "theirs_only", "neither", "unmeasurable"]

#: The published diff grain. ``sheet`` is null for a single-frame template, so
#: it joins ``CellMembership`` (which uses the same convention) directly.
CELL_DIFF_SCHEMA: dict[str, pl.DataType] = {
    "template_id": pl.String(),
    "sheet": pl.String(),
    "row_ref": pl.String(),
    "col_ref": pl.String(),
    "ours": pl.Float64(),
    "theirs": pl.Float64(),
    "delta": pl.Float64(),
    "ours_state": pl.String(),
    "theirs_state": pl.String(),
    "status": pl.String(),
}

#: The migration matrix's grain and its own metadata columns.
ROW_MIGRATION_SCHEMA: dict[str, pl.DataType] = {
    "template_id": pl.String(),
    "sheet": pl.String(),
    "predicate_key": pl.String(),
    "our_row_ref": pl.String(),
    "their_row_ref": pl.String(),
    "legs": pl.UInt32(),
    "money_ours": pl.Float64(),
    "money_theirs": pl.Float64(),
    "money": pl.Float64(),
    "movement_basis": pl.String(),
    "axis_is_partition": pl.Boolean(),
}

#: The axis bucket for a leg the other side does not hold in THIS group. It
#: therefore mixes a leg missing from their template with one that moved sheet;
#: ``decompose_cell`` is what separates those two. Cannot collide with a COREP
#: row ref, which is always four digits.
ABSENT_ROW = "absent"

#: The axis bucket for a leg this side DOES hold but cannot place on a single
#: template row: every row holding it is a strict parent or an indistinguishable
#: NULL, or it sits in several provable leaves at once. Its money is real and
#: stays in the matrix — dropping it is the measured "total loss" failure, where
#: a ``~is_parent_row`` filter reports 0.00 against a sheet holding millions.
UNDECIDABLE_ROW = "undecidable"

#: The honesty line every result carries. See the module docstring.
PLACEMENT_ATTRIBUTION = (
    "Both sides are banded by our own generators from each side's own PD, so a "
    "row-placement difference is VALUE-driven by construction (their PD differs "
    "from ours). A RULE-driven difference — same PD, different banding basis — "
    "is structurally invisible here and needs their filed return or a mapped "
    "band label. Do not read this as evidence about their banding rule."
)

#: The money carriers ``CellMembership.legs`` publishes, and so the only prices
#: the migration matrix can quote. Anything else would need a second read of the
#: plan frame at a grain the matrix does not have.
MIGRATION_MONEY_COLUMNS: tuple[str, ...] = ("ead_final", "rwa_final")

#: The identity columns membership carries; either is a valid reconciliation
#: join key. ``exposure_reference`` is the default the recon grammar already
#: uses (``recon_registry.LegacyColumnMapping.our_keys``).
KEY_COLUMNS: tuple[str, ...] = ("exposure_reference", "source_exposure_reference")

#: Absolute floor of the additivity tolerance, widened by the cell's own
#: magnitude so a GBP 400m cell is not held to a GBP 0.000001 residual.
_ABS_TOLERANCE = 1e-6
_REL_TOLERANCE = 1e-9

#: Separator for the internal ``(row_ref, predicate_key)`` batching key, matching
#: ``reporting.membership``'s own — ``subset_rows`` needs one flat key.
_SEP = "|"


# =============================================================================
# Results
# =============================================================================


@dataclass(frozen=True)
class CellTerm:
    """One signed cause of a cell delta, with the legs behind it.

    ``amount`` is signed so the terms sum to the delta directly: a population
    the other side holds and we do not enters NEGATIVE, exactly as it reduces
    our figure relative to theirs.
    """

    name: TermName
    amount: float
    keys: int


@dataclass(frozen=True)
class CellDecomposition:
    """One cell's delta, split four ways — or a refusal saying why it is not.

    ``reconciles`` is the deliverable, not a diagnostic: it is ``True`` only
    when the terms sum to the REPORTED delta within tolerance. A consumer that
    renders the waterfall without reading it is rendering an unverified number.
    """

    template_id: str
    sheet: str | None
    row_ref: str
    col_ref: str
    kind: str
    metric: str | None
    ours: float | None
    theirs: float | None
    ours_state: CellState
    theirs_state: CellState
    delta: float | None
    terms: tuple[CellTerm, ...]
    reconciles: bool
    residual: float | None
    refusal: str | None
    attribution: str = PLACEMENT_ATTRIBUTION

    @property
    def decomposable(self) -> bool:
        """Whether the four-way split applies to this cell at all."""
        return self.refusal is None

    @property
    def explained(self) -> float:
        """The sum of the four terms — what the waterfall claims to explain."""
        return sum(term.amount for term in self.terms)

    def amount(self, name: TermName) -> float:
        """One term's signed amount, ``0.0`` when the cell was refused."""
        return next((term.amount for term in self.terms if term.name == name), 0.0)


@dataclass(frozen=True)
class SideView:
    """One side's generated templates, plans and membership, built ONCE.

    Generating a template bundle is expensive, so every entry point in this
    module takes (or builds) exactly one of these per side and reuses it across
    every cell. The memo dictionaries are mutable by design — the dataclass is
    frozen against REBINDING, which is what protects the artifacts; the memos
    only ever gain derived values of those artifacts.
    """

    source: ResultsSource
    results: pl.LazyFrame
    cols: set[str]
    membership: CellMembership
    plans: dict[str, dict[str, SheetPlan]]
    frames: dict[str, dict[str, pl.DataFrame]]
    #: What this side's mapping could NOT supply. ``None`` for our own sealed
    #: results, which have no mapping; a ``LegacyLedgerSource`` always has one,
    #: and without it every false zero it prints is read as a real figure.
    coverage: LedgerCoverage | None = None
    groups: dict[tuple[str, str], dict[str, pl.DataFrame]] = field(default_factory=dict)
    money: dict[tuple[str, str, str, str, tuple[str, ...], bool], dict[str, float]] = field(
        default_factory=dict
    )
    keys: dict[tuple[str, str | None], frozenset[str]] = field(default_factory=dict)
    unpopulatable: dict[str, dict[str, str]] = field(default_factory=dict)
    records: dict[tuple[str, str], dict[str, dict[str, float | None]]] = field(default_factory=dict)
    queries: dict[tuple[str, str, str, str], CellQuery | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ReturnRecon:
    """Both sides of one comparison, generated once and reused.

    Built by ``build_recon``. Hold on to it: the per-cell entry points take it
    rather than two sources precisely so that a screen full of cells costs one
    generation, not one per cell.
    """

    framework: str
    template_ids: tuple[str, ...]
    key_column: str
    ours: SideView
    theirs: SideView


# =============================================================================
# Main entry points
# =============================================================================


def build_recon(  # noqa: PLR0913 - two sides, each with its own coverage record
    ours: ResultsSource,
    theirs: ResultsSource,
    template_ids: Sequence[str] | None = None,
    *,
    key_column: str = "exposure_reference",
    ours_coverage: LedgerCoverage | None = None,
    theirs_coverage: LedgerCoverage | None = None,
) -> ReturnRecon:
    """Generate both sides once: templates, plans and membership.

    Args:
        ours: Our results source (the sealed aggregator exit, normally).
        theirs: Their results source — a ``LegacyLedgerSource`` in production,
            any ``ResultsSource`` here.
        template_ids: Defaults to ``RECON_TEMPLATE_IDS``. An id outside
            ``LINEAGE_PLANS`` is skipped with a WARNING, never guessed at.
        key_column: The reconciliation join key. One of ``KEY_COLUMNS``.
        ours_coverage: What our mapping could not supply. Normally ``None`` —
            our own results come off the sealed pipeline, not a mapping.
        theirs_coverage: The second return value of ``project_legacy_ledger``.
            **Pass it whenever the legacy side is a projection.** Without it
            every cell the mapping could not populate is read as a measured
            figure, including the injected-all-null ``0.00`` on the gross
            columns — see the module docstring. Taken as a parameter rather
            than reached for, so the guard is pure and testable.

    Raises:
        ValueError: If the two sources disagree about the framework (a
            programming error — the caller chose both regimes), or if
            ``key_column`` is not an identity column membership carries.
    """
    if ours.framework != theirs.framework:
        raise ValueError(
            "both sides must be on the same framework, got "
            f"{ours.framework!r} (ours) and {theirs.framework!r} (theirs)"
        )
    if key_column not in KEY_COLUMNS:
        raise ValueError(f"key_column must be one of {KEY_COLUMNS}, got {key_column!r}")
    if theirs_coverage is None and isinstance(theirs, LegacyLedgerSource):
        # The guard is OPT-IN, so an unarmed projection is the one shape that
        # silently reproduces the false zero. Say so loudly rather than trusting
        # every future caller to remember — see the module docstring for why an
        # isinstance tripwire is necessary and NOT sufficient.
        logger.warning(
            "return_recon: the legacy side is a projected ledger but no theirs_coverage was "
            "passed. Every cell its mapping could not populate will be read as a MEASURED "
            "figure — including the gross columns, where an injected all-null column reports "
            "a confident 0.00. Pass the LedgerCoverage that project_legacy_ledger returned"
        )
    requested = tuple(RECON_TEMPLATE_IDS if template_ids is None else template_ids)
    return ReturnRecon(
        framework=ours.framework,
        template_ids=requested,
        key_column=key_column,
        ours=_build_side(ours, requested, key_column, ours_coverage, side="ours"),
        theirs=_build_side(theirs, requested, key_column, theirs_coverage, side="theirs"),
    )


def cell_diff(  # noqa: PLR0913 - the brief's four positional args plus the two coverages
    ours: ResultsSource,
    theirs: ResultsSource,
    template_id: str,
    sheet: str | None = None,
    *,
    ours_coverage: LedgerCoverage | None = None,
    theirs_coverage: LedgerCoverage | None = None,
) -> pl.DataFrame:
    """Every published cell of one template, our figure against theirs.

    One row per ``(sheet, row_ref, col_ref)`` the union of the two sides emits,
    in ``CELL_DIFF_SCHEMA``. ``status`` and the two state columns are what keep
    "emitted on one side only" apart from "zero on both" — see the module
    docstring; a consumer that renders ``delta`` alone has thrown that away.

    Pass ``theirs_coverage`` whenever the legacy side is a projection: a cell it
    could not populate then reads ``unavailable`` with a NULL delta, instead of
    a confident zero minus our real figure.

    ``sheet`` restricts to one sheet key; ``None`` diffs them all. Generates
    both sides, so a caller diffing more than one template should build a
    ``ReturnRecon`` once and call ``diff_cells``.
    """
    recon = build_recon(
        ours,
        theirs,
        [template_id],
        ours_coverage=ours_coverage,
        theirs_coverage=theirs_coverage,
    )
    return diff_cells(recon, template_id, sheet)


def diff_cells(recon: ReturnRecon, template_id: str, sheet: str | None = None) -> pl.DataFrame:
    """``cell_diff`` over an already-built ``ReturnRecon``."""
    provider = _provider(template_id)
    if provider is None:
        return pl.DataFrame(schema=CELL_DIFF_SCHEMA)
    our_frames = recon.ours.frames.get(template_id, {})
    their_frames = recon.theirs.frames.get(template_id, {})
    keys = _ordered_union(our_frames, their_frames)
    if sheet is not None:
        keys = [key for key in keys if key == sheet]
    rows: list[dict[str, object]] = []
    for key in keys:
        rows.extend(
            _sheet_diff(
                recon,
                provider,
                template_id,
                key,
                None if provider.single_frame else key,
            )
        )
    if not rows:
        return pl.DataFrame(schema=CELL_DIFF_SCHEMA)
    return pl.DataFrame(rows, schema=CELL_DIFF_SCHEMA)


def decompose_cell(
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
) -> CellDecomposition:
    """Split one cell's delta into population, row, sheet and measurement.

    Returns a REFUSAL — ``decomposable`` false, ``terms`` empty, ``refusal``
    saying why — for every cell the identity does not apply to: a cell that is
    not row-backed (a formula, a side context, a prior period, a constant), a
    non-additive metric (weighted average, mean, ratio, count, first-non-null),
    an uninstrumented template, and a cell one side reports as ``unavailable``
    — either because it carries none of the cell's metric sources, or because
    that side's ``LedgerCoverage`` names the column as unpopulatable. The second
    case includes cells that print a confident ``0.00``: decomposing one of
    those attributes the WHOLE cell to ``measurement`` (their zero sits on the
    same keys as our figure), which reads as "the same loans, valued
    differently" and is a confident wrong answer aimed at the wrong half of the
    problem — worse than no answer. See the module docstring.

    An EMPTY or unemitted cell IS decomposed: an empty population contributes
    0.0 and is the ordinary shape of a one-sided finding — on C 07.00's static
    row axis it is the ONLY shape one takes.

    Otherwise the four terms are computed and scored against the reported
    delta. ``reconciles`` is ``False`` — with the shortfall in ``residual`` —
    whenever they do not sum to it, which is the case a post-execute pass
    creates by overwriting a cell after the executor ran.
    """
    provider = _provider(template_id)
    if provider is None:
        return _refused(
            template_id,
            sheet,
            row_ref,
            col_ref,
            "unbound",
            None,
            f"{template_id} is "
            "not instrumented: it has no membership and so no addressable populations",
        )
    sheet_key = _sheet_key(recon, template_id, sheet)
    if sheet_key is None:
        return _refused(
            template_id, sheet, row_ref, col_ref, "unbound", None, "sheet is on neither side"
        )
    query = _query(recon.ours, provider, template_id, sheet_key, sheet, row_ref, col_ref) or _query(
        recon.theirs, provider, template_id, sheet_key, sheet, row_ref, col_ref
    )
    if query is None:
        return _refused(
            template_id,
            sheet,
            row_ref,
            col_ref,
            "unbound",
            None,
            "cell is not on this template on either side",
        )

    ours, ours_state = _side_cell(
        recon.ours, provider, template_id, sheet_key, sheet, row_ref, col_ref
    )
    theirs, theirs_state = _side_cell(
        recon.theirs, provider, template_id, sheet_key, sheet, row_ref, col_ref
    )
    refusal = _refusal_reason(query, ours_state, theirs_state)
    if refusal is not None and "unavailable on" in refusal:
        side = recon.ours if ours_state == "unavailable" else recon.theirs
        cause = _coverage_refusal(side, template_id, col_ref)
        if cause is not None:
            refusal = f"{refusal.split(':', 1)[0]}: {cause}"
    if refusal is not None:
        return _refused(
            template_id,
            sheet,
            row_ref,
            col_ref,
            query.kind,
            query.metric,
            refusal,
            ours=ours,
            theirs=theirs,
            ours_state=ours_state,
            theirs_state=theirs_state,
        )

    our_money = _cell_money(
        recon.ours, recon.key_column, template_id, sheet_key, row_ref, col_ref, query
    )
    their_money = _cell_money(
        recon.theirs, recon.key_column, template_id, sheet_key, row_ref, col_ref, query
    )
    key = recon.key_column
    terms = _terms(
        our_money,
        their_money,
        their_all=_side_keys(recon.theirs, key, template_id, None),
        their_sheet=_side_keys(recon.theirs, key, template_id, sheet),
        our_all=_side_keys(recon.ours, key, template_id, None),
        our_sheet=_side_keys(recon.ours, key, template_id, sheet),
    )
    delta = (ours or 0.0) - (theirs or 0.0)
    residual = delta - sum(term.amount for term in terms)
    scale = max(abs(delta), sum(abs(term.amount) for term in terms))
    return CellDecomposition(
        template_id=template_id,
        sheet=sheet,
        row_ref=row_ref,
        col_ref=col_ref,
        kind=query.kind,
        metric=query.metric,
        ours=ours,
        theirs=theirs,
        ours_state=ours_state,
        theirs_state=theirs_state,
        delta=delta,
        terms=terms,
        reconciles=abs(residual) <= max(_ABS_TOLERANCE, _REL_TOLERANCE * scale),
        residual=residual,
        refusal=None,
    )


def row_migration(
    recon: ReturnRecon,
    template_id: str,
    sheet: str | None,
    predicate_key: str,
    *,
    money_column: str = "rwa_final",
) -> pl.DataFrame:
    """Our row against their row, for one predicate group, priced.

    The diagonal is agreement; every off-diagonal cell is money that moved rows,
    and — per ``PLACEMENT_ATTRIBUTION``, restated on every row as
    ``movement_basis = "value_driven"`` — it moved because their PD (or risk
    weight, or whatever the row axis keys) differs from ours, NOT because their
    banding rule does. Legs the other side does not hold in this group land in
    the ``ABSENT_ROW`` bucket on the relevant axis.

    THE AXIS IS BUILT FROM DISTINCT LEGS, NOT FROM A ROW SUM, and that is a
    correctness requirement rather than an implementation note. Summing the rows
    a ``~is_parent_row`` filter leaves behind fails in two silent, measured ways:

    - **Over-count.** Within one group a leg legitimately appears in a parent row
      AND its child, so a row sum counts it twice (and across ``predicate_key``,
      a substituted leg is counted on both bases — measured at 3.00x on C 07.00
      ``retail_other`` and 1.86x on C 08.01 ``corporate``). This function keys on
      the reconciliation key and prices each leg ONCE, so no filter can
      double-count it.
    - **Total loss.** On a sheet where every row of the group is ``True`` or
      ``NULL``, no row is a decidable leaf and the filter is legitimately EMPTY —
      ``0.00`` against real money, on four sheets of the review fixture. So a leg
      that resolves to no single provable leaf row is NOT dropped: it is placed
      in the ``UNDECIDABLE_ROW`` bucket, where its money stays visible and
      labelled ``movement_basis = "undecidable"``.

    The invariant that follows, and which the tests assert as an equality
    against an independently derived figure: **the matrix's money always equals
    the group's distinct-leg total on each side**, whatever the parent flags say.
    ``axis_is_partition`` reports the separate question of whether every leg
    reached a real template row — ``False`` means some money sits in the
    undecidable bucket rather than that any of it was lost or doubled.

    A leg is placed on a row only where ``is_parent_row`` is provably ``False``.
    ``True`` and ``NULL`` are both non-leaf, but only the ``True`` exclusion
    changes any output — see ``_group_legs`` for the measurement and for why the
    single-leaf rule, not the fill direction, is what makes NULL safe.

    Raises:
        ValueError: If ``money_column`` is not a carrier membership publishes.
    """
    if money_column not in MIGRATION_MONEY_COLUMNS:
        raise ValueError(
            f"money_column must be one of {MIGRATION_MONEY_COLUMNS}, got {money_column!r}"
        )
    key = recon.key_column
    ours = _group_legs(recon.ours, key, template_id, sheet, predicate_key, money_column, "ours")
    theirs = _group_legs(
        recon.theirs, key, template_id, sheet, predicate_key, money_column, "theirs"
    )
    if ours.height == 0 and theirs.height == 0:
        logger.info(
            "row_migration: no membership at all for %s/%s/%s — the group holds no legs on "
            "either side (this is an EMPTY group, not a zero)",
            template_id,
            sheet,
            predicate_key,
        )
        return pl.DataFrame(schema=ROW_MIGRATION_SCHEMA)

    partition = not (
        (ours["row_ref"] == UNDECIDABLE_ROW).any() or (theirs["row_ref"] == UNDECIDABLE_ROW).any()
    )
    joined = ours.join(theirs, on=key, how="full", coalesce=True, suffix="_theirs")
    return (
        joined.with_columns(
            # An explicit bucket, not a false zero: the sentinel says "this side
            # does not hold the leg in this group" and is read as such below.
            pl.col("row_ref").fill_null(ABSENT_ROW).alias("our_row_ref"),
            pl.col("row_ref_theirs").fill_null(ABSENT_ROW).alias("their_row_ref"),
        )
        .group_by("our_row_ref", "their_row_ref")
        .agg(
            pl.len().cast(pl.UInt32()).alias("legs"),
            pl.col(money_column).sum().alias("money_ours"),
            pl.col(f"{money_column}_theirs").sum().alias("money_theirs"),
            pl.col(money_column).is_null().all().alias("_no_ours"),
            pl.col(f"{money_column}_theirs").is_null().all().alias("_no_theirs"),
        )
        .with_columns(
            # ``sum`` returns 0.0 for an all-null group, which would render an
            # absent side as a measured zero; restore the null explicitly.
            pl.when(pl.col("_no_ours"))
            .then(None)
            .otherwise(pl.col("money_ours"))
            .alias("money_ours"),
            pl.when(pl.col("_no_theirs"))
            .then(None)
            .otherwise(pl.col("money_theirs"))
            .alias("money_theirs"),
        )
        .with_columns(
            pl.lit(template_id, dtype=pl.String()).alias("template_id"),
            pl.lit(sheet, dtype=pl.String()).alias("sheet"),
            pl.lit(predicate_key, dtype=pl.String()).alias("predicate_key"),
            pl.coalesce("money_ours", "money_theirs").alias("money"),
            _movement_basis().alias("movement_basis"),
            pl.lit(value=partition, dtype=pl.Boolean()).alias("axis_is_partition"),
        )
        .select(*ROW_MIGRATION_SCHEMA)
        .sort("our_row_ref", "their_row_ref")
    )


# =============================================================================
# Building one side
# =============================================================================


def _build_side(  # noqa: PLR0913 - the source plus its scope, key, coverage and label
    source: ResultsSource,
    template_ids: tuple[str, ...],
    key_column: str,
    coverage: LedgerCoverage | None,
    *,
    side: str,
) -> SideView:
    """Generate one side's templates, plans and membership from ONE frame."""
    raw = source.scan_results()
    # The frame the generator executes. ``COREPGenerator`` derives the per-side
    # gross carriers at its own entry and the lineage path does not, so ensuring
    # them here — idempotent on a sealed exit — is what keeps the bundle, the
    # plans and the membership reading one frame rather than three.
    results = ensure_gross_side_carriers(raw, available_columns(raw))
    cols = available_columns(results)
    ensured = _EnsuredSource(results, source.framework)
    bundle = COREPGenerator().generate_from_lazyframe(results, framework=source.framework)
    membership = cell_membership(ensured, template_ids)

    plans: dict[str, dict[str, SheetPlan]] = {}
    frames: dict[str, dict[str, pl.DataFrame]] = {}
    for template_id in template_ids:
        provider = _provider(template_id)
        if provider is None:
            continue
        errors: list[str] = []
        plans[template_id] = provider.plans(results, cols, source.framework, errors)
        for error in errors:
            logger.warning("return_recon: %s plan (%s) reported %s", template_id, side, error)
        frames[template_id] = getattr(bundle, template_id, {}) or {}

    null_keys = membership.legs.filter(pl.col(key_column).is_null()).height
    if null_keys:
        logger.warning(
            "return_recon: %s side has %d membership rows with a null %s — those legs "
            "cannot be reconciled and will read as one unmatched key",
            side,
            null_keys,
            key_column,
        )
    if coverage is None:
        logger.debug("return_recon: %s side supplied no coverage record", side)
    else:
        for template_id in template_ids:
            _log_coverage(coverage, template_id, side=side)
    return SideView(
        source=source,
        coverage=coverage,
        results=results,
        cols=cols,
        membership=membership,
        plans=plans,
        frames=frames,
    )


def _log_coverage(coverage: LedgerCoverage, template_id: str, *, side: str) -> None:
    """Say up front which cells of a template this side cannot populate."""
    if template_id not in coverage.reachable_templates:
        logger.warning(
            "return_recon: %s side cannot produce %s at all (needs %s) — every cell of it "
            "is UNAVAILABLE, not zero",
            side,
            template_id,
            ", ".join(coverage.blocking_columns(template_id)) or "an unmapped label",
        )
        return
    refs = coverage.unavailable_refs(template_id)
    if refs:
        logger.warning(
            "return_recon: %s side cannot populate %d column(s) of %s (%s) — they are "
            "UNAVAILABLE whatever figure the generator prints for them",
            side,
            len(refs),
            template_id,
            ", ".join(refs),
        )


def _unpopulatable(side: SideView, template_id: str) -> dict[str, str]:
    """``col_ref -> why`` for the cells this side's mapping cannot populate.

    Empty when the side has no coverage record — our own results come off the
    sealed pipeline and every column they carry is genuinely measured. Memoised;
    the diff asks this of every cell.
    """
    cached = side.unpopulatable.get(template_id)
    if cached is not None:
        return cached
    coverage = side.coverage
    out: dict[str, str] = {}
    if coverage is not None:
        # ``unavailable_cells`` entries are ``"<ref>: needs <columns>"``, so the
        # reason travels with the ref and a refusal can name what to map.
        for entry in coverage.unavailable_cells.get(template_id, ()):
            ref, _sep, reason = entry.partition(":")
            out[ref] = reason.strip() or "the mapping supplies none of its sources"
    side.unpopulatable[template_id] = out
    return out


def _coverage_refusal(side: SideView, template_id: str, col_ref: str) -> str | None:
    """Why coverage says this side cannot populate the cell, or ``None``.

    Checked BEFORE the printed figure, because the dangerous case prints a
    figure: ``ensure_gross_side_carriers`` injects an all-null column and
    ``col_sum`` sums it to 0.0 (see the module docstring).
    """
    coverage = side.coverage
    if coverage is None:
        return None
    if template_id not in coverage.reachable_templates:
        blocking = ", ".join(coverage.blocking_columns(template_id)) or "an unmapped label"
        return f"the mapping cannot produce {template_id} at all (needs {blocking})"
    reason = _unpopulatable(side, template_id).get(col_ref)
    return None if reason is None else f"the mapping cannot populate this column: {reason}"


@dataclass(frozen=True)
class _EnsuredSource:
    """A ``ResultsSource`` over an already gross-ensured frame."""

    frame: pl.LazyFrame
    framework: str

    def scan_results(self) -> pl.LazyFrame:
        return self.frame


# =============================================================================
# The diff
# =============================================================================


def _sheet_diff(
    recon: ReturnRecon,
    provider: _Provider,
    template_id: str,
    sheet_key: str,
    sheet: str | None,
) -> list[dict[str, object]]:
    """Every cell of one sheet, from the union of the two sides' emitted axes."""
    our_cells = _records(recon.ours, template_id, sheet_key)
    their_cells = _records(recon.theirs, template_id, sheet_key)
    row_refs = _ordered_union(our_cells, their_cells)
    col_refs = _ordered_union(
        _value_columns(recon.ours.frames.get(template_id, {}).get(sheet_key)),
        _value_columns(recon.theirs.frames.get(template_id, {}).get(sheet_key)),
    )
    rows: list[dict[str, object]] = []
    for row_ref in row_refs:
        for col_ref in col_refs:
            our_value, our_state = _side_cell(
                recon.ours, provider, template_id, sheet_key, sheet, row_ref, col_ref
            )
            their_value, their_state = _side_cell(
                recon.theirs, provider, template_id, sheet_key, sheet, row_ref, col_ref
            )
            if our_state == "absent" and their_state == "absent":
                continue
            status = _status(our_state, their_state)
            rows.append(
                {
                    "template_id": template_id,
                    "sheet": sheet,
                    "row_ref": row_ref,
                    "col_ref": col_ref,
                    "ours": our_value,
                    "theirs": their_value,
                    "delta": (
                        None
                        if status == "unmeasurable"
                        else (our_value or 0.0) - (their_value or 0.0)
                    ),
                    "ours_state": our_state,
                    "theirs_state": their_state,
                    "status": status,
                }
            )
    return rows


def _side_cell(  # noqa: PLR0913 - the cell's full address plus its side and provider
    side: SideView,
    provider: _Provider,
    template_id: str,
    sheet_key: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
) -> tuple[float | None, CellState]:
    """One side's reported figure for a cell, with the REASON for any blank.

    Three distinctions, in the order they are tested — and the ORDER is the
    point:

    1. **Coverage first, ahead of the printed figure.** A cell this side's
       mapping cannot populate is ``unavailable`` even when the generator prints
       a number for it, because the number can be an artefact: an injected
       all-null column sums to 0.0, not to null. The printed figure is not
       returned — carrying it would put the false zero back on the screen.
    2. An emitted null with no metric source at all (``CellQuery`` not
       source-backed) is likewise ``unavailable``.
    3. Any other emitted null is ``empty`` — an empty population, which
       contributes 0.0 exactly as an unemitted row does.
    """
    record = _records(side, template_id, sheet_key).get(row_ref)
    if record is None or col_ref not in record:
        return None, "absent"
    if _coverage_refusal(side, template_id, col_ref) is not None:
        return None, "unavailable"
    value = record[col_ref]
    if value is not None:
        return value, "figure"
    query = _query(side, provider, template_id, sheet_key, sheet, row_ref, col_ref)
    if query is None:
        return None, "absent"
    if query.kind == "rows" and not query.is_source_backed:
        return None, "unavailable"
    return None, "empty"


def _records(
    side: SideView, template_id: str, sheet_key: str
) -> dict[str, dict[str, float | None]]:
    """``row_ref -> {col_ref: figure}`` for one generated sheet, first row wins.

    Only the VALUE columns are carried, cast to ``Float64`` strictly: a template
    column that is not numeric would be a programming error here, and raising
    beats reading it back as a silent null. Memoised per sheet — the diff asks
    for every cell of it and every decomposition asks again.
    """
    memo_key = (template_id, sheet_key)
    cached = side.records.get(memo_key)
    if cached is not None:
        return cached
    frame = side.frames.get(template_id, {}).get(sheet_key)
    out: dict[str, dict[str, float | None]] = {}
    if frame is not None and "row_ref" in frame.columns:
        value_cols = _value_columns(frame)
        typed = frame.select(
            pl.col("row_ref").cast(pl.String()),
            *(pl.col(col).cast(pl.Float64()) for col in value_cols),
        )
        for record in typed.iter_rows(named=True):
            ref = record["row_ref"]
            if ref is not None and ref not in out:
                out[ref] = {col: record[col] for col in value_cols}
    side.records[memo_key] = out
    return out


def _value_columns(frame: pl.DataFrame | None) -> tuple[str, ...]:
    """The published column refs of a generated sheet, in template order."""
    if frame is None:
        return ()
    return tuple(col for col in frame.columns if col not in {"row_ref", "row_name"})


def _status(ours: CellState, theirs: CellState) -> DiffStatus:
    """The two states' digest. ``unavailable`` on either side beats everything.

    ``empty`` and ``absent`` are both "this side reports nothing here", so a
    figure opposite either of them is a one-sided cell — which is the whole
    point on a static row axis like C 07.00's, where a population difference
    shows up as a null rather than as a missing row.
    """
    if "unavailable" in (ours, theirs):
        return "unmeasurable"
    if ours == "figure":
        return "both" if theirs == "figure" else "ours_only"
    return "theirs_only" if theirs == "figure" else "neither"


# =============================================================================
# The decomposition
# =============================================================================


def _refusal_reason(query: CellQuery, ours: CellState, theirs: CellState) -> str | None:
    """Why this cell carries no four-way split, or ``None`` if it does."""
    if query.kind != "rows":
        return (
            f"cell is {query.kind}, not row-backed: it has no exposure population to "
            "decompose (link to the cells it references instead)"
        )
    if query.metric != "sum":
        return (
            f"non-additive metric {query.metric!r}: the four-way identity is a statement "
            "about sums and does not hold for a weighted average, mean, ratio, count or "
            "first-non-null"
        )
    if "unavailable" in (ours, theirs):
        side = "ours" if ours == "unavailable" else "theirs"
        return (
            f"unavailable on {side}: that side carries none of this cell's metric sources, "
            "so its blank means 'cannot compute', not 'nothing to report' — and a blank "
            "that is not a zero has no delta to explain"
        )
    return None


def _cell_money(  # noqa: PLR0913 - the cell's full address plus its side and key
    side: SideView,
    key_column: str,
    template_id: str,
    sheet_key: str,
    row_ref: str,
    col_ref: str,
    query: CellQuery,
) -> dict[str, float]:
    """Per-key money for one cell's OWN population on one side.

    The population is resolved through ``CellMembership.columns`` — a row does
    not have one population, so the column's predicate group is the only correct
    address (see the module docstring). An empty dict means this side does not
    report the cell from rows at all: an empty population, not an error.
    """
    predicate_key = _predicate_key(side, template_id, sheet_key, row_ref, col_ref)
    if predicate_key is None:
        return {}
    plan = side.plans.get(template_id, {}).get(sheet_key)
    if plan is None:
        return {}
    negate = col_ref in plan.negative_cols
    memo_key = (template_id, sheet_key, row_ref, predicate_key, query.metric_columns, negate)
    cached = side.money.get(memo_key)
    if cached is not None:
        return cached
    subset = _group_subsets(side, template_id, sheet_key).get(f"{row_ref}{_SEP}{predicate_key}")
    money = _key_money(subset, key_column, query.metric_columns, negate=negate)
    side.money[memo_key] = money
    return money


def _key_money(
    subset: pl.DataFrame | None,
    key_column: str,
    metric_columns: tuple[str, ...],
    *,
    negate: bool,
) -> dict[str, float]:
    """``key -> money`` over one predicate group, summed the executor's way.

    ``pl.col(c).sum()`` treats a null within a present column as zero and an
    all-null group as ``0.0``, which is exactly ``kernel/sums.py``'s documented
    behaviour — so no ``fill_null`` is needed and none is used. A metric column
    the plan frame does not carry is skipped, mirroring ``SafeSum``.
    """
    if subset is None or subset.height == 0 or key_column not in subset.columns:
        return {}
    present = [col for col in metric_columns if col in subset.columns]
    if not present:
        return {}
    agg = subset.group_by(key_column).agg(pl.col(col).sum().alias(col) for col in present)
    sign = -1.0 if negate else 1.0
    totals = agg.select(
        pl.col(key_column).cast(pl.String()).alias("key"),
        (pl.sum_horizontal(present) * sign).alias("value"),
    )
    return dict(zip(totals["key"].to_list(), totals["value"].to_list(), strict=True))


def _terms(  # noqa: PLR0913 - the four classification sets are the whole signature
    ours: dict[str, float],
    theirs: dict[str, float],
    *,
    their_all: frozenset[str],
    their_sheet: frozenset[str],
    our_all: frozenset[str],
    our_sheet: frozenset[str],
) -> tuple[CellTerm, ...]:
    """The four causes, as five signed terms that sum to the population delta.

    Each side's population is partitioned by the SAME ordered test, so no key is
    counted twice and none is dropped — which is what makes the identity exact
    rather than approximate. See the module docstring.
    """
    amounts = dict.fromkeys(TERM_NAMES, 0.0)
    keys: dict[TermName, set[str]] = {name: set() for name in TERM_NAMES}

    for key, value in ours.items():
        name: TermName
        if key in theirs:
            name, value = "measurement", value - theirs[key]
        elif key in their_sheet:
            name = "row_placement"
        elif key in their_all:
            name = "sheet_placement"
        else:
            name = "population_ours_only"
        amounts[name] += value
        keys[name].add(key)

    for key, value in theirs.items():
        if key in ours:
            continue  # already netted into measurement above
        name = (
            "row_placement"
            if key in our_sheet
            else "sheet_placement"
            if key in our_all
            else "population_theirs_only"
        )
        amounts[name] -= value
        keys[name].add(key)

    return tuple(
        CellTerm(name=name, amount=amounts[name], keys=len(keys[name])) for name in TERM_NAMES
    )


def _side_keys(
    side: SideView, key_column: str, template_id: str, sheet: str | None
) -> frozenset[str]:
    """Every reconciliation key one side's membership holds, template- or
    sheet-wide. ``sheet=None`` means the WHOLE template, which is the set a
    population difference is measured against."""
    memo_key = (template_id, sheet)
    cached = side.keys.get(memo_key)
    if cached is not None:
        return cached
    legs = side.membership.legs.filter(pl.col("template_id") == template_id)
    if sheet is not None:
        legs = legs.filter(pl.col("sheet") == sheet)
    keys = frozenset(legs[key_column].drop_nulls().cast(pl.String()).to_list())
    side.keys[memo_key] = keys
    return keys


# =============================================================================
# The migration matrix
# =============================================================================


def _group_legs(  # noqa: PLR0913 - the group's full address plus the key, price and side
    side: SideView,
    key_column: str,
    template_id: str,
    sheet: str | None,
    predicate_key: str,
    money_column: str,
    label: str,
) -> pl.DataFrame:
    """One predicate group's DISTINCT legs, each priced once and placed once.

    The unit is the reconciliation KEY, never the membership row, because a leg
    legitimately appears on several rows of one group (a parent and its child)
    and a row-level read would price it once per row. Each key is then placed:

    - on its single provably-leaf row (``is_parent_row`` is ``False``), or
    - in ``UNDECIDABLE_ROW`` when it has none — every row holding it is a strict
      parent or an indistinguishable NULL — or several, so no one row is its
      place. Both cases are WARNED about; neither drops the leg, because a leg
      whose row cannot be decided is not a leg that carries no money.

    WHAT ACTUALLY GUARDS THIS IS THE SINGLE-LEAF RULE, NOT THE FILL DIRECTION —
    recorded because the opposite is the natural assumption and this docstring
    asserted it until it was measured. ``is_parent_row`` is filled to ``True``
    before negating, and the ``True`` half is load-bearing: ignore the flag
    entirely and 18 of 59 membership groups change, reddening 5 tests. The
    ``NULL`` half changes NOTHING: flipping ONLY the fill to ``False`` alters no
    group and reddens no test, because ``_parent_flags`` emits ``None`` only for
    a row whose leg set another row holds exactly, so a NULL-flagged leg has
    either zero candidate leaves (filled ``True``) or at least two (filled
    ``False``) and routes to ``UNDECIDABLE_ROW`` on the ``list.len() == 1`` test
    either way.

    So the fill direction is kept as the conservative statement of intent — NULL
    means "indistinguishable from the data", never "leaf" — and not as a defence
    anything relies on. Filling a BOOLEAN flag towards the conservative state is
    not the banned Float/String zero-fill: it excludes a row from being a
    placement, it invents no figure.
    """
    legs = side.membership.legs.filter(pl.col("template_id") == template_id)
    legs = legs.filter(pl.col("sheet").is_null() if sheet is None else pl.col("sheet") == sheet)
    legs = legs.filter(pl.col("predicate_key") == predicate_key).select(
        pl.col(key_column).cast(pl.String()).alias(key_column),
        pl.col("row_ref"),
        pl.col(money_column),
        pl.col("is_parent_row"),
    )
    if legs.height == 0:
        return pl.DataFrame(
            schema={key_column: pl.String(), "row_ref": pl.String(), money_column: pl.Float64()}
        )

    priced = legs.group_by(key_column).agg(
        pl.col(money_column).first().alias(money_column),
        pl.col(money_column).n_unique().alias("_prices"),
        pl.col("row_ref")
        .filter(pl.col("is_parent_row").fill_null(value=True).not_())
        .unique()
        .alias("_leaves"),
    )
    _warn_placement(priced, template_id, sheet, predicate_key, label)
    return priced.select(
        pl.col(key_column),
        pl.when(pl.col("_leaves").list.len() == 1)
        .then(pl.col("_leaves").list.first())
        .otherwise(pl.lit(UNDECIDABLE_ROW))
        .alias("row_ref"),
        pl.col(money_column),
    )


def _warn_placement(
    priced: pl.DataFrame, template_id: str, sheet: str | None, predicate_key: str, label: str
) -> None:
    """Say out loud what a silent filter would have swallowed."""
    where = f"{template_id}/{sheet}/{predicate_key} ({label})"
    unplaced = int((priced["_leaves"].list.len() == 0).sum())
    if unplaced:
        logger.warning(
            "row_migration: %s — %d leg(s) reach NO provable leaf row (every row holding "
            "them is a parent or indistinguishable). They are bucketed as %r, not dropped: "
            "an empty filter is not a zero",
            where,
            unplaced,
            UNDECIDABLE_ROW,
        )
    several = int((priced["_leaves"].list.len() > 1).sum())
    if several:
        logger.warning(
            "row_migration: %s — %d leg(s) sit in several provable leaf rows, so no single "
            "row is their placement. Bucketed as %r rather than counted in each",
            where,
            several,
            UNDECIDABLE_ROW,
        )
    prices = int((priced["_prices"] > 1).sum())
    if prices:
        logger.warning(
            "row_migration: %s — %d leg(s) carry more than one value for the money column "
            "across their membership rows; the first is used and the matrix may be wrong",
            where,
            prices,
        )


def _movement_basis() -> pl.Expr:
    """The per-row honesty label. Off-diagonal is VALUE-driven by construction."""
    return (
        pl.when(pl.col("their_row_ref") == ABSENT_ROW)
        .then(pl.lit("ours_only"))
        .when(pl.col("our_row_ref") == ABSENT_ROW)
        .then(pl.lit("theirs_only"))
        .when(
            (pl.col("our_row_ref") == UNDECIDABLE_ROW)
            | (pl.col("their_row_ref") == UNDECIDABLE_ROW)
        )
        .then(pl.lit("undecidable"))
        .when(pl.col("our_row_ref") == pl.col("their_row_ref"))
        .then(pl.lit("agreed"))
        .otherwise(pl.lit("value_driven"))
    )


# =============================================================================
# Shared helpers
# =============================================================================


def _provider(template_id: str) -> _Provider | None:
    """The template's lineage provider, or ``None`` with a WARNING."""
    provider = LINEAGE_PLANS.get(template_id)
    if provider is None:
        logger.warning("return_recon: template %s is not instrumented -- skipped", template_id)
    return provider


def _sheet_key(recon: ReturnRecon, template_id: str, sheet: str | None) -> str | None:
    """The generator's own dict key for a sheet, given the membership's name.

    A single-frame template reports ``sheet = None`` everywhere (membership's
    convention), but its plans and frames still live under one canonical key —
    so resolve it from the side that has it rather than inventing the string.
    """
    if sheet is not None:
        return sheet
    for side in (recon.ours, recon.theirs):
        plans = side.plans.get(template_id, {})
        if len(plans) == 1:
            return next(iter(plans))
    return None


def _query(  # noqa: PLR0913 - the cell's full address plus its side and provider
    side: SideView,
    provider: _Provider,
    template_id: str,
    sheet_key: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
) -> CellQuery | None:
    """One cell's meaning on one side, memoised, or ``None`` if it has none.

    Read through ``reporting.lineage.describe_cell`` so the cell-kind vocabulary
    has ONE home and this module cannot drift from what the drill-down says the
    same cell means. Memoised per side because both the diff and every
    decomposition ask the same question of the same cell.
    """
    memo_key = (template_id, sheet_key, row_ref, col_ref)
    if memo_key in side.queries:
        return side.queries[memo_key]
    plan = side.plans.get(template_id, {}).get(sheet_key)
    query = (
        None
        if plan is None or plan.spec.cells.get((row_ref, col_ref)) is None
        else describe_cell(provider, plan, template_id, sheet, row_ref, col_ref, sealed=side.cols)
    )
    side.queries[memo_key] = query
    return query


def _predicate_key(
    side: SideView, template_id: str, sheet_key: str, row_ref: str, col_ref: str
) -> str | None:
    """The membership group that serves one cell on one side."""
    served = side.membership.columns.filter(
        (pl.col("template_id") == template_id)
        & (pl.col("sheet") == sheet_key)
        & (pl.col("row_ref") == row_ref)
        & (pl.col("col_ref") == col_ref)
    )
    if served.height == 0:
        return None
    return str(served["predicate_key"][0])


def _group_subsets(side: SideView, template_id: str, sheet_key: str) -> dict[str, pl.DataFrame]:
    """Every membership group's rows on one sheet, computed once per sheet.

    The groups are exactly ``reporting.membership``'s: the sheet predicate
    conjoined with the ANCHOR cell's own predicate, batched through the same
    ``subset_rows`` kernel. Reproducing membership's predicates rather than
    re-deriving a row selection is the one rule the lineage seam exists for.
    """
    memo_key = (template_id, sheet_key)
    cached = side.groups.get(memo_key)
    if cached is not None:
        return cached
    plan = side.plans.get(template_id, {}).get(sheet_key)
    if plan is None:
        side.groups[memo_key] = {}
        return {}
    frame = plan.frame
    if plan.spec.predicate is not None:
        frame = plan.spec.predicate.apply(frame)
    wanted = (
        side.membership.columns.filter(
            (pl.col("template_id") == template_id) & (pl.col("sheet") == sheet_key)
        )
        .select("row_ref", "predicate_key")
        .unique()
    )
    predicates = {}
    for row_ref, predicate_key in wanted.iter_rows():
        cell = plan.spec.cells.get((row_ref, predicate_key))
        if cell is None:  # pragma: no cover - a predicate_key IS an anchor col_ref
            logger.warning(
                "return_recon: %s/%s row %s names anchor %s, which is not a cell",
                template_id,
                sheet_key,
                row_ref,
                predicate_key,
            )
            continue
        predicates[f"{row_ref}{_SEP}{predicate_key}"] = cell.predicate
    subsets = subset_rows(frame, predicates) if predicates else {}
    side.groups[memo_key] = subsets
    return subsets


def _refused(  # noqa: PLR0913 - a refusal still reports the cell's full identity
    template_id: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
    kind: str,
    metric: str | None,
    refusal: str,
    *,
    ours: float | None = None,
    theirs: float | None = None,
    ours_state: CellState = "absent",
    theirs_state: CellState = "absent",
) -> CellDecomposition:
    """A cell the identity does not apply to, saying so on the result itself."""
    return CellDecomposition(
        template_id=template_id,
        sheet=sheet,
        row_ref=row_ref,
        col_ref=col_ref,
        kind=kind,
        metric=metric,
        ours=ours,
        theirs=theirs,
        ours_state=ours_state,
        theirs_state=theirs_state,
        delta=None,
        terms=(),
        reconciles=False,
        residual=None,
        refusal=refusal,
    )


def _ordered_union(first: Iterable[str], second: Iterable[str]) -> list[str]:
    """``first``'s order, then whatever only ``second`` has, order preserved."""
    out = list(dict.fromkeys(first))
    seen = set(out)
    out.extend(item for item in dict.fromkeys(second) if item not in seen)
    return out
