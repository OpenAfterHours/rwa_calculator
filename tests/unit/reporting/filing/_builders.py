"""
Shared builders for the filing-adapter tests.

These tests exercise the ADAPTER — our table bindings and sheet maps, and the
rule engine reached through them — not the regulatory findings: every frame here
is a hand-built synthetic template, never real pipeline output. The rule engine
itself (grammar, evaluation semantics, the checker and its coverage guard) is
tested in ``packages/rwa-filer/tests`` against a sample source; what is pinned
here is that OUR bundles reach it correctly.

Key responsibilities:
- ``build_frame`` — one template frame from a ``{row_ref: {column_ref: value}}``
  literal, preserving null as null (never as 0.0).
- ``build_corep`` / ``build_index`` — a ``COREPTemplateBundle`` carrying only the
  templates a test names, indexed through the production binding path.
- ``build_rule`` — a ``ValidationRule`` with neutral defaults, so each test
  overrides only the one field it is about.

References:
- src/rwa_calc/reporting/filing/ — the adapter under test
- packages/rwa-filer/src/rwa_filer/validate/ — the engine it drives
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.filing.bindings import build_template_index
from rwa_filer.rules.catalogue import (
    ARITHMETIC_INTERVAL,
    FRAMEWORK_CRR,
    MISSING_ZERO,
    SEVERITY_ERROR,
    ValidationRule,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_filer.validate.index import TemplateIndex

#: A cell map: ``{row_ref: {column_ref: value}}``. ``None`` means "reported the
#: row but left the cell blank" — which is NOT the same as omitting the column.
type Cells = Mapping[str, Mapping[str, float | None]]


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
