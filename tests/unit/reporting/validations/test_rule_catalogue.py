"""
The rule catalogue: liveness and the normalisation of two publisher schemas.

Pipeline position:
    rules/*.json (package data) -> load_rules(framework) -> RuleSet

Key responsibilities:
- Pin LIVENESS, which is the single most common way to get the enforced
  population wrong: a rule is in force when it is ``live`` OR carries a
  ``reactivated_on`` date, in both cases excluding ``deleted``. Filtering on
  ``status`` alone silently drops the 153 EBA rules that were switched back on.
- Pin the normalisation of the two very different publisher schemas onto one
  ``ValidationRule``: the EBA's spreadsheet scope columns and ``If value
  missing`` / ``Arithmetic approach`` cells, and the BoE's inline
  ``scope(...)`` expression, ``dv:`` default values and ``i=`` interval
  operators — the last of which the SIMPLIFIED expression drops entirely.

Both mapping families are asserted pairwise against the raw extract across the
whole population, not on a hand-picked rule, so a normalisation that regresses
on one publisher value cannot hide behind a passing sample.

References:
- EBA DPM 3.0(3.0.1) validation rules (CRR)
- BoE banking_reporting v4.0.0 validation rules (Basel 3.1)
"""

from __future__ import annotations

import pytest

from rwa_calc.reporting.validations.rules import (
    ARITHMETIC_INTERVAL,
    ARITHMETIC_NOT_APPLICABLE,
    ARITHMETIC_POINT,
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    MISSING_SKIP,
    MISSING_ZERO,
    SCOPE_LIST,
    build_rule_reference,
    is_currently_enforced,
    load_rules,
    rules_for_tables,
)
from tests.unit.reporting.validations._builders import build_rule, raw_extract

# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def test_a_live_rule_is_enforced() -> None:
    """The unambiguous case."""
    # Arrange / Act / Assert
    assert is_currently_enforced(build_rule(status=("live",))) is True


def test_a_deactivated_rule_with_a_reactivation_date_is_enforced() -> None:
    """A rule switched back on still reports ``deactivated`` — and is in force.

    This is the limb that 153 EBA rules depend on; dropping it would silently
    shrink the enforced population by a fifth.
    """
    # Arrange
    rule = build_rule(status=("deactivated",), reactivated_on="2024-03-01")

    # Act / Assert
    assert is_currently_enforced(rule) is True


def test_a_deactivated_rule_without_a_reactivation_date_is_not_enforced() -> None:
    """Deactivation with no reactivation means the rule is off."""
    # Arrange
    rule = build_rule(status=("deactivated",), reactivated_on=None)

    # Act / Assert
    assert is_currently_enforced(rule) is False


def test_a_deleted_rule_is_not_enforced_even_when_it_carries_a_reactivation_date() -> None:
    """``deleted`` is permanent withdrawal and outranks the reactivation limb."""
    # Arrange
    rule = build_rule(status=("deleted",), reactivated_on="2024-03-01")

    # Act / Assert
    assert is_currently_enforced(rule) is False


def test_a_rule_marked_deleted_alongside_another_status_is_not_enforced() -> None:
    """``deleted`` anywhere in the status tuple withdraws the rule."""
    # Arrange
    rule = build_rule(status=("deactivated", "deleted"))

    # Act / Assert
    assert is_currently_enforced(rule) is False


def test_a_rule_absent_from_xbrl_is_not_enforced() -> None:
    """``not_in_xbrl`` is neither live nor reactivated, so it does not run."""
    # Arrange / Act / Assert
    assert is_currently_enforced(build_rule(status=("not_in_xbrl",))) is False


def test_the_reactivation_limb_is_what_separates_enforced_from_merely_live() -> None:
    """The enforced EBA population exceeds the ``live`` one by the reactivated rules."""
    # Arrange
    ruleset = load_rules(FRAMEWORK_CRR)

    # Act
    live_only = [r for r in ruleset.rules if r.status == ("live",)]
    reactivated = [
        r for r in ruleset.enforced if r.status != ("live",) and r.reactivated_on is not None
    ]

    # Assert: 588 live + 153 reactivated = the 741 enforced rules.
    assert (len(live_only), len(reactivated)) == (588, 153)
    assert len(ruleset.enforced) == len(live_only) + len(reactivated)


def test_the_boe_taxonomy_has_no_reactivation_concept() -> None:
    """The second liveness limb never fires for the BoE — every enforced rule is live."""
    # Arrange
    ruleset = load_rules(FRAMEWORK_BASEL_3_1)

    # Act / Assert
    assert all(r.status == ("live",) for r in ruleset.enforced)


# ---------------------------------------------------------------------------
# EBA normalisation
# ---------------------------------------------------------------------------


