"""
CRR — the on-B/S netting perimeter is the netting AGREEMENT, not the counterparty.

Scenario: a £200k deposit (negative-drawn loan) and a £1m loan share netting
agreement AGR1. Only the loan's counterparty differs:

    crr_same_cp  — loan owed by the deposit's counterparty  -> nets, RWA £800k
    crr_cross_cp — loan owed by a DIFFERENT counterparty
                   under the SAME agreement                 -> nets, RWA £800k
                   plus one CRM016 audit-trail WARNING recording the applied
                   cross-counterparty offset

This REVERSES the earlier P1.238 reading (which keyed netting pools on
(agreement, currency, counterparty) and refused the cross-counterparty offset)
by operator decision dated 2026-09-04. Art. 195/205(a)/219 describe netting of
reciprocal cash balances and the drawn-on-drawn mechanics without confining the
perimeter to a single counterparty pair; enforceability against every party to
the agreement (Art. 205(a)) is what CRM016 now flags for evidencing.

The behaviour is gated by the cited pack Feature
``on_bs_netting_perimeter_is_agreement``, enabled under both regimes. The
Feature-disabled control below injects a pack with it flipped off and expects
the pre-reversal £1m — so a green suite cannot be produced by a Feature that
does nothing.

References:
    - CRR Art. 195: on-B/S netting of reciprocal balances.
    - CRR Art. 205(a): enforceability against all parties.
    - CRR Art. 219: drawn-on-drawn cash netting.
    - CRR Art. 122: unrated corporate 100% risk weight.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_238.p1_238 import (
    RWA_NO_NETTING,
    RWA_SAME_CP_NETTED,
    SCENARIOS,
    build_p1_238_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CROSS_COUNTERPARTY_NETTING
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.model import Citation, Feature

REPORTING_DATE = date(2026, 6, 30)
NETTING_PERIMETER_FEATURE = "on_bs_netting_perimeter_is_agreement"


def _config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _run(scenario_label: str):
    bundle = build_p1_238_bundle([scenario_label], REPORTING_DATE)
    return PipelineOrchestrator().run_with_data(bundle, _config())


def _run_perimeter_disabled(scenario_label: str):
    """Run the scenario with the agreement-perimeter Feature flipped off."""
    config = _config()
    disabled = RulepackV0.from_config(config).pack.with_overrides(
        **{
            NETTING_PERIMETER_FEATURE: Feature(
                name=NETTING_PERIMETER_FEATURE,
                enabled=False,
                citation=Citation("CRR", "195", "agreement perimeter disabled for test"),
            )
        }
    )
    bundle = build_p1_238_bundle([scenario_label], REPORTING_DATE)
    return PipelineOrchestrator().run_with_data(
        bundle, config, rulepack=RulepackV0.from_resolved(config, disabled)
    )


def _loan_rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"no result rows for {loan_ref} - the loan never reached the output"
    assert all(r.get("rwa_final") is not None for r in rows), (
        f"{loan_ref} published a null rwa_final; a null and a zero are different claims"
    )
    return sum(r["rwa_final"] for r in rows)


def _crm016(result) -> list:
    return [e for e in result.errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]


def _assert_scenarios_are_adequate() -> None:
    """C11 adequacy: the two scenarios must actually differ in counterparty."""
    same = SCENARIOS["crr_same_cp"]
    cross = SCENARIOS["crr_cross_cp"]
    assert same.deposit_cp == same.loan_cp, (
        "the same_cp control does not share a counterparty, so it is not a control"
    )
    assert cross.deposit_cp != cross.loan_cp, (
        "the cross_cp scenario's legs share a counterparty, so the agreement "
        "perimeter and the counterparty perimeter agree and it proves nothing"
    )
    assert RWA_SAME_CP_NETTED != RWA_NO_NETTING, (
        "the netted and un-netted expectations are equal, so no assertion below "
        "can distinguish a netted run from an un-netted one"
    )


class TestCrrAgreementPerimeterNetting:
    """CRR: the agreement reference alone bounds on-B/S netting."""

    def test_same_counterparty_loan_nets(self) -> None:
        """Control: same-counterparty loan nets the £200k deposit → RWA £800k."""
        # Arrange
        _assert_scenarios_are_adequate()

        # Act
        result = _run("crr_same_cp")

        # Assert
        assert _loan_rwa(result, SCENARIOS["crr_same_cp"].loan_ref) == pytest.approx(
            RWA_SAME_CP_NETTED, rel=1e-3
        )
        assert _crm016(result) == []

    def test_cross_counterparty_loan_nets_under_shared_agreement(self) -> None:
        """LOAD-BEARING: a different-counterparty loan under AGR1 nets → RWA £800k."""
        # Arrange
        _assert_scenarios_are_adequate()

        # Act
        result = _run("crr_cross_cp")

        # Assert
        assert _loan_rwa(result, SCENARIOS["crr_cross_cp"].loan_ref) == pytest.approx(
            RWA_SAME_CP_NETTED, rel=1e-3
        )

    def test_cross_counterparty_emits_crm016_audit_record(self) -> None:
        """The spanning agreement raises exactly one CRM016 - and still nets.

        CRM016 stays a WARNING (``ErrorSeverity`` has no INFO level) and keeps its
        Art. 195 reference, but it records an APPLIED offset that needs Art. 205(a)
        enforceability evidence - so the message must not call it "disallowed", and
        the same run must show the netted RWA.
        """
        # Arrange
        scenario = SCENARIOS["crr_cross_cp"]

        # Act
        result = _run("crr_cross_cp")

        # Assert
        warnings = _crm016(result)
        assert len(warnings) == 1
        assert warnings[0].regulatory_reference == "CRR Art. 195"
        assert "disallowed" not in warnings[0].message.lower(), (
            f"CRM016 still describes the offset as refused: {warnings[0].message!r}"
        )
        assert scenario.agreement_ref in warnings[0].message, (
            f"CRM016 does not name {scenario.agreement_ref!r}, so the audit record "
            f"cannot be attributed to the agreement it describes: "
            f"{warnings[0].message!r}"
        )
        assert "across 2 counterparties" in warnings[0].message, (
            f"CRM016 does not say HOW MANY counterparties the agreement spans; the "
            f"count is what scopes the Art. 205(a) enforceability evidence: "
            f"{warnings[0].message!r}"
        )
        assert _loan_rwa(result, scenario.loan_ref) == pytest.approx(
            RWA_SAME_CP_NETTED, rel=1e-3
        ), "CRM016 fired but the offset was not applied"

    def test_cross_equals_same(self) -> None:
        """The counterparty split alone must NOT change the loan's RWA."""
        # Act
        cross = _loan_rwa(_run("crr_cross_cp"), SCENARIOS["crr_cross_cp"].loan_ref)
        same = _loan_rwa(_run("crr_same_cp"), SCENARIOS["crr_same_cp"].loan_ref)

        # Assert
        assert cross == pytest.approx(same, rel=1e-3)
        assert cross == pytest.approx(RWA_SAME_CP_NETTED, rel=1e-3)

    def test_feature_disabled_restores_no_cross_counterparty_netting(self) -> None:
        """Feature off → the cross-counterparty loan keeps its full £1m RWA.

        This is what stops the tests above passing under a Feature that does
        nothing (LESSONS C1.11): the disabled pack must produce a DIFFERENT
        number from the default pack on identical input.
        """
        # Arrange
        _assert_scenarios_are_adequate()

        # Act
        disabled = _loan_rwa(
            _run_perimeter_disabled("crr_cross_cp"), SCENARIOS["crr_cross_cp"].loan_ref
        )
        default = _loan_rwa(_run("crr_cross_cp"), SCENARIOS["crr_cross_cp"].loan_ref)

        # Assert
        assert disabled == pytest.approx(RWA_NO_NETTING, rel=1e-3)
        assert default == pytest.approx(RWA_SAME_CP_NETTED, rel=1e-3)

    def test_feature_disabled_leaves_same_counterparty_netting_intact(self) -> None:
        """Feature off → the same-counterparty loan still nets to £800k."""
        # Act
        result = _run_perimeter_disabled("crr_same_cp")

        # Assert
        assert _loan_rwa(result, SCENARIOS["crr_same_cp"].loan_ref) == pytest.approx(
            RWA_SAME_CP_NETTED, rel=1e-3
        )
