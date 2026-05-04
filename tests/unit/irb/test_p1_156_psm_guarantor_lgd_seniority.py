"""
P1.156 — PSM guarantor LGD must be seniority- and FSE-aware per Art. 236/161.

Pipeline position: IRB guarantee substitution (engine/irb/guarantee.py)
    _apply_parameter_substitution -> guarantor_rw

Bug: _apply_parameter_substitution() always calls
    firb_lgd_table["unsecured_senior"] (= 0.40 under Basel 3.1) regardless of
    guarantor_seniority or guarantor_is_financial_sector_entity.  This gives
    the wrong F-IRB LGD for:

    Sub-case (b) — senior + FSE guarantor:
        Correct: Art. 161(1)(a) FSE LGD = 0.45  (unsecured_senior_fse under B31)
        Current: 0.40  (unsecured_senior — non-FSE path, wrong)

    Sub-case (c) — subordinated guarantor:
        Correct: Art. 161(1)(b) LGD = 0.75  (subordinated)
        Current: 0.40  (unsecured_senior — senior path, wrong)

Expected (post-fix) guarantor IRB risk weights:
    (a) PD=0.005, LGD=0.40 (non-FSE senior)  -> RW ≈ 0.6188
    (b) PD=0.005, LGD=0.45 (FSE senior)      -> RW ≈ 0.6961
    (c) PD=0.005, LGD=0.75 (subordinated)    -> RW ≈ 1.1602

References:
    - CRR Art. 236: substitution approach for guarantees under IRB.
    - CRR Art. 161(1)(a): F-IRB supervisory LGD 45% (senior unsecured, CRR / B31 FSE).
    - CRR Art. 161(1)(aa): B31 non-FSE senior unsecured = 40%.
    - CRR Art. 161(1)(b): F-IRB supervisory LGD 75% (subordinated).
    - PRA PS1/26 Art. 161: UK alignment — same Art. references retained.
    - Bug site: src/rwa_calc/engine/irb/guarantee.py _apply_parameter_substitution()
    - Fixture:  tests/fixtures/p1_156/
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_156.p1_156 import (
    GUAR_SR_FSE_REF,
    GUAR_SR_NONFSE_REF,
    GUAR_SUB_REF,
    LOAN_A_REF,
    LOAN_B_REF,
    LOAN_C_REF,
    PD_BORROWER,
    PD_GUARANTOR,
)

import rwa_calc.engine.irb.namespace  # noqa: F401 — registers lf.irb namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import _parametric_irb_risk_weight_expr

# =============================================================================
# CONSTANTS
# =============================================================================

# Expected B31 non-FSE senior F-IRB LGD (task brief sub-case (a))
EXPECTED_LGD_SENIOR_NONFSE: float = 0.40
# Expected B31 FSE senior F-IRB LGD (task brief sub-case (b))
EXPECTED_LGD_SENIOR_FSE: float = 0.45
# Expected F-IRB subordinated LGD (task brief sub-case (c))
EXPECTED_LGD_SUBORDINATED_FLOAT: float = 0.75


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture()
def b31_config() -> CalculationConfig:
    """Basel 3.1 config with reporting date in the B31 window."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _compute_expected_guarantor_rw(lgd: float, pd: float = PD_GUARANTOR) -> float:
    """Compute expected guarantor IRB risk weight via the parametric helper.

    Mirrors the logic inside _apply_parameter_substitution() so the test
    asserts the CORRECT end-state rather than an intermediate scalar.
    """
    lf = pl.LazyFrame(
        {
            "exposure_class": ["CORPORATE"],
            "turnover_m": [None],
            "maturity": [2.5],
            "requires_fi_scalar": [False],
            "has_one_day_maturity_floor": [False],
        }
    )
    rw_expr = _parametric_irb_risk_weight_expr(
        pd_expr=pl.lit(pd),
        lgd=lgd,
        scaling_factor=1.0,  # B31: no 1.06 scaling factor
        eur_gbp_rate=0.8732,
        is_b31=True,
    )
    return lf.with_columns(rw_expr.alias("rw")).collect()["rw"][0]


