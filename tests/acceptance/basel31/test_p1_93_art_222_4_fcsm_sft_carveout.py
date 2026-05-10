"""
P1.93 — FCSM Art. 222(4) SFT 0%/10% Carve-Out + Art. 222(6) Non-SFT Gating.

Acceptance scenario testing PRA PS1/26 Art. 222(4): for SFT exposures that meet
the Art. 227(2) zero-haircut criteria, the 20% FCSM floor is displaced.  The
replacement floor depends on the counterparty being a "core market participant"
(Art. 227(3)):

  CMP     → 0% secured-portion RW floor   (Art. 222(4)(a))
  non-CMP → 10% secured-portion RW floor  (Art. 222(4)(b))

Art. 222(6) (non-SFT same-currency cash/0%-RW-sovereign) remains a separate
code path and must not be affected by the SFT carve-out change.

Pipeline position:
    CRMProcessor._compute_fcsm_columns → SACalculator.apply_fcsm_rw_substitution

Three runs share the same fixture parquet files; each test sub-selects by
exposure_reference / collateral beneficiary_reference.

Run A — SFT, CMP (institution CQS 1, GBP sovereign gilt, zero_haircut=True):
    Art. 222(4)(a): floor = 0%
    Gilt RW = 0%  →  secured RW = max(0%, 0%) = 0%
    fcsm_collateral_value = 1,000,000  (no 20% sovereign discount under Art. 227)
    fcsm_collateral_rw    = 0.00
    risk_weight           = 0.00
    rwa                   = 0

Run B — SFT, non-CMP (corporate, GBP sovereign gilt, zero_haircut=True):
    Art. 222(4)(b): floor = 10%
    Gilt RW = 0%  →  secured RW = max(10%, 0%) = 10%
    fcsm_collateral_value = 1,000,000  (no 20% discount under Art. 227)
    fcsm_collateral_rw    = 0.10
    risk_weight           = 0.10
    rwa                   = 100,000
    HEADLINE REGRESSION: pre-fix engine emits rwa=200,000 (mis-fires same-currency
    0% branch AND applies 20% sovereign discount → collateral_value=800,000).

Run C — Non-SFT, CMP (institution CQS 1, GBP cash, zero_haircut=False):
    Art. 222(6)(a): same-currency cash → floor = 0%  (existing path, regression guard)
    fcsm_collateral_value = 1,000,000  (cash has no discount)
    fcsm_collateral_rw    = 0.00
    ead_final             = 500,000   (CCF 50% for MR OBS already applied)
    risk_weight           = 0.00
    rwa                   = 0

Hand calculation (Basel 3.1, CalculationConfig.basel_3_1(..., crm_collateral_method=SIMPLE)):
    Run A: unsecured_rw=20% (institution CQS 1 Art. 120(1) Table 3)
        is_sft=True, qualifies_for_zero_haircut=True, CMP=True
        → Art. 222(4): sovereign gilt discount waived, floor = 0%
        collateral_rw=0%, secured RW = max(0%, 0%) = 0%
        blended_rw = 1.0 × 0.0 + 0.0 × 0.20 = 0.0
        rwa = 1,000,000 × 0.0 = 0

    Run B: unsecured_rw=100% (corporate unrated Art. 122)
        is_sft=True, qualifies_for_zero_haircut=True, CMP=False
        → Art. 222(4): sovereign gilt discount waived, floor = 10%
        collateral_rw=0%, secured RW = max(10%, 0%) = 10%
        blended_rw = 1.0 × 0.10 + 0.0 × 1.0 = 0.10
        rwa = 1,000,000 × 0.10 = 100,000

    Run C: unsecured_rw=20% (institution CQS 1)
        is_sft=False → Art. 222(4) SFT carve-out does not apply
        same-currency GBP cash → Art. 222(6)(a) → floor = 0%
        collateral_rw=0%, secured RW = 0%
        ead_final=500,000 (50% CCF for MR), collateral_value=1,000,000 → secured=500,000
        blended_rw = 1.0 × 0.0 + 0.0 × 0.20 = 0.0
        rwa = 500,000 × 0.0 = 0

Regulatory references:
    PRA PS1/26 Art. 222(3): 20% FCSM RW floor (default).
    PRA PS1/26 Art. 222(4): 0%/10% SFT carve-out gated by Art. 227 criteria.
    PRA PS1/26 Art. 222(6)(a): 0% for non-SFT same-currency cash.
    PRA PS1/26 Art. 227(2): Eight preconditions for zero-haircut.
    PRA PS1/26 Art. 227(3): Core market participant definition.
    PRA PS1/26 Art. 114(2): 0%-RW sovereign CQS 1.
    PRA PS1/26 Art. 120(1) Table 3: institution SA risk weights by CQS.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.sa.namespace  # noqa: F401 — register sa namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.crm.simple_method import compute_fcsm_columns

# =============================================================================
# Scenario constants  (mirrors tests/fixtures/p1_93/p1_93.py)
# =============================================================================

_EAD = 1_000_000.0
_COLLATERAL_VALUE = 1_000_000.0
_EAD_C = 500_000.0  # CCF 50% applied for MR OBS

# Expected post-fix FCSM outputs
_EXPECTED_FCSM_COLL_VALUE_A = 1_000_000.0  # sovereign gilt discount waived under Art. 227
_EXPECTED_FCSM_COLL_RW_A = 0.00  # Art. 222(4)(a) CMP → 0% floor; gilt RW = 0%
_EXPECTED_RISK_WEIGHT_A = 0.00
_EXPECTED_RWA_A = 0.0

_EXPECTED_FCSM_COLL_VALUE_B = 1_000_000.0  # sovereign gilt discount waived under Art. 227
_EXPECTED_FCSM_COLL_RW_B = 0.10  # Art. 222(4)(b) non-CMP → 10% floor; gilt RW = 0%
_EXPECTED_RISK_WEIGHT_B = 0.10
_EXPECTED_RWA_B = 100_000.0

_EXPECTED_FCSM_COLL_VALUE_C = 1_000_000.0  # cash; no discount
_EXPECTED_FCSM_COLL_RW_C = 0.00  # Art. 222(6)(a) same-currency cash → 0%
_EXPECTED_RISK_WEIGHT_C = 0.00
_EXPECTED_RWA_C = 0.0


# =============================================================================
# Frame builders
# =============================================================================


def _make_exposure_a() -> pl.LazyFrame:
    """Run A: SFT repo, institution CQS 1, CMP=True, GBP."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["FAC_REPO_A"],
            "ead_gross": [_EAD],
            "ead_pre_crm": [_EAD],
            "ead": [_EAD],
            "ead_final": [_EAD],
            "currency": ["GBP"],
            "approach": ["standardised"],
            "exposure_class": ["INSTITUTION"],
            "cqs": [1],
            "risk_weight": [0.20],
            # Art. 222(4) inputs — must be propagated through to compute_fcsm_columns
            "is_sft": [True],
            "cp_is_core_market_participant": [True],
        }
    )


def _make_exposure_b() -> pl.LazyFrame:
    """Run B: SFT repo, corporate unrated, CMP=False, GBP."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["FAC_REPO_B"],
            "ead_gross": [_EAD],
            "ead_pre_crm": [_EAD],
            "ead": [_EAD],
            "ead_final": [_EAD],
            "currency": ["GBP"],
            "approach": ["standardised"],
            "exposure_class": ["CORPORATE"],
            "cqs": [None],
            "risk_weight": [1.0],
            # Art. 222(4) inputs — non-CMP triggers 10% floor
            "is_sft": [True],
            "cp_is_core_market_participant": [False],
        }
    )


def _make_exposure_c() -> pl.LazyFrame:
    """Run C: non-SFT OBS, institution CQS 1, CMP=True, GBP; ead_final=500k (50% CCF)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["FAC_OBS_C"],
            "ead_gross": [_EAD],
            "ead_pre_crm": [_EAD],
            "ead": [_EAD],
            "ead_final": [_EAD_C],  # CCF 50% for MR OBS pre-applied
            "currency": ["GBP"],
            "approach": ["standardised"],
            "exposure_class": ["INSTITUTION"],
            "cqs": [1],
            "risk_weight": [0.20],
            # Art. 222(6)(a) path — not SFT, Art. 222(4) must NOT fire
            "is_sft": [False],
            "cp_is_core_market_participant": [True],
        }
    )


