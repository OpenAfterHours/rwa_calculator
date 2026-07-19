"""
P1.273 Basel 3.1 — Art. 199(7)/211: lease exposures treated as collateralised.

Scenario: £10m senior corporate F-IRB lease exposure secured by a £10m leased
asset (``other_physical``). Everything is held constant except the lessor's
Art. 211 attestation (``is_lease_collateral_attested``):

    b31_lease_attested    — attested   -> leased asset recognised, LGD* = 0.31,
                            RWA falls.
    b31_lease_unattested  — null       -> the FCM gate zeroes effectively_secured,
                            LGD reverts to LGDU = 0.40 (Art. 161(1)(aa) non-FSE) —
                            the conservative pre-P1.273 lessor treatment.

PS1/26 retains CRR Art. 199(7) and Art. 211 verbatim; is_eligible_irb_collateral
is False in both, so the attestation is the ONLY lever.

References:
    - PS1/26 Art. 199(7): lease exposures treated as collateralised per Art. 211.
    - PS1/26 Art. 211: requirements for treating lease exposures as collateralised.
    - PS1/26 Art. 230: F-IRB Foundation Collateral Method.
    - PS1/26 Art. 161(1)(aa): LGDU senior unsecured non-FSE corporate = 40%.
    - IMPLEMENTATION_PLAN.md: P1.273.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows, first
from tests.fixtures.p1_273.p1_273 import SCENARIOS, build_p1_273_bundle

REPORTING_DATE = date(2030, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_273_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _lgd(scenario_label: str) -> float:
    rows = find_loan_rows(_run(scenario_label), SCENARIOS[scenario_label].loan_ref)
    assert rows, f"P1.273 {scenario_label}: no result rows — F-IRB routing failed."
    return first(rows, "lgd_floored")


def _rwa(scenario_label: str) -> float:
    rows = find_loan_rows(_run(scenario_label), SCENARIOS[scenario_label].loan_ref)
    assert rows, f"P1.273 {scenario_label}: no result rows."
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


class TestP1273B31LeaseCollateral:
    """B31: an Art. 211-attested leased asset reduces F-IRB LGD via the FCM."""

    def test_attested_lease_recognised(self) -> None:
        """Control: attested lease -> LGD* = 0.31 (leased asset recognised)."""
        assert _lgd("b31_lease_attested") == pytest.approx(
            SCENARIOS["b31_lease_attested"].expected_lgd, abs=1e-3
        )

    def test_unattested_lease_reverts_to_lgdu(self) -> None:
        """LOAD-BEARING: no attestation -> LGD reverts to LGDU = 0.40 (non-FSE)."""
        assert _lgd("b31_lease_unattested") == pytest.approx(
            SCENARIOS["b31_lease_unattested"].expected_lgd, abs=1e-3
        )

    def test_attestation_changes_rwa(self) -> None:
        """The attestation alone must lower RWA (guards against a no-op route)."""
        assert _rwa("b31_lease_attested") < _rwa("b31_lease_unattested")
