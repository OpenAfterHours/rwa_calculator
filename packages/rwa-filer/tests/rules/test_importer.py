"""
The rule importer: a publisher workbook in, a deterministic JSON extract out.

Pipeline position:
    publisher workbook (.xlsx) -> importer.extract -> payload -> rules/data/*.json

The real workbooks are the publishers' files and are not redistributed, so the
packaged extracts cannot be re-derived in CI (``tests/rules/
test_packaged_rules_integrity.py`` is the offline guard on those). These tests
pin the importer's own behaviour against throwaway workbooks built here, laid
out on the publishers' column positions.

Key responsibilities:
- Only rows naming a credit-risk table are extracted; the table filter is a
  prefix match on any of a rule's table columns.
- Scope cells keep their ids VERBATIM — a legacy 3-digit id is flagged, never
  zero-padded onto the 4-digit grid.
- Status flags are derived per publisher, and ``("live",)`` only when none apply.
- Serialisation is deterministic and pure ASCII, so re-importing an unchanged
  workbook reproduces an extract byte for byte — which is what makes
  ``is_extract_current`` a meaningful check.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from rwa_filer.rules import importer

EBA_WIDTH = 25
BOE_WIDTH = 21


def _eba_row(**cells: Any) -> list[Any]:
    """One EBA sheet row, addressed by the importer's own column constants."""
    row: list[Any] = [None] * EBA_WIDTH
    positions = {
        "id": importer.EBA_COL_ID,
        "deactivated": importer.EBA_COL_DEACTIVATED,
        "reactivated": importer.EBA_COL_REACTIVATED,
        "deleted": importer.EBA_COL_DELETED,
        "not_in_xbrl": importer.EBA_COL_NOT_IN_XBRL,
        "type": importer.EBA_COL_TYPE,
        "severity": importer.EBA_COL_SEVERITY,
        "table": importer.EBA_COL_TABLES[0],
        "table2": importer.EBA_COL_TABLES[1],
        "rows": importer.EBA_COL_ROWS,
        "columns": importer.EBA_COL_COLUMNS,
        "sheets": importer.EBA_COL_SHEETS,
        "formula": importer.EBA_COL_FORMULA,
        "if_missing": importer.EBA_COL_IF_VALUE_MISSING,
        "arithmetic": importer.EBA_COL_ARITHMETIC,
        "narrative": importer.EBA_COL_NARRATIVE,
    }
    for name, value in cells.items():
        row[positions[name]] = value
    return row


def _boe_row(**cells: Any) -> list[Any]:
    """One BoE sheet row, addressed by the importer's own column constants."""
    row: list[Any] = [None] * BOE_WIDTH
    # The owner column leads every real row, and a row without it is skipped as
    # blank — so the builder always fills it.
    row[importer.BOE_COL_OWNER] = "BoE"
    positions = {
        "id": importer.BOE_COL_RULE_CODE,
        "scope": importer.BOE_COL_SCOPE,
        "expression_raw": importer.BOE_COL_EXPRESSION,
        "expression": importer.BOE_COL_SIMPLE_EXPRESSION,
        "in_xbrl": importer.BOE_COL_IN_XBRL,
        "deactivated": importer.BOE_COL_DEACTIVATED,
        "label": importer.BOE_COL_LABEL,
        "severity": importer.BOE_COL_SEVERITY,
        "table": importer.BOE_COL_TABLES[0],
    }
    for name, value in cells.items():
        row[positions[name]] = value
    return row


def _write_workbook(path: Path, sheet: str, rows: list[list[Any]]) -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(["header"] * len(rows[0]))
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


@pytest.fixture
def eba_workbook(tmp_path: Path) -> Path:
    rows = [
        _eba_row(
            id="v0001_m",
            severity="Error",
            type="Manual",
            table="C 07.00.a",
            rows="(0010;0020)",
            columns="(All)",
            formula="{c0010} = {c0020}",
            if_missing="Treat as zero/empty string",
            arithmetic="Interval",
            narrative="A credit-risk rule",
        ),
        _eba_row(
            id="v0002_m",
            severity="Warning",
            type="Manual",
            table="C 01.00",
            table2="C 08.01.a",
            rows="(010;020)",
            formula="{r010} >= {r020}",
            deactivated="2020-01-01",
            reactivated="2021-01-01",
        ),
        _eba_row(id="v0003_m", severity="Error", type="Manual", table="C 01.00", formula="x"),
        _eba_row(
            id="v0004_m", severity="Error", type="Manual", table="C 02.00", deleted="2022-06-30"
        ),
    ]
    return _write_workbook(tmp_path / "eba-rules.xlsx", importer.EBA_SHEET, rows)