def _make_gilt_collateral(beneficiary_ref: str, coll_ref: str) -> pl.LazyFrame:
    """GBP CQS-1 sovereign gilt, market_value=1,000,000, qualifies_for_zero_haircut=True."""
    return pl.LazyFrame(
        {
            "collateral_reference": [coll_ref],
            "collateral_type": ["govt_bond"],
            "market_value": [_COLLATERAL_VALUE],
            "currency": ["GBP"],
            "beneficiary_reference": [beneficiary_ref],
            "beneficiary_type": ["facility"],
            "issuer_cqs": [1],
            "issuer_type": ["sovereign"],
            "is_eligible_financial_collateral": [True],
            "qualifies_for_zero_haircut": [True],
        }
    )


def _make_cash_collateral(beneficiary_ref: str, coll_ref: str) -> pl.LazyFrame:
    """GBP cash deposit, market_value=1,000,000, qualifies_for_zero_haircut=False."""
    return pl.LazyFrame(
        {
            "collateral_reference": [coll_ref],
            "collateral_type": ["cash"],
            "market_value": [_COLLATERAL_VALUE],
            "currency": ["GBP"],
            "beneficiary_reference": [beneficiary_ref],
            "beneficiary_type": ["facility"],
            "issuer_cqs": [None],
            "issuer_type": [None],
            "is_eligible_financial_collateral": [True],
            "qualifies_for_zero_haircut": [False],
        }
    )


