"""
P1.94f — B31 Art. 123B: currency-mismatch multiplier scope limited to retail exposures.

Acceptance scenario verifying that the 1.5x Art. 123B currency-mismatch multiplier
fires ONLY on retail_other exposures and does NOT fire on commercial_mortgage or
corporate exposures, even when all other conditions (EUR loan, GBP income,
is_hedged=False) are met.

Pipeline position:
    SACalculator.apply_currency_mismatch_multiplier  (namespace.py)

Scenario design:
    All three arms share EUR-denominated loans against GBP-income counterparties
    in a Basel 3.1 framework. All exposures have is_hedged=False.

    Arm A — P194F_RRE (retail_other, EAD = EUR 100,000):
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        is_hedged=False + currency mismatch (EUR vs GBP income)
            → Art. 123B multiplier fires: 1.5 × 75% = 112.5%
        Expected: exposure_class = retail_other
                  risk_weight = 1.125
                  rwa = 112,500
                  currency_mismatch_multiplier_applied = True

    Arm B — P194F_CRE (commercial_mortgage, EAD = EUR 1,000,000):
        LTV 65% (EUR 1,000,000 / EUR 1,538,461.54 ≈ 65%), unrated corporate
        Base SA CRE RW = 100%  (PRA PS1/26 Art. 126, standard CRE)
        is_hedged=False + currency mismatch — but exposure_class is NOT retail_other
            → Art. 123B gate fails: multiplier SUPPRESSED by exposure-class scope
        Expected: exposure_class = commercial_mortgage
                  risk_weight = 1.00
                  rwa = 1,000,000
                  currency_mismatch_multiplier_applied = False
        Anti-assertion (load-bearing — fails on master):
            risk_weight != 1.50  (master bug: engine sees COMMERCIAL_MORTGAGE
            matching "COMMERCIAL" in is_retail_or_re predicate → fires multiplier)
            rwa != 1,500,000

    Arm C — P194F_CORP (corporate, EAD = EUR 1,000,000):
        Base SA corporate RW = 100%  (PRA PS1/26 Art. 122, unrated)
        is_hedged=False + currency mismatch — but exposure_class is NOT retail_other
            → Art. 123B gate fails: multiplier SUPPRESSED by exposure-class scope
        Expected: exposure_class = corporate
                  risk_weight = 1.00
                  rwa = 1,000,000
                  currency_mismatch_multiplier_applied = False

Engine bug locus (master):
    engine/sa/namespace.py lines 1886-1892 — is_retail_or_re predicate contains
    "COMMERCIAL" and "CRE" literals which sweep in COMMERCIAL_MORTGAGE, causing the
    multiplier to fire on Arm B producing risk_weight = 1.50, rwa = 1,500,000.

Pre-fix failure mode (Wave 3):
    Arm B test (test_arm_b_cre_out_of_scope_multiplier_NOT_applied) fails:
    risk_weight = 1.50 instead of 1.00.
    currency_mismatch_multiplier_applied = True instead of False.

References:
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - PRA PS1/26 Art. 123B: 1.5x currency-mismatch multiplier applies only to
      retail exposures (non-mortgage retail / retail_other class).
    - PRA PS1/26 Art. 122: corporate SA risk weights.
    - PRA PS1/26 Art. 126: commercial RE SA risk weights (LTV-dependent table).
    - BCBS CRE20.89-90: currency mismatch add-on for unhedged FX retail.
    - tests/fixtures/p1_94f/p1_94f.py: fixture constants (RW_RRE, RW_CRE, etc.)
    - tests/acceptance/basel31/test_p1_94a_is_hedged_gates_currency_mismatch.py:
      sibling scenario for is_hedged gate (same multiplier logic).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from tests.fixtures.p1_94f.p1_94f import (
    CURRENCY_MISMATCH_MULTIPLIER,
    RW_CORP,
    RW_CRE,
    RW_RRE,
    RWA_CORP,
    RWA_CRE,
    RWA_RRE,
    SA_RETAIL_BASE_RW,
)
from tests.fixtures.single_exposure import calculate_single_sa_exposure

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_EAD_RRE = Decimal("100_000")
_EAD_CRE = Decimal("1_000_000")
_EAD_CORP = Decimal("1_000_000")
_REPORTING_DATE = date(2027, 1, 4)

# Absolute tolerances
_RW_TOL = 1e-6  # risk_weight (dimensionless ratio)
_RWA_TOL = 0.50  # 50p on rwa

# Pre-fix (master) bug value for Arm B: commercial_mortgage gets 1.5x on 100% base
# namespace.py str.contains("COMMERCIAL") matches COMMERCIAL_MORTGAGE → multiplier fires
_BUGGY_RW_CRE_MASTER = 1.00 * CURRENCY_MISMATCH_MULTIPLIER  # 1.50
_BUGGY_RWA_CRE_MASTER = float(_EAD_CRE) * _BUGGY_RW_CRE_MASTER  # 1,500,000

# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sa_calculator() -> SACalculator:
    """Return a fresh SACalculator instance (SA-only, no IRB)."""
    return SACalculator()


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 config with 2027 reporting date (post-effective date)."""
    return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)


