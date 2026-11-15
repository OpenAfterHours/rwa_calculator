"""
The packaged rule books: what ships, and how much of it the engine can run.

Two registers are held here, and both are two-way: a number may not get worse,
and an entry that no longer applies must be removed.

- ``UNREADABLE`` — rules this package cannot parse. Each is a rule it cannot
  check, so each is named, with the reason.
- ``UNSUPPORTED`` — enforced rules of a module whose taxonomy pack is packaged
  that the engine refuses. This is the never-evaluated register: a rule in it
  is one the Bank's gateway runs and this package does not.
- ``CLOSED_BY_FORMULA`` — enforced rules the taxonomy's OWN formula cannot fire
  on any cell the rule names, so neither the gateway nor the engine evaluates
  them. A rule in it is a rule nobody runs, by the publisher's doing.

A rule in a register is a known gap. A rule missing from one, that should be in
it, is a gap nobody knows about — which is the state these tests exist to make
impossible.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from pack_builders import VALID_LEI
from release_measurements import shipped_measurements
from rwa_filer.boe.catalogue import available_rulebooks, load_rulebook
from rwa_filer.boe.engine import REASON_UNKNOWN_TABLE, REASON_UNSUPPORTED, evaluate_rules
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.release import release_packs, release_rulebook, release_rulebooks
from rwa_filer.release_build import closing_dimensions
from rwa_filer.taxonomy.pack import available_packs, load_packaged

#: Each shipped release's measured numbers (``tests/releases/<version>/``):
#: rule counts, formula folders, unreadable rules and the closed-by-formula
#: register, re-measured by ``scripts/build_filer_release.py``, never typed.
MEASURED = shipped_measurements()
RELEASES = sorted(MEASURED)

#: (module, rule) the gateway runs and the engine refuses. Empty: for every
#: module with a packaged taxonomy pack, every enforced rule is evaluated.
UNSUPPORTED: dict[tuple[str, str], str] = {}


@pytest.mark.parametrize("version", RELEASES)
def test_every_family_of_the_publication_is_packaged(version: str) -> None:
    # Act
    counts = {
        name: {
            "rules": len(book.rules),
            "enforced": {module: len(book.enforced(module)) for module in sorted(book.modules)},
        }
        for name in release_rulebooks(version)
        for book in [load_rulebook(name)]
    }

    # Assert — every rule book the release was measured with, and no other.
    assert counts == {
        name: {"rules": book["rules"], "enforced": book["enforced"]}
        for name, book in MEASURED[version]["rulebooks"].items()
    }


@pytest.mark.parametrize("version", RELEASES)
def test_the_rules_this_package_cannot_read_are_exactly_the_measured_ones(version: str) -> None:
    """Each one a cell the publisher's export cut at the spreadsheet cell limit."""
    # Act
    unreadable = {
        (name, rule.rule_id): rule
        for name in release_rulebooks(version)
        for rule in load_rulebook(name).rules
        if rule.parse_error is not None
    }

    # Assert — two-way: nothing unmeasured, nothing measured that now parses; and
    # none is a rule the gateway runs.
    assert set(unreadable) == {
        (name, rule_id)
        for name, book in MEASURED[version]["rulebooks"].items()
        for rule_id in book["unreadable"]
    }
    for key, rule in unreadable.items():
        assert rule.truncated and "cut at the spreadsheet cell limit" in (rule.parse_error or ""), (
            key
        )
        assert not rule.in_xbrl, key


def test_no_rule_the_gateway_runs_is_unreadable() -> None:
    """Every enforced rule of every module, in all eleven families, parses."""
    # Act
    enforced_and_unreadable = [
        (name, module, rule.rule_id)
        for name in available_rulebooks()
        for book in [load_rulebook(name)]
        for module in book.modules
        for rule in book.enforced(module)
        if rule.parse_error is not None
    ]

    # Assert
    assert enforced_and_unreadable == []


@pytest.mark.parametrize("version", RELEASES)
def test_a_module_is_found_in_its_release_whatever_its_case_and_an_unknown_one_is_not(
    version: str,
) -> None:
    pra001 = release_rulebook(version, "pra001")
    lvr001 = release_rulebook(version, "LVR001")
    assert pra001 is not None and pra001.framework_version == "banking_reporting"
    assert lvr001 is not None and lvr001.framework_version == "leverage_ratio"
    assert release_rulebook(version, "XYZ999") is None
    assert release_rulebook("0.0.0", "PRA001") is None


