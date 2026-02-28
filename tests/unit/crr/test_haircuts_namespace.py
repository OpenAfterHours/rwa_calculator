"""Unit tests for the Haircuts Polars namespace.

Tests cover:
- Namespace registration and availability
- Maturity band classification
- Collateral haircut application
- FX haircut application
- Maturity mismatch adjustment
- Adjusted value calculation
- Full pipeline (apply_all_haircuts)
- Method chaining

References:
- CRR Art. 224: Supervisory haircuts
- CRR Art. 238: Maturity mismatch adjustment
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm import HaircutsExpr, HaircutsLazyFrame  # noqa: F401

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def cash_collateral() -> pl.LazyFrame:
    """Return cash collateral."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL001"],
            "collateral_type": ["cash"],
            "market_value": [100_000.0],
            "currency": ["GBP"],
            "residual_maturity_years": [None],
            "issuer_cqs": [None],
        }
    )


@pytest.fixture
def bond_collateral() -> pl.LazyFrame:
    """Return government bond collateral with various maturities."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL001", "COLL002", "COLL003"],
            "collateral_type": ["govt_bond", "govt_bond", "govt_bond"],
            "market_value": [100_000.0, 100_000.0, 100_000.0],
            "currency": ["GBP", "GBP", "GBP"],
            "residual_maturity_years": [0.5, 3.0, 7.0],  # 0-1y, 1-5y, 5y+
            "issuer_cqs": [1, 1, 1],
            "is_eligible_financial_collateral": [True, True, True],
        }
    )


@pytest.fixture
def equity_collateral() -> pl.LazyFrame:
    """Return equity collateral."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL001", "COLL002"],
            "collateral_type": ["equity", "equity"],
            "market_value": [100_000.0, 100_000.0],
            "currency": ["GBP", "GBP"],
            "residual_maturity_years": [None, None],
            "issuer_cqs": [None, None],
            "is_eligible_financial_collateral": [True, False],  # Main index vs other
        }
    )


