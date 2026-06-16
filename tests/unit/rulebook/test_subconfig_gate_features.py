"""
Pins for the S11d sub-config regime-GATE migration.

Phase 5 S11d moves the three regime-derived ``enabled`` gates off the mixed
sub-config dataclasses (``OutputFloorConfig`` / ``EquityTransitionalConfig`` /
``PostModelAdjustmentConfig``) onto the rulepack as Features. The engine sources
the on/off gate from these Features (engine/aggregator, engine/stages/calc,
engine/sa/calculator, engine/equity/calculator, engine/irb/adjustments); the
regulatory VALUES (floor pct + transitional schedule, equity transitional RW
schedule, mortgage RW floor) and the firm ELECTIONS (institution_type /
reporting_basis, opt_out, PMA scalars) stay config-side until the S11e carve.

Byte-identity holds because every config construction site sets ``enabled``
consistent with its regime (CRR factories disable; B31 factories enable), so the
Feature value equals the regime-derived ``enabled`` flag at every read site.

References:
- PRA PS1/26 Art. 92 / 92(5): aggregate output floor (Basel 3.1 only).
- PRA PS1/26 Rules 4.1-4.10: equity transitional regime (Basel 3.1 only).
- PRA PS1/26 Art. 153(5A) / 154(4A) / 158(6A): IRB post-model adjustments.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.domain.enums import InstitutionType, ReportingBasis
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_GATE_MATRIX = (
    ("output_floor", False, True),
    ("equity_transitional", False, True),
    ("post_model_adjustments", False, True),
)


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _GATE_MATRIX)
def test_subconfig_gate_feature_polarity(name: str, crr_enabled: bool, b31_enabled: bool) -> None:
    # Arrange / Act / Assert — each gate is regime-derived: off under CRR, on under B31.
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled


def test_output_floor_gate_matches_config_enabled() -> None:
    """The output_floor Feature mirrors OutputFloorConfig.enabled regime-for-regime."""
    from rwa_calc.contracts.config import OutputFloorConfig

    assert _CRR_PACK.feature("output_floor") is OutputFloorConfig.crr().enabled
    assert _B31_PACK.feature("output_floor") is OutputFloorConfig.basel_3_1().enabled


def test_is_entity_in_scope_is_enabled_independent() -> None:
    """is_entity_in_scope is the firm-election half of is_floor_applicable.

    It ignores the enabled gate (now Feature-sourced engine-side) and answers
    only the Art. 92 para 2A(a) entity-scope question.
    """
    from rwa_calc.contracts.config import OutputFloorConfig

    # CRR floor is disabled, but the (unset) entity is still "in scope" by the
    # backward-compatible default — the gate is what makes it inapplicable.
    crr_floor = OutputFloorConfig.crr()
    assert crr_floor.is_entity_in_scope() is True
    assert crr_floor.is_floor_applicable() is False  # enabled=False short-circuits

    # B31 default (no entity type set) → in scope and applicable.
    b31_floor = OutputFloorConfig.basel_3_1()
    assert b31_floor.is_entity_in_scope() is True
    assert b31_floor.is_floor_applicable() is True


def test_is_entity_in_scope_honours_art_92_2a_carveouts() -> None:
    """An Art. 92 para 2A(b)-(d) exempt entity is out of scope even when enabled."""
    from rwa_calc.contracts.config import OutputFloorConfig

    in_scope = OutputFloorConfig.basel_3_1(
        institution_type=InstitutionType.STANDALONE_UK,
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )
    assert in_scope.is_entity_in_scope() is True
    assert in_scope.is_floor_applicable() is True

    exempt = OutputFloorConfig.basel_3_1(
        institution_type=InstitutionType.RING_FENCED_BODY,
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )
    assert exempt.is_entity_in_scope() is False
    assert exempt.is_floor_applicable() is False

    # is_floor_applicable == enabled AND is_entity_in_scope (the refactor identity).
    assert exempt.is_floor_applicable() == (exempt.enabled and exempt.is_entity_in_scope())
