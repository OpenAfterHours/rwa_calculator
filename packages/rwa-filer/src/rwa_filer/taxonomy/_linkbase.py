"""
Taxonomy package reader — what only the XBRL taxonomy itself can say.

Pipeline position:
    taxonomy package (.zip or extracted tree)  ->  TaxonomyPackage.open
        ->  read_module / read_default_sheets / read_hypercubes + accepts
        ->  compiler.compile_pack

Key responsibilities:
- List an entry point's tables from its ``mod/<module>-pre.xml`` (group-table
  arcs), with each table's rc-code and FILING INDICATOR from the table's
  ``-lab-codes.xml``. The indicator is not derivable from the workbooks: most are
  the 3-part group code, but some groups carry one indicator per table.
- Give the entry point's schemaRef URL exactly as an instance must write it.
- Name the "total" sheet of a fixed z-axis — the rule node that constrains no
  aspect. The annotated workbook publishes that sheet as an empty list entry,
  with no code and no label.
- Decide REPORTABILITY. A table's ``-def.xml`` holds the closed hypercubes that
  say which (metric, dimension members) combinations the regulator's system
  accepts; ``accepts`` is the XBRL Dimensions validity test against them.

The definition linkbases are large (25 MB for one table, 87 MB for the Banking
Reporting module), so ``read_hypercubes`` stream-parses one definitionLink at a
time and keeps only a compact arc table.

References:
- XBRL Dimensions 1.0, section 3.1 (dimensional validity; ``xbrldt:targetRole``)
- XBRL Table Linkbase 1.0 (rule nodes, breakdowns)
- Eurofiling / EBA architecture: ``rc-code`` and ``filing-indicator-code`` label
  roles, ``group-table`` arcs
- XBRL Taxonomy Packages 1.0 (``META-INF/taxonomyPackage.xml`` entry points)
"""

from __future__ import annotations

import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING

from rwa_filer.inputs import open_zip

if TYPE_CHECKING:
    import zipfile
    from collections.abc import Collection, Iterator, Mapping
    from pathlib import Path

#: One closed hypercube: dimension -> allowed members, or ``None`` for a typed dimension.
type Hypercube = Mapping[str, frozenset[str] | None]
#: metric QName -> the hypercubes that metric is a primary item of.
type Hypercubes = Mapping[str, tuple[Hypercube, ...]]

_XLINK = "{http://www.w3.org/1999/xlink}"
_LINK = "{http://www.xbrl.org/2003/linkbase}"
_GEN = "{http://xbrl.org/2008/generic}"
_LABEL = "{http://xbrl.org/2008/label}"
_TABLE = "{http://xbrl.org/2014/table}"
_XBRLDT = "{http://xbrl.org/2005/xbrldt}"
_PACKAGE = "{http://xbrl.org/2016/taxonomy-package}"
# XBRL names its namespaces, roles and arcroles as http:// strings. They are
# identifiers, compared as strings and never fetched: https:// would be another
# name. Hence the line-end marker for python:S5332, held to that by
# test_identifier_literals.py.
_ARC_ALL = "http://xbrl.org/int/dim/arcrole/all"  # NOSONAR
_ARC_HYPERCUBE_DIMENSION = "http://xbrl.org/int/dim/arcrole/hypercube-dimension"  # NOSONAR
_ARC_DIMENSION_DOMAIN = "http://xbrl.org/int/dim/arcrole/dimension-domain"  # NOSONAR
_ARC_DOMAIN_MEMBER = "http://xbrl.org/int/dim/arcrole/domain-member"  # NOSONAR
#: The scheme of a taxonomy's published URLs, which a schemaRef must repeat.
_ENTRY_POINT_SCHEME = "http://"  # NOSONAR
_RENDERING_SUFFIX = "-rend.xml"

