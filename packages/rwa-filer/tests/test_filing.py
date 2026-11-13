"""
The filing package: when a return is written, what is written, and what is recorded.

The synthetic module has no packaged rule set, so on it only the structure
checks can stop a return; the rule gate is exercised by handing ``build_filing``
a small rule set of its own.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from filer_builders import build_rule
from pack_builders import VALID_LEI, build_pack, build_return
from rwa_filer import filing
from rwa_filer.filing import (
    BLOCKED_BY_RULES,
    BLOCKED_BY_STRUCTURE,
    build_filing,
    default_name,
)
from rwa_filer.model import CanonicalReturn
from rwa_filer.rules.catalogue import FRAMEWORK_BASEL_3_1, RuleSet
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.checker import Finding
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import InstanceOptions

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value"]
BASE = f"{VALID_LEI}_TST001_2027-03-31"


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def ret(*rows: tuple[object, ...]) -> CanonicalReturn:
    padded = [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"))


SOUND = (
    ("T01.00.01.01", None, None, "0010", "0010", 100.0),
    ("T01.00.01.01", None, None, "0020", "0010", 60.0),
    ("T01.00.01.01", None, None, "0030", "0010", 40.0),
)


def test_a_sound_return_is_written_with_its_manifest(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path / "out", pack=pack)

    # Assert
    assert package.written and package.blocked_by is None
    assert package.instance_path == tmp_path / "out" / f"{BASE}.xbrl"
    assert package.manifest_path == tmp_path / "out" / f"{BASE}.manifest.json"
    assert package.zip_path is None and package.upload_path == package.instance_path
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == [
        f"{BASE}.manifest.json",
        f"{BASE}.xbrl",
    ]


def test_the_written_instance_is_the_return(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path, pack=pack)
    assert package.instance_path is not None
    back = read_instance(package.instance_path, pack=pack)

    # Assert
    assert back.findings == ()
    assert back.ret.facts.sort("row")["value"].to_list() == [100.0, 60.0, 40.0]


def test_the_manifest_records_what_was_filed_and_under_which_verdict(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path, pack=pack)
    assert package.manifest_path is not None and package.instance_path is not None
    manifest = json.loads(package.manifest_path.read_text())
    content = package.instance_path.read_bytes()

    # Assert — the checksum is of the bytes on disk.
    assert manifest["instance"] == {
        "file": f"{BASE}.xbrl",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "facts": 3,
        "cells": 3,
        "contexts": 4,
        "filing_indicators": ["T01.00.01"],
        "monetary_decimals": -3,
        "percentage_decimals": 4,
    }
    assert manifest["taxonomy"] == {
        "module": "TST001",
        "version": "1.0.0",
        "entry_point": pack.info.entry_point,
    }
    assert manifest["upload"] == f"{BASE}.xbrl" and manifest["zip"] is None
    assert manifest["validation"]["submittable"] is True
    assert manifest["created_at"] is None
    assert manifest["header"]["Entity identifier"] == VALID_LEI


def test_building_twice_gives_identical_files(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Act
    first = build_filing(ret(*SOUND), tmp_path / "a", pack=pack, always_zip=True)
    second = build_filing(ret(*SOUND), tmp_path / "b", pack=pack, always_zip=True)

    # Assert — instance, zip and manifest, byte for byte.
    for one, two in (
        (first.instance_path, second.instance_path),
        (first.zip_path, second.zip_path),
        (first.manifest_path, second.manifest_path),
    ):
        assert one is not None and two is not None
        assert one.read_bytes() == two.read_bytes()


def test_a_creation_time_is_recorded_in_the_instance_and_the_manifest(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange
    options = InstanceOptions(created_at=datetime(2027, 4, 20, 9, 30, tzinfo=UTC))

    # Act
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, options=options)
    assert package.manifest_path is not None and package.instance_path is not None

    # Assert
    assert (
        json.loads(package.manifest_path.read_text())["created_at"] == "2027-04-20T09:30:00+00:00"
    )
    assert b'creationdate="2027-04-20T09:30:00+00:00"' in package.instance_path.read_bytes()


# ---------------------------------------------------------------------------
# The zip
# ---------------------------------------------------------------------------


def test_a_zip_on_request_holds_the_instance_and_nothing_else(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, always_zip=True)
    assert package.zip_path is not None and package.instance_path is not None

    # Assert — the member keeps the .xbrl extension (Filing Manual rule 1.1).
    with zipfile.ZipFile(package.zip_path) as archive:
        assert archive.namelist() == [f"{BASE}.xbrl"]
        assert archive.read(f"{BASE}.xbrl") == package.instance_path.read_bytes()
    assert package.upload_path == package.zip_path


def test_an_instance_over_the_threshold_is_zipped_unasked(
    pack: TaxonomyPack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Filing Manual requires a zip above 10 MB; the threshold is lowered to test it."""
    # Arrange
    monkeypatch.setattr(filing, "ZIP_THRESHOLD_BYTES", 100)

    # Act
    package = build_filing(ret(*SOUND), tmp_path, pack=pack)
    assert package.manifest_path is not None

    # Assert
    assert package.zip_path is not None
    manifest = json.loads(package.manifest_path.read_text())
    assert manifest["upload"] == f"{BASE}.zip"
    assert manifest["zip"]["sha256"] == hashlib.sha256(package.zip_path.read_bytes()).hexdigest()


