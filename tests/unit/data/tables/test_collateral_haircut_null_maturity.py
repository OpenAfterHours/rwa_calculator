"""
Tests for lookup_collateral_haircut conservative-band fallback when
residual_maturity_years is None (P1.158).

Bug: haircuts.py lines 456 (govt_bond) and 475 (corp_bond) use
    maturity = residual_maturity_years or 5.0
This falsy-ors None to 5.0, which maps to the mid-band under CRR
(5.0 <= 5.0 → "1_5y") instead of the longest band ("5y_plus").
Under Basel 3.1 the same pattern maps 5.0 to "3_5y" instead of "10y_plus".

Post-fix behaviour: when residual_maturity_years is None the function must
return the longest / most conservative band haircut.

References:
    CRR Art. 224 Table 1: supervisory haircuts by maturity band
    PRA PS1/26 Art. 224 Table 1: Basel 3.1 supervisory haircuts
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.data.tables.haircuts import lookup_collateral_haircut

# =============================================================================
# CRR — null maturity must fall into the longest band (5y+)
# =============================================================================


class TestCRRNullMaturityFallback:
    """When residual_maturity_years is None under CRR, use the 5y+ (longest) band."""

    def test_corp_bond_cqs2_null_maturity_returns_5y_plus_haircut(self) -> None:
        """CRR corp bond CQS 2, null maturity → 5y+ band haircut = 12%.

        CRR Art. 224 Table 1: corp CQS 2-3, 5y+ band = 12%.
        Bug: falsy-or maps None → 5.0, get_maturity_band(5.0) → "1_5y" → 6%.
        """
        # Arrange
        collateral_type = "corp_bond"
        cqs = 2
        residual_maturity_years = None

        # Act
        result = lookup_collateral_haircut(
            collateral_type,
            cqs=cqs,
            residual_maturity_years=residual_maturity_years,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )

        # Assert — post-fix expected value
        assert result == Decimal("0.12"), (
            f"Expected 0.12 (5y+ band) but got {result}; "
            f"bug returns 0.06 (1_5y band via falsy-or 5.0)"
        )

    def test_govt_bond_cqs1_null_maturity_returns_5y_plus_haircut(self) -> None:
        """CRR govt bond CQS 1, null maturity → 5y+ band haircut = 4%.

        CRR Art. 224 Table 1: govt CQS 1, 5y+ band = 4%.
        Bug: falsy-or maps None → 5.0, get_maturity_band(5.0) → "1_5y" → 2%.
        """
        # Arrange
        collateral_type = "govt_bond"
        cqs = 1
        residual_maturity_years = None

        # Act
        result = lookup_collateral_haircut(
            collateral_type,
            cqs=cqs,
            residual_maturity_years=residual_maturity_years,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )

        # Assert — post-fix expected value
        assert result == Decimal("0.04"), (
            f"Expected 0.04 (5y+ band) but got {result}; "
            f"bug returns 0.02 (1_5y band via falsy-or 5.0)"
        )

    def test_corp_bond_cqs3_null_maturity_returns_5y_plus_haircut(self) -> None:
        """CRR corp bond CQS 3, null maturity → 5y+ band = 12% (shared CQS 2-3 key)."""
        # Arrange / Act
        result = lookup_collateral_haircut(
            "corp_bond",
            cqs=3,
            residual_maturity_years=None,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )

        # Assert
        assert result == Decimal("0.12")

    def test_corp_bond_cqs1_null_maturity_returns_5y_plus_haircut(self) -> None:
        """CRR corp bond CQS 1, null maturity → 5y+ band haircut = 8%."""
        # Arrange / Act
        result = lookup_collateral_haircut(
            "corp_bond",
            cqs=1,
            residual_maturity_years=None,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )

        # Assert
        assert result == Decimal("0.08")

    def test_govt_bond_cqs2_null_maturity_returns_5y_plus_haircut(self) -> None:
        """CRR govt bond CQS 2, null maturity → 5y+ band haircut = 6%."""
        # Arrange / Act
        result = lookup_collateral_haircut(
            "govt_bond",
            cqs=2,
            residual_maturity_years=None,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )

        # Assert
        assert result == Decimal("0.06")


# =============================================================================
# Basel 3.1 — null maturity must fall into the longest band (10y+)
# =============================================================================


class TestBasel31NullMaturityFallback:
    """When residual_maturity_years is None under Basel 3.1, use the 10y+ (longest) band."""

    def test_corp_bond_cqs1_null_maturity_returns_10y_plus_haircut(self) -> None:
        """B31 corp bond CQS 1, null maturity → 10y+ band haircut = 12%.

        PRA PS1/26 Art. 224 Table 1: corp CQS 1, 10y+ band = 12%.
        This exercises the ALREADY-CORRECT code path at haircuts.py:115.
        Regression-pins that the fix does not break existing Basel 3.1 behaviour.
        """
        # Arrange
        collateral_type = "corp_bond"
        cqs = 1
        residual_maturity_years = None

        # Act
        result = lookup_collateral_haircut(
            collateral_type,
            cqs=cqs,
            residual_maturity_years=residual_maturity_years,
            is_basel_3_1=True,
            liquidation_period_days=10,
        )

        # Assert
        assert result == Decimal("0.12"), f"Expected 0.12 (B31 10y+ band) but got {result}"

    def test_corp_bond_cqs2_null_maturity_returns_10y_plus_haircut(self) -> None:
        """B31 corp bond CQS 2, null maturity → 10y+ band haircut = 20%.

        PRA PS1/26 Art. 224 Table 1: corp CQS 2-3, 10y+ band = 20%.
        Bug: falsy-or maps None → 5.0, get_maturity_band(5.0, is_b31=True) → "3_5y" → 6%.
        """
        # Arrange / Act
        result = lookup_collateral_haircut(
            "corp_bond",
            cqs=2,
            residual_maturity_years=None,
            is_basel_3_1=True,
            liquidation_period_days=10,
        )

        # Assert — post-fix expected value
        assert result == Decimal("0.20"), (
            f"Expected 0.20 (B31 10y+ band) but got {result}; "
            f"bug returns 0.06 (3_5y band via falsy-or 5.0)"
        )

    def test_govt_bond_cqs1_null_maturity_returns_10y_plus_haircut(self) -> None:
        """B31 govt bond CQS 1, null maturity → 10y+ band haircut = 4%."""
        # Arrange / Act
        result = lookup_collateral_haircut(
            "govt_bond",
            cqs=1,
            residual_maturity_years=None,
            is_basel_3_1=True,
            liquidation_period_days=10,
        )

        # Assert
        assert result == Decimal("0.04")


# =============================================================================
# Regression: existing behaviour with explicit maturity is unchanged
# =============================================================================


class TestExplicitMaturityUnchanged:
    """Explicit residual_maturity_years values must not be affected by the fix."""

    def test_corp_bond_cqs2_explicit_3y_returns_mid_band(self) -> None:
        """CRR corp bond CQS 2 at 3y → 1_5y band = 6%."""
        result = lookup_collateral_haircut(
            "corp_bond",
            cqs=2,
            residual_maturity_years=3.0,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )
        assert result == Decimal("0.06")

    def test_govt_bond_cqs1_explicit_0_5y_returns_short_band(self) -> None:
        """CRR govt bond CQS 1 at 0.5y → 0_1y band = 0.5%."""
        result = lookup_collateral_haircut(
            "govt_bond",
            cqs=1,
            residual_maturity_years=0.5,
            is_basel_3_1=False,
            liquidation_period_days=10,
        )
        assert result == Decimal("0.005")

    def test_corp_bond_cqs1_explicit_15y_b31_returns_10y_plus(self) -> None:
        """B31 corp bond CQS 1 at 15y → 10y+ band = 12%."""
        result = lookup_collateral_haircut(
            "corp_bond",
            cqs=1,
            residual_maturity_years=15.0,
            is_basel_3_1=True,
            liquidation_period_days=10,
        )
        assert result == Decimal("0.12")
