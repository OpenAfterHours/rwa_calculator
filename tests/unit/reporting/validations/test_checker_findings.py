"""
The checker: rule outcomes adapted onto the project's error channel.

Pipeline position:
    COREP + Pillar 3 bundles -> evaluate_all -> ValidationReport
        -> check_supervisory_validations -> list[CalculationError]

Key responsibilities:
- Pin the finding contract: an Error-severity break is ``VAL001`` (it REJECTS
  the whole submission), a Warning-severity one is ``VAL002``, the rule id rides
  on ``field_name``, and both figures reach the message.
- Pin the roll-up: one finding per broken RULE, not per broken coordinate, with
  the recorded coordinates capped.
- Pin that only FAIL yields a rule finding — a VACUOUS or NOT_EVALUATED rule
  must never reach the error channel as a break, and a clean run returns ``[]``,
  not ``None``.
- Pin the ``VAL003`` coverage guard, which is what makes an empty result safe to
  read as a green light: an estate on which nothing ran produces no FAIL and
  would otherwise look identical to a clean one.
- Pin that nothing raises. A malformed formula, an unknown table, an unmappable
  sheet and a rule carrying an unsupported precondition all become recorded
  skips. This is asserted over the ENTIRE enforced population of both
  frameworks, because a single raise here takes the whole reporting run down.

Rules are injected rather than read from the packaged extract wherever the
assertion is about the ADAPTER: a break that depends on real regulatory data
would move whenever the estate does.

References:
- src/rwa_calc/contracts/errors.py — VAL001 / VAL002
"""

from __future__ import annotations

import pytest

from rwa_calc.contracts.errors import (
    ERROR_VALIDATION_COVERAGE_INSUFFICIENT,
    ERROR_VALIDATION_RULE_ERROR,
    ERROR_VALIDATION_RULE_WARNING,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.reporting.validations import checker as checker_module
from rwa_calc.reporting.validations.checker import (
    MAX_RECORDED_FAILURES,
    check_supervisory_validations,
    evaluate_all,
)
from rwa_calc.reporting.validations.evaluate import (
    SKIP_PRECONDITION_UNSUPPORTED,
    SKIP_UNSUPPORTED_GRAMMAR,
    SKIP_WHERE_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
)
from rwa_calc.reporting.validations.rules import (
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    SCOPE_LIST,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleScope,
    RuleSet,
    TableScope,
)
from rwa_calc.reporting.validations.scope import SKIP_TABLE_NOT_EMITTED
from tests.unit.reporting.validations._builders import (
    build_corep,
    build_frame,
    build_rule,
)

# One C 02.00 frame where 0010 does NOT equal 0020 — every injected rule below
# is written to break (or hold) against these two figures.
_BROKEN_C02 = {"0010": {"0010": 100.0, "0020": 40.0}}


@pytest.fixture
def corep():
    """A COREP bundle carrying only the two-cell C 02.00 frame."""
    return build_corep(c_02_00=build_frame(_BROKEN_C02))


def inject(monkeypatch: pytest.MonkeyPatch, *rules) -> None:
    """Replace the packaged catalogue with the given rules, for both frameworks."""
    ruleset = RuleSet(framework=FRAMEWORK_CRR, publisher="EBA", source={}, rules=tuple(rules))
    monkeypatch.setattr(checker_module, "load_rules", lambda _framework: ruleset)


def rule_breaks(corep, pillar3, framework) -> list:
    """Only the broken-RULE findings, setting the VAL003 coverage guard aside."""
    return [
        finding
        for finding in check_supervisory_validations(corep, pillar3, framework)
        if finding.code != ERROR_VALIDATION_COVERAGE_INSUFFICIENT
    ]


# ---------------------------------------------------------------------------
# The finding contract
# ---------------------------------------------------------------------------


def test_an_error_severity_break_is_reported_as_val001(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """An Error-severity break rejects the submission, so it takes the blocking code."""
    # Arrange
    inject(monkeypatch, build_rule(severity=SEVERITY_ERROR))

    # Act
    findings = check_supervisory_validations(corep, None, FRAMEWORK_CRR)

    # Assert
    assert [f.code for f in findings] == [ERROR_VALIDATION_RULE_ERROR]


def test_an_error_severity_break_is_raised_to_error_severity(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """The finding's own severity must match the supervisor's, not default to warning."""
    # Arrange
    inject(monkeypatch, build_rule(severity=SEVERITY_ERROR))

    # Act
    finding = check_supervisory_validations(corep, None, FRAMEWORK_CRR)[0]

    # Assert
    assert (finding.severity, finding.category) == (
        ErrorSeverity.ERROR,
        ErrorCategory.BUSINESS_RULE,
    )


def test_a_warning_severity_break_is_reported_as_val002(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """A Warning-severity break is accepted by the supervisor but must be explained."""
    # Arrange
    inject(monkeypatch, build_rule(severity=SEVERITY_WARNING))

    # Act
    findings = check_supervisory_validations(corep, None, FRAMEWORK_CRR)

    # Assert
    assert [(f.code, f.severity) for f in findings] == [
        (ERROR_VALIDATION_RULE_WARNING, ErrorSeverity.WARNING)
    ]


def test_the_rule_id_rides_on_the_findings_field_name(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """One code per failure mode means the broken rule must be identified elsewhere."""
    # Arrange
    inject(monkeypatch, build_rule(rule_id="v9999_m"))

    # Act
    finding = check_supervisory_validations(corep, None, FRAMEWORK_CRR)[0]

    # Assert
    assert finding.field_name == "v9999_m"


def test_both_figures_reach_the_finding(monkeypatch: pytest.MonkeyPatch, corep) -> None:
    """A supervisor's break is only actionable with the two numbers that disagree."""
    # Arrange
    inject(monkeypatch, build_rule())

    # Act
    finding = check_supervisory_validations(corep, None, FRAMEWORK_CRR)[0]

    # Assert: left = 100, right = 40.
    assert (finding.actual_value, finding.expected_value) == ("100.0000", "40.0000")


def test_the_message_names_the_rule_the_expression_and_the_coordinate(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """The message must stand alone in a log with no access to the report object."""
    # Arrange
    inject(monkeypatch, build_rule(rule_id="v9999_m"))

    # Act
    message = check_supervisory_validations(corep, None, FRAMEWORK_CRR)[0].message

    # Assert
    assert "v9999_m" in message
    assert "{c0010} = {c0020}" in message
    assert "C 02.00" in message


def test_a_publisher_label_is_folded_to_ascii(monkeypatch: pytest.MonkeyPatch, corep) -> None:
    """Typographic dashes and curly quotes must never reach a cp1252 log handler."""
    # Arrange
    inject(monkeypatch, build_rule(label="Total – of which “secured”"))

    # Act
    message = check_supervisory_validations(corep, None, FRAMEWORK_CRR)[0].message

    # Assert
    assert message.isascii()


def test_the_finding_cites_the_publishers_annex(monkeypatch: pytest.MonkeyPatch, corep) -> None:
    """The regulatory reference points at the annex a reader would open."""
    # Arrange
    inject(monkeypatch, build_rule())

    # Act
    finding = check_supervisory_validations(corep, None, FRAMEWORK_CRR)[0]

    # Assert
    assert finding.regulatory_reference is not None
    assert "COREP Annex II" in finding.regulatory_reference


# ---------------------------------------------------------------------------
# What must NOT reach the error channel
# ---------------------------------------------------------------------------


def test_a_clean_run_returns_an_empty_list_not_none(monkeypatch: pytest.MonkeyPatch, corep) -> None:
    """The contract is a list of findings; ``None`` would break every caller."""
    # Arrange: a rule that holds on the frame.
    inject(monkeypatch, build_rule(expression="{c0010} = {c0010}"))

    # Act
    findings = check_supervisory_validations(corep, None, FRAMEWORK_CRR)

    # Assert
    assert findings == []


def test_a_vacuous_rule_produces_no_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule whose operands are all zero is no evidence — and no defect."""
    # Arrange
    corep = build_corep(c_02_00=build_frame({"0010": {"0010": 0.0, "0020": 0.0}}))
    inject(monkeypatch, build_rule())

    # Act
    report = evaluate_all(corep, None, FRAMEWORK_CRR)

    # Assert
    assert report.status_counts()[STATUS_VACUOUS] == 1
    assert rule_breaks(corep, None, FRAMEWORK_CRR) == []


def test_a_rule_on_an_unemitted_template_produces_no_finding(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """A structural gap is a skip with a reason, never a break."""
    # Arrange
    inject(monkeypatch, build_rule(tables=("C 08.07",)))

    # Act
    report = evaluate_all(corep, None, FRAMEWORK_CRR)

    # Assert
    assert (report.outcomes[0].status, report.outcomes[0].reason) == (
        STATUS_NOT_EVALUATED,
        SKIP_TABLE_NOT_EMITTED,
    )
    assert rule_breaks(corep, None, FRAMEWORK_CRR) == []


def test_a_deactivated_rule_is_never_evaluated(monkeypatch: pytest.MonkeyPatch, corep) -> None:
    """Only currently-enforced rules run — the catalogue's liveness is honoured here."""
    # Arrange
    inject(monkeypatch, build_rule(status=("deactivated",), reactivated_on=None))

    # Act
    report = evaluate_all(corep, None, FRAMEWORK_CRR)

    # Assert
    assert (report.rules_loaded, report.rules_enforced, report.outcomes) == (1, 0, ())


# ---------------------------------------------------------------------------
# Roll-up
# ---------------------------------------------------------------------------


def test_a_rule_breaking_on_many_coordinates_is_one_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken identity usually breaks on every row at once — that is one defect."""
    # Arrange: eight rows, each breaking the same identity.
    cells = {f"00{index:02d}": {"0010": 1.0, "0020": 2.0} for index in range(10, 18)}
    corep = build_corep(c_02_00=build_frame(cells))
    rule = build_rule(
        table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, tuple(cells))),)
    )
    inject(monkeypatch, rule)

    # Act
    findings = check_supervisory_validations(corep, None, FRAMEWORK_CRR)
    outcome = evaluate_all(corep, None, FRAMEWORK_CRR).outcomes[0]

    # Assert
    assert len(findings) == 1
    assert (outcome.failed, outcome.evaluated) == (8, 8)


def test_only_the_first_few_failing_coordinates_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rest are noise; the full counts stay on the outcome."""
    # Arrange
    cells = {f"00{index:02d}": {"0010": 1.0, "0020": 2.0} for index in range(10, 18)}
    corep = build_corep(c_02_00=build_frame(cells))
    inject(
        monkeypatch,
        build_rule(table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, tuple(cells))),)),
    )

    # Act
    outcome = evaluate_all(corep, None, FRAMEWORK_CRR).outcomes[0]

    # Assert
    assert len(outcome.failures) == MAX_RECORDED_FAILURES < outcome.failed


def test_a_rule_that_holds_on_some_rows_and_breaks_on_others_is_a_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One broken coordinate is enough — passes elsewhere do not excuse it."""
    # Arrange
    cells = {"0010": {"0010": 1.0, "0020": 1.0}, "0020": {"0010": 1.0, "0020": 2.0}}
    corep = build_corep(c_02_00=build_frame(cells))
    inject(
        monkeypatch,
        build_rule(
            table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, ("0010", "0020"))),)
        ),
    )

    # Act
    outcome = evaluate_all(corep, None, FRAMEWORK_CRR).outcomes[0]

    # Assert
    assert (outcome.status, outcome.passed, outcome.failed) == (STATUS_FAIL, 1, 1)


# ---------------------------------------------------------------------------
# Refusals are recorded, never raised
# ---------------------------------------------------------------------------


def test_a_malformed_formula_is_recorded_as_a_skip(monkeypatch: pytest.MonkeyPatch, corep) -> None:
    """An unparseable rule must not take the reporting run down."""
    # Arrange
    inject(monkeypatch, build_rule(expression="{c0010} = {c0020} &&"))

    # Act
    outcome = evaluate_all(corep, None, FRAMEWORK_CRR).outcomes[0]

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_UNSUPPORTED_GRAMMAR)


def test_an_unsupported_precondition_refuses_the_rule_rather_than_ignoring_it(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """Silently dropping a gating condition would evaluate the rule out of context."""
    # Arrange
    inject(monkeypatch, build_rule(precondition="{c0010} > 0"))

    # Act
    outcome = evaluate_all(corep, None, FRAMEWORK_CRR).outcomes[0]

    # Assert
    assert (outcome.status, outcome.reason) == (
        STATUS_NOT_EVALUATED,
        SKIP_PRECONDITION_UNSUPPORTED,
    )


def test_an_unsupported_where_clause_refuses_the_rule(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """The ``where`` row filter is the same hazard as a precondition."""
    # Arrange
    inject(monkeypatch, build_rule(where="row_type = 'x'"))

    # Act
    outcome = evaluate_all(corep, None, FRAMEWORK_CRR).outcomes[0]

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_WHERE_UNSUPPORTED)


def test_an_unmappable_sheet_code_is_recorded_as_a_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A z-code whose meaning was never established must not be guessed at."""
    # Arrange: OF 08.01 code 0003 is deliberately absent from the sheet map.
    corep = build_corep("BASEL_3_1", c08_01={"institution": build_frame({"0010": {"0010": 1.0}})})
    inject(
        monkeypatch,
        build_rule(
            tables=("OF08.01.01.01",),
            table_scopes=(TableScope("OF08.01.01.01", sheets=RuleScope(SCOPE_LIST, ("0003",))),),
        ),
    )

    # Act
    outcome = evaluate_all(corep, None, FRAMEWORK_BASEL_3_1).outcomes[0]

    # Assert
    assert outcome.status == STATUS_NOT_EVALUATED
    assert rule_breaks(corep, None, FRAMEWORK_BASEL_3_1) == []


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_the_whole_enforced_population_runs_without_raising(framework: str) -> None:
    """Every packaged rule, against a near-empty estate, resolves to a status.

    The broadest guard there is: one raise anywhere in 1,549 enforced rules takes
    the reporting run down, and the conditions that provoke it (absent templates,
    empty frames, unmappable sheets) are exactly what a partial run produces.
    """
    # Arrange: one template, one row, one column — almost everything is absent.
    corep = build_corep(framework, c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act
    report = evaluate_all(corep, None, framework)

    # Assert
    assert report.rules_enforced == len(report.outcomes)
    assert {o.status for o in report.outcomes} <= {
        STATUS_PASS,
        STATUS_FAIL,
        STATUS_VACUOUS,
        STATUS_NOT_EVALUATED,
    }


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_every_unevaluated_rule_carries_a_reason(framework: str) -> None:
    """A skip with no reason is indistinguishable from a silent pass."""
    # Arrange
    corep = build_corep(framework, c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act
    report = evaluate_all(corep, None, framework)

    # Assert
    unexplained = [
        o.rule_id for o in report.outcomes if o.status == STATUS_NOT_EVALUATED and not o.reason
    ]
    assert unexplained == []


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_an_entirely_empty_bundle_is_survivable(framework: str) -> None:
    """A run that produced no template at all still returns a report, not a crash."""
    # Arrange
    corep = build_corep(framework)

    # Act
    report = evaluate_all(corep, None, framework)

    # Assert: no rule broke — but see the coverage guard below, which is what
    # stops that emptiness being read as a clean estate.
    assert report.status_counts()[STATUS_FAIL] == 0
    assert rule_breaks(corep, None, framework) == []


# ---------------------------------------------------------------------------
# The VAL003 coverage guard
#
# The guard itself is pinned against the real catalogue in test_coverage_guard.py.
# What belongs here is the one interaction between coverage and the ADAPTER: a
# rule the checker refused to parse must not confer coverage on the template it
# names, or an estate could be waved through by rules that never ran.
# ---------------------------------------------------------------------------


def test_a_rule_that_never_executed_does_not_count_towards_coverage(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """Coverage counts EXECUTED rules; a skipped one exercised nothing."""
    # Arrange: the rule names C 02.00 but cannot be parsed.
    inject(monkeypatch, build_rule(expression="if {c0010} > 0 then {c0020} = 1"))

    # Act
    report = evaluate_all(corep, None, FRAMEWORK_CRR)

    # Assert
    assert (report.rules_executed, report.templates_uncovered) == (0, ("c_02_00",))


def test_a_clean_covered_estate_yields_no_finding_of_any_kind(
    monkeypatch: pytest.MonkeyPatch, corep
) -> None:
    """The green light: every emitted template checked, and every rule holding."""
    # Arrange
    inject(monkeypatch, build_rule(expression="{c0010} = {c0010}"))

    # Act
    findings = check_supervisory_validations(corep, None, FRAMEWORK_CRR)

    # Assert
    assert findings == []
