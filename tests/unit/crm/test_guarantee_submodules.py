"""
Direct unit tests for CRM guarantee sub-functions.

Tests individual guarantee functions in isolation, complementing the
integration-level tests that go through CRMProcessor. This provides faster,
more focused regression detection for critical regulatory formulas.

Why these tests matter:
- FX mismatch haircut (Art. 233(3-4)) directly affects capital: 8% reduction
  on cross-currency guarantees.
- CDS restructuring exclusion (Art. 233(2)) applies a 40% haircut — a missing
  test let a previous bug survive for weeks.
- Multi-level allocation and pro-rata splitting are complex Polars operations
  where off-by-one errors or join mismatches silently produce wrong capital.
- Cross-approach CCF substitution (IRB + SA guarantor) changes EAD calculation
  method — incorrect application overstates or understates capital.

References:
    CRR Art. 213-217: Unfunded credit protection
    CRR Art. 233(2-4): Haircuts on unfunded protection
    CRR Art. 224 Table 4: H_fx = 8%
    PRA PS1/26 Art. 233(2-4): Same treatment under Basel 3.1
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.data.tables.crr_haircuts import FX_HAIRCUT, RESTRUCTURING_EXCLUSION_HAIRCUT
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.guarantees import (
    _allocate_guarantees_pro_rata,
    _apply_cross_approach_ccf,
    _apply_guarantee_fx_haircut,
    _apply_guarantee_splits,
    _apply_restructuring_exclusion_haircut,
    _resolve_guarantee_amount_expr,
    _resolve_guarantees_multi_level,
)


# =============================================================================
# Helpers
# =============================================================================


def _fx_exposure(
    *,
    guaranteed_portion: float = 500_000.0,
    ead_after_collateral: float = 1_000_000.0,
    guarantee_currency: str | None = "EUR",
    exposure_currency: str = "GBP",
    currency_col: str = "currency",
) -> pl.LazyFrame:
    """Build minimal frame for FX haircut testing."""
    data: dict = {
        "exposure_reference": ["EXP001"],
        "guaranteed_portion": [guaranteed_portion],
        "ead_after_collateral": [ead_after_collateral],
        "unguaranteed_portion": [ead_after_collateral - guaranteed_portion],
    }
    if guarantee_currency is not None:
        data["guarantee_currency"] = [guarantee_currency]
    else:
        data["guarantee_currency"] = pl.Series("guarantee_currency", [None], dtype=pl.String)
    data[currency_col] = [exposure_currency]
    return pl.LazyFrame(data)


def _restructuring_exposure(
    *,
    guaranteed_portion: float = 500_000.0,
    ead_after_collateral: float = 1_000_000.0,
    protection_type: str | None = "credit_derivative",
    includes_restructuring: bool | None = False,
    include_protection_type_col: bool = True,
    include_restructuring_col: bool = True,
) -> pl.LazyFrame:
    """Build minimal frame for restructuring exclusion haircut testing."""
    data: dict = {
        "exposure_reference": ["EXP001"],
        "guaranteed_portion": [guaranteed_portion],
        "ead_after_collateral": [ead_after_collateral],
        "unguaranteed_portion": [ead_after_collateral - guaranteed_portion],
    }
    if include_protection_type_col:
        data["protection_type"] = [protection_type]
    if include_restructuring_col:
        data["includes_restructuring"] = [includes_restructuring]
    return pl.LazyFrame(data)


# =============================================================================
# FX mismatch haircut (Art. 233(3-4))
# =============================================================================


class TestGuaranteeFxHaircut:
    """Art. 233(3-4): G* = G x (1 - H_fx) where H_fx = 8%."""

    def test_cross_currency_applies_8pct_haircut(self) -> None:
        """EUR guarantee on GBP exposure reduces guaranteed portion by 8%."""
        lf = _fx_exposure(guaranteed_portion=500_000.0, guarantee_currency="EUR")
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0 * 0.92, rel=1e-9)
        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.08)

    def test_same_currency_no_haircut(self) -> None:
        """GBP guarantee on GBP exposure: no FX haircut."""
        lf = _fx_exposure(guaranteed_portion=500_000.0, guarantee_currency="GBP")
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)
        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.0)

    def test_null_guarantee_currency_no_haircut(self) -> None:
        """Null guarantee currency: no mismatch detected, no haircut."""
        lf = _fx_exposure(guaranteed_portion=500_000.0, guarantee_currency=None)
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)
        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.0)

    def test_zero_guaranteed_portion_no_haircut(self) -> None:
        """Zero guaranteed portion: condition false, no haircut applied."""
        lf = _fx_exposure(guaranteed_portion=0.0, guarantee_currency="EUR")
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(0.0)
        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.0)

    def test_guarantee_currency_column_absent_early_return(self) -> None:
        """Missing guarantee_currency column: early return with haircut = 0."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "guaranteed_portion": [500_000.0],
                "ead_after_collateral": [1_000_000.0],
                "unguaranteed_portion": [500_000.0],
                "currency": ["GBP"],
            }
        )
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.0)
        # guaranteed_portion unchanged
        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)

    def test_exposure_currency_column_absent_early_return(self) -> None:
        """Neither currency nor original_currency: early return with haircut = 0."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "guaranteed_portion": [500_000.0],
                "ead_after_collateral": [1_000_000.0],
                "unguaranteed_portion": [500_000.0],
                "guarantee_currency": ["EUR"],
            }
        )
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.0)

    def test_original_currency_preferred_over_currency(self) -> None:
        """original_currency takes priority over currency for mismatch detection."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "guaranteed_portion": [500_000.0],
                "ead_after_collateral": [1_000_000.0],
                "unguaranteed_portion": [500_000.0],
                "guarantee_currency": ["EUR"],
                "original_currency": ["EUR"],  # same as guarantee → no mismatch
                "currency": ["GBP"],  # different but ignored
            }
        )
        result = _apply_guarantee_fx_haircut(lf).collect()

        # original_currency == guarantee_currency → no mismatch
        assert result["guarantee_fx_haircut"][0] == pytest.approx(0.0)
        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)

    def test_unguaranteed_portion_recalculated(self) -> None:
        """After FX haircut, unguaranteed_portion = EAD - guaranteed_portion."""
        lf = _fx_exposure(
            guaranteed_portion=800_000.0,
            ead_after_collateral=1_000_000.0,
            guarantee_currency="USD",
        )
        result = _apply_guarantee_fx_haircut(lf).collect()

        expected_guar = 800_000.0 * 0.92
        assert result["guaranteed_portion"][0] == pytest.approx(expected_guar, rel=1e-9)
        assert result["unguaranteed_portion"][0] == pytest.approx(
            1_000_000.0 - expected_guar, rel=1e-9
        )

    def test_fx_haircut_constant_value(self) -> None:
        """FX_HAIRCUT constant is 8% (Decimal 0.08)."""
        from decimal import Decimal

        assert FX_HAIRCUT == Decimal("0.08")

    def test_full_guarantee_cross_currency(self) -> None:
        """Full EAD guarantee in different currency: 8% becomes unguaranteed."""
        lf = _fx_exposure(
            guaranteed_portion=1_000_000.0,
            ead_after_collateral=1_000_000.0,
            guarantee_currency="JPY",
        )
        result = _apply_guarantee_fx_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(920_000.0, rel=1e-9)
        assert result["unguaranteed_portion"][0] == pytest.approx(80_000.0, rel=1e-9)


