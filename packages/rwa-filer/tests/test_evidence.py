"""
The evidence export: everything a validation executed, in a file that explains itself.

The property the evidence exists for is that a reader can rely on it WITHOUT
this engine: every recorded comparison's verdict must follow from the numbers
recorded beside it, by the rule the schema states, and every rule's counts from
its evaluation records. ``_independent_check`` is that reader. It imports
nothing from ``rwa_filer`` — it reads the lines with ``json`` and the shipped
schema with ``jsonschema`` — so it cannot share a mistake with the code it
checks (LESSONS B3).

Mutation evidence (C1.11), each probe one change to ``boe/engine.py``, measured
2026-11-15 and verified red for the reason named:

- recording ``tolerance`` as 0, or ``interval`` as ``False``: 6 red — the four
  ``test_every_recorded_verdict_follows_from_its_recorded_numbers`` cases (the
  recorded tolerance no longer follows from the recorded allowances and flag),
  the boundary test and the conditional test;
- recording only the first ``MAX_FAILURES`` failing evaluations of a rule: 3
  red — the independent check on ``POSITIVE`` (its counts no longer match the
  rule record) and ``test_every_failing_evaluation_is_recorded_however_many_there_are``.

The writer's own work (the last section) is pinned separately: the tests above
stay green on a side that drops cell id 0 or sorts its ids, and on every
mistake in which rules' labels an evaluation is given. Each probe is one change
to ``evidence.py``, measured 2026-11-22:

- a side that treats cell id 0 as unreported (``if not number``) or sorts the
  ids: red on
  ``test_a_side_lists_what_it_read_in_reading_order_reported_cells_by_id``
  alone (and the lookup count, for the first); the two lists swapped: red
  there and on seven cases above;
- labels looked up by issue instead of by rule, an unlabelled rule's
  evaluations given ``[]`` where ``null`` belongs, no evaluation asked at all,
  or a rule record without its labels: red on
  ``test_only_an_unsatisfied_evaluation_of_a_labelled_rule_names_its_issues``
  and nothing above;
- the last block never written, a block written but not hashed, hashed but not
  written, or the gathered lines never emptied: red on
  ``test_the_file_does_not_depend_on_how_many_lines_a_block_holds`` (the first
  and the third on most cases above as well).

Its cost is gated by counts, not a clock: the last three tests. Each was seen
red against the code it replaced, with every other test in the file green: two
lookups per cell, a call for every evaluation, a write per line.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import jsonschema
import polars as pl
import pytest

from boe_builders import T01, T04, book, issue_register, ref, rule
from compare_builders import corporate_return
from pack_builders import VALID_LEI, build_pack, build_return
from rwa_filer import evidence as evidence_module
from rwa_filer.boe.engine import MAX_FAILURES, Accuracy, CellAddress
from rwa_filer.cli import EXIT_FAILED, main
from rwa_filer.evidence import collect_evidence, read_evidence, write_evidence
from rwa_filer.model import DECIMALS_EXACT, CanonicalReturn, ReturnHeader
from rwa_filer.release import release_for_pack
from rwa_filer.schemas import EVIDENCE_SCHEMA, VALIDATION_REPORT_SCHEMA, load_schema
from rwa_filer.validate.returns import validate_return

HEADER = ReturnHeader(
    entity_identifier=VALID_LEI, reference_date=date(2027, 3, 31), module="PRA001"
)
HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
#: v0174_m: r0070 i= r0080 i+ r0090 i+ r0091 — out by 2,000, four facts' allowance at -3.
FOOTING = {"0070": 9000.0, "0080": 0.0, "0090": 8000.0, "0091": 3000.0}
#: v3685_s: each listed row <= 0 — seven positive rows, seven failures.
POSITIVE = dict.fromkeys(("0070", "0080", "0090", "0091", "0092", "0170", "0260"), 1000.0)
SCHEMA = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
    "decimals": pl.Int32,
}


def c01(values: dict[str, float], decimals: int | None = None) -> CanonicalReturn:
    frame = pl.DataFrame(
        [
            ("C01.00.01.01", None, None, row, "0010", value, None, decimals)
            for row, value in values.items()
        ],
        schema=SCHEMA,
        orient="row",
    )
    return CanonicalReturn.from_frame(HEADER, frame)


def lines(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def written(tmp_path: Path, ret: CanonicalReturn, **options: Any) -> list[dict[str, Any]]:
    path = tmp_path / "evidence.jsonl"
    write_evidence(collect_evidence(ret, **options), path)
    return lines(path)


def evaluations(records: list[dict[str, Any]], rule_id: str) -> list[dict[str, Any]]:
    return [
        item for item in records if item["record"] == "evaluation" and item["rule_id"] == rule_id
    ]


# ---------------------------------------------------------------------------
# One pass: the evidence is the verdict's own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("values", [FOOTING, POSITIVE])
def test_the_evidence_reaches_the_verdict_validate_return_reaches(values: dict[str, float]) -> None:
    # Arrange
    ret = c01(values)

    # Act
    evidence = collect_evidence(ret)
    plain = validate_return(ret)

    # Assert
    assert evidence.validation.report == plain.report
    assert evidence.validation.findings == plain.findings
    assert evidence.trace is not None
    assert evidence.trace.results == plain.report.results  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The evidence explains itself — checked by a reader that is not the engine
# ---------------------------------------------------------------------------


def _independent_check(records: list[dict[str, Any]]) -> None:
    """Every claim the file makes, re-derived from what the file holds."""
    validator = jsonschema.Draft202012Validator(load_schema(EVIDENCE_SCHEMA))
    for record in records:
        validator.validate(record)
    cells = {item["id"]: item for item in records if item["record"] == "cell"}
    rules = {item["rule_id"]: item for item in records if item["record"] == "rule"}
    tally: dict[str, list[int]] = {rule_id: [0, 0] for rule_id in rules}
    for item in records:
        if item["record"] != "evaluation":
            continue
        tally[item["rule_id"]][0 if item["holds"] else 1] += 1
        for comparison in item["comparisons"]:
            _check_comparison(comparison, cells)
    for rule_id, (satisfied, unsatisfied) in tally.items():
        assert (rules[rule_id]["satisfied"], rules[rule_id]["unsatisfied"]) == (
            satisfied,
            unsatisfied,
        ), rule_id


def _check_comparison(comparison: dict[str, Any], cells: dict[int, dict[str, Any]]) -> None:
    left, right = comparison["left"], comparison["right"]
    for operand in (left, right):
        assert all(cell in cells for cell in operand["cells"])
    if not all(isinstance(side["value"], (int, float)) for side in (left, right)):
        return
    difference = left["value"] - right["value"]
    tolerance = left["allowance"] + right["allowance"] if comparison["interval"] else 0.0
    assert comparison["difference"] == pytest.approx(difference)
    assert comparison["tolerance"] == pytest.approx(tolerance)
    expected = {
        "=": abs(difference) <= tolerance,
        "!=": abs(difference) > tolerance,
        "<=": difference <= tolerance,
        "<": difference < tolerance,
        ">=": difference >= -tolerance,
        ">": difference > -tolerance,
    }[comparison["operator"]]
    assert comparison["holds"] is expected, comparison


@pytest.mark.parametrize("values", [FOOTING, POSITIVE])
@pytest.mark.parametrize("decimals", [-3, 0])
def test_every_recorded_verdict_follows_from_its_recorded_numbers(
    values: dict[str, float], decimals: int, tmp_path: Path
) -> None:
    # Act
    records = written(tmp_path, c01(values), accuracy=Accuracy(decimals, 4))

    # Assert
    assert evaluations(records, "v0174_m") or evaluations(records, "v3685_s")
    _independent_check(records)


def test_a_comparison_on_the_rounding_boundary_shows_why_it_held(tmp_path: Path) -> None:
    # Act
    thousands = evaluations(written(tmp_path, c01(FOOTING)), "v0174_m")
    units = evaluations(written(tmp_path, c01(FOOTING), accuracy=Accuracy(0, 4)), "v0174_m")

    # Assert — the same -2,000, inside four facts' 500 and outside four facts' 0.5.
    ((held,),) = [item["comparisons"] for item in thousands]
    ((broke,),) = [item["comparisons"] for item in units]
    assert (held["operator"], held["interval"], held["branch"]) == ("=", True, "rule")
    assert (held["difference"], held["tolerance"], held["excess"]) == (-2000.0, 2000.0, 0.0)
    assert (held["left"]["allowance"], held["right"]["allowance"]) == (500.0, 1500.0)
    assert held["holds"] is True
    assert (broke["tolerance"], broke["excess"], broke["holds"]) == (2.0, 1998.0, False)


def test_each_cell_says_what_accuracy_it_was_compared_at(tmp_path: Path) -> None:
    # Act — the same figures, once taking the run's accuracy, once stating their own.
    defaulted = written(tmp_path, c01(FOOTING))
    stated = written(tmp_path, c01(FOOTING, decimals=2))

    # Assert
    cell = next(item for item in defaulted if item["record"] == "cell" and item["row"] == "0070")
    assert (cell["decimals"], cell["decimals_source"], cell["allowance"]) == (-3, "accuracy", 500.0)
    cell = next(item for item in stated if item["record"] == "cell" and item["row"] == "0070")
    assert (cell["decimals"], cell["decimals_source"], cell["allowance"]) == (2, "stated", 0.005)


def test_every_failing_evaluation_is_recorded_however_many_there_are(tmp_path: Path) -> None:
    # Arrange — adequacy: more failures than the summary keeps.
    ret = c01(POSITIVE)
    (result,) = [r for r in validate_return(ret).report.results if r.rule_id == "v3685_s"]  # type: ignore[union-attr]
    assert result.unsatisfied > MAX_FAILURES == len(result.failures)

    # Act
    failing = [item for item in evaluations(written(tmp_path, ret), "v3685_s") if not item["holds"]]

    # Assert
    assert len(failing) == result.unsatisfied
    assert {item["place"]["r@v1"] for item in failing} == set(POSITIVE)


def test_every_enforced_rule_has_a_record_passes_included(tmp_path: Path) -> None:
    # Act
    records = written(tmp_path, c01(FOOTING))

    # Assert
    rules = [item for item in records if item["record"] == "rule"]
    statuses = {item["status"] for item in rules}
    assert len(rules) == records[0]["identity"]["rulebook"]["rules_enforced"]
    assert {"PASS", "NOT_EVALUATED"} <= statuses
    assert all(item["rule_sha256"] and item["expression"] for item in rules)


# ---------------------------------------------------------------------------
# Defaults and branches, on a rule book of the test's own
# ---------------------------------------------------------------------------

SYNTHETIC = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}


def test_a_cell_read_at_its_default_is_recorded_as_defaulted(tmp_path: Path) -> None:
    # Arrange — part two (r0030) is left out, so it is read at its default, zero.
    pack = build_pack(tmp_path / "pack")
    ret = build_return(
        pl.DataFrame(
            [
                (T01, None, None, "0010", "0010", 60.0, None),
                (T01, None, None, "0020", "0010", 60.0, None),
            ],
            schema=SYNTHETIC,
            orient="row",
        )
    )
    footing = rule(
        "tst_0001",
        f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )

    # Act
    records = written(tmp_path, ret, pack=pack, rulebook=book(footing))

    # Assert
    ((comparison,),) = [item["comparisons"] for item in evaluations(records, "tst_0001")]
    (defaulted,) = comparison["right"]["defaulted"]
    assert defaulted["default"] == "zero"
    assert (defaulted["address"]["row"], defaulted["address"]["column"]) == ("0030", "0010")
    assert len(comparison["right"]["cells"]) == 1


def test_a_conditional_records_the_branch_it_took(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path / "pack")
    ret = build_return(
        pl.DataFrame(
            [
                (T01, None, None, "0010", "0010", 100.0, None),
                (T01, None, None, "0020", "0010", 100.0, None),
            ],
            schema=SYNTHETIC,
            orient="row",
        )
    )
    conditional = rule(
        "tst_0003",
        f"if ({ref(T01, '0010', '0010')} > 0) then "
        f"({ref(T01, '0020', '0010')} i= {ref(T01, '0010', '0010')}) else true()",
        tables=(T01,),
    )

    # Act
    records = written(tmp_path, ret, pack=pack, rulebook=book(conditional))

    # Assert
    ((condition, consequence),) = [item["comparisons"] for item in evaluations(records, "tst_0003")]
    assert (condition["branch"], condition["operator"]) == ("rule/if", ">")
    assert (consequence["branch"], consequence["holds"]) == ("rule/then", True)
    _independent_check(records)


# ---------------------------------------------------------------------------
# The file: identity, determinism, integrity
# ---------------------------------------------------------------------------


def test_the_header_and_the_report_share_one_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    source = tmp_path / "facts.csv"
    source.write_text(
        "table,sheet,row,column,value\n"
        + "".join(f"C01.00.01.01,,{row},0010,{value}\n" for row, value in FOOTING.items())
    )
    path = tmp_path / "out" / "evidence.jsonl.gz"

    # Act
    main(["validate", str(source), *HEADER_ARGS, "--format", "json", "--evidence", str(path)])
    captured = capsys.readouterr()
    record = json.loads(captured.out)

    # Assert
    header = lines(path)[0]
    assert header["identity"] == record["identity"]
    assert header["status"] == record["status"]
    assert "Wrote " in captured.err and "evaluation(s)" in captured.err
    jsonschema.Draft202012Validator(load_schema(VALIDATION_REPORT_SCHEMA)).validate(record)


@pytest.mark.parametrize("name", ["evidence.jsonl", "evidence.jsonl.gz"])
def test_the_same_inputs_give_the_same_bytes_whatever_the_hash_seed(
    name: str, tmp_path: Path
) -> None:
    # Arrange — two processes: string hashing differs, the file must not.
    source = tmp_path / "facts.csv"
    source.write_text(
        "table,sheet,row,column,value\n"
        + "".join(f"C01.00.01.01,,{row},0010,{value}\n" for row, value in POSITIVE.items())
    )
    script = "import sys; from rwa_filer.cli import main; sys.exit(main(sys.argv[1:]))"

    def run(seed: str, out: Path) -> bytes:
        subprocess.run(
            [sys.executable, "-c", script, "validate", str(source), *HEADER_ARGS]
            + ["--evidence", str(out), "--no-timestamp"],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            check=False,
        )
        return out.read_bytes()

    # Act
    first = run("1", tmp_path / "a" / name)
    second = run("2", tmp_path / "b" / name)

    # Assert
    assert first == second


def test_reading_back_refuses_a_file_that_was_cut_short_or_altered(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "evidence.jsonl"
    file = write_evidence(collect_evidence(c01(FOOTING)), path)
    text = path.read_text(encoding="utf-8").splitlines(keepends=True)
    cut, altered = tmp_path / "cut.jsonl", tmp_path / "altered.jsonl"
    cut.write_text("".join(text[:-1]), encoding="utf-8")
    altered.write_text("".join(text).replace('"holds":true', '"holds":false', 1), encoding="utf-8")

    # Act
    document = read_evidence(path)

    # Assert
    assert document.trailer["content_sha256"] == file.content_sha256
    assert len(document.rules) == file.records["rule"]
    with pytest.raises(ValueError, match="not a complete evidence file"):
        read_evidence(cut)
    with pytest.raises(ValueError, match="digest"):
        read_evidence(altered)


def test_a_module_with_no_rule_book_still_writes_its_verdict(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path / "pack")
    ret = build_return(
        pl.DataFrame([(T01, None, None, "0010", "0010", 1.0, None)], schema=SYNTHETIC, orient="row")
    )

    # Act
    document = read_evidence(
        write_evidence(collect_evidence(ret, pack), tmp_path / "evidence.jsonl").path
    )

    # Assert
    assert document.header["status"] == "BLOCKED" and document.rules == ()
    assert [item["subject"] for item in document.findings] == ["no_rulebook"]


def test_validate_with_evidence_exits_as_it_would_without(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    source = tmp_path / "facts.csv"
    source.write_text(
        "table,sheet,row,column,value\n"
        + "".join(f"C01.00.01.01,,{row},0010,{value}\n" for row, value in POSITIVE.items())
    )

    # Act
    without = main(["validate", str(source), *HEADER_ARGS])
    with_evidence = main(
        ["validate", str(source), *HEADER_ARGS, "--evidence", str(tmp_path / "e.jsonl")]
    )

    # Assert
    capsys.readouterr()
    assert without == with_evidence == EXIT_FAILED


# ---------------------------------------------------------------------------
# The Bank's validations deny list
# ---------------------------------------------------------------------------


def test_a_rule_the_bank_deactivated_has_its_entry_and_no_evaluation_records(
    tmp_path: Path,
) -> None:
    """boe_b0710 (known issue #22): the gateway does not run it, so nothing it found is evidence.

    Its rule record keeps the published rule's own counts under ``formula``.
    """
    # Act: the corporates return breaks boe_b0710 as published.
    records = written(tmp_path, corporate_return(), taxonomy="4.1.1", today=date(2026, 11, 16))

    # Assert
    _independent_check(records)
    rule_record = next(
        item for item in records if item["record"] == "rule" and item["rule_id"] == "boe_b0710"
    )
    assert (rule_record["status"], rule_record["reason"]) == (
        "NOT_EVALUATED",
        "deactivated_by_publisher",
    )
    assert rule_record["deny_list"]["known_issue"] == 22
    assert rule_record["formula"]["status"] == "FAIL"
    assert rule_record["formula"]["unsatisfied"] >= 1
    assert evaluations(records, "boe_b0710") == []
    assert records[0]["schema"]["version"] == "1.1"


def test_before_the_bank_deactivated_it_the_rule_is_evidence_like_any_other(
    tmp_path: Path,
) -> None:
    """The leg that stays red: the same return, a day before the entry applied."""
    records = written(tmp_path, corporate_return(), taxonomy="4.1.1", today=date(2026, 10, 18))

    _independent_check(records)
    rule_record = next(
        item for item in records if item["record"] == "rule" and item["rule_id"] == "boe_b0710"
    )
    assert (rule_record["status"], rule_record["deny_list"], rule_record["formula"]) == (
        "FAIL",
        None,
        None,
    )
    assert any(not item["holds"] for item in evaluations(records, "boe_b0710"))


# ---------------------------------------------------------------------------
# The writer's own work: one pass per side, labels found by rule, block writes
# ---------------------------------------------------------------------------


def test_a_side_lists_what_it_read_in_reading_order_reported_cells_by_id(tmp_path: Path) -> None:
    # Arrange — the left side reads r0030, r0020 c0020, r0010, r0020 c0010 in that
    # order; the two r0020 cells are not reported. Adequacy: the cell with id 0
    # (r0010 c0010, first in coordinate order) is read AFTER the cell with id 2,
    # so neither a sorted list nor an id taken for "missing" can pass.
    pack = build_pack(tmp_path / "pack")
    ret = build_return(
        pl.DataFrame(
            [
                (T01, None, None, "0030", "0010", 5.0, None),
                (T01, None, None, "0010", "0010", 60.0, None),
                (T01, None, None, "0010", "0020", 0.5, None),
            ],
            schema=SYNTHETIC,
            orient="row",
        )
    )
    mixed = rule(
        "tst_0001",
        f"{ref(T01, '0030', '0010')} i+ {ref(T01, '0020', '0020')} i+ "
        f"{ref(T01, '0010', '0010')} i+ {ref(T01, '0020', '0010')} "
        f"i= {ref(T01, '0010', '0020')}",
        tables=(T01,),
    )

    # Act
    records = written(tmp_path, ret, pack=pack, rulebook=book(mixed))

    # Assert
    ids = {
        (item["row"], item["column"]): item["id"] for item in records if item["record"] == "cell"
    }
    assert ids == {("0010", "0010"): 0, ("0010", "0020"): 1, ("0030", "0010"): 2}
    (evaluation,) = evaluations(records, "tst_0001")
    assert evaluation["left"]["cells"] == [2, 0]
    assert [(item["row"], item["column"]) for item in evaluation["left"]["unreported"]] == [
        ("0020", "0020"),
        ("0020", "0010"),
    ]
    assert evaluation["right"] == {"cells": [1], "unreported": []}


def test_only_an_unsatisfied_evaluation_of_a_labelled_rule_names_its_issues(
    tmp_path: Path,
) -> None:
    # Arrange — two broken rules, one of them labelled by a known issue whose
    # footprint is open row g1. The labelled rule is evaluated once per open
    # row: g1 breaks inside the footprint, g2 breaks outside it, g3 holds.
    pack = build_pack(tmp_path / "pack")
    per_row = rule("tst_0004", f"{ref(T04, c='0010')} >= 1000", tables=(T04,))
    footing = rule(
        "tst_0001",
        f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )
    amounts = {"g1": 500.0, "g2": 500.0, "g3": 2000.0}
    facts = [(T04, None, None, row, "0005", None, row) for row in amounts]
    facts += [(T04, None, None, row, "0010", amount, None) for row, amount in amounts.items()]
    facts += [
        (T01, None, None, "0010", "0010", 100.0, None),
        (T01, None, None, "0020", "0010", 60.0, None),
        (T01, None, None, "0030", "0010", 30.0, None),
    ]
    ret = build_return(pl.DataFrame(facts, schema=SYNTHETIC, orient="row"))
    register = issue_register(per_row, footprint=[{"table": T04, "rows": ["g1"]}])
    release = replace(
        release_for_pack(pack, book(per_row, footing), today=date(2026, 11, 16)), issues=register
    )

    # Act
    records = written(
        tmp_path, ret, release=release, accuracy=Accuracy(DECIMALS_EXACT, DECIMALS_EXACT)
    )

    # Assert — ``None`` is "nothing to say", ``[]`` is "labelled, and not explained".
    labelled = {
        item["place"]["key:tst_dim:OGR"]: (item["holds"], item["publisher_issues"])
        for item in evaluations(records, "tst_0004")
    }
    assert labelled == {"g1": (False, ["PI-01"]), "g2": (False, []), "g3": (True, None)}
    (unlabelled,) = evaluations(records, "tst_0001")
    assert (unlabelled["holds"], unlabelled["publisher_issues"]) == (False, None)
    notes = {
        item["rule_id"]: [note["issue"] for note in item["publisher_issues"]]
        for item in records
        if item["record"] == "rule"
    }
    assert notes == {"tst_0004": ["PI-01"], "tst_0001": []}


def _per_line_gzip(plain: bytes) -> bytes:
    """``plain`` compressed as a writer that hands the stream one line at a time would."""
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
        for line in plain.splitlines(keepends=True):
            stream.write(line)
    return raw.getvalue()


def test_the_file_does_not_depend_on_how_many_lines_a_block_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical content, and identical ``.gz`` bytes on this zlib.

    A block of one line is the writer that hashed and wrote line by line, so it
    is the reference. The other sizes are: several blocks and a short last one,
    one block that the lines fill exactly (nothing is left for a last block),
    the shipped size, and one short block for the whole file.
    """
    # Arrange
    evidence = collect_evidence(c01(POSITIVE))
    shipped = evidence_module._BLOCK_LINES

    def write(lines_per_block: int, name: str) -> tuple[bytes, tuple[Any, ...]]:
        monkeypatch.setattr(evidence_module, "_BLOCK_LINES", lines_per_block)
        path = tmp_path / str(lines_per_block) / name
        file = write_evidence(evidence, path)
        outcome = (file.sha256, file.content_sha256, file.evidence_id, dict(file.records))
        return path.read_bytes(), outcome

    plain, plain_file = write(1, "e.jsonl")
    packed, packed_file = write(1, "e.jsonl.gz")
    in_blocks = plain.count(b"\n") - 1  # every line but the trailer goes through a block
    assert in_blocks > 1000, "too few lines to fill a block more than a few times"
    short_last = next(size for size in (7, 11, 13) if in_blocks % size)
    sizes = (short_last, in_blocks, shipped, 10**6)

    # Act
    plains = {size: write(size, "e.jsonl") for size in sizes}
    packeds = {size: write(size, "e.jsonl.gz") for size in sizes}

    # Assert
    assert {size: outcome == (plain, plain_file) for size, outcome in plains.items()} == (
        dict.fromkeys(sizes, True)
    )
    assert {size: outcome == (packed, packed_file) for size, outcome in packeds.items()} == (
        dict.fromkeys(sizes, True)
    )
    assert gzip.decompress(packed) == plain
    assert packed == _per_line_gzip(plain), "the compressed bytes moved (the content did not)"
    content_sha256, evidence_id = plain_file[1:3]
    assert packed_file[1:3] == (content_sha256, evidence_id)
    assert packed_file[0] != plain_file[0], "sha256 is of the file as written, compressed or not"
    document = read_evidence(tmp_path / str(short_last) / "e.jsonl.gz")
    assert document.trailer["content_sha256"] == content_sha256
    assert document.header["identity"]["evidence_id"] == evidence_id


class _CountingCells(dict[CellAddress, int]):
    """Cell ids that count how often they are asked about an address."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.lookups = 0

    def get(self, key: CellAddress, default: Any = None) -> Any:
        self.lookups += 1
        return super().get(key, default)

    def __getitem__(self, key: CellAddress) -> int:
        self.lookups += 1
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self.lookups += 1
        return super().__contains__(key)


def test_a_side_looks_each_cell_up_once() -> None:
    # Arrange — an address is hashed in Python, so a lookup is the cost counted.
    addresses = [CellAddress(T01, None, None, f"{row:04d}", "0010") for row in range(10, 90, 10)]
    cells = _CountingCells({address: number for number, address in enumerate(addresses[::2])})

    # Act
    side = evidence_module._side(addresses, cells)

    # Assert
    assert (len(side["cells"]), len(side["unreported"])) == (4, 4), "both kinds must be read"
    assert cells.lookups == len(addresses)


def test_only_a_labelled_rule_has_its_evaluations_asked_about_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a labelled rule and an unlabelled one, eight evaluations each.
    # The file is the same whichever are asked; the calls are not.
    pack = build_pack(tmp_path / "pack")
    labelled = rule("tst_0004", f"{ref(T04, c='0010')} >= 1000", tables=(T04,))
    unlabelled = rule("tst_0005", f"{ref(T04, c='0010')} >= 0", tables=(T04,))
    rows = [f"g{number}" for number in range(1, 9)]
    facts = [(T04, None, None, row, "0005", None, row) for row in rows]
    facts += [(T04, None, None, row, "0010", 500.0, None) for row in rows[:3]]
    facts += [(T04, None, None, row, "0010", 2000.0, None) for row in rows[3:]]
    ret = build_return(pl.DataFrame(facts, schema=SYNTHETIC, orient="row"))
    register = issue_register(labelled, footprint=[{"table": T04, "rows": rows[:3]}])
    release = replace(
        release_for_pack(pack, book(labelled, unlabelled), today=date(2026, 11, 16)),
        issues=register,
    )
    asked: list[str] = []
    real = evidence_module.evaluation_issues

    def counting(evaluation: Any, *args: Any) -> Any:
        asked.append(evaluation.rule_id)
        return real(evaluation, *args)

    monkeypatch.setattr(evidence_module, "evaluation_issues", counting)

    # Act
    records = written(tmp_path, ret, release=release)

    # Assert
    assert len(evaluations(records, "tst_0005")) == 8, "the unlabelled rule must be evaluated"
    assert asked == ["tst_0004"] * 8


def test_the_compressed_file_is_written_a_block_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — count the writes that reach the gzip stream.
    evidence = collect_evidence(c01(POSITIVE))
    writes: list[int] = []
    compressed = evidence_module._compressed

    class Counting:
        def __init__(self, raw: Any) -> None:
            self._stream = compressed(raw)

        def write(self, data: bytes) -> int:
            writes.append(data.count(b"\n"))
            return self._stream.write(data)

        def close(self) -> None:
            self._stream.close()

    monkeypatch.setattr(evidence_module, "_compressed", Counting)
    monkeypatch.setattr(evidence_module, "_BLOCK_LINES", 100)

    # Act
    file = write_evidence(evidence, tmp_path / "e.jsonl.gz")

    # Assert — every block is full but the last, and the trailer is its own write.
    in_blocks = sum(file.records.values()) + 1  # the body and the header
    assert in_blocks > 1000, "too few lines for the count to tell a block from a line"
    assert in_blocks % 100, "the lines fill the last block exactly: use another block size"
    assert sum(writes) == in_blocks + 1
    assert writes[:-2] == [100] * (in_blocks // 100)
    assert writes[-2:] == [in_blocks % 100, 1]
    read_evidence(file.path)
