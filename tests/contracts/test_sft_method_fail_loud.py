"""Fail-loud contract for unimplemented SFT EAD methods (Phase 3 / Phase 6).

The SFT/FCCM separation (docs/plans/sft-fccm-separation.md) reserves the
``"var"`` (CRR Art. 221) and ``"imm"`` (CRR Art. 283) SFT EAD methods on
``SFTConfig.method`` but only implements ``"fccm"`` (Art. 220-223). A reserved
method must fail loud (``NotImplementedError``) rather than silently dropping all
SFT rows (which would under-report exposure).

Phase 6 flipped the SFT source: SFTs now arrive via ``RawDataBundle.sft`` and are
priced by the peer ``sft_fccm`` stage (``engine/stages/sft.py``). The fail-loud
guard moved there verbatim from the deleted in-CCR ``ccr_rows_to_exposures`` path.
This module pins the corrected behaviour on the NEW stage: the stage raises when
the firm has an SFT book and ``SFTConfig.method`` is a reserved literal.

References:
    - CRR Art. 221 — VaR-based SFT method (reserved, unimplemented).
    - CRR Art. 283 — IMM SFT method (reserved, unimplemented).
    - CRR Art. 271(2) — SFT EAD routing.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.fixtures.ccr.golden_ccr_a11_a12 import (
    _build_cp_inst_001_counterparty,
    _build_cp_inst_001_rating,
    _build_empty_facilities,
    _build_empty_facility_mappings,
    _build_empty_lending_mappings,
    _build_empty_loans,
)
from tests.fixtures.ccr.sft_bundle_builder import build_sft_bundle_ccr_a11
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.context import PipelineContext
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.orchestrator import COMPONENTS, RAW_DATA, build_components
from rwa_calc.engine.stages import hierarchy as hierarchy_stage
from rwa_calc.engine.stages import securitisation as securitisation_stage
from rwa_calc.engine.stages import sft as sft_stage
from rwa_calc.rulebook import RulepackV0

_REPORTING_DATE = date(2026, 6, 30)


def _config(sft_method: str) -> CalculationConfig:
    """CRR config with the SFT method overridden (sets SFTConfig.method)."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
        sft_method=sft_method,  # ty: ignore[invalid-argument-type]
    )


def _base_ctx(config: CalculationConfig) -> PipelineContext:
    """A context whose ``raw.sft`` carries the CCR-A11 SFT trade (no prefix run)."""
    bundle = make_raw_bundle(
        counterparties=_build_cp_inst_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_inst_001_rating(),
        sft=build_sft_bundle_ccr_a11(),
    )
    return PipelineContext.empty().put(RAW_DATA, bundle).put(COMPONENTS, build_components(config))


def _resolved_ctx(config: CalculationConfig, rulepack: RulepackV0) -> PipelineContext:
    """Run securitisation -> hierarchy so RESOLVED_HIERARCHY is populated."""
    ctx = _base_ctx(config)
    ctx = securitisation_stage.run(ctx, rulepack, config)
    return hierarchy_stage.run(ctx, rulepack, config)


@pytest.mark.parametrize("reserved_method", ["var", "imm"])
def test_reserved_sft_method_raises_not_implemented(reserved_method: str) -> None:
    """A reserved SFT method must fail loud on the sft_fccm stage.

    The CCR-A11 SFT book is populated on ``raw.sft``. The sft_fccm stage must
    raise NotImplementedError before computing any EAD when the method is a
    reserved literal, rather than silently dropping the SFT exposure. The guard
    fires ahead of ``RESOLVED_HIERARCHY``, so a minimal context suffices.
    """
    # Arrange
    config = _config(reserved_method)
    rulepack = RulepackV0.from_config(config)
    ctx = _base_ctx(config)

    # Act + Assert
    with pytest.raises(NotImplementedError, match=reserved_method):
        sft_stage.run(ctx, rulepack, config)


def test_fccm_sft_method_does_not_raise() -> None:
    """The default "fccm" method runs the FCCM chain (no raise).

    The dark-launch + acceptance suites pin the numeric FCCM result; here we
    only assert the sft_fccm stage does NOT raise for "fccm" — the full
    securitisation -> hierarchy prefix is run so RESOLVED_HIERARCHY exists.
    """
    # Arrange
    config = _config("fccm")
    rulepack = RulepackV0.from_config(config)
    ctx = _resolved_ctx(config, rulepack)

    # Act — running the stage on a "fccm" book must not raise.
    sft_stage.run(ctx, rulepack, config)
