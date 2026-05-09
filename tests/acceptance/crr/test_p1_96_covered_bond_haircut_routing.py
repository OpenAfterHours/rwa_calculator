"""
P1.96: Covered-bond collateral haircut routing — acceptance test.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario:
    A repo loan (is_sft=True) to a GB institution (CQS 2) is secured by a
    covered bond (issuer_cqs=1, residual_maturity_years=2.0,
    liquidation_period_days=5).

    Under CRR Art. 207(2) covered bonds are eligible financial collateral on
    the SFT path; the engine routes them through the Art. 224 Table 1 corp-bond
    haircut band (not "other_physical"). For CQS 1, 1–5y residual maturity the
    base haircut is H_10 = 4%.

    is_sft=True is REQUIRED on this fixture: with is_sft=False the engine
    correctly enforces Art. 197 ineligibility for covered_bond and the FCSM
    reduction is not applied. See ``test_p1_96_art_197_covered_bond_eligibility``
    for the paired non-SFT (Art. 197 ineligible) scenario.

    Liquidation-period scaling (Art. 226):
        H_m = H_10 × sqrt(T_m / 10) = 0.04 × sqrt(5/10) = 0.04 × 0.70710678 ≈ 0.02828427

    FX haircut = 0 (GBP/GBP).

    Adjusted collateral value:
        C_adj = 600_000 × (1 − 0.02828427) = 583_029.44

    E* (FCSM, Art. 223(5)):
        E* = max(0, 1_000_000 − 583_029.44) = 416_970.56

    Pre-fix (current bug):
        covered_bond falls through to "other_physical" (40% base haircut),
        scaled to sqrt(5/10) → Hc ≈ 0.28284271, C_adj ≈ 430_294.37,
        E* ≈ 569_705.63.

Isolation strategy (Strategy A):
    The primary assertion is on ead_final (E*), which is computed BEFORE the
    borrower-RW lookup. This isolates the covered-bond haircut routing bug that
    P1.96 owns and makes the test independent of the separate institution_cqs=2
    → RW=1.0 issue (out of P1.96 scope). RWA assertions are intentionally
    omitted — the RW bug will be addressed in a separate item.

References:
- CRR Art. 223:  Financial Collateral Comprehensive Method
- CRR Art. 224 Table 1:  Covered bonds use corp-bond haircut band
- CRR Art. 226:  Liquidation-period scaling (sqrt(T_m / 10))
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Hand-calc constants
# ---------------------------------------------------------------------------

# Post-fix expected E* = 1_000_000 - 600_000 × (1 - 0.02828427) = 416_970.56
_EAD_EXPECTED = 416_970.56

# Pre-fix E* using other_physical 40% base haircut scaled to 5-day liq. period:
#   H_m = 0.40 × sqrt(5/10) ≈ 0.28284271
#   C_adj = 600_000 × (1 − 0.28284271) ≈ 430_294.37
#   E* = 1_000_000 − 430_294.37 ≈ 569_705.63
_EAD_PRE_FIX = 569_705.63

_REPORTING_DATE = date(2025, 12, 31)

# Absolute tolerance: £0.50 on a 6-figure number is ~0.00012% relative error —
# tight enough to catch routing bugs, loose enough for float arithmetic.
_ABS_TOL = 0.50

# ---------------------------------------------------------------------------
# Inline data schemas
# ---------------------------------------------------------------------------

_COUNTERPARTY_SCHEMA: dict[str, pl.DataType] = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
    "default_status": pl.Boolean,
    "sector_code": pl.String,
    "apply_fi_scalar": pl.Boolean,
    "is_managed_as_retail": pl.Boolean,
    "is_natural_person": pl.Boolean,
    "is_social_housing": pl.Boolean,
    "is_financial_sector_entity": pl.Boolean,
    "scra_grade": pl.String,
    "is_investment_grade": pl.Boolean,
    "is_ccp_client_cleared": pl.Boolean,
    "borrower_income_currency": pl.String,
    "sovereign_cqs": pl.Int32,
    "local_currency": pl.String,
    "institution_cqs": pl.Int8,
}

_FACILITY_SCHEMA: dict[str, pl.DataType] = {
    "facility_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "limit": pl.Float64,
    "committed": pl.Boolean,
    "lgd": pl.Float64,
    "lgd_unsecured": pl.Float64,
    "has_sufficient_collateral_data": pl.Boolean,
    "beel": pl.Float64,
    "is_revolving": pl.Boolean,
    "is_qrre_transactor": pl.Boolean,
    "seniority": pl.String,
    "risk_type": pl.String,
    "underlying_risk_type": pl.String,
    "ccf_modelled": pl.Float64,
    "ead_modelled": pl.Float64,
    "is_short_term_trade_lc": pl.Boolean,
    "is_payroll_loan": pl.Boolean,
    "is_buy_to_let": pl.Boolean,
    "has_one_day_maturity_floor": pl.Boolean,
    "facility_termination_date": pl.Date,
    # CRR Art. 207(2): is_sft=True signals repo / SFT path so the engine
    # routes covered_bond collateral through the corp-bond haircut band
    # (Art. 224 Table 1) and the 5-day SFT liquidation period (Art. 224(2)(c)).
    # Without this flag the engine treats covered_bond as ineligible per Art. 197.
    "is_sft": pl.Boolean,
}

_LOAN_SCHEMA: dict[str, pl.DataType] = {
    "loan_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "interest": pl.Float64,
    "lgd": pl.Float64,
    "lgd_unsecured": pl.Float64,
    "has_sufficient_collateral_data": pl.Boolean,
    "beel": pl.Float64,
    "seniority": pl.String,
    "is_payroll_loan": pl.Boolean,
    "is_buy_to_let": pl.Boolean,
    "has_one_day_maturity_floor": pl.Boolean,
    "has_netting_agreement": pl.Boolean,
    "netting_facility_reference": pl.String,
    "due_diligence_performed": pl.Boolean,
    "due_diligence_override_rw": pl.Float64,
    # CRR Art. 207(2): is_sft=True drives the repo / SFT eligibility path —
    # see facility-schema comment above.
    "is_sft": pl.Boolean,
}

_COLLATERAL_SCHEMA: dict[str, pl.DataType] = {
    "collateral_reference": pl.String,
    "collateral_type": pl.String,
    "currency": pl.String,
    "maturity_date": pl.Date,
    "market_value": pl.Float64,
    "nominal_value": pl.Float64,
    "pledge_percentage": pl.Float64,
    "beneficiary_type": pl.String,
    "beneficiary_reference": pl.String,
    "issuer_cqs": pl.Int8,
    "issuer_type": pl.String,
    "residual_maturity_years": pl.Float64,
    "original_maturity_years": pl.Float64,
    "is_eligible_financial_collateral": pl.Boolean,
    "is_eligible_irb_collateral": pl.Boolean,
    "valuation_date": pl.Date,
    "valuation_type": pl.String,
    "property_type": pl.String,
    "property_ltv": pl.Float64,
    "is_income_producing": pl.Boolean,
    "is_adc": pl.Boolean,
    "is_presold": pl.Boolean,
    "is_qualifying_re": pl.Boolean,
    "prior_charge_ltv": pl.Float64,
    "liquidation_period_days": pl.Int32,
    "qualifies_for_zero_haircut": pl.Boolean,
    "insurer_risk_weight": pl.Float64,
    "credit_event_reduction": pl.Float64,
}


# ---------------------------------------------------------------------------
# Data builders
# ---------------------------------------------------------------------------


def _institution_counterparty(ref: str, institution_cqs: int) -> dict:
    """Institution counterparty with explicit CQS on the CP record."""
    return {
        "counterparty_reference": ref,
        "counterparty_name": f"Test {ref}",
        "entity_type": "institution",
        "country_code": "GB",
        "annual_revenue": None,
        "total_assets": None,
        "default_status": False,
        "sector_code": None,
        "apply_fi_scalar": None,
        "is_managed_as_retail": False,
        "is_natural_person": False,
        "is_social_housing": False,
        "is_financial_sector_entity": False,
        "scra_grade": None,
        "is_investment_grade": None,
        "is_ccp_client_cleared": False,
        "borrower_income_currency": None,
        "sovereign_cqs": None,
        "local_currency": None,
        "institution_cqs": institution_cqs,
    }


def _repo_facility(ref: str, cp_ref: str, limit: float = 1_000_000.0) -> dict:
    return {
        "facility_reference": ref,
        "product_type": "repo",
        "book_code": "FI_LENDING",
        "counterparty_reference": cp_ref,
        "value_date": date(2025, 1, 1),
        "maturity_date": date(2026, 6, 30),
        "currency": "GBP",
        "limit": limit,
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
        "facility_termination_date": None,
        "is_sft": True,
    }


def _repo_loan(ref: str, cp_ref: str, drawn_amount: float = 1_000_000.0) -> dict:
    return {
        "loan_reference": ref,
        "product_type": "repo",
        "book_code": "FI_LENDING",
        "counterparty_reference": cp_ref,
        "value_date": date(2025, 1, 1),
        "maturity_date": date(2026, 6, 30),
        "currency": "GBP",
        "drawn_amount": drawn_amount,
        "interest": 0.0,
        "lgd": None,
        "lgd_unsecured": None,
        "has_sufficient_collateral_data": False,
        "beel": None,
        "seniority": "senior",
        "is_payroll_loan": False,
        "is_buy_to_let": False,
        "has_one_day_maturity_floor": False,
        "has_netting_agreement": False,
        "netting_facility_reference": None,
        "due_diligence_performed": None,
        "due_diligence_override_rw": None,
        "is_sft": True,
    }


def _covered_bond_collateral(
    ref: str,
    beneficiary_ref: str,
    market_value: float,
    *,
    issuer_cqs: int,
    residual_maturity_years: float,
    original_maturity_years: float,
    liquidation_period_days: int,
    currency: str = "GBP",
) -> dict:
    return {
        "collateral_reference": ref,
        "collateral_type": "covered_bond",
        "currency": currency,
        "maturity_date": date(2027, 1, 1),
        "market_value": market_value,
        "nominal_value": market_value,
        "pledge_percentage": None,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "issuer_cqs": issuer_cqs,
        "issuer_type": "institution",
        "residual_maturity_years": residual_maturity_years,
        "original_maturity_years": original_maturity_years,
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        "valuation_date": date(2026, 1, 1),
        "valuation_type": "market",
        "property_type": None,
        "property_ltv": None,
        "is_income_producing": None,
        "is_adc": None,
        "is_presold": None,
        "is_qualifying_re": None,
        "prior_charge_ltv": None,
        "liquidation_period_days": liquidation_period_days,
        "qualifies_for_zero_haircut": None,
        "insurer_risk_weight": None,
        "credit_event_reduction": None,
    }


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_d15() -> object:
    """Run the SA pipeline with P1.96 covered-bond scenario inputs."""
    fac_map = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    lend_map = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    bundle = RawDataBundle(
        facilities=pl.LazyFrame(
            [_repo_facility("FAC_D15", "CP_D15")],
            schema=_FACILITY_SCHEMA,
        ),
        loans=pl.LazyFrame(
            [_repo_loan("LOAN_CRM_D15", "CP_D15", drawn_amount=1_000_000.0)],
            schema=_LOAN_SCHEMA,
        ),
        counterparties=pl.LazyFrame(
            [_institution_counterparty("CP_D15", institution_cqs=2)],
            schema=_COUNTERPARTY_SCHEMA,
        ),
        facility_mappings=fac_map,
        lending_mappings=lend_map,
        collateral=pl.LazyFrame(
            [
                _covered_bond_collateral(
                    "COLL_D15",
                    "LOAN_CRM_D15",
                    market_value=600_000.0,
                    issuer_cqs=1,
                    residual_maturity_years=2.0,
                    original_maturity_years=5.0,
                    liquidation_period_days=5,
                )
            ],
            schema=_COLLATERAL_SCHEMA,
        ),
    )
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_rows(results: object, loan_ref: str) -> list[dict]:
    """Return all result rows whose exposure_reference contains *loan_ref*."""
    rows: list[dict] = []
    for lf in [results.sa_results, results.irb_results, results.slotting_results]:
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        rows.extend(df.to_dicts())
    return rows


def _total(rows: list[dict], field: str) -> float:
    return sum(r.get(field, 0.0) or 0.0 for r in rows)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP196_CoveredBondHaircutRouting:
    """
    P1.96 — Covered bond collateral must route through Art. 224 Table 1
    corporate-bond band, not 'other_physical'.

    The primary assertion is on ead_final (E*), which is computed inside the
    CRM processor BEFORE any borrower risk-weight lookup. This isolates the
    covered-bond haircut routing bug that P1.96 owns and keeps the test
    independent of the separate institution_cqs=2 → RW=1.0 issue.

    Pre-fix:  ead_final ≈ 569_705.63  (other_physical 40% base haircut)
    Post-fix: ead_final ≈ 416_970.56  (corp-bond CQS-1 4% base haircut)
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_d15()

    # ------------------------------------------------------------------
    # Primary assertion — ead_final (E*) isolates the haircut routing bug
    # ------------------------------------------------------------------

    def test_ead_final_reflects_covered_bond_haircut(self, result) -> None:
        """
        E* must use the Art. 224 Table 1 corp-bond haircut (4% base, CQS 1,
        1–5y maturity), scaled to a 5-day liquidation period via Art. 226.

        Post-fix expected: ead_final ≈ 416_970.56
        Pre-fix (other_physical 40% base): ead_final ≈ 569_705.63

        Arrange: 1M repo loan vs institution CQS 2, covered bond MV 600k,
                 issuer_cqs=1, residual_maturity=2y, liquidation_period=5d.
        Act: run full CRR SA pipeline.
        Assert: ead_final ≈ 416_970.56 (±£0.50).
        """
        # Arrange / Act (pipeline run happens in fixture)
        rows = _find_rows(result, "LOAN_CRM_D15")
        assert rows, "LOAN_CRM_D15 not found in any result set"

        # Assert
        ead = _total(rows, "ead_final")
        assert ead == pytest.approx(_EAD_EXPECTED, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {_EAD_EXPECTED:,.2f}. "
            f"If ead_final ≈ {_EAD_PRE_FIX:,.2f} the covered_bond collateral_type "
            f"is routing through other_physical (40% base haircut) instead of "
            f"the Art. 224 corp-bond band (4% base haircut for CQS 1, 1–5y)."
        )

    # ------------------------------------------------------------------
    # Directional sanity checks — EAD-based, independent of RW
    # ------------------------------------------------------------------

    def test_ead_final_less_than_pre_fix_value(self, result) -> None:
        """
        Post-fix ead_final must be less than the pre-fix ead_final (569_705.63).

        The corp-bond haircut (4% base) is smaller than other_physical (40%),
        so the adjusted collateral value is higher → lower net exposure (E*).

        Arrange/Act: as above.
        Assert: ead_final < 569_705.63.
        """
        rows = _find_rows(result, "LOAN_CRM_D15")
        assert rows, "LOAN_CRM_D15 not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead < _EAD_PRE_FIX, (
            f"ead_final {ead:,.2f} is not less than pre-fix value {_EAD_PRE_FIX:,.2f}. "
            f"Covered bond may still be routing through other_physical."
        )

    def test_ead_final_less_than_unprotected(self, result) -> None:
        """
        ead_final must be less than the unprotected EAD (1_000_000).

        Collateral always reduces net exposure — if ead_final = 1M the CRM
        processor ignored the collateral entirely.

        Arrange/Act: as above.
        Assert: ead_final < 1_000_000.
        """
        rows = _find_rows(result, "LOAN_CRM_D15")
        assert rows, "LOAN_CRM_D15 not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead < 1_000_000.0, (
            f"ead_final {ead:,.2f} is not less than unprotected 1M. "
            f"Collateral is providing no EAD reduction."
        )

    def test_ead_final_greater_than_zero(self, result) -> None:
        """
        ead_final must be positive — collateral does not over-collateralise
        this exposure (600k MV < 1M loan).

        Arrange/Act: as above.
        Assert: ead_final > 0.
        """
        rows = _find_rows(result, "LOAN_CRM_D15")
        assert rows, "LOAN_CRM_D15 not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead > 0.0, (
            f"ead_final {ead:,.2f} is not positive. "
            f"Collateral appears to have over-collateralised the exposure."
        )
