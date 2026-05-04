"""
Integration tests: end-to-end pipeline with mixed RRE+CRE collateral.

Verifies that a single SA exposure secured by both residential and
commercial property is partitioned through the full pipeline:

    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> RealEstateSplitter (mixed-aware) -> SACalculator -> Aggregator

into the regulatorily-required component rows:

- **PRA PS1/26 Art. 124(4) (Basel 3.1):** pro-rata by collateral value.
  Each component's secured EAD = min(EAD × component_share, 0.55 ×
  component_value); residual goes to counterparty RW per Art. 124L.
- **CRR Art. 124(1) "any part of an exposure" (legacy):** RRE-first
  sequential — RRE consumes up to its 80% LTV cap (Art. 125), then CRE
  on the remainder up to its 50% LTV cap (Art. 126 with rental cov).

References:
- PRA PS1/26 Art. 124(4): mixed RE pro-rata mandatory split.
- PRA PS1/26 Art. 124F: B3.1 RRE 20% on portion up to 55% LTV.
- PRA PS1/26 Art. 124H(1)-(2): B3.1 CRE NP/SME 60% on portion up to 55% LTV.
- CRR Art. 124(1): "any part of an exposure" framing for partial security.
- CRR Art. 125: RRE 35% on portion up to 80% LTV.
- CRR Art. 126: CRE 50% on portion up to 50% LTV (rental cov gate).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_REPORTING_DATE = date(2026, 12, 31)
_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 12, 31)


def _build_mixed_collateral_bundle(
    *,
    loan_amount: float,
    rre_value: float,
    cre_value: float,
    rental_to_interest_ratio: float | None = None,
    annual_revenue: float = 10_000_000.0,
) -> RawDataBundle:
    """Corporate borrower with one loan secured by RRE + CRE collateral.

    The hierarchy resolver aggregates both real-estate collateral rows
    onto the loan via beneficiary_reference, populating
    ``residential_collateral_value`` (RRE only) and
    ``property_collateral_value`` (RRE + CRE total) on the exposure.
    """
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
    return RawDataBundle(
        counterparties=pl.LazyFrame(
            {
                "counterparty_reference": ["CP_MIX"],
                "counterparty_name": ["Mixed Collateral Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                # Caller controls SME-ness via annual_revenue. Below the
                # B3.1 SME threshold (GBP 44m) → SME, routing the CRE-
                # secured component through Art. 124H(1)/(2) with the 60%
                # loan-split RW. Above → Art. 124H(3) max(60%, cp_rw).
                "annual_revenue": [annual_revenue],
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
        ),
        facilities=pl.LazyFrame(
            schema={
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
        ),
        loans=pl.LazyFrame(
            {
                "loan_reference": ["LOAN_MIX"],
                "product_type": ["term_loan"],
                "book_code": ["BANK"],
                "counterparty_reference": ["CP_MIX"],
                "value_date": [_VALUE_DATE],
                "maturity_date": [_MATURITY_DATE],
                "currency": ["GBP"],
                "drawn_amount": [loan_amount],
                "interest": [0.0],
                "lgd": [0.45],
                "lgd_unsecured": [0.45],
                "has_sufficient_collateral_data": [True],
                "beel": [None],
                "seniority": ["senior"],
                "is_payroll_loan": [False],
                "is_buy_to_let": [False],
                "has_one_day_maturity_floor": [False],
                "has_netting_agreement": [False],
                "netting_facility_reference": [None],
                "due_diligence_performed": [None],
                "due_diligence_override_rw": [None],
            }
        ),
        facility_mappings=fac_map,
        lending_mappings=lend_map,
        collateral=pl.LazyFrame(
            {
                "collateral_reference": ["RRE_COLL_MIX", "CRE_COLL_MIX"],
                "collateral_type": ["real_estate", "real_estate"],
                "currency": ["GBP", "GBP"],
                "maturity_date": [None, None],
                "market_value": [rre_value, cre_value],
                "nominal_value": [rre_value, cre_value],
                "pledge_percentage": [None, None],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["LOAN_MIX", "LOAN_MIX"],
                "issuer_cqs": [None, None],
                "issuer_type": [None, None],
                "residual_maturity_years": [None, None],
                "original_maturity_years": [None, None],
                "is_eligible_financial_collateral": [False, False],
                "is_eligible_irb_collateral": [True, True],
                "is_main_index": [None, None],
                "valuation_date": [_REPORTING_DATE, _REPORTING_DATE],
                "valuation_type": ["market", "market"],
                "property_type": ["residential", "commercial"],
                "property_ltv": [1.0, 1.0],
                "is_income_producing": [False, False],
                "is_adc": [False, False],
                "is_presold": [False, False],
                "is_qualifying_re": [True, True],
                "prior_charge_ltv": [0.0, 0.0],
                "liquidation_period_days": [None, None],
                "qualifies_for_zero_haircut": [False, False],
                "insurer_risk_weight": [None, None],
                "credit_event_reduction": [0.0, 0.0],
                "rental_to_interest_ratio": [None, rental_to_interest_ratio],
            }
        ),
    )


def _run(bundle: RawDataBundle, config: CalculationConfig) -> pl.DataFrame:
    result = PipelineOrchestrator().run_with_data(bundle, config)
    assert result.results is not None
    df = result.results.collect()
    assert isinstance(df, pl.DataFrame)
    return df


# ---------------------------------------------------------------------------
# Basel 3.1 — Art. 124(4) pro-rata mandatory split
# ---------------------------------------------------------------------------


class TestB31MixedCollateralEndToEnd:
    """PRA PS1/26 Art. 124(4) — pro-rata by collateral value."""

    def test_corporate_mixed_60_40_emits_rre_cre_residual(self) -> None:
        """SME corporate £1M / RRE £600K / CRE £400K → 3 rows.

        Pro-rata: rre_share=0.6, cre_share=0.4.
        rre_secured = min(£1M × 0.6, 0.55 × £600K) = min(£600K, £330K) = £330K
        cre_secured = min(£1M × 0.4, 0.55 × £400K) = min(£400K, £220K) = £220K
        residual = £1M − £330K − £220K = £450K

        Hand-calc RWA (SME counterparty, so Art. 124H(1)/(2) for CRE):
            RRE @ Art. 124F (LTV = £330K / £600K = 55% → 20%): £66,000
            CRE @ Art. 124H(1) SME (LTV = £220K / £400K = 55% → 60%): £132,000
            Residual @ unrated SME corporate (Art. 122 SME = 85%): £382,500
            Total: £580,500
        """
        bundle = _build_mixed_collateral_bundle(
            loan_amount=1_000_000.0, rre_value=600_000.0, cre_value=400_000.0
        )
        config = CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
        df = _run(bundle, config)

        children = df.filter(pl.col("exposure_reference").str.contains("LOAN_MIX"))
        assert children.height == 3, "expected secured_rre + secured_cre + residual"

        rows = {r["re_split_role"]: r for r in children.to_dicts()}
        rre = rows["secured_rre"]
        cre = rows["secured_cre"]
        residual = rows["residual"]

        assert rre["exposure_class"] == "residential_mortgage"
        assert rre["ead_final"] == pytest.approx(330_000.0, rel=1e-6)
        assert rre["risk_weight"] == pytest.approx(0.20, rel=1e-6)

        assert cre["exposure_class"] == "commercial_mortgage"
        assert cre["ead_final"] == pytest.approx(220_000.0, rel=1e-6)
        assert cre["risk_weight"] == pytest.approx(0.60, rel=1e-6)

        # Residual: SME unrated corporate → Art. 122 SME = 85%.
        assert residual["ead_final"] == pytest.approx(450_000.0, rel=1e-6)
        assert residual["risk_weight"] == pytest.approx(0.85, rel=1e-6)

        # Reconciliation: child EADs sum to parent.
        total_ead = rre["ead_final"] + cre["ead_final"] + residual["ead_final"]
        assert total_ead == pytest.approx(1_000_000.0, rel=1e-6)

    def test_corporate_mixed_total_rwa_matches_hand_calc(self) -> None:
        """Sum of secured_rre + secured_cre + residual RWA = expected total."""
        bundle = _build_mixed_collateral_bundle(
            loan_amount=1_000_000.0, rre_value=600_000.0, cre_value=400_000.0
        )
        config = CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
        df = _run(bundle, config)

        total_rwa = df.filter(pl.col("exposure_reference").str.contains("LOAN_MIX"))[
            "rwa_final"
        ].sum()
        # 330k × 20% + 220k × 60% + 450k × 85% = 66k + 132k + 382.5k = 580.5k
        assert total_rwa == pytest.approx(580_500.0, rel=1e-3)

    def test_pure_rre_only_no_cre_collateral_uses_secured_role(self) -> None:
        """Regression: pure-RRE exposure under B3.1 still uses 'secured' role."""
        bundle = _build_mixed_collateral_bundle(
            loan_amount=1_000_000.0, rre_value=1_000_000.0, cre_value=0.0
        )
        config = CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
        df = _run(bundle, config)

        children = df.filter(pl.col("exposure_reference").str.contains("LOAN_MIX"))
        # 0 EAD on the CRE collateral row may or may not be filtered — check
        # only that a single 'secured' (non-mixed) row exists.
        roles = set(children["re_split_role"].drop_nulls().to_list())
        assert "secured" in roles
        assert "secured_rre" not in roles
        assert "secured_cre" not in roles


# ---------------------------------------------------------------------------
# CRR — Art. 124(1) "any part of an exposure", RRE-first sequential
# ---------------------------------------------------------------------------


class TestCRRMixedCollateralEndToEnd:
    """CRR Art. 124(1) "any part of an exposure" — RRE-first sequential.

    Rationale: CRR has no explicit "mixed RE" article, but Art. 124(1)
    permits per-portion preferential treatment. Allocating to RRE first
    (35% RW, lower than CRE's 50%) is bank-favourable and matches the
    "any part" wording.
    """

    def test_corporate_mixed_cre_rental_failed_only_rre_secured(self) -> None:
        """CRE rental coverage absent → only RRE component is preferential.

        Corporate £1M / RRE £500K (cap 80% × 500K = £400K) / CRE £1M with
        rental_to_interest_ratio absent → CRE eligibility = False, only RRE
        secured emitted alongside residual.

        Hand-calc:
            rre_secured = min(£1M, £400K) = £400K → 35% RW = £140K RWA
            residual = £600K → 100% (unrated corporate) = £600K RWA
            total = £740K RWA
        """
        bundle = _build_mixed_collateral_bundle(
            loan_amount=1_000_000.0,
            rre_value=500_000.0,
            cre_value=1_000_000.0,
            rental_to_interest_ratio=None,  # CRE rental cov absent → fails
            annual_revenue=200_000_000.0,  # large corporate (non-SME)
        )
        config = CalculationConfig.crr(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
        df = _run(bundle, config)

        children = df.filter(pl.col("exposure_reference").str.contains("LOAN_MIX"))
        # Single-component split: secured + residual (CRE not eligible).
        rows = {r["re_split_role"]: r for r in children.to_dicts()}
        secured = rows["secured"]
        residual = rows["residual"]

        assert secured["exposure_class"] == "residential_mortgage"
        assert secured["ead_final"] == pytest.approx(400_000.0, rel=1e-6)
        assert secured["risk_weight"] == pytest.approx(0.35, rel=1e-6)

        assert residual["exposure_class"] == "corporate"
        assert residual["ead_final"] == pytest.approx(600_000.0, rel=1e-6)
        assert residual["risk_weight"] == pytest.approx(1.0, rel=1e-6)

        total_rwa = children["rwa_final"].sum()
        # 400k × 35% + 600k × 100% = 140k + 600k = 740k
        assert total_rwa == pytest.approx(740_000.0, rel=1e-3)
