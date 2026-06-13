"""Unit tests for the rulebook Decimal->float compile boundary (``rulebook/compile.py``)."""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from rwa_calc.rulebook.compile import (
    banded_expr,
    decision_expr,
    feature_enabled,
    formula_param_lit,
    lookup_expr,
    scalar_lit,
    scalar_value,
)
from rwa_calc.rulebook.model import (
    BandedTable,
    Citation,
    DecisionTable,
    Feature,
    FormulaParams,
    LookupTable,
    ScalarParam,
)

_CIT = Citation("CRR", "1")


# ---------------------------------------------------------------------------
# scalar_lit — the Decimal->float boundary
# ---------------------------------------------------------------------------


def test_scalar_lit_evaluates_to_float() -> None:
    # Arrange
    param = ScalarParam("fx_haircut", Decimal("0.08"), _CIT)

    # Act
    value = pl.select(scalar_lit(param)).item()

    # Assert
    assert value == 0.08


def test_scalar_value_returns_python_float() -> None:
    # Arrange
    param = ScalarParam("fcsm_rw_floor", Decimal("0.20"), _CIT)

    # Act
    value = scalar_value(param)

    # Assert — the float sibling of scalar_lit (no Polars boundary)
    assert isinstance(value, float)
    assert value == 0.20


def test_scalar_lit_is_float64() -> None:
    # Arrange
    param = ScalarParam("fx_haircut", Decimal("0.08"), _CIT)

    # Act
    dtype = pl.select(scalar_lit(param).alias("v")).schema["v"]

    # Assert — the Decimal has crossed into float at the compile boundary
    assert dtype == pl.Float64


# ---------------------------------------------------------------------------
# lookup_expr
# ---------------------------------------------------------------------------


def test_lookup_expr_maps_keys() -> None:
    # Arrange
    table = LookupTable(
        "corporate_cqs_rw",
        {1: Decimal("0.20"), 2: Decimal("0.50")},
        "cqs",
        _CIT,
        default=Decimal("1.00"),
    )
    frame = pl.DataFrame({"cqs": [1, 2, 9]})

    # Act
    result = frame.select(lookup_expr(table).alias("rw"))["rw"].to_list()

    # Assert — exact keys map, unknown key falls to default
    assert result == [0.20, 0.50, 1.00]


def test_lookup_expr_null_default_when_unset() -> None:
    # Arrange
    table = LookupTable("t", {1: Decimal("0.20")}, "cqs", _CIT)
    frame = pl.DataFrame({"cqs": [1, 9]})

    # Act
    result = frame.select(lookup_expr(table).alias("rw"))["rw"].to_list()

    # Assert
    assert result == [0.20, None]


# ---------------------------------------------------------------------------
# banded_expr
# ---------------------------------------------------------------------------


def test_banded_expr_assigns_band_across_boundaries() -> None:
    # Arrange — <=1 -> 0.5, <=2 -> 0.7, else -> 1.0
    table = BandedTable(
        "b",
        ((Decimal("1"), Decimal("0.5")), (Decimal("2"), Decimal("0.7")), (None, Decimal("1.0"))),
        "x",
        _CIT,
    )
    frame = pl.DataFrame({"x": [0.5, 1.0, 1.5, 2.0, 5.0]})

    # Act
    result = frame.select(banded_expr(table).alias("v"))["v"].to_list()

    # Assert — right-closed: 1.0 and 2.0 fall in their own band
    assert result == [0.5, 0.5, 0.7, 0.7, 1.0]


def test_banded_expr_right_open_uses_strict_lt() -> None:
    # Arrange — <1 -> 0.5, else -> 1.0
    table = BandedTable(
        "b",
        ((Decimal("1"), Decimal("0.5")), (None, Decimal("1.0"))),
        "x",
        _CIT,
        right_closed=False,
    )
    frame = pl.DataFrame({"x": [0.5, 1.0]})

    # Act
    result = frame.select(banded_expr(table).alias("v"))["v"].to_list()

    # Assert — boundary value 1.0 now falls to the catch-all band
    assert result == [0.5, 1.0]


def test_banded_expr_is_float64() -> None:
    # Arrange
    table = BandedTable("b", ((None, Decimal("1.0")),), "x", _CIT)

    # Act
    dtype = pl.DataFrame({"x": [1.0]}).select(banded_expr(table).alias("v")).schema["v"]

    # Assert
    assert dtype == pl.Float64


# ---------------------------------------------------------------------------
# decision_expr
# ---------------------------------------------------------------------------


def test_decision_expr_multi_key_match() -> None:
    # Arrange — (asset_class, cqs) -> rw
    table = DecisionTable(
        "d",
        ("asset_class", "cqs"),
        ((("corp", 1), Decimal("0.20")), (("corp", 2), Decimal("0.50"))),
        _CIT,
        default=Decimal("1.00"),
    )
    frame = pl.DataFrame({"asset_class": ["corp", "corp", "retail"], "cqs": [1, 2, 1]})

    # Act
    result = frame.select(decision_expr(table).alias("rw"))["rw"].to_list()

    # Assert
    assert result == [0.20, 0.50, 1.00]


# ---------------------------------------------------------------------------
# formula_param_lit / feature_enabled
# ---------------------------------------------------------------------------


def test_formula_param_lit_evaluates_named_param() -> None:
    # Arrange
    bundle = FormulaParams("f", {"correlation": Decimal("0.15")}, _CIT)

    # Act
    value = pl.select(formula_param_lit(bundle, "correlation")).item()

    # Assert
    assert value == 0.15


def test_feature_enabled_returns_bool() -> None:
    # Arrange
    feature = Feature("output_floor", True, _CIT)

    # Act / Assert
    assert feature_enabled(feature) is True