def test_the_threshold_is_the_filing_manuals_ten_megabytes() -> None:
    assert filing.ZIP_THRESHOLD_BYTES == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# What stops a return being written
# ---------------------------------------------------------------------------


def test_a_structure_finding_always_stops_the_file(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange — a figure in a greyed cell.
    broken = ret(*SOUND, ("T01.00.01.01", None, None, "0030", "0020", 0.5))

    # Act — even when asked to write regardless.
    package = build_filing(broken, tmp_path / "out", pack=pack, allow_rule_breaks=True)

    # Assert — nothing on disk at all.
    assert not package.written and package.blocked_by == BLOCKED_BY_STRUCTURE
    assert not (tmp_path / "out").exists()
    assert [finding.code for finding in package.validation.structure] == ["STR002"]


def test_a_broken_rule_stops_the_file_unless_overridden(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange — total 100 against parts of 60 + 30.
    wrong = ret(
        ("T01.00.01.01", None, None, "0010", "0010", 100.0),
        ("T01.00.01.01", None, None, "0020", "0010", 60.0),
        ("T01.00.01.01", None, None, "0030", "0010", 30.0),
    )
    footing = build_rule(
        rule_id="tst_b0001",
        publisher="BoE",
        framework=FRAMEWORK_BASEL_3_1,
        tables=("T01.00.01.01",),
        expression="{r0010} = {r0020} + {r0030}",
    )
    rules = RuleSet(framework=FRAMEWORK_BASEL_3_1, publisher="BoE", source={}, rules=(footing,))

    # Act
    stopped = build_filing(wrong, tmp_path / "stopped", pack=pack, ruleset=rules)
    forced = build_filing(
        wrong, tmp_path / "forced", pack=pack, ruleset=rules, allow_rule_breaks=True
    )

    # Assert
    assert not stopped.written and stopped.blocked_by == BLOCKED_BY_RULES
    assert not (tmp_path / "stopped").exists()
    assert forced.written and not forced.validation.is_submittable
    assert forced.manifest_path is not None
    recorded = json.loads(forced.manifest_path.read_text())["validation"]
    assert recorded["submittable"] is False
    assert [finding["code"] for finding in recorded["findings"]] == ["VAL001"]


def test_findings_from_reading_the_source_stop_the_file(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange — a sound return, but its source held something unreadable.
    stray = Finding("XBR001", "ERROR", "1 fact(s) are not data points", "ref", "TST001", "", "")

    # Act
    package = build_filing(ret(*SOUND), tmp_path / "out", pack=pack, source_findings=[stray])

    # Assert
    assert package.blocked_by == BLOCKED_BY_STRUCTURE
    assert package.validation.structure[0] is stray


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_a_name_may_be_given(pack: TaxonomyPack, tmp_path: Path) -> None:
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, name="q1-return")

    assert package.instance_path == tmp_path / "q1-return.xbrl"


def test_the_default_name_is_safe_as_a_file_name() -> None:
    # Arrange — an identifier under a scheme that allows punctuation.
    sample = build_return(
        pl.DataFrame({"table": ["T"], "row": ["1"], "column": ["1"], "value": [1.0]}),
        entity_identifier="12/34 56",
        module="TST-001",
    )

    # Act / Assert
    assert default_name(sample) == "123456_TST001_2027-03-31"
