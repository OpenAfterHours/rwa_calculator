"""
Producer-sealed stage-edge contracts.

Pipeline position:
    Shared contracts-layer primitive — each pipeline stage seals its output
    frame against its edge contract at stage exit (via
    ``engine.materialise.materialise_sealed_edge``), and the frozen bundles
    validate the resulting brand in ``__post_init__``.

Key responsibilities:
- ``EdgeColumn`` / ``EdgeContract``: per-edge column declarations with
  null-semantics annotations and regulatory citations
- ``EdgeContract.conform``: assert required columns + dtypes (violations
  RAISE — a producer breaking its own output contract is a programming
  error, not a data-quality error), inject producer-owned defaults for
  absent optional columns, fill present-but-null Booleans (and only
  Booleans), strip undeclared scratch columns, emit canonical column order
- ``seal`` / ``sealed_edge_of``: brand a conformed frame with its edge name;
  the brand is an instance attribute and deliberately does NOT survive any
  frame transformation — a transformed frame is no longer the sealed frame

Conservatism gate:
    ``fill_null_default`` is legal on Boolean columns only, enforced when
    the contract is DECLARED. Float/String nulls are never filled — a silent
    ``0.0`` EAD/provision understates RWA (anti-conservative). Broadening
    this requires Risk sign-off; see ``data/column_spec.py`` and
    ``tests/contracts/test_boolean_defaults_only.py``.

References:
- docs/plans/target-architecture-migration.md (Phase 3)
- docs/plans/engine-defensiveness-boundary-hardening.md (root cause: no
  producer-enforced inter-stage column contract)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.data.column_spec import ColumnSpec

_BRAND_ATTR = "_rwa_sealed_edge"


class EdgeContractViolation(Exception):
    """A frame failed its edge contract, or a bundle field lacks its brand.

    This is the programming-error channel: a producing stage emitting a
    frame that violates its own declared output contract is a code defect,
    never a data-quality condition — so it raises instead of accumulating
    a ``CalculationError``.
    """


@dataclass(frozen=True, slots=True)
class EdgeColumn:
    """Declarative contract for one column at a stage edge.

    Attributes:
        dtype: Exact Polars dtype the producer emits. A mismatch is a
            contract violation — ``conform`` never re-casts.
        required: When True the producer must emit the column; ``conform``
            raises if it is absent. When False an absent column is injected
            as ``default`` cast to ``dtype``.
        default: Producer-owned value injected when an optional column is
            absent. ``None`` injects a typed null column. Must be ``None``
            for required columns (the producer emits them; a default would
            be dead config).
        fill_null_default: Fill present-but-null values with ``default``.
            Boolean columns only — enforced at contract declaration
            (conservatism gate; Float/String nulls are never filled).
        null_meaning: Documented semantics of a null value (e.g. tri-state
            flags where null means "unknown", which must not collapse to a
            filled value).
        citation: Regulatory citation for derived columns (e.g.
            ``effectively_secured`` ← CRR Art. 230).
    """

    dtype: pl.DataType
    required: bool = True
    default: object = None
    fill_null_default: bool = False
    null_meaning: str | None = None
    citation: str | None = None


@dataclass(frozen=True)
class EdgeContract:
    """The full column contract for one stage edge.

    ``columns`` insertion order is the edge's canonical column order —
    ``conform`` re-orders its output to match.
    """

    name: str
    columns: dict[str, EdgeColumn] = field(default_factory=dict)

    def __post_init__(self) -> None:
        problems: list[str] = []
        for col_name, col in self.columns.items():
            if col.fill_null_default and col.dtype != pl.Boolean:
                problems.append(
                    f"{col_name}: fill_null_default is legal on Boolean columns only "
                    f"(got {col.dtype}); Float/String null fills are anti-conservative "
                    "and require Risk sign-off"
                )
            if col.fill_null_default and col.default is None:
                problems.append(f"{col_name}: fill_null_default=True requires a non-None default")
            if col.required and col.default is not None:
                problems.append(
                    f"{col_name}: a default on a required column is dead config — "
                    "drop the default or mark the column optional"
                )
        if problems:
            raise ValueError(f"invalid edge contract '{self.name}':\n  " + "\n  ".join(problems))

    def conform(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Validate ``lf`` against this contract and normalise its shape.

        Raises ``EdgeContractViolation`` (listing every problem at once)
        when a required column is missing or a declared column's dtype
        does not match. Otherwise: injects absent optional columns with
        their producer-owned defaults, fills present-but-null Boolean
        columns declared ``fill_null_default``, strips undeclared scratch
        columns, and emits columns in contract order.
        """
        schema = lf.collect_schema()
        present = dict(schema)

        violations: list[str] = []
        for col_name, col in self.columns.items():
            actual = present.get(col_name)
            if actual is None:
                if col.required:
                    violations.append(f"missing required column '{col_name}'")
                continue
            if actual != col.dtype:
                violations.append(
                    f"column '{col_name}' has dtype {actual}, contract requires {col.dtype}"
                )
        if violations:
            raise EdgeContractViolation(
                f"edge '{self.name}' contract violated:\n  " + "\n  ".join(violations)
            )

        additions = [
            pl.lit(col.default).cast(col.dtype).alias(col_name)
            for col_name, col in self.columns.items()
            if col_name not in present
        ]
        if additions:
            lf = lf.with_columns(additions)

        fills = [
            pl.col(col_name).fill_null(pl.lit(col.default).cast(pl.Boolean))
            for col_name, col in self.columns.items()
            if col.fill_null_default and col_name in present
        ]
        if fills:
            lf = lf.with_columns(fills)

        return lf.select(list(self.columns))

    def empty_frame(self) -> pl.LazyFrame:
        """A zero-row, schema-complete, sealed frame for this edge."""
        empty = pl.LazyFrame(schema={col_name: col.dtype for col_name, col in self.columns.items()})
        return brand(empty, self.name)