_DICT_ITEM = re.compile(r"/dict/(dim|met)/\w+\.xsd$")
_DICT_MEMBER = re.compile(r"/dict/dom/(\w+)/mem\.xsd$")
_DICT_DOMAIN = re.compile(r"/dict/dom/(exp|typ)\.xsd$")
_TABLE_LOCATOR = re.compile(r"#\w+?_t[^g]")

#: role -> source QName -> ``(target QName, arcrole, usable, targetRole)`` arcs.
type _Arcs = dict[str, dict[str, list[tuple[str, str, bool, str | None]]]]


# ── Records ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaxonomyPackage:
    """Read-only view of a taxonomy package: an extracted tree or a ``.zip``."""

    path: Path
    names: tuple[str, ...]
    members: frozenset[str]
    archive: zipfile.ZipFile | None

    @classmethod
    def open(cls, path: Path) -> TaxonomyPackage:
        """Index the package's ``.xml`` / ``.xsd`` members by their path inside it.

        Raises:
            ValueError: ``path`` is a file that is not a zip archive.
        """
        if path.is_dir():
            names = sorted(
                p.relative_to(path).as_posix()
                for p in path.rglob("*")
                if p.suffix in {".xml", ".xsd"} and p.is_file()
            )
            return cls(path, tuple(names), frozenset(names), None)
        archive = open_zip(path)
        names = sorted(archive.namelist())
        return cls(path, tuple(names), frozenset(names), archive)

    def close(self) -> None:
        """Release the archive handle (a no-op for an extracted tree)."""
        if self.archive is not None:
            self.archive.close()

    def has(self, name: str) -> bool:
        """Whether the package holds a member of exactly this path."""
        return name in self.members

    def read(self, name: str) -> bytes:
        """The whole of one member — for the small linkbases."""
        if self.archive is not None:
            return self.archive.read(name)
        return (self.path / name).read_bytes()

    def parse(self, name: str) -> ET.Element:
        """One member parsed as XML.

        Raises:
            ValueError: the member is not well-formed XML.
        """
        with self.well_formed(name):
            return ET.fromstring(self.read(name))

    @contextmanager
    def well_formed(self, name: str) -> Iterator[None]:
        """Report XML that ``name`` fails to parse as a ``ValueError`` naming the member.

        For a member read as a stream (``stream``), where ``parse`` cannot be used.
        """
        try:
            yield
        except ET.ParseError as exc:
            raise ValueError(f"{self.path}: {name} is not well-formed XML ({exc})") from exc

    def stream(self, name: str) -> IO[bytes]:
        """An open binary stream on one member — for the large definition linkbases."""
        if self.archive is not None:
            return self.archive.open(name)
        return (self.path / name).open("rb")

    def ending_with(self, suffix: str) -> list[str]:
        """Member paths that end with ``suffix``, compared case-insensitively."""
        wanted = suffix.lower()
        return [name for name in self.names if name.lower().endswith(wanted)]


@dataclass(frozen=True)
class ModuleTable:
    """One table of an entry point, as the taxonomy identifies it."""

    code: str
    table_id: str
    group_id: str
    rendering: str
    filing_indicator: str | None

    @property
    def definition(self) -> str:
        """Package path of the table's definition linkbase (its hypercubes)."""
        return self.rendering[: -len(_RENDERING_SUFFIX)] + "-def.xml"


@dataclass(frozen=True)
class ModuleListing:
    """An entry point: its schemaRef URL and its tables keyed by rc-code."""

    entry_point: str
    tables: Mapping[str, ModuleTable]


# ── Public entry points ───────────────────────────────────────────────────────


