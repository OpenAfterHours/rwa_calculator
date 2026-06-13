"""
Rulebook compile boundary — Decimal rule shapes -> Polars expressions.

Pipeline position:
    The single Decimal->float boundary of the rulebook (migration Phase 5
    principle 2). ``rulebook/resolve.py`` produces a ``ResolvedRulepack`` of
    at-rest ``Decimal`` rule shapes; this module compiles the ones that drive
    per-row vectorised maths into Polars expressions, once per run. Every
    ``float(...)`` of a regulatory ``Decimal`` lives here — ``model.py`` and
    ``resolve.py`` stay Decimal.

Key responsibilities:
- Turn ``ScalarParam`` / ``LookupTable`` / ``BandedTable`` /
  ``DecisionTable`` / ``FormulaParams`` into ``pl.Expr`` and read
  ``Feature`` as a Python ``bool``.
- Keep the compilers as plain module-level typed functions (no classes, no
  Polars namespace registration — banned by arch_check check 14).

References:
- docs/plans/target-architecture-migration.md (Phase 5 — "compile turns
  packs into Polars expressions once per run — the only Decimal->float
  boundary").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Hashable
    from decimal import Decimal

    from polars._typing import PolarsDataType

    from rwa_calc.rulebook.model import (
        BandedTable,
        DecisionTable,
        Feature,
        FormulaParams,
        LookupTable,
        ScalarParam,
    )


def scalar_lit(p: ScalarParam) -> pl.Expr:
    """Compile a ``ScalarParam`` to a Float64 literal expression."""
    return pl.lit(float(p.value))


def scalar_value(p: ScalarParam) -> float:
    """Read a ``ScalarParam`` as a Python ``float`` (no Polars boundary).

    The float-valued sibling of :func:`scalar_lit`, for the rare scalars that
    feed Python-level arithmetic before the expression is built (e.g. a
    ``1 - discount`` multiplier) rather than a bare ``pl.lit``. Keeping the
    ``float(...)`` here preserves "compile is the only Decimal->float boundary".
    """
    return float(p.value)


def lookup_expr(t: LookupTable, key_col: str | None = None) -> pl.Expr:
    """Compile a ``LookupTable`` to an exact-match when/then chain.

    ``key_col`` overrides the table's declared ``key`` column. Keys absent
    from ``entries`` resolve to ``t.default`` (Float64) when set, else null.
    """
    col = key_col or t.key
    chain: pl.Expr | None = None
    for raw_key, value in t.entries.items():
        chain = (
            pl.when(pl.col(col) == raw_key).then(pl.lit(float(value)))
            if chain is None
            else chain.when(pl.col(col) == raw_key).then(pl.lit(float(value)))
        )
    if chain is None:
        # An empty lookup table: degenerate to the default / null literal.
        return pl.lit(float(t.default)) if t.default is not None else pl.lit(None)
    if t.default is not None:
        return chain.otherwise(pl.lit(float(t.default)))
    return chain.otherwise(pl.lit(None))


def lookup_float_map(t: LookupTable) -> dict[Hashable, float]:
    """Read a ``LookupTable``'s entries as a ``{key: float}`` map.

    The dict-shaped sibling of :func:`lookup_expr`, for consumers that plug the
    per-key values into a hand-built ``when/then`` chain (e.g. category ``is_in``
    predicates) rather than an exact-match key column. The Decimal->float
    boundary lives here; the table stays Decimal at rest.
    """
    return {key: float(value) for key, value in t.entries.items()}


def banded_expr(t: BandedTable, input_col: str | None = None) -> pl.Expr:
    """Compile a ``BandedTable`` to a cumulative threshold when/then chain.

    Bands are evaluated in order; for each finite ``(bound, value)`` the
    branch fires when ``input <= bound`` (or ``input < bound`` when the table
    is not ``right_closed``). The ``None``-bound catch-all becomes the final
    ``.otherwise(...)``.
    """
    col = input_col or t.input
    chain: pl.Expr | None = None
    catch_all: float | None = None
    for bound, value in t.bands:
        if bound is None:
            catch_all = float(value)
            continue
        predicate = pl.col(col) <= float(bound) if t.right_closed else pl.col(col) < float(bound)
        chain = (
            pl.when(predicate).then(pl.lit(float(value)))
            if chain is None
            else chain.when(predicate).then(pl.lit(float(value)))
        )
    if chain is None:
        # Only a catch-all band: a constant Float64 literal.
        return pl.lit(catch_all)
    return chain.otherwise(pl.lit(catch_all))


def decision_expr(t: DecisionTable[Decimal], key_cols: tuple[str, ...] | None = None) -> pl.Expr:
    """Compile a Decimal-valued ``DecisionTable`` to a multi-key when/then chain.

    Each row's key-tuple is matched as an AND of equality predicates across
    ``key_cols`` (defaulting to the table's ``key_names``). Non-matching rows
    fall through to ``t.default`` (Float64) when set, else null.
    """
    cols = key_cols or t.key_names
    chain: pl.Expr | None = None
    for keys, value in t.rows:
        predicate = pl.lit(True)
        for col, key in zip(cols, keys, strict=True):
            predicate = predicate & (pl.col(col) == key)
        chain = (
            pl.when(predicate).then(pl.lit(float(value)))
            if chain is None
            else chain.when(predicate).then(pl.lit(float(value)))
        )
    if chain is None:
        return pl.lit(float(t.default)) if t.default is not None else pl.lit(None)
    if t.default is not None:
        return chain.otherwise(pl.lit(float(t.default)))
    return chain.otherwise(pl.lit(None))


def decision_table_df(
    t: DecisionTable[Decimal],
    *,
    value_name: str = "value",
    key_dtypes: dict[str, PolarsDataType] | None = None,
) -> pl.DataFrame:
    """Render a Decimal-valued ``DecisionTable`` to a keyed lookup ``pl.DataFrame``.

    The DataFrame-shaped sibling of :func:`decision_expr`, for the one consumer
    that *joins* a regime table rather than evaluating an inline when/then chain
    (the collateral haircut lookup in ``engine/crm/haircuts.py``). Each row
    becomes one DataFrame row: the key-tuple spreads across columns named by
    ``t.key_names`` and the Decimal value lands in the ``value_name`` column
    (Float64 — the Decimal->float boundary). ``key_dtypes`` pins specific
    key-column dtypes (e.g. ``{"cqs": pl.Int8}``) so the rendered frame matches
    the consumer's join schema exactly; unpinned key columns keep Polars'
    inferred dtype. Key-tuple ``None`` entries render as nulls. Neither row nor
    column order is significant to a keyed left join.
    """
    key_columns = {name: [keys[i] for keys, _ in t.rows] for i, name in enumerate(t.key_names)}
    frame = pl.DataFrame({**key_columns, value_name: [float(value) for _, value in t.rows]})
    casts = [pl.col(value_name).cast(pl.Float64)]
    if key_dtypes is not None:
        casts.extend(pl.col(name).cast(dtype) for name, dtype in key_dtypes.items())
    return frame.with_columns(casts)


def formula_param_lit(b: FormulaParams, key: str) -> pl.Expr:
    """Compile one named ``FormulaParams`` parameter to a Float64 literal."""
    return pl.lit(float(b.get(key)))


def formula_float_map(b: FormulaParams) -> dict[str, float]:
    """Read a ``FormulaParams`` bundle's parameters as a ``{name: float}`` map.

    The dict-shaped sibling of :func:`formula_param_lit`, for consumers that plug
    several named parameters into a hand-built ``when/then`` chain (or Python-level
    arithmetic) rather than one ``pl.lit`` per call — e.g. the per-exposure-class
    PD floor and per-collateral-type LGD floor builders in ``engine/irb``. The
    Decimal->float boundary lives here; the bundle stays Decimal at rest.
    """
    return {key: float(value) for key, value in b.params.items()}


def feature_enabled(f: Feature) -> bool:
    """Return a ``Feature`` flag as a Python bool (no Polars boundary)."""
    return f.enabled
