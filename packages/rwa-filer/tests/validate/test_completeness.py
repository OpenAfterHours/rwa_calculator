"""
Completeness: an incomplete check is told apart from a clean one, cause by cause.

``status`` is ``BLOCKED`` when a finding stops the return, else ``INCOMPLETE``
when something the module requires checking was not checked, else ``CLEAN``.
Each cause names every rule and template it covers. What is pinned here is
that each cause fires on the case it exists for, and NOT on a complete check —
an alarm that fires on every return says nothing (LESSONS B9).
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01, T03, book, ref, rule
from pack_builders import VALID_LEI, build_pack, build_return
from rwa_filer.boe.catalogue import Rule
from rwa_filer.cli import EXIT_INCOMPLETE, EXIT_OK, main
from rwa_filer.model import CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.checker import FINDING_LINKED_TEMPLATE_MISSING, FINDING_RULES_NOT_EVALUABLE
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import (
    INCOMPLETE_COVERAGE_SHORTFALL,
    INCOMPLETE_LINKED_TEMPLATES_MISSING,
    INCOMPLETE_NO_RULEBOOK,
    INCOMPLETE_RULES_TABLE_NOT_IN_TAXONOMY,
    INCOMPLETE_RULES_UNSUPPORTED,
    VERDICT_BLOCKED,
    VERDICT_CLEAN,
    VERDICT_INCOMPLETE,
    validate_return,
)

SCHEMA = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}
#: T01 foots: 100 = 60 + 40.
T01_ROWS = [
    (T01, None, None, "0010", "0010", 100.0, None),
    (T01, None, None, "0020", "0010", 60.0, None),
    (T01, None, None, "0030", "0010", 40.0, None),
]
FOOTING = rule(
    "tst_0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
#: Read T01 with T03: with T03 left out, it does not run.
LINKED = rule(
    "tst_0006", f"{ref(T01, '0010', '0010')} i= {ref(T03, '0010', '0010')}", tables=(T01, T03)
)
#: Calls a function this engine does not implement.
UNSUPPORTED = rule("tst_0101", f"frobnicate({ref(T01, '0010', '0010')})", tables=(T01,))
#: Reads a table the pack does not have.
ELSEWHERE = rule(
    "tst_0102",
    "{t: T99.00.01.01, r: 0010, c: 0010, dv: 0, seq: False, f: test, fv: test} >= 0",
    tables=("T99.00.01.01",),
)
CLEAN_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,0\n"  # one zero: every rule reading it runs and holds
)


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


@pytest.fixture
def t01() -> CanonicalReturn:
    return build_return(pl.DataFrame(T01_ROWS, schema=SCHEMA, orient="row"))


def test_a_complete_check_that_holds_is_clean(pack: TaxonomyPack, t01: CanonicalReturn) -> None:
    # Act
    validation = validate_return(t01, pack, rulebook=book(FOOTING))

    # Assert — the control for every cause below: none of them fires here.
    assert validation.completeness == ()
    assert validation.status == VERDICT_CLEAN
    assert to_record(t01, validation)["completeness"] == []


def test_a_linked_template_left_out_is_incomplete_but_not_blocking(
    pack: TaxonomyPack, t01: CanonicalReturn
) -> None:
    # Act
    validation = validate_return(t01, pack, rulebook=book(FOOTING, LINKED))

    # Assert
    (cause,) = validation.completeness
    assert cause.code == INCOMPLETE_LINKED_TEMPLATES_MISSING
    assert (cause.rules, cause.templates) == (("tst_0006",), ("T03.00.01",))
    assert validation.status == VERDICT_INCOMPLETE and validation.is_submittable
    assert FINDING_LINKED_TEMPLATE_MISSING in {finding.code for finding in validation.findings}


@pytest.mark.parametrize(
    ("unrun", "code"),
    [
        (UNSUPPORTED, INCOMPLETE_RULES_UNSUPPORTED),
        (ELSEWHERE, INCOMPLETE_RULES_TABLE_NOT_IN_TAXONOMY),
    ],
)
def test_a_rule_the_engine_cannot_evaluate_is_named_by_val005(
    unrun: Rule, code: str, pack: TaxonomyPack, t01: CanonicalReturn
) -> None:
    # Act
    validation = validate_return(t01, pack, rulebook=book(FOOTING, unrun))

    # Assert — incomplete, and said so in a finding, not a count alone.
    (cause,) = validation.completeness
    assert (cause.code, cause.rules) == (code, (unrun.rule_id,))
    (finding,) = [item for item in validation.findings if item.code == FINDING_RULES_NOT_EVALUABLE]
    assert finding.subject == code and not finding.is_blocking
    assert unrun.rule_id in finding.message
    assert validation.status == VERDICT_INCOMPLETE


def test_no_rule_book_is_blocked_and_says_why(pack: TaxonomyPack, t01: CanonicalReturn) -> None:
    # Act
    validation = validate_return(t01, pack)

    # Assert
    (cause,) = validation.completeness
    assert cause.code == INCOMPLETE_NO_RULEBOOK
    assert validation.status == VERDICT_BLOCKED
    assert "no rule book for the module" in render_text(t01, validation)


def test_a_coverage_shortfall_is_a_cause_as_well_as_a_block(pack: TaxonomyPack) -> None:
    # Arrange — T01 reported with nothing its rule can read: no rule executes.
    ret = build_return(
        pl.DataFrame(
            [(T01, None, None, "0010", "0030", None, "a note")], schema=SCHEMA, orient="row"
        )
    )

    # Act
    validation = validate_return(ret, pack, rulebook=book(FOOTING))

    # Assert
    assert INCOMPLETE_COVERAGE_SHORTFALL in {cause.code for cause in validation.completeness}
    assert validation.status == VERDICT_BLOCKED


def test_the_text_report_states_the_status_with_its_causes(
    pack: TaxonomyPack, t01: CanonicalReturn
) -> None:
    # Act
    clean = render_text(t01, validate_return(t01, pack, rulebook=book(FOOTING)))
    linked = render_text(t01, validate_return(t01, pack, rulebook=book(FOOTING, LINKED)))

    # Assert
    assert "  status: CLEAN\n" in clean
    assert "status: INCOMPLETE — linked templates not reported (1 template(s), 1 rule(s))" in linked


def test_require_complete_exits_3_on_an_incomplete_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange — OF 07.00 alone leaves out templates its rules read (VAL004).
    path = tmp_path / "facts.csv"
    path.write_text(CLEAN_CSV)
    header = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]

    # Act
    plain = main(["validate", str(path), *header])
    capsys.readouterr()
    strict = main(["validate", str(path), *header, "--require-complete", "--format", "json"])
    record = json.loads(capsys.readouterr().out)

    # Assert — the default exit is unchanged; the flag tells the two apart.
    assert plain == EXIT_OK and strict == EXIT_INCOMPLETE
    assert record["status"] == VERDICT_INCOMPLETE and record["submittable"] is True
