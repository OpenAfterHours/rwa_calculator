"""
Returns and instances for the XBRL reader's tests.

The reader's own tests need three things ``pack_builders`` does not give:

- ``open_row_return`` — a return over the open-row tables of a REAL pack. The
  sample pack has one open-row table with one typed key. PRA001 has eighteen,
  and between them every shape the reader has to put back together: a typed key
  (text, whole number, date), a key chosen from a list of members, two keys on
  one row, a key beside an open sheet axis, and data points that leave two
  dimensions open at once.
- ``many_rows_return`` — the sample pack's open-row table at any number of
  rows, for the tests that count what a read costs at two sizes.
- ``instance_of`` — an instance written by hand in the pack's own prefixes, for
  facts the package's writer refuses to write because no cell shows them. Those
  are exactly the facts the reader exists to report.

Every row id is the row's key values joined by ``|``, which is how the reader
names an open row it reads. A return built here therefore reads back equal to
itself, not merely equal cell for cell.

They are test data, not a statement about any real return.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape, quoteattr

import polars as pl

from pack_builders import VALID_LEI, build_return
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.xbrl.writer import NS_ISO4217, NS_LINK, NS_XBRLDI, NS_XBRLI, NS_XLINK

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_filer.taxonomy.pack import Metric, OpenKey, Table, TaxonomyPack

#: The PRA001 open-row tables ``open_row_return`` fills, and what each one adds.
OPEN_ROW_TABLES = (
    "C06.02.01.01",  # a listed key and a text key; every data point leaves two dimensions open
    "C32.03.01.01",  # a whole-number key
    "C34.06.01.01",  # a text key and a listed key, the other way round
    "OF08.02.01.01",  # a whole-number key under fixed sheets
    "OF08.05.01.02",  # a text key beside an open sheet axis, under fixed sheets
    "OF24.03.01.03",  # a text key and a date key
)

#: The accuracy the writer states for a fact that names none, by metric type.
#: A return that states the same reads back equal in ``decimals`` too.
_DECIMALS = {"monetary": -3, "percentage": 4, "decimal": 4, "integer": 0}

_SHEETS_PER_TABLE = 2
_OPEN_KEYS_PER_TABLE = 2

_ROW_KEY_SEPARATOR = "|"
_INSTANT = "2027-03-31"
_LEI_SCHEME = "http://standards.iso.org/iso/17442"


# =============================================================================
# Returns
# =============================================================================


def open_row_return(
    pack: TaxonomyPack, header: ReturnHeader, rows_per_table: int
) -> CanonicalReturn:
    """``rows_per_table`` rows in each of ``OPEN_ROW_TABLES``, every cell of each row filled.

    The return states the accuracy of every number and declares its own filing
    indicators, so nothing is left for the writer to fill in: what is read back
    from the written instance is this return.
    """
    rows: list[tuple[object, ...]] = []
    for code in OPEN_ROW_TABLES:
        rows.extend(_open_table_rows(pack, pack.tables[code], rows_per_table))
    frame = pl.DataFrame(rows, schema=FACT_SCHEMA, orient="row")
    indicators = {pack.tables[code].filing_indicator: True for code in OPEN_ROW_TABLES}
    return CanonicalReturn.from_frame(header, frame, dict(sorted(indicators.items())))


def many_rows_return(rows: int) -> CanonicalReturn:
    """The sample pack's open-row table ``T04.00.01.01`` with ``rows`` rows.

    Each row is two facts in one context — an amount and a count under the same
    typed key — so the file has half as many contexts as facts.
    """
    cells: list[tuple[object, ...]] = []
    for number in range(1, rows + 1):
        key = str(number)
        cells.append(("T04.00.01.01", None, None, key, "0005", None, key, None))
        cells.append(("T04.00.01.01", None, None, key, "0010", float(1000 + number), None, -3))
        cells.append(("T04.00.01.01", None, None, key, "0020", float(number % 9), None, 0))
    return build_return(pl.DataFrame(cells, schema=FACT_SCHEMA, orient="row"))


# =============================================================================
# Instances
# =============================================================================


@dataclass(frozen=True)
class HandFact:
    """One fact of a hand-written instance: a metric, its explicit members, its text."""

    metric: str
    members: tuple[tuple[str, str], ...] = ()
    text: str = "1"


def instance_of(pack: TaxonomyPack, facts: Sequence[HandFact]) -> bytes:
    """An instance holding ``facts`` as given, in the pack's prefixes and with no indicators.

    Nothing is checked: a fact no cell of the pack shows is written like any
    other. Facts with the same members share a context, as a filing's do. With
    no filing indicators the reader takes every template as reported.
    """
    contexts: dict[tuple[tuple[str, str], ...], str] = {}
    lines: list[str] = []
    for fact in facts:
        context = contexts.setdefault(fact.members, f"c{len(contexts) + 1}")
        lines.append(
            f'  <{fact.metric} contextRef="{context}" unitRef="u" decimals="0">'
            f"{escape(fact.text)}</{fact.metric}>"
        )
    namespaces = {
        "xbrli": NS_XBRLI,
        "link": NS_LINK,
        "xlink": NS_XLINK,
        "xbrldi": NS_XBRLDI,
        "iso4217": NS_ISO4217,
        **pack.namespaces,
    }
    declarations = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in namespaces.items())
    head = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<xbrli:xbrl {declarations}>",
        f'  <link:schemaRef xlink:type="simple" xlink:href={quoteattr(pack.info.entry_point)}/>',
        '  <xbrli:unit id="u"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>',
    ]
    head.extend(_context(name, members) for members, name in contexts.items())
    return "\n".join([*head, *lines, "</xbrli:xbrl>", ""]).encode("utf-8")


# =============================================================================
# Private helpers
# =============================================================================


def _open_table_rows(pack: TaxonomyPack, table: Table, count: int) -> list[tuple[object, ...]]:
    """``count`` complete rows of one open-row table, on a few of its sheets."""
    cells = pack.cells.filter(pl.col("table") == table.code)
    sheets = cells["sheet"].unique(maintain_order=True).to_list()[:_SHEETS_PER_TABLE]
    rows: list[tuple[object, ...]] = []
    for number in range(count):
        keys = [(key.code, _key_text(key, number)) for key in table.open_keys]
        row = _ROW_KEY_SEPARATOR.join(text for _code, text in keys)
        for sheet in sheets:
            shown = cells.filter(pl.col("sheet").eq_missing(sheet))
            for open_key in _open_keys(pack, table):
                place = (table.code, sheet, open_key, row)
                rows.extend((*place, code, None, text, None) for code, text in keys)
                for column, point in shown.select("column", "datapoint").iter_rows():
                    metric = pack.metrics[pack.datapoints[point].metric]
                    value, text = _cell_value(pack, metric, number)
                    rows.append((*place, column, value, text, _DECIMALS.get(metric.data_type)))
    return rows


def _open_keys(pack: TaxonomyPack, table: Table) -> list[str | None]:
    """Open sheets to fill, by the local name the reader gives them; ``[None]`` with no open axis.

    A dimension's default member is never written to a file, so a fact under
    it reads back with no open key. It is left out to keep the round trip exact.
    """
    axis = table.open_axis
    if axis is None:
        return [None]
    definition = pack.dimensions.get(axis.dimension)
    default = definition.default if definition is not None else None
    members = [member for member in axis.members if member != default]
    return [member.rsplit(":", 1)[-1] for member in members[:_OPEN_KEYS_PER_TABLE]]


def _key_text(key: OpenKey, number: int) -> str:
    """Row ``number``'s value in one key column, as the reader hands it back."""
    if key.kind == "explicit":
        return key.members[number % len(key.members)].rsplit(":", 1)[-1]
    kind = (key.typed_type or "").lower()
    if "int" in kind:
        return str(number + 1)
    if "date" in kind:
        return f"2026-{1 + number % 12:02d}-{1 + number % 28:02d}"
    return f"KEY{number:05d}"


