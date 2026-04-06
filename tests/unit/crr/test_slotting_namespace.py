"""Unit tests for the Slotting Polars namespace.

Tests cover:
- Namespace registration and availability
- Column preparation
- CRR slotting weights (non-HVCRE and HVCRE, maturity-based)
- Basel 3.1 slotting weights (non-HVCRE, HVCRE, PF pre-operational)
- RWA calculation
- Full pipeline (apply_all)
- Method chaining
- Expression namespace methods

References:
- CRR Art. 153(5): Supervisory slotting approach (Tables 1 & 2)
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.slotting.namespace  # noqa: F401
from rwa_calc.contracts.config import CalculationConfig

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def basic_slotting_exposures() -> pl.LazyFrame:
    """Return basic slotting exposures with various categories."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SL001", "SL002", "SL003", "SL004", "SL005"],
            "ead_final": [1_000_000.0, 500_000.0, 250_000.0, 100_000.0, 50_000.0],
            "slotting_category": ["strong", "good", "satisfactory", "weak", "default"],
            "is_hvcre": [False, False, False, False, False],
            "sl_type": ["project_finance", "object_finance", "commodities_finance", "ipre", "ipre"],
        }
    )


@pytest.fixture
def hvcre_exposures() -> pl.LazyFrame:
    """Return HVCRE exposures."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["HVCRE001", "HVCRE002", "HVCRE003"],
            "ead_final": [1_000_000.0, 500_000.0, 250_000.0],
            "slotting_category": ["strong", "good", "satisfactory"],
            "is_hvcre": [True, True, True],
            "sl_type": ["hvcre", "hvcre", "hvcre"],
        }
    )


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestSlottingNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, basic_slotting_exposures: pl.LazyFrame) -> None:
        """LazyFrame should have .slotting namespace available."""
        assert hasattr(basic_slotting_exposures, "slotting")

    def test_expr_namespace_registered(self) -> None:
        """Expression should have .slotting namespace available."""
        expr = pl.col("slotting_category")
        assert hasattr(expr, "slotting")

    def test_namespace_methods_available(self, basic_slotting_exposures: pl.LazyFrame) -> None:
        """Namespace should have expected methods."""
        slotting = basic_slotting_exposures.slotting
        expected_methods = [
            "prepare_columns",
            "apply_slotting_weights",
            "calculate_rwa",
            "apply_all",
            "build_audit",
        ]
        for method in expected_methods:
            assert hasattr(slotting, method), f"Missing method: {method}"


# =============================================================================
# Prepare Columns Tests
# =============================================================================


class TestPrepareColumns:
    """Tests for column preparation."""

    def test_adds_missing_columns(self, crr_config: CalculationConfig) -> None:
        """prepare_columns should add missing columns with defaults."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead": [100_000.0],
            }
        )
        result = lf.slotting.prepare_columns().collect()

        assert "ead_final" in result.columns
        assert "slotting_category" in result.columns
        assert "is_hvcre" in result.columns
        assert "sl_type" in result.columns
        assert "is_short_maturity" in result.columns
        assert "is_pre_operational" in result.columns

    def test_preserves_existing_columns(
        self, basic_slotting_exposures: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """prepare_columns should preserve existing columns."""
        result = basic_slotting_exposures.slotting.prepare_columns().collect()

        assert result["slotting_category"][0] == "strong"
        assert result["is_hvcre"][0] == False  # noqa: E712


# =============================================================================
# Maturity Derivation Tests (CRR Art. 153(5) — <2.5yr vs >=2.5yr)
# =============================================================================


class TestMaturityDerivation:
    """Tests for is_short_maturity derivation from maturity_date."""

    def test_short_maturity_derived_from_date(self, crr_config: CalculationConfig) -> None:
        """Remaining maturity < 2.5yr should set is_short_maturity=True."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": [date(2026, 7, 1)],  # ~0.5yr from 2024-12-31
            }
        )
        result = lf.slotting.prepare_columns(crr_config).collect()

        assert result["is_short_maturity"][0] is True

    def test_long_maturity_derived_from_date(self, crr_config: CalculationConfig) -> None:
        """Remaining maturity >= 2.5yr should set is_short_maturity=False."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": [date(2030, 1, 1)],  # ~5yr from 2024-12-31
            }
        )
        result = lf.slotting.prepare_columns(crr_config).collect()

        assert result["is_short_maturity"][0] is False

    def test_boundary_at_2_5_years_is_not_short(self) -> None:
        """Remaining maturity >= 2.5yr should be classified as not short."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": [date(2028, 7, 2)],  # 2.501yr from 2026-01-01 (>=2.5yr)
            }
        )
        result = lf.slotting.prepare_columns(config).collect()

        assert result["is_short_maturity"][0] is False

    def test_boundary_just_below_2_5_years_is_short(self) -> None:
        """Remaining maturity just below 2.5yr should be classified as short."""
        config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": [date(2028, 7, 1)],  # 2.499yr from 2026-01-01 (<2.5yr)
            }
        )
        result = lf.slotting.prepare_columns(config).collect()

        assert result["is_short_maturity"][0] is True

    def test_null_maturity_date_defaults_to_not_short(self, crr_config: CalculationConfig) -> None:
        """Null maturity_date should conservatively default to is_short_maturity=False."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": pl.Series([None], dtype=pl.Date),
            }
        )
        result = lf.slotting.prepare_columns(crr_config).collect()

        assert result["is_short_maturity"][0] is False

    def test_existing_is_short_maturity_not_overwritten(
        self, crr_config: CalculationConfig
    ) -> None:
        """Pre-existing is_short_maturity column should not be overwritten."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [True],
                "maturity_date": [date(2030, 1, 1)],  # Long maturity
            }
        )
        result = lf.slotting.prepare_columns(crr_config).collect()

        # Should preserve the explicit True, not recalculate from date
        assert result["is_short_maturity"][0] is True

    def test_remaining_maturity_years_column_added(self, crr_config: CalculationConfig) -> None:
        """remaining_maturity_years should be added for audit trail."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": [date(2029, 12, 31)],  # ~5yr from 2024-12-31
            }
        )
        result = lf.slotting.prepare_columns(crr_config).collect()

        assert "remaining_maturity_years" in result.columns
        assert result["remaining_maturity_years"][0] == pytest.approx(5.0, abs=0.01)

    def test_no_config_defaults_to_not_short(self) -> None:
        """Without config, is_short_maturity should default to False."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2026, 6, 1)],
            }
        )
        result = lf.slotting.prepare_columns().collect()

        assert result["is_short_maturity"][0] is False

    def test_short_maturity_gives_reduced_risk_weight(self, crr_config: CalculationConfig) -> None:
        """Strong with <2.5yr maturity should get 50% RW (not 70%)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "maturity_date": [date(2025, 6, 1)],  # Short maturity from 2024-12-31
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .collect()
        )

        assert result["risk_weight"][0] == pytest.approx(0.50)


