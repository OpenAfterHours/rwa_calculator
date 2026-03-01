"""
Unit tests for CRR Equity Calculator.

Tests equity exposure RWA calculation under two approaches:

Article 133 (Standardised Approach):
- Central bank: 0% RW
- Listed/Exchange-traded: 100% RW
- Government-supported: 100% RW
- Unlisted: 250% RW
- Speculative: 400% RW

Article 155 (IRB Simple Risk Weight):
- Private equity (diversified): 190% RW
- Exchange-traded: 290% RW
- Other equity: 370% RW

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
- EBA Q&A 2023_6716: Strategic equity treatment
"""

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle, EquityResultBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.contracts.errors import LazyFrameResult
from rwa_calc.data.tables.crr_equity_rw import (
    get_equity_rw_table,
    lookup_equity_rw,
)
from rwa_calc.engine.equity import EquityCalculator, create_equity_calculator

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_config() -> CalculationConfig:
    """SA-only configuration for testing Article 133."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture
def irb_config() -> CalculationConfig:
    """IRB configuration for testing Article 155."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    """Create an equity calculator."""
    return EquityCalculator()


def create_equity_bundle(
    exposures_data: list[dict],
) -> CRMAdjustedBundle:
    """Helper to create a CRMAdjustedBundle with equity exposures."""
    equity_frame = pl.LazyFrame(exposures_data)
    return CRMAdjustedBundle(
        exposures=pl.LazyFrame(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        equity_exposures=equity_frame,
    )


# =============================================================================
# ARTICLE 133 - SA RISK WEIGHT TESTS
# =============================================================================


class TestSAEquityRiskWeights:
    """Test Article 133 SA equity risk weights."""

    def test_central_bank_zero_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Central bank equity gets 0% RW under SA (Art. 133(6))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="central_bank",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00)
        assert result["approach"] == "sa"

    def test_listed_hundred_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Listed equity gets 100% RW under SA (Art. 133(1))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_exchange_traded_hundred_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Exchange-traded equity gets 100% RW under SA (Art. 133(1))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="exchange_traded",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_government_supported_hundred_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Government-supported equity gets 100% RW under SA (Art. 133(4)(c))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="government_supported",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_unlisted_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Unlisted equity gets 250% RW under SA (Art. 133(2))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_speculative_400_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Speculative unlisted equity gets 400% RW under SA (Art. 133(2))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="speculative",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00)

    def test_is_speculative_flag_overrides_type(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """is_speculative flag forces 400% RW even for unlisted type."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            is_speculative=True,
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00)

    def test_private_equity_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Private equity gets 250% RW under SA (same as unlisted)."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="private_equity",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_ciu_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU (collective investment undertaking) gets 250% RW under SA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)


# =============================================================================
# ARTICLE 155 - IRB SIMPLE RISK WEIGHT TESTS
# =============================================================================


class TestIRBSimpleEquityRiskWeights:
    """Test Article 155 IRB Simple equity risk weights."""

    def test_central_bank_zero_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Central bank equity gets 0% RW under IRB Simple."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="central_bank",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00)
        assert result["approach"] == "irb_simple"

    def test_private_equity_diversified_190_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Diversified private equity gets 190% RW under IRB Simple (Art. 155(2))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="private_equity",
            is_diversified=True,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90)

    def test_exchange_traded_290_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Exchange-traded equity gets 290% RW under IRB Simple (Art. 155(2))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="exchange_traded",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90)

    def test_listed_290_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Listed equity gets 290% RW under IRB Simple (same as exchange-traded)."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90)

    def test_other_equity_370_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Other equity gets 370% RW under IRB Simple (Art. 155(2))."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="other",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)

    def test_unlisted_370_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Unlisted equity gets 370% RW under IRB Simple."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)

    def test_speculative_370_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Speculative equity gets 370% RW under IRB Simple (same as other)."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="speculative",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)

    def test_government_supported_190_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Government-supported gets 190% RW under IRB Simple (treated as PE diversified)."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="government_supported",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90)

    def test_non_diversified_private_equity_370_percent(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Non-diversified private equity gets 370% RW under IRB Simple."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="private_equity",
            is_diversified=False,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)


# =============================================================================
# RWA CALCULATION TESTS
# =============================================================================


class TestEquityRWACalculation:
    """Test equity RWA calculations."""

    def test_rwa_equals_ead_times_rw(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """RWA = EAD × RW."""
        ead = Decimal("1000000")
        result = equity_calculator.calculate_single_exposure(
            ead=ead,
            equity_type="listed",
            config=sa_config,
        )
        expected_rwa = float(ead) * 1.00
        assert result["rwa"] == pytest.approx(expected_rwa)

    def test_sa_listed_1m_rwa(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """SA Listed: £1m at 100% = £1m RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(1_000_000)

    def test_sa_unlisted_1m_rwa(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """SA Unlisted: £1m at 250% = £2.5m RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)
        assert result["rwa"] == pytest.approx(2_500_000)

    def test_sa_speculative_1m_rwa(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """SA Speculative: £1m at 400% = £4m RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="speculative",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00)
        assert result["rwa"] == pytest.approx(4_000_000)

    def test_irb_pe_diversified_1m_rwa(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """IRB PE Diversified: £1m at 190% = £1.9m RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="private_equity",
            is_diversified=True,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90)
        assert result["rwa"] == pytest.approx(1_900_000)

    def test_irb_exchange_traded_1m_rwa(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """IRB Exchange-traded: £1m at 290% = £2.9m RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="exchange_traded",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90)
        assert result["rwa"] == pytest.approx(2_900_000)

    def test_irb_other_1m_rwa(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """IRB Other: £1m at 370% = £3.7m RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="other",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)
        assert result["rwa"] == pytest.approx(3_700_000)


# =============================================================================
# BUNDLE PROCESSING TESTS
# =============================================================================


class TestEquityBundleProcessing:
    """Test equity calculator bundle processing."""

    def test_calculate_returns_lazyframe_result(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Calculate method returns LazyFrameResult."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "listed",
                    "fair_value": 1_000_000.0,
                },
            ]
        )
        result = equity_calculator.calculate(bundle, sa_config)
        assert isinstance(result, LazyFrameResult)
        assert result.frame is not None

    def test_multiple_exposures_processed(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Multiple equity exposures are processed correctly."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "listed",
                    "fair_value": 1_000_000.0,
                },
                {
                    "exposure_reference": "EQ002",
                    "equity_type": "unlisted",
                    "fair_value": 500_000.0,
                },
            ]
        )
        result = equity_calculator.calculate(bundle, sa_config)
        df = result.frame.collect()
        assert len(df) == 2

        # Check first exposure
        row1 = df.filter(pl.col("exposure_reference") == "EQ001").to_dicts()[0]
        assert row1["risk_weight"] == pytest.approx(1.00)
        assert row1["rwa"] == pytest.approx(1_000_000)

        # Check second exposure
        row2 = df.filter(pl.col("exposure_reference") == "EQ002").to_dicts()[0]
        assert row2["risk_weight"] == pytest.approx(2.50)
        assert row2["rwa"] == pytest.approx(1_250_000)

    def test_empty_equity_exposures_returns_empty_result(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Empty equity exposures returns empty result."""
        bundle = CRMAdjustedBundle(
            exposures=pl.LazyFrame(),
            sa_exposures=pl.LazyFrame(),
            irb_exposures=pl.LazyFrame(),
            equity_exposures=None,
        )
        result = equity_calculator.calculate(bundle, sa_config)
        df = result.frame.collect()
        assert len(df) == 0

    def test_get_equity_result_bundle_returns_bundle(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """get_equity_result_bundle returns EquityResultBundle."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "listed",
                    "fair_value": 1_000_000.0,
                },
            ]
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        assert isinstance(result, EquityResultBundle)
        assert result.results is not None
        assert result.calculation_audit is not None
        assert result.approach == "sa"


# =============================================================================
# APPROACH DETERMINATION TESTS
# =============================================================================


