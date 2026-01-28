"""Unit tests for the IRB Polars namespace.

Tests cover:
- Namespace registration and availability
- PD floor application (CRR and Basel 3.1)
- LGD floor application
- Correlation calculation (corporate, retail, SME adjustment)
- Capital requirement (K) calculation
- Maturity adjustment
- Full pipeline (apply_all_formulas)
- Method chaining
- Expression namespace methods

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162-163: Maturity and PD floors
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb import IRBLazyFrame, IRBExpr  # noqa: F401 - imports register namespace


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def basic_lazyframe() -> pl.LazyFrame:
    """Return a basic LazyFrame with IRB columns."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "pd": [0.01, 0.05, 0.0001],  # Last one below CRR floor
        "lgd": [0.45, 0.35, 0.40],
        "ead_final": [1_000_000.0, 500_000.0, 250_000.0],
        "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
        "maturity": [2.5, 3.0, 5.0],
        "approach": ["foundation_irb", "foundation_irb", "foundation_irb"],
    })


@pytest.fixture
def retail_lazyframe() -> pl.LazyFrame:
    """Return a LazyFrame with retail exposures."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "pd": [0.02, 0.03, 0.01],
        "lgd": [0.30, 0.25, 0.15],
        "ead_final": [100_000.0, 50_000.0, 200_000.0],
        "exposure_class": ["RETAIL_MORTGAGE", "RETAIL_QRRE", "RETAIL"],
        "maturity": [5.0, 2.5, 3.0],
        "approach": ["advanced_irb", "advanced_irb", "advanced_irb"],
    })


@pytest.fixture
def sme_lazyframe() -> pl.LazyFrame:
    """Return a LazyFrame with SME exposures for correlation adjustment.

    Note: turnover_m is in GBP millions, converted to EUR using eur_gbp_rate (0.8732).
    GBP values are chosen so they convert to nice EUR amounts:
    - GBP 4.366m → EUR 5m (min SME threshold)
    - GBP 21.83m → EUR 25m (mid SME)
    - GBP 87.32m → EUR 100m (large corp, above 50m threshold)
    """
    return pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "pd": [0.01, 0.01, 0.01],
        "lgd": [0.45, 0.45, 0.45],
        "ead_final": [1_000_000.0, 1_000_000.0, 1_000_000.0],
        "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
        "maturity": [2.5, 2.5, 2.5],
        "turnover_m": [4.366, 21.83, 87.32],  # GBP values converting to EUR 5m, 25m, 100m
        "approach": ["foundation_irb", "foundation_irb", "foundation_irb"],
    })


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestIRBNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, basic_lazyframe: pl.LazyFrame) -> None:
        """LazyFrame should have .irb namespace available."""
        assert hasattr(basic_lazyframe, "irb")

    def test_expr_namespace_registered(self) -> None:
        """Expression should have .irb namespace available."""
        expr = pl.col("pd")
        assert hasattr(expr, "irb")

    def test_namespace_methods_available(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Namespace should have expected methods."""
        irb = basic_lazyframe.irb
        expected_methods = [
            "classify_approach",
            "apply_firb_lgd",
            "prepare_columns",
            "apply_pd_floor",
            "apply_lgd_floor",
            "calculate_correlation",
            "calculate_k",
            "calculate_maturity_adjustment",
            "calculate_rwa",
            "calculate_expected_loss",
            "apply_all_formulas",
            "select_expected_loss",
            "build_audit",
        ]
        for method in expected_methods:
            assert hasattr(irb, method), f"Missing method: {method}"


# =============================================================================
# PD Floor Tests
# =============================================================================