def test_the_same_rule_code_names_different_rules_in_different_families() -> None:
    """Why a rule's identity is its framework version AND its code."""
    # Act — a code two families of one release both use, for different rules.
    shared = [(version, code) for version in RELEASES for code in _codes_in_two_families(version)]

    # Assert
    assert shared, "no rule code is shared between families: identity by code alone would do"


def test_every_enforced_rule_of_a_packaged_module_is_supported_by_the_engine() -> None:
    """The never-evaluated register, for each module whose taxonomy pack ships.

    The return declares every template reported and holds no facts, so no rule
    is blocked and none has data: what is left is each rule's own readiness —
    its tables are in the pack, its filters fit its tables, and it calls only
    functions the engine implements.
    """
    # Arrange
    refused: dict[tuple[str, str], str] = {}
    for info in available_packs():
        pack = load_packaged(info.key)
        rules = _rulebook(info.version, info.module).enforced(info.module)
        header = ReturnHeader(VALID_LEI, max(info.valid_from, date(2027, 3, 31)), info.module)
        empty = CanonicalReturn(
            header, pl.DataFrame(schema=FACT_SCHEMA), dict.fromkeys(pack.filing_indicators, True)
        )

        # Act
        for result in evaluate_rules(empty, pack, rules):
            if result.reason in (REASON_UNSUPPORTED, REASON_UNKNOWN_TABLE):
                refused[(info.module, result.rule_id)] = f"{result.reason}: {result.detail}"

    # Assert — two-way against the register.
    assert refused.keys() == UNSUPPORTED.keys(), (
        f"unregistered: {sorted(refused.keys() - UNSUPPORTED.keys())[:10]}; "
        f"stale: {sorted(UNSUPPORTED.keys() - refused.keys())[:10]}"
    )


@pytest.mark.parametrize("version", RELEASES)
def test_every_packaged_rule_book_records_what_its_formulas_close(version: str) -> None:
    """Built with the taxonomy package, each from its own framework's folder."""
    # Act
    folders = {
        name: load_rulebook(name).source.get("formulas", {}).get("folder")
        for name in release_rulebooks(version)
    }
    without = [
        (name, rule.rule_id)
        for name in release_rulebooks(version)
        for rule in load_rulebook(name).rules
        if rule.in_xbrl and not rule.closed and not rule.closed_by_variable
    ]

    # Assert — nearly every formula closes something; a rule book where none
    # does was built without the package.
    assert all(folders.values()), f"rule books built without the taxonomy package: {folders}"
    assert folders == {
        name: book["formula_folder"] for name, book in MEASURED[version]["rulebooks"].items()
    }
    assert len(without) < 100, f"{len(without)} XBRL rules record no closed dimension"


@pytest.mark.parametrize("version", RELEASES)
def test_the_rules_their_own_formulas_cannot_fire_are_exactly_the_measured_ones(
    version: str,
) -> None:
    """For each module whose pack ships: which enforced rules nobody can run.

    A rule joins this register when a new taxonomy closes a dimension its
    table reports on, and leaves it when the publisher repairs the formula.
    Either is a change in what a return is checked against, and must be seen.
    """
    # Act
    found: dict[str, str] = {}
    for info in release_packs(version):
        pack = load_packaged(info.key)
        for rule in _rulebook(info.version, info.module).enforced(info.module):
            if rule.parse_error is not None or not (rule.closed or rule.closed_by_variable):
                continue
            shut = closing_dimensions(pack, rule)
            if shut is not None:
                found[f"{info.module}/{rule.rule_id}"] = ", ".join(sorted(shut))

    # Assert — two-way against the measured register.
    assert found == MEASURED[version]["closed_by_formula"]


def _rulebook(version: str, module: str):  # noqa: ANN202 - a test helper
    """The rule book of ``module`` in release ``version``; every packaged pack has one."""
    rulebook = release_rulebook(version, module)
    assert rulebook is not None, f"no rule book for {module} in {version}"
    return rulebook


def _codes_in_two_families(version: str) -> list[str]:
    """Rule codes two rule books of ``version`` both use, for different expressions."""
    expressions: dict[str, set[str]] = {}
    for name in release_rulebooks(version):
        for rule in load_rulebook(name).rules:
            expressions.setdefault(rule.rule_id, set()).add(rule.expression)
    return sorted(code for code, seen in expressions.items() if len(seen) > 1)
