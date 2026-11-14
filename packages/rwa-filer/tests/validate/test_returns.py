"""
Return-level validation: a canonical return, read against a pack, run through the rules.

What is pinned here is the VERDICT — how structure findings and rule results
combine into "may this be submitted", and what makes an empty result mean
something. The rules themselves are injected, in the published syntax, so
nothing here moves when the Bank's rule books do; how a rule is evaluated is
pinned in ``tests/boe/test_engine.py``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01, T02, T03, book, ref, rule
from pack_builders import SAMPLE_MODULE, build_pack, build_return
from rwa_filer.boe.catalogue import RuleBookNotFoundError, rulebook_for_module
from rwa_filer.boe.engine import (
    REASON_NOT_REPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    Accuracy,
)
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    Finding,
)
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import validate_return
from rwa_filer.validate.structure import FINDING_CELL_NOT_REPORTABLE

#: The figures here are small and the tests are about the verdict, not about
#: rounding, so where a break must be a break the facts are taken as exact.
EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def facts(*rows: tuple[object, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        list(rows),
        schema={
            "table": pl.String,
            "sheet": pl.String,
            "open_key": pl.String,
            "row": pl.String,
            "column": pl.String,
            "value": pl.Float64,
            "text_value": pl.String,
        },
        orient="row",
    )


#: T01 total = parts; T02 exposure (r0010) and RWEA (r0020) on two sheets; T03 by country.
RETURN = facts(
    (T01, None, None, "0010", "0010", 100.0, None),
    (T01, None, None, "0020", "0010", 60.0, None),
    (T01, None, None, "0030", "0010", 40.0, None),
    (T01, None, None, "0010", "0030", None, "a comment"),
    (T02, "0001", None, "0010", "0010", 60.0, None),
    (T02, "0001", None, "0020", "0010", 30.0, None),
    (T02, "0002", None, "0010", "0010", 40.0, None),
    (T02, "0002", None, "0020", "0010", 50.0, None),
    (T03, None, "x1", "0010", "0010", 100.0, None),
    (T03, None, "GB", "0010", "0010", 70.0, None),
)

#: ``total = part one + part two`` on T01.
FOOTING = rule(
    "tst_0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
#: ``RWEA <= exposure`` on every sheet of T02 — breaks on sheet 0002 (50 > 40).
RWEA_CAP = rule(
    "tst_0002", f"{ref(T02, '0020', '0010')} i<= {ref(T02, '0010', '0010')}", tables=(T02,)
)
#: A rule that holds on T03, so that table is covered where a test needs it to be.
GEOGRAPHY = rule("tst_0004", f"{ref(T03, '0010', '0010')} >= 0", tables=(T03,))


def only(table: str) -> pl.DataFrame:
    return RETURN.filter(pl.col("table") == table)


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def test_a_sound_return_that_satisfies_its_rules_is_submittable(pack: TaxonomyPack) -> None:
    # Act
    validation = validate_return(build_return(only(T01)), pack, rulebook=book(FOOTING))

    # Assert
    assert validation.findings == ()
    assert validation.is_submittable
    assert validation.report is not None
    assert validation.report.status_counts()[STATUS_PASS] == 1


def test_a_broken_error_rule_blocks_submission(pack: TaxonomyPack) -> None:
    # Act
    validation = validate_return(
        build_return(only(T02)), pack, rulebook=book(RWEA_CAP), accuracy=EXACT
    )

    # Assert — one finding for the rule, quoting where it first broke.
    (finding,) = validation.rules
    assert (finding.code, finding.subject) == (FINDING_RULE_ERROR, "tst_0002")
    assert "1 of 2 evaluation(s)" in finding.message and "sheet 0002" in finding.message
    assert not validation.is_submittable


def test_a_broken_warning_rule_is_reported_but_does_not_block(pack: TaxonomyPack) -> None:
    # Arrange
    warning = rule(
        "tst_0003",
        RWEA_CAP.expression,
        tables=(T02,),
        severities={SAMPLE_MODULE: "WARNING"},
    )

    # Act
    validation = validate_return(
        build_return(only(T02)), pack, rulebook=book(warning), accuracy=EXACT
    )

    # Assert
    assert [finding.code for finding in validation.rules] == [FINDING_RULE_WARNING]
    assert validation.is_submittable and validation.blocking == ()


def test_structure_findings_come_first_and_block(pack: TaxonomyPack) -> None:
    # Arrange — a figure in the one greyed cell of T01, plus a rule that holds.
    frame = pl.concat([only(T01), facts((T01, None, None, "0030", "0020", 0.5, None))])

    # Act
    validation = validate_return(build_return(frame), pack, rulebook=book(FOOTING))

    # Assert
    assert [finding.code for finding in validation.findings] == [FINDING_CELL_NOT_REPORTABLE]
    assert not validation.is_submittable


def test_findings_from_reading_the_source_are_reported_with_the_structure(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    stray = Finding("XBR001", "ERROR", "1 fact(s) are not data points", "ref", "TST001", "", "")

    # Act
    validation = validate_return(
        build_return(only(T01)), pack, rulebook=book(FOOTING), source_findings=[stray]
    )

    # Assert
    assert validation.structure == (stray,) and not validation.is_submittable


def test_only_rules_the_module_enforces_are_run(pack: TaxonomyPack) -> None:
    """Not in the taxonomy, deactivated, or another module's: the gateway does not run it."""
    # Arrange — three copies of a rule that would break, none of them enforced.
    broken = RWEA_CAP.expression
    rulebook = book(
        FOOTING,
        rule("not_serialised", broken, tables=(T02,), in_xbrl=False),
        rule("switched_off", broken, tables=(T02,), deactivated=True),
        rule("other_module", broken, tables=(T02,), severities={"OTHER": "ERROR"}),
    )

    # Act
    validation = validate_return(build_return(RETURN), pack, rulebook=rulebook)

    # Assert
    assert validation.report is not None
    assert [result.rule_id for result in validation.report.results] == ["tst_0001"]
    assert validation.report.rules_loaded == 4
    assert validation.is_submittable


