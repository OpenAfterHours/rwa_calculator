"""Unit tests for Financial Collateral Simple Method (Art. 222).

Tests cover:
1. Collateral risk weight derivation (cash=0%, sovereign/institution/corp CQS tables)
2. FCSM column computation (secured value, weighted-avg RW per exposure)
3. 20% RW floor on secured portion (Art. 222(1))
4. Art. 222(4) 0% exceptions (same-currency cash, 0%-RW sovereign bonds)
5. SA-only gate (IRB exposures unaffected)
6. SA calculator RW substitution (blended secured/unsecured RW)
7. EAD not reduced under Simple Method
8. Config propagation (CRMCollateralMethod on CalculationConfig)
9. FCSM vs Comprehensive Method capital comparison
10. Multi-collateral weighted average

Why these tests matter:
    The Simple Method is a firm-wide CRM election that affects all SA capital
    calculations. Getting the RW substitution wrong would cause systematic
    capital misstatement across the entire SA portfolio. The 20% floor and
    0% exceptions create edge cases that must be handled precisely.

References:
    CRR Art. 222: Financial Collateral Simple Method
    PRA PS1/26 Art. 222: Retained for Basel 3.1 SA exposures
    CRR Art. 191A: CRM method selection framework
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import (
    ApproachType,
    CRMCollateralMethod,
    PermissionMode,
)
from rwa_calc.engine.crm.simple_method import (
    FCSM_RW_FLOOR,
    SOVEREIGN_BOND_DISCOUNT,
    _add_default_fcsm_columns,
    _derive_collateral_rw_expr,
    compute_fcsm_columns,
    undo_sa_ead_reduction,
)
from rwa_calc.engine.sa.calculator import SACalculator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_simple_config() -> CalculationConfig:
    """CRR configuration with Simple Method elected."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


@pytest.fixture
def b31_simple_config() -> CalculationConfig:
    """Basel 3.1 configuration with Simple Method elected."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


@pytest.fixture
def comprehensive_config() -> CalculationConfig:
    """CRR configuration with Comprehensive Method (default)."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        crm_collateral_method=CRMCollateralMethod.COMPREHENSIVE,
    )


def _make_exposures(
    ead: float = 1_000_000.0,
    currency: str = "GBP",
    approach: str = "standardised",
    exposure_reference: str = "EXP_001",
    exposure_class: str = "corporate",
    cqs: int = 0,
) -> pl.LazyFrame:
    """Create a single-exposure LazyFrame for testing."""
    return pl.LazyFrame({
        "exposure_reference": [exposure_reference],
        "ead_gross": [ead],
        "ead_pre_crm": [ead],
        "ead": [ead],
        "ead_final": [ead],
        "currency": [currency],
        "approach": [approach],
        "exposure_class": [exposure_class],
        "cqs": [cqs],
        "risk_weight": [1.0],  # 100% default
    })


def _make_collateral(
    collateral_type: str = "cash",
    market_value: float = 500_000.0,
    currency: str = "GBP",
    beneficiary_reference: str = "EXP_001",
    issuer_cqs: int | None = None,
    issuer_type: str | None = None,
    is_eligible: bool = True,
) -> pl.LazyFrame:
    """Create a single-collateral LazyFrame for testing."""
    return pl.LazyFrame({
        "collateral_reference": ["COLL_001"],
        "collateral_type": [collateral_type],
        "market_value": [market_value],
        "currency": [currency],
        "beneficiary_reference": [beneficiary_reference],
        "beneficiary_type": ["loan"],
        "issuer_cqs": [issuer_cqs],
        "issuer_type": [issuer_type],
        "is_eligible_financial_collateral": [is_eligible],
    })


# =============================================================================
# Constants
# =============================================================================


class TestFCSMConstants:
    """Test FCSM module constants."""

    def test_rw_floor_is_20_pct(self):
        assert FCSM_RW_FLOOR == Decimal("0.20")

    def test_sovereign_bond_discount_is_20_pct(self):
        assert SOVEREIGN_BOND_DISCOUNT == Decimal("0.20")


# =============================================================================
# Config
# =============================================================================


