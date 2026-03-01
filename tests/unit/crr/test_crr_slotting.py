"""
Unit tests for CRR Slotting Calculator.

Tests the supervisory slotting approach for specialised lending
as per CRR Art. 153(5).

CRR has TWO slotting tables with maturity-based splits:

Table 1 — Non-HVCRE (PF, OF, CF, IPRE):
    >=2.5yr: Strong=70%, Good=90%, Satisfactory=115%, Weak=250%, Default=0%
    <2.5yr:  Strong=50%, Good=70%, Satisfactory=115%, Weak=250%, Default=0%

Table 2 — HVCRE:
    >=2.5yr: Strong=95%, Good=120%, Satisfactory=140%, Weak=250%, Default=0%
    <2.5yr:  Strong=70%, Good=95%,  Satisfactory=140%, Weak=250%, Default=0%
"""

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SlottingResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import LazyFrameResult
from rwa_calc.engine.slotting import SlottingCalculator, create_slotting_calculator

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration for testing."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration for testing."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


@pytest.fixture
def slotting_calculator() -> SlottingCalculator:
    """Create a slotting calculator."""
    return SlottingCalculator()


def create_slotting_bundle(
    exposures_data: list[dict],
) -> CRMAdjustedBundle:
    """Helper to create a CRMAdjustedBundle with slotting exposures."""
    slotting_frame = pl.LazyFrame(exposures_data)
    return CRMAdjustedBundle(
        exposures=pl.LazyFrame(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=slotting_frame,
    )


# =============================================================================
# CRR SLOTTING RISK WEIGHT TESTS — Non-HVCRE, >=2.5yr (default)
# =============================================================================


class TestCRRSlottingRiskWeights:
    """Test CRR slotting risk weight lookup (non-HVCRE, >=2.5yr maturity)."""

    def test_strong_category_seventy_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Strong category gets 70% RW under CRR (>=2.5yr, non-HVCRE)."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.70)

    def test_good_category_ninety_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Good category gets 90% RW under CRR (>=2.5yr, non-HVCRE)."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="good",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.90)

    def test_satisfactory_category_115_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Satisfactory category gets 115% RW."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="satisfactory",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.15)

    def test_weak_category_250_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Weak category gets 250% RW (punitive weight)."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_default_category_zero_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Default category gets 0% RW (100% provisioned)."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            category="default",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00)


# =============================================================================
# CRR SHORT MATURITY TESTS — Non-HVCRE, <2.5yr
# =============================================================================


class TestCRRShortMaturityWeights:
    """Test CRR slotting risk weights for short maturity (<2.5yr)."""

    def test_strong_short_maturity_fifty_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Strong gets 50% RW for <2.5yr maturity (vs 70% for >=2.5yr)."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_short_maturity=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_good_short_maturity_seventy_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Good gets 70% RW for <2.5yr maturity (vs 90% for >=2.5yr)."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="good",
            is_hvcre=False,
            is_short_maturity=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.70)

    def test_satisfactory_short_maturity_same(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Satisfactory is 115% regardless of maturity."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="satisfactory",
            is_hvcre=False,
            is_short_maturity=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.15)

    def test_weak_short_maturity_same(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Weak is 250% regardless of maturity."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=False,
            is_short_maturity=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)


# =============================================================================
# CRR HVCRE WEIGHT TESTS — Art. 153(5) Table 2
# =============================================================================


