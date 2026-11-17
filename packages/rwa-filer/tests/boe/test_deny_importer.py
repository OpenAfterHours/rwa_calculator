"""
The deny-list importer: the Bank's workbook, one release's sheet, matched to its rules.

The workbooks here are built in the test, in the layout of the Bank's November
2026 deny list and known-issues log (the real files are git-ignored). Codes are
matched against the rule books this package ships for 4.1.1, so the codes used
are real ones: ``boe_b0710`` (PRA001), ``boe_b1022`` (PRA115 and, a different
rule, PRA001), ``boe_b4006_1`` (MRL001).

What is pinned: matching by module AND code, the one typo rule (a surplus
leading zero in the rule number), that an unmatched code is reported and kept,
that a blank date is pending, the known-issues join, and deterministic bytes.

References:
- Bank of England, "Banking validations deny list", sheets "Note" and "Version 4.1.1"
- Bank of England, Banking taxonomy known-issues log, sheet "Known Issues"
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from rwa_filer.boe.deny import DENY_DEACTIVATED, DENY_DOWNGRADED, deny_list_from
from rwa_filer.boe.deny_importer import (
    RESOLVED_LEADING_ZERO,
    dump_deny_list,
    import_deny_list,
    is_deny_list_current,
    resolve_code,
    write_deny_list,
)

openpyxl = pytest.importorskip("openpyxl", reason="reading the deny list needs rwa-filer[excel]")

HEADER = ["Validation Code", "Date Applied", "Deny Type", "Module", None]
APPLIED = datetime(2026, 10, 19)


def deny_workbook(tmp_path: Path, *rows: list[Any], sheet: str = "Version 4.1.1 ") -> Path:
    """The Bank's layout: a Note sheet, then one sheet per release (trailing space and all)."""
    book = openpyxl.Workbook()
    book.active.title = "Note"
    book.active.append([None, "These validation execution amendments are applied ..."])
    other = book.create_sheet("Version 3.7.0 ")
    other.append(HEADER)
    other.append(["boe_b0710", APPLIED, "Deactivated", "PRA001"])
    release = book.create_sheet(sheet)
    release.append(HEADER)
    for cells in rows:
        release.append(cells)
    path = tmp_path / "deny-list.xlsx"
    book.save(path)
    return path


def issues_workbook(tmp_path: Path, *issues: list[Any]) -> Path:
    """The known-issues log: a title row, "Last updated", the header, then the issues."""
    book = openpyxl.Workbook()
    book.active.title = "Readme"
    sheet = book.create_sheet("Known Issues")
    sheet.append(["Bank of England Banking DPM and XBRL Taxonomy - List of known issues"])
    sheet.append(["Last updated:", None, datetime(2026, 11, 16)])
    sheet.append(
        [
            "#",
            "Affected version",
            "Entry point",
            "Affected artefact",
            "Issue title",
            "Publication date of the issue",
        ]
    )
    for cells in issues:
        sheet.append(cells)
    path = tmp_path / "known-issues.xlsx"
    book.save(path)
    return path


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_a_code_is_matched_to_the_rule_of_its_module(tmp_path: Path) -> None:
    workbook = deny_workbook(tmp_path, ["boe_b0710", APPLIED, "Deactivated", "PRA001"])

    imported = import_deny_list(workbook, "4.1.1")

    entry = imported.deny_list.entry("PRA001", "boe_b0710")
    assert entry is not None
    assert (entry.deny_type, entry.date_applied) == (DENY_DEACTIVATED, date(2026, 10, 19))
    assert imported.deny_list.unmatched == ()


def test_only_the_release_sheet_is_read(tmp_path: Path) -> None:
    """The 3.7.0 sheet lists boe_b0710 too; it is not 4.1.1's."""
    workbook = deny_workbook(tmp_path, ["boe_b1022", APPLIED, "Deactivated", "PRA115"])

    imported = import_deny_list(workbook, "4.1.1")

    assert [item.rule_id for item in imported.deny_list.entries] == ["boe_b1022"]
    assert imported.deny_list.source["sheet"] == "Version 4.1.1 "


def test_a_code_matching_no_rule_is_reported_and_kept_not_dropped(tmp_path: Path) -> None:
    workbook = deny_workbook(
        tmp_path,
        ["boe_b9999", APPLIED, "Deactivated", "PRA001"],
        ["boe_b0001", APPLIED, "Deactivated", "ZZZ999"],
    )

    imported = import_deny_list(workbook, "4.1.1")

    unmatched = {item.code: item.reason for item in imported.deny_list.unmatched}
    assert set(unmatched) == {"boe_b9999", "boe_b0001"}
    assert "no rule of module PRA001" in unmatched["boe_b9999"]
    assert "no rule book of taxonomy 4.1.1 covers module ZZZ999" in unmatched["boe_b0001"]
    assert imported.deny_list.entries == ()
    assert any("UNMATCHED" in line and "boe_b9999" in line for line in imported.lines())


