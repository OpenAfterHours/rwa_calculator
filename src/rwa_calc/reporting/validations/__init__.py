"""
Published supervisory validation rules, evaluated against our generated estate.

Pipeline position:
    COREPGenerator + Pillar3Generator  ->  check_supervisory_validations
        ->  list[CalculationError]

Key responsibilities:
- Ship the two committed rule extracts as PACKAGE DATA (``rules/*.json``), so an
  installed wheel carries the supervisor's checks without the repo checkout.
- Evaluate every currently-enforced rule for a framework against the templates a
  run produced, honouring the publishers' own liveness, missing-value and
  rounding-tolerance semantics.
- Surface breaks on the error channel as ``VAL001`` (Error — blocks the
  submission) / ``VAL002`` (Warning) findings, never as exceptions.

Module map:
- ``rules``    — load and normalise the packaged JSON onto one rule shape
- ``scope``    — bind publisher table/sheet codes to our frames; expand a rule
                 into concrete coordinates (owns the cited sheet-index map)
- ``evaluate`` — parse and evaluate one rule at one coordinate
- ``checker``  — the public entry points

References:
- docs/reference/validation-rules/index.md — provenance, schema, formula grammar
- COREP Annex II (CRR); PRA PS1/26 Annex II (Basel 3.1)
"""

from __future__ import annotations

from rwa_calc.reporting.validations.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    MAX_RECORDED_FAILURES,
    CoverageShortfall,
    RuleOutcome,
    ValidationReport,
    check_supervisory_validations,
    evaluate_all,
)
from rwa_calc.reporting.validations.evaluate import (
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
    CoordinateOutcome,
)
from rwa_calc.reporting.validations.rules import (
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleSet,
    ValidationRule,
    is_currently_enforced,
    load_rules,
    rules_for_tables,
)
from rwa_calc.reporting.validations.scope import (
    SHEET_INDEX_MAPS,
    SINGLE_SHEET,
    Coordinate,
    SheetCode,
    TemplateIndex,
    build_template_index,
    expand_rule,
    resolve_sheet_codes,
)

__all__ = [
    "COVERAGE_NO_RULE_EXECUTED",
    "COVERAGE_TEMPLATE_NOT_COVERED",
    "SINGLE_SHEET",
    "FRAMEWORK_BASEL_3_1",
    "FRAMEWORK_CRR",
    "MAX_RECORDED_FAILURES",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "SHEET_INDEX_MAPS",
    "STATUS_FAIL",
    "STATUS_NOT_EVALUATED",
    "STATUS_PASS",
    "STATUS_VACUOUS",
    "Coordinate",
    "CoordinateOutcome",
    "CoverageShortfall",
    "RuleOutcome",
    "RuleSet",
    "SheetCode",
    "TemplateIndex",
    "ValidationReport",
    "ValidationRule",
    "build_template_index",
    "check_supervisory_validations",
    "evaluate_all",
    "expand_rule",
    "is_currently_enforced",
    "load_rules",
    "resolve_sheet_codes",
    "rules_for_tables",
]
