"""
The XBRL writer: one fact per data point, in the form the Filing Manual requires.

Every assertion is about the written bytes, parsed back with the standard XML
library — not about the writer's own intermediate state — against the small
synthetic pack, where each case can be read at a glance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import polars as pl
import pytest

from pack_builders import build_pack, build_return
from rwa_filer.model import DECIMALS_EXACT, CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.xbrl.writer import (
    BASE_CONTEXT,
    NS_FIND,
    NS_LINK,
    NS_XBRLDI,
    NS_XBRLI,
    NS_XLINK,
    InstanceOptions,
    UnwritableReturnError,
    lexical,
    write_instance,
)

NS = {"xbrli": NS_XBRLI, "xbrldi": NS_XBRLDI, "find": NS_FIND, "link": NS_LINK}
MET = "{http://example.test/xbrl/dict/met}"
COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def ret(*rows: tuple[object, ...], **header: object) -> CanonicalReturn:
    padded = [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"), **header)


def parse(content: bytes) -> ElementTree.Element:
    return ElementTree.fromstring(content)


def facts_of(root: ElementTree.Element) -> list[ElementTree.Element]:
    return [child for child in root if child.get("contextRef") and child.tag.startswith(MET)]


def members(root: ElementTree.Element, context: str) -> dict[str, str]:
    node = root.find(f"xbrli:context[@id='{context}']", NS)
    assert node is not None
    explicit = {
        m.get("dimension", ""): m.text or "" for m in node.iter(f"{{{NS_XBRLDI}}}explicitMember")
    }
    typed = {
        m.get("dimension", ""): f"{next(iter(m)).tag}={next(iter(m)).text}"
        for m in node.iter(f"{{{NS_XBRLDI}}}typedMember")
    }
    return explicit | typed


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def test_the_file_is_utf8_with_an_upper_case_declaration_and_one_schema_ref(
    pack: TaxonomyPack,
) -> None:
    # Act
    content = write_instance(ret(("T01.00.01.01", None, None, "0010", "0010", 5.0)), pack).content
    root = parse(content)

    # Assert — the declaration is spelt UTF-8: a lower-case one draws a false
    # encoding error from the reference XBRL processor's filing checks.
    assert content.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<?instance-generator ')
    refs = root.findall("link:schemaRef", NS)
    assert [ref.get(f"{{{NS_XLINK}}}href") for ref in refs] == [pack.info.entry_point]


def test_the_same_return_always_gives_the_same_bytes(pack: TaxonomyPack) -> None:
    # Arrange — the same facts, supplied in two different orders.
    rows = [
        ("T02.00.01.01", "0002", None, "0010", "0010", 7.0),
        ("T01.00.01.01", None, None, "0010", "0010", 5.0),
        ("T02.00.01.01", "0001", None, "0010", "0010", 6.0),
    ]

    # Act
    first = write_instance(ret(*rows), pack).content
    second = write_instance(ret(*reversed(rows)), pack).content

    # Assert
    assert first == second


def test_a_creation_time_is_written_only_when_given(pack: TaxonomyPack) -> None:
    # Arrange
    sample = ret(("T01.00.01.01", None, None, "0010", "0010", 5.0))
    stamped = InstanceOptions(created_at=datetime(2027, 4, 20, 9, 30, tzinfo=UTC))

    # Act
    plain = write_instance(sample, pack).content
    dated = write_instance(sample, pack, options=stamped).content

    # Assert
    assert b"creationdate" not in plain
    assert b'creationdate="2027-04-20T09:30:00+00:00"' in dated


def test_every_context_names_the_one_entity_and_the_one_date(pack: TaxonomyPack) -> None:
    # Act
    root = parse(
        write_instance(
            ret(
                ("T01.00.01.01", None, None, "0010", "0010", 5.0),
                ("T02.00.01.01", "0001", None, "0010", "0010", 6.0),
            ),
            pack,
        ).content
    )
    contexts = root.findall("xbrli:context", NS)

    # Assert
    identifiers = {
        (node.get("scheme"), node.text) for node in root.iter(f"{{{NS_XBRLI}}}identifier")
    }
    assert identifiers == {("http://standards.iso.org/iso/17442", "5493001KJTIIGC8Y1R12")}
    assert {node.text for node in root.iter(f"{{{NS_XBRLI}}}instant")} == {"2027-03-31"}
    assert not list(root.iter(f"{{{NS_XBRLI}}}segment"))
    assert len(contexts) == 3  # the dimensionless one, and one per data point


def test_no_namespace_is_declared_that_the_file_does_not_use(pack: TaxonomyPack) -> None:
    # Act — one monetary fact with one explicit member.
    text = write_instance(
        ret(("T01.00.01.01", None, None, "0010", "0010", 5.0)), pack
    ).content.decode()
    declared = set(__import__("re").findall(r'xmlns:(\w+)="', text))

    # Assert
    assert declared == {
        "xbrli",
        "link",
        "xlink",
        "find",
        "xbrldi",
        "iso4217",
        "tst_met",
        "tst_dim",
        "tst_BA",
    }


# ---------------------------------------------------------------------------
# Facts and their contexts
# ---------------------------------------------------------------------------


def test_a_fact_is_its_metric_in_the_context_of_its_data_points_members(
    pack: TaxonomyPack,
) -> None:
    # Act
    root = parse(
        write_instance(ret(("T02.00.01.01", "0002", None, "0020", "0010", 7.0)), pack).content
    )
    (fact,) = facts_of(root)

    # Assert
    assert fact.tag == f"{MET}mi3"
    assert members(root, fact.get("contextRef", "")) == {"tst_dim:EXC": "tst_EC:x2"}


def test_an_open_sheet_member_fills_the_dimension_the_data_point_leaves_open(
    pack: TaxonomyPack,
) -> None:
    # Act — the open key may be given as a local name or as a full QName.
    root = parse(
        write_instance(
            ret(
                ("T03.00.01.01", None, "GB", "0010", "0010", 70.0),
                ("T03.00.01.01", None, "eba_GA:FR", "0010", "0010", 30.0),
            ),
            pack,
        ).content
    )

    # Assert
    written = sorted(
        members(root, fact.get("contextRef", ""))["eba_dim:CEG"] for fact in facts_of(root)
    )
    assert written == ["eba_GA:FR", "eba_GA:GB"]


def test_an_optional_open_dimension_is_absent_for_the_all_sheet(pack: TaxonomyPack) -> None:
    # Act — no open key is the "all lending" sheet; x1 is one type of it.
    root = parse(
        write_instance(
            ret(
                ("T07.00.01.01", None, None, "0010", "0010", 100.0),
                ("T07.00.01.01", None, "x1", "0010", "0010", 40.0),
            ),
            pack,
        ).content
    )
    by_value = {fact.text: fact.get("contextRef", "") for fact in facts_of(root)}

    # Assert — the dimensionless fact shares the filing indicators' context.
    assert by_value["100"] == BASE_CONTEXT
    assert members(root, by_value["40"]) == {"tst_dim:TSL": "tst_TA:x1"}


def test_an_open_rows_key_becomes_a_typed_member_and_is_not_itself_a_fact(
    pack: TaxonomyPack,
) -> None:
    # Act
    root = parse(
        write_instance(
            ret(
                ("T04.00.01.01", None, None, "a", "0005", 3.0),
                ("T04.00.01.01", None, None, "a", "0010", 500.0),
                ("T04.00.01.01", None, None, "a", "0020", 12.0),
            ),
            pack,
        ).content
    )
    facts = facts_of(root)

    # Assert — two facts (exposure, obligors); the key 3 is their typed member.
    assert sorted(fact.tag for fact in facts) == [f"{MET}ii1", f"{MET}mi6"]
    assert {fact.get("contextRef") for fact in facts} == {"c1"}
    assert members(root, "c1") == {"tst_dim:OGR": "{http://example.test/xbrl/dict/typ}ID=3"}


def test_a_data_point_shown_in_two_tables_is_written_once(pack: TaxonomyPack) -> None:
    # Act
    instance = write_instance(
        ret(
            ("T05.00.01.01", None, None, "0010", "0010", 9.0),
            ("T05.00.01.02", None, None, "0010", "0010", 9.0),
        ),
        pack,
    )

    # Assert
    assert (instance.facts, instance.cells) == (1, 2)
    assert len(facts_of(parse(instance.content))) == 1


def test_no_context_is_written_twice_or_left_unused(pack: TaxonomyPack) -> None:
    # Act — two metrics sharing one set of members share one context.
    root = parse(
        write_instance(
            ret(
                ("T01.00.01.01", None, None, "0010", "0010", 5.0),
                ("T01.00.01.01", None, None, "0010", "0020", 0.25),
                ("T01.00.01.01", None, None, "0010", "0030", None, "note"),
            ),
            pack,
        ).content
    )
    ids = [node.get("id") for node in root.findall("xbrli:context", NS)]
    used = {fact.get("contextRef") for fact in facts_of(root)} | {
        node.get("contextRef") for node in root.iter(f"{{{NS_FIND}}}filingIndicator")
    }

    # Assert
    assert ids == [BASE_CONTEXT, "c1"] and set(ids) == used


# ---------------------------------------------------------------------------
# Numbers, units and text
# ---------------------------------------------------------------------------


def test_numbers_carry_decimals_and_a_unit_and_text_carries_neither(pack: TaxonomyPack) -> None:
    # Act
    root = parse(
        write_instance(
            ret(
                ("T01.00.01.01", None, None, "0010", "0010", 1234567.891),
                ("T01.00.01.01", None, None, "0010", "0020", 0.0931),
                ("T01.00.01.01", None, None, "0010", "0030", None, "a < b & c"),
                ("T04.00.01.01", None, None, "a", "0005", 1.0),
                ("T04.00.01.01", None, None, "a", "0020", 12.0),
            ),
            pack,
        ).content
    )
    by_metric = {fact.tag.removeprefix(MET): fact for fact in facts_of(root)}
    units = {
        node.get("id"): node.findtext("xbrli:measure", namespaces=NS)
        for node in root.findall("xbrli:unit", NS)
    }

    # Assert
    assert by_metric["mi1"].attrib | {"text": by_metric["mi1"].text} == {
        "contextRef": "c1",
        "decimals": "-3",
        "unitRef": "uGBP",
        "text": "1234567.89",
    }
    assert by_metric["pi1"].attrib | {"text": by_metric["pi1"].text} == {
        "contextRef": "c1",
        "decimals": "4",
        "unitRef": "upure",
        "text": "0.0931",
    }
    assert by_metric["ii1"].get("decimals") == "0" and by_metric["ii1"].text == "12"
    assert by_metric["si1"].attrib == {"contextRef": "c1"} and by_metric["si1"].text == "a < b & c"
    assert units == {"uGBP": "iso4217:GBP", "upure": "xbrli:pure"}
    assert not any("precision" in fact.attrib for fact in by_metric.values())


def test_a_facts_own_decimals_wins_and_exact_is_written_as_inf(pack: TaxonomyPack) -> None:
    # Act
    root = parse(
        write_instance(
            ret(
                ("T01.00.01.01", None, None, "0010", "0010", 5.0, None, 2),
                ("T01.00.01.01", None, None, "0020", "0010", 6.0, None, DECIMALS_EXACT),
                ("T01.00.01.01", None, None, "0010", "0020", 0.5, None, 2),
            ),
            pack,
            options=InstanceOptions(monetary_decimals=-6),
        ).content
    )
    stated = {fact.text: fact.get("decimals") for fact in facts_of(root)}

    # Assert — a percentage is never stated to fewer than four places.
    assert stated == {"5": "2", "6": "INF", "0.5": "4"}


def test_the_reporting_currency_names_the_monetary_unit(pack: TaxonomyPack) -> None:
    root = parse(
        write_instance(
            ret(("T01.00.01.01", None, None, "0010", "0010", 5.0), currency="EUR"), pack
        ).content
    )

    assert root.find("xbrli:unit", NS).get("id") == "uEUR"  # type: ignore[union-attr]


def test_booleans_dates_and_enumerations_are_written_in_their_lexical_form(
    pack: TaxonomyPack,
) -> None:
    # Act — the enumeration member is given by local name and written qualified.
    text = write_instance(
        ret(
            ("T06.00.01.01", None, None, "0010", "0010", None, "TRUE"),
            ("T06.00.01.01", None, None, "0010", "0020", None, "2027-03-31"),
            ("T06.00.01.01", None, None, "0010", "0030", None, "x2"),
        ),
        pack,
    ).content.decode()

    # Assert
    assert '<tst_met:bi1 contextRef="c0">true</tst_met:bi1>' in text
    assert '<tst_met:di1 contextRef="c0">2027-03-31</tst_met:di1>' in text
    assert '<tst_met:ei1 contextRef="c0">tst_ZZ:x2</tst_met:ei1>' in text
    assert 'xmlns:tst_ZZ="http://example.test/xbrl/dict/dom/ZZ"' in text


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [
        (1234567.891, 2, "1234567.89"),
        (100.0, 2, "100"),
        (0.125, 2, "0.12"),  # half to even
        (0.135, 2, "0.14"),
        (-0.001, 2, "0"),  # never "-0"
        (1e-7, 6, "0"),
        (1e15, 2, "1000000000000000"),  # never an exponent
        (0.0931, 6, "0.0931"),
        (12.0, 0, "12"),
    ],
)
def test_a_number_is_written_in_plain_decimal_notation(
    value: float, places: int, expected: str
) -> None:
    assert lexical(value, places) == expected


# ---------------------------------------------------------------------------
# Filing indicators
# ---------------------------------------------------------------------------


def indicators(root: ElementTree.Element) -> dict[str, str]:
    return {
        node.text or "": node.get(f"{{{NS_FIND}}}filed", "true")
        for node in root.iter(f"{{{NS_FIND}}}filingIndicator")
    }


def test_every_template_with_a_fact_is_declared_reported_and_no_other(pack: TaxonomyPack) -> None:
    # Act — T05's two tables share one filing indicator.
    instance = write_instance(
        ret(
            ("T01.00.01.01", None, None, "0010", "0010", 5.0),
            ("T05.00.01.01", None, None, "0010", "0010", 9.0),
            ("T05.00.01.02", None, None, "0010", "0010", 9.0),
        ),
        pack,
    )
    root = parse(instance.content)

    # Assert
    assert indicators(root) == {"T01.00.01": "true", "T05.00.01": "true"}
    assert instance.filing_indicators == ("T01.00.01", "T05.00.01")
    assert {n.get("contextRef") for n in root.iter(f"{{{NS_FIND}}}filingIndicator")} == {
        BASE_CONTEXT
    }


def test_unreported_templates_can_be_declared_as_such(pack: TaxonomyPack) -> None:
    # Act
    root = parse(
        write_instance(
            ret(("T01.00.01.01", None, None, "0010", "0010", 5.0)),
            pack,
            options=InstanceOptions(declare_unreported=True),
        ).content
    )
    declared = indicators(root)

    # Assert
    assert declared["T01.00.01"] == "true"
    assert {code for code, filed in declared.items() if filed == "false"} == set(
        pack.filing_indicators
    ) - {"T01.00.01"}


def test_declared_indicators_are_written_as_declared(pack: TaxonomyPack) -> None:
    """A template may be reported with no facts: every cell is then zero to the regulator."""
    # Arrange
    base = ret(("T01.00.01.01", None, None, "0010", "0010", 5.0))
    declared = CanonicalReturn(
        base.header, base.facts, {"T01.00.01": True, "T02.00.01": True, "T03.00.01": False}
    )

    # Act
    root = parse(write_instance(declared, pack).content)

    # Assert
    assert indicators(root) == {"T01.00.01": "true", "T02.00.01": "true", "T03.00.01": "false"}


# ---------------------------------------------------------------------------
# What the writer refuses
# ---------------------------------------------------------------------------


def test_a_return_with_a_structure_finding_is_not_written(pack: TaxonomyPack) -> None:
    # Arrange — a figure in a cell the taxonomy greys.
    broken = ret(("T01.00.01.01", None, None, "0030", "0020", 0.5))

    # Act / Assert
    with pytest.raises(UnwritableReturnError, match="STR002"):
        write_instance(broken, pack)


def test_percentages_may_not_be_stated_to_fewer_than_four_places() -> None:
    with pytest.raises(ValueError, match="at least 4"):
        InstanceOptions(percentage_decimals=2)
