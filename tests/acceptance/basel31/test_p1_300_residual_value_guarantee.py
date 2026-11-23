"""
P1.300 Basel 3.1 — PS1/26 Art. 134(7) / 166A(4): a third party's residual-value
payment obligation on a lease, recognised as unfunded credit protection.

PS1/26 keeps the limb (Art. 134(7), ``ps126app1.pdf`` 0-indexed page 68; Art.
166A(4), page 116): where a party other than the lessee is required to pay the
residual value of a leased asset and the obligation meets Credit Risk Mitigation
(CRR) Part Art. 201 and Art. 213-215, it "may be taken into account as unfunded
credit protection under the Credit Risk Mitigation (CRR) Part". CRM Part Art.
213(1)(c)(iii) (page 186) keeps the "when the leasing contract has expired"
payout limb and points back at Art. 134(7) and 166A(4).

Same input route as the CRR twin: the residual value is its own exposure
(``entity_type = "other_residual_lease"``, class OTHER) and the obligation is an
ordinary GUARANTEE row on it. Scenarios (``tests/fixtures/p1_300/p1_300.py``
holds the derivation), each a residual value of 1,000,000 at 100%:

    unguaranteed      control                               -> rwa_final 1,000,000
    institution_cqs2  CQS 2 institution, ECRA 30% (Table 3) -> rwa_final   300,000
    corporate_cqs5    CQS 5 corporate, 150% (Table 6)       -> declined, 1,000,000

The CRR mover is 500,000, so the regimes are told apart by the ECRA weight.

References:
    - PS1/26 Art. 134(7), Art. 166A(4), Art. 147(8).
    - PS1/26 CRM Part Art. 201(1)(g), 213(1)(c)(iii), 235(1), 193(1).
    - PS1/26 Art. 120 Table 3 (ECRA CQS 2 30%), Art. 122(2) Table 6 (CQS 5 150%).
    - IMPLEMENTATION_PLAN.md: P1.300.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_300.p1_300 import (
    B31_INSTITUTION_CQS2_RW,
    CORPORATE_CQS5_RW,
    EXPECTED_RWA,
    RESIDUAL_VALUE_RW,
    SCENARIOS,
    STATUS_DECLINED,
    STATUS_SUBSTITUTED,
    build_p1_300_bundle,
)

REPORTING_DATE = date(2030, 6, 30)
REGIME = "b31"


@pytest.fixture(scope="module")
def result() -> AggregatedResultBundle:
    config = CalculationConfig.basel_3_1(reporting_date=REPORTING_DATE)
    return PipelineOrchestrator().run_with_data(build_p1_300_bundle(REPORTING_DATE), config)


def _rows(result: AggregatedResultBundle, label: str) -> pl.DataFrame:
    loan_ref = SCENARIOS[label].loan_ref
    rows = result.sa_results.filter(pl.col("parent_exposure_reference") == loan_ref).collect()
    assert rows.height > 0, f"P1.300 {label}: no SA result rows for {loan_ref!r}"
    assert rows["rwa_final"].null_count() == 0, f"P1.300 {label}: null rwa_final"
    return rows


def _guaranteed_leg(result: AggregatedResultBundle, label: str) -> dict:
    legs = _rows(result, label).filter(pl.col("guaranteed_portion") > 0)
    assert legs.height == 1, f"P1.300 {label}: expected one guaranteed leg, got {legs.height}"
    return legs.row(0, named=True)


class TestP1300B31ResidualValueGuarantee:
    """Basel 3.1: a residual-value guarantee substitutes the guarantor's SA risk weight."""

    def test_unguaranteed_residual_value_takes_full_weight(
        self, result: AggregatedResultBundle
    ) -> None:
        """Control: no guarantee -> Art. 134(7) residual value at 100% (no ``t`` input)."""
        # Arrange / Act
        rows = _rows(result, "unguaranteed")

        # Assert
        assert rows["pre_crm_risk_weight"].to_list() == [RESIDUAL_VALUE_RW]
        assert rows["rwa_final"].sum() == pytest.approx(EXPECTED_RWA[(REGIME, "unguaranteed")])

    def test_institution_guarantee_substitutes_residual_value(
        self, result: AggregatedResultBundle
    ) -> None:
        """MOVER: a CQS 2 institution guarantee takes the residual value to ECRA 30%."""
        # Arrange / Act
        leg = _guaranteed_leg(result, "institution_cqs2")
        total = _rows(result, "institution_cqs2")["rwa_final"].sum()

        # Assert
        assert leg["pre_crm_risk_weight"] == pytest.approx(RESIDUAL_VALUE_RW)
        assert leg["guarantor_rw"] == pytest.approx(B31_INSTITUTION_CQS2_RW)
        assert leg["guarantee_status"] == STATUS_SUBSTITUTED
        assert leg["post_crm_exposure_class_guaranteed"] == "institution"
        assert total == pytest.approx(EXPECTED_RWA[(REGIME, "institution_cqs2")])

    def test_non_beneficial_guarantee_is_declined(self, result: AggregatedResultBundle) -> None:
        """SURVIVOR: a rated CQS 5 corporate (150%) is declined by Art. 193(1).

        ``guarantor_rw`` is asserted non-null so the decline is proved to come
        from the benefit test, not from Art. 201(1)(g) ineligibility (which
        nulls ``guarantor_rw`` and reports the same status string).
        """
        # Arrange / Act
        leg = _guaranteed_leg(result, "corporate_cqs5")
        total = _rows(result, "corporate_cqs5")["rwa_final"].sum()

        # Assert
        assert leg["guarantor_rw"] == pytest.approx(CORPORATE_CQS5_RW)
        assert leg["is_guarantee_beneficial"] is False
        assert leg["guarantee_status"] == STATUS_DECLINED
        assert total == pytest.approx(EXPECTED_RWA[(REGIME, "corporate_cqs5")])

    def test_both_guarantors_pass_eligibility(self, result: AggregatedResultBundle) -> None:
        """Neither guarantee is screened out: no CRM-coded warning is raised."""
        # Arrange / Act
        crm_codes = [e.code for e in result.errors if (e.code or "").startswith("CRM")]

        # Assert
        assert crm_codes == []
