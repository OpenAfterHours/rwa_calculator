"""
Unit tests for Basel 3.1 equity SA risk weights (PRA PS1/26 Art. 133).

Under Basel 3.1, all equity uses SA (IRB removed per Art. 147A).
Key changes from CRR:
- Listed/exchange-traded: 100% -> 250% (Art. 133(3))
- CIU fallback: 150% -> 250% (Art. 132(2))
- Transitional floor phases from 160%/220% (2027) to 250%/400% (2030)

References:
- PRA PS1/26 Art. 133(3)-(6)
- PRA Rules 4.1-4.10: Equity transitional schedule
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.single_exposure import calculate_single_equity_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_equity_rw import (
    B31_SA_EQUITY_RISK_WEIGHTS,
    get_b31_equity_risk_weights,
    get_b31_equity_rw_table,
    lookup_b31_equity_rw,
)
from rwa_calc.domain.enums import EquityType, PermissionMode
from rwa_calc.engine.equity import EquityCalculator

# =============================================================================
# Data Table Tests
# =============================================================================


class TestB31EquityRiskWeightTable:
    """Tests for the B31 SA equity risk weight data table."""

    def test_central_bank_zero(self) -> None:
        """Central bank equity should be 0% under B31 (Art. 133(6))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.CENTRAL_BANK] == Decimal("0.00")

    def test_listed_250_percent(self) -> None:
        """Listed equity should be 250% under B31 (Art. 133(3))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.LISTED] == Decimal("2.50")

    def test_exchange_traded_250_percent(self) -> None:
        """Exchange-traded equity should be 250% under B31 (Art. 133(3))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.EXCHANGE_TRADED] == Decimal("2.50")

    def test_government_supported_100_percent(self) -> None:
        """Government-supported equity should be 100% (legislative programme)."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.GOVERNMENT_SUPPORTED] == Decimal("1.00")

    def test_unlisted_250_percent(self) -> None:
        """Unlisted equity should be 250% under B31 (Art. 133(3))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.UNLISTED] == Decimal("2.50")

    def test_speculative_400_percent(self) -> None:
        """Speculative equity should be 400% under B31 (Art. 133(4))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.SPECULATIVE] == Decimal("4.00")

    def test_private_equity_250_percent(self) -> None:
        """Private equity should be 250% under B31 (Art. 133(3))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.PRIVATE_EQUITY] == Decimal("2.50")

    def test_ciu_250_percent(self) -> None:
        """CIU fallback should be 250% under B31 (Art. 132(2))."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.CIU] == Decimal("2.50")

    def test_all_equity_types_covered(self) -> None:
        """All EquityType members should have a B31 weight."""
        for equity_type in EquityType:
            assert equity_type in B31_SA_EQUITY_RISK_WEIGHTS


class TestB31EquityLookup:
    """Tests for B31 equity risk weight lookup functions."""

    def test_lookup_listed(self) -> None:
        """Lookup by string should return correct B31 weight."""
        assert lookup_b31_equity_rw("listed") == Decimal("2.50")

    def test_lookup_speculative(self) -> None:
        """Lookup speculative should return 400%."""
        assert lookup_b31_equity_rw("speculative") == Decimal("4.00")

    def test_lookup_unknown_defaults_to_other(self) -> None:
        """Unknown equity type should default to OTHER = 250%."""
        assert lookup_b31_equity_rw("unknown_type") == Decimal("2.50")

    def test_get_b31_equity_risk_weights_returns_copy(self) -> None:
        """get_b31_equity_risk_weights should return a copy, not original."""
        weights = get_b31_equity_risk_weights()
        weights[EquityType.LISTED] = Decimal("9.99")
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.LISTED] == Decimal("2.50")

    def test_dataframe_table_has_all_types(self) -> None:
        """DataFrame table should have one row per equity type."""
        df = get_b31_equity_rw_table()
        assert len(df) == len(EquityType)
        assert "equity_type" in df.columns
        assert "risk_weight" in df.columns


# =============================================================================
# Calculator Tests — B31 SA Weights
# =============================================================================


class TestB31EquityCalculatorSAWeights:
    """Tests for B31 SA equity risk weight assignment in the calculator.

    Tests weight assignment in isolation by calling _apply_b31_equity_weights_sa
    directly, then testing end-to-end via calculate_branch which includes
    transitional floor.
    """

    @staticmethod
    def _apply_b31_weight(equity_type: str, **kwargs: bool | str | float | None) -> float:
        """Apply B31 SA weight to a single exposure and return the risk_weight."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2031, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        calculator = EquityCalculator()
        df = pl.DataFrame(
            {
                "exposure_reference": ["EQ_TEST"],
                "ead_final": [1_000_000.0],
                "equity_type": [equity_type],
                "is_speculative": [kwargs.get("is_speculative", False)],
                "is_exchange_traded": [kwargs.get("is_exchange_traded", False)],
                "is_government_supported": [kwargs.get("is_government_supported", False)],
                "is_diversified_portfolio": [False],
                "ciu_approach": [kwargs.get("ciu_approach")],
                "ciu_mandate_rw": [kwargs.get("ciu_mandate_rw")],
                "ciu_third_party_calc": [kwargs.get("ciu_third_party_calc")],
                "ciu_look_through_rw": [None],
            }
        ).lazy()
        result = calculator._apply_b31_equity_weights_sa(df, config).collect()
        return result["risk_weight"][0]

    def test_listed_equity_250_percent(self) -> None:
        """B31 Art. 133(3): Listed equity = 250%."""
        assert self._apply_b31_weight("listed") == pytest.approx(2.50)

    def test_exchange_traded_250_percent(self) -> None:
        """B31 Art. 133(3): Exchange-traded equity = 250%."""
        assert self._apply_b31_weight("exchange_traded", is_exchange_traded=True) == pytest.approx(
            2.50
        )

    def test_unlisted_equity_250_percent(self) -> None:
        """B31 Art. 133(3): Unlisted equity = 250%."""
        assert self._apply_b31_weight("unlisted") == pytest.approx(2.50)

    def test_speculative_equity_400_percent(self) -> None:
        """B31 Art. 133(4): Speculative equity = 400%."""
        assert self._apply_b31_weight("speculative", is_speculative=True) == pytest.approx(4.00)

    def test_is_speculative_flag_overrides_type(self) -> None:
        """B31: is_speculative=True overrides listed type to 400%."""
        assert self._apply_b31_weight("listed", is_speculative=True) == pytest.approx(4.00)

    def test_government_supported_100_percent(self) -> None:
        """B31: Government-supported equity = 100% (legislative carve-out).

        Note: The transitional floor (250%+ during 2027-2030) overrides this to 250%
        when applied via calculate_branch. This test verifies the base weight before floor.
        """
        assert self._apply_b31_weight(
            "government_supported", is_government_supported=True
        ) == pytest.approx(1.00)

    def test_central_bank_zero_percent(self) -> None:
        """B31 Art. 133(6): Central bank equity = 0%."""
        assert self._apply_b31_weight("central_bank") == pytest.approx(0.00)

    def test_private_equity_250_percent(self) -> None:
        """B31 Art. 133(3): Private equity = 250% (standard)."""
        assert self._apply_b31_weight("private_equity") == pytest.approx(2.50)

    def test_ciu_fallback_250_percent(self) -> None:
        """B31: CIU fallback = 250% (was 150% under CRR)."""
        assert self._apply_b31_weight("ciu", ciu_approach="fallback") == pytest.approx(2.50)

    def test_other_equity_250_percent(self) -> None:
        """B31 Art. 133(3): Other equity = 250% (standard)."""
        assert self._apply_b31_weight("other") == pytest.approx(2.50)


