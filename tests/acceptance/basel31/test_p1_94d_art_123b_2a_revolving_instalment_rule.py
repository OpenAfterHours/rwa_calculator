"""
P1.94d — B31 Art. 123B(2A): revolving-instalment rule for the currency-mismatch multiplier.

Acceptance scenario verifying that the Art. 123B(2A) revolving-instalment branch
rescales the hedge coverage test denominator to the fully-drawn committed amount for
revolving facilities, so that a hedge that covers >= 90% of the current drawing but
< 90% of the full facility limit does NOT suppress the Art. 123B 1.5x multiplier.

Pipeline position:
    SACalculator.apply_currency_mismatch_multiplier  (namespace.py)

Parent rule (Art. 123B(2)):
    A partial hedge suppresses the Art. 123B 1.5x multiplier when:
        hedge_coverage_ratio >= 0.90  (coverage of current drawn balance)

Art. 123B(2A) change (revolving facilities only):
    For revolving facilities, the 90%-coverage test denominator is the
    fully-drawn committed amount (facility_limit = drawn + undrawn), not the
    current drawn balance.  The engine must rescale:
        full_draw_base     = max(drawn_amount, facility_limit)
        covered_amount     = hedge_coverage_ratio * drawn_amount
        effective_coverage = covered_amount / full_draw_base
    The waiver holds only when effective_coverage >= 0.90.

Scenario design:
    Three arms share GBP-denominated retail loans against a EUR-income counterparty
    (currency mismatch present). All have is_hedged=False, hedge_coverage_ratio=0.95,
    drawn_amount=100,000.  The base SA retail RW is 75% (retail_other, natural person).

    Arm A — P194D_REVOLVING (in-scope, Art. 123B(2A) behaviour):
        is_revolving=True, drawn=100,000, facility_limit=400,000 (undrawn=300,000)
        full_draw_base     = max(100,000, 400,000) = 400,000
        covered_amount     = 0.95 * 100,000 = 95,000
        effective_coverage = 95,000 / 400,000 = 0.2375  (<0.90 — waiver does NOT hold)
        mismatch_applies   = True
        RW_adjusted        = min(0.75 * 1.5, 1.50) = 1.125
        RWA                = 100,000 * 1.125 = 112,500
        currency_mismatch_multiplier_applied = True

        LOAD-BEARING: current engine applies Art. 123B(2) waiver directly on
        hedge_coverage_ratio (0.95 >= 0.90) without the revolving rescale.
        Pre-fix engine: risk_weight=0.75, rwa=75,000, multiplier_applied=False.

    Arm B — P194D_NON_REVOLVING (control — parent rule holds):
        is_revolving=False, drawn=100,000, facility_limit=400,000
        effective_coverage = hedge_coverage_ratio = 0.95 (no rescale for non-revolving)
        waiver             = True  (0.95 >= 0.90)
        RW                 = 0.75 ; RWA = 75,000
        currency_mismatch_multiplier_applied = False
        Confirms the (d) branch is gated on is_revolving and does NOT regress Art. 123B(2).

    Arm C — P194D_FULLY_DRAWN (revolving negative control):
        is_revolving=True, drawn=100,000, facility_limit=100,000 (fully drawn, undrawn=0)
        full_draw_base     = max(100,000, 100,000) = 100,000
        covered_amount     = 0.95 * 100,000 = 95,000
        effective_coverage = 95,000 / 100,000 = 0.95 (>= 0.90 — waiver holds)
        RW                 = 0.75 ; RWA = 75,000
        currency_mismatch_multiplier_applied = False
        Confirms the rule bites only when there is undrawn headroom.

Pre-fix failure mode:
    Arm A test (test_p1_94d_arm_a_revolving_risk_weight_equals_multiplied_rw) FAILS:
        assert 0.75 == pytest.approx(1.125)  (current engine applies 0.95>=0.90 waiver directly)
    Arms B and C: pass (waiver holds under both old and new logic).

References:
    - PRA PS1/26 App1 Art. 123B: 1.5x currency-mismatch multiplier (retail, non-mortgage).
    - PRA PS1/26 App1 Art. 123B(2): >= 90% hedge coverage suppresses the multiplier.
    - PRA PS1/26 App1 Art. 123B(2A): for revolving facilities, coverage is measured against
      the fully-drawn committed amount (max(drawn, facility_limit)).
    - BCBS CRE20.88: revolving-instalment base equivalent.
    - tests/fixtures/p1_94d/p1_94d.py: scenario constants (RW_REVOLVING, RWA_REVOLVING, etc.)
    - tests/acceptance/basel31/test_p1_94a_is_hedged_gates_currency_mismatch.py: sibling.
    - tests/acceptance/basel31/test_p1_94b_hedge_coverage_ratio_gates_currency_mismatch.py:
      sibling — hedge_coverage_ratio gate (parent rule).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from tests.fixtures.p1_94d.p1_94d import (
    CURRENCY_MISMATCH_MULTIPLIER,
    DRAWN_AMOUNT,
    EFFECTIVE_COVERAGE_A,
    FACILITY_LIMIT_FULLY_DRAWN,
    FACILITY_LIMIT_PARTIAL,
    FULL_DRAW_BASE_A,
    HEDGE_COVERAGE_RATIO,
    HEDGE_COVERAGE_THRESHOLD,
    LOAN_REF_FULLY_DRAWN,
    LOAN_REF_NON_REVOLVING,
    LOAN_REF_REVOLVING,
    RW_FULLY_DRAWN,
    RW_NON_REVOLVING,
    RW_REVOLVING,
    RWA_FULLY_DRAWN,
    RWA_NON_REVOLVING,
    RWA_REVOLVING,
    SA_RETAIL_QRRE_BASE_RW,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_EAD = Decimal("100_000")
_REPORTING_DATE = date(2027, 1, 4)

# Absolute tolerances
_RW_TOL = 1e-6  # risk_weight (dimensionless ratio)
_RWA_TOL = 0.50  # 50p on rwa

# Pre-fix (current engine) values for Arm A.
# The engine applies Art. 123B(2) waiver on hedge_coverage_ratio (0.95 >= 0.90)
# directly, without the revolving rescale to fully-drawn base — so waiver holds.
_PRE_FIX_RW_A = SA_RETAIL_QRRE_BASE_RW  # 0.75 (waiver fires incorrectly pre-fix)
_PRE_FIX_RWA_A = DRAWN_AMOUNT * _PRE_FIX_RW_A  # 75,000.0


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sa_calculator() -> SACalculator:
    """Return a fresh SACalculator instance (SA-only, no IRB)."""
    return SACalculator()


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 config with 2027 reporting date (post-effective date)."""
    return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)


