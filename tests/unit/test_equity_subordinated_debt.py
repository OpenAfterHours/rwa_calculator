"""
Unit tests for EquityType.SUBORDINATED_DEBT (PRA PS1/26 Art. 133(1)).

Under Basel 3.1, subordinated debt / non-equity own funds instruments held as
equity exposures receive a flat 150% risk weight (Art. 133(1)). This weight:
- Takes priority after central_bank in the classification decision tree
- Is EXCLUDED from the transitional floor (PRA Rule 4.3)
- Under CRR, subordinated debt equity gets flat 100% (Art. 133(2))
- Under CRR IRB Simple, gets 370% (OTHER category)

References:
- PRA PS1/26 Art. 133(1): 150% for subordinated debt
- PRA Rule 4.3: transitional does not apply to subordinated debt
- CRR Art. 133(2): 100% flat for all equity
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
    get_b31_equity_rw_table,
    lookup_b31_equity_rw,
)
from rwa_calc.data.tables.crr_equity_rw import (
    IRB_SIMPLE_EQUITY_RISK_WEIGHTS,
    SA_EQUITY_RISK_WEIGHTS,
    get_equity_rw_table,
    lookup_equity_rw,
)
from rwa_calc.domain.enums import EquityType, PermissionMode
from rwa_calc.engine.equity import EquityCalculator


# =============================================================================
# Data Table Constants
# =============================================================================


class TestSubordinatedDebtDataTables:
    """Tests for subordinated debt entries in equity risk weight tables."""

    def test_b31_subordinated_debt_150_percent(self) -> None:
        """B31 Art. 133(1): subordinated debt = 150%."""
        assert B31_SA_EQUITY_RISK_WEIGHTS[EquityType.SUBORDINATED_DEBT] == Decimal("1.50")

    def test_crr_subordinated_debt_100_percent(self) -> None:
        """CRR Art. 133(2): subordinated debt = 100% (flat)."""
        assert SA_EQUITY_RISK_WEIGHTS[EquityType.SUBORDINATED_DEBT] == Decimal("1.00")

    def test_irb_simple_subordinated_debt_370_percent(self) -> None:
        """CRR Art. 155: subordinated debt = 370% (OTHER category)."""
        assert IRB_SIMPLE_EQUITY_RISK_WEIGHTS[EquityType.SUBORDINATED_DEBT] == Decimal("3.70")

    def test_b31_lookup_subordinated_debt(self) -> None:
        """B31 lookup function returns 150% for subordinated_debt."""
        assert lookup_b31_equity_rw("subordinated_debt") == Decimal("1.50")

    def test_crr_sa_lookup_subordinated_debt(self) -> None:
        """CRR SA lookup returns 100% for subordinated_debt."""
        assert lookup_equity_rw("subordinated_debt", approach="sa") == Decimal("1.00")

    def test_crr_irb_lookup_subordinated_debt(self) -> None:
        """CRR IRB Simple lookup returns 370% for subordinated_debt."""
        assert lookup_equity_rw("subordinated_debt", approach="irb_simple") == Decimal("3.70")

    def test_b31_dataframe_includes_subordinated_debt(self) -> None:
        """B31 DataFrame table should include subordinated_debt row."""
        df = get_b31_equity_rw_table()
        sub_debt_rows = df.filter(pl.col("equity_type") == "subordinated_debt")
        assert len(sub_debt_rows) == 1
        assert sub_debt_rows["risk_weight"][0] == pytest.approx(1.50)

    def test_crr_sa_dataframe_includes_subordinated_debt(self) -> None:
        """CRR SA DataFrame table should include subordinated_debt row."""
        df = get_equity_rw_table("sa")
        sub_debt_rows = df.filter(pl.col("equity_type") == "subordinated_debt")
        assert len(sub_debt_rows) == 1
        assert sub_debt_rows["risk_weight"][0] == pytest.approx(1.00)

    def test_crr_irb_dataframe_includes_subordinated_debt(self) -> None:
        """CRR IRB Simple DataFrame table should include subordinated_debt row."""
        df = get_equity_rw_table("irb_simple")
        sub_debt_rows = df.filter(pl.col("equity_type") == "subordinated_debt")
        assert len(sub_debt_rows) == 1
        assert sub_debt_rows["risk_weight"][0] == pytest.approx(3.70)

    def test_all_equity_types_still_covered_in_b31_table(self) -> None:
        """All EquityType members should have a B31 weight (including new member)."""
        for equity_type in EquityType:
            assert equity_type in B31_SA_EQUITY_RISK_WEIGHTS, (
                f"Missing {equity_type} in B31 table"
            )

    def test_all_equity_types_still_covered_in_crr_tables(self) -> None:
        """All EquityType members should have CRR SA and IRB Simple weights."""
        for equity_type in EquityType:
            assert equity_type in SA_EQUITY_RISK_WEIGHTS, (
                f"Missing {equity_type} in CRR SA table"
            )
            assert equity_type in IRB_SIMPLE_EQUITY_RISK_WEIGHTS, (
                f"Missing {equity_type} in CRR IRB Simple table"
            )


# =============================================================================
# B31 Calculator Weight Assignment
# =============================================================================


class TestB31SubordinatedDebtCalculator:
    """Tests for B31 SA subordinated debt weight in equity calculator."""

    @staticmethod
    def _apply_b31_weight(equity_type: str, **kwargs: bool | str | float | None) -> float:
        """Apply B31 SA weight to a single exposure."""
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

    def test_subordinated_debt_150_percent(self) -> None:
        """B31 Art. 133(1): subordinated debt equity = 150%."""
        assert self._apply_b31_weight("subordinated_debt") == pytest.approx(1.50)

    def test_subordinated_debt_rwa_correctness(self) -> None:
        """B31: subordinated debt RWA = EAD x 1.50."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2031, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type="subordinated_debt",
            config=config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)
        assert result["rwa"] == pytest.approx(1_500_000.0)

    def test_subordinated_debt_priority_over_speculative(self) -> None:
        """Subordinated debt type takes priority even if is_speculative flag set."""
        # The equity_type match should fire before is_speculative flag check
        assert self._apply_b31_weight(
            "subordinated_debt", is_speculative=True
        ) == pytest.approx(1.50)

    def test_subordinated_debt_not_affected_by_government_supported(self) -> None:
        """Subordinated debt type is not affected by is_government_supported flag."""
        assert self._apply_b31_weight(
            "subordinated_debt", is_government_supported=True
        ) == pytest.approx(1.50)

    def test_listed_still_250_percent(self) -> None:
        """Regression: listed equity still 250% after subordinated debt addition."""
        assert self._apply_b31_weight("listed") == pytest.approx(2.50)

    def test_speculative_still_400_percent(self) -> None:
        """Regression: speculative equity still 400% after subordinated debt addition."""
        assert self._apply_b31_weight("speculative", is_speculative=True) == pytest.approx(4.00)