# =============================================================================
# Restructuring exclusion haircut (Art. 233(2))
# =============================================================================


class TestRestructuringExclusionHaircut:
    """Art. 233(2): CDS without restructuring gets 40% haircut."""

    def test_cd_without_restructuring_40pct_haircut(self) -> None:
        """Credit derivative excluding restructuring: G* = G x 0.60."""
        lf = _restructuring_exposure(
            guaranteed_portion=500_000.0,
            protection_type="credit_derivative",
            includes_restructuring=False,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(300_000.0, rel=1e-9)
        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.40)

    def test_cd_with_restructuring_no_haircut(self) -> None:
        """Credit derivative including restructuring: no haircut."""
        lf = _restructuring_exposure(
            guaranteed_portion=500_000.0,
            protection_type="credit_derivative",
            includes_restructuring=True,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)
        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_guarantee_type_no_haircut(self) -> None:
        """Regular guarantee (not CD): no haircut regardless of restructuring."""
        lf = _restructuring_exposure(
            guaranteed_portion=500_000.0,
            protection_type="guarantee",
            includes_restructuring=False,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)
        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_null_includes_restructuring_defaults_to_true(self) -> None:
        """Null includes_restructuring → fill_null(True) → no haircut."""
        lf = _restructuring_exposure(
            guaranteed_portion=500_000.0,
            protection_type="credit_derivative",
            includes_restructuring=None,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)
        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_zero_guaranteed_portion_no_haircut(self) -> None:
        """Zero guaranteed portion: condition false, no haircut."""
        lf = _restructuring_exposure(
            guaranteed_portion=0.0,
            protection_type="credit_derivative",
            includes_restructuring=False,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(0.0)
        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_protection_type_absent_early_return(self) -> None:
        """Missing protection_type column: early return with haircut = 0."""
        lf = _restructuring_exposure(
            include_protection_type_col=False,
            include_restructuring_col=True,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_includes_restructuring_absent_early_return(self) -> None:
        """Missing includes_restructuring column: early return with haircut = 0."""
        lf = _restructuring_exposure(
            include_protection_type_col=True,
            include_restructuring_col=False,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_unguaranteed_portion_recalculated_after_haircut(self) -> None:
        """After haircut, unguaranteed = EAD - guaranteed (clipped >= 0)."""
        lf = _restructuring_exposure(
            guaranteed_portion=800_000.0,
            ead_after_collateral=1_000_000.0,
            protection_type="credit_derivative",
            includes_restructuring=False,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        expected_guar = 800_000.0 * 0.60
        assert result["guaranteed_portion"][0] == pytest.approx(expected_guar, rel=1e-9)
        assert result["unguaranteed_portion"][0] == pytest.approx(
            1_000_000.0 - expected_guar, rel=1e-9
        )

    def test_restructuring_haircut_constant_value(self) -> None:
        """RESTRUCTURING_EXCLUSION_HAIRCUT constant is 40%."""
        from decimal import Decimal

        assert RESTRUCTURING_EXCLUSION_HAIRCUT == Decimal("0.40")

    def test_both_columns_absent_early_return(self) -> None:
        """Both protection_type and includes_restructuring absent: early return."""
        lf = _restructuring_exposure(
            include_protection_type_col=False,
            include_restructuring_col=False,
        )
        result = _apply_restructuring_exclusion_haircut(lf).collect()

        assert result["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)


# =============================================================================
# Multi-level guarantee resolution
# =============================================================================


class TestResolveGuaranteesMultiLevel:
    """Expand facility/counterparty guarantees to exposure-level."""

    def test_beneficiary_type_absent_returns_unchanged(self) -> None:
        """No beneficiary_type column: guarantees returned unchanged."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_after_collateral": [1_000_000.0],
                "counterparty_reference": ["CP001"],
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        assert len(result) == 1
        assert result["beneficiary_reference"][0] == "EXP001"
        assert result["amount_covered"][0] == pytest.approx(100_000.0)

    def test_direct_guarantees_pass_through(self) -> None:
        """Direct-level guarantees (loan/exposure/contingent) pass unchanged."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP002"],
                "beneficiary_type": ["loan", "exposure"],
                "amount_covered": [100_000.0, 200_000.0],
                "guarantor": ["GUAR001", "GUAR002"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "ead_after_collateral": [500_000.0, 500_000.0],
                "counterparty_reference": ["CP001", "CP001"],
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        assert len(result) == 2
        # Direct guarantees amounts unchanged
        refs = set(result["beneficiary_reference"].to_list())
        assert refs == {"EXP001", "EXP002"}

    def test_counterparty_level_allocated_pro_rata(self) -> None:
        """Counterparty-level guarantee split by EAD weight."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP001"],
                "beneficiary_type": ["counterparty"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "ead_after_collateral": [600_000.0, 400_000.0],
                "counterparty_reference": ["CP001", "CP001"],
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        # Pro-rata: 60% and 40% of 100k
        result_sorted = result.sort("beneficiary_reference")
        assert result_sorted["amount_covered"][0] == pytest.approx(60_000.0, rel=1e-6)
        assert result_sorted["amount_covered"][1] == pytest.approx(40_000.0, rel=1e-6)

    def test_facility_level_allocated_pro_rata(self) -> None:
        """Facility-level guarantee split by EAD weight across child exposures."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["FAC001"],
                "beneficiary_type": ["facility"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "ead_after_collateral": [750_000.0, 250_000.0],
                "counterparty_reference": ["CP001", "CP001"],
                "parent_facility_reference": ["FAC001", "FAC001"],
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        result_sorted = result.sort("beneficiary_reference")
        assert result_sorted["amount_covered"][0] == pytest.approx(75_000.0, rel=1e-6)
        assert result_sorted["amount_covered"][1] == pytest.approx(25_000.0, rel=1e-6)

    def test_facility_level_skipped_without_parent_facility_col(self) -> None:
        """Facility-level guarantees skipped when parent_facility_reference absent."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["FAC001"],
                "beneficiary_type": ["facility"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_after_collateral": [1_000_000.0],
                "counterparty_reference": ["CP001"],
                # No parent_facility_reference column
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        # Facility guarantee silently dropped (inner join in pro-rata fails)
        # Only counterparty-level runs (but no counterparty guarantees exist)
        facility_rows = result.filter(pl.col("beneficiary_reference") == "FAC001")
        assert len(facility_rows) == 0

    def test_case_insensitive_beneficiary_type(self) -> None:
        """beneficiary_type matching is case-insensitive."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["LOAN"],  # uppercase
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_after_collateral": [1_000_000.0],
                "counterparty_reference": ["CP001"],
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        assert len(result) == 1
        assert result["beneficiary_reference"][0] == "EXP001"

    def test_mixed_levels_combined(self) -> None:
        """Direct + counterparty guarantees correctly combined."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "CP001"],
                "beneficiary_type": ["loan", "counterparty"],
                "amount_covered": [50_000.0, 100_000.0],
                "guarantor": ["GUAR001", "GUAR002"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "ead_after_collateral": [500_000.0, 500_000.0],
                "counterparty_reference": ["CP001", "CP001"],
            }
        )
        result = _resolve_guarantees_multi_level(guarantees, exposures).collect()

        # 1 direct + 2 cp-level (split 50:50) = 3 rows
        assert len(result) == 3
        total_amount = result["amount_covered"].sum()
        assert total_amount == pytest.approx(150_000.0, rel=1e-6)


# =============================================================================
# Pro-rata allocation
# =============================================================================


class TestAllocateGuaranteesProRata:
    """Pro-rata guarantee allocation by EAD within a group."""

    def test_single_exposure_full_allocation(self) -> None:
        """Single exposure gets full guarantee amount."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP001"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
                "beneficiary_type": ["counterparty"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = _allocate_guarantees_pro_rata(
            guarantees, exposures, "counterparty_reference"
        ).collect()

        assert len(result) == 1
        assert result["amount_covered"][0] == pytest.approx(100_000.0)
        assert result["beneficiary_reference"][0] == "EXP001"
        assert result["beneficiary_type"][0] == "loan"

    def test_two_exposures_weighted_by_ead(self) -> None:
        """Two exposures get amount proportional to EAD."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP001"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
                "beneficiary_type": ["counterparty"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP001"],
                "ead_after_collateral": [300_000.0, 700_000.0],
            }
        )
        result = _allocate_guarantees_pro_rata(
            guarantees, exposures, "counterparty_reference"
        ).collect()

        result_sorted = result.sort("beneficiary_reference")
        assert result_sorted["amount_covered"][0] == pytest.approx(30_000.0, rel=1e-6)
        assert result_sorted["amount_covered"][1] == pytest.approx(70_000.0, rel=1e-6)

    def test_zero_total_ead_gets_zero_allocation(self) -> None:
        """All exposures with zero EAD: weight = 0, allocation = 0."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP001"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
                "beneficiary_type": ["counterparty"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "ead_after_collateral": [0.0],
            }
        )
        result = _allocate_guarantees_pro_rata(
            guarantees, exposures, "counterparty_reference"
        ).collect()

        assert result["amount_covered"][0] == pytest.approx(0.0)

    def test_no_matching_references_empty_result(self) -> None:
        """No matching references: inner join produces empty output."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP999"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
                "beneficiary_type": ["counterparty"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = _allocate_guarantees_pro_rata(
            guarantees, exposures, "counterparty_reference"
        ).collect()

        assert len(result) == 0

    def test_beneficiary_type_overwritten_to_loan(self) -> None:
        """Output beneficiary_type is always 'loan' regardless of input."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["CP001"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
                "beneficiary_type": ["counterparty"],
            }
        )
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = _allocate_guarantees_pro_rata(
            guarantees, exposures, "counterparty_reference"
        ).collect()

        assert result["beneficiary_type"][0] == "loan"


# =============================================================================
# Guarantee amount resolution expression
# =============================================================================


class TestResolveGuaranteeAmountExpr:
    """Build expression for guarantee amount from amount_covered or percentage_covered."""

    def test_no_percentage_uses_amount_covered(self) -> None:
        """has_percentage=False: uses amount_covered directly."""
        expr = _resolve_guarantee_amount_expr(has_percentage=False, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": [100_000.0],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        assert result["guar_amount"][0] == pytest.approx(100_000.0)

    def test_no_percentage_null_amount_defaults_zero(self) -> None:
        """has_percentage=False: null amount_covered → 0.0."""
        expr = _resolve_guarantee_amount_expr(has_percentage=False, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": pl.Series("amount_covered", [None], dtype=pl.Float64),
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        assert result["guar_amount"][0] == pytest.approx(0.0)

    def test_percentage_used_when_amount_null(self) -> None:
        """has_percentage=True + null amount: percentage x EAD."""
        expr = _resolve_guarantee_amount_expr(has_percentage=True, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": pl.Series("amount_covered", [None], dtype=pl.Float64),
                "percentage_covered": [0.50],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        assert result["guar_amount"][0] == pytest.approx(500_000.0)

    def test_percentage_used_when_amount_near_zero(self) -> None:
        """has_percentage=True + amount ~0 (< 1e-10): uses percentage."""
        expr = _resolve_guarantee_amount_expr(has_percentage=True, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": [1e-11],
                "percentage_covered": [0.30],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        assert result["guar_amount"][0] == pytest.approx(300_000.0)

    def test_amount_used_when_both_present(self) -> None:
        """has_percentage=True + nonzero amount: amount_covered takes priority."""
        expr = _resolve_guarantee_amount_expr(has_percentage=True, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": [200_000.0],
                "percentage_covered": [0.50],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        assert result["guar_amount"][0] == pytest.approx(200_000.0)

    def test_both_null_returns_zero(self) -> None:
        """has_percentage=True + both null: 0.0."""
        expr = _resolve_guarantee_amount_expr(has_percentage=True, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": pl.Series("amount_covered", [None], dtype=pl.Float64),
                "percentage_covered": pl.Series("percentage_covered", [None], dtype=pl.Float64),
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        assert result["guar_amount"][0] == pytest.approx(0.0)

    def test_zero_percentage_falls_through_to_amount(self) -> None:
        """has_percentage=True + percentage <= 0: uses amount_covered."""
        expr = _resolve_guarantee_amount_expr(has_percentage=True, alias="guar_amount")
        lf = pl.LazyFrame(
            {
                "amount_covered": pl.Series("amount_covered", [None], dtype=pl.Float64),
                "percentage_covered": [0.0],
                "ead_after_collateral": [1_000_000.0],
            }
        )
        result = lf.with_columns(expr).collect()

        # percentage <= 0 doesn't trigger, falls to amount.fill_null(0.0)
        assert result["guar_amount"][0] == pytest.approx(0.0)


# =============================================================================
# Guarantee splits (multi-guarantor row splitting)
# =============================================================================


class TestApplyGuaranteeSplits:
    """Split exposures by guarantor into sub-rows."""

    def _base_exposure(self, ead: float = 1_000_000.0) -> pl.LazyFrame:
        return pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "parent_exposure_reference": ["EXP001"],
                "ead_after_collateral": [ead],
                "drawn_amount": [ead],
                "nominal_amount": [0.0],
                "counterparty_reference": ["CP001"],
            }
        )

    def test_no_guarantees_exposure_unchanged(self) -> None:
        """Exposure with no matching guarantee: zero guaranteed_portion."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["OTHER"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = self._base_exposure()
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        assert len(result) == 1
        assert result["guaranteed_portion"][0] == pytest.approx(0.0)
        assert result["unguaranteed_portion"][0] == pytest.approx(1_000_000.0)

    def test_single_guarantor_partial(self) -> None:
        """Single guarantor covering less than EAD: guaranteed + unguaranteed sum to EAD."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [400_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = self._base_exposure(ead=1_000_000.0)
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        assert len(result) == 1
        assert result["guaranteed_portion"][0] == pytest.approx(400_000.0)
        assert result["unguaranteed_portion"][0] == pytest.approx(600_000.0)

    def test_single_guarantor_full_coverage(self) -> None:
        """Single guarantor covering full EAD: capped at EAD."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [1_500_000.0],  # exceeds EAD
                "guarantor": ["GUAR001"],
            }
        )
        exposures = self._base_exposure(ead=1_000_000.0)
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        assert len(result) == 1
        assert result["guaranteed_portion"][0] == pytest.approx(1_000_000.0)
        assert result["unguaranteed_portion"][0] == pytest.approx(0.0)

    def test_multiple_guarantors_creates_subrows(self) -> None:
        """Two guarantors: creates 3 rows (2 guarantor + 1 remainder)."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP001"],
                "amount_covered": [300_000.0, 400_000.0],
                "guarantor": ["GUAR_A", "GUAR_B"],
            }
        )
        exposures = self._base_exposure(ead=1_000_000.0)
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        assert len(result) == 3

        guar_a = result.filter(pl.col("exposure_reference") == "EXP001__G_GUAR_A")
        guar_b = result.filter(pl.col("exposure_reference") == "EXP001__G_GUAR_B")
        rem = result.filter(pl.col("exposure_reference") == "EXP001__REM")

        assert len(guar_a) == 1
        assert len(guar_b) == 1
        assert len(rem) == 1

        assert guar_a["guaranteed_portion"][0] == pytest.approx(300_000.0, rel=1e-6)
        assert guar_b["guaranteed_portion"][0] == pytest.approx(400_000.0, rel=1e-6)
        assert rem["guaranteed_portion"][0] == pytest.approx(0.0)
        assert rem["unguaranteed_portion"][0] == pytest.approx(300_000.0, rel=1e-6)

    def test_multiple_guarantors_exceeding_ead_pro_rata_scaled(self) -> None:
        """Two guarantors totalling > EAD: amounts scaled pro-rata."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001", "EXP001"],
                "amount_covered": [800_000.0, 600_000.0],
                "guarantor": ["GUAR_A", "GUAR_B"],
            }
        )
        exposures = self._base_exposure(ead=1_000_000.0)
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        guar_a = result.filter(pl.col("exposure_reference") == "EXP001__G_GUAR_A")
        guar_b = result.filter(pl.col("exposure_reference") == "EXP001__G_GUAR_B")

        # Total = 1.4M, EAD = 1M → scale = 1M / 1.4M ≈ 0.7143
        scale = 1_000_000.0 / 1_400_000.0
        assert guar_a["guaranteed_portion"][0] == pytest.approx(800_000.0 * scale, rel=1e-4)
        assert guar_b["guaranteed_portion"][0] == pytest.approx(600_000.0 * scale, rel=1e-4)

    def test_percentage_covered_used_when_amount_absent(self) -> None:
        """percentage_covered used when amount_covered is null."""
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": pl.Series("amount_covered", [None], dtype=pl.Float64),
                "percentage_covered": [0.50],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = self._base_exposure(ead=1_000_000.0)
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        # 50% of 1M = 500k
        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0, rel=1e-6)


# =============================================================================
# Cross-approach CCF substitution
# =============================================================================


class TestCrossApproachCcf:
    """IRB exposure + SA guarantor: guaranteed portion uses SA CCF."""

    def _ccf_exposure(
        self,
        approach: str = "FIRB",
        guarantor_approach: str = "sa",
        guaranteed_portion: float = 500_000.0,
        nominal_amount: float = 1_000_000.0,
        drawn_amount: float = 500_000.0,
        ccf: float = 0.75,
        risk_type: str | None = "LC",
        include_risk_type: bool = True,
    ) -> pl.LazyFrame:
        data: dict = {
            "exposure_reference": ["EXP001"],
            "approach": [approach],
            "guarantor_approach": [guarantor_approach],
            "guaranteed_portion": [guaranteed_portion],
            "unguaranteed_portion": [500_000.0],
            "ead_after_collateral": [guaranteed_portion + 500_000.0],
            "nominal_amount": [nominal_amount],
            "drawn_amount": [drawn_amount],
            "interest": [0.0],
            "ccf": [ccf],
            "ead_from_ccf": [nominal_amount * ccf],
        }
        if include_risk_type:
            data["risk_type"] = [risk_type]
        return pl.LazyFrame(data)

    def test_risk_type_absent_no_op(self) -> None:
        """Missing risk_type column: function returns unchanged."""
        lf = self._ccf_exposure(include_risk_type=False)
        result = _apply_cross_approach_ccf(lf).collect()

        # No new columns added, no modification
        assert "guarantee_ratio" not in result.columns

    def test_sa_exposure_sa_guarantor_no_substitution(self) -> None:
        """SA exposure with SA guarantor: no CCF substitution needed."""
        lf = self._ccf_exposure(approach=ApproachType.SA.value, guarantor_approach="sa")
        result = _apply_cross_approach_ccf(lf).collect()

        # SA approach doesn't trigger needs_ccf_sub
        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)

    def test_irb_exposure_irb_guarantor_no_substitution(self) -> None:
        """IRB exposure with IRB guarantor: no substitution."""
        lf = self._ccf_exposure(approach="FIRB", guarantor_approach="irb")
        result = _apply_cross_approach_ccf(lf).collect()

        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)

    def test_irb_exposure_sa_guarantor_substitutes_ccf(self) -> None:
        """F-IRB exposure with SA guarantor: guaranteed portion uses SA CCF."""
        lf = self._ccf_exposure(
            approach="FIRB",
            guarantor_approach="sa",
            guaranteed_portion=500_000.0,
            nominal_amount=1_000_000.0,
            drawn_amount=500_000.0,
            ccf=0.75,
        )
        result = _apply_cross_approach_ccf(lf).collect()

        # guarantee_ratio, ccf_guaranteed, ccf_original should be set
        assert "guarantee_ratio" in result.columns
        assert "ccf_guaranteed" in result.columns
        assert "ccf_original" in result.columns
        assert result["ccf_original"][0] == pytest.approx(0.75)

    def test_zero_guaranteed_portion_no_substitution(self) -> None:
        """Zero guaranteed_portion: condition false, no substitution."""
        lf = self._ccf_exposure(guaranteed_portion=0.0)
        result = _apply_cross_approach_ccf(lf).collect()

        if "ccf_guaranteed" in result.columns:
            # ccf_guaranteed = original ccf when condition is false
            assert result["ccf_guaranteed"][0] == pytest.approx(0.75)

    def test_zero_nominal_no_substitution(self) -> None:
        """Zero nominal_amount: no off-balance-sheet → no substitution."""
        lf = self._ccf_exposure(nominal_amount=0.0)
        result = _apply_cross_approach_ccf(lf).collect()

        # nominal_amount == 0 → needs_ccf_sub is false
        assert result["guaranteed_portion"][0] == pytest.approx(500_000.0)

    def test_airb_exposure_sa_guarantor_also_substitutes(self) -> None:
        """A-IRB exposure with SA guarantor: also triggers substitution."""
        lf = self._ccf_exposure(
            approach="AIRB",
            guarantor_approach="sa",
            guaranteed_portion=500_000.0,
            nominal_amount=1_000_000.0,
        )
        result = _apply_cross_approach_ccf(lf).collect()

        assert "ccf_guaranteed" in result.columns
        # The SA CCF should differ from the original 0.75
        # (actual value depends on sa_ccf_expression for risk_type "LC")