# ===========================================================================
# Arm A — retail_other: multiplier MUST fire (regression guard against over-narrowing)
# ===========================================================================


class TestP194FArmARREMultiplierApplied:
    """
    Arm A: retail_other EUR exposure, is_hedged=False, GBP income.

    Art. 123B fires: base retail RW (75%) × 1.5 = 112.5%.
    This arm already passes on master. It is a regression guard to ensure that
    the engine fix (narrowing is_retail_or_re) does NOT suppress the multiplier
    for genuine retail_other exposures.

    Expected: risk_weight = 1.125  (75% × 1.5)
              rwa = 112,500  (100,000 × 1.125)
              currency_mismatch_multiplier_applied = True
    """

    @pytest.fixture(scope="class")
    def rre_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """Run the SA calculator for Arm A: retail_other, EUR, GBP income, is_hedged=False."""
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD_RRE,
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=b31_config,
        )

    def test_arm_a_rre_in_scope_risk_weight(self, rre_result: dict) -> None:
        """
        Arm A (retail_other): risk_weight = 1.125 (75% base × 1.5 Art. 123B multiplier).

        Arrange: retail_other, EUR currency, GBP income, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  risk_weight ≈ 1.125.

        Regression guard: the engine fix must NOT suppress the multiplier for retail_other.
        If this assertion fails, the is_retail_or_re predicate has been over-narrowed.
        """
        rw = float(rre_result["risk_weight"])
        assert rw == pytest.approx(RW_RRE, abs=_RW_TOL), (
            f"Arm A (retail_other): risk_weight {rw:.6f} != expected {RW_RRE:.6f} "
            f"(= {SA_RETAIL_BASE_RW:.2f} × {CURRENCY_MISMATCH_MULTIPLIER:.2f}). "
            f"The Art. 123B multiplier must still fire for retail_other exposures "
            f"with currency mismatch and is_hedged=False. "
            f"If this fails post-fix, the is_retail_or_re predicate was over-narrowed "
            f"and no longer includes retail_other."
        )

    def test_arm_a_rre_in_scope_rwa(self, rre_result: dict) -> None:
        """
        Arm A (retail_other): rwa = EAD × 1.125 = 112,500.

        Arrange/Act: as above.
        Assert:  rwa ≈ 112,500 (abs=0.50).
        """
        rwa = float(rre_result["rwa"])
        assert rwa == pytest.approx(RWA_RRE, abs=_RWA_TOL), (
            f"Arm A (retail_other): rwa {rwa:,.2f} != expected {RWA_RRE:,.2f}. "
            f"EAD = {float(_EAD_RRE):,.0f} × risk_weight {RW_RRE:.4f}."
        )

    def test_arm_a_rre_in_scope_multiplier_applied(self, rre_result: dict) -> None:
        """
        Arm A (retail_other): currency_mismatch_multiplier_applied = True.

        Arrange/Act: as above.
        Assert:  currency_mismatch_multiplier_applied == True.
        """
        applied = rre_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result. "
            "The engine must emit this column "
            "(see namespace.py apply_currency_mismatch_multiplier)."
        )
        assert applied is True or applied == True, (  # noqa: E712
            f"Arm A (retail_other): currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected True — retail_other + EUR vs GBP income + is_hedged=False "
            f"must trigger Art. 123B."
        )


