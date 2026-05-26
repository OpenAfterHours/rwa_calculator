"""
CCR-A2: single 1-year GBP/USD outright FX forward, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (FX branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate FX adjusted notional per CRR Art. 279b(1)(b)(i):
  leg2 is the reporting currency (GBP) → take leg1 (USD 100m) converted at
  spot 0.80 USD->GBP = 80m GBP.
- Validate FX PFE add-on per Art. 277a(2): SF_FX * |D_HS| with one
  hedging set (single GBP/USD currency pair).
- Validate EAD = alpha * (RC + PFE) with RC = 0 (at-par, unmargined).
- Validate SA risk weight lookup for CQS-2 institution (50% under CRR
  Art. 120(1) Table 3) — same counterparty stub as CCR-A1.
- Validate RWA = EAD * RW.

Scenario:
    Trade T_FX_001 (1y GBP/USD outright forward, USD 100m / GBP 80m, MtM=0,
    delta=1), netting set NS_FX_001 (CP_001, enforceable, unmargined),
    fx_rates table with USD->GBP = 0.80.

Hand-calculation reference (see golden_ccr_a2.py docstring for full derivation):
    adjusted_notional = 80m GBP   (Art. 279b(1)(b)(i): take USD leg converted)
    MF                = sqrt(365 / 365.25) ≈ 0.99965770
    effective_notional ≈ 79,972,616.13 GBP
    AddOn_FX          = 0.04 * 79_972_616.13 ≈ 3,198,904.67 GBP
    RC                = 0
    PFE_multiplier    = 1.0 (V-C = 0 → exp(0) = 1 → 0.05 + 0.95 = 1.0)
    PFE_addon         ≈ 3,198,904.67 GBP
    EAD               ≈ 4,478,466.54 GBP
    RW                = 0.50 (institution, CQS 2, CRR Art. 120(1) Table 3)
    RWA               ≈ 2,239,233.27 GBP

References:
    - CRR Art. 274(2): EAD = alpha * (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(3)(a): FX hedging set = currency pair
    - CRR Art. 277a(2): hedging-set add-on = SF * |D_HS|
    - CRR Art. 278: PFE = multiplier * AddOn_aggregate
    - CRR Art. 279b(1)(b)(i): FX adjusted notional, one-leg-is-base case
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 1: SF_FX = 0.04
    - BCBS CRE52.55: FX cross-hedging-set aggregation is a simple sum
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a2.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A2.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a2 import build_raw_data_bundle_with_ccr_a2

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A2.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A2.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_FX_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a2_result() -> dict:
    """Run CCR-A2 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_raw_data_bundle_with_ccr_a2()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A2: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set even when the asset class is FX."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A2 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA2UnmarginedFXForward:
    """CCR-A2: 1y GBP/USD FX forward, unmargined — six acceptance assertions."""

    def test_ccr_a2_rc(self, ccr_a2_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0."""
        expected = _EXPECTED["rc_unmargined"]
        assert ccr_a2_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A2: expected rc_unmargined={expected} (at-par FX forward, no collateral), "
            f"got {ccr_a2_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_ccr_a2_addon_aggregate(self, ccr_a2_result: dict) -> None:
        """FX asset-class add-on = SF_FX * |D_HS| with one hedging set."""
        expected = _EXPECTED["addon_aggregate"]
        assert ccr_a2_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A2: expected addon_aggregate ≈ {expected:,.3f} GBP, "
            f"got {ccr_a2_result['addon_aggregate']:,.3f}. "
            "CRR Art. 277a(2) + 280 Table 1 (SF_FX = 0.04); "
            "BCBS CRE52.55 (FX = single-HS sum)."
        )

    def test_ccr_a2_pfe(self, ccr_a2_result: dict) -> None:
        """PFE = multiplier(1.0) * AddOn ≈ 3,198,904.67 GBP."""
        expected = _EXPECTED["pfe_addon"]
        assert ccr_a2_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A2: expected pfe_addon ≈ {expected:,.3f} GBP, "
            f"got {ccr_a2_result['pfe_addon']:,.3f}. CRR Art. 278."
        )

    def test_ccr_a2_ead(self, ccr_a2_result: dict) -> None:
        """EAD = alpha * (RC + PFE) = 1.4 * 3,198,904.67 ≈ 4,478,466.54 GBP."""
        expected = _EXPECTED["ead_final"]
        assert ccr_a2_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A2: expected ead_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a2_result['ead_final']:,.3f}. CRR Art. 274(2)."
        )

    def test_ccr_a2_exposure_class(self, ccr_a2_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        expected = _EXPECTED["exposure_class"]
        assert ccr_a2_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A2: expected exposure_class={expected!r}, "
            f"got {ccr_a2_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_ccr_a2_rwa(self, ccr_a2_result: dict) -> None:
        """RWA = EAD * RW ≈ 4,478,466.54 * 0.50 ≈ 2,239,233.27 GBP."""
        expected = _EXPECTED["rwa_final"]
        assert ccr_a2_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A2: expected rwa_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a2_result['rwa_final']:,.3f}. "
            "RWA = EAD * RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )
