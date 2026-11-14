"""
Referee plan — which assertions an instance can fire, split so each worker fits in memory.

Pipeline position:
    <name>.xbrl            -> read_instance_header -> (schemaRef, filed templates)
    taxonomy package (zip) -> TaxonomyModule.read  -> select -> chunk -> write_overlay
        -> runner.run_referee (one Arelle worker per overlay)

Key responsibilities:
- Read one entry point of a taxonomy package: its assertion linkbases, the size
  of each, and the filing indicators each one's precondition names.
- Select the assertions whose precondition can hold for an instance. A rule
  about a template the instance does not file is never evaluated by an XBRL
  processor, so loading it buys nothing.
- Split the selected assertions into chunks of bounded XML size, first-fit
  decreasing, deterministically.
- Write, per chunk, an OVERLAY taxonomy package: a catalog that remaps two URLs
  — the entry point and its filing-indicator preconditions — to trimmed copies
  naming only that chunk's assertions and only the filed templates' tables.

Why trim at all
    The PRA001 entry point pulls in 105 MB of table XML and 628 MB of assertion
    XML (1,441 assertions, the largest single file 40 MB); Arelle needs roughly
    12-13 GB just to load it. Measured on instances of up to a few thousand
    facts, resident memory is about 1.5 GB plus 14-18.5 MB per MB of assertion
    XML, so a 120 MB chunk stays under 4 GB.
    Partitioning does not change a verdict: every assertion is evaluated on its
    own, and identical counts were measured across different chunk sizes.

What the overlay does and does not touch
    The instance is never modified and every assertion linkbase still comes
    from the official package. A processor resolves a URL through the longest
    matching catalog prefix, so the overlay's two exact-URL rewrites win over
    the official package's host-level one (Arelle notes the overlap as
    ``tpe:packageRewriteOverlap``, which is expected).

Drop only what is understood
    Trimming removes a reference only when this module has positively
    identified it as droppable; anything else is left exactly as published.
    - A precondition that is not a plain ``$find:tA [and $find:tB ...]``
      conjunction keeps its assertion in the run.
    - An assertion linkbase the entry point references with NO filing-indicator
      precondition stays in every trimmed entry point.
    - A table whose filing-indicator code cannot be read stays imported.
    - A precondition arc that cannot be resolved to one assertion file and a
      test is refused (``RefereePlanError``): re-emitting the preconditions
      without it would let a rule run that the taxonomy says must not.

    On the Banking Taxonomy v4.1.1 none of those cases occurs: in all 24 entry
    points every referenced assertion has exactly one precondition, every
    precondition is a conjunction of one to three filing indicators, and every
    imported table has a filing-indicator code.

Pure standard library: nothing here imports Arelle, Polars or the rest of rwa-filer.

References:
- XBRL Taxonomy Packages 1.0 — the catalog's ``rewriteURI`` remapping
- XBRL Variables 1.0 — a variable set is evaluated only if all of its
  preconditions hold
- Eurofiling filing indicators — ``find:filingIndicator`` and ``find:filed``
- Bank of England Banking Taxonomy v4.1.1 — the shape measured above
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from collections.abc import Set as AbstractSet
    from pathlib import Path

# =============================================================================
# Constants
# =============================================================================

# XBRL names its namespaces, roles and arcroles as http:// strings. They are
# identifiers, compared as strings and never fetched: https:// would be another
# name. Hence the line-end marker for python:S5332, held to that by
# test_identifier_literals.py.
NS_FIND: Final = "http://www.eurofiling.info/xbrl/ext/filing-indicators"  # NOSONAR
NS_LINK: Final = "http://www.xbrl.org/2003/linkbase"  # NOSONAR
NS_XLINK: Final = "http://www.w3.org/1999/xlink"
NS_GEN: Final = "http://xbrl.org/2008/generic"  # NOSONAR
NS_VARIABLE: Final = "http://xbrl.org/2008/variable"  # NOSONAR

#: The arc that ties a precondition to the assertion it guards.
ARCROLE_PRECONDITION: Final = "http://xbrl.org/arcrole/2008/variable-set-precondition"  # NOSONAR

#: The label role that carries a table's filing-indicator code.
ROLE_FILING_INDICATOR_CODE: Final = (
    "http://www.eurofiling.info/xbrl/role/filing-indicator-code"  # NOSONAR
)

#: ``write_overlay(tables=...)``: import only the filed templates' tables, or all.
TABLES_INDICATED: Final = "indicated"
TABLES_ALL: Final = "all"

#: The publisher prefix an assertion id carries in front of the rule id.
_OWNER_PREFIX: Final = re.compile(r"^(boe|eba)_")

#: The one precondition shape that is understood well enough to drop a rule on.
_CONJUNCTION: Final = re.compile(r"\(?\s*\$find:t[\w.]+(\s+and\s+\$find:t[\w.]+)*\s*\)?")
_INDICATOR_VARIABLE: Final = re.compile(r"\$find:t([A-Za-z0-9._]+)")

_VAL_LOCATOR: Final = re.compile(r"\.\./val/(?P<file>[^/#]+)#(?P<id>.+)")
# A reference and its import are matched as whole elements, with the indentation
# of their line when they start one, and their attribute read from the match:
# one quantifier per element, so the scan is linear in the schema's length.
_LINKBASE_REF: Final = re.compile(r"(?:^[ \t]+)?<link:linkbaseRef\b[^>]*/>\r?\n?", re.M)
_HREF: Final = re.compile(r'\bxlink:href="([^"]+)"')
_ASSERTION_REF: Final = re.compile(r"\.\./val/(vr-.+?)(-err-en|-lab-en)?\.xml")
_TABLE_IMPORT: Final = re.compile(r"(?:^[ \t]+)?<xsd:import\b[^>]*/>\r?\n?", re.M)
_TABLE_LOCATION: Final = re.compile(r'schemaLocation="\.\./tab/([^/"]+)/')

_XLINK_HREF: Final = f"{{{NS_XLINK}}}href"
_XLINK_LABEL: Final = f"{{{NS_XLINK}}}label"
_XLINK_ROLE: Final = f"{{{NS_XLINK}}}role"
_XLINK_ARCROLE: Final = f"{{{NS_XLINK}}}arcrole"
_XLINK_FROM: Final = f"{{{NS_XLINK}}}from"
_XLINK_TO: Final = f"{{{NS_XLINK}}}to"

_SCHEMA_REF: Final = f"{{{NS_LINK}}}schemaRef"
_FILING_INDICATOR: Final = f"{{{NS_FIND}}}filingIndicator"
_FILED: Final = f"{{{NS_FIND}}}filed"
#: Elements of the XBRL 2.1 namespaces are kept while streaming; facts are not.
_XBRL_2003: Final = "{http://www.xbrl.org/2003/"

_BYTES_PER_MB: Final = 1e6


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class TaxonomyModule:
    """One entry point (``mod/<name>.xsd``) inside a taxonomy package zip.

    Build one with ``TaxonomyModule.read``; everything is read up front, so the
    package is not opened again.

    Attributes:
        package: The taxonomy package the entry point was read from.
        url: The entry point's URL — the ``schemaRef`` of its instances.
        member: The entry point's path inside the zip.
        xsd: The entry point schema's text.
        xml_bytes: Uncompressed bytes of everything under the entry point's
            framework folder; what decides whether trimming is needed.
        assertions: Every assertion that has a filing-indicator precondition,
            by file name.
        table_codes: Table folder -> filing-indicator code, for each imported
            table whose code could be read.
    """

    package: Path
    url: str
    member: str
    xsd: str
    xml_bytes: int
    assertions: Mapping[str, Assertion]
    table_codes: Mapping[str, str]

    @classmethod
    def read(cls, package: Path, schema_ref: str) -> TaxonomyModule:
        """Read the entry point ``schema_ref`` names out of ``package``.

        Raises:
            RefereePlanError: ``schema_ref`` is not an entry point of the
                package, or its preconditions cannot be resolved.
        """
        tail = schema_ref.partition("://")[2]
        with zipfile.ZipFile(package) as archive:
            sizes = {info.filename: info.file_size for info in archive.infolist()}
            member = next((name for name in sizes if tail and name.endswith("/" + tail)), None)
            if member is None:
                raise RefereePlanError(
                    f"schemaRef {schema_ref} is not an entry point of the taxonomy package "
                    f"{package.name}"
                )
            mod_dir, _, file_name = member.rpartition("/")
            framework = mod_dir.rpartition("/")[0]
            xsd = archive.read(member).decode("utf-8-sig")
            preconditions = f"{mod_dir}/{file_name.removesuffix('.xsd')}-find-prec.xml"
            located = (
                _read_preconditions(archive.read(preconditions), preconditions)
                if preconditions in sizes
                else {}
            )
            table_codes: dict[str, str] = {}
            for table in dict.fromkeys(_TABLE_LOCATION.findall(xsd)):
                labels = f"{framework}/tab/{table}/{table}-lab-codes.xml"
                code = _filing_indicator_code(archive.read(labels)) if labels in sizes else None
                if code:
                    table_codes[table] = code
        assertions = {
            file: Assertion(
                file=file,
                assertion_id=assertion_id,
                size=sizes.get(f"{framework}/val/{file}", 0),
                tests=tests,
                needs=frozenset(code for test in tests for code in _indicator_codes(test)),
            )
            for file, (assertion_id, tests) in located.items()
        }
        return cls(
            package=package,
            url=schema_ref,
            member=member,
            xsd=xsd,
            xml_bytes=sum(size for name, size in sizes.items() if name.startswith(framework + "/")),
            assertions=assertions,
            table_codes=table_codes,
        )

    @property
    def name(self) -> str:
        """The entry point's file name without ``.xsd``, e.g. ``pra001``."""
        return self.member.rpartition("/")[2].removesuffix(".xsd")

    @property
    def xml_mb(self) -> float:
        """``xml_bytes`` in megabytes."""
        return self.xml_bytes / _BYTES_PER_MB

    def select(self, indicators: AbstractSet[str]) -> tuple[list[str], list[str]]:
        """Split the assertion files into (precondition can hold, precondition is false).

        Both lists are sorted. See ``Assertion.can_fire`` for what "false" means.
        """
        kept: list[str] = []
        dropped: list[str] = []
        for file, assertion in self.assertions.items():
            (kept if assertion.can_fire(indicators) else dropped).append(file)
        return sorted(kept), sorted(dropped)

    def chunk(self, files: Iterable[str], chunk_mb: float) -> list[list[str]]:
        """First-fit-decreasing bins of at most ``chunk_mb`` MB of assertion XML.

        Deterministic whatever order ``files`` arrive in: the largest file is
        placed first, ties broken by name, and every bin is returned sorted. A
        file larger than the limit gets a bin to itself.
        """
        limit = chunk_mb * _BYTES_PER_MB
        bins: list[list[str]] = []
        used: list[int] = []
        for file in sorted(files, key=lambda name: (-self.assertions[name].size, name)):
            size = self.assertions[file].size
            fits = next((n for n, taken in enumerate(used) if taken + size <= limit), None)
            if fits is None:
                bins.append([file])
                used.append(size)
            else:
                bins[fits].append(file)
                used[fits] += size
        return [sorted(members) for members in bins]

    def write_overlay(
        self,
        path: Path,
        files: Sequence[str],
        indicators: AbstractSet[str],
        *,
        tables: str,
    ) -> Path:
        """Write the taxonomy package that remaps the entry point to a trimmed copy.

        Args:
            path: The overlay zip to write.
            files: The assertion files this overlay keeps (one chunk).
            indicators: The filing-indicator codes the instance files.
            tables: ``TABLES_INDICATED`` to import only the filed templates'
                tables, ``TABLES_ALL`` to leave the imports as published.

        Returns:
            ``path``.
        """
        if tables not in (TABLES_INDICATED, TABLES_ALL):
            raise ValueError(f"tables must be {TABLES_INDICATED!r} or {TABLES_ALL!r}")
        base = self.url.rpartition("/")[0]
        prefix = f"../files/{self.name}"
        catalog = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            f"  <rewriteURI uriStartString={quoteattr(self.url)}"
            f" rewritePrefix={quoteattr(prefix + '.xsd')}/>\n"
            f"  <rewriteURI uriStartString={quoteattr(f'{base}/{self.name}-find-prec.xml')}"
            f" rewritePrefix={quoteattr(prefix + '-find-prec.xml')}/>\n"
            "</catalog>\n"
        )
        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<tp:taxonomyPackage xmlns:tp="http://xbrl.org/2016/taxonomy-package"'
            ' xml:lang="en">\n'
            f"  <tp:identifier>urn:rwa-filer:referee-overlay:{self.name}:{path.stem}"
            "</tp:identifier>\n"
            f"  <tp:name>referee overlay {self.name} {path.stem}</tp:name>\n"
            "  <tp:version>0</tp:version>\n"
            "</tp:taxonomyPackage>\n"
        )
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("overlay/META-INF/taxonomyPackage.xml", manifest)
            archive.writestr("overlay/META-INF/catalog.xml", catalog)
            archive.writestr(
                f"overlay/files/{self.name}.xsd",
                self._trimmed_entry_point(frozenset(files), indicators, tables),
            )
            archive.writestr(
                f"overlay/files/{self.name}-find-prec.xml", self._trimmed_preconditions(files)
            )
        return path

    def _trimmed_entry_point(
        self, keep: AbstractSet[str], indicators: AbstractSet[str], tables: str
    ) -> str:
        """The entry point schema, referencing only ``keep`` and the filed tables."""

        def keep_ref(match: re.Match[str]) -> str:
            attribute = _HREF.search(match.group(0))
            if attribute is None:
                return match.group(0)
            href = attribute.group(1)
            if href.startswith("../val/aset-") or href.endswith("-pre.xml"):
                # Assertion sets and the module presentation only pull every
                # assertion and table back in; evaluation needs neither.
                return ""
            reference = _ASSERTION_REF.fullmatch(href)
            if reference is None:
                return match.group(0)
            file = reference.group(1) + ".xml"
            if file not in self.assertions:
                return match.group(0)  # no precondition known: always evaluated
            # A kept assertion's message linkbase locates the assertion itself,
            # and so do the trimmed preconditions; its labels are for display.
            return match.group(0) if file in keep and reference.group(2) != "-lab-en" else ""

        def keep_import(match: re.Match[str]) -> str:
            location = _TABLE_LOCATION.search(match.group(0))
            if location is None:
                return match.group(0)
            code = self.table_codes.get(location.group(1))
            return match.group(0) if code is None or code in indicators else ""

        xsd = _LINKBASE_REF.sub(keep_ref, self.xsd)
        return _TABLE_IMPORT.sub(keep_import, xsd) if tables == TABLES_INDICATED else xsd

    def _trimmed_preconditions(self, files: Sequence[str]) -> str:
        """The filing-indicator preconditions, re-emitted for ``files`` only.

        The published linkbase locates every assertion of the module, and a
        locator is enough to pull an assertion's file into the run.
        """
        members = [self.assertions[file] for file in files]
        labels = {
            test: f"findPrec{number}"
            for number, test in enumerate(
                sorted({test for member in members for test in member.tests}), 1
            )
        }
        parts = [
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<link:linkbase xmlns:xlink="{NS_XLINK}" xmlns:link="{NS_LINK}"'
            f' xmlns:gen="{NS_GEN}" xmlns:find="{NS_FIND}" xmlns:variable="{NS_VARIABLE}">\n'
            f'  <link:arcroleRef arcroleURI="{ARCROLE_PRECONDITION}" xlink:type="simple"'
            ' xlink:href="http://www.xbrl.org/2008/variable.xsd#variable-set-precondition" />\n'
            '  <gen:link xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">\n'
        ]
        parts += [
            f'    <variable:precondition xlink:type="resource" xlink:label="{label}"'
            f" test={quoteattr(test)} />\n"
            for test, label in labels.items()
        ]
        for member in members:
            locator = f"loc_{member.assertion_id}"
            href = f"../val/{member.file}#{member.assertion_id}"
            parts.append(
                f'    <link:loc xlink:type="locator" xlink:href={quoteattr(href)}'
                f" xlink:label={quoteattr(locator)} />\n"
            )
            parts += [
                f'    <gen:arc xlink:type="arc" xlink:arcrole="{ARCROLE_PRECONDITION}"'
                f' xlink:from={quoteattr(locator)} xlink:to="{labels[test]}" />\n'
                for test in member.tests
            ]
        parts.append("  </gen:link>\n</link:linkbase>\n")
        return "".join(parts)


# =============================================================================
# Supporting public classes and functions
# =============================================================================


@dataclass(frozen=True)
class Assertion:
    """One assertion linkbase of an entry point, as its preconditions describe it.

    Attributes:
        file: The linkbase's file name inside the framework's ``val`` folder,
            e.g. ``vr-boe_b0021.xml``.
        assertion_id: The assertion's id, e.g. ``boe_boe_b0021``.
        size: Uncompressed bytes of ``file`` — what the chunking weighs.
        tests: The XPath test of each of its filing-indicator preconditions.
            A processor evaluates the assertion only if ALL of them hold.
        needs: The filing-indicator codes those tests name.
    """

    file: str
    assertion_id: str
    size: int
    tests: tuple[str, ...]
    needs: frozenset[str]

    @property
    def rule_id(self) -> str:
        """The published rule id (the assertion id without its owner prefix)."""
        return rule_id(self.assertion_id)

    def can_fire(self, indicators: AbstractSet[str]) -> bool:
        """Whether the preconditions can hold for an instance filing ``indicators``.

        False only when a precondition is a plain conjunction naming a template
        that is not filed. Any other test shape answers True: a shape this
        module does not understand must never hide a rule.
        """
        return not any(
            _CONJUNCTION.fullmatch(test) and not _indicator_codes(test) <= indicators
            for test in self.tests
        )


class RefereePlanError(ValueError):
    """The instance or the taxonomy package cannot be planned against."""


def rule_id(assertion_id: str) -> str:
    """The published rule id of an assertion: its id with the owner prefix removed once.

    ``boe_boe_b0021`` is rule ``boe_b0021``; ``boe_v0718_m`` is rule ``v0718_m``.
    An id with no owner prefix is returned unchanged.
    """
    return _OWNER_PREFIX.sub("", assertion_id, count=1)


def read_instance_header(path: Path) -> tuple[str, frozenset[str]]:
    """Stream an instance once for its ``schemaRef`` and the templates it files.

    Returns:
        The ``schemaRef`` href and the POSITIVE filing-indicator codes — an
        indicator written with ``find:filed="false"`` declares a template as
        not reported and is left out.

    Raises:
        RefereePlanError: the instance has no ``link:schemaRef``.
    """
    schema_ref = ""
    indicators: set[str] = set()
    for _event, element in ElementTree.iterparse(path, events=("end",)):
        if element.tag == _SCHEMA_REF:
            schema_ref = element.get(_XLINK_HREF, "")
        elif element.tag == _FILING_INDICATOR:
            if element.get(_FILED, "true") in ("true", "1") and element.text:
                indicators.add(element.text.strip())
        elif element.tag.endswith("}context") or not element.tag.startswith(_XBRL_2003):
            element.clear()  # a context or a fact: nothing here reads it
    if not schema_ref:
        raise RefereePlanError(f"{path}: the instance has no link:schemaRef")
    return schema_ref, frozenset(indicators)


