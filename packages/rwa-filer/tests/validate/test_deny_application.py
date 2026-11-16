"""
The Bank's deny list applied to a validation: what the gateway no longer runs, or runs as a warning.

Pipeline position:
    CanonicalReturn  ->  validate_return  ->  boe.engine (every enforced rule, as
    the taxonomy's formula has it)  ->  validate.execution.apply_deny_list  ->  verdict

What is pinned:
- a rule the Bank has deactivated at its gateway, on or before the run date, is
  NOT_EVALUATED with reason ``deactivated_by_publisher`` — not a failure, and
  not a gap that leaves the check incomplete; what the formula found is kept
  beside it (``RuleResult.formula``), for the referee;
- a rule the Bank has downgraded is a Warning, so its break no longer blocks;
- an entry with no date, or applied after the run (or submission) date, or for
  another module, changes nothing;
- on the real 4.1.1 rule book, a return that breaks ``boe_b0710`` (known issue
  #22) is blocked by it before 19 October 2026 and not after.

References:
- Bank of England, "Banking validations deny list" (November 2026), sheet "Note"
- Bank of England, Banking taxonomy known-issues log, #22
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema
import polars as pl
import pytest

from boe_builders import T01, book, ref, rule
from compare_builders import corporate_return
from pack_builders import SAMPLE_MODULE, build_pack, build_return
from rwa_filer.boe.catalogue import SEVERITY_ERROR, SEVERITY_WARNING
from rwa_filer.boe.deny import DENY_DEACTIVATED, DENY_DOWNGRADED, DenyEntry, DenyList
from rwa_filer.boe.engine import (
    REASON_DEACTIVATED_BY_PUBLISHER,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    Accuracy,
)
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.release import release_for_pack, release_rulebook
from rwa_filer.schemas import VALIDATION_REPORT_SCHEMA, load_schema
from rwa_filer.validate.checker import FINDING_RULE_ERROR, FINDING_RULE_WARNING
from rwa_filer.validate.report import REPORT_SCHEMA_VERSION, render_text, to_record
from rwa_filer.validate.returns import VERDICT_CLEAN, validate_return

if TYPE_CHECKING:
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack

EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)
APPLIED = date(2026, 10, 19)
RUN = date(2026, 11, 16)

#: T01 total = parts, which this return breaks (100 != 60 + 30).
FOOTING = rule(
    "tst_0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
#: A rule that holds on T01, so the template stays covered when FOOTING is switched off.
POSITIVE = rule("tst_0002", f"{ref(T01, '0010', '0010')} >= 0", tables=(T01,))


def _facts() -> pl.DataFrame:
    return pl.DataFrame(
        [
            (T01, None, None, "0010", "0010", 100.0, None),
            (T01, None, None, "0020", "0010", 60.0, None),
            (T01, None, None, "0030", "0010", 30.0, None),
        ],
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


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def _release(pack: TaxonomyPack, *entries: DenyEntry) -> Release:
    """The synthetic pack's release, its rules FOOTING and POSITIVE, with ``entries`` denied."""
    release = release_for_pack(pack, book(FOOTING, POSITIVE), today=RUN)
    return replace(release, deny_list=DenyList(release="1.0.0", entries=entries))


def _deactivated(module: str = SAMPLE_MODULE, applied: date | None = APPLIED) -> DenyEntry:
    return DenyEntry("tst_0001", module, DENY_DEACTIVATED, applied, known_issue=22)


def _result(validation, rule_id: str):  # noqa: ANN001, ANN202 - test helper
    assert validation.report is not None
    return next(item for item in validation.report.results if item.rule_id == rule_id)


# ---------------------------------------------------------------------------
# Deactivated: not run at the gateway, so not a failure and not a gap
# ---------------------------------------------------------------------------