def test_every_eba_treat_as_zero_rule_normalises_to_zero_fill() -> None:
    """``treat as zero/empty string`` is the ONLY setting that invents a 0.0."""
    # Arrange
    raw = {r["id"]: r for r in raw_extract(FRAMEWORK_CRR)["rules"]}

    # Act
    mismatched = [
        rule.rule_id
        for rule in load_rules(FRAMEWORK_CRR).rules
        if (raw[rule.rule_id]["if_value_missing"] or "").startswith("treat as zero")
        and rule.missing_value != MISSING_ZERO
    ]

    # Assert
    assert mismatched == []


def test_every_other_eba_missing_value_setting_normalises_to_skip() -> None:
    """``do not run rule``, ``not applicable`` and blank all refuse the cell.

    The conservative reading: defaulting a cell the publisher did not ask us to
    default turns an unreported figure into an assertion.
    """
    # Arrange
    raw = {r["id"]: r for r in raw_extract(FRAMEWORK_CRR)["rules"]}

    # Act
    mismatched = [
        rule.rule_id
        for rule in load_rules(FRAMEWORK_CRR).rules
        if not (raw[rule.rule_id]["if_value_missing"] or "").startswith("treat as zero")
        and rule.missing_value != MISSING_SKIP
    ]

    # Assert
    assert mismatched == []


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("Interval", ARITHMETIC_INTERVAL),
        ("interval", ARITHMETIC_INTERVAL),
        ("Mixed", ARITHMETIC_INTERVAL),
        ("Point", ARITHMETIC_POINT),
        ("Not applicable", ARITHMETIC_NOT_APPLICABLE),
        ("Not Applicable", ARITHMETIC_NOT_APPLICABLE),
    ],
)
def test_the_eba_arithmetic_column_is_read_case_insensitively(spelling: str, expected: str) -> None:
    """The sheet spells each value several ways; ``Mixed`` takes the tolerant path."""
    # Arrange
    raw = {r["id"]: r for r in raw_extract(FRAMEWORK_CRR)["rules"]}
    ids = [r["id"] for r in raw.values() if r["arithmetic_approach"] == spelling]

    # Act
    normalised = {
        rule.arithmetic for rule in load_rules(FRAMEWORK_CRR).rules if rule.rule_id in ids
    }

    # Assert
    assert ids, f"no rule in the extract spells the column {spelling!r}"
    assert normalised == {expected}


def test_eba_prerequisites_are_split_into_table_codes() -> None:
    """``"C 01.00 and C 03.00 and C 02.00"`` is a conjunction, not one code."""
    # Arrange
    rule = next(r for r in load_rules(FRAMEWORK_CRR).rules if len(r.prerequisites) > 1)

    # Act / Assert
    assert all(" and " not in code for code in rule.prerequisites)


def test_eba_scope_columns_become_the_home_tables_iteration_domain() -> None:
    """The EBA keeps one rule-level scope, bound to the first table code."""
    # Arrange
    rule = next(
        r
        for r in load_rules(FRAMEWORK_CRR).rules
        if r.table_scopes and r.table_scopes[0].rows.kind == SCOPE_LIST
    )

    # Act / Assert
    assert rule.scope_for(rule.tables[0]).rows.ids


# ---------------------------------------------------------------------------
# BoE normalisation
# ---------------------------------------------------------------------------


def test_every_boe_rule_with_a_default_value_normalises_to_zero_fill() -> None:
    """``dv: 0`` in the raw expression is the publisher's own "treat as zero"."""
    # Arrange
    raw = {r["id"]: r for r in raw_extract(FRAMEWORK_BASEL_3_1)["rules"]}

    # Act
    mismatched = [
        rule.rule_id
        for rule in load_rules(FRAMEWORK_BASEL_3_1).rules
        if "dv:" in (raw[rule.rule_id]["expression_raw"] or "")
        and rule.missing_value != MISSING_ZERO
    ]

    # Assert
    assert mismatched == []


def test_every_boe_rule_without_a_default_value_normalises_to_skip() -> None:
    """No declared default means the cell is refused, not zero-filled."""
    # Arrange
    raw = {r["id"]: r for r in raw_extract(FRAMEWORK_BASEL_3_1)["rules"]}

    # Act
    mismatched = [
        rule.rule_id
        for rule in load_rules(FRAMEWORK_BASEL_3_1).rules
        if "dv:" not in (raw[rule.rule_id]["expression_raw"] or "")
        and rule.missing_value != MISSING_SKIP
    ]

    # Assert
    assert mismatched == []


def test_the_boe_interval_operator_is_recovered_from_the_raw_expression() -> None:
    """``i=`` survives only in the raw form — the simplified one drops it.

    Reading tolerance off the simplified expression would type 654 of the 820
    rules as exact comparisons and manufacture breaks over float dust.
    """
    # Arrange: a rule whose simplified expression shows a bare ``=``.
    rule = next(
        r
        for r in load_rules(FRAMEWORK_BASEL_3_1).rules
        if r.arithmetic == ARITHMETIC_INTERVAL and "i=" not in (r.expression or "")
    )

    # Act / Assert
    assert "i=" in (rule.expression_raw or "")


