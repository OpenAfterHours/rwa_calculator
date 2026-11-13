"""
XBRL instance reader — a submission file, from any system, as a canonical return.

Pipeline position:
    <name>.xbrl | <name>.zip  ->  read_instance
        ->  InstanceReading(ret: CanonicalReturn, findings)
        ->  validate.returns.validate_return

Key responsibilities:
- Read an XBRL 2.1 instance written by this package or by anything else, and
  put every fact back in the cell — table, sheet, row, column — the taxonomy
  shows it in. The same structure checks and published rules then run on a
  file exactly as they run on a fact table.
- Choose the taxonomy pack from the file's own ``schemaRef``. The file says
  which module and taxonomy version it is filed against; nothing is guessed.
- Honour the file's filing indicators: a fact is placed only in templates the
  file declares as reported, and a template may be reported with no facts.
- Report what the file contains that the module does not accept — a fact that
  is no data point of the module, a fact no reported template shows, a breach
  of a Filing Manual rule the reader can see — as findings, never by dropping
  it in silence.

What the reader does NOT do: validate the file as XBRL. It does not load the
taxonomy's schemas or linkbases, so it cannot say that the file is valid
against them — that is what the Arelle referee is for.

Security: an instance is untrusted input. A document type declaration is
refused outright — a filing never has one, and it is the only way an XML file
can declare entities — and a zipped filing is read only if it holds exactly one
instance of a bounded size.

References:
- BoE XBRL Filing Manual v1.0.1: 1.1 (.xbrl, .zip), 1.6 (filing indicators),
  2.9-2.10 (one entity, one date), 2.14 (no segment), 2.16 (duplicates),
  2.17-2.19 (decimals, no precision, no nil)
- XBRL 2.1; XBRL Dimensions 1.0
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree

import polars as pl

from rwa_filer.model import DECIMALS_EXACT, FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.rules.catalogue import SEVERITY_ERROR
from rwa_filer.taxonomy.pack import (
    MEMBER_OPEN_OPTIONAL,
    MEMBER_TYPED_PREFIX,
    available_packs,
    load_packaged,
)
from rwa_filer.validate.checker import Finding
from rwa_filer.validate.structure import local_name
from rwa_filer.xbrl.writer import NS_FIND, NS_ISO4217, NS_LINK, NS_XBRLDI, NS_XBRLI, NS_XLINK

if TYPE_CHECKING:
    from collections.abc import Iterator

    from rwa_filer.taxonomy.pack import Table, TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: A fact that is not a data point of the module: its metric and dimension
#: members, taken together, are in no reportable cell.
FINDING_UNKNOWN_DATAPOINT: Final = "XBR001"
#: A fact that only templates the file does not declare as reported would show.
FINDING_FACT_NOT_INDICATED: Final = "XBR002"
#: The file breaks a Filing Manual rule the reader can see.
FINDING_FILING_RULE: Final = "XBR003"

READER_REFERENCE: Final = "BoE XBRL Filing Manual; Bank of England Banking Taxonomy"

#: Examples named in one finding.
MAX_EXAMPLES: Final = 5

#: The largest instance read from a zip, uncompressed. The Bank's own full
#: PRA001 sample is 45 MB; this is a bound on a hostile archive, not on a return.
MAX_INSTANCE_BYTES: Final = 2 * 1024**3

_NS_XSI: Final = "http://www.w3.org/2001/XMLSchema-instance"
_CONTEXT: Final = f"{{{NS_XBRLI}}}context"
_UNIT: Final = f"{{{NS_XBRLI}}}unit"
_SCHEMA_REF: Final = f"{{{NS_LINK}}}schemaRef"
_INDICATORS: Final = f"{{{NS_FIND}}}fIndicators"
_INDICATOR: Final = f"{{{NS_FIND}}}filingIndicator"
_FILED: Final = f"{{{NS_FIND}}}filed"
_HREF: Final = f"{{{NS_XLINK}}}href"
_NIL: Final = f"{{{_NS_XSI}}}nil"

_NUMERIC_TYPES: Final = frozenset({"monetary", "percentage", "integer", "decimal"})

#: Separates the key values in a regenerated open-row identifier.
_ROW_KEY_SEPARATOR: Final = "|"

#: One dimension of a fact as read: (member QName or typed value, typed element).
_Value = tuple[str, str | None]


# =============================================================================
# Public entry point
# =============================================================================


class InstanceFormatError(ValueError):
    """The file is not an XBRL instance this package can read at all."""


@dataclass(frozen=True)
class InstanceReading:
    """An instance read back into the canonical return.

    Attributes:
        ret: The return: header, facts in their cells, and the filing
            indicators as the file declares them.
        pack: The taxonomy pack the file's ``schemaRef`` selected.
        findings: What the file holds that the module does not accept
            (``XBR001``-``XBR003``). All block submission.
        facts: XBRL facts in the file.
    """

    ret: CanonicalReturn
    pack: TaxonomyPack
    findings: tuple[Finding, ...]
    facts: int


def read_instance(source: Path | bytes, *, pack: TaxonomyPack | None = None) -> InstanceReading:
    """Read an XBRL instance — a ``.xbrl`` file, a ``.zip`` holding one, or its bytes.

    Args:
        source: The file, or its content.
        pack: The taxonomy to read it against. Defaults to the packaged pack
            whose entry point the file's ``schemaRef`` names.

    Raises:
        InstanceFormatError: the content is not well-formed XML, is not an XBRL
            instance, declares a document type, or names an entry point no
            packaged taxonomy has.
    """
    document = _parse(_content(source))
    pack = pack or _pack_for(document.schema_refs)
    header = _header(document, pack)
    findings = _filing_rule_findings(document, pack)

    facts, duplicate_findings = _distinct_facts(document, pack)
    findings.extend(duplicate_findings)
    indicators = dict(sorted(document.indicators.items())) if document.indicators else None
    rows, placement_findings = _place(facts, pack, indicators)
    findings.extend(placement_findings)

    frame = pl.DataFrame(rows, schema=FACT_SCHEMA, orient="row")
    logger.info(
        "read %s %s instance: %d fact(s) into %d cell(s), %d finding(s)",
        pack.info.module,
        pack.info.version,
        len(document.facts),
        frame.height,
        len(findings),
    )
    return InstanceReading(
        ret=CanonicalReturn.from_frame(header, frame, indicators),
        pack=pack,
        findings=tuple(findings),
        facts=len(document.facts),
    )


# =============================================================================
# Private helpers — parsing
# =============================================================================


@dataclass(frozen=True)
class _Context:
    identifier: str
    scheme: str
    instant: str | None
    members: tuple[tuple[str, _Value], ...]
    has_segment: bool


@dataclass(frozen=True)
class _RawFact:
    name: tuple[str, str]
    context: str
    unit: str | None
    decimals: str | None
    has_precision: bool
    is_nil: bool
    text: str
    prefixes: tuple[tuple[str, str], ...]


@dataclass
class _Document:
    schema_refs: list[str]
    contexts: dict[str, _Context]
    units: dict[str, tuple[str, str]]
    indicators: dict[str, bool]
    indicator_contexts: set[str]
    facts: list[_RawFact]
    uris: dict[str, str]


def _content(source: Path | bytes) -> bytes:
    """The instance's bytes, taken out of a zip where the source is one."""
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    if not data.startswith(b"PK\x03\x04"):
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [info for info in archive.infolist() if info.filename.lower().endswith(".xbrl")]
        if len(members) != 1:
            raise InstanceFormatError(
                f"A zipped filing holds exactly one .xbrl file; this one holds {len(members)}"
            )
        if members[0].file_size > MAX_INSTANCE_BYTES:
            raise InstanceFormatError("The .xbrl file in the zip is implausibly large")
        return archive.read(members[0])


def _parse(data: bytes) -> _Document:
    """One streaming pass over the instance."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise InstanceFormatError(
            "The file declares a document type. An XBRL filing never has one, and it is "
            "refused rather than processed."
        )
    document = _Document([], {}, {}, {}, set(), [], {})
    prefixes: list[tuple[str, str]] = []
    depth = 0
    root_seen = False
    try:
        for event, payload in ElementTree.iterparse(
            io.BytesIO(data), events=("start-ns", "start", "end")
        ):
            if event == "start-ns":
                prefix, uri = payload
                prefixes.append((prefix, uri))
                document.uris[prefix] = uri
                continue
            element = payload
            if event == "start":
                if depth == 0:
                    root_seen = True
                    if element.tag != f"{{{NS_XBRLI}}}xbrl":
                        raise InstanceFormatError(
                            "The file's root element is not xbrli:xbrl, so it is not an XBRL "
                            "instance"
                        )
                depth += 1
                continue
            depth -= 1
            if depth != 1:
                continue
            _read_top_level(element, document, tuple(prefixes))
            element.clear()
    except ElementTree.ParseError as error:
        raise InstanceFormatError(f"The file is not well-formed XML: {error}") from error
    if not root_seen:
        raise InstanceFormatError("The file is empty")
    return document


def _read_top_level(
    element: ElementTree.Element, document: _Document, prefixes: tuple[tuple[str, str], ...]
) -> None:
    """Record one child of the root: a context, unit, schemaRef, indicator set or fact."""
    tag = element.tag
    if tag == _SCHEMA_REF:
        document.schema_refs.append(element.get(_HREF, ""))
    elif tag == _CONTEXT:
        document.contexts[element.get("id", "")] = _read_context(element, dict(prefixes))
    elif tag == _UNIT:
        measure = (element.findtext(f"{{{NS_XBRLI}}}measure") or "").strip()
        document.units[element.get("id", "")] = _split(measure, dict(prefixes))
    elif tag == _INDICATORS:
        for indicator in element.iter(_INDICATOR):
            code = (indicator.text or "").strip()
            if code:
                document.indicators[code] = indicator.get(_FILED, "true").strip().lower() != "false"
                document.indicator_contexts.add(indicator.get("contextRef", ""))
    elif element.get("contextRef") is not None and tag.startswith("{"):
        uri, _, name = tag[1:].partition("}")
        document.facts.append(
            _RawFact(
                name=(uri, name),
                context=element.get("contextRef", ""),
                unit=element.get("unitRef"),
                decimals=element.get("decimals"),
                has_precision=element.get("precision") is not None,
                is_nil=element.get(_NIL, "false").strip().lower() in ("true", "1"),
                text=element.text or "",
                prefixes=prefixes,
            )
        )


def _read_context(element: ElementTree.Element, prefixes: dict[str, str]) -> _Context:
    identifier = element.find(f"{{{NS_XBRLI}}}entity/{{{NS_XBRLI}}}identifier")
    members: list[tuple[str, _Value]] = []
    for explicit in element.iter(f"{{{NS_XBRLDI}}}explicitMember"):
        dimension = _clark(explicit.get("dimension", ""), prefixes)
        members.append((dimension, (_clark((explicit.text or "").strip(), prefixes), None)))
    for typed in element.iter(f"{{{NS_XBRLDI}}}typedMember"):
        dimension = _clark(typed.get("dimension", ""), prefixes)
        child = next(iter(typed), None)
        if child is not None:
            members.append((dimension, ((child.text or "").strip(), child.tag)))
    return _Context(
        identifier=(identifier.text or "").strip() if identifier is not None else "",
        scheme=identifier.get("scheme", "") if identifier is not None else "",
        instant=(element.findtext(f"{{{NS_XBRLI}}}period/{{{NS_XBRLI}}}instant") or "").strip()
        or None,
        members=tuple(members),
        has_segment=element.find(f"{{{NS_XBRLI}}}entity/{{{NS_XBRLI}}}segment") is not None,
    )


def _split(qname: str, prefixes: dict[str, str]) -> tuple[str, str]:
    """A QName in the file's own prefixes as ``(namespace URI, local name)``."""
    prefix, _, name = qname.rpartition(":")
    return prefixes.get(prefix, ""), name


def _clark(qname: str, prefixes: dict[str, str]) -> str:
    """A QName in the file's own prefixes as ``{uri}local``."""
    uri, name = _split(qname, prefixes)
    return f"{{{uri}}}{name}"


# =============================================================================
# Private helpers — the header and the pack
# =============================================================================


def _pack_for(schema_refs: list[str]) -> TaxonomyPack:
    """The packaged pack whose entry point the file names."""
    if len(schema_refs) != 1:
        raise InstanceFormatError(
            f"A filing names exactly one taxonomy entry point; this file has {len(schema_refs)} "
            "schemaRef element(s)"
        )
    infos = [info for info in available_packs() if info.entry_point == schema_refs[0]]
    if not infos:
        known = ", ".join(f"{info.module} {info.version}" for info in available_packs()) or "none"
        raise InstanceFormatError(
            f"No packaged taxonomy has the entry point {schema_refs[0]!r}. Packaged: {known}."
        )
    return load_packaged(infos[-1].key)


def _header(document: _Document, pack: TaxonomyPack) -> ReturnHeader:
    """Who is reporting and as at when, from the file's first context."""
    context = next(iter(document.contexts.values()), None)
    if context is None or context.instant is None:
        raise InstanceFormatError("The file has no context with an instant period")
    try:
        reference_date = date.fromisoformat(context.instant[:10])
    except ValueError as error:
        raise InstanceFormatError(f"The file's period {context.instant!r} is not a date") from error
    currencies = sorted(name for uri, name in document.units.values() if uri == NS_ISO4217 and name)
    return ReturnHeader(
        entity_identifier=context.identifier,
        reference_date=reference_date,
        module=pack.info.module,
        currency=currencies[0] if currencies else "GBP",
        entity_scheme=context.scheme,
    )


# =============================================================================
# Private helpers — facts
# =============================================================================


@dataclass(frozen=True)
class _Fact:
    """One distinct fact, in the pack's own prefixes."""

    metric: str
    members: tuple[tuple[str, _Value], ...]
    value: float | None
    text: str | None
    decimals: int | None

    @property
    def label(self) -> str:
        members = ", ".join(f"{dimension}={value}" for dimension, (value, _typed) in self.members)
        return f"{self.metric}[{members}]" if members else self.metric


def _distinct_facts(document: _Document, pack: TaxonomyPack) -> tuple[list[_Fact], list[Finding]]:
    """The file's facts in the pack's prefixes, one per metric and context content.

    Two facts that say the same thing twice are one fact. Two that disagree
    cannot both be filed: the first is kept and the clash is reported.
    """
    prefix_of = {uri: prefix for prefix, uri in pack.namespaces.items()}

    def canonical(clark: str) -> str:
        uri, _, name = clark[1:].partition("}")
        return f"{prefix_of.get(uri, uri)}:{name}"

    distinct: dict[tuple[str, tuple[tuple[str, _Value], ...]], _Fact] = {}
    clashes: list[str] = []
    for raw in document.facts:
        context = document.contexts.get(raw.context)
        if context is None:
            continue
        metric = f"{prefix_of.get(raw.name[0], raw.name[0])}:{raw.name[1]}"
        members = tuple(
            sorted(
                (
                    canonical(dimension),
                    (
                        value if element else canonical(value),
                        canonical(element) if element else None,
                    ),
                )
                for dimension, (value, element) in context.members
            )
        )
        fact = _typed_fact(metric, members, raw, pack, prefix_of)
        seen = distinct.setdefault((metric, members), fact)
        if (seen.value, seen.text) != (fact.value, fact.text):
            clashes.append(fact.label)

    findings = (
        [
            _finding(
                FINDING_FILING_RULE,
                f"{len(clashes)} fact(s) are reported more than once with different values "
                f"(Filing Manual rule 2.16): {_examples(clashes)}.",
                subject="2.16",
                expected="one value per fact",
                actual=f"{len(clashes)} inconsistent duplicate(s)",
            )
        ]
        if clashes
        else []
    )
    return list(distinct.values()), findings


def _typed_fact(
    metric: str,
    members: tuple[tuple[str, _Value], ...],
    raw: _RawFact,
    pack: TaxonomyPack,
    prefix_of: dict[str, str],
) -> _Fact:
    """``raw``'s value as the canonical model holds one of the metric's type."""
    definition = pack.metrics.get(metric)
    text = raw.text.strip()
    if definition is not None and definition.data_type in _NUMERIC_TYPES:
        try:
            number: float | None = float(text)
        except ValueError:
            return _Fact(metric, members, None, text or None, None)
        return _Fact(metric, members, number, None, _decimals(raw.decimals))
    if definition is not None and definition.data_type == "enumeration" and ":" in text:
        uri, name = _split(text, dict(raw.prefixes))
        text = f"{prefix_of.get(uri, uri)}:{name}"
    return _Fact(metric, members, None, text or None, None)


def _decimals(text: str | None) -> int | None:
    if text is None:
        return None
    if text.strip().upper() == "INF":
        return DECIMALS_EXACT
    try:
        return int(text)
    except ValueError:
        return None


# =============================================================================
# Private helpers — placing facts in cells
# =============================================================================


def _place(
    facts: list[_Fact], pack: TaxonomyPack, indicators: dict[str, bool] | None
) -> tuple[list[tuple[object, ...]], list[Finding]]:
    """Each fact as the cell(s) the taxonomy shows it in.

    A fact is placed in every reported template that shows its data point —
    some figures appear in two tables, and the rules of both read them.
    """
    index = _DataPointIndex(pack)
    reported = None if indicators is None else {code for code, filed in indicators.items() if filed}
    rows: dict[tuple[object, ...], tuple[object, ...]] = {}
    unknown: list[str] = []
    orphaned: list[str] = []
    for fact in facts:
        points = index.match(fact)
        if not points:
            unknown.append(fact.label)
            continue
        placed = False
        for point in points:
            for table_code, row, column, sheet in index.cells.get(point, ()):
                table = pack.tables[table_code]
                if reported is not None and table.filing_indicator not in reported:
                    continue
                placed = True
                for cell in _cells(fact, table, row, column, sheet):
                    rows.setdefault(cell[:5], cell)
        if not placed:
            orphaned.append(fact.label)

    findings: list[Finding] = []
    if unknown:
        findings.append(
            _finding(
                FINDING_UNKNOWN_DATAPOINT,
                f"{len(unknown)} fact(s) are not data points of {pack.info.module} "
                f"{pack.info.version}: no reportable cell has that metric with those dimension "
                f"members. {_examples(unknown)}.",
                subject=pack.info.module,
                expected="a data point of the module",
                actual=f"{len(unknown)} fact(s)",
            )
        )
    if orphaned:
        findings.append(
            _finding(
                FINDING_FACT_NOT_INDICATED,
                f"{len(orphaned)} fact(s) appear only in templates the file does not declare "
                f"as reported (Filing Manual rule 1.7.1): {_examples(orphaned)}.",
                subject="1.7.1",
                expected="a positive filing indicator for a template showing the fact",
                actual=f"{len(orphaned)} fact(s)",
            )
        )
    return list(rows.values()), findings


class _DataPointIndex:
    """Finds the data point(s) a fact's metric and members identify.

    A data point fixes most of its members and may leave some OPEN, to be
    chosen by the filer. A fact matches when its members are exactly the fixed
    ones plus a member for each open dimension (an optional one may be absent).
    """

    def __init__(self, pack: TaxonomyPack) -> None:
        self._fixed: dict[tuple[str, frozenset[tuple[str, str]]], list[int]] = {}
        self._open: dict[int, tuple[tuple[str, str], ...]] = {}
        self._open_names: set[str] = set()
        for number, point in enumerate(pack.datapoints):
            fixed = frozenset(
                (dimension, member)
                for dimension, member in point.dimensions
                if not member.startswith("*")
            )
            opened = tuple(
                (dimension, member)
                for dimension, member in point.dimensions
                if member.startswith("*")
            )
            self._fixed.setdefault((point.metric, fixed), []).append(number)
            if opened:
                self._open[number] = opened
                self._open_names.update(dimension for dimension, _member in opened)
        self.cells: dict[int, list[tuple[str, str | None, str, str | None]]] = {}
        for table, row, column, sheet, point in pack.cells.select(
            "table", "row", "column", "sheet", "datapoint"
        ).iter_rows():
            self.cells.setdefault(point, []).append((table, row, column, sheet))

    def match(self, fact: _Fact) -> list[int]:
        members = dict(fact.members)
        candidates = [dimension for dimension in members if dimension in self._open_names]
        matches: list[int] = []
        for size in range(len(candidates) + 1):
            for supplied in combinations(candidates, size):
                rest = {d: v for d, v in members.items() if d not in supplied}
                if any(element is not None for _value, element in rest.values()):
                    continue
                fixed = frozenset((d, value) for d, (value, _element) in rest.items())
                for number in self._fixed.get((fact.metric, fixed), ()):
                    if self._accepts(number, set(supplied), members):
                        matches.append(number)
        return matches

    def _accepts(self, number: int, supplied: set[str], members: dict[str, _Value]) -> bool:
        opened = self._open.get(number, ())
        if not supplied <= {dimension for dimension, _placeholder in opened}:
            return False
        for dimension, placeholder in opened:
            if dimension not in supplied:
                if placeholder != MEMBER_OPEN_OPTIONAL:
                    return False
                continue
            _value, element = members[dimension]
            is_typed = placeholder.startswith(MEMBER_TYPED_PREFIX)
            if is_typed != (element is not None):
                return False
            if is_typed and placeholder[len(MEMBER_TYPED_PREFIX) :] != element:
                return False
        return True


