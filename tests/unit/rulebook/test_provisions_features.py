"""
Pin for the S9e provisions SA-CCF-table regime Feature.

Phase 5 S9e moved the SA-CCF table selection used as the pro-rata
provision-weighting basis off ``config.is_basel_3_1`` and onto one cited
pack Feature, threaded into engine/crm/provisions.py::resolve_provisions
from the CRM processor. ``_resolve_provisions_multi_level`` and the
``sa_ccf_expression`` it calls keep their ``is_basel_3_1`` bool plumbing
params (Option B); only the regime read moves to the pack:

- ``sa_revised_ccf_table`` selects the Basel 3.1 SA CCF table (Table A1:
  OC 40%, LR 10%) vs the CRR Annex I table. This is DISTINCT from
  ``firb_uses_sa_ccf`` (S9c), which decides WHETHER F-IRB uses SA CCFs;
  this Feature selects WHICH SA CCF table. The CCF table VALUES stay
  static data-layer constants (not FX-derived).

The Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 111 Annex I SA CCF table / PRA PS1/26 Art. 111(1) Table A1.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("sa_revised_ccf_table", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_provisions_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
