"""
Pins for the S6a Standardised-Approach risk-weight regime Features.

Phase 5 S6a moved the SA base risk-weight table selection off
``config.is_basel_3_1`` and onto pack Features (the table VALUES they gate stay
in ``data/tables/{crr,b31}_risk_weights.py``):

- ``sa_revised_risk_weight_tables`` gates the combined-CQS table selection in
  ``engine/sa/risk_weights.py::_prepare_risk_weight_lookup`` (CRR Art. 112-134
  tables vs the PS1/26 revised set) — and, from S6c, the shared guarantor-RW
  builder.
- ``sa_revised_risk_weight_overrides`` (S10a) gates the top-level override-LADDER
  dispatch in ``engine/sa/risk_weights.py::apply_risk_weights`` — the whole CRR
  ``_apply_crr_risk_weight_overrides`` vs Basel 3.1 ``_apply_b31_risk_weight_overrides``
  when/then sequence applied on top of the base CQS join (distinct from the
  base-table Feature above).
- ``sa_sl_inferred_rating_disapplied`` gates the PS1/26 Art. 139(2B)
  non-issue-specific-ECAI CQS-nulling for specialised lending.
- ``sa_revised_defaulted_treatment`` gates the Art. 127 defaulted-RW regime
  block (Basel 3.1 gross-outstanding denominator + the Art. 127(3) residential-RE
  non-income flat-100% carve-out, vs the CRR pre-provision denominator).
- ``sa_currency_mismatch_multiplier`` gates the PS1/26 Art. 123B 1.5x retail/RE
  currency-mismatch multiplier (Basel-3.1-only).
- ``sa_due_diligence_override`` gates the PS1/26 Art. 110A due-diligence RW
  override (Basel-3.1-only).

Each Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract: a pack typo
fails here, before the engine-level behaviour and the 10k stress parity gate.

References:
- CRR Art. 112-134 / PRA PS1/26 Art. 122(2): SA risk-weight tables.
- PRA PS1/26 Art. 139(2B): non-issue-specific ECAI assessments disapplied for SL.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("sa_revised_risk_weight_tables", False, True),
    ("sa_revised_risk_weight_overrides", False, True),
    ("sa_sl_inferred_rating_disapplied", False, True),
    ("sa_revised_defaulted_treatment", False, True),
    ("sa_currency_mismatch_multiplier", False, True),
    ("sa_due_diligence_override", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_sa_risk_weight_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
