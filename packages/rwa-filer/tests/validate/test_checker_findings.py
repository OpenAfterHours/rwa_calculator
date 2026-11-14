"""
The checker: rule outcomes reported as findings.

Pipeline position:
    TemplateIndex -> evaluate_index -> ValidationReport
        -> check_index -> list[Finding]

Key responsibilities:
- Pin the finding contract: an Error-severity break is ``VAL001`` (it REJECTS
  the whole submission), a Warning-severity one is ``VAL002``, the rule id rides
  on ``subject``, and both figures reach the message.
- Pin the roll-up: one finding per broken RULE, not per broken coordinate, with
  the recorded coordinates capped.
- Pin that only FAIL yields a rule finding — a VACUOUS or NOT_EVALUATED rule
  must never be reported as a break, and a clean run returns ``[]``, not
  ``None``.
- Pin the ``VAL003`` coverage guard, which is what makes an empty result safe to
  read as a green light: an estate on which nothing ran produces no FAIL and
  would otherwise look identical to a clean one.
- Pin that nothing raises. A malformed formula, an unknown table, an unmappable
  sheet and a rule carrying an unsupported precondition all become recorded
  skips. This is asserted over the ENTIRE enforced population of both
  frameworks, because a single raise here takes the whole reporting run down.

Rules are injected rather than read from the packaged extract wherever the
assertion is about the CHECKER: a break that depends on real regulatory data
would move whenever the rule set does.

References:
- rwa_filer.validate.checker — VAL001 / VAL002 / VAL003
"""

from __future__ import annotations

import pytest

from filer_builders import (
    build_frame,
    build_index,
    build_rule,
)
from rwa_filer.rules.catalogue import (
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    SCOPE_LIST,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleScope,
    RuleSet,
    TableScope,
)
from rwa_filer.validate import checker as checker_module
from rwa_filer.validate.checker import (
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    MAX_RECORDED_FAILURES,
    Finding,
    check_index,
    evaluate_index,
)
from rwa_filer.validate.evaluate import (
    SKIP_PRECONDITION_UNSUPPORTED,
    SKIP_UNSUPPORTED_GRAMMAR,
    SKIP_WHERE_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
)
from rwa_filer.validate.index import SKIP_TABLE_NOT_EMITTED

# One C 02.00 frame where 0010 does NOT equal 0020 — every injected rule below
# is written to break (or hold) against these two figures.
_BROKEN_C02 = {"0010": {"0010": 100.0, "0020": 40.0}}


@pytest.fixture
def index():
    """An index carrying only the two-cell C 02.00 frame."""
    return build_index(c_02_00=build_frame(_BROKEN_C02))


def inject(monkeypatch: pytest.MonkeyPatch, *rules) -> None:
    """Replace the packaged catalogue with the given rules, for both frameworks."""
    ruleset = RuleSet(framework=FRAMEWORK_CRR, publisher="EBA", source={}, rules=tuple(rules))
    monkeypatch.setattr(checker_module, "load_rules", lambda _framework: ruleset)


def rule_breaks(index) -> list[Finding]:
    """Only the broken-RULE findings, setting the VAL003 coverage guard aside."""
    return [
        finding for finding in check_index(index) if finding.code != FINDING_COVERAGE_INSUFFICIENT
    ]


# ---------------------------------------------------------------------------
# The finding contract
# ---------------------------------------------------------------------------


