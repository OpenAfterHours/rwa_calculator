"""
The engine against Arelle on rounded figures and on an all-types OF 08.06 sheet.

Two readings the engine once took wrongly, each invisible on figures exact to
the unit and on returns with no all-types sheet — which is every return the
other oracles hold:

- A plain ``sum(...)`` or ``abs(...)`` in a rule is XPath's, and returns a number
  with no rounding allowance; only ``isum`` / ``iabs`` keep the allowances of the
  facts they read. Read alike, ``boe_b0770``, ``boe_b0794``, ``boe_b0820``-``b0823``,
  ``boe_b0829`` and SDDT ``boe_b1037_ss`` passed rounded figures the gateway
  fails.
- A fact with no member on OF 08.06's type-of-lending axis is on the all-types
  sheet (the dimension default), one place among the types. Given no place on
  the axis, its cells were read into every type's evaluation: ``boe_b0815`` and
  ``boe_b1042`` failed on each type sheet where Arelle passes every sheet. Two
  returns pin it, an all-types sheet with category rows and one with its total
  alone: the old reading gets different counts wrong on each.

These tests hold the engine to Arelle's counts, rule by rule, on the returns
``rounding_and_default_returns.py`` builds. They run in CI: the counts were
measured once with Arelle and are kept in
``tests/releases/4.1.1/oracles/rounding_and_default_oracle.json``, and the
returns are ours, so nothing here needs Arelle or the Bank's files.

Two adequacy assertions keep the returns honest (``.claude/LESSONS.md`` C11):
every rule each return exists for fires, and read the old way — plain functions
as their ``i``-prefixed twins, the all-types sheet as no place of its own —
every one of them is counted differently from Arelle.

References:
- Bank of England XBRL Filing Manual v1.0.1, rule 2.18 (interval arithmetic)
- XBRL Dimensions 1.0 — dimension defaults
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import TYPE_CHECKING, Any

import pytest

from rounding_and_default_returns import MODULES, PACKS, RULES, build_returns, oracle_path
from rwa_filer.boe.engine import evaluate_rules
from rwa_filer.taxonomy.pack import load_packaged
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

#: The rules each return exists for: on it, the old reading and Arelle's differ.
MISREAD: dict[str, frozenset[str]] = {
    "rounded": frozenset(
        {"boe_b0770", "boe_b0794", "boe_b0820", "boe_b0821", "boe_b0822", "boe_b0823", "boe_b0829"}
    ),
    "rounded_sddt": frozenset({"boe_b0794", "boe_b1037_ss"}),
    "all_types": frozenset({"boe_b0815", "boe_b1042", "boe_b0823", "boe_b0829"}),
    "all_types_total_only": frozenset({"boe_b0815", "boe_b1042", "boe_b0823", "boe_b0829"}),
}

#: The returns that file an all-types OF 08.06 sheet; the rest file rounded figures.
ALL_TYPES_RETURNS = frozenset({"all_types", "all_types_total_only"})

#: The open sheet axis whose default member is the all-types sheet.
ALL_TYPES_TABLE = "OF08.06.01.01"

#: A plain function, as the rule text writes it.
_PLAIN = re.compile(r"(?<![\w:])(sum|abs)\(")


@pytest.fixture(scope="module")
def oracle() -> dict[str, Any]:
    return json.loads(oracle_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def filed() -> dict[str, tuple[CanonicalReturn, TaxonomyPack, list[Rule], int]]:
    """Each return as filed — written and read back — with the rules it exists for."""
    out: dict[str, tuple[CanonicalReturn, TaxonomyPack, list[Rule], int]] = {}
    for name, ret in build_returns().items():
        module = MODULES[name]
        pack = load_packaged(PACKS[module])
        assert check_structure(ret, pack) == [], f"{name}: the return is not well formed"
        instance = write_instance(ret, pack)
        read = read_instance(instance.content, pack=pack)
        assert read.release.rulebook is not None
        rules = [
            rule
            for rule in read.release.rulebook.enforced(module)
            if re.search(RULES[name], rule.rule_id)
        ]
        out[name] = (read.ret, read.pack, rules, instance.facts)
    return out


def counts(ret: CanonicalReturn, pack: TaxonomyPack, rules: list[Rule]) -> dict[str, list[int]]:
    return {
        result.rule_id: [result.satisfied, result.unsatisfied]
        for result in evaluate_rules(ret, pack, rules)
    }


@pytest.mark.parametrize("name", sorted(MODULES))
def test_each_return_is_the_one_arelle_saw(
    name: str, oracle: dict[str, Any], filed: dict[str, Any]
) -> None:
    # Act
    facts = filed[name][3]

    # Assert
    measured = oracle["returns"][name]
    assert (measured["module"], facts) == (MODULES[name], measured["facts"])


@pytest.mark.parametrize("name", sorted(MODULES))
def test_every_rule_is_counted_as_arelle_counted_it(
    name: str, oracle: dict[str, Any], filed: dict[str, Any]
) -> None:
    """Satisfied and unsatisfied evaluations, exactly, for every rule Arelle ran."""
    # Arrange
    ret, pack, rules, _facts = filed[name]
    arelle = oracle["returns"][name]["rules"]

    # Act
    native = counts(ret, pack, rules)

    # Assert
    assert set(native) == set(arelle)
    differences = {
        rule: (arelle[rule], native[rule]) for rule in arelle if native[rule] != arelle[rule]
    }
    assert differences == {}, f"(Arelle, engine) differ on {len(differences)} rule(s)"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_every_misread_rule_is_measured_and_fires(name: str, oracle: dict[str, Any]) -> None:
    """A rule that never fires here proves nothing about how it is read."""
    # Act
    arelle = oracle["returns"][name]["rules"]
    silent = sorted(rule for rule in MISREAD[name] if sum(arelle.get(rule, [0, 0])) == 0)

    # Assert
    assert silent == []


@pytest.mark.parametrize("name", sorted(MODULES))
def test_read_the_old_way_every_misread_rule_is_counted_differently(
    name: str, oracle: dict[str, Any], filed: dict[str, Any]
) -> None:
    """The returns can see each defect: read the escaped way, each count is wrong.

    The escaped readings, reproduced: a plain ``sum`` / ``abs`` read as its
    ``i``-prefixed twin, and OF 08.06's axis read as having no all-types sheet
    — a fact with no member is then given no place on it, as every fact with
    no member was before.
    """
    # Arrange
    ret, pack, rules, _facts = filed[name]
    arelle = oracle["returns"][name]["rules"]
    if name in ALL_TYPES_RETURNS:
        pack = _without_default_sheet(pack, ALL_TYPES_TABLE)
    else:
        rules = [
            dataclasses.replace(rule, expression=_PLAIN.sub(r"i\1(", rule.expression))
            for rule in rules
        ]

    # Act
    native = counts(ret, pack, rules)

    # Assert
    agreeing = sorted(rule for rule in MISREAD[name] if native[rule] == arelle[rule])
    assert agreeing == [], "these returns cannot tell the two readings apart for them"


def _without_default_sheet(pack: TaxonomyPack, code: str) -> TaxonomyPack:
    """``pack`` with ``code``'s open sheet axis no longer accepting its default member."""
    table = pack.tables[code]
    axes = tuple(
        dataclasses.replace(axis, default_allowed=False) if axis is table.open_axis else axis
        for axis in table.z_axes
    )
    tables = {**pack.tables, code: dataclasses.replace(table, z_axes=axes)}
    return dataclasses.replace(pack, tables=tables)
