"""
CCR-A7: single 2-year GBP oil forward, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (commodity branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate commodity adjusted notional per CRR Art. 279b(1)(c):
  d = market_price × number_of_units = 50.0 × 20_000.0 = 1_000_000.0 GBP.
- Validate commodity PFE add-on per Art. 277a(1) + Art. 280 Table 2:
  SF_CM[OIL_GAS] = 0.18; AddOn = 0.18 × 1_000_000.0 = 180_000.0.
- Validate EAD = alpha × (RC + PFE) = 1.4 × 180_000.0 = 252_000.0.
- Validate SA risk weight lookup for CQS-2 institution (50%, CRR Art. 120(1) Table 3).
- Validate RWA = EAD × RW = 252_000.0 × 0.50 = 126_000.0.

Scenario:
    Trade T_CO_OIL_001 (2y GBP oil forward, buy 20,000 bbl at GBP 50/bbl, MtM=0,
    delta=1), netting set NS_CO_001 (CP_001 institution CQS 2, enforceable, unmargined),
    no collateral.

Hand-calculation reference (see golden_ccr_a7.py docstring for full derivation):
    d          = 50.0 × 20_000.0 = 1_000_000.0 GBP   Art. 279b(1)(c)
    MF         = sqrt(min(1.998630, 1) / 1) = 1.0     Art. 279c(1)
    e          = 1.0 × 1_000_000.0 × 1.0 = 1_000_000.0
    AddOn      = 0.18 × 1_000_000.0 = 180_000.0       Art. 280 Table 2
    RC         = max(0 - 0, 0) = 0                     Art. 275(1)
    PFE_mult   = 1.0 (V=C=0)                           Art. 278(3)
    PFE_addon  = 1.0 × 180_000.0 = 180_000.0          Art. 278(1)
    EAD        = 1.4 × 180_000.0 = 252_000.0          Art. 274(2)
    RW         = 0.50                                  Art. 120(1) Table 3
    RWA        = 252_000.0 × 0.50 = 126_000.0

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(3)(b): 5 commodity buckets
    - CRR Art. 277a(1): commodity add-on aggregation
    - CRR Art. 278: PFE = multiplier × AddOn_aggregate
    - CRR Art. 279b(1)(c): commodity adjusted notional d = mp × units
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_CM OIL_GAS = 0.18
    - CRR Art. 280c: commodity asset-class add-on
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a7.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A7.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a7 import build_raw_data_bundle_with_ccr_a7

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A7.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A7.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_CO_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a7_result() -> dict:
    """Run CCR-A7 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_raw_data_bundle_with_ccr_a7()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A7: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set for the commodity asset class."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A7 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA7CommodityOilForward:
    """CCR-A7: 2y GBP oil forward, unmargined — six acceptance assertions."""

    def test_ccr_a7_rc(self, ccr_a7_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0."""
        expected = _EXPECTED["rc_unmargined"]
        assert ccr_a7_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A7: expected rc_unmargined={expected} (at-par forward, no collateral), "
            f"got {ccr_a7_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_ccr_a7_addon_aggregate(self, ccr_a7_result: dict) -> None:
        """Commodity add-on = SF_CM[OIL_GAS] × |e| = 0.18 × 1_000_000 = 180_000.0."""
        expected = _EXPECTED["addon_aggregate"]
        assert ccr_a7_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A7: expected addon_aggregate = {expected:,.3f} GBP, "
            f"got {ccr_a7_result['addon_aggregate']:,.3f}. "
            "CRR Art. 277a(1) + Art. 280 Table 2 (SF_CM OIL_GAS = 0.18)."
        )

    def test_ccr_a7_pfe(self, ccr_a7_result: dict) -> None:
        """PFE = multiplier(1.0) × AddOn = 180_000.0 GBP."""
        expected = _EXPECTED["pfe_addon"]
        assert ccr_a7_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A7: expected pfe_addon = {expected:,.3f} GBP, "
            f"got {ccr_a7_result['pfe_addon']:,.3f}. CRR Art. 278."
        )

    def test_ccr_a7_ead(self, ccr_a7_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × 180_000.0 = 252_000.0 GBP."""
        expected = _EXPECTED["ead_final"]
        assert ccr_a7_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A7: expected ead_final = {expected:,.3f} GBP, "
            f"got {ccr_a7_result['ead_final']:,.3f}. CRR Art. 274(2)."
        )

    def test_ccr_a7_exposure_class(self, ccr_a7_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        expected = _EXPECTED["exposure_class"]
        assert ccr_a7_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A7: expected exposure_class={expected!r}, "
            f"got {ccr_a7_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_ccr_a7_rwa(self, ccr_a7_result: dict) -> None:
        """RWA = EAD × RW = 252_000.0 × 0.50 = 126_000.0 GBP."""
        expected = _EXPECTED["rwa_final"]
        assert ccr_a7_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A7: expected rwa_final = {expected:,.3f} GBP, "
            f"got {ccr_a7_result['rwa_final']:,.3f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )
