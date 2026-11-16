"""
The command line says what the Bank's validations deny list did, wherever it lists rules.

Pipeline position:
    rwa-filer validate / rules list / rulebook list / rulebook deny-list
        ->  the packaged deny list (``boe/data/deny/<release>.json``)

What is pinned: ``validate`` names each rule the Bank's gateway no longer runs
as published, with the date and the known issue, and stops blocking on it from
that date (``--submission-date`` says which date); the listings name the
deny-listed rules; and the import / check commands build and verify a release's
list from the Bank's workbook.

References:
- Bank of England, "Banking validations deny list" (November 2026)
- Bank of England, Banking taxonomy known-issues log, #22 (boe_b0710 family)
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

import jsonschema
import pytest

from compare_builders import corporate_csv
from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main
from rwa_filer.release import release_deny_list
from rwa_filer.schemas import VALIDATION_REPORT_SCHEMA, load_schema

HEADER_ARGS = [
    "--entity",
    VALID_LEI,
    "--reference-date",
    "2027-03-31",
    "--module",
    "PRA001",
    "--taxonomy",
    "4.1.1",
]
B0710_LINE = (
    "boe_b0710 deactivated by the Bank of England on 19 October 2026 "
    "(validations deny list; known issues log #22)"
)


@pytest.fixture
def corporates(tmp_path: Path) -> Path:
    """A PRA001 return that breaks boe_b0710: no CCF breakdown on its on-balance-sheet rows."""
    path = tmp_path / "corporates.csv"
    path.write_text(corporate_csv(ecai_columns=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_names_each_rule_the_bank_switched_off_and_does_not_block_on_it(
    corporates: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(["validate", str(corporates), *HEADER_ARGS, "--submission-date", "2026-11-16"])
    out = capsys.readouterr().out

    # Assert
    assert "validations deny list (taxonomy 4.1.1, as at 2026-11-16)" in out
    assert B0710_LINE in out
    assert "the published rule breaks" in out
    assert "Validation rule boe_b0710 " not in out, "a rule the gateway does not run is no finding"


def test_validate_before_the_date_applied_still_blocks_on_the_rule(
    corporates: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The leg that stays red: the return really does break boe_b0710 as published."""
    code = main(["validate", str(corporates), *HEADER_ARGS, "--submission-date", "2026-10-18"])
    out = capsys.readouterr().out

    assert code == EXIT_FAILED
    assert "[VAL001] ERROR: Validation rule boe_b0710 does not hold" in out


def test_validate_json_carries_the_entry_and_the_published_verdict(
    corporates: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(
        [
            "validate",
            str(corporates),
            *HEADER_ARGS,
            "--submission-date",
            "2026-11-16",
            "--format",
            "json",
        ]
    )
    record = json.loads(capsys.readouterr().out)

    # Assert
    jsonschema.Draft202012Validator(load_schema(VALIDATION_REPORT_SCHEMA)).validate(record)
    rule = next(item for item in record["rules"] if item["rule_id"] == "boe_b0710")
    assert (rule["status"], rule["reason"]) == ("NOT_EVALUATED", "deactivated_by_publisher")
    assert (rule["deny_list"]["date_applied"], rule["deny_list"]["known_issue"]) == (
        "2026-10-19",
        22,
    )
    assert rule["formula"]["status"] == "FAIL"
    assert "boe_b0710" in record["summary"]["deny_list"]["deactivated"]
    assert record["identity"]["deny_list"]["applied_on"] == "2026-11-16"


# ---------------------------------------------------------------------------
# The listings
# ---------------------------------------------------------------------------


def test_rules_list_names_the_deny_listed_template_level_rules(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["rules", "list"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert "BASEL_3_1: the Bank's validations deny list" in out
    assert any(
        line.split()[0] == "boe_b0710" and "on 19 October 2026" in line and "#22" in line
        for line in out.splitlines()
        if line.startswith("  ")
    )


def test_rulebook_list_counts_the_deny_listed_rules_of_each_module(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["rulebook", "list"])
    lines = capsys.readouterr().out.splitlines()

    pra001 = next(line.split() for line in lines if " PRA001 " in f" {line} ")
    in_force = release_deny_list("4.1.1").in_force("PRA001", date.today())
    assert code == EXIT_OK
    assert "deny-listed" in lines[0]
    assert int(pra001[5]) == len(in_force) > 0


def test_rulebook_deny_list_shows_each_entry_and_whether_it_is_in_force(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["rulebook", "deny-list", "--module", "PRA001", "--on", "2026-11-15"])
    lines = capsys.readouterr().out.splitlines()

    assert code == EXIT_OK
    b0710 = next(line for line in lines if " boe_b0710 " in line)
    b0272 = next(line for line in lines if " boe_b0272 " in line)
    assert "on 19 October 2026" in b0710 and "#22" in b0710
    assert "not in force" not in b0710
    assert "on 16 November 2026" in b0272 and "[not in force on this date]" in b0272
    assert not any("MRL001" in line for line in lines), "--module limits the listing"


def test_rulebook_deny_list_json_says_whether_each_entry_is_in_force(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["rulebook", "deny-list", "--taxonomy", "4.1.1", "--on", "2026-11-15", "--format", "json"])
    (listed,) = json.loads(capsys.readouterr().out)

    entries = {(item["module"], item["rule_id"]): item for item in listed["entries"]}
    assert entries[("PRA001", "boe_b0710")]["in_force"] is True
    assert entries[("PRA001", "boe_b0272")]["in_force"] is False
    assert entries[("MRL001", "boe_b4006_1")]["published_code"] == "boe_b04006_1"


# ---------------------------------------------------------------------------
# import / check
# ---------------------------------------------------------------------------


def _deny_workbook(tmp_path: Path) -> Path:
    openpyxl = pytest.importorskip("openpyxl", reason="reading the deny list needs openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "Note"
    sheet = book.create_sheet("Version 4.1.1")
    sheet.append(["Validation Code", "Date Applied", "Deny Type", "Module"])
    sheet.append(["boe_b0710", datetime(2026, 10, 19), "Deactivated", "PRA001"])
    sheet.append(["boe_b9999", datetime(2026, 10, 19), "Deactivated", "PRA001"])
    path = tmp_path / "deny.xlsx"
    book.save(path)
    return path


def test_rulebook_deny_list_import_writes_the_file_and_reports_unmatched_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        [
            "rulebook",
            "deny-list",
            "import",
            str(_deny_workbook(tmp_path)),
            "--release",
            "4.1.1",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    out = capsys.readouterr().out

    # Assert
    written = json.loads((tmp_path / "out" / "4.1.1.json").read_text(encoding="utf-8"))
    assert code == EXIT_OK
    assert [item["rule_id"] for item in written["entries"]] == ["boe_b0710"]
    assert [item["code"] for item in written["unmatched"]] == ["boe_b9999"]
    assert "UNMATCHED  PRA001 boe_b9999" in out


def test_rulebook_deny_list_check_fails_when_the_packaged_list_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["rulebook", "deny-list", "check", str(_deny_workbook(tmp_path)), "--release", "4.1.1"]
    )

    assert code == EXIT_FAILED
    assert "packaged deny list 4.1.1.json is out of date" in capsys.readouterr().err


def test_rulebook_deny_list_refuses_a_release_that_is_not_shipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["rulebook", "deny-list", "check", str(_deny_workbook(tmp_path)), "--release", "0.0.1"]
    )

    assert code == EXIT_FAILED
    assert "taxonomy 0.0.1 is not shipped" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The Bank's own workbook — opt-in (it is not in the repository)
# ---------------------------------------------------------------------------

DENY_WORKBOOK = os.environ.get("RWA_FILER_DENY_LIST")
KNOWN_ISSUES = os.environ.get("RWA_FILER_KNOWN_ISSUES")


@pytest.mark.skipif(
    not DENY_WORKBOOK, reason="set RWA_FILER_DENY_LIST to the Bank's deny-list workbook"
)
def test_the_packaged_list_is_what_the_banks_workbook_yields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With RWA_FILER_KNOWN_ISSUES naming the known-issues log it was joined to."""
    arguments = ["rulebook", "deny-list", "check", str(DENY_WORKBOOK), "--release", "4.1.1"]
    if KNOWN_ISSUES:
        arguments += ["--known-issues", KNOWN_ISSUES]

    code = main(arguments)

    assert code == EXIT_OK, capsys.readouterr().err
