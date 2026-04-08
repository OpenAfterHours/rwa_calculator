"""
Advanced CRM acceptance tests for CRR framework.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenarios complement the basic CRR-D group (D1-D6 in test_scenario_crr_d_crm.py)
and CRR-G group (G1-G3 in test_scenario_crr_g_provisions.py) with advanced CRM
scenarios: non-beneficial guarantees, sovereign guarantees, credit derivative
restructuring exclusion, gold/other-equity collateral haircuts, overcollateralisation,
full CRM chain (provision + collateral + guarantee combined), and multi-provision
aggregation.

References:
- CRR Art. 110 (SA provision deduction)
- CRR Art. 213-217 (unfunded credit protection eligibility)
- CRR Art. 224 Table 4 (supervisory haircuts: gold 15%, other equity 25%)
- CRR Art. 233(2) / Art. 216(1) (CDS restructuring exclusion: 40% haircut)
- CRR Art. 233A (proportional guarantee coverage)
- CRR Art. 235 (SA risk-weight substitution)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator


# ---------------------------------------------------------------------------
# Data builders (inline, self-contained per-scenario data)
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2025, 12, 31)

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
}

_RATING_SCHEMA: dict[str, pl.DataType] = {
    "rating_reference": pl.String,
    "counterparty_reference": pl.String,
    "rating_type": pl.String,
    "rating_agency": pl.String,
    "rating_value": pl.String,
    "cqs": pl.Int8,
    "pd": pl.Float64,
    "rating_date": pl.Date,
    "is_solicited": pl.Boolean,
    "model_id": pl.String,
}

_GUARANTEE_SCHEMA: dict[str, pl.DataType] = {
    "guarantee_reference": pl.String,
    "guarantee_type": pl.String,
    "guarantor": pl.String,
    "currency": pl.String,
    "maturity_date": pl.Date,
    "amount_covered": pl.Float64,
    "percentage_covered": pl.Float64,
    "beneficiary_type": pl.String,
    "beneficiary_reference": pl.String,
    "protection_type": pl.String,
    "includes_restructuring": pl.Boolean,
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

_PROVISION_SCHEMA: dict[str, pl.DataType] = {
    "provision_reference": pl.String,
    "provision_type": pl.String,
    "ifrs9_stage": pl.Int8,
    "currency": pl.String,
    "amount": pl.Float64,
    "as_of_date": pl.Date,
    "beneficiary_type": pl.String,
    "beneficiary_reference": pl.String,
}


def _counterparty(
    ref: str,
    entity_type: str = "corporate",
    country_code: str = "GB",
    annual_revenue: float | None = 50_000_000.0,
    sovereign_cqs: int | None = None,
    institution_cqs: int | None = None,
    default_status: bool = False,
) -> dict:
    return {
        "counterparty_reference": ref,
        "counterparty_name": f"Test {ref}",
        "entity_type": entity_type,
        "country_code": country_code,
        "annual_revenue": annual_revenue,
        "total_assets": None,
        "default_status": default_status,
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
        "sovereign_cqs": sovereign_cqs,
        "local_currency": None,
        "institution_cqs": institution_cqs,
    }


def _facility(ref: str, cp_ref: str, risk_type: str = "corporate") -> dict:
    return {
        "facility_reference": ref,
        "product_type": "term_loan",
        "book_code": "MAIN",
        "counterparty_reference": cp_ref,
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2030, 12, 31),
        "currency": "GBP",
        "limit": 10_000_000.0,
        "committed": True,
        "lgd": None,
        "lgd_unsecured": None,
        "has_sufficient_collateral_data": False,
        "beel": None,
        "is_revolving": False,
        "is_qrre_transactor": False,
        "seniority": "senior",
        "risk_type": risk_type,
        "underlying_risk_type": None,
        "ccf_modelled": None,
        "ead_modelled": None,
        "is_short_term_trade_lc": False,
        "is_payroll_loan": False,
        "is_buy_to_let": False,
        "has_one_day_maturity_floor": False,
        "facility_termination_date": None,
    }


def _loan(
    ref: str,
    cp_ref: str,
    drawn_amount: float = 1_000_000.0,
) -> dict:
    return {
        "loan_reference": ref,
        "product_type": "term_loan",
        "book_code": "MAIN",
        "counterparty_reference": cp_ref,
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2030, 12, 31),
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
    }


def _rating(
    cp_ref: str,
    cqs: int,
    rating_type: str = "external",
    agency: str = "S&P",
    rating_value: str = "A",
    pd: float | None = None,
) -> dict:
    return {
        "rating_reference": f"RAT_{cp_ref}",
        "counterparty_reference": cp_ref,
        "rating_type": rating_type,
        "rating_agency": agency,
        "rating_value": rating_value,
        "cqs": cqs,
        "pd": pd,
        "rating_date": date(2025, 6, 1),
        "is_solicited": True,
        "model_id": None,
    }


def _guarantee(
    ref: str,
    guarantor: str,
    beneficiary_ref: str,
    amount: float,
    *,
    guarantee_type: str = "bank_guarantee",
    currency: str = "GBP",
    protection_type: str = "guarantee",
    includes_restructuring: bool | None = None,
    percentage_covered: float | None = None,
) -> dict:
    return {
        "guarantee_reference": ref,
        "guarantee_type": guarantee_type,
        "guarantor": guarantor,
        "currency": currency,
        "maturity_date": date(2030, 12, 31),
        "amount_covered": amount,
        "percentage_covered": percentage_covered,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "protection_type": protection_type,
        "includes_restructuring": includes_restructuring,
    }


def _collateral(
    ref: str,
    beneficiary_ref: str,
    collateral_type: str,
    market_value: float,
    *,
    currency: str = "GBP",
    issuer_cqs: int | None = None,
    issuer_type: str | None = None,
    residual_maturity_years: float | None = None,
    is_eligible_financial: bool = True,
) -> dict:
    return {
        "collateral_reference": ref,
        "collateral_type": collateral_type,
        "currency": currency,
        "maturity_date": None,
        "market_value": market_value,
        "nominal_value": market_value,
        "pledge_percentage": None,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "issuer_cqs": issuer_cqs,
        "issuer_type": issuer_type,
        "residual_maturity_years": residual_maturity_years,
        "original_maturity_years": None,
        "is_eligible_financial_collateral": is_eligible_financial,
        "is_eligible_irb_collateral": is_eligible_financial,
        "valuation_date": date(2025, 12, 31),
        "valuation_type": "market",
        "property_type": None,
        "property_ltv": None,
        "is_income_producing": None,
        "is_adc": None,
        "is_presold": None,
        "is_qualifying_re": None,
        "prior_charge_ltv": None,
        "liquidation_period_days": None,
        "qualifies_for_zero_haircut": None,
        "insurer_risk_weight": None,
        "credit_event_reduction": None,
    }


def _provision(
    ref: str,
    beneficiary_ref: str,
    amount: float,
    *,
    provision_type: str = "scra",
    ifrs9_stage: int = 2,
) -> dict:
    return {
        "provision_reference": ref,
        "provision_type": provision_type,
        "ifrs9_stage": ifrs9_stage,
        "currency": "GBP",
        "amount": amount,
        "as_of_date": date(2025, 12, 31),
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
    }


def _empty_mappings() -> tuple[pl.LazyFrame, pl.LazyFrame]:
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
    return fac_map, lend_map


def _run_pipeline(
    counterparties: list[dict],
    facilities: list[dict],
    loans: list[dict],
    *,
    ratings: list[dict] | None = None,
    guarantees: list[dict] | None = None,
    collateral: list[dict] | None = None,
    provisions: list[dict] | None = None,
):
    """Run the CRR SA pipeline and return the orchestrator result."""
    fac_map, lend_map = _empty_mappings()
    bundle = RawDataBundle(
        facilities=pl.LazyFrame(facilities, schema=_FACILITY_SCHEMA),
        loans=pl.LazyFrame(loans, schema=_LOAN_SCHEMA),
        counterparties=pl.LazyFrame(counterparties, schema=_COUNTERPARTY_SCHEMA),
        facility_mappings=fac_map,
        lending_mappings=lend_map,
        ratings=pl.LazyFrame(ratings, schema=_RATING_SCHEMA) if ratings else None,
        guarantees=(
            pl.LazyFrame(guarantees, schema=_GUARANTEE_SCHEMA) if guarantees else None
        ),
        collateral=(
            pl.LazyFrame(collateral, schema=_COLLATERAL_SCHEMA) if collateral else None
        ),
        provisions=(
            pl.LazyFrame(provisions, schema=_PROVISION_SCHEMA) if provisions else None
        ),
    )
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_rows(results, loan_ref: str) -> list[dict]:
    """Find all exposure rows matching *loan_ref* across result sets."""
    rows: list[dict] = []
    for lf in [results.sa_results, results.irb_results, results.slotting_results]:
        if lf is None:
            continue
        df = lf.filter(
            pl.col("exposure_reference").str.contains(loan_ref)
        ).collect()
        rows.extend(df.to_dicts())
    return rows


def _find_single(results, loan_ref: str) -> dict:
    """Find exactly one exposure row matching *loan_ref*."""
    rows = _find_rows(results, loan_ref)
    assert len(rows) >= 1, f"Exposure {loan_ref!r} not found in any result set"
    return rows[0]


def _total_rwa(rows: list[dict]) -> float:
    """Sum rwa_final across all rows (handles guarantee sub-row splits)."""
    return sum(r.get("rwa_final", 0.0) or 0.0 for r in rows)


def _total_ead(rows: list[dict]) -> float:
    """Sum ead_final across all rows."""
    return sum(r.get("ead_final", 0.0) or 0.0 for r in rows)


# ===================================================================
# CRR-D7: Non-beneficial guarantee (guarantor RW >= borrower RW)
# ===================================================================
class TestCRRD7_NonBeneficialGuarantee:
    """Guarantee where guarantor has same/higher RW as borrower -> no benefit.

    Borrower: unrated corporate (100% RW)
    Guarantor: unrated corporate (100% RW)
    Full guarantee coverage on GBP 1M loan.

    Expected: RW stays at 100%, RWA = 1M. Guarantee substitution provides no
    capital relief because the guarantor's RW is not lower than the borrower's.

    Reference: CRR Art. 235 — substitution only when beneficial.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[
                _counterparty("CP_D7", entity_type="corporate"),
                _counterparty("CP_D7_G", entity_type="corporate"),
            ],
            facilities=[_facility("FAC_D7", "CP_D7")],
            loans=[_loan("LOAN_D7", "CP_D7", drawn_amount=1_000_000.0)],
            guarantees=[
                _guarantee("GUAR_D7", "CP_D7_G", "LOAN_D7", 1_000_000.0),
            ],
        )

    def test_rwa_equals_unprotected(self, result):
        """RWA should equal the unprotected RWA (no benefit from guarantee)."""
        rows = _find_rows(result, "LOAN_D7")
        rwa = _total_rwa(rows)
        # Unprotected: 1M × 100% = 1M
        assert rwa == pytest.approx(1_000_000.0, rel=0.01)

    def test_risk_weight_unchanged(self, result):
        """Risk weight should remain at 100% (unrated corporate)."""
        rows = _find_rows(result, "LOAN_D7")
        # All rows should have 100% effective RW
        for row in rows:
            if row.get("risk_weight") is not None:
                assert row["risk_weight"] == pytest.approx(1.0, abs=0.01)

    def test_ead_not_reduced(self, result):
        """EAD should not be reduced (guarantee substitutes RW, not EAD)."""
        rows = _find_rows(result, "LOAN_D7")
        ead = _total_ead(rows)
        assert ead == pytest.approx(1_000_000.0, rel=0.01)


# ===================================================================
# CRR-D8: Sovereign guarantee — full substitution to 0% RW
# ===================================================================
class TestCRRD8_SovereignGuarantee:
    """UK sovereign guarantees a corporate loan -> 0% RW substitution.

    Borrower: unrated corporate (100% RW)
    Guarantor: UK sovereign (CQS 0, 0% RW)
    Full guarantee coverage on GBP 1M loan.

    Expected: RWA near 0 (full substitution to 0% sovereign RW).

    Reference: CRR Art. 235 — substitution with sovereign RW.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[
                _counterparty("CP_D8", entity_type="corporate"),
                _counterparty(
                    "CP_D8_G",
                    entity_type="sovereign",
                    country_code="GB",
                    sovereign_cqs=0,
                ),
            ],
            facilities=[_facility("FAC_D8", "CP_D8")],
            loans=[_loan("LOAN_D8", "CP_D8", drawn_amount=1_000_000.0)],
            ratings=[_rating("CP_D8_G", cqs=0, rating_value="AAA")],
            guarantees=[
                _guarantee(
                    "GUAR_D8",
                    "CP_D8_G",
                    "LOAN_D8",
                    1_000_000.0,
                    guarantee_type="sovereign_guarantee",
                ),
            ],
        )

    def test_rwa_near_zero(self, result):
        """RWA should be near zero with sovereign 0% RW substitution."""
        rows = _find_rows(result, "LOAN_D8")
        rwa = _total_rwa(rows)
        assert rwa < 10_000.0, f"Expected near-zero RWA, got {rwa:,.0f}"

    def test_ead_preserved(self, result):
        """EAD should be preserved (guarantee substitutes RW, not EAD)."""
        rows = _find_rows(result, "LOAN_D8")
        ead = _total_ead(rows)
        assert ead == pytest.approx(1_000_000.0, rel=0.01)

    def test_significantly_less_than_unprotected(self, result):
        """RWA should be significantly less than unprotected 1M."""
        rows = _find_rows(result, "LOAN_D8")
        rwa = _total_rwa(rows)
        assert rwa < 100_000.0


# ===================================================================
# CRR-D9: CDS restructuring exclusion (Art. 216(1) / Art. 233(2))
# ===================================================================
class TestCRRD9_CDSRestructuringExclusion:
    """Credit derivative without restructuring clause -> 40% protection reduction.

    Borrower: unrated corporate (100% RW), GBP 1M
    Protection provider: CQS 1 institution (20% RW)
    Protection: credit derivative, full 1M coverage, includes_restructuring=False
    CDS restructuring exclusion: 40% reduction -> effective protection = 600k

    Expected: RWA = 600k × 0.20 + 400k × 1.00 = 520k (approximately)

    Reference: CRR Art. 216(1) restructuring exclusion, Art. 233(2) haircut.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[
                _counterparty("CP_D9", entity_type="corporate"),
                _counterparty("CP_D9_G", entity_type="institution", institution_cqs=1),
            ],
            facilities=[_facility("FAC_D9", "CP_D9")],
            loans=[_loan("LOAN_D9", "CP_D9", drawn_amount=1_000_000.0)],
            ratings=[_rating("CP_D9_G", cqs=1, rating_value="AA")],
            guarantees=[
                _guarantee(
                    "GUAR_D9",
                    "CP_D9_G",
                    "LOAN_D9",
                    1_000_000.0,
                    protection_type="credit_derivative",
                    includes_restructuring=False,
                ),
            ],
        )

    def test_rwa_between_protected_and_unprotected(self, result):
        """RWA should be between fully-protected (200k) and unprotected (1M).

        With 40% CDS haircut: effective protection ~600k.
        RWA ≈ 600k × 20% + 400k × 100% = 520k.
        """
        rows = _find_rows(result, "LOAN_D9")
        rwa = _total_rwa(rows)
        assert 200_000 < rwa < 1_000_000, (
            f"Expected RWA between 200k and 1M, got {rwa:,.0f}"
        )

    def test_rwa_less_than_unprotected(self, result):
        """CDS still provides some benefit despite the 40% haircut."""
        rows = _find_rows(result, "LOAN_D9")
        rwa = _total_rwa(rows)
        assert rwa < 1_000_000.0

    def test_rwa_more_than_full_guarantee(self, result):
        """RWA should exceed what a full guarantee (no haircut) would produce.

        Full 1M guarantee at 20% RW = 200k RWA. With 40% haircut, RWA > 200k.
        """
        rows = _find_rows(result, "LOAN_D9")
        rwa = _total_rwa(rows)
        assert rwa > 200_000.0


