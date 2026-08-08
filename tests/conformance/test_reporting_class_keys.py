"""
C4a — every exposure-class collection in ``rwa_calc.reporting`` is keyed on the enum.

Pipeline position:
    rwa_calc.reporting.** (introspected) -> these assertions

Key responsibilities:
- DISCOVER the class collections rather than listing them: walk every module of
  ``rwa_calc.reporting``, pull out each homogeneous group of exposure-class-like
  strings, and check the whole estate in one assertion.
- Anchor the assertion to ``{m.value for m in ExposureClass}`` — never to a
  hand-written list of class strings. ``.claude/LESSONS.md`` B2/B3: the phantom
  ``C02_00_SA_CLASS_MAP`` passed its own test because the test used the same
  invented strings the map did.

Why discovery and not enumeration: a map added tomorrow is checked without
anyone remembering to add it here. The trade-off is a heuristic, so the
heuristic is stated, bounded, and guarded against becoming vacuous — a
discovery that finds nothing would pass silently, which is the same failure
class the check exists to prevent.

Note that an EMPTY class tuple is not a violation. Rows 13 and 14 of
``SA_DISCLOSURE_CLASSES`` (short-term claims, CIUs) have no ``ExposureClass``
member and are legitimately empty; the assertion is "no member that is not an
``ExposureClass`` value", not "no empty group".

References:
- CRR Art. 112 / Art. 147: the exposure classes the enum represents
- docs/plans/independent-validation-system.md §C4a
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING, Any

import rwa_calc.reporting
from rwa_calc.domain.enums import ExposureClass

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

logger = logging.getLogger(__name__)

#: The one source of truth. Never a hand-written list of class strings.
CLASS_VALUES: frozenset[str] = frozenset(m.value for m in ExposureClass)

#: A SLOT (a dict's keys, a dict's values, a tuple position, a dataclass field)
#: is a candidate exposure-class axis when it holds at least this many real
#: class values and they are at least this proportion of it.
#:
#: The ratio floor separates a class axis from the neighbouring ROW-KEY
#: vocabularies, which deliberately reuse several class names alongside their
#: own (``mortgage_sme``, ``sl_slotting``, ``ciu_look_through`` in
#: ``COREPRow.exposure_class_value``; ``corporate_other_non_sme`` in the CR9
#: row keys). Those sit at 0.42-0.67. It is calibrated to stay BELOW the shape
#: the check exists to catch: the historical ``C02_00_SA_CLASS_MAP``, which
#: carried two invented keys among seventeen real ones (0.89). That claim is
#: not asserted by argument — ``test_the_check_catches_a_planted_phantom_key``
#: plants exactly that map and requires it to be caught.
_MIN_HITS = 2
_MIN_RATIO = 0.8

#: How far structural recursion goes. Everything in this estate is a dict, a
#: sequence of tuples, or a sequence of small dataclasses; nothing needs more.
_MAX_DEPTH = 3

#: Anti-vacuity floors. If discovery silently stops finding collections — a
#: renamed package, an import that starts failing, a heuristic that drifts —
#: these fail rather than letting the file go green on nothing.
_MIN_GROUPS = 10
_MIN_DISTINCT_CLASSES = 12


def test_every_reporting_class_collection_is_keyed_on_the_enum() -> None:
    """No reporting collection of exposure classes contains a non-member.

    Arrange: import every module under ``rwa_calc.reporting`` and extract each
    homogeneous group of exposure-class-like strings.
    Act: intersect each group with ``{m.value for m in ExposureClass}``.
    Assert: any group that clearly holds exposure classes holds ONLY exposure
    classes. An unmatched key does not raise anywhere in production — it
    zero-fills, so the breakdown row silently sheds exposure while the
    independently-computed parent still counts it.
    """
    groups = list(_discover_class_groups())
    offenders = {
        origin: sorted(members - CLASS_VALUES)
        for origin, members in groups
        if not members <= CLASS_VALUES
    }
    assert not offenders, (
        "reporting collections keyed on strings that are not ExposureClass members:\n  "
        + "\n  ".join(f"{origin}: {extra}" for origin, extra in sorted(offenders.items()))
    )


def test_the_discovery_is_not_vacuous() -> None:
    """Discovery finds a real estate of collections, covering most of the enum.

    Without this, a heuristic that stopped matching anything would make the
    check above pass on the empty set — the exact shape of failure it exists to
    catch.
    """
    groups = list(_discover_class_groups())
    covered = set().union(*(members for _origin, members in groups)) & CLASS_VALUES
    logger.info(
        "C4a reporting-key discovery: %d group(s) across %d module(s), %d distinct classes",
        len(groups),
        len({origin.split("::", 1)[0] for origin, _ in groups}),
        len(covered),
    )
    assert len(groups) >= _MIN_GROUPS, f"only {len(groups)} class group(s) discovered"
    assert len(covered) >= _MIN_DISTINCT_CLASSES, f"only {sorted(covered)} covered"


def test_the_check_catches_a_planted_phantom_key() -> None:
    """The detector catches the historical defect it was built for.

    Arrange: a namespace holding the ``C02_00_SA_CLASS_MAP`` shape as it was
    when two invented strings (``central_government``, ``retail``) sat among the
    real class values — the map keyed on names no pipeline run produces, whose
    own test used the same invented names and therefore proved nothing
    (``.claude/LESSONS.md`` B2/B3).
    Act: run the same discovery the estate-wide check runs.
    Assert: the phantom keys are found. Without this, the ratio floor above
    could be raised until nothing is ever checked and every assertion in this
    file would still pass.
    """
    planted = {
        "C02_00_SA_CLASS_MAP": {
            "central_government": "0070",  # phantom — the real value is central_govt_central_bank
            "rgla": "0080",
            "pse": "0090",
            "mdb": "0100",
            "international_organisation": "0110",
            "institution": "0120",
            "corporate": "0130",
            "corporate_sme": "0130",
            "specialised_lending": "0130",
            "retail": "0140",  # phantom — the real values are retail_other / retail_qrre
            "retail_qrre": "0140",
            "retail_mortgage": "0150",
            "residential_mortgage": "0150",
            "commercial_mortgage": "0150",
            "defaulted": "0160",
            "high_risk": "0170",
            "covered_bond": "0180",
            "equity": "0210",
            "other": "0211",
        }
    }
    found = {
        origin: sorted(members - CLASS_VALUES)
        for origin, members in _class_groups_in(planted, "planted")
        if not members <= CLASS_VALUES
    }
    assert found == {"planted::C02_00_SA_CLASS_MAP.keys": ["central_government", "retail"]}, found


# ---------------------------------------------------------------------------
# Discovery (private)
# ---------------------------------------------------------------------------


def _discover_class_groups() -> Iterator[tuple[str, frozenset[str]]]:
    """Yield ``(origin, members)`` — one exposure-class axis per collection.

    A collection has AT MOST ONE exposure-class axis, so the best-fitting slot
    wins and the rest are left alone. Without that rule the value side of every
    ``class -> row_key`` map is checked as if it were a class axis, and its row
    keys (``retail``, ``corporate_financial_large``) look like violations when
    they are simply a different vocabulary. The trade-off is stated: a
    collection with two class axes has only its best-fitting one checked.
    """
    for module_name in _reporting_modules():
        module = importlib.import_module(module_name)
        yield from _class_groups_in(vars(module), module_name, home=module_name)


def _class_groups_in(
    namespace: Mapping[str, Any], origin: str, *, home: str | None = None
) -> Iterator[tuple[str, frozenset[str]]]:
    """Yield the exposure-class axis of every collection in one namespace.

    ``home`` restricts the scan to objects DEFINED in that module, so a symbol
    re-exported through a package ``__init__`` is checked once, where it lives.
    """
    for attribute in sorted(namespace):
        if attribute.startswith("__"):
            continue
        value = namespace[attribute]
        if home is not None and getattr(value, "__module__", home) != home:
            continue
        best = _best_class_slot(_string_groups(value))
        if best is not None:
            suffix, members = best
            yield f"{origin}::{attribute}{suffix}", members


def _best_class_slot(
    slots: Iterator[tuple[str, frozenset[str]]],
) -> tuple[str, frozenset[str]] | None:
    """The candidate slot with the highest class-hit ratio, or None."""
    candidates = [(s, m) for s, m in slots if _is_class_group(m)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (_hit_ratio(item[1]), len(item[1] & CLASS_VALUES)))


def _hit_ratio(members: frozenset[str]) -> float:
    return len(members & CLASS_VALUES) / len(members) if members else 0.0


def _reporting_modules() -> list[str]:
    """Every importable module of the ``rwa_calc.reporting`` package."""
    return [
        info.name
        for info in pkgutil.walk_packages(rwa_calc.reporting.__path__, prefix="rwa_calc.reporting.")
    ]


def _string_groups(value: Any) -> Iterator[tuple[str, frozenset[str]]]:
    """Yield every structural SLOT of ``value`` that holds strings.

    A dict contributes its key set and the slots of its values; any other
    collection contributes the slots of its elements. Slots are kept SEPARATE
    — a tuple position, a dataclass field and the flattened contents of a
    nested collection are three different vocabularies, and merging them is
    what makes an approach value look like a broken class key.
    """
    if isinstance(value, dict):
        keys = frozenset(k for k in value if isinstance(k, str))
        if keys:
            yield ".keys", keys
        for suffix, members in _element_slots(list(value.values()), depth=1):
            yield f".values{suffix}", members
        return
    if isinstance(value, (set, frozenset, tuple, list)):
        yield from _element_slots(list(value), depth=0)


def _element_slots(items: list[Any], depth: int) -> Iterator[tuple[str, frozenset[str]]]:
    """Slots over a collection of same-shaped elements.

    Tuple positions are split only at the top level (``depth == 0``): splitting
    an inner tuple of class values positionally would let a clean position out-
    score, and so hide, the broken union it belongs to. Dataclass fields are
    split at any depth up to ``_MAX_DEPTH`` because a dataclass field IS a
    distinct vocabulary wherever it appears.
    """
    if depth > _MAX_DEPTH:
        return
    direct = frozenset(item for item in items if isinstance(item, str))
    if direct:
        yield "", direct
    nested: set[str] = set()
    for item in items:
        if isinstance(item, (set, frozenset, tuple, list)):
            nested.update(inner for inner in item if isinstance(inner, str))
    if nested:
        yield "[]", frozenset(nested)
    if depth == 0:
        rows = [item for item in items if isinstance(item, tuple)]
        for position in range(max((len(row) for row in rows), default=0)):
            cells = [row[position] for row in rows if len(row) > position]
            for suffix, members in _element_slots(cells, depth + 1):
                yield f"[{position}]{suffix}", members
    records = [item for item in items if is_dataclass(item) and not isinstance(item, type)]
    for name in sorted({spec.name for record in records for spec in fields(record)}):
        values = [getattr(record, name) for record in records if hasattr(record, name)]
        for suffix, members in _element_slots(values, depth + 1):
            yield f".{name}{suffix}", members


def _is_class_group(members: frozenset[str]) -> bool:
    """Whether a discovered group is an exposure-class collection.

    Stated rather than tuned: at least :data:`_MIN_HITS` real class values, and
    at least :data:`_MIN_RATIO` of the group. A group that fails the ratio test
    is a row-key or label axis that merely reuses some class names.
    """
    hits = len(members & CLASS_VALUES)
    return hits >= _MIN_HITS and hits >= _MIN_RATIO * len(members)