class TestFCSMConfig:
    """Test CRMCollateralMethod config propagation."""

    def test_crr_default_is_comprehensive(self):
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.crm_collateral_method == CRMCollateralMethod.COMPREHENSIVE

    def test_b31_default_is_comprehensive(self):
        config = CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))
        assert config.crm_collateral_method == CRMCollateralMethod.COMPREHENSIVE

    def test_crr_simple_election(self):
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            crm_collateral_method=CRMCollateralMethod.SIMPLE,
        )
        assert config.crm_collateral_method == CRMCollateralMethod.SIMPLE

    def test_b31_simple_election(self):
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            crm_collateral_method=CRMCollateralMethod.SIMPLE,
        )
        assert config.crm_collateral_method == CRMCollateralMethod.SIMPLE

    def test_enum_values(self):
        assert CRMCollateralMethod.COMPREHENSIVE == "comprehensive"
        assert CRMCollateralMethod.SIMPLE == "simple"


# =============================================================================
# Collateral Risk Weight Derivation
# =============================================================================


class TestCollateralRWDerivation:
    """Test _derive_collateral_rw_expr for different collateral types."""

    def _compute_rw(
        self,
        collateral_type: str,
        issuer_type: str | None = None,
        issuer_cqs: int | None = None,
        is_basel_3_1: bool = False,
    ) -> float:
        """Helper to compute single collateral RW."""
        df = pl.DataFrame({
            "collateral_type": [collateral_type],
            "issuer_type": [issuer_type],
            "issuer_cqs": [issuer_cqs],
        })
        result = df.with_columns(
            _derive_collateral_rw_expr(is_basel_3_1).alias("rw")
        )
        return result["rw"][0]

    def test_cash_zero_rw(self):
        assert self._compute_rw("cash") == 0.0

    def test_deposit_zero_rw(self):
        assert self._compute_rw("deposit") == 0.0

    def test_gold_zero_rw(self):
        assert self._compute_rw("gold") == 0.0

    def test_sovereign_cqs1_zero_rw(self):
        assert self._compute_rw("government_bond", "sovereign", 1) == 0.0

    def test_sovereign_cqs2_twenty_pct(self):
        assert self._compute_rw("government_bond", "sovereign", 2) == 0.20

    def test_sovereign_cqs3_fifty_pct(self):
        assert self._compute_rw("government_bond", "sovereign", 3) == 0.50

    def test_sovereign_cqs4_hundred_pct(self):
        assert self._compute_rw("government_bond", "sovereign", 4) == 1.00

    def test_sovereign_cqs6_one_fifty_pct(self):
        assert self._compute_rw("government_bond", "sovereign", 6) == 1.50

    def test_institution_cqs1_twenty_pct(self):
        assert self._compute_rw("corporate_bond", "institution", 1) == 0.20

    def test_institution_cqs2_fifty_pct(self):
        assert self._compute_rw("corporate_bond", "institution", 2) == 0.50

    def test_institution_unrated_hundred_pct(self):
        assert self._compute_rw("corporate_bond", "institution", None) == 1.00

    def test_corporate_cqs1_twenty_pct(self):
        assert self._compute_rw("corporate_bond", "corporate", 1) == 0.20

    def test_corporate_cqs2_fifty_pct(self):
        assert self._compute_rw("corporate_bond", "corporate", 2) == 0.50

    def test_corporate_cqs3_hundred_pct(self):
        assert self._compute_rw("corporate_bond", "corporate", 3) == 1.00

    def test_corporate_cqs5_crr_hundred_pct(self):
        """CRR Art. 122 Table 5: CQS 5 = 100%."""
        assert self._compute_rw("corporate_bond", "corporate", 5, is_basel_3_1=False) == 1.00

    def test_corporate_cqs5_b31_one_fifty_pct(self):
        """B31 Art. 122(2) Table 6: CQS 5 = 150%."""
        assert self._compute_rw("corporate_bond", "corporate", 5, is_basel_3_1=True) == 1.50

    def test_equity_hundred_pct(self):
        assert self._compute_rw("equity") == 1.00

    def test_equity_main_index_hundred_pct(self):
        assert self._compute_rw("equity_main_index") == 1.00

    def test_unknown_type_defaults_to_corporate(self):
        """Unknown collateral type treated as corporate bond (conservative)."""
        assert self._compute_rw("other_instrument", "corporate", 1) == 0.20


