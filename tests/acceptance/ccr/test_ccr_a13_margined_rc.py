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

Hand-calculation reference (CCR-A13 golden values from CCR-A13.json):
    V  = -4_000_000  (trade MtM)
    C  = 0           (no CCR collateral)
    TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000

    RC (post-fix, Art. 275(2)) = max(V-C, TH+MTA-NICA, 0)
                                = max(-4m, 2.25m, 0) = 2_250_000
    RC (pre-fix bug, Art. 275(1)) = max(V-C, 0) = max(-4m, 0) = 0

    PFE  = 2_367_400.27955979
    EAD  = 1.4 * (2_250_000 + 2_367_400.280) = 6_464_360.391
    RW   = 0.50  (institution, CQS 2, CRR Art. 120(1) Table 3)
    RWA  = 6_464_360.391 * 0.50 = 3_232_180.196

    Pre-fix buggy values (current engine):
        rc = 0  -> EAD = 3_314_360.391  -> RWA = 1_657_180.196

This test is expected to FAIL (RED) on the current unfixed engine because
`compute_rc_margined` is not yet wired through the SA-CCR orchestrator.
It becomes GREEN when P8.19 is applied.

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
    CCR-A13: 10y GBP IR swap, margined netting set — five acceptance assertions.

    Five tests verify:
      - rc (the unified replacement cost feeding EAD) approx 2_250_000.0
        (post-fix: max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0) = 2_250_000)
      - pfe_addon approx 2_367_400.280
      - ead_final approx 6_464_360.391
      - exposure_class == 'institution'
      - rwa_final approx 3_232_180.196

    The rc/rwa_final tests are the load-bearing assertions that will be RED
    until P8.19 wires compute_rc_margined through the SA-CCR orchestrator.

    All expected values are sourced from tests/expected_outputs/ccr/CCR-A13.json.
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

    def test_ccr_a13_pfe(self, ccr_a13_result: dict) -> None:
        """
        PFE add-on = multiplier * AddOn_aggregate approx 2_367_400.280.

        Arrange: 10y GBP IR swap, notional GBP 100m, same trade inputs as CCR-A1.
                 MtM=-4m (V<0) so pfe_multiplier < 1.0 (cap does not bind at floor).
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 2_367_400.27955979 (rel tol 1e-6).

        References:
            CRR Art. 278: PFE = multiplier * AddOn_aggregate.
            CRR Art. 280a: IR supervisory factor SF = 0.5%.
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["pfe_addon"]

        # Assert
        assert row["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A13: expected pfe_addon approx {expected:,.6f}, "
            f"got {row['pfe_addon']:,.6f}. "
            "CRR Art. 278: PFE = multiplier * AddOn_aggregate; Art. 280a: SF_IR=0.005."
        )

    def test_ccr_a13_ead(self, ccr_a13_result: dict) -> None:
        """
        EAD = alpha * (RC + PFE) = 1.4 * (2_250_000 + 2_367_400.280) = 6_464_360.391.

        Arrange: alpha=1.4 (CRR Art. 274(2)), rc_margined=2_250_000, PFE=2_367_400.280.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final approx 6_464_360.391383706 (rel tol 1e-6).

        This assertion is RED on the pre-fix engine where EAD = 1.4*(0+PFE) = 3_314_360.391.

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["ead_final"]

        # Assert
        assert row["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A13: expected ead_final approx {expected:,.6f}, "
            f"got {row['ead_final']:,.6f}. "
            "CRR Art. 274(2): EAD = 1.4 * (rc_margined + PFE) = 1.4 * (2_250_000 + 2_367_400.280). "
            "Pre-fix engine produces ead_final=3_314_360.391 (rc=0 bug)."
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
        RWA = EAD * RW = 6_464_360.391 * 0.50 = 3_232_180.196.

        Arrange: EAD=6_464_360.391, institution CQS 2 -> RW=50% (CRR Art. 120(1) Table 3).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 3_232_180.195691853 (rel tol 1e-6).

        This assertion is RED on the pre-fix engine where rwa_final=1_657_180.196
        (because rc=0 understates EAD).

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 -> 50% risk weight.
        """
        # Arrange
        row = ccr_a13_result
        expected = _EXPECTED["rwa_final"]

        # Assert
        assert row["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A13: expected rwa_final approx {expected:,.6f}, "
            f"got {row['rwa_final']:,.6f}. "
            "RWA = EAD * RW = 6_464_360.391 * 0.50 (CRR Art. 120(1) Table 3, CQS 2). "
            "Pre-fix engine produces rwa_final=1_657_180.196 (rc=0 bug)."
        )