class TestApplyPdFloor:
    """Tests for PD floor application."""

    def test_crr_pd_floor_applied(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """CRR PD floor (0.03%) should be applied to PD below floor."""
        result = basic_lazyframe.irb.apply_pd_floor(crr_config).collect()

        # Third exposure has PD = 0.0001 (0.01%), should be floored to 0.0003 (0.03%)
        assert result["pd_floored"][2] == pytest.approx(0.0003)

    def test_pd_above_floor_unchanged(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """PD above floor should remain unchanged."""
        result = basic_lazyframe.irb.apply_pd_floor(crr_config).collect()

        # First two exposures are above floor
        assert result["pd_floored"][0] == pytest.approx(0.01)
        assert result["pd_floored"][1] == pytest.approx(0.05)

    def test_basel31_higher_pd_floor(self, basic_lazyframe: pl.LazyFrame, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 PD floor (0.05%) should be higher than CRR."""
        result = basic_lazyframe.irb.apply_pd_floor(basel31_config).collect()

        # Third exposure should be floored to 0.0005 (0.05%)
        assert result["pd_floored"][2] == pytest.approx(0.0005)


# =============================================================================
# LGD Floor Tests
# =============================================================================


class TestApplyLgdFloor:
    """Tests for LGD floor application."""

    def test_crr_no_lgd_floor(self, crr_config: CalculationConfig) -> None:
        """CRR should not apply LGD floor."""
        lf = pl.LazyFrame({
            "lgd": [0.10, 0.20, 0.45],  # All below Basel 3.1 unsecured floor
        })
        result = lf.irb.apply_lgd_floor(crr_config).collect()

        # All LGDs should be unchanged
        assert result["lgd_floored"][0] == pytest.approx(0.10)
        assert result["lgd_floored"][1] == pytest.approx(0.20)
        assert result["lgd_floored"][2] == pytest.approx(0.45)

    def test_basel31_lgd_floor_applied(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 should apply 25% LGD floor for unsecured."""
        lf = pl.LazyFrame({
            "lgd": [0.10, 0.20, 0.45],  # First two below 25% floor
        })
        result = lf.irb.apply_lgd_floor(basel31_config).collect()

        # First two should be floored to 0.25
        assert result["lgd_floored"][0] == pytest.approx(0.25)
        assert result["lgd_floored"][1] == pytest.approx(0.25)
        # Third is above floor, unchanged
        assert result["lgd_floored"][2] == pytest.approx(0.45)


# =============================================================================
# Correlation Tests
# =============================================================================


class TestCalculateCorrelation:
    """Tests for correlation calculation."""

    def test_corporate_correlation_range(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Corporate correlation should be between 0.12 and 0.24."""
        result = (basic_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
            .irb.calculate_correlation(crr_config)
            .collect()
        )

        for corr in result["correlation"]:
            assert 0.12 <= corr <= 0.24

    def test_retail_mortgage_fixed_correlation(self, retail_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Retail mortgage should have fixed 0.15 correlation."""
        result = (retail_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
            .irb.calculate_correlation(crr_config)
            .collect()
        )

        # First exposure is RETAIL_MORTGAGE
        assert result["correlation"][0] == pytest.approx(0.15)

    def test_qrre_fixed_correlation(self, retail_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """QRRE should have fixed 0.04 correlation."""
        result = (retail_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
            .irb.calculate_correlation(crr_config)
            .collect()
        )

        # Second exposure is RETAIL_QRRE
        assert result["correlation"][1] == pytest.approx(0.04)

    def test_sme_correlation_adjustment(self, sme_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """SME turnover should reduce corporate correlation."""
        result = (sme_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .irb.calculate_correlation(crr_config)
            .collect()
        )

        # Small SME (5m) should have lowest correlation
        # Mid SME (25m) should have medium correlation
        # Large corp (100m) should have standard correlation
        assert result["correlation"][0] < result["correlation"][1]
        assert result["correlation"][1] < result["correlation"][2]

        # Large corp should have no SME adjustment
        # At PD=1%, correlation is approximately 0.19
        assert result["correlation"][2] == pytest.approx(0.19, rel=0.1)


# =============================================================================
# Capital K Tests
# =============================================================================


class TestCalculateK:
    """Tests for capital requirement (K) calculation."""

    def test_k_positive(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """K should be positive for normal exposures."""
        result = (basic_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
            .irb.calculate_correlation(crr_config)
            .irb.calculate_k(crr_config)
            .collect()
        )

        for k in result["k"]:
            assert k > 0

    def test_k_less_than_lgd(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """K should be less than LGD for non-defaulted exposures."""
        result = (basic_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
            .irb.calculate_correlation(crr_config)
            .irb.calculate_k(crr_config)
            .collect()
        )

        for i, k in enumerate(result["k"]):
            lgd = result["lgd_floored"][i]
            assert k < lgd

    def test_k_increases_with_pd(self, crr_config: CalculationConfig) -> None:
        """K should increase with PD."""
        lf = pl.LazyFrame({
            "pd": [0.01, 0.05, 0.10],
            "lgd": [0.45, 0.45, 0.45],
            "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
            "turnover_m": [None, None, None],
        })

        result = (lf
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .irb.calculate_correlation(crr_config)
            .irb.calculate_k(crr_config)
            .collect()
        )

        assert result["k"][0] < result["k"][1] < result["k"][2]


# =============================================================================
# Maturity Adjustment Tests
# =============================================================================


class TestCalculateMaturityAdjustment:
    """Tests for maturity adjustment calculation."""

    def test_ma_greater_than_one_at_base_maturity(self, crr_config: CalculationConfig) -> None:
        """MA at 2.5 years should be > 1.0 due to denominator."""
        lf = pl.LazyFrame({
            "pd_floored": [0.01],
            "maturity": [2.5],
            "exposure_class": ["CORPORATE"],
        })

        result = lf.irb.calculate_maturity_adjustment(crr_config).collect()
        assert result["maturity_adjustment"][0] > 1.0
        assert result["maturity_adjustment"][0] < 1.5  # Reasonable bound

    def test_ma_increases_with_maturity(self, crr_config: CalculationConfig) -> None:
        """MA should increase with maturity above 2.5 years."""
        lf = pl.LazyFrame({
            "pd_floored": [0.01, 0.01, 0.01],
            "maturity": [1.0, 2.5, 5.0],
            "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
        })

        result = lf.irb.calculate_maturity_adjustment(crr_config).collect()
        assert result["maturity_adjustment"][0] < result["maturity_adjustment"][1]
        assert result["maturity_adjustment"][1] < result["maturity_adjustment"][2]

    def test_retail_no_maturity_adjustment(self, retail_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Retail exposures should have MA = 1.0."""
        result = (retail_lazyframe
            .irb.apply_pd_floor(crr_config)
            .irb.calculate_maturity_adjustment(crr_config)
            .collect()
        )

        # All retail exposures should have MA = 1.0
        for ma in result["maturity_adjustment"]:
            assert ma == pytest.approx(1.0)


# =============================================================================
# Exact Fractional Years Tests
# =============================================================================


class TestExactFractionalYears:
    """Tests for exact fractional years calculation from maturity_date.

    The calculation uses ordinal days and accounts for leap years:
        years = (end_year - start_year) + (end_ordinal/end_days) - (start_ordinal/start_days)
    """

    def test_same_year_calculation(self, crr_config: CalculationConfig) -> None:
        """Fractional years within same year should be accurate."""
        # reporting_date is 2024-12-31 (leap year)
        # maturity_date is 2024-03-15 would be negative, so use a future date
        # Let's create a config with earlier reporting date
        config = CalculationConfig.crr(reporting_date=date(2024, 3, 15))

        lf = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead": [1_000_000.0],
            "maturity_date": [date(2024, 6, 15)],  # 92 days later
            "exposure_class": ["CORPORATE"],
            "approach": ["foundation_irb"],
        })

        result = (lf
            .irb.classify_approach(config)
            .irb.apply_firb_lgd(config)
            .irb.prepare_columns(config)
            .collect()
        )

        # 2024 is a leap year (366 days)
        # March 15 = day 75, June 15 = day 167
        # Expected: (167 - 75) / 366 = 92 / 366 = 0.2514
        # But floored to 1.0
        assert result["maturity"][0] == pytest.approx(1.0)  # Floored

    def test_cross_year_calculation(self, crr_config: CalculationConfig) -> None:
        """Fractional years crossing year boundary should be accurate."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 15))

        lf = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead": [1_000_000.0],
            "maturity_date": [date(2027, 3, 15)],  # ~2.25 years
            "exposure_class": ["CORPORATE"],
            "approach": ["foundation_irb"],
        })

        result = (lf
            .irb.classify_approach(config)
            .irb.apply_firb_lgd(config)
            .irb.prepare_columns(config)
            .collect()
        )

        # 2024-12-15 to 2027-03-15
        # Start: 2024 (leap), ordinal 350, 350/366 = 0.9563
        # End: 2027 (non-leap), ordinal 74, 74/365 = 0.2027
        # Years = (2027 - 2024) + 0.2027 - 0.9563 = 3 - 0.7536 = 2.2464
        assert result["maturity"][0] == pytest.approx(2.2464, rel=0.01)

    def test_leap_year_handling(self) -> None:
        """Leap years should be handled correctly in calculation."""
        # Use a reporting date in a non-leap year
        config = CalculationConfig.crr(reporting_date=date(2025, 6, 15))

        lf = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead": [1_000_000.0],
            "maturity_date": [date(2028, 6, 15)],  # Exactly 3 years (2028 is leap)
            "exposure_class": ["CORPORATE"],
            "approach": ["foundation_irb"],
        })

        result = (lf
            .irb.classify_approach(config)
            .irb.apply_firb_lgd(config)
            .irb.prepare_columns(config)
            .collect()
        )

        # 2025-06-15 to 2028-06-15
        # Start: 2025 (non-leap), ordinal 166, 166/365 = 0.4548
        # End: 2028 (leap), ordinal 167, 167/366 = 0.4563
        # Years = (2028 - 2025) + 0.4563 - 0.4548 = 3.0015
        assert result["maturity"][0] == pytest.approx(3.0, rel=0.01)

    def test_maturity_from_date_vs_direct(self, crr_config: CalculationConfig) -> None:
        """Maturity calculated from date should work in full pipeline."""
        lf = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead": [1_000_000.0],
            "maturity_date": [date(2027, 12, 31)],  # 3 years from reporting_date
            "exposure_class": ["CORPORATE"],
            "approach": ["foundation_irb"],
        })

        result = (lf
            .irb.classify_approach(crr_config)
            .irb.apply_firb_lgd(crr_config)
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )

        # Should have valid RWA
        assert result["rwa"][0] > 0
        # Maturity should be approximately 3 years
        assert 2.9 < result["maturity"][0] < 3.1


# =============================================================================
# RWA Calculation Tests
# =============================================================================


class TestCalculateRwa:
    """Tests for RWA calculation."""

    def test_rwa_formula_with_scaling(self, crr_config: CalculationConfig) -> None:
        """RWA = K × 12.5 × 1.06 × EAD × MA under CRR."""
        lf = pl.LazyFrame({
            "k": [0.05],
            "ead_final": [1_000_000.0],
            "maturity_adjustment": [1.2],
        })

        result = lf.irb.calculate_rwa(crr_config).collect()

        expected_rwa = 0.05 * 12.5 * 1.06 * 1_000_000.0 * 1.2
        assert result["rwa"][0] == pytest.approx(expected_rwa)
        assert result["scaling_factor"][0] == pytest.approx(1.06)

    def test_rwa_formula_without_scaling(self, basel31_config: CalculationConfig) -> None:
        """RWA = K × 12.5 × EAD × MA under Basel 3.1 (no 1.06 scaling)."""
        lf = pl.LazyFrame({
            "k": [0.05],
            "ead_final": [1_000_000.0],
            "maturity_adjustment": [1.2],
        })

        result = lf.irb.calculate_rwa(basel31_config).collect()

        expected_rwa = 0.05 * 12.5 * 1_000_000.0 * 1.2  # No 1.06
        assert result["rwa"][0] == pytest.approx(expected_rwa)
        assert result["scaling_factor"][0] == pytest.approx(1.0)

    def test_scaling_factor_difference(self) -> None:
        """CRR RWA should be 6% higher than Basel 3.1 due to scaling."""
        lf = pl.LazyFrame({
            "k": [0.05],
            "ead_final": [1_000_000.0],
            "maturity_adjustment": [1.2],
        })

        crr = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        basel = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))

        crr_result = lf.irb.calculate_rwa(crr).collect()
        basel_result = lf.irb.calculate_rwa(basel).collect()

        ratio = crr_result["rwa"][0] / basel_result["rwa"][0]
        assert ratio == pytest.approx(1.06)


# =============================================================================
# Expected Loss Tests
# =============================================================================


class TestCalculateExpectedLoss:
    """Tests for expected loss calculation."""

    def test_expected_loss_formula(self, crr_config: CalculationConfig) -> None:
        """EL = PD × LGD × EAD."""
        lf = pl.LazyFrame({
            "pd_floored": [0.01],
            "lgd_floored": [0.45],
            "ead_final": [1_000_000.0],
        })

        result = lf.irb.calculate_expected_loss(crr_config).collect()
        expected = 0.01 * 0.45 * 1_000_000.0  # 4500
        assert result["expected_loss"][0] == pytest.approx(expected)


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestApplyAllFormulas:
    """Tests for full IRB formula pipeline."""

    def test_apply_all_formulas_adds_expected_columns(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """apply_all_formulas should add all expected columns."""
        result = basic_lazyframe.irb.apply_all_formulas(crr_config).collect()

        expected_columns = [
            "pd_floored",
            "lgd_floored",
            "correlation",
            "k",
            "maturity_adjustment",
            "scaling_factor",
            "rwa",
            "risk_weight",
            "expected_loss",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_apply_all_formulas_all_rwa_positive(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """All RWAs should be positive."""
        result = basic_lazyframe.irb.apply_all_formulas(crr_config).collect()

        for rwa in result["rwa"]:
            assert rwa > 0

    def test_apply_all_formulas_preserves_rows(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Number of rows should be preserved."""
        original_count = basic_lazyframe.collect().shape[0]
        result = basic_lazyframe.irb.apply_all_formulas(crr_config).collect()
        assert result.shape[0] == original_count


# =============================================================================
# Method Chaining Tests
# =============================================================================


class TestMethodChaining:
    """Tests for method chaining."""

    def test_full_pipeline_chain(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Full pipeline should work with method chaining."""
        result = (basic_lazyframe
            .irb.classify_approach(crr_config)
            .irb.apply_firb_lgd(crr_config)
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )

        assert "rwa" in result.columns
        assert "correlation" in result.columns
        assert "k" in result.columns

    def test_individual_step_chain(self, crr_config: CalculationConfig) -> None:
        """Individual steps should be chainable."""
        lf = pl.LazyFrame({
            "pd": [0.01],
            "lgd": [0.45],
            "ead_final": [1_000_000.0],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "turnover_m": [None],
        })

        result = (lf
            .irb.apply_pd_floor(crr_config)
            .irb.apply_lgd_floor(crr_config)
            .irb.calculate_correlation(crr_config)
            .irb.calculate_k(crr_config)
            .irb.calculate_maturity_adjustment(crr_config)
            .irb.calculate_rwa(crr_config)
            .irb.calculate_expected_loss(crr_config)
            .collect()
        )

        assert "rwa" in result.columns
        assert result["rwa"][0] > 0


# =============================================================================
# Expression Namespace Tests
# =============================================================================


class TestExprNamespace:
    """Tests for expression namespace methods."""

    def test_floor_pd(self) -> None:
        """floor_pd should apply PD floor."""
        df = pl.DataFrame({"pd": [0.0001, 0.01, 0.05]})
        result = df.with_columns(
            pl.col("pd").irb.floor_pd(0.0003).alias("pd_floored")
        )

        assert result["pd_floored"][0] == pytest.approx(0.0003)
        assert result["pd_floored"][1] == pytest.approx(0.01)
        assert result["pd_floored"][2] == pytest.approx(0.05)

    def test_floor_lgd(self) -> None:
        """floor_lgd should apply LGD floor."""
        df = pl.DataFrame({"lgd": [0.10, 0.25, 0.45]})
        result = df.with_columns(
            pl.col("lgd").irb.floor_lgd(0.25).alias("lgd_floored")
        )

        assert result["lgd_floored"][0] == pytest.approx(0.25)
        assert result["lgd_floored"][1] == pytest.approx(0.25)
        assert result["lgd_floored"][2] == pytest.approx(0.45)

    def test_clip_maturity(self) -> None:
        """clip_maturity should apply floor and cap."""
        df = pl.DataFrame({"maturity": [0.5, 2.5, 10.0]})
        result = df.with_columns(
            pl.col("maturity").irb.clip_maturity(floor=1.0, cap=5.0).alias("maturity_clipped")
        )

        assert result["maturity_clipped"][0] == pytest.approx(1.0)  # Floored
        assert result["maturity_clipped"][1] == pytest.approx(2.5)  # Unchanged
        assert result["maturity_clipped"][2] == pytest.approx(5.0)  # Capped


# =============================================================================
# Output Method Tests
# =============================================================================


class TestOutputMethods:
    """Tests for output convenience methods."""

    def test_select_expected_loss(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """select_expected_loss should return EL columns only."""
        result = (basic_lazyframe
            .irb.apply_all_formulas(crr_config)
            .irb.select_expected_loss()
            .collect()
        )

        expected_cols = ["exposure_reference", "pd", "lgd", "ead", "expected_loss"]
        assert list(result.columns) == expected_cols

    def test_build_audit(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """build_audit should include calculation string."""
        result = (basic_lazyframe
            .irb.apply_all_formulas(crr_config)
            .irb.build_audit()
            .collect()
        )

        assert "irb_calculation" in result.columns
        calc_str = result["irb_calculation"][0]
        assert "PD=" in calc_str
        assert "LGD=" in calc_str
        assert "R=" in calc_str
        assert "K=" in calc_str
        assert "RWA=" in calc_str


# =============================================================================
# Integration with Existing Tests (Backward Compatibility)
# =============================================================================


class TestBackwardCompatibility:
    """Tests to ensure namespace produces same results as existing functions."""

    def test_matches_apply_irb_formulas_function(self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig) -> None:
        """Namespace results should match apply_irb_formulas function."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        # Add turnover_m for correlation calculation
        lf = basic_lazyframe.with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))

        # Using existing function
        result_function = apply_irb_formulas(lf, crr_config).collect()

        # Using namespace
        result_namespace = lf.irb.apply_all_formulas(crr_config).collect()

        # Compare key columns
        for col in ["pd_floored", "lgd_floored", "correlation", "k", "rwa", "expected_loss"]:
            for i in range(len(result_function)):
                assert result_function[col][i] == pytest.approx(result_namespace[col][i], rel=1e-6), \
                    f"Mismatch in {col} at row {i}"
