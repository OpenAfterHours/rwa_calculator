"""Contract tests for CCR input schemas (P8.5).

Verifies that the four CCR schema objects in ``rwa_calc.data.schemas`` exist
with the architect's exact column list and dtypes.  These are pure
structural / protocol checks — they do NOT test calculation behaviour or
loader wiring (those are in ``tests/integration/test_ccr_loader.py``).

Each schema object is a ``dict[str, ColumnSpec]`` following the same
conventions as ``FACILITY_SCHEMA``, ``LOAN_SCHEMA``, etc.

Schemas tested (P8.5 architect's specification):
    TRADE_SCHEMA              — 14 columns per architect
    NETTING_SET_SCHEMA        — 10 columns per architect (fixture has 8)
    MARGIN_AGREEMENT_SCHEMA   — 10 columns per architect (fixture has 7)
    CCR_COLLATERAL_SCHEMA     — 11 columns per architect (fixture has 8)

Column-count assertions use ``>= N`` where the exact count is debatable
between the architect's spec and the fixture-builder's inline dtype dicts.
Named-column dtype/default assertions are exact.

References:
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement), 272(9) (MPOR)
    - CRR Art. 275(1)-(2) (replacement cost — MtM value V, collateral C)
    - CRR Art. 285(2)(b) — 10 business-day MPOR minimum for margined sets
    - CRR Art. 295-297 (contractual netting recognition)
"""

from __future__ import annotations

import polars as pl

import rwa_calc.data.schemas as schemas
from rwa_calc.data.column_spec import ColumnSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_schema(name: str) -> dict[str, ColumnSpec]:
    """Fetch a schema by name, asserting it exists."""
    obj = getattr(schemas, name, None)
    assert obj is not None, (
        f"rwa_calc.data.schemas does not expose '{name}'. "
        f"Add the schema to src/rwa_calc/data/schemas.py (P8.5)."
    )
    return obj  # type: ignore[return-value]


def _dtype_of(schema: dict[str, ColumnSpec], col: str) -> pl.DataType:
    """Return the Polars dtype for *col* from a ColumnSpec schema."""
    spec = schema.get(col)
    assert spec is not None, f"Column '{col}' not found in schema"
    assert isinstance(spec, ColumnSpec), f"Schema entry for '{col}' must be a ColumnSpec"
    return spec.dtype


def _default_of(schema: dict[str, ColumnSpec], col: str) -> object:
    """Return the default value for *col* from a ColumnSpec schema."""
    spec = schema.get(col)
    assert spec is not None, f"Column '{col}' not found in schema"
    return spec.default


# ===========================================================================
# TRADE_SCHEMA
# ===========================================================================


def test_trade_schema_exists() -> None:
    """TRADE_SCHEMA must be importable from rwa_calc.data.schemas."""
    # Arrange — module imported at top of file

    # Act
    obj = getattr(schemas, "TRADE_SCHEMA", None)

    # Assert
    assert obj is not None, (
        "rwa_calc.data.schemas does not expose 'TRADE_SCHEMA'. "
        "Add the schema to src/rwa_calc/data/schemas.py (P8.5)."
    )


def test_trade_schema_has_14_columns() -> None:
    """TRADE_SCHEMA must have at least 14 columns (architect's P8.5 spec)."""
    # Arrange
    schema = _get_schema("TRADE_SCHEMA")

    # Act
    col_count = len(schema)

    # Assert
    assert col_count >= 14, (
        f"TRADE_SCHEMA must have at least 14 columns, got {col_count}: {list(schema.keys())}"
    )


def test_trade_schema_trade_id_is_required_string() -> None:
    """TRADE_SCHEMA.trade_id must be pl.String and required=True."""
    # Arrange
    schema = _get_schema("TRADE_SCHEMA")

    # Act
    spec = schema.get("trade_id")

    # Assert
    assert spec is not None, "TRADE_SCHEMA must have 'trade_id' column"
    assert isinstance(spec, ColumnSpec), "'trade_id' entry must be a ColumnSpec"
    assert spec.dtype == pl.String, f"TRADE_SCHEMA.trade_id must be pl.String, got {spec.dtype}"
    assert spec.required is True, "TRADE_SCHEMA.trade_id must be required=True (primary key)"


def test_trade_schema_notional_is_float64() -> None:
    """TRADE_SCHEMA.notional must be pl.Float64."""
    # Arrange
    schema = _get_schema("TRADE_SCHEMA")

    # Act
    dtype = _dtype_of(schema, "notional")

    # Assert
    assert dtype == pl.Float64, f"TRADE_SCHEMA.notional must be pl.Float64, got {dtype}"