def _build_arm_frame(
    *,
    exposure_reference: str,
    is_revolving: bool,
    facility_limit: float,
    drawn_amount: float,
) -> pl.LazyFrame:
    """
    Build a single-row LazyFrame for one P1.94d scenario arm.

    The frame includes all columns required by SACalculator.calculate_branch plus
    the three Art. 123B(2A) fields:
        - hedge_coverage_ratio  (pl.Float64, proportion of current drawn balance hedged)
        - is_revolving          (pl.Boolean, FACILITY_SCHEMA field forwarded to loan rows)
        - facility_limit        (pl.Float64, committed limit = drawn + undrawn)

    The currency mismatch (GBP loan vs EUR borrower income) is present for all arms.
    is_hedged=False keeps the is_hedged gate open (multiplier not suppressed by flag).
    drawn_amount is also passed so the revolving branch can compute covered_amount.

    Args:
        exposure_reference: Row label (e.g. LOAN_REF_REVOLVING).
        is_revolving:       True for Arms A and C, False for Arm B.
        facility_limit:     400,000 for Arms A and B; 100,000 for Arm C.
        drawn_amount:       100,000 for all arms.

    Returns:
        Single-row LazyFrame ready for SACalculator.calculate_branch.
    """
    data: dict = {
        "exposure_reference": [exposure_reference],
        "ead_final": [drawn_amount],
        "exposure_class": ["retail_other"],
        "cqs": [None],
        "ltv": [None],
        "is_sme": [False],
        "is_infrastructure": [False],
        "has_income_cover": [False],
        "cp_is_managed_as_retail": [True],
        "qualifies_as_retail": [True],
        "property_type": [None],
        "is_adc": [False],
        "is_presold": [False],
        "seniority": ["senior"],
        "cp_scra_grade": [None],
        "cp_is_investment_grade": [False],
        "is_defaulted": [False],
        "provision_allocated": [0.0],
        "provision_deducted": [0.0],
        "currency": ["GBP"],
        "cp_country_code": [None],
        "borrower_income_currency": ["EUR"],
        "residual_maturity_years": [None],
        "original_maturity_years": [None],
        "cp_entity_type": [None],
        "is_short_term_trade_lc": [False],
        "cp_is_natural_person": [True],
        "cp_is_social_housing": [False],
        "is_payroll_loan": [False],
        "cp_sovereign_cqs": [None],
        "cp_local_currency": [None],
        "cp_institution_cqs": [None],
        "is_hedged": [False],
        # Art. 123B(2) / (2A) fields
        "hedge_coverage_ratio": [HEDGE_COVERAGE_RATIO],
        "is_revolving": [is_revolving],
        "facility_limit": [facility_limit],
        "drawn_amount": [drawn_amount],
    }
    return pl.DataFrame(data).lazy()


