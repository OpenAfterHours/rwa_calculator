"""
CCR-A5: single 1-year GBP single-name equity TRS, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (equity branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate equity adjusted notional per CRR Art. 279b(1)(c):
  d = market_price × number_of_units = 50.0 × 1_000_000 = 50_000_000 GBP.
- Validate equity PFE add-on per Art. 277a + Art. 280b: SF_SN × effective_notional
  (single-entity collapse) with SF_SN=0.32 and rho_SN=0.50.
- Validate EAD = alpha × (RC + PFE) with RC = 0 (at-par, unmargined).
- Validate SA risk weight lookup for CQS-2 institution (50% under CRR
  Art. 120(1) Table 3) — same counterparty stub as CCR-A1.
- Validate RWA = EAD × RW.

Scenario:
    Trade T_EQ_001 (1y GBP single-name equity TRS, market_price=50.0,
    units=1_000_000, is_index=False, MtM=0, delta=1.0),
    netting set NS_EQ_001 (CP_001, enforceable, unmargined, no collateral).

Hand-calculation reference (see golden_ccr_a5.py docstring for full derivation):
    adjusted_notional = 50m GBP       (Art. 279b(1)(c): market_price × units)
    MF                = sqrt(365 / 365.25) ≈ 0.99965770
    effective_notional ≈ 49_982_885.30 GBP
    SF_SN = 0.32, rho_SN = 0.50
    AddOn_HS = SF × sqrt((rho × EN)^2 + (1−rho^2) × EN^2) = 0.32 × EN
             ≈ 15_994_523.295317 GBP (single-entity collapse)
    RC                = 0
    PFE_multiplier    = 1.0 (V-C = 0 → exp(0) = 1 → 0.05 + 0.95 = 1.0)
    PFE_addon         ≈ 15_994_523.295317 GBP
    EAD               ≈ 22_392_332.613444 GBP
    RW                = 0.50 (institution, CQS 2, CRR Art. 120(1) Table 3)
    RWA               ≈ 11_196_166.306722 GBP

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(2)(d): equity hedging set = one per asset class per NS
    - CRR Art. 277a + Art. 280b: equity add-on formula
    - CRR Art. 278: PFE = multiplier × AddOn_aggregate
    - CRR Art. 279b(1)(c): equity adjusted notional d = market_price × units
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_EQ_SN = 0.32, SF_EQ_IDX = 0.20
    - CRR Art. 280b: rho_SN = 0.50, rho_IDX = 0.80
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a5.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A5.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a5 import (
    CCR_A5_ADDON_AGGREGATE,
    CCR_A5_EAD_FINAL,
    CCR_A5_EXPOSURE_CLASS,
    CCR_A5_MONETARY_REL_TOLERANCE,
    CCR_A5_MULTIPLIER_ABS_TOLERANCE,
    CCR_A5_PFE_ADDON,
    CCR_A5_PFE_MULTIPLIER,
    CCR_A5_RC_UNMARGINED,
    CCR_A5_RWA_FINAL,
    build_raw_data_bundle_with_ccr_a5,
)

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A5.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A5.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_EQ_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a5_result() -> dict:
    """Run CCR-A5 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_raw_data_bundle_with_ccr_a5()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A5: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set even when the asset class is equity."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A5 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA5UnmarginedEquityTRS:
    """CCR-A5: 1y GBP single-name equity TRS, unmargined — seven acceptance assertions."""

    def test_ccr_a5_rc(self, ccr_a5_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0."""
        expected = CCR_A5_RC_UNMARGINED
        assert ccr_a5_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A5: expected rc_unmargined={expected} (at-par TRS, no collateral), "
            f"got {ccr_a5_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_ccr_a5_addon_aggregate(self, ccr_a5_result: dict) -> None:
        """Equity add-on (single-entity collapse) = SF_SN × EN ≈ 15_994_523.295317 GBP."""
        expected = CCR_A5_ADDON_AGGREGATE
        assert ccr_a5_result["addon_aggregate"] == pytest.approx(
            expected, rel=CCR_A5_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A5: expected addon_aggregate ≈ {expected:,.6f} GBP, "
            f"got {ccr_a5_result['addon_aggregate']:,.6f}. "
            "CRR Art. 277a + Art. 280b (SF_SN=0.32, rho_SN=0.50; single-entity collapse)."
        )

    def test_ccr_a5_pfe_multiplier(self, ccr_a5_result: dict) -> None:
        """PFE multiplier = 1.0 (at-par, unmargined, V=C=0)."""
        expected = CCR_A5_PFE_MULTIPLIER
        assert ccr_a5_result["pfe_multiplier"] == pytest.approx(
            expected, abs=CCR_A5_MULTIPLIER_ABS_TOLERANCE
        ), (
            f"CCR-A5: expected pfe_multiplier={expected}, "
            f"got {ccr_a5_result['pfe_multiplier']!r}. CRR Art. 278(3)."
        )

    def test_ccr_a5_pfe(self, ccr_a5_result: dict) -> None:
        """PFE = multiplier(1.0) × AddOn ≈ 15_994_523.295317 GBP."""
        expected = CCR_A5_PFE_ADDON
        assert ccr_a5_result["pfe_addon"] == pytest.approx(
            expected, rel=CCR_A5_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A5: expected pfe_addon ≈ {expected:,.6f} GBP, "
            f"got {ccr_a5_result['pfe_addon']:,.6f}. CRR Art. 278."
        )

    def test_ccr_a5_ead(self, ccr_a5_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × 15_994_523.295317 ≈ 22_392_332.613444 GBP."""
        expected = CCR_A5_EAD_FINAL
        assert ccr_a5_result["ead_final"] == pytest.approx(
            expected, rel=CCR_A5_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A5: expected ead_final ≈ {expected:,.6f} GBP, "
            f"got {ccr_a5_result['ead_final']:,.6f}. CRR Art. 274(2)."
        )

    def test_ccr_a5_exposure_class(self, ccr_a5_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        expected = CCR_A5_EXPOSURE_CLASS
        assert ccr_a5_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A5: expected exposure_class={expected!r}, "
            f"got {ccr_a5_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_ccr_a5_rwa(self, ccr_a5_result: dict) -> None:
        """RWA = EAD × RW = 22_392_332.613444 × 0.50 ≈ 11_196_166.306722 GBP."""
        expected = CCR_A5_RWA_FINAL
        assert ccr_a5_result["rwa_final"] == pytest.approx(
            expected, rel=CCR_A5_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A5: expected rwa_final ≈ {expected:,.6f} GBP, "
            f"got {ccr_a5_result['rwa_final']:,.6f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )
