"""
The referee's runner, with no Arelle: a FAKE worker stands in for the real one.

``runner.WORKER_SCRIPT`` names the script each worker process runs. These tests
point it at a small stand-in (``FAKE_WORKER`` below) that reads its spec exactly
as the real worker does and answers from a script the test wrote — canned
verdicts for the assertions it was handed, canned messages, or a failure: a
non-zero exit, no result, a sleep past the timeout, more memory than the cap.
So what is pinned here is everything around Arelle: the plan a worker is
handed, the guard it runs under, and the merge of what the workers report.

The module, ``tst001``, files against templates T01 and T02 and has four rules:
- ``boe_b0001`` (400 bytes of XML) needs T01 — the workers report 3 satisfied.
- ``boe_b0002`` (300) needs T01 — 1 satisfied, 2 unsatisfied, with an example.
- ``v0003_m`` (300) needs T01 and T02 — never fires.
- ``boe_b0004`` (200) needs T03, which the instance does NOT file.

Under a 600-byte chunk limit that is two workers: ``boe_b0001`` alone, then
``boe_b0002`` with ``v0003_m``.

The last two sections pin what keeps Arelle optional: the worker's and the
shim's imports, the shape Arelle reads the shim's hooks from, and the parts of
the worker that need no Arelle to run.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import sys
import time
import types
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import rwa_filer.referee
from rwa_filer.referee import (
    ENV_ARELLE_PYTHON,
    VERDICT_FAIL,
    VERDICT_NEVER_FIRED,
    VERDICT_PASS,
    RefereeMessage,
    RefereeResult,
    RefereeUnavailableError,
    RuleVerdict,
    boe_shim,
    find_arelle_python,
    run_referee,
    runner,
    worker,
)

ENTRY_POINT = "http://www.example.test/xbrl/fws/tst/2027-01-01/mod/tst001.xsd"
FRAMEWORK = "tst-package/www.example.test/xbrl/fws/tst/2027-01-01"
XMLNS = 'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"'
PRECONDITION_ARCROLE = "http://xbrl.org/arcrole/2008/variable-set-precondition"

#: name -> (bytes of assertion XML, filing-indicator precondition)
RULES = {
    "boe_b0001": (400, "$find:tT01"),
    "boe_b0002": (300, "$find:tT01"),
    "v0003_m": (300, "($find:tT01 and $find:tT02)"),
    "boe_b0004": (200, "$find:tT03"),
}
FILED = ("T01", "T02")
CHUNK_MB = 600 / 1e6

#: What Arelle would count for each ASSERTION id. An untrimmed run loads every
#: assertion and counts 0 / 0 for the one whose precondition is false.
VERDICTS = {
    "boe_boe_b0001": [3, 0],
    "boe_boe_b0002": [1, 2],
    "boe_v0003_m": [0, 0],
    "boe_boe_b0004": [0, 0],
}
EXAMPLES = {
    "boe_boe_b0002": [
        {
            "level": "ERROR",
            "text": "[boe_b0002];[(t: T01, c: 0010) reported as 5 = 7]",
            "facts": [{"assertion_test": "$a = $b"}, {"line": 12, "value": "5"}],
        }
    ]
}

UNUSED_PREFIX = {"code": "EBA.3.4", "level": "WARNING", "text": "unused prefix eba_GA"}
INVALID_FACT = {"code": "xbrldie:invalid", "level": "ERROR", "text": "fact not valid"}
REWRITE_OVERLAP = {"code": "tpe:packageRewriteOverlap", "level": "WARNING", "text": "overlap"}
SINGLE_CURRENCY = {"code": "EBA.3.1", "level": "ERROR", "text": "only one currency"}

FAKE_WORKER = '''
"""A stand-in for the referee worker: reads the same spec, needs no Arelle."""
import json, re, sys, time, zipfile
from pathlib import Path

if not sys.flags.isolated:
    sys.exit("a worker must be launched isolated (python -I)")
if sys.argv[1:]:
    sys.exit("a worker takes no argument: the spec arrives on standard input")
spec = json.load(sys.stdin)
script = json.loads(Path(__file__).with_name("script.json").read_text(encoding="utf-8"))
chunk = f"chunk{spec['chunk']}"  # "chunk0", "chunk1", ...
behaviour = {**script.get("every", {}), **script.get(chunk, {})}

# The assertions handed over: the ones the overlay's preconditions name or,
# against the official entry point, all of them (less a run-id restriction).
overlays = spec["packages"][1:]
if not spec["formula"]:
    handed = set()
elif overlays:
    with zipfile.ZipFile(overlays[0]) as archive:
        name = next(n for n in archive.namelist() if n.endswith("-find-prec.xml"))
        handed = set(re.findall(r'#([^"]+)"', archive.read(name).decode("utf-8")))
else:
    handed = set(script["verdicts"])
    if spec["run_ids"]:
        handed &= set(spec["run_ids"].split("|"))

ballast = bytearray(b"x") * (behaviour.get("allocate_mb", 0) << 20)
time.sleep(behaviour.get("sleep", 0))
sys.stderr.write(behaviour.get("stderr", ""))
if behaviour.get("exit", 0) == 0 and not behaviour.get("silent"):
    omitted = set(behaviour.get("omit", []))
    counted = {a: c for a, c in script["verdicts"].items() if a in handed and a not in omitted}
    result = {
        "assertions": counted | behaviour.get("also", {}),
        "examples": {a: e for a, e in script["examples"].items() if a in handed},
        "messages": behaviour.get("messages", []),
        "timings": {"loaded_s": 1.5, "validated_s": 2.5},
    }
    # As the real worker does: a fixed name, in the directory it was started in.
    Path("result.json").write_text(json.dumps(result), encoding="utf-8")
sys.exit(behaviour.get("exit", 0))
'''


def build_package(path: Path) -> Path:
    """A taxonomy package with one entry point, its preconditions and assertion files."""
    refs = "".join(
        f'<link:linkbaseRef xlink:href="../val/vr-{name}-err-en.xml" xlink:type="simple" />\n'
        for name in RULES
    )
    xsd = (
        f'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" {XMLNS}>\n'
        f"<xsd:annotation><xsd:appinfo>\n{refs}"
        '<link:linkbaseRef xlink:href="tst001-find-prec.xml" xlink:type="simple" />\n'
        "</xsd:appinfo></xsd:annotation>\n</xsd:schema>\n"
    )
    arcs = "".join(
        f'<variable:precondition xlink:type="resource" xlink:label="p_{name}" test="{test}" />\n'
        f'<link:loc xlink:type="locator" xlink:href="../val/vr-{name}.xml#boe_{name}"'
        f' xlink:label="loc_{name}" />\n'
        f'<gen:arc xlink:type="arc" xlink:arcrole="{PRECONDITION_ARCROLE}"'
        f' xlink:from="loc_{name}" xlink:to="p_{name}" />\n'
        for name, (_size, test) in RULES.items()
    )
    preconditions = (
        f'<link:linkbase {XMLNS} xmlns:gen="http://xbrl.org/2008/generic"'
        ' xmlns:variable="http://xbrl.org/2008/variable">\n'
        f'<gen:link xlink:type="extended">\n{arcs}</gen:link>\n</link:linkbase>\n'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{FRAMEWORK}/mod/tst001.xsd", xsd)
        archive.writestr(f"{FRAMEWORK}/mod/tst001-find-prec.xml", preconditions)
        for name, (size, _test) in RULES.items():
            archive.writestr(f"{FRAMEWORK}/val/vr-{name}.xml", "x" * size)
    return path


def write_instance(path: Path) -> Path:
    indicators = "".join(
        f'<find:filingIndicator contextRef="c0">{code}</find:filingIndicator>' for code in FILED
    )
    path.write_text(
        f'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" {XMLNS}'
        ' xmlns:find="http://www.eurofiling.info/xbrl/ext/filing-indicators">\n'
        f'<link:schemaRef xlink:type="simple" xlink:href="{ENTRY_POINT}"/>\n'
        f"<find:fIndicators>{indicators}</find:fIndicators>\n</xbrli:xbrl>\n",
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class Referee:
    """One instance, one package, and a fake worker whose answers a test scripts."""

    instance: Path
    package: Path
    workdir: Path
    script: Path

    def run(self, script: dict[str, Any] | None = None, **options: Any) -> RefereeResult:
        """Run the referee; ``script`` says how the workers behave (see ``FAKE_WORKER``)."""
        scripted = {"verdicts": VERDICTS, "examples": EXAMPLES} | (script or {})
        self.script.write_text(json.dumps(scripted), encoding="utf-8")
        options.setdefault("python", Path(sys.executable))
        options.setdefault("workdir", self.workdir)
        options.setdefault("chunk_mb", CHUNK_MB)
        return run_referee(self.instance, self.package, **options)

    def spec(self, index: int) -> dict[str, Any]:
        """The spec worker ``index`` was launched with."""
        return json.loads((self.workdir / f"chunk{index}.spec.json").read_text(encoding="utf-8"))

    def handed(self, index: int) -> set[str]:
        """The assertion ids the overlay of worker ``index`` names."""
        with zipfile.ZipFile(self.workdir / f"overlay{index}.zip") as archive:
            text = archive.read("overlay/files/tst001-find-prec.xml").decode("utf-8")
        return set(re.findall(r'\.xml#([^"]+)"', text))


def _referee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Referee:
    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKER_SCRIPT", fake)
    return Referee(
        instance=write_instance(tmp_path / "instance.xbrl"),
        package=build_package(tmp_path / "taxonomy.zip"),
        workdir=tmp_path / "work",
        script=tmp_path / "script.json",
    )


@pytest.fixture
def trimmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Referee:
    """A referee that treats the (tiny) entry point as too large to load whole."""
    monkeypatch.setattr(runner, "AUTO_FULL_LIMIT_MB", 0.0)
    return _referee(tmp_path, monkeypatch)


@pytest.fixture
def untrimmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Referee:
    """A referee on the same entry point, small enough to run against the official one."""
    return _referee(tmp_path, monkeypatch)


def counts(result: RefereeResult) -> dict[str, tuple[int, int]]:
    return {rule: (v.satisfied, v.unsatisfied) for rule, v in result.rules.items()}


# ---------------------------------------------------------------------------
# Merging what the workers report
# ---------------------------------------------------------------------------


def test_verdicts_from_every_worker_are_merged_under_rule_ids(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert — two workers, one result, keyed by RULE id and sorted.
    assert len(result.chunks) == 2
    assert list(result.rules) == ["boe_b0001", "boe_b0002", "v0003_m"]
    assert counts(result) == {"boe_b0001": (3, 0), "boe_b0002": (1, 2), "v0003_m": (0, 0)}
    assert all(verdict.rule_id == rule for rule, verdict in result.rules.items())


def test_a_run_whose_workers_all_finish_is_complete(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert
    assert result.complete is True
    assert result.lost == ()
    assert [chunk.status for chunk in result.chunks] == [runner.CHUNK_OK, runner.CHUNK_OK]
    assert [chunk.index for chunk in result.chunks] == [0, 1]


def test_the_result_describes_the_instance_and_the_run(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert
    assert result.schema_ref == ENTRY_POINT
    assert result.filing_indicators == FILED
    assert result.mode == runner.MODE_TRIM


@pytest.mark.parametrize(
    ("satisfied", "unsatisfied", "status"),
    [
        (3, 0, VERDICT_PASS),
        (1, 2, VERDICT_FAIL),
        (0, 1, VERDICT_FAIL),
        (0, 0, VERDICT_NEVER_FIRED),
    ],
)
def test_a_rule_passes_fails_or_never_fired(satisfied: int, unsatisfied: int, status: str) -> None:
    assert RuleVerdict("boe_b0001", satisfied, unsatisfied).status == status


def test_each_merged_rule_has_the_status_its_counts_give(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert
    assert {rule: verdict.status for rule, verdict in result.rules.items()} == {
        "boe_b0001": "PASS",
        "boe_b0002": "FAIL",
        "v0003_m": "NEVER_FIRED",
    }


def test_the_examples_of_an_unsatisfied_rule_travel_with_it(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert
    (example,) = result.rules["boe_b0002"].examples
    assert example.level == "ERROR"
    assert example.text == "[boe_b0002];[(t: T01, c: 0010) reported as 5 = 7]"
    assert example.facts == ({"assertion_test": "$a = $b"}, {"line": 12, "value": "5"})
    assert result.rules["boe_b0001"].examples == ()


def test_rules_whose_template_is_not_filed_are_skipped_not_run(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert — reported apart, and never handed to a worker.
    assert result.skipped == ("boe_b0004",)
    assert "boe_b0004" not in result.rules
    assert "boe_boe_b0004" not in trimmed.handed(0) | trimmed.handed(1)


def test_a_verdict_for_a_rule_the_plan_did_not_know_is_still_reported(trimmed: Referee) -> None:
    """An assertion with no precondition runs in every worker; Arelle's count stands."""
    # Act
    result = trimmed.run({"every": {"also": {"boe_boe_b0777": [2, 0]}}})

    # Assert
    assert counts(result)["boe_b0777"] == (2, 0)


# ---------------------------------------------------------------------------
# What each worker is handed
# ---------------------------------------------------------------------------


def test_each_worker_is_handed_only_its_own_chunk(trimmed: Referee) -> None:
    # Act
    result = trimmed.run()

    # Assert — first-fit decreasing under the 600-byte limit.
    assert trimmed.handed(0) == {"boe_boe_b0001"}
    assert trimmed.handed(1) == {"boe_boe_b0002", "boe_v0003_m"}
    assert [chunk.assertions for chunk in result.chunks] == [1, 2]


def test_a_trimmed_worker_loads_the_official_package_under_its_overlay(trimmed: Referee) -> None:
    # Act
    trimmed.run()
    spec = trimmed.spec(1)

    # Assert
    assert spec["instance"] == str(trimmed.instance)
    assert spec["packages"] == [str(trimmed.package), str(trimmed.workdir / "overlay1.zip")]
    assert spec["skip_loading"] == "*-rend.xml"
    assert spec["run_ids"] is None
    assert spec["formula"] is True
    assert spec["max_examples"] == 2


def test_the_filing_rules_run_through_the_shim_by_default(trimmed: Referee) -> None:
    # Act
    trimmed.run()
    spec = trimmed.spec(0)

    # Assert — the plug-in is the shim's own file, handed over by path.
    assert spec["disclosure_system"] == "eba"
    assert Path(spec["plugin"]) == Path(boe_shim.__file__)
    assert Path(spec["plugin"]).is_file()


def test_every_worker_loads_the_function_plugins_and_applies_the_repairs(
    trimmed: Referee,
) -> None:
    """With or without the filing rules: they are about the formulas, not the filing."""
    # Act
    with_rules = trimmed.run()
    spec = trimmed.spec(0)
    trimmed.run(filing_rules=False)
    bare = trimmed.spec(0)

    # Assert — and the result says what was changed in Arelle.
    assert spec["function_plugins"] == bare["function_plugins"] == ["functionsMath"]
    assert spec["repairs"] == bare["repairs"] == ["match_any"]
    assert with_rules.to_record()["arelle_repairs"] == ["match_any"]


def test_the_filing_rules_can_be_left_out(trimmed: Referee) -> None:
    # Act
    trimmed.run(filing_rules=False)
    spec = trimmed.spec(0)

    # Assert
    assert spec["disclosure_system"] is None
    assert spec["plugin"] is None


def test_without_formulas_one_worker_loads_no_assertion(trimmed: Referee) -> None:
    # Act
    result = trimmed.run(formulas=False)

    # Assert — nothing to evaluate, so nothing to skip or lose either.
    assert len(result.chunks) == 1
    assert trimmed.spec(0)["formula"] is False
    assert trimmed.handed(0) == set()
    assert result.rules == {}
    assert result.skipped == ()
    assert result.complete is True


def test_the_rules_filter_selects_by_rule_id(trimmed: Referee) -> None:
    # Act — "^v" matches the RULE id v0003_m, whose assertion id starts "boe_".
    result = trimmed.run(rules="^v")

    # Assert
    assert len(result.chunks) == 1
    assert trimmed.handed(0) == {"boe_v0003_m"}
    assert list(result.rules) == ["v0003_m"]
    assert result.skipped == ()


def test_the_rules_filter_applies_to_skipped_rules_too(trimmed: Referee) -> None:
    # Act
    result = trimmed.run(rules="b000[24]")

    # Assert
    assert list(result.rules) == ["boe_b0002"]
    assert result.skipped == ("boe_b0004",)


def test_a_verdict_outside_the_rules_filter_is_not_reported(trimmed: Referee) -> None:
    # Act — the worker also counts an assertion nobody asked for.
    result = trimmed.run({"every": {"also": {"boe_boe_b0777": [2, 0]}}}, rules="^v")

    # Assert
    assert list(result.rules) == ["v0003_m"]


def test_the_overlays_and_each_workers_files_are_kept_in_the_workdir(trimmed: Referee) -> None:
    # Act
    trimmed.run()
    progress = json.loads((trimmed.workdir / "progress.json").read_text(encoding="utf-8"))

    # Assert
    for name in ("overlay0.zip", "chunk0.spec.json", "chunk0.json", "chunk1.stderr.txt"):
        assert (trimmed.workdir / name).is_file()
    assert progress["chunks_planned"] == 2
    assert [chunk["status"] for chunk in progress["chunks"]] == ["ok", "ok"]


def test_without_a_workdir_nothing_is_left_behind(
    trimmed: Referee, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — make this folder the system's temporary directory.
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))

    # Act
    result = trimmed.run(workdir=None)

    # Assert
    assert result.complete is True
    assert list(result.rules) == ["boe_b0001", "boe_b0002", "v0003_m"]
    assert list(scratch.iterdir()) == []


# ---------------------------------------------------------------------------
# Small entry points run untrimmed
# ---------------------------------------------------------------------------