def test_an_error_severity_break_is_reported_as_val001(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """An Error-severity break rejects the submission, so it takes the blocking code."""
    # Arrange
    inject(monkeypatch, build_rule(severity=SEVERITY_ERROR))

    # Act
    findings = check_index(index)

    # Assert
    assert [f.code for f in findings] == [FINDING_RULE_ERROR]


def test_an_error_severity_break_is_raised_to_error_severity(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """The finding's own severity must match the supervisor's, not default to warning."""
    # Arrange
    inject(monkeypatch, build_rule(severity=SEVERITY_ERROR))

    # Act
    finding = check_index(index)[0]

    # Assert
    assert finding.severity == SEVERITY_ERROR
    assert finding.is_blocking


def test_a_warning_severity_break_is_reported_as_val002(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """A Warning-severity break is accepted by the supervisor but must be explained."""
    # Arrange
    inject(monkeypatch, build_rule(severity=SEVERITY_WARNING))

    # Act
    findings = check_index(index)

    # Assert
    assert [(f.code, f.severity) for f in findings] == [(FINDING_RULE_WARNING, SEVERITY_WARNING)]


def test_the_rule_id_rides_on_the_findings_field_name(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """One code per failure mode means the broken rule must be identified elsewhere."""
    # Arrange
    inject(monkeypatch, build_rule(rule_id="v9999_m"))

    # Act
    finding = check_index(index)[0]

    # Assert
    assert finding.subject == "v9999_m"


def test_both_figures_reach_the_finding(monkeypatch: pytest.MonkeyPatch, index) -> None:
    """A supervisor's break is only actionable with the two numbers that disagree."""
    # Arrange
    inject(monkeypatch, build_rule())

    # Act
    finding = check_index(index)[0]

    # Assert: left = 100, right = 40.
    assert (finding.actual, finding.expected) == ("100.0000", "40.0000")


def test_the_message_names_the_rule_the_expression_and_the_coordinate(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """The message must stand alone in a log with no access to the report object."""
    # Arrange
    inject(monkeypatch, build_rule(rule_id="v9999_m"))

    # Act
    message = check_index(index)[0].message

    # Assert
    assert "v9999_m" in message
    assert "{c0010} = {c0020}" in message
    assert "C 02.00" in message


def test_a_publisher_label_is_folded_to_ascii(monkeypatch: pytest.MonkeyPatch, index) -> None:
    """Typographic dashes and curly quotes must never reach a cp1252 log handler."""
    # Arrange
    inject(monkeypatch, build_rule(label="Total – of which “secured”"))

    # Act
    message = check_index(index)[0].message

    # Assert
    assert message.isascii()


def test_the_finding_cites_the_publishers_annex(monkeypatch: pytest.MonkeyPatch, index) -> None:
    """The regulatory reference points at the annex a reader would open."""
    # Arrange
    inject(monkeypatch, build_rule())

    # Act
    finding = check_index(index)[0]

    # Assert
    assert finding.reference is not None
    assert "COREP Annex II" in finding.reference


# ---------------------------------------------------------------------------
# What must NOT reach the error channel
# ---------------------------------------------------------------------------


def test_a_clean_run_returns_an_empty_list_not_none(monkeypatch: pytest.MonkeyPatch, index) -> None:
    """The contract is a list of findings; ``None`` would break every caller."""
    # Arrange: a rule that holds on the frame.
    inject(monkeypatch, build_rule(expression="{c0010} = {c0010}"))

    # Act
    findings = check_index(index)

    # Assert
    assert findings == []


def test_a_vacuous_rule_produces_no_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule whose operands are all zero is no evidence — and no defect."""
    # Arrange
    index = build_index(c_02_00=build_frame({"0010": {"0010": 0.0, "0020": 0.0}}))
    inject(monkeypatch, build_rule())

    # Act
    report = evaluate_index(index)

    # Assert
    assert report.status_counts()[STATUS_VACUOUS] == 1
    assert rule_breaks(index) == []


def test_a_rule_on_an_unemitted_template_produces_no_finding(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """A structural gap is a skip with a reason, never a break."""
    # Arrange
    inject(monkeypatch, build_rule(tables=("C 08.07",)))

    # Act
    report = evaluate_index(index)

    # Assert
    assert (report.outcomes[0].status, report.outcomes[0].reason) == (
        STATUS_NOT_EVALUATED,
        SKIP_TABLE_NOT_EMITTED,
    )
    assert rule_breaks(index) == []


def test_a_deactivated_rule_is_never_evaluated(monkeypatch: pytest.MonkeyPatch, index) -> None:
    """Only currently-enforced rules run — the catalogue's liveness is honoured here."""
    # Arrange
    inject(monkeypatch, build_rule(status=("deactivated",), reactivated_on=None))

    # Act
    report = evaluate_index(index)

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
    index = build_index(c_02_00=build_frame(cells))
    rule = build_rule(
        table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, tuple(cells))),)
    )
    inject(monkeypatch, rule)

    # Act
    findings = check_index(index)
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert len(findings) == 1
    assert (outcome.failed, outcome.evaluated) == (8, 8)


def test_only_the_first_few_failing_coordinates_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rest are noise; the full counts stay on the outcome."""
    # Arrange
    cells = {f"00{index:02d}": {"0010": 1.0, "0020": 2.0} for index in range(10, 18)}
    index = build_index(c_02_00=build_frame(cells))
    inject(
        monkeypatch,
        build_rule(table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, tuple(cells))),)),
    )

    # Act
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert len(outcome.failures) == MAX_RECORDED_FAILURES < outcome.failed


def test_a_rule_that_holds_on_some_rows_and_breaks_on_others_is_a_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One broken coordinate is enough — passes elsewhere do not excuse it."""
    # Arrange
    cells = {"0010": {"0010": 1.0, "0020": 1.0}, "0020": {"0010": 1.0, "0020": 2.0}}
    index = build_index(c_02_00=build_frame(cells))
    inject(
        monkeypatch,
        build_rule(
            table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, ("0010", "0020"))),)
        ),
    )

    # Act
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert (outcome.status, outcome.passed, outcome.failed) == (STATUS_FAIL, 1, 1)


# ---------------------------------------------------------------------------
# Refusals are recorded, never raised
# ---------------------------------------------------------------------------


def test_a_malformed_formula_is_recorded_as_a_skip(monkeypatch: pytest.MonkeyPatch, index) -> None:
    """An unparseable rule must not take the reporting run down."""
    # Arrange
    inject(monkeypatch, build_rule(expression="{c0010} = {c0020} &&"))

    # Act
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_UNSUPPORTED_GRAMMAR)


def test_an_unsupported_precondition_refuses_the_rule_rather_than_ignoring_it(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """Silently dropping a gating condition would evaluate the rule out of context."""
    # Arrange
    inject(monkeypatch, build_rule(precondition="{c0010} > 0"))

    # Act
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert (outcome.status, outcome.reason) == (
        STATUS_NOT_EVALUATED,
        SKIP_PRECONDITION_UNSUPPORTED,
    )


def test_an_unsupported_where_clause_refuses_the_rule(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """The ``where`` row filter is the same hazard as a precondition."""
    # Arrange
    inject(monkeypatch, build_rule(where="row_type = 'x'"))

    # Act
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_WHERE_UNSUPPORTED)


def test_an_unmappable_sheet_code_is_recorded_as_a_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A z-code whose meaning was never established must not be guessed at."""
    # Arrange: OF 08.01 code 0003 is deliberately absent from the sheet map.
    index = build_index("BASEL_3_1", c08_01={"institution": build_frame({"0010": {"0010": 1.0}})})
    inject(
        monkeypatch,
        build_rule(
            tables=("OF08.01.01.01",),
            table_scopes=(TableScope("OF08.01.01.01", sheets=RuleScope(SCOPE_LIST, ("0003",))),),
        ),
    )

    # Act
    outcome = evaluate_index(index).outcomes[0]

    # Assert
    assert outcome.status == STATUS_NOT_EVALUATED
    assert rule_breaks(index) == []


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_the_whole_enforced_population_runs_without_raising(framework: str) -> None:
    """Every packaged rule, against a near-empty estate, resolves to a status.

    The broadest guard there is: one raise anywhere in 1,549 enforced rules takes
    the reporting run down, and the conditions that provoke it (absent templates,
    empty frames, unmappable sheets) are exactly what a partial run produces.
    """
    # Arrange: one template, one row, one column — almost everything is absent.
    index = build_index(framework, c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act
    report = evaluate_index(index)

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
    index = build_index(framework, c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act
    report = evaluate_index(index)

    # Assert
    unexplained = [
        o.rule_id for o in report.outcomes if o.status == STATUS_NOT_EVALUATED and not o.reason
    ]
    assert unexplained == []


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_an_entirely_empty_index_is_survivable(framework: str) -> None:
    """A return carrying no template at all still yields a report, not a crash."""
    # Arrange
    index = build_index(framework)

    # Act
    report = evaluate_index(index)

    # Assert: no rule broke — but see the coverage guard below, which is what
    # stops that emptiness being read as a clean estate.
    assert report.status_counts()[STATUS_FAIL] == 0
    assert rule_breaks(index) == []


# ---------------------------------------------------------------------------
# The VAL003 coverage guard
#
# The guard itself is pinned against the real catalogue in test_coverage_guard.py.
# What belongs here is the one interaction between coverage and the ADAPTER: a
# rule the checker refused to parse must not confer coverage on the template it
# names, or an estate could be waved through by rules that never ran.
# ---------------------------------------------------------------------------


def test_a_rule_that_never_executed_does_not_count_towards_coverage(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """Coverage counts EXECUTED rules; a skipped one exercised nothing."""
    # Arrange: the rule names C 02.00 but cannot be parsed.
    inject(monkeypatch, build_rule(expression="if {c0010} > 0 then {c0020} = 1"))

    # Act
    report = evaluate_index(index)

    # Assert
    assert (report.rules_executed, report.templates_uncovered) == (0, ("c_02_00",))


def test_a_clean_covered_estate_yields_no_finding_of_any_kind(
    monkeypatch: pytest.MonkeyPatch, index
) -> None:
    """The green light: every emitted template checked, and every rule holding."""
    # Arrange
    inject(monkeypatch, build_rule(expression="{c0010} = {c0010}"))

    # Act
    findings = check_index(index)

    # Assert
    assert findings == []
