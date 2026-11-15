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
- Name the templates left out that the reported ones are checked against, in
  the summary as well as in their ``VAL004`` findings.
- Keep the record self-contained: a reader holding only the JSON knows which
  entity, date, module and taxonomy version it describes, and — from its
  ``identity`` block — the fingerprint of every input the verdict rests on.
- List EVERY enforced rule, passes included, so the record shows the whole set
  of checks that ran, not only the ones that broke.
- Say whether the check was complete (``status``, ``completeness``), apart from
  whether it passed.
- Declare its own shape: ``schema`` names the record and its version, and
  ``schemas/validation-report-2.schema.json`` (shipped in the wheel) is its
  contract. Within a major version, changes only add.

References:
- rwa_filer.validate.returns — what a ``ReturnValidation`` holds
- rwa_filer.validate.identity — the fingerprints
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from rwa_filer import __version__
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, STATUS_PASS
from rwa_filer.validate.identity import identity_record
from rwa_filer.validate.returns import (
    INCOMPLETE_COVERAGE_SHORTFALL,
    INCOMPLETE_LINKED_TEMPLATES_MISSING,
    INCOMPLETE_NO_RULEBOOK,
    INCOMPLETE_RULES_TABLE_NOT_IN_TAXONOMY,
    INCOMPLETE_RULES_UNSUPPORTED,
)

if TYPE_CHECKING:
    from rwa_filer.boe.engine import CellAddress, RuleResult
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.validate.checker import Finding
    from rwa_filer.validate.returns import IncompleteCause, MissingTemplate, ReturnValidation

#: The record's name and version (``schema``). The major version changes when
#: a field is renamed, removed or changes meaning; the minor when one is added.
REPORT_SCHEMA_NAME: Final = "rwa-filer/validation-report"
REPORT_SCHEMA_VERSION: Final = "2.0"

#: Not-evaluated reasons quoted in the text summary (commonest first).
_REASONS_SHOWN = 5
#: Missing linked templates named in the text summary (most rules first).
_MISSING_SHOWN = 5


def to_record(ret: CanonicalReturn, validation: ReturnValidation) -> dict[str, Any]:
    """A JSON-ready record of one validated return.

    The record holds what it was computed from (``identity``), the verdict and
    whether the check was complete, the counts behind them, every finding, and
    one entry per enforced rule — passed, failed or not evaluated.
    """
    report = validation.report
    info = validation.pack.info
    module = info.module
    rules = (
        {rule.rule_id: rule for rule in validation.rulebook.rules} if validation.rulebook else {}
    )
    return {
        "schema": {"name": REPORT_SCHEMA_NAME, "version": REPORT_SCHEMA_VERSION},
        "generator": f"rwa-filer {__version__}",
        "identity": identity_record(ret, validation),
        "header": ret.header.as_fields(),
        "taxonomy": {
            "module": info.module,
            "version": info.version,
            "entry_point": info.entry_point,
        },
        "status": validation.status,
        "submittable": validation.is_submittable,
        "completeness": [cause_record(cause) for cause in validation.completeness],
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
            "templates_missing": [
                {
                    "template": missing.code,
                    "rules": list(missing.rules),
                    "linked_from": list(missing.linked_from),
                }
                for missing in (report.templates_missing if report else ())
            ],
        },
        "findings": [finding_record(finding) for finding in validation.findings],
        "rules": [
            rule_record(
                result,
                rules[result.rule_id].fingerprint(module) if result.rule_id in rules else None,
            )
            for result in (report.results if report else ())
        ],
    }


def rule_record(result: RuleResult, fingerprint: str | None) -> dict[str, Any]:
    """One enforced rule's outcome, as the report and the evidence export record it."""
    return {
        "rule_id": result.rule_id,
        "rule_sha256": fingerprint,
        "severity": result.severity,
        "status": result.status,
        "reason": result.reason,
        "detail": result.detail,
        "evaluations": result.evaluations,
        "satisfied": result.satisfied,
        "unsatisfied": result.unsatisfied,
        "tables": list(result.tables),
        "failures": [
            {
                "place": failure.place,
                "cells": list(failure.cells),
                "addresses": [address_record(address) for address in failure.addresses],
            }
            for failure in result.failures
        ],
    }


def address_record(address: CellAddress) -> dict[str, Any]:
    """A cell, in the publisher's coordinates."""
    return {
        "table": address.table,
        "sheet": address.sheet,
        "open_key": address.open_key,
        "row": address.row,
        "column": address.column,
        "reported": address.reported,
    }


def cause_record(cause: IncompleteCause) -> dict[str, Any]:
    """One reason the check is incomplete."""
    return {
        "code": cause.code,
        "rules": list(cause.rules),
        "templates": list(cause.templates),
        "detail": cause.detail,
    }


def finding_record(finding: Finding) -> dict[str, Any]:
    """One finding. Its positions are counted; the evidence export lists them all."""
    return {
        "code": finding.code,
        "severity": finding.severity,
        "blocking": finding.is_blocking,
        "subject": finding.subject,
        "message": finding.message,
        "expected": finding.expected,
        "actual": finding.actual,
        "reference": finding.reference,
        "positions_total": len(finding.positions),
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
        f"  status: {status_line(validation)}",
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
        if report.templates_missing:
            lines.append(
                f"  linked templates not reported: {_missing_line(report.templates_missing)}"
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


def _missing_line(missing: tuple[MissingTemplate, ...]) -> str:
    """The missing linked templates, most rules first, the rest counted."""
    ranked = sorted(missing, key=lambda item: (-len(item.rules), item.code))
    named = ", ".join(
        f"{item.code} ({len(item.rules)} rule{'s' if len(item.rules) != 1 else ''})"
        for item in ranked[:_MISSING_SHOWN]
    )
    rest = len(ranked) - _MISSING_SHOWN
    return f"{named} and {rest} more" if rest > 0 else named


def status_line(validation: ReturnValidation) -> str:
    """``CLEAN``, or the status with what left the check incomplete — for any display."""
    causes = validation.completeness
    if not causes:
        return validation.status
    return f"{validation.status} — " + "; ".join(_describe_cause(cause) for cause in causes)


def _describe_cause(cause: IncompleteCause) -> str:
    rules, templates = len(cause.rules), len(cause.templates)
    if cause.code == INCOMPLETE_NO_RULEBOOK:
        return "no rule book for the module, so no rule was run"
    if cause.code == INCOMPLETE_RULES_UNSUPPORTED:
        return f"{rules} rule(s) this engine cannot evaluate"
    if cause.code == INCOMPLETE_RULES_TABLE_NOT_IN_TAXONOMY:
        return f"{rules} rule(s) read a table the taxonomy pack lacks"
    if cause.code == INCOMPLETE_LINKED_TEMPLATES_MISSING:
        return f"linked templates not reported ({templates} template(s), {rules} rule(s))"
    if cause.code == INCOMPLETE_COVERAGE_SHORTFALL:
        return f"rule coverage insufficient ({cause.detail})"
    return cause.code
