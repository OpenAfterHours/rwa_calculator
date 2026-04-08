"""
Tests for equity collateral is_main_index field (P6.21).

Why this matters:
    CRR Art. 224 Table 4 and PRA PS1/26 Art. 224 Table 3 define two tiers of
    equity supervisory haircuts: main-index (CRR 15%, B31 20%) and other-listed
    (CRR 25%, B31 30%). Previously, `is_eligible_financial_collateral` was
    overloaded as the `is_main_index` proxy, making other-listed equity
    unreachable — all eligible equity got main-index treatment.

    The fix adds a dedicated `is_main_index` Boolean field to COLLATERAL_SCHEMA.
    When present, it drives the haircut lookup directly. When absent, the old
    `is_eligible_financial_collateral` fallback preserves backward compatibility.

References:
    CRR Art. 224 Table 4: main-index 15%, other listed 25%
    PRA PS1/26 Art. 224 Table 3: main-index 20%, other listed 30%
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.tables.crr_haircuts import (
    lookup_collateral_haircut,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.pipeline import PipelineOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_equity_collateral(
    *,
    is_main_index: bool | None = None,
    is_eligible: bool = True,
    include_main_index_col: bool = True,
) -> pl.LazyFrame:
    """Build a minimal equity collateral LazyFrame for haircut testing.

    Includes exposure_currency (required by apply_haircuts FX mismatch step).
    """
    schema: dict[str, pl.DataType] = {
        "collateral_reference": pl.String,
        "collateral_type": pl.String,
        "currency": pl.String,
        "exposure_currency": pl.String,
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
    data: dict = {
        "collateral_reference": ["EQ1"],
        "collateral_type": ["equity"],
        "currency": ["GBP"],
        "exposure_currency": ["GBP"],
        "maturity_date": [None],
        "market_value": [100_000.0],
        "nominal_value": [100_000.0],
        "pledge_percentage": [None],
        "beneficiary_type": ["loan"],
        "beneficiary_reference": ["LOAN1"],
        "issuer_cqs": [None],
        "issuer_type": [None],
        "residual_maturity_years": [None],
        "original_maturity_years": [None],
        "is_eligible_financial_collateral": [is_eligible],
        "is_eligible_irb_collateral": [is_eligible],
        "valuation_date": [date(2025, 12, 31)],
        "valuation_type": ["market"],
        "property_type": [None],
        "property_ltv": [None],
        "is_income_producing": [None],
        "is_adc": [None],
        "is_presold": [None],
        "is_qualifying_re": [None],
        "prior_charge_ltv": [None],
        "liquidation_period_days": [None],
        "qualifies_for_zero_haircut": [None],
        "insurer_risk_weight": [None],
        "credit_event_reduction": [None],
    }
    if include_main_index_col:
        data["is_main_index"] = [is_main_index]
        schema["is_main_index"] = pl.Boolean
    return pl.LazyFrame(data, schema=schema)


def _get_haircut(collateral_lf: pl.LazyFrame, is_basel_3_1: bool = False) -> float:
    """Run the HaircutCalculator and return the collateral_haircut value."""
    calc = HaircutCalculator(is_basel_3_1=is_basel_3_1)
    config = (
        CalculationConfig.basel_3_1(reporting_date=date(2025, 12, 31))
        if is_basel_3_1
        else CalculationConfig.crr(reporting_date=date(2025, 12, 31))
    )
    result = calc.apply_haircuts(collateral_lf, config)
    df = result.collect()
    return df["collateral_haircut"][0]


# ===========================================================================
# Schema tests
# ===========================================================================


class TestIsMainIndexSchema:
    """Verify is_main_index field exists in COLLATERAL_SCHEMA."""

    def test_field_exists_in_schema(self) -> None:
        from rwa_calc.data.schemas import COLLATERAL_SCHEMA

        assert "is_main_index" in COLLATERAL_SCHEMA

    def test_field_type_is_boolean(self) -> None:
        from rwa_calc.data.schemas import COLLATERAL_SCHEMA

        assert COLLATERAL_SCHEMA["is_main_index"] == pl.Boolean

    def test_field_distinct_from_eligibility(self) -> None:
        """is_main_index is a separate field from is_eligible_financial_collateral."""
        from rwa_calc.data.schemas import COLLATERAL_SCHEMA

        assert "is_main_index" in COLLATERAL_SCHEMA
        assert "is_eligible_financial_collateral" in COLLATERAL_SCHEMA
        assert COLLATERAL_SCHEMA["is_main_index"] != COLLATERAL_SCHEMA.get(
            "is_eligible_financial_collateral_NONEXISTENT", None
        )


# ===========================================================================
# CRR haircut tests (Art. 224 Table 4)
# ===========================================================================


class TestCRREquityHaircutsWithMainIndex:
    """CRR equity haircuts: main-index 15%, other-listed 25%."""

    def test_main_index_true_gets_15pct(self) -> None:
        haircut = _get_haircut(_build_equity_collateral(is_main_index=True), is_basel_3_1=False)
        assert haircut == pytest.approx(0.15)

    def test_main_index_false_gets_25pct(self) -> None:
        haircut = _get_haircut(_build_equity_collateral(is_main_index=False), is_basel_3_1=False)
        assert haircut == pytest.approx(0.25)

    def test_main_index_null_defaults_to_main(self) -> None:
        """Null is_main_index defaults to True (main-index) for backward compat."""
        haircut = _get_haircut(_build_equity_collateral(is_main_index=None), is_basel_3_1=False)
        assert haircut == pytest.approx(0.15)

    def test_other_listed_eligible_and_haircut(self) -> None:
        """Other-listed equity is eligible AND gets 25% haircut (decoupled)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_main_index=False, is_eligible=True),
            is_basel_3_1=False,
        )
        assert haircut == pytest.approx(0.25)

    def test_lookup_function_main_index(self) -> None:
        assert lookup_collateral_haircut(
            "equity", is_main_index=True, is_basel_3_1=False
        ) == Decimal("0.15")

    def test_lookup_function_other_listed(self) -> None:
        assert lookup_collateral_haircut(
            "equity", is_main_index=False, is_basel_3_1=False
        ) == Decimal("0.25")


