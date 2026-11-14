"""
The rule trace — every evaluation the engine made, with the cells each side read.

``trace_rules`` is what lets two returns be compared rule by rule and place by
place: an evaluation that holds in one file and breaks in the other, and the
cells it read in each, is the evidence a comparison points at. These tests pin
that the trace is the engine's own evaluation, not a second reading of the rule.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01, T02, T03, ref, rule
from pack_builders import build_pack, build_return
from rwa_filer.boe.engine import (
    STATUS_FAIL,
    STATUS_PASS,
    Accuracy,
    CellAddress,
    evaluate_rules,
    trace_rules,
)
from rwa_filer.model import DECIMALS_EXACT, CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)

#: Row 0010 is the sum of rows 0020 and 0030.
FOOTING = rule(
    "footing",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
#: RWEA (row 0020) may not exceed exposure (row 0010) — once per sheet of T02 (0001, 0002).
CAP = rule("cap", f"{ref(T02, '0020', '0010')} i<= {ref(T02, '0010', '0010')}", tables=(T02,))
#: Not a comparison at the top: a function of the cells.
NOT_NEGATIVE = rule("not-negative", f"not({ref(T01, '0010', '0010')} < 0)", tables=(T01,))


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def ret(*rows: tuple[object, ...]) -> CanonicalReturn:
    padded = [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"))


def t01(row: str, value: float) -> tuple[object, ...]:
    return (T01, None, None, row, "0010", value)


def t02(sheet: str, row: str, value: float) -> tuple[object, ...]:
    return (T02, sheet, None, row, "0010", value)


def test_the_trace_carries_the_engines_own_results(pack: TaxonomyPack) -> None:
    """Tracing changes nothing about the verdicts — it only keeps what was read."""
    # Arrange
    a_return = ret(t01("0010", 100), t01("0020", 60), t01("0030", 30), t02("0002", "0010", 5))

    # Act
    traced = trace_rules(a_return, pack, [FOOTING, CAP], accuracy=EXACT)

    # Assert
    assert list(traced.results) == evaluate_rules(a_return, pack, [FOOTING, CAP], accuracy=EXACT)


def test_an_evaluation_that_holds_is_traced_with_the_cells_of_each_side(
    pack: TaxonomyPack,
) -> None:
    # Act
    traced = trace_rules(
        ret(t01("0010", 100), t01("0020", 60), t01("0030", 40)), pack, [FOOTING], accuracy=EXACT
    )

    # Assert
    (evaluation,) = traced.evaluations
    assert (evaluation.rule_id, evaluation.holds, evaluation.relation) == ("footing", True, "=")
    assert evaluation.left == (CellAddress(T01, None, None, "0010", "0010"),)
    assert evaluation.right == (
        CellAddress(T01, None, None, "0020", "0010"),
        CellAddress(T01, None, None, "0030", "0010"),
    )
    assert (evaluation.left_value, evaluation.right_value) == (100, 100)


def test_a_broken_evaluation_keeps_both_sides_values_so_the_gap_can_be_stated(
    pack: TaxonomyPack,
) -> None:
    # Act — 100 is not 60 + 0: row 0030 is read at its default.
    traced = trace_rules(ret(t01("0010", 100), t01("0020", 60)), pack, [FOOTING], accuracy=EXACT)

    # Assert
    (evaluation,) = traced.evaluations
    assert not evaluation.holds
    assert evaluation.left_value - evaluation.right_value == 40
    assert CellAddress(T01, None, None, "0030", "0010", reported=False) in evaluation.right
    assert traced.results[0].status == STATUS_FAIL


def test_each_evaluation_has_its_own_place(pack: TaxonomyPack) -> None:
    """CAP runs once per sheet; the place is what pairs one file's evaluation with the other's."""
    # Act
    traced = trace_rules(
        ret(
            t02("0001", "0010", 40),
            t02("0001", "0020", 50),
            t02("0002", "0010", 40),
            t02("0002", "0020", 30),
        ),
        pack,
        [CAP],
        accuracy=EXACT,
    )

    # Assert
    held = {dict(item.place)["z"]: item.holds for item in traced.evaluations}
    assert held == {"0001": False, "0002": True}
    assert traced.results[0].status == STATUS_FAIL


def test_a_rule_that_is_not_a_comparison_traces_every_cell_on_one_side(
    pack: TaxonomyPack,
) -> None:
    # Act
    traced = trace_rules(ret(t01("0010", 100)), pack, [NOT_NEGATIVE], accuracy=EXACT)

    # Assert
    (evaluation,) = traced.evaluations
    assert evaluation.relation is None
    assert evaluation.left == (CellAddress(T01, None, None, "0010", "0010"),)
    assert evaluation.right == ()
    assert (evaluation.left_value, evaluation.right_value) == (None, None)
    assert traced.results[0].status == STATUS_PASS


def test_a_rule_that_is_not_run_leaves_no_evaluation(pack: TaxonomyPack) -> None:
    """T03 is not reported, so nothing that reads it is evaluated — or traced."""
    countries = rule("countries", f"{ref(T03, '0010', '0010')} >= 0", tables=(T03,))

    traced = trace_rules(ret(t01("0010", 100)), pack, [countries], accuracy=EXACT)

    assert traced.evaluations == ()