def test_trade_schema_maturity_date_is_date() -> None:
    """TRADE_SCHEMA.maturity_date must be pl.Date."""
    # Arrange
    schema = _get_schema("TRADE_SCHEMA")

    # Act
    dtype = _dtype_of(schema, "maturity_date")

    # Assert
    assert dtype == pl.Date, f"TRADE_SCHEMA.maturity_date must be pl.Date, got {dtype}"


def test_trade_schema_mtm_value_default_is_zero() -> None:
    """TRADE_SCHEMA.mtm_value must default to 0.0 (Art. 275: V = replacement cost value)."""
    # Arrange
    schema = _get_schema("TRADE_SCHEMA")

    # Act
    default = _default_of(schema, "mtm_value")

    # Assert
    assert default == 0.0, (
        f"TRADE_SCHEMA.mtm_value must default to 0.0 (Art. 275 replacement cost), "
        f"got {default!r}. Conservative default: at-par trade has zero MtM."
    )


def test_trade_schema_delta_default_is_one() -> None:
    """TRADE_SCHEMA.delta must default to 1.0 (non-option directional trade)."""
    # Arrange
    schema = _get_schema("TRADE_SCHEMA")

    # Act
    default = _default_of(schema, "delta")

    # Assert
    assert default == 1.0, (
        f"TRADE_SCHEMA.delta must default to 1.0 (non-option directional trade), got {default!r}."
    )


# ===========================================================================
# NETTING_SET_SCHEMA
# ===========================================================================


def test_netting_set_schema_exists() -> None:
    """NETTING_SET_SCHEMA must be importable from rwa_calc.data.schemas."""
    # Arrange — module imported at top of file

    # Act
    obj = getattr(schemas, "NETTING_SET_SCHEMA", None)

    # Assert
    assert obj is not None, (
        "rwa_calc.data.schemas does not expose 'NETTING_SET_SCHEMA'. "
        "Add the schema to src/rwa_calc/data/schemas.py (P8.5)."
    )


def test_netting_set_schema_has_at_least_8_columns() -> None:
    """NETTING_SET_SCHEMA must have at least 8 columns.

    The architect's spec has 10 columns; the fixture-builder inlined 8.
    We assert the minimum to allow the engine-implementer to choose either
    count while still covering the CCR-A1 shape.
    """
    # Arrange
    schema = _get_schema("NETTING_SET_SCHEMA")

    # Act
    col_count = len(schema)

    # Assert
    assert col_count >= 8, (
        f"NETTING_SET_SCHEMA must have at least 8 columns, got {col_count}: {list(schema.keys())}"
    )


def test_netting_set_schema_is_legally_enforceable_default_false() -> None:
    """NETTING_SET_SCHEMA.is_legally_enforceable must default to False (CRR Art. 295 conservative).

    A netting set is only recognised for CRR Chapter 6 CCR capital relief if
    the bank can demonstrate legal enforceability of the netting agreement in
    each relevant jurisdiction (Art. 295(a)-(b)).  The conservative default
    of False means an unflagged netting set gets no netting benefit — correct
    for a bank that has not yet completed its legal review.
    """
    # Arrange
    schema = _get_schema("NETTING_SET_SCHEMA")

    # Act
    default = _default_of(schema, "is_legally_enforceable")

    # Assert
    assert default is False, (
        f"NETTING_SET_SCHEMA.is_legally_enforceable must default to False "
        f"(Art. 295 conservative: netting not recognised until legality confirmed), "
        f"got {default!r}."
    )


def test_netting_set_schema_is_margined_default_false() -> None:
    """NETTING_SET_SCHEMA.is_margined must default to False (unmargined by default)."""
    # Arrange
    schema = _get_schema("NETTING_SET_SCHEMA")

    # Act
    default = _default_of(schema, "is_margined")

    # Assert
    assert default is False, (
        f"NETTING_SET_SCHEMA.is_margined must default to False (unmargined by default), "
        f"got {default!r}."
    )


# ===========================================================================
# MARGIN_AGREEMENT_SCHEMA
# ===========================================================================


def test_margin_agreement_schema_exists() -> None:
    """MARGIN_AGREEMENT_SCHEMA must be importable from rwa_calc.data.schemas."""
    # Arrange — module imported at top of file

    # Act
    obj = getattr(schemas, "MARGIN_AGREEMENT_SCHEMA", None)

    # Assert
    assert obj is not None, (
        "rwa_calc.data.schemas does not expose 'MARGIN_AGREEMENT_SCHEMA'. "
        "Add the schema to src/rwa_calc/data/schemas.py (P8.5)."
    )