# =============================================================================
# Private helpers
# =============================================================================


def _indicator_codes(test: str) -> frozenset[str]:
    """The filing-indicator codes a precondition's test names."""
    return frozenset(_INDICATOR_VARIABLE.findall(test))


def _read_preconditions(content: bytes, member: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Assertion file -> (assertion id, precondition tests), from a ``-find-prec`` linkbase.

    Strict on purpose: every precondition arc must run from a locator of one
    assertion in the ``val`` folder to a precondition resource. An arc that
    does not is refused rather than skipped, because the trimmed copy is
    re-emitted from what is read here and a skipped arc would be a lost guard.
    """
    found: dict[str, tuple[str, list[str]]] = {}
    for link in ElementTree.fromstring(content).iter(f"{{{NS_GEN}}}link"):
        tests = _by_label(link, f"{{{NS_VARIABLE}}}precondition", "test")
        hrefs = _by_label(link, f"{{{NS_LINK}}}loc", _XLINK_HREF)
        for arc in link.iter(f"{{{NS_GEN}}}arc"):
            if arc.get(_XLINK_ARCROLE) != ARCROLE_PRECONDITION:
                continue
            source, target = arc.get(_XLINK_FROM, ""), arc.get(_XLINK_TO, "")
            sources = hrefs.get(source, [])
            located = [match for href in sources if (match := _VAL_LOCATOR.fullmatch(href))]
            if not sources or len(located) != len(sources) or target not in tests:
                raise RefereePlanError(
                    f"{member}: the precondition arc from {source!r} to {target!r} does not "
                    "join an assertion in ../val/ to a precondition"
                )
            for match in located:
                assertion_id, held = found.setdefault(match["file"], (match["id"], []))
                if assertion_id != match["id"]:
                    raise RefereePlanError(
                        f"{member}: {match['file']} is located as both {assertion_id!r} and "
                        f"{match['id']!r}; one assertion per file is assumed"
                    )
                held.extend(tests[target])
    return {
        file: (assertion_id, tuple(dict.fromkeys(held)))
        for file, (assertion_id, held) in found.items()
    }


def _by_label(link: ElementTree.Element, tag: str, attribute: str) -> dict[str, list[str]]:
    """``xlink:label`` -> the ``attribute`` of every ``tag`` child carrying that label."""
    values: dict[str, list[str]] = {}
    for element in link.iter(tag):
        values.setdefault(element.get(_XLINK_LABEL, ""), []).append(element.get(attribute, ""))
    return values


def _filing_indicator_code(content: bytes) -> str | None:
    """The filing-indicator code a table's ``-lab-codes`` linkbase gives it, if any."""
    for element in ElementTree.fromstring(content).iter():
        if element.get(_XLINK_ROLE) == ROLE_FILING_INDICATOR_CODE and element.text:
            return element.text.strip()
    return None