def test_a_deactivated_rule_is_not_evaluated_and_does_not_block(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(_facts())

    # Act
    validation = validate_return(ret, release=_release(pack, _deactivated()), accuracy=EXACT)

    # Assert
    result = _result(validation, "tst_0001")
    assert (result.status, result.reason) == (STATUS_NOT_EVALUATED, REASON_DEACTIVATED_BY_PUBLISHER)
    assert "deactivated by the Bank of England on 19 October 2026" in result.detail
    assert validation.is_submittable
    assert validation.status == VERDICT_CLEAN, "a deactivated rule is not a gap in the check"


def test_a_deactivated_rule_keeps_what_the_formula_found(pack: TaxonomyPack) -> None:
    """The referee compares Arelle, which runs the taxonomy's formula, with this."""
    validation = validate_return(
        build_return(_facts()), release=_release(pack, _deactivated()), accuracy=EXACT
    )

    result = _result(validation, "tst_0001")

    assert result.formula is not None
    assert (result.formula.status, result.formula.unsatisfied) == (STATUS_FAIL, 1)
    assert result.deny == _deactivated()


def test_without_the_entry_the_same_return_is_blocked(pack: TaxonomyPack) -> None:
    """The leg that stays red: the fixture really does break the rule."""
    validation = validate_return(build_return(_facts()), release=_release(pack), accuracy=EXACT)

    assert _result(validation, "tst_0001").status == STATUS_FAIL
    assert [item.subject for item in validation.blocking] == ["tst_0001"]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(_deactivated(applied=None), id="pending: no date applied"),
        pytest.param(_deactivated(applied=date(2026, 11, 17)), id="applied after the run date"),
        pytest.param(_deactivated(module="OTHER01"), id="another module's entry"),
    ],
)
def test_an_entry_not_in_force_for_this_module_on_this_date_changes_nothing(
    pack: TaxonomyPack, entry: DenyEntry
) -> None:
    validation = validate_return(
        build_return(_facts()), release=_release(pack, entry), accuracy=EXACT
    )

    result = _result(validation, "tst_0001")
    assert (result.status, result.deny, result.formula) == (STATUS_FAIL, None, None)
    assert not validation.is_submittable


def test_the_submission_date_decides_which_entries_apply(pack: TaxonomyPack) -> None:
    """The deny list is the gateway's configuration when the return is submitted."""
    release = _release(pack, _deactivated())

    before = validate_return(
        build_return(_facts()), release=release, accuracy=EXACT, submission_date=date(2026, 10, 18)
    )
    on = validate_return(
        build_return(_facts()), release=release, accuracy=EXACT, submission_date=APPLIED
    )

    assert _result(before, "tst_0001").status == STATUS_FAIL
    assert _result(on, "tst_0001").reason == REASON_DEACTIVATED_BY_PUBLISHER


# ---------------------------------------------------------------------------
# Downgraded: still run, but a break no longer blocks
# ---------------------------------------------------------------------------


def test_a_downgraded_rule_breaks_as_a_warning_and_says_why(pack: TaxonomyPack) -> None:
    # Arrange
    entry = DenyEntry("tst_0001", SAMPLE_MODULE, DENY_DOWNGRADED, APPLIED, known_issue=23)

    # Act
    validation = validate_return(
        build_return(_facts()), release=_release(pack, entry), accuracy=EXACT
    )

    # Assert
    result = _result(validation, "tst_0001")
    assert (result.status, result.severity) == (STATUS_FAIL, SEVERITY_WARNING)
    assert result.formula is not None and result.formula.severity == SEVERITY_ERROR
    (finding,) = validation.rules
    assert (finding.code, finding.severity) == (FINDING_RULE_WARNING, SEVERITY_WARNING)
    assert "downgraded from Error to Warning by the Bank of England" in finding.message
    assert "known issues log #23" in finding.message
    assert validation.is_submittable


def test_the_rule_fingerprint_is_the_published_rules_whatever_the_deny_list_says(
    pack: TaxonomyPack,
) -> None:
    entry = DenyEntry("tst_0001", SAMPLE_MODULE, DENY_DOWNGRADED, APPLIED)
    ret = build_return(_facts())

    plain = to_record(ret, validate_return(ret, release=_release(pack), accuracy=EXACT))
    denied = to_record(ret, validate_return(ret, release=_release(pack, entry), accuracy=EXACT))

    def sha(record: dict) -> str:
        return next(item for item in record["rules"] if item["rule_id"] == "tst_0001")[
            "rule_sha256"
        ]

    assert sha(denied) == sha(plain) == FOOTING.fingerprint(SAMPLE_MODULE)


# ---------------------------------------------------------------------------
# The report says what the Bank did
# ---------------------------------------------------------------------------