# ===================================================================
# CRR-D9b: CDS with restructuring included (no haircut)
# ===================================================================
class TestCRRD9b_CDSWithRestructuring:
    """Credit derivative with restructuring included -> no haircut.

    Same setup as D9 but includes_restructuring=True.
    Expected: full protection benefit, RWA ≈ 200k (1M × 20% RW).

    Reference: CRR Art. 233(2) — haircut only when restructuring excluded.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[
                _counterparty("CP_D9B", entity_type="corporate"),
                _counterparty(
                    "CP_D9B_G", entity_type="institution", institution_cqs=1
                ),
            ],
            facilities=[_facility("FAC_D9B", "CP_D9B")],
            loans=[_loan("LOAN_D9B", "CP_D9B", drawn_amount=1_000_000.0)],
            ratings=[_rating("CP_D9B_G", cqs=1, rating_value="AA")],
            guarantees=[
                _guarantee(
                    "GUAR_D9B",
                    "CP_D9B_G",
                    "LOAN_D9B",
                    1_000_000.0,
                    protection_type="credit_derivative",
                    includes_restructuring=True,
                ),
            ],
        )

    def test_rwa_near_fully_substituted(self, result):
        """RWA should be near 200k (fully substituted to institution 20% RW)."""
        rows = _find_rows(result, "LOAN_D9B")
        rwa = _total_rwa(rows)
        assert rwa == pytest.approx(200_000.0, rel=0.15)

    def test_rwa_less_than_cds_without_restructuring(self, result):
        """RWA with restructuring < RWA without restructuring (no 40% haircut)."""
        rows = _find_rows(result, "LOAN_D9B")
        rwa = _total_rwa(rows)
        # D9 (without restructuring) gives ~520k; D9b should be ~200k
        assert rwa < 400_000.0


# ===================================================================
# CRR-D10: Gold collateral (15% CRR supervisory haircut)
# ===================================================================
class TestCRRD10_GoldCollateral:
    """Gold collateral at CRR 15% supervisory haircut.

    Borrower: unrated corporate (100% RW), GBP 1M drawn
    Collateral: gold, market value GBP 500k
    After 15% haircut: recognised value = 500k × (1 - 0.15) = 425k
    EAD = max(0, 1M - 425k) = 575k

    Expected: EAD ≈ 575k, RWA ≈ 575k (100% RW).

    Reference: CRR Art. 224 Table 4 — gold haircut 15%.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_D10", entity_type="corporate")],
            facilities=[_facility("FAC_D10", "CP_D10")],
            loans=[_loan("LOAN_D10", "CP_D10", drawn_amount=1_000_000.0)],
            collateral=[
                _collateral(
                    "COLL_D10",
                    "LOAN_D10",
                    "gold",
                    500_000.0,
                ),
            ],
        )

    def test_ead_reduced_by_gold(self, result):
        """EAD should be reduced from 1M by gold collateral minus haircut."""
        rows = _find_rows(result, "LOAN_D10")
        ead = _total_ead(rows)
        # Expected: 1M - 500k × 0.85 = 575k
        assert ead == pytest.approx(575_000.0, rel=0.05)

    def test_rwa_reduced(self, result):
        """RWA should be less than unprotected 1M."""
        rows = _find_rows(result, "LOAN_D10")
        rwa = _total_rwa(rows)
        assert rwa < 1_000_000.0

    def test_rwa_consistent_with_ead(self, result):
        """RWA ≈ EAD × 100% for unrated corporate."""
        rows = _find_rows(result, "LOAN_D10")
        rwa = _total_rwa(rows)
        ead = _total_ead(rows)
        assert rwa == pytest.approx(ead, rel=0.05)


