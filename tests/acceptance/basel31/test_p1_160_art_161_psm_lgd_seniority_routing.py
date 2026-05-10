"""
P1.160 — Basel 3.1 PSM F-IRB LGD routing by guarantor_seniority (subordinated).

Pipeline position:
    CRMProcessor.apply_guarantees -> IRB guarantee substitution
    (_apply_parameter_substitution -> guarantor_rw_irb)

Scenario design:
    The discriminating element is guarantor_seniority="subordinated" on the guarantee
    row. Under Art. 161(1)(b), a subordinated claim carries F-IRB supervisory LGD=0.75.
    Art. 161(1)(aa) gives LGD=0.40 for a senior non-FSE claim.

    The gap: engine/crm/guarantees.py::apply_guarantees does not thread the
    guarantor_seniority column from the guarantee table to the exposure frame.
    When apply_guarantee_substitution (irb/guarantee.py) checks for the column
    and finds it absent, it defaults to "senior" (line 330: fill_null("senior")),
    routing every row to LGD=0.40 regardless of the actual guarantee seniority.

    Fixed engine: guarantor_seniority propagated from guarantee table through CRM →
        guarantor_seniority="subordinated" → LGD=0.75 (Art. 161(1)(b))
        → guarantor_rw_irb ≈ 1.16037 → guarantee NOT beneficial
        → engine retains borrower RWA ≈ 938,690 (is_guarantee_beneficial=False)

    Buggy engine: guarantor_seniority not threaded → defaults to "senior"
        → LGD=0.40 (Art. 161(1)(aa)) → guarantor_rw_irb ≈ 0.61887
        → guarantee wrongly applied → RWA ≈ 618,870

Borrower (CORPORATE, F-IRB, non-FSE):
    PD_borrower       = 0.0150 (1.5%), above B31 corporate floor 0.0005
    F-IRB supervisory LGD (senior, non-FSE, B31) = 0.40 (Art. 161(1)(aa))
    EAD = 1,000,000 GBP, M = 2.5y
    Borrower IRB RW ≈ 0.93869

Guarantor (CORPORATE, F-IRB, non-FSE, SUBORDINATED):
    PD_guarantor      = 0.0050 (0.5%), above B31 corporate floor 0.0005
    F-IRB supervisory LGD (subordinated, B31) = 0.75 (Art. 161(1)(b))
    guarantor_rw_irb post-fix ≈ 1.16037 → NOT beneficial
    guarantor_rw_irb pre-fix  ≈ 0.61887 (LGD=0.40 wrong) → wrongly applied

Guarantee:
    guarantor_seniority = "subordinated"  — the load-bearing field
    amount_covered = 1,000,000 GBP (100% coverage)
    original_maturity_years = 5.0 (>= M=2.5 → Art. 237(2)(a) satisfied)

Hand calculation:
    Borrower RW: corporate, PD=0.015, LGD=0.40, M=2.5
        R ≈ 0.17668, MA ≈ 1.222885, K ≈ 0.07510, RW ≈ 0.93869
        RWA ≈ 938,690

    Guarantor RW post-fix (LGD=0.75, subordinated):
        corporate, PD=0.005, LGD=0.75, M=2.5
        R ≈ 0.23641, MA ≈ 1.588, K ≈ 0.09283, RW ≈ 1.16037 > 0.93869
        → is_guarantee_beneficial=False → RWA retained = 938,690

    Guarantor RW pre-fix (LGD=0.40, wrong — bug):
        corporate, PD=0.005, LGD=0.40, M=2.5 → RW ≈ 0.61887 < 0.93869
        → is_guarantee_beneficial=True → RWA ≈ 618,870 (wrong)

Regulatory references:
    - PRA PS1/26 Art. 236(1)(a): PSM substitutes guarantor PD/LGD/correlation.
    - PRA PS1/26 Art. 161(1)(aa): B31 F-IRB supervisory LGD 40% (senior, non-FSE).
    - PRA PS1/26 Art. 161(1)(b): B31 F-IRB supervisory LGD 75% (subordinated claim).
    - PRA PS1/26 Art. 163(1)(a): Corporate PD floor 0.05% (both PDs above floor).
    - Code gap: src/rwa_calc/engine/crm/guarantees.py::apply_guarantees not threading
      guarantor_seniority from the guarantee table to the exposure frame.
    - Fix target: src/rwa_calc/engine/irb/guarantee.py:357-365 — seniority branch correct,
      but only works once CRM threads the column through.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_160.p1_160 import (
    AMOUNT_COVERED,
    BORROWER_REF,
    EAD_AMOUNT,
    EFFECTIVE_MATURITY,
    GUARANTEE_REF,
    GUARANTOR_REF,
    LOAN_REF,
    ORIGINAL_MATURITY_YEARS,
    PD_BORROWER,
    PD_GUARANTOR,
    PERCENTAGE_COVERED,
)

import rwa_calc.engine.irb.namespace  # noqa: F401 — registers lf.irb namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Scenario expected values (from hand-calculation in module docstring above)
# =============================================================================

# Borrower pre-CRM RW: corporate non-FSE, PD=0.015, LGD=0.40 (B31 senior), M=2.5
EXPECTED_RW_ORIGINAL: float = 0.93869
EXPECTED_RWA_ORIGINAL: float = 938_690.0

# Guarantor PSM RW post-fix (CORRECT: LGD=0.75, subordinated, Art. 161(1)(b)):
# corporate, PD=0.005, LGD=0.75, M=2.5 → RW ≈ 1.16037 > borrower_rw → NOT beneficial
EXPECTED_GUARANTOR_RW_IRB_CORRECT: float = 1.16037

# Guarantor PSM RW pre-fix (BUGGY: LGD=0.40, senior default applied due to missing column):
# corporate, PD=0.005, LGD=0.40, M=2.5 → RW ≈ 0.61887 < borrower_rw → wrongly applied
BUGGY_GUARANTOR_RW_IRB: float = 0.61887

# Post-fix: guarantee NOT beneficial → borrower RWA retained at 938,690
EXPECTED_RWA_POST_FIX: float = 938_690.0
EXPECTED_RISK_WEIGHT_POST_FIX: float = 0.93869

# Pre-fix bug: guarantee wrongly applied → blended RWA ≈ 618,870
BUGGY_RWA: float = 618_870.0

# EL (post-fix, no substitution — borrower retains own EL):
# EL = PD_borrower * LGD_senior * EAD = 0.015 * 0.40 * 1,000,000 = 6,000
EXPECTED_EL_POST_FIX: float = 6_000.0


# =============================================================================
# Helpers
# =============================================================================


def _b31_config() -> CalculationConfig:
    """Basel 3.1 calculation config for P1.160 tests (F-IRB, post-2027)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


