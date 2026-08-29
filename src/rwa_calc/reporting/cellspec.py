"""
Declarative cell specifications and the ONE template executor (Phase 7 S7).

Pipeline position:
    sealed aggregator-exit ledger + ReportingContext
        -> TemplateSpec (per-template module) -> execute() -> template DataFrame

Key responsibilities:
- A small, closed vocabulary of value bindings (the verbs a template cell can
  mean): Sum, SafeSum, Mean, WeightedAvg, Ratio, Count, PriorPeriod, Formula.
- Row predicates over the canonical reporting-ledger columns
  (``reporting_class`` / ``reporting_class_origin`` / ``reporting_method`` /
  ``reporting_approach_origin`` / ``reporting_leg_role`` /
  ``reporting_on_balance_sheet`` / ``reporting_subclass`` / ``is_defaulted``).
- One executor that turns ``(TemplateSpec, ledger frame, ReportingContext)``
  into the template DataFrame, applying the per-template empty-cell policy
  (COREP zero vs Pillar 3 null — a recorded drift, never unified).

Deliberately NOT here (docs/plans/phase7-declarative-reporting.md §8):
no expression DSL — the executor has exactly two escapes. ``Formula`` is the
intra-row escape (a plain typed callable over already-computed row cells);
``PriorPeriod`` / the ``ReportingContext`` side inputs are the out-of-frame
escape. Anything richer is a typed kernel function a spec references.

References:
- docs/plans/phase7-declarative-reporting.md §3.2 (vocabulary sized to the
  measured cell-semantics taxonomy)
- Regulation (EU) 2021/451 Annex I/II; CRR Part 8 (template layouts)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast

import polars as pl

from rwa_calc.reporting.kernel import col_sum, safe_sum_or_none

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from rwa_calc.reporting.metadata import ReportingContext


# =============================================================================
# Value bindings — the verb vocabulary (taxonomy kinds 1-8, 11-12)
# =============================================================================


@dataclass(frozen=True)
class Sum:
    """Kind 1 (dominant): sum ``col`` over the cell's row subset."""

    col: str


@dataclass(frozen=True)
class Mean:
    """Kind 3: unweighted mean of ``col`` (e.g. C08.05 avg-PD — deliberately
    NOT EAD-weighted). ``scale`` multiplies a non-None result (the CR9
    average-PD column reports the arithmetic mean x100)."""

    col: str
    scale: float = 1.0


@dataclass(frozen=True)
class WeightedAvg:
    """Kind 2: ``weight``-weighted average of ``col`` (LGD, PD, maturity).

    ``scale`` multiplies a non-None result (the CR6 PD/LGD columns report
    percentages: weighted average x100)."""

    col: str
    weight: str = "reporting_ead"
    scale: float = 1.0


@dataclass(frozen=True)
class Ratio:
    """Kind 4: ``sum(numerator) / sum(denominator)``, scaled (OV1 x100 rows)."""

    numerator: str
    denominator: str
    scale: float = 1.0


@dataclass(frozen=True)
class Count:
    """Kind 5: row count, or ``n_unique(col)`` when ``distinct``."""

    col: str
    distinct: bool = False


@dataclass(frozen=True)
class SafeSum:
    """Kind 1 variant: sum every PRESENT column in ``cols`` over the row
    subset — absent names contribute nothing; None when NO named column is
    present (the kernel ``safe_sum_or_none`` gross-carrying-amount semantics:
    CR4 cols a/b and CR5 cols ba/bb sum ``drawn_amount``+``interest`` /
    ``nominal_amount``+``undrawn_amount``)."""

    cols: tuple[str, ...]


@dataclass(frozen=True)
class FirstNonNull:
    """First non-null value of ``col`` (a broadcast per-row constant — e.g.
    the OV1 row-26 output-floor multiplier carried on ``output_floor_pct``).
    None when the column is absent or all-null."""

    col: str


@dataclass(frozen=True)
class SideContext:
    """Kind 8: a named out-of-frame value from the ``ReportingContext``.

    ``key`` is one of the explicit names ``ReportingContext.side_value``
    resolves (``of_adj``, the six OV1 pre-floor capital-ratio fields);
    ``scale`` multiplies a non-None value (the ratio rows report x100).
    """

    key: str
    scale: float = 1.0


@dataclass(frozen=True)
class PriorPeriod:
    """Kinds 8/11: evaluate ``binding`` over the prior-period frame.

    Resolves to None when the context carries no prior-period results —
    flow templates (CR8, C 08.04) leave their opening rows null.
    """

    binding: Sum | SafeSum | Mean | WeightedAvg | Ratio | Count | FirstNonNull


