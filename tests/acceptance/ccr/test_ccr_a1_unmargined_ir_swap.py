"""
CCR-A1: single 10-year GBP vanilla IR swap, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate SA-CCR replacement cost (RC) for an unmargined netting set with
  MtM = 0 (at-par swap): RC = max(V - C, 0) = max(0 - 0, 0) = 0.0.
- Validate PFE add-on for a 10y GBP IR swap using Art. 278 + Art. 280a.
- Validate EAD = alpha * (RC + PFE_addon) = 1.4 * (0 + PFE_addon).
- Validate SA risk weight lookup for CQS-2 institution (50% under CRR
  Art. 120(1) Table 3).
- Validate RWA = EAD * RW = EAD * 0.50.

Scenario: one trade T_001 (10y GBP IR swap, notional GBP 100m, MtM=0, delta=1),
one netting set NS_001 (CP_001, legally enforceable, unmargined), no CSA, no
collateral.

Hand-calculation reference (CCR-A1 golden values from CCR-A1.json):
    RC     = max(0.0 - 0.0, 0) = 0.0
    PFE    = multiplier(1.0) * addon_aggregate(3,915,128.562) = 3,915,128.562
    EAD    = 1.4 * (0.0 + 3,915,128.562) = 5,481,179.988
    RW     = 0.50  (institution, CQS 2, CRR Art. 120(1) Table 3)
    RWA    = 5,481,179.988 * 0.50 = 2,740,589.994

Note — regression-only test:
    The P8.1-P8.40 CCR engine is already implemented. This test is expected to
    PASS on first run and is retained as a regression pin for the full end-to-end
    CCR pipeline.

References:
    - CRR Art. 274(2): EAD = alpha * (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 278: PFE = multiplier * AddOn_aggregate
    - CRR Art. 280a: IR supervisory factor SF = 0.5%
    - CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a1.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A1.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a1 import build_raw_data_bundle_with_ccr_a1

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A1.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A1.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a1_result() -> dict:
    """
    Run the CCR-A1 bundle through the CRR SA pipeline and return the single
    CCR synthetic row for ccr__NS_001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.

    Arrange:
        - 1 trade (T_001): 10y GBP IR swap, notional GBP 100m, MtM=0, delta=1
        - 1 netting set (NS_001): CP_001, legally enforceable, unmargined
        - CP_001: institution, CQS 2, GB (entity_type="institution")
        - External rating: S&P "A" = CQS 2
        - No CSA, no CCR collateral, no traditional lending
    """
    # Arrange
    bundle = build_raw_data_bundle_with_ccr_a1()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A1: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. "
        "The CCR pipeline adapter (P8.20) must emit one synthetic row per netting set."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A1 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA1UnmarginedIRSwap:
    """
    CCR-A1: 10y GBP IR swap, unmargined — five acceptance assertions.

    Five tests verify:
      - rc_unmargined == 0.0  (RC = max(V - C, 0) = max(0 - 0, 0) = 0)
      - pfe_addon approx 3,915,128.562
      - ead_final approx 5,481,179.988
      - exposure_class == 'institution'
      - rwa_final approx 2,740,589.994

    All expected values are sourced from tests/expected_outputs/ccr/CCR-A1.json.
    """

    def test_ccr_a1_rc(self, ccr_a1_result: dict) -> None:
        """
        Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0.

        Arrange: at-par IR swap (MtM=0), no CCR collateral, unmargined netting set.
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_unmargined == 0.0 (abs tol 1e-6).

        References: CRR Art. 275(1) — RC = max(V - C, 0).
        """
        # Arrange
        row = ccr_a1_result
        expected = _EXPECTED["rc_unmargined"]

        # Assert
        assert row["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A1: expected rc_unmargined={expected} (max(V-C,0) with V=0, C=0), "
            f"got {row['rc_unmargined']}. "
            "CRR Art. 275(1): unmargined RC = max(V - C, 0)."
        )

    def test_ccr_a1_pfe(self, ccr_a1_result: dict) -> None:
        """
        PFE add-on = multiplier * AddOn_aggregate approx 3,915,128.562.

        Arrange: 10y GBP IR swap, notional GBP 100m, PFE multiplier=1.0
                 (no netting benefit, aggregate add-on from Art. 280a SF=0.5%).
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 3,915,128.562 (rel tol 1e-6).

        References:
            CRR Art. 278: PFE = multiplier * AddOn_aggregate.
            CRR Art. 280a: IR supervisory factor SF = 0.5%.
        """
        # Arrange
        row = ccr_a1_result
        expected = _EXPECTED["pfe_addon"]

        # Assert
        assert row["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A1: expected pfe_addon approx {expected:,.3f}, "
            f"got {row['pfe_addon']:,.3f}. "
            "CRR Art. 278: PFE = multiplier * AddOn_aggregate; Art. 280a: SF_IR=0.005."
        )

    def test_ccr_a1_ead(self, ccr_a1_result: dict) -> None:
        """
        EAD = alpha * (RC + PFE) = 1.4 * (0 + 3,915,128.562) = 5,481,179.988.

        Arrange: alpha=1.4 (CRR Art. 274(2)), RC=0.0, PFE=3,915,128.562.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final approx 5,481,179.988 (rel tol 1e-6).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_a1_result
        expected = _EXPECTED["ead_final"]

        # Assert
        assert row["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A1: expected ead_final approx {expected:,.3f}, "
            f"got {row['ead_final']:,.3f}. "
            "CRR Art. 274(2): EAD = 1.4 * (RC + PFE) = 1.4 * (0 + 3_915_128.562)."
        )

    def test_ccr_a1_exposure_class(self, ccr_a1_result: dict) -> None:
        """
        Classifier routes CP_001 (entity_type='institution') to exposure_class 'institution'.

        Arrange: CP_001 entity_type='institution', GB, CQS 2.
        Act:     full CRR SA+CCR pipeline.
        Assert:  exposure_class == 'institution' (case-insensitive).

        References: CRR Art. 112(b) — institution exposure class.
        """
        # Arrange
        row = ccr_a1_result
        expected = _EXPECTED["exposure_class"]

        # Assert
        assert row["exposure_class"].lower() == expected.lower(), (
            f"CCR-A1: expected exposure_class={expected!r}, "
            f"got {row['exposure_class']!r}. "
            "CRR Art. 112(b): institution entity_type -> institution exposure class."
        )

    def test_ccr_a1_rwa(self, ccr_a1_result: dict) -> None:
        """
        RWA = EAD * RW = 5,481,179.988 * 0.50 = 2,740,589.994.

        Arrange: EAD=5,481,179.988, institution CQS 2 -> RW=50% (CRR Art. 120(1) Table 3).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 2,740,589.994 (rel tol 1e-6).

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 -> 50% risk weight.
        """
        # Arrange
        row = ccr_a1_result
        expected = _EXPECTED["rwa_final"]

        # Assert
        assert row["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A1: expected rwa_final approx {expected:,.3f}, "
            f"got {row['rwa_final']:,.3f}. "
            "RWA = EAD * RW = 5_481_179.988 * 0.50 (CRR Art. 120(1) Table 3, CQS 2)."
        )