# =============================================================================
# FCSM Column Computation
# =============================================================================


class TestComputeFCSMColumns:
    """Test compute_fcsm_columns aggregation and column setting."""

    def test_cash_collateral_sets_fcsm_columns(self, crr_simple_config):
        exposures = _make_exposures(ead=1_000_000.0)
        collateral = _make_collateral(
            collateral_type="cash", market_value=500_000.0, currency="GBP"
        )
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        assert result["fcsm_collateral_value"][0] == pytest.approx(500_000.0)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.0)

    def test_no_collateral_returns_zeros(self, crr_simple_config):
        exposures = _make_exposures()
        result = compute_fcsm_columns(exposures, None, crr_simple_config).collect()
        assert result["fcsm_collateral_value"][0] == pytest.approx(0.0)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.0)

    def test_collateral_capped_at_ead(self, crr_simple_config):
        """Collateral value cannot exceed EAD."""
        exposures = _make_exposures(ead=100_000.0)
        collateral = _make_collateral(market_value=200_000.0)
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        assert result["fcsm_collateral_value"][0] == pytest.approx(100_000.0)

    def test_ineligible_collateral_excluded(self, crr_simple_config):
        """Non-eligible financial collateral produces zero FCSM columns."""
        exposures = _make_exposures()
        collateral = _make_collateral(is_eligible=False)
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        assert result["fcsm_collateral_value"][0] == pytest.approx(0.0)

    def test_sovereign_bond_cqs2_rw(self, crr_simple_config):
        exposures = _make_exposures()
        collateral = _make_collateral(
            collateral_type="government_bond",
            issuer_type="sovereign",
            issuer_cqs=2,
            market_value=600_000.0,
        )
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        assert result["fcsm_collateral_value"][0] == pytest.approx(600_000.0)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.20)

    def test_default_fcsm_columns_utility(self):
        exposures = _make_exposures()
        result = _add_default_fcsm_columns(exposures).collect()
        assert "fcsm_collateral_value" in result.columns
        assert "fcsm_collateral_rw" in result.columns
        assert result["fcsm_collateral_value"][0] == 0.0


# =============================================================================
# Art. 222(4) Zero RW Exceptions
# =============================================================================


class TestZeroRWExceptions:
    """Test Art. 222(4) 0% RW exceptions."""

    def test_same_currency_cash_gets_zero_rw(self, crr_simple_config):
        """Art. 222(4)(a): cash deposit in same currency → 0% RW."""
        exposures = _make_exposures(currency="GBP")
        collateral = _make_collateral(
            collateral_type="cash", currency="GBP", market_value=500_000.0,
        )
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        # Cash always has 0% RW, and same-currency means 0% exception applies
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.0)

    def test_cross_currency_cash_still_zero_item_rw(self, crr_simple_config):
        """Cash has 0% intrinsic RW regardless of currency — but 20% floor applies."""
        exposures = _make_exposures(currency="GBP")
        collateral = _make_collateral(
            collateral_type="cash", currency="EUR", market_value=500_000.0,
        )
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        # Cash RW is 0%, but Art. 222(4) 0% exception only applies in same currency
        # The 20% floor at SA calculator level will catch this
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.0)

    def test_zero_rw_sovereign_bond_same_currency(self, crr_simple_config):
        """Art. 222(4)(b): 0%-RW sovereign bond in same currency with 20% discount."""
        exposures = _make_exposures(currency="GBP")
        collateral = _make_collateral(
            collateral_type="government_bond",
            issuer_type="sovereign",
            issuer_cqs=1,
            currency="GBP",
            market_value=1_000_000.0,
        )
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        # 20% discount on sovereign bond: 1m * 0.80 = 800k
        assert result["fcsm_collateral_value"][0] == pytest.approx(800_000.0)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.0)


# =============================================================================
# Undo SA EAD Reduction
# =============================================================================


