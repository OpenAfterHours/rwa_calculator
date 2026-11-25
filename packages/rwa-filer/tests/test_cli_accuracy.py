"""
``validate`` takes the accuracy options ``build`` takes, and reaches the same verdict.

The rules' ``i``-prefixed comparisons allow for each fact's rounding, and a fact
table states no accuracy of its own: the allowance comes from the accuracy the
file will be written with. ``build --monetary-decimals N`` validates at N, so a
``validate`` that could only ever run at the default could pass a return the
build then refuses.

The return here is measured, not hypothetical (docs/plans/rwa-filer-evidence-export.md,
F1): rule ``v0174_m`` (Error) checks ``C 01.00 r0070 i= r0080 i+ r0090 i+ r0091``,
and 9,000 against 0 + 8,000 + 3,000 is out by 2,000 — exactly four facts'
allowance at thousands (4 x 500), and far outside it at units (4 x 0.5).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer.cli import main
from rwa_filer.filing import build_filing
from rwa_filer.readers import HeaderFields, open_source
from rwa_filer.xbrl.writer import InstanceOptions

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
RULE = "v0174_m"
FOOTING_CSV = (
    "table,sheet,row,column,value\n"
    "C01.00.01.01,,0070,0010,9000\n"
    "C01.00.01.01,,0080,0010,0\n"
    "C01.00.01.01,,0090,0010,8000\n"
    "C01.00.01.01,,0091,0010,3000\n"
)


@pytest.fixture
def footing(tmp_path: Path) -> Path:
    path = tmp_path / "footing.csv"
    path.write_text(FOOTING_CSV)
    return path


def _validated_status(path: Path, capsys: pytest.CaptureFixture[str], *options: str) -> str:
    main(["validate", str(path), *HEADER_ARGS, "--format", "json", *options])
    record = json.loads(capsys.readouterr().out)
    return next(entry["status"] for entry in record["rules"] if entry["rule_id"] == RULE)


def _built_status(path: Path, out: Path, monetary_decimals: int) -> str:
    source = open_source(
        path, HeaderFields(entity=VALID_LEI, reference_date=date(2027, 3, 31), module="PRA001")
    )
    package = build_filing(
        source.ret, out, options=InstanceOptions(monetary_decimals=monetary_decimals)
    )
    assert package.validation.report is not None
    return next(
        result.status for result in package.validation.report.results if result.rule_id == RULE
    )


def test_the_measured_return_sits_on_the_rounding_boundary(
    footing: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adequacy: the fixture really does turn on the accuracy, in both directions."""
    # Act
    at_thousands = _validated_status(footing, capsys)
    at_units = _validated_status(footing, capsys, "--monetary-decimals", "0")

    # Assert
    assert (at_thousands, at_units) == ("PASS", "FAIL")


@pytest.mark.parametrize("decimals", [-3, 0, 2])
def test_validate_and_build_agree_at_every_accuracy(
    decimals: int, footing: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    validated = _validated_status(footing, capsys, "--monetary-decimals", str(decimals))
    built = _built_status(footing, tmp_path / f"out{decimals}", decimals)

    # Assert
    assert validated == built


def test_the_report_records_the_accuracy_it_was_validated_at(
    footing: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(
        [
            "validate",
            str(footing),
            *HEADER_ARGS,
            "--format",
            "json",
            "--monetary-decimals",
            "0",
            "--percentage-decimals",
            "6",
        ]
    )

    # Assert
    accuracy = json.loads(capsys.readouterr().out)["identity"]["settings"]["accuracy"]
    assert accuracy == {"monetary_decimals": 0, "percentage_decimals": 6, "source": "given"}


@pytest.mark.parametrize(
    "options", [[], ["--monetary-decimals", "-3", "--percentage-decimals", "4"]]
)
def test_the_default_accuracy_is_recorded_as_the_default(
    options: list[str], footing: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Asking for the defaults by name is still the default, and gives the same evidence id."""
    # Act
    main(["validate", str(footing), *HEADER_ARGS, "--format", "json", *options])
    identity = json.loads(capsys.readouterr().out)["identity"]
    main(["validate", str(footing), *HEADER_ARGS, "--format", "json", "--monetary-decimals", "0"])
    other = json.loads(capsys.readouterr().out)["identity"]

    # Assert
    assert identity["settings"]["accuracy"] == {
        "monetary_decimals": -3,
        "percentage_decimals": 4,
        "source": "default",
    }
    assert identity["evidence_id"] != other["evidence_id"]


def test_zero_filter_keeps_blocking_exit_and_full_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "mixed.csv"
    source.write_text(
        "table,sheet,row,column,value\n"
        + "".join(
            f"OF08.01.01.01,0006,{row},0101,{value}\n"
            for row, value in zip(
                ["0010", "0017", "0020", "0030", "0031", "0032", "0033"],
                [0, 0, 0, 0, 0, 0, 1],
                strict=True,
            )
        )
    )
    report, evidence = tmp_path / "report.json", tmp_path / "evidence.jsonl"
    status = main(
        [
            "validate",
            str(source),
            *HEADER_ARGS,
            "--hide-zero-null-errors",
            "--report",
            str(report),
            "--evidence",
            str(evidence),
        ]
    )
    output = capsys.readouterr().out
    record = json.loads(report.read_text())
    result = next(r for r in record["rules"] if r["rule_id"] == "boe_b1039")
    assert status == 1 and record["status"] == "BLOCKED"
    assert result["unsatisfied"] == len(result["failures"]) == 7
    assert "boe_b1039 has 7 failing evaluations, 6 hidden" in output
    assert "row of v0 0033" in output
    assert (
        sum(
            r.get("rule_id") == "boe_b1039" and r.get("holds") is False
            for r in map(json.loads, evidence.read_text(encoding="utf-8").splitlines())
        )
        == 7
    )


def test_cli_warning_threshold_keeps_the_boundary_and_full_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "warning.csv"
    source.write_text("table,sheet,row,column,value\nOF08.03.01.01,0012,0070,0010,-5\n")
    args = ["validate", str(source), *HEADER_ARGS, "--warning-materiality"]
    status = main([*args, "5"])
    assert "[VAL002] WARNING: Validation rule boe_b0317" in capsys.readouterr().out
    assert main([*args, "5.01"]) == status
    assert "[VAL002] WARNING: Validation rule boe_b0317" not in capsys.readouterr().out
    assert main([*args, "5.01", "--format", "json"]) == status
    report = json.loads(capsys.readouterr().out)
    assert any(r["rule_id"] == "boe_b0317" and r["status"] == "FAIL" for r in report["rules"])
