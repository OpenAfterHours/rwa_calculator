"""
CCR-A11 and CCR-A12: SFT EAD via FCCM (CRR Art. 271(2) + Art. 220-223).

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (SFT FCCM branch)
    -> Classifier -> CRMProcessor -> SACalculator -> OutputAggregator

Plan item: P8.38 (line 237) — SA-CCR SFT EAD branch per CRR Art. 271(2)
    and Art. 220-223 FCCM.

Key responsibilities:
- Validate that SFTs (transaction_type="sft") are routed to the FCCM SFT
  branch (Art. 271(2)) rather than the SA-CCR derivative branch (Art. 274).
- Validate the FCCM haircut mechanics:
    H_10 = 0.08 (corp bond CQS 1, residual > 5y, Art. 224 Table 1)
    HE   = H_10 × √(5/10) = 0.05656854249492381 (Art. 224(2)(c) + Art. 226(2))
    E*   = max(0, E·(1+HE) − CVA·(1−HC−HFX))    (Art. 223(5))
- Validate that the synthetic CCR row carries ccr_method="fccm_sft" and
  risk_type="CCR_SFT" (not "sa_ccr" / "CCR_DERIVATIVE").
- Validate cash collateral reduces E* by its full market value (HC_cash=0,
  HFX=0 for same-currency GBP/GBP pair).
- Validate risk weight = 0.50 for institution CQS 2 (CRR Art. 120 Table 3).
- Anti-degenerate pin: A11 EAD must exceed £60m (SFT add-on cannot reuse
  the derivative add-on which produces ~£4m).

Scenarios:
    CCR-A11: GBP 60.7m SFT (corp bond CQS 1, residual 7y), no collateral.
        EAD = E·(1+HE) = 64_133_710.52944188
        RWA = 64_133_710.52944188 × 0.50 = 32_066_855.26472094

    CCR-A12: Same SFT, GBP 60m cash collateral received (HC=0, HFX=0).
        E* = 64_133_710.52944188 − 60_000_000 = 4_133_710.52944188
        EAD = 4_133_710.52944188
        RWA = 4_133_710.52944188 × 0.50 = 2_066_855.26472094

LOAD-BEARING: A11 ead_ccr > 60_000_000 discriminates the SFT FCCM branch
from accidental routing through the SA-CCR derivative formula, which would
produce ead_ccr ≈ 0.0 (no derivative add-on for asset_class="credit" without
a reference-entity delta).

References:
    - CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274.
    - CRR Art. 220(1)(a) — single-CP SFT / master-netting-set scope.
    - CRR Art. 220(3)(a)(i) — standardised supervisory haircuts.
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
    - CRR Art. 224(2)(c) — 5-BD liquidation period floor for SFTs.
    - CRR Art. 224 Table 1 — H_10 = 0.08 (corp bond CQS 1, residual > 5y).
    - CRR Art. 226(2) — H_m = H_10 × √(T_m / 10) haircut scaling.
    - CRR Art. 120 Table 3 — institution CQS 2 → 50% SA risk weight.
    - tests/fixtures/ccr/golden_ccr_a11_a12.py: fixture builder and constants.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_a11_a12 import (
    CCR_A11_A12_CCR_METHOD,
    CCR_A11_A12_RISK_TYPE,
    CCR_A11_EAD,
    CCR_A11_EXPOSURE_REFERENCE,
    CCR_A11_RWA,
    CCR_A12_EAD,
    CCR_A12_EXPOSURE_REFERENCE,
    CCR_A12_RWA,
    build_raw_data_bundle_ccr_a11,
    build_raw_data_bundle_ccr_a12,
)

# ---------------------------------------------------------------------------
# Tolerance — 1 ppm relative, matching other CCR golden tests.
# ---------------------------------------------------------------------------
_REL_TOL: float = 1e-6

# Anti-degenerate bound: A11 EAD must exceed £60m.
# The SFT notional is £60.7m; the FCCM E·(1+HE) formula pushes the result
# above notional.  SA-CCR derivative routing produces ~0.0 for this trade.
_A11_EAD_LOWER_BOUND: float = 60_000_000.0

# Expected SA risk weight for CP_INST_001 (institution, CQS 2).
_EXPECTED_RISK_WEIGHT: float = 0.50

# Collateral delta between A11 and A12 (GBP 60m cash, HC=0, HFX=0).
_COLLATERAL_NET: float = 60_000_000.00


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures — one per scenario.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a11_result() -> dict:
    """
    Run CCR-A11 (uncollateralised SFT) through the CRR SA pipeline.

    Returns the single synthetic CCR netting-set row for NS_SFT_001.

    Arrange:
        - 1 SFT trade (T_SFT_001): transaction_type="sft", asset_class="credit",
          notional GBP 60.7m, corp bond exposure CQS 1 residual 7y, no collateral.
        - 1 netting set (NS_SFT_001): CP_INST_001 (institution, CQS 2, GB),
          legally enforceable, unmargined.
        - CCRConfig.sft_method="fccm" routes SFT trades to Art. 271(2) FCCM.
        - CalculationConfig.crr(), permission_mode=STANDARDISED.

    References:
        CRR Art. 271(2), 223(5), 224 Table 1, 226(2), 120 Table 3.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_a11()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == CCR_A11_EXPOSURE_REFERENCE).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A11: expected exactly 1 result row for "
        f"exposure_reference={CCR_A11_EXPOSURE_REFERENCE!r}, got {len(rows)}. "
        "The CCR pipeline adapter must emit one synthetic row per SFT netting set "
        "via the Art. 271(2) FCCM branch (P8.38 engine step)."
    )
    return rows[0]


