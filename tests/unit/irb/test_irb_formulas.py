"""
Comprehensive unit tests for IRB formula components.

Covers:
- Stats backend (normal_cdf, normal_ppf) — previously zero test coverage
- PD floor expressions (CRR uniform, Basel 3.1 differentiated per exposure class)
- LGD floor expressions (CRR zero, Basel 3.1 per class/collateral)
- Correlation formula (all exposure classes, SME adjustment CRR vs B31, FI scalar)
- Capital K formula (edge cases, known values, monotonicity)
- Maturity adjustment (boundaries, formula verification)
- F-IRB LGD pipeline (FSE vs non-FSE, CRR vs B31)
- Full apply_irb_formulas pipeline integration
- Scalar vs vectorized consistency

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 160/163: PD floors
- CRR Art. 161/164: LGD floors
- CRR Art. 162: Maturity
- PRA PS1/26 Art. 153(4): SME GBP thresholds
- CRE30.55: Basel 3.1 differentiated PD floors
- CRE30.41: Basel 3.1 LGD floors
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.irb.formulas import (
    G_999,
    apply_irb_formulas,
    calculate_correlation,
    calculate_double_default_k,
    calculate_expected_loss,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
    get_correlation_params,
)
from rwa_calc.engine.irb.stats_backend import normal_cdf, normal_ppf


# =============================================================================
# STATS BACKEND TESTS (previously zero coverage)
# =============================================================================


class TestNormalCDF:
    """Tests for normal_cdf() Polars expression wrapper."""

    def test_cdf_at_zero(self) -> None:
        """CDF(0) = 0.5 by symmetry of standard normal."""
        df = pl.DataFrame({"x": [0.0]})
        result = df.select(normal_cdf(pl.col("x")).alias("cdf"))
        assert result["cdf"][0] == pytest.approx(0.5, abs=1e-10)

    def test_cdf_at_large_positive(self) -> None:
        """CDF(5) ≈ 1.0 (deep right tail)."""
        df = pl.DataFrame({"x": [5.0]})
        result = df.select(normal_cdf(pl.col("x")).alias("cdf"))
        assert result["cdf"][0] == pytest.approx(1.0, abs=1e-6)

    def test_cdf_at_large_negative(self) -> None:
        """CDF(-5) ≈ 0.0 (deep left tail)."""
        df = pl.DataFrame({"x": [-5.0]})
        result = df.select(normal_cdf(pl.col("x")).alias("cdf"))
        assert result["cdf"][0] == pytest.approx(0.0, abs=1e-6)

    def test_cdf_symmetry(self) -> None:
        """CDF(x) + CDF(-x) = 1 for all x."""
        df = pl.DataFrame({"x": [1.0, 2.0, 0.5, 3.0]})
        result = df.select(
            normal_cdf(pl.col("x")).alias("cdf_pos"),
            normal_cdf(-pl.col("x")).alias("cdf_neg"),
        )
        for pos, neg in zip(result["cdf_pos"], result["cdf_neg"]):
            assert pos + neg == pytest.approx(1.0, abs=1e-12)

    def test_cdf_monotonically_increasing(self) -> None:
        """CDF is strictly increasing."""
        df = pl.DataFrame({"x": [-3.0, -1.0, 0.0, 1.0, 3.0]})
        result = df.select(normal_cdf(pl.col("x")).alias("cdf"))
        values = result["cdf"].to_list()
        for i in range(len(values) - 1):
            assert values[i] < values[i + 1]

    def test_cdf_known_values(self) -> None:
        """Verify CDF at standard z-scores."""
        df = pl.DataFrame({"x": [1.0, -1.0, 1.96, 2.576]})
        result = df.select(normal_cdf(pl.col("x")).alias("cdf"))
        vals = result["cdf"].to_list()
        assert vals[0] == pytest.approx(0.8413, abs=1e-3)  # CDF(1) ≈ 0.8413
        assert vals[1] == pytest.approx(0.1587, abs=1e-3)  # CDF(-1) ≈ 0.1587
        assert vals[2] == pytest.approx(0.975, abs=1e-3)  # CDF(1.96) ≈ 0.975
        assert vals[3] == pytest.approx(0.995, abs=1e-3)  # CDF(2.576) ≈ 0.995

    def test_cdf_vectorized(self) -> None:
        """CDF processes multiple values in a single expression."""
        df = pl.DataFrame({"x": [-2.0, -1.0, 0.0, 1.0, 2.0]})
        result = df.select(normal_cdf(pl.col("x")).alias("cdf"))
        assert result.height == 5
        assert all(0 <= v <= 1 for v in result["cdf"].to_list())


class TestNormalPPF:
    """Tests for normal_ppf() Polars expression wrapper (inverse CDF)."""

    def test_ppf_at_half(self) -> None:
        """PPF(0.5) = 0 (median of standard normal)."""
        df = pl.DataFrame({"p": [0.5]})
        result = df.select(normal_ppf(pl.col("p")).alias("z"))
        assert result["z"][0] == pytest.approx(0.0, abs=1e-10)

    def test_ppf_at_999(self) -> None:
        """PPF(0.999) ≈ 3.09 — matches the G_999 constant used in K formula."""
        df = pl.DataFrame({"p": [0.999]})
        result = df.select(normal_ppf(pl.col("p")).alias("z"))
        assert result["z"][0] == pytest.approx(G_999, abs=1e-4)

    def test_ppf_at_001(self) -> None:
        """PPF(0.001) ≈ -3.09 — symmetric to PPF(0.999)."""
        df = pl.DataFrame({"p": [0.001]})
        result = df.select(normal_ppf(pl.col("p")).alias("z"))
        assert result["z"][0] == pytest.approx(-G_999, abs=1e-4)

    def test_ppf_cdf_roundtrip(self) -> None:
        """CDF(PPF(p)) ≈ p — roundtrip identity."""
        probs = [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
        df = pl.DataFrame({"p": probs})
        result = df.select(normal_cdf(normal_ppf(pl.col("p"))).alias("roundtrip"))
        for orig, rt in zip(probs, result["roundtrip"].to_list()):
            assert rt == pytest.approx(orig, abs=1e-10)

    def test_cdf_ppf_roundtrip(self) -> None:
        """PPF(CDF(x)) ≈ x — inverse roundtrip identity."""
        xs = [-2.0, -1.0, 0.0, 1.0, 2.0]
        df = pl.DataFrame({"x": xs})
        result = df.select(normal_ppf(normal_cdf(pl.col("x"))).alias("roundtrip"))
        for orig, rt in zip(xs, result["roundtrip"].to_list()):
            assert rt == pytest.approx(orig, abs=1e-10)

    def test_ppf_monotonically_increasing(self) -> None:
        """PPF is strictly increasing on (0, 1)."""
        df = pl.DataFrame({"p": [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]})
        result = df.select(normal_ppf(pl.col("p")).alias("z"))
        values = result["z"].to_list()
        for i in range(len(values) - 1):
            assert values[i] < values[i + 1]

    def test_ppf_known_critical_values(self) -> None:
        """Verify PPF at standard quantiles."""
        df = pl.DataFrame({"p": [0.025, 0.05, 0.95, 0.975]})
        result = df.select(normal_ppf(pl.col("p")).alias("z"))
        vals = result["z"].to_list()
        assert vals[0] == pytest.approx(-1.96, abs=0.01)
        assert vals[1] == pytest.approx(-1.645, abs=0.01)
        assert vals[2] == pytest.approx(1.645, abs=0.01)
        assert vals[3] == pytest.approx(1.96, abs=0.01)


# =============================================================================
# PD FLOOR TESTS — Basel 3.1 differentiated floors (PRA Art. 160/163)
# =============================================================================


class TestPDFloorsCRR:
    """CRR PD floors: uniform 0.03% for all exposure classes."""

    @pytest.fixture()
    def crr_config(self) -> CalculationConfig:
        return CalculationConfig.crr(reporting_date=date(2026, 1, 1))

    @pytest.mark.parametrize(
        "exposure_class",
        [
            "corporate",
            "corporate_sme",
            "retail_mortgage",
            "retail_qrre",
            "retail_other",
            "institution",
            "central_govt_central_bank",
        ],
    )
    def test_crr_uniform_floor(self, crr_config: CalculationConfig, exposure_class: str) -> None:
        """CRR applies 0.03% floor uniformly to all exposure classes (Art. 163)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],  # Below floor
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": [exposure_class],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0003, abs=1e-8)

    def test_crr_pd_above_floor_unchanged(self, crr_config: CalculationConfig) -> None:
        """PD above floor passes through unchanged."""
        lf = pl.LazyFrame(
            {
                "pd": [0.05],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.05, abs=1e-8)


class TestPDFloorsBasel31:
    """Basel 3.1 PD floors: differentiated by exposure class."""

    @pytest.fixture()
    def b31_config(self) -> CalculationConfig:
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))

    def test_b31_corporate_floor_005pct(self, b31_config: CalculationConfig) -> None:
        """Corporate PD floor = 0.05% (Art. 160(1))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.40],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005, abs=1e-8)

    def test_b31_corporate_sme_floor_005pct(self, b31_config: CalculationConfig) -> None:
        """Corporate SME PD floor = 0.05% (Art. 160(1))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.40],
                "ead_final": [1_000_000.0],
                "exposure_class": ["CORPORATE_SME"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005, abs=1e-8)

    def test_b31_retail_mortgage_floor_010pct(self, b31_config: CalculationConfig) -> None:
        """Retail mortgage PD floor = 0.10% (Art. 163(1)(b))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.10],
                "ead_final": [500_000.0],
                "exposure_class": ["retail_mortgage"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0010, abs=1e-8)

    def test_b31_qrre_transactor_floor_005pct(self, b31_config: CalculationConfig) -> None:
        """QRRE transactor PD floor = 0.05% (Art. 163(1)(c))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.50],
                "ead_final": [10_000.0],
                "exposure_class": ["retail_qrre"],
                "is_qrre_transactor": [True],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005, abs=1e-8)

    def test_b31_qrre_revolver_floor_010pct(self, b31_config: CalculationConfig) -> None:
        """QRRE revolver PD floor = 0.10% (Art. 163(1)(a))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.50],
                "ead_final": [10_000.0],
                "exposure_class": ["retail_qrre"],
                "is_qrre_transactor": [False],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0010, abs=1e-8)

    def test_b31_retail_other_floor_005pct(self, b31_config: CalculationConfig) -> None:
        """Retail other PD floor = 0.05% (Art. 163(1)(c))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.30],
                "ead_final": [50_000.0],
                "exposure_class": ["retail_other"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005, abs=1e-8)

    def test_b31_null_exposure_class_defaults_to_corporate(
        self, b31_config: CalculationConfig
    ) -> None:
        """Null exposure_class falls back to corporate floor (0.05%)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.40],
                "ead_final": [1_000_000.0],
                "exposure_class": [None],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005, abs=1e-8)

    def test_b31_without_transactor_col_qrre_uses_revolver_floor(
        self, b31_config: CalculationConfig
    ) -> None:
        """Without is_qrre_transactor column, QRRE uses conservative revolver floor (0.10%)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.0001],
                "lgd": [0.50],
                "ead_final": [10_000.0],
                "exposure_class": ["retail_qrre"],
                "is_airb": [True],
            }
        )
        # No is_qrre_transactor column
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0010, abs=1e-8)


