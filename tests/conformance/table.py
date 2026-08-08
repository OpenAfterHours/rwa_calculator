"""
Loader and matcher for the externally-authored classification decision table.

Pipeline position:
    classification_table.toml -> DecisionTable -> test_classification_conformance

Key responsibilities:
- Parse the TOML decision table into typed rules (``Rule``), exclusions and
  known disagreements, validating the authoring contract: every rule carries a
  citation, and a non-``regulation`` sourcing (or an ``unsourced`` verdict)
  carries a note.
- Resolve a verdict for one combination per field, FIRST MATCH WINS, and report
  a miss as a miss rather than defaulting.
- Report coverage as numbers — combinations generated, excluded, verdicted,
  deliberately unsourced, and rules never matched.

This module knows nothing about the engine. It is pure data plus matching, so
a change to the classifier can never quietly change what the table says.

References:
- docs/plans/independent-validation-system.md §C4a
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from tests.conformance.portfolios import Combination

#: The four asserted output fields, each with its own rule list in the TOML.
FIELDS: tuple[str, ...] = (
    "exposure_class_sa",
    "exposure_class_irb",
    "exposure_class",
    "approach",
)

#: Field -> the TOML array-of-tables holding its rules.
_RULE_SECTION: dict[str, str] = {
    "exposure_class_sa": "sa_class_rule",
    "exposure_class_irb": "irb_class_rule",
    "exposure_class": "class_rule",
    "approach": "approach_rule",
}

#: Verdict sentinel meaning "deliberately not asserted — the article text does
#: not determine this field for this combination".
UNSOURCED = "unsourced"

_TABLE_PATH = Path(__file__).with_name("classification_table.toml")


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One row of the decision table for one output field."""

    id: str
    when: tuple[tuple[str, tuple[str, ...]], ...]
    verdict: str
    sourcing: str
    citation: str
    note: str

    def matches(self, dimensions: Mapping[str, str]) -> bool:
        """True when every constrained dimension admits the combination's value."""
        return all(dimensions[name] in allowed for name, allowed in self.when)


@dataclass(frozen=True)
class Exclusion:
    """An input combination the regulation does not admit, so it is not generated."""

    id: str
    when: tuple[tuple[str, tuple[str, ...]], ...]
    reason: str
    citation: str

    def matches(self, dimensions: Mapping[str, str]) -> bool:
        return all(dimensions[name] in allowed for name, allowed in self.when)


@dataclass(frozen=True)
class Disagreement:
    """A combination set where the engine is believed to contradict the article."""

    id: str
    field: str
    when: tuple[tuple[str, tuple[str, ...]], ...]
    expected: str
    observed: str
    citation: str
    detail: str

    def matches(self, dimensions: Mapping[str, str]) -> bool:
        return all(dimensions[name] in allowed for name, allowed in self.when)


@dataclass(frozen=True)
class Coverage:
    """The C4a coverage numbers, reported rather than assumed."""

    generated: int
    excluded: int
    asserted: int
    unsourced: dict[str, int] = field(default_factory=dict)
    dead_rules: tuple[str, ...] = ()
    dead_exclusions: tuple[str, ...] = ()

    def as_report(self) -> str:
        """A one-block human-readable summary for a failure message or a log."""
        unsourced = ", ".join(f"{k}={v}" for k, v in sorted(self.unsourced.items())) or "none"
        return (
            f"generated={self.generated} excluded={self.excluded} "
            f"in_scope={self.generated - self.excluded} "
            f"field_assertions={self.asserted} unsourced[{unsourced}] "
            f"dead_rules={list(self.dead_rules)} dead_exclusions={list(self.dead_exclusions)}"
        )


