"""
The sheets C 07.00 / OF 07.00 row 0015 is declared on, against the published rules.

Row 0015, "of which: Defaulted exposures", is reported only in the exposure
classes that keep a defaulted exposure rather than moving it to the "exposures
in default" class (CRR COREP Annex II p.91: high risk and equity; PS1/26 Annex
II p.88: high risk, equity and CIUs). ``templates.get_c07_defaulted_row_sheet_keys``
declares those classes as our sheet keys, and ``corep/c07.py`` scopes the row
to them.

The taxonomy cannot anchor that declaration: it publishes row 0015 on all
sixteen OF 07.00 sheets, the "in default" sheet included. The restriction lives
in the instructions and in the rules that enforce them, so this file holds the
declaration to the rules' own sheet lists, read from the packaged extracts and
mapped onto our sheet keys through ``SHEET_INDEX_MAPS`` — never to a list typed
from the same sentence as the declaration (``.claude/LESSONS.md`` B3):

- Basel 3.1: ``boe_b0431`` (OF 07.00.01.01) and ``boe_b1069`` (OF 07.00.01.02)
  are ``isNull`` over row 0015 on a ``z:`` list of the sheets that must leave it
  blank; ``boe_b0536`` (``r0015 <= r0010``) lists the sheets that may carry it.
- CRR: ``v4721_m`` (``{r0015} = empty``) and ``v4722_m`` (``{r0015} = 0``) list
  the must-be-blank sheets; ``v4728_m`` (``{r0015} <= {r0010}``) the others.

Each regime is stated three ways, so a later rule release that moves a sheet
fails here rather than silently disagreeing with the declaration.

References:
- CRR COREP Annex II C 07.00 row 0015 (p.91); PRA PS1/26 Annex II OF 07.00
  row 0015 (p.88)
- EBA validation rules v3.0 (v4721_m, v4722_m, v4728_m); Bank of England
  banking_reporting rule workbook v4.1.1 (boe_b0431, boe_b1069, boe_b0536)
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from rwa_calc.reporting.corep.templates import (
    C07_00_TOTAL_SHEET_KEY,
    get_c07_defaulted_row_sheet_keys,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.rules.catalogue import SCOPE_LIST, ValidationRule, load_rules

#: framework -> (sheet map name, the rules that BLANK row 0015 on their sheets,
#: the rule that ALLOWS it on its sheets).
_REGIMES: Final[dict[str, tuple[str, tuple[str, ...], str]]] = {
    "CRR": ("c07", ("v4721_m", "v4722_m"), "v4728_m"),
    "BASEL_3_1": ("of07", ("boe_b0431", "boe_b1069"), "boe_b0536"),
}
_TOTAL_SHEET_CODE: Final = "0001"

# The ``z:`` argument of a BoE ``isNull`` reference, e.g. ``z: 0002; 0003``.
_Z_LIST: Final = re.compile(r"\bz:\s*([0-9;\s]+)")


@pytest.mark.parametrize("framework", sorted(_REGIMES))
@pytest.mark.parametrize("blank_rule_index", [0, 1])
def test_declared_sheets_are_the_ones_the_must_be_blank_rule_leaves_out(
    framework: str, blank_rule_index: int
) -> None:
    # Arrange
    map_name, blank_rules, _allow_rule = _REGIMES[framework]
    rule = _rule(framework, blank_rules[blank_rule_index])
    codes = set(SHEET_INDEX_MAPS[map_name]) - {_TOTAL_SHEET_CODE}

    # Act
    allowed_codes = codes - _blank_sheet_codes(rule)

    # Assert
    assert get_c07_defaulted_row_sheet_keys(framework) == _sheet_keys(map_name, allowed_codes)


@pytest.mark.parametrize("framework", sorted(_REGIMES))
def test_declared_sheets_are_the_ones_the_upper_bound_rule_lists(framework: str) -> None:
    # Arrange
    map_name, _blank_rules, allow_rule = _REGIMES[framework]
    rule = _rule(framework, allow_rule)
    (scope,) = rule.table_scopes
    assert scope.sheets.kind == SCOPE_LIST, f"{allow_rule} no longer lists its sheets"

    # Act
    allowed_codes = set(scope.sheets.ids) - {_TOTAL_SHEET_CODE}

    # Assert - the Total is on the list too: it is the sum of the class sheets
    assert _TOTAL_SHEET_CODE in scope.sheets.ids
    assert get_c07_defaulted_row_sheet_keys(framework) == _sheet_keys(map_name, allowed_codes)


def test_the_declaration_never_names_the_total_or_the_default_class() -> None:
    # Act
    declared = {fw: get_c07_defaulted_row_sheet_keys(fw) for fw in _REGIMES}

    # Assert - the regimes differ by the CIU class alone (PS1/26 adds it)
    for keys in declared.values():
        assert C07_00_TOTAL_SHEET_KEY not in keys
        assert "defaulted" not in keys
    assert declared["BASEL_3_1"] - declared["CRR"] == {"ciu"}
    assert declared["CRR"] <= declared["BASEL_3_1"]


def _rule(framework: str, rule_id: str) -> ValidationRule:
    found = [rule for rule in load_rules(framework).rules if rule.rule_id == rule_id]
    assert len(found) == 1, f"{rule_id} is not in the packaged {framework} extract"
    return found[0]


def _blank_sheet_codes(rule: ValidationRule) -> set[str]:
    """The sheets a must-be-blank rule addresses: its table scope, or its ``z:`` list."""
    scoped = [scope.sheets.ids for scope in rule.table_scopes if scope.sheets.kind == SCOPE_LIST]
    if scoped:
        (ids,) = scoped
        return set(ids)
    matches = _Z_LIST.findall(rule.expression or "")
    assert len(matches) == 1, f"{rule.rule_id}: expected one z: list in {rule.expression!r}"
    return {code.strip() for code in matches[0].split(";") if code.strip()}


def _sheet_keys(map_name: str, codes: set[str]) -> frozenset[str]:
    entries = SHEET_INDEX_MAPS[map_name]
    return frozenset(key for code in codes for key in entries[code].bundle_keys)
