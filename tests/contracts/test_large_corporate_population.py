"""Contract tests: the Basel 3.1 large-corporate test reads the pack's corporate population.

PS1/26 Art. 147(4C)(b)(ii) assigns "'large' corporates with annual revenue of more
than GBP 440 million" to the financial-and-large subclass, which Art. 147A(1)(e)(ii)
restricts to Foundation IRB. The classifier reads that population from ONE
hand-written tuple, ``LARGE_CORPORATE_TEST_ENTITY_TYPES`` (``data/schemas.py``),
through ONE predicate, ``engine/classify/attributes.py::large_corporate_test_entity_expr``.

P1.321 was exactly a hand-written population drifting from the class map: the test
keyed on the literal ``"corporate"`` while the pack sent ``company`` to the corporate
class too, so a GBP 600m ``company`` kept A-IRB with its own LGD. These contracts pin
the tuple to the rulepack's entity-type class maps — the source of truth that cannot
drift with the code under test (``.claude/LESSONS.md`` B2/B3) — so the next alias the
pack adds to the corporate class fails here instead of escaping the restriction:

1. Every entity type the SA class map sends to CORPORATE is in the tuple, except
   ``specialised_lending``. That one exception is deliberate and recorded: a row with
   a specialised-lending record is outside the subclass by Art. 147(4C)(a) whatever
   its obligor's type, and how to route a ``specialised_lending``-typed obligor with
   NO record is an open owner decision (``tests/conformance/classification_table.toml``
   register entry D2). When that decision is taken, this exception is revisited with
   it — never silently.
2. The IRB class map, which sends ``specialised_lending`` to its own class, sends
   exactly the tuple's members to CORPORATE.
3. Both readers (the approach restriction and the CLS008 / CLS011 / CLS015 counts)
   go through the shared predicate and hold no entity-type literal of their own.

Both regimes are checked because the class maps are common-pack entries either
regime may override. Files are located through the imported ``rwa_calc`` package,
so these tests measure whichever source tree is on ``sys.path``.

References:
- PRA PS1/26 Art. 147(4C)(a)-(b)(ii), Art. 147A(1)(e)(ii)
- tests/contracts/test_sovereign_approach_gate.py — the same pin for
  ``B31_SOVEREIGN_LIKE_ENTITY_TYPES``
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

import rwa_calc.engine.classify.approach as approach_module
import rwa_calc.engine.classify.audit as audit_module
from rwa_calc.data.schemas import LARGE_CORPORATE_TEST_ENTITY_TYPES
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.entity_class_maps import entity_type_to_irb_class, entity_type_to_sa_class
from rwa_calc.rulebook.resolve import resolve

#: The one corporate-class entity type deliberately left out of the revenue test:
#: Art. 147(4C)(a) excludes the specialised-lending subclass, and routing a
#: ``specialised_lending``-typed obligor with no SL record is the open owner
#: decision recorded as classification_table.toml register entry D2.
_EXCLUDED_PENDING_OWNER_DECISION: frozenset[str] = frozenset({"specialised_lending"})

#: The predicate both readers must call.
_SHARED_PREDICATE = "large_corporate_test_entity_expr"

_READERS: tuple[ModuleType, ...] = (approach_module, audit_module)

_REGIMES: tuple[str, ...] = ("crr", "b31")


@pytest.mark.parametrize("regime", _REGIMES)
def test_every_sa_corporate_entity_type_but_specialised_lending_is_in_the_test(
    regime: str,
) -> None:
    """The tuple is the SA map's corporate entity types less the recorded exception.

    Arrange: the regime's resolved ``entity_type_to_sa_class`` map.
    Act:     select the entity types mapped to CORPORATE, less ``specialised_lending``.
    Assert:  the selection equals ``LARGE_CORPORATE_TEST_ENTITY_TYPES`` exactly.

    Pre-P1.321 shape: the test read only ``"corporate"``, so ``company`` would be
    reported as missing.
    """
    # Arrange
    sa_map = entity_type_to_sa_class(resolve(regime, date(2027, 6, 30)))

    # Act
    mapped = {
        entity_type
        for entity_type, sa_class in sa_map.items()
        if sa_class == ExposureClass.CORPORATE.value
    }

    # Assert
    assert mapped >= _EXCLUDED_PENDING_OWNER_DECISION, (
        "specialised_lending no longer maps to the SA corporate class: the recorded "
        "exception (register entry D2) is stale - revisit it with its owner decision"
    )
    expected = mapped - _EXCLUDED_PENDING_OWNER_DECISION
    assert set(LARGE_CORPORATE_TEST_ENTITY_TYPES) == expected, (
        f"LARGE_CORPORATE_TEST_ENTITY_TYPES is {sorted(LARGE_CORPORATE_TEST_ENTITY_TYPES)} "
        f"but the {regime} pack maps {sorted(expected)} (less specialised_lending) to the "
        "corporate class. A corporate-class entity type outside the tuple escapes the "
        "PS1/26 Art. 147(4C)(b)(ii) revenue test and keeps A-IRB where Art. 147A(1)(e)(ii) "
        "allows F-IRB only; one inside it that the pack does not class as corporate is "
        "restricted with no rule behind it."
    )


@pytest.mark.parametrize("regime", _REGIMES)
def test_the_irb_corporate_entity_types_are_exactly_the_test(regime: str) -> None:
    """The IRB map's corporate entity types are the tuple, with no exception needed.

    Arrange: the regime's resolved ``entity_type_to_irb_class`` map.
    Act:     select the entity types mapped to CORPORATE.
    Assert:  the selection equals ``LARGE_CORPORATE_TEST_ENTITY_TYPES`` exactly.
    """
    # Arrange
    irb_map = entity_type_to_irb_class(resolve(regime, date(2027, 6, 30)))

    # Act
    mapped = {
        entity_type
        for entity_type, irb_class in irb_map.items()
        if irb_class == ExposureClass.CORPORATE.value
    }

    # Assert
    assert set(LARGE_CORPORATE_TEST_ENTITY_TYPES) == mapped, (
        f"the {regime} IRB class map sends {sorted(mapped)} to the corporate class but "
        f"the large-corporate test reads {sorted(LARGE_CORPORATE_TEST_ENTITY_TYPES)}"
    )


@pytest.mark.parametrize("module", _READERS, ids=lambda module: module.__name__.rsplit(".")[-1])
def test_each_reader_uses_the_shared_predicate_and_no_entity_type_literal(
    module: ModuleType,
) -> None:
    """Both readers call the shared predicate and spell no member of the tuple.

    Arrange: parse the reader module.
    Act:     collect the names it calls and its string constants.
    Assert:  it calls ``large_corporate_test_entity_expr``, and no string constant is a
             member of ``LARGE_CORPORATE_TEST_ENTITY_TYPES``.

    Pre-P1.321 failure: both modules compared ``entity_type`` to the literal
    ``"corporate"`` and called no shared predicate.
    """
    # Arrange
    path = Path(str(module.__file__)).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # Act
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    # Assert
    assert _SHARED_PREDICATE in called, (
        f"{path}: does not call {_SHARED_PREDICATE} - its large-corporate population "
        "can drift from the other reader's"
    )
    spelled = sorted(literals & set(LARGE_CORPORATE_TEST_ENTITY_TYPES))
    assert not spelled, (
        f"{path}: spells entity type literal(s) {spelled}. Read the population through "
        f"{_SHARED_PREDICATE}, so the approach restriction and its warnings cannot disagree."
    )