def read_module(package: TaxonomyPackage, module: str) -> ModuleListing:
    """List the tables of one entry point, with rc-codes and filing indicators.

    Raises ``ValueError`` when the package has no such entry point — a usage
    error, not a data condition.
    """
    entry_point, schema = _locate_entry_point(package, module)
    presentation = schema[: -len(".xsd")] + "-pre.xml"
    if not package.has(presentation):
        raise ValueError(f"taxonomy package {package.path.name} has no {presentation}")
    root = package.parse(presentation)
    locators = {
        e.get(f"{_XLINK}label"): e.get(f"{_XLINK}href", "") for e in root.iter(f"{_LINK}loc")
    }
    tables: dict[str, ModuleTable] = {}
    for arc in root.iter(f"{_GEN}arc"):
        source = locators.get(arc.get(f"{_XLINK}from"), "")
        target = locators.get(arc.get(f"{_XLINK}to"), "")
        target_file, _, table_id = target.partition("#")
        if not target_file.endswith(_RENDERING_SUFFIX):
            continue
        rendering = posixpath.normpath(posixpath.join(posixpath.dirname(presentation), target_file))
        codes_part = rendering[: -len(_RENDERING_SUFFIX)] + "-lab-codes.xml"
        if not package.has(codes_part):
            continue
        code, indicator = _read_table_codes(package.parse(codes_part), table_id)
        if code is not None:
            tables[code] = ModuleTable(
                code, table_id, source.partition("#")[2], rendering, indicator
            )
    return ModuleListing(entry_point, dict(sorted(tables.items())))


def read_default_sheets(
    package: TaxonomyPackage, rendering: str
) -> list[tuple[str | None, str | None]]:
    """``(rc-code, label)`` of every z-axis rule node that constrains no aspect.

    That node is the sheet whose members are all dimension defaults — the
    "Total" sheet the annotated workbook leaves as an empty list entry.
    """
    root = package.parse(rendering)
    z_breakdowns = [
        arc.get(f"{_XLINK}to")
        for arc in root.iter(f"{_TABLE}tableBreakdownArc")
        if arc.get("axis") == "z"
    ]
    children: dict[str | None, list[str | None]] = {}
    for tag in ("breakdownTreeArc", "definitionNodeSubtreeArc"):
        for arc in root.iter(f"{_TABLE}{tag}"):
            children.setdefault(arc.get(f"{_XLINK}from"), []).append(arc.get(f"{_XLINK}to"))
    nodes = {node.get(f"{_XLINK}label"): node for node in root.iter(f"{_TABLE}ruleNode")}
    found: list[str] = []
    pending = list(z_breakdowns)
    while pending:
        label = pending.pop()
        node = nodes.get(label)
        if node is not None and node.get("abstract") != "true" and len(node) == 0:
            found.append(node.get("id", ""))
        pending.extend(children.get(label, []))
    stem = rendering[: -len(_RENDERING_SUFFIX)]
    codes = _node_labels(package, stem + "-lab-codes.xml", "/rc-code")
    labels = _node_labels(package, stem + "-lab-en.xml", "/label")
    return [(codes.get(node_id), labels.get(node_id)) for node_id in sorted(found)]


def read_hypercubes(stream: IO[bytes]) -> Hypercubes:
    """Read a table's definition linkbase into per-metric closed hypercubes.

    Stream-parsed: each ``definitionLink`` is reduced to its arcs and discarded.
    ``xbrldt:targetRole`` is followed on every consecutive arc — the BoE
    linkbases park a dimension's member list in a separate link role whenever two
    dimensions of one hypercube share a domain (APR and MRW both use ``eba_AP``).
    """
    arcs: _Arcs = {}
    for _, link in ET.iterparse(stream, events=("end",)):
        if link.tag != f"{_LINK}definitionLink":
            continue
        locators = {
            e.get(f"{_XLINK}label"): sys.intern(href_to_qname(e.get(f"{_XLINK}href", "")))
            for e in link.iter(f"{_LINK}loc")
        }
        role_arcs = arcs.setdefault(link.get(f"{_XLINK}role", ""), {})
        for arc in link.iter(f"{_LINK}definitionArc"):
            source = locators.get(arc.get(f"{_XLINK}from"))
            target = locators.get(arc.get(f"{_XLINK}to"))
            if source is None or target is None:
                continue
            role_arcs.setdefault(source, []).append(
                (
                    target,
                    arc.get(f"{_XLINK}arcrole", ""),
                    arc.get(f"{_XBRLDT}usable") != "false",
                    arc.get(f"{_XBRLDT}targetRole"),
                )
            )
        link.clear()

    cubes: dict[str, list[Hypercube]] = {}
    for role, role_arcs in arcs.items():
        for source, targets in role_arcs.items():
            for hypercube, arcrole, _, all_target in targets:
                if arcrole != _ARC_ALL:
                    continue
                cube = _read_cube(arcs, all_target or role, hypercube)
                # the primary item, and any items that inherit its hypercube
                inherited, _ = _members(arcs, role, source, _ARC_DOMAIN_MEMBER, set())
                for metric in (source, *sorted(inherited)):
                    cubes.setdefault(metric, []).append(cube)
    return {metric: tuple(found) for metric, found in cubes.items()}


def accepts(
    cubes: Hypercubes,
    metric: str,
    fixed: Mapping[str, str],
    opened: Collection[str],
    defaults: Mapping[str, str | None],
) -> bool:
    """Whether a data point is dimensionally valid in at least one closed hypercube.

    ``fixed`` holds the explicit members; ``opened`` the dimensions whose value the
    filer chooses (typed, or explicit from an open axis) — present, but not
    checked against a member list here. A hypercube dimension the data point does
    not carry is valid only when that dimension's DEFAULT member is allowed,
    because an instance never reports a default explicitly.
    """
    for cube in cubes.get(metric, ()):
        if any(dimension not in cube for dimension in fixed) or any(d not in cube for d in opened):
            continue
        if all(
            _dimension_ok(dimension, allowed, fixed, opened, defaults)
            for dimension, allowed in cube.items()
        ):
            return True
    return False


# ── Supporting public functions ───────────────────────────────────────────────


def href_to_qname(href: str) -> str:
    """Map a dictionary locator href to the prefixed QName an instance uses.

    ``…/eba…/dict/dom/ap/mem.xsd#eba_x42`` -> ``eba_AP:x42``; a BoE member of an
    EBA domain (``dict/dom/eba_ap/mem.xsd#boe_x10050``) -> ``boe_eba_AP:x10050``;
    ``dict/met/met.xsd#boe_mi10047`` -> ``boe_met:mi10047``. Anything else (the
    shared ``hyp`` hypercube element) is returned unchanged.
    """
    path, _, fragment = href.partition("#")
    owner, _, local = fragment.partition("_")
    item = _DICT_ITEM.search(path)
    if item:
        return f"{owner}_{item.group(1)}:{local}"
    member = _DICT_MEMBER.search(path)
    if member:
        domain = member.group(1)
        if domain.startswith("eba_") and owner != "eba":
            return f"{owner}_eba_{domain[4:].upper()}:{local}"
        return f"{owner}_{domain.removeprefix('eba_').upper()}:{local}"
    domain_item = _DICT_DOMAIN.search(path)
    if domain_item:
        return f"{owner}_{domain_item.group(1)}:{local}"
    return href


# ── Private helpers ───────────────────────────────────────────────────────────


def _locate_entry_point(package: TaxonomyPackage, module: str) -> tuple[str, str]:
    """``(schemaRef URL, package path)`` of the module's entry-point schema.

    The URL is taken verbatim from ``META-INF/taxonomyPackage.xml`` when the
    package has one — that is the string an instance's schemaRef must carry.
    """
    wanted = f"/mod/{module.lower()}.xsd"
    for manifest in package.ending_with("META-INF/taxonomyPackage.xml"):
        for document in package.parse(manifest).iter(f"{_PACKAGE}entryPointDocument"):
            url = document.get("href", "")
            if url.lower().endswith(wanted):
                paths = package.ending_with(url.partition("://")[2])
                if paths:
                    return url, paths[0]
    paths = package.ending_with(wanted)
    if not paths:
        raise ValueError(
            f"taxonomy package {package.path.name} has no entry point for module {module!r}"
        )
    path = paths[-1]  # several dated folders: the lexically last is the latest
    host = path.find("www.")
    return _ENTRY_POINT_SCHEME + (path[host:] if host >= 0 else path), path