# =============================================================================
# CRR Calculator — subordinated debt gets 100% flat
# =============================================================================


class TestCRRSubordinatedDebtCalculator:
    """Tests for CRR SA subordinated debt weight (Art. 133(2) flat 100%)."""

    def test_crr_subordinated_debt_100_percent(self) -> None:
        """CRR Art. 133(2): subordinated debt equity = 100% (flat)."""
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type="subordinated_debt",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(1_000_000.0)


# =============================================================================
# Transitional Floor Exclusion (PRA Rule 4.3)
# =============================================================================


class TestTransitionalFloorExclusion:
    """Tests that subordinated debt and government-supported equity are
    excluded from the transitional risk weight floor per PRA Rule 4.3.

    Transitional floor for 2027: standard=160%, higher-risk=220%.
    Without exclusion, subordinated debt (150%) would be raised to 160%.
    Without exclusion, government-supported (100%) would be raised to 160%.
    """

    @staticmethod
    def _calculate_with_transitional(
        equity_type: str,
        reporting_date: date,
        is_speculative: bool = False,
        is_government_supported: bool = False,
    ) -> float:
        """Calculate equity RW through full pipeline including transitional floor."""
        config = CalculationConfig.basel_3_1(
            reporting_date=reporting_date,
            permission_mode=PermissionMode.STANDARDISED,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type=equity_type,
            config=config,
            is_speculative=is_speculative,
            is_government_supported=is_government_supported,
        )
        return result["risk_weight"]

    def test_subordinated_debt_not_floored_in_2027(self) -> None:
        """PRA Rule 4.3: subordinated debt 150% should NOT be raised to 160% in 2027."""
        rw = self._calculate_with_transitional("subordinated_debt", date(2027, 6, 30))
        assert rw == pytest.approx(1.50)

    def test_subordinated_debt_not_floored_in_2028(self) -> None:
        """PRA Rule 4.3: subordinated debt 150% should NOT be raised to 190% in 2028."""
        rw = self._calculate_with_transitional("subordinated_debt", date(2028, 6, 30))
        assert rw == pytest.approx(1.50)

    def test_subordinated_debt_not_floored_in_2029(self) -> None:
        """PRA Rule 4.3: subordinated debt 150% should NOT be raised to 220% in 2029."""
        rw = self._calculate_with_transitional("subordinated_debt", date(2029, 6, 30))
        assert rw == pytest.approx(1.50)

    def test_government_supported_not_floored_in_2027(self) -> None:
        """PRA Rule 4.3: legislative equity 100% should NOT be raised to 160% in 2027."""
        rw = self._calculate_with_transitional(
            "government_supported", date(2027, 6, 30), is_government_supported=True
        )
        assert rw == pytest.approx(1.00)

    def test_government_supported_not_floored_in_2029(self) -> None:
        """PRA Rule 4.3: legislative equity 100% should NOT be raised to 220% in 2029."""
        rw = self._calculate_with_transitional(
            "government_supported", date(2029, 6, 30), is_government_supported=True
        )
        assert rw == pytest.approx(1.00)

    def test_central_bank_not_floored_in_2027(self) -> None:
        """Central bank equity 0% should NOT be raised by transitional floor."""
        rw = self._calculate_with_transitional("central_bank", date(2027, 6, 30))
        assert rw == pytest.approx(0.00)

    def test_listed_still_floored_in_2027(self) -> None:
        """Standard equity should still be subject to transitional floor."""
        rw = self._calculate_with_transitional("listed", date(2027, 6, 30))
        # B31 listed = 250%, transitional std 2027 = 160%, max(250%, 160%) = 250%
        assert rw == pytest.approx(2.50)

    def test_speculative_still_floored_in_2027(self) -> None:
        """Higher risk equity should still be subject to transitional floor."""
        rw = self._calculate_with_transitional(
            "speculative", date(2027, 6, 30), is_speculative=True
        )
        # B31 speculative = 400%, transitional hr 2027 = 220%, max(400%, 220%) = 400%
        assert rw == pytest.approx(4.00)

    def test_post_transitional_subordinated_unchanged(self) -> None:
        """After transitional period, subordinated debt still 150%."""
        rw = self._calculate_with_transitional("subordinated_debt", date(2031, 6, 30))
        assert rw == pytest.approx(1.50)