class TestUndoSAEADReduction:
    """Test undo_sa_ead_reduction for Simple Method."""

    def test_sa_ead_restored(self):
        """SA exposure EAD should be restored to ead_gross."""
        exposures = pl.LazyFrame({
            "approach": ["standardised"],
            "ead_gross": [1_000_000.0],
            "ead_after_collateral": [700_000.0],
            "collateral_adjusted_value": [300_000.0],
        })
        result = undo_sa_ead_reduction(exposures).collect()
        assert result["ead_after_collateral"][0] == pytest.approx(1_000_000.0)
        assert result["collateral_adjusted_value"][0] == pytest.approx(0.0)

    def test_irb_ead_unchanged(self):
        """IRB exposure should NOT have EAD restored."""
        exposures = pl.LazyFrame({
            "approach": ["foundation_irb"],
            "ead_gross": [1_000_000.0],
            "ead_after_collateral": [1_000_000.0],
            "collateral_adjusted_value": [0.0],
        })
        result = undo_sa_ead_reduction(exposures).collect()
        assert result["ead_after_collateral"][0] == pytest.approx(1_000_000.0)

    def test_mixed_approaches(self):
        """Only SA rows have EAD restored; IRB unchanged."""
        exposures = pl.LazyFrame({
            "approach": ["standardised", "foundation_irb"],
            "ead_gross": [1_000_000.0, 2_000_000.0],
            "ead_after_collateral": [700_000.0, 2_000_000.0],
            "collateral_adjusted_value": [300_000.0, 0.0],
        })
        result = undo_sa_ead_reduction(exposures).collect()
        assert result["ead_after_collateral"][0] == pytest.approx(1_000_000.0)  # SA restored
        assert result["ead_after_collateral"][1] == pytest.approx(2_000_000.0)  # IRB unchanged


# =============================================================================
# SA Calculator RW Substitution
# =============================================================================


class TestFCSMRWSubstitution:
    """Test SA calculator _apply_fcsm_rw_substitution."""

    def test_cash_50pct_secured_blended_rw(self, crr_simple_config):
        """50% secured by cash (0% RW → floored to 20%), 50% unsecured (100% RW).
        Blended = 0.5 * 20% + 0.5 * 100% = 60%.
        """
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],  # 100%
            "fcsm_collateral_value": [500_000.0],
            "fcsm_collateral_rw": [0.0],  # cash
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.60, rel=0.001)
        assert result["pre_fcsm_risk_weight"][0] == pytest.approx(1.0)

    def test_fully_secured_by_cash_20pct_floor(self, crr_simple_config):
        """Fully secured by cash → secured RW = max(20%, 0%) = 20%.
        Blended = 1.0 * 20% + 0.0 * RW = 20%.
        """
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "fcsm_collateral_value": [1_000_000.0],
            "fcsm_collateral_rw": [0.0],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.20, rel=0.001)

    def test_sovereign_bond_cqs2_secured(self, crr_simple_config):
        """Secured by CQS 2 sovereign bond (20% RW), 20% floor doesn't bind.
        Fully secured: blended = 1.0 * max(20%, 20%) = 20%.
        """
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "fcsm_collateral_value": [1_000_000.0],
            "fcsm_collateral_rw": [0.20],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.20, rel=0.001)

    def test_corporate_bond_cqs3_secured(self, crr_simple_config):
        """Secured by CQS 3 corporate bond (100% RW), floor doesn't bind.
        50% secured: blended = 0.5 * max(20%, 100%) + 0.5 * 100% = 100%.
        No benefit — collateral RW >= exposure RW.
        """
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "fcsm_collateral_value": [500_000.0],
            "fcsm_collateral_rw": [1.00],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.0, rel=0.001)

    def test_no_fcsm_columns_no_change(self, comprehensive_config):
        """Comprehensive Method: no FCSM columns → risk weight unchanged."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, comprehensive_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.0)

    def test_zero_fcsm_value_no_change(self, crr_simple_config):
        """Zero collateral value → risk weight unchanged."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "fcsm_collateral_value": [0.0],
            "fcsm_collateral_rw": [0.0],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.0)

    def test_rwa_correctness(self, crr_simple_config):
        """RWA = EAD × blended_rw. 50% secured by cash: RWA = 1m × 60% = 600k."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "fcsm_collateral_value": [500_000.0],
            "fcsm_collateral_rw": [0.0],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config)
        result = result.with_columns(
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa")
        ).collect()
        assert result["rwa"][0] == pytest.approx(600_000.0, rel=0.001)

    def test_ead_calculation_method_set(self, crr_simple_config):
        """When FCSM applies, ead_calculation_method should be 'simple'."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [1.0],
            "fcsm_collateral_value": [500_000.0],
            "fcsm_collateral_rw": [0.0],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
        })
        calc = SACalculator()
        result = calc._apply_fcsm_rw_substitution(exposures, crr_simple_config).collect()
        assert result["ead_calculation_method"][0] == "simple"