def test_a_surplus_leading_zero_in_the_rule_number_is_resolved_and_reported(
    tmp_path: Path,
) -> None:
    """The Bank's November list writes boe_b04006_1; MRL001's rule is boe_b4006_1."""
    workbook = deny_workbook(tmp_path, ["boe_b04006_1", APPLIED, "Downgraded", "MRL001"])

    imported = import_deny_list(workbook, "4.1.1")

    entry = imported.deny_list.entry("MRL001", "boe_b4006_1")
    assert entry is not None
    assert (entry.deny_type, entry.published_code) == (DENY_DOWNGRADED, "boe_b04006_1")
    assert imported.resolved == (entry,)
    assert any("boe_b04006_1 -> boe_b4006_1" in line for line in imported.lines())


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("boe_b0710", ("boe_b0710", None)),
        ("boe_b04006_1", ("boe_b4006_1", RESOLVED_LEADING_ZERO)),
        ("boe_b000710", ("boe_b0710", RESOLVED_LEADING_ZERO)),
        # Four digits already: a zero there is part of the number, never dropped.
        ("boe_b0406_1", (None, None)),
        # A surplus digit that is not a zero is not this typo.
        ("boe_b14006_1", (None, None)),
        # The four-digit reading must itself name a rule.
        ("boe_b05555", (None, None)),
    ],
)
def test_the_typo_rule_drops_surplus_leading_zeros_only(
    code: str, expected: tuple[str | None, str | None]
) -> None:
    codes = {"boe_b0710", "boe_b4006_1", "boe_b4006_2"}

    assert resolve_code(code, codes) == expected


def test_a_blank_date_is_kept_as_pending(tmp_path: Path) -> None:
    """The Note sheet: a blank Date Applied is identified but "not implemented yet"."""
    workbook = deny_workbook(tmp_path, ["boe_b0746", None, "Deactivate", "PRA001"])

    imported = import_deny_list(workbook, "4.1.1")

    entry = imported.deny_list.entry("PRA001", "boe_b0746")
    assert entry is not None
    assert entry.is_pending
    assert any(line.strip().startswith("pending") for line in imported.lines())


def test_an_unknown_deny_type_is_refused(tmp_path: Path) -> None:
    workbook = deny_workbook(tmp_path, ["boe_b0710", APPLIED, "Suspended", "PRA001"])

    with pytest.raises(ValueError, match="deny type"):
        import_deny_list(workbook, "4.1.1")


def test_a_workbook_with_no_sheet_for_the_release_is_refused(tmp_path: Path) -> None:
    workbook = deny_workbook(tmp_path, sheet="Version 9.9.9")

    with pytest.raises(ValueError, match="no sheet 'Version 4.1.1'"):
        import_deny_list(workbook, "4.1.1")


# ---------------------------------------------------------------------------
# The known-issues join
# ---------------------------------------------------------------------------


def test_each_entry_takes_the_newest_known_issue_naming_its_rule_and_module(
    tmp_path: Path,
) -> None:
    workbook = deny_workbook(
        tmp_path,
        ["boe_b0710", APPLIED, "Deactivated", "PRA001"],
        ["boe_b04006_1", APPLIED, "Downgraded", "MRL001"],
        ["boe_b1022", datetime(2026, 5, 14), "Deactivated", "PRA115"],
    )
    log = issues_workbook(
        tmp_path,
        [9, "4.0.0", "PRA001", "Validation rules", "Validation rule boe_b0710 (an old one)"],
        [22, "4.1.1", "PRA001", "Validation rules", "validation rules\nboe_b0710\nboe_b0710_1"],
        [23, "4.1.1", "MRL001", "Validation rules", "validation rules\nboe_b4006_1\nboe_b4006_2"],
        [15, "3.7.0 hotfix", "PRA115", "Validation rules", "Validation rule boe_b1022 and b1014"],
        # Names the rule, but for another module: not the PRA115 entry's issue.
        [31, "4.1.1", "PRA001", "Validation rules", "boe_b1022"],
    )

    imported = import_deny_list(workbook, "4.1.1", known_issues=log)

    deny_list = imported.deny_list
    assert deny_list.entry("PRA001", "boe_b0710").known_issue == 22  # type: ignore[union-attr]
    assert deny_list.entry("MRL001", "boe_b4006_1").known_issue == 23  # type: ignore[union-attr]
    assert deny_list.entry("PRA115", "boe_b1022").known_issue == 15  # type: ignore[union-attr]
    assert deny_list.source["known_issues"]["last_updated"] == "2026-11-16"


def test_an_entry_no_known_issue_names_is_reported(tmp_path: Path) -> None:
    workbook = deny_workbook(tmp_path, ["boe_b0746", APPLIED, "Deactivated", "PRA001"])
    log = issues_workbook(tmp_path, [22, "4.1.1", "PRA001", "Validation rules", "boe_b0710"])

    imported = import_deny_list(workbook, "4.1.1", known_issues=log)

    assert [item.rule_id for item in imported.without_issue] == ["boe_b0746"]
    assert imported.deny_list.entry("PRA001", "boe_b0746").known_issue is None  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def test_the_import_is_deterministic_and_checkable(tmp_path: Path) -> None:
    workbook = deny_workbook(
        tmp_path,
        ["boe_b0746", APPLIED, "Deactivated", "PRA001"],
        ["boe_b0710", APPLIED, "Deactivated", "PRA001"],
    )
    target = tmp_path / "out" / "4.1.1.json"

    first = import_deny_list(workbook, "4.1.1", url="https://example.invalid/deny.xlsx")
    write_deny_list(first.payload, target)
    second = import_deny_list(workbook, "4.1.1", url="https://example.invalid/deny.xlsx")

    committed = target.read_text(encoding="utf-8")
    assert is_deny_list_current(second.payload, committed)
    assert committed == dump_deny_list(second.payload)
    assert [item.rule_id for item in deny_list_from(second.payload).entries] == [
        "boe_b0710",
        "boe_b0746",
    ]
    assert first.payload["source"]["published"] == "2026-10-19"
    assert not is_deny_list_current(second.payload, committed.replace("b0746", "b0747"))
