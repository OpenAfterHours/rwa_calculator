"""
Tests for CRM haircut liquidation period scaling (Art. 224/226).

Validates:
- Corrected B31 haircut values per PRA PS1/26 Art. 224 Tables 1-4
- Liquidation period scaling formula: H_m = H_10 × sqrt(T_m / 10)
- Standard periods: 5-day (repos), 10-day (capital market), 20-day (secured lending)
- FX mismatch haircut scaling by liquidation period
- Backward compatibility (default 10-day, absent column)

Reference:
    PRA PS1/26 Art. 224 Tables 1-4: Supervisory haircuts
    Art. 226(2): Scaling to different holding/liquidation periods
"""

from __future__ import annotations

import math
from decimal import Decimal

import polars as pl

from rwa_calc.data.tables.crr_haircuts import (
    BASEL31_COLLATERAL_HAIRCUTS,
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
    LIQUIDATION_PERIOD_CAPITAL_MARKET,
    LIQUIDATION_PERIOD_REPO,
    LIQUIDATION_PERIOD_SECURED_LENDING,
    lookup_collateral_haircut,
    lookup_fx_haircut,
    scale_haircut_for_liquidation_period,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator

# =============================================================================
# B31 Haircut Value Corrections (PRA PS1/26 Art. 224 Table 3)
# =============================================================================


class TestB31HaircutValueCorrections:
    """Verify corrected B31 haircut values match PRA PS1/26 Art. 224 Table 3."""

    def test_b31_gold_20_percent(self) -> None:
        """Gold haircut under B31 is 20% (10-day) per Art. 224 Table 3."""
        assert BASEL31_COLLATERAL_HAIRCUTS["gold"] == Decimal("0.20")

    def test_b31_equity_main_index_20_percent(self) -> None:
        """Main index equity under B31 is 20% (10-day) per Art. 224 Table 3."""
        assert BASEL31_COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.20")

    def test_b31_equity_other_30_percent(self) -> None:
        """Other equity under B31 is 30% (10-day) per Art. 224 Table 3."""
        assert BASEL31_COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.30")

    def test_crr_gold_15_percent_unchanged(self) -> None:
        """CRR gold haircut remains 15% (10-day)."""
        assert COLLATERAL_HAIRCUTS["gold"] == Decimal("0.15")

    def test_crr_equity_main_index_15_percent_unchanged(self) -> None:
        """CRR main index equity remains 15%."""
        assert COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.15")

    def test_crr_equity_other_25_percent_unchanged(self) -> None:
        """CRR other equity remains 25%."""
        assert COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.25")

    def test_lookup_b31_gold(self) -> None:
        """Scalar lookup returns corrected 20% for B31 gold."""
        result = lookup_collateral_haircut("gold", is_basel_3_1=True)
        assert result == Decimal("0.20")

    def test_lookup_b31_equity_main_index(self) -> None:
        """Scalar lookup returns corrected 20% for B31 main index equity."""
        result = lookup_collateral_haircut("equity", is_main_index=True, is_basel_3_1=True)
        assert result == Decimal("0.20")

    def test_lookup_b31_equity_other(self) -> None:
        """Scalar lookup returns corrected 30% for B31 other equity."""
        result = lookup_collateral_haircut("equity", is_main_index=False, is_basel_3_1=True)
        assert result == Decimal("0.30")


# =============================================================================
# Scaling Formula (Art. 226(2))
# =============================================================================


class TestScalingFormula:
    """Test Art. 226(2) scaling: H_m = H_10 × sqrt(T_m / 10)."""

    def test_10_day_no_scaling(self) -> None:
        """10-day period returns base value unchanged."""
        assert scale_haircut_for_liquidation_period(0.20, 10) == 0.20

    def test_5_day_repo_scaling(self) -> None:
        """5-day (repo) scales down by sqrt(0.5)."""
        result = scale_haircut_for_liquidation_period(0.20, 5)
        expected = 0.20 * math.sqrt(0.5)
        assert abs(result - expected) < 1e-10

    def test_20_day_secured_lending_scaling(self) -> None:
        """20-day (secured lending) scales up by sqrt(2)."""
        result = scale_haircut_for_liquidation_period(0.20, 20)
        expected = 0.20 * math.sqrt(2.0)
        assert abs(result - expected) < 1e-10

    def test_zero_haircut_not_scaled(self) -> None:
        """Zero haircut (cash) stays zero regardless of period."""
        assert scale_haircut_for_liquidation_period(0.0, 20) == 0.0

    def test_gold_b31_5day(self) -> None:
        """B31 gold 5-day: 20% × sqrt(0.5) ≈ 14.142%."""
        result = scale_haircut_for_liquidation_period(0.20, 5)
        assert abs(result - 0.14142) < 0.001

    def test_gold_b31_20day(self) -> None:
        """B31 gold 20-day: 20% × sqrt(2) ≈ 28.284%."""
        result = scale_haircut_for_liquidation_period(0.20, 20)
        assert abs(result - 0.28284) < 0.001

    def test_fx_haircut_5day(self) -> None:
        """FX mismatch 5-day: 8% × sqrt(0.5) ≈ 5.657%."""
        result = scale_haircut_for_liquidation_period(0.08, 5)
        assert abs(result - 0.05657) < 0.001

    def test_fx_haircut_20day(self) -> None:
        """FX mismatch 20-day: 8% × sqrt(2) ≈ 11.314%."""
        result = scale_haircut_for_liquidation_period(0.08, 20)
        assert abs(result - 0.11314) < 0.001

    def test_equity_main_b31_5day(self) -> None:
        """B31 main index equity 5-day: 20% × sqrt(0.5) ≈ 14.142%."""
        result = scale_haircut_for_liquidation_period(0.20, 5)
        assert abs(result - 0.14142) < 0.001

    def test_equity_other_b31_20day(self) -> None:
        """B31 other equity 20-day: 30% × sqrt(2) ≈ 42.426%."""
        result = scale_haircut_for_liquidation_period(0.30, 20)
        assert abs(result - 0.42426) < 0.001

    def test_constants_exported(self) -> None:
        """Standard liquidation period constants are exported."""
        assert LIQUIDATION_PERIOD_REPO == 5
        assert LIQUIDATION_PERIOD_CAPITAL_MARKET == 10
        assert LIQUIDATION_PERIOD_SECURED_LENDING == 20


# =============================================================================
# Scalar Lookup with Liquidation Period
# =============================================================================


class TestScalarLookupWithLiquidationPeriod:
    """Test lookup_collateral_haircut with liquidation_period_days parameter."""

    def test_gold_b31_5day_scalar(self) -> None:
        """Scalar lookup gold B31 at 5-day period."""
        result = lookup_collateral_haircut("gold", is_basel_3_1=True, liquidation_period_days=5)
        expected = Decimal("0.20") * Decimal(str(math.sqrt(0.5)))
        assert result is not None
        assert abs(float(result) - float(expected)) < 0.001

    def test_gold_b31_20day_scalar(self) -> None:
        """Scalar lookup gold B31 at 20-day period."""
        result = lookup_collateral_haircut("gold", is_basel_3_1=True, liquidation_period_days=20)
        assert result is not None
        assert abs(float(result) - 0.28284) < 0.001

    def test_cash_not_scaled(self) -> None:
        """Cash haircut is 0% regardless of liquidation period."""
        result = lookup_collateral_haircut("cash", is_basel_3_1=True, liquidation_period_days=20)
        assert result == Decimal("0.00")

    def test_govt_bond_cqs1_5day(self) -> None:
        """CRR govt bond CQS1 1-5y: 2% at 10-day → 1.414% at 5-day."""
        result = lookup_collateral_haircut(
            "govt_bond",
            cqs=1,
            residual_maturity_years=3.0,
            is_basel_3_1=False,
            liquidation_period_days=5,
        )
        assert result is not None
        expected = 0.02 * math.sqrt(0.5)
        assert abs(float(result) - expected) < 0.001

    def test_corp_bond_cqs1_20day(self) -> None:
        """B31 corp bond CQS1 10y+: 12% at 10-day → 16.97% at 20-day."""
        result = lookup_collateral_haircut(
            "corp_bond",
            cqs=1,
            residual_maturity_years=15.0,
            is_basel_3_1=True,
            liquidation_period_days=20,
        )
        assert result is not None
        expected = 0.12 * math.sqrt(2.0)
        assert abs(float(result) - expected) < 0.001

    def test_receivables_not_scaled(self) -> None:
        """Receivables (non-financial, Art. 230) are not scaled by liquidation period."""
        result_10 = lookup_collateral_haircut(
            "receivables",
            is_basel_3_1=True,
            liquidation_period_days=10,
        )
        result_5 = lookup_collateral_haircut(
            "receivables",
            is_basel_3_1=True,
            liquidation_period_days=5,
        )
        assert result_10 == result_5  # Both 40%, no scaling

    def test_default_10day_backward_compat(self) -> None:
        """Default liquidation_period_days=10 produces unchanged results."""
        result = lookup_collateral_haircut(
            "equity",
            is_main_index=True,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.20")  # No scaling applied

    def test_equity_main_b31_5day_scalar(self) -> None:
        """B31 main index equity at 5-day: 20% × sqrt(0.5) ≈ 14.14%."""
        result = lookup_collateral_haircut(
            "equity",
            is_main_index=True,
            is_basel_3_1=True,
            liquidation_period_days=5,
        )
        assert result is not None
        assert abs(float(result) - 0.14142) < 0.001


# =============================================================================
# FX Haircut Scaling
# =============================================================================


class TestFXHaircutScaling:
    """Test FX mismatch haircut scaling by liquidation period."""

    def test_fx_same_currency_not_scaled(self) -> None:
        """Same currency → 0% regardless of period."""
        assert lookup_fx_haircut("GBP", "GBP", liquidation_period_days=20) == Decimal("0.00")

    def test_fx_10day_default(self) -> None:
        """Default 10-day FX mismatch is 8%."""
        assert lookup_fx_haircut("GBP", "USD") == FX_HAIRCUT

    def test_fx_5day_repo(self) -> None:
        """FX mismatch at 5-day: 8% × sqrt(0.5) ≈ 5.657%."""
        result = lookup_fx_haircut("GBP", "USD", liquidation_period_days=5)
        assert abs(float(result) - 0.05657) < 0.001

    def test_fx_20day_secured_lending(self) -> None:
        """FX mismatch at 20-day: 8% × sqrt(2) ≈ 11.314%."""
        result = lookup_fx_haircut("GBP", "USD", liquidation_period_days=20)
        assert abs(float(result) - 0.11314) < 0.001


# =============================================================================
# Calculator Single-Item with Liquidation Period
# =============================================================================


class TestCalculatorSingleItemLiquidationPeriod:
    """Test HaircutCalculator.calculate_single_haircut with liquidation period."""

    def test_equity_b31_5day_rwa(self) -> None:
        """B31 equity at 5-day: lower haircut → higher adjusted value."""
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
            liquidation_period_days=5,
        )
        # 20% × sqrt(0.5) ≈ 14.14% haircut → 85.86% retained
        expected_adj = Decimal("1000000") * (1 - Decimal(str(round(0.20 * math.sqrt(0.5), 6))))
        assert abs(float(result.adjusted_value) - float(expected_adj)) < 100

    def test_equity_b31_20day_rwa(self) -> None:
        """B31 equity at 20-day: higher haircut → lower adjusted value."""
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
            liquidation_period_days=20,
        )
        # 20% × sqrt(2) ≈ 28.28% haircut → 71.72% retained
        assert float(result.adjusted_value) < 720000

    def test_gold_b31_default_10day(self) -> None:
        """B31 gold at default 10-day: 20% haircut."""
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.calculate_single_haircut(
            collateral_type="gold",
            market_value=Decimal("500000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0.20")
        assert result.adjusted_value == Decimal("400000")

    def test_fx_mismatch_scaled_20day(self) -> None:
        """FX mismatch at 20-day: ~11.3% instead of 8%."""
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("1000000"),
            collateral_currency="USD",
            exposure_currency="GBP",
            liquidation_period_days=20,
        )
        # Cash 0% + FX 11.314% → adjusted ≈ 886,860
        assert abs(float(result.adjusted_value) - 886860) < 200


