"""Unit tests for the CRR Standardised Approach (SA) calculator.

Tests cover:
- SA risk weight lookups by exposure class and CQS
- UK institution deviation (30% for CQS2)
- Retail 75% risk weight
- Residential mortgage LTV treatment
- Commercial real estate LTV treatment
- SME supporting factor (tiered)
- Infrastructure supporting factor
- RWA calculation

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator, create_sa_calculator
from rwa_calc.engine.sa.supporting_factors import (
    SupportingFactorCalculator,
    create_supporting_factor_calculator,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA Calculator instance."""
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def supporting_factor_calculator() -> SupportingFactorCalculator:
    """Return a SupportingFactorCalculator instance."""
    return SupportingFactorCalculator()


# =============================================================================
# CQS-Based Risk Weight Tests
# =============================================================================


class TestSovereignRiskWeights:
    """Tests for sovereign exposure risk weights."""

    def test_cqs1_zero_risk_weight(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 1 sovereign (e.g., UK Govt) should get 0% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
            cqs=1,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.0"))
        assert result["rwa"] == pytest.approx(Decimal("0.0"))

    def test_cqs2_twenty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 2 sovereign should get 20% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
            cqs=2,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.20"))
        assert result["rwa"] == pytest.approx(Decimal("200000"))

    def test_unrated_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Unrated sovereign should get 100% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
            cqs=None,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("1.0"))
        assert result["rwa"] == pytest.approx(Decimal("1000000"))


class TestInstitutionRiskWeights:
    """Tests for institution exposure risk weights."""

    def test_cqs1_twenty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 1 institution should get 20% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=1,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.20"))
        assert result["rwa"] == pytest.approx(Decimal("200000"))

    def test_cqs2_uk_deviation_thirty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 2 institution with UK deviation should get 30% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            config=crr_config,
        )

        # UK deviation: 30% instead of Basel standard 50%
        assert result["risk_weight"] == pytest.approx(Decimal("0.30"))
        assert result["rwa"] == pytest.approx(Decimal("300000"))

    def test_unrated_forty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Unrated institution should get 40% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.40"))
        assert result["rwa"] == pytest.approx(Decimal("400000"))


class TestCorporateRiskWeights:
    """Tests for corporate exposure risk weights."""

    def test_cqs1_twenty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 1 corporate should get 20% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=1,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.20"))
        assert result["rwa"] == pytest.approx(Decimal("200000"))

    def test_cqs2_fifty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 2 corporate should get 50% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=2,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.50"))
        assert result["rwa"] == pytest.approx(Decimal("500000"))

    def test_unrated_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Unrated corporate should get 100% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("1.0"))
        assert result["rwa"] == pytest.approx(Decimal("1000000"))


# =============================================================================
# Retail Risk Weight Tests
# =============================================================================


class TestRetailRiskWeights:
    """Tests for retail exposure risk weights."""

    def test_retail_seventy_five_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Retail exposures should get 75% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("100000"),
            exposure_class="RETAIL",
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.75"))
        assert result["rwa"] == pytest.approx(Decimal("75000"))

    def test_retail_ignores_cqs(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Retail RW should not depend on CQS."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("100000"),
            exposure_class="RETAIL",
            cqs=1,  # Should be ignored
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.75"))


# =============================================================================
# Real Estate Tests
# =============================================================================


class TestResidentialMortgageRiskWeights:
    """Tests for residential mortgage LTV treatment."""

    def test_low_ltv_thirty_five_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """LTV <= 80% should get 35% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.60"),
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.35"))
        assert result["rwa"] == pytest.approx(Decimal("175000"))

    def test_at_threshold_thirty_five_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """LTV exactly at 80% should get 35% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.35"))

    def test_high_ltv_split_treatment(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """LTV > 80% should get split treatment."""
        # At 100% LTV: 80% at 35%, 20% at 75%
        # Weighted: (0.80 × 0.35) + (0.20 × 0.75) = 0.28 + 0.15 = 0.43
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.00"),
            config=crr_config,
        )

        expected_rw = 0.80 * 0.35 + 0.20 * 0.75
        assert float(result["risk_weight"]) == pytest.approx(expected_rw, rel=0.01)


class TestCommercialRERiskWeights:
    """Tests for commercial real estate LTV treatment."""

    def test_low_ltv_with_income_cover_fifty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRE LTV <= 50% with income cover should get 50% RW."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CRE001"],
            "ead_final": [600000.0],
            "exposure_class": ["COMMERCIAL_RE"],
            "cqs": [None],
            "ltv": [0.40],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [True],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.50)

    def test_low_ltv_without_income_cover_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRE LTV <= 50% without income cover should get 100% RW."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CRE001"],
            "ead_final": [600000.0],
            "exposure_class": ["COMMERCIAL_RE"],
            "cqs": [None],
            "ltv": [0.40],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(1.00)


# =============================================================================
# Supporting Factor Tests
# =============================================================================