# ===================================================================
# CRR-D11: Equity collateral (15% CRR main-index haircut)
# ===================================================================
class TestCRRD11_EquityCollateral:
    """Equity collateral at CRR 15% main-index supervisory haircut.

    Borrower: unrated corporate (100% RW), GBP 1M drawn
    Collateral: equity, market value GBP 500k
    After 15% haircut: recognised value = 500k × (1 - 0.15) = 425k
    EAD = max(0, 1M - 425k) = 575k

    Expected: EAD ≈ 575k, RWA ≈ 575k.

    Note: The ``is_main_index`` field on COLLATERAL_SCHEMA now drives the
    haircut lookup (P6.21). When absent, falls back to
    ``is_eligible_financial_collateral`` for backward compatibility.

    Reference: CRR Art. 224 Table 4 — main-index equity haircut 15%.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_D11", entity_type="corporate")],
            facilities=[_facility("FAC_D11", "CP_D11")],
            loans=[_loan("LOAN_D11", "CP_D11", drawn_amount=1_000_000.0)],
            collateral=[
                _collateral(
                    "COLL_D11",
                    "LOAN_D11",
                    "equity",
                    500_000.0,
                ),
            ],
        )

    def test_ead_reduced_by_equity(self, result):
        """EAD should be reduced from 1M by equity collateral minus 15% haircut."""
        rows = _find_rows(result, "LOAN_D11")
        ead = _total_ead(rows)
        # Expected: 1M - 500k × 0.85 = 575k (main-index 15% haircut)
        assert ead == pytest.approx(575_000.0, rel=0.05)

    def test_rwa_consistent_with_ead(self, result):
        """RWA ≈ EAD × 100% for unrated corporate."""
        rows = _find_rows(result, "LOAN_D11")
        rwa = _total_rwa(rows)
        ead = _total_ead(rows)
        assert rwa == pytest.approx(ead, rel=0.05)

    def test_same_haircut_as_gold(self, result):
        """Equity (main-index 15%) gives same EAD reduction as gold (15%).

        Both gold and main-index equity have 15% CRR haircut.
        """
        rows = _find_rows(result, "LOAN_D11")
        ead = _total_ead(rows)
        assert ead == pytest.approx(575_000.0, rel=0.05)


# ===================================================================
# CRR-D12: Overcollateralised exposure (EAD floored at 0)
# ===================================================================
class TestCRRD12_Overcollateralised:
    """Cash collateral exceeds exposure -> EAD floored at 0.

    Borrower: unrated corporate (100% RW), GBP 500k drawn
    Collateral: cash GBP 700k (0% haircut)
    After 0% haircut: recognised value = 700k > 500k EAD
    EAD = max(0, 500k - 700k) = 0

    Expected: EAD = 0, RWA = 0.

    Reference: CRR Art. 223 — EAD after CRM cannot be negative.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_D12", entity_type="corporate")],
            facilities=[_facility("FAC_D12", "CP_D12")],
            loans=[_loan("LOAN_D12", "CP_D12", drawn_amount=500_000.0)],
            collateral=[
                _collateral("COLL_D12", "LOAN_D12", "cash", 700_000.0),
            ],
        )

    def test_rwa_zero(self, result):
        """RWA should be zero when fully overcollateralised."""
        rows = _find_rows(result, "LOAN_D12")
        rwa = _total_rwa(rows)
        assert rwa == pytest.approx(0.0, abs=1.0)

    def test_ead_zero(self, result):
        """EAD should be zero (floored, not negative)."""
        rows = _find_rows(result, "LOAN_D12")
        ead = _total_ead(rows)
        assert ead == pytest.approx(0.0, abs=1.0)


