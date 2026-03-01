"""Unit tests for the SA Polars namespace.

Tests cover:
- Namespace registration and availability
- Risk weight application (CQS-based, LTV-based)
- Residential mortgage risk weights
- Commercial RE risk weights
- Retail risk weights
- Guarantee substitution
- RWA calculation
- Supporting factor application
- Full pipeline (apply_all)
- Method chaining
- Expression namespace methods

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SAExpr, SALazyFrame  # noqa: F401 - imports register namespace

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crr_config_eur() -> CalculationConfig:
    """Return a CRR configuration with EUR (no UK deviation)."""
    from decimal import Decimal

    from rwa_calc.contracts.config import (
        IRBPermissions,
        LGDFloors,
        OutputFloorConfig,
        PDFloors,
        RegulatoryFramework,
        RetailThresholds,
        SupportingFactors,
    )

    return CalculationConfig(
        framework=RegulatoryFramework.CRR,
        reporting_date=date(2024, 12, 31),
        base_currency="EUR",
        pd_floors=PDFloors.crr(),
        lgd_floors=LGDFloors.crr(),
        supporting_factors=SupportingFactors.crr(),
        output_floor=OutputFloorConfig.crr(),
        retail_thresholds=RetailThresholds.crr(),
        irb_permissions=IRBPermissions.sa_only(),
        scaling_factor=Decimal("1.06"),
        eur_gbp_rate=Decimal("1.0"),
    )


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def basic_lazyframe() -> pl.LazyFrame:
    """Return a basic LazyFrame with SA columns."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "ead_final": [1_000_000.0, 500_000.0, 250_000.0],
            "exposure_class": ["CORPORATE", "CENTRAL_GOVT_CENTRAL_BANK", "INSTITUTION"],
            "cqs": [2, 1, 3],
        }
    )


@pytest.fixture
def mortgage_lazyframe() -> pl.LazyFrame:
    """Return a LazyFrame with residential mortgages."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["MORT001", "MORT002", "MORT003"],
            "ead_final": [500_000.0, 400_000.0, 300_000.0],
            "exposure_class": [
                "RESIDENTIAL_MORTGAGE",
                "RESIDENTIAL_MORTGAGE",
                "RESIDENTIAL_MORTGAGE",
            ],
            "ltv": [0.60, 0.80, 0.95],  # Below, at, above threshold
        }
    )


@pytest.fixture
def cre_lazyframe() -> pl.LazyFrame:
    """Return a LazyFrame with commercial real estate."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["CRE001", "CRE002", "CRE003"],
            "ead_final": [2_000_000.0, 1_500_000.0, 1_000_000.0],
            "exposure_class": ["COMMERCIAL_RE", "COMMERCIAL_RE", "COMMERCIAL_RE"],
            "ltv": [0.50, 0.70, 0.50],
            "has_income_cover": [True, True, False],
        }
    )


@pytest.fixture
def retail_lazyframe() -> pl.LazyFrame:
    """Return a LazyFrame with retail exposures."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["RET001", "RET002"],
            "ead_final": [50_000.0, 100_000.0],
            "exposure_class": ["RETAIL", "RETAIL"],
        }
    )


@pytest.fixture
def sme_lazyframe() -> pl.LazyFrame:
    """Return a LazyFrame with SME exposures."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SME001", "SME002"],
            "ead_final": [1_000_000.0, 500_000.0],
            "exposure_class": ["CORPORATE_SME", "CORPORATE_SME"],
            "is_sme": [True, True],
        }
    )


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestSANamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, basic_lazyframe: pl.LazyFrame) -> None:
        """LazyFrame should have .sa namespace available."""
        assert hasattr(basic_lazyframe, "sa")

    def test_expr_namespace_registered(self) -> None:
        """Expression should have .sa namespace available."""
        expr = pl.col("ltv")
        assert hasattr(expr, "sa")

    def test_namespace_methods_available(self, basic_lazyframe: pl.LazyFrame) -> None:
        """Namespace should have expected methods."""
        sa = basic_lazyframe.sa
        expected_methods = [
            "prepare_columns",
            "apply_risk_weights",
            "apply_residential_mortgage_rw",
            "apply_commercial_re_rw",
            "apply_cqs_based_rw",
            "apply_guarantee_substitution",
            "blend_guarantee_rw",
            "calculate_rwa",
            "apply_supporting_factors",
            "apply_all",
            "build_audit",
        ]
        for method in expected_methods:
            assert hasattr(sa, method), f"Missing method: {method}"


