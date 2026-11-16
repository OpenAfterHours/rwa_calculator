"""
The engine against Arelle on returns that tell a summed reference's two readings apart.

What a sum in a published rule adds up — every row or member of an open
dimension, or only the one the rest of the rule is read at — is decided by the
rule's XBRL formula, which covers the dimension on the summed variable or
leaves it uncovered. The text does not say. Read from the text alone, the engine
misread 28 rules: it summed every obligor grade in ``boe_b0760``-``b0763`` and
failed each grade of every OF 08.02 sheet with more than one, which Arelle
passes (escape log, 2026-11-16).

These tests hold the engine to Arelle's counts, rule by rule, on the returns
``summed_returns.py`` builds to make the two readings disagree. They run in CI:
the counts were measured once with Arelle and are kept in
``tests/releases/4.1.1/oracles/summed_references_oracle.json``, and the returns
are ours, so nothing here needs Arelle or the Bank's files. (The opt-in
``test_sample_oracle.py`` could not see the defect: the Bank's sample has one
open row per open-row table and no member on OF 08.06's open axis.)

Two adequacy assertions keep the returns honest (``.claude/LESSONS.md`` C11):
every misread rule is in the oracle and fires, and, read from the text alone,
every one of them is counted differently from Arelle — the returns can see it.

References:
- packages/rwa-filer/src/rwa_filer/boe/formulas.py — what a summed variable spans
- XBRL Variables 1.0 — bind as sequence, covered aspects, implicit filtering
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import TYPE_CHECKING, Any

import pytest

from rwa_filer.boe.engine import evaluate_rules
from rwa_filer.taxonomy.pack import load_packaged
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance
from summed_returns import PACKS, RULES, build_returns, oracle_path

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

#: Every rule the text alone misread, by module: the scan of every packaged rule
#: book with a taxonomy pack against the formulas of the v4.1.1 package. The
#: first four, and C 14, SC 14, C/SC 06.02 and MREL, summed every row where the
#: formula sums one; OF 08.06's read one type of lending at a time where the
#: formula sums them all.
MISREAD: dict[str, frozenset[str]] = {
    "PRA001": frozenset(
        {
            "boe_b0760",
            "boe_b0761",
            "boe_b0762",
            "boe_b0763",
            *(f"boe_b08{n}" for n in range(16, 23)),
            "boe_b1043",
            *(f"v737{n}_m" for n in range(2, 8)),
            "v11871_m",
        }
    ),
    "PRA116": frozenset({*(f"boe_b0{n}_ss" for n in range(117, 123)), "v11871_m"}),
    "MRL003": frozenset({"boe_b4101", "boe_b4102"}),
}


@pytest.fixture(scope="module")
def oracle() -> dict[str, Any]:
    return json.loads(oracle_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def filed() -> dict[str, tuple[CanonicalReturn, TaxonomyPack, list[Rule], int]]:
    """Each return as filed — written and read back — with the rules it exists for."""
    out: dict[str, tuple[CanonicalReturn, TaxonomyPack, list[Rule], int]] = {}
    for module, ret in build_returns().items():
        pack = load_packaged(PACKS[module])
        assert check_structure(ret, pack) == [], f"{module}: the return is not well formed"
        instance = write_instance(ret, pack)
        read = read_instance(instance.content, pack=pack)
        assert read.release.rulebook is not None
        rules = [
            rule
            for rule in read.release.rulebook.enforced(module)
            if re.search(RULES[module], rule.rule_id)
        ]
        out[module] = (read.ret, read.pack, rules, instance.facts)
    return out


def counts(ret: CanonicalReturn, pack: TaxonomyPack, rules: list[Rule]) -> dict[str, list[int]]:
    return {
        result.rule_id: [result.satisfied, result.unsatisfied]
        for result in evaluate_rules(ret, pack, rules)
    }


@pytest.mark.parametrize("module", sorted(PACKS))
def test_each_return_is_the_one_arelle_saw(
    module: str, oracle: dict[str, Any], filed: dict[str, Any]
) -> None:
    # Act
    facts = filed[module][3]

    # Assert
    assert facts == oracle["returns"][module]["facts"], "the return is not the one Arelle saw"


@pytest.mark.parametrize("module", sorted(PACKS))
def test_every_rule_is_counted_as_arelle_counted_it(
    module: str, oracle: dict[str, Any], filed: dict[str, Any]
) -> None:
    """Satisfied and unsatisfied evaluations, exactly, for every rule Arelle ran."""
    # Arrange
    ret, pack, rules, _facts = filed[module]
    arelle = oracle["returns"][module]["rules"]

    # Act
    native = counts(ret, pack, rules)

    # Assert
    assert set(native) == set(arelle)
    differences = {
        rule: (arelle[rule], native[rule]) for rule in arelle if native[rule] != arelle[rule]
    }
    assert differences == {}, f"(Arelle, engine) differ on {len(differences)} rule(s)"


@pytest.mark.parametrize("module", sorted(PACKS))
def test_every_misread_rule_is_measured_and_fires(module: str, oracle: dict[str, Any]) -> None:
    """A rule that never fires here proves nothing about how its sum is read."""
    # Act
    arelle = oracle["returns"][module]["rules"]
    silent = sorted(rule for rule in MISREAD[module] if sum(arelle.get(rule, [0, 0])) == 0)

    # Assert
    assert silent == []


@pytest.mark.parametrize("module", sorted(PACKS))
def test_read_from_the_text_alone_every_misread_rule_is_counted_differently(
    module: str, oracle: dict[str, Any], filed: dict[str, Any]
) -> None:
    """The returns can see the defect: without the formula's word, each count is wrong.

    This is the escaped reading, reproduced: a rule book without ``spans`` is
    read from the text alone, as every rule book was before 2026-11-16.
    """
    # Arrange
    ret, pack, rules, _facts = filed[module]
    text_only = [dataclasses.replace(rule, spans_by_variable={}) for rule in rules]
    arelle = oracle["returns"][module]["rules"]

    # Act
    native = counts(ret, pack, text_only)

    # Assert
    agreeing = sorted(rule for rule in MISREAD[module] if native[rule] == arelle[rule])
    assert agreeing == [], "these returns cannot tell the two readings apart for them"