class TestApproachDetermination:
    """Test approach determination based on config."""

    def test_sa_only_uses_article_133(
        self,
        equity_calculator: EquityCalculator,
    ):
        """SA_ONLY config uses Article 133 (SA approach)."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.sa_only(),
        )
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=config,
        )
        assert result["approach"] == "sa"
        assert result["article"] == "133"

    def test_firb_uses_article_155(
        self,
        equity_calculator: EquityCalculator,
    ):
        """FIRB config uses Article 155 (IRB Simple approach)."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.firb_only(),
        )
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=config,
        )
        assert result["approach"] == "irb_simple"
        assert result["article"] == "155"

    def test_airb_uses_article_155(
        self,
        equity_calculator: EquityCalculator,
    ):
        """AIRB config uses Article 155 (IRB Simple approach)."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.airb_only(),
        )
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=config,
        )
        assert result["approach"] == "irb_simple"

    def test_full_irb_uses_article_155(
        self,
        equity_calculator: EquityCalculator,
    ):
        """FULL_IRB config uses Article 155 (IRB Simple approach)."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.full_irb(),
        )
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=config,
        )
        assert result["approach"] == "irb_simple"


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================


class TestEquityFactoryFunctions:
    """Test equity calculator factory functions."""

    def test_create_equity_calculator(self):
        """create_equity_calculator returns EquityCalculator instance."""
        calculator = create_equity_calculator()
        assert isinstance(calculator, EquityCalculator)


# =============================================================================
# RISK WEIGHT TABLE TESTS
# =============================================================================