def _build_p1160_crm_and_irb_result(
    *,
    guarantor_seniority: str = "subordinated",
    ead: float = EAD_AMOUNT,
) -> pl.DataFrame:
    """
    Run the P1.160 scenario through the CRM + IRB pipeline and return results.

    This exercises the complete path from apply_guarantees (CRM) through
    apply_guarantee_substitution (IRB) — the same path P1.160 bugs through.

    The discriminating input: guarantor_seniority on the guarantee row. The bug
    is that apply_guarantees (crm/guarantees.py) does not thread this column to
    the exposure frame, so irb/guarantee.py falls back to "senior" (LGD=0.40)
    regardless of the actual guarantee seniority.

    Arrange:
        - Corporate borrower (non-FSE), PD=0.015, LGD=0.40 (senior, B31 Art. 161(1)(aa))
        - Corporate guarantor (non-FSE), internal PD=0.005, subordinated guarantee
        - Guarantee: guarantor_seniority="subordinated" (load-bearing field),
          original_maturity_years=5.0, 100% coverage

    Act:
        processor.apply_guarantees → .irb.classify_approach → .irb.apply_firb_lgd
        → .irb.prepare_columns → .irb.apply_all_formulas → .irb.compute_el_shortfall_excess
        → .irb.apply_guarantee_substitution

    Returns:
        Collected DataFrame with IRB guarantee substitution results.
    """
    config = _b31_config()
    processor = CRMProcessor(is_basel_3_1=config.is_basel_3_1)

    exposures = pl.LazyFrame(
        {
            # --- Exposure identity ---
            "exposure_reference": [LOAN_REF],
            "counterparty_reference": [BORROWER_REF],
            "exposure_class": ["corporate"],
            "approach": [ApproachType.FIRB.value],
            "is_airb": [False],
            # --- Borrower IRB parameters (pre-CRM) ---
            "pd": [PD_BORROWER],
            "lgd": [0.40],
            "maturity": [EFFECTIVE_MATURITY],
            "currency": ["GBP"],
            "seniority": ["senior"],
            # --- EAD columns required by CRM processor ---
            "ead_after_collateral": [ead],
            "ead_final": [ead],
            "risk_type": ["drawn"],
            "ccf": [1.0],
            "nominal_amount": [0.0],
            "drawn_amount": [ead],
            "ead_from_ccf": [0.0],
        }
    )

    # Guarantee row — guarantor_seniority is the load-bearing field for this scenario.
    # The bug: crm/guarantees.py does not thread this column to the exposure frame.
    guarantees = pl.LazyFrame(
        {
            "guarantee_reference": [GUARANTEE_REF],
            "guarantee_type": ["corporate_guarantee"],
            "guarantor": [GUARANTOR_REF],
            "currency": ["GBP"],
            "maturity_date": [date(2030, 12, 31)],
            "amount_covered": [AMOUNT_COVERED],
            "percentage_covered": [PERCENTAGE_COVERED],
            "beneficiary_type": ["loan"],
            "beneficiary_reference": [LOAN_REF],
            "protection_type": ["guarantee"],
            "includes_restructuring": [True],
            "original_maturity_years": [ORIGINAL_MATURITY_YEARS],
            # THE LOAD-BEARING FIELD — the bug is that this never reaches the IRB stage:
            "guarantor_seniority": [guarantor_seniority],
        }
    )

    counterparty_lookup = pl.LazyFrame(
        {
            "counterparty_reference": [BORROWER_REF, GUARANTOR_REF],
            "entity_type": ["corporate", "corporate"],
            "is_financial_sector_entity": [False, False],
        }
    )

    rating_inheritance = pl.LazyFrame(
        {
            "counterparty_reference": [GUARANTOR_REF],
            "cqs": [2],
            "pd": [PD_GUARANTOR],
            "internal_pd": [PD_GUARANTOR],  # internal rating → IRB approach route
        }
    )

    # CRM: apply guarantees — the bug is here (guarantor_seniority not threaded)
    exposures_with_guarantee = processor.apply_guarantees(
        exposures, guarantees, counterparty_lookup, config, rating_inheritance
    )

    # IRB pipeline: classify → F-IRB LGD → prepare → formulas → EL → guarantee sub
    result = (
        exposures_with_guarantee.irb.classify_approach(config)
        .irb.apply_firb_lgd(config)
        .irb.prepare_columns(config)
        .irb.apply_all_formulas(config)
        .irb.compute_el_shortfall_excess()
        .irb.apply_guarantee_substitution(config)
    )

    return result.collect()


