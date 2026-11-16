"""
Formula reach — the dimensions each rule's XBRL formula closes, and those each
of its summed variables spans.

Pipeline position:
    taxonomy package (.zip)  ->  read_formula_reach  ->  importer.import_workbook
        ->  rule book (.json: ``formula_dimensions``, per rule ``open`` /
            ``closed`` / ``spans``)
        ->  catalogue.Rule.closed / closed_by_variable / spans_by_variable  ->  engine

Every published rule exists twice: as a row of the validation workbook, which
the engine reads, and as an XBRL formula assertion in the taxonomy package,
which is what the Bank's gateway runs. The two are generated from one source
and almost always say the same thing. Where they do not, the formula wins —
it is the one that decides whether a submission is accepted.

Key responsibilities:
- Read, for every rule of a framework version, which dimensions its formula
  CLOSES: fixes to the default member, or requires to be absent. A fact that
  carries a closed dimension can never bind in that formula.
- Keep the two levels apart: a dimension closed for the whole variable set, and
  one closed for a single variable.
- Read, for every variable bound AS A SEQUENCE (the operand of a sum or a
  count), which dimensions its own filters COVER. It takes every value of those
  at once; every dimension it leaves uncovered is matched, fact by fact, to the
  rest of the rule (implicit filtering). A filter hung off the variable SET
  covers nothing, and a filter nested in a boolean filter covers what that
  filter covers.
- Read nothing else. Which member a formula fixes an OPEN dimension to is the
  cell's own data point and is already what the rule text names.

Why this exists: in taxonomy 4.1.1 the formulas for table OF 91.01 fix the
table's own sheet dimension (``eba_dim:PRP``) to its default member, so no
reported fact of that table can bind and seven rules never fire — measured
with Arelle on the Bank's sample instance. Evaluated from the workbook text
alone, those rules would run, and could block a return the gateway accepts.

Why the spans exist: the text of a sum cannot say what it adds up.
``isum({t: OF08.02.01.01, c: 0040; 0050; 0060, seq: True})`` is the same text
whether the formula covers the obligor-grade dimension (the sum runs over every
grade, as in ``boe_b0752``) or leaves it uncovered (it runs over the grade the
rest of the rule is read at, as in ``boe_b0761``). Read from the text alone, the
engine summed every grade in ``boe_b0760``-``b0763`` and failed each grade of
every OF 08.02 sheet with more than one, where Arelle passes them — and 24 more
rules in three rule books were misread the same way, in one direction or the
other (escape log, 2026-11-16).

References:
- XBRL Formula 1.0; Dimension Filters 1.0 (explicit and typed dimension filters)
- XBRL Variables 1.0 — bind as sequence, covered aspects, implicit filtering;
  Boolean Filters 1.0
- Bank of England Banking Taxonomy v4.1.1 — ``fws/**/val/vr-*.xml``
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from rwa_filer.inputs import open_zip

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: Rule-book keys. ``formula_dimensions`` (the file) lists every dimension some
#: formula closes; a rule's ``open`` lists those of them ITS formula leaves
#: open, its ``closed`` the ones closed for a single variable only, and its
#: ``spans`` what each variable bound as a sequence covers.
KEY_FORMULAS: Final = "formulas"
KEY_DIMENSIONS: Final = "formula_dimensions"
KEY_OPEN: Final = "open"
KEY_CLOSED: Final = "closed"
KEY_SPANS: Final = "spans"

#: The local name of a domain's default member in the DPM architecture
#: ("not applicable / all members"). A formula that fixes a dimension to it
#: admits only facts that do not carry the dimension.
DEFAULT_MEMBER: Final = "x0"

_XLINK: Final = "{http://www.w3.org/1999/xlink}"
_DIMENSION_FILTER: Final = "{http://xbrl.org/2008/filter/dimension}"
_BOOLEAN_FILTER: Final = "{http://xbrl.org/2008/filter/boolean}"
_VARIABLE: Final = "{http://xbrl.org/2008/variable}"
_EXPLICIT: Final = f"{_DIMENSION_FILTER}explicitDimension"
_TYPED: Final = f"{_DIMENSION_FILTER}typedDimension"
_SET_FILTER_ARC: Final = f"{_VARIABLE}variableSetFilterArc"
_VARIABLE_FILTER_ARC: Final = f"{_VARIABLE}variableFilterArc"
_VARIABLE_ARC: Final = f"{_VARIABLE}variableArc"
_FACT_VARIABLE: Final = f"{_VARIABLE}factVariable"
_BOOLEAN_FILTERS: Final = (f"{_BOOLEAN_FILTER}andFilter", f"{_BOOLEAN_FILTER}orFilter")

#: ``<folder>/val/vr-<rule>.xml`` — a rule's formula, not its message files
#: (``vr-<rule>-err-en.xml`` and the like sit beside it).
_FORMULA_FILE: Final = re.compile(r"/fws/(?P<folder>.+)/val/vr-(?P<rule>[^/]+)\.xml$")
#: XML that declares a document type or an entity is refused, not parsed.
_FORBIDDEN: Final = (b"<!DOCTYPE", b"<!ENTITY")


# =============================================================================
# Public entry point
# =============================================================================


class FormulaPackageError(ValueError):
    """The taxonomy package does not hold formulas for the rules asked about."""


@dataclass(frozen=True)
class RuleReach:
    """What one rule's formula closes, and what each of its summed variables spans.

    Attributes:
        closed: Dimensions closed for every variable of the rule.
        closed_by_variable: Dimensions closed for one variable only, by the
            variable's name (``v0``).
        spans_by_variable: For EVERY variable bound as a sequence, by name, the
            dimensions its own filters cover and admit facts for — possibly
            none. Dimensions it closes are left out: it spans nothing there.
    """

    closed: frozenset[str] = frozenset()
    closed_by_variable: Mapping[str, frozenset[str]] = field(default_factory=dict)
    spans_by_variable: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class FormulaReach:
    """The reach of every formula of one framework version.

    Attributes:
        folder: Where in the package the formulas were read from, e.g.
            ``banking/banking_reporting/2026-08-17``.
        rules: A ``RuleReach`` per rule that has a formula, by rule code.
    """

    folder: str
    rules: Mapping[str, RuleReach]

    @property
    def dimensions(self) -> tuple[str, ...]:
        """Every dimension some rule closes for its whole variable set, sorted."""
        return tuple(sorted({dim for reach in self.rules.values() for dim in reach.closed}))


def read_formula_reach(package: Path, rule_ids: Collection[str]) -> FormulaReach:
    """Read what each of ``rule_ids``' formulas closes, from a taxonomy package.

    The package holds one formula folder per framework version, and two
    framework versions can share rule codes (the full and the SDDT banking
    frameworks do). The folder read is the one whose formulas are ``rule_ids``
    most exactly: the most of them found, then the fewest others beside them.

    Args:
        package: The publisher's taxonomy package zip.
        rule_ids: The rule codes of one framework version's XBRL rules.

    Raises:
        FormulaPackageError: no folder of the package holds a formula for any
            of the rules.
        ValueError: ``package`` is not a zip archive.
    """
    wanted = set(rule_ids)
    with open_zip(package) as archive:
        folders: dict[str, dict[str, str]] = {}
        for name in archive.namelist():
            match = _FORMULA_FILE.search(name)
            if match is not None:
                folders.setdefault(match.group("folder"), {})[match.group("rule")] = name
        ranked = sorted(
            (
                (-len(wanted & set(files)), len(set(files) - wanted), folder)
                for folder, files in folders.items()
            ),
        )
        if not ranked or ranked[0][0] == 0:
            raise FormulaPackageError(
                f"{package.name} holds no formula for any of the {len(wanted)} rule(s) asked about"
            )
        folder = ranked[0][2]
        files = folders[folder]
        rules = {
            rule_id: _reach(archive.read(files[rule_id]), files[rule_id])
            for rule_id in sorted(wanted & set(files))
        }
    logger.info(
        "read %d formula(s) from %s in %s (%d rule(s) have none)",
        len(rules),
        folder,
        package.name,
        len(wanted) - len(rules),
    )
    return FormulaReach(folder=folder, rules=rules)


# =============================================================================
# Private helpers
# =============================================================================


def _reach(content: bytes, name: str) -> RuleReach:
    """The dimensions one formula file closes."""
    if any(marker in content for marker in _FORBIDDEN):
        raise FormulaPackageError(f"{name} declares a document type or an entity; not read")
    root = ET.fromstring(content)  # noqa: S314 - DOCTYPE and ENTITY refused above
    resources = {
        label: element for element in root.iter() if (label := element.get(f"{_XLINK}label"))
    }
    variables = {
        target: name_
        for arc in root.iter(_VARIABLE_ARC)
        if (target := arc.get(f"{_XLINK}to")) and (name_ := arc.get("name"))
    }
    closed: set[str] = set()
    by_variable: dict[str, set[str]] = {}
    filter_arcs: dict[str, list[ET.Element]] = {}
    for arc in root.iter(_VARIABLE_FILTER_ARC):
        filter_arcs.setdefault(arc.get(f"{_XLINK}from", ""), []).append(arc)
    for arc in root.iter():
        if arc.tag not in (_SET_FILTER_ARC, _VARIABLE_FILTER_ARC):
            continue
        dimension = _closed_dimension(
            resources.get(arc.get(f"{_XLINK}to", "")), complement=arc.get("complement") == "true"
        )
        if dimension is None:
            continue
        if arc.tag == _SET_FILTER_ARC:
            closed.add(dimension)
        # A filter nested inside a boolean filter hangs off that filter, not
        # off a variable: it is one alternative, and closes nothing by itself.
        elif (variable := variables.get(arc.get(f"{_XLINK}from", ""))) is not None:
            by_variable.setdefault(variable, set()).add(dimension)
    closed_by_variable = {
        variable: frozenset(dimensions - closed)
        for variable, dimensions in sorted(by_variable.items())
        if dimensions - closed
    }
    spans: dict[str, frozenset[str]] = {}
    for element in root.iter(_FACT_VARIABLE):
        label = element.get(f"{_XLINK}label", "")
        name_ = variables.get(label)
        if name_ is None or element.get("bindAsSequence") != "true":
            continue
        covered = _covered(label, filter_arcs, resources)
        spans[name_] = frozenset(covered - closed_by_variable.get(name_, frozenset()))
    return RuleReach(
        closed=frozenset(closed),
        closed_by_variable=closed_by_variable,
        spans_by_variable=dict(sorted(spans.items())),
    )


def _covered(
    source: str,
    filter_arcs: Mapping[str, list[ET.Element]],
    resources: Mapping[str, ET.Element],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    """The dimensions the filters hung off ``source`` with ``cover="true"`` cover.

    ``source`` is a fact variable or a boolean filter: a boolean filter covers
    what its own covering sub-filters cover. Complemented or not, a dimension
    filter covers its dimension. ``seen`` stops a malformed, cyclic filter graph.
    """
    dimensions: set[str] = set()
    for arc in filter_arcs.get(source, ()):
        target = arc.get(f"{_XLINK}to", "")
        resource = resources.get(target)
        if arc.get("cover") != "true" or resource is None or target in seen:
            continue
        if resource.tag in (_EXPLICIT, _TYPED):
            qname = resource.find(f"{_DIMENSION_FILTER}dimension/{_DIMENSION_FILTER}qname")
            if qname is not None and qname.text:
                dimensions.add(qname.text.strip())
        elif resource.tag in _BOOLEAN_FILTERS:
            dimensions |= _covered(target, filter_arcs, resources, seen | {source})
    return dimensions


def _closed_dimension(resource: ET.Element | None, *, complement: bool) -> str | None:
    """The dimension a filter closes, or ``None`` when it closes none.

    Closed means no fact carrying the dimension can pass: an explicit filter
    naming only the default member, or the complement of a bare "has this
    dimension" filter, explicit or typed.
    """
    if resource is None or resource.tag not in (_EXPLICIT, _TYPED):
        return None
    qname = resource.find(f"{_DIMENSION_FILTER}dimension/{_DIMENSION_FILTER}qname")
    if qname is None or not qname.text:
        return None
    dimension = qname.text.strip()
    members = [
        (member.text or "").strip()
        for member in resource.findall(f"{_DIMENSION_FILTER}member/{_DIMENSION_FILTER}qname")
    ]
    if complement:
        # "Not (has the dimension)". With a member list or a test it is a
        # narrower exclusion, which closes nothing.
        bare = not members and resource.get("test") is None
        return dimension if bare else None
    if resource.tag == _EXPLICIT and len(members) == 1:
        return dimension if members[0].rpartition(":")[2] == DEFAULT_MEMBER else None
    return None