class TestEquityRiskWeightTables:
    """Test equity risk weight lookup tables."""

    def test_lookup_equity_rw_sa(self):
        """lookup_equity_rw returns correct SA risk weights."""
        assert lookup_equity_rw("central_bank", "sa") == Decimal("0.00")
        assert lookup_equity_rw("listed", "sa") == Decimal("1.00")
        assert lookup_equity_rw("unlisted", "sa") == Decimal("2.50")
        assert lookup_equity_rw("speculative", "sa") == Decimal("4.00")

    def test_lookup_equity_rw_irb_simple(self):
        """lookup_equity_rw returns correct IRB Simple risk weights."""
        assert lookup_equity_rw("central_bank", "irb_simple") == Decimal("0.00")
        assert lookup_equity_rw("exchange_traded", "irb_simple") == Decimal("2.90")
        assert lookup_equity_rw("other", "irb_simple") == Decimal("3.70")

    def test_lookup_equity_rw_diversified(self):
        """lookup_equity_rw handles is_diversified flag."""
        # Diversified private equity gets 190% under IRB Simple
        assert lookup_equity_rw("private_equity", "irb_simple", is_diversified=True) == Decimal(
            "1.90"
        )
        # Non-diversified private equity gets 370%
        assert lookup_equity_rw("private_equity", "irb_simple", is_diversified=False) == Decimal(
            "3.70"
        )

    def test_get_equity_rw_table_sa(self):
        """get_equity_rw_table returns correct SA DataFrame."""
        df = get_equity_rw_table("sa")
        assert df.height == 10  # All EquityType values
        listed_row = df.filter(pl.col("equity_type") == "listed").to_dicts()[0]
        assert listed_row["risk_weight"] == pytest.approx(1.00)

    def test_get_equity_rw_table_irb_simple(self):
        """get_equity_rw_table returns correct IRB Simple DataFrame."""
        df = get_equity_rw_table("irb_simple")
        assert df.height == 10  # All EquityType values
        other_row = df.filter(pl.col("equity_type") == "other").to_dicts()[0]
        assert other_row["risk_weight"] == pytest.approx(3.70)


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEquityEdgeCases:
    """Test edge cases in equity calculations."""

    def test_equity_type_case_insensitive(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Equity type matching is case-insensitive."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "LISTED",
                    "fair_value": 1_000_000.0,
                },
            ]
        )
        result = equity_calculator.calculate(bundle, sa_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_unknown_equity_type_defaults_to_other(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Unknown equity type defaults to 'other' (250% SA)."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "unknown_type",
                    "fair_value": 1_000_000.0,
                },
            ]
        )
        result = equity_calculator.calculate(bundle, sa_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(2.50)

    def test_zero_ead_produces_zero_rwa(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Zero EAD produces zero RWA."""
        result = equity_calculator.calculate_single_exposure(
            ead=Decimal("0"),
            equity_type="listed",
            config=sa_config,
        )
        assert result["rwa"] == pytest.approx(0.0)

    def test_uses_fair_value_for_ead(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Calculator uses fair_value column for EAD."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "listed",
                    "fair_value": 1_000_000.0,
                    "carrying_value": 900_000.0,
                },
            ]
        )
        result = equity_calculator.calculate(bundle, sa_config)
        df = result.frame.collect()
        # Should use fair_value (1m), not carrying_value (0.9m)
        assert df["ead_final"][0] == pytest.approx(1_000_000)
        assert df["rwa"][0] == pytest.approx(1_000_000)

    def test_uses_carrying_value_when_fair_value_missing(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Calculator falls back to carrying_value when fair_value is missing."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "listed",
                    "carrying_value": 900_000.0,
                },
            ]
        )
        result = equity_calculator.calculate(bundle, sa_config)
        df = result.frame.collect()
        assert df["ead_final"][0] == pytest.approx(900_000)


# =============================================================================
# AUDIT TRAIL TESTS
# =============================================================================


class TestEquityAuditTrail:
    """Test equity calculation audit trail."""

    def test_audit_contains_calculation_details(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Audit trail contains calculation details."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "listed",
                    "fair_value": 1_000_000.0,
                },
            ]
        )
        result_bundle = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        audit_df = result_bundle.calculation_audit.collect()

        assert "equity_calculation" in audit_df.columns
        calc_str = audit_df["equity_calculation"][0]
        assert "Type=listed" in calc_str
        assert "RW=100" in calc_str
        assert "Art. 133" in calc_str

    def test_audit_shows_irb_approach(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
    ):
        """Audit trail shows IRB Simple approach when applicable."""
        bundle = create_equity_bundle(
            [
                {
                    "exposure_reference": "EQ001",
                    "equity_type": "exchange_traded",
                    "fair_value": 1_000_000.0,
                },
            ]
        )
        result_bundle = equity_calculator.get_equity_result_bundle(bundle, irb_config)
        audit_df = result_bundle.calculation_audit.collect()

        calc_str = audit_df["equity_calculation"][0]
        assert "Art. 155 IRB Simple" in calc_str


# =============================================================================
# COMPARISON: SA VS IRB SIMPLE
# =============================================================================


class TestSAVsIRBSimple:
    """Test comparison between SA and IRB Simple approaches."""

    def test_listed_sa_lower_than_irb(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
        irb_config: CalculationConfig,
    ):
        """Listed equity: SA (100%) is lower than IRB Simple (290%)."""
        sa_result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=sa_config,
        )
        irb_result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="listed",
            config=irb_config,
        )
        assert sa_result["risk_weight"] == pytest.approx(1.00)
        assert irb_result["risk_weight"] == pytest.approx(2.90)
        assert sa_result["risk_weight"] < irb_result["risk_weight"]

    def test_unlisted_sa_lower_than_irb(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
        irb_config: CalculationConfig,
    ):
        """Unlisted equity: SA (250%) is lower than IRB Simple (370%)."""
        sa_result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=sa_config,
        )
        irb_result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=irb_config,
        )
        assert sa_result["risk_weight"] == pytest.approx(2.50)
        assert irb_result["risk_weight"] == pytest.approx(3.70)
        assert sa_result["risk_weight"] < irb_result["risk_weight"]

    def test_speculative_sa_higher_than_irb(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
        irb_config: CalculationConfig,
    ):
        """Speculative equity: SA (400%) is higher than IRB Simple (370%)."""
        sa_result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="speculative",
            config=sa_config,
        )
        irb_result = equity_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="speculative",
            config=irb_config,
        )
        assert sa_result["risk_weight"] == pytest.approx(4.00)
        assert irb_result["risk_weight"] == pytest.approx(3.70)
        assert sa_result["risk_weight"] > irb_result["risk_weight"]
