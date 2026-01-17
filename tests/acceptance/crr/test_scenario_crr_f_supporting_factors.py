"""
CRR Group F: Supporting Factors Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
the CRR-specific supporting factors.

Tests are skipped until the production calculator is implemented in src/rwa_calc/.

Key Features:
- SME supporting factor uses TIERED approach (CRR2 Art. 501):
  - Exposures up to €2.5m (£2.2m): factor of 0.7619 (23.81% reduction)
  - Exposures above €2.5m (£2.2m): factor of 0.85 (15% reduction)
- Infrastructure supporting factor: 0.75 (flat, not tiered)

These factors are NOT available under Basel 3.1.

Regulatory References:
- CRR2 Art. 501: SME supporting factor (tiered)
- CRR Art. 501a: Infrastructure supporting factor
"""

import pytest
from decimal import Decimal
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_supporting_factor_match,
)


# Marker for tests awaiting production implementation
SKIP_REASON = "Production calculator not yet implemented (Phase 3)"


class TestCRRGroupF_TieredSMEFactor:
    """
    CRR Tiered SME Supporting Factor acceptance tests.

    The SME factor is calculated as:
        factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E

    Where threshold = £2.2m (€2.5m)
    """

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f1_sme_tier1_only_small_exposure(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F1: Small SME exposure (£2m) gets Tier 1 factor only.

        Input: £2m exposure (< £2.2m threshold)
        Expected: Factor = 0.7619 (pure Tier 1)

        Hand calculation:
        - EAD: £2,000,000
        - Factor: 0.7619 (exposure ≤ threshold, 100% Tier 1)
        - RWA after: £2,000,000 × 1.0 × 0.7619 = £1,523,800
        """
        expected = expected_outputs_dict["CRR-F1"]

        # Verify Tier 1 only factor
        # assert result.supporting_factor == pytest.approx(0.7619, rel=0.0001)

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f2_sme_blended_medium_exposure(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F2: Medium SME exposure (£4m) gets blended factor.

        Input: £4m exposure (above £2.2m threshold)
        Expected: Blended factor between 0.7619 and 0.85

        Hand calculation:
        - Tier 1: £2.2m × 0.7619 = £1,676,180
        - Tier 2: £1.8m × 0.85 = £1,530,000
        - Total weighted: £3,206,180
        - Effective factor: £3,206,180 / £4,000,000 = 0.8015
        """
        expected = expected_outputs_dict["CRR-F2"]

        # Verify blended factor
        # assert result.supporting_factor == pytest.approx(0.8015, rel=0.001)

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f3_sme_tier2_dominant_large_exposure(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F3: Large SME exposure (£10m) - Tier 2 dominates.

        Input: £10m exposure (well above threshold)
        Expected: Factor approaching 0.85 as Tier 2 dominates

        Hand calculation:
        - Tier 1: £2.2m × 0.7619 = £1,676,180 (22%)
        - Tier 2: £7.8m × 0.85 = £6,630,000 (78%)
        - Total: £8,306,180
        - Effective factor: 0.8306
        """
        expected = expected_outputs_dict["CRR-F3"]

        # Verify Tier 2 dominant factor
        # assert 0.83 < result.supporting_factor < 0.85

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f4_sme_retail_with_tiered_factor(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F4: SME retail with tiered factor.

        Input: £500k retail SME exposure
        Expected: 75% RW + Tier 1 SME factor (0.7619)

        Effective RW = 75% × 0.7619 = 57.14%
        """
        expected = expected_outputs_dict["CRR-F4"]

        # Verify retail + SME factor combination
        # assert result.risk_weight == 0.75
        # assert result.supporting_factor == pytest.approx(0.7619, rel=0.0001)

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f5_infrastructure_factor_not_tiered(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F5: Infrastructure factor is NOT tiered.

        Input: £50m infrastructure exposure
        Expected: Flat 0.75 factor regardless of exposure size

        Note: Infrastructure factor is not tiered like SME factor
        """
        expected = expected_outputs_dict["CRR-F5"]

        # Verify flat infrastructure factor
        # assert result.supporting_factor == 0.75

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f6_large_corporate_no_factor(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F6: Large corporate (turnover > £44m) gets no SME factor.

        Input: £20m exposure, turnover £200m
        Expected: No SME factor (turnover exceeds eligibility threshold)
        """
        expected = expected_outputs_dict["CRR-F6"]

        # Verify no factor applied
        # assert result.supporting_factor == 1.0

    @pytest.mark.skip(reason=SKIP_REASON)
    def test_crr_f7_at_exposure_threshold_boundary(
        self,
        load_test_fixtures,
        expected_outputs_dict: dict[str, dict[str, Any]],
        crr_config: dict[str, Any],
    ) -> None:
        """
        CRR-F7: Exposure exactly at £2.2m threshold.

        Input: £2.2m exposure (exactly at threshold)
        Expected: Factor = 0.7619 (Tier 1 includes threshold)
        """
        expected = expected_outputs_dict["CRR-F7"]

        # Verify at-threshold factor
        # assert result.supporting_factor == pytest.approx(0.7619, rel=0.0001)


class TestCRRGroupF_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_f_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-F scenarios exist in expected outputs."""
        expected_ids = [f"CRR-F{i}" for i in range(1, 8)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_crr_f_sme_factors_in_valid_range(
        self,
        crr_f_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify SME factors are in valid range [0.7619, 1.0].

        Note: CRR-F5 is an infrastructure scenario with factor 0.75, not SME.
        """
        for scenario in crr_f_scenarios:
            sf = scenario["supporting_factor"]
            scenario_id = scenario["scenario_id"]

            # Infrastructure scenarios have factor 0.75 (not SME)
            if scenario_id == "CRR-F5":
                assert sf == pytest.approx(0.75, rel=0.001), (
                    f"Scenario {scenario_id} should have infrastructure factor 0.75, got {sf}"
                )
            else:
                assert 0.7619 <= sf <= 1.0, (
                    f"Scenario {scenario_id} has invalid supporting factor: {sf}"
                )

    def test_crr_f1_has_tier1_only_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F1 (small exposure) has Tier 1 factor."""
        scenario = expected_outputs_dict["CRR-F1"]
        assert scenario["supporting_factor"] == pytest.approx(0.7619, rel=0.001), (
            "CRR-F1 should have Tier 1 factor 0.7619"
        )

    def test_crr_f2_has_blended_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F2 (medium exposure) has blended factor."""
        scenario = expected_outputs_dict["CRR-F2"]
        sf = scenario["supporting_factor"]
        # Blended factor should be between 0.7619 and 0.85
        assert 0.7619 < sf < 0.85, (
            f"CRR-F2 should have blended factor between 0.7619 and 0.85, got {sf}"
        )

    def test_crr_f3_has_tier2_dominant_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F3 (large exposure) has Tier 2 dominant factor."""
        scenario = expected_outputs_dict["CRR-F3"]
        sf = scenario["supporting_factor"]
        # Large exposure factor should be closer to 0.85
        assert sf > 0.80, (
            f"CRR-F3 should have Tier 2 dominant factor > 0.80, got {sf}"
        )

    def test_crr_f5_has_infrastructure_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F5 has flat infrastructure factor."""
        scenario = expected_outputs_dict["CRR-F5"]
        assert scenario["supporting_factor"] == pytest.approx(0.75, rel=0.001), (
            "CRR-F5 should have infrastructure factor 0.75"
        )

    def test_crr_f6_has_no_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F6 (large corporate) has no supporting factor."""
        scenario = expected_outputs_dict["CRR-F6"]
        assert scenario["supporting_factor"] == pytest.approx(1.0), (
            "CRR-F6 should have no supporting factor (1.0)"
        )

    def test_tiered_factor_calculation_formula(
        self,
        crr_config: dict[str, Any],
    ) -> None:
        """Verify tiered factor calculation matches expected formula."""
        from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
            calculate_sme_supporting_factor,
        )

        # Test various exposure amounts
        test_cases = [
            # (exposure_gbp, expected_factor)
            (Decimal("1000000"), Decimal("0.7619")),      # £1m - Tier 1 only
            (Decimal("2200000"), Decimal("0.7619")),      # £2.2m - at threshold
            (Decimal("4000000"), None),                    # £4m - blended (calculate)
            (Decimal("10000000"), None),                   # £10m - Tier 2 dominant
        ]

        for exposure, expected in test_cases:
            factor = calculate_sme_supporting_factor(exposure, "GBP")
            factor_float = float(factor)
            if expected is not None:
                assert factor_float == pytest.approx(float(expected), rel=0.001), (
                    f"Factor for £{exposure:,} should be {expected}, got {factor_float}"
                )
            else:
                # Just verify it's in valid range
                assert 0.7619 <= factor_float <= 0.85, (
                    f"Factor for £{exposure:,} should be between 0.7619 and 0.85"
                )
