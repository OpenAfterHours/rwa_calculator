"""
P1.273 CRR — Art. 199(7)/211: lease exposures treated as collateralised.

Scenario: £10m senior corporate F-IRB lease exposure secured by a £10m leased
asset (``other_physical``). Everything is held constant except the lessor's
Art. 211 attestation (``is_lease_collateral_attested``):

    crr_lease_attested    — attested   -> leased asset recognised, LGD* = 0.428571
                            (Art. 230(2) haircut 40%, OC=1.4×, LGDS 40%, LGDU 45%),
                            RWA falls.
    crr_lease_unattested  — null       -> the FCM gate zeroes effectively_secured,
                            LGD reverts to LGDU = 0.45 (Art. 161(1)(a)) — the
                            conservative pre-P1.273 lessor treatment.

is_eligible_irb_collateral is False in both, so the attestation is the ONLY lever:
recognition flows solely from the Art. 211 lease route.

References:
    - CRR Art. 199(7): lease exposures treated as collateralised per Art. 211.
    - CRR Art. 211: requirements for treating lease exposures as collateralised.
    - CRR Art. 230: F-IRB Foundation Collateral Method / OC ratios.
    - CRR Art. 161(1)(a): LGDU senior unsecured corporate = 45%.
    - IMPLEMENTATION_PLAN.md: P1.273.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows, first
from tests.fixtures.p1_273.p1_273 import SCENARIOS, build_p1_273_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_273_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.crr(
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


class TestP1273CrrLeaseCollateral:
    """CRR: an Art. 211-attested leased asset reduces F-IRB LGD via the FCM."""

    def test_attested_lease_recognised(self) -> None:
        """Control: attested lease -> LGD* = 0.428571 (leased asset recognised)."""
        assert _lgd("crr_lease_attested") == pytest.approx(
            SCENARIOS["crr_lease_attested"].expected_lgd, abs=1e-3
        )

    def test_unattested_lease_reverts_to_lgdu(self) -> None:
        """LOAD-BEARING: no attestation -> LGD reverts to LGDU = 0.45.

        The Art. 199 FCM gate zeroes effectively_secured for the unattested leased
        asset, collapsing the secured LGD to the senior unsecured supervisory value.
        """
        assert _lgd("crr_lease_unattested") == pytest.approx(
            SCENARIOS["crr_lease_unattested"].expected_lgd, abs=1e-3
        )

    def test_attestation_changes_rwa(self) -> None:
        """The attestation alone must lower RWA (guards against a no-op route)."""
        assert _rwa("crr_lease_attested") < _rwa("crr_lease_unattested")
