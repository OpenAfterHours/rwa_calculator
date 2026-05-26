"""
CCR-A10: five-trade mixed-asset-class netting set — one trade per asset class.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (all five asset-class branches)
    -> Classifier -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate cross-asset-class linear AddOn aggregation per CRR Art. 278(2):
  AddOn_aggregate = AddOn_IR + AddOn_FX + AddOn_credit + AddOn_equity + AddOn_commodity
                  = 3_914_298.228 + 3_198_904.672 + 2_016_405.972
                    + 15_994_523.295317 + 180_000.0
                  = 25_304_132.167317
- Validate each per-asset-class add-on component matches the existing golden values
  from CCR-A1/A2/A3/A5/A7 via the ``addon_by_asset_class`` struct column.
- Confirm the linear-sum result (~25.3M) is strictly larger than the naive
  sqrt-of-sum-of-squares (~16.69M) — proving Art. 278(2) linear aggregation
  rather than within-class sqrt aggregation.
- Validate EAD = 1.4 × (RC + PFE) = 35_425_785.034244.
- Validate RWA = EAD × 0.50 = 17_712_892.517122 (institution CQS 2).

LOAD-BEARING: the linear-sum pin (addon_aggregate ≈ 25_304_132.167317) is the
discriminating assertion for CRR Art. 278(2).  The naive sqrt-of-sum-of-squares
across all five add-ons would be:
    sqrt(3_914_298² + 3_198_904² + 2_016_405² + 15_994_523² + 180_000²)
  ≈ 16_690_000
The Art. 278(2) linear sum must produce ~25.3M.  A result close to ~16.7M would
indicate the engine incorrectly applied intra-asset-class sqrt aggregation across
classes.

Scenario:
    Five trades in netting set NS_MIX_001, counterparty CP_001 (institution,
    CQS 2, GB), legally enforceable, unmargined, no collateral.  Each trade is
    a clone of the corresponding single-asset CCR-A* scenario so that the
    per-class add-on reproduces the existing golden value.

    | trade_id       | asset_class   | per-class add-on      |
    |----------------|---------------|-----------------------|
    | T_MIX_IR_001   | interest_rate | 3_914_298.228         |
    | T_MIX_FX_001   | fx            | 3_198_904.672         |
    | T_MIX_CR_001   | credit        | 2_016_405.972         |
    | T_MIX_EQ_001   | equity        | 15_994_523.295317     |
    | T_MIX_CO_001   | commodity     | 180_000.0             |

Hand-calculation reference:
    AddOn_aggregate = Σ AddOn_asset_class   (CRR Art. 278(2), linear sum)
                    = 25_304_132.167317
    RC              = max(0 - 0, 0) = 0     (CRR Art. 275(1))
    PFE_multiplier  = 1.0  (V=C=0)         (CRR Art. 278(3))
    PFE_addon       = 1.0 × 25_304_132.167317
    EAD             = 1.4 × 25_304_132.167317 = 35_425_785.034244  (CRR Art. 274(2))
    RW              = 0.50                  (CRR Art. 120(1) Table 3, institution CQS 2)
    RWA             = 35_425_785.034244 × 0.50 = 17_712_892.517122

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(1)-(3): asset-class / hedging-set partition
    - CRR Art. 278(1): PFE = multiplier × AddOn_aggregate
    - CRR Art. 278(2): AddOn_aggregate = linear sum across asset classes
    - CRR Art. 278(3): PFE multiplier floor F = 0.05
    - CRR Art. 279b: adjusted notional — per-asset-class branches
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280-280c: supervisory factors per asset class
    - CRR Art. 120(1) Table 3: institution CQS 2 SA risk weight = 50%
    - BCBS CRE52.20-22: cross-asset-class linear aggregation (no inter-class correlation)
    - tests/fixtures/ccr/golden_ccr_a10.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A10.json: expected values (single source of truth)
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_a10 import build_raw_data_bundle_with_ccr_a10

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A10.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A10.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_MIX_001"

# Anti-degenerate bounds for the load-bearing addon_aggregate assertion.
# The naive sqrt-of-sum-of-squares of the five per-class add-ons would give
# approximately 16_690_000; the correct Art. 278(2) linear sum is ~25_304_132.
_ADDON_LINEAR_SUM_LO: float = 24_000_000.0  # well above the sqrt-of-squares result
_ADDON_LINEAR_SUM_HI: float = 26_000_000.0  # well below any double-counted variant


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a10_result() -> dict:
    """Run CCR-A10 through the CRR SA pipeline; return the synthetic CCR row."""
    # Arrange
    bundle = build_raw_data_bundle_with_ccr_a10()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    # Assert row exists (fixture-level guard — not a test assertion)
    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A10: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set for the mixed-asset-class scenario."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A10 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRA10MixedAssetClass:
    """CCR-A10: five-trade mixed-asset-class netting set, unmargined.

    Load-bearing assertion: cross-asset-class linear-sum aggregation per
    CRR Art. 278(2) yielding addon_aggregate ≈ 25_304_132.167317.
    """

    def test_ccr_a10_rc_unmargined_zero(self, ccr_a10_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0 (CRR Art. 275(1))."""
        # Arrange
        expected = _EXPECTED["rc_unmargined"]
        # Act / Assert
        assert ccr_a10_result["rc_unmargined"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A10: expected rc_unmargined={expected} (zero MtM on all five trades, "
            f"no collateral), got {ccr_a10_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_ccr_a10_addon_aggregate_load_bearing(self, ccr_a10_result: dict) -> None:
        """LOAD-BEARING: AddOn_aggregate ≈ 25_304_132.167317 (Art. 278(2) linear sum).

        The five per-class add-ons must be summed linearly — no inter-class
        correlation — yielding 25_304_132.167317.  The naive sqrt-of-sum-of-squares
        would give ~16_690_000; the linear sum is the discriminating value.
        """
        # Arrange
        expected = _EXPECTED["addon_aggregate"]
        # Act / Assert
        assert ccr_a10_result["addon_aggregate"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A10 LOAD-BEARING: expected addon_aggregate ≈ {expected:,.6f} GBP "
            f"(Art. 278(2) linear sum of 5 per-class add-ons), "
            f"got {ccr_a10_result['addon_aggregate']:,.6f}. "
            "CRR Art. 278(2): AddOn_aggregate = Σ AddOn_asset_class (linear, no cross-class corr)."
        )

    def test_ccr_a10_addon_aggregate_above_sqrt_of_squares(self, ccr_a10_result: dict) -> None:
        """Anti-degenerate: addon_aggregate must be > 24_000_000 (above sqrt-of-squares regime).

        The sqrt of sum-of-squares across the five per-class add-ons would be
        approximately 16_690_000.  A result near 16.7M would indicate the engine
        incorrectly applied intra-asset-class sqrt aggregation across classes instead
        of the Art. 278(2) linear sum.  The correct result must exceed 24_000_000.
        """
        # Arrange
        addon = ccr_a10_result["addon_aggregate"]
        # Act / Assert
        assert addon > _ADDON_LINEAR_SUM_LO, (
            f"CCR-A10 anti-degenerate: addon_aggregate={addon:,.3f} must exceed "
            f"{_ADDON_LINEAR_SUM_LO:,.0f}. "
            "A value near 16_690_000 would indicate incorrect sqrt-of-squares aggregation "
            "across asset classes; CRR Art. 278(2) requires a linear sum."
        )

    def test_ccr_a10_addon_aggregate_below_double_count(self, ccr_a10_result: dict) -> None:
        """Anti-degenerate: addon_aggregate must be < 26_000_000 (no double-counting).

        The correct linear sum is ≈ 25_304_132.  A result above 26_000_000 would
        indicate double-counting of one or more per-class add-ons.
        """
        # Arrange
        addon = ccr_a10_result["addon_aggregate"]
        # Act / Assert
        assert addon < _ADDON_LINEAR_SUM_HI, (
            f"CCR-A10 anti-degenerate: addon_aggregate={addon:,.3f} must be below "
            f"{_ADDON_LINEAR_SUM_HI:,.0f}. "
            "A value above this threshold indicates double-counted add-on contributions."
        )

    def test_ccr_a10_pfe_multiplier_unity(self, ccr_a10_result: dict) -> None:
        """PFE multiplier = 1.0 when V = C = 0 (CRR Art. 278(3) floor not triggered)."""
        # Arrange
        expected = _EXPECTED["pfe_multiplier"]
        # Act / Assert
        assert ccr_a10_result["pfe_multiplier"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A10: expected pfe_multiplier={expected} (all MtM=0, no collateral), "
            f"got {ccr_a10_result['pfe_multiplier']}. CRR Art. 278(3)."
        )

    def test_ccr_a10_pfe_addon(self, ccr_a10_result: dict) -> None:
        """PFE_addon = multiplier × AddOn_aggregate = 1.0 × 25_304_132.167317."""
        # Arrange
        expected = _EXPECTED["pfe_addon"]
        # Act / Assert
        assert ccr_a10_result["pfe_addon"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A10: expected pfe_addon ≈ {expected:,.6f} GBP, "
            f"got {ccr_a10_result['pfe_addon']:,.6f}. CRR Art. 278(1)."
        )

    def test_ccr_a10_ead_ccr(self, ccr_a10_result: dict) -> None:
        """EAD_CCR = alpha × (RC + PFE) = 1.4 × 25_304_132.167317 = 35_425_785.034244."""
        # Arrange
        expected = _EXPECTED["ead_ccr"]
        # Act / Assert
        assert ccr_a10_result["ead_ccr"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A10: expected ead_ccr ≈ {expected:,.6f} GBP, "
            f"got {ccr_a10_result['ead_ccr']:,.6f}. CRR Art. 274(2): EAD = 1.4 × (RC + PFE)."
        )

    def test_ccr_a10_ead_final(self, ccr_a10_result: dict) -> None:
        """EAD_final = EAD_CCR = 35_425_785.034244 GBP (no CRM adjustment)."""
        # Arrange
        expected = _EXPECTED["ead_final"]
        # Act / Assert
        assert ccr_a10_result["ead_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A10: expected ead_final ≈ {expected:,.6f} GBP, "
            f"got {ccr_a10_result['ead_final']:,.6f}. CRR Art. 274(2)."
        )

    def test_ccr_a10_risk_weight(self, ccr_a10_result: dict) -> None:
        """SA risk weight = 0.50 for CQS-2 institution (CRR Art. 120(1) Table 3)."""
        # Arrange
        expected = _EXPECTED["risk_weight"]
        # Act / Assert
        assert ccr_a10_result["risk_weight"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A10: expected risk_weight={expected} (institution CQS 2), "
            f"got {ccr_a10_result['risk_weight']}. CRR Art. 120(1) Table 3."
        )

    def test_ccr_a10_rwa_final(self, ccr_a10_result: dict) -> None:
        """RWA = EAD × RW = 35_425_785.034244 × 0.50 = 17_712_892.517122 GBP."""
        # Arrange
        expected = _EXPECTED["rwa_final"]
        # Act / Assert
        assert ccr_a10_result["rwa_final"] == pytest.approx(expected, rel=1e-6), (
            f"CCR-A10: expected rwa_final ≈ {expected:,.6f} GBP, "
            f"got {ccr_a10_result['rwa_final']:,.6f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, institution CQS 2 = 50%)."
        )

    def test_ccr_a10_addon_by_asset_class_struct_present(self, ccr_a10_result: dict) -> None:
        """Pipeline adapter must surface addon_by_asset_class struct column on the result row.

        Strategy A: assert the ``addon_by_asset_class`` Struct column (or equivalent
        per-class scalar columns) is present on the final exposure row.  This drives
        the engine-implementer to extend pipeline_adapter.py to surface the breakdown.

        The struct must contain keys: interest_rate, fx, credit, equity, commodity.
        """
        # Arrange / Act
        # Assert the column exists on the result row
        assert "addon_by_asset_class" in ccr_a10_result, (
            "CCR-A10: expected 'addon_by_asset_class' struct column on the synthetic CCR "
            "exposure row. The pipeline_adapter must be extended to surface the per-class "
            "add-on breakdown (interest_rate, fx, credit, equity, commodity) so downstream "
            "COREP exports and acceptance tests can reconcile AddOn_aggregate without "
            "re-running the full chain. CRR Art. 278(2)."
        )

    def test_ccr_a10_addon_by_asset_class_ir(self, ccr_a10_result: dict) -> None:
        """Per-class IR add-on = 3_914_298.228 (clone of CCR-A1 golden value)."""
        # Arrange
        expected_breakdown = _EXPECTED["addon_breakdown"]
        breakdown = ccr_a10_result.get("addon_by_asset_class") or {}
        # Act / Assert
        assert breakdown.get("interest_rate") == pytest.approx(
            expected_breakdown["interest_rate"], rel=1e-6
        ), (
            f"CCR-A10: expected addon_by_asset_class['interest_rate'] ≈ "
            f"{expected_breakdown['interest_rate']:,.3f} GBP, got {breakdown.get('interest_rate')}. "
            "Should reproduce the CCR-A1 golden add-on (10y IR swap, 100M GBP notional)."
        )

    def test_ccr_a10_addon_by_asset_class_fx(self, ccr_a10_result: dict) -> None:
        """Per-class FX add-on = 3_198_904.672 (clone of CCR-A2 golden value)."""
        # Arrange
        expected_breakdown = _EXPECTED["addon_breakdown"]
        breakdown = ccr_a10_result.get("addon_by_asset_class") or {}
        # Act / Assert
        assert breakdown.get("fx") == pytest.approx(
            expected_breakdown["fx"], rel=1e-6
        ), (
            f"CCR-A10: expected addon_by_asset_class['fx'] ≈ "
            f"{expected_breakdown['fx']:,.3f} GBP, got {breakdown.get('fx')}. "
            "Should reproduce the CCR-A2 golden add-on (1y USD/GBP forward, 100M USD notional)."
        )

    def test_ccr_a10_addon_by_asset_class_credit(self, ccr_a10_result: dict) -> None:
        """Per-class credit add-on = 2_016_405.972 (clone of CCR-A3 golden value)."""
        # Arrange
        expected_breakdown = _EXPECTED["addon_breakdown"]
        breakdown = ccr_a10_result.get("addon_by_asset_class") or {}
        # Act / Assert
        assert breakdown.get("credit") == pytest.approx(
            expected_breakdown["credit"], rel=1e-6
        ), (
            f"CCR-A10: expected addon_by_asset_class['credit'] ≈ "
            f"{expected_breakdown['credit']:,.3f} GBP, got {breakdown.get('credit')}. "
            "Should reproduce the CCR-A3 golden add-on (5y IG single-name CDS, 100M GBP)."
        )

    def test_ccr_a10_addon_by_asset_class_equity(self, ccr_a10_result: dict) -> None:
        """Per-class equity add-on = 15_994_523.295317 (clone of CCR-A5 golden value)."""
        # Arrange
        expected_breakdown = _EXPECTED["addon_breakdown"]
        breakdown = ccr_a10_result.get("addon_by_asset_class") or {}
        # Act / Assert
        assert breakdown.get("equity") == pytest.approx(
            expected_breakdown["equity"], rel=1e-6
        ), (
            f"CCR-A10: expected addon_by_asset_class['equity'] ≈ "
            f"{expected_breakdown['equity']:,.6f} GBP, got {breakdown.get('equity')}. "
            "Should reproduce the CCR-A5 golden add-on (1y equity TRS, 1M units at GBP 50)."
        )

    def test_ccr_a10_addon_by_asset_class_commodity(self, ccr_a10_result: dict) -> None:
        """Per-class commodity add-on = 180_000.0 (clone of CCR-A7 golden value)."""
        # Arrange
        expected_breakdown = _EXPECTED["addon_breakdown"]
        breakdown = ccr_a10_result.get("addon_by_asset_class") or {}
        # Act / Assert
        assert breakdown.get("commodity") == pytest.approx(
            expected_breakdown["commodity"], rel=1e-6
        ), (
            f"CCR-A10: expected addon_by_asset_class['commodity'] ≈ "
            f"{expected_breakdown['commodity']:,.3f} GBP, got {breakdown.get('commodity')}. "
            "Should reproduce the CCR-A7 golden add-on (2y OIL_GAS forward, 20k bbl at GBP 50)."
        )

    def test_ccr_a10_addon_breakdown_sums_to_aggregate(self, ccr_a10_result: dict) -> None:
        """Cross-check: sum of per-class add-ons in the struct must equal addon_aggregate.

        Validates internal consistency: the five components in addon_by_asset_class
        must sum to addon_aggregate within floating-point tolerance.
        """
        # Arrange
        breakdown = ccr_a10_result.get("addon_by_asset_class") or {}
        addon_aggregate = ccr_a10_result["addon_aggregate"]
        # Act
        component_sum = sum(
            v for v in breakdown.values() if isinstance(v, int | float) and not math.isnan(v)
        )
        # Assert
        assert component_sum == pytest.approx(addon_aggregate, rel=1e-6), (
            f"CCR-A10: sum of addon_by_asset_class components ({component_sum:,.6f}) "
            f"must equal addon_aggregate ({addon_aggregate:,.6f}). "
            "CRR Art. 278(2): AddOn_aggregate = Σ per-class add-ons."
        )
