"""
Tests for Art. 227 zero-haircut conditions for repo-style transactions.

Validates:
1. Zero haircut for cash in qualifying repos (Art. 227)
2. Zero haircut for CQS 1 sovereign bonds in qualifying repos
3. Standard haircut applied when qualifies_for_zero_haircut=False
4. Standard haircut applied for ineligible types (corporate bonds, equity)
5. FX haircut zeroed for Art. 227 qualifying collateral
6. CQS 2+ sovereign bonds do NOT qualify for zero haircut
7. Single-item calculator Art. 227 path
8. Pipeline (LazyFrame) Art. 227 path
9. Backward compatibility (absent qualifies_for_zero_haircut column)
10. CRR and Basel 3.1 both support Art. 227

Why these tests matter:
    Art. 227 zero-haircut treatment is critical for repo books.  Large
    institutions routinely hold billions in repo positions backed by
    sovereign bonds.  Applying standard haircuts (0.5-4%) to these
    positions materially overstates capital requirements.  The 8 conditions
    (daily margining, core market participant, standard documentation, etc.)
    are institution-certified, but the calculator must validate collateral
    type eligibility (condition (a)) and apply zero haircuts correctly.

References:
    CRR Art. 227: Zero volatility adjustments for qualifying repos/SFTs
    CRR Art. 227(2)(a): Eligible collateral = cash or 0%-RW sovereign bonds
    CRR Art. 227(3): Core market participant definition
    PRA PS1/26 Art. 227: Unchanged from CRR
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.engine.crm.constants import (
    ZERO_HAIRCUT_ELIGIBLE_TYPES,
    ZERO_HAIRCUT_MAX_SOVEREIGN_CQS,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator, HaircutResult


# =============================================================================
# Constants
# =============================================================================


class TestArt227Constants:
    """Verify Art. 227 constants are correct."""

    def test_eligible_types_include_cash(self) -> None:
        """Cash/deposit must be eligible for zero haircut."""
        assert "cash" in ZERO_HAIRCUT_ELIGIBLE_TYPES
        assert "deposit" in ZERO_HAIRCUT_ELIGIBLE_TYPES

    def test_eligible_types_include_sovereign_bonds(self) -> None:
        """Sovereign bond variants must be eligible for zero haircut."""
        assert "govt_bond" in ZERO_HAIRCUT_ELIGIBLE_TYPES
        assert "sovereign_bond" in ZERO_HAIRCUT_ELIGIBLE_TYPES
        assert "government_bond" in ZERO_HAIRCUT_ELIGIBLE_TYPES

    def test_eligible_types_exclude_corporate(self) -> None:
        """Corporate bonds and equity must NOT be in zero-haircut eligible types."""
        assert "corporate_bond" not in ZERO_HAIRCUT_ELIGIBLE_TYPES
        assert "corp_bond" not in ZERO_HAIRCUT_ELIGIBLE_TYPES
        assert "equity" not in ZERO_HAIRCUT_ELIGIBLE_TYPES

    def test_max_sovereign_cqs_is_1(self) -> None:
        """Only CQS 1 sovereign bonds (0% RW) qualify for zero haircut."""
        assert ZERO_HAIRCUT_MAX_SOVEREIGN_CQS == 1


# =============================================================================
# Single-item calculator (calculate_single_haircut)
# =============================================================================


class TestSingleItemArt227:
    """Art. 227 zero-haircut via calculate_single_haircut."""

    @pytest.fixture
    def crr_calc(self) -> HaircutCalculator:
        return HaircutCalculator(is_basel_3_1=False)

    @pytest.fixture
    def b31_calc(self) -> HaircutCalculator:
        return HaircutCalculator(is_basel_3_1=True)

    def test_cash_zero_haircut(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227: cash in qualifying repo gets 0% haircut + 0% FX."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")
        assert result.fx_haircut == Decimal("0.0")
        assert result.adjusted_value == Decimal("1000000")
        assert "Art.227" in result.description

    def test_deposit_zero_haircut(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227: deposit in qualifying repo gets 0% haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="deposit",
            market_value=Decimal("500000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")
        assert result.adjusted_value == Decimal("500000")

    def test_sovereign_bond_cqs1_zero_haircut(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227: CQS 1 sovereign bond in qualifying repo gets 0% haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=5.0,
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")
        assert result.fx_haircut == Decimal("0.0")
        assert result.adjusted_value == Decimal("1000000")
        assert "Art.227" in result.description

    def test_sovereign_bond_cqs1_standard_without_flag(
        self, crr_calc: HaircutCalculator
    ) -> None:
        """Without Art. 227 flag, CQS 1 sovereign bond gets standard haircut (>0%)."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=5.0,
            qualifies_for_zero_haircut=False,
        )
        assert result.collateral_haircut > Decimal("0.0")
        assert result.adjusted_value < Decimal("1000000")

    def test_sovereign_bond_cqs2_not_eligible(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227(2)(a): CQS 2 sovereign bonds are NOT 0%-RW → standard haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=2,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=True,
        )
        # CQS 2 falls through to standard haircut lookup
        assert result.collateral_haircut > Decimal("0.0")
        assert "Art.227" not in result.description

    def test_sovereign_bond_null_cqs_not_eligible(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227: null CQS sovereign bond is not eligible (unrated ≠ CQS 1)."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=None,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=True,
        )
        # Null CQS → falls through to standard (ineligible per Art. 197)
        assert result.collateral_haircut > Decimal("0.0")

    def test_corporate_bond_not_eligible(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227(2)(a): corporate bonds never qualify for zero haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="corp_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut > Decimal("0.0")

    def test_equity_not_eligible(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227(2)(a): equity never qualifies for zero haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut > Decimal("0.0")

    def test_cash_cross_currency_still_zero(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227 waives ALL volatility adjustments — FX haircut is 0% too.

        Art. 227(2)(b) requires same currency as a precondition, so the institution
        should not certify qualifies_for_zero_haircut=True with mismatched currencies.
        But if they do, we trust the flag and set all haircuts to zero.
        """
        result = crr_calc.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("1000000"),
            collateral_currency="EUR",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")
        assert result.fx_haircut == Decimal("0.0")
        assert result.adjusted_value == Decimal("1000000")

    def test_b31_sovereign_bond_cqs1_zero_haircut(
        self, b31_calc: HaircutCalculator
    ) -> None:
        """Art. 227 applies identically under Basel 3.1."""
        result = b31_calc.calculate_single_haircut(
            collateral_type="government_bond",
            market_value=Decimal("2000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=10.0,
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")
        assert result.adjusted_value == Decimal("2000000")

    def test_b31_sovereign_bond_cqs1_without_flag_gets_standard(
        self, b31_calc: HaircutCalculator
    ) -> None:
        """B31 CQS 1 sovereign 10yr bond without flag gets standard haircut (>0%)."""
        result = b31_calc.calculate_single_haircut(
            collateral_type="government_bond",
            market_value=Decimal("2000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=10.0,
            qualifies_for_zero_haircut=False,
        )
        assert result.collateral_haircut > Decimal("0.0")
        assert result.adjusted_value < Decimal("2000000")

    def test_default_flag_is_false(self, crr_calc: HaircutCalculator) -> None:
        """Default qualifies_for_zero_haircut=False preserves existing behavior."""
        result_default = crr_calc.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=3.0,
        )
        result_explicit = crr_calc.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=False,
        )
        assert result_default.collateral_haircut == result_explicit.collateral_haircut
        assert result_default.adjusted_value == result_explicit.adjusted_value


# =============================================================================
# Pipeline (LazyFrame) haircut application
# =============================================================================


def _make_collateral(
    collateral_type: str = "cash",
    market_value: float = 1_000_000.0,
    currency: str = "GBP",
    exposure_currency: str = "GBP",
    issuer_cqs: int | None = None,
    residual_maturity_years: float | None = None,
    qualifies_for_zero_haircut: bool | None = None,
    is_eligible_financial_collateral: bool = True,
    liquidation_period_days: int | None = None,
) -> pl.LazyFrame:
    """Create a single collateral LazyFrame for pipeline tests.

    All columns required by HaircutCalculator.apply_haircuts are included
    with sensible defaults to avoid ColumnNotFoundError.
    """
    data: dict[str, list] = {
        "collateral_reference": ["COLL_001"],
        "collateral_type": [collateral_type],
        "market_value": [market_value],
        "currency": [currency],
        "exposure_currency": [exposure_currency],
        "is_eligible_financial_collateral": [is_eligible_financial_collateral],
        "issuer_cqs": [issuer_cqs],
        "residual_maturity_years": [residual_maturity_years],
    }
    if qualifies_for_zero_haircut is not None:
        data["qualifies_for_zero_haircut"] = [qualifies_for_zero_haircut]
    if liquidation_period_days is not None:
        data["liquidation_period_days"] = [liquidation_period_days]
    return pl.LazyFrame(data)


class TestPipelineArt227:
    """Art. 227 zero-haircut via HaircutCalculator.apply_haircuts pipeline."""

    @pytest.fixture
    def crr_config(self):
        from rwa_calc.contracts.config import CalculationConfig

        return CalculationConfig.crr(reporting_date=date(2024, 12, 31))

    @pytest.fixture
    def b31_config(self):
        from rwa_calc.contracts.config import CalculationConfig

        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    def test_cash_zero_haircut_pipeline(self, crr_config) -> None:
        """Pipeline: cash with qualifies_for_zero_haircut=True → 0% Hc + 0% Hfx."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="cash",
            market_value=1_000_000.0,
            qualifies_for_zero_haircut=True,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["collateral_haircut"][0] == pytest.approx(0.0)
        assert result["fx_haircut"][0] == pytest.approx(0.0)
        assert result["value_after_haircut"][0] == pytest.approx(1_000_000.0)

    def test_sovereign_cqs1_zero_haircut_pipeline(self, crr_config) -> None:
        """Pipeline: CQS 1 sovereign bond with Art. 227 flag → 0% haircut."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="govt_bond",
            market_value=500_000.0,
            issuer_cqs=1,
            residual_maturity_years=5.0,
            qualifies_for_zero_haircut=True,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["collateral_haircut"][0] == pytest.approx(0.0)
        assert result["fx_haircut"][0] == pytest.approx(0.0)
        assert result["value_after_haircut"][0] == pytest.approx(500_000.0)

    def test_sovereign_cqs1_standard_haircut_without_flag(self, crr_config) -> None:
        """Pipeline: CQS 1 sovereign bond WITHOUT flag → standard haircut (>0%)."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="govt_bond",
            market_value=500_000.0,
            issuer_cqs=1,
            residual_maturity_years=5.0,
            qualifies_for_zero_haircut=False,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["collateral_haircut"][0] > 0.0
        assert result["value_after_haircut"][0] < 500_000.0

    def test_sovereign_cqs2_not_eligible_pipeline(self, crr_config) -> None:
        """Pipeline: CQS 2 sovereign bond with flag → standard haircut (not CQS 1)."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="govt_bond",
            market_value=500_000.0,
            issuer_cqs=2,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=True,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["collateral_haircut"][0] > 0.0

    def test_corporate_bond_not_eligible_pipeline(self, crr_config) -> None:
        """Pipeline: corporate bond with flag → standard haircut (not eligible type)."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="corp_bond",
            market_value=500_000.0,
            issuer_cqs=1,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=True,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["collateral_haircut"][0] > 0.0

    def test_fx_haircut_zeroed_for_art227_cross_currency(self, crr_config) -> None:
        """Pipeline: Art. 227 zero-haircut waives FX haircut even with currency mismatch."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="cash",
            market_value=1_000_000.0,
            currency="EUR",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["fx_haircut"][0] == pytest.approx(0.0)
        assert result["value_after_haircut"][0] == pytest.approx(1_000_000.0)

    def test_fx_haircut_applied_without_flag_cross_currency(self, crr_config) -> None:
        """Pipeline: without Art. 227, cross-currency cash gets 8% FX haircut."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="cash",
            market_value=1_000_000.0,
            currency="EUR",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=False,
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["fx_haircut"][0] == pytest.approx(0.08)
        assert result["value_after_haircut"][0] == pytest.approx(920_000.0)

    def test_absent_column_backward_compatible(self, crr_config) -> None:
        """Pipeline: absent qualifies_for_zero_haircut column → standard haircuts."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = _make_collateral(
            collateral_type="govt_bond",
            market_value=500_000.0,
            issuer_cqs=1,
            residual_maturity_years=3.0,
            qualifies_for_zero_haircut=None,  # column not added
        )
        result = calc.apply_haircuts(coll, crr_config).collect()
        # Standard CQS 1 haircut applies
        assert result["collateral_haircut"][0] > 0.0

    def test_null_flag_treated_as_false(self, crr_config) -> None:
        """Pipeline: null qualifies_for_zero_haircut → treated as False (conservative)."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = pl.LazyFrame({
            "collateral_reference": ["COLL_001"],
            "collateral_type": ["govt_bond"],
            "market_value": [500_000.0],
            "currency": ["GBP"],
            "exposure_currency": ["GBP"],
            "issuer_cqs": [1],
            "residual_maturity_years": [3.0],
            "qualifies_for_zero_haircut": [None],
            "is_eligible_financial_collateral": [True],
        })
        result = calc.apply_haircuts(coll, crr_config).collect()
        assert result["collateral_haircut"][0] > 0.0

    def test_b31_pipeline_sovereign_zero_haircut(self, b31_config) -> None:
        """Pipeline: B31 CQS 1 sovereign bond with Art. 227 → 0% haircut."""
        calc = HaircutCalculator(is_basel_3_1=True)
        coll = _make_collateral(
            collateral_type="govt_bond",
            market_value=1_000_000.0,
            issuer_cqs=1,
            residual_maturity_years=8.0,
            qualifies_for_zero_haircut=True,
        )
        result = calc.apply_haircuts(coll, b31_config).collect()
        assert result["collateral_haircut"][0] == pytest.approx(0.0)
        assert result["value_after_haircut"][0] == pytest.approx(1_000_000.0)

    def test_liquidation_period_irrelevant_for_art227(self, crr_config) -> None:
        """Art. 227 zero-haircut overrides liquidation period scaling."""
        calc = HaircutCalculator(is_basel_3_1=False)
        for period in [5, 10, 20]:
            coll = _make_collateral(
                collateral_type="cash",
                market_value=1_000_000.0,
                qualifies_for_zero_haircut=True,
                liquidation_period_days=period,
            )
            result = calc.apply_haircuts(coll, crr_config).collect()
            assert result["collateral_haircut"][0] == pytest.approx(0.0), (
                f"Expected 0% haircut for Art. 227 with {period}-day period"
            )
            assert result["value_after_haircut"][0] == pytest.approx(1_000_000.0)


# =============================================================================
# Mixed batch scenarios
# =============================================================================


class TestArt227MixedBatch:
    """Test Art. 227 with multiple collateral items in one batch."""

    @pytest.fixture
    def crr_config(self):
        from rwa_calc.contracts.config import CalculationConfig

        return CalculationConfig.crr(reporting_date=date(2024, 12, 31))

    def test_mixed_qualifying_and_non_qualifying(self, crr_config) -> None:
        """Batch: only qualifying items get zero haircut; others get standard."""
        calc = HaircutCalculator(is_basel_3_1=False)
        coll = pl.LazyFrame({
            "collateral_reference": [
                "REPO_CASH",
                "REPO_GILT",
                "NORMAL_GILT",
                "REPO_CORP",
            ],
            "collateral_type": ["cash", "govt_bond", "govt_bond", "corp_bond"],
            "market_value": [1_000_000.0, 500_000.0, 500_000.0, 300_000.0],
            "currency": ["GBP", "GBP", "GBP", "GBP"],
            "exposure_currency": ["GBP", "GBP", "GBP", "GBP"],
            "issuer_cqs": [None, 1, 1, 1],
            "residual_maturity_years": [None, 3.0, 3.0, 3.0],
            "qualifies_for_zero_haircut": [True, True, False, True],
            "is_eligible_financial_collateral": [True, True, True, True],
        })
        result = calc.apply_haircuts(coll, crr_config).collect()

        # REPO_CASH: Art. 227 → 0%
        assert result["collateral_haircut"][0] == pytest.approx(0.0)
        assert result["value_after_haircut"][0] == pytest.approx(1_000_000.0)

        # REPO_GILT: Art. 227 + CQS 1 → 0%
        assert result["collateral_haircut"][1] == pytest.approx(0.0)
        assert result["value_after_haircut"][1] == pytest.approx(500_000.0)

        # NORMAL_GILT: no Art. 227, CQS 1 → standard haircut (>0%)
        assert result["collateral_haircut"][2] > 0.0
        assert result["value_after_haircut"][2] < 500_000.0

        # REPO_CORP: Art. 227 flag but corporate bond → standard haircut (not eligible type)
        assert result["collateral_haircut"][3] > 0.0
        assert result["value_after_haircut"][3] < 300_000.0

    def test_capital_impact_comparison(self, crr_config) -> None:
        """Demonstrate capital impact: zero haircut vs standard for CQS 1 sovereign 5yr."""
        calc = HaircutCalculator(is_basel_3_1=False)
        mv = 10_000_000.0

        # With Art. 227
        coll_art227 = _make_collateral(
            collateral_type="govt_bond",
            market_value=mv,
            issuer_cqs=1,
            residual_maturity_years=5.0,
            qualifies_for_zero_haircut=True,
        )
        r227 = calc.apply_haircuts(coll_art227, crr_config).collect()

        # Without Art. 227
        coll_std = _make_collateral(
            collateral_type="govt_bond",
            market_value=mv,
            issuer_cqs=1,
            residual_maturity_years=5.0,
            qualifies_for_zero_haircut=False,
        )
        r_std = calc.apply_haircuts(coll_std, crr_config).collect()

        # Art. 227 preserves full collateral value
        assert r227["value_after_haircut"][0] == pytest.approx(mv)
        # Standard haircut reduces collateral value
        assert r_std["value_after_haircut"][0] < mv
        # The difference is significant for large repo positions
        capital_saving = r227["value_after_haircut"][0] - r_std["value_after_haircut"][0]
        assert capital_saving > 0, "Art. 227 must preserve more collateral value"


# =============================================================================
# Edge cases
# =============================================================================


class TestArt227EdgeCases:
    """Edge cases for Art. 227 zero-haircut treatment."""

    @pytest.fixture
    def crr_calc(self) -> HaircutCalculator:
        return HaircutCalculator(is_basel_3_1=False)

    def test_gilt_alias_eligible(self, crr_calc: HaircutCalculator) -> None:
        """'gilt' collateral type alias should be eligible for zero haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="gilt",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=2.0,
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")

    def test_sovereign_bond_alias_eligible(self, crr_calc: HaircutCalculator) -> None:
        """'sovereign_bond' collateral type alias should be eligible for zero haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="sovereign_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=1,
            residual_maturity_years=2.0,
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut == Decimal("0.0")

    def test_gold_not_eligible(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227(2)(a): gold is NOT eligible — only cash and 0%-RW sovereign bonds."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="gold",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        assert result.collateral_haircut > Decimal("0.0")

    def test_other_physical_not_eligible(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227: other_physical collateral is never eligible for zero haircut."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="other_physical",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        # Falls through to standard path → 40% default haircut
        assert result.collateral_haircut > Decimal("0.0")
        assert result.adjusted_value < Decimal("1000000")

    def test_zero_market_value(self, crr_calc: HaircutCalculator) -> None:
        """Art. 227: zero market value → adjusted value is 0 regardless."""
        result = crr_calc.calculate_single_haircut(
            collateral_type="cash",
            market_value=Decimal("0"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            qualifies_for_zero_haircut=True,
        )
        assert result.adjusted_value == Decimal("0")
        assert result.collateral_haircut == Decimal("0.0")
