"""
CCR-A14: single 10-year GBP vanilla IR swap, margined netting set, 126-day remargin.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Prove the "EAD rises" branch of P8.54: a long-remargin CSA (126-day frequency)
  produces MPOR_eff=135 and MF_margined=1.10227, which exceeds the unmargined MF=1.0
  cap, lifting EAD ABOVE the unmargined-MF=1.0 baseline.
- Validate MPOR cascade per CRR Art. 285(2)-(5):
    base = 10 BD (OTC Art. 285(2)(b)), no 20-BD upgrade, no dispute doubling,
    MPOR_eff = max(10 + 126 - 1, 10) = 135.
    MF_margined = 1.5 × sqrt(135/250) = 1.102270384252.
- Validate addon_aggregate = 3_914_298.2277279915 × 1.102270384252 = 4_314_615.012
  (exactly linear in MF for a single-trade single-bucket netting set).
- Validate rc_margined = max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0) = 2_250_000.
- Validate post-fix EAD = alpha * (rc_margined + PFE_addon) > 6_464_360.391383706
  (load-bearing inequality — proves EAD exceeds unmargined MF=1.0 baseline).
- Validate SA risk weight lookup for CQS-2 institution (50% under CRR Art. 120(1) Table 3).
- Validate RWA = EAD * RW = EAD * 0.50.

Scenario: one trade T_MGN_002 (10y GBP IR swap, notional GBP 100m, MtM=-4m, delta=1),
one netting set NS_MGN_002 (CP_001, legally enforceable, margined, TH=2m, MTA=0.5m,
NICA=0.25m, MPOR=10d), margin agreement MA_MGN_002 with remargining_frequency_days=126.
No CCR collateral. Identical to CCR-A13 except remargining_frequency_days=126 vs 1.

Hand-calculation reference (CCR-A14, P8.54):
    MPOR cascade (CRR Art. 285):
        base = 10 BD (OTC Art. 285(2)(b))
        number_of_trades = 1 < 5000, has_illiquid = False → no 20-BD upgrade
        dispute_count_qtr = 0 → no doubling
        MPOR_eff = max(10 + 126 - 1, 10) = max(135, 10) = 135
        MF_margined = 1.5 × sqrt(135/250) = 1.5 × 0.734846922834 = 1.102270384252

    V  = -4_000_000  (trade MtM)
    C  = 0           (no CCR collateral)
    TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000

    RC (Art. 275(2)) = max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0) = 2_250_000

    addon_aggregate (MF=1.10227) = 3_914_298.2277279915 × 1.102270384252
                                 = 4_314_615.011554657  (exact — linear in MF)

    pfe_multiplier ≈ 0.633217  (V < 0, MtM out-of-the-money; exp()-dependent)
    pfe_addon ≈ 2_732_138      (hand-calc; engine bytes confirmed by engine-implementer)
    EAD ≈ 1.4 × (2_250_000 + 2_732_138) ≈ 6_974_993
    RW  = 0.50  (institution, CQS 2, CRR Art. 120(1) Table 3)
    RWA ≈ 6_974_993 × 0.50 ≈ 3_487_497

    Load-bearing inequality:
        EAD > 6_464_360.391383706  (CCR-A13 unmargined-MF=1.0 baseline)
        Proves: margined MF > 1.0 (long-remargin) RAISES EAD vs the unmargined cap.

Current engine behaviour (MF wiring absent):
    addon_aggregate ≈ 3_914_298.228 (MF=1.0 applied to both A13 and A14)
    ead_final ≈ 6_464_360.391383706 (equals the load-bearing lower bound — NOT above it)
    The `ead_final > 6_464_360.391383706` assertion FAILS RED.

PRECISION NOTE: pfe_multiplier, pfe_addon, ead_final, rwa_final involve exp() so
their final bytes in CCR-A14.json are hand-calc approximations.  The engine-implementer
must confirm/re-pin these to Polars-precise values during the P8.54 validation gate.
addon_aggregate is exactly linear in MF and is asserted with rel=1e-9.

References:
    - CRR Art. 272(7): margin agreement / CSA definition
    - CRR Art. 274(2): EAD = alpha * (RC + PFE), alpha = 1.4
    - CRR Art. 275(2): margined RC = max(V - C, TH + MTA - NICA, 0)
    - CRR Art. 278: PFE = multiplier * AddOn_aggregate
    - CRR Art. 279c(2): margined MF = 1.5 * sqrt(MPOR_eff / 250)
    - CRR Art. 280a: IR supervisory factor SF = 0.5%
    - CRR Art. 285(2)(b): 10-day minimum MPOR for OTC derivatives
    - CRR Art. 285(5): MPOR_eff = base + remargining_frequency_days - 1
    - CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a14.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A14.json: expected values (single source of truth)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_a14 import (
    CCR_A14_ADDON_AGGREGATE,
    CCR_A14_EAD_LOWER_BOUND,
    build_raw_data_bundle_with_ccr_a14,
)

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A14.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A14.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_MGN_002"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a14_result() -> dict:
    """
    Run the CCR-A14 bundle through the CRR SA pipeline and return the single
    CCR synthetic row for ccr__NS_MGN_002 as a dict.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.

    Arrange:
        - 1 trade (T_MGN_002): 10y GBP IR swap, notional GBP 100m, MtM=-4m, delta=1
        - 1 netting set (NS_MGN_002): CP_001, legally enforceable, margined
          (TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d)
        - margin agreement MA_MGN_002: remargining_frequency_days=126 (126-day remargin)
        - CP_001: institution, CQS 2, GB (entity_type="institution")
        - External rating: S&P "A" = CQS 2
        - No CCR collateral (c_net=0)
    """
    # Arrange
    bundle = build_raw_data_bundle_with_ccr_a14()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A14: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A14 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA14LongRemarginMF:
    """
    CCR-A14: 10y GBP IR swap, margined netting set, 126-day remargin — seven acceptance assertions.

    Seven tests verify:
      - rc_margined == 2_250_000.0 (MF-independent; Art. 275(2) floor arm)
      - rc_unmargined == 0.0 (margined netting set → unmargined path skipped)
      - addon_aggregate ≈ 4_314_615.012 (= 3_914_298.228 × MF_margined(1.10227); linear)
      - pfe_addon ≈ 2_732_138 (multiplier × addon_aggregate; exp()-dependent)
      - ead_final > 6_464_360.391383706 (load-bearing inequality — EAD rises above MF=1.0)
      - exposure_class == 'institution'
      - rwa_final ≈ 3_487_497 (= EAD × 0.50; exp()-dependent)

    The `addon_aggregate` test and `ead_final > bound` inequality are the two
    load-bearing P8.54 assertions:
      - Current engine (MF=1.0 unwired): addon_aggregate ≈ 3_914_298.228 — RED
      - Current engine: ead_final == 6_464_360.391383706 (equals bound, NOT above it) — RED
      - Post-fix (MF=1.10227 wired): addon_aggregate ≈ 4_314_615.012 — GREEN
      - Post-fix: ead_final ≈ 6_974_993 > 6_464_360.391383706 — GREEN

    All expected values are sourced from tests/expected_outputs/ccr/CCR-A14.json.
    Engine-implementer must confirm/re-pin exp()-dependent bytes (pfe_addon/ead/rwa)
    to Polars-precise values during the P8.54 validation gate.
    """

    def test_ccr_a14_rc_margined(self, ccr_a14_result: dict) -> None:
        """
        Margined RC = max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0) = 2_250_000.

        Identical to CCR-A13: rc_margined is MF-independent (same TH/MTA/NICA/MtM).
        This verifies Art. 275(2) and confirms the CCR-A14 netting set is correctly
        configured as margined (NS_MGN_002 with TH=2m, MTA=0.5m, NICA=0.25m).

        Arrange: MtM=-4m, no collateral, TH=2m, MTA=0.5m, NICA=0.25m.
                 max(-4_000_000, 2_250_000, 0) = 2_250_000 [floor arm binds].
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_margined == 2_250_000.0 (abs tol 1e-6).

        References: CRR Art. 275(2) — margined RC = max(V - C, TH + MTA - NICA, 0).
        """
        # Arrange
        row = ccr_a14_result
        expected_rc_margined: float = _EXPECTED["rc_margined"]

        # Act: rc_margined is the column written by compute_rc_margined.
        # On the current engine this column may be absent or contain 0.
        actual_rc = row.get("rc_margined") or row.get("rc") or 0.0

        # Assert
        assert actual_rc == pytest.approx(expected_rc_margined, abs=1e-6), (
            f"CCR-A14: expected rc_margined={expected_rc_margined:,.1f} "
            f"(CRR Art. 275(2): max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0)), "
            f"got {actual_rc}. "
            "rc_margined is MF-independent — same for CCR-A13 and CCR-A14."
        )

    def test_ccr_a14_rc_unmargined(self, ccr_a14_result: dict) -> None:
        """
        Unmargined RC = max(V - C, 0) = max(-4m, 0) = 0.0.

        NS_MGN_002 is margined, so the unmargined path is skipped.

        Arrange: MtM=-4m, margined netting set (NS_MGN_002).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_unmargined == 0.0 (abs tol 1e-6).

        References: CRR Art. 275(1) — unmargined RC = max(V - C, 0).
        """
        # Arrange
        row = ccr_a14_result
        expected = _EXPECTED["rc_unmargined"]

        # Assert
        actual = row.get("rc_unmargined", 0.0)
        assert actual == pytest.approx(expected, abs=1e-6), (
            f"CCR-A14: expected rc_unmargined={expected} (max(-4m, 0) = 0), "
            f"got {actual}. "
            "CRR Art. 275(1): unmargined RC = max(V - C, 0)."
        )

    def test_ccr_a14_addon_aggregate(self, ccr_a14_result: dict) -> None:
        """
        addon_aggregate = 3_914_298.2277279915 × MF_margined(1.10227) = 4_314_615.012.

        This is the P8.54 load-bearing precision assertion. addon_aggregate is exactly
        linear in MF (single trade, single bucket), so this test directly proves whether
        the engine wires MF_margined≈1.10227 (long-remargin) vs the unwired MF=1.0 baseline.

        Arrange: remargining_frequency_days=126 → MPOR_eff=135
                 → MF_margined = 1.5 × sqrt(135/250) = 1.102270384252.
                 Baseline addon_aggregate (MF=1.0) = 3_914_298.2277279915.
                 addon_aggregate (MF=1.10227) = 3_914_298.2277279915 × 1.102270384252
                                              = 4_314_615.011554657 (exact).
        Act:     full CRR SA+CCR pipeline.
        Assert:  addon_aggregate == 4_314_615.011554657 (rel tol 1e-9 — exactly linear in MF).

        Current engine (MF=1.0 unwired): addon_aggregate ≈ 3_914_298.228 — FAILS RED.
        Post-fix (MF=1.10227 wired): addon_aggregate ≈ 4_314_615.012 — PASSES GREEN.

        References: CRR Art. 279c(2) MF=1.5×sqrt(MPOR_eff/250); Art. 285(5) MPOR_eff cascade.
        """
        # Arrange
        row = ccr_a14_result
        expected = CCR_A14_ADDON_AGGREGATE  # 4_314_615.011554657 (exact, from fixture constant)

        # Assert — rel=1e-9 (linear precision; no exp() in addon_aggregate itself)
        assert row["addon_aggregate"] == pytest.approx(expected, rel=1e-9), (
            f"CCR-A14: expected addon_aggregate={expected:,.9f} "
            f"(= 3_914_298.228 × MF_margined(1.10227)), "
            f"got {row['addon_aggregate']:,.9f}. "
            "P8.54: current engine applies unmargined MF=1.0 (≈3_914_298.228 — wrong). "
            "CRR Art. 279c(2): MF_margined = 1.5 × sqrt(135/250) = 1.102270384252."
        )

    def test_ccr_a14_pfe_addon(self, ccr_a14_result: dict) -> None:
        """
        PFE add-on = multiplier * AddOn_aggregate ≈ 2_732_138 (MF≈1.10227).

        Arrange: 10y GBP IR swap, notional GBP 100m. MtM=-4m (V<0).
                 addon_aggregate(MF=1.10227) ≈ 4_314_615.012.
                 denom = 2 × 0.95 × 4_314_615 ≈ 8_197_769.
                 exponent = -4_000_000 / 8_197_769 ≈ -0.487939.
                 pfe_multiplier ≈ 0.633217; pfe_addon ≈ 2_732_138.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 2_732_138 (rel tol 1e-6; exp()-dependent).

        NOTE: The exact bytes depend on Polars exp() — the engine-implementer must
        confirm/re-pin the CCR-A14.json pfe_addon value during the P8.54 validation gate.

        References:
            CRR Art. 278: PFE = multiplier * AddOn_aggregate.
            CRR Art. 280a: IR supervisory factor SF = 0.5%.
        """
        # Arrange
        row = ccr_a14_result
        expected = _EXPECTED["pfe_addon"]

        # Assert
        assert row["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A14: expected pfe_addon approx {expected:,.6f} (MF≈1.10227 post-fix), "
            f"got {row['pfe_addon']:,.6f}. "
            "CRR Art. 278: PFE = multiplier * AddOn_aggregate; Art. 280a: SF_IR=0.005."
        )

    def test_ccr_a14_ead_rises_above_unmargined_baseline(self, ccr_a14_result: dict) -> None:
        """
        EAD > 6_464_360.391383706 (load-bearing inequality — margined MF > 1.0 raises EAD).

        This is the definitive proof of P8.54: when MF_margined > 1.0 (long-remargin CSA),
        the margined path produces a HIGHER EAD than the unmargined-MF=1.0 baseline.

        6_464_360.391383706 is the CCR-A13 (and current CCR-A14 engine) EAD with MF=1.0.
        After the P8.54 fix, CCR-A14 EAD ≈ 6_974_993 (MF=1.10227), which exceeds the bound.

        Arrange: alpha=1.4; rc_margined=2_250_000; pfe_addon(MF=1.10227) ≈ 2_732_138.
                 EAD ≈ 1.4 × (2_250_000 + 2_732_138) ≈ 6_974_993
                 Bound = 6_464_360.391383706 (unmargined-MF=1.0 EAD).
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final > 6_464_360.391383706 (strict inequality).

        Current engine (MF=1.0 unwired):
            ead_final ≈ 6_464_360.391383706 (EQUALS the bound — strict > FAILS RED).
        Post-fix (MF=1.10227 wired):
            ead_final ≈ 6_974_993 (EXCEEDS the bound — strict > PASSES GREEN).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_a14_result
        lower_bound: float = CCR_A14_EAD_LOWER_BOUND  # 6_464_360.391383706

        # Assert — strict inequality proves the "EAD rises" branch
        assert row["ead_final"] > lower_bound, (
            f"CCR-A14: expected ead_final > {lower_bound:,.9f} "
            f"(unmargined-MF=1.0 baseline, i.e. CCR-A13 pre-fix EAD), "
            f"got ead_final={row['ead_final']:,.9f}. "
            "P8.54: current engine applies MF=1.0 so ead_final EQUALS the bound. "
            "After fix: MF_margined=1.10227 → ead_final ≈ 6_974_993 (rises above bound). "
            "CRR Art. 279c(2): MF_margined = 1.5 × sqrt(135/250) = 1.102270384252 > 1.0."
        )

    def test_ccr_a14_exposure_class(self, ccr_a14_result: dict) -> None:
        """
        Classifier routes CP_001 (entity_type='institution') to exposure_class 'institution'.

        Arrange: CP_001 entity_type='institution', GB, CQS 2.
        Act:     full CRR SA+CCR pipeline.
        Assert:  exposure_class == 'institution' (case-insensitive).

        References: CRR Art. 112(b) — institution exposure class.
        """
        # Arrange
        row = ccr_a14_result
        expected = _EXPECTED["exposure_class"]

        # Assert
        assert row["exposure_class"].lower() == expected.lower(), (
            f"CCR-A14: expected exposure_class={expected!r}, "
            f"got {row['exposure_class']!r}. "
            "CRR Art. 112(b): institution entity_type -> institution exposure class."
        )

    def test_ccr_a14_rwa(self, ccr_a14_result: dict) -> None:
        """
        RWA = EAD * RW ≈ 6_974_993 * 0.50 ≈ 3_487_497 (MF≈1.10227 post-fix).

        Arrange: EAD≈6_974_993 (P8.54 MF=1.10227), institution CQS 2 → RW=50%.
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 3_487_497 (rel tol 1e-6; exp()-dependent).

        NOTE: The exact bytes depend on Polars exp() — engine-implementer must confirm/re-pin
        the CCR-A14.json rwa_final value during the P8.54 validation gate.

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 -> 50% risk weight.
        """
        # Arrange
        row = ccr_a14_result
        expected = _EXPECTED["rwa_final"]

        # Assert
        assert row["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A14: expected rwa_final approx {expected:,.6f} (P8.54 MF≈1.10227), "
            f"got {row['rwa_final']:,.6f}. "
            "RWA = EAD * RW ≈ 6_974_993 * 0.50 ≈ 3_487_497 "
            "(CRR Art. 120(1) Table 3, CQS 2, institution). "
            "Pre-fix engine (MF=1.0): rwa_final≈3_232_180."
        )