# =============================================================================
# LGD FLOOR TESTS — Basel 3.1 A-IRB floors (PRA Art. 161/164)
# =============================================================================


class TestLGDFloorsBasel31:
    """Basel 3.1 LGD floors for A-IRB exposures."""

    @pytest.fixture()
    def b31_config(self) -> CalculationConfig:
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))

    @pytest.fixture()
    def crr_config(self) -> CalculationConfig:
        return CalculationConfig.crr(reporting_date=date(2026, 1, 1))

    def test_crr_no_lgd_floors(self, crr_config: CalculationConfig) -> None:
        """CRR has no LGD floors — lgd_floored equals lgd."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.10],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10, abs=1e-8)

    def test_b31_corporate_unsecured_floor_25pct(self, b31_config: CalculationConfig) -> None:
        """A-IRB corporate unsecured: LGD floor = 25% (Art. 161(5))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.10],  # Below 25% floor
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25, abs=1e-4)

    def test_b31_corporate_lgd_above_floor_unchanged(
        self, b31_config: CalculationConfig
    ) -> None:
        """LGD above floor passes through unchanged."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.40],  # Above 25% floor
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.40, abs=1e-8)

    def test_b31_retail_mortgage_floor_5pct(self, b31_config: CalculationConfig) -> None:
        """A-IRB retail mortgage: LGD floor = 5% (Art. 164(4)(a))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.005],
                "lgd": [0.02],  # Below 5% floor
                "ead_final": [300_000.0],
                "exposure_class": ["retail_mortgage"],
                "is_airb": [True],
                "collateral_type": ["real_estate"],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.05, abs=1e-4)

    def test_b31_retail_qrre_unsecured_floor_50pct(
        self, b31_config: CalculationConfig
    ) -> None:
        """A-IRB QRRE unsecured: LGD floor = 50% (Art. 164(4)(b)(i))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.30],  # Below 50% floor
                "ead_final": [10_000.0],
                "exposure_class": ["retail_qrre"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.50, abs=1e-4)

    def test_b31_retail_other_unsecured_floor_30pct(
        self, b31_config: CalculationConfig
    ) -> None:
        """A-IRB retail other unsecured: LGD floor = 30% (Art. 164(4)(b)(ii))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.15],  # Below 30% floor
                "ead_final": [50_000.0],
                "exposure_class": ["retail_other"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.30, abs=1e-4)

    def test_b31_firb_not_floored(self, b31_config: CalculationConfig) -> None:
        """F-IRB supervisory LGDs are NOT floored — only A-IRB own estimates."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.10],  # Below corporate floor 25%, but F-IRB
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "is_airb": [False],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10, abs=1e-8)

    def test_b31_financial_collateral_floor_0pct(self, b31_config: CalculationConfig) -> None:
        """Financial collateral LGD floor = 0% (Art. 161(5))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.0],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "collateral_type": ["financial"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.0, abs=1e-8)

    def test_b31_other_physical_collateral_floor_15pct(
        self, b31_config: CalculationConfig
    ) -> None:
        """Other physical collateral LGD floor = 15% (Art. 161(5))."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.05],  # Below 15% floor
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "collateral_type": ["other_physical"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.15, abs=1e-4)

    def test_b31_subordinated_corporate_floor_25pct_with_exposure_class(
        self, b31_config: CalculationConfig
    ) -> None:
        """Subordinated corporate: LGD floor = 25% when exposure_class present.

        Art. 161(5) floor is 25% for all corporate unsecured regardless of seniority.
        The 50% subordinated_unsecured in config is a conservative fallback for when
        exposure_class column is absent.
        """
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.10],  # Below 25% corporate floor
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, b31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25, abs=1e-4)

    def test_b31_subordinated_fallback_50pct_without_exposure_class(
        self, b31_config: CalculationConfig
    ) -> None:
        """Without exposure_class column, subordinated gets conservative 50% floor.

        Tests _lgd_floor_expression directly since apply_irb_formulas requires
        exposure_class for other steps (correlation, defaulted treatment).
        """
        from rwa_calc.engine.irb.formulas import _lgd_floor_expression

        lgd_floor_expr = _lgd_floor_expression(
            b31_config, has_seniority=True, has_exposure_class=False
        )
        lf = pl.LazyFrame({"lgd": [0.30], "seniority": ["subordinated"]})
        result = lf.with_columns(
            pl.max_horizontal(pl.col("lgd"), lgd_floor_expr).alias("lgd_floored")
        ).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.50, abs=1e-4)


# =============================================================================
# CORRELATION TESTS
# =============================================================================


class TestCorrelation:
    """Tests for asset correlation calculation."""

    def test_corporate_low_pd_near_max(self) -> None:
        """Corporate at very low PD → correlation ≈ 0.24 (r_max)."""
        r = calculate_correlation(0.0003, "corporate")
        assert r == pytest.approx(0.24, abs=0.005)

    def test_corporate_high_pd_near_min(self) -> None:
        """Corporate at high PD → correlation ≈ 0.12 (r_min)."""
        r = calculate_correlation(0.99, "corporate")
        assert r == pytest.approx(0.12, abs=0.005)

    def test_corporate_mid_pd(self) -> None:
        """Corporate at mid PD → between 0.12 and 0.24."""
        r = calculate_correlation(0.01, "corporate")
        assert 0.12 < r < 0.24

    def test_retail_mortgage_fixed_015(self) -> None:
        """Retail mortgage: fixed correlation = 0.15."""
        r = calculate_correlation(0.01, "retail_mortgage")
        assert r == pytest.approx(0.15, abs=1e-6)

    def test_retail_mortgage_fixed_regardless_of_pd(self) -> None:
        """Retail mortgage correlation is PD-independent."""
        r_low = calculate_correlation(0.001, "RETAIL_MORTGAGE")
        r_high = calculate_correlation(0.50, "RETAIL_MORTGAGE")
        assert r_low == pytest.approx(r_high, abs=1e-10)

    def test_qrre_fixed_004(self) -> None:
        """QRRE: fixed correlation = 0.04."""
        r = calculate_correlation(0.01, "retail_qrre")
        assert r == pytest.approx(0.04, abs=1e-6)

    def test_retail_other_low_pd_near_max(self) -> None:
        """Retail other at very low PD → correlation ≈ 0.16 (r_max)."""
        r = calculate_correlation(0.0003, "retail_other")
        assert r == pytest.approx(0.16, abs=0.005)

    def test_retail_other_high_pd_near_min(self) -> None:
        """Retail other at high PD → correlation ≈ 0.03 (r_min)."""
        r = calculate_correlation(0.99, "retail_other")
        assert r == pytest.approx(0.03, abs=0.005)

    def test_institution_uses_corporate_params(self) -> None:
        """Institutions use corporate correlation parameters."""
        r_inst = calculate_correlation(0.01, "institution")
        r_corp = calculate_correlation(0.01, "corporate")
        assert r_inst == pytest.approx(r_corp, abs=1e-10)

    def test_sovereign_uses_corporate_params(self) -> None:
        """Sovereigns use corporate correlation parameters."""
        r_sov = calculate_correlation(0.01, "central_govt_central_bank")
        r_corp = calculate_correlation(0.01, "corporate")
        assert r_sov == pytest.approx(r_corp, abs=1e-10)

    def test_unknown_class_defaults_to_corporate(self) -> None:
        """Unknown exposure class falls back to corporate."""
        r_unk = calculate_correlation(0.01, "some_unknown_class")
        r_corp = calculate_correlation(0.01, "corporate")
        assert r_unk == pytest.approx(r_corp, abs=1e-10)


class TestCorrelationSMEAdjustment:
    """Tests for SME firm-size correlation adjustment."""

    def test_crr_sme_reduces_correlation(self) -> None:
        """CRR SME adjustment reduces corporate correlation (EUR thresholds)."""
        r_no_sme = calculate_correlation(0.01, "corporate", turnover_m=None)
        # GBP 10m → EUR ~11.45m (below EUR 50m threshold)
        r_sme = calculate_correlation(0.01, "corporate", turnover_m=10.0)
        assert r_sme < r_no_sme

    def test_crr_sme_at_threshold_no_adjustment(self) -> None:
        """CRR: turnover at/above EUR 50m threshold → no SME adjustment."""
        # GBP 43.66m ≈ EUR 50m at rate 0.8732
        r_at_threshold = calculate_correlation(0.01, "corporate", turnover_m=43.66)
        r_no_turnover = calculate_correlation(0.01, "corporate", turnover_m=None)
        assert r_at_threshold == pytest.approx(r_no_turnover, abs=1e-4)

    def test_crr_sme_max_adjustment_at_floor(self) -> None:
        """CRR: very small turnover → maximum 0.04 correlation reduction."""
        r_no_sme = calculate_correlation(0.01, "corporate", turnover_m=None)
        r_min_turnover = calculate_correlation(0.01, "corporate", turnover_m=0.01)
        # s = max(5, min(turnover_eur, 50)) = 5; adjustment = 0.04 × (1 - 0/45) = 0.04
        assert r_no_sme - r_min_turnover == pytest.approx(0.04, abs=0.002)

    def test_b31_sme_uses_gbp_thresholds(self) -> None:
        """Basel 3.1: SME adjustment uses GBP thresholds (44m/4.4m) per Art. 153(4)."""
        # Below GBP 44m threshold → SME adjustment applies
        r_sme = calculate_correlation(0.01, "corporate", turnover_m=20.0, is_b31=True)
        r_no_sme = calculate_correlation(0.01, "corporate", turnover_m=None, is_b31=True)
        assert r_sme < r_no_sme

    def test_b31_sme_at_44m_no_adjustment(self) -> None:
        """Basel 3.1: GBP 44m+ → no SME adjustment."""
        r_at = calculate_correlation(0.01, "corporate", turnover_m=44.0, is_b31=True)
        r_none = calculate_correlation(0.01, "corporate", turnover_m=None, is_b31=True)
        assert r_at == pytest.approx(r_none, abs=1e-6)

    def test_b31_sme_max_reduction_at_floor(self) -> None:
        """Basel 3.1: GBP 4.4m floor → maximum 0.04 reduction."""
        r_no_sme = calculate_correlation(0.01, "corporate", turnover_m=None, is_b31=True)
        r_floor = calculate_correlation(0.01, "corporate", turnover_m=1.0, is_b31=True)
        assert r_no_sme - r_floor == pytest.approx(0.04, abs=0.002)

    def test_sme_null_turnover_no_adjustment(self) -> None:
        """Null turnover → no SME adjustment applied."""
        r_null = calculate_correlation(0.01, "corporate", turnover_m=None)
        r_high = calculate_correlation(0.01, "corporate", turnover_m=100.0)
        # Both should equal non-SME correlation (100m > 50m EUR threshold)
        assert r_null == pytest.approx(r_high, abs=1e-6)

    def test_sme_only_corporate(self) -> None:
        """SME adjustment only applies to corporate, not retail."""
        r_retail_no_sme = calculate_correlation(0.01, "retail_other", turnover_m=None)
        r_retail_sme = calculate_correlation(0.01, "retail_other", turnover_m=10.0)
        assert r_retail_no_sme == pytest.approx(r_retail_sme, abs=1e-10)


class TestCorrelationFIScalar:
    """Tests for FI scalar (1.25×) on correlation — CRR Art. 153(2)."""

    def test_fi_scalar_multiplies_by_125(self) -> None:
        """FI scalar multiplies base correlation by 1.25."""
        r_base = calculate_correlation(0.01, "corporate", apply_fi_scalar=False)
        r_fi = calculate_correlation(0.01, "corporate", apply_fi_scalar=True)
        assert r_fi == pytest.approx(r_base * 1.25, abs=1e-8)

    def test_fi_scalar_can_exceed_024(self) -> None:
        """FI scalar can push correlation above 0.24 for low-PD corporates."""
        r_fi = calculate_correlation(0.0003, "corporate", apply_fi_scalar=True)
        # At low PD, base ≈ 0.24; with FI → ≈ 0.30
        assert r_fi > 0.24

    def test_fi_scalar_on_retail_mortgage(self) -> None:
        """FI scalar on retail mortgage: 0.15 × 1.25 = 0.1875."""
        r_fi = calculate_correlation(0.01, "retail_mortgage", apply_fi_scalar=True)
        assert r_fi == pytest.approx(0.15 * 1.25, abs=1e-6)

    def test_fi_scalar_disabled_by_default(self) -> None:
        """FI scalar is not applied by default."""
        r_default = calculate_correlation(0.01, "corporate")
        r_explicit_false = calculate_correlation(0.01, "corporate", apply_fi_scalar=False)
        assert r_default == pytest.approx(r_explicit_false, abs=1e-10)


class TestCorrelationParams:
    """Tests for get_correlation_params() lookup."""

    def test_corporate_params(self) -> None:
        p = get_correlation_params("CORPORATE")
        assert p.r_min == 0.12
        assert p.r_max == 0.24
        assert p.decay_factor == 50.0

    def test_retail_mortgage_fixed(self) -> None:
        p = get_correlation_params("RETAIL_MORTGAGE")
        assert p.correlation_type == "fixed"
        assert p.fixed == 0.15

    def test_qrre_fixed(self) -> None:
        p = get_correlation_params("RETAIL_QRRE")
        assert p.correlation_type == "fixed"
        assert p.fixed == 0.04

    def test_retail_other_params(self) -> None:
        p = get_correlation_params("RETAIL_OTHER")
        assert p.r_min == 0.03
        assert p.r_max == 0.16
        assert p.decay_factor == 35.0

    def test_substring_matching_mortgage(self) -> None:
        p = get_correlation_params("residential_mortgage")
        assert p.fixed == 0.15

    def test_substring_matching_government(self) -> None:
        p = get_correlation_params("GOVERNMENT_BOND")
        assert p.r_min == 0.12  # Corporate params

    def test_unknown_defaults_to_corporate(self) -> None:
        p = get_correlation_params("SOME_UNKNOWN")
        assert p.r_min == 0.12
        assert p.r_max == 0.24


# =============================================================================
# CAPITAL K FORMULA TESTS
# =============================================================================


class TestCapitalK:
    """Tests for capital requirement K formula."""

    def test_k_positive_for_typical_corporate(self) -> None:
        """K is positive for a typical corporate exposure."""
        k = calculate_k(0.01, 0.45, 0.20)
        assert k > 0

    def test_k_zero_for_pd_zero(self) -> None:
        """K = 0 when PD = 0 (scalar wrapper short-circuit)."""
        k = calculate_k(0.0, 0.45, 0.20)
        assert k == 0.0

    def test_k_equals_lgd_for_pd_one(self) -> None:
        """K = LGD when PD = 1.0 (certain default, scalar wrapper)."""
        k = calculate_k(1.0, 0.45, 0.20)
        assert k == pytest.approx(0.45, abs=1e-8)

    def test_k_zero_for_zero_lgd(self) -> None:
        """K = 0 when LGD = 0 (no loss)."""
        k = calculate_k(0.01, 0.0, 0.20)
        assert k == pytest.approx(0.0, abs=1e-10)

    def test_k_increases_with_pd(self) -> None:
        """K increases monotonically with PD (all else equal)."""
        k_low = calculate_k(0.001, 0.45, 0.20)
        k_mid = calculate_k(0.01, 0.45, 0.20)
        k_high = calculate_k(0.10, 0.45, 0.20)
        assert k_low < k_mid < k_high

    def test_k_increases_with_lgd(self) -> None:
        """K increases monotonically with LGD (all else equal)."""
        k_low = calculate_k(0.01, 0.20, 0.20)
        k_high = calculate_k(0.01, 0.45, 0.20)
        assert k_low < k_high

    def test_k_increases_with_correlation(self) -> None:
        """K increases monotonically with correlation (all else equal)."""
        k_low_r = calculate_k(0.01, 0.45, 0.10)
        k_high_r = calculate_k(0.01, 0.45, 0.30)
        assert k_low_r < k_high_r

    def test_k_bounded_by_lgd(self) -> None:
        """K ≤ LGD always (capital requirement cannot exceed loss)."""
        for pd in [0.001, 0.01, 0.05, 0.10, 0.50, 0.99]:
            for lgd in [0.10, 0.25, 0.45, 1.0]:
                k = calculate_k(pd, lgd, 0.20)
                assert k <= lgd + 1e-10

    def test_k_non_negative(self) -> None:
        """K ≥ 0 always (floored at zero)."""
        for pd in [1e-6, 0.001, 0.01, 0.10, 0.50, 0.99]:
            k = calculate_k(pd, 0.45, 0.20)
            assert k >= -1e-10

    def test_k_realistic_range_corporate(self) -> None:
        """K for typical corporate (PD=1%, LGD=45%, R=0.20) in 2-10% range."""
        k = calculate_k(0.01, 0.45, 0.20)
        assert 0.02 < k < 0.10

    def test_k_formula_manual_verification(self) -> None:
        """Verify K against manual formula using the project's stats backend.

        K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD
        """
        pd_val, lgd_val, r = 0.01, 0.45, 0.20

        # Use project's own stats backend for the manual calculation
        df = pl.DataFrame({"pd": [pd_val], "g999_p": [0.999]})
        stats = df.select(
            normal_ppf(pl.col("pd")).alias("g_pd"),
            normal_ppf(pl.col("g999_p")).alias("g_999"),
        )
        g_pd = stats["g_pd"][0]
        g_999_val = stats["g_999"][0]

        term1 = (1 / (1 - r)) ** 0.5 * g_pd
        term2 = (r / (1 - r)) ** 0.5 * g_999_val
        cond_df = pl.DataFrame({"x": [term1 + term2]})
        conditional_pd = cond_df.select(normal_cdf(pl.col("x")).alias("cp"))["cp"][0]
        k_expected = lgd_val * conditional_pd - pd_val * lgd_val

        k_actual = calculate_k(pd_val, lgd_val, r)
        assert k_actual == pytest.approx(k_expected, rel=1e-6)

    def test_k_vectorized_matches_scalar(self) -> None:
        """Vectorized K expression matches scalar wrapper for multiple cases."""
        cases = [(0.01, 0.45, 0.20), (0.05, 0.30, 0.15), (0.001, 0.10, 0.04)]
        lf = pl.LazyFrame(
            {
                "pd_floored": [c[0] for c in cases],
                "lgd_floored": [c[1] for c in cases],
                "correlation": [c[2] for c in cases],
            }
        )
        from rwa_calc.engine.irb.formulas import _polars_capital_k_expr

        result = lf.with_columns(_polars_capital_k_expr().alias("k")).collect()
        for i, (pd, lgd, r) in enumerate(cases):
            k_scalar = calculate_k(pd, lgd, r)
            assert result["k"][i] == pytest.approx(k_scalar, rel=1e-8)


# =============================================================================
# MATURITY ADJUSTMENT TESTS
# =============================================================================


class TestMaturityAdjustment:
    """Tests for maturity adjustment factor."""

    def test_ma_at_1_year_equals_one(self) -> None:
        """MA = 1.0 at M=1.0 (the maturity floor).

        At M=1: MA = (1 + (1-2.5)×b) / (1-1.5×b) = (1-1.5b)/(1-1.5b) = 1.0.
        """
        ma = calculate_maturity_adjustment(0.01, 1.0)
        assert ma == pytest.approx(1.0, abs=1e-6)

    def test_ma_at_25_years_above_one(self) -> None:
        """MA > 1.0 at M=2.5 (the default maturity, not the neutral point)."""
        ma = calculate_maturity_adjustment(0.01, 2.5)
        assert ma > 1.0

    def test_ma_at_5_years_is_maximum(self) -> None:
        """MA at M=5 is the maximum value in the valid [1, 5] range."""
        ma = calculate_maturity_adjustment(0.01, 5.0)
        assert ma > 1.0

    def test_ma_increases_with_maturity(self) -> None:
        """MA increases monotonically with maturity."""
        ma_1 = calculate_maturity_adjustment(0.01, 1.0)
        ma_2 = calculate_maturity_adjustment(0.01, 2.0)
        ma_3 = calculate_maturity_adjustment(0.01, 3.0)
        ma_5 = calculate_maturity_adjustment(0.01, 5.0)
        assert ma_1 < ma_2 < ma_3 < ma_5

    def test_ma_below_floor_clipped(self) -> None:
        """Maturity below 1 year is clipped to 1 year."""
        ma_floor = calculate_maturity_adjustment(0.01, 1.0)
        ma_below = calculate_maturity_adjustment(0.01, 0.5)
        assert ma_below == pytest.approx(ma_floor, abs=1e-10)

    def test_ma_above_cap_clipped(self) -> None:
        """Maturity above 5 years is clipped to 5 years."""
        ma_cap = calculate_maturity_adjustment(0.01, 5.0)
        ma_above = calculate_maturity_adjustment(0.01, 10.0)
        assert ma_above == pytest.approx(ma_cap, abs=1e-10)

    def test_ma_low_pd_higher_sensitivity(self) -> None:
        """Low PD produces higher MA at M=5 than high PD (b coefficient larger)."""
        ma_low_pd = calculate_maturity_adjustment(0.001, 5.0)
        ma_high_pd = calculate_maturity_adjustment(0.10, 5.0)
        assert ma_low_pd > ma_high_pd

    def test_ma_always_positive(self) -> None:
        """MA > 0 for all valid inputs."""
        for pd in [0.001, 0.01, 0.05, 0.10, 0.50]:
            for m in [1.0, 2.5, 5.0]:
                ma = calculate_maturity_adjustment(pd, m)
                assert ma > 0

    def test_ma_formula_manual_verification(self) -> None:
        """Verify MA against manual formula: b = (0.11852 - 0.05478 × ln(PD))²."""
        pd, m = 0.01, 3.0
        b = (0.11852 - 0.05478 * math.log(pd)) ** 2
        ma_expected = (1.0 + (m - 2.5) * b) / (1.0 - 1.5 * b)
        ma_actual = calculate_maturity_adjustment(pd, m)
        assert ma_actual == pytest.approx(ma_expected, rel=1e-6)

    def test_ma_vectorized_matches_scalar(self) -> None:
        """Vectorized expression matches scalar wrapper."""
        cases = [(0.01, 2.0), (0.05, 3.0), (0.001, 5.0)]
        lf = pl.LazyFrame(
            {
                "pd_floored": [c[0] for c in cases],
                "maturity": [c[1] for c in cases],
            }
        )
        from rwa_calc.engine.irb.formulas import _polars_maturity_adjustment_expr

        result = lf.with_columns(_polars_maturity_adjustment_expr().alias("ma")).collect()
        for i, (pd, m) in enumerate(cases):
            ma_scalar = calculate_maturity_adjustment(pd, m)
            assert result["ma"][i] == pytest.approx(ma_scalar, rel=1e-8)


# =============================================================================
# DOUBLE DEFAULT TESTS
# =============================================================================


class TestDoubleDefault:
    """Tests for double default multiplier formula — CRR Art. 153(3)."""

    def test_dd_formula_basic(self) -> None:
        """K_dd = K_obligor × (0.15 + 160 × PD_g)."""
        k_dd = calculate_double_default_k(0.05, 0.01)
        expected = 0.05 * (0.15 + 160 * 0.01)
        assert k_dd == pytest.approx(expected, rel=1e-6)

    def test_dd_very_low_guarantor_pd(self) -> None:
        """Very low PD_g → multiplier ≈ 0.15."""
        k_dd = calculate_double_default_k(0.05, 0.0001)
        expected = 0.05 * (0.15 + 160 * 0.0001)
        assert k_dd == pytest.approx(expected, rel=1e-6)
        # Multiplier should be close to 0.15
        assert k_dd / 0.05 == pytest.approx(0.166, abs=0.01)

    def test_dd_zero_obligor_k(self) -> None:
        """Zero K_obligor → zero K_dd."""
        k_dd = calculate_double_default_k(0.0, 0.01)
        assert k_dd == pytest.approx(0.0, abs=1e-10)

    def test_dd_investment_grade_guarantor(self) -> None:
        """Investment-grade guarantor (PD=0.05%) → strong reduction."""
        k_obligor = 0.05
        k_dd = calculate_double_default_k(k_obligor, 0.0005)
        multiplier = k_dd / k_obligor
        assert multiplier < 0.25  # Much less than 1.0


# =============================================================================
# EXPECTED LOSS TESTS
# =============================================================================


class TestExpectedLoss:
    """Tests for EL = PD × LGD × EAD scalar calculation."""

    def test_el_basic(self) -> None:
        el = calculate_expected_loss(0.01, 0.45, 1_000_000.0)
        assert el == pytest.approx(4_500.0, rel=1e-6)

    def test_el_zero_pd(self) -> None:
        el = calculate_expected_loss(0.0, 0.45, 1_000_000.0)
        assert el == pytest.approx(0.0, abs=1e-10)

    def test_el_zero_lgd(self) -> None:
        el = calculate_expected_loss(0.01, 0.0, 1_000_000.0)
        assert el == pytest.approx(0.0, abs=1e-10)

    def test_el_zero_ead(self) -> None:
        el = calculate_expected_loss(0.01, 0.45, 0.0)
        assert el == pytest.approx(0.0, abs=1e-10)


# =============================================================================
# calculate_irb_rwa SCALAR ORCHESTRATOR TESTS
# =============================================================================


class TestCalculateIRBRWA:
    """Tests for the scalar calculate_irb_rwa() orchestrator."""

    def test_basic_corporate(self) -> None:
        """Standard corporate exposure produces reasonable RWA."""
        result = calculate_irb_rwa(
            ead=1_000_000.0,
            pd=0.01,
            lgd=0.45,
            correlation=0.20,
            maturity=2.5,
            apply_maturity_adjustment=True,
            apply_scaling_factor=True,
            pd_floor=0.0003,
            lgd_floor=None,
        )
        assert result["rwa"] > 0
        assert result["pd_floored"] == 0.01  # Above floor
        assert result["scaling_factor"] == 1.06

    def test_crr_scaling_factor(self) -> None:
        """CRR applies 1.06 scaling factor."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.01, lgd=0.45, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=True,
            pd_floor=0.0003, lgd_floor=None,
        )
        assert result["scaling_factor"] == 1.06

    def test_b31_no_scaling_factor(self) -> None:
        """Basel 3.1 uses scaling factor = 1.0."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.01, lgd=0.45, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=False,
            pd_floor=0.0005, lgd_floor=None,
        )
        assert result["scaling_factor"] == 1.0

    def test_pd_floor_applied(self) -> None:
        """PD below floor is raised to floor value."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.0001, lgd=0.45, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=True,
            pd_floor=0.0005, lgd_floor=None,
        )
        assert result["pd_floored"] == 0.0005

    def test_lgd_floor_applied(self) -> None:
        """LGD below floor is raised to floor value."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.01, lgd=0.10, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=True,
            pd_floor=0.0003, lgd_floor=0.25,
        )
        assert result["lgd_floored"] == 0.25

    def test_no_maturity_adjustment(self) -> None:
        """Without maturity adjustment, MA forced to 1.0."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.01, lgd=0.45, correlation=0.20, maturity=5.0,
            apply_maturity_adjustment=False, apply_scaling_factor=True,
            pd_floor=0.0003, lgd_floor=None,
        )
        assert result["maturity_adjustment"] == 1.0

    def test_risk_weight_formula(self) -> None:
        """risk_weight = K × 12.5 × scaling × MA."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.01, lgd=0.45, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=True,
            pd_floor=0.0003, lgd_floor=None,
        )
        expected_rw = result["k"] * 12.5 * result["scaling_factor"] * result["maturity_adjustment"]
        assert result["risk_weight"] == pytest.approx(expected_rw, rel=1e-6)

    def test_rwa_formula(self) -> None:
        """RWA = risk_weight × EAD."""
        result = calculate_irb_rwa(
            ead=1_000_000.0, pd=0.01, lgd=0.45, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=True,
            pd_floor=0.0003, lgd_floor=None,
        )
        assert result["rwa"] == pytest.approx(result["risk_weight"] * result["ead"], rel=1e-6)

    def test_zero_ead_gives_zero_rwa(self) -> None:
        """Zero EAD → zero RWA."""
        result = calculate_irb_rwa(
            ead=0.0, pd=0.01, lgd=0.45, correlation=0.20, maturity=2.5,
            apply_maturity_adjustment=True, apply_scaling_factor=True,
            pd_floor=0.0003, lgd_floor=None,
        )
        assert result["rwa"] == pytest.approx(0.0, abs=1e-10)


# =============================================================================
# F-IRB LGD PIPELINE TESTS (FSE vs non-FSE, CRR vs B31)
# =============================================================================


class TestFIRBLGDPipeline:
    """Tests for apply_firb_lgd() namespace method — FSE/non-FSE and CRR/B31 distinction."""

    def test_crr_firb_senior_unsecured_45pct(self) -> None:
        """CRR F-IRB: senior unsecured = 45% (Art. 161(1))."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
                "seniority": ["senior"],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.45, abs=1e-6)

    def test_crr_firb_subordinated_75pct(self) -> None:
        """CRR F-IRB: subordinated = 75% (Art. 161(1))."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
                "seniority": ["subordinated"],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.75, abs=1e-6)

    def test_b31_firb_non_fse_senior_40pct(self) -> None:
        """Basel 3.1 F-IRB: non-FSE senior unsecured = 40% (Art. 161(1)(aa))."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
                "seniority": ["senior"],
                "cp_is_financial_sector_entity": [False],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.40, abs=1e-6)

    def test_b31_firb_fse_senior_45pct(self) -> None:
        """Basel 3.1 F-IRB: FSE senior unsecured = 45% (Art. 161(1)(a))."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
                "seniority": ["senior"],
                "cp_is_financial_sector_entity": [True],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.45, abs=1e-6)

    def test_b31_firb_subordinated_75pct(self) -> None:
        """Basel 3.1 F-IRB: subordinated = 75% regardless of FSE."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
                "seniority": ["subordinated"],
                "cp_is_financial_sector_entity": [True],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.75, abs=1e-6)

    def test_airb_keeps_own_lgd(self) -> None:
        """A-IRB exposures retain their own LGD estimate, not supervisory."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.30],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.AIRB.value],
                "seniority": ["senior"],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.30, abs=1e-6)

    def test_firb_uses_lgd_post_crm_when_available(self) -> None:
        """F-IRB uses lgd_post_crm from CRM processor when available."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "lgd_post_crm": [0.20],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd_input"][0] == pytest.approx(0.20, abs=1e-6)

    def test_b31_missing_fse_column_defaults_to_non_fse(self) -> None:
        """Without cp_is_financial_sector_entity column, uses non-FSE LGD (40%)."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [None],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "approach": [ApproachType.FIRB.value],
                "seniority": ["senior"],
            }
        )
        result = lf.irb.apply_firb_lgd(config).collect()
        assert result["lgd"][0] == pytest.approx(0.40, abs=1e-6)


# =============================================================================
# FULL PIPELINE INTEGRATION TESTS
# =============================================================================


class TestApplyIRBFormulas:
    """Integration tests for apply_irb_formulas() — full pipeline."""

    def test_all_output_columns_present(self) -> None:
        """Pipeline produces all expected output columns."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
            }
        )
        result = apply_irb_formulas(lf, config).collect()
        expected_cols = {
            "pd_floored", "lgd_floored", "correlation", "k",
            "maturity_adjustment", "scaling_factor", "risk_weight",
            "rwa", "expected_loss",
        }
        assert expected_cols.issubset(set(result.columns))

    def test_crr_corporate_end_to_end(self) -> None:
        """CRR corporate: verify key intermediate values."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "maturity": [2.5],
            }
        )
        result = apply_irb_formulas(lf, config).collect()

        # PD floored at 0.03% (CRR) but 1% > 0.03%
        assert result["pd_floored"][0] == pytest.approx(0.01, abs=1e-8)
        # CRR: no LGD floors
        assert result["lgd_floored"][0] == pytest.approx(0.45, abs=1e-8)
        # Corporate correlation between 0.12 and 0.24
        assert 0.12 <= result["correlation"][0] <= 0.24
        # K positive
        assert result["k"][0] > 0
        # MA at M=2.5 → > 1.0 (MA=1 only at M=1.0 floor)
        assert result["maturity_adjustment"][0] > 1.0
        # CRR scaling
        assert result["scaling_factor"][0] == pytest.approx(1.06, abs=1e-8)
        # RWA positive
        assert result["rwa"][0] > 0
        # EL = PD × LGD × EAD = 0.01 × 0.45 × 1M = 4,500
        assert result["expected_loss"][0] == pytest.approx(4_500.0, rel=1e-4)

    def test_b31_vs_crr_scaling_difference(self) -> None:
        """Basel 3.1 RWA is ~6% lower than CRR due to no 1.06 scaling."""
        crr_config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        b31_config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))

        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "maturity": [2.5],
                "is_airb": [False],
            }
        )

        crr_result = apply_irb_formulas(lf, crr_config).collect()
        b31_result = apply_irb_formulas(lf, b31_config).collect()

        ratio = crr_result["rwa"][0] / b31_result["rwa"][0]
        assert ratio == pytest.approx(1.06, abs=0.01)

    def test_retail_no_maturity_adjustment(self) -> None:
        """Retail exposures get MA = 1.0 (no maturity adjustment)."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.30],
                "ead_final": [50_000.0],
                "exposure_class": ["retail_other"],
                "maturity": [5.0],  # Long maturity should not affect retail
            }
        )
        result = apply_irb_formulas(lf, config).collect()
        assert result["maturity_adjustment"][0] == pytest.approx(1.0, abs=1e-8)

    def test_missing_maturity_defaults_to_25(self) -> None:
        """Missing maturity column defaults to 2.5 years.

        At M=2.5, MA > 1.0 (MA=1 only at M=1.0 floor). The default maturity
        gives a specific non-trivial MA value that is consistent across runs.
        """
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf_default = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
            }
        )
        lf_explicit = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "maturity": [2.5],
            }
        )
        result_default = apply_irb_formulas(lf_default, config).collect()
        result_explicit = apply_irb_formulas(lf_explicit, config).collect()
        # Default maturity should produce same MA as explicit 2.5
        assert result_default["maturity_adjustment"][0] == pytest.approx(
            result_explicit["maturity_adjustment"][0], abs=1e-8
        )

    def test_missing_turnover_m_no_sme_adjustment(self) -> None:
        """Missing turnover_m column → no SME adjustment on correlation."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
            }
        )
        result = apply_irb_formulas(lf, config).collect()
        # Without SME adjustment, corporate correlation is standard PD-dependent
        expected_r = calculate_correlation(0.01, "corporate", turnover_m=None)
        assert result["correlation"][0] == pytest.approx(expected_r, abs=1e-6)

    def test_mixed_exposure_classes(self) -> None:
        """Multiple exposure classes in one batch get correct treatment."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01, 0.02, 0.005],
                "lgd": [0.45, 0.30, 0.10],
                "ead_final": [1_000_000.0, 50_000.0, 500_000.0],
                "exposure_class": ["corporate", "retail_other", "retail_mortgage"],
                "maturity": [2.5, 3.0, 5.0],
            }
        )
        result = apply_irb_formulas(lf, config).collect()

        # Row 0 (corporate M=2.5): MA > 1.0 (MA=1 only at M=1.0 floor)
        assert result["maturity_adjustment"][0] > 1.0
        # Row 1 (retail_other): MA = 1.0 (retail)
        assert result["maturity_adjustment"][1] == pytest.approx(1.0, abs=1e-8)
        # Row 2 (retail_mortgage): MA = 1.0 (retail)
        assert result["maturity_adjustment"][2] == pytest.approx(1.0, abs=1e-8)

        # Row 0 (corporate): correlation in [0.12, 0.24]
        assert 0.12 <= result["correlation"][0] <= 0.24
        # Row 1 (retail_other): correlation in [0.03, 0.16]
        assert 0.03 <= result["correlation"][1] <= 0.16
        # Row 2 (retail_mortgage): fixed 0.15
        assert result["correlation"][2] == pytest.approx(0.15, abs=1e-6)

        # All RWA positive
        assert all(r > 0 for r in result["rwa"].to_list())

    def test_row_count_preserved(self) -> None:
        """Pipeline preserves input row count."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "pd": [0.01] * 5,
                "lgd": [0.45] * 5,
                "ead_final": [1_000_000.0] * 5,
                "exposure_class": ["corporate"] * 5,
            }
        )
        result = apply_irb_formulas(lf, config).collect()
        assert result.height == 5

    def test_fi_scalar_in_pipeline(self) -> None:
        """Pipeline applies FI scalar when requires_fi_scalar=True."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))

        lf_no_fi = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "requires_fi_scalar": [False],
            }
        )
        lf_fi = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "requires_fi_scalar": [True],
            }
        )
        result_no = apply_irb_formulas(lf_no_fi, config).collect()
        result_fi = apply_irb_formulas(lf_fi, config).collect()

        # FI scalar → 1.25× correlation → higher K → higher RWA
        assert result_fi["correlation"][0] == pytest.approx(
            result_no["correlation"][0] * 1.25, abs=1e-6
        )
        assert result_fi["rwa"][0] > result_no["rwa"][0]


# =============================================================================
# CONFIG FACTORY TESTS (PDFloors, LGDFloors)
# =============================================================================


class TestPDFloorsConfig:
    """Tests for PDFloors dataclass factory methods and get_floor()."""

    def test_crr_all_003pct(self) -> None:
        from rwa_calc.contracts.config import PDFloors

        floors = PDFloors.crr()
        from decimal import Decimal

        assert floors.corporate == Decimal("0.0003")
        assert floors.retail_mortgage == Decimal("0.0003")
        assert floors.retail_qrre_transactor == Decimal("0.0003")
        assert floors.retail_qrre_revolver == Decimal("0.0003")

    def test_b31_differentiated(self) -> None:
        from decimal import Decimal

        from rwa_calc.contracts.config import PDFloors

        floors = PDFloors.basel_3_1()
        assert floors.corporate == Decimal("0.0005")
        assert floors.retail_mortgage == Decimal("0.0010")
        assert floors.retail_qrre_transactor == Decimal("0.0005")
        assert floors.retail_qrre_revolver == Decimal("0.0010")
        assert floors.retail_other == Decimal("0.0005")

    def test_get_floor_qrre_transactor_vs_revolver(self) -> None:
        from rwa_calc.contracts.config import PDFloors
        from rwa_calc.domain.enums import ExposureClass

        floors = PDFloors.basel_3_1()
        trans = floors.get_floor(ExposureClass.RETAIL_QRRE, is_qrre_transactor=True)
        rev = floors.get_floor(ExposureClass.RETAIL_QRRE, is_qrre_transactor=False)
        assert trans < rev  # Transactor floor (0.05%) < Revolver floor (0.10%)

    def test_get_floor_unknown_class_defaults_to_corporate(self) -> None:
        from rwa_calc.contracts.config import PDFloors
        from rwa_calc.domain.enums import ExposureClass

        floors = PDFloors.basel_3_1()
        # PSE doesn't have a specific floor → defaults to corporate
        floor = floors.get_floor(ExposureClass.PSE)
        assert floor == floors.corporate