# ===========================================================================
# Arm A — P194D_REVOLVING (in-scope): Art. 123B(2A) must fire the multiplier
# ===========================================================================


class TestP194DArmARevolvingMultiplierFires:
    """
    Arm A: retail_other GBP exposure, revolving (partially drawn), EUR income.

    Art. 123B(2A) requires the coverage test denominator to be the fully-drawn
    committed amount (facility_limit=400,000), not the current drawing (100,000).

        effective_coverage = (0.95 * 100,000) / 400,000 = 0.2375  (<0.90)

    The waiver does NOT hold, so the 1.5x multiplier fires:
        risk_weight = 0.75 * 1.5 = 1.125
        rwa         = 100,000 * 1.125 = 112,500

    LOAD-BEARING: the current engine does NOT implement the Art. 123B(2A) revolving
    rescale.  It applies the waiver on the firm-supplied hedge_coverage_ratio directly
    (0.95 >= 0.90 → waiver fires → risk_weight = 0.75).  This class provides the
    failing tests that drive the engine-implementer (Wave 4).

    Pre-fix failure (AssertionError on risk_weight / rwa):
        assert 0.75 == pytest.approx(1.125)
        assert 75,000 == pytest.approx(112,500)
    """

    @pytest.fixture(scope="class")
    def arm_a_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """
        Run Arm A (revolving, partially drawn) through the SA calculator.

        Arrange: retail_other, GBP currency, EUR income, is_hedged=False,
                 hedge_coverage_ratio=0.95, is_revolving=True,
                 drawn=100,000, facility_limit=400,000. B31 framework.
        Act:     SACalculator.calculate_branch → apply_currency_mismatch_multiplier.
        Return:  Single result dict with risk_weight, rwa_post_factor, and
                 currency_mismatch_multiplier_applied.
        """
        lf = _build_arm_frame(
            exposure_reference=LOAN_REF_REVOLVING,
            is_revolving=True,
            facility_limit=FACILITY_LIMIT_PARTIAL,
            drawn_amount=DRAWN_AMOUNT,
        )
        result = sa_calculator.calculate_branch(lf, b31_config).collect().to_dicts()[0]
        result["rwa"] = result["rwa_post_factor"]
        return result

    def test_p1_94d_arm_a_revolving_risk_weight_equals_multiplied_rw(
        self, arm_a_result: dict
    ) -> None:
        """
        Arm A (revolving, partially drawn): risk_weight = 1.125.

        Art. 123B(2A) rescales coverage to fully-drawn base:
            effective_coverage = (0.95 * 100k) / 400k = 0.2375 < 0.90
        Waiver does NOT hold → multiplier fires: 0.75 * 1.5 = 1.125.

        Arrange: is_revolving=True, drawn=100,000, facility_limit=400,000,
                 hedge_coverage_ratio=0.95, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier (revolving branch).
        Assert:  risk_weight ≈ 1.125.

        Pre-fix failure:
            Current engine applies the waiver on hedge_coverage_ratio directly
            (0.95 >= 0.90) → risk_weight = 0.75.
            assert 0.75 == pytest.approx(1.125) → FAILS.
        """
        rw = float(arm_a_result["risk_weight"])
        assert rw == pytest.approx(RW_REVOLVING, abs=_RW_TOL), (
            f"P1.94d Arm A (P194D_REVOLVING): risk_weight {rw:.6f} != "
            f"expected {RW_REVOLVING:.6f} "
            f"(= {SA_RETAIL_QRRE_BASE_RW:.2f} × {CURRENCY_MISMATCH_MULTIPLIER:.2f}). "
            f"Art. 123B(2A) revolving branch not yet implemented — "
            f"current engine applies hedge_coverage_ratio ({HEDGE_COVERAGE_RATIO:.2f}) "
            f"directly against the {HEDGE_COVERAGE_THRESHOLD:.2f} threshold "
            f"(waiver fires; pre-fix value = {_PRE_FIX_RW_A:.4f}). "
            f"Expected: coverage rescaled to full draw base "
            f"(effective_coverage = {EFFECTIVE_COVERAGE_A:.4f} < {HEDGE_COVERAGE_THRESHOLD:.2f} "
            f"→ waiver fails → multiplier fires). "
            f"full_draw_base = max(100k, 400k) = {FULL_DRAW_BASE_A:,.0f}."
        )

    def test_p1_94d_arm_a_revolving_rwa_equals_multiplied_rwa(self, arm_a_result: dict) -> None:
        """
        Arm A (revolving, partially drawn): rwa = 100,000 * 1.125 = 112,500.

        Arrange/Act: as above.
        Assert:  rwa ≈ 112,500.00 (abs=0.50).

        Pre-fix failure:
            Current engine: rwa = 75,000 (waiver fires, no multiplier).
            assert 75,000 == pytest.approx(112,500) → FAILS.
        """
        rwa = float(arm_a_result["rwa"])
        assert rwa == pytest.approx(RWA_REVOLVING, abs=_RWA_TOL), (
            f"P1.94d Arm A (P194D_REVOLVING): rwa {rwa:,.2f} != "
            f"expected {RWA_REVOLVING:,.2f}. "
            f"EAD = {DRAWN_AMOUNT:,.0f} × risk_weight {RW_REVOLVING:.4f}. "
            f"Pre-fix value: {_PRE_FIX_RWA_A:,.2f} "
            f"(waiver fires → multiplier suppressed)."
        )

    def test_p1_94d_arm_a_revolving_currency_mismatch_multiplier_applied(
        self, arm_a_result: dict
    ) -> None:
        """
        Arm A (revolving): currency_mismatch_multiplier_applied = True.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == True.

        Pre-fix failure:
            Current engine: currency_mismatch_multiplier_applied = False
            (waiver fires on raw hedge_coverage_ratio 0.95 >= 0.90).
        """
        applied = arm_a_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result. "
            "The engine must emit this column "
            "(see namespace.py apply_currency_mismatch_multiplier)."
        )
        assert applied is True or applied == True, (  # noqa: E712
            f"P1.94d Arm A (P194D_REVOLVING): "
            f"currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected True — Art. 123B(2A) revolving branch should override the "
            f"Art. 123B(2) waiver when effective_coverage ({EFFECTIVE_COVERAGE_A:.4f}) "
            f"< threshold ({HEDGE_COVERAGE_THRESHOLD:.2f}). "
            f"Pre-fix: engine sets False (uses raw hedge_coverage_ratio without rescale)."
        )