def _cells(
    fact: _Fact, table: Table, row: str | None, column: str, sheet: str | None
) -> Iterator[tuple[object, ...]]:
    """The canonical fact row(s) for ``fact`` in one cell of ``table``.

    In an open-row table the row is identified by its key values, and each key
    is itself a fact in its key column.
    """
    members = dict(fact.members)
    axis = table.open_axis
    open_key = None
    if axis is not None and axis.dimension in members:
        open_key = local_name(members[axis.dimension][0])
    if not table.open_rows:
        yield (table.code, sheet, open_key, row, column, fact.value, fact.text, fact.decimals)
        return

    keys = [
        (key.code, _key_text(members.get(key.dimension), key.kind == "explicit"))
        for key in table.open_keys
    ]
    row_id = _ROW_KEY_SEPARATOR.join(text for _code, text in keys)
    for code, text in keys:
        yield (table.code, sheet, open_key, row_id, code, None, text, None)
    yield (table.code, sheet, open_key, row_id, column, fact.value, fact.text, fact.decimals)


def _key_text(value: _Value | None, explicit: bool) -> str:
    if value is None:
        return ""
    return local_name(value[0]) if explicit else value[0]


# =============================================================================
# Private helpers — Filing Manual rules the reader can see
# =============================================================================


def _filing_rule_findings(document: _Document, pack: TaxonomyPack) -> list[Finding]:
    """Breaches visible without loading the taxonomy, one finding per rule."""
    contexts = document.contexts.values()
    used = {fact.context for fact in document.facts} | document.indicator_contexts
    prefix_of = {uri: prefix for prefix, uri in pack.namespaces.items()}
    numeric_names = {
        (pack.namespaces[qname.split(":", 1)[0]], qname.split(":", 1)[1])
        for qname, metric in pack.metrics.items()
        if metric.data_type in _NUMERIC_TYPES and qname.split(":", 1)[0] in pack.namespaces
    }
    numeric = [fact for fact in document.facts if fact.name in numeric_names]
    foreign = sum(fact.name[0] not in prefix_of for fact in document.facts)
    checks: list[tuple[str, str, int]] = [
        (
            "2.9",
            "every context names the same reporting entity and identifier scheme",
            max(len({(context.identifier, context.scheme) for context in contexts}) - 1, 0),
        ),
        (
            "2.10",
            "every context carries the same instant date",
            max(len({context.instant for context in contexts}) - 1, 0)
            + sum(context.instant is None for context in contexts),
        ),
        ("2.14", "no context uses xbrli:segment", sum(c.has_segment for c in contexts)),
        (
            "1.6",
            "filing indicators refer to a context with no dimensions",
            sum(
                bool(document.contexts[name].members)
                for name in document.indicator_contexts
                if name in document.contexts
            ),
        ),
        ("2.7", "no context is unused", len(set(document.contexts) - used)),
        (
            "2.7",
            "every fact refers to a context the file defines",
            sum(fact.context not in document.contexts for fact in document.facts),
        ),
        ("2.17", "no fact uses @precision", sum(fact.has_precision for fact in document.facts)),
        ("2.18", "every numeric fact states @decimals", sum(f.decimals is None for f in numeric)),
        ("2.19", "no fact is nil", sum(fact.is_nil for fact in document.facts)),
        (
            "2.19",
            "no fact is empty",
            sum(not fact.text.strip() and not fact.is_nil for fact in document.facts),
        ),
        (
            "2.21",
            "every numeric fact refers to a unit the file defines",
            sum(fact.unit not in document.units for fact in numeric),
        ),
    ]
    if foreign:
        logger.info("%d fact(s) are in a namespace the pack does not declare", foreign)
    return [
        _finding(
            FINDING_FILING_RULE,
            f"Filing Manual rule {rule} requires that {requirement}; {count} breach(es) found.",
            subject=rule,
            expected=requirement,
            actual=f"{count} breach(es)",
        )
        for rule, requirement, count in checks
        if count
    ]


def _examples(labels: list[str]) -> str:
    shown = "; ".join(labels[:MAX_EXAMPLES])
    more = "" if len(labels) <= MAX_EXAMPLES else f" (first {MAX_EXAMPLES} of {len(labels)})"
    return f"{shown}{more}"


def _finding(code: str, message: str, *, subject: str, expected: str, actual: str) -> Finding:
    return Finding(
        code=code,
        severity=SEVERITY_ERROR,
        message=message,
        reference=READER_REFERENCE,
        subject=subject,
        expected=expected,
        actual=actual,
    )