# ===========================================================================
# Arm B — commercial_mortgage: multiplier must NOT fire (load-bearing failing test)
# ===========================================================================


class TestP194FArmBCREMultiplierNotApplied:
    """
    Arm B: commercial_mortgage EUR exposure, is_hedged=False, GBP income.

    The exposure has a currency mismatch, but commercial_mortgage is OUT of
    Art. 123B scope — the multiplier must be suppressed by the exposure-class gate.

    THIS is the load-bearing class that FAILS on master.

    Master bug: namespace.py is_retail_or_re predicate uses:
        _uc.str.contains("COMMERCIAL", literal=True)  # line 1890
    which catches COMMERCIAL_MORTGAGE (upper-cased to "COMMERCIAL_MORTGAGE").
    Engine produces: risk_weight = 1.50, rwa = 1,500,000,
                     currency_mismatch_multiplier_applied = True.

    Expected post-fix:
        risk_weight = 1.00  (Art. 126 standard CRE, LTV 65%, unrated corporate;
                             no 1.5x multiplier)
        rwa = 1,000,000  (EUR 1,000,000 × 1.00)
        currency_mismatch_multiplier_applied = False
    """

    @pytest.fixture(scope="class")
    def cre_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """Run the SA calculator for Arm B: commercial_mortgage, EUR, GBP income, is_hedged=False.

        LTV = 65% (EAD 1,000,000 / collateral 1,538,461.54). Under Art. 126, standard
        CRE (unrated, non-ADC, non-IPRE) with LTV <= 80% → 100% risk weight.
        The collateral_re_value is passed directly to bypass the CRM pipeline
        (consistent with p1_94a pattern of using calculate_single_sa_exposure).
        """
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD_CRE,
            exposure_class="commercial_mortgage",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=False,
            is_hedged=False,
            ltv=Decimal("0.65"),
            property_type="commercial",
            config=b31_config,
        )

    def test_arm_b_cre_out_of_scope_multiplier_NOT_applied(self, cre_result: dict) -> None:
        """
        Arm B (commercial_mortgage): currency_mismatch_multiplier_applied = False.

        LOAD-BEARING TEST — FAILS on master (engine returns True).

        Arrange: commercial_mortgage, EUR 1,000,000, GBP income, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  currency_mismatch_multiplier_applied == False.

        Pre-fix failure: namespace.py line 1890 — str.contains("COMMERCIAL") matches
        COMMERCIAL_MORTGAGE → mismatch_applies=True → multiplier fires.
        Post-fix: is_retail_or_re must be narrowed to exact retail_other /
        residential_mortgage classes only.
        """
        applied = cre_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result. "
            "The engine must emit this column "
            "(see namespace.py apply_currency_mismatch_multiplier)."
        )
        assert applied is False or applied == False, (  # noqa: E712
            f"P1.94f Arm B (commercial_mortgage): "
            f"currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected False — Art. 123B scope is limited to retail exposures; "
            f"commercial_mortgage is NOT in scope. "
            f"Master bug (namespace.py:1890): is_retail_or_re uses "
            f"str.contains('COMMERCIAL') which over-matches COMMERCIAL_MORTGAGE. "
            f"Fix: narrow predicate to exact {{retail_other, residential_mortgage}} classes."
        )

    def test_arm_b_cre_out_of_scope_risk_weight(self, cre_result: dict) -> None:
        """
        Arm B (commercial_mortgage): risk_weight = 1.00 (Art. 126, LTV 65%, no multiplier).

        LOAD-BEARING TEST — FAILS on master (engine returns 1.50).

        Arrange: commercial_mortgage, EUR 1,000,000, LTV 65%, is_hedged=False, B31.
        Act:     SA calculator → commercial_mortgage risk weight lookup → no multiplier.
        Assert:  risk_weight ≈ 1.00.

        Anti-assertion: risk_weight != 1.50. On master, the over-broad
        is_retail_or_re predicate fires the 1.5x multiplier on the 100% CRE base
        RW, producing risk_weight = 1.50.
        """
        rw = float(cre_result["risk_weight"])

        # Anti-assertion (documents the master bug)
        assert rw != pytest.approx(_BUGGY_RW_CRE_MASTER, abs=_RW_TOL), (
            f"P1.94f Arm B (commercial_mortgage): risk_weight = {rw:.4f} "
            f"equals the buggy master value {_BUGGY_RW_CRE_MASTER:.4f}. "
            f"The Art. 123B multiplier must NOT fire on commercial_mortgage. "
            f"Expected risk_weight = {RW_CRE:.4f} (Art. 126, no multiplier)."
        )

        # Primary assertion
        assert rw == pytest.approx(RW_CRE, abs=_RW_TOL), (
            f"P1.94f Arm B (commercial_mortgage): risk_weight {rw:.6f} != "
            f"expected {RW_CRE:.6f}. "
            f"Art. 126 standard CRE (LTV 65%, unrated corporate) = 100%. "
            f"No Art. 123B multiplier (commercial_mortgage out of scope). "
            f"Pre-fix master value: {_BUGGY_RW_CRE_MASTER:.4f} "
            f"(str.contains('COMMERCIAL') over-matches COMMERCIAL_MORTGAGE)."
        )

    def test_arm_b_cre_out_of_scope_rwa(self, cre_result: dict) -> None:
        """
        Arm B (commercial_mortgage): rwa = EUR 1,000,000 × 1.00 = 1,000,000.

        LOAD-BEARING TEST — FAILS on master (engine returns 1,500,000).

        Arrange/Act: as above.
        Assert:  rwa ≈ 1,000,000 (abs=0.50).

        Anti-assertion: rwa != 1,500,000. On master the multiplier fires
        producing rwa = 1,500,000 = 1,000,000 × 1.50.
        """
        rwa = float(cre_result["rwa"])

        # Anti-assertion (documents master bug)
        assert rwa != pytest.approx(_BUGGY_RWA_CRE_MASTER, abs=_RWA_TOL), (
            f"P1.94f Arm B (commercial_mortgage): rwa = {rwa:,.2f} "
            f"equals the buggy master value {_BUGGY_RWA_CRE_MASTER:,.2f}. "
            f"Expected {RWA_CRE:,.2f} (no Art. 123B multiplier)."
        )

        # Primary assertion
        assert rwa == pytest.approx(RWA_CRE, abs=_RWA_TOL), (
            f"P1.94f Arm B (commercial_mortgage): rwa {rwa:,.2f} != "
            f"expected {RWA_CRE:,.2f}. "
            f"EAD = {float(_EAD_CRE):,.0f} × risk_weight {RW_CRE:.4f}. "
            f"Pre-fix master value: {_BUGGY_RWA_CRE_MASTER:,.2f}."
        )