def test_the_report_records_the_entry_and_the_formula_verdict(pack: TaxonomyPack) -> None:
    # Arrange
    ret = build_return(_facts())
    validation = validate_return(ret, release=_release(pack, _deactivated()), accuracy=EXACT)

    # Act
    record = to_record(ret, validation)

    # Assert
    jsonschema.Draft202012Validator(load_schema(VALIDATION_REPORT_SCHEMA)).validate(record)
    assert record["schema"]["version"] == REPORT_SCHEMA_VERSION == "2.1"
    rule_record = next(item for item in record["rules"] if item["rule_id"] == "tst_0001")
    assert rule_record["deny_list"] == {
        "rule_id": "tst_0001",
        "module": SAMPLE_MODULE,
        "deny_type": DENY_DEACTIVATED,
        "date_applied": "2026-10-19",
        "known_issue": 22,
        "description": _deactivated().describe(),
    }
    assert rule_record["formula"] == {
        "severity": SEVERITY_ERROR,
        "status": STATUS_FAIL,
        "satisfied": 0,
        "unsatisfied": 1,
    }
    assert record["summary"]["deny_list"]["deactivated"] == ["tst_0001"]
    assert record["summary"]["deny_list"]["applied_on"] == RUN.isoformat()
    other = next(item for item in record["rules"] if item["rule_id"] == "tst_0002")
    assert (other["deny_list"], other["formula"]) == (None, None)


def test_the_text_report_lists_each_rule_the_bank_switched_off(pack: TaxonomyPack) -> None:
    ret = build_return(_facts())
    validation = validate_return(ret, release=_release(pack, _deactivated()), accuracy=EXACT)

    text = render_text(ret, validation)

    assert text.startswith("SUBMITTABLE")
    assert (
        "tst_0001 deactivated by the Bank of England on 19 October 2026 "
        "(validations deny list; known issues log #22)"
    ) in text
    assert "the published rule breaks 1 of 1 evaluation(s) here" in text


# ---------------------------------------------------------------------------
# The real rule book: boe_b0710 (known issue #22)
# ---------------------------------------------------------------------------


def test_boe_b0710_blocks_a_return_before_the_bank_deactivated_it() -> None:
    """The return does not fill OF 07.00 cols 0160-0190 on its on-balance-sheet rows."""
    validation = validate_return(corporate_return(), taxonomy="4.1.1", today=date(2026, 10, 18))

    assert _result(validation, "boe_b0710").status == STATUS_FAIL
    assert "boe_b0710" in {item.subject for item in validation.blocking}


def test_boe_b0710_is_not_run_once_the_bank_has_deactivated_it() -> None:
    # Act
    validation = validate_return(corporate_return(), taxonomy="4.1.1", today=RUN)

    # Assert
    result = _result(validation, "boe_b0710")
    assert (result.status, result.reason) == (STATUS_NOT_EVALUATED, REASON_DEACTIVATED_BY_PUBLISHER)
    assert "known issues log #22" in result.detail
    assert result.formula is not None and result.formula.status == STATUS_FAIL
    assert "boe_b0710" not in {item.subject for item in validation.findings}


def test_boe_b0710s_fingerprint_does_not_move_with_its_deny_status() -> None:
    rulebook = release_rulebook("4.1.1", "PRA001")
    assert rulebook is not None
    ret = corporate_return()

    record = to_record(ret, validate_return(ret, taxonomy="4.1.1", today=RUN))

    entry = next(item for item in record["rules"] if item["rule_id"] == "boe_b0710")
    assert entry["rule_sha256"] == rulebook.rule("boe_b0710").fingerprint("PRA001")  # type: ignore[union-attr]
    assert entry["status"] == STATUS_NOT_EVALUATED


def test_a_finding_for_a_rule_with_no_entry_is_unchanged(pack: TaxonomyPack) -> None:
    """Only the rule on the list moves: an Error rule off it still blocks as VAL001."""
    blocking = rule("tst_0003", f"{ref(T01, '0010', '0010')} i= 1", tables=(T01,))
    release = release_for_pack(pack, book(FOOTING, blocking), today=RUN)
    release = replace(release, deny_list=DenyList(release="1.0.0", entries=(_deactivated(),)))

    validation = validate_return(build_return(_facts()), release=release, accuracy=EXACT)

    assert [(item.code, item.subject) for item in validation.blocking] == [
        (FINDING_RULE_ERROR, "tst_0003")
    ]
