"""
P1.147 fixture helper: mandatory-only parquet set (no model_permissions).

Pipeline position:
    fixture-builder output → test-writer (test_p1_147_irb_mode_validation.py)

Key responsibilities:
- Write the five mandatory parquet files to a caller-supplied Path so that
  DataPathValidator.validate(...) passes the base mandatory-file check.
- Deliberately omit config/model_permissions.parquet to exercise the P1.147
  engine change: when permission_mode="irb" the validator must add
  config/model_permissions.parquet to files_missing and emit VAL003.
- Provide a single corporate counterparty + loan + facility_mapping row so
  that CreditRiskCalc(..., permission_mode="irb").calculate() reaches the
  validation gate before the pipeline runs (not fail during loading).

Mandatory files written:
    counterparty/counterparties.parquet   (1 row — UK corporate)
    exposures/facilities.parquet          (1 row — committed term facility)
    exposures/loans.parquet               (1 row — drawn loan)
    exposures/facility_mapping.parquet    (1 row — loan → facility mapping)
    mapping/lending_mapping.parquet       (0 rows — empty, schema-valid)

File deliberately NOT written:
    config/model_permissions.parquet

Usage:
    from tests.fixtures.api_validation.build_mandatory_only import (
        write_mandatory_minimum,
    )

    def test_something(tmp_path):
        data_dir = write_mandatory_minimum(tmp_path)
        # data_dir contains all mandatory files but no model_permissions
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — single SA-eligible corporate counterparty
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP-P1147-001"
LOAN_REF: str = "LN-P1147-001"
FACILITY_REF: str = "FAC-P1147-001"

_VALUE_DATE = date(2025, 1, 1)
_MATURITY_DATE = date(2030, 1, 1)


# ---------------------------------------------------------------------------
# Row-level builders
# ---------------------------------------------------------------------------


def _counterparty_row() -> dict:
    """Single UK corporate counterparty row — SA-eligible, not in default."""
    return {
        "counterparty_reference": COUNTERPARTY_REF,
        "counterparty_name": "P1.147 Test Corp Ltd",
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": 50_000_000.0,
        "total_assets": None,
        "default_status": False,
        "sector_code": None,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "is_natural_person": False,
        "is_social_housing": False,
        "is_financial_sector_entity": False,
        "scra_grade": None,
        "is_investment_grade": False,
        "is_ccp_client_cleared": False,
        "borrower_income_currency": None,
        "sovereign_cqs": None,
        "local_currency": None,
        "institution_cqs": None,
        "eca_score": None,
        "is_core_market_participant": False,
    }


def _facility_row() -> dict:
    """Single committed term-loan facility row."""
    return {
        "facility_reference": FACILITY_REF,
        "product_type": "term_loan",
        "book_code": "MAIN",
        "counterparty_reference": COUNTERPARTY_REF,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
        "currency": "GBP",
        "limit": 1_000_000.0,
        "committed": True,
        "lgd": None,
        "lgd_unsecured": None,
        "has_sufficient_collateral_data": False,
        "beel": None,
        "is_revolving": False,
        "is_qrre_transactor": False,
        "seniority": "senior",
        "risk_type": None,
        "underlying_risk_type": None,
        "ccf_modelled": None,
        "ead_modelled": None,
        "is_short_term_trade_lc": False,
        "is_payroll_loan": False,
        "is_buy_to_let": False,
        "has_one_day_maturity_floor": False,
        "is_obs_commitment": True,
        "is_sft": False,
        "effective_maturity": None,
        "facility_termination_date": None,
        "purchased_receivables_subtype": None,
    }


def _loan_row() -> dict:
    """Single drawn loan row, child of the facility above."""
    return {
        "loan_reference": LOAN_REF,
        "product_type": "term_loan",
        "book_code": "MAIN",
        "counterparty_reference": COUNTERPARTY_REF,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
        "currency": "GBP",
        "drawn_amount": 1_000_000.0,
        "interest": 0.0,
        "lgd": None,
        "lgd_unsecured": None,
        "has_sufficient_collateral_data": False,
        "beel": None,
        "seniority": "senior",
        "is_payroll_loan": False,
        "is_buy_to_let": False,
        "has_one_day_maturity_floor": False,
        "is_sft": False,
        "effective_maturity": None,
        "has_netting_agreement": False,
        "netting_facility_reference": None,
        "due_diligence_performed": False,
        "due_diligence_override_rw": None,
        "purchased_receivables_subtype": None,
    }


def _facility_mapping_row() -> dict:
    """Facility→loan mapping row linking LN-P1147-001 under FAC-P1147-001."""
    return {
        "parent_facility_reference": FACILITY_REF,
        "child_reference": LOAN_REF,
        "child_type": "loan",
    }


# ---------------------------------------------------------------------------
# Public writer
# ---------------------------------------------------------------------------


def write_mandatory_minimum(out_dir: Path) -> Path:
    """
    Write the mandatory-only parquet set into *out_dir* and return *out_dir*.

    Creates the five subdirectories required by DataSourceRegistry and writes
    one schema-valid parquet file per mandatory data source:

        counterparty/counterparties.parquet   — 1 row
        exposures/facilities.parquet          — 1 row
        exposures/loans.parquet               — 1 row
        exposures/facility_mapping.parquet    — 1 row
        mapping/lending_mapping.parquet       — 0 rows (empty, schema-valid)

    config/model_permissions.parquet is deliberately NOT written.  Tests for
    P1.147 assert that DataPathValidator raises VAL003 and CreditRiskCalc
    short-circuits with success=False when permission_mode="irb" and this
    file is absent.

    Args:
        out_dir: Target directory.  Created if it does not exist.

    Returns:
        out_dir (for chaining).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectory layout mirrors DataSourceRegistry relative paths
    (out_dir / "counterparty").mkdir(exist_ok=True)
    (out_dir / "exposures").mkdir(exist_ok=True)
    (out_dir / "mapping").mkdir(exist_ok=True)

    # --- counterparty/counterparties.parquet ---
    cp_df = pl.DataFrame(
        [_counterparty_row()],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    cp_df.write_parquet(out_dir / "counterparty" / "counterparties.parquet")

    # --- exposures/facilities.parquet ---
    fac_df = pl.DataFrame(
        [_facility_row()],
        schema=dtypes_of(FACILITY_SCHEMA),
    )
    fac_df.write_parquet(out_dir / "exposures" / "facilities.parquet")

    # --- exposures/loans.parquet ---
    loan_df = pl.DataFrame(
        [_loan_row()],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    loan_df.write_parquet(out_dir / "exposures" / "loans.parquet")

    # --- exposures/facility_mapping.parquet ---
    fm_df = pl.DataFrame(
        [_facility_mapping_row()],
        schema=dtypes_of(FACILITY_MAPPING_SCHEMA),
    )
    fm_df.write_parquet(out_dir / "exposures" / "facility_mapping.parquet")

    # --- mapping/lending_mapping.parquet (empty — no lending hierarchy needed) ---
    lm_df = pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))
    lm_df.write_parquet(out_dir / "mapping" / "lending_mapping.parquet")

    return out_dir
