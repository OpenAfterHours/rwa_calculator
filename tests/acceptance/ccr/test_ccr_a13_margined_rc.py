"""
CCR-A13: single 10-year GBP vanilla IR swap, margined netting set.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate SA-CCR replacement cost (RC) for a MARGINED netting set with
  MtM = -4_000_000 (out-of-the-money): RC = max(V-C, TH+MTA-NICA, 0).
- Prove P8.19 bug: current engine uses unmargined formula max(V-C, 0) = 0
  instead of the margined formula, understating EAD.
- Validate post-fix EAD = alpha * (rc_margined + PFE_addon).
- Validate SA risk weight lookup for CQS-2 institution (50% under CRR
  Art. 120(1) Table 3).
- Validate RWA = EAD * RW = EAD * 0.50.

Scenario: one trade T_MGN_001 (10y GBP IR swap, notional GBP 100m, MtM=-4m,
delta=1), one netting set NS_MGN_001 (CP_001, legally enforceable, margined,
TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d), margin agreement MA_MGN_001, no
CCR collateral.

Hand-calculation reference (CCR-A13 golden values from CCR-A13.json, P8.54 re-pin):
    V  = -4_000_000  (trade MtM)
    C  = 0           (no CCR collateral)
    TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000

    RC (post-fix, Art. 275(2)) = max(V-C, TH+MTA-NICA, 0)
                                = max(-4m, 2.25m, 0) = 2_250_000
    RC (pre-fix bug, Art. 275(1)) = max(V-C, 0) = max(-4m, 0) = 0

    MPOR cascade (P8.54 re-pin — daily remargin → MF_margined=0.30):
        remargining_frequency_days = 1 (daily remargin CSA)
        base MPOR = 10 BD (Art. 285(2)(b) OTC floor)
        MPOR_eff = max(10 + 1 - 1, 10) = 10
        MF_margined = 1.5 × sqrt(10/250) = 0.30 (exact)

    PFE add-on (MF=0.30, P8.54 re-pin):
        addon_aggregate (MF=0.30) = 3_914_298.228 × 0.30 = 1_174_289.468
        exponent = -4_000_000 / (2 * 0.95 * 1_174_289.468) ≈ -1.79279
        pfe_multiplier ≈ 0.208148
        pfe_addon ≈ 244_426

    EAD  = 1.4 * (2_250_000 + 244_426) ≈ 3_492_196
    RW   = 0.50  (institution, CQS 2, CRR Art. 120(1) Table 3)
    RWA  ≈ 3_492_196 * 0.50 ≈ 1_746_098

    Pre-fix MF=1.0 baseline (unmargined path, current engine):
        addon_aggregate = 3_914_298.228 -> pfe_addon = 2_367_400.280
        EAD = 6_464_360.391383706  -> RWA = 3_232_180.196

    NOTE: pfe_multiplier, pfe_addon, ead_final, rwa_final involve exp() so the
    final bytes in CCR-A13.json are hand-calc approximations; the engine-implementer
    must confirm/re-pin these to engine-precise values during the P8.54 validation gate.
    addon_aggregate is exactly linear in MF and asserted with rel=1e-9.

This test is expected to FAIL (RED) on the current engine because MF_margined
is not yet wired — the engine applies unmargined MF=1.0, producing
addon_aggregate≈3_914_298.228 (vs golden 1_174_289.468).
It becomes GREEN when P8.54 wires compute_maturity_factor_margined.

References:
    - CRR Art. 272(7): margin agreement / CSA definition
    - CRR Art. 274(2): EAD = alpha * (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 275(2): margined RC = max(V - C, TH + MTA - NICA, 0)
    - CRR Art. 278: PFE = multiplier * AddOn_aggregate
    - CRR Art. 280a: IR supervisory factor SF = 0.5%
    - CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a13.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A13.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a13 import build_raw_data_bundle_with_ccr_a13

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A13.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A13.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_MGN_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a13_result() -> dict:
    """
    Run the CCR-A13 bundle through the CRR SA pipeline and return the single
    CCR synthetic row for ccr__NS_MGN_001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.

    Arrange:
        - 1 trade (T_MGN_001): 10y GBP IR swap, notional GBP 100m, MtM=-4m, delta=1
        - 1 netting set (NS_MGN_001): CP_001, legally enforceable, margined
          (TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d)
        - margin agreement MA_MGN_001 with identical margin parameters
        - CP_001: institution, CQS 2, GB (entity_type="institution")
        - External rating: S&P "A" = CQS 2
        - No CCR collateral (c_net=0)
    """
    # Arrange
    bundle = build_raw_data_bundle_with_ccr_a13()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A13: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A13 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA13MarginedRC:
    """
    CCR-A13: 10y GBP IR swap, margined netting set — six acceptance assertions.

    Six tests verify (P8.54 re-pin — MF_margined=0.30, daily remargin):
      - rc_margined == 2_250_000.0 (MF-independent; Art. 275(2) floor arm)
      - rc_unmargined == 0.0 (margined netting set → unmargined path skipped)
      - addon_aggregate ≈ 1_174_289.468 (= 3_914_298.228 × 0.30; exactly linear in MF)
      - pfe_addon ≈ 244_426 (multiplier × addon_aggregate; exp()-dependent)
      - ead_final ≈ 3_492_196 (= 1.4 × (2_250_000 + 244_426); exp()-dependent)
      - exposure_class == 'institution'
      - rwa_final ≈ 1_746_098 (= EAD × 0.50; exp()-dependent)

    The addon_aggregate test is the load-bearing P8.54 precision assertion:
      - Current engine (MF=1.0 unwired): addon_aggregate ≈ 3_914_298.228 — RED
      - Post-fix (MF=0.30 wired): addon_aggregate ≈ 1_174_289.468 — GREEN

    All expected values are sourced from tests/expected_outputs/ccr/CCR-A13.json.
    Engine-implementer must confirm/re-pin exp()-dependent bytes (pfe_addon/ead/rwa)
    to Polars-precise values during the P8.54 validation gate.
    """

    def test_ccr_a13_rc_margined(self, ccr_a13_result: dict) -> None:
        """
        Margined RC = max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0) = 2_250_000.

        Arrange: MtM=-4m, no collateral, TH=2m, MTA=0.5m, NICA=0.25m.
                 max(-4_000_000, 2_250_000, 0) = 2_250_000 [floor arm binds].
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_margined == 2_250_000.0 (abs tol 1e-6).

        This assertion is RED on the pre-fix engine where the adapter uses
        rc_unmargined=max(-4m, 0)=0 instead of the margined formula.

        References: CRR Art. 275(2) — margined RC = max(V - C, TH + MTA - NICA, 0).
        """
        # Arrange
        row = ccr_a13_result
        expected_rc_margined: float = _EXPECTED["rc_margined"]

        # Act: rc_margined is the column written by compute_rc_margined (post-fix).
        # On the current unfixed engine this column may be absent or 0.
        # We assert on the value that feeds EAD — either rc_margined directly
        # (if the column exists) or fall back to asserting rc (the unified field).
        # Either way the assertion will fail with a clean AssertionError on the
        # wrong (0) value instead of a KeyError.
        actual_rc = row.get("rc_margined") or row.get("rc") or 0.0

        assert actual_rc == pytest.approx(expected_rc_margined, abs=1e-6), (
            f"CCR-A13: expected rc_margined={expected_rc_margined:,.1f} "
            f"(CRR Art. 275(2): max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0)), "
            f"got {actual_rc}. "
            "P8.19 fix must wire compute_rc_margined through the SA-CCR orchestrator."
        )

    def test_ccr_a13_rc_unmargined(self, ccr_a13_result: dict) -> None:
        """
        Unmargined RC = max(V - C, 0) = max(-4m, 0) = 0.0.

        This confirms the unmargined path is NOT used for this margined netting set.

        Arrange: MtM=-4m, margined netting set (NS_MGN_001).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_unmargined == 0.0 (abs tol 1e-6).

        References: CRR Art. 275(1) — unmargined RC = max(V - C, 0).
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["rc_unmargined"]

        # Assert
        actual = row.get("rc_unmargined", 0.0)
        assert actual == pytest.approx(expected, abs=1e-6), (
            f"CCR-A13: expected rc_unmargined={expected} (max(-4m, 0) = 0), "
            f"got {actual}. "
            "CRR Art. 275(1): unmargined RC = max(V - C, 0)."
        )

    def test_ccr_a13_addon_aggregate(self, ccr_a13_result: dict) -> None:
        """
        addon_aggregate = 3_914_298.2277279915 × MF_margined(0.30) = 1_174_289.468.

        This is the P8.54 load-bearing precision assertion: addon_aggregate is exactly
        linear in MF (single trade, single bucket), so this test catches whether the
        engine wires MF_margined=0.30 vs the unwired MF=1.0 baseline.

        Arrange: daily remargin (freq=1) → MPOR_eff=10 → MF=1.5×sqrt(10/250)=0.30.
                 Baseline addon_aggregate (MF=1.0) = 3_914_298.2277279915.
                 addon_aggregate (MF=0.30) = 3_914_298.2277279915 × 0.30 = 1_174_289.468.
        Act:     full CRR SA+CCR pipeline.
        Assert:  addon_aggregate ≈ 1_174_289.468 (rel tol 1e-9 — exactly linear in MF).

        Current engine (unwired MF=1.0): addon_aggregate ≈ 3_914_298.228 — this assertion
        will FAIL RED until P8.54 wires compute_maturity_factor_margined.

        References: CRR Art. 279c(2) MF=1.5×sqrt(MPOR_eff/250); Art. 280a SF_IR=0.5%.
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["addon_aggregate"]

        # Assert
        assert row["addon_aggregate"] == pytest.approx(expected, rel=1e-9), (
            f"CCR-A13: expected addon_aggregate={expected:,.9f} "
            f"(=3_914_298.228 × MF_margined(0.30)), "
            f"got {row['addon_aggregate']:,.9f}. "
            "P8.54: current engine applies unmargined MF=1.0 (≈3_914_298.228 — wrong). "
            "CRR Art. 279c(2): MF_margined = 1.5 × sqrt(10/250) = 0.30."
        )

    def test_ccr_a13_pfe(self, ccr_a13_result: dict) -> None:
        """
        PFE add-on = multiplier * AddOn_aggregate ≈ 244_426 (MF=0.30, P8.54 re-pin).

        Arrange: 10y GBP IR swap, notional GBP 100m. MtM=-4m (V<0).
                 addon_aggregate(MF=0.30) ≈ 1_174_289.468.
                 exponent = -4_000_000 / (2 × 0.95 × 1_174_289.468) ≈ -1.79279.
                 pfe_multiplier ≈ 0.208148; pfe_addon ≈ 244_426.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 244_426 (rel tol 1e-6; exp()-dependent).

        NOTE: The exact bytes depend on Polars exp() — the engine-implementer must
        confirm/re-pin the CCR-A13.json value during the P8.54 validation gate.

        References:
            CRR Art. 278: PFE = multiplier * AddOn_aggregate.
            CRR Art. 280a: IR supervisory factor SF = 0.5%.
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["pfe_addon"]

        # Assert
        assert row["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A13: expected pfe_addon approx {expected:,.6f} (P8.54 MF=0.30 re-pin), "
            f"got {row['pfe_addon']:,.6f}. "
            "CRR Art. 278: PFE = multiplier * AddOn_aggregate; Art. 280a: SF_IR=0.005."
        )

    def test_ccr_a13_ead(self, ccr_a13_result: dict) -> None:
        """
        EAD = alpha * (RC + PFE) ≈ 1.4 * (2_250_000 + 244_426) ≈ 3_492_196 (MF=0.30 re-pin).

        Arrange: alpha=1.4 (CRR Art. 274(2)), rc_margined=2_250_000, pfe_addon≈244_426 (MF=0.30).
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final approx 3_492_196 (rel tol 1e-6; exp()-dependent).

        NOTE: The exact bytes depend on Polars exp() — engine-implementer must confirm/re-pin
        the CCR-A13.json ead_final value during the P8.54 validation gate.

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["ead_final"]

        # Assert
        assert row["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A13: expected ead_final approx {expected:,.6f} (P8.54 MF=0.30 re-pin), "
            f"got {row['ead_final']:,.6f}. "
            "CRR Art. 274(2): EAD = 1.4 * (rc_margined + PFE(MF=0.30)) ≈ 3_492_196. "
            "Pre-fix engine (MF=1.0): ead_final≈6_464_360."
        )

    def test_ccr_a13_exposure_class(self, ccr_a13_result: dict) -> None:
        """
        Classifier routes CP_001 (entity_type='institution') to exposure_class 'institution'.

        Arrange: CP_001 entity_type='institution', GB, CQS 2.
        Act:     full CRR SA+CCR pipeline.
        Assert:  exposure_class == 'institution' (case-insensitive).

        References: CRR Art. 112(b) — institution exposure class.
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["exposure_class"]

        # Assert
        assert row["exposure_class"].lower() == expected.lower(), (
            f"CCR-A13: expected exposure_class={expected!r}, "
            f"got {row['exposure_class']!r}. "
            "CRR Art. 112(b): institution entity_type -> institution exposure class."
        )

    def test_ccr_a13_rwa(self, ccr_a13_result: dict) -> None:
        """
        RWA = EAD * RW ≈ 3_492_196 * 0.50 ≈ 1_746_098 (MF=0.30 re-pin).

        Arrange: EAD≈3_492_196 (P8.54 MF=0.30), institution CQS 2 -> RW=50% (CRR Art. 120(1)).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 1_746_098 (rel tol 1e-6; exp()-dependent).

        NOTE: The exact bytes depend on Polars exp() — engine-implementer must confirm/re-pin
        the CCR-A13.json rwa_final value during the P8.54 validation gate.

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 -> 50% risk weight.
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["rwa_final"]

        # Assert
        assert row["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A13: expected rwa_final approx {expected:,.6f} (P8.54 MF=0.30 re-pin), "
            f"got {row['rwa_final']:,.6f}. "
            "RWA = EAD * RW ≈ 3_492_196 * 0.50 ≈ 1_746_098 (CRR Art. 120(1) Table 3, CQS 2). "
            "Pre-fix engine (MF=1.0): rwa_final≈3_232_180."
        )
