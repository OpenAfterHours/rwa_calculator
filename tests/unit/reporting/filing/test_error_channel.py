"""
The filing adapter: the rule engine's findings, brought onto our error channel.

Pipeline position:
    COREP + Pillar 3 bundles -> filing.evaluate_all -> rwa_filer ValidationReport
        -> filing.check_supervisory_validations -> list[CalculationError]

The rule engine is ``rwa-filer``, and its own suite pins what a finding SAYS —
the roll-up, the coverage guard, the message. What is pinned here is the part
only this project owns: that our bundles reach the engine through the
production bindings, and that each engine ``Finding`` lands on the error channel
with OUR codes, severities and category.

Key responsibilities:
- The engine's finding codes map onto ``contracts/errors.py``'s ``VAL001`` /
  ``VAL002`` / ``VAL003`` — and the two vocabularies are spelled the same, which
  is asserted rather than assumed because they live in two packages.
- An Error-severity finding is ``ErrorSeverity.ERROR``, a Warning-severity one
  ``ErrorSeverity.WARNING``; every one is ``ErrorCategory.BUSINESS_RULE``.
- The machine-readable subject (the rule id, or the coverage reason) rides on
  ``field_name``; both figures and the regulatory reference survive the mapping.
- ``check_supervisory_validations`` is exactly the engine's findings for our
  index, mapped — nothing added, dropped or reordered — and an empty estate
  still yields the ``VAL003`` guard rather than an empty (green) list.

References:
- src/rwa_calc/reporting/filing/checks.py — the adapter under test
- src/rwa_calc/contracts/errors.py — VAL001 / VAL002 / VAL003
"""

from __future__ import annotations

import pytest

from rwa_calc.contracts.errors import (
    ERROR_VALIDATION_COVERAGE_INSUFFICIENT,
    ERROR_VALIDATION_RULE_ERROR,
    ERROR_VALIDATION_RULE_WARNING,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.reporting.filing import (
    build_template_index,
    check_supervisory_validations,
    evaluate_all,
    to_calculation_error,
)
from rwa_filer.rules.catalogue import (
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleSet,
)
from rwa_filer.validate import checker as engine_checker
from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    Finding,
    check_index,
)

from ._builders import build_corep, build_frame, build_rule

# One C 02.00 frame where 0010 does NOT equal 0020, so the default injected rule
# (``{c0010} = {c0020}``) breaks on it.
_BROKEN_C02 = {"0010": {"0010": 100.0, "0020": 40.0}}


def _finding(code: str, severity: str) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        message="a finding message",
        reference="COREP Annex II C 02.00",
        subject="vTEST_m",
        expected="40.0000",
        actual="100.0000",
    )


def _inject(monkeypatch: pytest.MonkeyPatch, *rules) -> None:
    """Replace the engine's packaged catalogue with the given rules."""
    ruleset = RuleSet(framework=FRAMEWORK_CRR, publisher="EBA", source={}, rules=tuple(rules))
    monkeypatch.setattr(engine_checker, "load_rules", lambda _framework: ruleset)


# ---------------------------------------------------------------------------
# The code vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("engine_code", "channel_code"),
    [
        (FINDING_RULE_ERROR, ERROR_VALIDATION_RULE_ERROR),
        (FINDING_RULE_WARNING, ERROR_VALIDATION_RULE_WARNING),
        (FINDING_COVERAGE_INSUFFICIENT, ERROR_VALIDATION_COVERAGE_INSUFFICIENT),
    ],
)
def test_engine_finding_codes_are_spelled_as_our_error_codes(
    engine_code: str, channel_code: str
) -> None:
    """Two packages, one vocabulary — a drift here would relabel every finding."""
    assert engine_code == channel_code


@pytest.mark.parametrize(
    ("engine_code", "channel_code"),
    [
        (FINDING_RULE_ERROR, ERROR_VALIDATION_RULE_ERROR),
        (FINDING_RULE_WARNING, ERROR_VALIDATION_RULE_WARNING),
        (FINDING_COVERAGE_INSUFFICIENT, ERROR_VALIDATION_COVERAGE_INSUFFICIENT),
    ],
)
def test_each_finding_code_maps_to_its_error_channel_code(
    engine_code: str, channel_code: str
) -> None:
    # Act
    error = to_calculation_error(_finding(engine_code, SEVERITY_ERROR))

    # Assert
    assert error.code == channel_code


# ---------------------------------------------------------------------------
# The field mapping
# ---------------------------------------------------------------------------


def test_an_error_finding_maps_to_error_severity_and_business_rule_category() -> None:
    # Act
    error = to_calculation_error(_finding(FINDING_RULE_ERROR, SEVERITY_ERROR))

    # Assert
    assert isinstance(error, CalculationError)
    assert error.severity is ErrorSeverity.ERROR
    assert error.category is ErrorCategory.BUSINESS_RULE


def test_a_warning_finding_maps_to_warning_severity() -> None:
    # Act
    error = to_calculation_error(_finding(FINDING_RULE_WARNING, SEVERITY_WARNING))

    # Assert
    assert error.severity is ErrorSeverity.WARNING
    assert error.category is ErrorCategory.BUSINESS_RULE


def test_every_finding_field_survives_the_mapping() -> None:
    # Arrange
    finding = _finding(FINDING_RULE_ERROR, SEVERITY_ERROR)

    # Act
    error = to_calculation_error(finding)

    # Assert
    assert error.message == finding.message
    assert error.regulatory_reference == finding.reference
    assert error.field_name == finding.subject
    assert error.expected_value == finding.expected
    assert error.actual_value == finding.actual


# ---------------------------------------------------------------------------
# End to end through the production bindings
# ---------------------------------------------------------------------------


def test_a_broken_error_rule_reaches_the_channel_as_val001(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _inject(monkeypatch, build_rule(severity=SEVERITY_ERROR))
    corep = build_corep(c_02_00=build_frame(_BROKEN_C02))

    # Act
    errors = check_supervisory_validations(corep, None, FRAMEWORK_CRR)

    # Assert
    assert [(e.code, e.severity, e.field_name) for e in errors] == [
        (ERROR_VALIDATION_RULE_ERROR, ErrorSeverity.ERROR, "vTEST_m")
    ]
    assert (errors[0].actual_value, errors[0].expected_value) == ("100.0000", "40.0000")


def test_a_broken_warning_rule_reaches_the_channel_as_val002(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _inject(monkeypatch, build_rule(severity=SEVERITY_WARNING))
    corep = build_corep(c_02_00=build_frame(_BROKEN_C02))

    # Act
    errors = check_supervisory_validations(corep, None, FRAMEWORK_CRR)

    # Assert
    assert [(e.code, e.severity) for e in errors] == [
        (ERROR_VALIDATION_RULE_WARNING, ErrorSeverity.WARNING)
    ]


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_an_empty_estate_yields_the_val003_guard_not_a_green_light(framework: str) -> None:
    """Nothing ran, so nothing failed — and that must not read as a clean estate."""
    # Arrange
    corep = build_corep(framework)

    # Act
    errors = check_supervisory_validations(corep, None, framework)

    # Assert
    assert [(e.code, e.severity, e.field_name) for e in errors] == [
        (ERROR_VALIDATION_COVERAGE_INSUFFICIENT, ErrorSeverity.ERROR, COVERAGE_NO_RULE_EXECUTED)
    ]


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_the_adapter_adds_and_drops_nothing(framework: str) -> None:
    """Our findings are exactly the engine's findings for our index, mapped in order."""
    # Arrange — a C 07.00 sheet the packaged rules can reach, with a deliberate break.
    corep = build_corep(
        framework,
        c07_00={
            "corporate": build_frame(
                {"0010": {"0050": 1.0, "0060": 2.0, "0070": 3.0, "0080": 4.0, "0090": 99.0}}
            )
        },
    )

    # Act
    errors = check_supervisory_validations(corep, None, framework)
    engine = check_index(build_template_index(corep, None, framework))

    # Assert
    assert errors == [to_calculation_error(finding) for finding in engine]
    assert errors, "the fixture is meant to yield at least one finding"


def test_evaluate_all_reports_against_the_requested_framework() -> None:
    # Arrange
    corep = build_corep(FRAMEWORK_BASEL_3_1, c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act
    report = evaluate_all(corep, None, FRAMEWORK_BASEL_3_1)

    # Assert
    assert (report.framework, report.publisher) == (FRAMEWORK_BASEL_3_1, "BoE")
    assert report.rules_enforced == len(report.outcomes)
