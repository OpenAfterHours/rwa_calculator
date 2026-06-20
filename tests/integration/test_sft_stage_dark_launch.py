"""
Dark-launch integration test for the SFT FCCM peer stage (Phase 5).

Pipeline position:
    Loader -> HierarchyResolver -> ccr_sa_ccr -> sft_fccm -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

SFT/FCCM separation Phase 5 ships the new ``sft_fccm`` stage but does NOT yet
re-point any fixture at ``raw.sft`` (Phase 6 flips the golden). Without this
test the new stage would never fire in the suite. This test populates
``RawDataBundle.sft`` directly and runs the full pipeline to prove the stage
works END TO END before the source flip:

- The synthetic SFT EAD exposure row appears in the final results with
  ``ccr_method == "fccm_sft"`` and ``risk_type == "CCR_SFT"``.
- The FCCM E* matches the CCR-A11 (uncollateralised) and CCR-A12
  (cash-collateralised) golden hand-calc — the peer subsystem reproduces the
  Art. 223(5) math byte-for-byte for the same trade.
- The SA-CCR provenance columns (``ccr_method`` / ``ead_ccr``) SURVIVE all the
  way to the aggregated results — proving the stage sealed to the existing
  ``ccr_exit`` brand (a fresh ``sft_exit`` brand would de-select the rows onto
  the non-CCR edge and strip these columns; see Section 3 of the plan).
- The ``sft_fccm`` ``stage_timer`` label is emitted (the stage actually ran).

References:
    - CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274.
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
    - CRR Art. 120 Table 3 — institution CQS 2 → 50% SA risk weight.
    - docs/plans/sft-fccm-separation.md (Phase 5).
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import sealed_edge_of
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.observability import RunIdFilter
from tests.fixtures.ccr.golden_ccr_a11_a12 import (
    CCR_A11_EAD,
    CCR_A11_RWA,
    CCR_A12_EAD,
    CCR_A12_RWA,
    _build_cp_inst_001_counterparty,
    _build_cp_inst_001_rating,
    _build_empty_facilities,
    _build_empty_facility_mappings,
    _build_empty_lending_mappings,
    _build_empty_loans,
)
from tests.fixtures.ccr.sft_bundle_builder import (
    SFT_DL_A11_EXPOSURE_REFERENCE,
    SFT_DL_A12_EXPOSURE_REFERENCE,
    build_sft_bundle_a11,
    build_sft_bundle_a12,
)
from tests.fixtures.raw_bundle import make_raw_bundle

_REL_TOL: float = 1e-6
_EXPECTED_RISK_WEIGHT: float = 0.50
_A11_EAD_LOWER_BOUND: float = 60_000_000.0


def _make_sft_data_bundle(sft_bundle) -> object:
    """Assemble a RawDataBundle with a populated ``raw.sft`` (no ``raw.ccr``)."""
    return make_raw_bundle(
        counterparties=_build_cp_inst_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_inst_001_rating(),
        sft=sft_bundle,
    )


def _run(sft_bundle) -> pl.DataFrame:
    """Run the full CRR SA pipeline with the SFT book populated."""
    bundle = _make_sft_data_bundle(sft_bundle)
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    return results.results.collect()


@pytest.fixture(scope="module")
def sft_dl_a11_row() -> dict:
    """The single synthetic SFT EAD row from the uncollateralised dark-launch run."""
    df = _run(build_sft_bundle_a11())
    rows = df.filter(pl.col("exposure_reference") == SFT_DL_A11_EXPOSURE_REFERENCE).to_dicts()
    assert len(rows) == 1, (
        f"expected exactly 1 result row for {SFT_DL_A11_EXPOSURE_REFERENCE!r}, got {len(rows)}. "
        "The sft_fccm stage must emit one synthetic row per SFT netting set."
    )
    return rows[0]


@pytest.fixture(scope="module")
def sft_dl_a12_row() -> dict:
    """The single synthetic SFT EAD row from the cash-collateralised dark-launch run."""
    df = _run(build_sft_bundle_a12())
    rows = df.filter(pl.col("exposure_reference") == SFT_DL_A12_EXPOSURE_REFERENCE).to_dicts()
    assert len(rows) == 1, (
        f"expected exactly 1 result row for {SFT_DL_A12_EXPOSURE_REFERENCE!r}, got {len(rows)}. "
        "The sft_fccm stage must emit one synthetic row per SFT netting set."
    )
    return rows[0]


class TestSftStageDarkLaunchUncollateralised:
    """The new sft_fccm stage produces the CCR-A11 result from ``raw.sft``."""

    def test_ccr_method_is_fccm_sft(self, sft_dl_a11_row: dict) -> None:
        assert sft_dl_a11_row["ccr_method"] == "fccm_sft"

    def test_risk_type_is_ccr_sft(self, sft_dl_a11_row: dict) -> None:
        assert sft_dl_a11_row["risk_type"] == "CCR_SFT"

    def test_ead_above_lower_bound(self, sft_dl_a11_row: dict) -> None:
        """LOAD-BEARING: ead_ccr > £60m — FCCM E·(1+HE), not a degenerate route."""
        assert sft_dl_a11_row["ead_ccr"] > _A11_EAD_LOWER_BOUND

    def test_ead_matches_golden(self, sft_dl_a11_row: dict) -> None:
        """E* = E·(1+HE) = CCR-A11 golden — the peer subsystem reproduces Art. 223(5)."""
        assert sft_dl_a11_row["ead_ccr"] == pytest.approx(CCR_A11_EAD, rel=_REL_TOL)

    def test_risk_weight_fifty_percent(self, sft_dl_a11_row: dict) -> None:
        """Institution CQS 2 → 50% (CRR Art. 120 Table 3) — rating enrichment ran."""
        assert sft_dl_a11_row["risk_weight"] == pytest.approx(_EXPECTED_RISK_WEIGHT, abs=1e-12)

    def test_rwa_matches_golden(self, sft_dl_a11_row: dict) -> None:
        assert sft_dl_a11_row["rwa_final"] == pytest.approx(CCR_A11_RWA, rel=_REL_TOL)


class TestSftStageDarkLaunchCollateralised:
    """The new sft_fccm stage applies the optional collateral term (CCR-A12)."""

    def test_ccr_method_is_fccm_sft(self, sft_dl_a12_row: dict) -> None:
        assert sft_dl_a12_row["ccr_method"] == "fccm_sft"

    def test_ead_matches_golden(self, sft_dl_a12_row: dict) -> None:
        """E* = E·(1+HE) − 60m cash (HC=0, HFX=0) = CCR-A12 golden."""
        assert sft_dl_a12_row["ead_ccr"] == pytest.approx(CCR_A12_EAD, rel=_REL_TOL)

    def test_rwa_matches_golden(self, sft_dl_a12_row: dict) -> None:
        assert sft_dl_a12_row["rwa_final"] == pytest.approx(CCR_A12_RWA, rel=_REL_TOL)

    def test_collateral_offset_delta(self, sft_dl_a11_row: dict, sft_dl_a12_row: dict) -> None:
        """A11.ead_ccr − A12.ead_ccr == the GBP 60m cash collateral exactly."""
        delta = sft_dl_a11_row["ead_ccr"] - sft_dl_a12_row["ead_ccr"]
        assert delta == pytest.approx(60_000_000.0, rel=_REL_TOL)


class TestSftStageBrandSurvivesDownstream:
    """The stage sealed to ``ccr_exit`` so SFT provenance reaches the results."""

    def test_provenance_columns_survive(self, sft_dl_a11_row: dict) -> None:
        """``ccr_method`` and ``ead_ccr`` reach the aggregated results.

        These columns are declared by ``CCR_EXIT_EDGE`` only. Their presence on
        the final SFT row proves the stage re-sealed ``resolved.exposures`` to
        the existing ``ccr_exit`` brand — a fresh ``sft_exit`` brand would have
        de-selected the row onto the non-CCR classifier edge and stripped them.
        """
        assert sft_dl_a11_row["ccr_method"] == "fccm_sft"
        assert sft_dl_a11_row["ead_ccr"] is not None

    def test_resolved_exposures_branded_ccr_exit(self) -> None:
        """Drive the stage directly and assert the re-sealed frame's brand."""
        from rwa_calc.contracts.context import PipelineContext
        from rwa_calc.engine.orchestrator import (
            COMPONENTS,
            RAW_DATA,
            RESOLVED_HIERARCHY,
            build_components,
        )
        from rwa_calc.engine.stages import hierarchy as hierarchy_stage
        from rwa_calc.engine.stages import securitisation as securitisation_stage
        from rwa_calc.engine.stages import sft as sft_stage
        from rwa_calc.rulebook import RulepackV0

        # Arrange — run the prefix (securitisation -> hierarchy), then the SFT
        # stage, on a pure-SFT bundle (no ccr_sa_ccr stage in between).
        bundle = _make_sft_data_bundle(build_sft_bundle_a11())
        config = CalculationConfig.crr(
            reporting_date=date(2026, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        rulepack = RulepackV0.from_config(config)
        ctx = (
            PipelineContext.empty().put(RAW_DATA, bundle).put(COMPONENTS, build_components(config))
        )
        ctx = securitisation_stage.run(ctx, rulepack, config)
        ctx = hierarchy_stage.run(ctx, rulepack, config)

        # Act
        ctx = sft_stage.run(ctx, rulepack, config)

        # Assert — the resolver exit frame now carries the ccr_exit brand even
        # though no SA-CCR stage ran ahead of the SFT stage.
        resolved = ctx.get(RESOLVED_HIERARCHY)
        assert sealed_edge_of(resolved.exposures) == "ccr_exit"


def test_sft_fccm_stage_timer_emitted(
    reset_logging_state: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fold emits a ``sft_fccm`` stage_timer record when the SFT book runs.

    Pins the registered stage-timer label and proves the stage actually fired
    (the dark-launch fixture is the only thing in the suite that populates
    ``raw.sft``).
    """
    caplog.set_level(logging.INFO, logger="rwa_calc")
    caplog.handler.addFilter(RunIdFilter())
    PipelineOrchestrator().run_with_data(
        _make_sft_data_bundle(build_sft_bundle_a11()),
        CalculationConfig.crr(
            reporting_date=date(2026, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        ),
    )

    matching = [
        r
        for r in caplog.records
        if getattr(r, "stage", None) == "sft_fccm" and "completed" in r.getMessage()
    ]
    assert len(matching) == 1, (
        "expected exactly 1 stage_timer 'sft_fccm completed' record; "
        f"got {len(matching)}. The fold must wrap the registered sft_fccm stage."
    )
