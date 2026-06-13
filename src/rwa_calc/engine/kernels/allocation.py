"""
Multi-level beneficiary allocation kernel.

Pipeline position:
    Cross-cutting engine kernel — consumed by the CRM stage (provisions,
    guarantees, collateral lookup builders, collateral-link demand pooling)
    and the hierarchy stage (property coverage, LTV metadata). Not a stage
    itself; it never reads regulatory values and never materialises.

Key responsibilities:
- Classify CRM items (collateral / provisions / guarantees) into beneficiary
  levels (direct / facility / counterparty) and aggregate per beneficiary.
- Pro-rata allocate level aggregates onto exposures (annotate direction) or
  expand an item table down to exposure-level rows (expand direction).
- Build per-level exposure lookups: direct per-row select, facility
  ancestor-cascade aggregate, counterparty aggregate; plus the 3-join +
  beneficiary_type-switched value coalesce.
- Precedence (coalesce, first-non-null) resolution of per-level attribute
  lookups (the LTV / property-metadata sibling of pro-rata allocation).

Drift between the historical copies is regulatorily load-bearing and is
therefore expressed as PARAMETERS — never silently unified:

================== ===================== ==================== ====================
Drift axis         CRM collateral (1)    Provisions (2)       Guarantees (3)
================== ===================== ==================== ====================
pro-rata basis     ead_for_crm           pre-CCF synthetic    ead_after_collateral
                   (Art. 223(4))         weight (Art. 111)    (Art. 213-217)
facility level     ancestor cascade      ancestor cascade     ancestor cascade
unknown/null type  -> direct             dropped              dropped
weight mechanics   pool-gated lookups    group_by + join      group_by + join
direction          lookup builders       annotate             expand
================== ===================== ==================== ====================

================== ============================ =============================
Drift axis         Property coverage (5)        LTV metadata (sibling)
================== ============================ =============================
pro-rata basis     drawn.clip(0) (Art. 147)     n/a (precedence coalesce)
facility level     immediate parent only        immediate parent only
unknown/null type  -> direct                    dropped (incl. contingent)
weight mechanics   .over() window               n/a (unique keep="first")
direction          annotate                     attribute precedence
================== ============================ =============================

FCSM (copy 4, ``engine/crm/simple_method.py``) remains UNCONVERTED: it is
level-BLIND — one aggregate keyed by ``beneficiary_reference`` alone, joined
under three different exposure keys — which double-counts when reference
namespaces collide. Routing it through this level-aware kernel would change
results for such data; converting it requires a signed-off behaviour change.

Arithmetic form is deliberately tied to the weight mechanics so each copy's
exact float associativity is preserved:

- ``weights="join"`` and cascade levels compute ``value * basis / total``
  (the provisions form);
- ``weights="window"`` levels and :func:`expand_items_pro_rata` compute the
  ratio ``weight = basis / total`` first, then multiply (the property /
  guarantee form).

Zero-denominator pools yield weight 0.0 everywhere (value strands — matching
every copy). :func:`expand_items_pro_rata` uses an INNER join, so items whose
group has no exposures vanish silently with no CalculationError (preserved
guarantee-copy behaviour). :func:`level_attribute_lookup` deduplicates with
``unique(keep="first")`` and NO preceding sort — tie-breaking between
duplicate beneficiary rows is engine-order-dependent (preserved LTV-sibling
behaviour, documented rather than fixed in the zero-behaviour-change slice).

References:
- CRR Art. 111: provision allocation basis (pre-CCF weight)
- CRR Art. 147: "total amount owed" — drawn-only property-coverage basis
- CRR Art. 213-217: unfunded credit protection allocation
- CRR Art. 223(4): CCF=100% CRM valuation basis (ead_for_crm)
- CRR Art. 230-231: allocation of collateral across exposures
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import polars as pl

from rwa_calc.data.schemas import DIRECT_BENEFICIARY_TYPES
from rwa_calc.engine.utils import partition_by_nullable

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

logger = logging.getLogger(__name__)

#: Sentinel for "no fill_null default" in attribute precedence specs.
NO_DEFAULT: Any = object()

#: Weight mechanics for a pro-rata level. ``"join"`` builds group_by totals
#: and joins them back (CRM-stage form); ``"window"`` computes the total with
#: an ``.over()`` window guarded by ``partition_by_nullable`` (hierarchy-stage
#: form, avoids plan-tree branching).
WeightMechanics = Literal["join", "window"]

_LEVEL_COLUMN = "_kl_level"
_BASIS_COLUMN = "_kl_basis"


@dataclass(frozen=True)
class LevelSpec:
    """One beneficiary level of a multi-level allocation.

    Attributes:
        name: Level label matched against the caller's ``level_of``
            expression output (e.g. ``"direct"`` / ``"facility"`` /
            ``"counterparty"``).
        exposure_key: Exposure-side join key for this level
            (``exposure_reference`` / ``parent_facility_reference`` /
            ``counterparty_reference``).
        pro_rata: ``False`` for the direct level — a 1:1 join with no
            weighting.
        cascade: ``True`` for the facility ancestor cascade — exposures are
            exploded over ``ancestor_facilities`` (falling back to the
            1-element ``[parent]`` list) so an item pledged at any ancestor
            allocates over that ancestor's whole descendant subtree, with
            contributions stacking across ancestor levels.
        weights: Weight mechanics for non-cascade pro-rata levels (see
            :data:`WeightMechanics`). Ignored when ``cascade`` is set
            (cascade always uses the explode -> group_by -> join form).
    """

    name: str
    exposure_key: str
    pro_rata: bool = True
    cascade: bool = False
    weights: WeightMechanics = "join"


def beneficiary_level_expr(
    bt_col: str = "beneficiary_type",
    *,
    unknown: str | None = "direct",
) -> pl.Expr:
    """Classify ``beneficiary_type`` into direct / facility / counterparty.

    ``unknown`` controls the null / unrecognised-type fallback — a load-bearing
    drift axis between the copies:

    - ``"direct"`` (default): collateral (copy 1) and property coverage
      (copy 5) treat unknown beneficiary types as direct.
    - ``None``: provisions (copy 2) and guarantees (copy 3) DROP rows with
      null / unknown beneficiary types (the null label matches no level).
    """
    bt_lower = pl.col(bt_col).str.to_lowercase()
    fallback = pl.lit(unknown) if unknown is not None else pl.lit(None, dtype=pl.String)
    return (
        pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
        .then(pl.lit("direct"))
        .when(bt_lower == "facility")
        .then(pl.lit("facility"))
        .when(bt_lower == "counterparty")
        .then(pl.lit("counterparty"))
        .otherwise(fallback)
    )


def allocate_multi_level(
    exposures: pl.LazyFrame,
    items: pl.LazyFrame,
    *,
    values: Mapping[str, pl.Expr],
    basis: pl.Expr,
    level_of: pl.Expr,
    levels: Sequence[LevelSpec],
    item_key: str = "beneficiary_reference",
    exposure_id: str = "exposure_reference",
    flag_values: Mapping[str, pl.Expr] | None = None,
    any_positive: Mapping[str, str] | None = None,
) -> pl.LazyFrame:
    """Annotate ``exposures`` with multi-level pro-rata item allocations.

    One conditional ``group_by([level, item_key])`` aggregates every item
    metric per beneficiary; each level is then joined onto ``exposures`` at
    its own key and combined additively (values), by OR (``flag_values``),
    or by any-level-positive OR (``any_positive``).

    Per-copy parameterisation (Phase 4 Slice 6):

    - Provisions (copy 2): ``values={"provision_allocated": amount.sum()}``,
      ``basis`` = pre-CCF synthetic weight, levels = direct / facility
      cascade / counterparty ``"join"``, ``level_of`` with ``unknown=None``.
    - Property coverage (copy 5): residential / all-property sums,
      ``basis = total_exposure_amount``, immediate-parent ``"window"``
      levels, ``level_of`` with ``unknown="direct"``.

    Args:
        exposures: Exposure frame to annotate (returned with the output
            columns appended; all kernel scratch is dropped).
        items: Item table carrying ``item_key`` and the value columns.
        values: Output alias -> item-side aggregate expression (evaluated in
            the per-beneficiary group context, e.g. ``pl.col("amount").sum()``).
        basis: Exposure-side pro-rata basis expression.
        level_of: Item-side expression labelling each row with a level name
            (see :func:`beneficiary_level_expr`); rows whose label matches no
            ``LevelSpec.name`` are dropped.
        levels: Level specifications, in combine order.
        item_key: Item-side beneficiary reference column.
        exposure_id: Exposure identity key (cascade re-aggregation grain).
        flag_values: Output alias -> item-side Boolean aggregate (e.g.
            ``expr.any()``); combined across levels by OR, never weighted.
        any_positive: Output alias -> ``values`` alias; emits an OR across
            levels of "raw level aggregate > 0" (per-exposure allocated sum
            for cascade levels).

    Returns:
        ``exposures`` with one column per ``values`` / ``any_positive`` /
        ``flag_values`` alias appended, in that order.
    """
    flags = dict(flag_values or {})
    presence = dict(any_positive or {})

    # --- 1. One conditional aggregate per (level, beneficiary) ---
    agg_exprs = [expr.alias(f"_kl_v_{alias}") for alias, expr in values.items()]
    agg_exprs += [expr.alias(f"_kl_f_{alias}") for alias, expr in flags.items()]
    item_agg = (
        items.with_columns(level_of.alias(_LEVEL_COLUMN))
        .group_by([_LEVEL_COLUMN, item_key])
        .agg(agg_exprs)
    )

    exposures = exposures.with_columns(basis.alias(_BASIS_COLUMN))
    scratch: list[str] = [_BASIS_COLUMN]

    exp_columns: Collection[str] = (
        exposures.collect_schema().names() if any(lv.cascade for lv in levels) else ()
    )

    # Window totals are computed BEFORE the level joins (property-coverage
    # form): the joins are row-preserving, so the totals are identical, and
    # keeping them up front mirrors the original plan shape.
    window_total_exprs: list[pl.Expr] = []
    for lv in levels:
        if lv.pro_rata and not lv.cascade and lv.weights == "window":
            total_col = f"_kl_total_{lv.name}"
            window_total_exprs.append(
                partition_by_nullable(
                    pl.col(_BASIS_COLUMN).sum().over(lv.exposure_key),
                    lv.exposure_key,
                    pl.col(_BASIS_COLUMN),
                ).alias(total_col)
            )
            scratch.append(total_col)
    if window_total_exprs:
        exposures = exposures.with_columns(window_total_exprs)

    # "join"-mechanics totals read the pre-join frame: the level joins are
    # row-preserving left joins, so the group totals are identical.
    base_frame = exposures

    value_terms: dict[str, list[pl.Expr]] = {alias: [] for alias in values}
    flag_terms: dict[str, list[pl.Expr]] = {alias: [] for alias in flags}
    presence_terms: dict[str, list[pl.Expr]] = {out: [] for out in presence}
    weight_exprs: list[pl.Expr] = []

    # --- 2. Per-level joins and contribution terms ---
    for lv in levels:
        v_cols = {alias: f"_kl_v_{alias}_{lv.name}" for alias in values}
        f_cols = {alias: f"_kl_f_{alias}_{lv.name}" for alias in flags}
        renames = {f"_kl_v_{alias}": col for alias, col in v_cols.items()}
        renames |= {f"_kl_f_{alias}": col for alias, col in f_cols.items()}
        level_items = (
            item_agg.filter(pl.col(_LEVEL_COLUMN) == lv.name).drop(_LEVEL_COLUMN).rename(renames)
        )

        if lv.cascade:
            exposures = _join_cascade_allocation(
                exposures,
                base_frame,
                level_items,
                lv,
                exp_columns,
                values=values,
                flags=flags,
                item_key=item_key,
                exposure_id=exposure_id,
            )
            for alias in values:
                alloc_col = f"_kl_a_{alias}_{lv.name}"
                value_terms[alias].append(pl.col(alloc_col).fill_null(0.0))
                scratch.append(alloc_col)
            for alias in flags:
                alloc_col = f"_kl_af_{alias}_{lv.name}"
                flag_terms[alias].append(pl.col(alloc_col).fill_null(False))
                scratch.append(alloc_col)
            for out, src in presence.items():
                presence_terms[out].append(pl.col(f"_kl_a_{src}_{lv.name}").fill_null(0.0) > 0)
            continue

        exposures = exposures.join(
            level_items, left_on=lv.exposure_key, right_on=item_key, how="left"
        )
        scratch.extend(v_cols.values())
        scratch.extend(f_cols.values())

        if not lv.pro_rata:
            for alias in values:
                value_terms[alias].append(pl.col(v_cols[alias]).fill_null(0.0))
        elif lv.weights == "window":
            total_col = f"_kl_total_{lv.name}"
            weight_col = f"_kl_w_{lv.name}"
            weight_exprs.append(
                pl.when(pl.col(total_col) > 0)
                .then(pl.col(_BASIS_COLUMN) / pl.col(total_col))
                .otherwise(pl.lit(0.0))
                .alias(weight_col)
            )
            scratch.append(weight_col)
            for alias in values:
                value_terms[alias].append(pl.col(v_cols[alias]).fill_null(0.0) * pl.col(weight_col))
        else:
            total_col = f"_kl_total_{lv.name}"
            totals = base_frame.group_by(lv.exposure_key).agg(
                pl.col(_BASIS_COLUMN).sum().alias(total_col)
            )
            exposures = exposures.join(totals, on=lv.exposure_key, how="left")
            scratch.append(total_col)
            for alias in values:
                value_terms[alias].append(
                    pl.when(pl.col(total_col) > 0)
                    .then(
                        pl.col(v_cols[alias]).fill_null(0.0)
                        * pl.col(_BASIS_COLUMN)
                        / pl.col(total_col)
                    )
                    .otherwise(pl.lit(0.0))
                )

        for alias in flags:
            flag_terms[alias].append(pl.col(f_cols[alias]).fill_null(False))
        for out, src in presence.items():
            presence_terms[out].append(pl.col(v_cols[src]).fill_null(0.0) > 0)

    if weight_exprs:
        exposures = exposures.with_columns(weight_exprs)

    # --- 3. Combine across levels (additive / any-positive / OR) ---
    out_exprs: list[pl.Expr] = []
    for alias in values:
        out_exprs.append(_sum_terms(value_terms[alias]).alias(alias))
    for out in presence:
        out_exprs.append(_or_terms(presence_terms[out]).alias(out))
    for alias in flags:
        out_exprs.append(_or_terms(flag_terms[alias]).alias(alias))
    exposures = exposures.with_columns(out_exprs)

    return exposures.drop(scratch)


def expand_items_pro_rata(
    items: pl.LazyFrame,
    exposures: pl.LazyFrame,
    *,
    group_key: str,
    basis: pl.Expr,
    scale_columns: Sequence[str],
    item_key: str = "beneficiary_reference",
    exposure_id: str = "exposure_reference",
    rewrite_type: str | None = "loan",
) -> pl.LazyFrame:
    """Expand an item table to exposure-level rows, pro-rata by ``basis``.

    The expand direction of the kernel (guarantees, copy 3): instead of
    annotating exposures, each item row is replicated per exposure in its
    ``group_key`` group, with each ``scale_columns`` value multiplied by the
    exposure's ``basis / group total`` weight, ``item_key`` rewritten to the
    exposure reference, and ``beneficiary_type`` rewritten to
    ``rewrite_type``.

    Preserved copy-3 semantics: the items -> weights join is INNER, so an
    item whose group has zero or missing exposures vanishes silently (no
    CalculationError); a zero/negative group total yields weight 0.0 (the
    item value strands on rows that all carry 0).

    Args:
        items: Item table (e.g. facility-level guarantees).
        exposures: Exposure frame carrying ``exposure_id``, ``group_key``
            and the ``basis`` inputs. For the facility cascade, pass the
            pre-exploded membership frame from
            :func:`explode_facility_membership` and its alias as
            ``group_key``.
        group_key: Exposure-side grouping key matched against ``item_key``.
        basis: Exposure-side pro-rata basis expression.
        scale_columns: Item columns multiplied by the weight (in place).
        item_key: Item-side beneficiary reference column (rewritten to the
            exposure reference on output).
        exposure_id: Exposure identity column.
        rewrite_type: Value written to ``beneficiary_type`` on the expanded
            rows (``None`` leaves the column untouched).

    Returns:
        Expanded item rows in the original item column shape.
    """
    level_exposures = exposures.select(
        pl.col(exposure_id), pl.col(group_key), basis.alias(_BASIS_COLUMN)
    )

    totals = level_exposures.group_by(group_key).agg(pl.col(_BASIS_COLUMN).sum().alias("_kl_total"))

    weighted = (
        level_exposures.join(totals, on=group_key, how="left")
        .with_columns(
            pl.when(pl.col("_kl_total") > 0)
            .then(pl.col(_BASIS_COLUMN) / pl.col("_kl_total"))
            .otherwise(pl.lit(0.0))
            .alias("_kl_weight"),
        )
        .select(exposure_id, group_key, "_kl_weight")
    )

    rewrites: list[pl.Expr] = [
        (pl.col(col) * pl.col("_kl_weight")).alias(col) for col in scale_columns
    ]
    rewrites.append(pl.col(exposure_id).alias(item_key))
    if rewrite_type is not None:
        rewrites.append(pl.lit(rewrite_type).alias("beneficiary_type"))

    return (
        items.join(
            weighted,
            left_on=item_key,
            right_on=group_key,
            how="inner",
        )
        .with_columns(rewrites)
        .drop(exposure_id, "_kl_weight")
    )


# ---------------------------------------------------------------------------
# Facility ancestor membership
# ---------------------------------------------------------------------------


def ancestor_membership_expr(
    columns: Collection[str],
    parent_key: str = "parent_facility_reference",
) -> pl.Expr:
    """The facility-membership list: ``ancestor_facilities`` or ``[parent]``.

    The single source of the ``[parent]``-fallback expression that was
    previously duplicated across collateral, provisions, guarantees, and the
    processor lookup builders: when the HierarchyResolver's
    ``ancestor_facilities`` list column (parent + all ancestors up to root,
    incl. self) is absent, fall back to the 1-element immediate-parent list —
    identical to the legacy single-level behaviour.
    """
    if "ancestor_facilities" in columns:
        return pl.col("ancestor_facilities")
    return pl.concat_list(parent_key)


def explode_facility_membership(
    exposures: pl.LazyFrame,
    columns: Collection[str],
    *,
    alias: str,
    parent_key: str = "parent_facility_reference",
    keep: Sequence[pl.Expr | str] | None = None,
) -> pl.LazyFrame:
    """One row per (exposure, ancestor facility), null ancestors dropped.

    ``keep=None`` carries the full exposure frame through the explode
    (guarantee form); a ``keep`` projection selects only those columns plus
    the membership alias before exploding (provisions form).
    """
    membership = ancestor_membership_expr(columns, parent_key)
    if keep is not None:
        frame = exposures.select(*keep, membership.alias(alias))
    else:
        frame = exposures.with_columns(membership.alias(alias))
    return frame.explode(alias).filter(pl.col(alias).is_not_null())


# ---------------------------------------------------------------------------
# Per-level exposure lookups (collateral lookup-builder form, copy 1)
# ---------------------------------------------------------------------------


def direct_level_lookup(
    exposures: pl.LazyFrame,
    *,
    key: str,
    out_key: str,
    values: Sequence[pl.Expr],
) -> pl.LazyFrame:
    """Per-row direct-level lookup: one row per exposure, no aggregation."""
    return exposures.select([pl.col(key).alias(out_key), *values])


def grouped_level_lookup(
    exposures: pl.LazyFrame,
    *,
    key: str,
    out_key: str,
    values: Sequence[pl.Expr],
    membership: pl.Expr | None = None,
) -> pl.LazyFrame:
    """Aggregated level lookup, keyed by ``out_key``.

    With ``membership`` (a facility ancestor list expression, see
    :func:`ancestor_membership_expr`) the exposures are exploded over the
    membership first, so the aggregates for a facility cover its WHOLE
    descendant subtree — the ancestor-cascade form of the collateral lookup
    builders. Without it, a plain ``group_by(key)`` (counterparty form).
    """
    if membership is not None:
        return (
            exposures.with_columns(membership.alias(out_key))
            .explode(out_key)
            .filter(pl.col(out_key).is_not_null())
            .group_by(out_key)
            .agg(values)
        )
    return exposures.group_by(key).agg(values).rename({key: out_key})


def join_items_to_level_lookups(
    items: pl.LazyFrame,
    lookups: Sequence[tuple[pl.LazyFrame, str]],
    *,
    item_key: str = "beneficiary_reference",
) -> pl.LazyFrame:
    """Left-join each ``(lookup, right_key)`` onto ``items`` at ``item_key``."""
    for lookup, right_key in lookups:
        items = items.join(lookup, left_on=item_key, right_on=right_key, how="left")
    return items


def switch_by_beneficiary_level(
    direct: pl.Expr,
    facility: pl.Expr,
    counterparty: pl.Expr,
    default: pl.Expr,
    *,
    bt_col: str = "beneficiary_type",
) -> pl.Expr:
    """Select the level-appropriate value by ``beneficiary_type``.

    Null / unknown beneficiary types fall through to ``default`` (the
    collateral lookup-builder form — each output column carries its own
    neutral default: 0.0 EAD, null currency/maturity, False flags).
    """
    bt_lower = pl.col(bt_col).str.to_lowercase()
    return (
        pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
        .then(direct)
        .when(bt_lower == "facility")
        .then(facility)
        .when(bt_lower == "counterparty")
        .then(counterparty)
        .otherwise(default)
    )


# ---------------------------------------------------------------------------
# Attribute precedence (LTV-metadata sibling — coalesce, not pro-rata)
# ---------------------------------------------------------------------------


def level_attribute_lookup(
    items: pl.LazyFrame,
    *,
    filter_expr: pl.Expr,
    prefix: str,
    attributes: Sequence[tuple[str, pl.Expr]],
    key: str = "beneficiary_reference",
) -> pl.LazyFrame:
    """Single-level attribute lookup with ``{prefix}_``-aliased columns.

    Filters ``items`` to one beneficiary level, projects ``key`` as
    ``{prefix}_ref`` plus each ``(name, expr)`` attribute as
    ``{prefix}_{name}``, and deduplicates on the prefixed reference with
    ``unique(keep="first")`` so a beneficiary appearing twice does not
    duplicate exposure rows after the join. NOTE: there is no preceding
    sort — the keep-first tie-break is engine-order-dependent (preserved
    legacy behaviour, documented rather than changed).
    """
    return (
        items.filter(filter_expr)
        .select(
            [
                pl.col(key).alias(f"{prefix}_ref"),
                *[expr.alias(f"{prefix}_{name}") for name, expr in attributes],
            ]
        )
        .unique(subset=[f"{prefix}_ref"], keep="first")
    )


def coalesce_attribute_levels(
    exposures: pl.LazyFrame,
    *,
    prefixes: Sequence[str],
    specs: Sequence[tuple[str, str, Any]],
) -> pl.LazyFrame:
    """Collapse per-level attribute columns by first-non-null precedence.

    For each ``(source_suffix, output_col, default)`` spec, coalesce
    ``{prefix}_{source_suffix}`` in declared ``prefixes`` order (earliest
    non-null wins) and apply ``fill_null(default)`` unless ``default`` is
    :data:`NO_DEFAULT`. All scratch ``{prefix}_*`` columns are dropped.
    """
    coalesces: list[pl.Expr] = []
    drop_cols: list[str] = []
    for source_suffix, output_col, default in specs:
        expr = pl.coalesce(*[pl.col(f"{p}_{source_suffix}") for p in prefixes])
        if default is not NO_DEFAULT:
            expr = expr.fill_null(default)
        coalesces.append(expr.alias(output_col))
        drop_cols.extend(f"{p}_{source_suffix}" for p in prefixes)
    return exposures.with_columns(coalesces).drop(drop_cols)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _join_cascade_allocation(
    exposures: pl.LazyFrame,
    base_frame: pl.LazyFrame,
    level_items: pl.LazyFrame,
    lv: LevelSpec,
    exp_columns: Collection[str],
    *,
    values: Mapping[str, pl.Expr],
    flags: Mapping[str, pl.Expr],
    item_key: str,
    exposure_id: str,
) -> pl.LazyFrame:
    """Allocate a cascade level's items per exposure and join the result.

    Explodes the ancestor membership into (exposure, ancestor) edges,
    derives subtree basis totals per ancestor, inner-joins the level's item
    aggregates, weights each edge by ``value * basis / total`` (provisions
    form, weight 0.0 on non-positive totals), and re-aggregates per exposure
    so contributions STACK across ancestor levels.
    """
    edge_alias = f"_kl_anc_{lv.name}"
    total_col = f"_kl_total_{lv.name}"

    edges = explode_facility_membership(
        base_frame,
        exp_columns,
        alias=edge_alias,
        parent_key=lv.exposure_key,
        keep=[pl.col(exposure_id), pl.col(_BASIS_COLUMN)],
    )
    subtree_totals = edges.group_by(edge_alias).agg(pl.col(_BASIS_COLUMN).sum().alias(total_col))

    contribs = [
        pl.when(pl.col(total_col) > 0)
        .then(pl.col(f"_kl_v_{alias}_{lv.name}") * pl.col(_BASIS_COLUMN) / pl.col(total_col))
        .otherwise(pl.lit(0.0))
        .alias(f"_kl_c_{alias}_{lv.name}")
        for alias in values
    ]
    re_aggs = [
        pl.col(f"_kl_c_{alias}_{lv.name}").sum().alias(f"_kl_a_{alias}_{lv.name}")
        for alias in values
    ]
    re_aggs += [
        pl.col(f"_kl_f_{alias}_{lv.name}").any().alias(f"_kl_af_{alias}_{lv.name}")
        for alias in flags
    ]

    alloc = (
        edges.join(level_items, left_on=edge_alias, right_on=item_key, how="inner")
        .join(subtree_totals, on=edge_alias, how="left")
        .with_columns(contribs)
        .group_by(exposure_id)
        .agg(re_aggs)
    )
    return exposures.join(alloc, on=exposure_id, how="left")


def _sum_terms(terms: Sequence[pl.Expr]) -> pl.Expr:
    """Left-associative sum of per-level contribution terms."""
    combined = terms[0]
    for term in terms[1:]:
        combined = combined + term
    return combined


def _or_terms(terms: Sequence[pl.Expr]) -> pl.Expr:
    """Left-associative OR of per-level Boolean terms."""
    combined = terms[0]
    for term in terms[1:]:
        combined = combined | term
    return combined