@pytest.fixture
def fx_collateral() -> pl.LazyFrame:
    """Return collateral with FX mismatch."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL001", "COLL002"],
            "collateral_type": ["cash", "cash"],
            "market_value": [100_000.0, 100_000.0],
            "currency": ["GBP", "USD"],
            "exposure_currency": ["GBP", "GBP"],
            "residual_maturity_years": [None, None],
        }
    )


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestHaircutsNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, cash_collateral: pl.LazyFrame) -> None:
        """LazyFrame should have .haircuts namespace available."""
        assert hasattr(cash_collateral, "haircuts")

    def test_expr_namespace_registered(self) -> None:
        """Expression should have .haircuts namespace available."""
        expr = pl.col("market_value")
        assert hasattr(expr, "haircuts")

    def test_namespace_methods_available(self, cash_collateral: pl.LazyFrame) -> None:
        """Namespace should have expected methods."""
        haircuts = cash_collateral.haircuts
        expected_methods = [
            "classify_maturity_band",
            "apply_collateral_haircuts",
            "apply_fx_haircut",
            "apply_maturity_mismatch",
            "calculate_adjusted_value",
            "apply_all_haircuts",
            "build_haircut_audit",
        ]
        for method in expected_methods:
            assert hasattr(haircuts, method), f"Missing method: {method}"


# =============================================================================
# Maturity Band Classification Tests
# =============================================================================


class TestClassifyMaturityBand:
    """Tests for maturity band classification."""

    def test_short_term_0_1y(self, bond_collateral: pl.LazyFrame) -> None:
        """Maturity <= 1y should be classified as 0_1y."""
        result = bond_collateral.haircuts.classify_maturity_band().collect()
        # First bond has 0.5y maturity
        assert result["maturity_band"][0] == "0_1y"

    def test_medium_term_1_5y(self, bond_collateral: pl.LazyFrame) -> None:
        """1y < maturity <= 5y should be classified as 1_5y."""
        result = bond_collateral.haircuts.classify_maturity_band().collect()
        # Second bond has 3.0y maturity
        assert result["maturity_band"][1] == "1_5y"

    def test_long_term_5y_plus(self, bond_collateral: pl.LazyFrame) -> None:
        """Maturity > 5y should be classified as 5y_plus."""
        result = bond_collateral.haircuts.classify_maturity_band().collect()
        # Third bond has 7.0y maturity
        assert result["maturity_band"][2] == "5y_plus"

    def test_null_maturity_defaults_to_5y_plus(self, cash_collateral: pl.LazyFrame) -> None:
        """Null maturity should default to 5y_plus."""
        result = cash_collateral.haircuts.classify_maturity_band().collect()
        assert result["maturity_band"][0] == "5y_plus"


# =============================================================================
# Collateral Haircut Tests
# =============================================================================


class TestApplyCollateralHaircuts:
    """Tests for collateral haircut application."""

    def test_cash_zero_haircut(
        self, cash_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Cash should have 0% haircut."""
        result = cash_collateral.haircuts.apply_collateral_haircuts(crr_config).collect()
        assert result["collateral_haircut"][0] == pytest.approx(0.0)

    def test_govt_bond_cqs1_0_1y_haircut(
        self, bond_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Government bond CQS 1, 0-1y maturity should have 0.5% haircut."""
        result = bond_collateral.haircuts.apply_collateral_haircuts(crr_config).collect()
        # First bond: CQS 1, 0.5y maturity
        assert result["collateral_haircut"][0] == pytest.approx(0.005)

    def test_govt_bond_cqs1_1_5y_haircut(
        self, bond_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Government bond CQS 1, 1-5y maturity should have 2% haircut."""
        result = bond_collateral.haircuts.apply_collateral_haircuts(crr_config).collect()
        # Second bond: CQS 1, 3.0y maturity
        assert result["collateral_haircut"][1] == pytest.approx(0.02)

    def test_govt_bond_cqs1_5y_plus_haircut(
        self, bond_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Government bond CQS 1, 5y+ maturity should have 4% haircut."""
        result = bond_collateral.haircuts.apply_collateral_haircuts(crr_config).collect()
        # Third bond: CQS 1, 7.0y maturity
        assert result["collateral_haircut"][2] == pytest.approx(0.04)

    def test_equity_main_index_haircut(
        self, equity_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Main index equity should have 15% haircut."""
        result = equity_collateral.haircuts.apply_collateral_haircuts(crr_config).collect()
        # First equity: is_eligible_financial_collateral = True (main index)
        assert result["collateral_haircut"][0] == pytest.approx(0.15)

    def test_equity_other_haircut(
        self, equity_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Other equity should have 25% haircut."""
        result = equity_collateral.haircuts.apply_collateral_haircuts(crr_config).collect()
        # Second equity: is_eligible_financial_collateral = False (other)
        assert result["collateral_haircut"][1] == pytest.approx(0.25)


# =============================================================================
# FX Haircut Tests
# =============================================================================


class TestApplyFXHaircut:
    """Tests for FX haircut application."""

    def test_no_fx_mismatch_zero_haircut(self, fx_collateral: pl.LazyFrame) -> None:
        """No FX mismatch should have 0% haircut."""
        result = fx_collateral.haircuts.apply_fx_haircut("exposure_currency").collect()
        # First collateral: GBP/GBP
        assert result["fx_haircut"][0] == pytest.approx(0.0)

    def test_fx_mismatch_8_percent_haircut(self, fx_collateral: pl.LazyFrame) -> None:
        """FX mismatch should have 8% haircut."""
        result = fx_collateral.haircuts.apply_fx_haircut("exposure_currency").collect()
        # Second collateral: USD/GBP
        assert result["fx_haircut"][1] == pytest.approx(0.08)


# =============================================================================
# Maturity Mismatch Tests
# =============================================================================


class TestApplyMaturityMismatch:
    """Tests for maturity mismatch adjustment."""

    def test_long_maturity_no_adjustment(self) -> None:
        """Collateral maturity >= exposure maturity should have factor = 1.0."""
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL001"],
                "residual_maturity_years": [10.0],
            }
        )
        result = collateral.haircuts.apply_maturity_mismatch(exposure_maturity_years=5.0).collect()
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)

    def test_very_short_maturity_no_protection(self) -> None:
        """Collateral maturity < 3 months should have factor = 0.0."""
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL001"],
                "residual_maturity_years": [0.1],  # ~1.2 months
            }
        )
        result = collateral.haircuts.apply_maturity_mismatch(exposure_maturity_years=5.0).collect()
        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)

    def test_intermediate_maturity_partial_factor(self) -> None:
        """Intermediate collateral maturity should have partial factor."""
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL001"],
                "residual_maturity_years": [2.5],  # Between 0.25 and 5
            }
        )
        result = collateral.haircuts.apply_maturity_mismatch(exposure_maturity_years=5.0).collect()
        # Factor = (2.5 - 0.25) / (5.0 - 0.25) = 2.25 / 4.75 ~ 0.474
        expected = (2.5 - 0.25) / (5.0 - 0.25)
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected)


# =============================================================================
# Adjusted Value Calculation Tests
# =============================================================================


class TestCalculateAdjustedValue:
    """Tests for adjusted value calculation."""

    def test_value_after_haircut(self, crr_config: CalculationConfig) -> None:
        """value_after_haircut should equal MV * (1 - Hc - Hfx)."""
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL001"],
                "market_value": [100_000.0],
                "collateral_haircut": [0.10],  # 10%
                "fx_haircut": [0.08],  # 8%
            }
        )
        result = collateral.haircuts.calculate_adjusted_value().collect()
        # value_after_haircut = 100,000 * (1 - 0.10 - 0.08) = 82,000
        assert result["value_after_haircut"][0] == pytest.approx(82_000.0)

    def test_value_after_maturity_adj(self, crr_config: CalculationConfig) -> None:
        """value_after_maturity_adj should apply maturity factor."""
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL001"],
                "market_value": [100_000.0],
                "collateral_haircut": [0.10],
                "fx_haircut": [0.0],
                "maturity_adjustment_factor": [0.5],
            }
        )
        result = collateral.haircuts.calculate_adjusted_value().collect()
        # value_after_haircut = 100,000 * 0.90 = 90,000
        # value_after_maturity_adj = 90,000 * 0.5 = 45,000
        assert result["value_after_maturity_adj"][0] == pytest.approx(45_000.0)


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestApplyAllHaircuts:
    """Tests for full haircut pipeline."""

    def test_apply_all_haircuts(
        self, bond_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """apply_all_haircuts should apply full pipeline."""
        result = bond_collateral.haircuts.apply_all_haircuts(config=crr_config).collect()

        expected_columns = [
            "maturity_band",
            "collateral_haircut",
            "fx_haircut",
            "maturity_adjustment_factor",
            "value_after_haircut",
            "value_after_maturity_adj",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"


# =============================================================================
# Method Chaining Tests
# =============================================================================


class TestMethodChaining:
    """Tests for method chaining."""

    def test_full_pipeline_chain(
        self, bond_collateral: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Full pipeline should work with method chaining."""
        result = (
            bond_collateral.haircuts.classify_maturity_band()
            .haircuts.apply_collateral_haircuts(crr_config)
            .haircuts.apply_fx_haircut("currency")
            .haircuts.apply_maturity_mismatch(5.0)
            .haircuts.calculate_adjusted_value()
            .collect()
        )

        assert "collateral_haircut" in result.columns
        assert "value_after_haircut" in result.columns


# =============================================================================
# Expression Namespace Tests
# =============================================================================


class TestExprNamespace:
    """Tests for expression namespace methods."""

    def test_apply_haircut(self) -> None:
        """apply_haircut should reduce value by haircut percentage."""
        df = pl.DataFrame({"market_value": [100_000.0]})
        result = df.with_columns(
            pl.col("market_value").haircuts.apply_haircut(0.15).alias("adjusted")
        )
        assert result["adjusted"][0] == pytest.approx(85_000.0)


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestBuildHaircutAudit:
    """Tests for audit trail generation."""

    def test_build_haircut_audit_includes_calculation_string(
        self,
        bond_collateral: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """build_haircut_audit should include haircut_calculation string."""
        result = (
            bond_collateral.haircuts.apply_all_haircuts(config=crr_config)
            .haircuts.build_haircut_audit()
            .collect()
        )

        assert "haircut_calculation" in result.columns
        calc_str = result["haircut_calculation"][0]
        assert "MV=" in calc_str
        assert "Hc=" in calc_str
