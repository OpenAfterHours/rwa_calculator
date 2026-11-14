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
from rwa_filer.boe.catalogue import (
    Rule,
    RuleBookNotFoundError,
    available_rulebooks,
    load_rulebook,
    rulebook_for_module,
)
from rwa_filer.boe.engine import REASON_UNKNOWN_TABLE, REASON_UNSUPPORTED, evaluate_rules
from rwa_filer.boe.formulas import DEFAULT_MEMBER
from rwa_filer.boe.grammar import references
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.taxonomy.pack import TaxonomyPack, available_packs, load_packaged

TAXONOMY = "4.1.1"

#: Rule book file -> (rules, {module: rules the gateway runs}). Measured on the
#: v4.1.1 workbooks; a new publication needs a new measurement, not an edit.
EXPECTED = {
    "banking_reporting-4.1.1.json": (1486, {"PRA001": 1441}),
    "banking_reporting_sddt-4.1.1.json": (560, {"PRA116": 531}),
    "capital_plus-4.1.1.json": (61, {"PRA112": 46, "PRA113": 18, "PRA114": 3}),
    "capital_plus_sddt-4.1.1.json": (19, {"PRA117": 13, "PRA118": 9}),
    "financialstatements-4.1.1.json": (30, {"PRA_GAAP": 15, "PRA_IFRS": 13, "PRA_MEM": 2}),
    "leverage_2023_05_11-4.1.1.json": (48, {"LVR002": 48}),
    "leverage_ratio-4.1.1.json": (61, {"LVR001": 61}),
    "liquidity_pillarii-4.1.1.json": (1108, {"PRA110": 1108}),
    "mrel-4.1.1.json": (26, {"MRL001": 15, "MRL003": 11}),
    "step_in_risk-4.1.1.json": (27, {"PRA115": 26}),
    "structural_reform-4.1.1.json": (
        387,
        {
            "RFB001": 46,
            "RFB002": 7,
            "RFB003": 29,
            "RFB004": 162,
            "RFB005": 12,
            "RFB006": 11,
            "RFB007": 46,
            "RFB008": 57,
        },
    ),
}

#: (rule book, rule) this package cannot parse, and why. All three are cells the
#: publisher's export cut at the spreadsheet cell limit; none is run by the
#: gateway ("Include in XBRL: no").
UNREADABLE = {
    ("banking_reporting-4.1.1.json", "v4011_a"): "cut at the spreadsheet cell limit",
    ("banking_reporting-4.1.1.json", "v4023_a"): "cut at the spreadsheet cell limit",
    ("banking_reporting_sddt-4.1.1.json", "v4023_a"): "cut at the spreadsheet cell limit",
}

#: (module, rule) the gateway runs and the engine refuses. Empty: for every
#: module with a packaged taxonomy pack, every enforced rule is evaluated.
UNSUPPORTED: dict[tuple[str, str], str] = {}

#: Rule book file -> the folder of the taxonomy package its formulas were read
#: from. Not derivable from the name: "leverage_ratio" is ``leverage/2026-02-27``.
FORMULA_FOLDERS = {
    "banking_reporting-4.1.1.json": "banking/banking_reporting/2026-08-17",
    "banking_reporting_sddt-4.1.1.json": "banking/banking_reporting_sddt/2026-08-17",
    "capital_plus-4.1.1.json": "banking/capital_plus/2026-02-27",
    "capital_plus_sddt-4.1.1.json": "banking/capital_plus_sddt/2026-02-27",
    "financialstatements-4.1.1.json": "banking/financialstatements/2021-07-31",
    "leverage_2023_05_11-4.1.1.json": "banking/leverage/2023-05-11",
    "leverage_ratio-4.1.1.json": "banking/leverage/2026-02-27",
    "liquidity_pillarii-4.1.1.json": "banking/liquidity_pillarii/2019-08-14",
    "mrel-4.1.1.json": "banking/mrel/2026-06-22",
    "step_in_risk-4.1.1.json": "banking/step-in-risk/2025-09-08",
    "structural_reform-4.1.1.json": "banking/structural_reform/2021-07-31",
}

#: (module, rule) -> the dimension its formula closes that every cell it names
#: carries. Table OF 91.01 is filed on two sheets, each a member of
#: ``eba_dim:PRP``; the v4.1.1 formulas for its rules fix PRP to its default
#: member, so no reported fact binds. Arelle never fires any of the seven on the
#: Bank's sample (``pra001_sample_all_tables_oracle.json``).
CLOSED_BY_FORMULA = {
    ("PRA001", "boe_b0281"): "eba_dim:PRP",
    ("PRA001", "boe_b0408"): "eba_dim:PRP",
    ("PRA001", "boe_b0527"): "eba_dim:PRP",
    ("PRA001", "boe_b0528"): "eba_dim:PRP",
    ("PRA001", "boe_b0539"): "eba_dim:PRP",
    ("PRA001", "boe_b0540"): "eba_dim:PRP",
    ("PRA001", "boe_b0541"): "eba_dim:PRP",
}