@pytest.fixture
def b31_simple_config() -> CalculationConfig:
    """Basel 3.1 config with Simple Method elected."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


# =============================================================================
# Run A — SFT + CMP → 0% floor (Art. 222(4)(a))
# =============================================================================


class TestRunA_SFT_CMP_ZeroFloor:
    """
    Run A — SFT repo + CQS-1 sovereign gilt + core market participant.

    Art. 222(4)(a): CMP counterparty → 0% floor on secured portion.
    The sovereign gilt discount (Art. 222(4)(b) 20%) is waived for
    Art. 227-qualifying collateral.  Gilt RW = 0% → secured RW = 0%.

    Expected: fcsm_collateral_value=1,000,000, fcsm_collateral_rw=0.00,
              risk_weight=0.00, rwa=0.
    """

    def test_p1_93_run_a_sft_cmp_fcsm_collateral_value(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 227 zero-haircut suppresses the 20% sovereign discount.

        Arrange: SFT repo, CMP institution, GBP gilt, qualifies_for_zero_haircut=True.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:  fcsm_collateral_value = 1,000,000  (no 20% discount applied).
        """
        # Arrange
        exposures = _make_exposure_a()
        collateral = _make_gilt_collateral("FAC_REPO_A", "COLL_GILT_A")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_value"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_VALUE_A, abs=1e-6
        ), (
            f"Run A: fcsm_collateral_value should be {_EXPECTED_FCSM_COLL_VALUE_A:,.0f} "
            f"(Art. 227 suppresses 20% sovereign discount), "
            f"got {result['fcsm_collateral_value'][0]:,.0f}"
        )

    def test_p1_93_run_a_sft_cmp_fcsm_collateral_rw(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 222(4)(a) CMP → 0% floor; gilt RW 0% → fcsm_collateral_rw = 0.00.

        Arrange: SFT repo, CMP institution, GBP gilt, qualifies_for_zero_haircut=True.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:  fcsm_collateral_rw = 0.00  (0% floor, gilt RW = 0%).
        """
        # Arrange
        exposures = _make_exposure_a()
        collateral = _make_gilt_collateral("FAC_REPO_A", "COLL_GILT_A")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_rw"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_RW_A, abs=1e-6
        ), (
            f"Run A: fcsm_collateral_rw should be {_EXPECTED_FCSM_COLL_RW_A} "
            f"(Art. 222(4)(a) CMP → 0% floor), got {result['fcsm_collateral_rw'][0]}"
        )

    def test_p1_93_run_a_sft_cmp_rwa_zero(self, b31_simple_config: CalculationConfig) -> None:
        """
        Run A E2E: RWA = 0 (fully secured at 0% RW).

        Arrange: institution CQS 1, SFT repo, GBP gilt 1M, CMP=True.
        Act:     compute_fcsm_columns → apply_fcsm_rw_substitution.
        Assert:
            fcsm_collateral_value = 1,000,000
            fcsm_collateral_rw    = 0.00
            risk_weight           = 0.00
            rwa                   = 0
        """
        # Arrange
        exposures = _make_exposure_a()
        collateral = _make_gilt_collateral("FAC_REPO_A", "COLL_GILT_A")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, b31_simple_config)
        result = (
            with_fcsm.sa.apply_fcsm_rw_substitution(b31_simple_config)
            .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
            .collect()
        )

        # Assert
        assert result["fcsm_collateral_value"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_VALUE_A, abs=1e-6
        )
        assert result["fcsm_collateral_rw"][0] == pytest.approx(_EXPECTED_FCSM_COLL_RW_A, abs=1e-6)
        assert result["risk_weight"][0] == pytest.approx(_EXPECTED_RISK_WEIGHT_A, abs=1e-6), (
            f"Run A: risk_weight should be {_EXPECTED_RISK_WEIGHT_A} "
            f"(Art. 222(4)(a) CMP → blended 0%), got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(_EXPECTED_RWA_A, abs=1.0), (
            f"Run A: rwa should be {_EXPECTED_RWA_A:,.0f}, got {result['rwa'][0]:,.0f}"
        )


# =============================================================================
# Run B — SFT + non-CMP → 10% floor (Art. 222(4)(b)) — HEADLINE REGRESSION
# =============================================================================


class TestRunB_SFT_NonCMP_TenPercentFloor:
    """
    Run B — SFT repo + CQS-1 sovereign gilt + NON-core market participant.

    Art. 222(4)(b): non-CMP → 10% floor on secured portion.
    The gilt itself has 0% RW (sovereign CQS 1) but the 10% floor supersedes it.
    The Art. 227 qualifying collateral also means the 20% sovereign discount is
    waived → collateral_value = 1,000,000 (not 800,000).

    HEADLINE REGRESSION (pre-fix engine):
        - Mis-fires the same-currency 0%-RW-sovereign carve-out from Art. 222(6)
          (which should only apply to non-SFT exposures).
        - Also applies the 20% sovereign discount → collateral_value = 800,000.
        - Result: fcsm_collateral_rw=0.0, risk_weight=0.20, rwa=200,000.
        - Expected post-fix: fcsm_collateral_rw=0.10, risk_weight=0.10, rwa=100,000.
    """

    def test_p1_93_run_b_sft_noncmp_fcsm_collateral_value(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 227 zero-haircut suppresses the 20% sovereign discount even for non-CMP.

        Arrange: SFT repo, non-CMP corporate, GBP gilt, qualifies_for_zero_haircut=True.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:  fcsm_collateral_value = 1,000,000  (no 20% discount).
        """
        # Arrange
        exposures = _make_exposure_b()
        collateral = _make_gilt_collateral("FAC_REPO_B", "COLL_GILT_B")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_value"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_VALUE_B, abs=1e-6
        ), (
            f"Run B: fcsm_collateral_value should be {_EXPECTED_FCSM_COLL_VALUE_B:,.0f} "
            f"(Art. 227 suppresses 20% sovereign discount), "
            f"got {result['fcsm_collateral_value'][0]:,.0f}"
        )

    def test_p1_93_run_b_sft_noncmp_fcsm_collateral_rw_ten_pct(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 222(4)(b): non-CMP → 10% floor fires; gilt RW=0% → secured RW=10%.

        Arrange: SFT repo, non-CMP corporate, GBP gilt, qualifies_for_zero_haircut=True.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:  fcsm_collateral_rw = 0.10
                 (pre-fix: returns 0.0 — fires Art. 222(6) carve-out incorrectly)

        This is the discriminating assertion for P1.93.
        """
        # Arrange
        exposures = _make_exposure_b()
        collateral = _make_gilt_collateral("FAC_REPO_B", "COLL_GILT_B")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert — BUG: currently returns 0.0
        assert result["fcsm_collateral_rw"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_RW_B, abs=1e-6
        ), (
            f"Run B: fcsm_collateral_rw should be {_EXPECTED_FCSM_COLL_RW_B} "
            f"(Art. 222(4)(b) non-CMP → 10% floor), "
            f"got {result['fcsm_collateral_rw'][0]} "
            f"(pre-fix: engine fires Art. 222(6) 0% carve-out for SFT non-CMP)"
        )

    def test_p1_93_run_b_sft_noncmp_risk_weight_ten_pct(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Blended RW = 1.0 × 0.10 + 0.0 × 1.0 = 0.10 (fully secured, 10% floor).

        Arrange: corporate exposure with post-fix fcsm_collateral_rw = 0.10.
        Act:     apply_fcsm_rw_substitution.
        Assert:  risk_weight = 0.10.
        """
        # Arrange — pre-set fcsm columns to the expected post-fix values to isolate
        # the blending arithmetic from the derivation bug
        exposures_with_fcsm = pl.LazyFrame(
            {
                "exposure_reference": ["FAC_REPO_B"],
                "ead_final": [_EAD],
                "risk_weight": [1.0],
                "fcsm_collateral_value": [_COLLATERAL_VALUE],  # 1,000,000
                "fcsm_collateral_rw": [0.10],  # post-fix target
                "approach": ["standardised"],
                "exposure_class": ["CORPORATE"],
            }
        )

        # Act
        result = exposures_with_fcsm.sa.apply_fcsm_rw_substitution(b31_simple_config).collect()

        # Assert
        assert result["risk_weight"][0] == pytest.approx(0.10, abs=1e-6), (
            f"Run B: blended risk_weight should be 0.10 "
            f"(1.0 × 0.10 fully secured, Art. 222(4)(b)), "
            f"got {result['risk_weight'][0]:.4f}"
        )

    def test_p1_93_run_b_sft_noncmp_rwa_one_hundred_k(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        RWA = EAD × blended_rw = 1,000,000 × 0.10 = 100,000.

        Primary E2E assertion for Run B.  Pre-fix engine emits rwa=200,000:
          - 20% sovereign discount → collateral_value=800,000 (secured_pct=0.8)
          - Art. 222(6) carve-out fires (wrong path) → collateral_rw=0.0
          - blended_rw = 0.8 × 0.0 + 0.2 × 1.0 = 0.20 → rwa=200,000

        Post-fix expected:
          - Art. 227 waives discount → collateral_value=1,000,000 (secured_pct=1.0)
          - Art. 222(4)(b) non-CMP floor = 10% → collateral_rw=0.10
          - blended_rw = 1.0 × 0.10 = 0.10 → rwa=100,000
        """
        # Arrange
        exposures = _make_exposure_b()
        collateral = _make_gilt_collateral("FAC_REPO_B", "COLL_GILT_B")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, b31_simple_config)
        result = (
            with_fcsm.sa.apply_fcsm_rw_substitution(b31_simple_config)
            .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
            .collect()
        )

        # Assert — fcsm_collateral_rw is the discriminating check
        assert result["fcsm_collateral_rw"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_RW_B, abs=1e-6
        ), (
            f"Run B: fcsm_collateral_rw must be {_EXPECTED_FCSM_COLL_RW_B} before blending "
            f"(Art. 222(4)(b) non-CMP 10% floor), got {result['fcsm_collateral_rw'][0]}"
        )
        assert result["risk_weight"][0] == pytest.approx(_EXPECTED_RISK_WEIGHT_B, abs=1e-6), (
            f"Run B: risk_weight should be {_EXPECTED_RISK_WEIGHT_B} "
            f"(fully secured at 10% Art. 222(4)(b)), got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(_EXPECTED_RWA_B, abs=1.0), (
            f"Run B: rwa should be {_EXPECTED_RWA_B:,.0f} "
            f"(Art. 222(4)(b) non-CMP 10% floor), got {result['rwa'][0]:,.0f} "
            f"(pre-fix delta: {result['rwa'][0] - _EXPECTED_RWA_B:+,.0f})"
        )


# =============================================================================
# Run C — Non-SFT + same-currency cash → Art. 222(6)(a) (regression guard)
# =============================================================================


class TestRunC_NonSFT_CMP_ArtSix_RegressionGuard:
    """
    Run C — Non-SFT OBS, GBP cash collateral, CMP institution.

    Art. 222(6)(a): same-currency cash deposit → 0% floor (non-SFT path).
    This test must pass BOTH before and after the P1.93 fix — it ensures the
    engine-implementer does not accidentally break the Art. 222(6) path when
    adding the Art. 222(4) SFT gate.

    Note: Run C currently passes (the cash/same-currency carve-out fires
    correctly for non-SFT exposures).
    """

    def test_p1_93_run_c_nonsft_cash_fcsm_collateral_value(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Non-SFT GBP cash: fcsm_collateral_value = 1,000,000 (no discount on cash).

        Arrange: non-SFT OBS, institution CQS 1, GBP cash, qualifies_for_zero_haircut=False.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:  fcsm_collateral_value = 1,000,000.
        """
        # Arrange
        exposures = _make_exposure_c()
        collateral = _make_cash_collateral("FAC_OBS_C", "COLL_CASH_C")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_value"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_VALUE_C, abs=1e-6
        ), (
            f"Run C: fcsm_collateral_value should be {_EXPECTED_FCSM_COLL_VALUE_C:,.0f} "
            f"(cash, no discount), got {result['fcsm_collateral_value'][0]:,.0f}"
        )

    def test_p1_93_run_c_nonsft_cash_fcsm_collateral_rw_zero(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 222(6)(a) same-currency cash → fcsm_collateral_rw = 0.00.

        Regression pin: must pass before and after the P1.93 fix.

        Arrange: non-SFT OBS, GBP cash, qualifies_for_zero_haircut=False.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:  fcsm_collateral_rw = 0.00.
        """
        # Arrange
        exposures = _make_exposure_c()
        collateral = _make_cash_collateral("FAC_OBS_C", "COLL_CASH_C")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_rw"][0] == pytest.approx(
            _EXPECTED_FCSM_COLL_RW_C, abs=1e-6
        ), (
            f"Run C regression: fcsm_collateral_rw should be {_EXPECTED_FCSM_COLL_RW_C} "
            f"(Art. 222(6)(a)), got {result['fcsm_collateral_rw'][0]}"
        )

    def test_p1_93_run_c_nonsft_cash_rwa_zero(self, b31_simple_config: CalculationConfig) -> None:
        """
        Run C E2E: RWA = 0 (ead_final=500k, secured at 0%).

        Regression pin — must pass before and after the P1.93 fix.

        Arrange: institution CQS 1, non-SFT OBS, GBP cash 1M, CMP=True.
                 ead_final = 500,000 (50% CCF for MR OBS pre-applied).
        Act:     compute_fcsm_columns → apply_fcsm_rw_substitution.
        Assert:
            fcsm_collateral_value = 1,000,000  (caps at ead_final=500,000 post-join)
            fcsm_collateral_rw    = 0.00
            risk_weight           = 0.00
            rwa                   = 0
        """
        # Arrange
        exposures = _make_exposure_c()
        collateral = _make_cash_collateral("FAC_OBS_C", "COLL_CASH_C")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, b31_simple_config)
        result = (
            with_fcsm.sa.apply_fcsm_rw_substitution(b31_simple_config)
            .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
            .collect()
        )

        # Assert
        assert result["fcsm_collateral_rw"][0] == pytest.approx(_EXPECTED_FCSM_COLL_RW_C, abs=1e-6)
        assert result["risk_weight"][0] == pytest.approx(_EXPECTED_RISK_WEIGHT_C, abs=1e-6), (
            f"Run C: risk_weight should be {_EXPECTED_RISK_WEIGHT_C} "
            f"(Art. 222(6)(a) same-currency cash 0%), got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(_EXPECTED_RWA_C, abs=1.0), (
            f"Run C: rwa should be {_EXPECTED_RWA_C:,.0f} (regression pin), "
            f"got {result['rwa'][0]:,.0f}"
        )


# =============================================================================
# Framework invariant — Run B vs Run A (delta = 100,000 RWA)
# =============================================================================


class TestSFTCarveOutFrameworkInvariant:
    """
    Structural validation: CMP vs non-CMP delta under Art. 222(4).

    The CMP/non-CMP distinction costs exactly 100,000 RWA in this scenario:
        CMP    (Run A): EAD × floor_A × secured_pct = 1,000,000 × 0.00 × 1.0 = 0
        non-CMP (Run B): EAD × floor_B × secured_pct = 1,000,000 × 0.10 × 1.0 = 100,000
        delta = 100,000 (the marginal cost of not being a core market participant).
    """

    def test_p1_93_cmp_vs_noncmp_rwa_delta_one_hundred_k(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Run B RWA should exceed Run A RWA by exactly 100,000.

        Arrange: Run A (CMP), Run B (non-CMP); identical EAD, gilt, currency.
        Act:     compute_fcsm_columns → apply_fcsm_rw_substitution for each run.
        Assert:  rwa_B - rwa_A == 100,000  (Art. 222(4) CMP/non-CMP premium).
        """
        # Arrange
        exposures_a = _make_exposure_a()
        collateral_a = _make_gilt_collateral("FAC_REPO_A", "COLL_GILT_A")
        exposures_b = _make_exposure_b()
        collateral_b = _make_gilt_collateral("FAC_REPO_B", "COLL_GILT_B")

        def _compute_rwa(exposures: pl.LazyFrame, collateral: pl.LazyFrame) -> float:
            with_fcsm = compute_fcsm_columns(exposures, collateral, b31_simple_config)
            result = (
                with_fcsm.sa.apply_fcsm_rw_substitution(b31_simple_config)
                .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
                .collect()
            )
            return float(result["rwa"][0])

        # Act
        rwa_a = _compute_rwa(exposures_a, collateral_a)
        rwa_b = _compute_rwa(exposures_b, collateral_b)

        # Assert
        assert rwa_b - rwa_a == pytest.approx(100_000.0, abs=1.0), (
            f"Art. 222(4) CMP/non-CMP delta should be 100,000: "
            f"Run A (CMP)={rwa_a:,.0f}, Run B (non-CMP)={rwa_b:,.0f}, "
            f"delta={rwa_b - rwa_a:,.0f}"
        )
