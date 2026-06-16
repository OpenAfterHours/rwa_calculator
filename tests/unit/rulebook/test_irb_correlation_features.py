"""
Pin for the S8c shared IRB SME-correlation regime Feature.

Phase 5 S8c moved the SME-correlation regime selector off
``config.is_basel_3_1`` and onto one cited pack Feature, atomically across all
five call sites that feed the shared ``_correlation_expr_from_pd`` /
``_polars_correlation_expr`` helpers (engine/irb/formulas.py:apply_irb_formulas,
engine/irb/transforms.py:calculate_correlation + apply_all_formulas,
engine/irb/guarantee.py NBD floor, engine/equity/calculator.py PD/LGD):

- ``irb_correlation_sme_gbp_native`` selects the Basel 3.1 GBP-native SME
  turnover basis (Art. 153(4)) vs the CRR EUR-conversion basis. The shared
  helpers keep their ``is_b31: bool`` param (fed from the Feature at the call
  sites); the FX-derived turnover threshold VALUES they read (EUR 50m / GBP 44m /
  eur_gbp_rate) stay config-threaded → S11.

The Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 153(4) (GBP→EUR turnover conversion) / PRA PS1/26 Art. 153(4)
  (GBP-native turnover thresholds).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("irb_correlation_sme_gbp_native", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_irb_correlation_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
