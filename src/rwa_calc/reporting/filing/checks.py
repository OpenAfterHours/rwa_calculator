"""
Supervisory validation checks — the published rules, run on our generated estate.

Pipeline position:
    COREPGenerator + Pillar3Generator
        ->  evaluate_all                   ->  ValidationReport (per-rule outcomes)
        ->  check_supervisory_validations  ->  list[CalculationError]

Key responsibilities:
- Run every currently-enforced published validation rule for a framework against
  the templates this run generated. The rule engine is ``rwa-filer``; this
  module hands it our bundles as a ``TemplateIndex`` (``bindings``) and brings
  its answer back.
- Adapt the engine's ``Finding`` records onto the project's error channel as
  ``VAL001`` / ``VAL002`` / ``VAL003`` ``CalculationError`` findings —
  accumulated, never raised, following the same contract as
  ``reporting/tieouts.py``.

Why this is critical path: these are the supervisor's own checks, run at
submission. An Error-severity break REJECTS the whole return, so a ``VAL001``
finding is a blocking defect in the filing, not a quality nit. ``tieouts.py``
is the hand-curated in-house ancestor of this — five cross-template identities
we derived ourselves; this is the published, exhaustive form.

An EMPTY finding list is meaningful: the engine reports insufficient coverage
as ``VAL003``, so the obvious gate —
``if not check_supervisory_validations(...): submit()`` — cannot fail open on
an estate where every rule was NOT_EVALUATED.

References:
- docs/reference/validation-rules/index.md — the rule grammar and provenance
- COREP Annex II; PRA PS1/26 Annex II — the templates the rules address
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from rwa_calc.contracts.errors import (
    ERROR_VALIDATION_COVERAGE_INSUFFICIENT,
    ERROR_VALIDATION_RULE_ERROR,
    ERROR_VALIDATION_RULE_WARNING,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.reporting.filing.bindings import build_template_index
from rwa_filer.validate.checker import (
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    evaluate_index,
    findings_for,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle
    from rwa_filer.validate.checker import Finding, ValidationReport

logger = logging.getLogger(__name__)

#: The engine's finding codes onto this project's error-channel codes. The two
#: vocabularies are spelled the same today, and
#: ``tests/unit/reporting/filing/test_error_channel.py`` pins that; the mapping
#: exists so the code a caller sees always comes from OUR contract
#: (``contracts/errors.py``), whatever the engine calls it.
_ERROR_CODES: Final[Mapping[str, str]] = {
    FINDING_RULE_ERROR: ERROR_VALIDATION_RULE_ERROR,
    FINDING_RULE_WARNING: ERROR_VALIDATION_RULE_WARNING,
    FINDING_COVERAGE_INSUFFICIENT: ERROR_VALIDATION_COVERAGE_INSUFFICIENT,
}


# =============================================================================
# Public entry points
# =============================================================================


def check_supervisory_validations(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle | None,
    framework: str,
) -> list[CalculationError]:
    """Run the published validation rules and return the breaks as findings.

    Only FAIL outcomes yield rule findings — one per broken rule, following the
    roll-up pattern (a single code per failure mode, the rule id on
    ``field_name``, both figures in the message), so a rule that breaks on 40
    sheets is one finding, not 40.

    An EMPTY result means "the estate was checked and holds" — and nothing else.
    A ``VAL003`` coverage finding is what makes that safe: without it, an estate
    on which NOTHING ran would yield no FAIL and therefore no finding.

    Args:
        corep: The generated COREP template bundle.
        pillar3: The generated Pillar 3 bundle (carried for contract symmetry;
            no published rule addresses a Pillar 3 template — see
            ``bindings.build_template_index``).
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        ``VAL001`` (Error-severity rule broken — blocks the submission),
        ``VAL002`` (Warning-severity rule broken) and ``VAL003`` (the estate was
        not checked well enough for an empty result to mean anything) findings;
        empty only when every enforced rule that could run did run and holds.
        Never raises.
    """
    report = evaluate_all(corep, pillar3, framework)
    return [to_calculation_error(finding) for finding in findings_for(report)]


def evaluate_all(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle | None,
    framework: str,
) -> ValidationReport:
    """Evaluate every currently-enforced rule for ``framework`` and report.

    Args:
        corep: The generated COREP template bundle.
        pillar3: The generated Pillar 3 bundle (see above).
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        The engine's ``ValidationReport``: one ``RuleOutcome`` per enforced rule
        — status, both figures, the coordinates and, for anything not evaluated,
        the reason — plus the per-template coverage the run achieved. Never
        raises for a data condition.
    """
    return evaluate_index(build_template_index(corep, pillar3, framework))


def to_calculation_error(finding: Finding) -> CalculationError:
    """Map one engine ``Finding`` onto the project's error channel.

    The rule id (or, for ``VAL003``, the machine-readable coverage reason)
    travels on ``field_name``, so a caller holding only the error channel still
    gets the structured verdict rather than having to parse the message.
    """
    return CalculationError(
        code=_ERROR_CODES[finding.code],
        message=finding.message,
        severity=ErrorSeverity.ERROR if finding.is_blocking else ErrorSeverity.WARNING,
        category=ErrorCategory.BUSINESS_RULE,
        regulatory_reference=finding.reference,
        field_name=finding.subject,
        expected_value=finding.expected,
        actual_value=finding.actual,
    )
