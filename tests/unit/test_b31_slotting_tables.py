"""
Unit tests for Basel 3.1 slotting data tables.

Tests verify:
- Lookup tables contain expected values per BCBS CRE33
- Lookup function returns correct values
- Pre-operational phase has distinct (higher) weights
- HVCRE weights match CRR HVCRE equivalents
"""

from decimal import Decimal

from rwa_calc.data.tables.b31_slotting import (
    B31_SLOTTING_RISK_WEIGHTS,
    B31_SLOTTING_RISK_WEIGHTS_HVCRE,
    B31_SLOTTING_RISK_WEIGHTS_PREOP,
    lookup_b31_slotting_rw,
)
from rwa_calc.domain.enums import SlottingCategory


class TestB31SlottingRiskWeights:
    """Tests for Basel 3.1 slotting risk weights (BCBS CRE33)."""

    def test_base_strong_seventy_percent(self) -> None:
        """Strong operational gets 70% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.STRONG] == Decimal("0.70")

    def test_base_good_ninety_percent(self) -> None:
        """Good operational gets 90% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.GOOD] == Decimal("0.90")

    def test_base_satisfactory_one_fifteen(self) -> None:
        """Satisfactory operational gets 115% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.SATISFACTORY] == Decimal("1.15")

    def test_base_weak_two_fifty(self) -> None:
        """Weak operational gets 250% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.WEAK] == Decimal("2.50")

    def test_base_default_zero(self) -> None:
        """Default gets 0% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.DEFAULT] == Decimal("0.00")

    def test_base_has_five_categories(self) -> None:
        """Base table has exactly 5 categories."""
        assert len(B31_SLOTTING_RISK_WEIGHTS) == 5


class TestB31SlottingPreOperational:
    """Tests for Basel 3.1 pre-operational phase weights."""

    def test_preop_strong_eighty_percent(self) -> None:
        """Strong pre-operational gets 80% RW (higher than base 70%)."""
        assert B31_SLOTTING_RISK_WEIGHTS_PREOP[SlottingCategory.STRONG] == Decimal("0.80")

    def test_preop_good_hundred_percent(self) -> None:
        """Good pre-operational gets 100% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS_PREOP[SlottingCategory.GOOD] == Decimal("1.00")

    def test_preop_satisfactory_one_twenty(self) -> None:
        """Satisfactory pre-operational gets 120% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS_PREOP[SlottingCategory.SATISFACTORY] == Decimal("1.20")

    def test_preop_weak_three_fifty(self) -> None:
        """Weak pre-operational gets 350% RW (higher than base 250%)."""
        assert B31_SLOTTING_RISK_WEIGHTS_PREOP[SlottingCategory.WEAK] == Decimal("3.50")

    def test_preop_weak_differs_from_base(self) -> None:
        """Pre-operational Weak (350%) differs from base Weak (250%)."""
        assert (
            B31_SLOTTING_RISK_WEIGHTS_PREOP[SlottingCategory.WEAK]
            != B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.WEAK]
        )


class TestB31SlottingHVCRE:
    """Tests for Basel 3.1 HVCRE slotting weights."""

    def test_hvcre_strong_ninety_five(self) -> None:
        """HVCRE Strong gets 95% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS_HVCRE[SlottingCategory.STRONG] == Decimal("0.95")

    def test_hvcre_good_one_twenty(self) -> None:
        """HVCRE Good gets 120% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS_HVCRE[SlottingCategory.GOOD] == Decimal("1.20")

    def test_hvcre_satisfactory_one_forty(self) -> None:
        """HVCRE Satisfactory gets 140% RW."""
        assert B31_SLOTTING_RISK_WEIGHTS_HVCRE[SlottingCategory.SATISFACTORY] == Decimal("1.40")

    def test_hvcre_weak_same_as_base(self) -> None:
        """HVCRE Weak (250%) is same as base Weak."""
        assert (
            B31_SLOTTING_RISK_WEIGHTS_HVCRE[SlottingCategory.WEAK]
            == B31_SLOTTING_RISK_WEIGHTS[SlottingCategory.WEAK]
        )


class TestB31SlottingLookup:
    """Tests for Basel 3.1 slotting lookup function."""

    def test_lookup_base_by_string(self) -> None:
        """Lookup base weight by string category."""
        assert lookup_b31_slotting_rw("strong") == Decimal("0.70")

    def test_lookup_base_by_enum(self) -> None:
        """Lookup base weight by enum."""
        assert lookup_b31_slotting_rw(SlottingCategory.GOOD) == Decimal("0.90")

    def test_lookup_hvcre(self) -> None:
        """Lookup HVCRE weight."""
        assert lookup_b31_slotting_rw("strong", is_hvcre=True) == Decimal("0.95")

    def test_lookup_preop(self) -> None:
        """Lookup pre-operational weight."""
        assert lookup_b31_slotting_rw("strong", is_pre_operational=True) == Decimal("0.80")

    def test_lookup_hvcre_takes_precedence_over_preop(self) -> None:
        """HVCRE flag takes precedence when both flags are set."""
        assert lookup_b31_slotting_rw("strong", is_hvcre=True, is_pre_operational=True) == Decimal(
            "0.95"
        )

    def test_lookup_unknown_category_defaults_to_satisfactory(self) -> None:
        """Unknown category defaults to satisfactory (115%)."""
        assert lookup_b31_slotting_rw("unknown") == Decimal("1.15")

    def test_lookup_case_insensitive(self) -> None:
        """Lookup handles uppercase input."""
        assert lookup_b31_slotting_rw("STRONG") == Decimal("0.70")