# =============================================================================
# CRR Slotting Weight Tests — Non-HVCRE >= 2.5yr (default)
# =============================================================================


class TestCRRSlottingWeights:
    """Tests for CRR slotting weights (non-HVCRE, >= 2.5yr maturity)."""

    def test_crr_strong_70_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Strong (>=2.5yr) should get 70% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.70)

    def test_crr_good_90_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Good (>=2.5yr) should get 90% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.90)

    def test_crr_satisfactory_115_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Satisfactory should get 115% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["satisfactory"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.15)

    def test_crr_weak_250_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Weak should get 250% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["weak"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(2.50)

    def test_crr_default_0_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Default should get 0% risk weight (fully provisioned)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["default"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.0)


# =============================================================================
# CRR Slotting Weight Tests — Non-HVCRE < 2.5yr
# =============================================================================


class TestCRRSlottingWeightsShortMaturity:
    """Tests for CRR slotting weights (non-HVCRE, < 2.5yr maturity)."""

    def test_crr_short_strong_50_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Strong (<2.5yr) should get 50% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [True],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.50)

    def test_crr_short_good_70_percent(self, crr_config: CalculationConfig) -> None:
        """CRR Good (<2.5yr) should get 70% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "is_short_maturity": [True],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.70)


# =============================================================================
# CRR Slotting Weight Tests — HVCRE
# =============================================================================


class TestCRRSlottingWeightsHVCRE:
    """Tests for CRR HVCRE slotting weights (different from non-HVCRE)."""

    def test_crr_hvcre_strong_95_percent(self, crr_config: CalculationConfig) -> None:
        """CRR HVCRE Strong (>=2.5yr) should get 95% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.95)

    def test_crr_hvcre_good_120_percent(self, crr_config: CalculationConfig) -> None:
        """CRR HVCRE Good (>=2.5yr) should get 120% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.20)

    def test_crr_hvcre_satisfactory_140_percent(self, crr_config: CalculationConfig) -> None:
        """CRR HVCRE Satisfactory (>=2.5yr) should get 140% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["satisfactory"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.40)

    def test_crr_hvcre_short_strong_70_percent(self, crr_config: CalculationConfig) -> None:
        """CRR HVCRE Strong (<2.5yr) should get 70% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "is_short_maturity": [True],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.70)

    def test_crr_hvcre_short_good_95_percent(self, crr_config: CalculationConfig) -> None:
        """CRR HVCRE Good (<2.5yr) should get 95% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [True],
                "is_short_maturity": [True],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(crr_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.95)


