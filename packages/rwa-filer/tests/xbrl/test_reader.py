"""
The XBRL reader: an instance, from this package or any other, back into cells.

Two kinds of test. The round trips write a return with the package's own writer
and read it back — what goes in must come out, cell for cell. The hand-written
instances pin what a file from ANOTHER system may legitimately look like
(different prefixes, a different context order) and what the reader must report
rather than drop.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import polars as pl
import pytest

from pack_builders import VALID_LEI, build_pack, build_return
from rwa_filer.model import CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.reader import (
    FINDING_FACT_NOT_INDICATED,
    FINDING_FILING_RULE,
    FINDING_UNKNOWN_DATAPOINT,
    InstanceFormatError,
    read_instance,
)
from rwa_filer.xbrl.writer import InstanceOptions, write_instance

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
COORDINATES = ["table", "sheet", "open_key", "row", "column"]

ENTRY_POINT = "http://example.test/xbrl/fws/test/2027-01-01/mod/tst001.xsd"

#: A hand-written instance in ANOTHER system's style: its own prefixes (``m``,
#: ``d``, ``ba``), the filing indicators first, a context named freely.
FOREIGN_INSTANCE = f"""<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:fi="http://www.eurofiling.info/xbrl/ext/filing-indicators"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:m="http://example.test/xbrl/dict/met"
      xmlns:d="http://example.test/xbrl/dict/dim"
      xmlns:ba="http://example.test/xbrl/dict/dom/BA">
  <link:schemaRef xlink:type="simple" xlink:href="{ENTRY_POINT}"/>
  <context id="plain">
    <entity><identifier scheme="http://standards.iso.org/iso/17442">{VALID_LEI}</identifier></entity>
    <period><instant>2027-03-31</instant></period>
  </context>
  <fi:fIndicators>
    <fi:filingIndicator contextRef="plain">T01.00.01</fi:filingIndicator>
    <fi:filingIndicator contextRef="plain" fi:filed="false">T02.00.01</fi:filingIndicator>
  </fi:fIndicators>
  <context id="total">
    <entity><identifier scheme="http://standards.iso.org/iso/17442">{VALID_LEI}</identifier></entity>
    <period><instant>2027-03-31</instant></period>
    <scenario><xbrldi:explicitMember dimension="d:BAS">ba:x1</xbrldi:explicitMember></scenario>
  </context>
  <unit id="pounds"><measure>iso4217:GBP</measure></unit>
  <m:mi1 contextRef="total" unitRef="pounds" decimals="0">1500</m:mi1>
EXTRA
</xbrl>
"""


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def ret(*rows: tuple[object, ...]) -> CanonicalReturn:
    padded = [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"))


def foreign(extra: str = "") -> bytes:
    return FOREIGN_INSTANCE.replace("EXTRA", extra).encode("utf-8")


def cells(reading_or_return: object) -> list[tuple[object, ...]]:
    source = getattr(reading_or_return, "ret", reading_or_return)
    return source.facts.select(*COORDINATES, "value", "text_value").sort(COORDINATES).rows()  # type: ignore[union-attr]


def codes(findings: tuple) -> list[str]:
    return [finding.code for finding in findings]


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------

EVERYTHING = (
    ("T01.00.01.01", None, None, "0010", "0010", 1234567.89),
    ("T01.00.01.01", None, None, "0010", "0020", 0.0931),
    ("T01.00.01.01", None, None, "0010", "0030", None, "a < b & c"),
    ("T02.00.01.01", "0001", None, "0010", "0010", 6.0),
    ("T02.00.01.01", "0002", None, "0020", "0010", 7.0),
    ("T03.00.01.01", None, "GB", "0010", "0010", 70.0),
    ("T03.00.01.01", None, "x1", "0010", "0010", 100.0),
    ("T04.00.01.01", None, None, "3", "0005", None, "3"),
    ("T04.00.01.01", None, None, "3", "0010", 500.0),
    ("T04.00.01.01", None, None, "3", "0020", 12.0),
    ("T04.00.01.01", None, None, "8", "0005", None, "8"),
    ("T04.00.01.01", None, None, "8", "0010", 250.0),
    ("T05.00.01.01", None, None, "0010", "0010", 9.0),
    ("T05.00.01.02", None, None, "0010", "0010", 9.0),
    ("T06.00.01.01", None, None, "0010", "0010", None, "true"),
    ("T06.00.01.01", None, None, "0010", "0020", None, "2027-03-31"),
    ("T06.00.01.01", None, None, "0010", "0030", None, "tst_ZZ:x2"),
    ("T07.00.01.01", None, None, "0010", "0010", 100.0),
    ("T07.00.01.01", None, "x1", "0010", "0010", 40.0),
)


def test_a_written_return_reads_back_cell_for_cell(pack: TaxonomyPack) -> None:
    """Every kind of cell the pack has: sheets, open axes, open rows, shared, typed."""
    # Arrange
    original = ret(*EVERYTHING)

    # Act
    reading = read_instance(write_instance(original, pack).content, pack=pack)

    # Assert
    assert reading.findings == ()
    assert cells(reading) == cells(original)
    assert reading.ret.header == original.header
    assert check_structure(reading.ret, pack) == []


def test_reading_and_rewriting_an_instance_gives_the_same_bytes(pack: TaxonomyPack) -> None:
    # Arrange
    first = write_instance(ret(*EVERYTHING), pack).content

    # Act
    second = write_instance(read_instance(first, pack=pack).ret, pack).content

    # Assert
    assert second == first


def test_decimals_and_filing_indicators_survive_the_round_trip(pack: TaxonomyPack) -> None:
    # Arrange
    base = ret(
        ("T01.00.01.01", None, None, "0010", "0010", 5.0, None, 2),
        ("T01.00.01.01", None, None, "0020", "0010", 6.0),
    )
    declared = CanonicalReturn(base.header, base.facts, {"T01.00.01": True, "T02.00.01": False})

    # Act
    reading = read_instance(
        write_instance(declared, pack, options=InstanceOptions(monetary_decimals=-6)).content,
        pack=pack,
    )

    # Assert
    assert reading.ret.indicators == {"T01.00.01": True, "T02.00.01": False}
    assert reading.ret.facts.sort("row")["decimals"].to_list() == [2, -6]


def test_a_data_point_shown_in_two_reported_tables_is_placed_in_both(pack: TaxonomyPack) -> None:
    """One fact in the file; the rules of both tables read it."""
    # Arrange — only the first view is supplied; both share filing indicator T05.00.01.
    original = ret(("T05.00.01.01", None, None, "0010", "0010", 9.0))

    # Act
    reading = read_instance(write_instance(original, pack).content, pack=pack)

    # Assert
    assert [row[0] for row in cells(reading)] == ["T05.00.01.01", "T05.00.01.02"]


def test_a_zipped_instance_is_read_the_same(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange
    content = write_instance(ret(("T01.00.01.01", None, None, "0010", "0010", 5.0)), pack).content
    path = tmp_path / "filing.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("filing.xbrl", content)

    # Act
    reading = read_instance(path, pack=pack)

    # Assert
    assert cells(reading) == [("T01.00.01.01", None, None, "0010", "0010", 5.0, None)]


# ---------------------------------------------------------------------------
# An instance from another system
# ---------------------------------------------------------------------------


def test_a_file_with_its_own_prefixes_and_ordering_is_read(pack: TaxonomyPack) -> None:
    # Act
    reading = read_instance(foreign(), pack=pack)

    # Assert
    assert reading.findings == ()
    assert cells(reading) == [("T01.00.01.01", None, None, "0010", "0010", 1500.0, None)]
    assert reading.ret.indicators == {"T01.00.01": True, "T02.00.01": False}
    assert (reading.ret.header.entity_identifier, reading.ret.header.currency) == (VALID_LEI, "GBP")
    assert reading.ret.facts["decimals"].to_list() == [0]


def test_a_fact_that_is_no_data_point_of_the_module_is_reported(pack: TaxonomyPack) -> None:
    # Arrange — mi1 exists, but not with member x9.
    extra = """
  <context id="odd">
    <entity><identifier scheme="http://standards.iso.org/iso/17442">X</identifier></entity>
    <period><instant>2027-03-31</instant></period>
    <scenario><xbrldi:explicitMember dimension="d:BAS">ba:x9</xbrldi:explicitMember></scenario>
  </context>
  <m:mi1 contextRef="odd" unitRef="pounds" decimals="0">1</m:mi1>"""

    # Act
    reading = read_instance(foreign(extra), pack=pack)

    # Assert — reported, and the good fact is still read.
    assert FINDING_UNKNOWN_DATAPOINT in codes(reading.findings)
    assert "tst_met:mi1[tst_dim:BAS=tst_BA:x9]" in reading.findings[-1].message
    assert len(cells(reading)) == 1


def test_a_fact_only_an_unreported_template_shows_is_reported(pack: TaxonomyPack) -> None:
    """Filing Manual rule 1.7.1: the regulator cannot tell whether the figure is meant."""
    # Arrange — mi7 is shown only by T05, which the file does not declare.
    extra = '\n  <m:mi7 contextRef="plain" unitRef="pounds" decimals="0">9</m:mi7>'

    # Act
    reading = read_instance(foreign(extra), pack=pack)

    # Assert
    assert codes(reading.findings) == [FINDING_FACT_NOT_INDICATED]
    assert "tst_met:mi7" in reading.findings[0].message
    assert len(cells(reading)) == 1


def test_the_same_fact_twice_is_one_fact_unless_the_values_differ(pack: TaxonomyPack) -> None:
    # Arrange
    same = '\n  <m:mi1 contextRef="total" unitRef="pounds" decimals="0">1500</m:mi1>'
    different = '\n  <m:mi1 contextRef="total" unitRef="pounds" decimals="0">1600</m:mi1>'

    # Act
    consistent = read_instance(foreign(same), pack=pack)
    inconsistent = read_instance(foreign(different), pack=pack)

    # Assert
    assert consistent.findings == () and len(cells(consistent)) == 1
    assert [(f.code, f.subject) for f in inconsistent.findings] == [(FINDING_FILING_RULE, "2.16")]


@pytest.mark.parametrize(
    ("extra", "rule"),
    [
        ('\n  <m:mi1 contextRef="total" unitRef="pounds" precision="4">1500</m:mi1>', "2.17"),
        ('\n  <m:mi1 contextRef="total" unitRef="pounds">1500</m:mi1>', "2.18"),
        ('\n  <m:mi1 contextRef="total" unitRef="missing" decimals="0">1500</m:mi1>', "2.21"),
        (
            f"""
  <context id="spare">
    <entity><identifier scheme="http://standards.iso.org/iso/17442">{VALID_LEI}</identifier></entity>
    <period><instant>2027-03-31</instant></period>
  </context>""",
            "2.7",
        ),
        (
            """
  <context id="other">
    <entity><identifier scheme="http://standards.iso.org/iso/17442">SOMEONE-ELSE</identifier></entity>
    <period><instant>2026-12-31</instant></period>
  </context>""",
            "2.9",
        ),
    ],
    ids=["precision", "no-decimals", "undefined-unit", "unused-context", "second-entity"],
)
def test_a_filing_manual_breach_the_reader_can_see_is_reported(
    pack: TaxonomyPack, extra: str, rule: str
) -> None:
    # Act
    reading = read_instance(foreign(extra), pack=pack)

    # Assert
    assert (FINDING_FILING_RULE, rule) in [(f.code, f.subject) for f in reading.findings]
    assert all(finding.is_blocking for finding in reading.findings)


# ---------------------------------------------------------------------------
# What is not an instance at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty|well-formed"),
        (b'<xbrl xmlns="http://www.xbrl.org/2003/instance"><open>', "well-formed"),
        (b"<root xmlns='urn:x'/>", "not xbrli:xbrl"),
        (
            b'<!DOCTYPE x [<!ENTITY a "aaaa">]><xbrl xmlns="http://www.xbrl.org/2003/instance"/>',
            "document type",
        ),
        (b'<xbrl xmlns="http://www.xbrl.org/2003/instance"/>', "exactly one taxonomy entry point"),
    ],
    ids=["empty", "malformed", "wrong-root", "doctype", "no-schema-ref"],
)
def test_a_file_that_is_not_a_readable_instance_is_refused(content: bytes, message: str) -> None:
    with pytest.raises(InstanceFormatError, match=message):
        read_instance(content)


def test_an_entry_point_no_packaged_taxonomy_has_is_refused() -> None:
    # Arrange — a well-formed instance for a taxonomy this package does not carry.
    with pytest.raises(InstanceFormatError, match="No packaged taxonomy has the entry point"):
        read_instance(foreign())


def test_a_zip_must_hold_exactly_one_instance() -> None:
    # Arrange
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.xbrl", "<x/>")
        archive.writestr("b.xbrl", "<x/>")

    # Act / Assert
    with pytest.raises(InstanceFormatError, match="exactly one .xbrl"):
        read_instance(buffer.getvalue())