def test_margin_agreement_schema_mpor_days_default_is_ten() -> None:
    """MARGIN_AGREEMENT_SCHEMA.mpor_days must default to 10.

    CRR Art. 285(2)(b): the minimum Margin Period of Risk for standard
    margined netting sets is 10 business days.  Default to 10 so that
    the SA-CCR PFE add-on uses the regulatory minimum when mpor_days is
    not explicitly supplied.
    """
    # Arrange
    schema = _get_schema("MARGIN_AGREEMENT_SCHEMA")

    # Act
    default = _default_of(schema, "mpor_days")

    # Assert
    assert default == 10, (
        f"MARGIN_AGREEMENT_SCHEMA.mpor_days must default to 10 "
        f"(Art. 285(2)(b) — 10 business-day MPOR minimum), got {default!r}."
    )


# ===========================================================================
# CCR_COLLATERAL_SCHEMA
# ===========================================================================


def test_ccr_collateral_schema_exists() -> None:
    """CCR_COLLATERAL_SCHEMA must be importable from rwa_calc.data.schemas."""
    # Arrange — module imported at top of file

    # Act
    obj = getattr(schemas, "CCR_COLLATERAL_SCHEMA", None)

    # Assert
    assert obj is not None, (
        "rwa_calc.data.schemas does not expose 'CCR_COLLATERAL_SCHEMA'. "
        "Add the schema to src/rwa_calc/data/schemas.py (P8.5)."
    )


def test_ccr_collateral_schema_market_value_default_is_zero() -> None:
    """CCR_COLLATERAL_SCHEMA.market_value must default to 0.0.

    Conservative default: a collateral row with no stated market value
    contributes zero collateral credit (C = 0) in the RC formula
    (CRR Art. 275(1)), which is the maximum-capital, most-conservative outcome.
    """
    # Arrange
    schema = _get_schema("CCR_COLLATERAL_SCHEMA")

    # Act
    default = _default_of(schema, "market_value")

    # Assert
    assert default == 0.0, (
        f"CCR_COLLATERAL_SCHEMA.market_value must default to 0.0 "
        f"(conservative: no collateral credit when value unknown), got {default!r}."
    )


# ===========================================================================
# VALID_RISK_TYPES_INPUT extension
# ===========================================================================


def test_valid_risk_types_input_includes_ccr_derivative() -> None:
    """VALID_RISK_TYPES_INPUT must include 'CCR_DERIVATIVE' (P8.5 extension)."""
    # Arrange
    valid_set = getattr(schemas, "VALID_RISK_TYPES_INPUT", None)
    assert valid_set is not None, "rwa_calc.data.schemas does not expose 'VALID_RISK_TYPES_INPUT'"

    # Act + Assert
    assert "CCR_DERIVATIVE" in valid_set, (
        f"VALID_RISK_TYPES_INPUT must include 'CCR_DERIVATIVE' (P8.5 extension for "
        f"derivative exposure risk_type), current values: {sorted(valid_set)}"
    )


def test_valid_risk_types_input_includes_ccr_sft() -> None:
    """VALID_RISK_TYPES_INPUT must include 'CCR_SFT' (P8.5 extension)."""
    # Arrange
    valid_set = getattr(schemas, "VALID_RISK_TYPES_INPUT", None)
    assert valid_set is not None, "rwa_calc.data.schemas does not expose 'VALID_RISK_TYPES_INPUT'"

    # Act + Assert
    assert "CCR_SFT" in valid_set, (
        f"VALID_RISK_TYPES_INPUT must include 'CCR_SFT' (P8.5 extension for "
        f"securities-financing transaction risk_type), current values: {sorted(valid_set)}"
    )


def test_valid_risk_types_input_length_is_eight() -> None:
    """VALID_RISK_TYPES_INPUT must contain exactly 8 values after P8.5 extension.

    Original 6 values: FR, FRC, MR, OC, MLR, LR.
    P8.5 adds: CCR_DERIVATIVE, CCR_SFT.
    Total = 8.
    """
    # Arrange
    valid_set = getattr(schemas, "VALID_RISK_TYPES_INPUT", None)
    assert valid_set is not None, "rwa_calc.data.schemas does not expose 'VALID_RISK_TYPES_INPUT'"

    # Act
    count = len(valid_set)

    # Assert
    assert count == 8, (
        f"VALID_RISK_TYPES_INPUT must contain exactly 8 values after P8.5 extension "
        f"(original 6 + CCR_DERIVATIVE + CCR_SFT), got {count}: {sorted(valid_set)}"
    )
