"""
P1.157 — Basel 3.1 PSM Art. 160(4) "no better than direct" floor (PSM in guarantor context).

Pipeline position:
    IRB guarantee substitution (_apply_parameter_substitution → guarantor_rw_post_nbd)

Scenario design:
    Per Art. 236(1)(a)(i) (PRA PS1/26) the PSM correlation must be derived from
    the **guarantor's** exposure class context, not the borrower's. With the
    correct engine (post-P1.159) ``guarantor_rw_irb`` and ``rw_direct`` are
    both computed in the guarantor's corporate context and produce the same
    value here (≈ 0.17489), so the Art. 160(4) NBD floor does not strictly
    bind in this scenario — but the floor mechanic is still exercised by the
    test (max(guarantor_rw_irb, rw_direct) is taken and emitted as
    ``guarantor_rw_post_nbd``).

    The blended RWA on the guaranteed portion (≈ 233,494) is materially higher
    than the borrower's QRRE RW × 60% would be — i.e., PSM raises the capital
    on the covered portion, which is the substantive Art. 160(4) outcome.

Borrower (QRRE revolver, A-IRB):
    exposure_class  = RETAIL_QRRE
    is_qrre_transactor = False  (revolver, not transactor)
    PD_borrower     = 0.0200, LGD_borrower = 0.50
    EAD             = 1,000,000 GBP, R=0.04 (retail), MA=1.0

Guarantor (corporate, F-IRB via PSM):
    PD_guarantor_raw    = 0.0004  (below B31 corporate floor 0.0005 per Art. 163(1)(a))
    PD_guarantor_floored = 0.0005  (Art. 163(1)(a) corporate floor)
    F-IRB supervisory LGD (senior, non-FSE, B31) = 0.40 (Art. 161(1)(aa))

Guarantee:
    amount_covered = 600,000 GBP (60% of EAD)
    guarantor_seniority = "senior"
    original_maturity_years = 5.0

Hand calculation:
    Borrower pre-CRM RW           = 0.32140  (QRRE R=0.04, MA=1.0, PD=0.02, LGD=0.50)
    PD_guarantor_floored          = 0.0005   (corporate floor, Art. 163(1)(a))
    guarantor_rw_irb              = 0.17489  (PSM in GUARANTOR corporate context — Art. 236(1)(a)(i))
    RW_direct                     = 0.17489  (NBD: same guarantor corporate context)
    guarantor_rw_post_nbd         = max(0.17489, 0.17489) = 0.17489
    is_guarantee_beneficial       = True (0.17489 < 0.32140)
    RWA_blended                   = 321,400×0.40 + 600,000×0.17489 = 233,494

Regulatory references:
    - PRA PS1/26 Art. 236(1)(a)(i): PSM correlation derived from guarantor's class
    - PRA PS1/26 Art. 160(4): "no better than direct" floor on PSM RW
    - PRA PS1/26 Art. 163(1)(a): Corporate PD floor 0.05%
    - PRA PS1/26 Art. 161(1)(aa): B31 F-IRB supervisory LGD 40% (non-FSE senior corporate)
    - CRR Art. 154: Retail QRRE correlation R=0.04
    - CRR Art. 153: Corporate correlation formula

Code references:
    - src/rwa_calc/engine/irb/guarantee.py — _apply_parameter_substitution
    - src/rwa_calc/engine/irb/guarantee.py — _apply_no_better_than_direct_floor
    - src/rwa_calc/engine/irb/formulas.py — _parametric_irb_risk_weight_expr
    - src/rwa_calc/engine/irb/formulas.py — _pd_floor_expression
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_157.p1_157 import (
    AMOUNT_COVERED,
    EAD_FACILITY,
    FACILITY_REF,
    GUARANTOR_REF,
    LGD_BORROWER,
    ORIGINAL_MATURITY_YEARS,
    PD_BORROWER,
    PD_GUARANTOR_FLOORED,
    PD_GUARANTOR_RAW,
    PERCENTAGE_COVERED,
)

import rwa_calc.engine.irb.namespace  # noqa: F401 — registers lf.irb namespace
from rwa_calc.contracts.config import CalculationConfig

# =============================================================================
# Scenario expected values (from hand-calculation in tmp/scenario-P1.157.md)
# =============================================================================

# Borrower pre-CRM QRRE revolver IRB RW: R=0.04, MA=1.0, PD=0.02, LGD=0.50
# N[-1.46527] ≈ 0.07142; K = 0.50×0.07142 − 0.02×0.50 = 0.02571; RW = 0.02571×12.5
EXPECTED_RW_ORIGINAL: float = 0.32140
EXPECTED_RWA_ORIGINAL: float = 321_400.0

# guarantor_rw_irb: PSM in GUARANTOR's corporate context per Art. 236(1)(a)(i)
# (R≈0.237, MA≈1.75 at M=2.5, LGD=0.40, floored PD=0.0005). Equal to rw_direct
# in this scenario because both use the guarantor's class.
EXPECTED_GUARANTOR_RW_IRB: float = 0.17489

# RW_direct: NBD uses GUARANTOR's corporate context (R~0.237, MA~1.75, M=2.5)
# PD=0.0005, LGD=0.40 → RW_direct = 0.17489 >> guarantor_rw_irb
EXPECTED_RW_DIRECT: float = 0.17489

# guarantor_rw_post_nbd = max(guarantor_rw_irb, RW_direct) = max(0.01346, 0.17489) = 0.17489
EXPECTED_GUARANTOR_RW_POST_NBD: float = 0.17489

# Blended RWA (guarantee is beneficial: 0.17489 < 0.32140)
# RWA_unguaranteed = 321,400 × (400,000/1,000,000) = 128,560
# RWA_guaranteed   = 600,000 × 0.17489              = 104,934
EXPECTED_RISK_WEIGHT_BLENDED: float = 0.23349
EXPECTED_RWA_BLENDED: float = 233_494.0
EXPECTED_EL_BLENDED: float = 4_120.0

# =============================================================================
# Helpers
# =============================================================================


def _b31_config() -> CalculationConfig:
    """Basel 3.1 calculation config for P1.157 tests."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _build_p1157_lf(
    *,
    borrower_rw: float = EXPECTED_RW_ORIGINAL,
    ead: float = EAD_FACILITY,
) -> pl.LazyFrame:
    """
    Build a minimal IRB LazyFrame for the P1.157 scenario.

    Represents the QRRE revolver borrower after IRB formula has been applied,
    with the corporate guarantor's attributes joined by the CRM processor.
    This is the input shape consumed by apply_guarantee_substitution().

    The exposure_class="retail_qrre" determines:
    - PSM correlation: R=0.04 (retail QRRE)
    - PSM maturity adjustment: MA=1.0 (no MA for retail)
    - PD floor for guarantor PD in PSM: should use corporate floor 0.0005
      (Art. 163(1)(a)) since the guaranteed portion is treated as a direct
      exposure to the corporate guarantor — not the QRRE revolver floor 0.0010.

    The `maturity=2.5` is used by the NBD direct-curve calculation
    (_apply_no_better_than_direct_floor) when it swaps in the guarantor's
    corporate exposure class. At M=2.5 the corporate MA ≈ 1.75, making
    RW_direct >> guarantor_rw_irb (NBD floor load-bearing).
    """
    guaranteed = AMOUNT_COVERED
    unguaranteed = ead - guaranteed
    el_pre_crm = PD_BORROWER * LGD_BORROWER * ead

    return pl.LazyFrame(
        {
            # --- Exposure identity ---
            "exposure_reference": [FACILITY_REF],
            "exposure_class": ["retail_qrre"],
            # --- Borrower IRB parameters ---
            "pd": [PD_BORROWER],
            "lgd": [LGD_BORROWER],
            "maturity": [2.5],
            "ead_final": [ead],
            "turnover_m": [None],
            "requires_fi_scalar": [False],
            "has_one_day_maturity_floor": [False],
            "is_qrre_transactor": [False],
            # --- Pre-CRM IRB results ---
            "rwa": [borrower_rw * ead],
            "risk_weight": [borrower_rw],
            "expected_loss": [el_pre_crm],
            # --- Guarantee split (from CRM processor) ---
            "guaranteed_portion": [guaranteed],
            "unguaranteed_portion": [unguaranteed],
            # --- Guarantor attributes (joined by CRM processor) ---
            "guarantor_entity_type": ["corporate"],
            "guarantor_cqs": [1],
            "guarantor_approach": ["irb"],
            "guarantor_pd": [PD_GUARANTOR_RAW],
            "guarantor_reference": [GUARANTOR_REF],
            "guarantor_seniority": ["senior"],
            "guarantor_is_financial_sector_entity": [False],
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
# P1.157 acceptance test class
# =============================================================================


class TestP1157PSMNoBetterThanDirect:
    """
    P1.157: Basel 3.1 PSM Art. 160(4) "no better than direct" floor mechanic.

    Per Art. 236(1)(a)(i) (post-P1.159) the PSM correlation is derived from
    the GUARANTOR's class context, so ``guarantor_rw_irb`` and ``rw_direct``
    are both computed in the guarantor's corporate context and equal each
    other here (≈ 17.49%). The NBD floor (max-of-two) is still emitted as
    ``guarantor_rw_post_nbd`` even when it does not strictly raise the RW.

    The guarantee remains beneficial (17.49% < borrower_rw 32.14%), producing
    a blended RWA of 233,494.
    """

    @pytest.fixture(scope="class")
    def config(self) -> CalculationConfig:
        """Basel 3.1 config for P1.157 tests."""
        return _b31_config()

    @pytest.fixture(scope="class")
    def p1157_result(self, config: CalculationConfig) -> pl.DataFrame:
        """
        Apply guarantee substitution to the P1.157 exposure and collect results.

        Arrange: QRRE revolver with 60% corporate IRB guarantee.
                 Guarantor PD_raw=0.0004 below B31 corporate floor 0.0005.
                 PSM in guarantor corporate context: rw_irb == rw_direct ≈ 0.17489.
        Act:     lf.irb.apply_guarantee_substitution(config).
        Return:  Collected DataFrame for all assertions.
        """
        lf = _build_p1157_lf()
        return lf.irb.apply_guarantee_substitution(config).collect()

    # -------------------------------------------------------------------------
    # BORROWER PRE-CRM VALUES — regression guard (must be stable)
    # -------------------------------------------------------------------------

    def test_p1_157_risk_weight_irb_original(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: pre-CRM borrower RW = 0.32140 (QRRE R=0.04, MA=1.0, PD=0.02, LGD=0.50).

        Arrange: QRRE revolver, PD=2%, LGD=50%, EAD=£1m.
        Act:     apply_guarantee_substitution stores original as risk_weight_irb_original.
        Assert:  risk_weight_irb_original ≈ 0.32140 (rel=1e-3).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["risk_weight_irb_original"]
        assert actual == pytest.approx(EXPECTED_RW_ORIGINAL, rel=1e-3), (
            f"P1.157: risk_weight_irb_original should be {EXPECTED_RW_ORIGINAL:.5f} "
            f"(QRRE revolver R=0.04, MA=1.0), got {actual:.5f}"
        )

    def test_p1_157_rwa_irb_original(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: pre-CRM borrower RWA = 321,400 (EAD × 0.32140).

        Arrange: EAD=£1,000,000, risk_weight_irb_original=0.32140.
        Act:     apply_guarantee_substitution stores original as rwa_irb_original.
        Assert:  rwa_irb_original ≈ 321,400 (rel=1e-3).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["rwa_irb_original"]
        assert actual == pytest.approx(EXPECTED_RWA_ORIGINAL, rel=1e-3), (
            f"P1.157: rwa_irb_original should be {EXPECTED_RWA_ORIGINAL:,.0f}, got {actual:,.0f}"
        )

    # -------------------------------------------------------------------------
    # PSM INTERMEDIATE COLUMNS — core correctness assertions
    # -------------------------------------------------------------------------

    def test_p1_157_guarantor_rw_irb(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantor_rw_irb ≈ 0.17489 (PSM in GUARANTOR corporate context).

        Per Art. 236(1)(a)(i) the PSM correlation is derived from the
        **guarantor's** exposure class context — corporate (R≈0.237) at M=2.5,
        with floored PD=0.0005 (Art. 163(1)(a)) and F-IRB supervisory LGD=0.40
        (Art. 161(1)(aa)). The borrower's QRRE class plays no role in the
        guarantor's PSM RW.

        Arrange: guarantor_pd=0.0004 → floored to 0.0005, exposure_class=corporate.
        Act:     _apply_parameter_substitution evaluates PSM RW in guarantor context.
        Assert:  guarantor_rw_irb ≈ 0.17489 (rel=1e-2).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["guarantor_rw_irb"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_IRB, rel=1e-2), (
            f"P1.157: guarantor_rw_irb should be {EXPECTED_GUARANTOR_RW_IRB:.5f} "
            f"(PSM in guarantor corporate context: R≈0.237, MA≈1.75 at M=2.5, "
            f"floored PD=0.0005, LGD=0.40). Got {actual:.5f}."
        )

    def test_p1_157_rw_direct(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: rw_direct = 0.17489 (NBD: corporate context, R~0.237, MA~1.75, M=2.5).

        RW_direct is the IRB risk weight the guarantor would attract as a DIRECT
        borrower, using the guarantor's own corporate exposure class and M=2.5.
        This is the Art. 160(4) reference point against which guarantor_rw_irb
        is floored.

        Arrange: guarantor_pd_floored=0.0005, corporate class, maturity=2.5.
        Act:     _apply_no_better_than_direct_floor swaps in corporate class context.
        Assert:  rw_direct ≈ 0.17489 (rel=1e-2).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["rw_direct"]
        assert actual == pytest.approx(EXPECTED_RW_DIRECT, rel=1e-2), (
            f"P1.157: rw_direct should be {EXPECTED_RW_DIRECT:.5f} "
            f"(corporate context: R~0.237, MA~1.75 at M=2.5, PD=0.0005, LGD=0.40), "
            f"got {actual:.5f}"
        )

    # -------------------------------------------------------------------------
    # LOAD-BEARING NBD FLOOR ASSERTIONS — the core P1.157 requirement
    # -------------------------------------------------------------------------

    def test_p1_157_guarantor_rw_post_nbd_equals_rw_direct(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantor_rw_post_nbd == rw_direct (NBD floor mechanic emits max).

        Art. 160(4) "no better than direct" floor: the substituted RW for the
        guaranteed portion must not be lower than the RW the guarantor would
        attract as a direct borrower. ``guarantor_rw_post_nbd`` is the
        ``max(guarantor_rw_irb, rw_direct)`` regardless of whether the floor
        strictly binds.

        Under Art. 236(1)(a)(i) (post-P1.159) ``guarantor_rw_irb`` and
        ``rw_direct`` are both computed in the guarantor's corporate context
        and are equal here, so the NBD floor does not strictly raise the RW —
        but the max is still emitted as ``guarantor_rw_post_nbd`` and equals
        ``rw_direct``.

        Arrange: guarantor_rw_irb ≈ rw_direct ≈ 0.17489.
        Act:     max(guarantor_rw_irb, rw_direct).
        Assert:  guarantor_rw_post_nbd == rw_direct (within rel=1e-3)
                 AND guarantor_rw_post_nbd >= guarantor_rw_irb.
        """
        # Arrange
        row = p1157_result.row(0, named=True)
        post_nbd = row["guarantor_rw_post_nbd"]
        rw_direct = row["rw_direct"]
        rw_irb = row["guarantor_rw_irb"]

        # Assert: post_nbd equals rw_direct (max-of-two, with rw_direct >= rw_irb)
        assert post_nbd == pytest.approx(rw_direct, rel=1e-3), (
            f"P1.157 Art. 160(4): guarantor_rw_post_nbd ({post_nbd:.5f}) must equal "
            f"rw_direct ({rw_direct:.5f}). guarantor_rw_irb = {rw_irb:.5f}"
        )

        # Assert: NBD-floored value is never below the raw PSM RW
        assert post_nbd >= rw_irb, (
            f"P1.157 Art. 160(4): guarantor_rw_post_nbd ({post_nbd:.5f}) must be "
            f">= guarantor_rw_irb ({rw_irb:.5f}). "
        )

    def test_p1_157_guarantor_rw_post_nbd_value(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantor_rw_post_nbd = 0.17489 (== rw_direct, NBD floor applies).

        The proposal expected value. See test_p1_157_guarantor_rw_post_nbd_equals_rw_direct
        for the structural assertion.

        Arrange: rw_direct ≈ 0.17489, guarantor_rw_irb ≈ 0.01346.
        Act:     guarantor_rw_post_nbd = max(rw_irb, rw_direct).
        Assert:  guarantor_rw_post_nbd ≈ 0.17489 (rel=1e-2).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["guarantor_rw_post_nbd"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_POST_NBD, rel=1e-2), (
            f"P1.157: guarantor_rw_post_nbd should be {EXPECTED_GUARANTOR_RW_POST_NBD:.5f} "
            f"(NBD floor: max(0.01346, 0.17489) = 0.17489), got {actual:.5f}"
        )

    def test_p1_157_guarantor_rw_equals_post_nbd(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantor_rw == guarantor_rw_post_nbd (NBD-floored value used).

        After the NBD floor, guarantor_rw must equal guarantor_rw_post_nbd for IRB
        guarantors (not the raw guarantor_rw_irb). The beneficial gate and blending
        both consume guarantor_rw.

        Arrange: IRB guarantor, post_nbd floor applied.
        Act:     guarantor_rw is set to guarantor_rw_post_nbd for IRB guarantors.
        Assert:  guarantor_rw == guarantor_rw_post_nbd (within rel=1e-2).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual_rw = row["guarantor_rw"]
        actual_post_nbd = row["guarantor_rw_post_nbd"]
        assert actual_rw == pytest.approx(actual_post_nbd, rel=1e-3), (
            f"P1.157: guarantor_rw ({actual_rw:.5f}) must equal "
            f"guarantor_rw_post_nbd ({actual_post_nbd:.5f}) for IRB guarantors — "
            f"the NBD-floored value is the one used for blending and the beneficial gate."
        )
        assert actual_rw == pytest.approx(EXPECTED_GUARANTOR_RW_POST_NBD, rel=1e-2), (
            f"P1.157: guarantor_rw should be {EXPECTED_GUARANTOR_RW_POST_NBD:.5f} "
            f"(NBD-floored), got {actual_rw:.5f}"
        )

    # -------------------------------------------------------------------------
    # BENEFICIAL GATE — guarantee applies because NBD RW < borrower RW
    # -------------------------------------------------------------------------

    def test_p1_157_is_guarantee_beneficial(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantee is beneficial (guarantor_rw_post_nbd < borrower RW).

        After the NBD floor: guarantor_rw = 0.17489 < borrower_rw = 0.32140.
        The guarantee reduces capital → is_guarantee_beneficial = True.

        Art. 213: guarantees are only applied when they provide a capital benefit.

        Arrange: guarantor_rw_post_nbd=0.17489, risk_weight_irb_original=0.32140.
        Act:     guarantor_rw < risk_weight_irb_original → is_guarantee_beneficial=True.
        Assert:  is_guarantee_beneficial == True.
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        assert row["is_guarantee_beneficial"] is True, (
            f"P1.157: guarantee should be beneficial — "
            f"guarantor_rw_post_nbd ({row['guarantor_rw_post_nbd']:.5f}) < "
            f"borrower_rw ({row['risk_weight_irb_original']:.5f}). "
            f"Got is_guarantee_beneficial={row['is_guarantee_beneficial']}"
        )

    def test_p1_157_guarantee_status_is_parameter_substitution(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantee_status = "PD_PARAMETER_SUBSTITUTION" (IRB guarantor, B31).

        IRB guarantor under Basel 3.1 → PD parameter substitution method used.

        Arrange: guarantor_approach="irb", guarantor_pd present, B31 config.
        Act:     _apply_parameter_substitution selects PSM path.
        Assert:  guarantee_status == "PD_PARAMETER_SUBSTITUTION".
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        assert row["guarantee_status"] == "PD_PARAMETER_SUBSTITUTION", (
            f"P1.157: guarantee_status should be PD_PARAMETER_SUBSTITUTION "
            f"(IRB guarantor under Basel 3.1), got {row['guarantee_status']!r}"
        )

    # -------------------------------------------------------------------------
    # BLENDED RWA — final capital outcome
    # -------------------------------------------------------------------------

    def test_p1_157_blended_risk_weight(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: blended risk weight = 0.23349 after NBD floor + guarantee blending.

        RWA_blended = 321,400×0.40 + 600,000×0.17489 = 233,494
        risk_weight_blended = 233,494 / 1,000,000 = 0.23349

        This reflects the NBD floor raising the guaranteed portion's RW from
        1.35% (raw PSM) to 17.49% (NBD-floored). Without the NBD floor the
        blended RW would be ~0.13664 (RWA 136,636).

        Arrange: blended result after beneficial guarantee applied.
        Act:     risk_weight = rwa / ead_final.
        Assert:  risk_weight ≈ 0.23349 (rel=1e-3).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_RISK_WEIGHT_BLENDED, rel=1e-3), (
            f"P1.157: blended risk_weight should be {EXPECTED_RISK_WEIGHT_BLENDED:.5f}, "
            f"got {actual:.5f}. "
            f"Blended = unguaranteed_rwa/EAD + guaranteed_pct×guarantor_rw_post_nbd "
            f"= 0.40×0.32140 + 0.60×0.17489 = 0.23349"
        )

    def test_p1_157_blended_rwa(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: blended RWA = 233,494 after NBD floor application.

        Without NBD floor: guarantor_rw=0.01346 → RWA_blended=136,636
        With NBD floor:    guarantor_rw=0.17489 → RWA_blended=233,494
        Delta: +96,858 (+71%)

        This is the primary financial impact of Art. 160(4). The NBD floor
        prevents firms from exploiting PSM to achieve artificially low RWA
        on the guaranteed portion.

        Arrange: beneficial guarantee, blended across unguaranteed/guaranteed portions.
        Act:     rwa = rwa_original×(unguaranteed/EAD) + guaranteed×guarantor_rw_post_nbd.
        Assert:  rwa ≈ 233,494 (rel=1e-3).
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        actual = row["rwa"]
        assert actual == pytest.approx(EXPECTED_RWA_BLENDED, rel=1e-3), (
            f"P1.157: blended RWA should be {EXPECTED_RWA_BLENDED:,.0f} "
            f"(321,400×0.40 + 600,000×0.17489), got {actual:,.0f}. "
            f"If RWA≈136,636: NBD floor not applied (guarantor_rw=0.01346 used instead of 0.17489). "
            f"If RWA≈233,494: NBD floor correct."
        )

    # -------------------------------------------------------------------------
    # REGRESSION GUARD — fixture constants sanity check
    # -------------------------------------------------------------------------

    def test_p1_157_fixture_pd_below_corporate_floor(self) -> None:
        """
        P1.157: fixture guarantor PD (0.0004) is below B31 corporate floor (0.0005).

        This is the input condition that makes Art. 160(4) load-bearing:
        the guarantor's low raw PD, when floored to 0.0005 (corporate floor),
        gives a very low guarantor_rw_irb in the QRRE context. The NBD floor
        then raises this to RW_direct (corporate context at M=2.5).

        Arrange: fixture constants PD_GUARANTOR_RAW, PD_GUARANTOR_FLOORED.
        Assert:  PD_GUARANTOR_RAW < PD_GUARANTOR_FLOORED == 0.0005.
        """
        # Assert — fixture constants
        assert PD_GUARANTOR_RAW < PD_GUARANTOR_FLOORED, (
            f"Fixture: raw guarantor PD ({PD_GUARANTOR_RAW}) must be below "
            f"B31 corporate floor ({PD_GUARANTOR_FLOORED}) so Art. 160(4) is exercised"
        )
        assert pytest.approx(0.0005, abs=1e-10) == PD_GUARANTOR_FLOORED, (
            f"B31 corporate PD floor should be 0.0005 (0.05%), got {PD_GUARANTOR_FLOORED}"
        )

    def test_p1_157_percentage_covered_is_sixty_pct(self) -> None:
        """
        P1.157: guarantee covers exactly 60% of EAD (GBP 600,000 / 1,000,000).

        Regression guard: ensures partial guarantee blending arithmetic is exercised,
        not full substitution. Unguaranteed portion (40%) retains borrower's RW.

        Assert: PERCENTAGE_COVERED == 0.60, AMOUNT_COVERED == 600,000.
        """
        assert pytest.approx(0.60, abs=1e-10) == PERCENTAGE_COVERED, (
            f"Fixture: PERCENTAGE_COVERED should be 0.60, got {PERCENTAGE_COVERED}"
        )
        assert pytest.approx(600_000.0, abs=0.01) == AMOUNT_COVERED, (
            f"Fixture: AMOUNT_COVERED should be 600,000, got {AMOUNT_COVERED:,.0f}"
        )
