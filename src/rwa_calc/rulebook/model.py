"""
Rulebook rule-shape vocabulary — the regime-as-data model.

Pipeline position:
    Authored in ``rulebook/packs/*`` (one pack module per regime layer),
    merged by ``rulebook/resolve.py`` into a ``ResolvedRulepack``, and
    compiled to Polars expressions by ``rulebook/compile.py`` once per run
    (the only Decimal->float boundary). This module is the at-rest model:
    every regulatory value stays ``Decimal`` here and carries a mandatory
    article citation.

Key responsibilities:
- Define the small fixed vocabulary of rule shapes (migration Phase 5
  principle 2): ``ScalarParam``, ``IntParam``, ``LookupTable``,
  ``CategoryMap``, ``BandedTable``, ``Schedule``, ``DecisionTable``,
  ``FormulaParams``, ``Feature``. All are Decimal-valued except ``IntParam``
  (integer counts) and ``CategoryMap`` (string category labels).
- Define ``Citation``, the framework + article provenance carried by every
  entry, with a string form matching the watchfire citation grammar.
- Stay free of Polars and of any ``float(...)`` of a regulatory value —
  those live exclusively in ``rulebook/compile.py``.

References:
- docs/plans/target-architecture-migration.md (Phase 5, principle 2 —
  "Regimes are data"; the rule-shape vocabulary and the Decimal->float
  compile boundary).
- docs/development/citation-tracking.md (the watchfire citation grammar the
  ``Citation`` string form matches: ``CRR Art. <n>`` / ``PS1/26,
  paragraph <n>``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping
    from datetime import date


# =============================================================================
# CITATION — provenance carried by every rule entry
# =============================================================================


@dataclass(frozen=True)
class Citation:
    """Regulatory provenance for a single rule entry.

    ``framework`` is the instrument short name (e.g. ``"CRR"``, ``"PS1/26"``)
    and ``article`` the article / paragraph reference (e.g. ``"153(1)"``).
    The string form matches the watchfire citation grammar: CRR uses the
    ``Art.`` form, PS1/26 uses the ``paragraph`` form.
    """

    framework: str
    article: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.framework:
            raise ValueError("Citation.framework must be non-empty")
        if not self.article:
            raise ValueError("Citation.article must be non-empty")

    def __str__(self) -> str:
        if self.framework == "PS1/26":
            return f"PS1/26, paragraph {self.article}"
        return f"{self.framework} Art. {self.article}"


# =============================================================================
# RULE SHAPES — the small fixed vocabulary (every entry Decimal-valued)
# =============================================================================


@dataclass(frozen=True)
class ScalarParam:
    """A single cited regulatory scalar (e.g. a scaling factor or haircut)."""

    name: str
    value: Decimal
    citation: Citation


@dataclass(frozen=True)
class IntParam:
    """A single cited integer-typed regulatory count.

    The int sibling of :class:`ScalarParam`, for regulatory *counts* that must
    stay integers end-to-end — MPOR business-day floors, settlement-band day
    bounds, trade-count thresholds, property-count limits, the zero-haircut CQS
    cap. There is no Decimal->float compile boundary for these: consumers read
    ``int_param(name).value`` and use the raw ``int`` directly (a deliberate
    float of one — e.g. the days-per-year divisor — happens at the call site,
    never here).
    """

    name: str
    value: int
    citation: Citation


@dataclass(frozen=True)
class LookupTable:
    """An exact-match lookup from a key column to a cited Decimal value.

    ``key`` names the input column matched against ``entries``; ``default``
    (if set) is the fallback value for keys absent from ``entries``.
    """

    name: str
    entries: Mapping[Hashable, Decimal]
    key: str
    citation: Citation
    default: Decimal | None = None


@dataclass(frozen=True)
class CategoryMap:
    """A cited exact-match mapping from one category label to another.

    The string-valued sibling of :class:`LookupTable`: regulatory
    *classification* mappings (entity_type -> exposure class, OBS product ->
    Annex I risk type) where both key and value are category labels, not Decimal
    rates. Consumed in Python — rebuilt into a plain ``dict`` for
    ``Expr.replace_strict`` — never compiled to a Polars float. ``key`` names the
    intended input column. The fallback for keys absent from ``entries`` is a
    consumer-side ``replace_strict`` default that may differ per call site (e.g.
    the residual ``OTHER`` class vs an empty "no-class" sentinel), so ``default``
    here is an optional documentation aid, not an authoritative single fallback.
    """

    name: str
    entries: Mapping[str, str]
    key: str
    citation: Citation
    default: str | None = None


@dataclass(frozen=True)
class BandedTable:
    """An ordered banded (threshold) table over a numeric input column.

    ``bands`` is an ordered tuple of ``(upper_bound, value)`` pairs. A band
    applies when ``input <= upper_bound`` (or ``input < upper_bound`` when
    ``right_closed`` is False). A ``None`` upper bound is the catch-all top
    band and must be last. Finite bounds must be strictly increasing.
    """

    name: str
    bands: tuple[tuple[Decimal | None, Decimal], ...]
    input: str
    citation: Citation
    right_closed: bool = True

    def __post_init__(self) -> None:
        if not self.bands:
            raise ValueError(f"BandedTable {self.name!r}: bands must be non-empty")
        for bound, _ in self.bands[:-1]:
            if bound is None:
                raise ValueError(
                    f"BandedTable {self.name!r}: only the last band may have a None bound"
                )
        finite = [bound for bound, _ in self.bands if bound is not None]
        for lower, upper in zip(finite, finite[1:], strict=False):
            if upper <= lower:
                raise ValueError(
                    f"BandedTable {self.name!r}: finite bounds must be strictly increasing"
                )


@dataclass(frozen=True)
class Schedule:
    """A date-stepped Decimal value with carry-forward semantics.

    ``steps`` is an ordered tuple of ``(effective_date, value)`` pairs sorted
    by date. ``resolve(on)`` returns the value of the last step whose date is
    on or before ``on``, else ``before_first``. An "expire" is modelled as an
    explicit step back to 0.
    """

    name: str
    steps: tuple[tuple[date, Decimal], ...]
    before_first: Decimal
    citation: Citation

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError(f"Schedule {self.name!r}: steps must be non-empty")
        dates = [step_date for step_date, _ in self.steps]
        if dates != sorted(dates):
            raise ValueError(f"Schedule {self.name!r}: steps must be sorted by date")

    def resolve(self, on: date) -> Decimal:
        """Value of the last step whose date is <= ``on``, else ``before_first``."""
        result = self.before_first
        for step_date, value in self.steps:
            if step_date <= on:
                result = value
            else:
                break
        return result


@dataclass(frozen=True)
class DecisionTable[V = Decimal]:
    """A multi-key decision table mapping cited key-tuples to a value.

    ``key_names`` names the input columns (in order); each row in ``rows`` is
    a ``(key_tuple, value)`` pair whose key-tuple length must equal
    ``len(key_names)``. ``default`` (if set) is the fallback value when no row
    matches. The value type defaults to ``Decimal`` but categorical decision
    tables (consumed in Python, not compiled) may use other value types.
    """

    name: str
    key_names: tuple[str, ...]
    rows: tuple[tuple[tuple[Hashable, ...], V], ...]
    citation: Citation
    default: V | None = None

    def __post_init__(self) -> None:
        width = len(self.key_names)
        for keys, _ in self.rows:
            if len(keys) != width:
                raise ValueError(
                    f"DecisionTable {self.name!r}: row key-tuple {keys!r} has length "
                    f"{len(keys)}, expected {width} (len(key_names))"
                )


@dataclass(frozen=True)
class FormulaParams:
    """A named bundle of cited Decimal parameters for one formula."""

    name: str
    params: Mapping[str, Decimal]
    citation: Citation

    def get(self, key: str) -> Decimal:
        """Return the cited Decimal parameter ``key`` (raises ``KeyError`` if absent)."""
        return self.params[key]


@dataclass(frozen=True)
class Feature:
    """A cited on/off regime feature flag."""

    name: str
    enabled: bool
    citation: Citation


# =============================================================================
# RULE-ENTRY UNION — the pack-entry value type
# =============================================================================

type RuleEntry = (
    ScalarParam
    | IntParam
    | LookupTable
    | CategoryMap
    | BandedTable
    | Schedule
    | DecisionTable
    | FormulaParams
    | Feature
)