# ===========================================================================
# Arm C — corporate: multiplier must NOT fire (sanity anchor)
# ===========================================================================


class TestP194FArmCCorporateMultiplierNotApplied:
    """
    Arm C: corporate EUR exposure, is_hedged=False, GBP income.

    The exposure has a currency mismatch, but corporate is clearly outside
    Art. 123B scope. This arm provides a sanity anchor — the "corporate"
    exposure class never matched the original is_retail_or_re predicate,
    so this passes on both master and post-fix.

    It guards against future regressions that might accidentally widen the
    predicate to include corporate.

    Expected: risk_weight = 1.00  (Art. 122, unrated)
              rwa = 1,000,000  (EUR 1,000,000 × 1.00)
              currency_mismatch_multiplier_applied = False
    """

    @pytest.fixture(scope="class")
    def corp_result(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> dict:
        """Run the SA calculator for Arm C: corporate, EUR, GBP income, is_hedged=False."""
        return calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD_CORP,
            exposure_class="corporate",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=False,
            is_hedged=False,
            config=b31_config,
        )

    def test_arm_c_corporate_out_of_scope_multiplier_NOT_applied(self, corp_result: dict) -> None:
        """
        Arm C (corporate): currency_mismatch_multiplier_applied = False.

        Arrange: corporate, EUR 1,000,000, GBP income, is_hedged=False, B31.
        Act:     SA calculator → apply_currency_mismatch_multiplier.
        Assert:  currency_mismatch_multiplier_applied == False.
        """
        applied = corp_result.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA result."
        )
        assert applied is False or applied == False, (  # noqa: E712
            f"Arm C (corporate): currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected False — Art. 123B scope does not include corporate exposures."
        )

    def test_arm_c_corporate_out_of_scope_risk_weight(self, corp_result: dict) -> None:
        """
        Arm C (corporate): risk_weight = 1.00 (Art. 122, unrated).

        Arrange/Act: as above.
        Assert:  risk_weight ≈ 1.00.
        """
        rw = float(corp_result["risk_weight"])
        assert rw == pytest.approx(RW_CORP, abs=_RW_TOL), (
            f"Arm C (corporate): risk_weight {rw:.6f} != expected {RW_CORP:.6f} "
            f"(Art. 122 unrated = 100%, no Art. 123B multiplier)."
        )

    def test_arm_c_corporate_out_of_scope_rwa(self, corp_result: dict) -> None:
        """
        Arm C (corporate): rwa = EUR 1,000,000 × 1.00 = 1,000,000.

        Arrange/Act: as above.
        Assert:  rwa ≈ 1,000,000 (abs=0.50).
        """
        rwa = float(corp_result["rwa"])
        assert rwa == pytest.approx(RWA_CORP, abs=_RWA_TOL), (
            f"Arm C (corporate): rwa {rwa:,.2f} != expected {RWA_CORP:,.2f}. "
            f"EAD = {float(_EAD_CORP):,.0f} × risk_weight {RW_CORP:.4f}."
        )


