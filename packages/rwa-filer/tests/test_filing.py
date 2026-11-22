"""
The filing package: when a return is written, what is written, and what is recorded.

The synthetic module has no packaged rule book. Validating it without one is a
``VAL003`` (nothing but structure would have been checked), so each build here
is handed a small rule book of its own: ``SOUND`` satisfies ``FOOTING``.

A build validates and then writes, and the writer is handed the return the
validation has just found structurally sound: it does not check the structure a
second time (``xbrl.writer._write_checked``). What that rests on is pinned in
"What stops a return being written" and counted in "One structure check per
build". Mutation evidence, each probe one change, measured 2026-11-22:

- the build's own stop for a structure finding removed, so the unchecked writer
  is reached: red on ``test_a_structure_finding_always_stops_the_file``,
  ``test_findings_from_reading_the_source_stop_the_file``,
  ``test_a_blocked_build_still_writes_its_evidence``,
  ``test_the_writer_called_on_its_own_still_refuses_what_a_build_would_stop``
  and ``test_cli_build.py::test_build_refuses_a_structure_error_even_when_forced``;
- the public ``write_instance`` writing without acting on its check: red on
  ``xbrl/test_writer.py::test_a_return_with_a_structure_finding_is_not_written``
  and on ``test_the_writer_called_on_its_own_still_refuses_what_a_build_would_stop``;
- the build calling the public, checking writer again: red on
  ``test_a_build_checks_the_structure_once`` (2 checks, as before the change).
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from boe_builders import T01, book, ref, rule
from pack_builders import VALID_LEI, build_pack, build_return
from rwa_filer import filing
from rwa_filer.filing import (
    BLOCKED_BY_RULES,
    BLOCKED_BY_STRUCTURE,
    build_filing,
    default_name,
)
from rwa_filer.model import CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate import structure
from rwa_filer.validate.checker import Finding
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import InstanceOptions, UnwritableReturnError, write_instance

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

#: ``total = part one + part two`` on T01, which ``SOUND`` satisfies.
FOOTING = rule(
    "tst_b0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
RULES = book(FOOTING)


def test_a_sound_return_is_written_with_its_manifest(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path / "out", pack=pack, rulebook=RULES)

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
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, rulebook=RULES)
    assert package.instance_path is not None
    back = read_instance(package.instance_path, pack=pack)

    # Assert
    assert back.findings == ()
    assert back.ret.facts.sort("row")["value"].to_list() == [100.0, 60.0, 40.0]


def test_the_manifest_records_what_was_filed_and_under_which_verdict(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, rulebook=RULES)
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
        "status": manifest["taxonomy"]["status"],
        "applies_from": pack.info.valid_from.isoformat(),
        "applies_to": None,
        "run_date": manifest["taxonomy"]["run_date"],
        "chosen_by": "pack",
        "shipped": [],
        "covers_reference_date": True,
    }
    assert manifest["upload"] == f"{BASE}.xbrl" and manifest["zip"] is None
    assert manifest["validation"]["submittable"] is True
    assert manifest["created_at"] is None
    assert manifest["header"]["Entity identifier"] == VALID_LEI


def test_building_twice_gives_identical_files(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Act
    first = build_filing(ret(*SOUND), tmp_path / "a", pack=pack, rulebook=RULES, always_zip=True)
    second = build_filing(ret(*SOUND), tmp_path / "b", pack=pack, rulebook=RULES, always_zip=True)

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
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, rulebook=RULES, options=options)
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
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, rulebook=RULES, always_zip=True)
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
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, rulebook=RULES)
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


def test_a_module_no_rule_book_covers_is_not_written_unchecked(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    """With no rule book, only structure would have been checked: VAL003, like no rule run."""
    # Act
    package = build_filing(ret(*SOUND), tmp_path / "out", pack=pack)

    # Assert
    assert not package.written and package.blocked_by == BLOCKED_BY_RULES
    assert [finding.code for finding in package.validation.rules] == ["VAL003"]
    assert package.validation.rules[0].subject == "no_rulebook"


def test_a_broken_rule_stops_the_file_unless_overridden(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange — total 100 against parts of 60 + 30.
    wrong = ret(
        ("T01.00.01.01", None, None, "0010", "0010", 100.0),
        ("T01.00.01.01", None, None, "0020", "0010", 60.0),
        ("T01.00.01.01", None, None, "0030", "0010", 30.0),
    )
    footing = rule(
        "tst_b0001",
        f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )
    rules = book(footing)

    # Act
    exact = InstanceOptions(monetary_decimals=0)
    stopped = build_filing(wrong, tmp_path / "stopped", pack=pack, rulebook=rules, options=exact)
    forced = build_filing(
        wrong,
        tmp_path / "forced",
        pack=pack,
        rulebook=rules,
        options=exact,
        allow_rule_breaks=True,
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
    package = build_filing(
        ret(*SOUND), tmp_path / "out", pack=pack, rulebook=RULES, source_findings=[stray]
    )

    # Assert
    assert package.blocked_by == BLOCKED_BY_STRUCTURE
    assert package.validation.structure[0] is stray


# ---------------------------------------------------------------------------
# One structure check per build
# ---------------------------------------------------------------------------


def _structure_checks(monkeypatch: pytest.MonkeyPatch) -> list[CanonicalReturn]:
    """Count ``check_structure`` calls, in every module that has imported it.

    Each importer holds its own name for the function, so the count is put on
    all of them: a new call site in a module already loaded is counted too.
    """
    real = structure.check_structure
    checked: list[CanonicalReturn] = []

    def counting(ret: CanonicalReturn, *args: Any, **kwargs: Any) -> list[Finding]:
        checked.append(ret)
        return real(ret, *args, **kwargs)

    importers = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("rwa_filer") and getattr(module, "check_structure", None) is real
    ]
    assert {"rwa_filer.validate.returns", "rwa_filer.xbrl.writer"} <= {
        module.__name__ for module in importers
    }, "the validation and the writer must both be counted"
    for module in importers:
        monkeypatch.setattr(module, "check_structure", counting)
    return checked


@pytest.mark.parametrize("with_evidence", [False, True])
def test_a_build_checks_the_structure_once(
    with_evidence: bool, pack: TaxonomyPack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the count is live on the writer: called on its own, it checks.
    sound = ret(*SOUND)
    checked = _structure_checks(monkeypatch)
    write_instance(sound, pack)
    assert len(checked) == 1, "the writer's own check is not being counted"
    checked.clear()

    # Act
    package = build_filing(
        sound,
        tmp_path / "out",
        pack=pack,
        rulebook=RULES,
        evidence=tmp_path / "e.jsonl" if with_evidence else None,
    )

    # Assert
    assert package.written
    assert len(checked) == 1, f"{len(checked)} structure checks in one build"
    assert checked[0] is sound


def test_the_writer_called_on_its_own_still_refuses_what_a_build_would_stop(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange — a figure in a greyed cell, on top of a sound return.
    broken = ret(*SOUND, ("T01.00.01.01", None, None, "0030", "0020", 0.5))

    # Act
    package = build_filing(broken, tmp_path / "out", pack=pack, rulebook=RULES)

    # Assert — the build stops it, and so does the writer anyone else calls.
    assert package.blocked_by == BLOCKED_BY_STRUCTURE and not (tmp_path / "out").exists()
    with pytest.raises(UnwritableReturnError, match="1 structure finding"):
        write_instance(broken, pack)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_a_name_may_be_given(pack: TaxonomyPack, tmp_path: Path) -> None:
    package = build_filing(ret(*SOUND), tmp_path, pack=pack, rulebook=RULES, name="q1-return")

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


def test_validation_uses_the_accuracy_the_file_is_written_with(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    """A 10-unit gap: within rounding when stated to thousands, a break when stated to units.

    The file's ``decimals`` are what the gateway's comparisons allow for, so the
    validation that decides whether to write must use the same.
    """
    # Arrange — total 100 against parts of 60 + 30.
    wrong = ret(
        ("T01.00.01.01", None, None, "0010", "0010", 100.0),
        ("T01.00.01.01", None, None, "0020", "0010", 60.0),
        ("T01.00.01.01", None, None, "0030", "0010", 30.0),
    )
    footing = rule(
        "tst_b0001",
        f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )

    # Act
    thousands = build_filing(wrong, tmp_path / "a", pack=pack, rulebook=book(footing))
    units = build_filing(
        wrong,
        tmp_path / "b",
        pack=pack,
        rulebook=book(footing),
        options=InstanceOptions(monetary_decimals=0),
    )

    # Assert
    assert thousands.written and thousands.validation.is_submittable
    assert not units.written and units.blocked_by == BLOCKED_BY_RULES


def test_a_reference_date_outside_the_release_is_warned_of_and_still_built(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    """``STR011`` is about the release chosen: it never stops a build."""
    # Arrange — the pack applies from 2027-01-01.
    early = build_return(
        pl.DataFrame(
            [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in SOUND],
            schema=COLUMNS,
            orient="row",
        ),
        reference_date=pack.info.valid_from.replace(year=pack.info.valid_from.year - 1),
    )

    # Act
    package = build_filing(early, tmp_path / "out", pack=pack, rulebook=RULES)

    # Assert
    assert package.written and package.blocked_by is None
    assert [finding.code for finding in package.validation.release_findings] == ["STR011"]
    assert package.validation.structure == ()


# ---------------------------------------------------------------------------
# The evidence behind the verdict
# ---------------------------------------------------------------------------


def test_the_manifest_binds_the_evidence_the_build_wrote(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Act
    package = build_filing(
        ret(*SOUND), tmp_path / "out", pack=pack, rulebook=RULES, evidence=tmp_path / "e.jsonl"
    )

    # Assert — the manifest names the file by checksum, so a sign-off covers it.
    assert package.written and package.evidence is not None and package.manifest_path is not None
    manifest = json.loads(package.manifest_path.read_text())
    recorded = manifest["evidence"]
    assert recorded["file"] == "e.jsonl"
    assert recorded["sha256"] == hashlib.sha256((tmp_path / "e.jsonl").read_bytes()).hexdigest()
    assert recorded["evidence_id"] == manifest["identity"]["evidence_id"]
    assert manifest["validation"]["status"] == "CLEAN"


def test_a_blocked_build_still_writes_its_evidence(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange — a figure in a greyed cell: nothing may be written.
    broken = ret(*SOUND, ("T01.00.01.01", None, None, "0030", "0020", 0.5))

    # Act
    package = build_filing(
        broken, tmp_path / "out", pack=pack, rulebook=RULES, evidence=tmp_path / "e.jsonl.gz"
    )

    # Assert
    assert not package.written and package.blocked_by == BLOCKED_BY_STRUCTURE
    assert package.evidence is not None and package.evidence.records["structure_exception"] == 1


def test_a_build_without_evidence_records_none(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Act
    package = build_filing(ret(*SOUND), tmp_path / "out", pack=pack, rulebook=RULES)

    # Assert
    assert package.evidence is None and package.manifest_path is not None
    assert json.loads(package.manifest_path.read_text())["evidence"] is None


def test_the_manifest_carries_the_publisher_issue_labels(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    """A break a known issue explains is filed as it is, and the manifest says which issue."""
    # Arrange
    from dataclasses import replace

    from boe_builders import issue_register
    from rwa_filer.release import release_for_pack

    broken = ret(
        (T01, None, None, "0010", "0010", 100_000.0, None),
        (T01, None, None, "0020", "0010", 60_000.0, None),
        (T01, None, None, "0030", "0010", 30_000.0, None),
    )
    release = replace(release_for_pack(pack, RULES), issues=issue_register(FOOTING))

    # Act
    package = build_filing(broken, tmp_path, release=release, allow_rule_breaks=True)
    assert package.manifest_path is not None
    manifest = json.loads(package.manifest_path.read_text())

    # Assert
    validation = manifest["validation"]
    labelled = [item for item in validation["findings"] if item["publisher_issues"]]
    assert validation["submittable"] is False
    assert [item["publisher_issues"] for item in labelled] == [["PI-01"]]
    assert [item["issue"] for item in validation["summary"]["publisher_issues"]] == ["PI-01"]