def _read_table_codes(root: ET.Element, table_id: str) -> tuple[str | None, str | None]:
    """A table's own ``(rc-code, filing-indicator-code)`` labels, from its ``-lab-codes.xml``."""
    labels = {e.get(f"{_XLINK}label"): e for e in root.iter(f"{_LABEL}label")}
    table_locators = {
        e.get(f"{_XLINK}label")
        for e in root.iter(f"{_LINK}loc")
        if e.get(f"{_XLINK}href", "").endswith("#" + table_id)
        or (not table_id and _TABLE_LOCATOR.search(e.get(f"{_XLINK}href", "")))
    }
    code = indicator = None
    for arc in root.iter(f"{_GEN}arc"):
        label = labels.get(arc.get(f"{_XLINK}to"))
        if arc.get(f"{_XLINK}from") not in table_locators or label is None:
            continue
        role = label.get(f"{_XLINK}role", "")
        if role.endswith("/rc-code"):
            code = label.text
        elif role.endswith("/filing-indicator-code"):
            indicator = label.text
    return code, indicator


def _node_labels(package: TaxonomyPackage, part: str, role_suffix: str) -> dict[str, str]:
    """node id -> text of its generic label whose role ends with ``role_suffix``."""
    if not package.has(part):
        return {}
    root = package.parse(part)
    locators = {
        e.get(f"{_XLINK}label"): e.get(f"{_XLINK}href", "").rpartition("#")[2]
        for e in root.iter(f"{_LINK}loc")
    }
    labels = {e.get(f"{_XLINK}label"): e for e in root.iter(f"{_LABEL}label")}
    found: dict[str, str] = {}
    for arc in root.iter(f"{_GEN}arc"):
        label = labels.get(arc.get(f"{_XLINK}to"))
        node_id = locators.get(arc.get(f"{_XLINK}from"))
        if label is not None and node_id and label.get(f"{_XLINK}role", "").endswith(role_suffix):
            found.setdefault(node_id, label.text or "")
    return found


def _read_cube(arcs: _Arcs, role: str, hypercube: str) -> Hypercube:
    """Dimensions of one hypercube with their usable members."""
    cube: dict[str, frozenset[str] | None] = {}
    for dimension, arcrole, _, target_role in arcs.get(role, {}).get(hypercube, ()):
        if arcrole != _ARC_HYPERCUBE_DIMENSION:
            continue
        members, has_domain = _members(
            arcs, target_role or role, dimension, _ARC_DIMENSION_DOMAIN, set()
        )
        cube[dimension] = frozenset(members) if has_domain else None
    return cube


def _members(
    arcs: _Arcs, role: str, source: str, arcrole: str, seen: set[tuple[str, str, str]]
) -> tuple[set[str], bool]:
    """Usable targets reachable from ``source`` by ``arcrole`` then domain-member arcs."""
    found: set[str] = set()
    any_arc = False
    for target, target_arcrole, usable, target_role in arcs.get(role, {}).get(source, ()):
        if target_arcrole != arcrole or (role, source, target) in seen:
            continue
        seen.add((role, source, target))
        any_arc = True
        if usable:
            found.add(target)
        found |= _members(arcs, target_role or role, target, _ARC_DOMAIN_MEMBER, seen)[0]
    return found, any_arc


def _dimension_ok(
    dimension: str,
    allowed: frozenset[str] | None,
    fixed: Mapping[str, str],
    opened: Collection[str],
    defaults: Mapping[str, str | None],
) -> bool:
    """One hypercube dimension against the data point (see ``accepts``)."""
    if dimension in opened:
        return True
    if allowed is None:
        return False  # a typed dimension must be reported, and only an open axis reports one
    if dimension in fixed:
        return fixed[dimension] in allowed
    return defaults.get(dimension) in allowed