@dataclass(frozen=True)
class Formula:
    """Kind 7 — the ONE intra-template escape.

    ``fn`` is a plain typed callable receiving the referenced already-computed
    cell values (None where a referenced cell is empty) and a
    ``prior_available`` flag (whether the context carried a prior-period
    frame — flow residuals are null without one, but coerce a None opening to
    zero WITH one, matching the generators' recorded semantics). ~5 cells
    across the whole estate use this; anything richer belongs in a kernel fn.

    Ref resolution: each ref is tried as a COLUMN ref in the formula's own row
    first (the COREP intra-row waterfalls, e.g. C07 ``0040 = 0010 - 0030``),
    then as a ROW ref in the formula's own column (the single-column flow
    templates, e.g. CR8 row 8 = row 9 - row 1). Formulas evaluate after every
    non-formula cell in the template; a formula referencing another formula is
    unsupported (raises).
    """

    refs: tuple[str, ...]
    fn: Callable[[Mapping[str, float | None], bool], float | None]


type ValueBinding = (
    Sum
    | SafeSum
    | Mean
    | WeightedAvg
    | Ratio
    | Count
    | FirstNonNull
    | SideContext
    | PriorPeriod
    | Formula
)

# Every binding EXCEPT the intra-row ``Formula`` escape (which pass 2 of the
# executor resolves over already-computed cells, not over a frame): what
# ``_evaluate`` and the batched pass resolve against the sheet frame.
type _EvaluableBinding = (
    Sum | SafeSum | Mean | WeightedAvg | Ratio | Count | FirstNonNull | SideContext | PriorPeriod
)


# =============================================================================
# Row predicates — over the canonical reporting-ledger columns only
# =============================================================================


@dataclass(frozen=True)
class RowPredicate:
    """A conjunctive row filter over the sealed reporting-ledger columns.

    Post-substitution fields (``classes`` / ``approaches`` / ``method``) and
    origin fields (``classes_origin`` / ``approaches_origin``) are both
    available so each template keys on its RECORDED basis (the
    post-substitution retargets are per-template recorded decisions — plan
    F3/F4). Unset fields (empty tuple / None) impose no constraint.

    ``approaches`` is the post-substitution twin of ``approaches_origin``
    (sealed ``reporting_approach`` = the aggregator's ``approach_post_crm``).
    A leg whose guarantee the engine applied under Art. 235 is a direct
    exposure to the protection provider and is treated under the PROVIDER's
    approach, so a template disclosing "of which: the standardised approach"
    keys this, while one disclosing the obligor's own book keys the origin
    twin. Both are needed and neither is the default. Unlike every other
    field here it compiles in ``_compile``, not ``to_expr``, because it
    DEGRADES to the origin twin on a frame that seals no post-substitution
    approach — see the note there.
    """

    classes: tuple[str, ...] = ()
    classes_origin: tuple[str, ...] = ()
    method: str | None = None
    approaches: tuple[str, ...] = ()
    approaches_origin: tuple[str, ...] = ()
    leg_role: Literal["whole", "guaranteed", "retained"] | None = None
    on_balance_sheet: bool | None = None
    is_defaulted: bool | None = None
    subclass: str | None = None
    # Presence-TOLERANT column == value conditions for the audited F6 columns
    # (e.g. the OV1 equity sub-approach discriminators ciu_approach /
    # equity_transitional_approach, which the seal strips today) and for
    # template-owned derived discriminator columns (Boolean values compare
    # against derived flags like C07's substitution/band columns): an absent
    # column yields an EMPTY subset — the recorded permanently-null-cell
    # behaviour — never a raise. Sealed-ledger fields above stay strict.
    equals: tuple[tuple[str, str | bool], ...] = ()
    # Inclusive band over the per-leg reporting_rw (the OV1 250%-RW memo row).
    rw_between: tuple[float, float] | None = None
    # Presence-TOLERANT half-open bands ``low <= col < high`` over a named
    # column (the CR5 risk-weight bucket allocation over the derived
    # pre-multiplier bucket column): an absent column yields an EMPTY
    # subset, exactly like ``equals``.
    between: tuple[tuple[str, float, float], ...] = ()
    # Disjunctive membership: a row matches when ANY limb matches (each limb
    # is itself a conjunctive RowPredicate; nesting a further ``any_of``
    # inside a limb is unsupported). Conjoined with the other terms. Sized
    # for the CR5 row-9 membership: exposure class OR a 55%-LTV split-leg
    # role, because the Art. 124F/124L physical legs carry reclassified
    # exposure classes.
    any_of: tuple[RowPredicate, ...] = ()

    def __post_init__(self) -> None:
        if any(limb.any_of for limb in self.any_of):
            msg = "RowPredicate: an any_of limb may not itself carry any_of"
            raise ValueError(msg)

    def to_expr(self) -> pl.Expr | None:
        """Compile the sealed-column terms to a filter expression (None = no
        constraint). The presence-tolerant ``equals`` terms are applied by
        ``apply`` (they need the frame's columns)."""
        terms: list[pl.Expr] = []
        if self.classes:
            terms.append(pl.col("reporting_class").is_in(list(self.classes)))
        if self.classes_origin:
            terms.append(pl.col("reporting_class_origin").is_in(list(self.classes_origin)))
        if self.method is not None:
            terms.append(pl.col("reporting_method") == self.method)
        if self.approaches_origin:
            terms.append(pl.col("reporting_approach_origin").is_in(list(self.approaches_origin)))
        if self.leg_role is not None:
            terms.append(pl.col("reporting_leg_role") == self.leg_role)
        if self.on_balance_sheet is not None:
            terms.append(pl.col("reporting_on_balance_sheet") == self.on_balance_sheet)
        if self.is_defaulted is not None:
            terms.append(pl.col("is_defaulted") == self.is_defaulted)
        if self.subclass is not None:
            terms.append(pl.col("reporting_subclass") == self.subclass)
        if self.rw_between is not None:
            low, high = self.rw_between
            terms.append(pl.col("reporting_rw").is_between(low, high))
        if not terms:
            return None
        expr = terms[0]
        for term in terms[1:]:
            expr = expr & term
        return expr

    def apply(self, data: pl.DataFrame) -> pl.DataFrame:
        """Filter ``data``: strict terms + tolerant terms + ``any_of`` union."""
        expr = self._compile(set(data.columns))
        return data.filter(expr) if expr is not None else data

    def _compile(self, cols: set[str]) -> pl.Expr | None:
        """The full filter expression against a frame with ``cols`` (None =
        no constraint). A tolerant ``equals``/``between`` column absent from
        the frame compiles to match-nothing — the recorded permanently-
        null-cell behaviour. ``any_of`` limbs compile independently and
        union; an all-defaults limb matches everything."""
        if any(col not in cols for col, _value in self.equals) or any(
            col not in cols for col, _low, _high in self.between
        ):
            return pl.lit(False)
        expr = self.to_expr()
        if self.approaches:
            # DEGRADES to the origin twin, and compiles HERE rather than in
            # ``to_expr`` because only here are the frame's columns known. A
            # frame that seals no post-substitution approach (the synthetic
            # unit/lineage frames, which carry ``reporting_approach_origin``
            # alone) then reports exactly what it did before the post-basis
            # retarget, instead of raising ColumnNotFoundError or — worse, had
            # this been a tolerant ``equals`` — silently zeroing every
            # per-approach cell. Matching only where a leg substituted is the
            # whole point: post == origin wherever nothing did.
            approach_col = (
                "reporting_approach"
                if "reporting_approach" in cols
                else "reporting_approach_origin"
            )
            if approach_col in cols:
                expr = _conj(expr, pl.col(approach_col).is_in(list(self.approaches)))
        for col, value in self.equals:
            expr = _conj(expr, pl.col(col) == value)
        for col, low, high in self.between:
            expr = _conj(expr, (pl.col(col) >= low) & (pl.col(col) < high))
        if self.any_of:
            union: pl.Expr | None = None
            for limb in self.any_of:
                limb_expr = limb._compile(cols)
                limb_expr = pl.lit(True) if limb_expr is None else limb_expr
                union = limb_expr if union is None else union | limb_expr
            expr = _conj(expr, union) if union is not None else expr
        return expr


# =============================================================================
# Cell + template specifications
# =============================================================================


class TemplateRow(Protocol):
    """Structural row layout — satisfied by P3Row / COREPRow constants."""

    @property
    def ref(self) -> str: ...
    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class CellSpec:
    """One cell: a value binding, optionally narrowed by a row predicate.

    ``empty_cell`` overrides the template policy for this cell (e.g. the OV1
    per-approach rows report 0.0 for an absent approach while the template
    default is Pillar 3 null).
    """

    binding: ValueBinding
    predicate: RowPredicate | None = None
    empty_cell: Literal["zero", "null"] | None = None


