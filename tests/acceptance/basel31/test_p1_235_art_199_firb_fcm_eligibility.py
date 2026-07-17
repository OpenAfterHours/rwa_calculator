"""
P1.235 Basel 3.1 — Art. 199(2): FIRB Foundation Collateral Method eligibility gate.

Scenario: £10m senior corporate F-IRB exposure with £10m real-estate collateral.
Everything is held constant across the two scenarios except the institution's
``is_eligible_irb_collateral`` attestation flag:

    b31_attested_re   (flag True)  -> collateral recognised, LGD* = 0.2800
    b31_unattested_re (flag False) -> Art. 199(2) gate zeroes effectively_secured,
                                      LGD reverts to LGDU = 0.40 (PS1/26 Art. 161(1)(aa)).

The attested case reproduces the P1.190 b31_full_re hand-calc (continuous Art. 230(1)
formula, LGDU=40% non-FSE corporate); the flag is the only lever that changes it.

References:
    - PS1/26 Art. 199(2): eligible IRB collateral recognition conditions (attested).
    - PS1/26 Art. 230(1): F-IRB continuous LGD* formula.
    - PS1/26 Art. 161(1)(aa): LGDU senior unsecured non-FSE corporate = 40%.
    - IMPLEMENTATION_PLAN.md: P1.235.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_235_pipeline_helpers import build_p1_235_bundle, find_loan_rows, first
from tests.fixtures.p1_235.p1_235 import SCENARIOS

REPORTING_DATE = date(2030, 6, 30)


def _run(scenario_label: str) -> list[dict]:
    s = SCENARIOS[scenario_label]
    bundle = build_p1_235_bundle(scenario_label, s.fac_ref, s.loan_ref)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    rows = find_loan_rows(result, s.loan_ref)
    assert rows, f"P1.235 {scenario_label}: no result rows — F-IRB routing failed."
    return rows


class TestP1235B31EligibilityGate:
    """Basel 3.1: only attested RE collateral reduces F-IRB LGD (Art. 199(2))."""

    def test_attested_re_recognised(self) -> None:
        """Control: flag True -> LGD* = 0.2800 (collateral recognised)."""
        rows = _run("b31_attested_re")
        lgd = first(rows, "lgd_floored")
        assert lgd == pytest.approx(SCENARIOS["b31_attested_re"].expected_lgd, abs=1e-3)

    def test_unattested_re_reverts_to_lgdu(self) -> None:
        """LOAD-BEARING: flag False -> LGD reverts to LGDU = 0.40.

        The Art. 199(2) gate zeroes effectively_secured for the unattested RE
        collateral, so the secured LGD substitution collapses to the senior
        unsecured supervisory value (PS1/26 Art. 161(1)(aa) non-FSE corporate).
        """
        rows = _run("b31_unattested_re")
        lgd = first(rows, "lgd_floored")
        assert lgd == pytest.approx(SCENARIOS["b31_unattested_re"].expected_lgd, abs=1e-3)

    def test_attestation_flag_changes_outcome(self) -> None:
        """The attestation flag alone must change the LGD (guards against a no-op gate)."""
        attested = first(_run("b31_attested_re"), "lgd_floored")
        unattested = first(_run("b31_unattested_re"), "lgd_floored")
        assert unattested > attested