def seal(lf: pl.LazyFrame, edge: EdgeContract) -> pl.LazyFrame:
    """Conform ``lf`` to ``edge`` and brand the result.

    The contracts-level primitive: pipeline stages go through
    ``engine.materialise.materialise_sealed_edge`` (which also materialises
    the plan); tests and fixture builders call ``seal`` directly.
    """
    return brand(edge.conform(lf), edge.name)


def brand(lf: pl.LazyFrame, edge_name: str) -> pl.LazyFrame:
    """Mark ``lf`` as sealed for ``edge_name``.

    The brand is a plain instance attribute: any transformation returns a
    NEW LazyFrame without it, so only the exact object that went through
    the seal carries the brand. That is load-bearing — a derived frame has
    not been validated and must not claim to be sealed.
    """
    setattr(lf, _BRAND_ATTR, edge_name)
    return lf


def sealed_edge_of(lf: pl.LazyFrame) -> str | None:
    """The edge name ``lf`` was sealed for, or None if unsealed."""
    return getattr(lf, _BRAND_ATTR, None)


def require_brand(lf: pl.LazyFrame, edge_name: str, *, owner: str, field_name: str) -> None:
    """Raise unless ``lf`` carries exactly the ``edge_name`` brand.

    Called from bundle ``__post_init__`` for fields registered in
    ``contracts.bundles.SEALED_FRAME_FIELDS``.
    """
    found = sealed_edge_of(lf)
    if found == edge_name:
        return
    if found is None:
        raise EdgeContractViolation(
            f"{owner}.{field_name} requires a frame sealed for edge '{edge_name}', "
            "got an unsealed frame — construct it via the stage producer or a "
            "contract-derived test builder (transforming a sealed frame removes "
            "its brand)"
        )
    raise EdgeContractViolation(
        f"{owner}.{field_name} requires a frame sealed for edge '{edge_name}', "
        f"got a frame sealed for '{found}'"
    )


def edge_columns_from_specs(
    schema: Mapping[str, ColumnSpec],
    *,
    boolean_fill: bool = True,
) -> dict[str, EdgeColumn]:
    """Seed edge columns from an existing ``ColumnSpec`` schema.

    Maps ``ColumnSpec(dtype, default, required)`` onto ``EdgeColumn``; with
    ``boolean_fill`` (the default), Boolean columns that carry a non-None
    default also fill present-but-null values — preserving the loader's
    ``enforce_schema`` semantics when an input-table schema becomes an edge
    contract.
    """
    return {
        col_name: EdgeColumn(
            dtype=spec.dtype,
            required=spec.required,
            default=None if spec.required else spec.default,
            fill_null_default=(
                boolean_fill
                and not spec.required
                and spec.dtype == pl.Boolean
                and spec.default is not None
            ),
        )
        for col_name, spec in schema.items()
    }
