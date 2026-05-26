"""
CCR-A3: single 5-year GBP single-name investment-grade CDS, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (credit branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate credit adjusted notional per CRR Art. 279b(1)(a):
  d = N × SD(S, E), S floored at 0.04y, E = 1826/365.25 ≈ 4.998630y.
  d ≈ 100m × 4.383401 ≈ 438,340,123.6 GBP.
- Validate credit PFE add-on per Art. 277a + 280 Table 2:
  SF_SN_IG = 0.0046, rho_SN = 0.50, single-entity collapse → AddOn = 2,016,364.569.
- Validate EAD = alpha × (RC + PFE) = 1.4 × (0 + 2,016,364.569) ≈ 2,822,910.397.
- Validate SA risk weight for CQS-2 institution (50% under CRR Art. 120(1) Table 3).
- Validate RWA = EAD × RW = 2,822,910.397 × 0.50 ≈ 1,411,455.198.

Scenario:
    Trade T_CR_001 (5y GBP single-name IG CDS, notional=100m, MtM=0, delta=1),
    netting set NS_CR_001 (CP_001, enforceable, unmargined),
    no collateral, no margin agreement.

Hand-calculation reference (see golden_ccr_a3.py docstring for full derivation):
    S = max(0, 0.04) = 0.04
    E = 1826 / 365.25 ≈ 4.998630
    SD(0.04, 4.998630) ≈ 4.383401
    d ≈ 438,340,123.6 GBP
    EN = 1.0 × 438,340,123.6 × 1.0 = 438,340,123.6
    AddOn_entity = 0.0046 × 438,340,123.6 = 2,016,364.569
    AddOn_credit_HS = 2,016,364.569  (single-entity collapse)
    RC = 0
    PFE_multiplier = 1.0
    PFE_addon = 2,016,364.569
    EAD = 1.4 × 2,016,364.569 ≈ 2,822,910.397
    RW = 0.50  (institution CQS 2)
    RWA ≈ 1,411,455.198

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V − C, 0)
    - CRR Art. 277(2)(c): one credit hedging set per netting set
    - CRR Art. 277a(1)(b): credit add-on aggregation formula
    - CRR Art. 278: PFE = multiplier × AddOn_aggregate
    - CRR Art. 279b(1)(a): credit/IR adjusted notional via supervisory duration
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_CR_SN_IG = 0.0046
    - CRR Art. 280a: rho = 0.50 single-name credit
    - CRR Art. 120(1) Table 3: institution CQS 2 SA risk weight = 50%
    - tests/fixtures/ccr/golden_ccr_a3.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A3.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a3 import build_raw_data_bundle_with_ccr_a3

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A3.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A3.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_CR_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a3_result() -> dict:
    """Run CCR-A3 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_raw_data_bundle_with_ccr_a3()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A3: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set even when the asset class is credit."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A3 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA3UnmarginedCreditCDS:
    """CCR-A3: 5y GBP single-name IG CDS, unmargined — six acceptance assertions."""

    def test_ccr_a3_rc(self, ccr_a3_result: dict) -> None:
        """Unmargined RC = max(V − C, 0) = max(0 − 0, 0) = 0.0."""
        expected = _EXPECTED["rc_unmargined"]
        assert ccr_a3_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A3: expected rc_unmargined={expected} (at-par CDS, no collateral), "
            f"got {ccr_a3_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_ccr_a3_addon_aggregate(self, ccr_a3_result: dict) -> None:
        """Credit asset-class add-on = SF × |EN| with single-entity collapse."""
        expected = _EXPECTED["addon_aggregate"]
        assert ccr_a3_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A3: expected addon_aggregate ≈ {expected:,.3f} GBP, "
            f"got {ccr_a3_result['addon_aggregate']:,.3f}. "
            "SF_SN_IG=0.0046, EN=438,340,123.6, single-entity collapse. "
            "CRR Art. 277a(1)(b) + Art. 280 Table 2."
        )

    def test_ccr_a3_pfe(self, ccr_a3_result: dict) -> None:
        """PFE = multiplier(1.0) × AddOn ≈ 2,016,364.569 GBP."""
        expected = _EXPECTED["pfe_addon"]
        assert ccr_a3_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A3: expected pfe_addon ≈ {expected:,.3f} GBP, "
            f"got {ccr_a3_result['pfe_addon']:,.3f}. "
            "multiplier=1.0 (V=0, C=0). CRR Art. 278."
        )

    def test_ccr_a3_ead(self, ccr_a3_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × 2,016,364.569 ≈ 2,822,910.397 GBP."""
        expected = _EXPECTED["ead_final"]
        assert ccr_a3_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A3: expected ead_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a3_result['ead_final']:,.3f}. CRR Art. 274(2)."
        )

    def test_ccr_a3_exposure_class(self, ccr_a3_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        expected = _EXPECTED["exposure_class"]
        assert ccr_a3_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A3: expected exposure_class={expected!r}, "
            f"got {ccr_a3_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_ccr_a3_rwa(self, ccr_a3_result: dict) -> None:
        """RWA = EAD × RW = 2,822,910.397 × 0.50 ≈ 1,411,455.198 GBP."""
        expected = _EXPECTED["rwa_final"]
        assert ccr_a3_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A3: expected rwa_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a3_result['rwa_final']:,.3f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )
