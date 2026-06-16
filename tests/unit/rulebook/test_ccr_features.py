"""
Pin for the S9a SA-CCR transitional-alpha regime Feature.

Phase 5 S9a moved the SA-CCR transitional alpha add-on regime gate off
``run_config.is_basel_3_1`` and onto one cited pack Feature read at the CCR
stage adapter (engine/stages/ccr.py). The add-on branch in
engine/ccr/pipeline_adapter.py keeps its ``is_basel_3_1: bool`` plumbing
param (Option B); only the stage-level regime read moves to the pack:

- ``ccr_transitional_alpha_addon_applicable`` gates the PRA PS1/26
  Art. 274(2A) transitional alpha add-on (phase-in 2027-2029) for legacy
  CVA-exempt non-financial counterparties carved out to α=1.0. CRR has no
  such add-on. The phase fractions and the 0.4 alpha uplift stay engine /
  data constants (not FX-derived).

The Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 274 (no transitional add-on) / PRA PS1/26 Art. 274(2A).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("ccr_transitional_alpha_addon_applicable", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_ccr_feature_values_per_regime(name: str, crr_enabled: bool, b31_enabled: bool) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
