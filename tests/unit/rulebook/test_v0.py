"""
Tests for the RulepackV0 facade's Phase 5 S2 pack-build seam.

Verifies that ``RulepackV0.from_config`` resolves and attaches a
content-hashed ``ResolvedRulepack`` for the run's (regime, reporting_date),
that the resolved pack agrees with the config it was built from, and that
the existing regime facade is unchanged.

References:
- docs/plans/target-architecture-migration.md (Phase 5 — S2 pack-build seam).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.rulebook.resolve import ResolvedRulepack
from rwa_calc.rulebook.v0 import RulepackV0

_REPORTING_DATE = date(2027, 1, 1)


def test_from_config_attaches_resolved_pack_for_crr() -> None:
    # Arrange
    config = CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    # Act
    rulepack = RulepackV0.from_config(config)
    # Assert
    assert isinstance(rulepack.pack, ResolvedRulepack)
    assert rulepack.pack.regime_id == "crr"


def test_from_config_attaches_resolved_pack_for_basel_3_1() -> None:
    # Arrange
    config = CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
    # Act
    rulepack = RulepackV0.from_config(config)
    # Assert
    assert rulepack.pack.regime_id == "b31"


def test_pack_scaling_factor_matches_crr_config() -> None:
    # Arrange
    config = CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    # Act
    rulepack = RulepackV0.from_config(config)
    # Assert — the pack value agrees with the config it was resolved from
    assert rulepack.pack.scalar("irb_scaling_factor") == Decimal("1.06")
    assert float(rulepack.pack.scalar("irb_scaling_factor")) == float(config.scaling_factor)


def test_pack_scaling_factor_matches_basel_3_1_config() -> None:
    # Arrange
    config = CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
    # Act
    rulepack = RulepackV0.from_config(config)
    # Assert
    assert rulepack.pack.scalar("irb_scaling_factor") == Decimal("1.0")
    assert float(rulepack.pack.scalar("irb_scaling_factor")) == float(config.scaling_factor)


def test_pack_id_carries_reporting_date() -> None:
    # Arrange
    config = CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
    # Act
    rulepack = RulepackV0.from_config(config)
    # Assert
    assert rulepack.pack.id == "b31@2027-01-01"
    assert rulepack.pack.content_hash  # non-empty digest


def test_regime_facade_unchanged() -> None:
    # Arrange
    crr = RulepackV0.from_config(CalculationConfig.crr(reporting_date=_REPORTING_DATE))
    b31 = RulepackV0.from_config(CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE))
    # Assert — the back-compat facade still derives from config, unchanged
    assert crr.is_crr is True
    assert crr.is_basel_3_1 is False
    assert b31.is_basel_3_1 is True
    assert b31.scaling_factor == 1.0
