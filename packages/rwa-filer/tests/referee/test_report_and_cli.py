"""
``referee.report`` and the ``rwa-filer referee`` command.

No Arelle here. The report is pinned on hand-built results; the command is
pinned with ``run_referee`` replaced by a stand-in, so what is tested is the
command's own work: what it hands the referee, that it runs the native engine
on the same instance and compares, what it prints, and its exit code.

References:
- packages/rwa-filer/src/rwa_filer/referee/report.py
- packages/rwa-filer/src/rwa_filer/cli.py (``_referee``)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from rwa_filer import cli
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_PASS, RuleResult
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.referee import RefereeMessage, RefereeResult, RefereeUnavailableError, RuleVerdict
from rwa_filer.referee.differential import compare
from rwa_filer.referee.report import is_supported, render_text, to_record
from rwa_filer.referee.runner import CHUNK_OK, MODE_TRIM, ChunkStat
from rwa_filer.validate.returns import validate_return
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance

SCHEMA_REF = "http://example.test/mod/pra001.xsd"


def referee(
    verdicts: dict[str, tuple[int, int]],
    *,
    messages: tuple[RefereeMessage, ...] = (),
    lost: tuple[str, ...] = (),
    skipped: tuple[str, ...] = (),
) -> RefereeResult:
    chunk = ChunkStat(0, len(verdicts), 1.0, CHUNK_OK, 2.0, 512, 0)
    return RefereeResult(
        rules={rule: RuleVerdict(rule, held, broken) for rule, (held, broken) in verdicts.items()},
        messages=messages,
        skipped=skipped,
        lost=lost,
        chunks=(chunk,),
        schema_ref=SCHEMA_REF,
        filing_indicators=("OF02.00.01",),
        mode=MODE_TRIM,
    )


def native(rule_id: str, satisfied: int, unsatisfied: int) -> RuleResult:
    status = STATUS_FAIL if unsatisfied else STATUS_PASS
    return RuleResult(rule_id, "ERROR", status, satisfied=satisfied, unsatisfied=unsatisfied)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


class TestWhetherARunSupportsTheInstance:
    def test_a_finished_run_with_no_error_message_supports_it(self) -> None:
        """A broken RULE is a finding about the data, not about the file."""
        assert is_supported(referee({"r1": (0, 3)}))

    def test_an_error_level_message_does_not(self) -> None:
        invalid = RefereeMessage("xbrldie:invalid", "ERROR", "fact not valid")
        assert not is_supported(referee({"r1": (1, 0)}, messages=(invalid,)))

    def test_a_warning_alone_does_not_count_against_it(self) -> None:
        warning = RefereeMessage("EBA.3.4", "WARNING", "unused prefix")
        assert is_supported(referee({"r1": (1, 0)}, messages=(warning,)))

    def test_a_run_that_lost_a_rule_does_not(self) -> None:
        assert not is_supported(referee({"r1": (1, 0)}, lost=("r2",)))

    def test_a_disagreement_with_the_native_engine_does_not(self) -> None:
        # Arrange
        result = referee({"r1": (1, 0)})
        agreeing = compare([native("r1", 1, 0)], result)
        disagreeing = compare([native("r1", 0, 1)], result)

        # Act / Assert
        assert is_supported(result, agreeing)
        assert not is_supported(result, disagreeing)


class TestTheTextReport:
    def test_it_states_what_ran_and_names_each_disagreement(self) -> None:
        # Arrange
        result = referee({"r1": (1, 0), "r2": (0, 0), "r3": (0, 7)}, skipped=("r9",))
        differential = compare([native("r1", 1, 0), native("r2", 0, 2), native("r3", 0, 5)], result)

        # Act
        text = render_text("return.xbrl", result, differential)

        # Assert
        assert "Arelle on return.xbrl — complete" in text
        assert "3 evaluated (1 held, 1 broken, 1 never fired)" in text
        assert "1 skipped (template not filed), 0 lost" in text
        assert "3 rule(s): 1 agree, 1 same verdict over a different count, 1 DISAGREE" in text
        assert "disagree      r2: native FAIL (0, 2), Arelle NEVER_FIRED (0, 0)" in text
        assert "count_differs r3: native FAIL (0, 5), Arelle FAIL (0, 7)" in text
        assert text.splitlines()[-1].startswith("Verdict: DISAGREEMENT")

    @pytest.mark.parametrize(
        ("result", "compared", "opening"),
        [
            (referee({"r1": (1, 0)}), True, "Verdict: Arelle accepts the instance and the two"),
            (referee({"r1": (1, 0)}), False, "Verdict: Arelle accepts the instance (the native"),
            (referee({"r1": (1, 0)}, lost=("r2",)), True, "Verdict: NOT ESTABLISHED"),
            (
                referee({"r1": (1, 0)}, messages=(RefereeMessage("x:y", "ERROR", "bad"),)),
                True,
                "Verdict: REJECTED",
            ),
        ],
        ids=["agree", "not-compared", "incomplete", "rejected"],
    )
    def test_the_last_line_is_the_verdict(
        self, result: RefereeResult, compared: bool, opening: str
    ) -> None:
        # Act
        differential = compare([native("r1", 1, 0)], result) if compared else None
        text = render_text("return.xbrl", result, differential)

        # Assert
        assert text.splitlines()[-1].startswith(opening)

    def test_the_record_carries_both_halves_and_the_one_answer(self) -> None:
        # Arrange
        result = referee({"r1": (1, 0)})

        # Act
        alone = to_record(result)
        both = to_record(result, compare([native("r1", 0, 1)], result))

        # Assert
        assert alone["supported"] is True and "differential" not in alone
        assert both["supported"] is False
        assert both["differential"]["disagreements"][0]["rule"] == "r1"
        assert both["referee"]["rules"]["r1"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

LEI = "5493001KJTIIGC8Y1R12"
COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value"]
#: One reported zero: the engine's ``boe_b0708`` and its neighbours hold on it.
CLEAN = [("OF07.00.01.01", "0008", None, "0010", "0010", 0.0, None)]


@pytest.fixture
def instance(tmp_path: Path) -> Path:
    """A real PRA001 instance, written by this package and read by the command."""
    header = ReturnHeader(LEI, date(2027, 3, 31), "PRA001")
    ret = CanonicalReturn.from_frame(header, pl.DataFrame(CLEAN, schema=COLUMNS, orient="row"))
    path = tmp_path / f"{LEI}_PRA001_2027-03-31.xbrl"
    path.write_bytes(write_instance(ret).content)
    return path


@pytest.fixture
def package(tmp_path: Path) -> Path:
    path = tmp_path / "taxonomy.zip"
    path.write_bytes(b"stand-in: the referee is replaced in these tests")
    return path


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``run_referee`` replaced: records its call and returns what the test set."""
    state: dict[str, Any] = {"result": referee({})}

    def run_referee(instance: Path, taxonomy_package: Path, **options: Any) -> RefereeResult:
        state["call"] = (instance, taxonomy_package, options)
        if isinstance(state["result"], Exception):
            raise state["result"]
        return state["result"]

    monkeypatch.setattr(cli, "run_referee", run_referee)
    return state


def run(*arguments: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(["referee", *arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def native_counts(instance: Path, *rule_ids: str) -> dict[str, tuple[int, int]]:
    """What the native engine counts for ``rule_ids`` on the instance."""
    reading = read_instance(instance)
    report = validate_return(reading.ret, reading.pack).report
    assert report is not None
    by_id = {result.rule_id: result for result in report.results}
    return {rule: (by_id[rule].satisfied, by_id[rule].unsatisfied) for rule in rule_ids}


class TestTheRefereeCommand:
    def test_arelle_agreeing_with_the_native_engine_exits_zero(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange — Arelle reports, for two rules, exactly what the engine counts.
        stub["result"] = referee(native_counts(instance, "boe_b0708", "boe_b0713"))

        # Act
        code, out, _err = run(str(instance), "--taxonomy-package", str(package), capsys=capsys)

        # Assert
        assert code == cli.EXIT_OK
        assert "2 rule(s): 2 agree" in out
        assert out.splitlines()[-1].startswith("Verdict: Arelle accepts the instance and the two")

    def test_a_disagreement_exits_non_zero_and_names_the_rule(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange — Arelle says the rule is broken; on this instance it holds.
        held, _broken = native_counts(instance, "boe_b0708")["boe_b0708"]
        assert held > 0
        stub["result"] = referee({"boe_b0708": (0, 1)})

        # Act
        code, out, _err = run(str(instance), "--taxonomy-package", str(package), capsys=capsys)

        # Assert
        assert code == cli.EXIT_FAILED
        assert "disagree      boe_b0708: native PASS" in out

    def test_the_options_reach_the_referee(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Act
        run(
            str(instance),
            "--taxonomy-package",
            str(package),
            "--arelle-python",
            "/opt/arelle/bin/python",
            "--rules",
            "^boe_b07",
            "--workdir",
            str(tmp_path / "work"),
            "--chunk-mb",
            "60",
            "--max-rss-gb",
            "6.5",
            "--timeout",
            "900",
            "--no-filing-rules",
            "--no-compare",
            capsys=capsys,
        )

        # Assert
        called_instance, called_package, options = stub["call"]
        assert (called_instance, called_package) == (instance, package)
        assert options["python"] == Path("/opt/arelle/bin/python")
        assert options["rules"] == "^boe_b07"
        assert options["workdir"] == tmp_path / "work"
        assert (options["chunk_mb"], options["max_rss_gb"], options["timeout"]) == (60, 6.5, 900)
        assert options["filing_rules"] is False

    def test_without_the_comparison_arelle_alone_decides(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange — a verdict the native engine would dispute; it is not asked.
        stub["result"] = referee({"boe_b0708": (0, 1)})

        # Act
        code, out, _err = run(
            str(instance), "--taxonomy-package", str(package), "--no-compare", capsys=capsys
        )

        # Assert
        assert code == cli.EXIT_OK
        assert "Differential" not in out

    def test_the_json_form_and_the_report_file_are_one_record(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange
        stub["result"] = referee(native_counts(instance, "boe_b0708"))
        report = tmp_path / "out" / "referee.json"

        # Act
        code, out, _err = run(
            str(instance),
            "--taxonomy-package",
            str(package),
            "--format",
            "json",
            "--report",
            str(report),
            capsys=capsys,
        )

        # Assert
        assert code == cli.EXIT_OK
        assert json.loads(out) == json.loads(report.read_text(encoding="utf-8"))
        assert json.loads(out)["differential"]["outcomes"]["agree"] == 1

    def test_no_arelle_is_a_plain_failure_that_says_how_to_get_it(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange
        stub["result"] = RefereeUnavailableError(
            'run it as: uvx "rwa-filer[arelle]@latest" referee ...'
        )

        # Act
        code, _out, err = run(str(instance), "--taxonomy-package", str(package), capsys=capsys)

        # Assert
        assert code == cli.EXIT_FAILED
        assert "rwa-filer[arelle]" in err

    @pytest.mark.parametrize("missing", ["instance", "package"])
    def test_a_missing_file_fails_before_anything_is_run(
        self,
        instance: Path,
        package: Path,
        stub: dict[str, Any],
        missing: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange
        (instance if missing == "instance" else package).unlink()

        # Act
        code, _out, err = run(str(instance), "--taxonomy-package", str(package), capsys=capsys)

        # Assert
        assert code == cli.EXIT_FAILED
        assert "not found" in err
        assert "call" not in stub

    def test_a_zip_is_not_an_instance_the_referee_reads(
        self,
        package: Path,
        stub: dict[str, Any],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange
        zipped = tmp_path / "return.zip"
        zipped.write_bytes(b"PK")

        # Act
        code, _out, err = run(str(zipped), "--taxonomy-package", str(package), capsys=capsys)

        # Assert
        assert code == cli.EXIT_FAILED
        assert ".xbrl" in err
        assert "call" not in stub
