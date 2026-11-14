"""
Contract tests for the check catalogue (``scripts/export_check_catalogue.py``).

The catalogue is only worth handing to a reviewer if every sheet is a faithful
view of the code. These tests anchor each sheet to its source of truth
independently of the generator's own reading of it (`.claude/LESSONS.md` B3):
row counts against the loaded rule sets, schemas, registers and TOML tables; the
"not raised" and "no production call site" statements against a plain-text
search of ``src/rwa_calc``; and the written workbook against the in-memory
catalogue.

Key responsibilities:
- Every sheet holds exactly the population its source declares — no check is
  dropped and none is invented.
- Every claim the workbook makes about the code (a code is never raised, a
  family has no production caller) survives a text search that shares none of
  the generator's AST logic.
- The written .xlsx keeps identifiers as text ("0010" stays "0010") and holds
  one row per catalogue row.

References:
- scripts/export_check_catalogue.py
- docs/development/check-catalogue.md
"""

from __future__ import annotations

import io
import json
import re
import tokenize
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from scripts.export_check_catalogue import (
    CELL_REDERIVATION,
    CLASSIFICATION_TABLE,
    CONFIDENCE_SNAPSHOT,
    ERROR_CODE_PATTERN,
    ORACLE_VALUES,
    SRC_ROOT,
    build_catalogue,
    export_check_catalogue,
)

if TYPE_CHECKING:
    from scripts.export_check_catalogue import Catalogue, Sheet

#: Where the data table starts on every family sheet (heading rows above it).
_HEADER_ROW = 6


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return build_catalogue()


@pytest.fixture(scope="module")
def sheets(catalogue: Catalogue) -> dict[str, Sheet]:
    return {sheet.name: sheet for sheet in catalogue.sheets}


@pytest.fixture(scope="module")
def src_text() -> dict[str, str]:
    """Every module's raw source text."""
    return {
        path.relative_to(SRC_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in SRC_ROOT.rglob("*.py")
    }


@pytest.fixture(scope="module")
def src_code(src_text: dict[str, str]) -> dict[str, str]:
    """Every module's source with comments and string literals removed.

    Tokenised, not parsed: the generator reads ``src`` through ``ast``, so these
    tests read it another way. A comment that names a function is not a call,
    and a docstring that names a constant is not a reference.
    """
    return {module: _code_only(text) for module, text in src_text.items()}


def _code_only(text: str) -> str:
    dropped = {tokenize.COMMENT, tokenize.STRING, tokenize.FSTRING_MIDDLE}
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return " ".join(token.string for token in tokens if token.type not in dropped)


def _column(sheet: Sheet, header: str) -> list[object]:
    index = [column.header for column in sheet.columns].index(header)
    return [row[index] for row in sheet.rows]


# =============================================================================
# Error codes
# =============================================================================


def test_every_code_declared_in_contracts_errors_has_a_row(sheets: dict[str, Sheet]) -> None:
    # Arrange
    from rwa_calc.contracts import errors

    declared = {
        value
        for name, value in vars(errors).items()
        if name.startswith("ERROR_") and isinstance(value, str) and ERROR_CODE_PATTERN.match(value)
    }

    # Act
    listed = set(_column(sheets["Error codes"], "Code"))

    # Assert
    assert declared, "contracts/errors.py declared no codes - the anchor is broken"
    assert declared - listed == set()


def test_a_code_shaped_identifier_that_is_not_an_error_code_is_not_listed(
    sheets: dict[str, Sheet],
) -> None:
    # Arrange — the filing module id has exactly the shape of an error code.
    from rwa_calc.reporting.filing.canonical import FILING_MODULE

    assert ERROR_CODE_PATTERN.match(FILING_MODULE), "the guard no longer exercises the shape"

    # Act
    listed = set(_column(sheets["Error codes"], "Code"))

    # Assert
    assert FILING_MODULE not in listed


def test_a_code_reported_as_declared_only_is_named_nowhere_else_in_src(
    sheets: dict[str, Sheet], src_code: dict[str, str]
) -> None:
    # Arrange
    sheet = sheets["Error codes"]
    statuses = _column(sheet, "Raised in")
    constants = _column(sheet, "Constant")
    declared_only = [
        constant
        for constant, status in zip(constants, statuses, strict=True)
        if str(status).startswith("Not raised: declared")
    ]

    # Act — a plain word search, sharing nothing with the generator's AST walk.
    occurrences = {
        constant: sum(
            len(re.findall(rf"\b{re.escape(str(constant))}\b", text)) for text in src_code.values()
        )
        for constant in declared_only
    }

    # Assert — the declaration itself is the one occurrence.
    assert {constant: count for constant, count in occurrences.items() if count != 1} == {}


def test_a_code_reported_as_raised_appears_in_every_module_it_is_raised_in(
    sheets: dict[str, Sheet], src_text: dict[str, str]
) -> None:
    # Arrange
    sheet = sheets["Error codes"]
    rows = zip(
        _column(sheet, "Code"),
        _column(sheet, "Constant"),
        _column(sheet, "Raised in"),
        strict=True,
    )
    raised = [
        (code, constant, str(status).removeprefix("Raised in ").split("; "))
        for code, constant, status in rows
        if str(status).startswith("Raised in ")
    ]

    # Act
    missing = [
        (code, module)
        for code, constant, modules in raised
        for module in modules
        if str(constant) not in src_text[module] and f'"{code}"' not in src_text[module]
    ]

    # Assert
    assert raised, "no code is reported as raised - the raise-site scan is broken"
    assert missing == []


# =============================================================================
# Runtime families: populations
# =============================================================================


def test_input_columns_hold_every_declared_column(sheets: dict[str, Sheet]) -> None:
    from rwa_calc.data.schemas import TABLE_SCHEMAS

    expected = {(table, column) for table, schema in TABLE_SCHEMAS.items() for column in schema}
    sheet = sheets["Input columns"]

    listed = set(zip(_column(sheet, "Table"), _column(sheet, "Column"), strict=True))

    assert listed == expected
    assert len(sheet.rows) == len(expected)


@pytest.mark.parametrize(("framework", "label"), [("CRR", "CRR"), ("BASEL_3_1", "Basel 3.1")])
def test_template_rule_sheet_holds_every_published_rule(
    sheets: dict[str, Sheet], framework: str, label: str
) -> None:
    from rwa_filer.rules import load_rules

    rule_set = load_rules(framework)
    sheet = sheets[f"Template rules - {label}"]

    ids = _column(sheet, "Rule")
    enforced = [
        rule for rule, flag in zip(ids, _column(sheet, "Enforced"), strict=True) if flag == "Yes"
    ]

    assert sorted(ids) == sorted(rule.rule_id for rule in rule_set.rules)
    assert sorted(enforced) == sorted(rule.rule_id for rule in rule_set.enforced)


def test_filing_rule_sheet_holds_every_rule_the_gateway_enforces(sheets: dict[str, Sheet]) -> None:
    from rwa_calc.reporting.filing.canonical import FILING_MODULE
    from rwa_filer.boe.catalogue import rulebook_for_module

    enforced = rulebook_for_module(FILING_MODULE).enforced(FILING_MODULE)

    ids = _column(sheets[f"Filing rules - {FILING_MODULE}"], "Rule")

    assert sorted(ids) == sorted(rule.rule_id for rule in enforced)


def test_tie_out_sheet_holds_every_tie_and_every_non_comparable_pair(
    sheets: dict[str, Sheet],
) -> None:
    from rwa_calc.reporting.tieouts import NON_COMPARABLE_PAIRS, TIE_OUTS

    names = [name for name in _column(sheets["Tie-outs"], "Name") if name]

    assert sorted(names) == sorted(tie.name for tie in TIE_OUTS)
    assert len(sheets["Tie-outs"].rows) == len(TIE_OUTS) + len(NON_COMPARABLE_PAIRS)


@pytest.mark.parametrize(
    ("sheet_name", "function"),
    [
        ("Input columns", "validate_bundle_values"),
        ("Template rules - CRR", "evaluate_all"),
        ("Tie-outs", "check_cross_template_consistency"),
    ],
)
def test_where_it_runs_agrees_with_a_text_search_of_src(
    sheets: dict[str, Sheet], src_code: dict[str, str], sheet_name: str, function: str
) -> None:
    # Arrange — modules that call the function, by text, excluding its definer.
    callers = {
        module
        for module, text in src_code.items()
        if re.search(rf"\b{function} \(", text) and not re.search(rf"\bdef {function} \(", text)
    }

    # Act
    runs = sheets[sheet_name].runs

    # Assert — "no production call site" exactly when the text search finds none,
    # and otherwise every caller the text search finds is named.
    if not callers:
        assert runs.startswith("No production call site"), runs
    else:
        assert all(module in runs for module in callers), (callers, runs)


# =============================================================================
# Test-estate evidence: populations
# =============================================================================


def test_oracle_sheet_holds_every_case_and_marks_every_parked_disagreement(
    sheets: dict[str, Sheet],
) -> None:
    from tests.oracle.test_oracle import KNOWN_DISAGREEMENTS

    cases = json.loads(ORACLE_VALUES.read_text(encoding="utf-8"))["oracles"]
    sheet = sheets["Oracle cases"]

    parked = [
        case
        for case, status in zip(_column(sheet, "Case"), _column(sheet, "Status"), strict=True)
        if str(status).startswith("Known disagreement")
    ]

    assert sorted(_column(sheet, "Case")) == sorted(case["exposure_id"] for case in cases)
    assert sorted(parked) == sorted(KNOWN_DISAGREEMENTS)


def test_classification_sheet_holds_every_rule_exclusion_and_disagreement(
    sheets: dict[str, Sheet],
) -> None:
    table = tomllib.loads(CLASSIFICATION_TABLE.read_text(encoding="utf-8"))
    expected = sorted(
        entry["id"] for value in table.values() if isinstance(value, list) for entry in value
    )

    assert sorted(_column(sheets["Classification table"], "ID")) == expected


def test_cell_rederivation_sheet_holds_every_cell(sheets: dict[str, Sheet]) -> None:
    cells = tomllib.loads(CELL_REDERIVATION.read_text(encoding="utf-8"))["cell"]

    assert sorted(_column(sheets["Cell re-derivations"], "ID")) == sorted(c["id"] for c in cells)


def test_article_coverage_sheet_holds_every_article(sheets: dict[str, Sheet]) -> None:
    articles = json.loads(CONFIDENCE_SNAPSHOT.read_text(encoding="utf-8"))["articles"]

    listed = zip(
        _column(sheets["Article coverage"], "Framework"),
        _column(sheets["Article coverage"], "Article"),
        strict=True,
    )

    assert sorted(listed) == sorted((a["framework"], a["article"]) for a in articles)


def test_invariant_sheet_lists_every_property_test_function(sheets: dict[str, Sheet]) -> None:
    properties = Path(__file__).resolve().parent.parent / "properties"
    expected = {
        name
        for path in properties.glob("test_*.py")
        for name in re.findall(r"^\s*def (test_\w+)\(", path.read_text(encoding="utf-8"), re.M)
    }

    assert set(_column(sheets["Invariant tests"], "Test")) == expected


# =============================================================================
# The written workbook
# =============================================================================


def test_written_workbook_holds_every_sheet_row_and_keeps_identifiers_as_text(
    catalogue: Catalogue, tmp_path: Path
) -> None:
    # Arrange
    import openpyxl

    path = export_check_catalogue(catalogue, tmp_path / "catalogue.xlsx")

    # Act
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        names = workbook.sheetnames
        row_counts = {
            sheet.name: sum(
                1 for _ in workbook[sheet.name].iter_rows(min_row=_HEADER_ROW + 1, values_only=True)
            )
            for sheet in catalogue.sheets
        }
        cell_rows = [
            row[3]
            for row in workbook["Cell re-derivations"].iter_rows(
                min_row=_HEADER_ROW + 1, values_only=True
            )
        ]
    finally:
        workbook.close()

    # Assert
    assert names == ["Read me", *(sheet.name for sheet in catalogue.sheets)]
    assert row_counts == {sheet.name: len(sheet.rows) for sheet in catalogue.sheets}
    assert "0010" in cell_rows, "a zero-padded row id was written as a number"