# ===========================================================================
# Arm B — P194D_NON_REVOLVING (control): parent Art. 123B(2) waiver holds
# ===========================================================================


class TestP194DArmBNonRevolvingWaiverHolds:
    """
    Arm B: retail_other GBP exposure, non-revolving (term loan), EUR income.

    is_revolving=False → Art. 123B(2A) revolving branch does NOT apply.
    Art. 123B(2) parent rule: effective_coverage = hedge_coverage_ratio = 0.95 >= 0.90.
    Waiver holds → multiplier suppressed.

    Expected: risk_weight = 0.75, rwa = 75,000, multiplier_applied = False.

    This arm passes under both the current (pre-fix) and new (post-fix) engine.
    It is a regression guard to confirm the (d) branch is correctly gated on
    is_revolving — non-revolving exposures must not be affected.
    """

    @pytest.fixture(scope="class")
    def arm_b_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """
        Run Arm B (non-revolving control) through the SA calculator.

        Arrange: retail_other, GBP currency, EUR income, is_hedged=False,
                 hedge_coverage_ratio=0.95, is_revolving=False,
                 drawn=100,000, facility_limit=400,000. B31 framework.
        Act:     SACalculator.calculate_branch → apply_currency_mismatch_multiplier.
        Return:  Single result dict.
        """
        lf = _build_arm_frame(
            exposure_reference=LOAN_REF_NON_REVOLVING,
            is_revolving=False,
            facility_limit=FACILITY_LIMIT_PARTIAL,
            drawn_amount=DRAWN_AMOUNT,
        )
        result = sa_calculator.calculate_branch(lf, b31_config).collect().to_dicts()[0]
        result["rwa"] = result["rwa_post_factor"]
        return result

    def test_p1_94d_arm_b_non_revolving_risk_weight_equals_base_rw(
        self, arm_b_result: dict
    ) -> None:
        """
        Arm B (non-revolving): risk_weight = 0.75 (no multiplier, waiver holds).

        Art. 123B(2): hedge_coverage_ratio=0.95 >= 0.90 threshold → waiver holds.
        is_revolving=False → Art. 123B(2A) rescale does NOT apply.

        Arrange: is_revolving=False, drawn=100,000, facility_limit=400,000,
                 hedge_coverage_ratio=0.95, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier (no revolving branch).
        Assert:  risk_weight ≈ 0.75 (base retail RW; multiplier suppressed by waiver).

        Regression guard: after the engine-implementer adds the revolving branch,
        is_revolving=False rows must still use the parent Art. 123B(2) waiver.
        """
        rw = float(arm_b_result["risk_weight"])
        assert rw == pytest.approx(RW_NON_REVOLVING, abs=_RW_TOL), (
            f"P1.94d Arm B (P194D_NON_REVOLVING): risk_weight {rw:.6f} != "
            f"expected {RW_NON_REVOLVING:.6f}. "
            f"is_revolving=False → Art. 123B(2A) does not apply. "
            f"Art. 123B(2) waiver holds (hedge_coverage_ratio {HEDGE_COVERAGE_RATIO:.2f} "
            f">= threshold {HEDGE_COVERAGE_THRESHOLD:.2f}) → multiplier suppressed. "
            f"Post-fix regression: the revolving branch must be gated on is_revolving."
        )

    def test_p1_94d_arm_b_non_revolving_rwa_equals_base_rwa(self, arm_b_result: dict) -> None:
        """
        Arm B (non-revolving): rwa = 100,000 * 0.75 = 75,000.

        Arrange/Act: as above.
        Assert:  rwa ≈ 75,000.00 (abs=0.50).
        """
        rwa = float(arm_b_result["rwa"])
        assert rwa == pytest.approx(RWA_NON_REVOLVING, abs=_RWA_TOL), (
            f"P1.94d Arm B (P194D_NON_REVOLVING): rwa {rwa:,.2f} != "
            f"expected {RWA_NON_REVOLVING:,.2f}. "
            f"EAD = {DRAWN_AMOUNT:,.0f} × risk_weight {RW_NON_REVOLVING:.4f}."
        )

    def test_p1_94d_arm_b_non_revolving_multiplier_not_applied(self, arm_b_result: dict) -> None:
        """
        Arm B (non-revolving): currency_mismatch_multiplier_applied = False.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == False.
        """
        applied = arm_b_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result."
        )
        assert applied is False or applied == False, (  # noqa: E712
            f"P1.94d Arm B (P194D_NON_REVOLVING): "
            f"currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected False — is_revolving=False, hedge_coverage_ratio "
            f"({HEDGE_COVERAGE_RATIO:.2f}) >= threshold ({HEDGE_COVERAGE_THRESHOLD:.2f}), "
            f"Art. 123B(2) waiver suppresses the multiplier."
        )


