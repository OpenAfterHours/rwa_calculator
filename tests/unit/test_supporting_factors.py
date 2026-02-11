"""
Unit tests for Buy-to-Let (BTL) flag in supporting factors.

BTL exposures must NOT receive the SME supporting factor discount,
but they still contribute to total counterparty EAD for the tiered
threshold calculation. This ensures non-BTL exposures to the same
counterparty get the correct blended factor.
"""

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator


@pytest.fixture()
def calculator() -> SupportingFactorCalculator:
    return SupportingFactorCalculator()


@pytest.fixture()
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2025, 12, 31))


def _make_exposures(
    rows: list[dict],
    include_btl: bool = True,
) -> pl.LazyFrame:
    """Build a LazyFrame of exposures for supporting factor tests."""
    data = {
        "exposure_reference": [r["ref"] for r in rows],
        "counterparty_reference": [r["cp"] for r in rows],
        "ead_final": [r["ead"] for r in rows],
        "rwa_pre_factor": [r["rwa"] for r in rows],
        "is_sme": [r.get("is_sme", True) for r in rows],
        "is_infrastructure": [r.get("is_infra", False) for r in rows],
    }
    if include_btl:
        data["is_buy_to_let"] = [r.get("is_btl", False) for r in rows]
    return pl.LazyFrame(data)


class TestBTLExcludedFromSMEFactor:
    """BTL exposures get supporting_factor=1.0 but still count toward total_cp_ead."""

    def test_btl_excluded_non_btl_gets_blended(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """
        CP with 1.5m non-BTL + 1.0m BTL:
        - total_cp_ead = 2.5m (includes BTL)
        - Non-BTL gets the tiered blended factor (all within tier 1 threshold)
        - BTL gets 1.0
        """
        threshold_gbp = float(
            crr_config.supporting_factors.sme_exposure_threshold_eur
            * crr_config.eur_gbp_rate
        )
        exposures = _make_exposures([
            {"ref": "E1", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000, "is_btl": False},
            {"ref": "E2", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": True},
        ])

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Both exposures should see total_cp_ead = 2.5m (BTL included)
        assert result.filter(pl.col("exposure_reference") == "E1")["total_cp_ead"][0] == 2_500_000
        assert result.filter(pl.col("exposure_reference") == "E2")["total_cp_ead"][0] == 2_500_000

        # Non-BTL (E1) gets the SME factor < 1.0
        sf_e1 = result.filter(pl.col("exposure_reference") == "E1")["supporting_factor"][0]
        assert sf_e1 < 1.0, "Non-BTL exposure should get SME factor"

        # BTL (E2) gets factor = 1.0
        sf_e2 = result.filter(pl.col("exposure_reference") == "E2")["supporting_factor"][0]
        assert sf_e2 == pytest.approx(1.0), "BTL exposure should get factor 1.0"

        # Non-BTL RWA should be reduced
        rwa_e1 = result.filter(pl.col("exposure_reference") == "E1")["rwa_post_factor"][0]
        assert rwa_e1 < 600_000

        # BTL RWA should be unchanged
        rwa_e2 = result.filter(pl.col("exposure_reference") == "E2")["rwa_post_factor"][0]
        assert rwa_e2 == pytest.approx(400_000)

    def test_btl_contributes_to_total_cp_ead(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """total_cp_ead = 3.0m (includes 2.0m BTL)."""
        exposures = _make_exposures([
            {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": False},
            {"ref": "E2", "cp": "CP1", "ead": 2_000_000, "rwa": 800_000, "is_btl": True},
        ])

        result = calculator.apply_factors(exposures, crr_config).collect()

        # total_cp_ead should include BTL
        total_cp = result["total_cp_ead"][0]
        assert total_cp == pytest.approx(3_000_000)

    def test_all_btl_no_factor(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """CP with only BTL exposures: all get 1.0."""
        exposures = _make_exposures([
            {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": True},
            {"ref": "E2", "cp": "CP1", "ead": 500_000, "rwa": 200_000, "is_btl": True},
        ])

        result = calculator.apply_factors(exposures, crr_config).collect()

        assert result["supporting_factor"].to_list() == pytest.approx([1.0, 1.0])
        assert result["rwa_post_factor"].to_list() == pytest.approx([400_000, 200_000])

    def test_missing_column_defaults_false(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """No is_buy_to_let column -> same as all False (backward compat)."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000},
            ],
            include_btl=False,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Should get SME factor applied normally
        sf = result["supporting_factor"][0]
        assert sf < 1.0, "Without BTL column, should behave as all non-BTL"

    def test_btl_false_normal_factor(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """Explicit is_buy_to_let=False behaves same as column missing."""
        exposures = _make_exposures([
            {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": False},
        ])

        result = calculator.apply_factors(exposures, crr_config).collect()

        sf = result["supporting_factor"][0]
        assert sf < 1.0, "Non-BTL should get SME factor"

    def test_non_sme_with_btl_unaffected(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """Non-SME CP: BTL flag irrelevant, factor always 1.0."""
        exposures = _make_exposures([
            {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_sme": False, "is_btl": True},
            {"ref": "E2", "cp": "CP1", "ead": 500_000, "rwa": 200_000, "is_sme": False, "is_btl": False},
        ])

        result = calculator.apply_factors(exposures, crr_config).collect()

        assert result["supporting_factor"].to_list() == pytest.approx([1.0, 1.0])

    def test_btl_with_infrastructure(
        self, calculator: SupportingFactorCalculator, crr_config: CalculationConfig,
    ) -> None:
        """BTL excludes SME factor but infrastructure factor still applies."""
        exposures = _make_exposures([
            {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000,
             "is_btl": True, "is_infra": True},
        ])

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Infrastructure factor should apply (0.75) even though BTL
        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(0.75), "Infrastructure factor should still apply to BTL"
        assert result["rwa_post_factor"][0] == pytest.approx(300_000)