# ===========================================================================
# Basel 3.1 haircut tests (PRA PS1/26 Art. 224 Table 3)
# ===========================================================================


class TestB31EquityHaircutsWithMainIndex:
    """Basel 3.1 equity haircuts: main-index 20%, other-listed 30%."""

    def test_main_index_true_gets_20pct(self) -> None:
        haircut = _get_haircut(_build_equity_collateral(is_main_index=True), is_basel_3_1=True)
        assert haircut == pytest.approx(0.20)

    def test_main_index_false_gets_30pct(self) -> None:
        haircut = _get_haircut(_build_equity_collateral(is_main_index=False), is_basel_3_1=True)
        assert haircut == pytest.approx(0.30)

    def test_main_index_null_defaults_to_main(self) -> None:
        """Null is_main_index defaults to True (main-index) for backward compat."""
        haircut = _get_haircut(_build_equity_collateral(is_main_index=None), is_basel_3_1=True)
        assert haircut == pytest.approx(0.20)

    def test_other_listed_eligible_and_haircut(self) -> None:
        """Other-listed equity is eligible AND gets 30% haircut (decoupled)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_main_index=False, is_eligible=True),
            is_basel_3_1=True,
        )
        assert haircut == pytest.approx(0.30)


# ===========================================================================
# Backward compatibility tests (no is_main_index column)
# ===========================================================================


class TestBackwardCompatNoMainIndexColumn:
    """When is_main_index column is absent, fall back to is_eligible_financial_collateral."""

    def test_crr_eligible_fallback_main_index(self) -> None:
        """Eligible equity without is_main_index column → 15% (old behavior)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_eligible=True, include_main_index_col=False),
            is_basel_3_1=False,
        )
        assert haircut == pytest.approx(0.15)

    def test_crr_ineligible_fallback_other(self) -> None:
        """Ineligible equity without is_main_index column → 25% (old behavior)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_eligible=False, include_main_index_col=False),
            is_basel_3_1=False,
        )
        assert haircut == pytest.approx(0.25)

    def test_b31_eligible_fallback_main_index(self) -> None:
        """Eligible equity without is_main_index column → 20% (old behavior)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_eligible=True, include_main_index_col=False),
            is_basel_3_1=True,
        )
        assert haircut == pytest.approx(0.20)

    def test_b31_ineligible_fallback_other(self) -> None:
        """Ineligible equity without is_main_index column → 30% (old behavior)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_eligible=False, include_main_index_col=False),
            is_basel_3_1=True,
        )
        assert haircut == pytest.approx(0.30)


# ===========================================================================
# is_main_index overrides is_eligible_financial_collateral
# ===========================================================================


class TestMainIndexOverridesEligibility:
    """is_main_index takes precedence over is_eligible_financial_collateral."""

    def test_eligible_but_not_main_index_gets_other_haircut(self) -> None:
        """Eligible + not main-index → 25% CRR (not 15%)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_main_index=False, is_eligible=True),
            is_basel_3_1=False,
        )
        assert haircut == pytest.approx(0.25)

    def test_main_index_true_with_eligible_false(self) -> None:
        """Main-index True + ineligible → 15% haircut (index drives haircut)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_main_index=True, is_eligible=False),
            is_basel_3_1=False,
        )
        assert haircut == pytest.approx(0.15)

    def test_b31_eligible_but_not_main_gets_30pct(self) -> None:
        """Eligible + not main-index → 30% B31 (not 20%)."""
        haircut = _get_haircut(
            _build_equity_collateral(is_main_index=False, is_eligible=True),
            is_basel_3_1=True,
        )
        assert haircut == pytest.approx(0.30)


# ===========================================================================
# Multiple collateral rows
# ===========================================================================


class TestMultipleEquityCollateral:
    """Mixed main-index and other-listed equity in one collateral frame."""

    @staticmethod
    def _build_mixed_frame() -> pl.LazyFrame:
        _MULTI_SCHEMA: dict[str, pl.DataType] = {
            "collateral_reference": pl.String,
            "collateral_type": pl.String,
            "currency": pl.String,
            "exposure_currency": pl.String,
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
            "is_main_index": pl.Boolean,
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
        return pl.LazyFrame(
            {
                "collateral_reference": ["EQ_MAIN", "EQ_OTHER"],
                "collateral_type": ["equity", "equity"],
                "currency": ["GBP", "GBP"],
                "exposure_currency": ["GBP", "GBP"],
                "maturity_date": [None, None],
                "market_value": [100_000.0, 100_000.0],
                "nominal_value": [100_000.0, 100_000.0],
                "pledge_percentage": [None, None],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["LOAN1", "LOAN1"],
                "issuer_cqs": [None, None],
                "issuer_type": [None, None],
                "residual_maturity_years": [None, None],
                "original_maturity_years": [None, None],
                "is_eligible_financial_collateral": [True, True],
                "is_eligible_irb_collateral": [True, True],
                "is_main_index": [True, False],
                "valuation_date": [date(2025, 12, 31), date(2025, 12, 31)],
                "valuation_type": ["market", "market"],
                "property_type": [None, None],
                "property_ltv": [None, None],
                "is_income_producing": [None, None],
                "is_adc": [None, None],
                "is_presold": [None, None],
                "is_qualifying_re": [None, None],
                "prior_charge_ltv": [None, None],
                "liquidation_period_days": [None, None],
                "qualifies_for_zero_haircut": [None, None],
                "insurer_risk_weight": [None, None],
                "credit_event_reduction": [None, None],
            },
            schema=_MULTI_SCHEMA,
        )

    def test_mixed_main_and_other_crr(self) -> None:
        """Two equities: one main-index (15%), one other-listed (25%)."""
        lf = self._build_mixed_frame()
        calc = HaircutCalculator(is_basel_3_1=False)
        config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        result = calc.apply_haircuts(lf, config).collect()
        haircuts = result.sort("collateral_reference")["collateral_haircut"].to_list()
        assert haircuts[0] == pytest.approx(0.15)  # EQ_MAIN
        assert haircuts[1] == pytest.approx(0.25)  # EQ_OTHER

    def test_mixed_main_and_other_b31(self) -> None:
        """Two equities: one main-index (20%), one other-listed (30%)."""
        lf = self._build_mixed_frame()
        calc = HaircutCalculator(is_basel_3_1=True)
        config = CalculationConfig.basel_3_1(reporting_date=date(2025, 12, 31))
        result = calc.apply_haircuts(lf, config).collect()
        haircuts = result.sort("collateral_reference")["collateral_haircut"].to_list()
        assert haircuts[0] == pytest.approx(0.20)  # EQ_MAIN
        assert haircuts[1] == pytest.approx(0.30)  # EQ_OTHER


# ===========================================================================
# End-to-end pipeline acceptance test (other-listed equity)
# ===========================================================================

_REPORTING_DATE = date(2025, 12, 31)

_PIPELINE_COLLATERAL_SCHEMA: dict[str, pl.DataType] = {
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
    "is_main_index": pl.Boolean,
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


class TestOtherListedEquityPipeline:
    """End-to-end: other-listed equity gets higher haircut through the full pipeline."""

    @pytest.fixture(scope="class")
    def result_main_index(self):
        return self._run(is_main_index=True)

    @pytest.fixture(scope="class")
    def result_other_listed(self):
        return self._run(is_main_index=False)

    @staticmethod
    def _run(is_main_index: bool):
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
            counterparties=pl.LazyFrame(
                {
                    "counterparty_reference": ["CP1"],
                    "counterparty_name": ["Test Corp"],
                    "entity_type": ["corporate"],
                    "country_code": ["GB"],
                    "annual_revenue": [50_000_000.0],
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
                {
                    "facility_reference": ["FAC1"],
                    "product_type": ["term_loan"],
                    "book_code": ["BANK"],
                    "counterparty_reference": ["CP1"],
                    "value_date": [date(2024, 1, 1)],
                    "maturity_date": [date(2029, 12, 31)],
                    "currency": ["GBP"],
                    "limit": [1_100_000.0],
                    "committed": [True],
                    "lgd": [0.45],
                    "lgd_unsecured": [0.45],
                    "has_sufficient_collateral_data": [True],
                    "beel": [None],
                    "is_revolving": [False],
                    "is_qrre_transactor": [None],
                    "seniority": ["senior"],
                    "risk_type": ["corporate"],
                    "underlying_risk_type": [None],
                    "ccf_modelled": [None],
                    "ead_modelled": [None],
                    "is_short_term_trade_lc": [False],
                    "is_payroll_loan": [False],
                    "is_buy_to_let": [False],
                    "has_one_day_maturity_floor": [False],
                    "facility_termination_date": [None],
                }
            ),
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["LOAN1"],
                    "product_type": ["term_loan"],
                    "book_code": ["BANK"],
                    "counterparty_reference": ["CP1"],
                    "value_date": [date(2024, 1, 1)],
                    "maturity_date": [date(2029, 12, 31)],
                    "currency": ["GBP"],
                    "drawn_amount": [1_000_000.0],
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
                    "collateral_reference": ["COLL1"],
                    "collateral_type": ["equity"],
                    "currency": ["GBP"],
                    "maturity_date": [None],
                    "market_value": [500_000.0],
                    "nominal_value": [500_000.0],
                    "pledge_percentage": [None],
                    "beneficiary_type": ["loan"],
                    "beneficiary_reference": ["LOAN1"],
                    "issuer_cqs": [None],
                    "issuer_type": [None],
                    "residual_maturity_years": [None],
                    "original_maturity_years": [None],
                    "is_eligible_financial_collateral": [True],
                    "is_eligible_irb_collateral": [True],
                    "is_main_index": [is_main_index],
                    "valuation_date": [date(2025, 12, 31)],
                    "valuation_type": ["market"],
                    "property_type": [None],
                    "property_ltv": [None],
                    "is_income_producing": [None],
                    "is_adc": [None],
                    "is_presold": [None],
                    "is_qualifying_re": [None],
                    "prior_charge_ltv": [None],
                    "liquidation_period_days": [None],
                    "qualifies_for_zero_haircut": [None],
                    "insurer_risk_weight": [None],
                    "credit_event_reduction": [None],
                },
                schema=_PIPELINE_COLLATERAL_SCHEMA,
            ),
        )
        config = CalculationConfig.crr(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
        return PipelineOrchestrator().run_with_data(bundle, config)

    @staticmethod
    def _get_ead(result) -> float:
        for lf in [result.sa_results, result.irb_results, result.slotting_results]:
            if lf is None:
                continue
            df = lf.filter(pl.col("exposure_reference").str.contains("LOAN1")).collect()
            if len(df) > 0:
                return df["ead_final"].sum()
        return 0.0

    def test_main_index_ead(self, result_main_index) -> None:
        """Main-index equity (15% haircut): EAD = 1M - 500k × 0.85 = 575k."""
        ead = self._get_ead(result_main_index)
        assert ead == pytest.approx(575_000.0, rel=0.05)

    def test_other_listed_ead(self, result_other_listed) -> None:
        """Other-listed equity (25% haircut): EAD = 1M - 500k × 0.75 = 625k."""
        ead = self._get_ead(result_other_listed)
        assert ead == pytest.approx(625_000.0, rel=0.05)

    def test_other_listed_higher_ead_than_main(
        self, result_main_index, result_other_listed
    ) -> None:
        """Other-listed equity (25%) gives higher EAD than main-index (15%)."""
        ead_main = self._get_ead(result_main_index)
        ead_other = self._get_ead(result_other_listed)
        assert ead_other > ead_main

    def test_other_listed_higher_rwa_than_main(
        self, result_main_index, result_other_listed
    ) -> None:
        """Other-listed equity (25%) gives higher RWA than main-index (15%)."""
        rwa_main = sum(
            r.get("rwa_final", 0.0) or 0.0
            for lf in [
                result_main_index.sa_results,
                result_main_index.irb_results,
            ]
            if lf is not None
            for r in lf.filter(pl.col("exposure_reference").str.contains("LOAN1"))
            .collect()
            .to_dicts()
        )
        rwa_other = sum(
            r.get("rwa_final", 0.0) or 0.0
            for lf in [
                result_other_listed.sa_results,
                result_other_listed.irb_results,
            ]
            if lf is not None
            for r in lf.filter(pl.col("exposure_reference").str.contains("LOAN1"))
            .collect()
            .to_dicts()
        )
        assert rwa_other > rwa_main
