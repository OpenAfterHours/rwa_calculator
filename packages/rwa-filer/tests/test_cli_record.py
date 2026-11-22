"""
The JSON record and the identity block: built when read, computed once per run.

Pipeline position:
    rwa-filer validate / build  ->  validate.report.to_record
        ->  ``--report``, ``--format json``, the manifest
    evidence.Evidence.identity  ->  the evidence header

What is pinned here:
- a text ``validate`` with no ``--report`` builds no JSON record, because nothing
  reads it; every run that does read one builds it exactly once;
- skipping the record changes no output: the text report is the same bytes with
  and without ``--report``, and the file ``--report`` writes is the record
  ``--format json`` prints;
- one run fingerprints its facts once. With ``--evidence`` the identity block in
  the report, in the stdout record, in the manifest and in the evidence header is
  ONE block — and it is the block a run without ``--evidence`` computes, so
  handing it along cannot have changed it.

The counts are call counts, not times: the cost removed is a whole call
(``to_record``: one fingerprint per enforced rule; ``facts_sha256``: one JSON
line per fact), so the call is what is counted.

References:
- packages/rwa-filer/src/rwa_filer/cli.py (``_validate``)
- packages/rwa-filer/src/rwa_filer/filing.py (``build_filing``, ``_manifest``)
- packages/rwa-filer/src/rwa_filer/evidence.py (``Evidence.identity``)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pack_builders import VALID_LEI
from rwa_filer import cli
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main
from rwa_filer.evidence import read_evidence
from rwa_filer.validate import identity as identity_module

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
BASE = f"{VALID_LEI}_PRA001_2027-03-31"

#: An exposure and a value adjustment in real PRA001 cells (OF 07.00, corporates).
#: Structurally sound, and the rules that read the two cells break — so the
#: record carries findings and failures, not only passes.
BROKEN_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)
#: One reported zero: every rule that reads the cell runs and holds, so ``build``
#: writes the package and its manifest.
CLEAN_CSV = "table,sheet,row,column,value\nOF07.00.01.01,0008,0010,0010,0\n"


def _csv(tmp_path: Path, text: str = BROKEN_CSV) -> Path:
    path = tmp_path / "facts.csv"
    path.write_text(text)
    return path


@pytest.fixture
def record_builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per JSON record the ``validate`` command builds."""
    builds: list[int] = []
    build = cli.to_record

    def counted(*args: Any, **options: Any) -> dict[str, Any]:
        builds.append(1)
        return build(*args, **options)

    monkeypatch.setattr(cli, "to_record", counted)
    assert cli.to_record is counted, "the counter is not in place: every count would be 0"
    return builds


@pytest.fixture
def fingerprints(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per time a run fingerprints the return's facts."""
    taken: list[int] = []
    fingerprint = identity_module.facts_sha256

    def counted(ret: Any) -> str:
        taken.append(1)
        return fingerprint(ret)

    monkeypatch.setattr(identity_module, "facts_sha256", counted)
    assert identity_module.facts_sha256 is counted, "the counter is not in place"
    return taken


# ---------------------------------------------------------------------------
# The record is built when something reads it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reads_it", "expected"),
    [
        pytest.param([], 0, id="text-only"),
        pytest.param(["--format", "json"], 1, id="json"),
        pytest.param(["--report", "REPORT"], 1, id="report"),
        pytest.param(["--format", "json", "--report", "REPORT"], 1, id="json-and-report"),
    ],
)
def test_validate_builds_the_json_record_only_for_an_output_that_reads_it(
    reads_it: list[str],
    expected: int,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    record_builds: list[int],
) -> None:
    # Arrange
    options = [str(tmp_path / "report.json") if item == "REPORT" else item for item in reads_it]

    # Act
    code = main(["validate", str(_csv(tmp_path)), *HEADER_ARGS, *options])

    # Assert — the command reported (the path is live), and built what was read.
    assert code == EXIT_FAILED
    assert capsys.readouterr().out.strip(), "validate printed nothing: no report was made"
    assert len(record_builds) == expected


def test_skipping_the_record_changes_neither_the_text_report_nor_the_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    facts, report = _csv(tmp_path), tmp_path / "report.json"

    # Act — the text report with no record built, then with one; then the record printed.
    main(["validate", str(facts), *HEADER_ARGS])
    text_alone = capsys.readouterr().out
    main(["validate", str(facts), *HEADER_ARGS, "--report", str(report)])
    text_with_report = capsys.readouterr().out
    main(["validate", str(facts), *HEADER_ARGS, "--format", "json"])
    printed = capsys.readouterr().out

    # Assert
    assert text_alone.startswith("BLOCKED") and text_alone == text_with_report
    assert report.read_text(encoding="utf-8") == printed
    assert json.loads(printed)["summary"]["rule_findings"] > 0


# ---------------------------------------------------------------------------
# One identity block per run
# ---------------------------------------------------------------------------


def test_validate_with_evidence_fingerprints_the_facts_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fingerprints: list[int]
) -> None:
    # Arrange
    report, evidence = tmp_path / "report.json", tmp_path / "run.evidence.jsonl"

    # Act — every reader of the identity block at once: the record twice, the evidence header.
    main(
        [
            "validate",
            str(_csv(tmp_path)),
            *HEADER_ARGS,
            "--format",
            "json",
            "--report",
            str(report),
            "--evidence",
            str(evidence),
        ]
    )

    # Assert — all three were written (the path is live), from one fingerprint.
    printed = json.loads(capsys.readouterr().out)
    assert printed["identity"]["input"]["facts"] == 2
    assert report.is_file() and evidence.is_file()
    assert len(fingerprints) == 1


def test_build_with_evidence_fingerprints_the_facts_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fingerprints: list[int]
) -> None:
    # Arrange
    out, evidence = tmp_path / "out", tmp_path / "run.evidence.jsonl"

    # Act
    code = main(
        [
            "build",
            str(_csv(tmp_path, CLEAN_CSV)),
            "--out",
            str(out),
            *HEADER_ARGS,
            "--evidence",
            str(evidence),
        ]
    )

    # Assert — the manifest and the evidence file both carry the block, from one fingerprint.
    capsys.readouterr()
    assert code == EXIT_OK
    assert (out / f"{BASE}.manifest.json").is_file() and evidence.is_file()
    assert len(fingerprints) == 1


def test_the_identity_block_is_the_same_wherever_one_run_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    facts = _csv(tmp_path)
    report, evidence = tmp_path / "report.json", tmp_path / "run.evidence.jsonl"

    # Act — a run with no evidence computes the block inside the record, as it always did.
    main(["validate", str(facts), *HEADER_ARGS, "--format", "json"])
    computed_alone = json.loads(capsys.readouterr().out)["identity"]
    main(
        [
            "validate",
            str(facts),
            *HEADER_ARGS,
            "--format",
            "json",
            "--report",
            str(report),
            "--evidence",
            str(evidence),
            "--no-timestamp",
        ]
    )
    printed = json.loads(capsys.readouterr().out)["identity"]

    # Assert
    assert computed_alone["evidence_id"] and computed_alone["input"]["facts_sha256"]
    assert printed == computed_alone
    assert json.loads(report.read_text(encoding="utf-8"))["identity"] == computed_alone
    assert read_evidence(evidence).header["identity"] == computed_alone


def test_the_record_is_the_same_bytes_with_and_without_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    facts = _csv(tmp_path)

    # Act
    main(["validate", str(facts), *HEADER_ARGS, "--format", "json"])
    without = capsys.readouterr().out
    main(
        [
            "validate",
            str(facts),
            *HEADER_ARGS,
            "--format",
            "json",
            "--evidence",
            str(tmp_path / "run.evidence.jsonl"),
        ]
    )
    with_evidence = capsys.readouterr().out

    # Assert
    assert json.loads(without)["rules"], "the record lists no rule: nothing was compared"
    assert with_evidence == without


def test_the_manifest_carries_the_identity_block_of_the_evidence_it_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    facts = _csv(tmp_path, CLEAN_CSV)
    plain, evidenced = tmp_path / "plain", tmp_path / "evidenced"
    evidence = tmp_path / "run.evidence.jsonl"

    # Act — a build with no evidence computes the block inside the manifest's record.
    main(["build", str(facts), "--out", str(plain), *HEADER_ARGS, "--no-timestamp"])
    main(
        [
            "build",
            str(facts),
            "--out",
            str(evidenced),
            *HEADER_ARGS,
            "--no-timestamp",
            "--evidence",
            str(evidence),
        ]
    )

    # Assert
    capsys.readouterr()
    computed_alone = json.loads((plain / f"{BASE}.manifest.json").read_text())["identity"]
    manifest = json.loads((evidenced / f"{BASE}.manifest.json").read_text())
    assert computed_alone["input"]["facts_sha256"]
    assert manifest["identity"] == computed_alone
    assert read_evidence(evidence).header["identity"] == computed_alone
    assert manifest["evidence"]["evidence_id"] == computed_alone["evidence_id"]
