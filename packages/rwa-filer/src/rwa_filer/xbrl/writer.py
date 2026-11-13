"""
XBRL instance writer — a canonical return as the file the regulator accepts.

Pipeline position:
    CanonicalReturn -> validate.structure (must be clean) -> write_instance
        -> Instance(content: bytes)  ->  filing.build_filing  ->  <name>.xbrl

Key responsibilities:
- Turn each reported cell into the XBRL fact its data point defines: the metric
  as the element, the data point's dimension members as the context's scenario,
  the open-axis member or open-row key filled in where the data point leaves
  one open.
- Write ONE fact per data point. Some figures appear in more than one table;
  they are one fact in the submission, and the structure checks have already
  established that the cells agree.
- Follow the Bank of England XBRL Filing Manual: UTF-8, one ``schemaRef`` to the
  module's entry point, one entity and one instant across every context,
  dimensions in ``xbrli:scenario`` only, no unused or duplicated contexts or
  units, no unused namespace prefixes, ``decimals`` on every numeric fact and
  never ``precision``, the ``pure`` unit for non-monetary numbers, no ``nil``
  and no empty facts, and a positive filing indicator for every template that
  has a fact.
- Be deterministic: the same return and options give byte-identical output.

What the writer does NOT do: decide whether the return may be filed. It refuses
a return that is not structurally expressible — a fact with no data point has no
element to be written as — and nothing else. Rule breaks are the caller's
decision (``filing.build_filing``).

Numbers
- A monetary value is written as known, to the penny, in units of the reporting
  currency with no scaling. ``decimals`` states its accuracy, and defaults to
  ``-3`` — accurate to thousands, the convention of the Bank's own sample
  instances. Stating LESS accuracy than a value has is always true; stating
  more makes the regulator's interval arithmetic hold figures to a precision
  the source may not have.
- A percentage is a decimal fraction (9.31% is ``0.0931``), written to six
  places with ``decimals`` at least 4.
- An integer is written whole, with ``decimals="0"``.

References:
- BoE XBRL Filing Manual v1.0.1: 1.4 (UTF-8), 1.5 (entry point), 1.6 (filing
  indicators), 2.3 (one schemaRef), 2.7 (contexts), 2.8-2.10 (entity, period),
  2.14-2.15 (scenario only), 2.16 (duplicates), 2.17-2.19 (decimals, zeros),
  2.21-2.24 (units), 2.26 (software information), 3.2-3.5 (pure unit, decimal
  fractions, namespace prefixes)
- XBRL 2.1; XBRL Dimensions 1.0 (a default member is never written)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Final
from xml.sax.saxutils import escape, quoteattr

import polars as pl

from rwa_filer import __version__
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.taxonomy.pack import (
    MEMBER_OPEN,
    MEMBER_OPEN_OPTIONAL,
    MEMBER_TYPED_PREFIX,
    resolve_pack,
)
from rwa_filer.validate.structure import (
    IS_KEY,
    check_structure,
    filing_indicators,
    key_text,
    local_name,
    resolve_datapoints,
)

if TYPE_CHECKING:
    from datetime import datetime

    from rwa_filer.model import CanonicalReturn, ReturnHeader
    from rwa_filer.taxonomy.pack import Table, TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

NS_XBRLI: Final = "http://www.xbrl.org/2003/instance"
NS_LINK: Final = "http://www.xbrl.org/2003/linkbase"
NS_XLINK: Final = "http://www.w3.org/1999/xlink"
NS_XBRLDI: Final = "http://xbrl.org/2006/xbrldi"
NS_ISO4217: Final = "http://www.xbrl.org/2003/iso4217"
NS_FIND: Final = "http://www.eurofiling.info/xbrl/ext/filing-indicators"

#: The identifier written by the ``instance-generator`` processing instruction.
GENERATOR_ID: Final = "rwa-filer"

#: The context that carries no dimensions: the filing indicators', and that of
#: any fact whose data point has none. One context, so it is never duplicated.
BASE_CONTEXT: Final = "c0"
UNIT_PURE: Final = "upure"

TYPE_MONETARY: Final = "monetary"
TYPE_PERCENTAGE: Final = "percentage"
TYPE_INTEGER: Final = "integer"
TYPE_DECIMAL: Final = "decimal"
TYPE_ENUMERATION: Final = "enumeration"
TYPE_BOOLEAN: Final = "boolean"

#: Decimal places a value of each numeric type is written to.
_PLACES: Final = {TYPE_MONETARY: 2, TYPE_PERCENTAGE: 6, TYPE_DECIMAL: 6, TYPE_INTEGER: 0}

#: The least ``decimals`` the Filing Manual accepts on a percentage.
MIN_PERCENTAGE_DECIMALS: Final = 4


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class InstanceOptions:
    """How the numbers are stated, and how the file identifies its origin.

    Attributes:
        monetary_decimals: The ``decimals`` of every monetary fact — the
            accuracy the figures are stated to. ``-3`` is thousands, ``0``
            units, ``2`` pence.
        percentage_decimals: The ``decimals`` of percentages and ratios. The
            Filing Manual requires at least 4.
        created_at: Written to the ``instance-generator`` instruction. ``None``
            omits the creation date, which keeps the output reproducible.
        declare_unreported: Also write a negative filing indicator for every
            template of the module the return does not report.
    """

    monetary_decimals: int = -3
    percentage_decimals: int = 4
    created_at: datetime | None = None
    declare_unreported: bool = False

    def __post_init__(self) -> None:
        if self.percentage_decimals < MIN_PERCENTAGE_DECIMALS:
            raise ValueError(
                f"percentage_decimals must be at least {MIN_PERCENTAGE_DECIMALS} "
                "(BoE XBRL Filing Manual, rule 2.18)"
            )


@dataclass(frozen=True)
class Instance:
    """A written XBRL instance and what went into it.

    Attributes:
        content: The file, UTF-8 encoded.
        facts: XBRL facts written — one per reported data point.
        cells: Reported cells those facts came from. More than ``facts`` when a
            figure is shown in more than one table.
        contexts: Contexts written, the dimensionless one included.
        filing_indicators: The templates declared as reported, sorted.
    """

    content: bytes
    facts: int
    cells: int
    contexts: int
    filing_indicators: tuple[str, ...]


class UnwritableReturnError(ValueError):
    """The return has a fact that cannot be expressed in the taxonomy."""


def write_instance(
    ret: CanonicalReturn,
    pack: TaxonomyPack | None = None,
    *,
    options: InstanceOptions | None = None,
) -> Instance:
    """Write ``ret`` as an XBRL 2.1 instance against ``pack``'s entry point.

    Args:
        ret: The return. It must pass the structure checks.
        pack: The taxonomy it is filed against. Defaults to the packaged pack
            in force for the return's module on its reference date.
        options: How numbers are stated; the defaults follow the Bank's samples.

    Raises:
        UnwritableReturnError: ``ret`` has structure findings. Run
            ``validate_return`` first: its findings say what to fix.
        PackNotFoundError: no ``pack`` was given and none is packaged.
    """
    options = options or InstanceOptions()
    pack = pack or resolve_pack(ret.header.module, ret.header.reference_date)
    findings = check_structure(ret, pack)
    if findings:
        raise UnwritableReturnError(
            f"The return has {len(findings)} structure finding(s) and cannot be written; "
            f"the first is {findings[0].code}: {findings[0].message}"
        )

    facts = _xbrl_facts(ret, pack)
    document = _Document(ret.header, pack, options)
    for fact in facts:
        document.add(fact)
    indicators = filing_indicators(ret, pack)
    if options.declare_unreported:
        indicators = dict.fromkeys(pack.filing_indicators, False) | indicators
    content = document.render(indicators).encode("utf-8")
    cells = sum(fact.cells for fact in facts)
    logger.info(
        "wrote %s %s instance: %d fact(s) from %d cell(s), %d context(s), %d filing indicator(s)",
        pack.info.module,
        pack.info.version,
        len(facts),
        cells,
        len(document.contexts),
        sum(indicators.values()),
    )
    return Instance(
        content=content,
        facts=len(facts),
        cells=cells,
        contexts=len(document.contexts),
        filing_indicators=tuple(code for code, filed in indicators.items() if filed),
    )


def lexical(value: float, places: int) -> str:
    """``value`` as XBRL writes a decimal: fixed notation, no exponent, no padding.

    Rounded half-to-even to ``places`` decimal places — the rounding XBRL 2.1
    requires of a number that is rounded at all — with insignificant trailing
    zeros dropped, and never ``-0``.
    """
    quantum = Decimal(1).scaleb(-places)
    text = format(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_EVEN), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# =============================================================================
# Private helpers — facts
# =============================================================================

#: One dimension of a fact: (dimension qname, member qname or typed value,
#: typed element qname or None for an explicit member).
_Member = tuple[str, str, str | None]


@dataclass(frozen=True)
class _Fact:
    """One XBRL fact: a metric, its dimension members and a value."""

    metric: str
    members: tuple[_Member, ...]
    value: float | None
    text: str | None
    decimals: int | None
    cells: int


def _xbrl_facts(ret: CanonicalReturn, pack: TaxonomyPack) -> list[_Fact]:
    """The return's facts as XBRL facts, one per data point.

    The order is the return's own (table, sheet, open key, row, column), so the
    output does not depend on the order the source supplied its rows in.
    """
    resolved = resolve_datapoints(ret, pack)
    row_id = ("table", "sheet", "open_key", "row")
    row_keys: dict[tuple[object, ...], dict[str, str]] = {}
    for *identity, column, text in (
        resolved.filter(pl.col(IS_KEY))
        .select(*row_id, "column", key_text().alias("key"))
        .iter_rows()
    ):
        row_keys.setdefault(tuple(identity), {})[column] = text

    merged: dict[tuple[str, tuple[_Member, ...]], _Fact] = {}
    data = resolved.filter(~pl.col(IS_KEY)).sort(
        "table", "sheet", "open_key", "row", "column", nulls_last=False
    )
    for fact in data.iter_rows(named=True):
        table = pack.tables[fact["table"]]
        point = pack.datapoints[fact["datapoint"]]
        open_key = fact["open_key"]
        keys = row_keys.get((table.code, fact["sheet"], open_key, fact["row"]), {})
        members = tuple(
            sorted(
                (
                    member
                    for dimension, placeholder in point.dimensions
                    if (member := _member(pack, table, dimension, placeholder, open_key, keys))
                    is not None
                ),
                key=lambda member: member[0],
            )
        )
        identity = (point.metric, members)
        seen = merged.get(identity)
        if seen is None:
            merged[identity] = _Fact(
                point.metric, members, fact["value"], fact["text_value"], fact["decimals"], 1
            )
            continue
        if (seen.value, seen.text) != (fact["value"], fact["text_value"]):
            raise UnwritableReturnError(
                f"{table.code} row {fact['row']} reports {point.metric} with a different value "
                "from another cell of the same data point"
            )
        merged[identity] = _Fact(
            seen.metric,
            seen.members,
            seen.value,
            seen.text,
            _least_accurate(seen.decimals, fact["decimals"]),
            seen.cells + 1,
        )
    return list(merged.values())


def _least_accurate(first: int | None, second: int | None) -> int | None:
    """The lower of two stated accuracies; unstated yields to stated.

    One data point shown in two cells is one fact. Where the cells state
    different accuracies, claiming the lower is the one that is true of both.
    """
    if first is None or second is None:
        return first if second is None else second
    return min(first, second)


def _member(
    pack: TaxonomyPack,
    table: Table,
    dimension: str,
    placeholder: str,
    open_key: str | None,
    row_keys: dict[str, str],
) -> _Member | None:
    """One dimension of a fact, or ``None`` where the dimension is not written.

    A data point fixes most of its members. Where it leaves one open, the member
    comes from the fact: the open sheet axis's member (``open_key``), or the
    row's key in an open-row table. A dimension's DEFAULT member is never
    written — XBRL Dimensions forbids it, and its absence means the default.
    """
    if placeholder.startswith(MEMBER_TYPED_PREFIX):
        return (
            dimension,
            _supplied(table, dimension, open_key, row_keys),
            placeholder[len(MEMBER_TYPED_PREFIX) :],
        )
    if placeholder not in (MEMBER_OPEN, MEMBER_OPEN_OPTIONAL):
        return (dimension, placeholder, None)

    axis = table.open_axis
    if axis is not None and axis.dimension == dimension:
        if open_key is None:
            return None
        member = _qualified(open_key, axis.members)
    else:
        key = next(key for key in table.open_keys if key.dimension == dimension)
        member = _qualified(_supplied(table, dimension, open_key, row_keys), key.members)
    definition = pack.dimensions.get(dimension)
    if definition is not None and definition.default == member:
        return None
    return (dimension, member, None)


def _supplied(table: Table, dimension: str, open_key: str | None, row_keys: dict[str, str]) -> str:
    """The value a fact supplies for an open ``dimension``."""
    axis = table.open_axis
    if axis is not None and axis.dimension == dimension and open_key is not None:
        return open_key
    key = next((key for key in table.open_keys if key.dimension == dimension), None)
    if key is None or key.code not in row_keys:
        raise UnwritableReturnError(
            f"{table.code}: no value is supplied for the open dimension {dimension}"
        )
    return row_keys[key.code]


def _qualified(name: str, members: tuple[str, ...]) -> str:
    """``name`` as a member QName: itself if qualified, else the member with that local name."""
    if name in members or ":" in name:
        return name
    match = next((member for member in members if local_name(member) == name), None)
    if match is None:
        raise UnwritableReturnError(f"{name!r} is not a member the taxonomy accepts here")
    return match


# =============================================================================
# Private helpers — the document
# =============================================================================


class _Document:
    """Accumulates the contexts, units, prefixes and fact lines of one instance."""

    def __init__(self, header: ReturnHeader, pack: TaxonomyPack, options: InstanceOptions) -> None:
        self._header = header
        self._pack = pack
        self._options = options
        self.contexts: dict[tuple[_Member, ...], str] = {(): BASE_CONTEXT}
        self._units: dict[str, str] = {}
        self._prefixes: set[str] = set()
        self._facts: list[str] = []

    def add(self, fact: _Fact) -> None:
        """Write one fact, registering the context, unit and prefixes it needs."""
        metric = self._pack.metrics[fact.metric]
        context = self.contexts.setdefault(fact.members, f"c{len(self.contexts)}")
        self._use(fact.metric)
        for dimension, member, element in fact.members:
            self._use(dimension)
            self._use(element if element is not None else member)

        if metric.is_numeric:
            if fact.value is None:
                raise UnwritableReturnError(f"{fact.metric} is numeric and has no value")
            unit, decimals = self._unit_and_decimals(metric.data_type, fact.decimals)
            body = lexical(fact.value, _PLACES.get(metric.data_type, 6))
            stated = "INF" if decimals >= DECIMALS_EXACT else str(decimals)
            attributes = f'contextRef="{context}" decimals="{stated}" unitRef="{unit}"'
        else:
            body = escape(self._text(fact, metric.data_type, metric.enumeration))
            attributes = f'contextRef="{context}"'
        self._facts.append(f"  <{fact.metric} {attributes}>{body}</{fact.metric}>")

    def render(self, indicators: dict[str, bool]) -> str:
        """The whole instance as text, with ``indicators`` as its filing indicators."""
        header, pack = self._header, self._pack
        namespaces = {"xbrli": NS_XBRLI, "link": NS_LINK, "xlink": NS_XLINK, "find": NS_FIND}
        if len(self.contexts) > 1:
            namespaces["xbrldi"] = NS_XBRLDI
        if any(measure.startswith("iso4217:") for measure in self._units.values()):
            namespaces["iso4217"] = NS_ISO4217
        for prefix in sorted(self._prefixes):
            if prefix not in pack.namespaces:
                raise UnwritableReturnError(
                    f"the taxonomy pack declares no namespace for {prefix!r}"
                )
            namespaces[prefix] = pack.namespaces[prefix]

        entity = (
            "    <xbrli:entity>\n"
            f"      <xbrli:identifier scheme={quoteattr(header.entity_scheme)}>"
            f"{escape(header.entity_identifier)}</xbrli:identifier>\n"
            "    </xbrli:entity>\n"
            "    <xbrli:period>\n"
            f"      <xbrli:instant>{header.reference_date.isoformat()}</xbrli:instant>\n"
            "    </xbrli:period>\n"
        )
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', self._generator()]
        declarations = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in namespaces.items())
        lines.append(f"<xbrli:xbrl {declarations}>")
        lines.append(
            f'  <link:schemaRef xlink:type="simple" xlink:href={quoteattr(pack.info.entry_point)}/>'
        )
        for unit, measure in sorted(self._units.items()):
            lines.append(
                f'  <xbrli:unit id="{unit}">\n'
                f"    <xbrli:measure>{measure}</xbrli:measure>\n"
                "  </xbrli:unit>"
            )
        for members, context in self.contexts.items():
            lines.append(
                f'  <xbrli:context id="{context}">\n{entity}{_scenario(members)}  </xbrli:context>'
            )
        lines.extend(self._facts)
        lines.append("  <find:fIndicators>")
        for code, filed in sorted(indicators.items()):
            flag = "" if filed else ' find:filed="false"'
            lines.append(
                f'    <find:filingIndicator contextRef="{BASE_CONTEXT}"{flag}>{escape(code)}'
                "</find:filingIndicator>"
            )
        lines.append("  </find:fIndicators>")
        lines.append("</xbrli:xbrl>")
        return "\n".join(lines) + "\n"

    def _unit_and_decimals(self, data_type: str, stated: int | None) -> tuple[str, int]:
        """The unit a numeric fact is in and the accuracy it is stated to.

        A fact's own ``decimals`` wins over the default for its type, within
        what the Filing Manual allows: an integer is always exact to units, and
        a percentage is never stated to fewer than four places.
        """
        if data_type == TYPE_MONETARY:
            currency = self._header.currency.upper()
            unit = f"u{currency}"
            self._units[unit] = f"iso4217:{currency}"
            return unit, self._options.monetary_decimals if stated is None else stated
        self._units[UNIT_PURE] = "xbrli:pure"
        if data_type == TYPE_INTEGER:
            return UNIT_PURE, 0
        if stated is None:
            return UNIT_PURE, self._options.percentage_decimals
        return UNIT_PURE, max(stated, MIN_PERCENTAGE_DECIMALS)

    def _text(self, fact: _Fact, data_type: str, enumeration: str | None) -> str:
        text = (fact.text or "").strip()
        if not text:
            raise UnwritableReturnError(f"{fact.metric} has no value; an empty fact is not allowed")
        if data_type == TYPE_BOOLEAN:
            return text.lower()
        if data_type == TYPE_ENUMERATION:
            member = _qualified(text, self._pack.enumerations.get(enumeration or "", ()))
            self._use(member)
            return member
        return text

    def _use(self, qname: str) -> None:
        self._prefixes.add(qname.split(":", 1)[0])

    def _generator(self) -> str:
        created = self._options.created_at
        stamp = f' creationdate="{created.isoformat(timespec="seconds")}"' if created else ""
        return f'<?instance-generator id="{GENERATOR_ID}" version="{__version__}"{stamp}?>'


def _scenario(members: tuple[_Member, ...]) -> str:
    """A context's ``xbrli:scenario``, or nothing for the dimensionless context."""
    if not members:
        return ""
    lines = ["    <xbrli:scenario>"]
    for dimension, member, element in members:
        if element is None:
            lines.append(
                f'      <xbrldi:explicitMember dimension="{dimension}">{member}'
                "</xbrldi:explicitMember>"
            )
        else:
            lines.append(
                f'      <xbrldi:typedMember dimension="{dimension}">'
                f"<{element}>{escape(member)}</{element}></xbrldi:typedMember>"
            )
    lines.append("    </xbrli:scenario>")
    return "\n".join(lines) + "\n"