@pytest.fixture
def boe_workbook(tmp_path: Path) -> Path:
    rows = [
        _boe_row(
            id="boe_b0001",
            table="OF07.00.01.01",
            scope="scope({t: OF07.00.01.01, r:0010, z:0002;0003})",
            expression_raw="{t: OF07.00.01.01, c: 0010, dv: 0} i= {t: OF07.00.01.01, c: 0020}",
            expression="{c: 0010} = {c: 0020}",
            in_xbrl="Yes",
            deactivated="No",
            severity="ERROR - PRA001|",
            label="SHORT_LABEL(en) - A short label|DESCRIPTION(en) - Mirrors v1234_m|",
        ),
        _boe_row(
            id="boe_b0002",
            table="OF08.01.01.01",
            expression="{c: 0010} >= 0",
            in_xbrl="No",
            deactivated="Yes",
            severity="WARNING - PRA001;PRA116|",
        ),
        _boe_row(id="boe_b0003", table="LV47.00.00.01", expression="x", severity="ERROR|"),
    ]
    return _write_workbook(tmp_path / "boe-rules.xlsx", importer.BOE_SHEET, rows)


# ---------------------------------------------------------------------------
# EBA
# ---------------------------------------------------------------------------


def test_eba_extract_keeps_only_rules_naming_a_credit_risk_table(eba_workbook: Path) -> None:
    # Act
    payload = importer.extract_eba(eba_workbook)

    # Assert — v0003_m names only C 01.00 and is dropped; v0002_m matches on its
    # SECOND table column, so the filter is "any table", not "the first".
    assert [rule["id"] for rule in payload["rules"]] == ["v0001_m", "v0002_m", "v0004_m"]
    assert payload["filter"]["matched"] == 3


def test_eba_scope_ids_are_kept_verbatim_and_legacy_ids_flagged(eba_workbook: Path) -> None:
    # Act
    rules = {rule["id"]: rule for rule in importer.extract_eba(eba_workbook)["rules"]}

    # Assert
    assert rules["v0001_m"]["rows"] == ["0010", "0020"]
    assert rules["v0001_m"]["rows_scope"] == "list"
    assert rules["v0001_m"]["columns_scope"] == "all"
    assert rules["v0001_m"]["sheets_scope"] == "none"
    assert rules["v0001_m"]["has_legacy_ids"] is False
    assert rules["v0002_m"]["rows"] == ["010", "020"], "a 3-digit id must not be zero-padded"
    assert rules["v0002_m"]["has_legacy_ids"] is True


def test_eba_status_flags_and_liveness_tallies(eba_workbook: Path) -> None:
    # Act
    payload = importer.extract_eba(eba_workbook)
    rules = {rule["id"]: rule for rule in payload["rules"]}

    # Assert
    assert rules["v0001_m"]["status"] == ["live"]
    assert rules["v0002_m"]["status"] == ["deactivated"]
    assert rules["v0002_m"]["reactivated_on"] == "2021-01-01"
    assert rules["v0004_m"]["status"] == ["deleted"]
    assert payload["filter"]["live"] == 1
    assert payload["filter"]["live_or_reactivated"] == 2


def test_eba_source_block_names_the_workbook_it_was_read_from(eba_workbook: Path) -> None:
    # Act
    source = importer.extract_eba(eba_workbook)["source"]

    # Assert
    assert (source["publisher"], source["framework"]) == ("EBA", "CRR")
    assert source["file"] == "eba-rules.xlsx"
    assert source["sheet"] == importer.EBA_SHEET


# ---------------------------------------------------------------------------
# BoE
# ---------------------------------------------------------------------------


def test_boe_extract_keeps_only_rules_naming_a_credit_risk_table(boe_workbook: Path) -> None:
    # Act
    payload = importer.extract_boe(boe_workbook)

    # Assert — the leverage rule (LV47) is outside the credit-risk prefixes.
    assert [rule["id"] for rule in payload["rules"]] == ["boe_b0001", "boe_b0002"]


def test_boe_severity_cell_splits_into_severity_and_modules(boe_workbook: Path) -> None:
    # Act
    rules = {rule["id"]: rule for rule in importer.extract_boe(boe_workbook)["rules"]}

    # Assert
    assert rules["boe_b0001"]["severity"] == "ERROR"
    assert rules["boe_b0001"]["severity_modules"] == ["PRA001"]
    assert rules["boe_b0002"]["severity"] == "WARNING"
    assert rules["boe_b0002"]["severity_modules"] == ["PRA001", "PRA116"]


def test_boe_labels_and_eba_equivalent_are_parsed_from_the_label_cell(boe_workbook: Path) -> None:
    # Act
    rule = importer.extract_boe(boe_workbook)["rules"][0]

    # Assert
    assert rule["short_label"] == "A short label"
    assert rule["description"] == "Mirrors v1234_m"
    assert rule["eba_equivalent"] == "v1234_m"


