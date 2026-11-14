"""
The validation report — one validated return, as text or as a JSON-ready record.

Pipeline position:
    CanonicalReturn + ReturnValidation  ->  to_record / render_text
        ->  the ``rwa-filer validate`` command, or a caller's own store

Key responsibilities:
- Say first, and unmistakably, whether anything blocks submission.
- Never let "no breaks" stand alone: the report always carries how many rules
  were executed, how many could not be, and why — because "0 broken" on a
  return where nothing ran is the answer that misleads.
- Keep the record self-contained: a reader holding only the JSON knows which
  entity, date, module and taxonomy version it describes.

References:
- rwa_filer.validate.returns — what a ``ReturnValidation`` holds
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rwa_filer import __version__
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, STATUS_PASS

if TYPE_CHECKING:
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.validate.checker import Finding
    from rwa_filer.validate.returns import ReturnValidation

#: Not-evaluated reasons quoted in the text summary (commonest first).
_REASONS_SHOWN = 5


def to_record(ret: CanonicalReturn, validation: ReturnValidation) -> dict[str, Any]:
    """A JSON-ready record of one validated return.

    The record holds the verdict, the counts behind it, every finding, and one
    line per rule that did not simply pass.
    """
    report = validation.report
    info = validation.pack.info
    return {
        "generator": f"rwa-filer {__version__}",
        "header": ret.header.as_fields(),
        "taxonomy": {
            "module": info.module,
            "version": info.version,
            "entry_point": info.entry_point,
        },
        "submittable": validation.is_submittable,
        "facts": ret.facts.height,
        "tables": list(ret.tables),
        "summary": {
            "structure_findings": len(validation.structure),
            "rule_findings": len(validation.rules),
            "blocking_findings": len(validation.blocking),
            "rule_book": f"{report.framework_version} {report.taxonomy}" if report else None,
            "rules_enforced": report.rules_enforced if report else 0,
            "rules_executed": report.rules_executed if report else 0,
            "rule_status": report.status_counts() if report else {},
            "not_evaluated_reasons": report.not_evaluated_reasons() if report else {},
            "templates_reported": list(report.templates_reported) if report else [],
            "templates_uncovered": list(report.templates_uncovered) if report else [],
        },
        "findings": [_finding_record(finding) for finding in validation.findings],
        "rules": [
            {
                "rule_id": result.rule_id,
                "severity": result.severity,
                "status": result.status,
                "reason": result.reason,
                "detail": result.detail,
                "satisfied": result.satisfied,
                "unsatisfied": result.unsatisfied,
                "failures": [
                    {"place": failure.place, "cells": list(failure.cells)}
                    for failure in result.failures
                ],
            }
            for result in (report.results if report else ())
            if result.status != STATUS_PASS
        ],
    }


def render_text(ret: CanonicalReturn, validation: ReturnValidation) -> str:
    """The report as plain text: the verdict, the counts, then every finding."""
    info = validation.pack.info
    header = ret.header
    report = validation.report
    verdict = "SUBMITTABLE" if validation.is_submittable else "BLOCKED"
    lines = [
        f"{verdict}: {header.module} for {header.entity_identifier} "
        f"at {header.reference_date.isoformat()} "
        f"(taxonomy {info.version}, {ret.facts.height} facts, {len(ret.tables)} tables)",
        f"  structure: {len(validation.structure)} finding(s)",
    ]
    if report is None:
        lines.append(f"  rules: none packaged for module {info.module}")
    else:
        counts = report.status_counts()
        lines.append(
            f"  rules: {report.rules_executed} of {report.rules_enforced} executed — "
            f"{counts[STATUS_PASS]} passed, {counts[STATUS_FAIL]} failed, "
            f"{counts[STATUS_NOT_EVALUATED]} not evaluated"
        )
        reasons = list(report.not_evaluated_reasons().items())[:_REASONS_SHOWN]
        if reasons:
            lines.append(
                "  not evaluated because: "
                + ", ".join(f"{reason} ({count})" for reason, count in reasons)
            )
    if validation.findings:
        lines.append("")
        lines.extend(
            f"[{finding.code}] {finding.severity}: {finding.message}"
            for finding in validation.findings
        )
    lines.append("")
    lines.append(
        "The regulator's own validation on upload is authoritative; a clean result here "
        "is evidence the return is well-formed, not a guarantee of acceptance."
    )
    return "\n".join(lines)


def _finding_record(finding: Finding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "blocking": finding.is_blocking,
        "subject": finding.subject,
        "message": finding.message,
        "expected": finding.expected,
        "actual": finding.actual,
        "reference": finding.reference,
    }
