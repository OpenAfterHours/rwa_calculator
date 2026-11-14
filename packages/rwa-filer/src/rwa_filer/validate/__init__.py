"""
Evaluate the published supervisory validation rules against a return.

Pipeline position:
    TemplateIndex  ->  evaluate_index  ->  ValidationReport  ->  findings_for
        ->  list[Finding]

Key responsibilities:
- Evaluate every currently-enforced rule for a framework against the templates a
  return carries, honouring the publishers' own liveness, missing-value and
  rounding-tolerance semantics.
- Report breaks as ``VAL001`` (Error — blocks the submission) / ``VAL002``
  (Warning) findings and insufficient coverage as ``VAL003``; never raise for a
  data condition.

Module map:
- ``index``    — the ``TemplateIndex`` a return is read through; expand a rule
                 into concrete coordinates
- ``evaluate`` — parse and evaluate one rule at one coordinate
- ``checker``  — the public entry points and the report / finding shapes

References:
- COREP Annex II (CRR); PRA PS1/26 Annex II (Basel 3.1)
"""

from __future__ import annotations

from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    MAX_RECORDED_FAILURES,
    CoverageShortfall,
    Finding,
    RuleOutcome,
    ValidationReport,
    check_index,
    evaluate_index,
    findings_for,
)
from rwa_filer.validate.evaluate import (
    GEOGRAPHY_TOTAL_SHEET,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
    CoordinateOutcome,
)
from rwa_filer.validate.index import (
    SINGLE_SHEET,
    Coordinate,
    SheetCode,
    TableBinding,
    TemplateIndex,
    derive_variant_columns,
    expand_rule,
    resolve_sheet_codes,
)

__all__ = [
    "COVERAGE_NO_RULE_EXECUTED",
    "COVERAGE_TEMPLATE_NOT_COVERED",
    "FINDING_COVERAGE_INSUFFICIENT",
    "FINDING_RULE_ERROR",
    "FINDING_RULE_WARNING",
    "GEOGRAPHY_TOTAL_SHEET",
    "MAX_RECORDED_FAILURES",
    "SINGLE_SHEET",
    "STATUS_FAIL",
    "STATUS_NOT_EVALUATED",
    "STATUS_PASS",
    "STATUS_VACUOUS",
    "Coordinate",
    "CoordinateOutcome",
    "CoverageShortfall",
    "Finding",
    "RuleOutcome",
    "SheetCode",
    "TableBinding",
    "TemplateIndex",
    "ValidationReport",
    "check_index",
    "derive_variant_columns",
    "evaluate_index",
    "expand_rule",
    "findings_for",
    "resolve_sheet_codes",
]