def _cell_value(pack: TaxonomyPack, metric: Metric, number: int) -> tuple[float | None, str | None]:
    """A value of the metric's own type that survives being written and read exactly."""
    kind = metric.data_type
    if kind == "monetary":
        return float(1000 + 7 * number), None
    if kind in ("percentage", "decimal"):
        return 0.0125, None
    if kind == "integer":
        return float(1 + number % 9), None
    if kind == "boolean":
        return None, "false" if number % 2 else "true"
    if kind == "date":
        return None, "2026-12-31"
    if kind == "enumeration":
        options = pack.enumerations[metric.enumeration or ""]
        return None, options[number % len(options)]
    return None, f"text {number}"


def _context(name: str, members: tuple[tuple[str, str], ...]) -> str:
    scenario = "".join(
        f'<xbrldi:explicitMember dimension="{dimension}">{member}</xbrldi:explicitMember>'
        for dimension, member in members
    )
    return (
        f'  <xbrli:context id="{name}">'
        f'<xbrli:entity><xbrli:identifier scheme="{_LEI_SCHEME}">{VALID_LEI}</xbrli:identifier>'
        "</xbrli:entity>"
        f"<xbrli:period><xbrli:instant>{_INSTANT}</xbrli:instant></xbrli:period>"
        + (f"<xbrli:scenario>{scenario}</xbrli:scenario>" if scenario else "")
        + "</xbrli:context>"
    )