# ===========================================================================
# Cross-arm invariant: scope boundary — only retail_other fires the multiplier
# ===========================================================================


class TestP194FCrossArmScopeBoundary:
    """
    Cross-arm invariant: Art. 123B fires ONLY for retail_other exposures.

    All three arms have identical mismatch conditions (EUR loan, GBP income,
    is_hedged=False). The sole driver of multiplier application is exposure_class.

    Under the current master bug, Arm B (commercial_mortgage) also fires — the
    delta between Arm A and Arm B is incorrect (RW_RRE != RW_CRE).
    Post-fix: both Arm B and Arm C have risk_weight = 1.00 (no multiplier),
    while Arm A has risk_weight = 1.125 (multiplier applied).
    """

    @pytest.fixture(scope="class")
    def all_results(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> tuple[dict, dict, dict]:
        """Run all three arms and return (rre, cre, corp) results."""
        rre = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD_RRE,
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=True,
            is_hedged=False,
            config=b31_config,
        )
        cre = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD_CRE,
            exposure_class="commercial_mortgage",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=False,
            is_hedged=False,
            ltv=Decimal("0.65"),
            property_type="commercial",
            config=b31_config,
        )
        corp = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD_CORP,
            exposure_class="corporate",
            currency="EUR",
            borrower_income_currency="GBP",
            cp_is_natural_person=False,
            is_hedged=False,
            config=b31_config,
        )
        return rre, cre, corp

    def test_p1_94f_only_retail_other_arm_has_multiplier_applied(
        self, all_results: tuple[dict, dict, dict]
    ) -> None:
        """
        Exactly one arm (retail_other) has currency_mismatch_multiplier_applied=True.

        Under the master bug, two arms (retail_other + commercial_mortgage) have
        the flag set to True. Post-fix, only retail_other fires.

        Arrange: three arms — retail_other, commercial_mortgage, corporate.
        All share EUR currency, GBP income, is_hedged=False.
        Act:     SA calculator for each arm.
        Assert:  exactly 1 arm has multiplier_applied=True (the retail_other arm).

        Pre-fix failure: 2 arms have multiplier_applied=True.
        """
        rre, cre, corp = all_results
        multiplier_flags = {
            "retail_other": rre.get("currency_mismatch_multiplier_applied"),
            "commercial_mortgage": cre.get("currency_mismatch_multiplier_applied"),
            "corporate": corp.get("currency_mismatch_multiplier_applied"),
        }
        arms_with_multiplier = [k for k, v in multiplier_flags.items() if v]
        assert arms_with_multiplier == ["retail_other"], (
            f"P1.94f: exactly 1 arm should have currency_mismatch_multiplier_applied=True "
            f"(retail_other only). Got: {arms_with_multiplier}. "
            f"All flags: {multiplier_flags}. "
            f"Pre-fix: commercial_mortgage erroneously also fires the multiplier "
            f"(str.contains('COMMERCIAL') in is_retail_or_re over-matches)."
        )