@dataclass(frozen=True)
class TemplateSpec:
    """One template: the frozen layout constants paired with cell bindings.

    ``cells`` keys are ``(row_ref, column_ref)``; unbound cells take the
    template's ``empty_cell`` policy. ``predicate`` narrows the input frame
    for every cell (a per-cell predicate narrows further).
    """

    name: str
    rows: tuple[TemplateRow, ...]
    column_refs: tuple[str, ...]
    cells: Mapping[tuple[str, str], CellSpec]
    predicate: RowPredicate | None = None
    empty_cell: Literal["zero", "null"] = "zero"


# =============================================================================
# The ONE executor
# =============================================================================


def execute(
    spec: TemplateSpec,
    frame: pl.LazyFrame | pl.DataFrame,
    ctx: ReportingContext | None = None,
) -> pl.DataFrame:
    """Execute a template spec over the sealed ledger (+ side context).

    For each row x column: resolve the cell's binding over the (predicate-
    narrowed) frame; unbound cells take the template ``empty_cell`` policy
    (``"zero"`` -> 0.0, COREP; ``"null"`` -> None, Pillar 3 — the recorded
    drift, applied per template, never unified). ``Formula`` cells evaluate
    after the row's other cells, receiving their values.
    """
    data = frame.collect() if isinstance(frame, pl.LazyFrame) else frame
    data = _narrow(data, spec.predicate)

    prior = ctx.previous_period_results if ctx is not None else None
    prior_df = prior.collect() if isinstance(prior, pl.LazyFrame) else prior
    if prior_df is not None:
        prior_df = _narrow(prior_df, spec.predicate)
    prior_available = prior_df is not None

    empty_default: float | None = 0.0 if spec.empty_cell == "zero" else None
    empty_as_none = spec.empty_cell == "null"

    # Pass 1: every non-formula cell, keyed (row_ref, col_ref). The whole
    # sheet evaluates in ONE aggregation pass over the UNFILTERED frame —
    # each distinct predicate becomes one boolean mask column and each cell
    # one filtered aggregation expression (``_evaluate_batched``), instead of
    # a physical subset copy per predicate and a collect per cell. Same masks,
    # same aggregations as ``_evaluate`` — number-neutral by construction (the
    # binding-by-binding derivation is the comment block above
    # ``_cell_aggregation``).
    computed: dict[tuple[str, str], float | None] = {}
    formulas: list[tuple[str, str, Formula]] = []
    jobs: list[_CellJob] = []
    for row_def in spec.rows:
        for col_ref in spec.column_refs:
            cell = spec.cells.get((row_def.ref, col_ref))
            if cell is None:
                computed[(row_def.ref, col_ref)] = empty_default
                continue
            binding = cell.binding
            if isinstance(binding, Formula):
                formulas.append((row_def.ref, col_ref, binding))
                continue
            cell_empty_as_none = (
                empty_as_none if cell.empty_cell is None else cell.empty_cell == "null"
            )
            jobs.append(((row_def.ref, col_ref), cell, binding, cell_empty_as_none))
    batched, deferred = _evaluate_batched(jobs, data)
    computed.update(batched)

    # Pass 1b: the out-of-frame bindings (SideContext / PriorPeriod read the
    # context and the prior frame, not the sheet frame) keep the per-cell
    # ``_evaluate`` path — with subsets built ONLY for the predicates THEIR
    # cells use. Building them for the whole spec is exactly the per-predicate
    # frame copying pass 1 exists to avoid.
    if deferred:
        subsets = _predicate_subsets(spec, data, prior_df, [job[1] for job in deferred])
        for key, cell, binding, cell_empty_as_none in deferred:
            cell_data, cell_prior = subsets[cell.predicate]
            computed[key] = _evaluate(
                binding, cell_data, cell_prior, ctx, empty_as_none=cell_empty_as_none
            )

    # Pass 2: formulas, over the computed cells (own-row column ref first,
    # then own-column row ref — see Formula's resolution rule).
    for row_ref, col_ref, formula in formulas:
        inputs: dict[str, float | None] = {}
        for ref in formula.refs:
            if (row_ref, ref) in computed:
                inputs[ref] = computed[(row_ref, ref)]
            elif (ref, col_ref) in computed:
                inputs[ref] = computed[(ref, col_ref)]
            else:
                raise KeyError(
                    f"template {spec.name!r}: formula cell ({row_ref}, {col_ref}) "
                    f"references {ref!r}, which is not a computed cell (a formula "
                    "referencing another formula is unsupported)"
                )
        computed[(row_ref, col_ref)] = formula.fn(inputs, prior_available)

    rows_out: list[dict[str, object]] = []
    for row_def in spec.rows:
        row: dict[str, object] = {"row_ref": row_def.ref, "row_name": row_def.name}
        for col_ref in spec.column_refs:
            row[col_ref] = computed[(row_def.ref, col_ref)]
        rows_out.append(row)

    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "row_ref": pl.String,
        "row_name": pl.String,
    }
    schema.update(dict.fromkeys(spec.column_refs, pl.Float64))
    return pl.DataFrame(rows_out, schema=schema)


