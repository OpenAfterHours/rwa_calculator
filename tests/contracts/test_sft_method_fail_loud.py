"""Fail-loud contract for unimplemented SFT EAD methods (Phase 3).

The SFT/FCCM separation (docs/plans/sft-fccm-separation.md) reserves the
``"var"`` (CRR Art. 221) and ``"imm"`` (CRR Art. 283) SFT EAD methods on
``SFTConfig.method`` but only implements ``"fccm"`` (Art. 220-223). Prior to
Phase 3 the SA-CCR pipeline adapter silently dropped all SFT rows when the
method was anything other than ``"fccm"`` (returning derivative rows only).
This module pins the corrected fail-loud behaviour: ``ccr_rows_to_exposures``
must raise ``NotImplementedError`` when handed a reserved method.

References:
    - CRR Art. 221 — VaR-based SFT method (reserved, unimplemented).
    - CRR Art. 283 — IMM SFT method (reserved, unimplemented).
    - CRR Art. 271(2) — SFT EAD routing.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.fixtures.ccr.golden_ccr_a11_a12 import _build_ccr_a11_raw_ccr_bundle

from rwa_calc.contracts.config import CCRConfig
from rwa_calc.engine.ccr.pipeline_adapter import ccr_rows_to_exposures

_REPORTING_DATE = date(2026, 6, 30)


@pytest.mark.parametrize("reserved_method", ["var", "imm"])
def test_reserved_sft_method_raises_not_implemented(reserved_method: str) -> None:
    """A reserved SFT method must fail loud instead of dropping SFT rows.

    The CCR-A11 bundle carries one ``transaction_type == "sft"`` trade. Before
    Phase 3, a non-"fccm" method silently returned derivative-only rows (zero
    SFT EAD). Now ``ccr_rows_to_exposures`` must raise NotImplementedError.
    """
    # Arrange
    raw_ccr = _build_ccr_a11_raw_ccr_bundle()

    # Act + Assert
    with pytest.raises(NotImplementedError, match=reserved_method):
        ccr_rows_to_exposures(
            raw_ccr,
            CCRConfig(),
            _REPORTING_DATE,
            sft_method=reserved_method,
        ).collect()


def test_fccm_sft_method_does_not_raise() -> None:
    """The default "fccm" method still routes SFT rows through FCCM (no raise)."""
    # Arrange
    raw_ccr = _build_ccr_a11_raw_ccr_bundle()

    # Act
    result = ccr_rows_to_exposures(
        raw_ccr,
        CCRConfig(),
        _REPORTING_DATE,
        sft_method="fccm",
    ).collect()

    # Assert — the SFT row reached the synthetic-exposure output.
    assert "ccr__NS_SFT_001" in result["exposure_reference"].to_list()
