"""
P1.235 CRR — Art. 199(2): FIRB Foundation Collateral Method eligibility gate.

Scenario: £10m senior corporate F-IRB exposure with £10m real-estate collateral.
Everything is held constant across the two scenarios except the institution's
``is_eligible_irb_collateral`` attestation flag:

    crr_attested_re   (flag True)  -> collateral recognised, LGD* = 0.378571
    crr_unattested_re (flag False) -> Art. 199(2) gate zeroes effectively_secured,
                                      LGD reverts to LGDU = 0.45 (Art. 161(1)(a)).

The attested case reproduces the P1.190 crr_full_re hand-calc (OC=1.4×, LGDS=35%,
LGDU=45%); the flag is the only lever that changes the outcome.

References:
    - CRR Art. 199(2): eligible IRB collateral recognition conditions (attested).
    - CRR Art. 230: F-IRB Foundation Collateral Method / OC ratios.
    - CRR Art. 161(1)(a): LGDU senior unsecured corporate = 45%.
    - IMPLEMENTATION_PLAN.md: P1.235.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_235_pipeline_helpers import build_p1_235_bundle, find_loan_rows, first
from tests.fixtures.p1_235.p1_235 import SCENARIOS

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 6, 30)


def _run(scenario_label: str) -> list[dict]:
    s = SCENARIOS[scenario_label]
    bundle = build_p1_235_bundle(scenario_label, s.fac_ref, s.loan_ref)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    rows = find_loan_rows(result, s.loan_ref)
    assert rows, f"P1.235 {scenario_label}: no result rows — F-IRB routing failed."
    return rows


class TestP1235CrrEligibilityGate:
    """CRR: only attested RE collateral reduces F-IRB LGD (Art. 199(2))."""

    def test_attested_re_recognised(self) -> None:
        """Control: flag True -> LGD* = 0.378571 (collateral recognised)."""
        rows = _run("crr_attested_re")
        lgd = first(rows, "lgd_floored")
        assert lgd == pytest.approx(SCENARIOS["crr_attested_re"].expected_lgd, abs=1e-3)

    def test_unattested_re_reverts_to_lgdu(self) -> None:
        """LOAD-BEARING: flag False -> LGD reverts to LGDU = 0.45.

        The Art. 199(2) gate zeroes effectively_secured for the unattested RE
        collateral, so the secured LGD substitution collapses to the senior
        unsecured supervisory value.
        """
        rows = _run("crr_unattested_re")
        lgd = first(rows, "lgd_floored")
        assert lgd == pytest.approx(SCENARIOS["crr_unattested_re"].expected_lgd, abs=1e-3)

    def test_attestation_flag_changes_outcome(self) -> None:
        """The attestation flag alone must change the LGD (guards against a no-op gate)."""
        attested = first(_run("crr_attested_re"), "lgd_floored")
        unattested = first(_run("crr_unattested_re"), "lgd_floored")
        assert unattested > attested
