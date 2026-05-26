"""
CCR-A4: single 5-year GBP credit-index (iTraxx Europe S40) IG CDS, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (credit branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate credit adjusted notional per CRR Art. 279b(1)(a):
  d = N × SD(S, E), S floored at 0.04y, E = 1826/365.25 ≈ 4.9993155y.
  d ≈ 100m × 4.3834912427 ≈ 438,349,124.271 GBP.
- Validate credit PFE add-on per Art. 277a + 280 Table 2:
  SF_IDX_IG = 0.0038 (NOT SF_SN_IG=0.0046 used in CCR-A3), rho_IDX=0.80.
  Single-entity collapse → AddOn = 1,665,726.672 GBP.
- Validate EAD = alpha × (RC + PFE) = 1.4 × (0 + 1,665,726.672) ≈ 2,332,017.341 GBP.
- Validate SA risk weight for CQS-2 institution (50% under CRR Art. 120(1) Table 3).
- Validate RWA = EAD × RW = 2,332,017.341 × 0.50 ≈ 1,166,008.670 GBP.

Scenario:
    Trade T_CR_002 (5y GBP credit-index IG CDS, notional=100m, MtM=0, delta=1, is_index=True),
    netting set NS_CR_002 (CP_001, enforceable, unmargined),
    no collateral, no margin agreement.

Hand-calculation reference (see golden_ccr_a4.py docstring for full derivation):
    S = max(0, 0.04) = 0.04
    E = 1826 / 365.25 ≈ 4.9993155
    SD(0.04, 4.9993155) ≈ 4.3834912427
    d ≈ 438,349,124.271 GBP
    EN = 1.0 × 438,349,124.271 × 1.0 = 438,349,124.271
    SF_IDX_IG = 0.0038 (credit index, Art. 280 Table 2)
    rho_IDX   = 0.80   (credit index, Art. 280a)
    AddOn_entity = 0.0038 × 438,349,124.271 = 1,665,726.672
    AddOn_credit_HS = 1,665,726.672  (single-entity collapse)
    RC = 0
    PFE_multiplier = 1.0
    PFE_addon = 1,665,726.672
    EAD = 1.4 × 1,665,726.672 ≈ 2,332,017.341
    RW = 0.50  (institution CQS 2)
    RWA ≈ 1,166,008.670

Key distinction from CCR-A3 (single-name):
    CCR-A3 uses is_index=False → SF=0.0046, rho=0.50 → AddOn ≈ 2,016,364.569
    CCR-A4 uses is_index=True  → SF=0.0038, rho=0.80 → AddOn ≈ 1,665,726.672
    The is_index flag is the load-bearing difference.

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V − C, 0)
    - CRR Art. 277(2)(c): one credit hedging set per netting set
    - CRR Art. 277a(1)(b): credit add-on aggregation formula
    - CRR Art. 278: PFE = multiplier × AddOn_aggregate
    - CRR Art. 279b(1)(a): credit/IR adjusted notional via supervisory duration
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_CR_IDX_IG = 0.0038 (index row)
    - CRR Art. 280a: rho_IDX = 0.80 credit index correlation
    - CRR Art. 120(1) Table 3: institution CQS 2 SA risk weight = 50%
    - tests/fixtures/ccr/golden_ccr_a4.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A4.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a4 import build_ccr_a4_bundle

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A4.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A4.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_CR_002"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a4_result() -> dict:
    """Run CCR-A4 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_ccr_a4_bundle()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A4: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set even when the asset class is credit."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A4 acceptance tests
# ---------------------------------------------------------------------------


class TestCCR_A4_CreditIndexCDS:
    """CCR-A4: 5y GBP credit-index IG CDS, unmargined — six acceptance assertions."""

    def test_rc_unmargined_zero(self, ccr_a4_result: dict) -> None:
        """Unmargined RC = max(V − C, 0) = max(0 − 0, 0) = 0.0."""
        expected = _EXPECTED["rc_unmargined"]
        assert ccr_a4_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A4: expected rc_unmargined={expected} (at-par CDS, no collateral), "
            f"got {ccr_a4_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_addon_aggregate_index_supervisory_factor(self, ccr_a4_result: dict) -> None:
        """Credit index add-on = SF_IDX_IG × |EN| = 0.0038 × 438,349,124.271 ≈ 1,665,726.672.

        Load-bearing pin — proves SF_CR_IDX=0.0038 was used (credit index row of Art. 280
        Table 2), not SF_CR_SN=0.0046 (single-name row used in CCR-A3).
        """
        expected = _EXPECTED["addon_aggregate"]
        assert ccr_a4_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A4: expected addon_aggregate ≈ {expected:,.3f} GBP, "
            f"got {ccr_a4_result['addon_aggregate']:,.3f}. "
            "SF_IDX_IG=0.0038 (Art. 280 Table 2 index row), EN=438,349,124.271, "
            "single-entity collapse. CRR Art. 277a(1)(b) + Art. 280 Table 2."
        )

    def test_pfe_addon_equals_aggregate(self, ccr_a4_result: dict) -> None:
        """PFE = multiplier(1.0) × AddOn ≈ 1,665,726.672 GBP."""
        expected = _EXPECTED["pfe_addon"]
        assert ccr_a4_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A4: expected pfe_addon ≈ {expected:,.3f} GBP, "
            f"got {ccr_a4_result['pfe_addon']:,.3f}. "
            "multiplier=1.0 (V=0, C=0). CRR Art. 278."
        )

    def test_ead_alpha_times_pfe(self, ccr_a4_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × 1,665,726.672 ≈ 2,332,017.341 GBP."""
        expected = _EXPECTED["ead_final"]
        assert ccr_a4_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A4: expected ead_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a4_result['ead_final']:,.3f}. CRR Art. 274(2)."
        )

    def test_exposure_class_institution(self, ccr_a4_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        expected = _EXPECTED["exposure_class"]
        assert ccr_a4_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A4: expected exposure_class={expected!r}, "
            f"got {ccr_a4_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_rwa_half_of_ead(self, ccr_a4_result: dict) -> None:
        """RWA = EAD × RW = 2,332,017.341 × 0.50 ≈ 1,166,008.670 GBP."""
        expected = _EXPECTED["rwa_final"]
        assert ccr_a4_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A4: expected rwa_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a4_result['rwa_final']:,.3f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )

    def test_addon_not_single_name(self, ccr_a4_result: dict) -> None:
        """Credit index add-on must NOT equal the CCR-A3 single-name value (SF=0.0046).

        CCR-A3 single-name add-on ≈ 2,016,364.569 (SF_SN_IG=0.0046).
        CCR-A4 credit index add-on ≈ 1,665,726.672 (SF_IDX_IG=0.0038).
        The difference must exceed 100,000 — proving the is_index=True branch was taken.
        """
        addon = ccr_a4_result["addon_aggregate"]
        single_name_value = 2_016_364.569
        assert abs(addon - single_name_value) > 100_000, (
            f"CCR-A4: addon_aggregate={addon:,.3f} is too close to the CCR-A3 single-name "
            f"value {single_name_value:,.3f}. The is_index=True flag must route to "
            "SF_CR_IDX=0.0038 (Art. 280 Table 2 index row), not SF_CR_SN=0.0046. "
            "Difference was less than 100,000 — is_index branch not taken."
        )
