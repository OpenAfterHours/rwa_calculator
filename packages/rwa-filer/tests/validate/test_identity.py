"""
Evidence identity: every input of a verdict is fingerprinted, and the whole has one id.

What is pinned here is what each fingerprint DEPENDS on — the same input gives
the same digest, a changed input a changed one, and what is not an input (the
row order, the file the facts came in) moves nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01, book, ref, rule
from pack_builders import SAMPLE_MODULE, build_pack, build_return
from rwa_filer.boe.catalogue import available_rulebooks, canonical_sha256
from rwa_filer.boe.engine import Accuracy
from rwa_filer.release import resolve_release
from rwa_filer.validate.identity import facts_sha256, identity_record, source_identity
from rwa_filer.validate.returns import validate_return

ROWS = [
    (T01, None, None, "0010", "0010", 100.0, None),
    (T01, None, None, "0020", "0010", 60.0, None),
    (T01, None, None, "0030", "0010", 40.0, None),
]
SCHEMA = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}
FOOTING = rule(
    "tst_0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)


def _return(rows: list[tuple[object, ...]]):
    return build_return(pl.DataFrame(rows, schema=SCHEMA, orient="row"))


def test_the_facts_digest_ignores_row_order_and_follows_every_value() -> None:
    # Act
    forward = facts_sha256(_return(ROWS))
    backward = facts_sha256(_return(list(reversed(ROWS))))
    changed = facts_sha256(_return([*ROWS[:2], (T01, None, None, "0030", "0010", 41.0, None)]))

    # Assert
    assert forward == backward
    assert forward != changed


def test_the_facts_digest_of_awkward_numbers_and_text_is_pinned() -> None:
    """The digest feeds every ``evidence_id``: one byte written differently moves them all.

    The expected hex is the digest of exactly the lines written out below, as
    the package wrote them when this test was added: each number as Python's
    ``json`` writes a float (``1e-05``, ``1e+22``, ``-0.0``), each text as JSON
    escapes it, non-ASCII text as UTF-8 and not as ``\\u`` escapes.
    """
    # Arrange
    rows = [
        (T01, None, None, "0010", "0010", 1e-05, None, 2),
        (T01, None, None, "0010", "0020", 1e22, None, None),
        (T01, None, None, "0020", "0010", -0.0, None, 0),
        (T01, None, None, "0020", "0020", 0.1, None, None),
        (T01, None, None, "0010", "0030", None, 'a "quoted" word', None),
        (T01, None, None, "0020", "0030", None, "C:\\data\\return", None),
        (T01, None, None, "0030", "0030", None, "one\x01two", None),
        (T01, None, None, "0030", "0010", None, "Zürich – 東京", None),
    ]
    ret = build_return(pl.DataFrame(rows, schema={**SCHEMA, "decimals": pl.Int32}, orient="row"))
    values = ret.facts["value"].drop_nulls().to_list()
    assert values == [1e-05, 1e22, 0.0, 0.1], (
        "the return must still hold the awkward numbers, the sign of -0.0 included"
    )
    assert math.copysign(1.0, values[2]) == -1.0, (
        "the return must still hold the awkward numbers, the sign of -0.0 included"
    )
    assert "one\x01two" in ret.facts["text_value"].to_list(), "the control character must survive"
    lines = [
        '{"header":{"Currency":"GBP","Entity identifier":"5493001KJTIIGC8Y1R12",'
        '"Entity identifier scheme":"http://standards.iso.org/iso/17442","Module":"TST001",'
        '"Reference date":"2027-03-31"},"indicators":null}',
        '["T01.00.01.01",null,null,"0010","0010",1e-05,null,2]',
        '["T01.00.01.01",null,null,"0010","0020",1e+22,null,null]',
        '["T01.00.01.01",null,null,"0010","0030",null,"a \\"quoted\\" word",null]',
        '["T01.00.01.01",null,null,"0020","0010",-0.0,null,0]',
        '["T01.00.01.01",null,null,"0020","0020",0.1,null,null]',
        '["T01.00.01.01",null,null,"0020","0030",null,"C:\\\\data\\\\return",null]',
        '["T01.00.01.01",null,null,"0030","0010",null,"Zürich – 東京",null]',
        '["T01.00.01.01",null,null,"0030","0030",null,"one\\u0001two",null]',
    ]
    expected = "040f6c62e08cbce19f6128ff8f553cb9929e6e31fac97315e538c4cc82037bc0"
    assert hashlib.sha256("".join(f"{line}\n" for line in lines).encode()).hexdigest() == expected

    # Act
    digest = facts_sha256(ret)

    # Assert
    assert digest == expected


def test_the_evidence_id_follows_the_accuracy_but_not_the_source_file(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path / "pack")
    ret = _return(ROWS)
    first, second = tmp_path / "a.csv", tmp_path / "b.parquet"
    first.write_text("one")
    second.write_text("two")

    def identity(**options: object) -> dict[str, object]:
        return identity_record(ret, validate_return(ret, pack, rulebook=book(FOOTING), **options))

    # Act
    from_csv = identity(source=source_identity(first))
    from_parquet = identity(source=source_identity(second))
    at_units = identity(source=source_identity(first), accuracy=Accuracy(0, 4))

    # Assert
    assert from_csv["evidence_id"] == from_parquet["evidence_id"]
    assert from_csv["input"]["file_sha256"] != from_parquet["input"]["file_sha256"]
    assert (from_csv["input"]["file"], from_csv["input"]["format"]) == ("a.csv", "csv")
    assert at_units["evidence_id"] != from_csv["evidence_id"]
    assert at_units["settings"]["accuracy"] == {
        "monetary_decimals": 0,
        "percentage_decimals": 4,
        "source": "given",
    }
    assert from_csv["settings"]["accuracy"]["source"] == "default"


def test_the_pack_digest_covers_the_files_the_pack_was_loaded_from(tmp_path: Path) -> None:
    # Act
    same = build_pack(tmp_path / "one").content_sha256
    again = build_pack(tmp_path / "two").content_sha256
    other = build_pack(tmp_path / "three", valid_to=date(2030, 12, 31)).content_sha256

    # Assert
    assert same is not None and len(same) == 64
    assert same == again
    assert same != other


def test_a_packaged_rule_book_is_named_by_its_file_and_its_content() -> None:
    # Arrange
    release = resolve_release("PRA001")
    rulebook = release.rulebook
    assert rulebook is not None and rulebook.file in available_rulebooks()
    directory = Path(__file__).parents[2] / "src" / "rwa_filer" / "boe" / "data"
    payload = json.loads((directory / str(rulebook.file)).read_text(encoding="utf-8"))

    # Act
    record = identity_record(
        _return([]),
        validate_return(_return([]), release=release),
    )["rulebook"]

    # Assert
    assert rulebook.content_sha256 == canonical_sha256(payload)
    assert record["file"] == rulebook.file and record["sha256"] == rulebook.content_sha256
    assert record["workbook_sha256"] == payload["source"]["sha256"]
    assert record["formulas_package_sha256"] == payload["source"]["formulas"]["package_sha256"]
    assert record["rules_enforced"] == len(rulebook.enforced("PRA001"))


@pytest.mark.parametrize(
    "change",
    [
        {"expression": f"{ref(T01, '0010', '0010')} i>= 0"},
        {"severities": {SAMPLE_MODULE: "WARNING"}},
        {"scope": "scope({t: T01.00.01.01, c:0010, f: test, fv: test})"},
        # What a summed variable spans decides what the sum adds up.
        {"spans_by_variable": {"v1": frozenset({"tst_dim:OGR"})}},
    ],
)
def test_a_rule_fingerprint_changes_with_anything_that_changes_the_check(
    change: dict[str, object],
) -> None:
    # Act
    unchanged = rule("tst_0001", FOOTING.expression, tables=(T01,)).fingerprint(SAMPLE_MODULE)
    changed = rule("tst_0001", **{"expression": FOOTING.expression, **change}, tables=(T01,))

    # Assert
    assert unchanged == FOOTING.fingerprint(SAMPLE_MODULE)
    assert changed.fingerprint(SAMPLE_MODULE) != unchanged