# =============================================================================
# Private helpers
# =============================================================================


def _narrow(data: pl.DataFrame, predicate: RowPredicate | None) -> pl.DataFrame:
    return predicate.apply(data) if predicate is not None else data


def subset_rows(
    frame: pl.DataFrame, preds: Mapping[str, RowPredicate | None]
) -> dict[str, pl.DataFrame]:
    """Batched ``pred.apply(frame)`` for a keyed predicate family.

    All masks compile against ``frame``'s columns and evaluate in ONE
    ``select``; each subset is then a boolean-mask filter (~10x cheaper
    than per-predicate expression filters). ``None`` predicates (and
    constraint-free ones) share the whole frame. Same row sets as
    per-predicate ``apply`` — the module post-passes' batched kernel.
    """
    keys = list(preds)
    exprs: list[pl.Expr] = []
    free: list[bool] = []
    cols = set(frame.columns)
    for i, key in enumerate(keys):
        pred = preds[key]
        expr = None if pred is None else pred._compile(cols)  # noqa: SLF001 - same-module kernel
        free.append(expr is None)
        exprs.append((pl.lit(value=True) if expr is None else expr).alias(f"__mask_{i}"))
    mask_frame = frame.select(exprs) if exprs else None
    out: dict[str, pl.DataFrame] = {}
    for i, key in enumerate(keys):
        if free[i] or mask_frame is None:
            out[key] = frame
        else:
            out[key] = frame.filter(mask_frame[f"__mask_{i}"])
    return out


def matched_counts(frame: pl.DataFrame, preds: Mapping[str, RowPredicate | None]) -> dict[str, int]:
    """Batched ``pred.apply(frame).height`` — one select of mask sums,
    no filters at all (the empty-row post-passes only need counts)."""
    keys = list(preds)
    cols = set(frame.columns)
    exprs: list[pl.Expr] = []
    free: list[bool] = []
    for i, key in enumerate(keys):
        pred = preds[key]
        expr = None if pred is None else pred._compile(cols)  # noqa: SLF001 - same-module kernel
        free.append(expr is None)
        exprs.append(
            (pl.lit(value=True) if expr is None else expr).cast(pl.UInt32).sum().alias(f"__n_{i}")
        )
    counts = frame.select(exprs) if exprs else None
    out: dict[str, int] = {}
    for i, key in enumerate(keys):
        if free[i] or counts is None:
            out[key] = frame.height
        else:
            value = counts[f"__n_{i}"][0]
            out[key] = int(value) if value is not None else 0
    return out


def _predicate_subsets(
    spec: TemplateSpec,
    data: pl.DataFrame,
    prior_df: pl.DataFrame | None,
    cells: Iterable[CellSpec] | None = None,
) -> dict[RowPredicate | None, tuple[pl.DataFrame, pl.DataFrame | None]]:
    """Build the (data, prior) subset per DISTINCT cell predicate.

    All predicate expressions compile against the frame's own columns
    (tolerant terms compile per frame — a column present on ``data`` but
    absent on the prior frame still matches nothing there) and evaluate in
    ONE ``select`` per frame; subsets are then boolean-mask filters. A
    constraint-free predicate shares the whole frame.

    ``cells`` restricts the family to some of the spec's cells; the executor
    passes only the cells it could not batch, because materialising a subset
    per predicate in the WHOLE spec is the cost the batched pass exists to
    avoid. None = every cell in the spec.
    """
    subsets: dict[RowPredicate | None, tuple[pl.DataFrame, pl.DataFrame | None]] = {
        None: (data, prior_df)
    }
    preds: list[RowPredicate] = []
    for cell in spec.cells.values() if cells is None else cells:
        if isinstance(cell.binding, Formula) or cell.predicate is None:
            continue
        if cell.predicate not in subsets:
            subsets[cell.predicate] = (data, prior_df)  # placeholder, filled below
            preds.append(cell.predicate)
    if not preds:
        return subsets

    def masks_for(frame: pl.DataFrame) -> list[pl.Series | None]:
        cols = set(frame.columns)
        exprs: list[pl.Expr] = []
        free: list[bool] = []
        for i, pred in enumerate(preds):
            expr = pred._compile(cols)  # noqa: SLF001 - same-module kernel
            free.append(expr is None)
            exprs.append((pl.lit(value=True) if expr is None else expr).alias(f"__mask_{i}"))
        mask_frame = frame.select(exprs)
        return [None if free[i] else mask_frame[f"__mask_{i}"] for i in range(len(preds))]

    data_masks = masks_for(data)
    prior_masks = masks_for(prior_df) if prior_df is not None else None
    for i, pred in enumerate(preds):
        mask = data_masks[i]
        narrowed = data if mask is None else data.filter(mask)
        if prior_df is None:
            narrowed_prior = None
        else:
            prior_mask = prior_masks[i] if prior_masks is not None else None
            narrowed_prior = prior_df if prior_mask is None else prior_df.filter(prior_mask)
        subsets[pred] = (narrowed, narrowed_prior)
    return subsets


