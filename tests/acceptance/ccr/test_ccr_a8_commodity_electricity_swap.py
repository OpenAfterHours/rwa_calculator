"""
CCR-A8: single 1-year GBP electricity swap, unmargined, no collateral.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (commodity branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate commodity adjusted notional per CRR Art. 279b(1)(c):
  d = market_price × number_of_units = 25.0 × 40_000.0 = 1_000_000.0 GBP.
- Validate commodity PFE add-on per Art. 277a(1) + Art. 280 Table 2:
  SF_CM[ELECTRICITY] = 0.40 (NOT the 0.18 catch-all);
  MF = sqrt(365/365.25) ≈ 0.999657706; e ≈ 999_657.706;
  AddOn = 0.40 × 999_657.706 ≈ 399_863.080.
- Validate EAD = alpha × (RC + PFE) = 1.4 × 399_863.080 ≈ 559_808.312.
- Validate RWA = 559_808.312 × 0.50 ≈ 279_904.156.

LOAD-BEARING: the ELECTRICITY SF_CM = 0.40 is the discriminating assertion
vs CCR-A7 (OIL_GAS SF_CM = 0.18). With equal adjusted notionals (1_000_000),
the CCR-A8 AddOn is ≈2.22× larger than the CCR-A7 AddOn.

Scenario:
    Trade T_CO_ELEC_001 (1y GBP electricity swap, 40,000 MWh at GBP 25/MWh,
    MtM=0, delta=1), netting set NS_CO_002 (CP_001 institution CQS 2,
    enforceable, unmargined), no collateral.

Hand-calculation reference (see golden_ccr_a8.py docstring for full derivation):
    d          = 25.0 × 40_000.0 = 1_000_000.0 GBP   Art. 279b(1)(c)
    MF         = sqrt(365/365.25) ≈ 0.999657706       Art. 279c(1)
    e          ≈ 999_657.706
    AddOn      = 0.40 × 999_657.706 ≈ 399_863.080     Art. 280 Table 2
    RC         = 0                                     Art. 275(1)
    PFE_mult   = 1.0                                   Art. 278(3)
    PFE_addon  ≈ 399_863.080                           Art. 278(1)
    EAD        ≈ 559_808.312                           Art. 274(2)
    RW         = 0.50                                  Art. 120(1) Table 3
    RWA        ≈ 279_904.156

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(3)(b): 5 commodity buckets
    - CRR Art. 277a(1): commodity add-on aggregation
    - CRR Art. 278: PFE = multiplier × AddOn_aggregate
    - CRR Art. 279b(1)(c): commodity adjusted notional d = mp × units
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_CM ELECTRICITY = 0.40
    - CRR Art. 280c: commodity asset-class add-on
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a8.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A8.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a8 import build_raw_data_bundle_with_ccr_a8

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A8.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A8.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_CO_002"

# CCR-A7 reference for the load-bearing anti-degenerate assertion.
# An engine that collapses ELECTRICITY → 0.18 would produce CCR-A8 RWA ≈ 126_000.
# The threshold below is well above that degenerate value so the assertion
# fails iff the ELECTRICITY SF is wrong.
_CCR_A7_RWA: float = 126_000.0
_CCR_A7_EAD: float = 252_000.0
_DEGENERATE_RWA_THRESHOLD: float = _CCR_A7_EAD * 0.50  # = 126_000.0 (OIL_GAS SF)


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a8_result() -> dict:
    """Run CCR-A8 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_raw_data_bundle_with_ccr_a8()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A8: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set for the commodity asset class."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A8 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA8CommodityElectricitySwap:
    """CCR-A8: 1y GBP electricity swap, unmargined — six acceptance assertions
    plus one load-bearing anti-degenerate assertion for the ELECTRICITY SF."""

    def test_ccr_a8_rc(self, ccr_a8_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0."""
        expected = _EXPECTED["rc_unmargined"]
        assert ccr_a8_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A8: expected rc_unmargined={expected} (at-par swap, no collateral), "
            f"got {ccr_a8_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_ccr_a8_addon_aggregate(self, ccr_a8_result: dict) -> None:
        """Commodity add-on = SF_CM[ELECTRICITY] × |e| ≈ 0.40 × 999_657.706 ≈ 399_863.080."""
        expected = _EXPECTED["addon_aggregate"]
        assert ccr_a8_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A8: expected addon_aggregate ≈ {expected:,.3f} GBP, "
            f"got {ccr_a8_result['addon_aggregate']:,.3f}. "
            "CRR Art. 277a(1) + Art. 280 Table 2 (SF_CM ELECTRICITY = 0.40)."
        )

    def test_ccr_a8_pfe(self, ccr_a8_result: dict) -> None:
        """PFE = multiplier(1.0) × AddOn ≈ 399_863.080 GBP."""
        expected = _EXPECTED["pfe_addon"]
        assert ccr_a8_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A8: expected pfe_addon ≈ {expected:,.3f} GBP, "
            f"got {ccr_a8_result['pfe_addon']:,.3f}. CRR Art. 278."
        )

    def test_ccr_a8_ead(self, ccr_a8_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × 399_863.080 ≈ 559_808.312 GBP."""
        expected = _EXPECTED["ead_final"]
        assert ccr_a8_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A8: expected ead_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a8_result['ead_final']:,.3f}. CRR Art. 274(2)."
        )

    def test_ccr_a8_exposure_class(self, ccr_a8_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        expected = _EXPECTED["exposure_class"]
        assert ccr_a8_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A8: expected exposure_class={expected!r}, "
            f"got {ccr_a8_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_ccr_a8_rwa(self, ccr_a8_result: dict) -> None:
        """RWA = EAD × RW ≈ 559_808.312 × 0.50 ≈ 279_904.156 GBP."""
        expected = _EXPECTED["rwa_final"]
        assert ccr_a8_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A8: expected rwa_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a8_result['rwa_final']:,.3f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )

    def test_electricity_sf_is_distinct_from_other_buckets(
        self, ccr_a8_result: dict
    ) -> None:
        """LOAD-BEARING: ELECTRICITY SF = 0.40 produces RWA strictly greater than
        the degenerate value (126_000.0) that would result if ELECTRICITY were
        incorrectly routed to the 0.18 OIL_GAS catch-all.

        CCR-A7 (OIL_GAS, same adjusted notional 1_000_000) produces RWA = 126_000.0.
        CCR-A8 (ELECTRICITY, same adjusted notional) must produce RWA > 126_000.0.
        Any regression that collapses ELECTRICITY → 0.18 will fail here.
        """
        rwa = ccr_a8_result["rwa_final"]
        assert rwa > _DEGENERATE_RWA_THRESHOLD, (
            f"CCR-A8 LOAD-BEARING: ELECTRICITY SF=0.40 must produce "
            f"rwa_final > {_DEGENERATE_RWA_THRESHOLD:,.3f} (the degenerate OIL_GAS value). "
            f"Got rwa_final={rwa:,.3f}. "
            "A regression collapsing ELECTRICITY → SF=0.18 would produce ≈126_000. "
            "CRR Art. 280 Table 2: ELECTRICITY = 0.40, not 0.18."
        )