def test_boe_status_flags_follow_the_deactivated_and_in_xbrl_columns(boe_workbook: Path) -> None:
    # Act
    payload = importer.extract_boe(boe_workbook)
    rules = {rule["id"]: rule for rule in payload["rules"]}

    # Assert
    assert rules["boe_b0001"]["status"] == ["live"]
    assert rules["boe_b0002"]["status"] == ["deactivated", "not_in_xbrl"]
    assert payload["filter"] == {
        "table_prefixes": list(importer.BOE_TABLE_PREFIXES),
        "matched": 2,
        "live": 1,
        "not_deactivated": 1,
        "in_xbrl": 1,
    }


def test_boe_raw_expression_survives_alongside_the_simplified_one(boe_workbook: Path) -> None:
    """The raw form is the only carrier of ``dv:`` and the ``i=`` interval operator."""
    # Act
    rule = importer.extract_boe(boe_workbook)["rules"][0]

    # Assert
    assert "dv: 0" in rule["expression_raw"] and "i=" in rule["expression_raw"]
    assert rule["expression"] == "{c: 0010} = {c: 0020}"


# ---------------------------------------------------------------------------
# Dispatch and determinism
# ---------------------------------------------------------------------------


def test_extract_dispatches_on_the_publisher_key(eba_workbook: Path, boe_workbook: Path) -> None:
    # Act / Assert
    assert importer.extract("eba", eba_workbook)["source"]["publisher"] == "EBA"
    assert importer.extract("boe", boe_workbook)["source"]["publisher"] == "BoE"


def test_extract_rejects_an_unknown_publisher(eba_workbook: Path) -> None:
    with pytest.raises(ValueError, match="Unknown rule publisher"):
        importer.extract("esma", eba_workbook)


def test_a_workbook_not_laid_out_for_the_publisher_is_refused(
    boe_workbook: Path, tmp_path: Path
) -> None:
    # Arrange — an empty rule sheet, and each publisher's sheet one column short of
    # its layout (the fixtures above, at full width, are read)
    empty = Workbook()
    empty.active.title = importer.BOE_SHEET
    empty.save(tmp_path / "empty.xlsx")
    eba_short = _write_workbook(
        tmp_path / "eba.xlsx", importer.EBA_SHEET, [_eba_row(id="v1", table="C 07.00")[:-1]]
    )
    boe_short = _write_workbook(
        tmp_path / "boe.xlsx", importer.BOE_SHEET, [_boe_row(id="b1", table="OF07")[:-1]]
    )

    # Act / Assert
    with pytest.raises(ValueError, match=r"not the EBA rule workbook: it has no sheet 'v3\.0"):
        importer.extract(importer.PUBLISHER_EBA, boe_workbook)
    with pytest.raises(ValueError, match="sheet 'banking_reporting' is empty"):
        importer.extract(importer.PUBLISHER_BOE, tmp_path / "empty.xlsx")
    with pytest.raises(ValueError, match=f"has {EBA_WIDTH - 1} columns.*across {EBA_WIDTH}"):
        importer.extract(importer.PUBLISHER_EBA, eba_short)
    with pytest.raises(ValueError, match=f"has {BOE_WIDTH - 1} columns.*across {BOE_WIDTH}"):
        importer.extract(importer.PUBLISHER_BOE, boe_short)


def test_serialisation_is_deterministic_and_pure_ascii(boe_workbook: Path) -> None:
    # Arrange — a label carrying a typographic dash, as the real workbooks do.
    payload = importer.extract_boe(boe_workbook)
    payload["rules"][0]["short_label"] = "A label – with a dash"

    # Act
    first = importer.dump_json(payload)
    second = importer.dump_json(importer.extract_boe(boe_workbook) | {"rules": payload["rules"]})

    # Assert
    assert first == second
    assert first.isascii()
    assert first.endswith("\n")


def test_a_written_extract_is_current_and_an_edited_one_is_not(
    eba_workbook: Path, tmp_path: Path
) -> None:
    # Arrange
    payload = importer.extract_eba(eba_workbook)
    target = tmp_path / "out" / "extract.json"

    # Act
    importer.write_extract(payload, target)
    written = target.read_text(encoding="utf-8")

    # Assert
    assert importer.is_extract_current(payload, written)
    assert not importer.is_extract_current(payload, written.replace("v0001_m", "v0001_x"))
    assert not importer.is_extract_current(payload, None)


def test_without_the_excel_extra_the_error_says_how_to_run_with_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange — openpyxl unimportable, as in an environment without the extra
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    # Act
    with pytest.raises(ModuleNotFoundError) as raised:
        importer.extract_boe(tmp_path / "rules.xlsx")

    # Assert — the uv remedies, spelt so they can be copied, and no pip
    message = str(raised.value)
    assert 'uvx "rwa-filer[excel]@latest" rules import' in message
    assert 'uv add "rwa-filer[excel]"' in message
    assert "pip install" not in message
