"""
CRR-E9: UK CRR Art. 153(5) — HVCRE exposures must use Table 1, not Table 2.

Under UK CRR there is no HVCRE sub-class in Art. 153(5). All specialised lending
exposures — regardless of the is_hvcre flag — must be risk-weighted using Table 1.
The pre-fix engine incorrectly routes is_hvcre=True through EU CRR Table 2
(SLOTTING_RISK_WEIGHTS_HVCRE), yielding 95% for Strong >=2.5yr instead of the
correct 70%.

Regulatory Reference:
- CRR Art. 153(5): Slotting approach risk weights — Table 1 (non-HVCRE only)
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from rwa_calc.engine.slotting.transforms import lookup_rw

# Expected post-fix values (CRR Art. 153(5) Table 1, Strong >=2.5yr)
EXPECTED_EAD = 5_000_000.0
EXPECTED_RISK_WEIGHT = 0.70
EXPECTED_RWA = 3_500_000.0
EXPOSURE_REFERENCE = "LOAN_SL_HVCRE_TABLE1_FIX"
SCENARIO_ID = "CRR-E9"

# Pre-fix (buggy) value — regression sentinel
BUGGY_RISK_WEIGHT = 0.95


class TestCRRE9_UKCRRNoHVCRE:
    """
    CRR-E9: is_hvcre=True under UK CRR must use Table 1 (70% Strong >=2.5yr).

    UK CRR Art. 153(5) has only one slotting weight table. The EU HVCRE
    concept (Table 2) does not exist in the onshored UK text. An exposure
    flagged is_hvcre=True must therefore receive the same risk weight as
    any other Strong >=2.5yr specialised lending exposure: 70%.

    Pre-fix engine: applies EU Table 2 -> Strong >=2.5yr = 95% RW.
    Post-fix engine: applies Table 1 -> Strong >=2.5yr = 70% RW.
    """

    def test_crr_e9_hvcre_strong_long_maturity_uses_table_1_rw(self) -> None:
        """
        CRR-E9: is_hvcre=True + strong + >=2.5yr under CRR must yield 70% RW.

        Arrange: Polars LazyFrame with slotting_category='strong', is_hvcre=True,
                 is_short_maturity=False; CRR framework.
        Act: Apply lookup_rw(is_crr=True, is_hvcre=col('is_hvcre'),
             is_short=col('is_short_maturity')).
        Assert: risk_weight == 0.70 (Table 1, not EU Table 2's 0.95).

        This test directly exercises the lookup_rw transform path that the
        engine-implementer must fix.
        """
        # Arrange — single-row LazyFrame representing the CRR-E9 fixture
        lf = pl.LazyFrame(
            {
                "exposure_reference": [EXPOSURE_REFERENCE],
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "ead_final": [EXPECTED_EAD],
            }
        )

        # Act — apply the CRR slotting risk weight lookup
        result_df = lf.with_columns(
            risk_weight=lookup_rw(
                pl.col("slotting_category"),
                is_crr=True,
                is_hvcre=pl.col("is_hvcre"),
                is_short=pl.col("is_short_maturity"),
            )
        ).collect()

        actual_rw = result_df["risk_weight"][0]

        # Assert — pre-fix: 0.95 (Table 2 HVCRE Strong >=2.5yr); post-fix: 0.70
        assert actual_rw == pytest.approx(EXPECTED_RISK_WEIGHT, abs=1e-4), (
            f"{SCENARIO_ID}: UK CRR has no HVCRE Table 2. is_hvcre=True Strong >=2.5yr "
            f"must use Table 1 -> 70% RW. "
            f"Got {actual_rw:.4f} (pre-fix engine returns {BUGGY_RISK_WEIGHT} from EU Table 2)."
        )

    def test_crr_e9_hvcre_rwa_matches_expected(self) -> None:
        """
        CRR-E9: RWA = EAD x RW = 5,000,000 x 0.70 = 3,500,000 under UK CRR.

        Arrange: EAD=5_000_000, is_hvcre=True, strong, >=2.5yr.
        Act: Apply full slotting weight + RWA calculation via the transforms.
        Assert: rwa == 3_500_000.0 (not the pre-fix 4_750_000.0).
        """
        # Arrange
        lf = pl.LazyFrame(
            {
                "exposure_reference": [EXPOSURE_REFERENCE],
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
                "ead_final": [EXPECTED_EAD],
            }
        )

        # Act
        result_df = (
            lf.with_columns(
                risk_weight=lookup_rw(
                    pl.col("slotting_category"),
                    is_crr=True,
                    is_hvcre=pl.col("is_hvcre"),
                    is_short=pl.col("is_short_maturity"),
                )
            )
            .with_columns(rwa=pl.col("ead_final") * pl.col("risk_weight"))
            .collect()
        )

        actual_rwa = result_df["rwa"][0]

        # Assert
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=0.01), (
            f"{SCENARIO_ID}: RWA should be {EXPECTED_RWA:,.0f} (5m x 70% Table 1). "
            f"Got {actual_rwa:,.0f}. "
            f"Pre-fix: {EXPECTED_EAD * BUGGY_RISK_WEIGHT:,.0f} (5m x 95% Table 2)."
        )

    def test_crr_e9_regression_sentinel_not_table_2(self) -> None:
        """
        CRR-E9 regression: ensure the engine no longer returns Table 2's 95% for CRR HVCRE.

        The pre-fix engine routes is_hvcre=True under CRR to SLOTTING_RISK_WEIGHTS_HVCRE
        (EU Table 2) which gives Strong >=2.5yr = 95%. Post-fix it must give 70% (Table 1).

        Arrange: strong, is_hvcre=True, is_short_maturity=False, is_crr=True.
        Act: lookup_rw.
        Assert: result is NOT 0.95.
        """
        # Arrange
        lf = pl.LazyFrame(
            {
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "is_short_maturity": [False],
            }
        )

        # Act
        result_df = lf.with_columns(
            risk_weight=lookup_rw(
                pl.col("slotting_category"),
                is_crr=True,
                is_hvcre=pl.col("is_hvcre"),
                is_short=pl.col("is_short_maturity"),
            )
        ).collect()

        actual_rw = result_df["risk_weight"][0]

        # Assert — regression sentinel
        assert actual_rw != pytest.approx(BUGGY_RISK_WEIGHT, abs=1e-4), (
            f"{SCENARIO_ID} regression: risk_weight is still {BUGGY_RISK_WEIGHT} "
            f"(EU HVCRE Table 2). UK CRR has no HVCRE table — must be {EXPECTED_RISK_WEIGHT}."
        )

    def test_crr_e9_scenario_exists_in_expected_outputs(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-E9: Verify the scenario entry is present in expected_rwa_crr.json
        with the correct post-fix values.

        Arrange: expected_outputs_dict loaded from golden file.
        Act: Look up SCENARIO_ID.
        Assert: entry found with risk_weight=0.70 and rwa_after_sf=3_500_000.
        """
        # Arrange / Act
        assert SCENARIO_ID in expected_outputs_dict, (
            f"Scenario {SCENARIO_ID} not found in expected_rwa_crr.json"
        )

        expected = expected_outputs_dict[SCENARIO_ID]

        # Assert
        assert expected["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT), (
            f"{SCENARIO_ID}: expected_outputs risk_weight should be {EXPECTED_RISK_WEIGHT}, "
            f"got {expected['risk_weight']}"
        )
        assert expected["rwa_after_sf"] == pytest.approx(EXPECTED_RWA), (
            f"{SCENARIO_ID}: expected_outputs rwa_after_sf should be {EXPECTED_RWA:,.0f}, "
            f"got {expected['rwa_after_sf']:,.0f}"
        )