def test_every_family_of_the_publication_is_packaged() -> None:
    # Act
    counts = {
        name: (len(book.rules), {module: len(book.enforced(module)) for module in book.modules})
        for name in available_rulebooks()
        for book in [load_rulebook(name)]
    }

    # Assert — 3,813 rules in eleven rule books, all of one taxonomy release.
    assert counts == EXPECTED
    assert sum(rules for rules, _enforced in counts.values()) == 3813
    assert {load_rulebook(name).taxonomy for name in available_rulebooks()} == {TAXONOMY}


def test_the_rules_this_package_cannot_read_are_exactly_the_registered_ones() -> None:
    # Act
    unreadable = {
        (name, rule.rule_id): rule
        for name in available_rulebooks()
        for rule in load_rulebook(name).rules
        if rule.parse_error is not None
    }

    # Assert — two-way: nothing unregistered, nothing registered that now parses.
    assert set(unreadable) == set(UNREADABLE)
    for key, rule in unreadable.items():
        assert rule.truncated and UNREADABLE[key] in (rule.parse_error or ""), key


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


def test_a_module_is_found_whatever_its_case_and_an_unknown_one_is_not() -> None:
    assert rulebook_for_module("pra001").framework_version == "banking_reporting"
    assert rulebook_for_module("LVR001").framework_version == "leverage_ratio"
    with pytest.raises(RuleBookNotFoundError, match="XYZ999"):
        rulebook_for_module("XYZ999")


def test_the_same_rule_code_names_different_rules_in_different_families() -> None:
    """Why a rule's identity is its framework version AND its code."""
    # Act
    banking = load_rulebook("banking_reporting-4.1.1.json").rule("boe_b1014")
    step_in = load_rulebook("step_in_risk-4.1.1.json").rule("boe_b1014")

    # Assert
    assert isinstance(banking, Rule) and isinstance(step_in, Rule)
    assert banking.expression != step_in.expression


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
        rules = rulebook_for_module(info.module).enforced(info.module)
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


def test_every_packaged_rule_book_records_what_its_formulas_close() -> None:
    """Built with the taxonomy package, each from its own framework's folder."""
    # Act
    folders = {
        name: load_rulebook(name).source.get("formulas", {}).get("folder")
        for name in available_rulebooks()
    }
    without = [
        (name, rule.rule_id)
        for name in available_rulebooks()
        for rule in load_rulebook(name).rules
        if rule.in_xbrl and not rule.closed and not rule.closed_by_variable
    ]

    # Assert — nearly every formula closes something; a rule book where none
    # does was built without the package.
    assert folders == FORMULA_FOLDERS
    assert len(without) < 100, f"{len(without)} XBRL rules record no closed dimension"


def _closing_dimensions(pack: TaxonomyPack, rule: Rule) -> set[str] | None:
    """The closed dimensions that shut out EVERY cell some reference of ``rule`` names.

    ``None`` when each reference keeps at least one cell its formula admits.
    A static reading of the pack, with no return: which cells the rule text
    names, and whether the formula closes a dimension each of them carries.
    """
    shut: set[str] = set()
    for reference in references(rule.tree):
        table = pack.tables.get(reference.table or "")
        if table is None:
            continue
        rows = {table.row_code(code) for code in reference.rows}
        columns = {table.column_code(code) for code in reference.columns}
        sheets = {table.sheet_code(code) for code in reference.sheets}
        named = pack.cells.filter(pl.col("table") == table.code)
        for column, accepted in (("row", rows), ("column", columns), ("sheet", sheets)):
            if accepted:
                named = named.filter(pl.col(column).is_in(sorted(accepted)))
        closed = rule.closed | rule.closed_by_variable.get(reference.variable or "", frozenset())
        hits = [
            closed
            & {
                dimension
                for dimension, member in pack.datapoints[point].dimensions
                if member.rpartition(":")[2] != DEFAULT_MEMBER
            }
            for point in named["datapoint"].unique().to_list()
        ]
        if hits and all(hits):
            shut |= set().union(*hits)
    return shut or None


def test_the_rules_their_own_formulas_cannot_fire_are_exactly_the_registered_ones() -> None:
    """For each module whose pack ships: which enforced rules nobody can run.

    A rule joins this register when a new taxonomy closes a dimension its
    table reports on, and leaves it when the publisher repairs the formula.
    Either is a change in what a return is checked against, and must be seen.
    """
    # Act
    found: dict[tuple[str, str], str] = {}
    for info in available_packs():
        pack = load_packaged(info.key)
        for rule in rulebook_for_module(info.module).enforced(info.module):
            if rule.parse_error is not None or not (rule.closed or rule.closed_by_variable):
                continue
            shut = _closing_dimensions(pack, rule)
            if shut is not None:
                found[(info.module, rule.rule_id)] = ", ".join(sorted(shut))

    # Assert — two-way against the register.
    assert found == CLOSED_BY_FORMULA