# ===========================================================================
# Arm C — P194D_FULLY_DRAWN (revolving negative control): waiver holds
# ===========================================================================


class TestP194DArmCFullyDrawnRevolvingWaiverHolds:
    """
    Arm C: retail_other GBP exposure, revolving BUT fully drawn, EUR income.

    is_revolving=True, drawn=100,000, facility_limit=100,000 (no undrawn headroom).
    Art. 123B(2A):
        full_draw_base     = max(100,000, 100,000) = 100,000
        covered_amount     = 0.95 * 100,000 = 95,000
        effective_coverage = 95,000 / 100,000 = 0.95 >= 0.90
    Waiver holds → multiplier suppressed.

    Expected: risk_weight = 0.75, rwa = 75,000, multiplier_applied = False.

    This arm passes under both the current engine (0.95 >= 0.90 → waiver)
    and the new engine (rescaled coverage still >= 0.90 because no undrawn headroom).
    It confirms the (d) rule only bites when the facility has undrawn headroom.
    """

    @pytest.fixture(scope="class")
    def arm_c_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """
        Run Arm C (revolving, fully drawn) through the SA calculator.

        Arrange: retail_other, GBP currency, EUR income, is_hedged=False,
                 hedge_coverage_ratio=0.95, is_revolving=True,
                 drawn=100,000, facility_limit=100,000. B31 framework.
        Act:     SACalculator.calculate_branch → apply_currency_mismatch_multiplier.
        Return:  Single result dict.
        """
        lf = _build_arm_frame(
            exposure_reference=LOAN_REF_FULLY_DRAWN,
            is_revolving=True,
            facility_limit=FACILITY_LIMIT_FULLY_DRAWN,
            drawn_amount=DRAWN_AMOUNT,
        )
        result = sa_calculator.calculate_branch(lf, b31_config).collect().to_dicts()[0]
        result["rwa"] = result["rwa_post_factor"]
        return result

    def test_p1_94d_arm_c_fully_drawn_revolving_risk_weight_equals_base_rw(
        self, arm_c_result: dict
    ) -> None:
        """
        Arm C (revolving, fully drawn): risk_weight = 0.75 (waiver holds).

        Art. 123B(2A): when drawn == facility_limit, full_draw_base = drawn.
        effective_coverage = (0.95 * 100k) / 100k = 0.95 >= 0.90 → waiver holds.

        Arrange: is_revolving=True, drawn=100,000, facility_limit=100,000,
                 hedge_coverage_ratio=0.95, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier (revolving branch).
        Assert:  risk_weight ≈ 0.75 (waiver holds even after rescale).

        Regression guard: the revolving branch must not fire the multiplier when
        facility_limit == drawn_amount (no undrawn headroom).
        """
        rw = float(arm_c_result["risk_weight"])
        assert rw == pytest.approx(RW_FULLY_DRAWN, abs=_RW_TOL), (
            f"P1.94d Arm C (P194D_FULLY_DRAWN): risk_weight {rw:.6f} != "
            f"expected {RW_FULLY_DRAWN:.6f}. "
            f"is_revolving=True but facility_limit == drawn_amount (fully drawn). "
            f"Art. 123B(2A): effective_coverage = 0.95 >= {HEDGE_COVERAGE_THRESHOLD:.2f} "
            f"→ waiver holds → multiplier suppressed. "
            f"Post-fix regression: the revolving branch must pass when "
            f"max(drawn, limit) == drawn."
        )

    def test_p1_94d_arm_c_fully_drawn_revolving_rwa_equals_base_rwa(
        self, arm_c_result: dict
    ) -> None:
        """
        Arm C (revolving, fully drawn): rwa = 100,000 * 0.75 = 75,000.

        Arrange/Act: as above.
        Assert:  rwa ≈ 75,000.00 (abs=0.50).
        """
        rwa = float(arm_c_result["rwa"])
        assert rwa == pytest.approx(RWA_FULLY_DRAWN, abs=_RWA_TOL), (
            f"P1.94d Arm C (P194D_FULLY_DRAWN): rwa {rwa:,.2f} != "
            f"expected {RWA_FULLY_DRAWN:,.2f}. "
            f"EAD = {DRAWN_AMOUNT:,.0f} × risk_weight {RW_FULLY_DRAWN:.4f}."
        )

    def test_p1_94d_arm_c_fully_drawn_revolving_multiplier_not_applied(
        self, arm_c_result: dict
    ) -> None:
        """
        Arm C (revolving, fully drawn): currency_mismatch_multiplier_applied = False.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == False.
        """
        applied = arm_c_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result."
        )
        assert applied is False or applied == False, (  # noqa: E712
            f"P1.94d Arm C (P194D_FULLY_DRAWN): "
            f"currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected False — revolving but fully drawn, "
            f"effective_coverage ({HEDGE_COVERAGE_RATIO:.2f}) >= "
            f"threshold ({HEDGE_COVERAGE_THRESHOLD:.2f})."
        )


