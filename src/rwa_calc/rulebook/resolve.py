"""
Rulebook resolution — compose packs into a content-hashed ResolvedRulepack.

Pipeline position:
    Built once per run for a (regime id, reporting date) pair. Composes the
    pack modules named in ``rulebook/registry.py::REGIME_PACKS`` into a
    single frozen ``ResolvedRulepack``. Downstream, ``rulebook/compile.py``
    turns the Decimal-valued entries into Polars expressions (the only
    Decimal->float boundary); accessors here stay Decimal.

Key responsibilities:
- ``resolve(regime_id, reporting_date)`` — merge the ordered pack
  ``ENTRIES`` dicts (later overrides earlier), compute a process-stable
  content hash, and freeze the result.
- ``ResolvedRulepack`` — typed, shape-checked accessors (``scalar`` /
  ``feature`` / ``lookup`` / ``banded`` / ``decision`` / ``formula`` /
  ``schedule_value`` / ``entry``) plus an audit ``as_manifest()``.

References:
- docs/plans/target-architecture-migration.md (Phase 5 — versioned,
  citation-carrying, content-hashed regime data resolved once per run).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

from rwa_calc.rulebook.model import (
    BandedTable,
    CategoryMap,
    DateParam,
    DecisionTable,
    Feature,
    FormulaParams,
    IntParam,
    LookupTable,
    RuleEntry,
    ScalarParam,
    Schedule,
)
from rwa_calc.rulebook.registry import REGIME_PACKS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from decimal import Decimal


# =============================================================================
# RESOLVED RULEPACK — the frozen, content-hashed result
# =============================================================================


@dataclass(frozen=True)
class ResolvedRulepack:
    """A frozen, content-hashed set of cited rule entries for one regime/date.

    ``entries`` maps entry name -> ``RuleEntry``. Accessors are shape-checked:
    each raises ``KeyError`` if the name is absent and ``TypeError`` if the
    named entry is the wrong rule shape.
    """

    regime_id: str
    reporting_date: date
    entries: Mapping[str, RuleEntry]
    content_hash: str

    @property
    def id(self) -> str:
        """Stable identity ``<regime_id>@<reporting_date ISO>``."""
        return f"{self.regime_id}@{self.reporting_date.isoformat()}"

    def entry(self, name: str) -> RuleEntry:
        """Return the raw ``RuleEntry`` named ``name`` (raises ``KeyError``)."""
        try:
            return self.entries[name]
        except KeyError:
            raise KeyError(f"rulepack {self.id!r} has no entry {name!r}") from None

    def scalar(self, name: str) -> Decimal:
        """Return a ``ScalarParam`` value (raises ``TypeError`` if wrong shape)."""
        return self._typed(name, ScalarParam).value

    def scalar_param(self, name: str) -> ScalarParam:
        """Return the ``ScalarParam`` entry itself (raises ``TypeError`` if wrong shape).

        The entry-returning sibling of :meth:`scalar` (which returns only the
        ``Decimal`` value), for callers that hand the shape to
        ``rulebook/compile.py`` — symmetric with ``lookup`` / ``banded`` /
        ``decision`` / ``formula``.
        """
        return self._typed(name, ScalarParam)

    def int_param(self, name: str) -> IntParam:
        """Return an ``IntParam`` entry (raises ``TypeError`` if wrong shape).

        Consumers read ``.value`` for the raw ``int`` — there is no
        Decimal->float compile boundary for integer counts.
        """
        return self._typed(name, IntParam)

    def date_param(self, name: str) -> DateParam:
        """Return a ``DateParam`` entry (raises ``TypeError`` if wrong shape).

        Consumers read ``.value`` for the raw ``date`` — there is no
        Decimal->float compile boundary for calendar dates.
        """
        return self._typed(name, DateParam)

    def feature(self, name: str) -> bool:
        """Return a ``Feature`` flag (raises ``TypeError`` if wrong shape)."""
        return self._typed(name, Feature).enabled

    def lookup(self, name: str) -> LookupTable:
        """Return a ``LookupTable`` (raises ``TypeError`` if wrong shape)."""
        return self._typed(name, LookupTable)

    def category_map(self, name: str) -> CategoryMap:
        """Return a ``CategoryMap`` (raises ``TypeError`` if wrong shape).

        The string-valued sibling of :meth:`lookup`; consumers rebuild a plain
        ``dict`` from ``.entries`` for ``Expr.replace_strict``.
        """
        return self._typed(name, CategoryMap)

    def banded(self, name: str) -> BandedTable:
        """Return a ``BandedTable`` (raises ``TypeError`` if wrong shape)."""
        return self._typed(name, BandedTable)

    def decision(self, name: str) -> DecisionTable:
        """Return a ``DecisionTable`` (raises ``TypeError`` if wrong shape)."""
        return self._typed(name, DecisionTable)

    def formula(self, name: str) -> FormulaParams:
        """Return a ``FormulaParams`` (raises ``TypeError`` if wrong shape)."""
        return self._typed(name, FormulaParams)

    def schedule(self, name: str) -> Schedule:
        """Return the ``Schedule`` entry itself (raises ``TypeError`` if wrong shape).

        The entry-returning sibling of :meth:`schedule_value` (which resolves at
        ``self.reporting_date``), for callers that need the step structure — e.g.
        the equity transitional floor, which distinguishes "before the first step"
        (no transition → None) from "resolved to the before-first value".
        """
        return self._typed(name, Schedule)

    def schedule_value(self, name: str) -> Decimal:
        """Resolve the named ``Schedule`` at ``self.reporting_date``."""
        return self._typed(name, Schedule).resolve(self.reporting_date)

    def with_overrides(self, **entries: RuleEntry) -> ResolvedRulepack:
        """Return a copy with the named entries replaced, content hash recomputed.

        For amendment overlays and tests that substitute individual entries (e.g.
        an overridden floor bundle) onto an already-resolved pack. Keyword names
        are entry names; each value replaces (or adds) that entry. The result is a
        frozen pack whose content hash covers the merged entry set, so an
        overridden pack never carries the pre-override digest.
        """
        merged = {**self.entries, **entries}
        return ResolvedRulepack(
            regime_id=self.regime_id,
            reporting_date=self.reporting_date,
            entries=merged,
            content_hash=_content_hash(self.regime_id, self.reporting_date, merged),
        )

    def as_manifest(self) -> dict[str, object]:
        """Return a stable, audit-friendly summary of the resolved pack.

        Entries are sorted by name; each carries its kind, citation string,
        and a stable value summary (the scalar/feature value, or a structural
        summary for table-shaped entries).
        """
        manifest_entries = [
            {
                "name": name,
                "kind": type(self.entries[name]).__name__,
                "citation": str(self.entries[name].citation),
                "value": _manifest_value(self.entries[name]),
            }
            for name in sorted(self.entries)
        ]
        return {
            "id": self.id,
            "regime_id": self.regime_id,
            "reporting_date": self.reporting_date.isoformat(),
            "content_hash": self.content_hash,
            "entries": manifest_entries,
        }

    def _typed[T: RuleEntry](self, name: str, shape: type[T]) -> T:
        """Return ``entry(name)`` checked to be an instance of ``shape``."""
        value = self.entry(name)
        if not isinstance(value, shape):
            raise TypeError(
                f"rulepack {self.id!r} entry {name!r} is a "
                f"{type(value).__name__}, expected {shape.__name__}"
            )
        return value


# =============================================================================
# RESOLUTION ENTRY POINT
# =============================================================================


def resolve(regime_id: str, reporting_date: date) -> ResolvedRulepack:
    """Compose the regime's packs into a frozen, content-hashed rulepack.

    Merges the ``ENTRIES`` dicts of the pack modules named in
    ``REGIME_PACKS[regime_id]`` in order (later overrides earlier on name
    collision), computes a process-stable SHA-256 content hash over the
    sorted entries, and freezes the result.

    Raises ``ValueError`` for an unknown ``regime_id``.
    """
    pack_names = REGIME_PACKS.get(regime_id)
    if pack_names is None:
        raise ValueError(f"unknown regime_id {regime_id!r} (supported: {sorted(REGIME_PACKS)})")
    merged: dict[str, RuleEntry] = {}
    for pack_name in pack_names:
        module = import_module(f"rwa_calc.rulebook.packs.{pack_name}")
        merged.update(module.ENTRIES)
    content_hash = _content_hash(regime_id, reporting_date, merged)
    return ResolvedRulepack(
        regime_id=regime_id,
        reporting_date=reporting_date,
        entries=dict(merged),
        content_hash=content_hash,
    )


# =============================================================================
# PRIVATE HELPERS — content hashing & manifest summaries
# =============================================================================


def _content_hash(regime_id: str, reporting_date: date, entries: Mapping[str, RuleEntry]) -> str:
    """SHA-256 hexdigest over a canonical, process-stable serialisation.

    The serialisation uses only stable string forms (``str(Decimal)``, sorted
    dict items, ISO dates) — never Python's salted ``hash()`` or the ``repr``
    of an unordered set — so the digest is identical across processes.
    """
    parts = [f"regime={regime_id}", f"date={reporting_date.isoformat()}"]
    for name in sorted(entries):
        entry = entries[name]
        parts.append(f"{name}|{type(entry).__name__}|{entry.citation}|{_value_repr(entry)}")
    canonical = "\n".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _value_repr(entry: RuleEntry) -> str:
    """A deterministic, process-stable value representation for hashing."""
    if isinstance(entry, ScalarParam):
        return str(entry.value)
    if isinstance(entry, IntParam):
        return str(entry.value)
    if isinstance(entry, DateParam):
        return entry.value.isoformat()
    if isinstance(entry, Feature):
        return str(entry.enabled)
    if isinstance(entry, LookupTable):
        items = ",".join(f"{key!r}:{entry.entries[key]}" for key in _sorted_keys(entry.entries))
        return f"key={entry.key};default={entry.default};{{{items}}}"
    if isinstance(entry, CategoryMap):
        items = ",".join(f"{key!r}:{entry.entries[key]}" for key in sorted(entry.entries))
        return f"key={entry.key};default={entry.default};{{{items}}}"
    if isinstance(entry, BandedTable):
        bands = ",".join(f"{bound}<={value}" for bound, value in entry.bands)
        return f"input={entry.input};right_closed={entry.right_closed};[{bands}]"
    if isinstance(entry, Schedule):
        steps = ",".join(f"{d.isoformat()}={v}" for d, v in entry.steps)
        return f"before_first={entry.before_first};[{steps}]"
    if isinstance(entry, DecisionTable):
        rows = ",".join(f"{keys!r}={value}" for keys, value in entry.rows)
        return f"keys={entry.key_names};default={entry.default};[{rows}]"
    if isinstance(entry, FormulaParams):
        items = ",".join(f"{key}:{entry.params[key]}" for key in sorted(entry.params))
        return f"{{{items}}}"
    raise TypeError(f"un-hashable rule entry shape: {type(entry).__name__}")


def _manifest_value(entry: RuleEntry) -> object:
    """A stable manifest summary value for one rule entry."""
    if isinstance(entry, ScalarParam):
        return str(entry.value)
    if isinstance(entry, IntParam):
        return entry.value
    if isinstance(entry, Feature):
        return entry.enabled
    return _value_repr(entry)


def _sorted_keys(entries: Mapping[object, Decimal]) -> list[object]:
    """Sort heterogeneous lookup keys deterministically by their repr."""
    return sorted(entries, key=repr)
