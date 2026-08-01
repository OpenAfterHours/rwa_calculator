"""
Shared builders for the supervisory validation-rule evaluator tests.

These tests exercise the EVALUATOR, not the regulatory findings: every frame
here is a hand-built synthetic template, never real pipeline output. A rule
misread by one cell is a false negative on a submission gate, so the machinery
is pinned against figures a reader can verify by eye.

Key responsibilities:
- ``build_frame`` — one template frame from a ``{row_ref: {column_ref: value}}``
  literal, preserving null as null (never as 0.0).
- ``build_corep`` / ``build_index`` — a ``COREPTemplateBundle`` carrying only the
  templates a test names, indexed through the production binding path.
- ``build_rule`` — a ``ValidationRule`` with neutral defaults, so each test
  overrides only the one field it is about.
- ``evaluate`` — parse one expression and evaluate it at one coordinate.
- ``raw_extract`` — the packaged JSON as shipped, for tests that pin the
  normalisation of a publisher field against its raw value.

References:
- src/rwa_calc/reporting/validations/ — the module under test
"""

from __future__ import annotations

import json
from importlib import resources
from typing import TYPE_CHECKING, Any

import polars as pl

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.validations.evaluate import evaluate_at, parse_expression
from rwa_calc.reporting.validations.rules import (
    ARITHMETIC_INTERVAL,
    FRAMEWORK_CRR,
    MISSING_ZERO,
    SEVERITY_ERROR,
    ValidationRule,
)
from rwa_calc.reporting.validations.scope import (
    SINGLE_SHEET,
    Coordinate,
    build_template_index,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.validations.evaluate import CoordinateOutcome
    from rwa_calc.reporting.validations.scope import TemplateIndex

#: A cell map: ``{row_ref: {column_ref: value}}``. ``None`` means "reported the
#: row but left the cell blank" — which is NOT the same as omitting the column.
type Cells = Mapping[str, Mapping[str, float | None]]


#: Packaged extract filenames, mirrored from ``rules._EXTRACT_FILES`` so a
#: renamed extract fails the integrity test rather than silently reading nothing.
EXTRACT_FILES: dict[str, str] = {
    FRAMEWORK_CRR: "crr-eba-v3.0-credit-risk.json",
    "BASEL_3_1": "basel31-boe-v4.0.0-credit-risk.json",
}


def _extract_file(framework: str):
    """The packaged extract for ``framework``, as a traversable resource."""
    return resources.files("rwa_calc.reporting.validations").joinpath(
        "rules", EXTRACT_FILES[framework]
    )


def extract_bytes(framework: str) -> bytes:
    """Read the packaged rule extract as raw bytes, exactly as it ships."""
    return _extract_file(framework).read_bytes()


def raw_extract(framework: str) -> dict[str, Any]:
    """Parse the packaged extract, reading it with NO ``encoding=`` kwarg.

    The extracts are deliberately pure ASCII, so the platform default encoding
    (cp1252 on a Windows CI runner) can never mangle them. Omitting the kwarg
    here is the assertion, not an oversight.
    """
    return json.loads(_extract_file(framework).read_text())


def build_frame(cells: Cells) -> pl.DataFrame:
    """Build one generated-template frame from a ``{row: {column: value}}`` map.

    Column order follows first appearance; a row that omits a column another row
    carries gets a null there, mirroring how the generators emit a sparse
    template. Columns are Float64 even when every value is null, so the frame is
    schema-faithful to a real generated one.
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


def build_corep(framework: str = FRAMEWORK_CRR, **templates: Any) -> COREPTemplateBundle:
    """Build a ``COREPTemplateBundle`` carrying only the named templates.

    Every unnamed per-class template defaults to an empty dict — i.e. "this run
    did not emit that template", which is the condition the skip paths exist for.
    """
    templates.setdefault("c07_00", {})
    templates.setdefault("c08_01", {})
    templates.setdefault("c08_02", {})
    return COREPTemplateBundle(framework=framework, **templates)


def build_index(framework: str = FRAMEWORK_CRR, **templates: Any) -> TemplateIndex:
    """Index a synthetic bundle through the production binding path."""
    return build_template_index(build_corep(framework, **templates), None, framework)


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
