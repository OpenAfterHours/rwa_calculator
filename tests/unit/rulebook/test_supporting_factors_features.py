"""
Pins for the S11 supporting-factors regime migration.

Phase 5 S11 moves the CRR Art. 501/501a supporting factors off
``config.supporting_factors`` onto the rulepack:

- the regime ON/OFF gate -> pack Feature ``supporting_factors`` (CRR enabled /
  Basel 3.1 disabled);
- the factor multipliers (SME 0.7619 / 0.85, infrastructure 0.75) -> pack
  FormulaParams ``supporting_factors_values``.

The S11e carve then deleted the legacy ``contracts/config.py::SupportingFactors``
dataclass, so these pins assert the pack-authored values against the canonical
regulatory multipliers directly.

References:
- CRR Art. 501 / 501a: SME / infrastructure supporting factors.
- PRA PS1/26: supporting factors removed under Basel 3.1 (all 1.0).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# Canonical CRR multipliers (were SupportingFactors.crr() before the carve);
# Basel 3.1 removes the factors (all 1.0).
_CRR_VALUES = {
    "sme_factor_under_threshold": Decimal("0.7619"),
    "sme_factor_above_threshold": Decimal("0.85"),
    "infrastructure_factor": Decimal("0.75"),
}
_B31_VALUES = {
    "sme_factor_under_threshold": Decimal("1.0"),
    "sme_factor_above_threshold": Decimal("1.0"),
    "infrastructure_factor": Decimal("1.0"),
}


def test_supporting_factors_feature_per_regime() -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature("supporting_factors") is True
    assert _B31_PACK.feature("supporting_factors") is False


def test_supporting_factors_values_crr() -> None:
    assert dict(_CRR_PACK.formula("supporting_factors_values").params) == _CRR_VALUES


def test_supporting_factors_values_b31() -> None:
    assert dict(_B31_PACK.formula("supporting_factors_values").params) == _B31_VALUES