def test_a_boe_rule_with_no_interval_operator_is_typed_as_point() -> None:
    """Absent an ``i`` operator the comparison is exact."""
    # Arrange
    ruleset = load_rules(FRAMEWORK_BASEL_3_1)

    # Act
    point_rules = [r for r in ruleset.rules if r.arithmetic == ARITHMETIC_POINT]

    # Assert
    assert point_rules and all("i=" not in (r.expression_raw or "") for r in point_rules)


def test_the_boe_scope_expression_yields_one_table_scope_per_brace_group() -> None:
    """A rule scoping two tables carries a separate binding for each."""
    # Arrange: boe_b0307 scopes both OF 08.01 DPM variants.
    rule = next(r for r in load_rules(FRAMEWORK_BASEL_3_1).rules if r.rule_id == "boe_b0307")

    # Act
    tables = [scope.table for scope in rule.table_scopes]

    # Assert
    assert tables == ["OF08.01.01.01", "OF08.01.01.02"]


def test_a_boe_multi_valued_scope_axis_keeps_every_id() -> None:
    """``z:0001;0002;…`` is a list, not a range, and is kept verbatim."""
    # Arrange
    rule = next(r for r in load_rules(FRAMEWORK_BASEL_3_1).rules if r.rule_id == "boe_b0307")

    # Act
    sheets = rule.table_scopes[0].sheets

    # Assert
    assert (sheets.kind, sheets.ids[:3], len(sheets.ids)) == (
        SCOPE_LIST,
        ("0001", "0002", "0006"),
        17,
    )


# ---------------------------------------------------------------------------
# Catalogue API
# ---------------------------------------------------------------------------


def test_load_rules_rejects_an_unknown_framework() -> None:
    """An unsupported framework is a programming error, so it raises."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="Unknown validation-rule framework"):
        load_rules("SOLVENCY_II")


def test_rules_for_tables_matches_any_table_of_a_cross_table_rule() -> None:
    """A cross-table rule is selected by EITHER side, never only its first code."""
    # Arrange
    first = build_rule(rule_id="cross", tables=("C 09.02", "C 08.01.a"))
    other = build_rule(rule_id="unrelated", tables=("C 34.01.a",))

    # Act
    matched = rules_for_tables([first, other], ["C 08.01"])

    # Assert
    assert [r.rule_id for r in matched] == ["cross"]


def test_scope_for_an_unbound_table_is_empty_rather_than_the_first_scope() -> None:
    """Asking for a table the rule does not scope must not borrow another's axes."""
    # Arrange
    rule = build_rule(
        tables=("C 02.00", "C 07.00.a"),
        table_scopes=(build_rule().table_scopes or ()),
    )

    # Act
    scope = rule.scope_for("C 07.00.a")

    # Assert
    assert (scope.table, scope.rows.ids, scope.columns.ids) == ("C 07.00.a", (), ())


@pytest.mark.parametrize(
    ("publisher", "expected"),
    [("EBA", "COREP Annex II"), ("BoE", "PRA PS1/26 Annex II")],
)
def test_a_findings_regulatory_reference_names_the_publishers_annex(
    publisher: str, expected: str
) -> None:
    """The finding must cite the annex a reader would open to check the rule."""
    # Arrange / Act
    reference = build_rule_reference(publisher, ("C 07.00.a",))

    # Assert
    assert expected in reference and "C 07.00.a" in reference


def test_rule_ids_collide_across_the_two_extracts() -> None:
    """A rule id is only unique WITHIN a framework — 85 appear in both.

    Pinned as a fact, not an aspiration: any map keyed on ``rule_id`` alone
    silently drops one of each pair, and would look like it worked. Every
    consumer must key on ``(framework, rule_id)``.
    """
    # Arrange
    crr_ids = {rule.rule_id for rule in load_rules(FRAMEWORK_CRR).rules}
    b31_ids = {rule.rule_id for rule in load_rules(FRAMEWORK_BASEL_3_1).rules}

    # Act
    shared = crr_ids & b31_ids

    # Assert
    assert len(shared) == 85
    assert "v09779_m" in shared


def test_a_loaded_ruleset_is_shared_between_callers() -> None:
    """``load_rules`` is cached, so the returned object is not a private copy.

    Pinned because ``RuleSet.source`` is a plain mutable dict: a caller that
    mutates what it gets back poisons every later caller in the process.
    """
    # Arrange / Act
    first = load_rules(FRAMEWORK_CRR)
    second = load_rules(FRAMEWORK_CRR)

    # Assert
    assert first is second


@pytest.mark.parametrize("framework", [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1])
def test_rule_ids_are_unique_within_a_framework(framework: str) -> None:
    """Rule ids key the baseline register, so a duplicate would silently mask one."""
    # Arrange
    ruleset = load_rules(framework)

    # Act
    ids = [rule.rule_id for rule in ruleset.rules]

    # Assert
    assert len(set(ids)) == len(ids)
