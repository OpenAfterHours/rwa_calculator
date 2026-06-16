"""
Pins for the S7b equity regime Features.

Phase 5 S7b moved the equity calculator's regime branches off
``config.is_basel_3_1`` and onto pack Features (the RW VALUES they gate stay in
``data/tables/{crr,b31}_equity_rw.py``):

- ``equity_irb_approaches_available`` — under CRR the IRB equity approaches
  (Art. 155(2) IRB Simple / Art. 155(3) PD-LGD) are available; Basel 3.1 removes
  them (CRE20.58-62), so all equity uses SA. Gates ``_determine_approach`` and
  the COREP transitional-approach label in ``engine/equity/calculator.py``.
- ``equity_revised_sa_risk_weights`` — selects the CRR Art. 133(2) 100%-flat
  SA-equity RW method vs the Basel 3.1 Art. 133(3)-(5) 250%/400%/150% method.

The CIU look-through CQS table selection reuses the SA Feature
``sa_revised_risk_weight_tables`` (pinned in test_sa_risk_weight_features.py).

Each Feature's value mirrors ``config.is_basel_3_1`` per regime, so this pin is
the byte-identical-parity contract.

References:
- CRR Art. 133 / Art. 155: SA + IRB equity approaches.
- PRA PS1/26 Art. 133 / BCBS CRE20.58-62: Basel 3.1 equity (SA-only, revised RW).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("equity_irb_approaches_available", True, False),
    ("equity_revised_sa_risk_weights", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_equity_feature_values_per_regime(name: str, crr_enabled: bool, b31_enabled: bool) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