def test_a_small_entry_point_runs_untrimmed_in_one_worker(untrimmed: Referee) -> None:
    # Act
    result = untrimmed.run()
    spec = untrimmed.spec(0)

    # Assert — the official package alone: no overlay, nothing skipped on load.
    assert result.mode == runner.MODE_FULL
    assert len(result.chunks) == 1
    assert spec["packages"] == [str(untrimmed.package)]
    assert spec["skip_loading"] is None
    assert spec["run_ids"] is None
    assert not (untrimmed.workdir / "overlay0.zip").exists()


def test_the_result_does_not_depend_on_how_the_run_was_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Untrimmed, Arelle counts 0 / 0 for a rule whose precondition is false."""
    # Arrange
    whole = _referee(tmp_path, monkeypatch)

    # Act
    full = whole.run()
    monkeypatch.setattr(runner, "AUTO_FULL_LIMIT_MB", 0.0)
    trim = whole.run()

    # Assert — the unfiled template's rule is skipped either way, never NEVER_FIRED.
    assert (full.mode, trim.mode) == (runner.MODE_FULL, runner.MODE_TRIM)
    assert full.skipped == trim.skipped == ("boe_b0004",)
    assert full.rules == trim.rules


def test_a_verdict_arelle_did_reach_is_never_reported_as_skipped(untrimmed: Referee) -> None:
    # Act — the plan expects boe_b0004 not to run; the processor evaluated it.
    result = untrimmed.run({"verdicts": VERDICTS | {"boe_boe_b0004": [0, 1]}})

    # Assert
    assert result.skipped == ()
    assert result.rules["boe_b0004"].status == "FAIL"


def test_untrimmed_the_rules_filter_restricts_evaluation_by_assertion_id(
    untrimmed: Referee,
) -> None:
    # Act
    result = untrimmed.run(rules="^boe_")

    # Assert — the rule ids match; Arelle is given the ASSERTION ids that can fire.
    assert untrimmed.spec(0)["run_ids"] == "boe_boe_b0001|boe_boe_b0002"
    assert list(result.rules) == ["boe_b0001", "boe_b0002"]
    assert result.skipped == ("boe_b0004",)


def test_a_failed_untrimmed_worker_loses_every_rule_that_could_fire(untrimmed: Referee) -> None:
    # Act
    result = untrimmed.run({"every": {"exit": 1}})

    # Assert
    assert result.complete is False
    assert result.lost == ("boe_b0001", "boe_b0002", "v0003_m")
    assert result.skipped == ("boe_b0004",)
    assert result.rules == {}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def test_a_message_every_worker_reports_appears_once(trimmed: Referee) -> None:
    # Act
    result = trimmed.run({"every": {"messages": [UNUSED_PREFIX, INVALID_FACT, UNUSED_PREFIX]}})

    # Assert — in the order first seen.
    assert result.messages == (
        RefereeMessage("EBA.3.4", "WARNING", "unused prefix eba_GA"),
        RefereeMessage("xbrldie:invalid", "ERROR", "fact not valid"),
    )


def test_messages_that_differ_in_text_are_both_kept(trimmed: Referee) -> None:
    # Arrange
    other = UNUSED_PREFIX | {"text": "unused prefix eba_MC"}

    # Act
    result = trimmed.run({"chunk0": {"messages": [UNUSED_PREFIX]}, "chunk1": {"messages": [other]}})

    # Assert
    assert [message.text for message in result.messages] == [
        "unused prefix eba_GA",
        "unused prefix eba_MC",
    ]


def test_the_overlap_the_overlay_causes_is_not_reported(trimmed: Referee) -> None:
    # Act
    result = trimmed.run({"every": {"messages": [REWRITE_OVERLAP, UNUSED_PREFIX]}})

    # Assert
    assert [message.code for message in result.messages] == ["EBA.3.4"]


def test_the_single_currency_false_positive_is_not_reported(trimmed: Referee) -> None:
    # Act
    result = trimmed.run({"every": {"messages": [SINGLE_CURRENCY, INVALID_FACT]}})

    # Assert — dropped although it is an ERROR; the genuine error stays.
    assert [message.code for message in result.messages] == ["xbrldie:invalid"]
    assert "EBA.3.1" in runner.KNOWN_FALSE_POSITIVE_CODES


@pytest.mark.parametrize(
    ("level", "is_error"),
    [
        ("WARNING", False),
        ("WARNING-SEMANTIC", False),
        ("INCONSISTENCY", False),
        ("ERROR-SEMANTIC", True),
        ("ERROR", True),
        ("CRITICAL", True),
    ],
)
def test_errors_are_the_messages_at_an_error_level(
    trimmed: Referee, level: str, is_error: bool
) -> None:
    # Arrange
    message = {"code": "xbrl:something", "level": level, "text": "said once"}

    # Act
    result = trimmed.run({"chunk0": {"messages": [message, UNUSED_PREFIX]}})

    # Assert
    assert len(result.messages) == 2
    assert [error.level for error in result.errors] == ([level] if is_error else [])


def test_an_unsatisfied_rule_is_not_an_error_message(trimmed: Referee) -> None:
    """``errors`` is about whether the file is valid XBRL, not about the rules."""
    # Act
    result = trimmed.run()

    # Assert
    assert result.rules["boe_b0002"].status == "FAIL"
    assert result.errors == ()


def test_the_result_is_a_json_ready_record(trimmed: Referee) -> None:
    # Act
    record = trimmed.run({"every": {"messages": [UNUSED_PREFIX]}}).to_record()
    round_tripped = json.loads(json.dumps(record))

    # Assert
    assert round_tripped == record
    assert record["complete"] is True
    assert record["mode"] == "trim"
    assert record["filing_indicators"] == ["T01", "T02"]
    assert record["skipped"] == ["boe_b0004"]
    assert record["lost"] == []
    assert record["messages"] == [UNUSED_PREFIX]
    assert record["rules"]["boe_b0002"] == {
        "status": "FAIL",
        "satisfied": 1,
        "unsatisfied": 2,
        "examples": EXAMPLES["boe_boe_b0002"],
    }
    assert [chunk["status"] for chunk in record["chunks"]] == ["ok", "ok"]


# ---------------------------------------------------------------------------
# Workers that fail
# ---------------------------------------------------------------------------


def test_a_worker_that_exits_non_zero_loses_its_rules(trimmed: Referee) -> None:
    # Arrange
    traceback = "Traceback (most recent call last):\n  ...\nModuleNotFoundError: no arelle\n\n"

    # Act
    result = trimmed.run({"chunk1": {"exit": 3, "stderr": traceback}})

    # Assert — the other worker's verdicts stand; the status carries the reason.
    assert result.complete is False
    assert result.lost == ("boe_b0002", "v0003_m")
    assert list(result.rules) == ["boe_b0001"]
    assert result.chunks[0].ok is True
    assert result.chunks[1].ok is False
    assert result.chunks[1].returncode == 3
    assert result.chunks[1].status == "worker exit 3: ModuleNotFoundError: no arelle"


def test_a_worker_that_writes_nothing_loses_its_rules(trimmed: Referee) -> None:
    # Act
    result = trimmed.run({"chunk0": {"silent": True}})

    # Assert
    assert result.complete is False
    assert result.lost == ("boe_b0001",)
    assert list(result.rules) == ["boe_b0002", "v0003_m"]
    assert result.chunks[0].status == "worker wrote no result"
    assert result.chunks[0].returncode == 0


def test_a_finished_worker_that_gives_no_verdict_for_a_rule_loses_it(trimmed: Referee) -> None:
    """Arelle evaluates NOTHING in a session where one formula fails to compile.

    The worker still exits cleanly, with an empty verdict table. Silence about
    a rule it was handed is not "never fired".
    """
    # Act — worker 1 finishes, and says nothing about one of its two rules.
    result = trimmed.run({"chunk1": {"omit": ["boe_boe_b0002"]}})

    # Assert
    assert result.lost == ("boe_b0002",)
    assert result.complete is False
    assert "boe_b0002" not in result.rules
    assert list(result.rules) == ["boe_b0001", "v0003_m"]
    assert result.chunks[1].ok is True


def test_a_result_left_by_an_earlier_run_is_never_read(trimmed: Referee) -> None:
    # Arrange — a good run leaves chunk0.json in the workdir.
    assert trimmed.run().complete is True

    # Act — the same workdir again, and this time worker 0 writes nothing.
    result = trimmed.run({"chunk0": {"silent": True}})

    # Assert
    assert result.lost == ("boe_b0001",)
    assert "boe_b0001" not in result.rules


def test_a_stray_result_file_in_the_workdir_is_never_read(trimmed: Referee) -> None:
    """Each worker writes ``RESULT_FILE`` in the workdir; one already there is not its result."""
    # Arrange — a result file no worker of this run wrote.
    trimmed.workdir.mkdir(parents=True, exist_ok=True)
    stray = {"assertions": {"boe_boe_b0001": [9, 9]}, "examples": {}, "messages": []}
    (trimmed.workdir / worker.RESULT_FILE).write_text(json.dumps(stray), encoding="utf-8")

    # Act — worker 0 writes nothing.
    result = trimmed.run({"chunk0": {"silent": True}})

    # Assert
    assert result.lost == ("boe_b0001",)
    assert result.chunks[0].status == "worker wrote no result"


def test_a_lost_rule_is_neither_passed_nor_skipped(trimmed: Referee) -> None:
    # Act
    result = trimmed.run({"every": {"exit": 1}})

    # Assert — every rule is in exactly one of the three places.
    assert result.rules == {}
    assert result.lost == ("boe_b0001", "boe_b0002", "v0003_m")
    assert result.skipped == ("boe_b0004",)
    assert result.to_record()["complete"] is False


def test_a_failed_worker_with_no_rule_to_lose_still_leaves_the_run_incomplete(
    trimmed: Referee,
) -> None:
    """Without formulas a worker answers for no rule, only for the file's validity."""
    # Act
    result = trimmed.run({"every": {"exit": 1}}, formulas=False)

    # Assert — nothing is lost by name, and the messages are missing all the same.
    assert result.lost == ()
    assert result.chunks[0].ok is False
    assert result.complete is False