# =============================================================================
# Prepare Columns Tests
# =============================================================================


class TestPrepareColumns:
    """Tests for column preparation."""

    def test_adds_missing_columns(self, crr_config: CalculationConfig) -> None:
        """prepare_columns should add missing columns with defaults."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead": [100_000.0],
            }
        )
        result = lf.sa.prepare_columns(crr_config).collect()

        assert "ead_final" in result.columns
        assert "exposure_class" in result.columns
        assert "cqs" in result.columns
        assert "ltv" in result.columns
        assert "is_sme" in result.columns
        assert "is_infrastructure" in result.columns

    def test_preserves_existing_columns(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """prepare_columns should preserve existing columns."""
        result = basic_lazyframe.sa.prepare_columns(crr_config).collect()

        assert result["exposure_class"][0] == "CORPORATE"
        assert result["cqs"][0] == 2

    def test_ead_final_from_ead(self, crr_config: CalculationConfig) -> None:
        """ead_final should be populated from ead if available."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead": [100_000.0],
            }
        )
        result = lf.sa.prepare_columns(crr_config).collect()

        assert result["ead_final"][0] == pytest.approx(100_000.0)


# =============================================================================
# Risk Weight Application Tests
# =============================================================================


class TestApplyRiskWeights:
    """Tests for risk weight application."""

    def test_corporate_cqs2_risk_weight(self, crr_config: CalculationConfig) -> None:
        """Corporate CQS 2 should get 50% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["CORPORATE"],
                "cqs": [2],
            }
        )
        result = lf.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()

        assert result["risk_weight"][0] == pytest.approx(0.50)

    def test_sovereign_cqs1_risk_weight(self, crr_config: CalculationConfig) -> None:
        """Sovereign CQS 1 should get 0% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["CENTRAL_GOVT_CENTRAL_BANK"],
                "cqs": [1],
            }
        )
        result = lf.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()

        assert result["risk_weight"][0] == pytest.approx(0.0)

    def test_institution_cqs2_uk_deviation(self, crr_config: CalculationConfig) -> None:
        """Institution CQS 2 with UK deviation (GBP) should get 30% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["INSTITUTION"],
                "cqs": [2],
            }
        )
        result = lf.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()

        # GBP config uses UK deviation: CQS 2 institutions get 30%
        assert result["risk_weight"][0] == pytest.approx(0.30)

    def test_institution_cqs2_no_deviation(self, crr_config_eur: CalculationConfig) -> None:
        """Institution CQS 2 without UK deviation (EUR) should get 50% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["INSTITUTION"],
                "cqs": [2],
            }
        )
        result = (
            lf.sa.prepare_columns(crr_config_eur).sa.apply_risk_weights(crr_config_eur).collect()
        )

        assert result["risk_weight"][0] == pytest.approx(0.50)

    def test_unrated_corporate_100_percent(self, crr_config: CalculationConfig) -> None:
        """Unrated corporate should get 100% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["CORPORATE"],
                "cqs": [None],
            }
        )
        result = lf.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()

        assert result["risk_weight"][0] == pytest.approx(1.0)


# =============================================================================
# Residential Mortgage Tests
# =============================================================================


class TestResidentialMortgageRW:
    """Tests for residential mortgage risk weights."""

    def test_low_ltv_35_percent(
        self, mortgage_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """LTV <= 80% should get 35% risk weight."""
        result = (
            mortgage_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .collect()
        )

        # First exposure has LTV = 0.60
        assert result["risk_weight"][0] == pytest.approx(0.35)

    def test_at_threshold_35_percent(
        self, mortgage_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """LTV = 80% should get 35% risk weight."""
        result = (
            mortgage_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .collect()
        )

        # Second exposure has LTV = 0.80
        assert result["risk_weight"][1] == pytest.approx(0.35)

    def test_high_ltv_blended(
        self, mortgage_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """LTV > 80% should get blended risk weight."""
        result = (
            mortgage_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .collect()
        )

        # Third exposure has LTV = 0.95
        # Blended: 0.35 * (0.8/0.95) + 0.75 * (0.15/0.95)
        expected = 0.35 * (0.8 / 0.95) + 0.75 * ((0.95 - 0.8) / 0.95)
        assert result["risk_weight"][2] == pytest.approx(expected, rel=0.01)


# =============================================================================
# Commercial RE Tests
# =============================================================================


class TestCommercialRERW:
    """Tests for commercial real estate risk weights."""

    def test_low_ltv_with_income_cover(
        self, cre_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """CRE with LTV <= 60% and income cover should get 50% risk weight."""
        result = (
            cre_lazyframe.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()
        )

        # First exposure: LTV = 0.50, has_income_cover = True
        assert result["risk_weight"][0] == pytest.approx(0.50)

    def test_high_ltv_with_income_cover(
        self, cre_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """CRE with LTV > 60% should get 100% risk weight."""
        result = (
            cre_lazyframe.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()
        )

        # Second exposure: LTV = 0.70, has_income_cover = True
        assert result["risk_weight"][1] == pytest.approx(1.0)

    def test_low_ltv_no_income_cover(
        self, cre_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """CRE with low LTV but no income cover should get 100% risk weight."""
        result = (
            cre_lazyframe.sa.prepare_columns(crr_config).sa.apply_risk_weights(crr_config).collect()
        )

        # Third exposure: LTV = 0.50, has_income_cover = False
        assert result["risk_weight"][2] == pytest.approx(1.0)


# =============================================================================
# Retail Tests
# =============================================================================


class TestRetailRW:
    """Tests for retail risk weights."""

    def test_retail_75_percent(
        self, retail_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Retail exposures should get 75% risk weight."""
        result = (
            retail_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .collect()
        )

        for rw in result["risk_weight"]:
            assert rw == pytest.approx(0.75)