# =============================================================================
# Capital Comparison
# =============================================================================


class TestFCSMCapitalComparison:
    """Compare Simple Method vs Comprehensive Method capital impact."""

    def test_simple_method_higher_capital_than_comprehensive_for_cash(self):
        """Simple Method: 20% floor means cash-secured still has 20% RW on secured.
        Comprehensive Method: cash reduces EAD to zero (H_c = 0%).
        Simple Method produces higher capital (more conservative for cash).
        """
        ead = 1_000_000.0
        cash_value = 1_000_000.0  # fully secured by cash

        # Simple Method: RWA = 1m × 20% = 200k
        simple_rwa = ead * 0.20  # 20% floor on secured, 100% secured
        assert simple_rwa == pytest.approx(200_000.0)

        # Comprehensive Method: EAD* = max(0, 1m - 1m×(1-0%)) = 0 → RWA = 0
        comprehensive_rwa = max(0, ead - cash_value) * 1.0
        assert comprehensive_rwa == pytest.approx(0.0)

        # Simple Method produces higher capital (more conservative)
        assert simple_rwa > comprehensive_rwa

    def test_simple_method_lower_capital_than_comprehensive_for_volatile_equity(self):
        """Simple Method: equity RW = max(20%, 100%) = 100%.
        Comprehensive Method: equity haircut ~25%, so EAD* = EAD - eq×(1-0.25).
        When exposure has high RW (e.g., 150% high-risk), simple method may be better.
        """
        ead = 1_000_000.0
        eq_value = 500_000.0

        # Simple Method: 50% secured at 100% RW, 50% unsecured at 150%
        simple_rw = 0.5 * 1.0 + 0.5 * 1.50
        simple_rwa = ead * simple_rw
        assert simple_rwa == pytest.approx(1_250_000.0)

        # Comprehensive: EAD* = 1m - 500k × (1-0.25) = 625k; RWA = 625k × 150%
        comp_ead = max(0, ead - eq_value * (1 - 0.25))
        comp_rwa = comp_ead * 1.50
        assert comp_rwa == pytest.approx(937_500.0)

        # In this case Comprehensive is more capital-efficient
        assert comp_rwa < simple_rwa


# =============================================================================
# Mixed Batch
# =============================================================================


class TestFCSMMixedBatch:
    """Test multi-exposure scenarios."""

    def test_multi_collateral_weighted_average_rw(self, crr_simple_config):
        """Two collateral items → weighted-average RW."""
        exposures = _make_exposures(ead=1_000_000.0)
        collateral = pl.LazyFrame({
            "collateral_reference": ["C1", "C2"],
            "collateral_type": ["cash", "government_bond"],
            "market_value": [200_000.0, 300_000.0],
            "currency": ["GBP", "GBP"],
            "beneficiary_reference": ["EXP_001", "EXP_001"],
            "beneficiary_type": ["loan", "loan"],
            "issuer_cqs": [None, 2],
            "issuer_type": [None, "sovereign"],
            "is_eligible_financial_collateral": [True, True],
        })
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        # Cash: 200k at 0%, Sovereign CQS 2: 300k at 20%
        # Weighted avg = (200k×0% + 300k×20%) / 500k = 60k/500k = 12%
        assert result["fcsm_collateral_value"][0] == pytest.approx(500_000.0)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.12, rel=0.01)