def test_the_stated_accuracy_decides_a_rounding_sized_difference(pack: TaxonomyPack) -> None:
    """100,000 against 60,000 + 39,200: holds to thousands, breaks to the penny."""
    # Arrange
    frame = facts(
        (T01, None, None, "0010", "0010", 100_000.0, None),
        (T01, None, None, "0020", "0010", 60_000.0, None),
        (T01, None, None, "0030", "0010", 39_200.0, None),
    )

    # Act
    thousands = validate_return(build_return(frame), pack, rulebook=book(FOOTING))
    exact = validate_return(build_return(frame), pack, rulebook=book(FOOTING), accuracy=EXACT)

    # Assert — the default is the writer's default: thousands.
    assert thousands.is_submittable
    assert not exact.is_submittable


# ---------------------------------------------------------------------------
# Coverage — when an empty result means nothing
# ---------------------------------------------------------------------------


def test_a_reported_template_none_of_whose_rules_ran_is_a_coverage_finding(
    pack: TaxonomyPack,
) -> None:
    """T02 has a rule, T02 is reported, and the rule did not run: not a clean result."""
    # Arrange — the T02 rule also reads T03, which this return does not report,
    # so the gateway would not run it.
    needs_both = rule(
        "tst_0005",
        f"{ref(T02, '0010', '0010', '0001')} i<= {ref(T03, '0010', '0010')}",
        tables=(T02, T03),
    )
    frame = pl.concat([only(T01), only(T02)])

    # Act
    validation = validate_return(build_return(frame), pack, rulebook=book(FOOTING, needs_both))

    # Assert
    (finding,) = validation.rules
    assert (finding.code, finding.subject) == (
        FINDING_COVERAGE_INSUFFICIENT,
        COVERAGE_TEMPLATE_NOT_COVERED,
    )
    assert "T02.00.01" in finding.message and REASON_NOT_REPORTED in finding.message
    assert not validation.is_submittable


