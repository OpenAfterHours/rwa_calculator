"""End-to-end pipeline tests for the securitisation pool allocation feature.

Covers SEC-01 ... SEC-08 from the implementation plan -- the full pipeline
runs with a hand-built RawDataBundle and a ``securitisation_allocations``
input frame; assertions verify the carved-out behaviour at the aggregator.

References:
- CRR Art. 109, Art. 244-246
- PRA PS1/26 Art. 147A(1)(j)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_SEC_FULLY_SECURITISED,
    ERROR_SEC_OVER_ALLOCATED,
    ERROR_SEC_UNKNOWN_REFERENCE,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_REPORTING_DATE = date(2025, 12, 31)
_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 12, 31)


# ---------------------------------------------------------------------------
# Minimal fixture builders
# ---------------------------------------------------------------------------


def _counterparty_row() -> dict:
    """Single corporate counterparty CP1, unrated -> 100% RW under SA."""
    return {
        "counterparty_reference": ["CP1"],
        "counterparty_name": ["Test Corp"],
        "entity_type": ["corporate"],
        "country_code": ["GB"],
        "annual_revenue": [200_000_000.0],
        "total_assets": [None],
        "default_status": [False],
        "sector_code": [None],
        "apply_fi_scalar": [None],
        "is_managed_as_retail": [False],
        "is_natural_person": [False],
        "is_social_housing": [False],
        "is_financial_sector_entity": [False],
        "scra_grade": [None],
        "is_investment_grade": [None],
        "is_ccp_client_cleared": [False],
        "borrower_income_currency": [None],
        "sovereign_cqs": [None],
        "local_currency": [None],
        "institution_cqs": [None],
    }


def _empty_facility_frame() -> pl.LazyFrame:
    return pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
            "limit": pl.Float64,
            "committed": pl.Boolean,
            "currency": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
        }
    )


def _empty_facility_mapping_frame() -> pl.LazyFrame:
    return pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )


def _empty_lending_mapping_frame() -> pl.LazyFrame:
    return pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )


def _loans(loans: list[dict]) -> pl.LazyFrame:
    """Build a loans LazyFrame from a list of dicts.

    Each dict needs ``loan_reference`` and ``drawn_amount``; everything else
    defaults via the schema.
    """
    rows = {
        "loan_reference": [],
        "product_type": [],
        "book_code": [],
        "counterparty_reference": [],
        "value_date": [],
        "maturity_date": [],
        "currency": [],
        "drawn_amount": [],
        "interest": [],
        "lgd": [],
        "lgd_unsecured": [],
        "has_sufficient_collateral_data": [],
        "beel": [],
        "seniority": [],
        "is_payroll_loan": [],
        "is_buy_to_let": [],
        "has_one_day_maturity_floor": [],
        "has_netting_agreement": [],
        "netting_facility_reference": [],
        "due_diligence_performed": [],
        "due_diligence_override_rw": [],
    }
    for loan in loans:
        rows["loan_reference"].append(loan["loan_reference"])
        rows["product_type"].append("term_loan")
        rows["book_code"].append("BANK")
        rows["counterparty_reference"].append(loan.get("counterparty_reference", "CP1"))
        rows["value_date"].append(_VALUE_DATE)
        rows["maturity_date"].append(_MATURITY_DATE)
        rows["currency"].append("GBP")
        rows["drawn_amount"].append(loan["drawn_amount"])
        rows["interest"].append(0.0)
        rows["lgd"].append(0.45)
        rows["lgd_unsecured"].append(0.45)
        rows["has_sufficient_collateral_data"].append(True)
        rows["beel"].append(None)
        rows["seniority"].append("senior")
        rows["is_payroll_loan"].append(False)
        rows["is_buy_to_let"].append(False)
        rows["has_one_day_maturity_floor"].append(False)
        rows["has_netting_agreement"].append(False)
        rows["netting_facility_reference"].append(None)
        rows["due_diligence_performed"].append(None)
        rows["due_diligence_override_rw"].append(None)
    return pl.LazyFrame(rows)


def _allocs(rows: list[dict]) -> pl.LazyFrame:
    """Build a securitisation_allocations LazyFrame."""
    return pl.LazyFrame(
        {
            "exposure_reference": [r["exposure_reference"] for r in rows],
            "exposure_type": [r.get("exposure_type", "loan") for r in rows],
            "pool_reference": [r["pool_reference"] for r in rows],
            "allocation_pct": [r["allocation_pct"] for r in rows],
        }
    )


def _bundle(loans: list[dict], allocs: pl.LazyFrame | None = None) -> RawDataBundle:
    return RawDataBundle(
        counterparties=pl.LazyFrame(_counterparty_row()),
        facilities=_empty_facility_frame(),
        loans=_loans(loans),
        facility_mappings=_empty_facility_mapping_frame(),
        lending_mappings=_empty_lending_mapping_frame(),
        securitisation_allocations=allocs,
    )


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )


def _run(bundle: RawDataBundle, config: CalculationConfig | None = None):
    return PipelineOrchestrator().run_with_data(bundle, config or _crr_config())


# ---------------------------------------------------------------------------
# SEC-01 ... SEC-08
# ---------------------------------------------------------------------------


def test_sec_01_fully_securitised_loan_zero_standard_rwa() -> None:
    """SEC-01: £1m loan, 100% to pool A -> standard RWA = £0."""
    bundle = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [{"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 1.0}]
        ),
    )
    result = _run(bundle)

    # The on-balance-sheet view (after residual multiplier) has zero EAD/RWA.
    df = result.results.collect()
    row = df.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    assert row["ead_final"] == pytest.approx(0.0)
    assert row["rwa_final"] == pytest.approx(0.0)

    # Pool summary shows the carved-off slice.
    pool = result.securitisation_summary.collect()
    assert pool.height == 1
    pool_row = pool.row(0, named=True)
    assert pool_row["pool_reference"] == "POOL_A"
    assert pool_row["total_ead"] == pytest.approx(1_000_000.0)
    assert pool_row["total_rwa_placeholder"] == pytest.approx(1_000_000.0)

    # SEC005 informational warning surfaces.
    assert any(e.code == ERROR_SEC_FULLY_SECURITISED for e in result.errors)


def test_sec_02_half_securitised_loan() -> None:
    """SEC-02: £1m loan, 50% pool A, 50% residual -> standard RWA = 50% x full."""
    bundle = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [{"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 0.5}]
        ),
    )
    result = _run(bundle)

    df = result.results.collect()
    row = df.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    # Unrated corporate -> 100% RW. Residual EAD = 500k. Residual RWA = 500k.
    assert row["ead_final"] == pytest.approx(500_000.0)
    assert row["rwa_final"] == pytest.approx(500_000.0)
    assert row["securitisation_residual_pct"] == pytest.approx(0.5)

    pool_row = result.securitisation_summary.collect().row(0, named=True)
    assert pool_row["total_ead"] == pytest.approx(500_000.0)


def test_sec_03_three_way_split() -> None:
    """SEC-03: 40% pool A + 30% pool B + 30% residual."""
    bundle = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [
                {"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 0.4},
                {"exposure_reference": "L001", "pool_reference": "POOL_B", "allocation_pct": 0.3},
            ]
        ),
    )
    result = _run(bundle)

    df = result.results.collect()
    row = df.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    assert row["ead_final"] == pytest.approx(300_000.0)
    assert row["securitisation_residual_pct"] == pytest.approx(0.3)

    pool = result.securitisation_summary.collect().sort("pool_reference")
    rows = {r["pool_reference"]: r for r in pool.iter_rows(named=True)}
    assert rows["POOL_A"]["total_ead"] == pytest.approx(400_000.0)
    assert rows["POOL_B"]["total_ead"] == pytest.approx(300_000.0)


def test_sec_06_residual_equals_pro_rata_via_linearity() -> None:
    """SEC-06: residual_rwa == full_pipeline_rwa * residual_pct.

    Two parallel pipeline runs: one un-securitised, one 60% securitised. The
    residual contribution of the securitised run equals 0.4x the un-securitised
    RWA -- demonstrates the linearity argument that justifies late multiplication.
    """
    # Run 1: un-securitised baseline
    bundle_baseline = _bundle(loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}])
    baseline = _run(bundle_baseline)
    baseline_row = (
        baseline.results.collect().filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    )

    # Run 2: 60% securitised
    bundle_secur = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [{"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 0.6}]
        ),
    )
    secur = _run(bundle_secur)
    secur_row = (
        secur.results.collect().filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    )

    # Linearity property
    assert secur_row["rwa_final"] == pytest.approx(baseline_row["rwa_final"] * 0.4)
    assert secur_row["ead_final"] == pytest.approx(baseline_row["ead_final"] * 0.4)


def test_sec_07_over_allocation_dq_error() -> None:
    """SEC-07: sum > 1.0 -> SEC001 raised, exposure kept fully on-balance-sheet."""
    bundle = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [
                {"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 0.7},
                {"exposure_reference": "L001", "pool_reference": "POOL_B", "allocation_pct": 0.5},
            ]
        ),
    )
    result = _run(bundle)

    df = result.results.collect()
    row = df.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    # Standard RWA = un-securitised value (residual_pct = 1.0).
    assert row["securitisation_residual_pct"] == pytest.approx(1.0)
    assert row["rwa_final"] == pytest.approx(1_000_000.0)

    assert any(e.code == ERROR_SEC_OVER_ALLOCATED for e in result.errors)


def test_sec_08_orphan_reference_dq_warning() -> None:
    """SEC-08: allocation references unknown loan -> warning, row dropped."""
    bundle = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [
                {
                    "exposure_reference": "L_ORPHAN",
                    "pool_reference": "POOL_A",
                    "allocation_pct": 0.5,
                },
                {"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 0.3},
            ]
        ),
    )
    result = _run(bundle)

    df = result.results.collect()
    row = df.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    # The valid L001 row honours its 30% allocation.
    assert row["securitisation_residual_pct"] == pytest.approx(0.7)

    assert any(e.code == ERROR_SEC_UNKNOWN_REFERENCE for e in result.errors)


# ---------------------------------------------------------------------------
# Audit + reconciliation
# ---------------------------------------------------------------------------


def test_securitisation_audit_reconciles_parent_ead() -> None:
    """parent_ead = residual_ead + securitised_ead; reconciliation_delta = 0."""
    bundle = _bundle(
        loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}],
        allocs=_allocs(
            [
                {"exposure_reference": "L001", "pool_reference": "POOL_A", "allocation_pct": 0.4},
                {"exposure_reference": "L001", "pool_reference": "POOL_B", "allocation_pct": 0.3},
            ]
        ),
    )
    result = _run(bundle)

    audit = result.securitisation_audit.collect()
    assert audit.height == 1
    row = audit.row(0, named=True)
    assert row["exposure_reference"] == "L001"
    assert row["parent_ead"] == pytest.approx(1_000_000.0)
    assert row["residual_ead"] == pytest.approx(300_000.0)
    assert row["securitised_ead"] == pytest.approx(700_000.0)
    assert row["reconciliation_delta"] == pytest.approx(0.0, abs=1e-6)
    assert row["audit_status"] == "ok"


def test_no_allocations_supplied_means_no_securitisation_outputs() -> None:
    """When no allocations are supplied, summary and audit are None."""
    bundle = _bundle(loans=[{"loan_reference": "L001", "drawn_amount": 1_000_000.0}])
    result = _run(bundle)

    assert result.securitisation_summary is None
    assert result.securitisation_audit is None

    # Standard pipeline still works -- L001 RWA is the unmodified £1m.
    df = result.results.collect()
    row = df.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
    assert row["rwa_final"] == pytest.approx(1_000_000.0)
