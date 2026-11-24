"""
P1.298: CRR Art. 116(5) on the PSE *guarantor* — end-to-end, both regimes, SA and IRB.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA / IRB calculators -> OutputAggregator

Key responsibilities:
- Prove a third-country PSE guarantor with no asserted equivalence determination
  substitutes at Art. 116(5)'s flat 100% on the covered part, end to end: the
  guarantor's ``is_equivalent_jurisdiction`` is read off its own counterparty row
  by the CRM guarantee join, carried on ``guarantor_is_equivalent_jurisdiction``
  through the sealed CRM / RE-split edges, and consumed by the SA and the IRB
  (RWSM ``guarantor_rw_sa``) substitution paths.
- Both directions: CQS1-3 guarantors lose relief (RWA up, and the strict-< benefit
  test then declines the guarantee over a 100% obligor); a CQS6 guarantor's 150%
  falls to 100% and the guarantee becomes beneficial over a 150% obligor (RWA
  down) — the rule's "Otherwise ... 100 %" is flat.
- The permitted limbs (GB guarantor; flag True) and the RGLA branch do not move.

Regulatory basis (verbatim):
    CRR Art. 116(5): "... institutions may risk weight exposures to such public
    sector entities in the same manner. Otherwise the institutions shall apply a
    risk weight of 100 %."
    PS1/26 Art. 235(1)(a): "rg = the risk weight of a comparable direct exposure to
    the protection provider as specified under the Credit Risk: Standardised
    Approach (CRR) Part and Chapter 2 of Title II of Part Three of CRR."
    PS1/26 Art. 116(5): "[Note: Provision not in PRA Rulebook]" — it survives in
    CRR and PS1/26 Art. 116(3A) cross-refers to it, so one gate binds both regimes.

References:
    - CRR Art. 116(5), Art. 201(1)(e), Art. 235(1); PS1/26 Art. 116(3A), 235(1)(a)
    - tests/fixtures/p1_298/p1_298.py — the scenario table
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.conftest import get_guaranteed_row, get_total_rwa
from tests.fixtures.p1_298.p1_298 import SA_SCENARIOS, build_irb_bundle, build_sa_bundle
from tests.fixtures.pse_rgla_guarantor.pse_rgla_guarantor import (
    EAD,
    LOAN_PSE_CQS2_REF,
    LOAN_PSE_CQS3_REF,
    LOAN_RGLA_DE_REF,
    LOAN_RGLA_GB_REF,
)


def _sa_config(regime: str) -> CalculationConfig:
    if regime == "b31":
        return CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.crr(
        reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.STANDARDISED
    )


def _irb_config(regime: str) -> CalculationConfig:
    if regime == "b31":
        return CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
    )


@pytest.fixture(scope="module")
def sa_results() -> dict[str, pl.DataFrame]:
    """The SA book's results frame under each regime."""
    return {
        regime: PipelineOrchestrator()
        .run_with_data(build_sa_bundle(), _sa_config(regime))
        .results.collect()
        for regime in ("crr", "b31")
    }


@pytest.fixture(scope="module")
def irb_results() -> dict[str, pl.DataFrame]:
    """The IRB book (US PSE guarantors: CQS2 flag null, CQS3 flag True) per regime."""
    out: dict[str, pl.DataFrame] = {}
    for regime in ("crr", "b31"):
        result = PipelineOrchestrator().run_with_data(
            build_irb_bundle(cqs2_flag=None, cqs3_flag=True), _irb_config(regime)
        )
        assert result.irb_results is not None, "IRB results must exist for the F-IRB borrower"
        out[regime] = result.irb_results.collect()
    return out


_GUARANTEED = sorted(loan for loan, (_o, g, *_r) in SA_SCENARIOS.items() if g is not None)
_MOVED = sorted(loan for loan, (*_x, rwa, pre) in SA_SCENARIOS.items() if rwa != pre)


