"""
A known issue with a published rule is a label on the result — never a change to the verdict.

Pipeline position:
    CanonicalReturn  ->  validate_return  ->  boe.engine  ->  validate.execution
        ->  validate.issue_labels (the release's publisher-issue register)
        ->  RuleReport.issue_notes, Finding.publisher_issues, the report and evidence

What is pinned:
- a broken rule a register issue names still blocks, with the same code,
  severity, subject and figures; its message gains the issue's sentence and
  the finding names the issue;
- with and without the register, the verdict, every result, every rule
  fingerprint and the evidence id are identical;
- a break outside the issue's footprint is not explained by it, and the two
  messages differ (``.claude/LESSONS.md`` B9: an alarm that fires on both is
  no alarm);
- every unsatisfied evaluation is classified, beyond the five a result keeps;
- a rule whose fingerprint is not the one the issue pinned is not labelled;
- each effect labels only the result it is about, a rule the Bank deactivated
  is told by the deny list and never labelled, whatever the issue's effect, and
  a withdrawn issue labels nothing;
- the report and the evidence carry the labels where their schemas say.

References:
- rwa_filer.boe.issues — the register
- rwa_filer.validate.issue_labels — the labels
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Any

import jsonschema
import polars as pl
import pytest

from boe_builders import T01, T02, T04, book, issue_register, ref, rule
from pack_builders import SAMPLE_MODULE, build_pack, build_return
from rwa_filer.boe.deny import DENY_DEACTIVATED, DenyEntry, DenyList
from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    REASON_DEACTIVATED_BY_PUBLISHER,
    REASON_NO_DATA,
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    Accuracy,
    RuleResult,
)
from rwa_filer.boe.issues import (
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_NEVER_RUNS,
    EFFECT_NO_RULE_EFFECT,
    EFFECT_PASSES_WRONG_RETURNS,
    STATUS_WITHDRAWN,
    IssueRegister,
    issues_from,
)
from rwa_filer.evidence import collect_evidence, read_evidence, write_evidence
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.release import release_for_pack
from rwa_filer.schemas import EVIDENCE_SCHEMA, VALIDATION_REPORT_SCHEMA, load_schema
from rwa_filer.validate.checker import FINDING_RULE_ERROR
from rwa_filer.validate.issue_labels import label_results
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import VERDICT_BLOCKED, trace_return, validate_return

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.returns import ReturnValidation

EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)
RUN = date(2026, 11, 16)

#: T01 total = parts; the facts below break it (100 != 60 + 30).
FOOTING = rule(
    "tst_0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
#: Holds on T01, so the template stays covered.
POSITIVE = rule("tst_0002", f"{ref(T01, '0010', '0010')} >= 0", tables=(T01,))
#: T02 row 0010 = row 0020, once per sheet (the sheet axis is left open).
PER_SHEET = rule("tst_0003", f"{ref(T02, '0010')} i= {ref(T02, '0020')}", tables=(T02,))
#: Every open row of T04 holds at least 1,000 in column 0010.
PER_ROW = rule("tst_0004", f"{ref(T04, c='0010')} >= 1000", tables=(T04,))

_SCHEMA = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}


def _facts(*rows: tuple[str, str | None, str | None, str, str, float | None, str | None]) -> Any:
    return pl.DataFrame(list(rows), schema=_SCHEMA, orient="row")


BROKEN_T01 = _facts(
    (T01, None, None, "0010", "0010", 100.0, None),
    (T01, None, None, "0020", "0010", 60.0, None),
    (T01, None, None, "0030", "0010", 30.0, None),
)


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def _release(pack: TaxonomyPack, register: IssueRegister | None = None, *rules: Rule) -> Release:
    release = release_for_pack(pack, book(*(rules or (FOOTING, POSITIVE))), today=RUN)
    return replace(release, issues=register or IssueRegister.empty("1.0.0"))


def _finding(validation: ReturnValidation, rule_id: str) -> Any:
    return next(item for item in validation.rules if item.subject == rule_id)


def _result(validation: ReturnValidation, rule_id: str) -> RuleResult:
    assert validation.report is not None
    return next(item for item in validation.report.results if item.rule_id == rule_id)


# ---------------------------------------------------------------------------
# The label, and the verdict it leaves alone
# ---------------------------------------------------------------------------


def test_a_broken_rule_with_a_publisher_issue_still_blocks_and_is_labelled(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    ret = build_return(BROKEN_T01)

    # Act
    validation = validate_return(
        ret, release=_release(pack, issue_register(FOOTING)), accuracy=EXACT
    )

    # Assert
    assert validation.report is not None
    finding = _finding(validation, "tst_0001")
    notes = validation.report.notes_for("tst_0001")
    assert validation.status == VERDICT_BLOCKED
    assert not validation.is_submittable
    assert (finding.code, finding.severity) == (FINDING_RULE_ERROR, "ERROR")
    assert finding.publisher_issues == ("PI-01",)
    assert [(note.issue_id, note.inside, note.outside) for note in notes] == [("PI-01", 1, 0)]
    assert finding.message.endswith(notes[0].sentence)
    assert "Known issue with the published rule (PI-01" in finding.message
    assert "identified by rwa-filer, not yet raised with the Bank of England" in finding.message


def test_the_verdict_is_identical_with_and_without_theissue_register(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(BROKEN_T01)

    # Act
    plain = validate_return(ret, release=_release(pack), accuracy=EXACT)
    labelled = validate_return(ret, release=_release(pack, issue_register(FOOTING)), accuracy=EXACT)

    # Assert
    def verdict(validation: ReturnValidation) -> Any:
        record = to_record(ret, validation)
        return (
            validation.status,
            validation.is_submittable,
            [finding.code for finding in validation.blocking],
            validation.report.results if validation.report else None,
            [
                (item.code, item.severity, item.subject, item.expected, item.actual)
                for item in validation.findings
            ],
            [(item["rule_id"], item["rule_sha256"]) for item in record["rules"]],
            record["identity"]["evidence_id"],
        )

    assert verdict(labelled) == verdict(plain)
    assert _finding(plain, "tst_0001").publisher_issues == ()
    assert _finding(labelled, "tst_0001").message != _finding(plain, "tst_0001").message


def test_a_break_outside_the_footprint_is_not_explained(pack: TaxonomyPack) -> None:
    """The same rule, the same issue, a break on each side of the footprint: two answers."""
    # Arrange — the issue applies on sheet 0001 only.
    register = issue_register(PER_SHEET, footprint=[{"table": T02, "sheets": ["0001"]}])
    release = _release(pack, register, PER_SHEET)
    inside = build_return(
        _facts(
            (T02, "0001", None, "0010", "0010", 10.0, None),
            (T02, "0001", None, "0020", "0010", 20.0, None),
            (T02, "0002", None, "0010", "0010", 10.0, None),
            (T02, "0002", None, "0020", "0010", 10.0, None),
        )
    )
    outside = build_return(
        _facts(
            (T02, "0001", None, "0010", "0010", 10.0, None),
            (T02, "0001", None, "0020", "0010", 10.0, None),
            (T02, "0002", None, "0010", "0010", 10.0, None),
            (T02, "0002", None, "0020", "0010", 20.0, None),
        )
    )

    # Act
    on_it = validate_return(inside, release=release, accuracy=EXACT)
    off_it = validate_return(outside, release=release, accuracy=EXACT)

    # Assert
    assert on_it.report is not None
    assert off_it.report is not None
    (note_in,) = on_it.report.notes_for("tst_0003")
    (note_out,) = off_it.report.notes_for("tst_0003")
    assert (note_in.inside, note_in.outside) == (1, 0)
    assert (note_out.inside, note_out.outside) == (0, 1)
    assert "are where a return that follows the reporting instructions breaks it" in (
        note_in.sentence
    )
    assert "not explained by it" in note_out.sentence
    assert _finding(on_it, "tst_0003").message != _finding(off_it, "tst_0003").message


def test_every_break_is_classified_when_there_are_more_than_the_recorded_failures(
    pack: TaxonomyPack,
) -> None:
    """Seven breaks, five recorded on the result: the label counts all seven."""
    # Arrange — seven open rows under 1,000; the issue applies to the first four.
    rows = [f"g{number}" for number in range(1, 8)]
    register = issue_register(PER_ROW, footprint=[{"table": T04, "rows": rows[:4]}])
    release = _release(pack, register, PER_ROW)
    facts = [(T04, None, None, row, "0005", None, row) for row in rows]
    facts += [(T04, None, None, row, "0010", 500.0, None) for row in rows]
    ret = build_return(_facts(*facts))

    # Act
    validated = validate_return(ret, release=release, accuracy=EXACT)
    traced, _trace = trace_return(ret, release=release, accuracy=EXACT)

    # Assert
    result = _result(validated, "tst_0004")
    assert result.unsatisfied == 7, "the fixture must break more than the recorded failures"
    assert len(result.failures) < result.unsatisfied
    for validation in (validated, traced):
        assert validation.report is not None
        (note,) = validation.report.notes_for("tst_0004")
        assert (note.inside, note.outside) == (4, 3)
        assert note.inside + note.outside == note.unsatisfied == 7


def test_a_rule_whose_fingerprint_differs_from_the_pin_is_not_labelled(
    pack: TaxonomyPack, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — the issue pinned the rule before a one-character change.
    pinned = rule("tst_0001", FOOTING.expression.replace("i+", "i-"), tables=FOOTING.tables)
    register = issue_register(FOOTING, sha=pinned.fingerprint(SAMPLE_MODULE))
    ret = build_return(BROKEN_T01)

    # Act
    with caplog.at_level(logging.WARNING, logger="rwa_filer.validate.issue_labels"):
        labelled = validate_return(ret, release=_release(pack, register), accuracy=EXACT)
    plain = validate_return(ret, release=_release(pack), accuracy=EXACT)

    # Assert
    assert labelled.report is not None
    assert labelled.report.notes_for("tst_0001") == ()
    assert _finding(labelled, "tst_0001").message == _finding(plain, "tst_0001").message
    assert any("PI-01" in record.getMessage() for record in caplog.records)


def test_a_possible_attribution_says_may_be(pack: TaxonomyPack) -> None:
    # Arrange
    register = issue_register(FOOTING, attribution="possible")

    # Act
    validation = validate_return(
        build_return(BROKEN_T01), release=_release(pack, register), accuracy=EXACT
    )

    # Assert
    assert validation.report is not None
    (note,) = validation.report.notes_for("tst_0001")
    assert "may be" in note.sentence


def test_a_clarification_is_worded_as_an_open_question_that_may_explain_the_break(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    register = issue_register(FOOTING, kind="clarification", attribution="possible")

    # Act
    validation = validate_return(
        build_return(BROKEN_T01), release=_release(pack, register), accuracy=EXACT
    )

    # Assert
    assert validation.report is not None
    (note,) = validation.report.notes_for("tst_0001")
    assert note.kind == "clarification"
    assert note.sentence.startswith("Open question with the published rule (PI-01")
    assert "may be where the published rule is open to question" in note.sentence
    assert "known to be wrong" not in note.sentence
    assert note.heading == "Open question with the published rule"


def test_an_acknowledged_issue_says_where_the_banks_log_records_it(pack: TaxonomyPack) -> None:
    # Arrange
    register = issue_register(FOOTING, kind="acknowledged", status="acknowledged")
    payload = register.to_payload()
    payload["issues"][0]["publisher_reference"] = "known issue 22 (published 2 October 2026)"
    payload["issues"][0]["publisher_log"] = [
        {"entry": 22, "published": "2026-10-02", "relation": "acknowledges", "statement": "x"}
    ]
    register = issues_from(payload, file="1.0.0.json")

    # Act
    validation = validate_return(
        build_return(BROKEN_T01), release=_release(pack, register), accuracy=EXACT
    )

    # Assert
    assert validation.report is not None
    (note,) = validation.report.notes_for("tst_0001")
    assert (note.kind, note.status) == ("acknowledged", "acknowledged")
    assert note.sentence.startswith(
        "Known issue with the published rule (PI-01, acknowledged by the Bank of England: "
        "known issue 22 (published 2 October 2026))"
    )


# ---------------------------------------------------------------------------
# Which result each effect labels
# ---------------------------------------------------------------------------


def _outcome(status: str, reason: str = "", **counts: int) -> RuleResult:
    return RuleResult(
        rule_id="tst_0001",
        severity="ERROR",
        status=status,
        reason=reason,
        satisfied=counts.get("satisfied", 0),
        unsatisfied=counts.get("unsatisfied", 0),
        tables=(T01,),
    )


@pytest.mark.parametrize(
    ("effect", "result", "labelled"),
    [
        (EFFECT_FAILS_CORRECT_RETURNS, _outcome(STATUS_FAIL, unsatisfied=1), True),
        (EFFECT_FAILS_CORRECT_RETURNS, _outcome(STATUS_PASS, satisfied=1), False),
        (EFFECT_PASSES_WRONG_RETURNS, _outcome(STATUS_PASS, satisfied=1), True),
        (EFFECT_PASSES_WRONG_RETURNS, _outcome(STATUS_FAIL, unsatisfied=1), False),
        (EFFECT_NEVER_RUNS, _outcome(STATUS_NOT_EVALUATED, REASON_CLOSED_BY_FORMULA), True),
        (EFFECT_NEVER_RUNS, _outcome(STATUS_NOT_EVALUATED, REASON_NO_DATA), True),
        (EFFECT_NEVER_RUNS, _outcome(STATUS_NOT_EVALUATED, REASON_NOT_REPORTED), False),
        # With the row above, every not-run reason outside NEVER_RUNS_REASONS
        # is pinned unlabelled: the Bank's deny list, a table the taxonomy does
        # not have, and grammar the engine does not implement.
        (
            EFFECT_NEVER_RUNS,
            _outcome(STATUS_NOT_EVALUATED, REASON_DEACTIVATED_BY_PUBLISHER),
            False,
        ),
        (EFFECT_NEVER_RUNS, _outcome(STATUS_NOT_EVALUATED, REASON_UNKNOWN_TABLE), False),
        (EFFECT_NEVER_RUNS, _outcome(STATUS_NOT_EVALUATED, REASON_UNSUPPORTED), False),
        (EFFECT_NEVER_RUNS, _outcome(STATUS_FAIL, unsatisfied=1), False),
        (EFFECT_NO_RULE_EFFECT, _outcome(STATUS_FAIL, unsatisfied=1), False),
        (
            EFFECT_FAILS_CORRECT_RETURNS,
            _outcome(STATUS_NOT_EVALUATED, REASON_DEACTIVATED_BY_PUBLISHER),
            False,
        ),
    ],
)
def test_each_effect_labels_only_its_status(
    effect: str, result: RuleResult, labelled: bool
) -> None:
    # Act
    notes = label_results(
        (result,),
        book(FOOTING),
        issue_register(FOOTING, effect=effect),
        SAMPLE_MODULE,
        evaluations=(),
    )

    # Assert
    assert bool(notes) is labelled


def test_a_withdrawn_issue_labels_nothing() -> None:
    # Act
    notes = label_results(
        (_outcome(STATUS_FAIL, unsatisfied=1),),
        book(FOOTING),
        issue_register(FOOTING, status=STATUS_WITHDRAWN),
        SAMPLE_MODULE,
        evaluations=(),
    )

    # Assert
    assert notes == ()


def test_a_rule_the_bank_deactivated_is_told_by_the_deny_list_not_labelled(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    release = replace(
        _release(pack, issue_register(FOOTING)),
        deny_list=DenyList(
            release="1.0.0",
            entries=(DenyEntry("tst_0001", SAMPLE_MODULE, DENY_DEACTIVATED, date(2026, 10, 19)),),
        ),
    )

    # Act
    validation = validate_return(build_return(BROKEN_T01), release=release, accuracy=EXACT)

    # Assert
    assert validation.report is not None
    assert _result(validation, "tst_0001").reason == REASON_DEACTIVATED_BY_PUBLISHER
    assert validation.report.notes_for("tst_0001") == ()


# ---------------------------------------------------------------------------
# The report and the evidence
# ---------------------------------------------------------------------------


def test_the_record_carries_the_issue_on_the_rule_the_finding_and_the_summary(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    ret = build_return(BROKEN_T01)
    validation = validate_return(
        ret, release=_release(pack, issue_register(FOOTING)), accuracy=EXACT
    )

    # Act
    record = to_record(ret, validation)
    text = render_text(ret, validation)

    # Assert
    jsonschema.Draft202012Validator(load_schema(VALIDATION_REPORT_SCHEMA)).validate(record)
    rule_record = next(item for item in record["rules"] if item["rule_id"] == "tst_0001")
    finding = next(item for item in record["findings"] if item["subject"] == "tst_0001")
    assert [note["issue"] for note in rule_record["publisher_issues"]] == ["PI-01"]
    assert finding["publisher_issues"] == ["PI-01"]
    assert record["summary"]["publisher_issues"] == [
        {
            "issue": "PI-01",
            "status": "draft",
            "effect": EFFECT_FAILS_CORRECT_RETURNS,
            "rules": ["tst_0001"],
            "breaks_inside": 1,
            "breaks_outside": 0,
        }
    ]
    assert record["identity"]["publisher_issues"]["file"] == "1.0.0.json"
    assert "known issues with the published rules" in text
    assert text.splitlines()[0].startswith("BLOCKED:")


def test_a_labelled_rule_and_its_evaluations_carry_the_issue_in_the_evidence(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange
    register = issue_register(PER_SHEET, footprint=[{"table": T02, "sheets": ["0001"]}])
    ret = build_return(
        _facts(
            (T02, "0001", None, "0010", "0010", 10.0, None),
            (T02, "0001", None, "0020", "0010", 20.0, None),
            (T02, "0002", None, "0010", "0010", 10.0, None),
            (T02, "0002", None, "0020", "0010", 30.0, None),
        )
    )
    release = _release(pack, register, PER_SHEET)

    # Act
    evidence = collect_evidence(ret, release=release, accuracy=EXACT)
    written = write_evidence(evidence, tmp_path / "out.evidence.jsonl")
    document = read_evidence(written.path)
    plain = collect_evidence(ret, release=_release(pack, None, PER_SHEET), accuracy=EXACT)

    # Assert
    validator = jsonschema.Draft202012Validator(load_schema(EVIDENCE_SCHEMA))
    for line in (document.header, *document.rules, *document.evaluations):
        validator.validate(line)
    (rule_line,) = (item for item in document.rules if item["rule_id"] == "tst_0003")
    assert [note["issue"] for note in rule_line["publisher_issues"]] == ["PI-01"]
    marks = sorted(
        (item["place"].get("z"), tuple(item["publisher_issues"]))
        for item in document.evaluations
        if item["rule_id"] == "tst_0003"
    )
    assert marks == [("0001", ("PI-01",)), ("0002", ())]
    assert document.header["identity"]["evidence_id"] == plain.identity["evidence_id"]
    assert document.header["identity"]["publisher_issues"]["issues"] == 1
