"""Contract tests: the Basel 3.1 sovereign-class SA gate is keyed on entity type alone.

PS1/26 Art. 147A(1)(a) puts the whole Art. 147(2)(a) class ("central
governments, central banks or quasi-sovereigns") on the Standardised Approach,
and PS1/26 Art. 147(3)(a)-(f) assigns central governments, central banks,
regional governments, local authorities, public sector entities and MDBs to
that class without condition. Nothing in either paragraph turns on the
currency an exposure is denominated or funded in.

The classifier implements this in one place: ``_apply_b31_approach_restrictions``
strips A-IRB and F-IRB from every ``cp_entity_type`` in
``B31_SOVEREIGN_LIKE_ENTITY_TYPES``. P1.357 deleted a second, currency-keyed gate
(``is_eu_domestic_sovereign``) that was dead in both regimes. These contracts
pin the two facts that made it dead and that keep the deletion safe:

1. ``engine/classify/approach.py`` does not route on denomination currency or
   counterparty country. The domestic-currency treatment of CRR Art. 114(4)/(7)
   is an SA risk weight (``engine/sa/risk_weights.py``), never an approach gate;
   a currency- or funding-keyed limb re-attached here would attach a condition
   Art. 147A(1)(a) does not have (and, ungated, would force SA under CRR, where
   Art. 150(1) permanent partial use - including its UK- and Art. 114(4)-scoped
   (d) limb - is an election resolved from ``model_permissions`` in
   ``engine/classify/permissions.py``, never in the approach ladder).
2. Every entity type the rulepack maps to an Art. 147(3)(a)-(f) SA class is in
   ``B31_SOVEREIGN_LIKE_ENTITY_TYPES``. If a new entity type mapped to one of
   those classes were left out, its rows would reach IRB under Basel 3.1 with
   nothing else to stop them.

Files are located through the imported ``rwa_calc`` package, so these tests
measure whichever source tree is on ``sys.path``.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

import rwa_calc.engine.classify.approach as approach_module
from rwa_calc.data.schemas import B31_SOVEREIGN_LIKE_ENTITY_TYPES
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.entity_class_maps import entity_type_to_sa_class
from rwa_calc.rulebook.resolve import resolve

_APPROACH_PATH = Path(approach_module.__file__).resolve()

# The module that holds the domestic-currency / funding-currency predicates of
# CRR Art. 114(4)/(7) and Art. 115(5)/(2). Its consumers are SA risk-weight,
# CRM and guarantee code — never approach routing.
_CURRENCY_PREDICATE_MODULE = "rwa_calc.engine.eu_sovereign"

# Column names that carry an exposure's currency or its counterparty's country.
_CURRENCY_AND_COUNTRY_COLUMNS: frozenset[str] = frozenset(
    {"currency", "original_currency", "funding_currency", "cp_country_code"}
)

# PS1/26 Art. 147(3)(a)-(f): the SA classes whose entity types join the
# Art. 147(2)(a) class unconditionally. Art. 147(3)(g) international
# organisations are excluded — only 0%-weighted ones join, so it is conditional.
_ART_147_3_A_TO_F_SA_CLASSES: tuple[str, ...] = (
    ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    ExposureClass.RGLA.value,
    ExposureClass.PSE.value,
    ExposureClass.MDB.value,
)


def test_approach_module_does_not_route_on_currency_or_country() -> None:
    """approach.py imports no currency predicate and reads no currency / country column.

    Arrange: parse engine/classify/approach.py.
    Act:     collect its ``from ... import`` modules and its string constants.
    Assert:  nothing is imported from ``rwa_calc.engine.eu_sovereign``, and no
             string constant names a currency or country column.

    Pre-P1.357 failure: the ``is_eu_domestic_sovereign`` branch imported
    ``build_eu_domestic_currency_expr`` / ``denomination_currency_expr`` and
    read ``cp_country_code``.
    """
    # Arrange
    tree = ast.parse(_APPROACH_PATH.read_text(encoding="utf-8"))

    # Act
    imported_from = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    string_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    # Assert
    assert _CURRENCY_PREDICATE_MODULE not in imported_from, (
        f"{_APPROACH_PATH}: imports from {_CURRENCY_PREDICATE_MODULE}. PS1/26 Art. "
        "147A(1)(a) routes the sovereign class to SA by entity type alone; the "
        "Art. 114(4)/(7) currency limbs are SA risk-weight rules, not approach gates."
    )
    read_columns = sorted(string_constants & _CURRENCY_AND_COUNTRY_COLUMNS)
    assert not read_columns, (
        f"{_APPROACH_PATH}: names currency / country column(s) {read_columns}. "
        "PS1/26 Art. 147A(1)(a) has no currency/country limb; CRR Art. 114(4)/(7) are "
        "SA risk weights; a CRR Art. 150(1) PPU election (whose (d) limb is UK- and "
        "Art. 114(4)-scoped) is resolved from model_permissions in permissions.py, "
        "never in this ladder."
    )


@pytest.mark.parametrize("sa_class", _ART_147_3_A_TO_F_SA_CLASSES)
@pytest.mark.parametrize("regime", ["b31", "crr"])
def test_every_art_147_3_entity_type_is_in_the_b31_sa_only_set(regime: str, sa_class: str) -> None:
    """Each entity type mapped to an Art. 147(3)(a)-(f) SA class is SA-only under Basel 3.1.

    Arrange: the regime's resolved ``entity_type_to_sa_class`` map (both regimes,
             because the map is a common-pack entry either regime may override).
    Act:     select the entity types mapped to ``sa_class``.
    Assert:  the selection is non-empty, and every member is in
             ``B31_SOVEREIGN_LIKE_ENTITY_TYPES``.
    """
    # Arrange
    sa_map = entity_type_to_sa_class(resolve(regime, date(2027, 6, 30)))

    # Act
    mapped = {entity_type for entity_type, cls in sa_map.items() if cls == sa_class}

    # Assert
    assert mapped, f"no entity type maps to {sa_class!r} - this contract checks nothing"
    outside = sorted(mapped - set(B31_SOVEREIGN_LIKE_ENTITY_TYPES))
    assert not outside, (
        f"entity type(s) {outside} map to the SA class {sa_class!r}, which PS1/26 "
        "Art. 147(3) assigns to the Art. 147(2)(a) class, but are missing from "
        "B31_SOVEREIGN_LIKE_ENTITY_TYPES - under Basel 3.1 their rows would reach "
        "IRB despite Art. 147A(1)(a)."
    )