class TestSAGuarantorJurisdictionGate:
    """SA book: every guarantee priced at the guarantor's Art. 116(5)-gated weight."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("loan", _GUARANTEED)
    def test_guarantor_rw(
        self, sa_results: dict[str, pl.DataFrame], regime: str, loan: str
    ) -> None:
        """
        Arrange: one GBP 1m loan per scenario, fully covered by one guarantor.
        Act:     the full SA pipeline under the named regime.
        Assert:  the guaranteed leg's guarantor_rw is the gated direct weight.
        """
        expected = SA_SCENARIOS[loan][2]

        row = get_guaranteed_row(sa_results[regime], loan)

        assert row["guarantor_rw"] == pytest.approx(expected, abs=1e-12), (
            f"{regime}/{loan}: guarantor_rw {row['guarantor_rw']} != {expected}"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("loan", sorted(SA_SCENARIOS))
    def test_rwa_final(self, sa_results: dict[str, pl.DataFrame], regime: str, loan: str) -> None:
        """
        Arrange: as above, plus one unguaranteed US PSE loan (the P1.252 direct path).
        Act:     the full SA pipeline.
        Assert:  total rwa_final per loan — 1,000,000 where the guarantee is declined
                 or prices at 100%, 200,000 where a permitted 20% applies.
        """
        expected = SA_SCENARIOS[loan][3]

        total = get_total_rwa(sa_results[regime], loan)

        assert total == pytest.approx(expected, rel=1e-9), (
            f"{regime}/{loan}: rwa_final {total:,.2f} != {expected:,.2f}"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("loan", _MOVED)
    def test_moved_loans_left_the_pre_fix_rwa(
        self, sa_results: dict[str, pl.DataFrame], regime: str, loan: str
    ) -> None:
        """
        Anti-confound: each gated loan moved off its pre-fix RWA, in the rule's direction.

        Arrange: the gated loans (L_US_NULL, L_NOCTRY_NULL up; L_US_CQS6 down).
        Act:     the full SA pipeline.
        Assert:  rwa_final differs from the pre-fix figure.
        """
        pre_fix = SA_SCENARIOS[loan][4]

        total = get_total_rwa(sa_results[regime], loan)

        assert total != pytest.approx(pre_fix, rel=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_cqs1_guarantee_declined_over_100pct_obligor(
        self, sa_results: dict[str, pl.DataFrame], regime: str
    ) -> None:
        """
        Arrange: L_US_NULL — a 100% obligor, a US CQS1 PSE guarantor with no flag.
        Act:     the full SA pipeline.
        Assert:  guarantor_rw 1.00 is not < 1.00, so the guarantee is not beneficial.
        """
        row = get_guaranteed_row(sa_results[regime], "L_US_NULL")

        assert row["pre_crm_risk_weight"] == pytest.approx(1.0)
        assert row["is_guarantee_beneficial"] is False

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_cqs6_guarantee_becomes_beneficial_over_150pct_obligor(
        self, sa_results: dict[str, pl.DataFrame], regime: str
    ) -> None:
        """
        Arrange: L_US_CQS6 — a 150% CQS6 obligor, a US CQS6 PSE guarantor with no flag.
        Act:     the full SA pipeline.
        Assert:  guarantor_rw 1.00 < 1.50, so the guarantee is beneficial (RWA-reducing).
        """
        row = get_guaranteed_row(sa_results[regime], "L_US_CQS6")

        assert row["pre_crm_risk_weight"] == pytest.approx(1.5)
        assert row["is_guarantee_beneficial"] is True

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_guarantor_flag_is_carried_on_the_output(
        self, sa_results: dict[str, pl.DataFrame], regime: str
    ) -> None:
        """
        Arrange: L_US_TRUE (flag True) and L_US_NULL (flag null) guarantors.
        Act:     the full SA pipeline.
        Assert:  guarantor_is_equivalent_jurisdiction carries the guarantor's own
                 flag — not the obligor's (L_US_NULL's obligor asserts True).
        """
        flag_true = get_guaranteed_row(sa_results[regime], "L_US_TRUE")
        flag_null = get_guaranteed_row(sa_results[regime], "L_US_NULL")

        assert flag_true["guarantor_is_equivalent_jurisdiction"] is True
        assert flag_null["guarantor_is_equivalent_jurisdiction"] is None


class TestIRBGuarantorJurisdictionGate:
    """IRB book: the RWSM leg of an F-IRB borrower prices the gated guarantor_rw_sa."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_non_equivalent_cqs2_pse_guarantor_substitutes_at_100pct(
        self, irb_results: dict[str, pl.DataFrame], regime: str
    ) -> None:
        """
        Arrange: F-IRB borrower (own RW > 100%), US CQS2 PSE guarantor, flag null.
        Act:     the full IRB pipeline.
        Assert:  guarantor_rw 1.00 (pre-fix 0.50); still beneficial, rwa_final = EAD x 1.00.
        """
        row = get_guaranteed_row(irb_results[regime], LOAN_PSE_CQS2_REF)

        assert row["guarantor_rw"] == pytest.approx(1.0, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(EAD * 1.0, rel=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_equivalent_cqs3_pse_guarantor_keeps_table_2a(
        self, irb_results: dict[str, pl.DataFrame], regime: str
    ) -> None:
        """
        Arrange: the same borrower, US CQS3 PSE guarantor with equivalence asserted.
        Act:     the full IRB pipeline.
        Assert:  Table 2A CQS3 50% — rwa_final = EAD x 0.50 (unchanged by the fix).
        """
        row = get_guaranteed_row(irb_results[regime], LOAN_PSE_CQS3_REF)

        assert row["guarantor_rw"] == pytest.approx(0.50, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(EAD * 0.50, rel=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        ("loan", "expected"), [(LOAN_RGLA_GB_REF, 0.20), (LOAN_RGLA_DE_REF, 1.00)]
    )
    def test_rgla_guarantors_unchanged(
        self, irb_results: dict[str, pl.DataFrame], regime: str, loan: str, expected: float
    ) -> None:
        """
        Arrange: the fixture's unrated RGLA guarantors (GB, DE).
        Act:     the full IRB pipeline.
        Assert:  the unrated RGLA fallback (GB 20%, other 100%) — no Art. 116(5) gate.
        """
        row = get_guaranteed_row(irb_results[regime], loan)

        assert row["guarantor_rw"] == pytest.approx(expected, abs=1e-12)
