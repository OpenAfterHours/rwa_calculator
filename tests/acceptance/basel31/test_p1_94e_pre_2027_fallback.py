"""
P1.94e — Basel 3.1 Art. 123B currency-mismatch multiplier: pre-2027 transitional fallback.

Acceptance scenario verifying that the 1.5x Art. 123B currency-mismatch multiplier
is suppressed when config.reporting_date < B31_EFFECTIVE_DATE (2027-01-01), and fires
when reporting_date >= 2027-01-01 (boundary date is in scope).

Pipeline position:
    SACalculator.apply_currency_mismatch_multiplier  (namespace.py)
    -> date gate: config.reporting_date < B31_EFFECTIVE_DATE => suppress multiplier

Scenario design:
    Two runs over an identical FX-mismatched unhedged retail_other row:
        - currency = EUR (mismatch against GBP income)
        - exposure_class = retail_other
        - is_hedged = False (multiplier eligibility open)
        - ead_final = 100,000
        - pre-multiplier risk_weight = 0.75 (Art. 123(1))

    Run A — reporting_date 2026-12-31 (pre-effective date):
        2026-12-31 < 2027-01-01 is True => transitional gate fires => multiplier suppressed
        Expected: risk_weight = 0.75, rwa = 75,000, multiplier_applied = False

    Run B — reporting_date 2027-01-01 (boundary; on effective date):
        2027-01-01 < 2027-01-01 is False => gate does not fire => multiplier applies
        Expected: risk_weight = 1.125, rwa = 112,500, multiplier_applied = True

Pre-fix failure mode:
    Engine applies the 1.5x multiplier regardless of reporting_date.
    Run A returns risk_weight = 1.125 / rwa = 112,500 instead of 0.75 / 75,000.
    Test fails on the Run A assertion: assert 1.125 == approx(0.75).

References:
    - PRA PS1/26 Art. 123B(3): transitional treatment; commencement 1 January 2027.
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - BCBS CRE20.93: currency mismatch multiplier effective date.
    - tests/fixtures/p1_94e/p1_94e.py: scenario constants.
    - tests/fixtures/single_exposure.py: calculate_single_sa_exposure helper.
    - src/rwa_calc/engine/sa/namespace.py: apply_currency_mismatch_multiplier.
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_EFFECTIVE_DATE (new scalar).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from tests.fixtures.p1_94e.p1_94e import (
    CURRENCY_MISMATCH_MULTIPLIER,
    EAD,
    MULTIPLIER_APPLIED_B31,
    MULTIPLIER_APPLIED_PRE_2027,
    REPORTING_DATE_B31,
    REPORTING_DATE_PRE_2027,
    RW_B31,
    RW_PRE_2027,
    RWA_B31,
    RWA_PRE_2027,
    SA_RETAIL_BASE_RW,
)
from tests.fixtures.single_exposure import calculate_single_sa_exposure

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_RW_TOL = 1e-6   # risk_weight (dimensionless ratio)
_RWA_TOL = 0.50  # £0.50 on rwa

# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sa_calculator() -> SACalculator:
    """Return a fresh SACalculator instance."""
    return SACalculator()


@pytest.fixture(scope="module")
def config_pre_2027() -> CalculationConfig:
    """Basel 3.1 config with 2026-12-31 reporting date (pre-effective date)."""
    return CalculationConfig.basel_3_1(reporting_date=REPORTING_DATE_PRE_2027)


@pytest.fixture(scope="module")
def config_b31() -> CalculationConfig:
    """Basel 3.1 config with 2027-01-01 reporting date (on effective date; boundary in scope)."""
    return CalculationConfig.basel_3_1(reporting_date=REPORTING_DATE_B31)


# ---------------------------------------------------------------------------
# Run A — reporting_date 2026-12-31: multiplier must be suppressed
# ---------------------------------------------------------------------------


class TestP194EPreEffectiveDateMultiplierSuppressed:
    """
    Run A: identical retail_other EUR exposure, reporting_date=2026-12-31.

    The transitional gate (config.reporting_date < B31_EFFECTIVE_DATE) fires,
    suppressing the Art. 123B 1.5x multiplier entirely.

    Pre-fix failure: engine applies the 1.5x multiplier unconditionally (no
    reporting_date gate), so risk_weight = 1.125 instead of 0.75.

    Expected post-fix: risk_weight = 0.75, rwa = 75,000,
                       currency_mismatch_multiplier_applied = False.
    """

    @pytest.fixture(scope="class")
    def pre_2027_result(
        self,
        sa_calculator: SACalculator,
        config_pre_2027: CalculationConfig,
    ) -> dict:
        """Run SA calculator with pre-2027 reporting date (Run A)."""
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal(str(EAD)),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=config_pre_2027,
        )

    def test_p1_94e_pre_2027_risk_weight_equals_base_retail_rw(
        self, pre_2027_result: dict
    ) -> None:
        """
        Pre-2027: risk_weight must equal base retail SA RW — multiplier suppressed.

        Arrange: retail_other, EUR currency, GBP income, is_hedged=False,
                 reporting_date=2026-12-31 (strict < 2027-01-01).
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  risk_weight ≈ 0.75 (Art. 123(1) base; reporting_date gate fires).

        Pre-fix failure: engine returns risk_weight = 1.125 (no reporting_date gate).
        """
        rw = float(pre_2027_result["risk_weight"])
        assert rw == pytest.approx(RW_PRE_2027, abs=_RW_TOL), (
            f"Run A (reporting_date=2026-12-31): risk_weight {rw:.4f} != "
            f"expected {RW_PRE_2027:.4f}. "
            f"The reporting_date gate is not yet implemented — engine fires the 1.5x "
            f"Art. 123B multiplier unconditionally (pre-fix value ≈ {RW_B31:.4f})."
        )

    def test_p1_94e_pre_2027_rwa_equals_base_rwa(self, pre_2027_result: dict) -> None:
        """
        Pre-2027: rwa must equal EAD × base retail RW = 75,000.

        Arrange/Act: as above.
        Assert:  rwa ≈ 75,000.00  (100,000 × 0.75; no mismatch premium).

        Pre-fix failure: engine returns rwa ≈ 112,500.
        """
        rwa = float(pre_2027_result["rwa"])
        assert rwa == pytest.approx(RWA_PRE_2027, abs=_RWA_TOL), (
            f"Run A (reporting_date=2026-12-31): rwa {rwa:,.2f} != "
            f"expected {RWA_PRE_2027:,.2f}. "
            f"Pre-fix (no reporting_date gate) produces rwa = {RWA_B31:,.2f}."
        )

    def test_p1_94e_pre_2027_currency_mismatch_multiplier_not_applied(
        self, pre_2027_result: dict
    ) -> None:
        """
        Pre-2027: currency_mismatch_multiplier_applied must be False.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == False.

        Pre-fix failure: engine sets the flag to True for all mismatch exposures.
        """
        applied = pre_2027_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result. "
            "The engine must emit this column (see namespace.py apply_currency_mismatch_multiplier)."
        )
        assert applied == MULTIPLIER_APPLIED_PRE_2027, (  # noqa: E712
            f"Run A (reporting_date=2026-12-31): currency_mismatch_multiplier_applied "
            f"= {applied!r}. Expected {MULTIPLIER_APPLIED_PRE_2027!r} — "
            f"reporting_date < 2027-01-01 must suppress the Art. 123B multiplier."
        )


# ---------------------------------------------------------------------------
# Run B — reporting_date 2027-01-01: multiplier must fire (boundary in scope)
# ---------------------------------------------------------------------------


class TestP194EOnEffectiveDateMultiplierFires:
    """
    Run B: identical retail_other EUR exposure, reporting_date=2027-01-01.

    The boundary date 2027-01-01 is NOT strictly less than 2027-01-01,
    so the gate does not fire and the Art. 123B multiplier applies.

    Expected: risk_weight = 1.125, rwa = 112,500,
              currency_mismatch_multiplier_applied = True.
    """

    @pytest.fixture(scope="class")
    def b31_result(
        self,
        sa_calculator: SACalculator,
        config_b31: CalculationConfig,
    ) -> dict:
        """Run SA calculator with 2027-01-01 reporting date (Run B)."""
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal(str(EAD)),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=config_b31,
        )

    def test_p1_94e_b31_risk_weight_equals_multiplied_rw(self, b31_result: dict) -> None:
        """
        On effective date: risk_weight = 75% × 1.5 = 112.5%.

        Arrange: retail_other, EUR currency, GBP income, is_hedged=False,
                 reporting_date=2027-01-01 (boundary; strict < is False).
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  risk_weight ≈ 1.125  (Art. 123(1) base × Art. 123B multiplier).
        """
        rw = float(b31_result["risk_weight"])
        assert rw == pytest.approx(RW_B31, abs=_RW_TOL), (
            f"Run B (reporting_date=2027-01-01): risk_weight {rw:.4f} != "
            f"expected {RW_B31:.4f}. "
            f"Art. 123B 1.5x multiplier must fire on the boundary date 2027-01-01."
        )

    def test_p1_94e_b31_rwa_equals_multiplied_rwa(self, b31_result: dict) -> None:
        """
        On effective date: rwa = 100,000 × 1.125 = 112,500.

        Arrange/Act: as above.
        Assert:  rwa ≈ 112,500.00.
        """
        rwa = float(b31_result["rwa"])
        assert rwa == pytest.approx(RWA_B31, abs=_RWA_TOL), (
            f"Run B (reporting_date=2027-01-01): rwa {rwa:,.2f} != "
            f"expected {RWA_B31:,.2f}."
        )

    def test_p1_94e_b31_currency_mismatch_multiplier_applied(self, b31_result: dict) -> None:
        """
        On effective date: currency_mismatch_multiplier_applied must be True.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == True.
        """
        applied = b31_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result."
        )
        assert applied == MULTIPLIER_APPLIED_B31, (  # noqa: E712
            f"Run B (reporting_date=2027-01-01): currency_mismatch_multiplier_applied "
            f"= {applied!r}. Expected {MULTIPLIER_APPLIED_B31!r} — "
            f"boundary date is in scope (strict < is False)."
        )


# ---------------------------------------------------------------------------
# Cross-run invariant: RW delta must equal Art. 123B premium
# ---------------------------------------------------------------------------


class TestP194ECrossRunRWDelta:
    """
    Cross-run invariant: Run B RW − Run A RW = Art. 123B premium on retail base RW.

    The only variable between the two runs is reporting_date; identical row, identical
    config otherwise. The RW delta must equal the mismatch premium:

        delta = SA_RETAIL_BASE_RW × (CURRENCY_MISMATCH_MULTIPLIER − 1)
              = 0.75 × 0.50 = 0.375

    Pre-fix delta: 0.000 (both runs produce 1.125 — no gate suppresses Run A).
    Post-fix delta: 0.375 (Run A suppressed = 0.75, Run B fires = 1.125).
    """

    @pytest.fixture(scope="class")
    def both_results(
        self,
        sa_calculator: SACalculator,
        config_pre_2027: CalculationConfig,
        config_b31: CalculationConfig,
    ) -> tuple[dict, dict]:
        """Run both configurations and return (pre_2027_result, b31_result)."""
        pre_2027 = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal(str(EAD)),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=config_pre_2027,
        )
        b31 = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal(str(EAD)),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=config_b31,
        )
        return pre_2027, b31

    def test_p1_94e_rw_delta_between_runs_equals_art123b_premium(
        self, both_results: tuple[dict, dict]
    ) -> None:
        """
        RW(Run B) − RW(Run A) must equal the Art. 123B mismatch premium = 0.375.

        Arrange: two runs of SA calculator, identical row; only reporting_date varies.
        Act:     compute delta of risk_weight outputs.
        Assert:  delta ≈ 0.375  (= SA_RETAIL_BASE_RW × (1.5 − 1) = 0.75 × 0.5).

        Pre-fix failure: delta = 0.000 (both runs get the multiplier; no date gate).
        Post-fix expected: delta = 0.375.
        """
        pre_2027_result, b31_result = both_results
        rw_pre_2027 = float(pre_2027_result["risk_weight"])
        rw_b31 = float(b31_result["risk_weight"])
        expected_delta = SA_RETAIL_BASE_RW * (CURRENCY_MISMATCH_MULTIPLIER - 1.0)

        delta = rw_b31 - rw_pre_2027
        assert delta == pytest.approx(expected_delta, abs=_RW_TOL), (
            f"RW delta (Run B − Run A) = {delta:.4f}. "
            f"Expected {expected_delta:.4f} = {SA_RETAIL_BASE_RW:.2f} × "
            f"({CURRENCY_MISMATCH_MULTIPLIER:.2f} − 1). "
            f"Pre-fix value: 0.000 (no reporting_date gate — both runs get the Art. 123B premium). "
            f"Run A (2026-12-31) RW = {rw_pre_2027:.4f}, "
            f"Run B (2027-01-01) RW = {rw_b31:.4f}."
        )
