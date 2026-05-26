"""
CCR-A9: three-trade commodity netting set spanning OIL_GAS, METALS, and
ELECTRICITY buckets — exercises cross-bucket sqrt(Σ AddOn_b²) aggregation.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (commodity branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate cross-bucket Art. 280c / CRE52.69 aggregation:
  AddOn_OIL_GAS   = SF_CM[OIL_GAS]   × d_OIL   = 0.18 × 1_000_000 = 180_000.0
  AddOn_METALS    = SF_CM[METALS]     × d_MET   = 0.18 × 2_000_000 = 360_000.0
  AddOn_ELECTRICITY = SF_CM[ELECTRICITY] × d_ELEC = 0.40 × 1_000_000 = 400_000.0
  AddOn_commodity = sqrt(180_000² + 360_000² + 400_000²) ≈ 567_450.441
- Confirm the result strictly between the max single-bucket (400_000) and
  the degenerate linear sum (940_000) — proving partial sqrt diversification.
- Validate EAD = alpha × (RC + PFE) = 1.4 × 567_450.441 ≈ 794_430.617.
- Validate RWA = EAD × 0.50 ≈ 397_215.308 (institution CQS 2, Art. 120(1) Table 3).

LOAD-BEARING: the sqrt(Σ AddOn_b²) cross-bucket pin (567_450.441) is the
discriminating assertion for Art. 280c / CRE52.69.  A naive sum would give
940_000; single-bucket collapse would give 400_000.  Only the square-root
formula yields the correct value.

Scenario:
    Three trades in netting set NS_CO_003, counterparty CP_001 (institution,
    CQS 2, GB), legally enforceable, unmargined, no collateral.  All trades
    carry a 2-year tenor so MF = 1.0 for every trade.

    | trade_id      | commodity_type | d (adjusted notional) |
    |---------------|----------------|-----------------------|
    | T_CO_OIL_002  | OIL_GAS        | 1_000_000.0 GBP       |
    | T_CO_MET_001  | METALS         | 2_000_000.0 GBP       |
    | T_CO_ELEC_002 | ELECTRICITY    | 1_000_000.0 GBP       |

Hand-calculation reference (see golden_ccr_a9.py docstring for full derivation):
    AddOn_OIL_GAS     = 0.18 × 1_000_000.0 = 180_000.0     Art. 280 Table 2
    AddOn_METALS      = 0.18 × 2_000_000.0 = 360_000.0     Art. 280 Table 2
    AddOn_ELECTRICITY = 0.40 × 1_000_000.0 = 400_000.0     Art. 280 Table 2
    AddOn_commodity   = sqrt(180_000² + 360_000² + 400_000²)
                      = sqrt(322_000_000_000)
                      ≈ 567_450.441                         Art. 280c / CRE52.69
    RC                = max(0 - 0, 0) = 0                   Art. 275(1)
    PFE_mult          = 1.0 (V = C = 0)                     Art. 278(3)
    PFE_addon         ≈ 567_450.441                         Art. 278(1)
    EAD               ≈ 794_430.617                         Art. 274(2)
    RW                = 0.50                                Art. 120(1) Table 3
    RWA               ≈ 397_215.308

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(3)(b): 5 commodity buckets
    - CRR Art. 277a(1): commodity add-on aggregation
    - CRR Art. 278: PFE = multiplier × AddOn_aggregate
    - CRR Art. 279b(1)(c): commodity adjusted notional d = mp × units
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_CM OIL_GAS/METALS = 0.18, ELECTRICITY = 0.40
    - CRR Art. 280c: commodity asset-class add-on (sqrt cross-bucket aggregation)
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight
    - BCBS CRE52.67-69: cross-bucket sqrt(Σ AddOn_b²), no cross-bucket correlation
    - tests/fixtures/ccr/golden_ccr_a9.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A9.json: expected values (single source of truth)
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
from tests.fixtures.ccr.golden_ccr_a9 import build_ccr_a9_bundle

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A9.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A9.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_CO_003"

# Anti-degenerate thresholds (see test docstrings below for rationale).
_LINEAR_SUM: float = 940_000.0       # degenerate: simple sum of all three bucket add-ons
_MAX_SINGLE_BUCKET: float = 400_000.0  # degenerate: largest single-bucket add-on (ELECTRICITY)
_DEGENERATE_THRESHOLD: float = 100_000.0  # distance tolerance for anti-degenerate assertions


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a9_result() -> dict:
    """Run CCR-A9 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_ccr_a9_bundle()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A9: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set for the commodity asset class."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A9 acceptance tests
# ---------------------------------------------------------------------------


class TestCCR_A9_CommodityMultiBucket:
    """CCR-A9: 3-trade commodity netting set, unmargined — sqrt cross-bucket
    aggregation per CRR Art. 280c / CRE52.69."""

    def test_rc_unmargined_zero(self, ccr_a9_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0."""
        # Arrange
        expected = _EXPECTED["rc_unmargined"]
        # Act / Assert
        assert ccr_a9_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A9: expected rc_unmargined={expected} (zero MtM, no collateral), "
            f"got {ccr_a9_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_pfe_multiplier_unity(self, ccr_a9_result: dict) -> None:
        """PFE multiplier = 1.0 when V = C = 0 (Art. 278(3) floor not triggered)."""
        # Arrange
        expected = _EXPECTED["pfe_multiplier"]
        # Act / Assert
        assert ccr_a9_result["pfe_multiplier"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A9: expected pfe_multiplier={expected} (V=C=0, no excess collateral), "
            f"got {ccr_a9_result['pfe_multiplier']}. CRR Art. 278(3)."
        )

    def test_addon_aggregate_sqrt_of_squares(self, ccr_a9_result: dict) -> None:
        """LOAD-BEARING: cross-bucket AddOn = sqrt(180_000² + 360_000² + 400_000²)
        ≈ 567_450.441 per CRR Art. 280c / CRE52.69."""
        # Arrange
        expected = _EXPECTED["addon_aggregate"]
        # Act / Assert
        assert ccr_a9_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A9 LOAD-BEARING: expected addon_aggregate ≈ {expected:,.3f} GBP "
            f"(sqrt of sum-of-squares: sqrt(180_000² + 360_000² + 400_000²)), "
            f"got {ccr_a9_result['addon_aggregate']:,.3f}. "
            "CRR Art. 280c + BCBS CRE52.69: cross-bucket aggregation = sqrt(Σ AddOn_b²)."
        )

    def test_addon_not_linear_sum(self, ccr_a9_result: dict) -> None:
        """Anti-degenerate: result must NOT equal the naive linear sum (940_000.0).

        If buckets were summed linearly (no diversification), the result would be
        180_000 + 360_000 + 400_000 = 940_000.  The sqrt-of-squares aggregation
        required by Art. 280c must produce a value strictly less than this.
        """
        # Arrange
        addon = ccr_a9_result["addon_aggregate"]
        # Act / Assert
        assert abs(addon - _LINEAR_SUM) > _DEGENERATE_THRESHOLD, (
            f"CCR-A9 anti-degenerate: addon_aggregate={addon:,.3f} is too close to the "
            f"degenerate linear sum {_LINEAR_SUM:,.0f}. "
            "Art. 280c requires sqrt(Σ AddOn_b²), not a simple sum."
        )

    def test_addon_not_max_bucket_alone(self, ccr_a9_result: dict) -> None:
        """Anti-degenerate: result must NOT collapse to just the largest bucket (400_000.0).

        If the engine only returned the maximum single-bucket add-on (ELECTRICITY,
        400_000), the cross-bucket sqrt aggregation would be absent.  The result
        must be strictly larger than 400_000 by more than the tolerance.
        """
        # Arrange
        addon = ccr_a9_result["addon_aggregate"]
        # Act / Assert
        assert abs(addon - _MAX_SINGLE_BUCKET) > _DEGENERATE_THRESHOLD, (
            f"CCR-A9 anti-degenerate: addon_aggregate={addon:,.3f} is too close to the "
            f"max single-bucket value {_MAX_SINGLE_BUCKET:,.0f}. "
            "Art. 280c must aggregate all buckets, not return only the largest."
        )

    def test_addon_in_sqrt_regime(self, ccr_a9_result: dict) -> None:
        """Strict ordering: max_bucket < addon_aggregate < linear_sum.

        The sqrt-of-squares result must lie strictly between the largest single-bucket
        add-on (400_000) and the degenerate linear sum (940_000), confirming the
        partial-diversification regime of Art. 280c.
        """
        # Arrange
        addon = ccr_a9_result["addon_aggregate"]
        # Act / Assert
        assert _MAX_SINGLE_BUCKET < addon < _LINEAR_SUM, (
            f"CCR-A9: addon_aggregate={addon:,.3f} must satisfy "
            f"{_MAX_SINGLE_BUCKET:,.0f} < addon < {_LINEAR_SUM:,.0f}. "
            "CRR Art. 280c sqrt regime: partial diversification between max bucket and linear sum."
        )

    def test_pfe_addon_equals_aggregate(self, ccr_a9_result: dict) -> None:
        """PFE_addon = multiplier × AddOn_aggregate = 1.0 × 567_450.441 ≈ 567_450.441."""
        # Arrange
        expected = _EXPECTED["pfe_addon"]
        # Act / Assert
        assert ccr_a9_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A9: expected pfe_addon ≈ {expected:,.3f} GBP, "
            f"got {ccr_a9_result['pfe_addon']:,.3f}. CRR Art. 278(1)."
        )

    def test_ead_alpha_times_pfe(self, ccr_a9_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × 567_450.441 ≈ 794_430.617 GBP."""
        # Arrange
        expected = _EXPECTED["ead_final"]
        # Act / Assert
        assert ccr_a9_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A9: expected ead_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a9_result['ead_final']:,.3f}. CRR Art. 274(2): EAD = 1.4 × (RC + PFE)."
        )

    def test_exposure_class_institution(self, ccr_a9_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'."""
        # Arrange
        expected = _EXPECTED["exposure_class"]
        # Act / Assert
        assert ccr_a9_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A9: expected exposure_class={expected!r}, "
            f"got {ccr_a9_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_rwa_half_of_ead(self, ccr_a9_result: dict) -> None:
        """RWA = EAD × 0.50 ≈ 794_430.617 × 0.50 ≈ 397_215.308 GBP."""
        # Arrange
        expected = _EXPECTED["rwa_final"]
        # Act / Assert
        assert ccr_a9_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A9: expected rwa_final ≈ {expected:,.3f} GBP, "
            f"got {ccr_a9_result['rwa_final']:,.3f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, institution CQS 2 = 50%)."
        )
