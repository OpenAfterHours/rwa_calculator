"""
The referee against the real Arelle and the Bank of England's own taxonomy package.

Opt-in, never in CI: Arelle is an optional tool and the taxonomy package is the
publisher's file, which is not redistributed. SKIPPED unless BOTH are named:

    RWA_FILER_ARELLE_PYTHON=/path/to/arelle-venv/bin/python \
    RWA_FILER_BOE_TAXONOMY=/path/to/boe-banking-taxonomy.zip \
        uv run pytest packages/rwa-filer/tests/referee/test_real_arelle.py -q

It takes a few minutes and several GB of memory — PRA001 is 741 MB of taxonomy
XML, which is why the referee runs it in trimmed chunks — and it runs one
Arelle process at a time. Do not run it alongside another.

The instance is written here, by this package's own writer, from seven cells
across four templates. So this is the end-to-end claim: what rwa-filer writes,
the reference XBRL processor accepts — valid XBRL 2.1, dimensionally valid,
no filing-rule message — and evaluates the published rules on.

The counts below were measured with arelle-release 2.47.5 on the Banking
Taxonomy v4.1.1 package (PRA001 entry point dated 2026-08-17: 1,441
assertions). A new publication needs a new measurement, not an edit.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_filer.boe.catalogue import rulebook_for_module
from rwa_filer.boe.engine import RuleResult, evaluate_rules
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.referee import (
    ENV_ARELLE_PYTHON,
    VERDICT_FAIL,
    VERDICT_NEVER_FIRED,
    VERDICT_PASS,
    RefereeResult,
    run_referee,
)
from rwa_filer.referee.differential import compare
from rwa_filer.referee.runner import MODE_TRIM
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance
from sample_carve import thin_carve

ENV_BOE_TAXONOMY = "RWA_FILER_BOE_TAXONOMY"
ARELLE_PYTHON = os.environ.get(ENV_ARELLE_PYTHON)
BOE_TAXONOMY = os.environ.get(ENV_BOE_TAXONOMY)

pytestmark = pytest.mark.skipif(
    not (ARELLE_PYTHON and BOE_TAXONOMY),
    reason=f"set {ENV_ARELLE_PYTHON} (a Python with arelle-release) and {ENV_BOE_TAXONOMY} "
    "(the BoE Banking Taxonomy package zip)",
)

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), "PRA001")
COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value"]
FACTS = [
    ("OF02.00.01.01", None, None, "0010", "0010", 1234567.89, None),
    ("OF07.00.01.01", "0008", None, "0010", "0010", 100.0, None),
    ("OF09.01.01.01", None, "GB", "0010", "0010", 70.0, None),
    ("OF09.01.01.01", None, "x1", "0010", "0010", 100.0, None),
    ("OF08.02.01.01", "0006", None, "1", "0005", None, "1"),
    ("OF08.02.01.01", "0006", None, "1", "0010", 0.0125, None),
    ("OF08.02.01.01", "0006", None, "1", "0020", 1000.0, None),
]
FILED = ("OF02.00.01", "OF07.00.01", "OF08.02.01", "OF09.01.01")

MODULE_ASSERTIONS = 1_441
#: Rules of templates the instance does not file: never loaded, never run.
SKIPPED = 1_085
#: The rest: loaded and applicable. Most bind no reported fact and never fire.
EVALUATED = 356
PASSED = 56
NEVER_FIRED = 298
#: Both fail on the DATA, not on the file: an unreported cell is read as zero.
#: boe_b0760 — OF 08.02 column 0090 (not reported) against the sum of 0020-0080.
#: boe_b1092 — OF 02.00 row 0010 against the sum of its (unreported) components.
FAILED = {"boe_b0760": "ERROR", "boe_b1092": "WARNING"}


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> RefereeResult:
    """One referee run for the whole module: it is minutes, not milliseconds."""
    folder = tmp_path_factory.mktemp("referee")
    frame = pl.DataFrame(FACTS, schema=COLUMNS, orient="row")
    instance = folder / "5493001KJTIIGC8Y1R12_PRA001_2027-03-31.xbrl"
    instance.write_bytes(write_instance(CanonicalReturn.from_frame(HEADER, frame)).content)
    return run_referee(instance, Path(BOE_TAXONOMY or ""), workdir=folder / "run")


def test_every_worker_ran_to_the_end(result: RefereeResult) -> None:
    # Assert — the large entry point was trimmed, and nothing was killed or lost.
    assert result.mode == MODE_TRIM
    assert len(result.chunks) > 1
    assert [chunk.status for chunk in result.chunks] == ["ok"] * len(result.chunks)
    assert result.lost == ()
    assert result.complete is True


def test_arelle_accepts_the_written_instance_without_a_message(result: RefereeResult) -> None:
    # Assert — not an error, and not a filing-rule warning either.
    assert result.errors == ()
    assert result.messages == ()
    assert result.filing_indicators == FILED


def test_only_the_filed_templates_rules_were_run(result: RefereeResult) -> None:
    # Assert — every assertion of the module is accounted for, once.
    assert len(result.skipped) == SKIPPED
    assert len(result.rules) == EVALUATED
    assert len(result.skipped) + len(result.rules) == MODULE_ASSERTIONS
    assert set(result.skipped).isdisjoint(result.rules)
    assert sum(chunk.assertions for chunk in result.chunks) == EVALUATED


def test_the_two_rules_the_sparse_data_breaks_are_the_only_failures(
    result: RefereeResult,
) -> None:
    # Act
    by_status = {
        status: sorted(rule for rule, verdict in result.rules.items() if verdict.status == status)
        for status in (VERDICT_PASS, VERDICT_FAIL, VERDICT_NEVER_FIRED)
    }

    # Assert
    assert by_status[VERDICT_FAIL] == sorted(FAILED)
    assert len(by_status[VERDICT_PASS]) == PASSED
    assert len(by_status[VERDICT_NEVER_FIRED]) == NEVER_FIRED


def test_each_failure_comes_with_its_severity_and_the_facts_it_bound(
    result: RefereeResult,
) -> None:
    for rule, severity in FAILED.items():
        # Act
        verdict = result.rules[rule]
        (example,) = verdict.examples

        # Assert — one unsatisfied evaluation, at the rule's published severity,
        # carrying the assertion's test and at least one fact of the instance.
        assert (verdict.satisfied, verdict.unsatisfied) == (0, 1)
        assert example.level == severity
        assert example.text.startswith(f"[{rule}]")
        assert "assertion_test" in example.facts[0]
        assert any(fact.get("contextRef") for fact in example.facts[1:])


# ---------------------------------------------------------------------------
# What stock Arelle cannot evaluate, on a carve of the Bank's sample
# ---------------------------------------------------------------------------

BOE_DIR = os.environ.get("RWA_FILER_BOE_DIR")
#: The market-risk desk tables (the twelve ``boe_b0919`` join rules) and the
#: OF 16.00 tables (``boe_b0599`` and ``boe_b0600``, which call ``xfm:log``).
DESK_AND_LOG_INDICATORS = frozenset(
    {
        "OF16.00.01.01",
        "OF16.00.01.02",
        "OF16.00.01.03",
        "OF16.00.01.04",
        "OF16.00.01.05",
        "OF16.00.01.06",
        "OF24.03.01",
    }
)
JOIN_RULES = tuple(f"boe_b0919_{number}" for number in range(1, 13))
LOG_RULES = ("boe_b0599", "boe_b0600")
SELECTED = r"^boe_b0(919_\d+|599|600)$"


@pytest.fixture(scope="module")
def desk_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[RefereeResult, dict[str, RuleResult]]:
    """Fourteen rules, by Arelle and by the native engine, on one carved instance."""
    found = sorted(Path(BOE_DIR or ".").rglob("*_PRA001_*.xbrl")) if BOE_DIR else []
    if not found:
        pytest.skip("set RWA_FILER_BOE_DIR to a directory holding the BoE PRA001 sample")
    sample = read_instance(found[0])
    written = write_instance(thin_carve(sample, DESK_AND_LOG_INDICATORS), sample.pack)
    folder = tmp_path_factory.mktemp("desks")
    instance = folder / "5493001KJTIIGC8Y1R12_PRA001_2027-03-31.xbrl"
    instance.write_bytes(written.content)
    referee = run_referee(
        instance, Path(BOE_TAXONOMY or ""), workdir=folder / "run", rules=SELECTED
    )
    filed = read_instance(written.content, pack=sample.pack)
    wanted = set(JOIN_RULES) | set(LOG_RULES)
    rules = [
        rule for rule in rulebook_for_module("PRA001").enforced("PRA001") if rule.rule_id in wanted
    ]
    native = {result.rule_id: result for result in evaluate_rules(filed.ret, filed.pack, rules)}
    return referee, native


def test_rules_that_call_a_registry_math_function_are_evaluated_not_lost(
    desk_run: tuple[RefereeResult, dict[str, RuleResult]],
) -> None:
    """Without Arelle's math plug-in neither compiles, and nothing in their session runs."""
    # Act
    referee, _native = desk_run

    # Assert
    assert referee.lost == ()
    assert referee.complete is True
    assert set(LOG_RULES) <= set(referee.rules)
    assert all(referee.rules[rule].status != VERDICT_NEVER_FIRED for rule in LOG_RULES)


def test_the_join_rules_match_a_desk_reported_in_both_tables(
    desk_run: tuple[RefereeResult, dict[str, RuleResult]],
) -> None:
    """Stock Arelle: unsatisfied, all twelve, whatever is reported. Repaired: each holds."""
    # Act
    referee, _native = desk_run
    counted = {rule: referee.rules[rule] for rule in JOIN_RULES}

    # Assert
    assert {(v.satisfied, v.unsatisfied) for v in counted.values()} == {(1, 0)}
    assert {v.status for v in counted.values()} == {VERDICT_PASS}


def test_the_native_engine_and_arelle_agree_on_every_one_of_them(
    desk_run: tuple[RefereeResult, dict[str, RuleResult]],
) -> None:
    # Act
    referee, native = desk_run
    differential = compare(native.values(), referee)

    # Assert
    assert differential.compared == len(JOIN_RULES) + len(LOG_RULES)
    assert differential.disagreements == ()
    assert differential.count_differences == ()
    assert differential.is_clean
