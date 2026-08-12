"""
Column specification for schema-driven DataFrame defaults.

Pipeline position:
    Shared data-layer primitive — used by data/schemas.py declarations and
    by engine stages (loader, calculators) that need to ensure columns exist
    before calculation.

Key responsibilities:
- Declare per-column metadata (dtype, default, required, input DOMAIN) in one place
- Fill missing optional columns on a LazyFrame with declared defaults
- Project a ColumnSpec schema down to a plain dtype dict for
  Polars constructors that require {name: dtype}
- Express a column's admissible input domain — a numeric interval or an
  enumerated string set — as data a generic validator can read

References:
- CLAUDE.md — data/engine separation; data/schemas is the only module
  permitted to declare input-domain / pipeline-default values.
- docs/plans/test-space-correctness-proposal.md (Phase 1)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from polars._typing import PolarsDataType


# =============================================================================
# INPUT DOMAINS
# =============================================================================
#
# Why the domain is declared here rather than checked in a validator
# ------------------------------------------------------------------
# Before Phase 1 the input domain of every numeric column lived in people's
# heads, and the four range validators in ``contracts/validation.py`` encoded
# four of them by hand. A column got validation by someone remembering to add
# a branch. These two types move the domain onto the column declaration, so a
# new column gets validation by being DECLARED — one generic validator reads
# every declaration (``contracts/validation.py::_validate_declared_domains``),
# and ``scripts/check_input_domains.py`` ratchets the declared population so a
# domain cannot quietly go away.
#
# ``reason`` is mandatory on both, and it is not decoration. A bound with no
# stated basis is how a WRONG bound survives review — and a wrong bound is
# worse than no bound, because it emits false errors on valid customer data
# and teaches people to ignore the error channel.


@dataclass(frozen=True, slots=True, kw_only=True)
class NumericDomain:
    """The interval a numeric column's non-null values must lie in.

    Bounds are independently open or closed because the distinction is
    load-bearing, not cosmetic: ``pd`` must be CLOSED at zero (CRR Art. 160(1)
    has no central-government limb, so the CRR rulepack carries a sovereign PD
    floor of 0 and a half-open ``(0, 1]`` would reject every sovereign IRB
    exposure priced at zero), while ``effective_maturity`` must be OPEN at zero
    (a zero-year maturity is not a maturity) and ``rate`` must be open at zero
    (a zero FX rate silently zeroes every converted amount).

    Either bound may be ``None``, meaning unbounded on that side. That is the
    honest declaration for LTV — CRR Art. 125/126 and PS1/26 Art. 124C band it
    upward without capping it, and negative equity puts real exposures above
    100% — so only the lower bound is stated.

    Nulls are NEVER a domain violation. A missing PD is a different finding
    (and a different error code) from an out-of-range one, and conflating them
    would make the error channel useless for both.

    Attributes:
        reason: Regulatory citation or stated reason for these bounds.
            Mandatory — see the module note above.
        lower: Inclusive/exclusive lower bound, or None for unbounded below.
        upper: Inclusive/exclusive upper bound, or None for unbounded above.
        lower_closed: True when ``lower`` itself is admissible.
        upper_closed: True when ``upper`` itself is admissible.
    """

    reason: str
    lower: float | None = None
    upper: float | None = None
    lower_closed: bool = True
    upper_closed: bool = True

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("NumericDomain.reason is mandatory — state the citation or the basis")
        if self.lower is None and self.upper is None:
            raise ValueError("NumericDomain must bound at least one side")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError(f"NumericDomain lower {self.lower} exceeds upper {self.upper}")

    def describe(self) -> str:
        """Interval notation for the error message, e.g. ``(0, 5.0]`` or ``>= 0``."""
        if self.lower is None:
            return f"<= {_trim(self.upper)}" if self.upper_closed else f"< {_trim(self.upper)}"
        if self.upper is None:
            return f">= {_trim(self.lower)}" if self.lower_closed else f"> {_trim(self.lower)}"
        open_bracket = "[" if self.lower_closed else "("
        close_bracket = "]" if self.upper_closed else ")"
        return f"{open_bracket}{_trim(self.lower)}, {_trim(self.upper)}{close_bracket}"

    def violation_expr(self, column: str) -> pl.Expr:
        """Boolean expression: True exactly where ``column`` is non-null and out of domain."""
        col = pl.col(column)
        out_of_domain = pl.lit(value=False)
        if self.lower is not None:
            out_of_domain = out_of_domain | (
                col < self.lower if self.lower_closed else col <= self.lower
            )
        if self.upper is not None:
            out_of_domain = out_of_domain | (
                col > self.upper if self.upper_closed else col >= self.upper
            )
        return col.is_not_null() & out_of_domain


@dataclass(frozen=True, slots=True, kw_only=True)
class EnumDomain:
    """The set of strings a categorical column's non-null values must come from.

    Subsumes the old free-standing ``COLUMN_VALUE_CONSTRAINTS`` registry, which
    is now DERIVED from these declarations (``data/schemas.py``) rather than
    maintained beside them. A registry that sits next to the schema it
    describes is a registry that drifts from it.

    Comparison is case-insensitive by default, matching the behaviour
    ``validate_column_values`` has always had.

    Attributes:
        reason: Regulatory citation or stated reason. Mandatory.
        values: The admissible strings.
        case_insensitive: When True (the default), values are compared
            lower-cased on both sides.
    """

    reason: str
    values: frozenset[str]
    case_insensitive: bool = True

    def __init__(
        self,
        *,
        reason: str,
        values: Collection[str],
        case_insensitive: bool = True,
    ) -> None:
        if not reason.strip():
            raise ValueError("EnumDomain.reason is mandatory — state the citation or the basis")
        if not values:
            raise ValueError("EnumDomain.values must not be empty")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "values", frozenset(values))
        object.__setattr__(self, "case_insensitive", case_insensitive)

    def describe(self) -> str:
        """Comma-joined sorted value list for the error message."""
        return ", ".join(sorted(self.values))

    def violation_expr(self, column: str) -> pl.Expr:
        """Boolean expression: True exactly where ``column`` is non-null and not permitted."""
        col = pl.col(column)
        if self.case_insensitive:
            return col.is_not_null() & ~col.str.to_lowercase().is_in(
                {v.lower() for v in self.values}
            )
        return col.is_not_null() & ~col.is_in(self.values)


#: A column's declared input domain. Deliberately a closed union rather than a
#: protocol: a third shape (a regex, a cross-column predicate) should be a
#: reviewed addition here, not something a caller can invent in passing.
type ColumnDomain = NumericDomain | EnumDomain


@dataclass(frozen=True, slots=True, kw_only=True)
class ForeignKey:
    """A referential link from one input column to another table's natural key.

    The cross-table sibling of :class:`NumericDomain` / :class:`EnumDomain`.
    Those two bound the values a column may hold on its own; this one states
    that a value must RESOLVE — that the row it names exists. Read generically
    by ``contracts/validation.py::validate_referential_integrity``, which emits
    ``DQ005`` for a reference that resolves to nothing and ``DQ001`` for one
    that was never supplied.

    ``reason`` is mandatory for the same reason it is mandatory on the two
    domain types, and it carries a specific burden here: it must say what the
    engine SUBSTITUTES when the link breaks. Every counterparty-attribute join
    in the hierarchy stage is ``how="left"`` and correctly so — dropping the
    exposure would lose its capital outright — so a broken link does not
    degrade to null-and-obvious, it degrades to a fallback classification that
    produces a plausible number. A declaration that does not say which number
    cannot be reviewed.

    Attributes:
        column: The referencing column on the declaring table.
        parent_table: ``TABLE_SCHEMAS`` key of the referenced table.
        parent_column: The referenced column — the parent's natural key.
        reason: Citation plus the substituted treatment. Mandatory.
    """

    column: str
    parent_table: str
    parent_column: str
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                "ForeignKey.reason is mandatory — state the citation and what the "
                "engine substitutes when the link breaks"
            )


def _trim(value: float | None) -> str:
    """Render a bound without a trailing ``.0`` on whole numbers."""
    if value is None:  # pragma: no cover — callers guard on None first
        return "None"
    return str(int(value)) if float(value).is_integer() else str(value)


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Declarative metadata for a single DataFrame column.

    Attributes:
        dtype: Polars dtype the column is cast to on load.
        default: Fill value applied by ``ensure_columns`` when the column is
            absent. Ignored when ``required`` is True.
        required: When True, a missing column is a data-quality error; the
            loader must fail (or emit a CalculationError). When False, a
            missing column is filled via ``ensure_columns`` using ``default``.
        domain: Optional admissible input domain — a ``NumericDomain``
            interval or an ``EnumDomain`` value set. Read by
            ``contracts/validation.py`` to emit a row-named
            ``CalculationError`` per offending value, and ratcheted by
            ``scripts/check_input_domains.py``. ``None`` means the column's
            domain is genuinely unbounded (or not yet established) — which is
            a reviewable statement, because the ratchet counts it.
    """

    dtype: PolarsDataType
    default: object = None
    required: bool = True
    domain: ColumnDomain | None = None


