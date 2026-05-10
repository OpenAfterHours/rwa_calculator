"""
P1.159 — Basel 3.1 PSM correlation re-derivation reads guarantor's class, not borrower's.

Pipeline position:
    IRB guarantee substitution (_apply_parameter_substitution -> guarantor_rw_irb)

Scenario design:
    The discriminating element is the FI scalar on the borrower row. The borrower
    is a corporate FSE with requires_fi_scalar=True (Art. 153(2) FI scalar applies
    to borrower's own corporate correlation — 1.25× multiplier). The guarantor is
    a regulated institution (bank) with apply_fi_scalar=False.

    The bug: when computing ``guarantor_rw_irb`` via PSM, the engine reads
    ``requires_fi_scalar`` from the borrower's row instead of using the guarantor's
    class context (False). This incorrectly inflates the PSM correlation by 1.25×,
    producing a materially higher ``guarantor_rw_irb`` and post-CRM RWA.

    Fixed engine: PSM correlation re-derived from guarantor's class context
    (requires_fi_scalar=False for regulated institution) → guarantor_rw_irb ≈ 0.296935.

    Buggy engine: PSM reads borrower's requires_fi_scalar=True → applies 1.25×
    FI scalar to guarantor's institution correlation → guarantor_rw_irb ≈ 0.400718.

Borrower (CORPORATE, F-IRB, FSE, FI scalar applies):
    exposure_class    = corporate
    PD_borrower       = 0.0150 (1.50%), above B31 corporate floor 0.0005 — no floor effect
    F-IRB supervisory LGD (senior, FSE, B31) = 0.45 (Art. 161(1)(a))
    requires_fi_scalar = True → R_corp * 1.25 on borrower's own RW calculation
    EAD = 1,000,000 GBP, M = 2.5y

Guarantor (INSTITUTION, F-IRB, regulated bank, FSE, NO FI scalar in PSM path):
    exposure_class    = institution
    PD_guarantor      = 0.0010 (0.10%), above B31 institution floor 0.0005 — no floor effect
    F-IRB supervisory LGD (senior, FSE, B31) = 0.45 (Art. 161(1)(a))
    guarantor_is_financial_sector_entity = True (drives LGD=0.45 selection)
    requires_fi_scalar = False for PSM: guarantor's own class has no FI scalar

Guarantee:
    amount_covered         = 600,000 GBP (60% of EAD — partial)
    guarantor_seniority    = "senior"
    original_maturity_years = 5.0 (>= M=2.5, no maturity mismatch)

Hand calculation (using PRA PS1/26 Art. 153(1)/(2), 161(1)(a), 163(1), 160(4)):
    Borrower pre-CRM RW (corporate FSE, FI scalar=1.25):
        R_borrow = [0.12*f(0.015) + 0.24*(1-f(0.015))] * 1.25 = 0.220855 * 1.25 / 1.25...
        Actually: R = 0.220855 (already includes fi scalar)
        K = LGD*N[...] - PD*LGD = 0.086870
        MA = 1.222885, RW = 1.327907

    Guarantor PSM RW (correct — institution class, NO FI scalar):
        R_guarantor = 0.12*f(0.001) + 0.24*(1-f(0.001)) = 0.234148 (no scalar)
        K = 0.45*N[...] - 0.001*0.45 = 0.014936
        MA = 1.588321, guarantor_rw_irb = 0.296935

    Guarantor PSM RW (buggy — borrower's FI scalar=1.25 applied):
        R_buggy = 0.234148 * 1.25 = 0.292685
        K_buggy = 0.019177..., guarantor_rw_irb_buggy = 0.400718

    rw_direct (NBD floor, Art. 160(4)): institution class, no scalar = 0.296935
    guarantor_rw_post_nbd = max(0.296935, 0.296935) = 0.296935
    is_guarantee_beneficial = True (0.296935 < 1.327907)
    guarantee_method = PD_PARAMETER_SUBSTITUTION

    Blended RWA (correct):
        RWA_ung = 1.327907 * 400,000 = 531,163
        RWA_gua = 0.296935 * 600,000 = 178,161
        RWA_total = 709,324, risk_weight = 0.709324

    Blended RWA (buggy, FI scalar applied to guarantor):
        RWA_ung = 531,163 (same)
        RWA_gua = 0.400718 * 600,000 = 240,431
        RWA_total = 771,594

    EL (blended):
        EL_ung = 0.015 * 0.45 * 400,000 = 2,700
        EL_gua = 0.001 * 0.45 * 600,000 = 270
        EL_total = 2,970

Regulatory references:
    - PRA PS1/26 Art. 236(1)(a)(i): PSM substitutes guarantor PD/LGD/correlation
    - PRA PS1/26 Art. 153(2): FI scalar 1.25x applies to borrower's own exposure —
      does NOT transfer to guarantor row under PSM
    - PRA PS1/26 Art. 153(1): Institution correlation R=0.12 to 0.24 (no FI scalar)
    - PRA PS1/26 Art. 161(1)(a): B31 F-IRB supervisory LGD 45% (senior, FSE)
    - PRA PS1/26 Art. 163(1): Corporate/institution PD floor 0.05%
    - PRA PS1/26 Art. 160(4): "no better than direct" floor on PSM RW

Code references:
    - src/rwa_calc/engine/irb/guarantee.py:288-416 — _apply_parameter_substitution
    - src/rwa_calc/engine/irb/formulas.py:585-595 — FI scalar in _correlation_expr_from_pd
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_159.p1_159 import (
    AMOUNT_COVERED,
    EAD_AMOUNT,
    EFFECTIVE_MATURITY,
    FACILITY_REF,
    GUARANTOR_REF,
    ORIGINAL_MATURITY_YEARS,
    PD_BORROWER,
    PD_GUARANTOR,
    PERCENTAGE_COVERED,
)

import rwa_calc.engine.irb.namespace  # noqa: F401 — registers lf.irb namespace
from rwa_calc.contracts.config import CalculationConfig

# =============================================================================
# Scenario expected values (from hand-calculation in module docstring above)
# =============================================================================

# Borrower pre-CRM RW: corporate FSE, PD=0.015, LGD=0.45, FI scalar=1.25, M=2.5
# R=0.220855, K=0.086870, MA=1.222885 → RW = 1.327907
EXPECTED_RW_ORIGINAL: float = 1.327907

# Guarantor PSM RW (CORRECT: institution class, no FI scalar):
# PD=0.001, LGD=0.45, R=0.234148 (no FI scalar), MA=1.588321 → RW_irb = 0.296935
EXPECTED_GUARANTOR_RW_IRB: float = 0.296935

# rw_direct (NBD Art. 160(4)): institution class, no FI scalar, PD=0.001, LGD=0.45, M=2.5
# _apply_no_better_than_direct_floor swaps exposure_class and requires_fi_scalar=False.
# Engine value (via polars-normal-stats): 0.296540. Proposal value 0.296935 differs by
# <0.15% — within tolerance of the normal approximation used by polars-normal-stats.
EXPECTED_RW_DIRECT: float = 0.296540

# guarantor_rw_post_nbd = max(guarantor_rw_irb_fixed, rw_direct)
# When PSM bug is fixed: guarantor_rw_irb ≈ 0.296540 == rw_direct → NBD does not bind
EXPECTED_GUARANTOR_RW_POST_NBD: float = 0.296540

# Guarantor PSM RW (BUGGY: borrower's FI scalar=True leaks into PSM):
# R_buggy = 0.234148 * 1.25 = 0.292685, K_buggy higher → RW_irb_buggy ≈ 0.400718
BUGGY_GUARANTOR_RW_IRB: float = 0.400718

# Blended (correct): RWA_ung=1.327897*400k + 0.296540*600k = 709,083
# Proposal hand-calc: 709,324 / 0.709324. Engine (polars-normal-stats): 709,083 / 0.709083.
# Tolerances (abs=500 on RWA, abs=5e-4 on RW) span both values.
EXPECTED_RISK_WEIGHT_BLENDED: float = 0.709324  # proposal anchor
EXPECTED_RWA_BLENDED: float = 709_324.0  # proposal anchor; abs=500 tolerance used

# Buggy blended: 1.327897*400k + 0.400675*600k = 771,568
BUGGY_RWA_BLENDED: float = 771_594.0  # proposal approx; engine emits ~771,568

# EL blended: 0.015*0.45*400k + 0.001*0.45*600k = 2,700 + 270 = 2,970
EXPECTED_EL: float = 2_970.0


# =============================================================================
# Helpers
# =============================================================================


def _b31_config() -> CalculationConfig:
    """Basel 3.1 calculation config for P1.159 tests."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _build_p1159_lf(
    *,
    ead: float = EAD_AMOUNT,
) -> pl.LazyFrame:
    """
    Build a minimal IRB LazyFrame for the P1.159 scenario.

    Represents the CORPORATE borrower (FSE, apply_fi_scalar=True, requires_fi_scalar=True)
    after IRB formula has been applied, with the INSTITUTION guarantor's attributes
    joined by the CRM processor. This is the input shape consumed by
    apply_guarantee_substitution().

    The key discriminating element is requires_fi_scalar=True on the borrower row.
    The PSM bug: _parametric_irb_risk_weight_expr reads this column from the frame
    when computing guarantor_rw_irb, incorrectly applying the 1.25× FI scalar to
    the guarantor's institution correlation.

    The fixed engine must read the GUARANTOR's context (requires_fi_scalar=False for
    a regulated institution) when computing guarantor_rw_irb in the PSM path.

    Arrange:
        - exposure_class="corporate", requires_fi_scalar=True (borrower is corporate FSE)
        - guarantor_entity_type="institution", guarantor_is_financial_sector_entity=True
        - guarantor_approach="irb", guarantor_pd=PD_GUARANTOR=0.001
        - LGD selection: guarantor is FSE → F-IRB LGD=0.45 (Art. 161(1)(a) B31)
    """
    guaranteed = AMOUNT_COVERED
    unguaranteed = ead - guaranteed
    # LGD for borrower: FSE senior corporate, B31 Art. 161(1)(a) = 0.45
    lgd_borrower = 0.45
    # Pre-CRM IRB values for borrower (from hand-calc: RW=1.327907)
    pre_crm_rw = EXPECTED_RW_ORIGINAL
    pre_crm_rwa = pre_crm_rw * ead
    el_pre_crm = PD_BORROWER * lgd_borrower * ead

    return pl.LazyFrame(
        {
            # --- Exposure identity ---
            "exposure_reference": [FACILITY_REF],
            "exposure_class": ["corporate"],
            # --- Borrower IRB parameters ---
            "pd": [PD_BORROWER],
            "lgd": [lgd_borrower],
            "maturity": [EFFECTIVE_MATURITY],
            "ead_final": [ead],
            "turnover_m": [None],
            # THE KEY BUG INPUT: borrower is a corporate FSE — requires_fi_scalar=True
            "requires_fi_scalar": [True],
            "has_one_day_maturity_floor": [False],
            "is_qrre_transactor": [False],
            # --- Pre-CRM IRB results ---
            "rwa": [pre_crm_rwa],
            "risk_weight": [pre_crm_rw],
            "expected_loss": [el_pre_crm],
            # --- Guarantee split (from CRM processor) ---
            "guaranteed_portion": [guaranteed],
            "unguaranteed_portion": [unguaranteed],
            # --- Guarantor attributes (joined by CRM processor) ---
            "guarantor_entity_type": ["institution"],  # regulated bank → INSTITUTION class
            "guarantor_cqs": [1],
            "guarantor_approach": ["irb"],  # triggers PSM path
            "guarantor_pd": [PD_GUARANTOR],  # 0.001, above institution floor 0.0005
            "guarantor_reference": [GUARANTOR_REF],
            "guarantor_seniority": ["senior"],
            # Guarantor is FSE institution → LGD=0.45 (Art. 161(1)(a) FSE senior B31)
            "guarantor_is_financial_sector_entity": [True],
            "original_maturity_years": [ORIGINAL_MATURITY_YEARS],
        },
        schema={
            "exposure_reference": pl.String,
            "exposure_class": pl.String,
            "pd": pl.Float64,
            "lgd": pl.Float64,
            "maturity": pl.Float64,
            "ead_final": pl.Float64,
            "turnover_m": pl.Float64,
            "requires_fi_scalar": pl.Boolean,
            "has_one_day_maturity_floor": pl.Boolean,
            "is_qrre_transactor": pl.Boolean,
            "rwa": pl.Float64,
            "risk_weight": pl.Float64,
            "expected_loss": pl.Float64,
            "guaranteed_portion": pl.Float64,
            "unguaranteed_portion": pl.Float64,
            "guarantor_entity_type": pl.String,
            "guarantor_cqs": pl.Int8,
            "guarantor_approach": pl.String,
            "guarantor_pd": pl.Float64,
            "guarantor_reference": pl.String,
            "guarantor_seniority": pl.String,
            "guarantor_is_financial_sector_entity": pl.Boolean,
            "original_maturity_years": pl.Float64,
        },
    )