def test_a_reported_template_the_rule_book_has_no_rule_for_is_not_a_shortfall(
    pack: TaxonomyPack,
) -> None:
    """Nothing could have been run on T02 and T03, so nothing is missing."""
    # Act
    validation = validate_return(build_return(RETURN), pack, rulebook=book(FOOTING))

    # Assert
    assert validation.report is not None
    assert validation.report.templates_reported == ("T01.00.01", "T02.00.01", "T03.00.01")
    assert validation.report.templates_ruled == ("T01.00.01",)
    assert validation.findings == () and validation.is_submittable


def test_nothing_executed_is_reported_as_such(pack: TaxonomyPack) -> None:
    # Arrange — a rule on a table the return does not report.
    validation = validate_return(build_return(only(T01)), pack, rulebook=book(RWEA_CAP))

    # Assert
    assert [(finding.code, finding.subject) for finding in validation.rules] == [
        (FINDING_COVERAGE_INSUFFICIENT, COVERAGE_NO_RULE_EXECUTED)
    ]
    assert not validation.is_submittable


def test_a_module_with_no_packaged_rule_book_has_only_its_structure_checked(
    pack: TaxonomyPack,
) -> None:
    # Arrange — adequacy: the synthetic module really has no packaged rule book.
    with pytest.raises(RuleBookNotFoundError):
        rulebook_for_module(SAMPLE_MODULE)

    # Act
    validation = validate_return(build_return(RETURN), pack)

    # Assert
    assert validation.report is None and validation.rules == ()
    assert validation.is_submittable


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_the_record_is_self_contained_and_json_ready(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(pl.concat([only(T02), only(T03)]))
    validation = validate_return(ret, pack, rulebook=book(RWEA_CAP, GEOGRAPHY), accuracy=EXACT)

    # Act
    record = to_record(ret, validation)

    # Assert — passed rules are counted; only the rest are listed.
    assert record["submittable"] is False
    assert record["header"]["Module"] == SAMPLE_MODULE
    assert record["taxonomy"]["version"] == "1.0.0"
    assert record["summary"]["rule_book"] == "test 1.0.0"
    assert record["summary"]["rules_executed"] == 2
    assert record["summary"]["rule_status"] == {
        STATUS_PASS: 1,
        STATUS_FAIL: 1,
        STATUS_NOT_EVALUATED: 0,
    }
    assert [finding["code"] for finding in record["findings"]] == [FINDING_RULE_ERROR]
    (listed,) = record["rules"]
    assert (listed["rule_id"], listed["satisfied"], listed["unsatisfied"]) == ("tst_0002", 1, 1)
    assert listed["failures"][0]["place"] == "sheet 0002"


def test_the_text_report_leads_with_the_verdict_and_the_counts(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(only(T02))
    validation = validate_return(ret, pack, rulebook=book(RWEA_CAP), accuracy=EXACT)

    # Act
    text = render_text(ret, validation)

    # Assert
    assert text.startswith("BLOCKED: TST001")
    assert "1 of 1 executed" in text and "1 failed" in text
    assert "[VAL001] ERROR" in text
    assert "authoritative" in text.splitlines()[-1]


def test_the_text_report_says_why_rules_were_not_evaluated(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(only(T01))

    # Act
    text = render_text(ret, validate_return(ret, pack, rulebook=book(FOOTING, RWEA_CAP)))

    # Assert
    assert f"not evaluated because: {REASON_NOT_REPORTED} (1)" in text


def test_a_clean_text_report_says_submittable(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(only(T01))

    # Act
    text = render_text(ret, validate_return(ret, pack, rulebook=book(FOOTING)))

    # Assert
    assert text.startswith("SUBMITTABLE: TST001")
