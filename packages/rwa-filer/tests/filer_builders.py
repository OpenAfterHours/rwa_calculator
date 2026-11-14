"""
Shared builders for the rule-engine tests.

These tests exercise the EVALUATOR, not any regulatory finding: every frame here
is a hand-built synthetic template, never real output. A rule misread by one
cell is a false negative on a submission gate, so the machinery is pinned
against figures a reader can verify by eye.

The engine reads a return through a ``TemplateIndex`` whose table bindings and
sheet maps are supplied by the SOURCE of the figures; this package ships none.
``SAMPLE_TABLES`` / ``SAMPLE_SHEET_MAPS`` below are a sample source for these
tests: one that keys its sheets by exposure-class NAME and is in places coarser
than the publisher's z-axis, which is the case the closure logic exists for.
They are test data, not a statement about any real source.

Key responsibilities:
- ``build_frame`` — one template frame from a ``{row_ref: {column_ref: value}}``
  literal, preserving null as null (never as 0.0).
- ``build_index`` — a ``TemplateIndex`` carrying only the templates a test names.
- ``build_rule`` — a ``ValidationRule`` with neutral defaults, so each test
  overrides only the one field it is about.
- ``evaluate`` — parse one expression and evaluate it at one coordinate.
- ``raw_extract`` — the packaged JSON as shipped, for tests that pin the
  normalisation of a publisher field against its raw value.
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING, Any

import polars as pl

from rwa_filer.rules.catalogue import (
    ARITHMETIC_INTERVAL,
    EXTRACT_FILES,
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    MISSING_ZERO,
    SEVERITY_ERROR,
    ValidationRule,
    extract_resource,
    load_rules,
)
from rwa_filer.validate.evaluate import evaluate_at, parse_expression
from rwa_filer.validate.index import (
    SINGLE_SHEET,
    Coordinate,
    SheetCode,
    TableBinding,
    TemplateIndex,
    derive_variant_columns,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_filer.validate.evaluate import CoordinateOutcome

#: A cell map: ``{row_ref: {column_ref: value}}``. ``None`` means "reported the
#: row but left the cell blank" — which is NOT the same as omitting the column.
type Cells = Mapping[str, Mapping[str, float | None]]

__all__ = [
    "EXTRACT_FILES",
    "SAMPLE_SHEET_MAPS",
    "SAMPLE_TABLES",
    "build_frame",
    "build_index",
    "build_rule",
    "evaluate",
    "evaluate_c02",
    "extract_bytes",
    "raw_extract",
]


# =============================================================================
# The sample source
# =============================================================================


def _sheet_map(*entries: tuple[str, tuple[str, ...]]) -> dict[str, SheetCode]:
    return {
        code: SheetCode(code, f"sample class {code}", keys, "test data") for code, keys in entries
    }


#: Publisher z-codes onto the sample source's class-named sheets. ``c08`` /
#: ``of08`` deliberately map several codes onto one key (the coarser axis), and
#: the total sheets carry no key at all.
SAMPLE_SHEET_MAPS: dict[str, dict[str, SheetCode]] = {
    "c07": _sheet_map(
        ("0001", ()),
        ("0002", ("central_govt_central_bank",)),
        ("0003", ("rgla",)),
        ("0004", ("pse",)),
        ("0005", ("mdb",)),
        ("0006", ("international_organisation",)),
        ("0007", ("institution",)),
        ("0008", ("corporate",)),
        ("0009", ("retail",)),
        ("0010", ("real_estate",)),
        ("0011", ("defaulted",)),
        ("0012", ("high_risk",)),
        ("0013", ("covered_bond",)),
        ("0014", ()),
        ("0015", ("ciu",)),
        ("0016", ("equity",)),
        ("0017", ("other",)),
    ),
    "of07": _sheet_map(
        ("0001", ()),
        ("0002", ("central_govt_central_bank",)),
        ("0003", ("rgla",)),
        ("0004", ("pse",)),
        ("0005", ("mdb",)),
        ("0006", ("international_organisation",)),
        ("0007", ("institution",)),
        ("0008", ("corporate",)),
        ("0009", ("retail",)),
        ("0010", ("real_estate",)),
        ("0011", ("defaulted",)),
        ("0012", ("high_risk",)),
        ("0013", ("covered_bond",)),
        ("0015", ("ciu",)),
        ("0016", ("equity",)),
        ("0017", ("other",)),
    ),
    "c08": _sheet_map(
        ("0001", ()),
        ("0002", ()),
        ("0003", ("central_govt_central_bank",)),
        ("0004", ("central_govt_central_bank",)),
        ("0005", ("institution",)),
        ("0006", ("institution",)),
        ("0007", ("corporate_sme",)),
        ("0008", ("corporate_sme",)),
        ("0009", ("specialised_lending",)),
        ("0010", ("specialised_lending",)),
        ("0011", ("corporate",)),
        ("0012", ("corporate",)),
        ("0013", ("retail_mortgage",)),
        ("0014", ("retail_mortgage",)),
        ("0015", ("retail_qrre",)),
        ("0016", ("retail_other",)),
        ("0017", ("retail_other",)),
    ),
    "of08": _sheet_map(
        ("0001", ()),
        ("0002", ()),
        ("0006", ("institution",)),
        ("0009", ("specialised_lending",)),
        ("0010", ("specialised_lending",)),
        ("0011", ("corporate",)),
        ("0012", ("corporate",)),
        ("0015", ("retail_qrre",)),
        ("0016", ("retail_other",)),
        ("0017", ("retail_other",)),
        ("0018", ("retail_mortgage",)),
        ("0019", ("retail_mortgage",)),
        ("0020", ("retail_mortgage",)),
        ("0021", ("retail_mortgage",)),
        ("0022", ("corporate",)),
        ("0023", ("corporate_sme",)),
        ("0024", ("corporate_sme",)),
    ),
}

_CRR_TABLES: dict[str, TableBinding] = {
    "C 02.00": TableBinding("c_02_00", per_sheet=False),
    "C 07.00.a": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 07.00.b": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 07.00.c": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 07.00.d": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 08.01.a": TableBinding("c08_01", per_sheet=True, sheet_map="c08"),
    "C 08.01.b": TableBinding("c08_01", per_sheet=True, sheet_map="c08"),
    "C 08.02": TableBinding("c08_02", per_sheet=True, sheet_map="c08"),
    "C 08.03": TableBinding("c08_03", per_sheet=True, sheet_map="c08"),
    "C 08.04": TableBinding("c08_04", per_sheet=True, sheet_map="c08"),
    "C 08.05": TableBinding("c08_05", per_sheet=True, sheet_map="c08"),
    "C 08.06": TableBinding("c08_06", per_sheet=True),
    "C 08.07": TableBinding("c08_07", per_sheet=False),
    "C 09.01.a": TableBinding("c09_01", per_sheet=True),
    "C 09.01.b": TableBinding("c09_01", per_sheet=True),
    "C 09.02": TableBinding("c09_02", per_sheet=True),
    "C 34.01.a": TableBinding("c34_01", per_sheet=False),
    "C 34.01.b": TableBinding("c34_01", per_sheet=False),
    "C 34.02": TableBinding("c34_02", per_sheet=True),
    "C 34.04": TableBinding("c34_04", per_sheet=False),
    "C 34.08.a": TableBinding("c34_08", per_sheet=False),
    "C 34.08.b": TableBinding("c34_08", per_sheet=False),
}

_B31_TABLES: dict[str, TableBinding] = {
    "OF02.00.01.01": TableBinding("c_02_00", per_sheet=False),
    "OF02.01.01.01": TableBinding("of_02_01", per_sheet=False),
    "OF02.01.01.02": TableBinding("of_02_01", per_sheet=False),
    "OF02.01.01.03": TableBinding("of_02_01", per_sheet=False),
    "OF07.00.01.01": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.02": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.03": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.04": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.05": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF08.01.01.01": TableBinding("c08_01", per_sheet=True, sheet_map="of08"),
    "OF08.01.01.02": TableBinding("c08_01", per_sheet=True, sheet_map="of08"),
    "OF08.02.01.01": TableBinding("c08_02", per_sheet=True, sheet_map="of08"),
    "OF08.03.01.01": TableBinding("c08_03", per_sheet=True, sheet_map="of08"),
    "C08.04.01.01": TableBinding("c08_04", per_sheet=True, sheet_map="of08"),
    "OF08.05.00.01": TableBinding("c08_05", per_sheet=True, sheet_map="of08"),
    "OF08.05.01.01": TableBinding("c08_05", per_sheet=True, sheet_map="of08"),
    "OF08.06.01.01": TableBinding("c08_06", per_sheet=True),
    "OF08.07.01.01": TableBinding("c08_07", per_sheet=False),
    "OF09.01.01.01": TableBinding("c09_01", per_sheet=True),
    "OF09.02.01.01": TableBinding("c09_02", per_sheet=True),
    "C34.01.01.01": TableBinding("c34_01", per_sheet=False),
    "C34.02.01.01": TableBinding("c34_02", per_sheet=True),
    "C34.04.01.01": TableBinding("c34_04", per_sheet=False),
    "C34.08.01.01": TableBinding("c34_08", per_sheet=False),
    "C34.08.01.02": TableBinding("c34_08", per_sheet=False),
}

#: Publisher table codes onto the sample source's frame groups, per framework.
SAMPLE_TABLES: dict[str, dict[str, TableBinding]] = {
    FRAMEWORK_CRR: _CRR_TABLES,
    FRAMEWORK_BASEL_3_1: _B31_TABLES,
}


@cache
def sample_bindings(framework: str) -> Mapping[str, TableBinding]:
    """The sample table map with each DPM variant restricted to its own columns."""
    base = SAMPLE_TABLES[framework]
    variant_columns = derive_variant_columns(load_rules(framework).enforced, base)
    return {
        table: (
            binding
            if table not in variant_columns
            else replace(binding, columns=variant_columns[table])
        )
        for table, binding in base.items()
    }


# =============================================================================
# Builders
# =============================================================================


def extract_bytes(framework: str) -> bytes:
    """Read the packaged rule extract as raw bytes, exactly as it ships."""
    return extract_resource(framework).read_bytes()


def raw_extract(framework: str) -> dict[str, Any]:
    """Parse the packaged extract, reading it with NO ``encoding=`` kwarg.

    The extracts are deliberately pure ASCII, so the platform default encoding
    (cp1252 on a Windows CI runner) can never mangle them. Omitting the kwarg
    here is the assertion, not an oversight.
    """
    return json.loads(extract_resource(framework).read_text())


def build_frame(cells: Cells) -> pl.DataFrame:
    """Build one template frame from a ``{row: {column: value}}`` map.

    Column order follows first appearance; a row that omits a column another row
    carries gets a null there, mirroring a sparse template. Columns are Float64
    even when every value is null, so the frame is schema-faithful to a real one.
    """
    columns: list[str] = []
    for row in cells.values():
        for column in row:
            if column not in columns:
                columns.append(column)
    data: dict[str, list[Any]] = {"row_ref": list(cells)}
    for column in columns:
        data[column] = [cells[row].get(column) for row in cells]
    schema: dict[str, Any] = {"row_ref": pl.String}
    schema.update(dict.fromkeys(columns, pl.Float64))
    return pl.DataFrame(data, schema=schema)


def build_index(framework: str = FRAMEWORK_CRR, **templates: Any) -> TemplateIndex:
    """Index the named templates through the sample source's bindings.

    A template passed as a DataFrame is a single-sheet template; one passed as a
    ``{sheet key: DataFrame}`` dict is per-sheet. An unnamed template — or an
    empty dict — is "this return does not carry that template", which is the
    condition the skip paths exist for.
    """
    frames: dict[str, dict[str, pl.DataFrame]] = {}
    for name, member in templates.items():
        if isinstance(member, pl.DataFrame):
            frames[name] = {SINGLE_SHEET: member}
        elif isinstance(member, dict) and member:
            frames[name] = dict(member)
    return TemplateIndex(
        framework=framework,
        frames=frames,
        bindings=sample_bindings(framework),
        sheet_maps=SAMPLE_SHEET_MAPS,
    )


def build_rule(**overrides: Any) -> ValidationRule:
    """Build a ``ValidationRule`` with neutral defaults.

    Defaults: a live EBA ERROR rule on ``C 02.00`` with no scope, zero-fill
    missing values and interval arithmetic. Each test overrides the single field
    whose behaviour it pins.
    """
    fields: dict[str, Any] = {
        "rule_id": "vTEST_m",
        "publisher": "EBA",
        "framework": FRAMEWORK_CRR,
        "severity": SEVERITY_ERROR,
        "rule_type": "Manual",
        "tables": ("C 02.00",),
        "expression": "{c0010} = {c0020}",
        "expression_raw": None,
        "table_scopes": (),
        "missing_value": MISSING_ZERO,
        "arithmetic": ARITHMETIC_INTERVAL,
        "prerequisites": (),
        "precondition": None,
        "where": None,
        "status": ("live",),
        "reactivated_on": None,
        "label": None,
    }
    fields.update(overrides)
    return ValidationRule(**fields)


def evaluate(
    expression: str | None,
    index: TemplateIndex,
    *,
    table: str = "C 02.00",
    sheet: str = SINGLE_SHEET,
    row: str | None = None,
    column: str | None = None,
    missing_value: str = MISSING_ZERO,
    arithmetic: str = ARITHMETIC_INTERVAL,
) -> CoordinateOutcome:
    """Parse one expression and evaluate it at one coordinate."""
    return evaluate_at(
        parse_expression(expression),
        Coordinate(table, sheet, row, column),
        index,
        missing_value=missing_value,
        arithmetic=arithmetic,
    )


def evaluate_c02(
    expression: str,
    cells: Cells,
    *,
    row: str | None = None,
    column: str | None = None,
    missing_value: str = MISSING_ZERO,
    arithmetic: str = ARITHMETIC_INTERVAL,
) -> CoordinateOutcome:
    """Evaluate an expression against a single-sheet ``C 02.00`` frame."""
    return evaluate(
        expression,
        build_index(c_02_00=build_frame(cells)),
        row=row,
        column=column,
        missing_value=missing_value,
        arithmetic=arithmetic,
    )