# =============================================================================
# Calculator Pipeline (LazyFrame) with Liquidation Period
# =============================================================================


class TestCalculatorPipelineLiquidationPeriod:
    """Test HaircutCalculator.apply_haircuts with liquidation_period_days column."""

    def _make_config(self, is_b31: bool = True) -> object:
        """Create a minimal config."""
        import datetime

        from rwa_calc.contracts.config import CalculationConfig

        rd = datetime.date(2030, 6, 30)
        if is_b31:
            return CalculationConfig.basel_3_1(reporting_date=rd)
        return CalculationConfig.crr(reporting_date=datetime.date(2025, 12, 31))

    def test_pipeline_5day_repo_scales_haircut(self) -> None:
        """Pipeline with liquidation_period_days=5 scales equity haircut down."""
        config = self._make_config(is_b31=True)
        calc = HaircutCalculator(is_basel_3_1=True)
        df = pl.LazyFrame(
            {
                "collateral_type": ["equity"],
                "market_value": [1_000_000.0],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [True],
                "liquidation_period_days": [5],
            }
        )
        result = calc.apply_haircuts(df, config).collect()
        hc = result["collateral_haircut"][0]
        # B31 main index equity 20% × sqrt(0.5) ≈ 14.14%
        assert abs(hc - 0.20 * math.sqrt(0.5)) < 0.01

    def test_pipeline_20day_secured_scales_haircut(self) -> None:
        """Pipeline with liquidation_period_days=20 scales equity haircut up."""
        config = self._make_config(is_b31=True)
        calc = HaircutCalculator(is_basel_3_1=True)
        df = pl.LazyFrame(
            {
                "collateral_type": ["equity"],
                "market_value": [1_000_000.0],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [True],
                "liquidation_period_days": [20],
            }
        )
        result = calc.apply_haircuts(df, config).collect()
        hc = result["collateral_haircut"][0]
        # B31 main index equity 20% × sqrt(2) ≈ 28.28%
        assert abs(hc - 0.20 * math.sqrt(2.0)) < 0.01

    def test_pipeline_no_liquidation_column_default_10day(self) -> None:
        """Pipeline without liquidation_period_days column uses 10-day base."""
        config = self._make_config(is_b31=True)
        calc = HaircutCalculator(is_basel_3_1=True)
        df = pl.LazyFrame(
            {
                "collateral_type": ["equity"],
                "market_value": [1_000_000.0],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [True],
            }
        )
        result = calc.apply_haircuts(df, config).collect()
        hc = result["collateral_haircut"][0]
        # 20% (10-day base, no scaling)
        assert abs(hc - 0.20) < 0.01

    def test_pipeline_null_liquidation_defaults_10day(self) -> None:
        """Null liquidation_period_days defaults to 10 (no scaling)."""
        config = self._make_config(is_b31=True)
        calc = HaircutCalculator(is_basel_3_1=True)
        df = pl.LazyFrame(
            {
                "collateral_type": ["equity"],
                "market_value": [1_000_000.0],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [True],
                "liquidation_period_days": [None],
            }
        ).cast({"liquidation_period_days": pl.Int32})
        result = calc.apply_haircuts(df, config).collect()
        hc = result["collateral_haircut"][0]
        assert abs(hc - 0.20) < 0.01

    def test_pipeline_fx_mismatch_scaled_5day(self) -> None:
        """FX mismatch haircut scaled for 5-day liquidation."""
        config = self._make_config(is_b31=True)
        calc = HaircutCalculator(is_basel_3_1=True)
        df = pl.LazyFrame(
            {
                "collateral_type": ["cash"],
                "market_value": [1_000_000.0],
                "currency": ["USD"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [True],
                "liquidation_period_days": [5],
            }
        )
        result = calc.apply_haircuts(df, config).collect()
        fx = result["fx_haircut"][0]
        # FX 8% × sqrt(0.5) ≈ 5.657%
        assert abs(fx - 0.08 * math.sqrt(0.5)) < 0.005

    def test_pipeline_mixed_liquidation_periods(self) -> None:
        """Batch with different liquidation periods produces correct haircuts."""
        config = self._make_config(is_b31=True)
        calc = HaircutCalculator(is_basel_3_1=True)
        df = pl.LazyFrame(
            {
                "collateral_type": ["gold", "gold", "gold"],
                "market_value": [100_000.0, 100_000.0, 100_000.0],
                "currency": ["GBP", "GBP", "GBP"],
                "exposure_currency": ["GBP", "GBP", "GBP"],
                "residual_maturity_years": [None, None, None],
                "issuer_cqs": [None, None, None],
                "is_eligible_financial_collateral": [None, None, None],
                "liquidation_period_days": [5, 10, 20],
            }
        )
        result = calc.apply_haircuts(df, config).collect()
        hc_5 = result["collateral_haircut"][0]
        hc_10 = result["collateral_haircut"][1]
        hc_20 = result["collateral_haircut"][2]

        # Gold B31: 20% base (10-day)
        assert abs(hc_5 - 0.20 * math.sqrt(0.5)) < 0.005  # ~14.14%
        assert abs(hc_10 - 0.20) < 0.005  # 20%
        assert abs(hc_20 - 0.20 * math.sqrt(2.0)) < 0.005  # ~28.28%

    def test_pipeline_crr_gold_unchanged(self) -> None:
        """CRR gold at 10-day remains 15% (not changed by B31 fix)."""
        config = self._make_config(is_b31=False)
        calc = HaircutCalculator(is_basel_3_1=False)
        df = pl.LazyFrame(
            {
                "collateral_type": ["gold"],
                "market_value": [100_000.0],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [None],
            }
        )
        result = calc.apply_haircuts(df, config).collect()
        hc = result["collateral_haircut"][0]
        assert abs(hc - 0.15) < 0.005
