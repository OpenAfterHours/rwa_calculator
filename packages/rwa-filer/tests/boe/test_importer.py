"""
The rule-workbook importer: read by header name, keep everything, write deterministically.

The workbooks here are built in the test, in the layouts the Bank's eleven
workbooks actually use — which differ from one another. That the importer
reproduces the PACKAGED rule books from the Bank's real workbooks is pinned by
the opt-in test at the foot of this file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from rwa_filer.boe.catalogue import RULEBOOKS_DIRECTORY, available_rulebooks, rulebook_from
from rwa_filer.boe.importer import (
    CELL_LIMIT,
    dump_rulebook,
    import_workbook,
    is_rulebook_current,
    rulebook_file_name,
    write_rulebook,
)

openpyxl = pytest.importorskip("openpyxl", reason="reading a rule workbook needs rwa-filer[excel]")

FULL_HEADER = [
    "Owner",
    "Framework code",
    "Framework version code",
    "Rule code",
    "Scope",
    "Where",
    "Join",
    "Expression",
    "Simplified Expression",
    "Precondition",
    "Simplified Precondition",
    "Include in XBRL",
    "Deactivated",
    "Always execute",
    "Error message",
    "Label",
    "Severity and modules",
    "T1",
    "T2",
]
#: The Step-in Risk layout: no precondition columns, so everything after shifts.
SHORT_HEADER = [name for name in FULL_HEADER if "Precondition" not in name][:-1]

EXPRESSION = "{t: T1, r: 0010, c: 0010, dv: 0, seq: False, id: v0, f: banking, fv: test_fw} >= 0"


def row(header: list[str], **cells: Any) -> list[Any]:
    """One data row, given by column NAME so the layout under test decides the position."""
    defaults = {
        "Owner": "BOE",
        "Framework code": "banking",
        "Framework version code": "test_fw",
        "Expression": EXPRESSION,
        "Include in XBRL": "yes",
        "Deactivated": "no",
        "Always execute": "no",
        "Severity and modules": "ERROR - TST001|",
        "T1": "T1",
    }
    return [{**defaults, **cells}.get(name) for name in header]


def workbook(tmp_path: Path, header: list[str], *rows: list[Any], name: str | None = None) -> Path:
    book = openpyxl.Workbook()
    book.active.title = "Note"
    sheet = book.create_sheet("test_fw")
    sheet.append(header)
    for cells in rows:
        sheet.append(cells)
    path = tmp_path / (name or "Bank of England Banking Taxonomy Validations Test v9.8.7.xlsx")
    book.save(path)
    return path


def test_every_rule_is_read_with_its_cells_flags_and_tables(tmp_path: Path) -> None:
    # Arrange
    path = workbook(
        tmp_path,
        FULL_HEADER,
        row(
            FULL_HEADER,
            **{
                "Rule code": "boe_b0002",
                "Scope": "scope({t: T1, c:0010;0020, f: banking, fv: test_fw})",
                "Always execute": "yes",
                "Label": "SHORT_LABEL(en) - Amounts are\n not negative |DESCRIPTION(en) - Long text",
                "T2": "T2",
            },
        ),
        row(
            FULL_HEADER, **{"Rule code": "boe_b0001", "Include in XBRL": "no", "Deactivated": "yes"}
        ),
    )

    # Act
    rulebook = import_workbook(path)

    # Assert — sorted by code; nothing filtered out.
    assert rulebook["framework_version"] == "test_fw"
    assert rulebook["source"]["taxonomy"] == "9.8.7" and rulebook["source"]["sheet"] == "test_fw"
    assert rulebook["modules"] == ["TST001"]
    assert rulebook["rules"] == [
        {
            "id": "boe_b0001",
            "expression": EXPRESSION,
            "severity": {"TST001": "ERROR"},
            "tables": ["T1"],
            "in_xbrl": False,
            "deactivated": True,
            "always_execute": False,
        },
        {
            "id": "boe_b0002",
            "expression": EXPRESSION,
            "severity": {"TST001": "ERROR"},
            "tables": ["T1", "T2"],
            "in_xbrl": True,
            "deactivated": False,
            "always_execute": True,
            "scope": "scope({t: T1, c:0010;0020, f: banking, fv: test_fw})",
            "label": "Amounts are not negative",
        },
    ]


def test_columns_are_found_by_name_whatever_the_layout(tmp_path: Path) -> None:
    """Without the two precondition columns every later column sits two places left."""
    # Arrange
    path = workbook(
        tmp_path,
        SHORT_HEADER,
        row(
            SHORT_HEADER, **{"Rule code": "boe_b0001", "Severity and modules": "WARNING - TST001|"}
        ),
    )

    # Act
    (rule,) = import_workbook(path)["rules"]

    # Assert — the flags and the severity are still read from the right cells.
    assert (rule["in_xbrl"], rule["deactivated"], rule["severity"]) == (
        True,
        False,
        {"TST001": "WARNING"},
    )
    assert rule["tables"] == ["T1"]


def test_a_severity_cell_lists_one_module_per_line(tmp_path: Path) -> None:
    # Arrange
    cell = "ERROR - PRA114| \nERROR - PRA113| \nWARNING - PRA112|"
    path = workbook(
        tmp_path, FULL_HEADER, row(FULL_HEADER, **{"Rule code": "b1", "Severity and modules": cell})
    )

    # Act
    rulebook = import_workbook(path)

    # Assert
    assert rulebook["rules"][0]["severity"] == {
        "PRA112": "WARNING",
        "PRA113": "ERROR",
        "PRA114": "ERROR",
    }
    assert rulebook["modules"] == ["PRA112", "PRA113", "PRA114"]


def test_a_rule_with_no_table_is_kept(tmp_path: Path) -> None:
    path = workbook(tmp_path, FULL_HEADER, row(FULL_HEADER, **{"Rule code": "b1", "T1": None}))

    assert import_workbook(path)["rules"][0]["tables"] == []


def test_an_expression_cut_at_the_cell_limit_is_marked(tmp_path: Path) -> None:
    """Such a cell is not a whole expression, and must not be evaluated as one."""
    # Arrange
    long = EXPRESSION + " or " * 10 + "x" * CELL_LIMIT
    path = workbook(
        tmp_path,
        FULL_HEADER,
        row(FULL_HEADER, **{"Rule code": "b1", "Expression": long[:CELL_LIMIT]}),
    )

    # Act
    (rule,) = import_workbook(path)["rules"]

    # Assert
    assert rule["truncated"] is True
    assert rulebook_from(import_workbook(path)).rules[0].parse_error is not None


def test_the_written_rule_book_is_deterministic_and_loads_back(tmp_path: Path) -> None:
    # Arrange
    path = workbook(
        tmp_path,
        FULL_HEADER,
        row(FULL_HEADER, **{"Rule code": "boe_b0002"}),
        row(FULL_HEADER, **{"Rule code": "boe_b0001"}),
    )
    rulebook = import_workbook(path)
    out = tmp_path / "out" / rulebook_file_name(rulebook)

    # Act
    write_rulebook(rulebook, out)

    # Assert — one rule per line, byte-stable, and readable by the catalogue.
    text = out.read_text(encoding="utf-8")
    assert out.name == "test_fw-9.8.7.json"
    assert text == dump_rulebook(import_workbook(path))
    assert sum(line.startswith('{"always_execute"') for line in text.splitlines()) == 2
    assert [rule.rule_id for rule in rulebook_from(rulebook).rules] == ["boe_b0001", "boe_b0002"]
    assert is_rulebook_current(rulebook, out)


def test_a_stale_or_missing_rule_book_is_not_current(tmp_path: Path) -> None:
    # Arrange
    path = workbook(tmp_path, FULL_HEADER, row(FULL_HEADER, **{"Rule code": "boe_b0001"}))
    rulebook = import_workbook(path)
    out = tmp_path / "book.json"
    write_rulebook(rulebook, out)
    changed = {**rulebook, "rules": [{**rulebook["rules"][0], "deactivated": True}]}

    # Act / Assert
    assert not is_rulebook_current(changed, out)
    assert not is_rulebook_current(rulebook, tmp_path / "absent.json")


def test_the_taxonomy_version_may_be_given_where_the_file_name_lacks_it(tmp_path: Path) -> None:
    # Arrange
    path = workbook(
        tmp_path, FULL_HEADER, row(FULL_HEADER, **{"Rule code": "b1"}), name="rules.xlsx"
    )

    # Act / Assert
    assert import_workbook(path, taxonomy_version="4.1.1")["source"]["taxonomy"] == "4.1.1"
    with pytest.raises(ValueError, match="no version in the file name"):
        import_workbook(path)


def test_a_workbook_that_is_not_a_rule_workbook_is_refused(tmp_path: Path) -> None:
    # Arrange
    no_column = workbook(
        tmp_path, [name for name in FULL_HEADER if name != "Expression"], name="a v1.0.0.xlsx"
    )
    mixed = workbook(
        tmp_path,
        FULL_HEADER,
        row(FULL_HEADER, **{"Rule code": "b1"}),
        row(FULL_HEADER, **{"Rule code": "b2", "Framework version code": "other_fw"}),
        name="b v1.0.0.xlsx",
    )

    # Act / Assert
    with pytest.raises(ValueError, match="no column.*Expression"):
        import_workbook(no_column)
    with pytest.raises(ValueError, match="one framework version"):
        import_workbook(mixed)


# ---------------------------------------------------------------------------
# The Bank's own workbooks — opt-in
# ---------------------------------------------------------------------------

BOE_DIR = os.environ.get("RWA_FILER_BOE_DIR")


@pytest.mark.skipif(
    not BOE_DIR, reason="set RWA_FILER_BOE_DIR to a directory holding the BoE rule workbooks"
)
def test_the_packaged_rule_books_are_exactly_what_the_banks_workbooks_yield() -> None:
    """Every packaged rule book, byte for byte, from the v4.1.1 publication.

    The Financial Statements workbook is NAMED v4.1.0; its Note sheet and its
    place in the publication say v4.1.1, which is why the version is given.
    """
    # Arrange
    workbooks = sorted(Path(BOE_DIR or "").rglob("*Taxonomy Validations*.xlsx"))
    if not workbooks:
        pytest.skip("no '*Taxonomy Validations*.xlsx' under RWA_FILER_BOE_DIR")
    packaged = Path(__file__).parents[2] / "src" / "rwa_filer" / "boe" / RULEBOOKS_DIRECTORY

    # Act
    produced = {}
    for path in workbooks:
        rulebook = import_workbook(path, taxonomy_version="4.1.1")
        produced[rulebook_file_name(rulebook)] = is_rulebook_current(
            rulebook, packaged / rulebook_file_name(rulebook)
        )

    # Assert
    assert set(produced) == set(available_rulebooks())
    assert all(produced.values()), [name for name, current in produced.items() if not current]