# =============================================================================
# Basel 3.1 Slotting Weight Tests — Non-HVCRE Operational
# =============================================================================


class TestBasel31SlottingWeights:
    """Tests for Basel 3.1 slotting weights (non-HVCRE operational)."""

    def test_basel31_strong_70_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Strong (non-HVCRE operational) should get 70% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.70)

    def test_basel31_good_90_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Good (non-HVCRE operational) should get 90% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.90)

    def test_basel31_satisfactory_115_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Satisfactory (non-HVCRE operational) should get 115% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["satisfactory"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.15)

    def test_basel31_weak_250_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Weak (non-HVCRE operational) should get 250% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["weak"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(2.50)

    def test_basel31_default_0_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Default should get 0% risk weight (EL covered by provisions)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["default"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.0)


# =============================================================================
# Basel 3.1 Slotting Weight Tests — HVCRE
# =============================================================================


class TestBasel31SlottingWeightsHVCRE:
    """Tests for Basel 3.1 HVCRE slotting weights."""

    def test_basel31_hvcre_strong_95_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Strong (HVCRE) should get 95% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.95)

    def test_basel31_hvcre_good_120_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Good (HVCRE) should get 120% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.20)

    def test_basel31_hvcre_satisfactory_140_percent(
        self, basel31_config: CalculationConfig
    ) -> None:
        """Basel 3.1 Satisfactory (HVCRE) should get 140% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["satisfactory"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.40)

    def test_basel31_hvcre_weak_250_percent(self, basel31_config: CalculationConfig) -> None:
        """Basel 3.1 Weak (HVCRE) should get 250% risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["weak"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(2.50)


# =============================================================================
# Basel 3.1 Slotting Weight Tests — PF Pre-Operational
# =============================================================================


class TestBasel31SlottingWeightsPFPreOp:
    """Tests for Basel 3.1 Project Finance pre-operational slotting weights.

    PRA PS1/26 Art. 153(5) Table A does NOT define separate pre-operational
    weights — all PF uses standard slotting weights regardless of operational
    status. BCBS CRE33 had higher pre-op weights (80/100/120/350%) but PRA
    did not adopt this distinction.
    """

    def test_basel31_pf_preop_strong_same_as_standard(
        self, basel31_config: CalculationConfig
    ) -> None:
        """Basel 3.1 PF Pre-Op Strong uses standard 70% RW (no PRA pre-op uplift)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [True],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.70)

    def test_basel31_pf_preop_good_same_as_standard(
        self, basel31_config: CalculationConfig
    ) -> None:
        """Basel 3.1 PF Pre-Op Good uses standard 90% RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [True],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(0.90)

    def test_basel31_pf_preop_satisfactory_same_as_standard(
        self, basel31_config: CalculationConfig
    ) -> None:
        """Basel 3.1 PF Pre-Op Satisfactory uses standard 115% RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["satisfactory"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [True],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(1.15)

    def test_basel31_pf_preop_weak_same_as_standard(
        self, basel31_config: CalculationConfig
    ) -> None:
        """Basel 3.1 PF Pre-Op Weak uses standard 250% RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "slotting_category": ["weak"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [True],
            }
        )
        result = lf.slotting.apply_slotting_weights(basel31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(2.50)


# =============================================================================
# Scaling Factor Tests
# =============================================================================


class TestScalingFactor:
    """Tests for scaling factor configuration."""

    def test_crr_scaling_factor_106(self) -> None:
        """CRR config should have scaling_factor = 1.06."""
        config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
        assert float(config.scaling_factor) == pytest.approx(1.06)

    def test_basel31_scaling_factor_10(self) -> None:
        """Basel 3.1 config should have scaling_factor = 1.0 (removed)."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
        assert float(config.scaling_factor) == pytest.approx(1.0)


# =============================================================================
# RWA Calculation Tests
# =============================================================================


class TestCalculateRWA:
    """Tests for RWA calculation."""

    def test_rwa_formula(self, crr_config: CalculationConfig) -> None:
        """RWA = EAD x RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.70],
            }
        )
        result = lf.slotting.calculate_rwa().collect()
        assert result["rwa"][0] == pytest.approx(700_000.0)

    def test_rwa_all_categories(
        self, basic_slotting_exposures: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """RWA should be calculated for all exposures."""
        result = (
            basic_slotting_exposures.slotting.prepare_columns()
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .collect()
        )

        # All RWAs should be >= 0
        for rwa in result["rwa"]:
            assert rwa >= 0


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestApplyAll:
    """Tests for full slotting pipeline."""

    def test_apply_all_adds_expected_columns(
        self, basic_slotting_exposures: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """apply_all should add all expected columns."""
        result = basic_slotting_exposures.slotting.apply_all(crr_config).collect()

        expected_columns = [
            "slotting_category",
            "is_hvcre",
            "risk_weight",
            "rwa",
            "rwa_final",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_apply_all_preserves_rows(
        self, basic_slotting_exposures: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Number of rows should be preserved."""
        original_count = basic_slotting_exposures.collect().shape[0]
        result = basic_slotting_exposures.slotting.apply_all(crr_config).collect()
        assert result.shape[0] == original_count


# =============================================================================
# Method Chaining Tests
# =============================================================================


class TestMethodChaining:
    """Tests for method chaining."""

    def test_full_pipeline_chain(
        self, basic_slotting_exposures: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """Full pipeline should work with method chaining."""
        result = (
            basic_slotting_exposures.slotting.prepare_columns()
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .collect()
        )

        assert "risk_weight" in result.columns
        assert "rwa" in result.columns


# =============================================================================
# Expression Namespace Tests
# =============================================================================


class TestExprNamespace:
    """Tests for expression namespace methods."""

    def test_lookup_rw_crr(self) -> None:
        """lookup_rw should return correct CRR weights (>=2.5yr default)."""
        df = pl.DataFrame({"category": ["strong", "good", "satisfactory", "weak", "default"]})
        result = df.with_columns(
            pl.col("category").slotting.lookup_rw(is_crr=True).alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.70)  # strong
        assert result["risk_weight"][1] == pytest.approx(0.90)  # good
        assert result["risk_weight"][2] == pytest.approx(1.15)  # satisfactory
        assert result["risk_weight"][3] == pytest.approx(2.50)  # weak
        assert result["risk_weight"][4] == pytest.approx(0.00)  # default

    def test_lookup_rw_crr_hvcre(self) -> None:
        """lookup_rw should return correct CRR HVCRE weights."""
        df = pl.DataFrame({"category": ["strong", "good", "satisfactory"]})
        result = df.with_columns(
            pl.col("category").slotting.lookup_rw(is_crr=True, is_hvcre=True).alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.95)  # strong
        assert result["risk_weight"][1] == pytest.approx(1.20)  # good
        assert result["risk_weight"][2] == pytest.approx(1.40)  # satisfactory

    def test_lookup_rw_basel31_non_hvcre(self) -> None:
        """lookup_rw should return correct Basel 3.1 non-HVCRE weights."""
        df = pl.DataFrame({"category": ["strong", "good", "satisfactory"]})
        result = df.with_columns(
            pl.col("category").slotting.lookup_rw(is_crr=False, is_hvcre=False).alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.70)  # strong
        assert result["risk_weight"][1] == pytest.approx(0.90)  # good
        assert result["risk_weight"][2] == pytest.approx(1.15)  # satisfactory

    def test_lookup_rw_basel31_hvcre(self) -> None:
        """lookup_rw should return correct Basel 3.1 HVCRE weights."""
        df = pl.DataFrame({"category": ["strong", "good", "satisfactory"]})
        result = df.with_columns(
            pl.col("category").slotting.lookup_rw(is_crr=False, is_hvcre=True).alias("risk_weight")
        )

        assert result["risk_weight"][0] == pytest.approx(0.95)  # strong
        assert result["risk_weight"][1] == pytest.approx(1.20)  # good
        assert result["risk_weight"][2] == pytest.approx(1.40)  # satisfactory


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestBuildAudit:
    """Tests for audit trail generation."""

    def test_build_audit_includes_calculation_string(
        self, basic_slotting_exposures: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """build_audit should include slotting_calculation string."""
        result = (
            basic_slotting_exposures.slotting.apply_all(crr_config).slotting.build_audit().collect()
        )

        assert "slotting_calculation" in result.columns
        calc_str = result["slotting_calculation"][0]
        assert "Category=" in calc_str
        assert "RW=" in calc_str
        assert "RWA=" in calc_str
