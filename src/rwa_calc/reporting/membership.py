"""
Cell membership — which template ROWS each exposure leg landed in.

Pipeline position:
    sealed aggregator-exit ledger -> <template>_plans() -> SheetPlan
        -> membership (this module) -> analysis return-reconciliation surfaces

Key responsibilities:
- For an instrumented template, emit the long frame
  ``(template_id, sheet, row_ref, predicate_key, leg)`` — one row per leg per
  template row it reported in, carrying the leg's identity and its money — plus
  the ``predicate_key -> col_ref`` mapping saying which cells each group serves.
- Flag the HIERARCHICAL rows (``is_parent_row``), derived empirically, so no
  consumer can treat a template's row axis as a partition and double-count.
- Skip, and report, a template that is not instrumented — never guess its rows.

**A cell's membership IS its spec.** This module reads ``LINEAGE_PLANS`` and
runs the very ``RowPredicate`` the generator executed
(``plan.spec.predicate`` conjoined with ``plan.spec.cells[(row, col)].predicate``),
exactly as ``reporting.lineage`` does. A second copy of a template's row
selection could silently disagree with the figure actually reported, which is
the one thing a membership feature may never do. It therefore runs unchanged on
ANY ``ResultsSource`` — including a projection of a firm's own extract, which is
what makes the two sides of a return comparable.

Three properties are load-bearing, and none is assumed:

1. **A ROW DOES NOT HAVE ONE POPULATION, and this module does not pretend it
   does.** Measured over the three templates in ``MEMBERSHIP_TEMPLATE_IDS``,
   both frameworks: on C 08.03 every row-backed cell of a row shares one
   predicate, but on C 07.00 and C 08.01 EVERY row carries several — the
   recorded two-basis split (origin-basis columns read the obligor's own book,
   post-substitution columns read the guarantor's) plus the per-column
   narrowings (defaulted, off-balance-sheet, CCF bucket, rated). Collapsing a
   row to a single population reproduced only 80% of C 08.01's summable cells;
   the rest were wrong by exactly the substituted legs. So the grain carries
   ``predicate_key`` — one group per DISTINCT predicate on the row, keyed by the
   first published column it serves — and ``CellMembership.columns`` maps every
   column to its group. Every cell's population is then exactly addressable.
2. **``is_parent_row`` is measured, not listed, and it is TRI-STATE.** Within
   one ``predicate_key`` (containment is only meaningful between comparable
   populations): ``True`` when the row's legs strictly contain another row's,
   ``False`` when they provably contain none and duplicate none, and ``None``
   when another row holds exactly the same legs, so the data cannot decide.
   The null state is load-bearing — several rows are different DECOMPOSITIONS
   of one total rather than a tree, and reporting ``False`` for a row that
   duplicates another made a leaves-only sum over-count by 3x. See
   ``_parent_flags``.
3. **The frame is the generator's frame.** ``ensure_gross_side_carriers`` runs
   at this module's entry exactly as it runs at each generator's, because the
   lineage path does not apply it — see ``cell_membership``. Without it a
   pre-seal or synthetic frame would be executed here in a shape the reported
   template never saw.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP template row axes)
- docs/plans/return-reconciliation.md (Phase 1 — cell membership)
- docs/plans/report-cell-lineage.md §4.1 (the SheetPlan seam this reuses)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.cellspec import subset_rows
from rwa_calc.reporting.kernel import available_columns, ensure_gross_side_carriers
from rwa_calc.reporting.lineage import LINEAGE_PLANS, describe_cell

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_calc.reporting.cellspec import RowPredicate
    from rwa_calc.reporting.lineage import _Provider
    from rwa_calc.reporting.metadata import ResultsSource
    from rwa_calc.reporting.plans import SheetPlan

logger = logging.getLogger(__name__)

#: The templates this slice covers. The same ids serve both frameworks —
#: OF 07.00 / OF 08.01 / OF 08.03 are the Basel 3.1 rendering of these very
#: generators, not separate templates.
MEMBERSHIP_TEMPLATE_IDS: tuple[str, ...] = ("c07_00", "c08_01", "c08_03")

#: The leg identity and money carried alongside every membership row. Absent
#: from a given plan frame -> a typed NULL, never a zero and never a dropped
#: column: an unsupplied carrier and a measured zero are different claims.
_LEG_COLUMNS: tuple[tuple[str, pl.DataType], ...] = (
    ("exposure_reference", pl.String()),
    ("source_exposure_reference", pl.String()),
    ("reporting_leg_role", pl.String()),
    ("reporting_class_origin", pl.String()),
    ("reporting_approach_origin", pl.String()),
    ("ead_final", pl.Float64()),
    ("rwa_final", pl.Float64()),
)

#: The membership schema, in output order. Published so a consumer can build an
#: empty side of a join without re-declaring the shape.
MEMBERSHIP_SCHEMA: dict[str, pl.DataType] = {
    "template_id": pl.String(),
    "sheet": pl.String(),
    "row_ref": pl.String(),
    "predicate_key": pl.String(),
    "is_parent_row": pl.Boolean(),
    **dict(_LEG_COLUMNS),
}

#: The group -> column mapping schema: one row per row-backed cell, naming the
#: membership group whose legs that cell aggregates.
MEMBERSHIP_COLUMN_SCHEMA: dict[str, pl.DataType] = {
    "template_id": pl.String(),
    "sheet": pl.String(),
    "row_ref": pl.String(),
    "predicate_key": pl.String(),
    "col_ref": pl.String(),
}

#: The positional key membership sets are compared on. Prefixed so it cannot
#: collide with a sealed ledger column or a template-derived discriminator.
_IDX = "__membership_idx"

#: Separator for the internal ``(row_ref, predicate_key)`` batching key. Not a
#: published string — ``subset_rows`` needs one flat key per predicate.
_SEP = "|"


@dataclass(frozen=True)
class CellMembership:
    """One run's membership, at ``(template, sheet, row, predicate group, leg)``.

    ``legs`` is the long membership frame (``MEMBERSHIP_SCHEMA``); ``columns``
    is the mapping (``MEMBERSHIP_COLUMN_SCHEMA``) from each row-backed cell to
    the group whose legs it aggregates. They are returned together because
    neither answers a cell-level question alone: ``legs`` says which exposures
    a group holds, ``columns`` says which group a given ``col_ref`` reads.

    To reach one cell's population, join ``columns`` on
    ``(template_id, sheet, row_ref, col_ref)`` and then ``legs`` on
    ``(template_id, sheet, row_ref, predicate_key)``.
    """

    legs: pl.DataFrame
    columns: pl.DataFrame


def cell_membership(
    source: ResultsSource,
    template_ids: Sequence[str] | None = None,
) -> CellMembership:
    """Which template rows each exposure leg landed in, one row per membership.

    A leg reported under BOTH a parent row and its child appears twice,
    distinguished by ``is_parent_row`` — the C 08.03 PD scale (and C 07.00's and
    C 08.01's totals) overlap and are not partitions. A leg counted on two
    different BASES of the same row (the obligor's own book and the
    post-substitution book) also appears twice, distinguished by
    ``predicate_key``.

    ``is_parent_row`` is TRI-STATE (see ``_parent_flags``): ``True`` contains
    another row, ``False`` provably contains and duplicates none, ``None``
    indistinguishable. A consumer that must not double-count filters
    ``~is_parent_row``, which drops both ``True`` and ``None`` — the safe
    direction. Because the row axes OVERLAP, no filter reconstructs a group's
    total by summing rows; read the group's own de-duplicated legs for that.

    ``template_ids`` defaults to ``MEMBERSHIP_TEMPLATE_IDS``. An id that is not
    instrumented (absent from ``LINEAGE_PLANS``) is skipped with a WARNING —
    never resolved to a guessed row set. A run that produces nothing yields
    EMPTY frames carrying the full schemas, so a consumer's join still types.
    """
    requested = MEMBERSHIP_TEMPLATE_IDS if template_ids is None else tuple(template_ids)
    results = source.scan_results()
    # The SAME frame the generator executes. ``COREPGenerator`` /
    # ``Pillar3Generator`` derive the per-side gross carriers at their LazyFrame
    # entry (a no-op on the sealed exit, which already carries them); the lineage
    # path does NOT, so a synthetic or pre-seal frame reaching the generators and
    # reaching here would be two different frames. Measured on a carrier-less
    # frame: the two paths disagree on 141 (CRR) / 151 (Basel 3.1) cells across
    # C 07.00, C 08.01 and C 08.03 — the gross columns publish 0.0 / null against
    # real money.
    results = ensure_gross_side_carriers(results, available_columns(results))
    cols = available_columns(results)

    legs: list[pl.DataFrame] = []
    columns: list[pl.DataFrame] = []
    for template_id in requested:
        for sheet_legs, sheet_columns in _template_membership(
            template_id, results, cols, source.framework
        ):
            legs.append(sheet_legs)
            columns.append(sheet_columns)
    if not legs:
        logger.info("cell_membership: no membership for templates %s", list(requested))
        return CellMembership(
            legs=pl.DataFrame(schema=MEMBERSHIP_SCHEMA),
            columns=pl.DataFrame(schema=MEMBERSHIP_COLUMN_SCHEMA),
        )
    return CellMembership(
        legs=pl.concat(legs, how="vertical"),
        columns=pl.concat(columns, how="vertical"),
    )


# =============================================================================
# Private helpers
# =============================================================================


def _template_membership(
    template_id: str,
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
) -> list[tuple[pl.DataFrame, pl.DataFrame]]:
    """Every sheet's ``(legs, columns)`` pair for one template."""
    provider = LINEAGE_PLANS.get(template_id)
    if provider is None:
        logger.warning("cell_membership: template %s is not instrumented -- skipped", template_id)
        return []
    errors: list[str] = []
    plans = provider.plans(results, cols, framework, errors)
    for error in errors:
        logger.warning("cell_membership: %s plan reported %s", template_id, error)
    if not plans:
        logger.info("cell_membership: %s produced no sheets for this run", template_id)
        return []
    out: list[tuple[pl.DataFrame, pl.DataFrame]] = []
    for key, plan in plans.items():
        sheet = None if provider.single_frame else key
        built = _sheet_membership(provider, plan, template_id, sheet, cols)
        if built is not None:
            out.append(built)
    return out


def _sheet_membership(
    provider: _Provider,
    plan: SheetPlan,
    template_id: str,
    sheet: str | None,
    cols: set[str],
) -> tuple[pl.DataFrame, pl.DataFrame] | None:
    """One sheet's membership groups: the legs behind each, and what each serves."""
    frame = plan.frame.with_row_index(_IDX)
    if plan.spec.predicate is not None:
        frame = plan.spec.predicate.apply(frame)

    predicates: dict[str, RowPredicate | None] = {}
    served: dict[str, list[str]] = {}
    for row in plan.spec.rows:
        for col_ref, predicate, anchor in _row_groups(
            provider, plan, template_id, sheet, row.ref, cols
        ):
            key = f"{row.ref}{_SEP}{anchor}"
            predicates[key] = predicate
            served.setdefault(key, []).append(col_ref)
    if not predicates:
        return None

    subsets = subset_rows(frame, predicates)
    members = {key: set(subset[_IDX].to_list()) for key, subset in subsets.items()}
    populated = {key: legs for key, legs in members.items() if legs}
    flags = _parent_flags(populated)

    projected = [
        _project(
            subsets[key],
            template_id,
            sheet,
            *_split(key),
            is_parent=flags[key],
        )
        for key in populated
    ]
    mapping = pl.DataFrame(
        [
            {
                "template_id": template_id,
                "sheet": sheet,
                "row_ref": _split(key)[0],
                "predicate_key": _split(key)[1],
                "col_ref": col_ref,
            }
            for key, col_refs in served.items()
            for col_ref in col_refs
        ],
        schema=MEMBERSHIP_COLUMN_SCHEMA,
    )
    if not projected:
        return None
    return pl.concat(projected, how="vertical"), mapping


def _row_groups(
    provider: _Provider,
    plan: SheetPlan,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    cols: set[str],
) -> list[tuple[str, RowPredicate | None, str]]:
    """``(col_ref, predicate, anchor col_ref)`` for each row-backed cell of a row.

    Read through ``lineage.describe_cell`` so the cell-kind vocabulary has one
    home: a cell that is not row-backed (``Formula`` / ``SideContext`` /
    ``PriorPeriod`` / a constant / unbound) has no population and joins no
    group. The ANCHOR is the first published column a predicate serves, which
    makes ``predicate_key`` readable and addressable without inventing a name
    for a predicate the template never named.
    """
    anchors: dict[RowPredicate | None, str] = {}
    out: list[tuple[str, RowPredicate | None, str]] = []
    for col_ref in plan.spec.column_refs:
        cell = plan.spec.cells.get((row_ref, col_ref))
        if cell is None:
            continue
        query = describe_cell(provider, plan, template_id, sheet, row_ref, col_ref, sealed=cols)
        if query.kind != "rows":
            continue
        anchor = anchors.setdefault(cell.predicate, col_ref)
        out.append((col_ref, cell.predicate, anchor))
    return out


def _parent_flags(populated: dict[str, set[int]]) -> dict[str, bool | None]:
    """The TRI-STATE hierarchy flag, measured WITHIN each predicate group.

    - ``True``  — this row's legs strictly CONTAIN another row's in the group.
    - ``False`` — they provably contain no other row's, and duplicate none.
    - ``None``  — another row in the group holds exactly the SAME legs, so
      containment cannot decide which (if either) is the aggregate.

    The null state is the whole point. Several template rows are DIFFERENT
    DECOMPOSITIONS of one total rather than a tree — C 08.01 row 0010 (TOTAL),
    row 0020 (on-balance sheet) and row 0070 (obligor grades) are three views of
    the same book, and coincide exactly whenever the sheet carries no
    off-balance-sheet or slotting leg. Measured on the test portfolio: 26 (C
    07.00) and 24 (C 08.01) duplicated memberships, and a consumer that excluded
    only strict parents and summed the rest over-counted by 3x. Reporting
    ``False`` there is not a conservative default, it is a wrong answer with a
    3x consequence; ``None`` says "indistinguishable from the data" and a
    ``~is_parent_row`` filter drops it, which is the safe direction.

    Note what this does NOT restore: because the axes overlap, no flag makes
    "sum the leaves" reconstruct a group total. Resolving the TOTAL row from the
    template's own row names would set one of the three to ``True`` and leave
    the other two still co-extensive — 2x instead of 3x — so it is deliberately
    not done. Containment across groups is likewise meaningless: the origin and
    post-substitution populations of one row differ by whatever substituted,
    which is a basis difference and not a hierarchy.

    Only populated rows take part: an empty set is a subset of everything, and
    letting it count would make every other row on the sheet a parent.
    """
    by_group: dict[str, dict[str, set[int]]] = {}
    for key, legs in populated.items():
        row_ref, predicate_key = _split(key)
        by_group.setdefault(predicate_key, {})[row_ref] = legs

    flags: dict[str, bool | None] = {}
    for predicate_key, rows in by_group.items():
        for row_ref, legs in rows.items():
            others = [other for ref, other in rows.items() if ref != row_ref]
            if any(legs > other for other in others):
                flag: bool | None = True
            elif any(legs == other for other in others):
                flag = None
            else:
                flag = False
            flags[f"{row_ref}{_SEP}{predicate_key}"] = flag
    return flags


def _split(key: str) -> tuple[str, str]:
    """``"<row_ref>|<predicate_key>"`` back into its two parts."""
    row_ref, _sep, predicate_key = key.partition(_SEP)
    return row_ref, predicate_key


def _project(  # noqa: PLR0913 - the group's full identity plus its legs
    subset: pl.DataFrame,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    predicate_key: str,
    *,
    is_parent: bool | None,
) -> pl.DataFrame:
    """One group's legs, in the published membership schema."""
    present = set(subset.columns)
    return subset.select(
        pl.lit(template_id, dtype=pl.String()).alias("template_id"),
        pl.lit(sheet, dtype=pl.String()).alias("sheet"),
        pl.lit(row_ref, dtype=pl.String()).alias("row_ref"),
        pl.lit(predicate_key, dtype=pl.String()).alias("predicate_key"),
        pl.lit(value=is_parent, dtype=pl.Boolean()).alias("is_parent_row"),
        *(
            pl.col(name).cast(dtype).alias(name)
            if name in present
            else pl.lit(None, dtype=dtype).alias(name)
            for name, dtype in _LEG_COLUMNS
        ),
    )