# ===================================================================
# CRR-D13: Full CRM chain (provision + collateral + guarantee)
# ===================================================================
class TestCRRD13_FullCRMChain:
    """Combined provision + cash collateral + bank guarantee on one exposure.

    Borrower: unrated corporate (100% RW), GBP 1M drawn
    Provision: GBP 100k specific provision (SA deduction from drawn)
    Collateral: cash GBP 300k (0% haircut)
    Guarantee: GBP 200k from CQS 1 institution (20% RW)

    CRM waterfall:
    1. Provision: drawn_after_provision = 1M - 100k = 900k
    2. EAD_gross = 900k
    3. Collateral: 300k cash (0% haircut) -> EAD_after_collateral = 600k
    4. Guarantee: 200k at guarantor RW 20%, 400k at borrower RW 100%

    Expected: RWA ≈ 200k × 0.20 + 400k × 1.00 = 440k (approximately).

    Reference: CRR Art. 110 (provisions), Art. 224 (collateral), Art. 235 (guarantee).
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[
                _counterparty("CP_D13", entity_type="corporate"),
                _counterparty(
                    "CP_D13_G", entity_type="institution", institution_cqs=1
                ),
            ],
            facilities=[_facility("FAC_D13", "CP_D13")],
            loans=[_loan("LOAN_D13", "CP_D13", drawn_amount=1_000_000.0)],
            ratings=[_rating("CP_D13_G", cqs=1, rating_value="AA")],
            guarantees=[
                _guarantee("GUAR_D13", "CP_D13_G", "LOAN_D13", 200_000.0),
            ],
            collateral=[
                _collateral("COLL_D13", "LOAN_D13", "cash", 300_000.0),
            ],
            provisions=[
                _provision("PROV_D13", "LOAN_D13", 100_000.0),
            ],
        )

    def test_rwa_significantly_reduced(self, result):
        """RWA should be well below unprotected 1M."""
        rows = _find_rows(result, "LOAN_D13")
        rwa = _total_rwa(rows)
        # All three CRM mechanisms reduce capital
        assert rwa < 600_000.0

    def test_rwa_above_zero(self, result):
        """Exposure not fully eliminated by CRM."""
        rows = _find_rows(result, "LOAN_D13")
        rwa = _total_rwa(rows)
        assert rwa > 0.0

    def test_ead_reduced_by_provision_and_collateral(self, result):
        """EAD should reflect both provision deduction and collateral reduction."""
        rows = _find_rows(result, "LOAN_D13")
        ead = _total_ead(rows)
        # EAD should be less than 900k (post-provision, pre-collateral)
        # and less than 1M (unprotected)
        assert ead < 900_000.0
        assert ead > 0.0

    def test_all_three_crm_mechanisms_contribute(self, result):
        """Each CRM mechanism (provision, collateral, guarantee) reduces total RWA
        below what the others alone would achieve.

        Unprotected: 1M. Provision-only: 900k. Provision+collateral: 600k.
        Full chain should be less than 600k.
        """
        rows = _find_rows(result, "LOAN_D13")
        rwa = _total_rwa(rows)
        assert rwa < 600_000.0


# ===================================================================
# CRR-D14: Mixed collateral types (cash + bond, different haircuts)
# ===================================================================
class TestCRRD14_MixedCollateral:
    """Two collateral types with different haircuts on one exposure.

    Borrower: unrated corporate (100% RW), GBP 2M drawn
    Collateral 1: cash GBP 500k (0% haircut) -> recognised 500k
    Collateral 2: CQS 1 sovereign bond, 6yr residual maturity, GBP 500k
                  CRR 3-band >5yr haircut = 4% -> recognised 480k
    Total recognised: 980k
    EAD = max(0, 2M - 980k) = 1.02M

    Expected: EAD ≈ 1.02M, RWA ≈ 1.02M.

    Reference: CRR Art. 224 Table 4 — cash 0%, CQS 1 sovereign bond >5yr 4%.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_D14", entity_type="corporate")],
            facilities=[_facility("FAC_D14", "CP_D14")],
            loans=[_loan("LOAN_D14", "CP_D14", drawn_amount=2_000_000.0)],
            collateral=[
                _collateral("COLL_D14A", "LOAN_D14", "cash", 500_000.0),
                _collateral(
                    "COLL_D14B",
                    "LOAN_D14",
                    "bond",
                    500_000.0,
                    issuer_cqs=1,
                    issuer_type="sovereign",
                    residual_maturity_years=6.0,
                ),
            ],
        )

    def test_ead_reduced_by_both(self, result):
        """EAD should be reduced by both collateral items."""
        rows = _find_rows(result, "LOAN_D14")
        ead = _total_ead(rows)
        # Cash: 500k × 1.0 = 500k recognised
        # Bond: 500k × 0.96 = 480k recognised
        # EAD ≈ 2M - 980k = 1.02M
        assert ead == pytest.approx(1_020_000.0, rel=0.05)

    def test_rwa_consistent(self, result):
        """RWA ≈ EAD × 100% for unrated corporate."""
        rows = _find_rows(result, "LOAN_D14")
        rwa = _total_rwa(rows)
        ead = _total_ead(rows)
        assert rwa == pytest.approx(ead, rel=0.05)

    def test_rwa_less_than_unprotected(self, result):
        """RWA should be less than the unprotected 2M."""
        rows = _find_rows(result, "LOAN_D14")
        rwa = _total_rwa(rows)
        assert rwa < 2_000_000.0


# ===================================================================
# CRR-G4: SA provision EAD reduction (drawn-first deduction)
# ===================================================================
class TestCRRG4_ProvisionSADeduction:
    """Provision reduces EAD under SA (drawn-first deduction).

    Borrower: unrated corporate (100% RW), GBP 500k drawn
    Provision: GBP 150k specific provision

    Under SA, provision is deducted from drawn amount first:
    drawn_after_provision = max(0, 500k - 150k) = 350k
    EAD = 350k

    Expected: EAD ≈ 350k, RWA ≈ 350k.

    Reference: CRR Art. 110 — SA provisions deducted from exposure value.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_G4", entity_type="corporate")],
            facilities=[_facility("FAC_G4", "CP_G4")],
            loans=[_loan("LOAN_G4", "CP_G4", drawn_amount=500_000.0)],
            provisions=[
                _provision("PROV_G4", "LOAN_G4", 150_000.0),
            ],
        )

    def test_ead_reduced(self, result):
        """EAD should be reduced by the provision amount."""
        rows = _find_rows(result, "LOAN_G4")
        ead = _total_ead(rows)
        assert ead == pytest.approx(350_000.0, rel=0.05)

    def test_rwa_reduced(self, result):
        """RWA should reflect the reduced EAD."""
        rows = _find_rows(result, "LOAN_G4")
        rwa = _total_rwa(rows)
        assert rwa == pytest.approx(350_000.0, rel=0.05)

    def test_rwa_less_than_unprotected(self, result):
        """RWA < 500k (unprotected)."""
        rows = _find_rows(result, "LOAN_G4")
        rwa = _total_rwa(rows)
        assert rwa < 500_000.0


# ===================================================================
# CRR-G5: Multiple provisions on same exposure (summed)
# ===================================================================
class TestCRRG5_MultipleProvisions:
    """Two provisions targeting the same exposure are summed.

    Borrower: unrated corporate (100% RW), GBP 1M drawn
    Provision 1: GBP 100k (Stage 2 SCRA)
    Provision 2: GBP 50k (Stage 1 SCRA)
    Total provision: 150k

    Expected: EAD ≈ 850k, RWA ≈ 850k.

    Reference: CRR Art. 110 — all eligible provisions deducted.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_G5", entity_type="corporate")],
            facilities=[_facility("FAC_G5", "CP_G5")],
            loans=[_loan("LOAN_G5", "CP_G5", drawn_amount=1_000_000.0)],
            provisions=[
                _provision("PROV_G5A", "LOAN_G5", 100_000.0, ifrs9_stage=2),
                _provision("PROV_G5B", "LOAN_G5", 50_000.0, ifrs9_stage=1),
            ],
        )

    def test_ead_reduced_by_total_provision(self, result):
        """EAD should reflect the sum of both provisions."""
        rows = _find_rows(result, "LOAN_G5")
        ead = _total_ead(rows)
        assert ead == pytest.approx(850_000.0, rel=0.05)

    def test_rwa_reduced(self, result):
        """RWA ≈ 850k (100% RW × 850k EAD)."""
        rows = _find_rows(result, "LOAN_G5")
        rwa = _total_rwa(rows)
        assert rwa == pytest.approx(850_000.0, rel=0.05)


# ===================================================================
# CRR-G6: Provision + collateral combined
# ===================================================================
class TestCRRG6_ProvisionAndCollateral:
    """Provision and collateral both applied to the same exposure.

    Borrower: unrated corporate (100% RW), GBP 1M drawn
    Provision: GBP 200k (deducted first from drawn)
    Collateral: cash GBP 300k (0% haircut, applied after provision)

    Flow:
    1. Provision deduction: EAD_post_provision = 800k
    2. Collateral: EAD_after_collateral = max(0, 800k - 300k) = 500k

    Expected: EAD ≈ 500k, RWA ≈ 500k.

    Reference: CRR Art. 110 (provision), Art. 224 (collateral).
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline(
            counterparties=[_counterparty("CP_G6", entity_type="corporate")],
            facilities=[_facility("FAC_G6", "CP_G6")],
            loans=[_loan("LOAN_G6", "CP_G6", drawn_amount=1_000_000.0)],
            collateral=[
                _collateral("COLL_G6", "LOAN_G6", "cash", 300_000.0),
            ],
            provisions=[
                _provision("PROV_G6", "LOAN_G6", 200_000.0),
            ],
        )

    def test_ead_reduced_by_both(self, result):
        """EAD should reflect both provision deduction and collateral reduction."""
        rows = _find_rows(result, "LOAN_G6")
        ead = _total_ead(rows)
        # Post-provision: 800k. Post-collateral: 500k.
        assert ead == pytest.approx(500_000.0, rel=0.05)

    def test_rwa_reduced(self, result):
        """RWA ≈ 500k."""
        rows = _find_rows(result, "LOAN_G6")
        rwa = _total_rwa(rows)
        assert rwa == pytest.approx(500_000.0, rel=0.05)

    def test_rwa_less_than_provision_only(self, result):
        """Adding collateral should reduce RWA below provision-only (800k)."""
        rows = _find_rows(result, "LOAN_G6")
        rwa = _total_rwa(rows)
        assert rwa < 800_000.0


# ===================================================================
# Structural validation
# ===================================================================
class TestCRRD2_StructuralValidation:
    """Cross-scenario structural checks."""

    @pytest.fixture(scope="class")
    def baseline_result(self):
        """Unprotected corporate 1M for RWA comparison."""
        return _run_pipeline(
            counterparties=[_counterparty("CP_BASE", entity_type="corporate")],
            facilities=[_facility("FAC_BASE", "CP_BASE")],
            loans=[_loan("LOAN_BASE", "CP_BASE", drawn_amount=1_000_000.0)],
        )

    def test_baseline_rwa(self, baseline_result):
        """Unprotected corporate at 100% RW should have RWA = 1M."""
        rows = _find_rows(baseline_result, "LOAN_BASE")
        rwa = _total_rwa(rows)
        assert rwa == pytest.approx(1_000_000.0, rel=0.01)

    def test_baseline_ead(self, baseline_result):
        """Unprotected EAD should equal drawn amount."""
        rows = _find_rows(baseline_result, "LOAN_BASE")
        ead = _total_ead(rows)
        assert ead == pytest.approx(1_000_000.0, rel=0.01)