@pytest.fixture(scope="module")
def ccr_a12_result() -> dict:
    """
    Run CCR-A12 (GBP 60m cash-collateralised SFT) through the CRR SA pipeline.

    Returns the single synthetic CCR netting-set row for NS_SFT_002.

    Arrange:
        - 1 SFT trade (T_SFT_002): same corp bond exposure as A11.
        - 1 netting set (NS_SFT_002): CP_INST_001, legally enforceable, unmargined.
        - 1 CCR collateral row (COLL_SFT_001): cash GBP 60m received, HC=0, HFX=0.
        - CCRConfig.sft_method="fccm" routes SFT trades to Art. 271(2) FCCM.
        - CalculationConfig.crr(), permission_mode=STANDARDISED.

    References:
        CRR Art. 271(2), 223(5), 224 Table 1, 226(2), 120 Table 3.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_a12()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == CCR_A12_EXPOSURE_REFERENCE).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A12: expected exactly 1 result row for "
        f"exposure_reference={CCR_A12_EXPOSURE_REFERENCE!r}, got {len(rows)}. "
        "The CCR pipeline adapter must emit one synthetic row per SFT netting set "
        "via the Art. 271(2) FCCM branch (P8.38 engine step)."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A11 acceptance tests — uncollateralised SFT.
# ---------------------------------------------------------------------------


class TestCCRA11UncollateralisedSFT:
    """CCR-A11: uncollateralised SFT, FCCM EAD = E·(1+HE).

    Load-bearing assertion: ead_ccr > 60_000_000 discriminates the FCCM SFT
    branch from accidental SA-CCR derivative routing (~0.0 result).
    """

    def test_ccr_a11_ccr_method(self, ccr_a11_result: dict) -> None:
        """ccr_method must be "fccm_sft" (SFT FCCM branch, not "sa_ccr").

        Arrange: SFT trade with CCRConfig.sft_method="fccm".
        Act:     full CRR SA+CCR pipeline.
        Assert:  ccr_method == "fccm_sft".

        References: CRR Art. 271(2) — SFT EAD via FCCM, not Art. 274 SA-CCR.
        """
        # Arrange
        expected = CCR_A11_A12_CCR_METHOD  # "fccm_sft"
        # Assert
        assert ccr_a11_result["ccr_method"] == expected, (
            f"CCR-A11: expected ccr_method={expected!r} (SFT FCCM branch per Art. 271(2)), "
            f"got {ccr_a11_result['ccr_method']!r}. "
            "SFT trades must be routed to Art. 271(2) FCCM, not the SA-CCR Art. 274 path."
        )

    def test_ccr_a11_risk_type(self, ccr_a11_result: dict) -> None:
        """risk_type must be "CCR_SFT" (not "CCR_DERIVATIVE").

        Arrange: SFT trade routed via FCCM.
        Act:     full CRR SA+CCR pipeline.
        Assert:  risk_type == "CCR_SFT".

        References: CRR Art. 271(2) — distinct SFT risk type for COREP reporting.
        """
        # Arrange
        expected = CCR_A11_A12_RISK_TYPE  # "CCR_SFT"
        # Assert
        assert ccr_a11_result["risk_type"] == expected, (
            f"CCR-A11: expected risk_type={expected!r}, "
            f"got {ccr_a11_result['risk_type']!r}. "
            "SFT rows must emit risk_type='CCR_SFT' to distinguish from derivatives."
        )

    def test_ccr_a11_ead_ccr_load_bearing(self, ccr_a11_result: dict) -> None:
        """LOAD-BEARING: ead_ccr must exceed £60m (SFT FCCM, not derivative add-on).

        SA-CCR derivative routing produces ead_ccr ≈ 0.0 for this SFT because
        asset_class="credit" with no reference-entity add-on input yields zero
        add-on.  The FCCM formula E·(1+HE) must produce ≈ £64.1m (> £60m).

        Arrange: SFT notional £60.7m, corp bond CQS 1 7y exposure (HE > 0).
        Act:     full CRR SA+CCR pipeline with FCCM SFT branch enabled.
        Assert:  ead_ccr > 60_000_000.

        References: CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
        """
        # Arrange
        ead = ccr_a11_result["ead_ccr"]
        # Assert
        assert ead > _A11_EAD_LOWER_BOUND, (
            f"CCR-A11 LOAD-BEARING: ead_ccr={ead:,.6f} must exceed "
            f"{_A11_EAD_LOWER_BOUND:,.0f}. "
            "A value near 0.0 indicates the engine routed the SFT through the SA-CCR "
            "derivative branch instead of the Art. 271(2) FCCM SFT branch. "
            "CRR Art. 223(5): E* = E·(1+HE) when no collateral."
        )

    def test_ccr_a11_ead_ccr_exact(self, ccr_a11_result: dict) -> None:
        """ead_ccr = E·(1+HE) = 64_133_710.52944188 (Art. 223(5), no collateral).

        Arrange: E=60_700_000, HE=0.08×√0.5=0.05657, CVA=0 (no collateral).
        Act:     full CRR SA+CCR pipeline with FCCM SFT branch.
        Assert:  ead_ccr ≈ 64_133_710.52944188 (rel tol 1e-6).

        References:
            CRR Art. 223(5): E* = max(0, E·(1+HE) − 0) = E·(1+HE).
            CRR Art. 224(2)(c): 5-BD liquidation period.
            CRR Art. 224 Table 1: H_10=0.08 for corp bond CQS 1, residual > 5y.
            CRR Art. 226(2): H_m = H_10 × √(T_m / 10).
        """
        # Arrange
        expected = CCR_A11_EAD  # 64_133_710.52944188
        # Assert
        assert ccr_a11_result["ead_ccr"] == pytest.approx(expected, rel=_REL_TOL), (
            f"CCR-A11: expected ead_ccr ≈ {expected:,.8f} GBP "
            f"(E·(1+HE) with E=60_700_000, HE=0.05657, no collateral), "
            f"got {ccr_a11_result['ead_ccr']:,.8f}. "
            "CRR Art. 223(5): E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))."
        )

    def test_ccr_a11_sa_ccr_columns_null(self, ccr_a11_result: dict) -> None:
        """SA-CCR derivative columns (rc_unmargined, pfe_addon, pfe_multiplier, addon_aggregate)
        must all be null on an FCCM SFT row — the FCCM path does not produce them.

        Arrange: SFT routed via FCCM.
        Act:     full CRR SA+CCR pipeline.
        Assert:  all four SA-CCR component columns are null.

        References: CRR Art. 271(2) — SFT EAD replaces RC+PFE formula entirely.
        """
        # Assert each SA-CCR component column is null
        for col in ("rc_unmargined", "pfe_addon", "pfe_multiplier", "addon_aggregate"):
            assert ccr_a11_result.get(col) is None, (
                f"CCR-A11: expected {col!r}=null on FCCM SFT row, "
                f"got {ccr_a11_result.get(col)!r}. "
                "SA-CCR derivative columns must be null when the FCCM SFT branch is used "
                "(CRR Art. 271(2): SFT EAD replaces the RC+PFE formula)."
            )

    def test_ccr_a11_risk_weight(self, ccr_a11_result: dict) -> None:
        """SA risk weight = 0.50 for CP_INST_001 (institution, CQS 2).

        Arrange: CP_INST_001 entity_type="institution", CQS=2.
        Act:     full CRR SA+CCR pipeline.
        Assert:  risk_weight == 0.50.

        References: CRR Art. 120 Table 3: institution CQS 2 → 50%.
        """
        # Arrange
        expected = _EXPECTED_RISK_WEIGHT
        # Assert
        assert ccr_a11_result["risk_weight"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A11: expected risk_weight={expected} (institution CQS 2, Art. 120 Table 3), "
            f"got {ccr_a11_result['risk_weight']}."
        )

    def test_ccr_a11_ead_final(self, ccr_a11_result: dict) -> None:
        """ead_final = ead_ccr = 64_133_710.52944188 (no CRM adjustment for SFT).

        Arrange: FCCM EAD already incorporates collateral (zero here); CRM
            does not apply a second haircut.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final ≈ CCR_A11_EAD (rel tol 1e-6).
        """
        # Arrange
        expected = CCR_A11_EAD
        # Assert
        assert ccr_a11_result["ead_final"] == pytest.approx(expected, rel=_REL_TOL), (
            f"CCR-A11: expected ead_final ≈ {expected:,.8f} GBP (= ead_ccr, no CRM), "
            f"got {ccr_a11_result['ead_final']:,.8f}. CRR Art. 271(2)."
        )

    def test_ccr_a11_rwa_final(self, ccr_a11_result: dict) -> None:
        """RWA = EAD × RW = 64_133_710.52944188 × 0.50 = 32_066_855.26472094.

        Arrange: ead_ccr=64_133_710.53, risk_weight=0.50.
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final ≈ 32_066_855.26472094 (rel tol 1e-6).

        References: CRR Art. 120 Table 3: institution CQS 2 → 50%.
        """
        # Arrange
        expected = CCR_A11_RWA  # 32_066_855.26472094
        # Assert
        assert ccr_a11_result["rwa_final"] == pytest.approx(expected, rel=_REL_TOL), (
            f"CCR-A11: expected rwa_final ≈ {expected:,.8f} GBP "
            f"(EAD × 0.50, institution CQS 2), "
            f"got {ccr_a11_result['rwa_final']:,.8f}. "
            "CRR Art. 120(1) Table 3."
        )


# ---------------------------------------------------------------------------
# CCR-A12 acceptance tests — GBP 60m cash-collateralised SFT.
# ---------------------------------------------------------------------------


class TestCCRA12CashCollateralisedSFT:
    """CCR-A12: GBP 60m cash collateral (HC=0, HFX=0), E* = E·(1+HE) − 60m.

    Key check: ead_ccr must reflect the full collateral offset, so the result
    is approximately £4.1m rather than £64.1m (A11) or £0.0 (SA-CCR routing).
    """

    def test_ccr_a12_ccr_method(self, ccr_a12_result: dict) -> None:
        """ccr_method must be "fccm_sft" on the collateralised SFT row too.

        References: CRR Art. 271(2) — both SFT scenarios use FCCM.
        """
        # Arrange
        expected = CCR_A11_A12_CCR_METHOD  # "fccm_sft"
        # Assert
        assert ccr_a12_result["ccr_method"] == expected, (
            f"CCR-A12: expected ccr_method={expected!r}, "
            f"got {ccr_a12_result['ccr_method']!r}. "
            "CRR Art. 271(2) FCCM applies regardless of collateral status."
        )

    def test_ccr_a12_risk_type(self, ccr_a12_result: dict) -> None:
        """risk_type must be "CCR_SFT" on the collateralised SFT row.

        References: CRR Art. 271(2) — SFT risk type.
        """
        # Arrange
        expected = CCR_A11_A12_RISK_TYPE  # "CCR_SFT"
        # Assert
        assert ccr_a12_result["risk_type"] == expected, (
            f"CCR-A12: expected risk_type={expected!r}, got {ccr_a12_result['risk_type']!r}."
        )

    def test_ccr_a12_ead_ccr_exact(self, ccr_a12_result: dict) -> None:
        """ead_ccr = E* = max(0, E·(1+HE) − 60m) = 4_133_710.52944188.

        Arrange: E=60_700_000, HE=0.05657, CVA=60_000_000 (HC=0, HFX=0).
        Act:     full CRR SA+CCR pipeline with FCCM SFT branch.
        Assert:  ead_ccr ≈ 4_133_710.52944188 (rel tol 1e-6).

        References:
            CRR Art. 223(5): E* = max(0, E·(1+HE) − CVA·(1−0−0)).
            CRR Art. 224 Table 1: HC_cash = 0.
        """
        # Arrange
        expected = CCR_A12_EAD  # 4_133_710.52944188
        # Assert
        assert ccr_a12_result["ead_ccr"] == pytest.approx(expected, rel=_REL_TOL), (
            f"CCR-A12: expected ead_ccr ≈ {expected:,.8f} GBP "
            f"(E·(1+HE) − 60m cash collateral, HC=0, HFX=0), "
            f"got {ccr_a12_result['ead_ccr']:,.8f}. "
            "CRR Art. 223(5): CVA·(1−HC−HFX) = 60m × (1−0−0) = 60m."
        )

    def test_ccr_a12_risk_weight(self, ccr_a12_result: dict) -> None:
        """SA risk weight = 0.50 for CP_INST_001 (institution, CQS 2).

        References: CRR Art. 120 Table 3.
        """
        # Arrange
        expected = _EXPECTED_RISK_WEIGHT
        # Assert
        assert ccr_a12_result["risk_weight"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A12: expected risk_weight={expected} (institution CQS 2), "
            f"got {ccr_a12_result['risk_weight']}. CRR Art. 120 Table 3."
        )

    def test_ccr_a12_ead_final(self, ccr_a12_result: dict) -> None:
        """ead_final = ead_ccr = 4_133_710.52944188 (FCCM already net of collateral).

        References: CRR Art. 271(2).
        """
        # Arrange
        expected = CCR_A12_EAD
        # Assert
        assert ccr_a12_result["ead_final"] == pytest.approx(expected, rel=_REL_TOL), (
            f"CCR-A12: expected ead_final ≈ {expected:,.8f} GBP, "
            f"got {ccr_a12_result['ead_final']:,.8f}. CRR Art. 271(2)."
        )

    def test_ccr_a12_rwa_final(self, ccr_a12_result: dict) -> None:
        """RWA = EAD × RW = 4_133_710.52944188 × 0.50 = 2_066_855.26472094.

        References: CRR Art. 120 Table 3: institution CQS 2 → 50%.
        """
        # Arrange
        expected = CCR_A12_RWA  # 2_066_855.26472094
        # Assert
        assert ccr_a12_result["rwa_final"] == pytest.approx(expected, rel=_REL_TOL), (
            f"CCR-A12: expected rwa_final ≈ {expected:,.8f} GBP "
            f"(EAD × 0.50, institution CQS 2), "
            f"got {ccr_a12_result['rwa_final']:,.8f}. "
            "CRR Art. 120(1) Table 3."
        )


# ---------------------------------------------------------------------------
# Cross-scenario anti-degenerate pins.
# ---------------------------------------------------------------------------


class TestCCRA11A12CrossScenarioPins:
    """Cross-scenario consistency checks for CCR-A11 and CCR-A12.

    These tests guard against implementation bugs that affect both scenarios
    simultaneously — e.g., wrong collateral lookup or method dispatch.
    """

    def test_collateral_offset_delta(self, ccr_a11_result: dict, ccr_a12_result: dict) -> None:
        """A11.ead_ccr − A12.ead_ccr must equal the GBP 60m cash collateral exactly.

        Arrange: A11 has no collateral; A12 has GBP 60m cash (HC=0, HFX=0).
        Act:     both pipelines run independently.
        Assert:  (A11_ead_ccr − A12_ead_ccr) ≈ 60_000_000.00 (rel tol 1e-6).

        References:
            CRR Art. 223(5): E* reduces by CVA·(1−HC−HFX) = 60m × 1.0 = 60m.
        """
        # Arrange
        ead_a11 = ccr_a11_result["ead_ccr"]
        ead_a12 = ccr_a12_result["ead_ccr"]
        delta = ead_a11 - ead_a12
        # Assert
        assert delta == pytest.approx(_COLLATERAL_NET, rel=_REL_TOL), (
            f"CCR-A11/A12 cross-scenario: expected A11.ead_ccr − A12.ead_ccr = "
            f"{_COLLATERAL_NET:,.2f} GBP (cash collateral offset, HC=0, HFX=0), "
            f"got {delta:,.6f}. "
            "CRR Art. 223(5): E* drops by the full collateral market value for cash (HC=0)."
        )

    def test_a11_ead_above_lower_bound_anti_degenerate(self, ccr_a11_result: dict) -> None:
        """ANTI-DEGENERATE: A11 ead_ccr must exceed £60m (not ~0 from derivative routing).

        A result near 0.0 would indicate the SFT was mistakenly routed through the
        SA-CCR derivative chain which produces zero add-on for this trade configuration.

        References: CRR Art. 271(2) — SFT uses FCCM; Art. 223(5) — E* = E·(1+HE) > E.
        """
        # Arrange
        ead = ccr_a11_result["ead_ccr"]
        # Assert
        assert ead > _A11_EAD_LOWER_BOUND, (
            f"CCR-A11 ANTI-DEGENERATE: ead_ccr={ead:,.6f} must exceed "
            f"{_A11_EAD_LOWER_BOUND:,.0f} GBP. "
            "A value near 0.0 means the SFT was routed through SA-CCR derivative logic "
            "instead of the Art. 271(2) FCCM branch. "
            "FCCM E* = E·(1+HE) = 60.7m × 1.0566 ≈ 64.1m > 60m."
        )

    def test_both_scenarios_fccm_sft_method(
        self, ccr_a11_result: dict, ccr_a12_result: dict
    ) -> None:
        """Both A11 and A12 must carry ccr_method="fccm_sft".

        References: CRR Art. 271(2) — method tag applies regardless of collateral.
        """
        # Arrange
        expected = CCR_A11_A12_CCR_METHOD
        # Assert
        assert ccr_a11_result["ccr_method"] == expected, (
            f"CCR-A11: ccr_method={ccr_a11_result['ccr_method']!r} != {expected!r}."
        )
        assert ccr_a12_result["ccr_method"] == expected, (
            f"CCR-A12: ccr_method={ccr_a12_result['ccr_method']!r} != {expected!r}."
        )

    def test_both_scenarios_risk_weight_fifty_percent(
        self, ccr_a11_result: dict, ccr_a12_result: dict
    ) -> None:
        """Both A11 and A12 must carry risk_weight=0.50 (institution CQS 2).

        References: CRR Art. 120 Table 3: institution CQS 2 → 50%.
        """
        # Arrange
        expected = _EXPECTED_RISK_WEIGHT
        # Assert
        assert ccr_a11_result["risk_weight"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A11: risk_weight={ccr_a11_result['risk_weight']} != {expected}."
        )
        assert ccr_a12_result["risk_weight"] == pytest.approx(expected, abs=1e-12), (
            f"CCR-A12: risk_weight={ccr_a12_result['risk_weight']} != {expected}."
        )
