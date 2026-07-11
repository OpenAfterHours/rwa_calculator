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
    from collections.abc import Callable, Mapping

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


# =============================================================================
# Row predicates — over the canonical reporting-ledger columns only
# =============================================================================


@dataclass(frozen=True)
class RowPredicate:
    """A conjunctive row filter over the sealed reporting-ledger columns.

    Post-substitution fields (``classes`` / ``method``) and origin fields
    (``classes_origin`` / ``approaches_origin``) are both available so each
    template keys on its RECORDED basis (COREP C 07.00 keys origin; the
    post-substitution retargets are per-template recorded decisions — plan
    F3/F4). Unset fields (empty tuple / None) impose no constraint.
    """

    classes: tuple[str, ...] = ()
    classes_origin: tuple[str, ...] = ()
    method: str | None = None
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

    # Pass 1: every non-formula cell, keyed (row_ref, col_ref).
    computed: dict[tuple[str, str], float | None] = {}
    formulas: list[tuple[str, str, Formula]] = []
    for row_def in spec.rows:
        for col_ref in spec.column_refs:
            cell = spec.cells.get((row_def.ref, col_ref))
            if cell is None:
                computed[(row_def.ref, col_ref)] = empty_default
                continue
            if isinstance(cell.binding, Formula):
                formulas.append((row_def.ref, col_ref, cell.binding))
                continue
            cell_data = _narrow(data, cell.predicate)
            cell_prior = _narrow(prior_df, cell.predicate) if prior_df is not None else None
            cell_empty_as_none = (
                empty_as_none if cell.empty_cell is None else cell.empty_cell == "null"
            )
            computed[(row_def.ref, col_ref)] = _evaluate(
                cell.binding, cell_data, cell_prior, ctx, empty_as_none=cell_empty_as_none
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


def _conj(expr: pl.Expr | None, term: pl.Expr) -> pl.Expr:
    return term if expr is None else expr & term


def _evaluate(
    binding: Sum
    | SafeSum
    | Mean
    | WeightedAvg
    | Ratio
    | Count
    | FirstNonNull
    | SideContext
    | PriorPeriod,
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
        if total == 0.0:
            return None if empty_as_none else 0.0
        weighted = float((data[binding.col].fill_null(0.0) * weights).sum())
        return weighted / total * binding.scale
    if isinstance(binding, Ratio):
        num = col_sum(data, cols, binding.numerator, empty_as_none=empty_as_none)
        den = col_sum(data, cols, binding.denominator, empty_as_none=empty_as_none)
        if num is None or den is None or den == 0.0:
            return None if empty_as_none else 0.0
        return num / den * binding.scale
    if isinstance(binding, Count):
        if binding.distinct:
            if binding.col not in cols:
                return None if empty_as_none else 0.0
            return float(data[binding.col].n_unique())
        return float(data.height)
    raise TypeError(f"unknown value binding: {type(binding).__name__}")
