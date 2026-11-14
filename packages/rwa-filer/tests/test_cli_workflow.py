"""
The preparer's commands end to end: build with adjustments, sign off, verify, diff.

On the packaged PRA001 pack and rules. The return used throughout breaks a
published rule as it comes from its source; the adjustments are what make it
fileable — which is the situation the workflow exists for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
BASE = f"{VALID_LEI}_PRA001_2027-03-31"

#: An exposure and a value adjustment with nothing else: a broken rule.
SOURCE_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)
#: Zero the exposure and take the adjustment out: every rule then holds.
ADJUSTMENTS_CSV = (
    "table,sheet,row,column,value,reason,remove\n"
    "OF07.00.01.01,0008,0010,0010,0,Booked to the wrong class,\n"
    "OF07.00.01.01,0008,0010,0030,,Follows the exposure,yes\n"
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "source.csv").write_text(SOURCE_CSV)
    (tmp_path / "adjustments.csv").write_text(ADJUSTMENTS_CSV)
    return tmp_path


def build(workspace: Path, *extra: str) -> int:
    return main(
        [
            "build",
            str(workspace / "source.csv"),
            "--out",
            str(workspace / "out"),
            *HEADER_ARGS,
            "--no-timestamp",
            *extra,
        ]
    )


def adjusted(workspace: Path) -> int:
    return build(
        workspace, "--adjustments", str(workspace / "adjustments.csv"), "--author", "A. Preparer"
    )


def manifest(workspace: Path) -> Path:
    return workspace / "out" / f"{BASE}.manifest.json"


def test_adjustments_make_a_blocked_return_fileable_and_are_recorded(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    unadjusted = build(workspace)
    with_adjustments = adjusted(workspace)

    # Assert — the manifest says which cells were overridden, from what, and why.
    out = capsys.readouterr().out
    assert (unadjusted, with_adjustments) == (EXIT_FAILED, EXIT_OK)
    assert "Applied 2 adjustment(s)" in out
    recorded = json.loads(manifest(workspace).read_text())["adjustments"]
    assert [
        (item["action"], item["before"], item["after"], item["reason"]) for item in recorded
    ] == [
        ("change", 1_000_000.0, 0.0, "Booked to the wrong class"),
        ("remove", -5_000.0, None, "Follows the exposure"),
    ]


def test_the_ledger_records_the_adjustments_and_the_build_under_the_authors_name(
    workspace: Path,
) -> None:
    # Act
    adjusted(workspace)
    entries = [
        json.loads(line)
        for line in (workspace / "out" / f"{BASE}.ledger.jsonl").read_text().splitlines()
    ]

    # Assert
    assert [(entry["sequence"], entry["event"], entry["author"]) for entry in entries] == [
        (1, "adjustment", "A. Preparer"),
        (2, "build", "A. Preparer"),
    ]
    assert entries[1]["payload"]["submittable"] is True
    assert (
        entries[1]["payload"]["sha256"]
        == json.loads(manifest(workspace).read_text())["instance"]["sha256"]
    )


def test_adjustments_need_an_author(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Act
    code = build(workspace, "--adjustments", str(workspace / "adjustments.csv"))

    # Assert
    assert code == EXIT_FAILED
    assert "needs --author" in capsys.readouterr().err
    assert not (workspace / "out").exists()


def test_an_adjustment_without_a_reason_stops_the_build(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    (workspace / "adjustments.csv").write_text(
        "table,sheet,row,column,value,reason\nOF07.00.01.01,0008,0010,0010,0,\n"
    )

    # Act
    code = adjusted(workspace)

    # Assert
    assert code == EXIT_FAILED
    assert "gives no reason" in capsys.readouterr().err
    assert not (workspace / "out").exists()


def test_sign_off_then_verify(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange
    adjusted(workspace)
    capsys.readouterr()

    # Act
    unsigned = main(["verify", str(manifest(workspace))])
    signed = main(
        [
            "signoff",
            str(manifest(workspace)),
            "--approver",
            "C. Approver",
            "--role",
            "Head of Reporting",
        ]
    )
    verified = main(["verify", str(manifest(workspace))])

    # Assert
    out = capsys.readouterr().out
    assert (unsigned, signed, verified) == (EXIT_FAILED, EXIT_OK, EXIT_OK)
    assert "has not been signed off" in out
    assert "Signed off by C. Approver (Head of Reporting)" in out
    assert "the files, the sign-off and the ledger agree" in out
    ledger = (workspace / "out" / f"{BASE}.ledger.jsonl").read_text().splitlines()
    assert json.loads(ledger[-1])["event"] == "signoff"


def test_verify_fails_when_the_file_or_the_ledger_is_changed_after_sign_off(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    adjusted(workspace)
    main(["signoff", str(manifest(workspace)), "--approver", "C. Approver", "--role", "Head"])
    instance = workspace / "out" / f"{BASE}.xbrl"
    ledger = workspace / "out" / f"{BASE}.ledger.jsonl"
    original = instance.read_bytes()
    capsys.readouterr()

    # Act — first the instance, then (restored) the ledger's first entry.
    instance.write_bytes(original.replace(b">0<", b">1<"))
    changed_file = main(["verify", str(manifest(workspace))])
    instance.write_bytes(original)
    ledger.write_text(ledger.read_text().replace("Booked to the wrong class", "Typo"))
    changed_ledger = main(["verify", str(manifest(workspace))])

    # Assert
    out = capsys.readouterr().out
    assert (changed_file, changed_ledger) == (EXIT_FAILED, EXIT_FAILED)
    assert "is not the file the manifest describes" in out
    assert "entry 1 has been altered since it was written" in out


def test_a_forced_package_is_signed_only_with_acknowledgement(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange — written with the rule break forced.
    build(workspace, "--force")
    capsys.readouterr()
    signing = ["signoff", str(manifest(workspace)), "--approver", "C. Approver", "--role", "Head"]

    # Act
    refused = main(signing)
    acknowledged = main([*signing, "--acknowledge-findings"])

    # Assert
    captured = capsys.readouterr()
    assert (refused, acknowledged) == (EXIT_FAILED, EXIT_OK)
    assert "acknowledged explicitly" in captured.err
    assert "although the validation found blocking findings" in captured.out


def test_diff_shows_what_the_adjustments_changed(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The source table against the filed instance: two different file formats."""
    # Arrange
    adjusted(workspace)
    capsys.readouterr()
    source, filed = str(workspace / "source.csv"), str(workspace / "out" / f"{BASE}.xbrl")

    # Act
    different = main(["diff", source, filed, *HEADER_ARGS])
    text = capsys.readouterr().out
    main(["diff", source, filed, *HEADER_ARGS, "--format", "json"])
    record = json.loads(capsys.readouterr().out)
    same = main(["diff", filed, filed])

    # Assert
    assert (different, same) == (EXIT_FAILED, EXIT_OK)
    assert text.startswith("DIFFERENT: 1 changed, 0 added, 1 removed, 0 unchanged")
    assert "changed OF07.00.01.01[z0008][r0010][c0010]: 1000000.0 -> 0.0" in text
    assert record["counts"] == {"added": 0, "removed": 1, "changed": 1}
    assert capsys.readouterr().out.startswith("IDENTICAL")