def _conj(expr: pl.Expr | None, term: pl.Expr) -> pl.Expr:
    return term if expr is None else expr & term


# =============================================================================
# Pass 1 — the batched (one select per sheet) evaluator
# =============================================================================

# One cell of work: its (row_ref, col_ref) key, its spec, its binding already
# narrowed away from ``Formula`` (pass 2 owns those), and the resolved
# per-cell empty-cell policy (template policy unless the cell overrides it).
type _CellJob = tuple[tuple[str, str], CellSpec, _EvaluableBinding, bool]
# Reads one cell's value back off the single one-row aggregation result.
type _Combiner = Callable[[Mapping[str, object]], float | None]


def _evaluate_batched(
    jobs: list[_CellJob], data: pl.DataFrame
) -> tuple[dict[tuple[str, str], float | None], list[_CellJob]]:
    """Evaluate every IN-FRAME cell binding of a sheet in ONE ``select``.

    Each distinct cell predicate compiles to one boolean mask column (all of
    them in a single ``with_columns``), and each cell becomes one or more
    aggregation expressions filtered by its mask over the UNFILTERED frame.
    A sheet therefore costs one mask pass and one aggregation pass, rather
    than a physical subset copy per distinct predicate plus a
    plan-optimise-collect round trip per cell.

    Returns ``(computed, deferred)`` — ``deferred`` being the cells whose
    binding is not an in-frame aggregation (``SideContext`` / ``PriorPeriod``,
    which read the context and the prior frame), left to the caller's
    per-cell ``_evaluate`` path.
    """
    cols = set(data.columns)
    masks: dict[RowPredicate | None, str | None] = {}
    mask_exprs: list[pl.Expr] = []
    counts: dict[str | None, str] = {}
    aggs: list[pl.Expr] = []
    combiners: list[tuple[tuple[str, str], _Combiner]] = []
    computed: dict[tuple[str, str], float | None] = {}
    deferred: list[_CellJob] = []

    for key, cell, binding, cell_empty_as_none in jobs:
        if isinstance(binding, SideContext | PriorPeriod):
            deferred.append((key, cell, binding, cell_empty_as_none))
            continue
        if cell.predicate not in masks:
            # Same _compile as _predicate_subsets: strict sealed-column terms,
            # tolerant equals/between compiled against THIS frame's columns.
            expr = None if cell.predicate is None else cell.predicate._compile(cols)  # noqa: SLF001 - same-module kernel
            if expr is None:
                masks[cell.predicate] = None  # constraint-free: no filter at all
            else:
                name = f"__cellspec_m{len(mask_exprs)}"
                mask_exprs.append(expr.alias(name))
                masks[cell.predicate] = name
        combine = _cell_aggregation(
            binding,
            masks[cell.predicate],
            cols,
            f"__cellspec_v{len(combiners)}",
            aggs,
            counts,
            empty_as_none=cell_empty_as_none,
        )
        if combine is None:
            deferred.append((key, cell, binding, cell_empty_as_none))
            continue
        combiners.append((key, combine))

    if not aggs:
        # Every cell resolved to a constant (absent columns) or deferred.
        row: Mapping[str, object] = {}
    else:
        masked = data.with_columns(mask_exprs) if mask_exprs else data
        row = masked.select(aggs).row(0, named=True)
    for key, combine in combiners:
        computed[key] = combine(row)
    return computed, deferred


# The binding -> expression mapping, derived line-by-line against ``_evaluate``
# (which sees a physically filtered subset where this sees mask + unfiltered
# frame; ``n`` below is the mask's row count, i.e. the old ``data.height``).
# ``ean`` is the resolved per-cell ``empty_as_none``; ``empty`` is
# ``None if ean else 0.0``.
#
# | binding             | absent column        | n == 0            | otherwise            |
# |---------------------|----------------------|-------------------|----------------------|
# | Sum                 | None (col_sum's own  | None if ean       | sum(fill_null(0))    |
# |                     | absent-col contract, | else 0.0          |                      |
# |                     | NOT the empty policy)|                   |                      |
# | SafeSum             | `empty` when NO col  | 0.0 (sum of the   | sum over the PRESENT |
# |                     | is present           | present cols)     | cols, in spec order  |
# | Mean                | `empty`              | `empty` (mean of  | mean(col) * scale    |
# |                     |                      | nothing is null)  | (nulls skipped)      |
# | WeightedAvg         | `empty` (either col) | `empty` (weight   | sum(col*w)/sum(w)    |
# |                     |                      | sum is 0.0)       | * scale; `empty` on  |
# |                     |                      |                   | an exactly-0 weight  |
# | Ratio               | `empty` — col_sum    | `empty` (the      | num/den * scale;     |
# |                     | returns None, which  | denominator sums  | `empty` on an        |
# |                     | _evaluate's guard    | to 0.0)           | exactly-0 den        |
# |                     | turns into `empty`   |                   |                      |
# | Count(distinct)     | `empty`              | 0.0               | n_unique (nulls      |
# |                     |                      |                   | count as one value)  |
# | Count               | n/a                  | 0.0               | float(n)             |
# | FirstNonNull        | None (never the      | None              | first non-null, or   |
# |                     | empty policy)        |                   | None if all null     |
# | SideContext         | deferred to _evaluate — reads the ReportingContext      |
# | PriorPeriod         | deferred to _evaluate — reads the prior-period subset   |
#
# Note the three kinds that do NOT take the empty-cell policy on an empty
# subset: SafeSum (0.0 once any named column is present), Count (0.0), and
# FirstNonNull (None). Sum and Ratio differ from each other on an ABSENT
# column — Sum is unconditionally None there, Ratio takes `empty`.
def _cell_aggregation(  # noqa: PLR0911 - one return per binding kind, mirroring _evaluate
    binding: ValueBinding,
    mask: str | None,
    cols: set[str],
    alias: str,
    aggs: list[pl.Expr],
    counts: dict[str | None, str],
    *,
    empty_as_none: bool,
) -> _Combiner | None:
    """Append ``binding``'s aggregation expressions to ``aggs`` and return the
    combiner reading its cell value back. None = not an in-frame aggregation.
    """

    def over_mask(expr: pl.Expr) -> pl.Expr:
        return expr if mask is None else expr.filter(pl.col(mask))

    empty: float | None = None if empty_as_none else 0.0

    if isinstance(binding, Sum):
        if binding.col not in cols:
            return lambda _row: None
        aggs.append(over_mask(pl.col(binding.col).fill_null(0.0)).sum().alias(alias))
        if not empty_as_none:
            return lambda row: _zeroed(row[alias])
        n_alias = _count_alias(mask, counts, aggs)
        return lambda row: None if _as_int(row[n_alias]) == 0 else _zeroed(row[alias])

    if isinstance(binding, SafeSum):
        names: list[str] = []
        for i, col in enumerate(binding.cols):
            if col in cols:
                names.append(f"{alias}s{i}")
                aggs.append(over_mask(pl.col(col).fill_null(0.0)).sum().alias(names[-1]))
        if not names:
            return lambda _row: empty
        return lambda row: float(sum(_zeroed(row[name]) for name in names))

    if isinstance(binding, Mean):
        if binding.col not in cols:
            return lambda _row: empty
        aggs.append(over_mask(pl.col(binding.col)).mean().alias(alias))

        def mean(row: Mapping[str, object]) -> float | None:
            value = _as_float(row[alias])
            return empty if value is None else value * binding.scale

        return mean

    if isinstance(binding, WeightedAvg):
        if binding.col not in cols or binding.weight not in cols:
            return lambda _row: empty
        weight = pl.col(binding.weight).fill_null(0.0)
        aggs.append(over_mask(pl.col(binding.col).fill_null(0.0) * weight).sum().alias(f"{alias}n"))
        aggs.append(over_mask(weight).sum().alias(f"{alias}d"))

        def weighted_avg(row: Mapping[str, object]) -> float | None:
            total = _as_float(row[f"{alias}d"])
            if not total:  # exact zero — an all-zero weight vector has no average
                return empty
            return _zeroed(row[f"{alias}n"]) / total * binding.scale

        return weighted_avg

    if isinstance(binding, Ratio):
        if binding.numerator not in cols or binding.denominator not in cols:
            return lambda _row: empty
        aggs.append(over_mask(pl.col(binding.numerator).fill_null(0.0)).sum().alias(f"{alias}n"))
        aggs.append(over_mask(pl.col(binding.denominator).fill_null(0.0)).sum().alias(f"{alias}d"))

        def ratio(row: Mapping[str, object]) -> float | None:
            den = _as_float(row[f"{alias}d"])
            if not den:  # exact zero — ratio undefined (and the empty-subset case)
                return empty
            return _zeroed(row[f"{alias}n"]) / den * binding.scale

        return ratio

    if isinstance(binding, Count):
        if not binding.distinct:
            n_alias = _count_alias(mask, counts, aggs)
            return lambda row: float(_as_int(row[n_alias]))
        if binding.col not in cols:
            return lambda _row: empty
        aggs.append(over_mask(pl.col(binding.col)).n_unique().alias(alias))
        return lambda row: float(_as_int(row[alias]))

    if isinstance(binding, FirstNonNull):
        if binding.col not in cols:
            return lambda _row: None
        aggs.append(over_mask(pl.col(binding.col)).drop_nulls().first().alias(alias))
        return lambda row: _as_float(row[alias])

    return None