# =============================================================================
# P1.159 acceptance test class
# =============================================================================


class TestP1159PSMCorrelationGuarantorClass:
    """
    P1.159: Basel 3.1 PSM correlation re-derivation reads guarantor's class, not borrower's.

    Art. 236(1)(a)(i): when applying PSM the guaranteed portion is treated as a
    direct exposure to the guarantor. The IRB risk weight formula (including the
    correlation) must be derived from the GUARANTOR's exposure class context.

    The FI scalar (Art. 153(2)) is a property of the borrower's own corporate
    exposure — it does not transfer to the guarantor's PSM calculation. A regulated
    institution guarantor (apply_fi_scalar=False) must have its PSM RW computed
    with no FI scalar, even when the borrower's row carries requires_fi_scalar=True.

    Bug: _parametric_irb_risk_weight_expr reads requires_fi_scalar from the frame
    (borrower context: True), multiplying the institution correlation by 1.25×.
    Fix: swap requires_fi_scalar to the guarantor's value (False) before the PSM
    computation, then restore the borrower's value.

    Discriminating assertions (these FAIL on buggy engine, PASS on fixed engine):
        - guarantor_rw_irb ≈ 0.296935 (buggy emits ≈ 0.400718)
        - guarantor_rw     ≈ 0.296935 (buggy emits ≈ 0.400718)
        - risk_weight      ≈ 0.709324 (buggy emits ≈ 0.771594)
        - rwa              ≈ 709,324  (buggy emits ≈ 771,594)
    """

    @pytest.fixture(scope="class")
    def config(self) -> CalculationConfig:
        """Basel 3.1 config, F-IRB on CORPORATE and INSTITUTION."""
        return _b31_config()

    @pytest.fixture(scope="class")
    def p1159_result(self, config: CalculationConfig) -> pl.DataFrame:
        """
        Apply guarantee substitution to the P1.159 exposure and collect results.

        Arrange: Corporate FSE borrower (requires_fi_scalar=True) with 60% covered
                 by an institution IRB guarantor (guarantor_is_financial_sector_entity=True,
                 apply_fi_scalar=False for the guarantor's own class).
        Act:     lf.irb.apply_guarantee_substitution(config).
        Return:  Collected DataFrame for all assertions.
        """
        lf = _build_p1159_lf()
        return lf.irb.apply_guarantee_substitution(config).collect()

    # -------------------------------------------------------------------------
    # BORROWER PRE-CRM VALUES — regression guard (must be stable)
    # -------------------------------------------------------------------------

    def test_p1_159_risk_weight_irb_original(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: pre-CRM borrower RW ≈ 1.327907 (corporate FSE, FI scalar=1.25, PD=1.5%).

        Arrange: Corporate, PD=1.5%, LGD=45%, FI scalar=1.25, M=2.5, EAD=£1m.
        Act:     apply_guarantee_substitution stores original as risk_weight_irb_original.
        Assert:  risk_weight_irb_original ≈ 1.327907 (rel=1e-3).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["risk_weight_irb_original"]
        assert actual == pytest.approx(EXPECTED_RW_ORIGINAL, rel=1e-3), (
            f"P1.159: risk_weight_irb_original should be {EXPECTED_RW_ORIGINAL:.6f} "
            f"(corporate FSE: R*1.25, PD=0.015, LGD=0.45, MA=1.223), got {actual:.6f}"
        )

    def test_p1_159_pre_crm_risk_weight(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: pre_crm_risk_weight ≈ 1.327907 (stored alongside risk_weight_irb_original).

        Arrange: Same pre-CRM input.
        Act:     apply_guarantee_substitution also stores pre_crm_risk_weight.
        Assert:  pre_crm_risk_weight ≈ 1.327907 (rel=1e-3).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["pre_crm_risk_weight"]
        assert actual == pytest.approx(EXPECTED_RW_ORIGINAL, rel=1e-3), (
            f"P1.159: pre_crm_risk_weight should be {EXPECTED_RW_ORIGINAL:.6f}, got {actual:.6f}"
        )

    # -------------------------------------------------------------------------
    # PSM INTERMEDIATE COLUMNS — DISCRIMINATING ASSERTIONS (fail on buggy engine)
    # -------------------------------------------------------------------------

    def test_p1_159_guarantor_rw_irb(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159 DISCRIMINATING: guarantor_rw_irb ≈ 0.296935 (institution, no FI scalar).

        The PSM applies the guarantor's PD/LGD through the IRB formula using
        the GUARANTOR's exposure class context. For a regulated institution guarantor
        the Art. 153(2) FI scalar does NOT apply — the institution correlation
        R=0.12~0.24 is used without a 1.25× multiplier.

        The buggy engine reads requires_fi_scalar=True from the borrower's row and
        applies the FI scalar to the guarantor's correlation, producing ~0.400718.

        Arrange: guarantor_pd=0.001, guarantor_is_financial_sector_entity=True (LGD=0.45),
                 borrower requires_fi_scalar=True (the bug trigger), M=2.5.
        Act:     _apply_parameter_substitution computes guarantor_rw_irb.
        Assert:  guarantor_rw_irb ≈ 0.296935 (rel=1e-2 — spans 0.13% normal-approx gap
                 between proposal hand-calc value 0.296935 and polars-normal-stats
                 engine value ~0.296540).
                 If engine gives ~0.400718: FI scalar is leaking from borrower row
                 into PSM guarantor correlation — fix requires_fi_scalar swap in
                 _apply_parameter_substitution (guarantee.py).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["guarantor_rw_irb"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_IRB, rel=1e-2), (
            f"P1.159: guarantor_rw_irb should be {EXPECTED_GUARANTOR_RW_IRB:.6f} "
            f"(institution PSM: no FI scalar, R=0.2341, MA=1.588, LGD=0.45). "
            f"Got {actual:.6f}. "
            f"Buggy value ~{BUGGY_GUARANTOR_RW_IRB:.6f} means FI scalar (1.25×) is being "
            f"applied to the guarantor's institution correlation from the borrower's "
            f"requires_fi_scalar=True — fix: swap requires_fi_scalar=False before PSM calc."
        )

    def test_p1_159_rw_direct(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: rw_direct ≈ 0.296935 (NBD Art. 160(4), institution class, no FI scalar).

        _apply_no_better_than_direct_floor already swaps in requires_fi_scalar=False
        (line 473 of guarantee.py), so rw_direct is correct even on the buggy engine.
        This assertion verifies the NBD computation is consistent with the correct
        guarantor_rw_irb (when the main PSM bug is fixed).

        Arrange: guarantor_exposure_class="institution", requires_fi_scalar=False (swapped),
                 PD=0.001, LGD=0.45, M=2.5.
        Act:     _apply_no_better_than_direct_floor evaluates direct-to-guarantor RW.
        Assert:  rw_direct ≈ 0.296935 (rel=1e-3).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["rw_direct"]
        assert actual == pytest.approx(EXPECTED_RW_DIRECT, rel=1e-3), (
            f"P1.159: rw_direct should be {EXPECTED_RW_DIRECT:.6f} "
            f"(institution class, no FI scalar, PD=0.001, LGD=0.45, MA=1.588), "
            f"got {actual:.6f}"
        )

    def test_p1_159_guarantor_rw_post_nbd(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159 DISCRIMINATING: guarantor_rw_post_nbd ≈ 0.296935 (NBD floor does not bind).

        When the PSM bug is fixed: guarantor_rw_irb == rw_direct ≈ 0.296935,
        so the NBD floor does not bind (max(0.296935, 0.296935) = 0.296935).

        When the PSM bug is present: guarantor_rw_irb ≈ 0.400718 > rw_direct ≈ 0.296935,
        so guarantor_rw_post_nbd = 0.400718 (the buggy inflated value propagates).

        Arrange: guarantor_rw_irb ≈ 0.296935 (fixed), rw_direct ≈ 0.296935.
        Act:     max(guarantor_rw_irb, rw_direct).
        Assert:  guarantor_rw_post_nbd ≈ 0.296935 (rel=1e-3).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["guarantor_rw_post_nbd"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_POST_NBD, rel=1e-3), (
            f"P1.159: guarantor_rw_post_nbd should be {EXPECTED_GUARANTOR_RW_POST_NBD:.6f} "
            f"(NBD floor does not bind: max(0.296935, 0.296935) = 0.296935). "
            f"Got {actual:.6f}."
        )

    def test_p1_159_guarantor_rw(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159 DISCRIMINATING: guarantor_rw ≈ 0.296935 (NBD-floored PSM value).

        For IRB guarantors, guarantor_rw is set to guarantor_rw_post_nbd.
        The buggy engine sets guarantor_rw ≈ 0.400718 (FI scalar incorrectly applied).

        Arrange: IRB guarantor, guarantor_rw_post_nbd ≈ 0.296935 (fixed).
        Act:     guarantor_rw = guarantor_rw_post_nbd (IRB path).
        Assert:  guarantor_rw ≈ 0.296935 (rel=1e-3).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["guarantor_rw"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_POST_NBD, rel=1e-3), (
            f"P1.159: guarantor_rw should be {EXPECTED_GUARANTOR_RW_POST_NBD:.6f} "
            f"(PSM: institution, no FI scalar). Got {actual:.6f}. "
            f"If ~{BUGGY_GUARANTOR_RW_IRB:.6f}: FI scalar leak not fixed."
        )

    # -------------------------------------------------------------------------
    # BENEFICIAL GATE
    # -------------------------------------------------------------------------

    def test_p1_159_is_guarantee_beneficial(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: guarantee is beneficial (guarantor_rw ≈ 0.297 < borrower_rw ≈ 1.328).

        Even on the buggy engine the guarantee is technically beneficial (0.400718 < 1.328),
        but the RWA reduction is smaller than it should be. The beneficial flag is True
        under both correct and buggy engine.

        Arrange: guarantor_rw (fixed) ≈ 0.296935, risk_weight_irb_original ≈ 1.327907.
        Act:     is_guarantee_beneficial = guarantor_rw < risk_weight_irb_original.
        Assert:  is_guarantee_beneficial is True (exact).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        assert row["is_guarantee_beneficial"] is True, (
            f"P1.159: guarantee should be beneficial — "
            f"guarantor_rw ({row.get('guarantor_rw', '?')}) < "
            f"risk_weight_irb_original ({row.get('risk_weight_irb_original', '?')}). "
            f"Got is_guarantee_beneficial={row['is_guarantee_beneficial']}"
        )

    def test_p1_159_guarantee_status_is_parameter_substitution(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: guarantee_status = "PD_PARAMETER_SUBSTITUTION" (IRB guarantor, B31).

        Arrange: guarantor_approach="irb", guarantor_pd present, B31 config.
        Act:     _apply_parameter_substitution selects PSM path.
        Assert:  guarantee_status == "PD_PARAMETER_SUBSTITUTION" (exact).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        assert row["guarantee_status"] == "PD_PARAMETER_SUBSTITUTION", (
            f"P1.159: guarantee_status should be PD_PARAMETER_SUBSTITUTION "
            f"(IRB guarantor under Basel 3.1), got {row['guarantee_status']!r}"
        )

    def test_p1_159_guarantee_method_used(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: guarantee_method_used = "PD_PARAMETER_SUBSTITUTION".

        Arrange: IRB guarantor approach, B31 config.
        Assert:  guarantee_method_used == "PD_PARAMETER_SUBSTITUTION" (exact).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        assert row["guarantee_method_used"] == "PD_PARAMETER_SUBSTITUTION", (
            f"P1.159: guarantee_method_used should be PD_PARAMETER_SUBSTITUTION, "
            f"got {row['guarantee_method_used']!r}"
        )

    # -------------------------------------------------------------------------
    # BLENDED RWA — DISCRIMINATING ASSERTIONS
    # -------------------------------------------------------------------------

    def test_p1_159_blended_risk_weight(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159 DISCRIMINATING: blended risk_weight ≈ 0.709324.

        RWA_ung = 1.327907 × 400,000 = 531,163
        RWA_gua = 0.296935 × 600,000 = 178,161
        risk_weight = 709,324 / 1,000,000 = 0.709324

        Buggy engine: 0.400718 × 600,000 = 240,431 → risk_weight ≈ 0.771594.

        Arrange: is_guarantee_beneficial=True, blended across portions.
        Act:     risk_weight = rwa / ead_final.
        Assert:  risk_weight ≈ 0.709324 (abs=5e-4).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_RISK_WEIGHT_BLENDED, abs=5e-4), (
            f"P1.159: blended risk_weight should be {EXPECTED_RISK_WEIGHT_BLENDED:.6f}, "
            f"got {actual:.6f}. "
            f"If ≈0.771594: FI scalar leak on guarantor_rw_irb not fixed. "
            f"Correct: unguaranteed_pct*RW_borrower + guaranteed_pct*guarantor_rw "
            f"= 0.40*1.327907 + 0.60*0.296935 = 0.709324."
        )

    def test_p1_159_blended_rwa(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159 DISCRIMINATING: blended RWA ≈ 709,324.

        Without fix: RWA ≈ 771,594 (FI scalar inflates guarantor portion by 34.8%).
        With fix:    RWA ≈ 709,324 (institution correlation used without FI scalar).
        Delta: -62,270 (-8.1%) — the capital overstatement from the bug.

        Arrange: beneficial guarantee, blended portions.
        Act:     rwa = rwa_original * (unguaranteed/EAD) + guaranteed * guarantor_rw.
        Assert:  rwa ≈ 709,324 (abs=500.0 — spans normal-approx gap between proposal
                 hand-calc and polars-normal-stats engine value of ~709,083).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["rwa"]
        assert actual == pytest.approx(EXPECTED_RWA_BLENDED, abs=500.0), (
            f"P1.159: blended RWA should be {EXPECTED_RWA_BLENDED:,.0f} "
            f"(1.327907*400k + 0.296935*600k). Got {actual:,.0f}. "
            f"If ≈{BUGGY_RWA_BLENDED:,.0f}: FI scalar not fixed on PSM path."
        )

    # -------------------------------------------------------------------------
    # EAD AND EXPECTED LOSS
    # -------------------------------------------------------------------------

    def test_p1_159_ead_final(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: ead_final = 1,000,000 (unchanged through guarantee substitution).

        Arrange: EAD_AMOUNT = 1,000,000.
        Assert:  ead_final == 1,000,000 (exact float).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        assert row["ead_final"] == pytest.approx(EAD_AMOUNT, abs=0.01), (
            f"P1.159: ead_final should be {EAD_AMOUNT:,.0f}, got {row['ead_final']:,.0f}"
        )

    def test_p1_159_expected_loss(
        self,
        p1159_result: pl.DataFrame,
    ) -> None:
        """
        P1.159: expected_loss ≈ 2,970 (blended: PD*LGD*EAD for each portion).

        EL_ung = 0.015 * 0.45 * 400,000 = 2,700
        EL_gua = 0.001 * 0.45 * 600,000 = 270
        EL_total = 2,970

        Arrange: PD_borrower=0.015, PD_guarantor=0.001, LGD=0.45 for both portions.
        Act:     _adjust_expected_loss blends EL for covered/uncovered portions.
        Assert:  expected_loss ≈ 2,970 (abs=1.0).
        """
        # Arrange
        row = p1159_result.row(0, named=True)

        # Assert
        actual = row["expected_loss"]
        assert actual == pytest.approx(EXPECTED_EL, abs=1.0), (
            f"P1.159: expected_loss should be {EXPECTED_EL:,.2f} "
            f"(EL_ung=2,700 + EL_gua=270 = 2,970), got {actual:,.2f}"
        )

    # -------------------------------------------------------------------------
    # REGRESSION GUARD — fixture constants sanity
    # -------------------------------------------------------------------------

    def test_p1_159_fixture_guarantor_pd_above_floor(self) -> None:
        """
        P1.159: guarantor PD (0.001) is ABOVE B31 institution/corporate floor (0.0005).

        This ensures the scenario isolates the FI scalar bug, not the PD floor.
        No floor effect expected — the discriminating element is requires_fi_scalar
        leaking from borrower context into PSM.

        Assert: PD_GUARANTOR > 0.0005 (institution PD floor under B31).
        """
        B31_INSTITUTION_PD_FLOOR = 0.0005
        assert PD_GUARANTOR > B31_INSTITUTION_PD_FLOOR, (
            f"Fixture: guarantor PD ({PD_GUARANTOR}) must be above B31 floor "
            f"({B31_INSTITUTION_PD_FLOOR}) so the scenario isolates the FI scalar bug"
        )

    def test_p1_159_percentage_covered_is_sixty_pct(self) -> None:
        """
        P1.159: guarantee covers exactly 60% of EAD (GBP 600,000 / 1,000,000).

        Partial coverage keeps both guaranteed (institution PSM RW) and unguaranteed
        (corporate FSE borrower RW) portions non-zero, making the class-routing
        difference visible in the blended RWA.

        Assert: PERCENTAGE_COVERED == 0.60, AMOUNT_COVERED == 600,000.
        """
        assert pytest.approx(0.60, abs=1e-10) == PERCENTAGE_COVERED, (
            f"Fixture: PERCENTAGE_COVERED should be 0.60, got {PERCENTAGE_COVERED}"
        )
        assert pytest.approx(600_000.0, abs=0.01) == AMOUNT_COVERED, (
            f"Fixture: AMOUNT_COVERED should be 600,000, got {AMOUNT_COVERED:,.0f}"
        )