# =============================================================================
# P1.160 acceptance test class
# =============================================================================


class TestP1160Art161PSMLGDSeniorityRouting:
    """
    P1.160: Basel 3.1 PSM F-IRB LGD routing by guarantor_seniority — subordinated case.

    Art. 161(1)(b): a subordinated claim carries supervisory LGD = 75%. Under PSM
    (Art. 236(1)(a)) the guaranteed portion is treated as a direct exposure to the
    guarantor using the guarantor's own PD and F-IRB supervisory LGD. For a subordinated
    guarantee the supervisory LGD must be 75%, not 40% (senior non-FSE Art. 161(1)(aa)).

    The gap: crm/guarantees.py::apply_guarantees does not thread guarantor_seniority
    from the guarantee table to the exposure frame. irb/guarantee.py (lines 329-330)
    detects the absent column and inserts NULL, then fill_null("senior") collapses
    every row to senior LGD=0.40. The fix must propagate guarantor_seniority from
    guarantee data through the CRM layer so the IRB routing logic sees the real value.

    Discriminating assertions (FAIL on buggy engine, PASS on fixed engine):
        - guarantor_rw_irb ≈ 1.16037 (buggy emits ≈ 0.61887 using LGD=0.40)
        - is_guarantee_beneficial = False (buggy emits True — guarantee wrongly applied)
        - rwa ≈ 938,690 retained (buggy emits ≈ 618,870 blended)
    """

    @pytest.fixture(scope="class")
    def config(self) -> CalculationConfig:
        """Basel 3.1 config, F-IRB on corporate."""
        return _b31_config()

    @pytest.fixture(scope="class")
    def p1160_result(self) -> pl.DataFrame:
        """
        Run P1.160 scenario through CRM + IRB pipeline and collect results.

        Arrange: Corporate borrower F-IRB (PD=1.5%, LGD=0.40, EAD=£1m)
                 with a SUBORDINATED corporate guarantee (PD=0.5%, 100% coverage).
        Act:     CRM apply_guarantees → full IRB pipeline → apply_guarantee_substitution.
        Return:  Collected DataFrame for all assertions.
        """
        return _build_p1160_crm_and_irb_result()

    # -------------------------------------------------------------------------
    # PRE-CRM BORROWER VALUES — regression guard
    # -------------------------------------------------------------------------

    def test_p1_160_borrower_rw_original(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160: pre-CRM borrower RW ≈ 0.93869 (corporate non-FSE, PD=1.5%, LGD=40%, M=2.5).

        Arrange: Corporate non-FSE, PD=0.015, LGD=0.40 (B31 Art. 161(1)(aa)), M=2.5, EAD=£1m.
        Act:     apply_guarantee_substitution stores original as risk_weight_irb_original.
        Assert:  risk_weight_irb_original ≈ 0.93869 (rel=1e-2).
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        actual = row["risk_weight_irb_original"]
        assert actual == pytest.approx(EXPECTED_RW_ORIGINAL, rel=1e-2), (
            f"P1.160: risk_weight_irb_original should be {EXPECTED_RW_ORIGINAL:.5f} "
            f"(corporate non-FSE: PD=0.015, LGD=0.40, M=2.5), got {actual:.5f}"
        )

    def test_p1_160_ead_final(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160: ead_final = 1,000,000 (unchanged through guarantee substitution).

        Arrange: EAD_AMOUNT = 1,000,000.
        Assert:  ead_final == 1,000,000 (approx, abs=0.01).
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        assert row["ead_final"] == pytest.approx(EAD_AMOUNT, abs=0.01), (
            f"P1.160: ead_final should be {EAD_AMOUNT:,.0f}, got {row['ead_final']:,.0f}"
        )

    # -------------------------------------------------------------------------
    # PSM INTERMEDIATE — DISCRIMINATING ASSERTIONS (fail on buggy engine)
    # -------------------------------------------------------------------------

    def test_p1_160_guarantor_rw_irb_uses_subordinated_lgd(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160 DISCRIMINATING: guarantor_rw_irb ≈ 1.16037 (subordinated LGD=0.75).

        The PSM LGD for a subordinated guarantee must be 0.75 (Art. 161(1)(b)),
        not 0.40 (Art. 161(1)(aa) senior). With LGD=0.75 and PD=0.005 (M=2.5):
        guarantor_rw_irb ≈ 1.16037 > borrower_rw ≈ 0.93869 → NOT beneficial.

        The buggy engine drops guarantor_seniority in CRM, defaults to "senior",
        and routes to LGD=0.40 → guarantor_rw_irb ≈ 0.61887 < borrower_rw → wrongly applied.

        Arrange: guarantor_seniority="subordinated" in guarantee table (load-bearing input).
        Act:     crm/guarantees.py should thread column; irb/guarantee.py reads and routes.
        Assert:  guarantor_rw_irb ≈ 1.16037 (rel=1e-2).
                 If engine emits ≈ 0.61887: guarantor_seniority not threaded by CRM —
                 irb/guarantee.py falls back to LGD=0.40 via fill_null("senior").
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        actual = row["guarantor_rw_irb"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_IRB_CORRECT, rel=1e-2), (
            f"P1.160: guarantor_rw_irb should be {EXPECTED_GUARANTOR_RW_IRB_CORRECT:.5f} "
            f"(subordinated LGD=0.75, PD=0.005, M=2.5, Art. 161(1)(b)). "
            f"Got {actual:.5f}. "
            f"Buggy value ~{BUGGY_GUARANTOR_RW_IRB:.5f} means guarantor_seniority was NOT "
            f"threaded from the guarantee table through crm/guarantees.py — "
            f"irb/guarantee.py defaulted to 'senior' → LGD=0.40. "
            f"Fix: propagate guarantor_seniority column in apply_guarantees()."
        )

    def test_p1_160_guarantee_not_beneficial_due_to_subordinated_lgd(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160 DISCRIMINATING: guarantee is NOT beneficial (guarantor_rw > borrower_rw).

        Post-fix: guarantor_rw_irb ≈ 1.16037 > borrower_rw ≈ 0.93869
        → is_guarantee_beneficial=False → engine retains borrower RWA.

        Pre-fix (buggy): guarantor_rw_irb ≈ 0.61887 < borrower_rw ≈ 0.93869
        → is_guarantee_beneficial=True → guarantee wrongly applied.

        Arrange: subordinated guarantee, full coverage (100% — makes decision unambiguous).
        Act:     is_guarantee_beneficial = guarantor_rw < risk_weight_irb_original.
        Assert:  is_guarantee_beneficial is False (exact boolean).
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        assert row["is_guarantee_beneficial"] is False, (
            f"P1.160: guarantee should NOT be beneficial — "
            f"subordinated guarantor_rw ({row.get('guarantor_rw', '?'):.5f}) "
            f"must be >= borrower_rw ({row.get('risk_weight_irb_original', '?'):.5f}). "
            f"Got is_guarantee_beneficial={row['is_guarantee_beneficial']}. "
            f"If True: crm/guarantees.py is not threading guarantor_seniority → "
            f"LGD defaults to 0.40 (senior) instead of 0.75 (subordinated, Art. 161(1)(b))."
        )

    def test_p1_160_rwa_retained_at_borrower_level(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160 DISCRIMINATING: RWA retained at borrower level ≈ 938,690.

        Post-fix: guarantee NOT beneficial → borrower RWA retained = 0.93869 × 1,000,000
        ≈ 938,690.

        Pre-fix bug: guarantee wrongly applied → RWA ≈ 618,870 (senior LGD used).
        Delta: +319,820 (+51.7%) — a material capital understatement from the bug.

        Arrange: is_guarantee_beneficial=False (post-fix), EAD=1,000,000.
        Act:     rwa = borrower's original IRB RWA (guarantee not substituted).
        Assert:  rwa ≈ 938,690 (abs=1,000 — spans normal-approx implementation gap).
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        actual = row["rwa"]
        assert actual == pytest.approx(EXPECTED_RWA_POST_FIX, abs=1_000.0), (
            f"P1.160: RWA should be retained at {EXPECTED_RWA_POST_FIX:,.0f} "
            f"(guarantee NOT beneficial: guarantor_rw ≈ 1.16037 > borrower_rw ≈ 0.93869). "
            f"Got {actual:,.0f}. "
            f"If ≈{BUGGY_RWA:,.0f}: guarantee is wrongly applied (LGD=0.40 bug) — "
            f"fix guarantor_seniority propagation in crm/guarantees.py."
        )

    def test_p1_160_risk_weight_retained_at_borrower_level(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160 DISCRIMINATING: risk_weight ≈ 0.93869 (borrower RW retained, no blending).

        Post-fix: guarantee NOT beneficial → risk_weight == borrower_rw ≈ 0.93869.
        Pre-fix bug: blended risk_weight ≈ 0.61887 (substituted by guarantor).

        Arrange: is_guarantee_beneficial=False, no blending occurs.
        Act:     risk_weight = rwa / ead_final = 938,690 / 1,000,000.
        Assert:  risk_weight ≈ 0.93869 (abs=0.01).
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_RISK_WEIGHT_POST_FIX, abs=0.01), (
            f"P1.160: risk_weight should be {EXPECTED_RISK_WEIGHT_POST_FIX:.5f} "
            f"(borrower RW retained — guarantee NOT beneficial). "
            f"Got {actual:.5f}. "
            f"If ≈{BUGGY_GUARANTOR_RW_IRB:.5f}: LGD=0.40 bug (senior fallback) not fixed."
        )

    # -------------------------------------------------------------------------
    # GUARANTEE METHOD — structural correctness
    # -------------------------------------------------------------------------

    def test_p1_160_guarantee_method_is_parameter_substitution(
        self,
        p1160_result: pl.DataFrame,
    ) -> None:
        """
        P1.160: guarantee_method_used = "PD_PARAMETER_SUBSTITUTION" (IRB guarantor, B31).

        The method is always PSM for an IRB corporate guarantor under Basel 3.1,
        regardless of whether the guarantee is beneficial. The non-beneficial gate
        preserves the borrower RWA but the PSM path was still taken.

        Arrange: guarantor_approach="irb" (internal rating present), B31 config.
        Act:     _apply_parameter_substitution selects PSM path.
        Assert:  guarantee_method_used == "PD_PARAMETER_SUBSTITUTION".
        """
        # Arrange
        row = p1160_result.row(0, named=True)

        # Assert
        assert row["guarantee_method_used"] == "PD_PARAMETER_SUBSTITUTION", (
            f"P1.160: guarantee_method_used should be PD_PARAMETER_SUBSTITUTION "
            f"(IRB guarantor under Basel 3.1), got {row['guarantee_method_used']!r}"
        )

    # -------------------------------------------------------------------------
    # REGRESSION GUARD — fixture constant sanity checks
    # -------------------------------------------------------------------------

    def test_p1_160_fixture_both_pds_above_b31_corporate_floor(self) -> None:
        """
        P1.160: both borrower PD (0.015) and guarantor PD (0.005) are above
        the B31 corporate floor 0.0005 (Art. 163(1)(a)).

        This ensures the scenario isolates the guarantor_seniority/LGD routing bug
        rather than a PD floor effect.

        Assert: PD_BORROWER > 0.0005, PD_GUARANTOR > 0.0005.
        """
        B31_CORPORATE_PD_FLOOR = 0.0005
        assert PD_BORROWER > B31_CORPORATE_PD_FLOOR, (
            f"Fixture: borrower PD ({PD_BORROWER}) must be above B31 corporate floor "
            f"({B31_CORPORATE_PD_FLOOR}) so the scenario isolates the seniority routing bug"
        )
        assert PD_GUARANTOR > B31_CORPORATE_PD_FLOOR, (
            f"Fixture: guarantor PD ({PD_GUARANTOR}) must be above B31 corporate floor "
            f"({B31_CORPORATE_PD_FLOOR}) so the scenario isolates the seniority routing bug"
        )

    def test_p1_160_fixture_full_coverage_makes_decision_unambiguous(self) -> None:
        """
        P1.160: guarantee covers 100% of EAD (PERCENTAGE_COVERED=1.0, AMOUNT_COVERED=1,000,000).

        Full coverage makes the is_guarantee_beneficial decision unambiguous:
        either the entire EAD is re-weighted by the guarantor's RW or retained
        at borrower RW. No partial-blending complication.

        Assert: PERCENTAGE_COVERED == 1.0, AMOUNT_COVERED == 1,000,000.
        """
        assert pytest.approx(1.0, abs=1e-10) == PERCENTAGE_COVERED, (
            f"Fixture: PERCENTAGE_COVERED should be 1.0 (100% coverage), got {PERCENTAGE_COVERED}"
        )
        assert pytest.approx(EAD_AMOUNT, abs=0.01) == AMOUNT_COVERED, (
            f"Fixture: AMOUNT_COVERED should equal EAD ({EAD_AMOUNT:,.0f}), "
            f"got {AMOUNT_COVERED:,.0f}"
        )

    def test_p1_160_fixture_subordinated_lgd_higher_than_senior_lgd(self) -> None:
        """
        P1.160: Art. 161(1)(b) subordinated LGD=0.75 > Art. 161(1)(aa) senior LGD=0.40.

        This relationship is the reason the bug matters: with LGD=0.40 (wrong) the
        guarantor RW can be below the borrower RW, making the guarantee appear beneficial.
        With LGD=0.75 (correct) the guarantor RW exceeds the borrower RW at PD=0.005.

        Assert: B31_SUBORDINATED_LGD > B31_SENIOR_NON_FSE_LGD.
        """
        B31_SENIOR_NON_FSE_LGD = 0.40  # Art. 161(1)(aa)
        B31_SUBORDINATED_LGD = 0.75  # Art. 161(1)(b)
        assert B31_SUBORDINATED_LGD > B31_SENIOR_NON_FSE_LGD, (
            f"Art. 161(1)(b) subordinated LGD ({B31_SUBORDINATED_LGD}) must exceed "
            f"Art. 161(1)(aa) senior non-FSE LGD ({B31_SENIOR_NON_FSE_LGD})"
        )

    def test_p1_160_fixture_original_maturity_satisfies_art_237(self) -> None:
        """
        P1.160: original_maturity_years=5.0 >= 1.0 (Art. 237(2)(a) eligibility satisfied).

        Guarantees with original maturity < 1y are ineligible. This guard ensures
        the guarantee is not dropped by the maturity filter in apply_guarantees,
        so the test exercises seniority routing rather than eligibility.

        Assert: ORIGINAL_MATURITY_YEARS >= 1.0.
        """
        assert ORIGINAL_MATURITY_YEARS >= 1.0, (
            f"Fixture: ORIGINAL_MATURITY_YEARS ({ORIGINAL_MATURITY_YEARS}) must be "
            f">= 1.0 (Art. 237(2)(a) eligibility) so the guarantee is not dropped"
        )