def _count_alias(mask: str | None, counts: dict[str | None, str], aggs: list[pl.Expr]) -> str:
    """The row count behind ``mask`` — the batched form of ``data.height`` on
    the old physical subset. One per DISTINCT mask, shared by every cell that
    needs it. A null mask value counts as False, exactly as ``filter`` drops
    it."""
    alias = counts.get(mask)
    if alias is None:
        alias = f"__cellspec_n{len(counts)}"
        counts[mask] = alias
        aggs.append((pl.len() if mask is None else pl.col(mask).sum()).alias(alias))
    return alias


def _as_float(value: object) -> float | None:
    return None if value is None else float(cast("float", value))


def _zeroed(value: object) -> float:
    """A summed aggregation, with the null of an empty/absent frame as 0.0 —
    the ``float(series.fill_null(0.0).sum())`` the per-cell path returns."""
    return 0.0 if value is None else float(cast("float", value))


def _as_int(value: object) -> int:
    return 0 if value is None else int(cast("int", value))


def _evaluate(
    binding: _EvaluableBinding,
    data: pl.DataFrame,
    prior: pl.DataFrame | None,
    ctx: ReportingContext | None,
    *,
    empty_as_none: bool,
) -> float | None:
    cols = set(data.columns)
    if isinstance(binding, PriorPeriod):
        if prior is None:
            return None
        return _evaluate(binding.binding, prior, None, ctx, empty_as_none=empty_as_none)
    if isinstance(binding, SideContext):
        value = ctx.side_value(binding.key) if ctx is not None else None
        return value * binding.scale if value is not None else None
    if isinstance(binding, FirstNonNull):
        if binding.col not in cols or data.height == 0:
            return None
        first = data.select(pl.col(binding.col).drop_nulls().first()).item()
        return float(first) if first is not None else None
    if isinstance(binding, Sum):
        return col_sum(data, cols, binding.col, empty_as_none=empty_as_none)
    if isinstance(binding, SafeSum):
        value = safe_sum_or_none(data, cols, *binding.cols)
        if value is not None:
            return value
        return None if empty_as_none else 0.0
    if isinstance(binding, Mean):
        if binding.col not in cols or data.height == 0:
            return None if empty_as_none else 0.0
        mean = data[binding.col].mean()
        if mean is None:
            return None if empty_as_none else 0.0
        return float(cast("float", mean)) * binding.scale
    if isinstance(binding, WeightedAvg):
        if binding.col not in cols or binding.weight not in cols or data.height == 0:
            return None if empty_as_none else 0.0
        weights = data[binding.weight].fill_null(0.0)
        total = float(weights.sum())
        if not total:  # exact zero — an all-zero weight vector has no average
            return None if empty_as_none else 0.0
        weighted = float((data[binding.col].fill_null(0.0) * weights).sum())
        return weighted / total * binding.scale
    if isinstance(binding, Ratio):
        num = col_sum(data, cols, binding.numerator, empty_as_none=empty_as_none)
        den = col_sum(data, cols, binding.denominator, empty_as_none=empty_as_none)
        if num is None or den is None or not den:  # exact zero — ratio undefined
            return None if empty_as_none else 0.0
        return num / den * binding.scale
    if isinstance(binding, Count):
        if binding.distinct:
            if binding.col not in cols:
                return None if empty_as_none else 0.0
            return float(data[binding.col].n_unique())
        return float(data.height)
    raise TypeError(f"unknown value binding: {type(binding).__name__}")