class TestLGDFloorsConfig:
    """Tests for LGDFloors dataclass factory methods and get_floor()."""

    def test_crr_all_zero(self) -> None:
        from decimal import Decimal

        from rwa_calc.contracts.config import LGDFloors

        floors = LGDFloors.crr()
        assert floors.unsecured == Decimal("0.0")
        assert floors.financial_collateral == Decimal("0.0")
        assert floors.retail_rre == Decimal("0.0")

    def test_b31_corporate_floors(self) -> None:
        from decimal import Decimal

        from rwa_calc.contracts.config import LGDFloors

        floors = LGDFloors.basel_3_1()
        assert floors.unsecured == Decimal("0.25")
        assert floors.financial_collateral == Decimal("0.0")
        assert floors.receivables == Decimal("0.10")
        assert floors.commercial_real_estate == Decimal("0.10")
        assert floors.residential_real_estate == Decimal("0.10")
        assert floors.other_physical == Decimal("0.15")

    def test_b31_retail_floors(self) -> None:
        from decimal import Decimal

        from rwa_calc.contracts.config import LGDFloors

        floors = LGDFloors.basel_3_1()
        assert floors.retail_rre == Decimal("0.05")
        assert floors.retail_qrre_unsecured == Decimal("0.50")
        assert floors.retail_other_unsecured == Decimal("0.30")
        assert floors.retail_lgdu == Decimal("0.30")

    def test_get_floor_retail_mortgage_immovable(self) -> None:
        from rwa_calc.contracts.config import LGDFloors
        from rwa_calc.domain.enums import CollateralType

        floors = LGDFloors.basel_3_1()
        floor = floors.get_floor(CollateralType.IMMOVABLE, exposure_class="retail_mortgage")
        from decimal import Decimal

        assert floor == Decimal("0.05")  # Art. 164(4)(a)

    def test_get_floor_corporate_immovable(self) -> None:
        from rwa_calc.contracts.config import LGDFloors
        from rwa_calc.domain.enums import CollateralType

        floors = LGDFloors.basel_3_1()
        floor = floors.get_floor(CollateralType.IMMOVABLE, exposure_class="corporate")
        from decimal import Decimal

        assert floor == Decimal("0.10")  # Art. 161(5)

    def test_get_floor_qrre_unsecured(self) -> None:
        from rwa_calc.contracts.config import LGDFloors
        from rwa_calc.domain.enums import CollateralType

        floors = LGDFloors.basel_3_1()
        floor = floors.get_floor(CollateralType.OTHER, exposure_class="retail_qrre")
        from decimal import Decimal

        assert floor == Decimal("0.50")  # Art. 164(4)(b)(i)

    def test_get_floor_retail_other_unsecured(self) -> None:
        from rwa_calc.contracts.config import LGDFloors
        from rwa_calc.domain.enums import CollateralType

        floors = LGDFloors.basel_3_1()
        floor = floors.get_floor(CollateralType.OTHER, exposure_class="retail_other")
        from decimal import Decimal

        assert floor == Decimal("0.30")  # Art. 164(4)(b)(ii)