# =============================================================================
# Enum Member Tests
# =============================================================================


class TestSubordinatedDebtEnum:
    """Tests for the EquityType.SUBORDINATED_DEBT enum member."""

    def test_enum_value(self) -> None:
        """SUBORDINATED_DEBT enum has correct string value."""
        assert EquityType.SUBORDINATED_DEBT == "subordinated_debt"
        assert EquityType.SUBORDINATED_DEBT.value == "subordinated_debt"

    def test_enum_member_count(self) -> None:
        """EquityType should now have 11 members (was 10)."""
        assert len(EquityType) == 11

    def test_subordinated_debt_in_valid_equity_types(self) -> None:
        """VALID_EQUITY_TYPES schema validation set includes subordinated_debt."""
        from rwa_calc.data.schemas import VALID_EQUITY_TYPES

        assert "subordinated_debt" in VALID_EQUITY_TYPES
        assert len(VALID_EQUITY_TYPES) == 11


# =============================================================================
# Mixed Batch Test
# =============================================================================


class TestSubordinatedDebtMixedBatch:
    """Test subordinated debt alongside other equity types in a batch."""

    def test_mixed_equity_batch_b31(self) -> None:
        """B31: mixed batch with subordinated debt, listed, and speculative."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2031, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        calculator = EquityCalculator()
        df = pl.DataFrame(
            {
                "exposure_reference": ["EQ_SUB", "EQ_LIST", "EQ_SPEC", "EQ_GOV"],
                "ead_final": [100_000.0, 200_000.0, 50_000.0, 150_000.0],
                "equity_type": [
                    "subordinated_debt",
                    "listed",
                    "speculative",
                    "government_supported",
                ],
                "is_speculative": [False, False, True, False],
                "is_exchange_traded": [False, False, False, False],
                "is_government_supported": [False, False, False, True],
                "is_diversified_portfolio": [False, False, False, False],
                "ciu_approach": [None, None, None, None],
                "ciu_mandate_rw": [None, None, None, None],
                "ciu_third_party_calc": [None, None, None, None],
                "ciu_look_through_rw": [None, None, None, None],
            }
        ).lazy()

        result = calculator._apply_b31_equity_weights_sa(df, config).collect()
        rws = result["risk_weight"].to_list()

        assert rws[0] == pytest.approx(1.50)  # subordinated_debt
        assert rws[1] == pytest.approx(2.50)  # listed
        assert rws[2] == pytest.approx(4.00)  # speculative
        assert rws[3] == pytest.approx(1.00)  # government_supported