def test_a_worker_past_the_timeout_is_killed_and_reported(trimmed: Referee) -> None:
    # Arrange
    started = time.monotonic()

    # Act — each worker would sleep for a minute.
    result = trimmed.run({"every": {"sleep": 60}}, timeout=0.2)

    # Assert — both killed long before that, and said so.
    assert time.monotonic() - started < 20
    assert [chunk.status for chunk in result.chunks] == ["killed: timeout 0.2s"] * 2
    assert all(chunk.returncode != 0 for chunk in result.chunks)
    assert result.complete is False
    assert result.lost == ("boe_b0001", "boe_b0002", "v0003_m")


needs_proc = pytest.mark.skipif(
    not Path("/proc/self/status").is_file(),
    reason="the memory guard reads /proc, which this platform does not have",
)


@needs_proc
def test_a_worker_over_the_memory_cap_is_killed_and_reported(trimmed: Referee) -> None:
    """The same cap spares a worker that stays under it."""
    # Act — worker 0 holds 300 MB for a minute; worker 1 holds nothing, for a second.
    result = trimmed.run(
        {"chunk0": {"allocate_mb": 300, "sleep": 60}, "chunk1": {"sleep": 1.2}}, max_rss_gb=0.2
    )
    hog, modest = result.chunks

    # Assert
    assert re.fullmatch(r"killed: rss \d+ MB > cap 204 MB", hog.status)
    assert hog.peak_rss_mb is not None
    assert hog.peak_rss_mb > 204
    assert modest.ok is True
    assert modest.peak_rss_mb is not None
    assert 0 < modest.peak_rss_mb < 204
    assert result.lost == ("boe_b0001",)


def test_where_memory_cannot_be_measured_only_the_timeout_is_enforced(
    trimmed: Referee,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange — a platform with no /proc, and a cap every process exceeds.
    monkeypatch.setattr(runner, "_PROC", tmp_path / "no-proc")
    caplog.set_level(logging.WARNING, logger=runner.__name__)

    # Act — long enough to be polled at least twice.
    result = trimmed.run({"chunk0": {"sleep": 1.2}}, max_rss_gb=1e-9)

    # Assert — not killed, not measured, and the run said why.
    assert result.complete is True
    assert [chunk.peak_rss_mb for chunk in result.chunks] == [None, None]
    (record,) = caplog.records
    assert "no /proc" in record.getMessage()
    assert "timeout only" in record.getMessage()


@needs_proc
def test_where_memory_can_be_measured_the_guard_is_silent_and_bites(
    trimmed: Referee, caplog: pytest.LogCaptureFixture
) -> None:
    """The control for the test above: the same run, with /proc, is killed."""
    # Arrange
    caplog.set_level(logging.WARNING, logger=runner.__name__)

    # Act
    result = trimmed.run({"chunk0": {"sleep": 1.2}}, max_rss_gb=1e-9)

    # Assert
    assert result.chunks[0].status.startswith("killed: rss")
    assert not any("no /proc" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Locating Arelle
# ---------------------------------------------------------------------------


@pytest.fixture
def no_arelle(monkeypatch: pytest.MonkeyPatch) -> None:
    """No environment variable, and no Arelle in the current interpreter."""
    real = importlib.util.find_spec

    def find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        return None if name == "arelle" else real(name, *args, **kwargs)

    monkeypatch.delenv(ENV_ARELLE_PYTHON, raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


@pytest.fixture
def arelle_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """No environment variable, and Arelle importable by the current interpreter."""
    real = importlib.util.find_spec

    def find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        return real("json") if name == "arelle" else real(name, *args, **kwargs)

    monkeypatch.delenv(ENV_ARELLE_PYTHON, raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


def test_an_explicit_interpreter_wins(monkeypatch: pytest.MonkeyPatch, arelle_here: None) -> None:
    # Arrange
    monkeypatch.setenv(ENV_ARELLE_PYTHON, "/from/the/environment/python")

    # Act / Assert
    assert find_arelle_python(Path("/explicit/python")) == Path("/explicit/python")


def test_the_environment_variable_wins_over_the_current_interpreter(
    monkeypatch: pytest.MonkeyPatch, arelle_here: None
) -> None:
    # Arrange
    monkeypatch.setenv(ENV_ARELLE_PYTHON, "/from/the/environment/python")

    # Act / Assert
    assert find_arelle_python(None) == Path("/from/the/environment/python")


def test_the_current_interpreter_is_used_when_it_has_arelle(arelle_here: None) -> None:
    assert find_arelle_python(None) == Path(sys.executable)


def test_an_empty_environment_variable_is_not_an_interpreter(
    monkeypatch: pytest.MonkeyPatch, arelle_here: None
) -> None:
    # Arrange
    monkeypatch.setenv(ENV_ARELLE_PYTHON, "")

    # Act / Assert
    assert find_arelle_python(None) == Path(sys.executable)


def test_with_no_arelle_anywhere_the_error_says_how_to_get_it(no_arelle: None) -> None:
    # Act
    with pytest.raises(RefereeUnavailableError) as raised:
        find_arelle_python(None)

    # Assert — both remedies, spelt so they can be copied.
    message = str(raised.value)
    assert 'pip install "rwa-filer[arelle]"' in message
    assert "RWA_FILER_ARELLE_PYTHON" in message
    assert "arelle-release" in message
    assert isinstance(raised.value, RuntimeError)


def test_the_referee_refuses_to_start_without_arelle(untrimmed: Referee, no_arelle: None) -> None:
    # Act / Assert
    with pytest.raises(RefereeUnavailableError):
        untrimmed.run(python=None)
    assert not untrimmed.workdir.exists()


def test_the_environment_variable_names_the_interpreter_the_workers_run_under(
    untrimmed: Referee, monkeypatch: pytest.MonkeyPatch, no_arelle: None
) -> None:
    # Arrange
    monkeypatch.setenv(ENV_ARELLE_PYTHON, sys.executable)

    # Act
    result = untrimmed.run(python=None)

    # Assert
    assert result.complete is True


@pytest.mark.skipif(
    importlib.util.find_spec("arelle") is not None,
    reason="Arelle is installed here, so the real worker would not fail",
)
def test_the_real_worker_fails_loudly_under_an_interpreter_without_arelle(
    untrimmed: Referee, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end with the REAL worker script: launched, isolated, and understood."""
    # Arrange
    monkeypatch.setattr(runner, "WORKER_SCRIPT", Path(worker.__file__))

    # Act
    result = untrimmed.run(python=Path(sys.executable))

    # Assert
    assert result.complete is False
    assert result.lost == ("boe_b0001", "boe_b0002", "v0003_m")
    assert "No module named 'arelle'" in result.chunks[0].status


# ---------------------------------------------------------------------------
# What keeps Arelle optional: imports and the plug-in declaration
# ---------------------------------------------------------------------------

REFEREE_DIR = Path(rwa_filer.referee.__file__).resolve().parent


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or "").split(".")[0])
    return names


def test_no_referee_module_imports_arelle_statically() -> None:
    # Arrange
    modules = sorted(REFEREE_DIR.glob("*.py"))

    # Act
    offenders = [path.name for path in modules if "arelle" in _imported_modules(_tree(path))]

    # Assert
    assert {path.name for path in modules} >= {"worker.py", "boe_shim.py", "runner.py", "plan.py"}
    assert offenders == []


@pytest.mark.parametrize("name", ["worker.py", "boe_shim.py", "plan.py"])
def test_the_standalone_modules_import_only_the_standard_library(name: str) -> None:
    """The worker and the shim run where rwa-filer is not installed."""
    # Act
    imported = _imported_modules(_tree(REFEREE_DIR / name))

    # Assert — nothing relative, nothing third-party, nothing from rwa-filer.
    assert imported
    assert imported <= sys.stdlib_module_names | {"__future__"}


def test_the_shim_declares_its_hooks_the_way_arelle_reads_them() -> None:
    """Arelle takes ``__pluginInfo__`` from the syntax tree, top to bottom.

    A hook counts only if its value is the bare name of a function defined at
    module level EARLIER in the file, in a plain assignment of a dict literal.
    """
    # Arrange
    body = _tree(REFEREE_DIR / "boe_shim.py").body
    defined: set[str] = set()
    hooks: dict[str, bool] = {}
    constants: dict[str, object] = {}

    # Act — the walk Arelle's plug-in manager makes.
    for node in body:
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__pluginInfo__"
        ):
            assert isinstance(node.value, ast.Dict)
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                assert isinstance(key, ast.Constant)
                if isinstance(value, ast.Constant):
                    constants[key.value] = value.value
                else:
                    hooks[key.value] = isinstance(value, ast.Name) and value.id in defined

    # Assert
    assert constants["name"]
    assert constants["version"]
    assert set(hooks) == {
        "DisclosureSystem.Types",
        "DisclosureSystem.ConfigURL",
        "Validate.XBRL.Start",
        "Validate.XBRL.Finally",
        "Streaming.ValidateFacts",
        "Streaming.ValidateFinish",
    }
    assert all(hooks.values())


def test_the_shim_imports_without_arelle_and_binds_its_own_set_up_hook() -> None:
    # Assert — importing it (above) needed no Arelle; the one changed hook is its own.
    assert boe_shim.__pluginInfo__["Validate.XBRL.Start"] is boe_shim.validate_setup
    assert Path(boe_shim.__file__).name == runner.FILING_RULES_PLUGIN.name


# ---------------------------------------------------------------------------
# The worker's Arelle-free parts
# ---------------------------------------------------------------------------


def test_only_the_first_few_evaluation_messages_of_an_assertion_pass() -> None:
    # Arrange
    limiter = worker._ExampleLimiter(2)

    # Act
    first = [limiter.match("message:boe_a") for _ in range(4)]
    other = [limiter.match("message:boe_b") for _ in range(3)]

    # Assert — the cap is per assertion.
    assert first == [True, True, False, False]
    assert other == [True, True, False]


def test_a_message_that_is_not_an_evaluation_always_passes() -> None:
    # Arrange
    limiter = worker._ExampleLimiter(0)

    # Act / Assert
    assert all(limiter.match("EBA.2.7") for _ in range(5))
    assert limiter.match("message:boe_a") is False


def test_the_verdict_counts_are_the_dicts_among_a_models_errors() -> None:
    # Arrange — message codes, then the dict formula processing appends.
    errors = ["EBA.2.7", {"boe_a": (3, 1, 0, 0, 1), "boe_b": (0, 0, 0, 0, 0)}, "xbrl:other"]

    # Act
    verdicts = worker.harvest_verdicts(errors)

    # Assert
    assert verdicts == {"boe_a": (3, 1), "boe_b": (0, 0)}


def test_log_records_are_sorted_into_examples_messages_and_timings() -> None:
    # Arrange
    ref = {"href": "/data/instance.xbrl#f1", "sourceLine": 12, "properties": []}
    records: list[Any] = [
        (0.1, "INFO", "info", "loaded in 5.94 secs at 2027", []),
        (0.2, "INFO", "info", "validated in 6.66 secs", []),
        (0.3, "INFO", "info:profileActivity", " validating filing rules 0.001 secs ", []),
        (0.4, "INFO", "formula:trace", "not a message", []),
        (0.5, "WARNING", "EBA.2.7", "unused context", []),
        (0.6, "ERROR", "message:boe_a", "first", [ref]),
        (0.7, "ERROR", "message:boe_a", "second", []),
        (0.8, "ERROR", "message:boe_a", "third", []),
    ]

    # Act
    summary = worker.summarise(records, "/data/instance.xbrl", max_examples=2)

    # Assert
    assert summary["timings"] == {
        "loaded_s": 5.94,
        "validated_s": 6.66,
        "activity": ["validating filing rules 0.001 secs"],
    }
    assert summary["messages"] == [
        {"code": "EBA.2.7", "level": "WARNING", "text": "unused context"}
    ]
    assert [example["text"] for example in summary["examples"]["boe_a"]] == ["first", "second"]
    assert summary["examples"]["boe_a"][0]["facts"][0]["line"] == 12


def test_a_failing_evaluations_refs_reduce_to_its_test_and_its_bound_facts() -> None:
    # Arrange — Arelle's refs: the assertion resource, then a fact of the instance.
    refs = [
        {"href": "vr-boe_a.xml#boe_a", "properties": [("test", "$a = sum($b)")]},
        {"href": "taxonomy.xsd#other", "properties": [("label", "not a fact, no test")]},
        {
            "href": "/data/instance.xbrl#element(/1/20)",
            "sourceLine": 119,
            "properties": [
                ("QName", "eba_met:mi180"),
                ("contextRef", "c4", [("dimensions", "(2)", [("eba_dim:BAS", "eba_BA:x9")])]),
                ("decimals", "-3"),
                ("value", "1000"),
            ],
        },
    ]

    # Act
    facts = worker._fact_refs(refs, "/data/instance.xbrl")

    # Assert
    assert facts == [
        {"assertion_test": "$a = sum($b)"},
        {
            "line": 119,
            "concept": "eba_met:mi180",
            "contextRef": "c4",
            "dimensions": {"eba_dim:BAS": "eba_BA:x9"},
            "decimals": "-3",
            "value": "1000",
        },
    ]


def test_the_collector_installs_the_limiter_on_arelles_logger_at_the_first_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    arelle_logger = logging.getLogger(worker.ARELLE_LOGGER)
    monkeypatch.setattr(arelle_logger, "messageCodeFilter", None, raising=False)
    limiter = worker._ExampleLimiter(2)
    collector = worker._Collector(limiter)
    record = logging.LogRecord("arelle", logging.ERROR, "", 0, "%s is wrong", ("this",), None)
    record.messageCode = "message:boe_a"
    record.refs = [{"href": "instance.xbrl"}]

    # Act
    collector.emit(record)

    # Assert
    assert arelle_logger.messageCodeFilter is limiter
    ((_seconds, level, code, text, refs),) = collector.records
    assert (level, code, text, refs) == (
        "ERROR",
        "message:boe_a",
        "this is wrong",
        [{"href": "instance.xbrl"}],
    )


def test_the_worker_script_takes_no_argument() -> None:
    """The spec arrives on standard input; a path on the command line is refused."""
    assert worker.main(["spec.json"]) == 2
    assert worker.main(["one.json", "two.json"]) == 2


def test_no_outside_value_reaches_a_path_taking_call_in_the_worker() -> None:
    """The worker opens files only by constant name, and never hands data to one.

    SonarCloud reported two taint flows through ``worker.main``:
    ``pythonsecurity:S8707`` (``sys.argv`` -> ``Path(...).read_text``, the spec's
    path from the command line) and ``pythonsecurity:S2083`` (the spec's own
    ``out`` -> ``Path(...).write_text``, the result's path from file content). The
    spec now arrives on standard input and the result is written through a stream
    opened on ``RESULT_FILE`` in the working directory the runner sets, so every
    ``Path(...)`` / ``open(...)`` in the module takes a module constant or
    ``__file__`` and nothing else, and no ``write_text`` / ``write_bytes`` carries
    data — the shape the generator's S2083 fix established
    (tests/contracts/test_docs_freshness.py).
    """
    # Arrange
    tree = _tree(REFEREE_DIR / "worker.py")
    constants = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id.isupper()
    }

    def is_constant(arg: ast.expr) -> bool:
        return isinstance(arg, ast.Constant) or (
            isinstance(arg, ast.Name) and (arg.id in constants or arg.id == "__file__")
        )

    # Act
    offenders = [
        f"line {node.lineno}: {ast.unparse(node)[:80]}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (
                isinstance(node.func, ast.Name)
                and node.func.id in {"Path", "open"}
                and not all(is_constant(arg) for arg in node.args)
            )
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"write_text", "write_bytes"}
            )
        )
    ]

    # Assert
    assert "RESULT_FILE" in constants
    assert not offenders, "\n".join(offenders)


# ---------------------------------------------------------------------------
# The worker's dealings with Arelle, against stand-ins for its modules
# ---------------------------------------------------------------------------


class _Fact:
    """Stands in for ``arelle.ModelInstanceObject.ModelFact``."""


class _Context:
    def __init__(self, bound: object) -> None:
        self.inScopeVars = {"v1": bound}


@pytest.fixture
def match_filter(monkeypatch: pytest.MonkeyPatch) -> type:
    """A stand-in ``ModelMatchFilter`` whose ``filter`` reports what it was handed."""

    class ModelMatchFilter:
        variable = "v1"

        def __init__(self, match_any: bool) -> None:
            self.matchAny = match_any

        def filter(self, context: _Context, _binding: object, _facts: object, _c: object) -> object:
            return context.inScopeVars[self.variable]

    formula_objects = types.ModuleType("arelle.ModelFormulaObject")
    formula_objects.ModelMatchFilter = ModelMatchFilter  # type: ignore[attr-defined]
    instance_objects = types.ModuleType("arelle.ModelInstanceObject")
    instance_objects.ModelFact = _Fact  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "arelle", types.ModuleType("arelle"))
    monkeypatch.setitem(sys.modules, "arelle.ModelFormulaObject", formula_objects)
    monkeypatch.setitem(sys.modules, "arelle.ModelInstanceObject", instance_objects)
    worker.repair_match_any()
    return ModelMatchFilter


def test_a_single_matched_fact_reaches_the_match_filter_as_a_sequence_of_one(
    match_filter: type,
) -> None:
    """Stock Arelle iterates the fact itself — its child elements — and matches nothing."""
    # Arrange
    fact = _Fact()
    context = _Context(fact)

    # Act
    handed = match_filter(match_any=True).filter(context, None, set(), False)

    # Assert — and the variable is left bound as it was.
    assert handed == (fact,)
    assert context.inScopeVars["v1"] is fact


@pytest.mark.parametrize(
    ("match_any", "bound"),
    [(False, _Fact()), (True, [_Fact(), _Fact()]), (True, None)],
    ids=["match-all", "already-a-sequence", "unbound"],
)
def test_the_match_filter_is_otherwise_left_alone(
    match_filter: type, match_any: bool, bound: object
) -> None:
    # Act
    handed = match_filter(match_any=match_any).filter(_Context(bound), None, set(), False)

    # Assert
    assert handed is bound


def test_the_repair_is_installed_once(match_filter: type) -> None:
    # Arrange
    installed = match_filter.filter

    # Act
    worker.repair_match_any()

    # Assert
    assert match_filter.filter is installed


@pytest.mark.parametrize(
    ("plugin", "expected"),
    [("/x/boe_shim.py", "/x/boe_shim.py|functionsMath"), (None, "functionsMath")],
    ids=["with-filing-rules", "without"],
)
def test_the_session_is_given_the_filing_plugin_and_the_function_plugins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, plugin: str | None, expected: str
) -> None:
    # Arrange — stand-ins for the two Arelle modules ``run_session`` reaches.
    seen: dict[str, Any] = {}

    class RuntimeOptions:
        def __init__(self, **options: Any) -> None:
            seen.update(options)

    class Session:
        def __enter__(self) -> Session:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def run(self, _options: object, logHandler: object = None) -> None:  # noqa: N803
            seen["ran"] = True

        def get_models(self) -> list[object]:
            return []

    session_api = types.ModuleType("arelle.api.Session")
    session_api.Session = Session  # type: ignore[attr-defined]
    runtime_options = types.ModuleType("arelle.RuntimeOptions")
    runtime_options.RuntimeOptions = RuntimeOptions  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "arelle", types.ModuleType("arelle"))
    monkeypatch.setitem(sys.modules, "arelle.api", types.ModuleType("arelle.api"))
    monkeypatch.setitem(sys.modules, "arelle.api.Session", session_api)
    monkeypatch.setitem(sys.modules, "arelle.RuntimeOptions", runtime_options)
    spec = {
        "instance": str(tmp_path / "i.xbrl"),
        "packages": [],
        "plugin": plugin,
        "disclosure_system": "eba" if plugin else None,
        "function_plugins": ["functionsMath"],
        "repairs": [],
        "formula": True,
        "run_ids": None,
        "skip_loading": None,
        "xdg": str(tmp_path / "xdg"),
        "max_examples": 2,
    }

    # Act
    result = worker.run_session(spec)

    # Assert
    assert seen["plugins"] == expected
    assert seen["ran"] is True
    assert result["assertions"] == {}
