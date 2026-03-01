"""
Unit tests for Expected Loss adjustment under guarantee substitution.

Per CRR Art. 158-159, Expected Loss is an IRB-only concept. When an IRB exposure
is guaranteed by an SA counterparty, the SA-guaranteed portion should have zero EL
(SA has no EL concept). Only the unguaranteed portion retains IRB EL.

For IRB guarantors, EL remains unchanged (PD substitution not yet implemented).
"""

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Create CRR configuration for tests."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestELGuaranteeAdjustment:
    """Tests for EL adjustment when guarantee substitution is applied."""

    def test_full_sa_guarantee_beneficial_el_is_zero(self, crr_config: CalculationConfig) -> None:
        """Full SA guarantee (beneficial) should reduce EL to 0."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "expected_loss": [4_500.0],  # PD * LGD * EAD = 0.01 * 0.45 * 1M
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["sa"],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert result["expected_loss_irb_original"][0] == pytest.approx(4_500.0)
        assert result["expected_loss"][0] == pytest.approx(0.0)

    def test_partial_sa_guarantee_beneficial_el_prorated(
        self, crr_config: CalculationConfig
    ) -> None:
        """Partial SA guarantee (60%, beneficial) should pro-rate EL to unguaranteed portion."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "expected_loss": [4_500.0],
                "guaranteed_portion": [600_000.0],  # 60% guaranteed
                "unguaranteed_portion": [400_000.0],  # 40% unguaranteed
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["sa"],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert result["expected_loss_irb_original"][0] == pytest.approx(4_500.0)
        # EL should be 40% of original: 4500 * 0.4 = 1800
        assert result["expected_loss"][0] == pytest.approx(1_800.0)

    def test_no_guarantee_el_unchanged(self, crr_config: CalculationConfig) -> None:
        """No guarantee should leave EL unchanged."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "expected_loss": [4_500.0],
                "guaranteed_portion": [0.0],
                "unguaranteed_portion": [1_000_000.0],
                "guarantor_entity_type": [None],
                "guarantor_cqs": [None],
                "guarantor_approach": [""],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert result["expected_loss_irb_original"][0] == pytest.approx(4_500.0)
        assert result["expected_loss"][0] == pytest.approx(4_500.0)

    def test_non_beneficial_guarantee_el_unchanged(self, crr_config: CalculationConfig) -> None:
        """Non-beneficial guarantee should leave EL unchanged."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.001],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [100_000.0],  # 10% RW
                "risk_weight": [0.10],
                "expected_loss": [450.0],
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["institution"],
                "guarantor_cqs": [2],  # UK: 30% RW > borrower 10%
                "guarantor_approach": ["sa"],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert result["is_guarantee_beneficial"][0] is False
        assert result["expected_loss"][0] == pytest.approx(450.0)

    def test_irb_guarantor_el_unchanged(self, crr_config: CalculationConfig) -> None:
        """IRB guarantor should leave EL unchanged (PD substitution not implemented)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "expected_loss": [4_500.0],
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["irb"],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # IRB guarantor: EL not adjusted (PD substitution not yet implemented)
        assert result["expected_loss"][0] == pytest.approx(4_500.0)

    def test_no_expected_loss_column_backward_compat(self, crr_config: CalculationConfig) -> None:
        """Method should still work when expected_loss column is absent."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["sa"],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # Should not fail; no expected_loss columns created
        assert "expected_loss" not in result.columns
        assert "expected_loss_irb_original" not in result.columns
        # RWA substitution should still work
        assert result["rwa"][0] == pytest.approx(0.0)

    def test_select_expected_loss_returns_adjusted_value(
        self, crr_config: CalculationConfig
    ) -> None:
        """select_expected_loss() should return the guarantee-adjusted EL value."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "approach": ["foundation_irb"],
            }
        )

        # Run full pipeline then guarantee substitution
        result_pre = (
            lf.irb.apply_firb_lgd(crr_config)
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
        )

        # Get original EL
        original_el = result_pre.collect()["expected_loss"][0]
        assert original_el > 0  # Sanity check

        # Now add guarantee columns and apply substitution
        result_with_guarantee = result_pre.with_columns(
            [
                pl.lit(1_000_000.0).alias("guaranteed_portion"),
                pl.lit(0.0).alias("unguaranteed_portion"),
                pl.lit("sovereign").alias("guarantor_entity_type"),
                pl.lit(1).cast(pl.Int64).alias("guarantor_cqs"),
                pl.lit("sa").alias("guarantor_approach"),
            ]
        ).irb.apply_guarantee_substitution(crr_config)

        el_result = result_with_guarantee.irb.select_expected_loss().collect()
        assert el_result["expected_loss"][0] == pytest.approx(0.0)
