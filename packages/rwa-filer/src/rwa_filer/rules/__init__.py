"""
Published supervisory validation rules, as normalised package data.

Module map:
- ``catalogue`` — load and normalise the packaged JSON extracts onto one
  ``ValidationRule`` shape
- ``importer``  — rebuild an extract from the publisher's rule workbook
- ``data/``     — the committed extracts (package data, not importable)

References:
- EBA DPM 3.0(3.0.1) validation rules (CRR framework)
- BoE banking_reporting v4.0.0 validation rules (PS1/26 / Basel 3.1 framework)
"""

from __future__ import annotations

from rwa_filer.rules.catalogue import (
    ARITHMETIC_INTERVAL,
    ARITHMETIC_NOT_APPLICABLE,
    ARITHMETIC_POINT,
    EXTRACT_FILES,
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    MISSING_SKIP,
    MISSING_ZERO,
    SCOPE_ALL,
    SCOPE_LIST,
    SCOPE_NONE,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleScope,
    RuleSet,
    TableScope,
    ValidationRule,
    build_rule_reference,
    extract_resource,
    is_currently_enforced,
    load_rules,
    rules_for_tables,
)

__all__ = [
    "ARITHMETIC_INTERVAL",
    "ARITHMETIC_NOT_APPLICABLE",
    "ARITHMETIC_POINT",
    "EXTRACT_FILES",
    "FRAMEWORK_BASEL_3_1",
    "FRAMEWORK_CRR",
    "MISSING_SKIP",
    "MISSING_ZERO",
    "SCOPE_ALL",
    "SCOPE_LIST",
    "SCOPE_NONE",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "RuleScope",
    "RuleSet",
    "TableScope",
    "ValidationRule",
    "build_rule_reference",
    "extract_resource",
    "is_currently_enforced",
    "load_rules",
    "rules_for_tables",
]