def _build_guarantee_lf(
    loan_ref: str,
    guarantor_ref: str,
    guarantor_seniority: str,
    guarantor_is_financial_sector_entity: bool,
    borrower_rw: float = 1.20,
    ead: float = 1_000_000.0,
) -> pl.LazyFrame:
    """Build a minimal LazyFrame for guarantee substitution with seniority/FSE columns.

    Passes `guarantor_seniority` and `guarantor_is_financial_sector_entity` as
    input columns — these are the NEW columns the engine-implementer must
    consume in _apply_parameter_substitution() to select the correct F-IRB LGD.

    borrower_rw is set high (1.20) so the guarantee is always beneficial and
    the engine applies substitution rather than rejecting it.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [loan_ref],
            "pd": [PD_BORROWER],
            "lgd": [0.40],
            "ead_final": [ead],
            "maturity": [2.5],
            "exposure_class": ["CORPORATE"],
            "turnover_m": [None],
            "requires_fi_scalar": [False],
            "rwa": [borrower_rw * ead],
            "risk_weight": [borrower_rw],
            "guaranteed_portion": [ead],
            "unguaranteed_portion": [0.0],
            "guarantor_entity_type": ["corporate"],
            "guarantor_cqs": [3],
            "guarantor_approach": ["irb"],
            "guarantor_pd": [PD_GUARANTOR],
            # NEW columns — engine-implementer reads these to select F-IRB LGD
            "guarantor_seniority": [guarantor_seniority],
            "guarantor_is_financial_sector_entity": [guarantor_is_financial_sector_entity],
            "guarantor_reference": [guarantor_ref],
        }
    )


# =============================================================================
# P1.156 — PSM guarantor LGD seniority/FSE parametrized test
# =============================================================================


@pytest.mark.parametrize(
    "loan_ref, guarantor_ref, guarantor_seniority, guarantor_is_fse, expected_firb_lgd",
    [
        pytest.param(
            LOAN_A_REF,
            GUAR_SR_NONFSE_REF,
            "senior",
            False,
            EXPECTED_LGD_SENIOR_NONFSE,
            id="a_senior_nonfse_lgd_40pct",
        ),
        pytest.param(
            LOAN_B_REF,
            GUAR_SR_FSE_REF,
            "senior",
            True,
            EXPECTED_LGD_SENIOR_FSE,
            id="b_senior_fse_lgd_45pct",
        ),
        pytest.param(
            LOAN_C_REF,
            GUAR_SUB_REF,
            "subordinated",
            False,
            EXPECTED_LGD_SUBORDINATED_FLOAT,
            id="c_subordinated_lgd_75pct",
        ),
    ],
)
class TestP1156PSMGuarantorLGDSeniority:
    """P1.156: F-IRB guarantor LGD in parameter substitution must reflect seniority and FSE.

    Art. 236(2) routes to Art. 161(1)(a)/(aa)/(b) depending on:
    - guarantor_seniority = "subordinated"   → 75%  (Art. 161(1)(b))
    - guarantor_seniority = "senior" + FSE  → 45%  (Art. 161(1)(a))
    - guarantor_seniority = "senior" + non-FSE → 40% (Art. 161(1)(aa), Basel 3.1 only)

    Current engine always uses unsecured_senior = 0.40 for ALL cases.
    Sub-cases (b) and (c) will FAIL until the engine is fixed.
    """

    def test_p1_156_guarantor_rw_reflects_correct_firb_lgd(
        self,
        b31_config: CalculationConfig,
        loan_ref: str,
        guarantor_ref: str,
        guarantor_seniority: str,
        guarantor_is_fse: bool,
        expected_firb_lgd: float,
    ) -> None:
        """guarantor_rw must be computed from the seniority/FSE-aware F-IRB LGD.

        The IRB risk weight is a monotone function of LGD; asserting on the
        final guarantor_rw is the most direct observable test of which LGD
        branch was taken.

        Sub-case (a): senior non-FSE → LGD=0.40 → RW already produced by current
                       engine (passes today, regression guard).
        Sub-case (b): senior FSE     → LGD=0.45 → current engine uses 0.40 (FAILS).
        Sub-case (c): subordinated   → LGD=0.75 → current engine uses 0.40 (FAILS).
        """
        # Arrange
        expected_rw = _compute_expected_guarantor_rw(lgd=expected_firb_lgd)
        lf = _build_guarantee_lf(
            loan_ref=loan_ref,
            guarantor_ref=guarantor_ref,
            guarantor_seniority=guarantor_seniority,
            guarantor_is_financial_sector_entity=guarantor_is_fse,
        )

        # Act
        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Assert: guarantor_rw must reflect the seniority/FSE-aware F-IRB LGD.
        # Sub-cases (b) and (c) FAIL here because the engine uses LGD=0.40 for all.
        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(expected_rw, rel=1e-4), (
            f"[{guarantor_seniority}/fse={guarantor_is_fse}] "
            f"Expected guarantor_rw ≈ {expected_rw:.6f} "
            f"(from F-IRB LGD={expected_firb_lgd}, PD={PD_GUARANTOR}), "
            f"got {actual_rw:.6f}. "
            f"Engine is using LGD=0.40 (unsecured_senior) for all cases "
            f"instead of routing via guarantor_seniority/guarantor_is_financial_sector_entity."
        )

    def test_p1_156_guarantee_method_is_pd_parameter_substitution(
        self,
        b31_config: CalculationConfig,
        loan_ref: str,
        guarantor_ref: str,
        guarantor_seniority: str,
        guarantor_is_fse: bool,
        expected_firb_lgd: float,
    ) -> None:
        """Guarantee method must be PD_PARAMETER_SUBSTITUTION (IRB guarantor under B31).

        Regression guard: ensure seniority/FSE routing does not accidentally
        fall back to SA_RW_SUBSTITUTION.
        """
        # Arrange
        lf = _build_guarantee_lf(
            loan_ref=loan_ref,
            guarantor_ref=guarantor_ref,
            guarantor_seniority=guarantor_seniority,
            guarantor_is_financial_sector_entity=guarantor_is_fse,
        )

        # Act
        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Assert: all sub-cases use parameter substitution (IRB guarantor, has PD)
        assert result["guarantee_method_used"][0] == "PD_PARAMETER_SUBSTITUTION", (
            f"[{guarantor_seniority}/fse={guarantor_is_fse}] "
            f"Expected PD_PARAMETER_SUBSTITUTION, "
            f"got {result['guarantee_method_used'][0]}"
        )
