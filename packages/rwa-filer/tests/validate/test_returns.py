"""
Return-level validation: a canonical return, read against a pack, run through the rules.

What is pinned here is the bridge — that a return already in the publisher's
coordinates reaches the rule engine through IDENTITY bindings, that its sheets
are keyed the way the engine expects, and that the verdict combines structure
and rule findings honestly. The rules themselves are injected, so nothing here
moves when a publisher's rule set does.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from filer_builders import build_rule
from pack_builders import SAMPLE_MODULE, build_pack, build_return
from rwa_filer.rules.catalogue import (
    FRAMEWORK_BASEL_3_1,
    SCOPE_LIST,
    SEVERITY_WARNING,
    RuleScope,
    RuleSet,
    TableScope,
)
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
)
from rwa_filer.validate.evaluate import GEOGRAPHY_TOTAL_SHEET, STATUS_FAIL, STATUS_PASS
from rwa_filer.validate.index import SINGLE_SHEET
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import MODULE_FRAMEWORKS, index_from_return, validate_return
from rwa_filer.validate.structure import FINDING_CELL_NOT_REPORTABLE

FRAMEWORK = FRAMEWORK_BASEL_3_1


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


def ruleset(*rules) -> RuleSet:
    return RuleSet(framework=FRAMEWORK, publisher="BoE", source={}, rules=tuple(rules))


#: T02: exposure (r0010) and RWEA (r0020) on two sheets; T01 total = parts.
RETURN = facts(
    ("T01.00.01.01", None, None, "0010", "0010", 100.0, None),
    ("T01.00.01.01", None, None, "0020", "0010", 60.0, None),
    ("T01.00.01.01", None, None, "0030", "0010", 40.0, None),
    ("T01.00.01.01", None, None, "0010", "0030", None, "a comment"),
    ("T02.00.01.01", "0001", None, "0010", "0010", 60.0, None),
    ("T02.00.01.01", "0001", None, "0020", "0010", 30.0, None),
    ("T02.00.01.01", "0002", None, "0010", "0010", 40.0, None),
    ("T02.00.01.01", "0002", None, "0020", "0010", 50.0, None),
    ("T03.00.01.01", None, "x1", "0010", "0010", 100.0, None),
    ("T03.00.01.01", None, "GB", "0010", "0010", 70.0, None),
)

#: ``total = part one + part two`` on T01.
FOOTING = build_rule(
    rule_id="tst_0001",
    publisher="BoE",
    framework=FRAMEWORK,
    tables=("T01.00.01.01",),
    expression="{r: 0010} = {r: 0020} + {r: 0030}",
    table_scopes=(TableScope("T01.00.01.01", columns=RuleScope(SCOPE_LIST, ("0010",))),),
)
#: ``RWEA <= exposure`` on every sheet of T02 — breaks on sheet 0002 (50 > 40).
RWEA_CAP = build_rule(
    rule_id="tst_0002",
    publisher="BoE",
    framework=FRAMEWORK,
    tables=("T02.00.01.01",),
    expression="{r: 0020, c: 0010} <= {r: 0010, c: 0010}",
)


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


def test_each_table_answers_to_its_own_frames(pack: TaxonomyPack) -> None:
    # Act
    index = index_from_return(build_return(RETURN), pack, FRAMEWORK)

    # Assert
    assert sorted(index.frames) == ["T01.00.01.01", "T02.00.01.01", "T03.00.01.01"]
    assert index.binding("T02.00.01.01").attribute == "T02.00.01.01"
    assert index.is_emitted("T01.00.01.01") and not index.is_emitted("T04.00.01.01")


def test_a_single_sheet_table_is_keyed_by_the_single_sheet_sentinel(pack: TaxonomyPack) -> None:
    # Act
    index = index_from_return(build_return(RETURN), pack, FRAMEWORK)

    # Assert
    assert index.sheet_keys("T01.00.01.01") == (SINGLE_SHEET,)
    assert index.cell("T01.00.01.01", SINGLE_SHEET, "0010", "0010").value == 100.0


def test_fixed_sheets_are_keyed_by_their_published_codes(pack: TaxonomyPack) -> None:
    # Act
    index = index_from_return(build_return(RETURN), pack, FRAMEWORK)

    # Assert
    assert index.sheet_keys("T02.00.01.01") == ("0001", "0002")
    assert index.cell("T02.00.01.01", "0002", "0020", "0010").value == 50.0


def test_the_sheet_map_is_the_identity_over_the_published_codes(pack: TaxonomyPack) -> None:
    # Act
    sheet_map = index_from_return(build_return(RETURN), pack, FRAMEWORK).sheet_maps["T02.00.01.01"]

    # Assert — one key per code, each its own: closed by construction.
    assert {code: entry.bundle_keys for code, entry in sheet_map.items()} == {
        "0001": ("0001",),
        "0002": ("0002",),
    }


def test_the_geography_total_is_keyed_as_the_engine_addresses_it(pack: TaxonomyPack) -> None:
    # Act
    index = index_from_return(build_return(RETURN), pack, FRAMEWORK)

    # Assert
    assert index.sheet_keys("T03.00.01.01") == ("GB", GEOGRAPHY_TOTAL_SHEET)
    assert index.cell("T03.00.01.01", GEOGRAPHY_TOTAL_SHEET, "0010", "0010").value == 100.0


def test_text_facts_are_not_presented_as_figures(pack: TaxonomyPack) -> None:
    # Act
    index = index_from_return(build_return(RETURN), pack, FRAMEWORK)

    # Assert — column 0030 of T01 holds only a comment, so it is not a column.
    assert "0030" not in index.column_refs("T01.00.01.01", SINGLE_SHEET)


def test_an_unreported_cell_is_absent_not_zero(pack: TaxonomyPack) -> None:
    # Act
    cell = index_from_return(build_return(RETURN), pack, FRAMEWORK).cell(
        "T01.00.01.01", SINGLE_SHEET, "0010", "0020"
    )

    # Assert
    assert not cell.present


# ---------------------------------------------------------------------------
# validate_return
# ---------------------------------------------------------------------------


def test_a_sound_return_that_satisfies_its_rules_is_submittable(pack: TaxonomyPack) -> None:
    # Arrange — only the rule that holds, and only the table it covers.
    ret = build_return(RETURN.filter(pl.col("table") == "T01.00.01.01"))

    # Act
    validation = validate_return(ret, pack, ruleset=ruleset(FOOTING))

    # Assert
    assert validation.findings == ()
    assert validation.is_submittable
    assert validation.report.status_counts()[STATUS_PASS] == 1


def test_a_broken_error_rule_blocks_submission(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(RETURN.filter(pl.col("table") == "T02.00.01.01"))

    # Act
    validation = validate_return(ret, pack, ruleset=ruleset(RWEA_CAP))

    # Assert
    assert [f.code for f in validation.rules] == [FINDING_RULE_ERROR]
    assert not validation.is_submittable
    outcome = validation.report.by_status(STATUS_FAIL)[0]
    assert outcome.coordinates == ("T02.00.01.01[0002]",)


def test_a_broken_warning_rule_is_reported_but_does_not_block(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(RETURN.filter(pl.col("table") == "T02.00.01.01"))
    warning = build_rule(
        rule_id="tst_0003",
        publisher="BoE",
        framework=FRAMEWORK,
        severity=SEVERITY_WARNING,
        tables=("T02.00.01.01",),
        expression="{r: 0020, c: 0010} <= {r: 0010, c: 0010}",
    )

    # Act
    validation = validate_return(ret, pack, ruleset=ruleset(warning))

    # Assert
    assert [f.code for f in validation.rules] == [FINDING_RULE_WARNING]
    assert validation.is_submittable and validation.blocking == ()


def test_structure_findings_come_first_and_block(pack: TaxonomyPack) -> None:
    # Arrange — a figure in the one greyed cell of T01, plus a rule that holds.
    frame = pl.concat(
        [
            RETURN.filter(pl.col("table") == "T01.00.01.01"),
            facts(("T01.00.01.01", None, None, "0030", "0020", 0.5, None)),
        ]
    )

    # Act
    validation = validate_return(build_return(frame), pack, ruleset=ruleset(FOOTING))

    # Assert
    assert [f.code for f in validation.findings] == [FINDING_CELL_NOT_REPORTABLE]
    assert not validation.is_submittable


def test_a_reported_table_no_rule_reached_is_a_coverage_finding(pack: TaxonomyPack) -> None:
    """T02 and T03 are reported but only T01 has a rule: that is not a clean result."""
    # Act
    validation = validate_return(build_return(RETURN), pack, ruleset=ruleset(FOOTING))

    # Assert
    assert [f.code for f in validation.rules] == [FINDING_COVERAGE_INSUFFICIENT]
    assert not validation.is_submittable


def test_a_module_with_no_packaged_rules_has_only_its_structure_checked(
    pack: TaxonomyPack,
) -> None:
    # Arrange — adequacy: the synthetic module really has no packaged rule set.
    assert SAMPLE_MODULE not in MODULE_FRAMEWORKS

    # Act
    validation = validate_return(build_return(RETURN), pack)

    # Assert
    assert validation.report is None and validation.rules == ()
    assert validation.is_submittable


def test_nothing_executed_is_reported_as_such(pack: TaxonomyPack) -> None:
    # Arrange — a rule on a table the return does not carry.
    ret = build_return(RETURN.filter(pl.col("table") == "T01.00.01.01"))

    # Act
    validation = validate_return(ret, pack, ruleset=ruleset(RWEA_CAP))

    # Assert
    assert [(f.code, f.subject) for f in validation.rules] == [
        (FINDING_COVERAGE_INSUFFICIENT, COVERAGE_NO_RULE_EXECUTED)
    ]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_the_record_is_self_contained_and_json_ready(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(RETURN.filter(pl.col("table") == "T02.00.01.01"))
    validation = validate_return(ret, pack, ruleset=ruleset(RWEA_CAP))

    # Act
    record = to_record(ret, validation)

    # Assert
    assert record["submittable"] is False
    assert record["header"]["Module"] == SAMPLE_MODULE
    assert record["taxonomy"]["version"] == "1.0.0"
    assert record["summary"]["rules_executed"] == 1
    assert record["summary"]["rule_status"][STATUS_FAIL] == 1
    assert [f["code"] for f in record["findings"]] == [FINDING_RULE_ERROR]
    assert record["rules"][0]["rule_id"] == "tst_0002"
    assert record["rules"][0]["cells"] == ["T02.00.01.01[0002]"]


def test_the_text_report_leads_with_the_verdict_and_the_counts(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(RETURN.filter(pl.col("table") == "T02.00.01.01"))
    validation = validate_return(ret, pack, ruleset=ruleset(RWEA_CAP))

    # Act
    text = render_text(ret, validation)

    # Assert
    assert text.startswith("BLOCKED: TST001")
    assert "1 of 1 executed" in text and "1 failed" in text
    assert "[VAL001] ERROR" in text
    assert "authoritative" in text.splitlines()[-1]


def test_a_clean_text_report_says_submittable(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(RETURN.filter(pl.col("table") == "T01.00.01.01"))

    # Act
    text = render_text(ret, validate_return(ret, pack, ruleset=ruleset(FOOTING)))

    # Assert
    assert text.startswith("SUBMITTABLE: TST001")