def ensure_columns(lf: pl.LazyFrame, schema: Mapping[str, ColumnSpec]) -> pl.LazyFrame:
    """Add optional columns from ``schema`` that are missing on ``lf``.

    Required columns are never added — the loader is responsible for raising
    a data-quality error when a required input column is missing. Columns
    already present on ``lf`` are left untouched (including their existing
    dtype — this function does not re-cast).
    """
    existing = set(lf.collect_schema().names())
    missing = [
        pl.lit(spec.default).cast(spec.dtype).alias(name)
        for name, spec in schema.items()
        if not spec.required and name not in existing
    ]
    if not missing:
        return lf
    return lf.with_columns(missing)


def dtypes_of(schema: Mapping[str, ColumnSpec]) -> dict[str, PolarsDataType]:
    """Project a ColumnSpec schema down to ``{column_name: dtype}``.

    Polars constructors (``pl.DataFrame(..., schema=...)``, ``pl.LazyFrame``)
    accept a plain dtype dict; this helper is the bridge for those call sites.
    """
    return {name: spec.dtype for name, spec in schema.items()}


def apply_boolean_column_defaults(
    lf: pl.LazyFrame, schema: Mapping[str, ColumnSpec]
) -> pl.LazyFrame:
    """Fill nulls in present Boolean columns with their schema defaults.

    Pipeline position:
        Called by ``loader.enforce_schema`` strictly *after* the cast pass:
        ``ensure_columns -> cast -> apply_boolean_column_defaults``. The
        order matters — running before cast against an inferred ``pl.Null``
        column would fail to type-coerce the literal cleanly.

    Why Boolean-only:
        A naive helper that filled nulls on every ``ColumnSpec(default=...)``
        column would also fill ``Float64`` defaults of ``0.0`` (e.g.
        ``LOAN_SCHEMA.drawn_amount``, ``PROVISION_SCHEMA.amount``). That is
        anti-conservative for EAD and provisions: a null in a parquet today
        propagates and surfaces in arithmetic as a null-bearing EAD (caught
        by validation); a silent ``0.0`` does not. Float and String defaults
        are intentionally **not** filled by this helper — broadening it
        requires Risk sign-off.

        The Boolean-only boundary is enforced by
        ``tests/contracts/test_boolean_defaults_only.py`` which asserts that
        non-Boolean defaults are NOT filled by this helper. Any future
        contributor who needs to broaden it must update both this helper
        and the contract test, surfacing the change for explicit review.

    Args:
        lf: LazyFrame to fill nulls on.
        schema: ColumnSpec schema. Only Boolean columns with a non-None
            default are filled; non-Boolean entries are silently skipped
            (the contract test pins this behaviour). Columns absent from
            ``lf`` are not added (use ``ensure_columns`` for that).

    Returns:
        LazyFrame with nulls filled in present Boolean columns.
    """
    existing = set(lf.collect_schema().names())

    fill_exprs = [
        pl.col(name).fill_null(pl.lit(spec.default).cast(pl.Boolean)).alias(name)
        for name, spec in schema.items()
        if spec.default is not None and spec.dtype == pl.Boolean and name in existing
    ]

    if not fill_exprs:
        return lf
    return lf.with_columns(fill_exprs)
