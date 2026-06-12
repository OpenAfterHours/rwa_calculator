"""Regression tests for P6.26: introduce _FACILITY_QRRE_COUPLED_COLUMNS constant.

Three assertions:
1. The module-level constant exists with the correct tuple value.
2. The legacy TODO(qrre-coupling) marker has been removed.
3. Behaviour-preservation pin: QRRE columns propagate through HierarchyResolver
   unchanged after the refactor.

Tests 1 and 2 are expected to FAIL until the engine-implementer lands the change.
Test 3 is expected to PASS (regression guard against accidental breakage).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

import rwa_calc.engine.hierarchy as hierarchy_module
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Test 1 — constant existence and value
# ---------------------------------------------------------------------------


def test_facility_qrre_coupled_columns_constant_exists() -> None:
    """_FACILITY_QRRE_COUPLED_COLUMNS must exist as a module-level tuple with
    exactly the four QRRE-relevant facility column names in canonical order."""
    # Arrange
    expected = ("is_revolving", "is_qrre_transactor", "facility_limit", "facility_termination_date")

    # Act / Assert — test fails here until the constant is added
    assert hasattr(hierarchy_module, "_FACILITY_QRRE_COUPLED_COLUMNS"), (
        "missing module-level constant _FACILITY_QRRE_COUPLED_COLUMNS in "
        "rwa_calc.engine.hierarchy; add it as part of the P6.26 refactor"
    )
    assert expected == hierarchy_module._FACILITY_QRRE_COUPLED_COLUMNS, (
        f"_FACILITY_QRRE_COUPLED_COLUMNS = {hierarchy_module._FACILITY_QRRE_COUPLED_COLUMNS!r} "
        f"does not equal expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — TODO marker removed
# ---------------------------------------------------------------------------


def test_qrre_coupling_todo_marker_removed() -> None:
    """The TODO(qrre-coupling) comment must be replaced by an explanatory
    comment referencing _FACILITY_QRRE_COUPLED_COLUMNS after the P6.26
    refactor lands."""
    # Arrange
    source_path = Path(hierarchy_module.__file__)
    source = source_path.read_text()

    # Act / Assert — test fails here until the TODO is removed
    assert "TODO(qrre-coupling)" not in source, (
        "TODO(qrre-coupling) marker still present in rwa_calc/engine/hierarchy.py; "
        "P6.26 requires replacing it with an explanatory comment that references "
        "_FACILITY_QRRE_COUPLED_COLUMNS"
    )


# ---------------------------------------------------------------------------
# Test 3 — behaviour-preservation regression pin (must PASS today)
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2024, 12, 31)

_COUNTERPARTIES = pl.DataFrame(
    {
        "counterparty_reference": ["CP_QRRE", "CP_CTRL"],
        "counterparty_name": ["QRRE Borrower", "Control Borrower"],
        "entity_type": ["individual", "individual"],
        "country_code": ["GB", "GB"],
        "annual_revenue": [0.0, 0.0],
        "total_assets": [0.0, 0.0],
        "default_status": [False, False],
        "sector_code": ["RETAIL", "RETAIL"],
        "is_financial_institution": [False, False],
        "apply_fi_scalar": [True, True],
        "is_pse": [False, False],
        "is_mdb": [False, False],
        "is_international_org": [False, False],
        "is_central_counterparty": [False, False],
        "is_regional_govt_local_auth": [False, False],
        "is_managed_as_retail": [False, False],
    }
).lazy()

_FACILITIES = pl.DataFrame(
    {
        "facility_reference": ["FAC_QRRE", "FAC_CTRL"],
        "product_type": ["CREDIT_CARD", "TERM_LOAN"],
        "book_code": ["RETAIL", "RETAIL"],
        "counterparty_reference": ["CP_QRRE", "CP_CTRL"],
        "value_date": [date(2023, 1, 1), date(2023, 1, 1)],
        "maturity_date": [date(2030, 6, 30), date(2030, 6, 30)],
        "currency": ["GBP", "GBP"],
        "limit": [100_000.0, 50_000.0],
        "committed": [True, True],
        "lgd": [0.45, 0.45],
        "beel": [0.01, 0.01],
        "seniority": ["senior", "senior"],
        "risk_type": ["MR", "MR"],
        "ccf_modelled": [None, None],
        "is_short_term_trade_lc": [False, False],
        # The four coupled columns under test
        "is_revolving": [True, False],
        "is_qrre_transactor": [True, False],
        "facility_termination_date": [date(2028, 6, 30), None],
    }
).lazy()

# One drawn loan under FAC_QRRE (partially uses the limit)
_LOANS = pl.DataFrame(
    {
        "loan_reference": ["LOAN_QRRE", "LOAN_CTRL"],
        "product_type": ["CREDIT_CARD_DRAW", "TERM_LOAN"],
        "book_code": ["RETAIL", "RETAIL"],
        "counterparty_reference": ["CP_QRRE", "CP_CTRL"],
        "value_date": [date(2024, 1, 1), date(2023, 1, 1)],
        "maturity_date": [date(2026, 1, 1), date(2030, 6, 30)],
        "currency": ["GBP", "GBP"],
        "drawn_amount": [30_000.0, 50_000.0],
        "lgd": [0.45, 0.45],
        "beel": [0.01, 0.01],
        "seniority": ["senior", "senior"],
        "risk_type": ["FR", "FR"],
        "ccf_modelled": [None, None],
        "is_short_term_trade_lc": [None, None],
    }
).lazy()

# Mappings: LOAN_QRRE belongs to FAC_QRRE; LOAN_CTRL belongs to FAC_CTRL
_FACILITY_MAPPINGS = pl.DataFrame(
    {
        "parent_facility_reference": ["FAC_QRRE", "FAC_CTRL"],
        "child_reference": ["LOAN_QRRE", "LOAN_CTRL"],
        "child_type": ["loan", "loan"],
    }
).lazy()

_EMPTY_LENDING_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_counterparty_reference": pl.String,
        "child_counterparty_reference": pl.String,
    }
)


def test_qrre_columns_propagate_unchanged_through_resolver() -> None:
    """Regression pin: after resolver.resolve(), QRRE-relevant columns must
    (a) exist in the schema with the correct dtypes, and
    (b) carry the parent facility values on both the loan exposure (Site B
        propagation via _propagate_facility_qrre_columns) and the synthesised
        facility_undrawn exposure (Site A synthesis in _undrawn_select_expressions).

    This test must PASS today and must continue to pass after P6.26 lands.
    """
    # Arrange
    bundle = make_raw_bundle(
        facilities=_FACILITIES,
        loans=_LOANS,
        counterparties=_COUNTERPARTIES,
        facility_mappings=_FACILITY_MAPPINGS,
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
        org_mappings=None,
        contingents=None,
        collateral=None,
        guarantees=None,
        provisions=None,
        ratings=None,
    )
    config = CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    resolver = HierarchyResolver()

    # Act
    result = resolver.resolve(bundle, config)
    df = result.exposures.collect()

    # Assert: the four QRRE-relevant columns exist in the schema
    schema = result.exposures.collect_schema()
    schema_names = set(schema.names())
    assert set(
        {"is_revolving", "is_qrre_transactor", "facility_limit", "facility_termination_date"}
    ).issubset(schema_names), (
        f"Not all QRRE-coupled columns present in resolved schema; found: {sorted(schema_names)}"
    )

    # Assert dtypes
    assert schema["is_revolving"] == pl.Boolean, (
        f"is_revolving dtype should be pl.Boolean, got {schema['is_revolving']}"
    )
    assert schema["is_qrre_transactor"] == pl.Boolean, (
        f"is_qrre_transactor dtype should be pl.Boolean, got {schema['is_qrre_transactor']}"
    )
    assert schema["facility_limit"] == pl.Float64, (
        f"facility_limit dtype should be pl.Float64, got {schema['facility_limit']}"
    )
    assert schema["facility_termination_date"] == pl.Date, (
        f"facility_termination_date dtype should be pl.Date, got {schema['facility_termination_date']}"
    )

    # Assert Site B: loan row for LOAN_QRRE inherits the facility QRRE values
    loan_row = df.filter(pl.col("exposure_reference") == "LOAN_QRRE")
    assert len(loan_row) == 1, "LOAN_QRRE exposure row missing from resolved frame"
    assert loan_row["is_revolving"][0] is True, (
        "LOAN_QRRE: is_revolving should be True (inherited from FAC_QRRE)"
    )
    assert loan_row["is_qrre_transactor"][0] is True, (
        "LOAN_QRRE: is_qrre_transactor should be True (inherited from FAC_QRRE)"
    )
    assert loan_row["facility_limit"][0] == pytest.approx(100_000.0), (
        "LOAN_QRRE: facility_limit should be 100_000.0 (inherited from FAC_QRRE)"
    )
    assert loan_row["facility_termination_date"][0] == date(2028, 6, 30), (
        "LOAN_QRRE: facility_termination_date should be 2028-06-30 (inherited from FAC_QRRE)"
    )

    # Assert Site A: facility_undrawn row for FAC_QRRE carries facility QRRE values
    # FAC_QRRE has limit=100_000, drawn=30_000 → undrawn=70_000 > 0, committed=True → row emitted
    undrawn_row = df.filter(pl.col("exposure_reference") == "FAC_QRRE_UNDRAWN")
    assert len(undrawn_row) == 1, (
        "FAC_QRRE_UNDRAWN exposure row missing; "
        f"facility_undrawn rows in frame: {df.filter(pl.col('exposure_type') == 'facility_undrawn')['exposure_reference'].to_list()}"
    )
    assert undrawn_row["is_revolving"][0] is True, (
        "FAC_QRRE_UNDRAWN: is_revolving should be True (set in _undrawn_select_expressions)"
    )
    assert undrawn_row["is_qrre_transactor"][0] is True, (
        "FAC_QRRE_UNDRAWN: is_qrre_transactor should be True (set in _undrawn_select_expressions)"
    )
    assert undrawn_row["facility_limit"][0] == pytest.approx(100_000.0), (
        "FAC_QRRE_UNDRAWN: facility_limit should be 100_000.0"
    )
    assert undrawn_row["facility_termination_date"][0] == date(2028, 6, 30), (
        "FAC_QRRE_UNDRAWN: facility_termination_date should be 2028-06-30"
    )

    # Assert control: non-revolving LOAN_CTRL inherits False values from FAC_CTRL
    ctrl_loan_row = df.filter(pl.col("exposure_reference") == "LOAN_CTRL")
    assert len(ctrl_loan_row) == 1, "LOAN_CTRL exposure row missing from resolved frame"
    assert ctrl_loan_row["is_revolving"][0] is False, (
        "LOAN_CTRL: is_revolving should be False (inherited from non-revolving FAC_CTRL)"
    )
    assert ctrl_loan_row["is_qrre_transactor"][0] is False, (
        "LOAN_CTRL: is_qrre_transactor should be False (inherited from FAC_CTRL)"
    )
