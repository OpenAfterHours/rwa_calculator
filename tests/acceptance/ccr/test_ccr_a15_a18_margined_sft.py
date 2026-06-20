"""
CCR-A15..A18: margined / non-daily SFT EAD via FCCM (CRR Art. 224(2), 226, 285).

Pipeline position:
    Loader -> HierarchyResolver -> ccr_sa_ccr -> sft_fccm (FCCM SFT stage)
    -> Classifier -> CRMProcessor -> SACalculator -> OutputAggregator

Plan item: SFT/FCCM margined extension — END-TO-END acceptance proof that the
FCCM margined / non-daily revaluation branch reproduces the verified hand-calcs
in ``.claude/state/margined-sft-design.md`` at the FINAL RWA (EAD → SA risk
weight → RWA → result row), not just at the haircut unit. The design only
unit-tested the margined / dispute-doubling path; these scenarios prove the full
pipeline.

Shared setup (mirrors CCR-A11/A12 for the counterparty + SA risk weight):
    Counterparty CP_INST_SFT_M01 — institution, external CQS 2, GB ⇒ SA risk
        weight 0.50 (CRR Art. 120(1) Table 3). RWA = E*·0.50 throughout.
    Exposure side: CASH (HE = 0). E = notional = 10,000,000.
    Collateral: govt_bond, CQS 1, residual 0.5y ⇒ H_10 = 0.005
        (CRR Art. 224 Table 1), market_value = 10,000,000. Same currency
        (GBP/GBP, HFX = 0) — except A17 (USD collateral vs GBP exposure).

    E* = max(0, E·(1+HE) − C·(1−H_C−H_FX)) = 10,000,000·(H_C + H_FX)   [HE = 0]

Scenarios (E* / RWA from the design hand-calcs):
    CCR-A15D — unmargined daily repo (anchor, design (i)):
        is_margined=False, remargining_frequency_days=1 ⇒ T_M=5, N_R=1.
        E* = 35,355.3390593268 → RWA = 17,677.6695296634.
    CCR-A15 — unmargined 3-day remargin (design (ii)):
        is_margined=False, remargining_frequency_days=3 ⇒ T_M=5, N_R=3.
        E* = 41,833.0013267044 → RWA = 20,916.5006633522.
    CCR-A16 — margined repo-only N=2 ⇒ MPOR=6 (design (iii)):
        is_margined=True, mpor_floor_category='repo_only',
        remargining_frequency_days=2 ⇒ MPOR=6 (N_R suppressed).
        E* = 38,729.8334620744 → RWA = 19,364.9167310372.
    CCR-A17 — unmargined daily + FX mismatch (design (iv)):
        is_margined=False, remargining_frequency_days=1, collateral USD vs GBP
        exposure ⇒ H_FX = 0.08·√0.5 on top of H_C.
        E* = 601,040.7640085649 → RWA = 300,520.38200428244.
    CCR-A18 — margined repo-only N=2 + dispute-doubling ⇒ MPOR=11:
        is_margined=True, mpor_floor_category='repo_only',
        remargining_frequency_days=2, has_margin_dispute_doubling=True ⇒
        MPOR = 5·2 + 2 − 1 = 11 (N_R suppressed).
        E* = 52,440.44240850769 → RWA = 26,220.221204253845.

Cross-scenario ordering (design ordering (i) < (iii) < (ii)):
    A15D (35,355) < A16 (38,730) < A15 (41,833).
Anti-degenerate pins: every row carries ccr_method='fccm_sft', risk_type=
'CCR_SFT' (never 'sa_ccr' / 'CCR_DERIVATIVE'); EAD is strictly positive (the
collateral never fully offsets the cash exposure once haircut).

References:
    - CRR Art. 220(1)(a) — single-CP SFT / master-netting-set scope.
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − C·(1−H_C−H_FX)).
    - CRR Art. 224(2)(b) — 5-BD repo liquidation period.
    - CRR Art. 224 Table 1 — H_10 = 0.005 (govt_bond CQS 1, 0-1y band).
    - CRR Art. 224 Table 4 — H_FX base 8% (FX mismatch).
    - CRR Art. 226 — H = H_10·√(T_M/10)·√((N_R+T_M−1)/T_M) non-daily scale-up.
    - CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274.
    - CRR Art. 285(2)-(5) — margined MPOR floors / dispute doubling / F+N−1.
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA risk weight.
    - tests/fixtures/ccr/golden_ccr_a15_a18_margined_sft.py — builders + constants.
    - .claude/state/margined-sft-design.md — verified hand-calcs (source of truth).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_a15_a18_margined_sft import (
    CCR_A15_A18_CCR_METHOD,
    CCR_A15_A18_RISK_TYPE,
    CCR_A15_A18_RISK_WEIGHT,
    CCR_A15_EAD,
    CCR_A15_EXPOSURE_REFERENCE,
    CCR_A15_RWA,
    CCR_A15D_EAD,
    CCR_A15D_EXPOSURE_REFERENCE,
    CCR_A15D_RWA,
    CCR_A16_EAD,
    CCR_A16_EXPOSURE_REFERENCE,
    CCR_A16_RWA,
    CCR_A17_EAD,
    CCR_A17_EXPOSURE_REFERENCE,
    CCR_A17_RWA,
    CCR_A18_EAD,
    CCR_A18_EXPOSURE_REFERENCE,
    CCR_A18_RWA,
    build_raw_data_bundle_ccr_a15,
    build_raw_data_bundle_ccr_a15d,
    build_raw_data_bundle_ccr_a16,
    build_raw_data_bundle_ccr_a17,
    build_raw_data_bundle_ccr_a18,
)

# ---------------------------------------------------------------------------
# Tolerance — 1 ppm relative, matching the other CCR golden tests.
# ---------------------------------------------------------------------------
_REL_TOL: float = 1e-6


def _run_scenario(builder, exposure_reference: str, label: str) -> dict:  # type: ignore[no-untyped-def]
    """Run one CCR-A15..A18 SFT bundle through the CRR SA pipeline.

    Returns the single synthetic CCR netting-set row for *exposure_reference*.
    """
    bundle = builder()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"{label}: expected exactly 1 result row for "
        f"exposure_reference={exposure_reference!r}, got {len(rows)}. "
        "The sft_fccm stage must emit one synthetic row per SFT netting set "
        "via the Art. 271(2) FCCM branch."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures — one per scenario.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a15d_result() -> dict:
    """CCR-A15D — unmargined daily repo SFT (regression anchor, design (i))."""
    return _run_scenario(build_raw_data_bundle_ccr_a15d, CCR_A15D_EXPOSURE_REFERENCE, "CCR-A15D")


@pytest.fixture(scope="module")
def ccr_a15_result() -> dict:
    """CCR-A15 — unmargined 3-day remargin SFT (design (ii))."""
    return _run_scenario(build_raw_data_bundle_ccr_a15, CCR_A15_EXPOSURE_REFERENCE, "CCR-A15")


@pytest.fixture(scope="module")
def ccr_a16_result() -> dict:
    """CCR-A16 — margined repo-only N=2 ⇒ MPOR=6 SFT (design (iii))."""
    return _run_scenario(build_raw_data_bundle_ccr_a16, CCR_A16_EXPOSURE_REFERENCE, "CCR-A16")


@pytest.fixture(scope="module")
def ccr_a17_result() -> dict:
    """CCR-A17 — unmargined daily + FX mismatch SFT (design (iv))."""
    return _run_scenario(build_raw_data_bundle_ccr_a17, CCR_A17_EXPOSURE_REFERENCE, "CCR-A17")


@pytest.fixture(scope="module")
def ccr_a18_result() -> dict:
    """CCR-A18 — margined repo-only N=2 + dispute-doubling ⇒ MPOR=11 SFT."""
    return _run_scenario(build_raw_data_bundle_ccr_a18, CCR_A18_EXPOSURE_REFERENCE, "CCR-A18")


# ---------------------------------------------------------------------------
# CCR-A15D — unmargined daily repo (regression anchor, design row (i)).
# ---------------------------------------------------------------------------


class TestCCRA15DUnmarginedDaily:
    """CCR-A15D: unmargined daily repo SFT — T_M=5, N_R=1 (anchor).

    H_C = 0.005·√(5/10)·1.0 ⇒ E* = 10,000,000·H_C = 35,355.3390593268.
    """

    def test_ccr_a15d_ccr_method(self, ccr_a15d_result: dict) -> None:
        """ccr_method must be "fccm_sft" (Art. 271(2) FCCM branch)."""
        assert ccr_a15d_result["ccr_method"] == CCR_A15_A18_CCR_METHOD, (
            f"CCR-A15D: expected ccr_method={CCR_A15_A18_CCR_METHOD!r}, "
            f"got {ccr_a15d_result['ccr_method']!r}."
        )

    def test_ccr_a15d_risk_type(self, ccr_a15d_result: dict) -> None:
        """risk_type must be "CCR_SFT" (not "CCR_DERIVATIVE")."""
        assert ccr_a15d_result["risk_type"] == CCR_A15_A18_RISK_TYPE, (
            f"CCR-A15D: expected risk_type={CCR_A15_A18_RISK_TYPE!r}, "
            f"got {ccr_a15d_result['risk_type']!r}."
        )

    def test_ccr_a15d_ead_ccr_exact(self, ccr_a15d_result: dict) -> None:
        """ead_ccr = E* = 35,355.3390593268 (Art. 223(5), unmargined daily).

        References: CRR Art. 223(5), Art. 224(2)(b) (T_M=5), Art. 226 (N_R=1).
        """
        assert ccr_a15d_result["ead_ccr"] == pytest.approx(CCR_A15D_EAD, rel=_REL_TOL), (
            f"CCR-A15D: expected ead_ccr ≈ {CCR_A15D_EAD:,.10f} "
            f"(10,000,000·0.005·√0.5), got {ccr_a15d_result['ead_ccr']:,.10f}."
        )

    def test_ccr_a15d_risk_weight(self, ccr_a15d_result: dict) -> None:
        """SA risk weight = 0.50 (institution CQS 2, CRR Art. 120 Table 3)."""
        assert ccr_a15d_result["risk_weight"] == pytest.approx(
            CCR_A15_A18_RISK_WEIGHT, abs=1e-12
        ), f"CCR-A15D: expected risk_weight={CCR_A15_A18_RISK_WEIGHT}."

    def test_ccr_a15d_ead_final(self, ccr_a15d_result: dict) -> None:
        """ead_final = ead_ccr = E* (FCCM already net of collateral, no CRM)."""
        assert ccr_a15d_result["ead_final"] == pytest.approx(CCR_A15D_EAD, rel=_REL_TOL), (
            f"CCR-A15D: expected ead_final ≈ {CCR_A15D_EAD:,.10f}, "
            f"got {ccr_a15d_result['ead_final']:,.10f}."
        )

    def test_ccr_a15d_rwa_final(self, ccr_a15d_result: dict) -> None:
        """RWA = E*·0.50 = 17,677.6695296634 (Art. 120 Table 3 CQS 2)."""
        assert ccr_a15d_result["rwa_final"] == pytest.approx(CCR_A15D_RWA, rel=_REL_TOL), (
            f"CCR-A15D: expected rwa_final ≈ {CCR_A15D_RWA:,.10f}, "
            f"got {ccr_a15d_result['rwa_final']:,.10f}."
        )


# ---------------------------------------------------------------------------
# CCR-A15 — unmargined 3-day remargin (design row (ii)).
# ---------------------------------------------------------------------------


class TestCCRA15UnmarginedThreeDayRemargin:
    """CCR-A15: unmargined 3-day remargin SFT — T_M=5, N_R=3.

    H_C = 0.005·√(5/10)·√((3+5−1)/5) ⇒ E* = 41,833.0013267044. The Art. 226
    non-daily scale-up (√1.4) is the only difference from A15D.
    """

    def test_ccr_a15_ccr_method(self, ccr_a15_result: dict) -> None:
        """ccr_method must be "fccm_sft"."""
        assert ccr_a15_result["ccr_method"] == CCR_A15_A18_CCR_METHOD, (
            f"CCR-A15: expected ccr_method={CCR_A15_A18_CCR_METHOD!r}, "
            f"got {ccr_a15_result['ccr_method']!r}."
        )

    def test_ccr_a15_risk_type(self, ccr_a15_result: dict) -> None:
        """risk_type must be "CCR_SFT"."""
        assert ccr_a15_result["risk_type"] == CCR_A15_A18_RISK_TYPE, (
            f"CCR-A15: expected risk_type={CCR_A15_A18_RISK_TYPE!r}, "
            f"got {ccr_a15_result['risk_type']!r}."
        )

    def test_ccr_a15_ead_ccr_exact(self, ccr_a15_result: dict) -> None:
        """ead_ccr = E* = 41,833.0013267044 (Art. 226 non-daily √1.4 scale-up).

        References: CRR Art. 226 — H = H_10·√(T_M/10)·√((N_R+T_M−1)/T_M).
        """
        assert ccr_a15_result["ead_ccr"] == pytest.approx(CCR_A15_EAD, rel=_REL_TOL), (
            f"CCR-A15: expected ead_ccr ≈ {CCR_A15_EAD:,.10f} "
            f"(10,000,000·0.005·√0.5·√1.4), got {ccr_a15_result['ead_ccr']:,.10f}."
        )

    def test_ccr_a15_risk_weight(self, ccr_a15_result: dict) -> None:
        """SA risk weight = 0.50 (institution CQS 2)."""
        assert ccr_a15_result["risk_weight"] == pytest.approx(CCR_A15_A18_RISK_WEIGHT, abs=1e-12), (
            f"CCR-A15: expected risk_weight={CCR_A15_A18_RISK_WEIGHT}."
        )

    def test_ccr_a15_ead_final(self, ccr_a15_result: dict) -> None:
        """ead_final = ead_ccr = E* (no CRM re-haircut)."""
        assert ccr_a15_result["ead_final"] == pytest.approx(CCR_A15_EAD, rel=_REL_TOL), (
            f"CCR-A15: expected ead_final ≈ {CCR_A15_EAD:,.10f}, "
            f"got {ccr_a15_result['ead_final']:,.10f}."
        )

    def test_ccr_a15_rwa_final(self, ccr_a15_result: dict) -> None:
        """RWA = E*·0.50 = 20,916.5006633522."""
        assert ccr_a15_result["rwa_final"] == pytest.approx(CCR_A15_RWA, rel=_REL_TOL), (
            f"CCR-A15: expected rwa_final ≈ {CCR_A15_RWA:,.10f}, "
            f"got {ccr_a15_result['rwa_final']:,.10f}."
        )


# ---------------------------------------------------------------------------
# CCR-A16 — margined repo-only N=2 ⇒ MPOR=6 (design row (iii)).
# ---------------------------------------------------------------------------


class TestCCRA16MarginedMporSix:
    """CCR-A16: margined repo-only N=2 ⇒ MPOR=6 SFT — T_M=6, N_R suppressed.

    H_C = 0.005·√(6/10) ⇒ E* = 38,729.8334620744. The margined branch sets
    T_M = MPOR = F + N − 1 = 5 + 2 − 1 = 6 (Art. 285(5)) and SUPPRESSES the
    Art. 226 non-daily term (N_R=1) because MPOR already encodes the remargin N.
    """

    def test_ccr_a16_ccr_method(self, ccr_a16_result: dict) -> None:
        """ccr_method must be "fccm_sft"."""
        assert ccr_a16_result["ccr_method"] == CCR_A15_A18_CCR_METHOD, (
            f"CCR-A16: expected ccr_method={CCR_A15_A18_CCR_METHOD!r}, "
            f"got {ccr_a16_result['ccr_method']!r}."
        )

    def test_ccr_a16_risk_type(self, ccr_a16_result: dict) -> None:
        """risk_type must be "CCR_SFT"."""
        assert ccr_a16_result["risk_type"] == CCR_A15_A18_RISK_TYPE, (
            f"CCR-A16: expected risk_type={CCR_A15_A18_RISK_TYPE!r}, "
            f"got {ccr_a16_result['risk_type']!r}."
        )

    def test_ccr_a16_ead_ccr_exact(self, ccr_a16_result: dict) -> None:
        """ead_ccr = E* = 38,729.8334620744 (MPOR=6, Art. 285(5)).

        References: CRR Art. 285(2)(a) (F=5), Art. 285(5) (MPOR=F+N−1=6),
        Art. 224(2) (√(6/10) rescale), Art. 226 suppressed (N_R=1).
        """
        assert ccr_a16_result["ead_ccr"] == pytest.approx(CCR_A16_EAD, rel=_REL_TOL), (
            f"CCR-A16: expected ead_ccr ≈ {CCR_A16_EAD:,.10f} "
            f"(10,000,000·0.005·√0.6), got {ccr_a16_result['ead_ccr']:,.10f}."
        )

    def test_ccr_a16_risk_weight(self, ccr_a16_result: dict) -> None:
        """SA risk weight = 0.50 (institution CQS 2)."""
        assert ccr_a16_result["risk_weight"] == pytest.approx(CCR_A15_A18_RISK_WEIGHT, abs=1e-12), (
            f"CCR-A16: expected risk_weight={CCR_A15_A18_RISK_WEIGHT}."
        )

    def test_ccr_a16_ead_final(self, ccr_a16_result: dict) -> None:
        """ead_final = ead_ccr = E* (no CRM re-haircut)."""
        assert ccr_a16_result["ead_final"] == pytest.approx(CCR_A16_EAD, rel=_REL_TOL), (
            f"CCR-A16: expected ead_final ≈ {CCR_A16_EAD:,.10f}, "
            f"got {ccr_a16_result['ead_final']:,.10f}."
        )

    def test_ccr_a16_rwa_final(self, ccr_a16_result: dict) -> None:
        """RWA = E*·0.50 = 19,364.9167310372."""
        assert ccr_a16_result["rwa_final"] == pytest.approx(CCR_A16_RWA, rel=_REL_TOL), (
            f"CCR-A16: expected rwa_final ≈ {CCR_A16_RWA:,.10f}, "
            f"got {ccr_a16_result['rwa_final']:,.10f}."
        )


# ---------------------------------------------------------------------------
# CCR-A17 — unmargined daily + FX mismatch (design row (iv)).
# ---------------------------------------------------------------------------


class TestCCRA17UnmarginedFxMismatch:
    """CCR-A17: unmargined daily + FX mismatch SFT — USD collateral vs GBP.

    H_C  = 0.005·√(5/10); H_FX = 0.08·√(5/10) (Art. 224 Table 4).
    E* = 10,000,000·(H_C + H_FX) = 601,040.7640085649. The FX haircut on the
    USD collateral against the GBP exposure is the dominant term.
    """

    def test_ccr_a17_ccr_method(self, ccr_a17_result: dict) -> None:
        """ccr_method must be "fccm_sft"."""
        assert ccr_a17_result["ccr_method"] == CCR_A15_A18_CCR_METHOD, (
            f"CCR-A17: expected ccr_method={CCR_A15_A18_CCR_METHOD!r}, "
            f"got {ccr_a17_result['ccr_method']!r}."
        )

    def test_ccr_a17_risk_type(self, ccr_a17_result: dict) -> None:
        """risk_type must be "CCR_SFT"."""
        assert ccr_a17_result["risk_type"] == CCR_A15_A18_RISK_TYPE, (
            f"CCR-A17: expected risk_type={CCR_A15_A18_RISK_TYPE!r}, "
            f"got {ccr_a17_result['risk_type']!r}."
        )

    def test_ccr_a17_ead_ccr_exact(self, ccr_a17_result: dict) -> None:
        """ead_ccr = E* = 601,040.7640085649 (H_C + H_FX, Art. 224 Table 4).

        References: CRR Art. 223(5), Art. 224 Table 4 (H_FX base 8%),
        Art. 224(2) (√(5/10) rescale applied to both H_C and H_FX).
        """
        assert ccr_a17_result["ead_ccr"] == pytest.approx(CCR_A17_EAD, rel=_REL_TOL), (
            f"CCR-A17: expected ead_ccr ≈ {CCR_A17_EAD:,.10f} "
            f"(10,000,000·(0.005+0.08)·√0.5), got {ccr_a17_result['ead_ccr']:,.10f}."
        )

    def test_ccr_a17_risk_weight(self, ccr_a17_result: dict) -> None:
        """SA risk weight = 0.50 (institution CQS 2)."""
        assert ccr_a17_result["risk_weight"] == pytest.approx(CCR_A15_A18_RISK_WEIGHT, abs=1e-12), (
            f"CCR-A17: expected risk_weight={CCR_A15_A18_RISK_WEIGHT}."
        )

    def test_ccr_a17_ead_final(self, ccr_a17_result: dict) -> None:
        """ead_final = ead_ccr = E* (no CRM re-haircut)."""
        assert ccr_a17_result["ead_final"] == pytest.approx(CCR_A17_EAD, rel=_REL_TOL), (
            f"CCR-A17: expected ead_final ≈ {CCR_A17_EAD:,.10f}, "
            f"got {ccr_a17_result['ead_final']:,.10f}."
        )

    def test_ccr_a17_rwa_final(self, ccr_a17_result: dict) -> None:
        """RWA = E*·0.50 = 300,520.38200428244."""
        assert ccr_a17_result["rwa_final"] == pytest.approx(CCR_A17_RWA, rel=_REL_TOL), (
            f"CCR-A17: expected rwa_final ≈ {CCR_A17_RWA:,.10f}, "
            f"got {ccr_a17_result['rwa_final']:,.10f}."
        )


# ---------------------------------------------------------------------------
# CCR-A18 — margined repo-only N=2 + dispute-doubling ⇒ MPOR=11.
# ---------------------------------------------------------------------------


class TestCCRA18MarginedDisputeDoubling:
    """CCR-A18: margined repo-only N=2 + dispute-doubling ⇒ MPOR=11 SFT.

    F doubled (Art. 285(4)): MPOR = 5·2 + 2 − 1 = 11. H_C = 0.005·√(11/10) ⇒
    E* = 52,440.44240850769. The design only UNIT-tested this path — this
    scenario proves it end-to-end through the full pipeline to RWA.
    """

    def test_ccr_a18_ccr_method(self, ccr_a18_result: dict) -> None:
        """ccr_method must be "fccm_sft"."""
        assert ccr_a18_result["ccr_method"] == CCR_A15_A18_CCR_METHOD, (
            f"CCR-A18: expected ccr_method={CCR_A15_A18_CCR_METHOD!r}, "
            f"got {ccr_a18_result['ccr_method']!r}."
        )

    def test_ccr_a18_risk_type(self, ccr_a18_result: dict) -> None:
        """risk_type must be "CCR_SFT"."""
        assert ccr_a18_result["risk_type"] == CCR_A15_A18_RISK_TYPE, (
            f"CCR-A18: expected risk_type={CCR_A15_A18_RISK_TYPE!r}, "
            f"got {ccr_a18_result['risk_type']!r}."
        )

    def test_ccr_a18_ead_ccr_exact(self, ccr_a18_result: dict) -> None:
        """ead_ccr = E* = 52,440.44240850769 (MPOR=11 via dispute doubling).

        References: CRR Art. 285(4) (F doubled), Art. 285(5) (MPOR=2F+N−1=11),
        Art. 224(2) (√(11/10) rescale), Art. 226 suppressed (N_R=1).
        """
        assert ccr_a18_result["ead_ccr"] == pytest.approx(CCR_A18_EAD, rel=_REL_TOL), (
            f"CCR-A18: expected ead_ccr ≈ {CCR_A18_EAD:,.10f} "
            f"(10,000,000·0.005·√1.1), got {ccr_a18_result['ead_ccr']:,.10f}."
        )

    def test_ccr_a18_risk_weight(self, ccr_a18_result: dict) -> None:
        """SA risk weight = 0.50 (institution CQS 2)."""
        assert ccr_a18_result["risk_weight"] == pytest.approx(CCR_A15_A18_RISK_WEIGHT, abs=1e-12), (
            f"CCR-A18: expected risk_weight={CCR_A15_A18_RISK_WEIGHT}."
        )

    def test_ccr_a18_ead_final(self, ccr_a18_result: dict) -> None:
        """ead_final = ead_ccr = E* (no CRM re-haircut)."""
        assert ccr_a18_result["ead_final"] == pytest.approx(CCR_A18_EAD, rel=_REL_TOL), (
            f"CCR-A18: expected ead_final ≈ {CCR_A18_EAD:,.10f}, "
            f"got {ccr_a18_result['ead_final']:,.10f}."
        )

    def test_ccr_a18_rwa_final(self, ccr_a18_result: dict) -> None:
        """RWA = E*·0.50 = 26,220.221204253845."""
        assert ccr_a18_result["rwa_final"] == pytest.approx(CCR_A18_RWA, rel=_REL_TOL), (
            f"CCR-A18: expected rwa_final ≈ {CCR_A18_RWA:,.10f}, "
            f"got {ccr_a18_result['rwa_final']:,.10f}."
        )


# ---------------------------------------------------------------------------
# Cross-scenario ordering + anti-degenerate pins.
# ---------------------------------------------------------------------------


class TestCCRA15A18CrossScenarioPins:
    """Cross-scenario consistency checks for CCR-A15..A18.

    Guards against bugs that move all scenarios together (wrong branch dispatch,
    wrong MPOR derivation, collapsed Art. 226 term) — these are invisible to the
    per-scenario absolute assertions but break the relative ordering.
    """

    def test_design_ordering_anchor_lt_margined_lt_remargin(
        self,
        ccr_a15d_result: dict,
        ccr_a16_result: dict,
        ccr_a15_result: dict,
    ) -> None:
        """Design ordering (i) < (iii) < (ii): A15D < A16 < A15 on ead_ccr.

        The MPOR=6 margined repo (A16) sits strictly between the unmargined-daily
        anchor (A15D, T_M=5) and the 3-day-remargin (A15, √1.4 scale-up). A wrong
        margined T_M or a non-suppressed Art. 226 term would break this order.

        References: .claude/state/margined-sft-design.md (ordering (i)<(iii)<(ii)).
        """
        ead_anchor = ccr_a15d_result["ead_ccr"]
        ead_margined = ccr_a16_result["ead_ccr"]
        ead_remargin = ccr_a15_result["ead_ccr"]
        assert ead_anchor < ead_margined < ead_remargin, (
            "CCR-A15..A18 ordering: expected A15D.ead_ccr < A16.ead_ccr < "
            f"A15.ead_ccr (design (i)<(iii)<(ii)), got "
            f"{ead_anchor:,.6f} / {ead_margined:,.6f} / {ead_remargin:,.6f}."
        )

    def test_anchor_equals_design_anchor_value(self, ccr_a15d_result: dict) -> None:
        """A15D ead_ccr equals the design anchor 35,355.3390593268 exactly.

        Back-compat cross-check: margined-but-daily repo-only N=1 ⇒ MPOR=5+1−1=5
        would equal this anchor — the unmargined-daily path must reproduce the
        regression anchor that pins the whole haircut chain.
        """
        assert ccr_a15d_result["ead_ccr"] == pytest.approx(CCR_A15D_EAD, rel=_REL_TOL), (
            f"CCR-A15D anchor: expected ead_ccr ≈ {CCR_A15D_EAD:,.10f}, "
            f"got {ccr_a15d_result['ead_ccr']:,.10f}."
        )

    def test_fx_mismatch_dominates_all_same_currency(
        self,
        ccr_a15d_result: dict,
        ccr_a15_result: dict,
        ccr_a16_result: dict,
        ccr_a17_result: dict,
        ccr_a18_result: dict,
    ) -> None:
        """A17 (FX mismatch) ead_ccr exceeds every same-currency scenario.

        The 8% FX base haircut on the USD collateral dwarfs the 0.5% govt-bond
        H_C, so A17 must be the largest EAD in the family. A silently-zeroed HFX
        (e.g. wrong same-currency shortcut) would collapse A17 onto A15D.

        References: CRR Art. 224 Table 4 — H_FX base 8% on currency mismatch.
        """
        ead_a17 = ccr_a17_result["ead_ccr"]
        others = (
            ccr_a15d_result["ead_ccr"],
            ccr_a15_result["ead_ccr"],
            ccr_a16_result["ead_ccr"],
            ccr_a18_result["ead_ccr"],
        )
        assert all(ead_a17 > o for o in others), (
            f"CCR-A17 FX mismatch: expected ead_ccr={ead_a17:,.6f} to exceed all "
            f"same-currency scenarios {others}. A collapsed HFX would zero the FX term."
        )

    def test_all_scenarios_fccm_sft_method(
        self,
        ccr_a15d_result: dict,
        ccr_a15_result: dict,
        ccr_a16_result: dict,
        ccr_a17_result: dict,
        ccr_a18_result: dict,
    ) -> None:
        """ANTI-DEGENERATE: every scenario carries ccr_method='fccm_sft'.

        A 'sa_ccr' tag would mean the SFT was mis-routed through the Art. 274
        derivative chain (≈0 EAD), not the Art. 271(2) FCCM branch.

        References: CRR Art. 271(2) — SFT EAD via FCCM.
        """
        for label, row in (
            ("A15D", ccr_a15d_result),
            ("A15", ccr_a15_result),
            ("A16", ccr_a16_result),
            ("A17", ccr_a17_result),
            ("A18", ccr_a18_result),
        ):
            assert row["ccr_method"] == CCR_A15_A18_CCR_METHOD, (
                f"CCR-{label}: ccr_method={row['ccr_method']!r} != {CCR_A15_A18_CCR_METHOD!r}."
            )

    def test_all_scenarios_risk_type_ccr_sft(
        self,
        ccr_a15d_result: dict,
        ccr_a15_result: dict,
        ccr_a16_result: dict,
        ccr_a17_result: dict,
        ccr_a18_result: dict,
    ) -> None:
        """ANTI-DEGENERATE: every scenario carries risk_type='CCR_SFT'.

        References: CRR Art. 271(2) — distinct SFT risk type for COREP reporting.
        """
        for label, row in (
            ("A15D", ccr_a15d_result),
            ("A15", ccr_a15_result),
            ("A16", ccr_a16_result),
            ("A17", ccr_a17_result),
            ("A18", ccr_a18_result),
        ):
            assert row["risk_type"] == CCR_A15_A18_RISK_TYPE, (
                f"CCR-{label}: risk_type={row['risk_type']!r} != {CCR_A15_A18_RISK_TYPE!r}."
            )

    def test_all_scenarios_positive_ead(
        self,
        ccr_a15d_result: dict,
        ccr_a15_result: dict,
        ccr_a16_result: dict,
        ccr_a17_result: dict,
        ccr_a18_result: dict,
    ) -> None:
        """ANTI-DEGENERATE: every scenario produces a strictly positive EAD.

        With E = C = 10,000,000 the collateral is fully haircut by H_C (+H_FX),
        so the net exposure (E − C·(1−H)) is always positive — never the
        degenerate 0.0 of a fully-offsetting collateral or a mis-routed row.

        References: CRR Art. 223(5) — E* = max(0, E·(1+HE) − C·(1−H_C−H_FX)).
        """
        for label, row in (
            ("A15D", ccr_a15d_result),
            ("A15", ccr_a15_result),
            ("A16", ccr_a16_result),
            ("A17", ccr_a17_result),
            ("A18", ccr_a18_result),
        ):
            assert row["ead_ccr"] > 0.0, (
                f"CCR-{label}: expected strictly positive ead_ccr, got {row['ead_ccr']!r}."
            )
