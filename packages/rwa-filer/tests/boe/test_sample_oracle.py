"""
The engine against Arelle, rule by rule, on the Bank of England's own sample.

Opt-in, never in CI: the sample instance is the Bank's file and is not
redistributed. SKIPPED unless ``RWA_FILER_BOE_DIR`` names a directory holding
it (``*_PRA001_*.xbrl``, searched recursively):

    RWA_FILER_BOE_DIR=/path/to/downloads \
        uv run pytest packages/rwa-filer/tests/boe/test_sample_oracle.py -q

Why this is the test that matters. Every other engine test pins a behaviour
this project chose. This one pins a behaviour it did not choose: the committed
oracle is what Arelle — an independent XBRL processor executing the Bank's own
formula linkbases — counted, rule by rule, as satisfied and unsatisfied
evaluations on a carve of the Bank's sample. The engine reads the workbook
text of the same rules and must arrive at the same counts. A wrong idea about
iteration, defaults, rounding allowances or preconditions shows up here as a
number that is off, on a named rule.

The carve is rebuilt from the Bank's file by ``sample_carve.thin_carve``, and
is written and read back through this package's own XBRL writer and reader, so
the engine sees what a filed instance would give it.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from rwa_filer.boe.catalogue import rulebook_for_module
from rwa_filer.boe.engine import REASON_NOT_REPORTED, RuleResult, evaluate_rules
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance
from sample_carve import CREDIT_INDICATORS, thin_carve

BOE_DIR = os.environ.get("RWA_FILER_BOE_DIR")
ORACLE_PATH = Path(__file__).parent / "data" / "pra001_sample_credit_oracle.json"

pytestmark = pytest.mark.skipif(
    not BOE_DIR, reason="set RWA_FILER_BOE_DIR to a directory holding the BoE PRA001 sample"
)


@pytest.fixture(scope="module")
def oracle() -> dict[str, Any]:
    return json.loads(ORACLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def results(oracle: dict[str, Any]) -> dict[str, RuleResult]:
    found = sorted(Path(BOE_DIR or "").rglob("*_PRA001_*.xbrl"))
    if not found:
        pytest.skip("no *_PRA001_*.xbrl sample instance under RWA_FILER_BOE_DIR")
    sample = read_instance(found[0])
    carved = thin_carve(
        sample,
        CREDIT_INDICATORS,
        sheets_per_table=oracle["carve"]["sheets_per_table"],
        open_rows_per_sheet=oracle["carve"]["open_rows_per_sheet"],
    )
    assert check_structure(carved, sample.pack) == []
    instance = write_instance(carved, sample.pack)
    assert instance.facts == oracle["carve"]["facts"], "the carve is not the one Arelle saw"
    filed = read_instance(instance.content, pack=sample.pack)
    rules = rulebook_for_module("PRA001").enforced("PRA001")
    return {result.rule_id: result for result in evaluate_rules(filed.ret, filed.pack, rules)}


def test_every_rule_arelle_ran_is_counted_the_same(
    oracle: dict[str, Any], results: dict[str, RuleResult]
) -> None:
    """Satisfied and unsatisfied evaluations, exactly, for each of the 456 rules."""
    # Act
    differences = {
        rule_id: (tuple(expected), (results[rule_id].satisfied, results[rule_id].unsatisfied))
        for rule_id, expected in oracle["rules"].items()
        if rule_id not in results
        or (results[rule_id].satisfied, results[rule_id].unsatisfied) != tuple(expected)
    }

    # Assert
    assert len(oracle["rules"]) == 456
    assert differences == {}, f"{len(differences)} rule(s) are counted differently from Arelle"


def test_the_verdicts_split_as_arelles_do(
    oracle: dict[str, Any], results: dict[str, RuleResult]
) -> None:
    """243 fail, 125 hold, 88 never fire — and nothing is unsupported."""

    def verdict(satisfied: int, unsatisfied: int) -> str:
        return "FAIL" if unsatisfied else ("PASS" if satisfied else "NEVER_FIRED")

    # Act
    arelle = Counter(verdict(*counts) for counts in oracle["rules"].values())
    native = Counter(
        verdict(results[rule_id].satisfied, results[rule_id].unsatisfied)
        for rule_id in oracle["rules"]
    )

    # Assert
    assert native == arelle == Counter({"FAIL": 243, "PASS": 125, "NEVER_FIRED": 88})


def test_the_engine_blocks_exactly_the_rules_arelle_did_not_run(
    oracle: dict[str, Any], results: dict[str, RuleResult]
) -> None:
    """A rule whose templates are not all reported is not run — by either engine."""
    # Act
    blocked = {
        rule_id for rule_id, result in results.items() if result.reason == REASON_NOT_REPORTED
    }

    # Assert — the two sets partition the 1,441 enforced rules.
    assert len(results) == 1441
    assert len(blocked) == oracle["rules_skipped_precondition_false"] == 985
    assert blocked == set(results) - set(oracle["rules"])


# ---------------------------------------------------------------------------
# Twelve further modules, each on its whole sample
# ---------------------------------------------------------------------------

MODULES_ORACLE_PATH = Path(__file__).parent / "data" / "module_sample_oracles.json"


def test_every_rule_of_twelve_further_modules_is_counted_as_arelle_counts_it() -> None:
    """Leverage, MREL, Capital+ and financial statements: 254 rules, exact counts.

    No carve: these modules are small enough for Arelle to evaluate the Bank's
    whole sample. Between them they exercise what the credit-risk templates do
    not — three-digit row codes, date comparisons, pattern matches on text
    cells, and tables that show one data point in two cells.
    """
    # Arrange
    oracle = json.loads(MODULES_ORACLE_PATH.read_text(encoding="utf-8"))["modules"]
    differences: dict[str, object] = {}
    compared = 0

    for module, expected in oracle.items():
        found = sorted(Path(BOE_DIR or "").rglob(f"*_{module.replace('_', '')}_*.xbrl"))
        if not found:
            continue
        # Act
        sample = read_instance(found[0])
        rules = rulebook_for_module(module).enforced(module)
        native = {
            result.rule_id: (result.satisfied, result.unsatisfied)
            for result in evaluate_rules(sample.ret, sample.pack, rules)
        }
        compared += 1
        if set(native) != set(expected["rules"]):
            differences[module] = "the engine and Arelle ran different rules"
            continue
        wrong = {
            rule_id: (tuple(counts), native[rule_id])
            for rule_id, counts in expected["rules"].items()
            if native[rule_id] != tuple(counts)
        }
        if wrong:
            differences[module] = wrong

    # Assert
    if compared == 0:
        pytest.skip("none of the twelve modules' sample instances is under RWA_FILER_BOE_DIR")
    assert differences == {}
    assert compared == len(oracle) == 12
    assert sum(len(expected["rules"]) for expected in oracle.values()) == 254
