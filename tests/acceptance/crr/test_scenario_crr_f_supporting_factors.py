"""
CRR Group F: Supporting Factors Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
the CRR-specific supporting factors.

Key Features:
- SME supporting factor uses TIERED approach (CRR2 Art. 501):
  - Exposures up to EUR 2.5m: factor of 0.7619 (23.81% reduction)
  - Exposures above EUR 2.5m: factor of 0.85 (15% reduction)
- Infrastructure supporting factor: 0.75 (flat, not tiered)

These factors are NOT available under Basel 3.1.

Regulatory References:
- CRR2 Art. 501: SME supporting factor (tiered)
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import polars as pl
import pytest
from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_supporting_factor_match,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-F1": "LOAN_SME_TIER1",
    "CRR-F2": "LOAN_SME_TIER_BLEND",
    "CRR-F3": "LOAN_SME_TIER2_DOM",
    "CRR-F4": "LOAN_RTL_SME_TIER1",
    "CRR-F5": "LOAN_INFRA_001",
    "CRR-F6": "LOAN_CORP_LARGE",
    "CRR-F7": "LOAN_SME_BOUNDARY",
    "CRR-F8": "LOAN_SME_LG_001",
}


class TestCRRGroupF_TieredSMEFactor:
    """
    CRR Tiered SME Supporting Factor acceptance tests.

    The SME factor is calculated as:
        factor = [min(E, threshold) * 0.7619 + max(E - threshold, 0) * 0.85] / E

    Where threshold = EUR 2.5m
    """

    def test_crr_f1_sme_tier1_only_small_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F1: Small SME exposure gets Tier 1 factor only.

        Input: Small exposure (< threshold)
        Expected: Factor = 0.7619 (pure Tier 1)
        """
        expected = expected_outputs_dict["CRR-F1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F1",
        )
        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-F1",
        )

    def test_crr_f2_sme_blended_medium_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F2: Medium SME exposure gets blended factor.

        Input: Medium exposure (above threshold)
        Expected: Blended factor between 0.7619 and 0.85
        """
        expected = expected_outputs_dict["CRR-F2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F2"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F2",
        )

    def test_crr_f3_sme_tier2_dominant_large_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F3: Large SME exposure - Tier 2 dominates.

        Input: Large exposure (well above threshold)
        Expected: Factor approaching 0.85 as Tier 2 dominates
        """
        expected = expected_outputs_dict["CRR-F3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F3"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F3",
        )

    def test_crr_f4_sme_retail_with_tiered_factor(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F4: SME retail with tiered factor.

        Input: Retail SME exposure
        Expected: 75% RW + Tier 1 SME factor (0.7619)
        """
        expected = expected_outputs_dict["CRR-F4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F4"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F4",
        )

    def test_crr_f5_infrastructure_factor_not_tiered(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F5: Infrastructure factor is NOT tiered.

        Input: Infrastructure exposure
        Expected: Flat 0.75 factor regardless of exposure size

        Note: Infrastructure factor is not tiered like SME factor
        """
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F5"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert result["supporting_factor"] == pytest.approx(0.75, rel=0.001), (
            "Infrastructure factor should be 0.75"
        )

    def test_crr_f6_large_corporate_no_factor(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F6: Large corporate (turnover > threshold) gets no SME factor.

        Input: Large exposure, high turnover
        Expected: No SME factor (turnover exceeds eligibility threshold)
        """
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F6"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert result["supporting_factor"] == pytest.approx(1.0), (
            "Large corporate should have no supporting factor (1.0)"
        )

    def test_crr_f7_at_exposure_threshold_boundary(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F7: Exposure exactly at threshold.

        Input: Exposure at threshold
        Expected: Factor = 0.7619 (Tier 1 includes threshold)
        """
        expected = expected_outputs_dict["CRR-F7"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F7"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F7",
        )

    def test_crr_f8_lending_group_aggregation(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F8: Two SMEs in same lending group at GBP 1.5m drawn each.

        Expected: E* = GBP 3m → blended factor (Art. 501 group-of-connected-
        clients aggregation). A pure Tier 1 result would indicate the engine
        aggregated only at counterparty level.

        Pipeline fixture for two-member lending group is a follow-up; this
        test will skip cleanly until that fixture exists.
        """
        expected = expected_outputs_dict["CRR-F8"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F8"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F8",
        )


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
        expected_ids = [f"CRR-F{i}" for i in range(1, 9)]
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
        assert sf > 0.80, f"CRR-F3 should have Tier 2 dominant factor > 0.80, got {sf}"

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

    def test_crr_f8_has_blended_group_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        Verify CRR-F8 (lending group of two SMEs at GBP 1.5m each) yields a
        blended factor — confirms E* is aggregated across the group of
        connected clients per CRR Art. 501. Pure Tier 1 (0.7619) would
        indicate counterparty-only aggregation, which would be incorrect.
        """
        scenario = expected_outputs_dict["CRR-F8"]
        sf = scenario["supporting_factor"]
        assert 0.7619 < sf < 0.85, (
            f"CRR-F8 should have a blended factor (0.7619 < SF < 0.85), got {sf}. "
            "If SF == 0.7619 the engine likely aggregated at counterparty level "
            "instead of across the lending group (CRR Art. 501)."
        )

    def test_tiered_factor_calculation_formula(
        self,
        crr_config: dict[str, Any],
    ) -> None:
        """Verify tiered factor calculation matches expected formula."""
        from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
            calculate_sme_supporting_factor,
        )
        from workbooks.crr_expected_outputs.data.crr_params import (
            CRR_SME_EXPOSURE_THRESHOLD_GBP,
        )

        # Test various exposure amounts
        # Use dynamic threshold value from config
        threshold = CRR_SME_EXPOSURE_THRESHOLD_GBP
        test_cases = [
            # (exposure_gbp, expected_factor)
            (Decimal("1000000"), Decimal("0.7619")),  # Small - Tier 1 only
            (threshold, Decimal("0.7619")),  # At threshold
            (Decimal("4000000"), None),  # Blended (calculate)
            (Decimal("10000000"), None),  # Tier 2 dominant
        ]

        for exposure, expected in test_cases:
            factor = calculate_sme_supporting_factor(exposure, "GBP")
            factor_float = float(factor)
            if expected is not None:
                assert factor_float == pytest.approx(float(expected), rel=0.001), (
                    f"Factor for {exposure:,} should be {expected}, got {factor_float}"
                )
            else:
                # Just verify it's in valid range
                assert 0.7619 <= factor_float <= 0.85, (
                    f"Factor for {exposure:,} should be between 0.7619 and 0.85"
                )


# =============================================================================
# P2.22: SME-vs-infrastructure supporting-factor overlap regression guard
# =============================================================================


class TestP222SMEInfraOverlapSubstitution:
    """
    P2.22 — Regression guard: when an exposure is eligible for BOTH the SME
    supporting factor (CRR Art. 501) AND the infrastructure supporting factor
    (CRR Art. 501a), the engine must apply the LOWER of the two factors.

    Algebraic invariant:
        0.75 (infra) < 0.7619 (SME tier-1) <= SME_blended <= 0.85 (SME tier-2)

    Because the infra factor (0.75) is always strictly less than any admissible
    SME blended factor (0.7619 to 0.85), the substitution rule mandates that the
    infrastructure factor wins whenever both eligibility flags are set.

    Regulatory references:
    - CRR Art. 501(2) second subparagraph: when both factors are eligible, only
      the lower of the two shall be applied.
    - CRR Art. 501a(1): infrastructure supporting factor = 0.75 (flat, not tiered).

    Test fixture:
    - Counterparty: CP_SME_INFRA_001 — SME Infrastructure Solutions Ltd,
      annual_revenue=30,000,000 GBP (eligible for SME factor),
      sector_code=42.21 (transport infrastructure, eligible for infra factor).
    - Loan: LOAN_SME_INFRA_001 — GBP 1,500,000 drawn, INFRASTRUCTURE_LOAN
      product_type, counterparty=CP_SME_INFRA_001, unrated corporate (100% RW).

    Hand-calculation (reporting_date=2025-12-31):
        EAD = 1,500,000
        RW  = 1.00 (CRR Art. 122 unrated corporate)
        RWA_pre_factor = EAD × RW = 1,500,000

        SME factor (tier-1, E=1.5m < threshold): 0.7619
        Infra factor (flat):                      0.75
        Effective factor applied (min rule):       0.75   [infra wins]
        RWA_final = 1,500,000 × 0.75 = 1,125,000

    Anti-assertion (regression probe):
        If the engine applies SME tier-1 (0.7619) instead of infra (0.75):
            RWA_final = 1,500,000 × 0.7619 = 1,142,850  (wrong)
    """

    @pytest.fixture(scope="class")
    def p2_22_result(self, pipeline_results_df: pl.DataFrame) -> dict:
        """
        Extract the LOAN_SME_INFRA_001 row from the shared CRR pipeline results.

        Uses the session-scoped pipeline_results_df fixture from conftest so the
        pipeline is not re-run for this class.
        """
        row = get_result_for_exposure(pipeline_results_df, "LOAN_SME_INFRA_001")
        if row is None:
            pytest.skip(
                "P2.22: LOAN_SME_INFRA_001 not found in pipeline results — "
                "fixture may not have been generated yet"
            )
        return row

    def test_p2_22_sme_infra_overlap_substitution_regression(
        self,
        p2_22_result: dict,
    ) -> None:
        """
        P2.22 — SME-vs-infra overlap: infrastructure factor (0.75) must be applied.

        When LOAN_SME_INFRA_001 is eligible for both the SME supporting factor
        (CRR Art. 501) and the infrastructure supporting factor (CRR Art. 501a),
        the engine must apply the LOWER factor.

        Algebraic invariant (calibration guard):
            0.75 < 0.7619 <= SME_blended <= 0.85
        The infra factor (0.75) is always strictly less than any admissible SME
        blended factor, so a future calibration change that violates this ordering
        will break this test.

        Regulatory references:
        - CRR Art. 501(2) second subparagraph: apply only the lower factor.
        - CRR Art. 501a(1): infrastructure factor = 0.75.

        Arrange: LOAN_SME_INFRA_001, EAD=1,500,000 GBP, RW=1.00 (unrated corporate).
        Act:     CRR SA pipeline (reporting_date=2025-12-31, STANDARDISED permissions).
        Assert:
            1. ead_final == 1,500,000 (full drawn, no CRM)
            2. risk_weight == 1.00 (Art. 122 unrated corporate)
            3. rwa_pre_factor == 1,500,000 (EAD × RW before factor)
            4. is_sme == True (SME eligibility set)
            5. is_infrastructure == True (infrastructure eligibility set)
            6. supporting_factor == 0.75 (infra factor wins, NOT 0.7619)
            7. supporting_factor_applied == True
            8. rwa_final == 1,125,000 (1,500,000 × 0.75)

        Anti-assertion (regression probe):
            supporting_factor != 0.7619  — SME tier-1 factor must NOT be applied
            even though the exposure is SME-tier-1 eligible (E < threshold).
        """
        # Arrange — tolerances
        _EAD = 1_500_000.0
        _RW = 1.00
        _RWA_PRE = 1_500_000.0
        _INFRA_FACTOR = 0.75
        _SME_TIER1_FACTOR = 0.7619
        _RWA_FINAL = 1_125_000.0  # 1,500,000 × 0.75
        _RWA_IF_SME = 1_142_850.0  # 1,500,000 × 0.7619 (wrong path)
        _MONEY_TOL = 0.50  # £0.50 absolute tolerance
        _RW_TOL = 1e-6
        _FACTOR_TOL = 1e-4

        row = p2_22_result

        # Assert 1 — EAD
        assert row["ead_final"] == pytest.approx(_EAD, abs=_MONEY_TOL), (
            f"P2.22 LOAN_SME_INFRA_001: expected ead_final={_EAD:,.0f}, got {row['ead_final']:,.2f}"
        )

        # Assert 2 — risk weight (unrated corporate = 100%)
        assert row["risk_weight"] == pytest.approx(_RW, abs=_RW_TOL), (
            f"P2.22 LOAN_SME_INFRA_001: expected risk_weight={_RW} "
            f"(CRR Art. 122 unrated corporate), got {row['risk_weight']}"
        )

        # Assert 3 — RWA before factor
        assert row["rwa_pre_factor"] == pytest.approx(_RWA_PRE, abs=_MONEY_TOL), (
            f"P2.22 LOAN_SME_INFRA_001: expected rwa_pre_factor={_RWA_PRE:,.0f}, "
            f"got {row['rwa_pre_factor']:,.2f}"
        )

        # Assert 4 — SME eligibility flag
        assert row["is_sme"] is True, (
            f"P2.22 LOAN_SME_INFRA_001: expected is_sme=True "
            f"(revenue=30m GBP, E=1.5m < SME threshold), got {row['is_sme']}"
        )

        # Assert 5 — infrastructure eligibility flag
        assert row["is_infrastructure"] is True, (
            f"P2.22 LOAN_SME_INFRA_001: expected is_infrastructure=True "
            f"(product_type=INFRASTRUCTURE_LOAN, sector_code=42.21), "
            f"got {row['is_infrastructure']}"
        )

        # Assert 6 — factor value: infra must win, NOT SME tier-1
        # Anti-assertion (regression probe): SME tier-1 (0.7619) must NOT be applied.
        # Algebraic invariant: 0.75 (infra) < 0.7619 (SME tier-1) <= SME_blended <= 0.85
        assert row["supporting_factor"] != pytest.approx(_SME_TIER1_FACTOR, abs=_FACTOR_TOL), (
            f"P2.22 LOAN_SME_INFRA_001: supporting_factor must NOT be {_SME_TIER1_FACTOR} "
            f"(SME tier-1) — CRR Art. 501(2) second subparagraph requires the LOWER factor "
            f"(infra=0.75) when both eligibility flags are set. "
            f"Algebraic invariant: 0.75 < 0.7619 <= SME_blended <= 0.85"
        )
        assert row["supporting_factor"] == pytest.approx(_INFRA_FACTOR, abs=_FACTOR_TOL), (
            f"P2.22 LOAN_SME_INFRA_001: expected supporting_factor={_INFRA_FACTOR} "
            f"(CRR Art. 501a(1) infrastructure factor — wins via min rule), "
            f"got {row['supporting_factor']} "
            f"(SME tier-1 would give {_SME_TIER1_FACTOR})"
        )

        # Assert 7 — factor is applied
        assert row["supporting_factor_applied"] is True, (
            f"P2.22 LOAN_SME_INFRA_001: expected supporting_factor_applied=True, "
            f"got {row['supporting_factor_applied']}"
        )

        # Assert 8 — final RWA confirms substitution outcome
        assert row["rwa_final"] == pytest.approx(_RWA_FINAL, abs=_MONEY_TOL), (
            f"P2.22 LOAN_SME_INFRA_001: expected rwa_final={_RWA_FINAL:,.0f} "
            f"(EAD 1,500,000 × RW 1.00 × infra_factor 0.75), "
            f"got {row['rwa_final']:,.2f} "
            f"(if SME tier-1 were applied: {_RWA_IF_SME:,.0f})"
        )