class TestB31EquityEndToEnd:
    """End-to-end tests for B31 equity via calculate_branch (includes transitional floor)."""

    def test_listed_equity_rwa(self) -> None:
        """B31: Listed equity = 250%, RWA = EAD x 2.50."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2031, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type="listed",
            config=config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)
        assert result["rwa"] == pytest.approx(2_500_000.0)

    def test_speculative_equity_rwa(self) -> None:
        """B31: Speculative = 400%, RWA = EAD x 4.00."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2031, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("200000"),
            equity_type="speculative",
            is_speculative=True,
            config=config,
        )
        assert result["risk_weight"] == pytest.approx(4.00)
        assert result["rwa"] == pytest.approx(800_000.0)

    def test_crr_listed_still_100_percent(self) -> None:
        """CRR: Listed equity = 100% (regression test)."""
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type="listed",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_ciu_fallback_150_percent(self) -> None:
        """CRR: CIU fallback = 150% (regression test)."""
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("300000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)


# =============================================================================
# Transitional Floor Tests via get_equity_result_bundle
# =============================================================================


class TestEquityTransitionalFloorInBundle:
    """Tests that get_equity_result_bundle applies the transitional floor.

    Prior to P1.43 fix, get_equity_result_bundle skipped _apply_transitional_floor.
    Both calculate_branch and get_equity_result_bundle should produce consistent results.
    """

    def _make_bundle(self, equity_type: str = "listed") -> pl.LazyFrame:
        """Create a minimal equity exposure LazyFrame."""
        return pl.DataFrame(
            {
                "exposure_reference": ["EQ001"],
                "ead_final": [1_000_000.0],
                "equity_type": [equity_type],
                "is_speculative": [equity_type == "speculative"],
                "is_exchange_traded": [equity_type in ("listed", "exchange_traded")],
                "is_government_supported": [equity_type == "government_supported"],
            }
        ).lazy()

    def test_bundle_path_applies_transitional_floor(self) -> None:
        """get_equity_result_bundle should apply transitional floor for 2027."""
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        calculator = EquityCalculator()

        # Create a minimal CRM-adjusted bundle with equity exposures
        bundle = CRMAdjustedBundle(
            exposures=pl.LazyFrame(),
            sa_exposures=pl.LazyFrame(),
            irb_exposures=pl.LazyFrame(),
            equity_exposures=self._make_bundle("listed"),
        )

        result = calculator.get_equity_result_bundle(bundle, config)
        row = result.results.collect().to_dicts()[0]

        # 2027: B31 SA listed = 250%, transitional floor std = 160%
        # max(250%, 160%) = 250%
        assert row["risk_weight"] == pytest.approx(2.50)

    def test_bundle_and_branch_produce_same_results(self) -> None:
        """Both entry points should produce identical risk weights."""
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        calculator = EquityCalculator()

        equity_data = self._make_bundle("listed")

        # Path 1: calculate_branch
        branch_result = calculator.calculate_branch(equity_data, config).collect()
        branch_rw = branch_result["risk_weight"][0]

        # Path 2: get_equity_result_bundle
        bundle = CRMAdjustedBundle(
            exposures=pl.LazyFrame(),
            sa_exposures=pl.LazyFrame(),
            irb_exposures=pl.LazyFrame(),
            equity_exposures=self._make_bundle("listed"),
        )
        bundle_result = calculator.get_equity_result_bundle(bundle, config)
        bundle_rw = bundle_result.results.collect()["risk_weight"][0]

        assert branch_rw == pytest.approx(bundle_rw)
