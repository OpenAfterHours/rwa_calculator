"""
CCR-A6: 1-year GBP long call on equity index, unmargined — Black-Scholes Phi(d1) path.

Pipeline position:
    Loader -> HierarchyResolver -> CCRAdapter (equity option branch) -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate that the SA-CCR pipeline applies the Black-Scholes Phi(d1) supervisory delta
  (Art. 279a(2)) rather than the linear ±1 delta (Art. 279a(1)) when the trade carries
  option_type="call" with non-null option_strike and option_underlying_price.
- Validate equity adjusted notional per CRR Art. 279b(1)(c):
  d = market_price × number_of_units = 100.0 × 500_000 = 50_000_000 GBP.
- Validate supervisory delta ≈ +Phi(d1) with d1 computed from sigma=0.75 (equity idx),
  T = (maturity - start).days / 365 = 1.0y, P=100, K=110.
- Validate equity PFE add-on per Art. 277a + Art. 280b: SF_IDX=0.20, rho_IDX=0.80
  (single-entity collapse → AddOn = SF × EN).
- Validate EAD = alpha × (RC + PFE) with RC = 0 (at-par, unmargined).
- Validate SA risk weight lookup for CQS-2 institution (50% under CRR
  Art. 120(1) Table 3) — same counterparty stub as CCR-A1.
- Validate anti-degenerate guard: option-delta EAD is materially different (>20%)
  from the would-be linear-delta EAD, confirming the Phi(d1) path is live.

Scenario:
    Trade T_EQ_OPT_001 (1y GBP long call on equity index, market_price=100.0,
    units=500_000, is_index=True, MtM=0, delta=1.0 placeholder),
    netting set NS_EQ_OPT_001 (CP_001, enforceable, unmargined, no collateral).

Hand-calculation reference (see golden_ccr_a6.py docstring for full derivation):
    sigma (equity idx, Art. 279a(2) / BCBS CRE52.47) = 0.75
    T_delta  = (2027-01-15 - 2026-01-15).days / 365 = 1.0  (Art. 279a(2) convention)
    d1       ≈ 0.24791976  (ln(100/110) + 0.5·0.75²·1.0) / (0.75·1.0)
    delta    ≈ +Phi(0.24791976) ≈ +0.59790
    adjusted_notional = 100.0 × 500_000 = 50_000_000 GBP
    MF       = sqrt(365/365.25) ≈ 0.99965771  (unmargined, Art. 279c(1))
    EN       ≈ 0.59790 × 50_000_000 × 0.99965771 ≈ 29_884_854.95 GBP
    AddOn    = 0.20 × EN ≈ 5_976_970.99 GBP  (single-entity collapse, SF=0.20)
    RC       = 0
    PFE_mult = 1.0  (V=C=0, unmargined)
    EAD      ≈ 1.4 × 5_976_970.99 ≈ 8_367_759.39 GBP
    RW       = 0.50  (institution CQS 2, CRR Art. 120(1) Table 3)
    RWA      ≈ 0.50 × 8_367_759.39 ≈ 4_183_879.69 GBP

References:
    - CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 277(2)(d): equity hedging set = one per asset class per NS
    - CRR Art. 279a(2)(a): long call supervisory delta = +Phi(d1)
    - CRR Art. 279b(1)(c): equity adjusted notional d = market_price × units
    - CRR Art. 279c(1): unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 280 Table 2: SF_EQ_IDX = 0.20; supervisory vol sigma = 0.75
    - CRR Art. 280b: rho_IDX = 0.80
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_a6.py: fixture builder
    - tests/expected_outputs/ccr/CCR-A6.json: expected values (single source of truth)
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
from rwa_calc.engine.irb.stats_backend import normal_cdf
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_a6 import (
    CCR_A6_ADJUSTED_NOTIONAL,
    CCR_A6_EXPOSURE_CLASS,
    CCR_A6_MATURITY_DATE,
    CCR_A6_MONETARY_REL_TOLERANCE,
    CCR_A6_MULTIPLIER_ABS_TOLERANCE,
    CCR_A6_OPTION_STRIKE,
    CCR_A6_OPTION_UNDERLYING_PRICE,
    CCR_A6_PFE_MULTIPLIER,
    CCR_A6_RC_UNMARGINED,
    CCR_A6_START_DATE,
    build_ccr_a6_bundle,
)

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-A6.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A6.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_EQ_OPT_001"

# ---------------------------------------------------------------------------
# Live recomputation helpers (computed once at import, used across the class)
# ---------------------------------------------------------------------------

# supervisory_delta.py uses: t_years = (maturity_date - start_date).days / 365
_T_DELTA: float = (CCR_A6_MATURITY_DATE - CCR_A6_START_DATE).days / 365.0
# sigma for "equity" asset class from SA_CCR_OPTION_VOLATILITY_EQUITY_IDX = 0.75
_SIGMA_EQ_IDX: float = 0.75
_D1: float = (
    math.log(CCR_A6_OPTION_UNDERLYING_PRICE / CCR_A6_OPTION_STRIKE)
    + 0.5 * _SIGMA_EQ_IDX**2 * _T_DELTA
) / (_SIGMA_EQ_IDX * math.sqrt(_T_DELTA))

# Phi(d1) computed via the live polars-normal-stats backend — same function
# the engine uses, so both sides use the identical CDF implementation.
_PHI_D1: float = float(
    pl.DataFrame({"d1": [_D1]}).with_columns(normal_cdf(pl.col("d1")).alias("phi"))["phi"][0]
)

# Maturity factor on the 250-business-day basis (Art. 279c(1)):
# MF = sqrt(min(BD, 250) / 250), BD = business_day_count(reporting_date, maturity).
# The 1y option spans ≈ 261 business days (≥ 250), so MF = 1.0.
_BD_MF: int = int(
    pl.DataFrame({"m": [CCR_A6_MATURITY_DATE]}).with_columns(
        pl.business_day_count(pl.lit(date(2026, 1, 15)), pl.col("m")).alias("bd")
    )["bd"][0]
)
_MF: float = math.sqrt(min(_BD_MF, 250) / 250)

# Effective notional = Phi(d1) × adj_notional × MF  (Art. 279a(2) + 279b(1)(c))
_EN: float = _PHI_D1 * CCR_A6_ADJUSTED_NOTIONAL * _MF

# AddOn (single-entity index collapse, Art. 277a + 280b): SF × EN for index
# rho_IDX = 0.80 → sqrt((0.80·EN)² + (1−0.64)·EN²) = EN·sqrt(0.64+0.36) = EN
_SF_IDX: float = 0.20
_RHO_IDX: float = 0.80
_ADDON_AGGREGATE: float = _SF_IDX * math.sqrt((_RHO_IDX * _EN) ** 2 + (1.0 - _RHO_IDX**2) * _EN**2)

# PFE = multiplier × AddOn = 1.0 × AddOn  (Art. 278(1))
_PFE_ADDON: float = _ADDON_AGGREGATE  # multiplier = 1.0

# EAD = alpha × (RC + PFE) = 1.4 × PFE  (Art. 274(2))
_EAD_FINAL: float = 1.4 * _PFE_ADDON

# RWA = EAD × RW  (institution CQS 2 → 50%)
_RWA_FINAL: float = 0.50 * _EAD_FINAL

# Linear-path EAD for the anti-degenerate test (delta=+1.0)
_EN_LINEAR: float = 1.0 * CCR_A6_ADJUSTED_NOTIONAL * _MF
_ADDON_LINEAR: float = _SF_IDX * math.sqrt(
    (_RHO_IDX * _EN_LINEAR) ** 2 + (1.0 - _RHO_IDX**2) * _EN_LINEAR**2
)
_EAD_LINEAR: float = 1.4 * _ADDON_LINEAR


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a6_result() -> dict:
    """Run CCR-A6 through the CRR SA pipeline; return the synthetic CCR row."""
    bundle = build_ccr_a6_bundle()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-A6: expected exactly 1 result row for exposure_reference={_EXPOSURE_REF!r}, "
        f"got {len(rows)}. The CCR pipeline adapter must emit one synthetic row per "
        "netting set even when the asset class is equity."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-A6 acceptance tests
# ---------------------------------------------------------------------------


class TestCCR_A6_EquityIndexOption:
    """CCR-A6: 1y GBP long call on equity index, unmargined — nine acceptance assertions."""

    def test_rc_unmargined_zero(self, ccr_a6_result: dict) -> None:
        """Unmargined RC = max(V - C, 0) = max(0 - 0, 0) = 0.0.

        Arrange: netting set with MtM=0, no collateral.
        Act: pipeline run via ccr_a6_result fixture.
        Assert: rc_unmargined == 0.0 (abs=1e-6).

        References: CRR Art. 275(1).
        """
        expected = CCR_A6_RC_UNMARGINED
        assert ccr_a6_result["rc_unmargined"] == pytest.approx(expected, abs=1e-6), (
            f"CCR-A6: expected rc_unmargined={expected} (at-par option, no collateral), "
            f"got {ccr_a6_result['rc_unmargined']}. CRR Art. 275(1)."
        )

    def test_pfe_multiplier_unity(self, ccr_a6_result: dict) -> None:
        """PFE multiplier = 1.0 (at-par, unmargined, V=C=0).

        Arrange: netting set with MtM=0, no collateral, no margin agreement.
        Act: pipeline run via ccr_a6_result fixture.
        Assert: pfe_multiplier == 1.0 (abs=1e-12).

        References: CRR Art. 278(3).
        """
        expected = CCR_A6_PFE_MULTIPLIER
        assert ccr_a6_result["pfe_multiplier"] == pytest.approx(
            expected, abs=CCR_A6_MULTIPLIER_ABS_TOLERANCE
        ), (
            f"CCR-A6: expected pfe_multiplier={expected}, "
            f"got {ccr_a6_result['pfe_multiplier']!r}. CRR Art. 278(3)."
        )

    def test_supervisory_delta_uses_phi_d1(self, ccr_a6_result: dict) -> None:
        """supervisory_delta ≈ +Phi(d1) ≈ +0.59790 — the option-delta path is wired in.

        Arrange:
            T_delta = (2027-01-15 - 2026-01-15).days / 365 = 1.0.
            sigma = 0.75 (equity index supervisory vol, BCBS CRE52.47).
            d1 ≈ 0.24792 (ln(100/110) + 0.5·0.75²·1.0) / (0.75·1.0).
            Expected: +Phi(0.24792) ≈ +0.59790 (long call, Art. 279a(2)(a)).

        Act: pipeline run via ccr_a6_result fixture; effective_notional back-computed
             from addon_aggregate to infer the implied supervisory_delta.

        Assert: implied supervisory_delta ≈ +0.59790 (abs=1e-4).

        This is the load-bearing assertion that confirms the Phi(d1) path
        replaces the default linear ±1 delta in the CCR pipeline adapter.

        References: CRR Art. 279a(2)(a); BCBS CRE52.42; BCBS CRE52.47.
        """
        # Back-compute the implied delta from the pipeline's addon_aggregate:
        #   addon = SF × EN = SF × delta × adj_notional × MF
        #   => delta = addon / (SF × adj_notional × MF)
        actual_addon = ccr_a6_result["addon_aggregate"]
        implied_delta = actual_addon / (_SF_IDX * CCR_A6_ADJUSTED_NOTIONAL * _MF)
        expected_delta = _PHI_D1
        assert implied_delta == pytest.approx(expected_delta, abs=1e-4), (
            f"CCR-A6: implied supervisory_delta ≈ {implied_delta:.6f} "
            f"(back-computed from addon_aggregate={actual_addon:,.4f}), "
            f"expected ≈ {expected_delta:.6f} (+Phi(d1={_D1:.8f}), sigma=0.75, T=1.0y). "
            "CRR Art. 279a(2)(a): long call -> +Phi(d1). "
            "Likely cause: pipeline_adapter still calls compute_supervisory_delta_linear "
            "instead of compute_supervisory_delta_option."
        )

    def test_addon_aggregate(self, ccr_a6_result: dict) -> None:
        """Equity add-on (index, single-entity collapse) = SF_IDX × EN.

        Arrange:
            EN = Phi(d1) × 50_000_000 × MF  (Art. 279a(2) + 279b(1)(c) + 279c(1)).
            SF_IDX = 0.20, rho_IDX = 0.80 (Art. 280 Table 2 + Art. 280b).
            Single-trade collapse: AddOn = SF × sqrt((rho·EN)² + (1−rho²)·EN²) = SF × EN.
        Act: pipeline run via ccr_a6_result fixture.
        Assert: addon_aggregate ≈ SF × EN (rel=1e-6).

        References: CRR Art. 277a; CRR Art. 280b.
        """
        expected = _ADDON_AGGREGATE
        assert ccr_a6_result["addon_aggregate"] == pytest.approx(
            expected, rel=CCR_A6_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A6: expected addon_aggregate ≈ {expected:,.4f} GBP "
            f"(SF=0.20 × EN={_EN:,.4f}), "
            f"got {ccr_a6_result['addon_aggregate']:,.4f}. "
            "CRR Art. 277a + Art. 280b (SF_IDX=0.20, rho_IDX=0.80; single-entity collapse)."
        )

    def test_pfe_equals_addon(self, ccr_a6_result: dict) -> None:
        """PFE_addon = multiplier(1.0) × AddOn_aggregate.

        Assert: pfe_addon ≈ addon_aggregate (rel=1e-6).

        References: CRR Art. 278(1).
        """
        expected = _PFE_ADDON
        assert ccr_a6_result["pfe_addon"] == pytest.approx(
            expected, rel=CCR_A6_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A6: expected pfe_addon ≈ {expected:,.4f} GBP "
            f"(multiplier=1.0 × addon={_ADDON_AGGREGATE:,.4f}), "
            f"got {ccr_a6_result['pfe_addon']:,.4f}. CRR Art. 278(1)."
        )

    def test_ead_alpha_times_pfe(self, ccr_a6_result: dict) -> None:
        """EAD = alpha × (RC + PFE) = 1.4 × PFE_addon.

        Assert: ead_final ≈ 1.4 × pfe_addon (rel=1e-6).

        References: CRR Art. 274(2).
        """
        expected = _EAD_FINAL
        assert ccr_a6_result["ead_final"] == pytest.approx(
            expected, rel=CCR_A6_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A6: expected ead_final ≈ {expected:,.4f} GBP "
            f"(1.4 × pfe={_PFE_ADDON:,.4f}), "
            f"got {ccr_a6_result['ead_final']:,.4f}. CRR Art. 274(2)."
        )

    def test_exposure_class_institution(self, ccr_a6_result: dict) -> None:
        """Classifier routes CP_001 (institution) to exposure_class 'institution'.

        Assert: exposure_class == 'institution'.

        References: CRR Art. 112(b).
        """
        expected = CCR_A6_EXPOSURE_CLASS
        assert ccr_a6_result["exposure_class"].lower() == expected.lower(), (
            f"CCR-A6: expected exposure_class={expected!r}, "
            f"got {ccr_a6_result['exposure_class']!r}. CRR Art. 112(b)."
        )

    def test_rwa_half_of_ead(self, ccr_a6_result: dict) -> None:
        """RWA = EAD × RW = EAD × 0.50 (institution CQS 2).

        Assert: rwa_final ≈ 0.50 × ead_final (rel=1e-6).

        References: CRR Art. 120(1) Table 3.
        """
        expected = _RWA_FINAL
        assert ccr_a6_result["rwa_final"] == pytest.approx(
            expected, rel=CCR_A6_MONETARY_REL_TOLERANCE
        ), (
            f"CCR-A6: expected rwa_final ≈ {expected:,.4f} GBP "
            f"(EAD={_EAD_FINAL:,.4f} × RW=0.50), "
            f"got {ccr_a6_result['rwa_final']:,.4f}. "
            "RWA = EAD × RW (CRR Art. 120(1) Table 3, CQS 2 institution = 50%)."
        )

    def test_delta_not_linear_one(self, ccr_a6_result: dict) -> None:
        """Anti-degenerate: option-delta EAD is >20% below the linear-delta EAD.

        The linear-delta path uses delta=+1.0, giving:
            EAD_linear = 1.4 × 0.20 × (1.0 × 50_000_000 × MF) ≈ 13_995_207.94 GBP.
        The Black-Scholes Phi(d1) path gives:
            EAD_option ≈ 1.4 × 0.20 × (0.59790 × 50_000_000 × MF) ≈ 8_367_759.39 GBP.

        If the engine silently bypasses the option-delta path (calling
        compute_supervisory_delta_linear instead of compute_supervisory_delta_option),
        ead_final will match _EAD_LINEAR, and this test will catch the regression.

        Assert: |ead_final - _EAD_LINEAR| / max(ead_final, _EAD_LINEAR) > 20%.

        References: CRR Art. 279a(2).
        """
        actual_ead = ccr_a6_result["ead_final"]
        deviation = abs(actual_ead - _EAD_LINEAR) / max(actual_ead, _EAD_LINEAR)
        assert deviation > 0.20, (
            f"CCR-A6 anti-degenerate: ead_final={actual_ead:,.4f} GBP is within 20% "
            f"of the linear-delta EAD={_EAD_LINEAR:,.4f} GBP (deviation={deviation:.2%}). "
            f"Expected option-delta EAD ≈ {_EAD_FINAL:,.4f} GBP (Phi(d1)≈{_PHI_D1:.5f}). "
            "Likely cause: pipeline_adapter calls compute_supervisory_delta_linear "
            "instead of compute_supervisory_delta_option."
        )