class TestCRRHVCREWeights:
    """Test CRR HVCRE has higher weights than non-HVCRE per Table 2."""

    def test_hvcre_strong_ninety_five_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """HVCRE Strong = 95% (>=2.5yr), higher than non-HVCRE 70%."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="strong",
            is_hvcre=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.95)

    def test_hvcre_good_120_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """HVCRE Good = 120% (>=2.5yr), higher than non-HVCRE 90%."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="good",
            is_hvcre=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.20)

    def test_hvcre_satisfactory_140_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """HVCRE Satisfactory = 140% (>=2.5yr), higher than non-HVCRE 115%."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="satisfactory",
            is_hvcre=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.40)

    def test_hvcre_weak_same_as_non_hvcre(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """HVCRE Weak = 250%, same as non-HVCRE Weak."""
        hvcre_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=True,
            config=crr_config,
        )
        non_hvcre_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=False,
            config=crr_config,
        )
        assert hvcre_result["risk_weight"] == pytest.approx(2.50)
        assert hvcre_result["risk_weight"] == non_hvcre_result["risk_weight"]

    def test_hvcre_short_maturity_strong_seventy_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """HVCRE Strong <2.5yr = 70%."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="strong",
            is_hvcre=True,
            is_short_maturity=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.70)

    def test_hvcre_short_maturity_good_ninety_five_percent(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """HVCRE Good <2.5yr = 95%."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="good",
            is_hvcre=True,
            is_short_maturity=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.95)


# =============================================================================
# RWA CALCULATION TESTS
# =============================================================================


class TestSlottingRWACalculation:
    """Test slotting RWA calculations."""

    def test_rwa_equals_ead_times_rw(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """RWA = EAD x RW."""
        ead = Decimal("10000000")
        result = slotting_calculator.calculate_single_exposure(
            ead=ead,
            category="strong",
            is_hvcre=False,
            config=crr_config,
        )
        expected_rwa = float(ead) * 0.70
        assert result["rwa"] == pytest.approx(expected_rwa)

    def test_crr_e1_project_finance_strong(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """CRR-E1: Project Finance Strong - 10m at 70% = 7m RWA."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            sl_type="project_finance",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.70)
        assert result["rwa"] == pytest.approx(7_000_000)

    def test_crr_e2_project_finance_good(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """CRR-E2: Project Finance Good - 10m at 90% = 9m RWA."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="good",
            is_hvcre=False,
            sl_type="project_finance",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.90)
        assert result["rwa"] == pytest.approx(9_000_000)

    def test_crr_e3_ipre_weak(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """CRR-E3: IPRE Weak - 5m at 250% = 12.5m RWA."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=False,
            sl_type="income_producing_re",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)
        assert result["rwa"] == pytest.approx(12_500_000)

    def test_crr_e4_hvcre_strong(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """CRR-E4: HVCRE Strong - 5m at 95% = 4.75m RWA."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="strong",
            is_hvcre=True,
            sl_type="hvcre",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.95)
        assert result["rwa"] == pytest.approx(4_750_000)


# =============================================================================
# BUNDLE PROCESSING TESTS
# =============================================================================


class TestSlottingBundleProcessing:
    """Test slotting calculator bundle processing."""

    def test_calculate_returns_lazyframe_result(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Calculate method returns LazyFrameResult."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "strong",
                    "is_hvcre": False,
                    "ead": 10_000_000.0,
                },
            ]
        )
        result = slotting_calculator.calculate(bundle, crr_config)
        assert isinstance(result, LazyFrameResult)
        assert result.frame is not None

    def test_multiple_exposures_processed(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Multiple slotting exposures are processed correctly."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "strong",
                    "is_hvcre": False,
                    "ead": 10_000_000.0,
                },
                {
                    "exposure_reference": "SL002",
                    "slotting_category": "weak",
                    "is_hvcre": True,
                    "ead": 5_000_000.0,
                },
            ]
        )
        result = slotting_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()
        assert len(df) == 2

        # Check first exposure (non-HVCRE Strong = 70%)
        row1 = df.filter(pl.col("exposure_reference") == "SL001").to_dicts()[0]
        assert row1["risk_weight"] == pytest.approx(0.70)
        assert row1["rwa"] == pytest.approx(7_000_000)

        # Check second exposure (HVCRE Weak = 250%, same as non-HVCRE)
        row2 = df.filter(pl.col("exposure_reference") == "SL002").to_dicts()[0]
        assert row2["risk_weight"] == pytest.approx(2.50)
        assert row2["rwa"] == pytest.approx(12_500_000)

    def test_empty_slotting_exposures_returns_empty_result(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Empty slotting exposures returns empty result."""
        bundle = CRMAdjustedBundle(
            exposures=pl.LazyFrame(),
            sa_exposures=pl.LazyFrame(),
            irb_exposures=pl.LazyFrame(),
            slotting_exposures=None,
        )
        result = slotting_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()
        assert len(df) == 0

    def test_get_slotting_result_bundle_returns_bundle(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """get_slotting_result_bundle returns SlottingResultBundle."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "strong",
                    "is_hvcre": False,
                    "ead": 10_000_000.0,
                },
            ]
        )
        result = slotting_calculator.get_slotting_result_bundle(bundle, crr_config)
        assert isinstance(result, SlottingResultBundle)
        assert result.results is not None
        assert result.calculation_audit is not None


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================


class TestSlottingFactoryFunctions:
    """Test slotting calculator factory functions."""

    def test_create_slotting_calculator(self):
        """create_slotting_calculator returns SlottingCalculator instance."""
        calculator = create_slotting_calculator()
        assert isinstance(calculator, SlottingCalculator)


# =============================================================================
# CRR VS BASEL 3.1 TESTS
# =============================================================================


class TestCRRVsBasel31:
    """Test differences between CRR and Basel 3.1 slotting weights."""

    def test_crr_strong_vs_basel31_strong_non_hvcre(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
        basel31_config: CalculationConfig,
    ):
        """CRR Strong = 70%, Basel 3.1 Strong = 70% (non-HVCRE operational)."""
        crr_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            config=crr_config,
        )
        basel31_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            config=basel31_config,
        )
        assert crr_result["risk_weight"] == pytest.approx(0.70)
        assert basel31_result["risk_weight"] == pytest.approx(0.70)

    def test_crr_weak_vs_basel31_weak(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
        basel31_config: CalculationConfig,
    ):
        """CRR Weak = 250%, Basel 3.1 Weak = 250% (non-HVCRE operational)."""
        crr_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=False,
            config=crr_config,
        )
        basel31_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="weak",
            is_hvcre=False,
            config=basel31_config,
        )
        assert crr_result["risk_weight"] == pytest.approx(2.50)
        assert basel31_result["risk_weight"] == pytest.approx(2.50)

    def test_basel31_hvcre_higher_than_non_hvcre(
        self,
        slotting_calculator: SlottingCalculator,
        basel31_config: CalculationConfig,
    ):
        """Basel 3.1 has higher HVCRE weights than non-HVCRE."""
        hvcre_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="good",
            is_hvcre=True,
            config=basel31_config,
        )
        non_hvcre_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="good",
            is_hvcre=False,
            config=basel31_config,
        )
        # Basel 3.1 Good: non-HVCRE operational=90%, HVCRE=120%
        assert non_hvcre_result["risk_weight"] == pytest.approx(0.90)
        assert hvcre_result["risk_weight"] == pytest.approx(1.20)
        assert hvcre_result["risk_weight"] > non_hvcre_result["risk_weight"]

    def test_basel31_pf_pre_operational_higher(
        self,
        slotting_calculator: SlottingCalculator,
        basel31_config: CalculationConfig,
    ):
        """Basel 3.1 PF pre-operational Strong = 80% vs operational 70%."""
        pre_op_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_pre_operational=True,
            sl_type="project_finance",
            config=basel31_config,
        )
        operational_result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_pre_operational=False,
            sl_type="project_finance",
            config=basel31_config,
        )
        assert pre_op_result["risk_weight"] == pytest.approx(0.80)
        assert operational_result["risk_weight"] == pytest.approx(0.70)


# =============================================================================
# AUDIT TRAIL TESTS
# =============================================================================


class TestSlottingAuditTrail:
    """Test slotting calculation audit trail."""

    def test_audit_contains_calculation_details(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Audit trail contains calculation details."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "strong",
                    "is_hvcre": False,
                    "ead": 10_000_000.0,
                },
            ]
        )
        result_bundle = slotting_calculator.get_slotting_result_bundle(bundle, crr_config)
        audit_df = result_bundle.calculation_audit.collect()

        assert "slotting_calculation" in audit_df.columns
        calc_str = audit_df["slotting_calculation"][0]
        assert "Category=strong" in calc_str
        assert "RW=70" in calc_str  # 70% or 70.0%

    def test_audit_shows_hvcre_flag(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Audit trail shows HVCRE flag when applicable."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "strong",
                    "is_hvcre": True,
                    "ead": 5_000_000.0,
                },
            ]
        )
        result_bundle = slotting_calculator.get_slotting_result_bundle(bundle, crr_config)
        audit_df = result_bundle.calculation_audit.collect()

        calc_str = audit_df["slotting_calculation"][0]
        assert "(HVCRE)" in calc_str


# =============================================================================
# SPECIALISED LENDING TYPES TESTS
# =============================================================================


class TestSpecialisedLendingTypes:
    """Test handling of different specialised lending types."""

    @pytest.mark.parametrize(
        "sl_type,is_hvcre,expected_rw",
        [
            ("project_finance", False, 0.90),
            ("object_finance", False, 0.90),
            ("commodities_finance", False, 0.90),
            ("income_producing_re", False, 0.90),
            ("hvcre", True, 1.20),  # HVCRE Good = 120% per Table 2
        ],
    )
    def test_all_sl_types_processed(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
        sl_type: str,
        is_hvcre: bool,
        expected_rw: float,
    ):
        """All specialised lending types can be processed with correct weights."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            category="good",
            is_hvcre=is_hvcre,
            sl_type=sl_type,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw)
        expected_rwa = 5_000_000 * expected_rw
        assert result["rwa"] == pytest.approx(expected_rwa)


# =============================================================================
# EDGE CASES
# =============================================================================


class TestSlottingEdgeCases:
    """Test edge cases in slotting calculations."""

    def test_category_case_insensitive(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Slotting category matching is case-insensitive."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "STRONG",
                    "is_hvcre": False,
                    "ead": 10_000_000.0,
                },
            ]
        )
        result = slotting_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(0.70)

    def test_unknown_category_defaults_to_satisfactory(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Unknown slotting category defaults to satisfactory (115%)."""
        bundle = create_slotting_bundle(
            [
                {
                    "exposure_reference": "SL001",
                    "slotting_category": "unknown_category",
                    "is_hvcre": False,
                    "ead": 10_000_000.0,
                },
            ]
        )
        result = slotting_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(1.15)

    def test_zero_ead_produces_zero_rwa(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ):
        """Zero EAD produces zero RWA."""
        result = slotting_calculator.calculate_single_exposure(
            ead=Decimal("0"),
            category="strong",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["rwa"] == pytest.approx(0.0)
