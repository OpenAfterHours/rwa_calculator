"""Contract tests for the dedicated SFT (FCCM) input schemas.

Phase 2 of the SFT / FCCM separation (docs/plans/sft-fccm-separation.md):
``SFT_TRADE_SCHEMA`` and ``SFT_COLLATERAL_SCHEMA`` declare the Financial
Collateral Comprehensive Method (FCCM, CRR Art. 220-223) input contract
first-class, replacing the columns previously tunnelled undeclared through
the SA-CCR ``TRADE_SCHEMA`` / ``CCR_COLLATERAL_SCHEMA``.

These are pure structural checks — they do NOT test calculation behaviour or
loader/bundle wiring (those land in later phases). Each schema object is a
``dict[str, ColumnSpec]`` following the same conventions as the other
``rwa_calc.data.schemas`` declarations.

References:
    - CRR Art. 220(1)(a) — single-counterparty SFT / master-netting-set scope
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))
    - CRR Art. 224 Table 1 — supervisory haircuts (HE / HC inputs)
    - CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274
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
        f"Add the schema to src/rwa_calc/data/schemas.py (SFT/FCCM separation Phase 2)."
    )
    return obj  # type: ignore[return-value]


def _spec(schema: dict[str, ColumnSpec], col: str) -> ColumnSpec:
    """Return the ColumnSpec for *col*, asserting it exists and is a ColumnSpec."""
    spec = schema.get(col)
    assert spec is not None, f"Column '{col}' not found in schema"
    assert isinstance(spec, ColumnSpec), f"Schema entry for '{col}' must be a ColumnSpec"
    return spec


# ===========================================================================
# SFT_TRADE_SCHEMA
# ===========================================================================

_SFT_TRADE_COLUMNS = {
    "trade_id",
    "netting_set_id",
    "counterparty_reference",
    "notional",
    "currency",
    "maturity_date",
    "start_date",
    "exposure_collateral_type",
    "exposure_security_cqs",
    "exposure_security_residual_maturity_years",
    # Phase 0b — margined-SFT (Art. 285) MPOR input columns. Additive,
    # all required=False so existing (unmargined) SFT rows default in.
    "is_margined",
    "remargining_frequency_days",
    "mpor_floor_category",
    "has_margin_dispute_doubling",
    "mpor_days_override",
    # CCR/SFT IRB effective-maturity fix Phase 2 — Art. 162 IRB-maturity input
    # flags. Additive, all required=False with conservative default False.
    "under_master_netting_agreement",
    "qualifies_one_day_maturity_floor",
    "qualifies_mna_intermediate_floor",
    # P1.215 — A-IRB routing carrier for synthetic CCR rows (own-estimate
    # LGD). Additive, required=False, no default value (null = no modelled
    # LGD; feeds the classifier's has_modelled_lgd AIRB gate).
    "ccr_modelled_lgd",
}


def test_sft_trade_schema_exists() -> None:
    """SFT_TRADE_SCHEMA must be importable from rwa_calc.data.schemas."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    assert isinstance(schema, dict) and schema, "SFT_TRADE_SCHEMA must be a non-empty dict"


def test_sft_trade_schema_has_exact_column_set() -> None:
    """SFT_TRADE_SCHEMA is a lean, dedicated schema with a fixed column set."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    assert set(schema.keys()) == _SFT_TRADE_COLUMNS, (
        f"SFT_TRADE_SCHEMA column set drift: got {sorted(schema.keys())}, "
        f"expected {sorted(_SFT_TRADE_COLUMNS)}"
    )


def test_sft_trade_schema_carries_no_derivative_only_columns() -> None:
    """The lean SFT trade schema must NOT inherit SA-CCR-only columns.

    The whole point of the separation is that an SFT row stops carrying ~25
    derivative-only columns (delta, option_*, cdo_*, commodity_type, ...).
    """
    schema = _get_schema("SFT_TRADE_SCHEMA")
    forbidden = {"delta", "mtm_value", "option_strike", "cdo_attachment", "commodity_type"}
    leaked = forbidden & set(schema.keys())
    assert not leaked, f"SFT_TRADE_SCHEMA must not carry SA-CCR-only columns: {sorted(leaked)}"


def test_sft_trade_schema_required_core_columns() -> None:
    """trade_id / netting_set_id / counterparty_reference / notional are required."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    for col in ("trade_id", "netting_set_id", "counterparty_reference", "notional"):
        assert _spec(schema, col).required is True, f"SFT_TRADE_SCHEMA.{col} must be required=True"


def test_sft_trade_schema_counterparty_reference_is_denormalised_string() -> None:
    """counterparty_reference is a required string (denormalised from the netting set)."""
    spec = _spec(_get_schema("SFT_TRADE_SCHEMA"), "counterparty_reference")
    assert spec.dtype == pl.String, f"counterparty_reference must be pl.String, got {spec.dtype}"
    assert spec.required is True


def test_sft_trade_schema_notional_is_float64() -> None:
    """notional (E in the E* formula) must be pl.Float64."""
    assert _spec(_get_schema("SFT_TRADE_SCHEMA"), "notional").dtype == pl.Float64


def test_sft_trade_schema_dates_are_date_dtype() -> None:
    """maturity_date and start_date must be pl.Date."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    for col in ("maturity_date", "start_date"):
        assert _spec(schema, col).dtype == pl.Date, f"SFT_TRADE_SCHEMA.{col} must be pl.Date"


def test_sft_trade_schema_he_inputs_are_first_class_nullable() -> None:
    """The three Art. 223(5) HE inputs are declared first-class, nullable.

    Dtypes match the identically named LOAN_SCHEMA / CONTINGENTS_SCHEMA columns:
    String / Int8 / Float64, all required=False (null => HE = 0).
    """
    schema = _get_schema("SFT_TRADE_SCHEMA")
    expected = {
        "exposure_collateral_type": pl.String,
        "exposure_security_cqs": pl.Int8,
        "exposure_security_residual_maturity_years": pl.Float64,
    }
    for col, dtype in expected.items():
        spec = _spec(schema, col)
        assert spec.dtype == dtype, f"SFT_TRADE_SCHEMA.{col} must be {dtype}, got {spec.dtype}"
        assert spec.required is False, f"SFT_TRADE_SCHEMA.{col} must be required=False (nullable)"
        assert spec.default is None, f"SFT_TRADE_SCHEMA.{col} must default to None"


# ---------------------------------------------------------------------------
# Phase 0b — margined-SFT (Art. 285 MPOR) input columns.
#
# Five additive, required=False columns make a margined SFT REPRESENTABLE.
# No engine math reads them yet (Phase 0b is carry-only): an SFT row without
# them defaults to the unmargined branch, so output is unchanged.
#
# References:
#   - CRR Art. 285(2)-(5) — margin period of risk (MPOR) floors / derivation
#   - CRR Art. 224(2) final sub-para — margined holding period brought in line
#   - CRR Art. 226 — non-daily revaluation term (unmargined branch)
# ---------------------------------------------------------------------------

#: Designed (dtype, default, required) for each new margining column.
_SFT_MARGINING_SPECS: dict[str, tuple[object, object, bool]] = {
    "is_margined": (pl.Boolean, False, False),
    "remargining_frequency_days": (pl.Int16, 1, False),
    "mpor_floor_category": (pl.String, "repo_only", False),
    "has_margin_dispute_doubling": (pl.Boolean, False, False),
    "mpor_days_override": (pl.Int16, None, False),
}


def test_sft_trade_schema_has_all_margining_columns() -> None:
    """All five Art. 285 margining columns must be present on SFT_TRADE_SCHEMA."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    missing = set(_SFT_MARGINING_SPECS) - set(schema.keys())
    assert not missing, f"SFT_TRADE_SCHEMA is missing margining columns: {sorted(missing)}"


def test_sft_trade_margining_columns_are_additive_optional() -> None:
    """Every margining column must be required=False (existing rows default in)."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    for col in _SFT_MARGINING_SPECS:
        assert _spec(schema, col).required is False, (
            f"SFT_TRADE_SCHEMA.{col} must be required=False so unmargined SFTs back-compat"
        )


def test_sft_trade_margining_columns_have_designed_dtypes_and_defaults() -> None:
    """Each margining column carries the regulatory design's dtype + default."""
    schema = _get_schema("SFT_TRADE_SCHEMA")
    for col, (dtype, default, _required) in _SFT_MARGINING_SPECS.items():
        spec = _spec(schema, col)
        assert spec.dtype == dtype, f"SFT_TRADE_SCHEMA.{col} must be {dtype}, got {spec.dtype}"
        assert spec.default == default, (
            f"SFT_TRADE_SCHEMA.{col} must default to {default!r}, got {spec.default!r}"
        )


def test_is_margined_defaults_false_for_back_compat() -> None:
    """is_margined defaults False — absent value == today's unmargined path."""
    spec = _spec(_get_schema("SFT_TRADE_SCHEMA"), "is_margined")
    assert spec.dtype == pl.Boolean
    assert spec.default is False


def test_remargining_frequency_days_defaults_one_daily() -> None:
    """remargining_frequency_days defaults 1 (daily revaluation, Art. 226 term=1.0)."""
    spec = _spec(_get_schema("SFT_TRADE_SCHEMA"), "remargining_frequency_days")
    assert spec.dtype == pl.Int16
    assert spec.default == 1


def test_mpor_days_override_is_nullable_no_default() -> None:
    """mpor_days_override is the 'derive me' signal — nullable, no default fill."""
    spec = _spec(_get_schema("SFT_TRADE_SCHEMA"), "mpor_days_override")
    assert spec.dtype == pl.Int16
    assert spec.default is None


def test_mpor_floor_category_is_value_constrained() -> None:
    """mpor_floor_category must be value-constrained to the three Art. 285 floors."""
    constraints = getattr(schemas, "COLUMN_VALUE_CONSTRAINTS", None)
    assert constraints is not None
    sft_trades = constraints.get("sft_trades")
    assert sft_trades is not None, (
        "COLUMN_VALUE_CONSTRAINTS must have an 'sft_trades' entry constraining "
        "mpor_floor_category (Phase 0b)."
    )
    assert sft_trades.get("mpor_floor_category") == {"repo_only", "other", "illiquid_or_large"}, (
        "mpor_floor_category must be constrained to {repo_only, other, illiquid_or_large}"
    )


def test_valid_mpor_floor_categories_is_exposed() -> None:
    """The constraint set is exposed as a named VALID_* collection."""
    valid = getattr(schemas, "VALID_MPOR_FLOOR_CATEGORIES", None)
    assert valid == {"repo_only", "other", "illiquid_or_large"}, (
        f"VALID_MPOR_FLOOR_CATEGORIES drift: {valid}"
    )


# ===========================================================================
# SFT_COLLATERAL_SCHEMA
# ===========================================================================

_SFT_COLLATERAL_COLUMNS = {
    "sft_collateral_reference",
    "netting_set_id",
    "collateral_type",
    "market_value",
    "currency",
    "issuer_cqs",
    "residual_maturity_years",
}


def test_sft_collateral_schema_exists() -> None:
    """SFT_COLLATERAL_SCHEMA must be importable from rwa_calc.data.schemas."""
    schema = _get_schema("SFT_COLLATERAL_SCHEMA")
    assert isinstance(schema, dict) and schema, "SFT_COLLATERAL_SCHEMA must be a non-empty dict"


def test_sft_collateral_schema_has_exact_column_set() -> None:
    """SFT_COLLATERAL_SCHEMA is a lean subset of CCR_COLLATERAL_SCHEMA."""
    schema = _get_schema("SFT_COLLATERAL_SCHEMA")
    assert set(schema.keys()) == _SFT_COLLATERAL_COLUMNS, (
        f"SFT_COLLATERAL_SCHEMA column set drift: got {sorted(schema.keys())}, "
        f"expected {sorted(_SFT_COLLATERAL_COLUMNS)}"
    )


def test_sft_collateral_schema_drops_sa_ccr_only_columns() -> None:
    """The lean collateral schema must drop the SA-CCR-only collateral columns."""
    schema = _get_schema("SFT_COLLATERAL_SCHEMA")
    dropped = {"is_posted_by_firm", "is_segregated", "issuer_type", "haircut_override"}
    leaked = dropped & set(schema.keys())
    assert not leaked, f"SFT_COLLATERAL_SCHEMA must drop SA-CCR-only columns: {sorted(leaked)}"


def test_sft_collateral_schema_market_value_default_is_zero() -> None:
    """market_value (CVA in the E* formula) must default to 0.0 (no collateral credit)."""
    spec = _spec(_get_schema("SFT_COLLATERAL_SCHEMA"), "market_value")
    assert spec.dtype == pl.Float64
    assert spec.required is False
    assert spec.default == 0.0, f"market_value must default to 0.0, got {spec.default!r}"


# ===========================================================================
# VALID_TRANSACTION_TYPES + COLUMN_VALUE_CONSTRAINTS wiring
# ===========================================================================


def test_valid_transaction_types_is_derivative_and_sft() -> None:
    """VALID_TRANSACTION_TYPES must be exactly {'derivative', 'sft'}."""
    valid = getattr(schemas, "VALID_TRANSACTION_TYPES", None)
    assert valid is not None, "rwa_calc.data.schemas does not expose 'VALID_TRANSACTION_TYPES'"
    assert valid == {"derivative", "sft"}, f"VALID_TRANSACTION_TYPES drift: {valid}"


def test_transaction_type_constraint_references_valid_transaction_types() -> None:
    """COLUMN_VALUE_CONSTRAINTS['trades']['transaction_type'] must be VALID_TRANSACTION_TYPES."""
    constraints = getattr(schemas, "COLUMN_VALUE_CONSTRAINTS", None)
    assert constraints is not None, (
        "rwa_calc.data.schemas does not expose 'COLUMN_VALUE_CONSTRAINTS'"
    )
    trades = constraints.get("trades")
    assert trades is not None, "COLUMN_VALUE_CONSTRAINTS must have a 'trades' entry"
    assert trades.get("transaction_type") == schemas.VALID_TRANSACTION_TYPES, (
        "COLUMN_VALUE_CONSTRAINTS['trades']['transaction_type'] must equal VALID_TRANSACTION_TYPES"
    )
