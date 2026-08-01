"""
Unit tests for the VAL003 validation-coverage guard.

The guard exists so that an EMPTY result from ``check_supervisory_validations``
means "the estate was checked and holds" and nothing else. Without it the
obvious production gate fails OPEN:

    if not check_supervisory_validations(corep, pillar3, framework):
        submit()        # <-- an estate on which NOTHING ran looks identical

Every rule NOT_EVALUATED yields no FAIL, therefore no finding, therefore a green
light on a return nobody checked. These tests pin both limbs of the guard —
nothing executed, and an emitted template no rule reached — plus the property
that matters most: the guard is silent when coverage is genuinely adequate, so
it never becomes noise a reader learns to ignore.

References:
- src/rwa_calc/reporting/validations/checker.py — the guard under test
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from rwa_calc.contracts.errors import ERROR_VALIDATION_COVERAGE_INSUFFICIENT
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.reporting.validations import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    check_supervisory_validations,
    evaluate_all,
)

from ._builders import build_corep, build_frame

if TYPE_CHECKING:
    from rwa_calc.contracts.errors import CalculationError

# A C 07.00 sheet that satisfies the CRM-outflow identity v0305_m
# (``{c0090} = {c0050} + {c0060} + {c0070} + {c0080}``) on the total row, so the
# bundle achieves genuine coverage of c07_00 without any rule breaking on it.
_COVERED_C07 = {
    "0010": {"0050": 1.0, "0060": 2.0, "0070": 3.0, "0080": 4.0, "0090": 10.0},
}

# A frame bound to a template no executed rule reaches (C 34.02, the per-netting
# -set SA-CCR table). Shape is irrelevant — the point is that it is EMITTED.
_UNREACHED = {"0010": {"0010": 1.0}}


def _coverage_findings(**templates: Any) -> list[CalculationError]:
    """Every VAL003 finding raised for a bundle carrying only ``templates``."""
    corep = build_corep(**templates)
    findings = check_supervisory_validations(corep, None, "CRR")
    return [f for f in findings if f.code == ERROR_VALIDATION_COVERAGE_INSUFFICIENT]


def test_empty_bundle_reports_insufficient_coverage() -> None:
    """A bundle with no templates must not read as a clean validation result."""
    # Arrange / Act
    findings = _coverage_findings()

    # Assert
    assert len(findings) == 1


def test_empty_bundle_would_otherwise_produce_no_findings_at_all() -> None:
    """The hole the guard closes: no rule executes, so no rule can fail."""
    # Arrange
    corep = build_corep()

    # Act
    report = evaluate_all(corep, None, "CRR")

    # Assert — every enforced rule skipped, so FAIL-derived findings are empty
    assert report.rules_executed == 0
    assert report.status_counts()["FAIL"] == 0


def test_coverage_finding_blocks_the_submission_decision() -> None:
    """VAL003 is Error severity: an unevaluated estate is not a clear one."""
    # Arrange / Act
    finding = _coverage_findings()[0]

    # Assert
    assert finding.severity is ErrorSeverity.ERROR
    assert finding.category is ErrorCategory.BUSINESS_RULE


def test_coverage_finding_quotes_the_actual_figures() -> None:
    """ "coverage 0 of 741" is actionable; "insufficient coverage" is not."""
    # Arrange / Act
    finding = _coverage_findings()[0]

    # Assert — both sides of the ratio, and the caller-facing warning
    assert "0 of 741 enforced rules executed" in finding.message
    assert "741 not evaluated" in finding.message
    assert "NOT evidence the return is valid" in finding.message


def test_adequately_covered_bundle_raises_no_coverage_finding() -> None:
    """The guard stays silent when every emitted template was checked."""
    # Arrange / Act
    findings = _coverage_findings(c07_00={"corporate": build_frame(_COVERED_C07)})

    # Assert
    assert findings == []


def test_emitted_template_with_no_executed_rule_is_reported() -> None:
    """A per-template floor, because a bare executed-rule count is gameable.

    Here c07_00 is genuinely covered — a count-based floor would report a
    healthy number and wave the estate through — while c34_02 goes out entirely
    unchecked.
    """
    # Arrange / Act
    findings = _coverage_findings(
        c07_00={"corporate": build_frame(_COVERED_C07)},
        c34_02={"NS1": build_frame(_UNREACHED)},
    )

    # Assert
    assert len(findings) == 1
    assert "c34_02" in findings[0].message


def test_report_names_the_uncovered_templates() -> None:
    """``templates_uncovered`` is reported, not left for a caller to infer."""
    # Arrange
    corep = build_corep(
        c07_00={"corporate": build_frame(_COVERED_C07)},
        c34_02={"NS1": build_frame(_UNREACHED)},
    )

    # Act
    report = evaluate_all(corep, None, "CRR")

    # Assert
    assert report.templates_uncovered == ("c34_02",)
    assert "c07_00" in report.templates_covered


# ---------------------------------------------------------------------------
# One predicate, two consumers
#
# ``coverage_shortfall`` is the single implementation; the VAL003 finding reads
# it rather than re-deriving the condition. These tests are what stop a third
# limb being added to one and not the other — the drift that would let a caller
# reading the property disagree with a caller reading the error channel.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("templates", "expected"),
    [
        pytest.param({}, COVERAGE_NO_RULE_EXECUTED, id="nothing-executed"),
        pytest.param(
            {"c07_00": {"corporate": build_frame(_COVERED_C07)}},
            None,
            id="adequately-covered",
        ),
        pytest.param(
            {
                "c07_00": {"corporate": build_frame(_COVERED_C07)},
                "c34_02": {"NS1": build_frame(_UNREACHED)},
            },
            COVERAGE_TEMPLATE_NOT_COVERED,
            id="template-not-covered",
        ),
    ],
)
def test_shortfall_reason_names_which_of_the_two_causes_applies(
    templates: dict[str, Any], expected: str | None
) -> None:
    """The reason is structured, because the two causes need different responses.

    ``no_rule_executed`` is a plumbing problem — nothing was checked at all —
    while ``template_not_covered`` means specific templates in an otherwise
    healthy estate went out unexamined.
    """
    # Arrange / Act
    report = evaluate_all(build_corep(**templates), None, "CRR")

    # Assert
    assert report.coverage_shortfall == expected
    assert report.is_coverage_sufficient is (expected is None)


@pytest.mark.parametrize(
    "templates",
    [
        pytest.param({}, id="nothing-executed"),
        pytest.param({"c07_00": {"corporate": build_frame(_COVERED_C07)}}, id="adequately-covered"),
        pytest.param(
            {
                "c07_00": {"corporate": build_frame(_COVERED_C07)},
                "c34_02": {"NS1": build_frame(_UNREACHED)},
            },
            id="template-not-covered",
        ),
    ],
)
def test_the_property_and_the_val003_finding_never_disagree(templates: dict[str, Any]) -> None:
    """A VAL003 finding is raised exactly when the property reports a shortfall."""
    # Arrange
    corep = build_corep(**templates)

    # Act
    shortfall = evaluate_all(corep, None, "CRR").coverage_shortfall
    findings = _coverage_findings(**templates)

    # Assert — presence agrees, and the finding carries the same machine reason
    assert bool(findings) is (shortfall is not None)
    assert [f.field_name for f in findings] == ([shortfall] if shortfall else [])


def test_limb_one_is_addressable_from_the_error_channel_alone() -> None:
    """A caller holding only findings can tell "nothing ran" from "a gap".

    Limb 1 is the fail-open case and is the one a production gate blocks on, so
    it has to be identifiable without reading the report object or parsing prose.
    """
    # Arrange / Act
    finding = _coverage_findings()[0]

    # Assert
    assert finding.field_name == COVERAGE_NO_RULE_EXECUTED


def test_limb_two_is_addressable_from_the_error_channel_alone() -> None:
    """Limb 2 is a coverage gap in a reachable estate — reportable, not fatal."""
    # Arrange / Act
    findings = _coverage_findings(
        c07_00={"corporate": build_frame(_COVERED_C07)},
        c34_02={"NS1": build_frame(_UNREACHED)},
    )

    # Assert
    assert findings[0].field_name == COVERAGE_TEMPLATE_NOT_COVERED


def test_both_limbs_share_one_code_because_they_are_one_failure_mode() -> None:
    """VAL003 means "coverage insufficient"; the limb is a detail of it.

    A second error code would say the two are different KINDS of problem. They
    are not — both mean an absent break proves nothing — so the limb rides on
    ``field_name``, the same slot VAL001 uses for the broken rule id.
    """
    # Arrange / Act
    none_executed = _coverage_findings()[0]
    uncovered = _coverage_findings(
        c07_00={"corporate": build_frame(_COVERED_C07)},
        c34_02={"NS1": build_frame(_UNREACHED)},
    )[0]

    # Assert
    assert none_executed.code == uncovered.code == ERROR_VALIDATION_COVERAGE_INSUFFICIENT
    assert none_executed.field_name != uncovered.field_name


def test_limb_two_message_still_names_the_uncovered_templates() -> None:
    """The figures and template names are the actionable part — don't regress to a code."""
    # Arrange / Act
    finding = _coverage_findings(
        c07_00={"corporate": build_frame(_COVERED_C07)},
        c34_02={"NS1": build_frame(_UNREACHED)},
    )[0]

    # Assert
    assert "c34_02" in finding.message
    assert "enforced rules executed" in finding.message
    assert COVERAGE_TEMPLATE_NOT_COVERED in finding.message
