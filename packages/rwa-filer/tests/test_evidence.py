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
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import jsonschema
import polars as pl
import pytest

from boe_builders import T01, book, ref, rule
from pack_builders import VALID_LEI, build_pack, build_return
from rwa_filer.boe.engine import MAX_FAILURES, Accuracy
from rwa_filer.cli import EXIT_FAILED, main
from rwa_filer.evidence import collect_evidence, read_evidence, write_evidence
from rwa_filer.model import CanonicalReturn, ReturnHeader
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
