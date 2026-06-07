"""
Parallel-run reconciliation engine (legacy calculator vs this one).

Pipeline position:
    Standalone analysis runner — wraps the results of two calculators
    (ours via CreditRiskCalc.calculate(); the legacy one via a mapped file)
    and produces a ReconciliationBundle.

Key responsibilities:
- Collapse our guarantee/RE sub-rows to the reconciliation key grain
- Full-outer join our results against a mapped legacy output on a composite key
- Bucket every mapped component (EAD, RWA, risk weight, PD, LGD, CCF, exposure
  class, ...) as exact_match / within_tolerance / break / missing_left / missing_right
- Attach our explain/input columns so a break can be triaged to data vs engine
- Produce headline (tie-out, by-component), segment (by bucket/class/approach), and
  forensic (per-key, break worklist) views

Why: firms migrating to this calculator run it in parallel with their existing
engine and must demonstrate, component by component, where the two agree and where
(and why) they diverge. This is distinct from engine/comparison.py (CRR vs Basel
3.1, same engine on the same inputs) — here the other side is an opaque external
file mapped onto our canonical components.

References:
- CLAUDE.md — data/engine separation; reconciliation is not a regulatory
  calculation, so this module carries no @cites decorators. Canonical component
  definitions live in data/schemas.RECONCILABLE_COMPONENTS; the documented output
  contract is data/schemas.CALCULATION_OUTPUT_SCHEMA.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    ReconciliationBundle,
    create_empty_reconciliation_bundle,
)
from rwa_calc.contracts.errors import (
    ERROR_RECON_DUPLICATE_LEGACY_KEY,
    ERROR_RECON_GRAIN_HETEROGENEOUS,
    ERROR_RECON_KEY_COLUMN_MISSING,
    ERROR_RECON_LEGACY_COLUMN_MISSING,
    reconciliation_warning,
)
from rwa_calc.data.schemas import RECONCILABLE_COMPONENTS
from rwa_calc.engine.aggregator._collapse import HETEROGENEITY_FLAG, aggregate_to_key_grain

if TYPE_CHECKING:
    from rwa_calc.contracts.config import LegacyColumnMapping
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.data.schemas import ReconcilableComponent

logger = logging.getLogger(__name__)

# Bucket labels (single source — reused by summaries and the UI).
BUCKET_EXACT = "exact_match"
BUCKET_WITHIN = "within_tolerance"
BUCKET_BREAK = "break"
BUCKET_MISSING_LEFT = "missing_left"  # present in legacy, absent in ours
BUCKET_MISSING_RIGHT = "missing_right"  # present in ours, absent in legacy

# Below this absolute difference two numeric values count as exactly equal
# (floating-point noise), regardless of the configured tolerance.
_EXACT_EPSILON = 1e-9
# Guard for relative-delta / percentage denominators near zero.
_ZERO_GUARD = 1e-10
# Internal join key built by concatenating the mapped key columns.
_RECON_KEY = "_recon_key"
_KEY_SEP = "||"


class ReconciliationRunner:
    """Reconcile our results against a mapped legacy output (component by component).

    Implements ``ReconciliationRunnerProtocol``. Pure and UI/IO-agnostic: it takes
    two LazyFrames and a mapping and returns a ReconciliationBundle. The legacy
    frame is expected to already carry canonical ``legacy_<component>`` value
    columns (scaled to our units) plus the legacy key columns named in
    ``mapping.legacy_keys`` — that mechanical mapping is the loader's job; the
    comparison semantics (collapse, join, bucketing, categorical value-mapping,
    summaries) live here.
    """

    def reconcile(
        self,
        our_results: pl.LazyFrame,
        legacy_results: pl.LazyFrame,
        mapping: LegacyColumnMapping,
    ) -> ReconciliationBundle:
        """Reconcile our results against a mapped legacy output.

        Args:
            our_results: Our per-exposure results LazyFrame (e.g. from
                ``CalculationResponse.scan_results()``).
            legacy_results: Legacy output with ``legacy_<component>`` columns and
                the ``mapping.legacy_keys`` columns.
            mapping: Column/key mapping and per-component tolerances.

        Returns:
            ReconciliationBundle with per-component reconciliation and summaries.
        """
        errors: list[CalculationError] = []

        our_schema = set(our_results.collect_schema().names())
        legacy_schema = set(legacy_results.collect_schema().names())

        if not self._keys_present(mapping, our_schema, legacy_schema, errors):
            return self._empty(errors)

        active = self._resolve_active_components(mapping, our_schema, legacy_schema, errors)
        if not active:
            logger.warning("Reconciliation found no comparable components; returning empty bundle")
            return self._empty(errors)

        collapsed = aggregate_to_key_grain(our_results, mapping.our_keys)
        self._check_heterogeneity(collapsed, errors)

        our_side = self._prepare_our_side(collapsed, mapping, active)
        legacy_side = self._prepare_legacy_side(legacy_results, mapping, active, errors)

        joined = our_side.join(legacy_side, on=_RECON_KEY, how="full", coalesce=True)
        joined = joined.with_columns(
            pl.col("_our_present").fill_null(False),  # noqa: FBT003
            pl.col("_legacy_present").fill_null(False),  # noqa: FBT003
        )

        recon = self._apply_buckets(joined, mapping, active)

        return ReconciliationBundle(
            component_reconciliation=recon,
            summary_by_component=_summary_by_component(recon, active),
            summary_by_bucket=_summary_by_bucket(recon),
            summary_by_exposure_class=_summary_by_group(recon, "our_exposure_class", active),
            summary_by_approach=_summary_by_group(recon, "our_approach", active),
            breaks_detail=_breaks_detail(recon, mapping, active),
            totals_tie_out=_totals_tie_out(recon, active),
            errors=errors,
        )

    # -- guards / resolution ------------------------------------------------

    def _keys_present(
        self,
        mapping: LegacyColumnMapping,
        our_schema: set[str],
        legacy_schema: set[str],
        errors: list[CalculationError],
    ) -> bool:
        """Validate that the join key columns exist on both sides (REC003)."""
        ok = True
        # our_keys: the default exposure_reference key is synthesised by the
        # collapse helper, so only validate non-default composite keys.
        if tuple(mapping.our_keys) != ("exposure_reference",):
            for col in mapping.our_keys:
                if col not in our_schema:
                    ok = False
                    errors.append(
                        reconciliation_warning(
                            ERROR_RECON_KEY_COLUMN_MISSING,
                            f"our key column '{col}' not found on results frame",
                            field_name=col,
                        )
                    )
        elif "exposure_reference" not in our_schema:
            ok = False
            errors.append(
                reconciliation_warning(
                    ERROR_RECON_KEY_COLUMN_MISSING,
                    "results frame has no 'exposure_reference' column",
                    field_name="exposure_reference",
                )
            )
        for col in mapping.legacy_keys:
            if col not in legacy_schema:
                ok = False
                errors.append(
                    reconciliation_warning(
                        ERROR_RECON_KEY_COLUMN_MISSING,
                        f"legacy key column '{col}' not found on legacy frame",
                        field_name=col,
                    )
                )
        return ok

    def _resolve_active_components(
        self,
        mapping: LegacyColumnMapping,
        our_schema: set[str],
        legacy_schema: set[str],
        errors: list[CalculationError],
    ) -> list[_ActiveComponent]:
        """Resolve each mapped component to (our column, legacy column), skipping
        and warning (REC001) when a required column is absent on either side."""
        active: list[_ActiveComponent] = []
        # Iterate in registry order for stable output / worst-component selection.
        for spec in RECONCILABLE_COMPONENTS:
            if spec.name not in mapping.components:
                continue
            our_col = _first_present(spec.our_columns, our_schema)
            legacy_col = f"legacy_{spec.name}"
            if our_col is None:
                errors.append(
                    reconciliation_warning(
                        ERROR_RECON_LEGACY_COLUMN_MISSING,
                        f"no column for component '{spec.name}' on our results "
                        f"(tried {list(spec.our_columns)}); skipping",
                        field_name=spec.name,
                    )
                )
                continue
            if legacy_col not in legacy_schema:
                errors.append(
                    reconciliation_warning(
                        ERROR_RECON_LEGACY_COLUMN_MISSING,
                        f"legacy column '{legacy_col}' for component "
                        f"'{spec.name}' not found; skipping",
                        field_name=legacy_col,
                    )
                )
                continue
            active.append(_ActiveComponent(spec=spec, our_col=our_col, legacy_col=legacy_col))
        return active

    def _check_heterogeneity(
        self, collapsed: pl.LazyFrame, errors: list[CalculationError]
    ) -> None:
        """Emit REC004 if a coarse key aggregated rows of mixed class/approach."""
        if HETEROGENEITY_FLAG not in collapsed.collect_schema().names():
            return
        # Small diagnostic collect (offline analysis tool, not the hot pipeline).
        count = (
            collapsed.filter(pl.col(HETEROGENEITY_FLAG)).select(pl.len()).collect().item()
        )
        if count:
            errors.append(
                reconciliation_warning(
                    ERROR_RECON_GRAIN_HETEROGENEOUS,
                    f"{count} reconciliation key(s) aggregated rows of differing "
                    "exposure class / approach; categorical values shown are the "
                    "first in each group",
                    actual_value=str(count),
                )
            )

    # -- side preparation ---------------------------------------------------

    def _prepare_our_side(
        self,
        collapsed: pl.LazyFrame,
        mapping: LegacyColumnMapping,
        active: list[_ActiveComponent],
    ) -> pl.LazyFrame:
        """Select our key, value, grouping and explain/input columns."""
        present = set(collapsed.collect_schema().names())
        exprs: list[pl.Expr] = [_key_expr(mapping.our_keys).alias(_RECON_KEY)]
        seen: set[str] = {_RECON_KEY}

        # Carry the our-key columns verbatim for the break worklist.
        for col in mapping.our_keys:
            if col not in seen and col in present:
                exprs.append(pl.col(col))
                seen.add(col)

        active_names = {a.spec.name for a in active}
        for a in active:
            out = f"our_{a.spec.name}"
            if out not in seen:
                exprs.append(pl.col(a.our_col).alias(out))
                seen.add(out)
            for extra in (*a.spec.explain_columns, *a.spec.input_columns):
                if extra in present and extra not in seen:
                    exprs.append(pl.col(extra))
                    seen.add(extra)

        # Grouping columns for the by-class / by-approach summaries. When the
        # component is mapped, ``our_exposure_class`` / ``our_approach`` already
        # exist from the loop above; only synthesise them otherwise (cannot
        # reference a same-select alias, so derive from the raw output column).
        if "exposure_class" not in active_names:
            exprs.append(_raw_grouping_expr("exposure_class", "our_exposure_class", present))
        if "approach" not in active_names:
            exprs.append(_raw_grouping_expr("approach_applied", "our_approach", present))
        exprs.append(pl.lit(True).alias("_our_present"))  # noqa: FBT003
        return collapsed.select(exprs)

    def _prepare_legacy_side(
        self,
        legacy_results: pl.LazyFrame,
        mapping: LegacyColumnMapping,
        active: list[_ActiveComponent],
        errors: list[CalculationError],
    ) -> pl.LazyFrame:
        """Select legacy key + value columns, deduped to one row per key (REC002)."""
        exprs: list[pl.Expr] = [_key_expr(mapping.legacy_keys).alias(_RECON_KEY)]
        for a in active:
            exprs.append(pl.col(a.legacy_col))
        exprs.append(pl.lit(True).alias("_legacy_present"))  # noqa: FBT003
        legacy = legacy_results.select(exprs)

        # Detect duplicate keys (small diagnostic collect) before deduping, so a
        # non-1:1 legacy file is surfaced rather than silently dropped on join.
        dup_count = (
            legacy.group_by(_RECON_KEY)
            .len()
            .filter(pl.col("len") > 1)
            .select(pl.len())
            .collect()
            .item()
        )
        if dup_count:
            errors.append(
                reconciliation_warning(
                    ERROR_RECON_DUPLICATE_LEGACY_KEY,
                    f"{dup_count} duplicate legacy key(s); keeping the first row of "
                    "each on join",
                    actual_value=str(dup_count),
                )
            )
        return legacy.unique(subset=[_RECON_KEY], keep="first")

    # -- bucketing ----------------------------------------------------------

    def _apply_buckets(
        self,
        joined: pl.LazyFrame,
        mapping: LegacyColumnMapping,
        active: list[_ActiveComponent],
    ) -> pl.LazyFrame:
        """Add per-component delta + bucket columns and the row-level rollup."""
        for a in active:
            joined = joined.with_columns(_component_columns(a, mapping))

        bucket_cols = [f"{a.spec.name}_bucket" for a in active]
        any_break = pl.any_horizontal([pl.col(c) == BUCKET_BREAK for c in bucket_cols])
        any_within = pl.any_horizontal([pl.col(c) == BUCKET_WITHIN for c in bucket_cols])

        row_bucket = (
            pl.when(~pl.col("_our_present"))
            .then(pl.lit(BUCKET_MISSING_LEFT))
            .when(~pl.col("_legacy_present"))
            .then(pl.lit(BUCKET_MISSING_RIGHT))
            .when(any_break)
            .then(pl.lit(BUCKET_BREAK))
            .when(any_within)
            .then(pl.lit(BUCKET_WITHIN))
            .otherwise(pl.lit(BUCKET_EXACT))
            .alias("row_bucket")
        )
        joined = joined.with_columns(row_bucket)

        worst_break = pl.coalesce(
            [pl.when(pl.col(f"{a.spec.name}_bucket") == BUCKET_BREAK).then(pl.lit(a.spec.name)) for a in active]
        )
        worst_within = pl.coalesce(
            [pl.when(pl.col(f"{a.spec.name}_bucket") == BUCKET_WITHIN).then(pl.lit(a.spec.name)) for a in active]
        )
        worst_component = (
            pl.when(pl.col("row_bucket") == BUCKET_BREAK)
            .then(worst_break)
            .when(pl.col("row_bucket") == BUCKET_WITHIN)
            .then(worst_within)
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("worst_component")
        )
        return joined.with_columns(worst_component)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _empty(errors: list[CalculationError]) -> ReconciliationBundle:
        bundle = create_empty_reconciliation_bundle()
        return ReconciliationBundle(
            component_reconciliation=bundle.component_reconciliation,
            summary_by_component=bundle.summary_by_component,
            summary_by_bucket=bundle.summary_by_bucket,
            summary_by_exposure_class=bundle.summary_by_exposure_class,
            summary_by_approach=bundle.summary_by_approach,
            breaks_detail=bundle.breaks_detail,
            totals_tie_out=bundle.totals_tie_out,
            errors=errors,
        )


class _ActiveComponent:
    """A mapped component resolved to concrete (our, legacy) column names."""

    __slots__ = ("spec", "our_col", "legacy_col")

    def __init__(self, spec: ReconcilableComponent, our_col: str, legacy_col: str) -> None:
        self.spec = spec
        self.our_col = our_col
        self.legacy_col = legacy_col


# =============================================================================
# Per-component bucketing
# =============================================================================


def _component_columns(a: _ActiveComponent, mapping: LegacyColumnMapping) -> list[pl.Expr]:
    """Delta + bucket expressions for one component."""
    name = a.spec.name
    ov = pl.col(f"our_{name}")
    lv = pl.col(a.legacy_col)

    if a.spec.kind == "numeric":
        abs_delta = (ov - lv).alias(f"abs_delta_{name}")
        rel_delta = (
            pl.when(lv.abs() > _ZERO_GUARD)
            .then((ov - lv) / lv)
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias(f"rel_delta_{name}")
        )
        within = _within_expr(ov, lv, a.spec, mapping)
        exact = (ov - lv).abs() <= _EXACT_EPSILON
        bucket = (
            pl.when(~pl.col("_our_present"))
            .then(pl.lit(BUCKET_MISSING_LEFT))
            .when(~pl.col("_legacy_present"))
            .then(pl.lit(BUCKET_MISSING_RIGHT))
            .when(ov.is_null() & lv.is_null())
            .then(pl.lit(BUCKET_EXACT))
            .when(ov.is_null() | lv.is_null())
            .then(pl.lit(BUCKET_BREAK))
            .when(exact)
            .then(pl.lit(BUCKET_EXACT))
            .when(within)
            .then(pl.lit(BUCKET_WITHIN))
            .otherwise(pl.lit(BUCKET_BREAK))
            .alias(f"{name}_bucket")
        )
        return [abs_delta, rel_delta, bucket]

    # categorical
    our_norm = _normalise(ov)
    legacy_norm = _apply_value_map(_normalise(lv), mapping.components[name].value_map)
    match = our_norm == legacy_norm
    bucket = (
        pl.when(~pl.col("_our_present"))
        .then(pl.lit(BUCKET_MISSING_LEFT))
        .when(~pl.col("_legacy_present"))
        .then(pl.lit(BUCKET_MISSING_RIGHT))
        .when(ov.is_null() & lv.is_null())
        .then(pl.lit(BUCKET_EXACT))
        .when(ov.is_null() | lv.is_null())
        .then(pl.lit(BUCKET_BREAK))
        .when(match)
        .then(pl.lit(BUCKET_EXACT))
        .otherwise(pl.lit(BUCKET_BREAK))
        .alias(f"{name}_bucket")
    )
    # Null delta columns keep the frame schema uniform across component kinds.
    abs_delta = pl.lit(None, dtype=pl.Float64).alias(f"abs_delta_{name}")
    rel_delta = pl.lit(None, dtype=pl.Float64).alias(f"rel_delta_{name}")
    return [abs_delta, rel_delta, bucket]


def _within_expr(
    ov: pl.Expr, lv: pl.Expr, spec: ReconcilableComponent, mapping: LegacyColumnMapping
) -> pl.Expr:
    """Boolean expr: is the numeric pair within the (possibly overridden) tolerance."""
    cm = mapping.components[spec.name]
    tol_kind = cm.tol_kind or spec.default_tol_kind
    tol = cm.tol if cm.tol is not None else spec.default_tol
    diff = (ov - lv).abs()
    if tol_kind == "rel":
        # Relative tolerance, zero-guarded: when legacy ~ 0, only an exact match
        # passes (handled separately by the exact-epsilon branch).
        return pl.when(lv.abs() > _ZERO_GUARD).then(diff <= tol * lv.abs()).otherwise(diff <= _EXACT_EPSILON)
    return diff <= tol


# =============================================================================
# Summaries
# =============================================================================


def _summary_by_component(recon: pl.LazyFrame, active: list[_ActiveComponent]) -> pl.LazyFrame:
    """One row per component: bucket counts, summed |abs delta|, break rate."""
    rows: list[pl.LazyFrame] = []
    for a in active:
        bucket = pl.col(f"{a.spec.name}_bucket")
        n_break = (bucket == BUCKET_BREAK).sum()
        n_within = (bucket == BUCKET_WITHIN).sum()
        n_exact = (bucket == BUCKET_EXACT).sum()
        n_ml = (bucket == BUCKET_MISSING_LEFT).sum()
        n_mr = (bucket == BUCKET_MISSING_RIGHT).sum()
        comparable = n_break + n_within + n_exact
        sum_abs = (
            pl.col(f"abs_delta_{a.spec.name}").abs().sum()
            if a.spec.kind == "numeric"
            else pl.lit(None, dtype=pl.Float64)
        )
        rows.append(
            recon.select(
                pl.lit(a.spec.name).alias("component"),
                pl.lit(a.spec.kind).alias("kind"),
                n_exact.alias("n_exact_match"),
                n_within.alias("n_within_tolerance"),
                n_break.alias("n_break"),
                n_ml.alias("n_missing_left"),
                n_mr.alias("n_missing_right"),
                sum_abs.alias("sum_abs_delta"),
                pl.when(comparable > 0)
                .then(n_break / comparable)
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("break_rate"),
            )
        )
    return pl.concat(rows, how="vertical")


def _summary_by_bucket(recon: pl.LazyFrame) -> pl.LazyFrame:
    """Row-level bucket counts."""
    return (
        recon.group_by("row_bucket")
        .agg(pl.len().alias("count"))
        .sort("row_bucket")
    )


def _summary_by_group(
    recon: pl.LazyFrame, group_col: str, active: list[_ActiveComponent]
) -> pl.LazyFrame:
    """Break counts/sums grouped by our exposure class or approach."""
    has_rwa = any(a.spec.name == "rwa" for a in active)
    sum_abs_rwa = (
        pl.col("abs_delta_rwa").abs().sum() if has_rwa else pl.lit(None, dtype=pl.Float64)
    )
    return (
        recon.group_by(group_col)
        .agg(
            pl.len().alias("n_total"),
            (pl.col("row_bucket") == BUCKET_EXACT).sum().alias("n_exact_match"),
            (pl.col("row_bucket") == BUCKET_WITHIN).sum().alias("n_within_tolerance"),
            (pl.col("row_bucket") == BUCKET_BREAK).sum().alias("n_break"),
            (pl.col("row_bucket") == BUCKET_MISSING_LEFT).sum().alias("n_missing_left"),
            (pl.col("row_bucket") == BUCKET_MISSING_RIGHT).sum().alias("n_missing_right"),
            sum_abs_rwa.alias("sum_abs_delta_rwa"),
        )
        .sort(group_col, nulls_last=True)
    )


def _breaks_detail(
    recon: pl.LazyFrame, mapping: LegacyColumnMapping, active: list[_ActiveComponent]
) -> pl.LazyFrame:
    """Long-format worklist: one row per (key, component) break, ranked by size."""
    frames: list[pl.LazyFrame] = []
    key_cols = [c for c in mapping.our_keys if c != "exposure_reference"]
    present = set(recon.collect_schema().names())
    for a in active:
        name = a.spec.name
        is_num = a.spec.kind == "numeric"
        explain_expr = _explain_expr(list(a.spec.explain_columns), present)
        frames.append(
            recon.filter(pl.col(f"{name}_bucket") == BUCKET_BREAK).select(
                pl.col(_RECON_KEY),
                *[pl.col(c) for c in key_cols],
                pl.lit(name).alias("component"),
                pl.col(f"our_{name}").cast(pl.String).alias("our_value"),
                pl.col(a.legacy_col).cast(pl.String).alias("legacy_value"),
                (
                    pl.col(f"abs_delta_{name}") if is_num else pl.lit(None, dtype=pl.Float64)
                ).alias("abs_delta"),
                (
                    pl.col(f"rel_delta_{name}") if is_num else pl.lit(None, dtype=pl.Float64)
                ).alias("rel_delta"),
                explain_expr.alias("our_explain"),
            )
        )
    if not frames:
        return pl.LazyFrame(
            schema={
                _RECON_KEY: pl.String,
                "component": pl.String,
                "our_value": pl.String,
                "legacy_value": pl.String,
                "abs_delta": pl.Float64,
                "rel_delta": pl.Float64,
                "our_explain": pl.String,
            }
        )
    return pl.concat(frames, how="vertical").sort(
        pl.col("abs_delta").abs(), descending=True, nulls_last=True
    )


def _totals_tie_out(recon: pl.LazyFrame, active: list[_ActiveComponent]) -> pl.LazyFrame:
    """Per additive numeric component: sum(legacy) vs sum(ours), delta, pct."""
    rows: list[pl.LazyFrame] = []
    for a in active:
        if not (a.spec.kind == "numeric" and a.spec.additive):
            continue
        legacy_total = pl.col(a.legacy_col).sum()
        our_total = pl.col(f"our_{a.spec.name}").sum()
        rows.append(
            recon.select(
                pl.lit(a.spec.name).alias("component"),
                legacy_total.alias("legacy_total"),
                our_total.alias("our_total"),
            ).with_columns(
                (pl.col("our_total") - pl.col("legacy_total")).alias("delta"),
            ).with_columns(
                pl.when(pl.col("legacy_total").abs() > _ZERO_GUARD)
                .then(pl.col("delta") / pl.col("legacy_total") * 100.0)
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("delta_pct"),
            )
        )
    if not rows:
        return pl.LazyFrame(
            schema={
                "component": pl.String,
                "legacy_total": pl.Float64,
                "our_total": pl.Float64,
                "delta": pl.Float64,
                "delta_pct": pl.Float64,
            }
        )
    return pl.concat(rows, how="vertical")


# =============================================================================
# Expression helpers
# =============================================================================


def _key_expr(key_columns: tuple[str, ...]) -> pl.Expr:
    """Concatenate key columns into a single string join key (null-safe)."""
    parts = [pl.col(c).cast(pl.String).fill_null("") for c in key_columns]
    if len(parts) == 1:
        return parts[0]
    return pl.concat_str(parts, separator=_KEY_SEP)


def _raw_grouping_expr(source_col: str, out_name: str, present: set[str]) -> pl.Expr:
    """Standalone grouping column derived from a raw output column (or null)."""
    if source_col in present:
        return pl.col(source_col).alias(out_name)
    return pl.lit(None, dtype=pl.String).alias(out_name)


def _explain_expr(explain_columns: list[str], present: set[str]) -> pl.Expr:
    """Concatenate present explain columns into one ``key=value; ...`` string."""
    cols = [c for c in explain_columns if c in present]
    if not cols:
        return pl.lit(None, dtype=pl.String)
    parts = [pl.lit(f"{c}=") + pl.col(c).cast(pl.String) for c in cols]
    return pl.concat_str(parts, separator="; ", ignore_nulls=True)


def _normalise(expr: pl.Expr) -> pl.Expr:
    """Casefold + strip a string expression for categorical comparison."""
    return expr.cast(pl.String).str.strip_chars().str.to_lowercase()


def _apply_value_map(expr: pl.Expr, value_map: dict[str, str]) -> pl.Expr:
    """Apply legacy→canonical synonyms (keys/values normalised) to a normalised expr."""
    if not value_map:
        return expr
    norm_map = {k.strip().lower(): v.strip().lower() for k, v in value_map.items()}
    return expr.replace(norm_map)


def _first_present(candidates: tuple[str, ...], schema: set[str]) -> str | None:
    """Return the first candidate column present in the schema, else None."""
    return next((c for c in candidates if c in schema), None)
