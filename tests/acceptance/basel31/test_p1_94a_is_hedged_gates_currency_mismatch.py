"""
P1.94a — B31 Art. 123B(2): is_hedged flag gates currency-mismatch multiplier.

Acceptance scenario verifying that the 1.5x Art. 123B currency-mismatch
multiplier is suppressed when is_hedged=True, and fires when is_hedged=False.

Pipeline position:
    SACalculator.apply_currency_mismatch_multiplier  (namespace.py)

Scenario design:
    Both arms are identical SA retail exposures (natural person, retail_other,
    EAD = EUR 100,000) against a GBP-income counterparty in GB.  The only
    difference is the is_hedged flag.

    Arm A — P194A_HEDGED (is_hedged=True):
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        is_hedged=True  → Art. 123B multiplier suppressed
        Expected: risk_weight ≈ 0.75, rwa ≈ 75,000, multiplier_applied = False

    Arm B — P194A_UNHEDGED (is_hedged=False):
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        is_hedged=False + currency mismatch (EUR vs GBP income)
            → Art. 123B multiplier fires: 1.5 × 75% = 112.5%
        Expected: risk_weight ≈ 1.125, rwa ≈ 112,500, multiplier_applied = True

Cross-arm invariant:
    RW delta (unhedged − hedged) = 0.375  (= 75% × 0.5)

Pre-fix failure mode (Wave 3 — engine has no is_hedged gate):
    Both arms produce risk_weight = 1.125, currency_mismatch_multiplier_applied = True.
    The hedged-arm tests fail on the assertion that risk_weight ≈ 0.75.

References:
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - PRA PS1/26 Art. 123B: 1.5x currency-mismatch multiplier for retail exposures
      where loan currency != borrower income currency AND is_hedged = False.
    - BCBS CRE20.89-90: currency mismatch add-on for unhedged FX retail.
    - tests/fixtures/p1_94a/p1_94a.py: scenario constants (RW_HEDGED, RW_UNHEDGED, etc.)
    - tests/fixtures/single_exposure.py: calculate_single_sa_exposure (is_hedged param).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.p1_94a.p1_94a import (
    CURRENCY_MISMATCH_MULTIPLIER,
    RW_HEDGED,
    RW_UNHEDGED,
    RWA_HEDGED,
    RWA_UNHEDGED,
    SA_RETAIL_BASE_RW,
)
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_EAD = Decimal("100_000")
_REPORTING_DATE = date(2027, 1, 4)

# Absolute tolerances
_RW_TOL = 1e-6      # risk_weight (dimensionless ratio)
_RWA_TOL = 0.50     # £0.50 on rwa


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


# ---------------------------------------------------------------------------
# Arm A — P194A_HEDGED (is_hedged=True): multiplier must be suppressed
# ---------------------------------------------------------------------------


class TestP194AHedgedArmMultiplierSuppressed:
    """
    Arm A: retail_other EUR exposure, is_hedged=True, income currency GBP.

    Art. 123B requires the 1.5x multiplier to be suppressed when is_hedged=True.
    The pre-fix engine ignores the is_hedged flag and applies the multiplier to
    both arms, so this class fails before Wave 4.

    Expected post-fix: risk_weight = 0.75, rwa = 75,000,
                       currency_mismatch_multiplier_applied = False.
    """

    @pytest.fixture(scope="class")
    def hedged_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """Run the SA calculator for the hedged arm (is_hedged=True)."""
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=True,
            config=b31_config,
        )

    def test_p1_94a_hedged_risk_weight_equals_base_retail_rw(
        self, hedged_result: dict
    ) -> None:
        """
        Hedged arm: risk_weight must equal base retail SA RW (no multiplier applied).

        Arrange: retail_other, EUR currency, GBP income, is_hedged=True, B31 framework.
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  risk_weight ≈ 0.75 (Art. 123(1) base; multiplier suppressed by is_hedged).

        Pre-fix failure: engine returns risk_weight = 1.125 (multiplier fires for all).
        """
        rw = float(hedged_result["risk_weight"])
        assert rw == pytest.approx(RW_HEDGED, abs=_RW_TOL), (
            f"Hedged arm (is_hedged=True): risk_weight {rw:.4f} != expected {RW_HEDGED:.4f}. "
            f"The is_hedged gate is not yet implemented — engine fires the 1.5x "
            f"Art. 123B multiplier unconditionally (pre-fix value ≈ {RW_UNHEDGED:.4f})."
        )

    def test_p1_94a_hedged_rwa_equals_base_rwa(self, hedged_result: dict) -> None:
        """
        Hedged arm: rwa must equal EAD × base retail RW = 75,000.

        Arrange/Act: as above.
        Assert:  rwa ≈ 75,000.00  (100,000 × 0.75; no mismatch premium).

        Pre-fix failure: engine returns rwa ≈ 112,500.
        """
        rwa = float(hedged_result["rwa"])
        assert rwa == pytest.approx(RWA_HEDGED, abs=_RWA_TOL), (
            f"Hedged arm (is_hedged=True): rwa {rwa:,.2f} != expected {RWA_HEDGED:,.2f}. "
            f"Pre-fix (no is_hedged gate) produces rwa = {RWA_UNHEDGED:,.2f}."
        )

    def test_p1_94a_hedged_currency_mismatch_multiplier_not_applied(
        self, hedged_result: dict
    ) -> None:
        """
        Hedged arm: currency_mismatch_multiplier_applied must be False.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == False.

        Pre-fix failure: engine sets the flag to True for all mismatch exposures.
        """
        applied = hedged_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result. "
            "The engine must emit this column (see namespace.py apply_currency_mismatch_multiplier)."
        )
        assert applied is False or applied == False, (  # noqa: E712
            f"Hedged arm (is_hedged=True): currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected False — is_hedged=True must suppress the Art. 123B multiplier."
        )


# ---------------------------------------------------------------------------
# Arm B — P194A_UNHEDGED (is_hedged=False): multiplier must fire
# ---------------------------------------------------------------------------


class TestP194AUnhedgedArmMultiplierFires:
    """
    Arm B: retail_other EUR exposure, is_hedged=False, income currency GBP.

    Art. 123B applies the 1.5x multiplier when is_hedged=False and there is a
    currency mismatch.  This arm already passes pre-fix (multiplier fires for
    all mismatch exposures); it serves as a regression pin after Wave 4.

    Expected: risk_weight = 1.125, rwa = 112,500,
              currency_mismatch_multiplier_applied = True.
    """

    @pytest.fixture(scope="class")
    def unhedged_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """Run the SA calculator for the unhedged arm (is_hedged=False)."""
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=b31_config,
        )

    def test_p1_94a_unhedged_risk_weight_equals_multiplied_rw(
        self, unhedged_result: dict
    ) -> None:
        """
        Unhedged arm: risk_weight = 75% × 1.5 = 112.5%.

        Arrange: retail_other, EUR currency, GBP income, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  risk_weight ≈ 1.125  (Art. 123(1) base × Art. 123B multiplier).
        """
        rw = float(unhedged_result["risk_weight"])
        assert rw == pytest.approx(RW_UNHEDGED, abs=_RW_TOL), (
            f"Unhedged arm (is_hedged=False): risk_weight {rw:.4f} != expected {RW_UNHEDGED:.4f}. "
            f"Art. 123B 1.5x multiplier must fire when is_hedged=False and currency mismatch."
        )

    def test_p1_94a_unhedged_rwa_equals_multiplied_rwa(
        self, unhedged_result: dict
    ) -> None:
        """
        Unhedged arm: rwa = 100,000 × 1.125 = 112,500.

        Arrange/Act: as above.
        Assert:  rwa ≈ 112,500.00.
        """
        rwa = float(unhedged_result["rwa"])
        assert rwa == pytest.approx(RWA_UNHEDGED, abs=_RWA_TOL), (
            f"Unhedged arm (is_hedged=False): rwa {rwa:,.2f} != expected {RWA_UNHEDGED:,.2f}."
        )

    def test_p1_94a_unhedged_currency_mismatch_multiplier_applied(
        self, unhedged_result: dict
    ) -> None:
        """
        Unhedged arm: currency_mismatch_multiplier_applied must be True.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == True.
        """
        applied = unhedged_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result."
        )
        assert applied is True or applied == True, (  # noqa: E712
            f"Unhedged arm (is_hedged=False): currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected True — is_hedged=False with currency mismatch must trigger Art. 123B."
        )


# ---------------------------------------------------------------------------
# Cross-arm regression guard: RW delta = 0.375
# ---------------------------------------------------------------------------


class TestP194ACrossArmRWDelta:
    """
    Cross-arm invariant: the sole driver of the RW difference is the is_hedged flag.

    Both arms are identical except for is_hedged. The RW delta must equal exactly
    the Art. 123B premium on the base retail RW:

        delta = SA_RETAIL_BASE_RW × (CURRENCY_MISMATCH_MULTIPLIER − 1)
              = 0.75 × 0.50 = 0.375

    This guard will catch regressions that break one arm without affecting the other.
    """

    @pytest.fixture(scope="class")
    def both_results(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> tuple[dict, dict]:
        """Run both arms and return (hedged_result, unhedged_result)."""
        hedged = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=True,
            config=b31_config,
        )
        unhedged = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=b31_config,
        )
        return hedged, unhedged

    def test_p1_94a_rw_delta_between_arms_equals_art123b_premium(
        self, both_results: tuple[dict, dict]
    ) -> None:
        """
        RW(unhedged) − RW(hedged) must equal the Art. 123B mismatch premium = 0.375.

        Arrange: two runs of SA calculator, identical except is_hedged flag.
        Act:     compute delta of risk_weight outputs.
        Assert:  delta ≈ 0.375  (= SA_RETAIL_BASE_RW × (1.5 − 1) = 0.75 × 0.5).

        Pre-fix failure: delta = 0.000 (both arms get the multiplier, no hedging gate).
        Post-fix expected: delta = 0.375 (only unhedged arm carries the Art. 123B premium).
        """
        hedged_result, unhedged_result = both_results
        rw_hedged = float(hedged_result["risk_weight"])
        rw_unhedged = float(unhedged_result["risk_weight"])
        expected_delta = SA_RETAIL_BASE_RW * (CURRENCY_MISMATCH_MULTIPLIER - 1.0)

        delta = rw_unhedged - rw_hedged
        assert delta == pytest.approx(expected_delta, abs=_RW_TOL), (
            f"RW delta (unhedged − hedged) = {delta:.4f}. "
            f"Expected {expected_delta:.4f} = {SA_RETAIL_BASE_RW:.2f} × "
            f"({CURRENCY_MISMATCH_MULTIPLIER:.2f} − 1). "
            f"Pre-fix value: 0.000 (no is_hedged gate — both arms get the Art. 123B premium). "
            f"hedged RW = {rw_hedged:.4f}, unhedged RW = {rw_unhedged:.4f}."
        )