# =============================================================================
# RWA Calculation Tests
# =============================================================================


class TestCalculateRWA:
    """Tests for RWA calculation."""

    def test_rwa_formula(self, crr_config: CalculationConfig) -> None:
        """RWA = EAD x RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.50],
            }
        )
        result = lf.sa.calculate_rwa().collect()

        assert result["rwa_pre_factor"][0] == pytest.approx(500_000.0)

    def test_rwa_multiple_exposures(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """RWA calculation should work for multiple exposures."""
        result = (
            basic_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .sa.calculate_rwa()
            .collect()
        )

        # All RWAs should be >= 0 (sovereign CQS 1 could be 0)
        for rwa in result["rwa_pre_factor"]:
            assert rwa >= 0


# =============================================================================
# Supporting Factor Tests
# =============================================================================


class TestSupportingFactors:
    """Tests for supporting factor application."""

    def test_sme_factor_applied(
        self, sme_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """SME supporting factor should reduce RWA."""
        result = (
            sme_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(crr_config)
            .collect()
        )

        # Supporting factor should be < 1.0 for SME
        for sf in result["supporting_factor"]:
            assert sf < 1.0

        # RWA post factor should be less than pre factor
        for i in range(len(result)):
            assert result["rwa_post_factor"][i] < result["rwa_pre_factor"][i]


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestApplyAll:
    """Tests for full SA calculation pipeline."""

    def test_apply_all_adds_expected_columns(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """apply_all should add all expected columns."""
        result = basic_lazyframe.sa.apply_all(crr_config).collect()

        expected_columns = [
            "risk_weight",
            "rwa_pre_factor",
            "supporting_factor",
            "rwa_post_factor",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_apply_all_preserves_rows(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Number of rows should be preserved."""
        original_count = basic_lazyframe.collect().shape[0]
        result = basic_lazyframe.sa.apply_all(crr_config).collect()
        assert result.shape[0] == original_count


# =============================================================================
# Method Chaining Tests
# =============================================================================


class TestMethodChaining:
    """Tests for method chaining."""

    def test_full_pipeline_chain(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Full pipeline should work with method chaining."""
        result = (
            basic_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(crr_config)
            .collect()
        )

        assert "risk_weight" in result.columns
        assert "rwa_pre_factor" in result.columns
        assert "rwa_post_factor" in result.columns


# =============================================================================
# Expression Namespace Tests
# =============================================================================


class TestExprNamespace:
    """Tests for expression namespace methods."""

    def test_apply_ltv_weight_below_threshold(self) -> None:
        """apply_ltv_weight should return low weight for LTV below threshold."""
        df = pl.DataFrame({"ltv": [0.60, 0.80, 0.90]})
        result = df.with_columns(
            pl.col("ltv").sa.apply_ltv_weight([0.8], [0.35, 0.75]).alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.35)
        assert result["risk_weight"][1] == pytest.approx(0.35)
        assert result["risk_weight"][2] == pytest.approx(0.75)

    def test_lookup_cqs_rw_sovereign(self) -> None:
        """lookup_cqs_rw should return correct sovereign weights."""
        df = pl.DataFrame({"cqs": [1, 2, 3, 4, 5, 6]})
        result = df.with_columns(
            pl.col("cqs").sa.lookup_cqs_rw("CENTRAL_GOVT_CENTRAL_BANK").alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.0)  # CQS 1
        assert result["risk_weight"][1] == pytest.approx(0.20)  # CQS 2
        assert result["risk_weight"][2] == pytest.approx(0.50)  # CQS 3
        assert result["risk_weight"][3] == pytest.approx(1.0)  # CQS 4
        assert result["risk_weight"][4] == pytest.approx(1.0)  # CQS 5
        assert result["risk_weight"][5] == pytest.approx(1.50)  # CQS 6

    def test_lookup_cqs_rw_institution_uk(self) -> None:
        """lookup_cqs_rw should use UK deviation for institutions."""
        df = pl.DataFrame({"cqs": [2]})
        result = df.with_columns(
            pl.col("cqs")
            .sa.lookup_cqs_rw("INSTITUTION", use_uk_deviation=True)
            .alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.30)


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestBuildAudit:
    """Tests for audit trail generation."""

    def test_build_audit_includes_calculation_string(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """build_audit should include sa_calculation string."""
        result = basic_lazyframe.sa.apply_all(crr_config).sa.build_audit().collect()

        assert "sa_calculation" in result.columns
        calc_str = result["sa_calculation"][0]
        assert "EAD=" in calc_str
        assert "RW=" in calc_str
        assert "RWA=" in calc_str


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegrationWithCalculator:
    """Tests to ensure namespace produces compatible results."""

    def test_rwa_calculation_equivalent(
        self, basic_lazyframe: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Namespace RWA calculation should be equivalent to manual calculation."""
        result = (
            basic_lazyframe.sa.prepare_columns(crr_config)
            .sa.apply_risk_weights(crr_config)
            .sa.calculate_rwa()
            .collect()
        )

        # Verify RWA = EAD * RW for each row
        for i in range(len(result)):
            expected_rwa = result["ead_final"][i] * result["risk_weight"][i]
            assert result["rwa_pre_factor"][i] == pytest.approx(expected_rwa)