@dataclass(frozen=True)
class DecisionTable:
    """The parsed table: rules per field, exclusions, and known disagreements."""

    rules: dict[str, tuple[Rule, ...]]
    exclusions: tuple[Exclusion, ...]
    disagreements: tuple[Disagreement, ...]
    meta: Mapping[str, object]

    def is_excluded(self, combo: Combination) -> Exclusion | None:
        """The first exclusion admitting ``combo``, or None."""
        dimensions = combo.as_dict()
        return next((e for e in self.exclusions if e.matches(dimensions)), None)

    def resolve(self, combo: Combination, field_name: str) -> Rule | None:
        """The first rule that matches ``combo`` for ``field_name``, or None.

        None is a HARD FAILURE for the caller — never a default. That is the
        whole point of the component: an input combination the table has no
        opinion about is a gap in the table, and a gap must be visible.
        """
        dimensions = combo.as_dict()
        return next((r for r in self.rules[field_name] if r.matches(dimensions)), None)

    def disagreement_for(self, combo: Combination, field_name: str) -> Disagreement | None:
        """The recorded disagreement covering ``(combo, field_name)``, or None."""
        dimensions = combo.as_dict()
        return next(
            (
                d
                for d in self.disagreements
                if d.field == field_name and d.matches(dimensions) and not self.is_excluded(combo)
            ),
            None,
        )

    def coverage(self, space: Iterable[Combination]) -> Coverage:
        """Measure the table against a generated space."""
        combos = list(space)
        excluded = [c for c in combos if self.is_excluded(c) is not None]
        in_scope = [c for c in combos if self.is_excluded(c) is None]

        matched_rule_ids: set[str] = set()
        matched_exclusion_ids: set[str] = set()
        for combo in excluded:
            hit = self.is_excluded(combo)
            if hit is not None:
                matched_exclusion_ids.add(hit.id)
        asserted = 0
        unsourced: dict[str, int] = {}
        for combo in in_scope:
            for field_name in FIELDS:
                rule = self.resolve(combo, field_name)
                if rule is None:
                    continue
                matched_rule_ids.add(rule.id)
                if rule.verdict == UNSOURCED:
                    unsourced[field_name] = unsourced.get(field_name, 0) + 1
                else:
                    asserted += 1

        all_rule_ids = [r.id for rules in self.rules.values() for r in rules]
        return Coverage(
            generated=len(combos),
            excluded=len(excluded),
            asserted=asserted,
            unsourced=unsourced,
            dead_rules=tuple(rid for rid in all_rule_ids if rid not in matched_rule_ids),
            dead_exclusions=tuple(
                e.id for e in self.exclusions if e.id not in matched_exclusion_ids
            ),
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_table() -> DecisionTable:
    """Parse and validate ``classification_table.toml``."""
    raw = tomllib.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    rules = {
        field_name: tuple(_rule(entry, field_name) for entry in raw.get(section, ()))
        for field_name, section in _RULE_SECTION.items()
    }
    exclusions = tuple(
        Exclusion(
            id=entry["id"],
            when=_when(entry["when"]),
            reason=entry["reason"],
            citation=entry["citation"],
        )
        for entry in raw.get("exclusion", ())
    )
    disagreements = tuple(
        Disagreement(
            id=entry["id"],
            field=entry["field"],
            when=_when(entry["when"]),
            expected=entry["expected"],
            observed=entry["observed"],
            citation=entry["citation"],
            detail=entry["detail"],
        )
        for entry in raw.get("known_disagreement", ())
    )
    _validate(rules, disagreements)
    return DecisionTable(
        rules=rules, exclusions=exclusions, disagreements=disagreements, meta=raw["meta"]
    )


def _rule(entry: Mapping[str, object], field_name: str) -> Rule:
    sourcing = str(entry.get("sourcing", ""))
    return Rule(
        id=str(entry["id"]),
        when=_when(entry["when"]),
        verdict=str(entry["verdict"]),
        sourcing=sourcing,
        citation=str(entry.get("citation", "")),
        note=str(entry.get("note", "")),
    )


def _when(raw: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Normalise a ``when`` table to (dimension, allowed values) pairs."""
    assert isinstance(raw, dict), "a rule's `when` must be a table"
    clauses: list[tuple[str, tuple[str, ...]]] = []
    for name, value in sorted(raw.items()):
        if isinstance(value, str):
            clauses.append((str(name), (value,)))
            continue
        assert isinstance(value, list), f"`when.{name}` must be a string or a list of strings"
        clauses.append((str(name), tuple(str(item) for item in value)))
    return tuple(clauses)


def _validate(rules: Mapping[str, Sequence[Rule]], disagreements: Sequence[Disagreement]) -> None:
    """Enforce the authoring contract before any assertion is made against it.

    A rule with no citation, or an unsourced / non-regulation verdict with no
    note, is an unsourced value quietly asserted — the failure mode that would
    make this component worthless.
    """
    seen: set[str] = set()
    for field_name, field_rules in rules.items():
        assert field_rules, f"no rules authored for {field_name}"
        for rule in field_rules:
            assert rule.id not in seen, f"duplicate rule id {rule.id}"
            seen.add(rule.id)
            assert rule.citation, f"{rule.id}: every rule must carry a citation"
            assert rule.sourcing in {"regulation", "convention", "scope"}, (
                f"{rule.id}: unknown sourcing {rule.sourcing!r}"
            )
            needs_note = rule.sourcing != "regulation" or rule.verdict == UNSOURCED
            assert not needs_note or rule.note, (
                f"{rule.id}: sourcing={rule.sourcing} verdict={rule.verdict} requires a note"
            )
    for disagreement in disagreements:
        assert disagreement.field in FIELDS, f"{disagreement.id}: unknown field"
        assert disagreement.citation and disagreement.detail, (
            f"{disagreement.id}: a disagreement must state the regulation and both figures"
        )