# ===========================================================================
# Cross-arm invariant: the (d) branch bites only when revolving AND partially drawn
# ===========================================================================


class TestP194DCrossArmRevolvingInstalment:
    """
    Cross-arm invariant: Art. 123B(2A) fires the multiplier ONLY for the combination
    of is_revolving=True AND effective_coverage (after rescaling) < 0.90.

    This guard catches two regression classes after Wave 4:
    1. Over-broad: the revolving branch fires for non-revolving (Arm B) or fully-drawn
       revolving (Arm C) rows.
    2. Under-narrow: the revolving branch still does not fire for Arm A (still waives
       based on raw hedge_coverage_ratio).

    Arms B and C: multiplier_applied == False.
    Arm A: multiplier_applied == True.

    Pre-fix state: all three arms have multiplier_applied == False.
    Expected post-fix: only Arm A has multiplier_applied == True.
    """

    @pytest.fixture(scope="class")
    def all_arm_results(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> tuple[dict, dict, dict]:
        """Run all three arms and return (arm_a, arm_b, arm_c) result dicts."""

        def _run(
            exposure_reference: str,
            is_revolving: bool,
            facility_limit: float,
        ) -> dict:
            lf = _build_arm_frame(
                exposure_reference=exposure_reference,
                is_revolving=is_revolving,
                facility_limit=facility_limit,
                drawn_amount=DRAWN_AMOUNT,
            )
            result = sa_calculator.calculate_branch(lf, b31_config).collect().to_dicts()[0]
            result["rwa"] = result["rwa_post_factor"]
            return result

        arm_a = _run(LOAN_REF_REVOLVING, True, FACILITY_LIMIT_PARTIAL)
        arm_b = _run(LOAN_REF_NON_REVOLVING, False, FACILITY_LIMIT_PARTIAL)
        arm_c = _run(LOAN_REF_FULLY_DRAWN, True, FACILITY_LIMIT_FULLY_DRAWN)
        return arm_a, arm_b, arm_c

    def test_p1_94d_only_revolving_partially_drawn_arm_fires_multiplier(
        self, all_arm_results: tuple[dict, dict, dict]
    ) -> None:
        """
        Exactly one arm has currency_mismatch_multiplier_applied = True (Arm A only).

        Pre-fix: all three arms have multiplier_applied=False (no revolving branch).
        Post-fix: only Arm A fires (revolving + effective_coverage < 0.90).

        Arrange: three arms — revolving-partial, non-revolving, revolving-fully-drawn.
        All share GBP currency, EUR income, is_hedged=False, hedge_coverage_ratio=0.95.
        Act:     SA calculator for each arm.
        Assert:  exactly 1 arm has multiplier_applied=True (Arm A).

        This test fails pre-fix because Arm A has multiplier_applied=False
        (engine applies raw hedge_coverage_ratio → waiver fires).
        """
        arm_a, arm_b, arm_c = all_arm_results
        multiplier_flags = {
            LOAN_REF_REVOLVING: arm_a.get("currency_mismatch_multiplier_applied"),
            LOAN_REF_NON_REVOLVING: arm_b.get("currency_mismatch_multiplier_applied"),
            LOAN_REF_FULLY_DRAWN: arm_c.get("currency_mismatch_multiplier_applied"),
        }
        arms_with_multiplier = [k for k, v in multiplier_flags.items() if v]
        assert arms_with_multiplier == [LOAN_REF_REVOLVING], (
            f"P1.94d: exactly 1 arm should have currency_mismatch_multiplier_applied=True "
            f"({LOAN_REF_REVOLVING} only). Got: {arms_with_multiplier}. "
            f"All flags: {multiplier_flags}. "
            f"Pre-fix: all three arms have False (no Art. 123B(2A) revolving branch). "
            f"Post-fix: only {LOAN_REF_REVOLVING} should fire "
            f"(is_revolving=True AND effective_coverage={EFFECTIVE_COVERAGE_A:.4f} "
            f"< {HEDGE_COVERAGE_THRESHOLD:.2f})."
        )

    def test_p1_94d_arm_a_rw_delta_vs_arms_b_and_c(
        self, all_arm_results: tuple[dict, dict, dict]
    ) -> None:
        """
        Arm A RW must exceed Arm B and Arm C by the Art. 123B premium.

        delta = SA_RETAIL_QRRE_BASE_RW * (CURRENCY_MISMATCH_MULTIPLIER - 1.0) = 0.375

        Pre-fix: delta = 0.0 (all arms at 0.75; revolving branch absent).
        Post-fix: delta = 0.375 (only Arm A carries the Art. 123B premium).

        Arrange: all three arms.
        Act:     compare risk_weight(Arm A) - risk_weight(Arm B) and (A) - (C).
        Assert:  both deltas ≈ 0.375.
        """
        arm_a, arm_b, arm_c = all_arm_results
        rw_a = float(arm_a["risk_weight"])
        rw_b = float(arm_b["risk_weight"])
        rw_c = float(arm_c["risk_weight"])
        expected_delta = SA_RETAIL_QRRE_BASE_RW * (CURRENCY_MISMATCH_MULTIPLIER - 1.0)  # 0.375

        delta_ab = rw_a - rw_b
        delta_ac = rw_a - rw_c
        assert delta_ab == pytest.approx(expected_delta, abs=_RW_TOL), (
            f"P1.94d: RW(ArmA) - RW(ArmB) = {delta_ab:.6f}, expected {expected_delta:.6f}. "
            f"RW_A = {rw_a:.4f}, RW_B = {rw_b:.4f}. "
            f"Pre-fix: delta = 0.0 (revolving branch absent — all arms at 0.75)."
        )
        assert delta_ac == pytest.approx(expected_delta, abs=_RW_TOL), (
            f"P1.94d: RW(ArmA) - RW(ArmC) = {delta_ac:.6f}, expected {expected_delta:.6f}. "
            f"RW_A = {rw_a:.4f}, RW_C = {rw_c:.4f}. "
            f"Pre-fix: delta = 0.0 (revolving branch absent — all arms at 0.75)."
        )