class TestSMESupportingFactor:
    """Tests for SME supporting factor."""

    def test_tier1_only_small_exposure(
        self,
        supporting_factor_calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposure <= £2.2m should get full Tier 1 factor (0.7619)."""
        factor = supporting_factor_calculator.calculate_sme_factor(
            total_exposure=Decimal("1000000"),
            config=crr_config,
        )

        assert factor == pytest.approx(Decimal("0.7619"))

    def test_tier2_dominant_large_exposure(
        self,
        supporting_factor_calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Large exposure should approach Tier 2 factor (0.85)."""
        # £10m exposure: £2.2m at 0.7619, £7.8m at 0.85
        # Effective: (2.2m × 0.7619 + 7.8m × 0.85) / 10m = 0.8306
        factor = supporting_factor_calculator.calculate_sme_factor(
            total_exposure=Decimal("10000000"),
            config=crr_config,
        )

        # Should be between 0.7619 and 0.85
        assert Decimal("0.7619") < factor < Decimal("0.85")

    def test_sme_factor_applies_to_rwa(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SME factor should reduce RWA."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,  # 100% RW
            is_sme=True,
            config=crr_config,
        )

        # Without factor: RWA = 1m × 100% = 1m
        # With factor: RWA = 1m × 100% × 0.7619 = £761,900
        assert result["supporting_factor"] == pytest.approx(Decimal("0.7619"))
        assert result["rwa"] == pytest.approx(Decimal("761900"))
        assert result["supporting_factor_applied"] is True

    def test_sme_factor_disabled_in_basel31(
        self,
        sa_calculator: SACalculator,
        basel31_config: CalculationConfig,
    ) -> None:
        """SME factor should be 1.0 under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_sme=True,
            config=basel31_config,
        )

        assert result["supporting_factor"] == pytest.approx(Decimal("1.0"))
        assert result["supporting_factor_applied"] is False


class TestInfrastructureSupportingFactor:
    """Tests for infrastructure supporting factor."""

    def test_infrastructure_factor_seventy_five_percent(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Infrastructure factor should be 0.75."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_infrastructure=True,
            config=crr_config,
        )

        assert result["supporting_factor"] == pytest.approx(Decimal("0.75"))
        # RWA = 10m × 100% × 0.75 = £7.5m
        assert result["rwa"] == pytest.approx(Decimal("7500000"))

    def test_infrastructure_factor_disabled_in_basel31(
        self,
        sa_calculator: SACalculator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Infrastructure factor should be 1.0 under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_infrastructure=True,
            config=basel31_config,
        )

        assert result["supporting_factor"] == pytest.approx(Decimal("1.0"))


class TestSupportingFactorPriority:
    """Tests for supporting factor selection when both apply."""

    def test_lower_factor_wins(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """When both SME and infra apply, lower factor should win."""
        # SME factor for small exposure: 0.7619
        # Infrastructure factor: 0.75
        # Should use 0.75 (infrastructure is lower for large exposures)

        # Large exposure where SME factor > infra factor
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("100000000"),  # £100m - SME factor close to 0.85
            exposure_class="CORPORATE",
            cqs=None,
            is_sme=True,
            is_infrastructure=True,
            config=crr_config,
        )

        # At £100m, SME factor is close to 0.85, infra is 0.75
        # Should use 0.75
        assert result["supporting_factor"] == pytest.approx(Decimal("0.75"))


class TestSMESupportingFactorCounterpartyAggregation:
    """Tests for SME factor counterparty-level aggregation (CRR2 Art. 501).

    The EUR 2.5m threshold for the tiered SME factor is applied at the
    counterparty level, not per-exposure. All exposures to the same
    counterparty are aggregated before determining the blended factor.
    """

    def test_multiple_exposures_same_counterparty_aggregated(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple exposures to same counterparty should use aggregated EAD for factor."""
        # Two exposures of £1.5m each to same counterparty = £3m total
        # Threshold is ~£2.183m (EUR 2.5m * 0.8732)
        # Factor should be blended, not pure Tier 1 (0.7619)
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001", "EXP002"],
            "counterparty_reference": ["CP001", "CP001"],  # Same counterparty
            "ead_final": [1500000.0, 1500000.0],  # £1.5m each
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "cqs": [None, None],
            "is_sme": [True, True],
            "is_infrastructure": [False, False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        # Both exposures should have the same blended factor
        # Total = £3m, threshold = £2,183,000
        # tier1 = £2,183,000 * 0.7619 = £1,663,277.70
        # tier2 = £817,000 * 0.85 = £694,450.00
        # weighted_factor = (1,663,277.70 + 694,450) / 3,000,000 = ~0.7859
        exp1_factor = df.filter(pl.col("exposure_reference") == "EXP001")["supporting_factor"][0]
        exp2_factor = df.filter(pl.col("exposure_reference") == "EXP002")["supporting_factor"][0]

        # Both should have same factor (blended based on total counterparty exposure)
        assert exp1_factor == pytest.approx(exp2_factor, rel=0.001)

        # Factor should be between 0.7619 and 0.85 (blended)
        assert 0.7619 < exp1_factor < 0.85

    def test_different_counterparties_use_individual_totals(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposures to different counterparties should use their own totals."""
        # CP001: £1m (small, gets pure 0.7619)
        # CP002: £5m (larger, gets blended factor closer to 0.85)
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001", "EXP002"],
            "counterparty_reference": ["CP001", "CP002"],  # Different counterparties
            "ead_final": [1000000.0, 5000000.0],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "cqs": [None, None],
            "is_sme": [True, True],
            "is_infrastructure": [False, False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        exp1_factor = df.filter(pl.col("exposure_reference") == "EXP001")["supporting_factor"][0]
        exp2_factor = df.filter(pl.col("exposure_reference") == "EXP002")["supporting_factor"][0]

        # CP001 (£1m) should get pure Tier 1 factor
        assert exp1_factor == pytest.approx(0.7619, rel=0.001)

        # CP002 (£5m) should get blended factor (closer to 0.85)
        assert 0.7619 < exp2_factor < 0.85

    def test_null_counterparty_falls_back_to_individual_ead(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposures with null counterparty should use individual EAD."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001", "EXP002"],
            "counterparty_reference": [None, None],  # No counterparty reference
            "ead_final": [1000000.0, 5000000.0],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "cqs": [None, None],
            "is_sme": [True, True],
            "is_infrastructure": [False, False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        exp1_factor = df.filter(pl.col("exposure_reference") == "EXP001")["supporting_factor"][0]
        exp2_factor = df.filter(pl.col("exposure_reference") == "EXP002")["supporting_factor"][0]

        # Both should use individual EAD for factor calculation
        # EXP001 (£1m) - small, gets pure Tier 1
        assert exp1_factor == pytest.approx(0.7619, rel=0.001)

        # EXP002 (£5m) - gets blended factor
        assert 0.7619 < exp2_factor < 0.85


# =============================================================================
# Bundle Processing Tests
# =============================================================================


class TestSACalculatorBundleProcessing:
    """Tests for processing CRMAdjustedBundle."""

    def test_calculate_returns_lazyframe_result(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """calculate() should return LazyFrameResult."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "ead_final": [1000000.0],
            "exposure_class": ["CORPORATE"],
            "cqs": [None],
            "is_sme": [False],
            "is_infrastructure": [False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)

        assert hasattr(result, "frame")
        assert hasattr(result, "errors")

    def test_get_sa_result_bundle_returns_bundle(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """get_sa_result_bundle() should return SAResultBundle."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "ead_final": [1000000.0],
            "exposure_class": ["CORPORATE"],
            "cqs": [None],
            "is_sme": [False],
            "is_infrastructure": [False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.get_sa_result_bundle(bundle, crr_config)

        assert hasattr(result, "results")
        assert hasattr(result, "calculation_audit")
        assert hasattr(result, "errors")

    def test_multiple_exposures_processed(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple exposures should all be processed."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "ead_final": [1000000.0, 500000.0, 100000.0],
            "exposure_class": ["CENTRAL_GOVT_CENTRAL_BANK", "INSTITUTION", "RETAIL"],
            "cqs": [1, 2, None],
            "is_sme": [False, False, False],
            "is_infrastructure": [False, False, False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        assert len(df) == 3
        # Sovereign CQS1: 0%
        assert df.filter(pl.col("exposure_reference") == "EXP001")["risk_weight"][0] == pytest.approx(0.0)
        # Institution CQS2: 30% (UK deviation)
        assert df.filter(pl.col("exposure_reference") == "EXP002")["risk_weight"][0] == pytest.approx(0.30)
        # Retail: 75%
        assert df.filter(pl.col("exposure_reference") == "EXP003")["risk_weight"][0] == pytest.approx(0.75)


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestSAFactoryFunctions:
    """Tests for SA factory functions."""

    def test_create_sa_calculator(self) -> None:
        """Factory should create SACalculator."""
        calculator = create_sa_calculator()
        assert isinstance(calculator, SACalculator)

    def test_create_supporting_factor_calculator(self) -> None:
        """Factory should create SupportingFactorCalculator."""
        calculator = create_supporting_factor_calculator()
        assert isinstance(calculator, SupportingFactorCalculator)


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestSAAuditTrail:
    """Tests for SA calculation audit trail."""

    def test_audit_contains_calculation_details(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Audit should contain calculation breakdown."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "ead_final": [1000000.0],
            "exposure_class": ["CORPORATE"],
            "cqs": [2],
            "is_sme": [True],
            "is_infrastructure": [False],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.get_sa_result_bundle(bundle, crr_config)
        audit = result.calculation_audit

        if audit is not None:
            audit_df = audit.collect()
            assert "sa_calculation" in audit_df.columns
            calc_str = audit_df["sa_calculation"][0]
            assert "EAD=" in calc_str
            assert "RW=" in calc_str
            assert "SF=" in calc_str
            assert "RWA=" in calc_str
