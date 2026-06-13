"""
P8.20 CCR pipeline-integration tests.

Verifies that the CCR SA-CCR stage is wired into the pipeline BEFORE the
Classifier (between HierarchyResolver at pipeline.py line 299 and Classifier
at line 304), emitting one synthetic exposure row per netting set with:

    exposure_reference = f"ccr__{netting_set_id}"
    risk_type          = "CCR_DERIVATIVE"
    drawn_amount       = ead_ccr
    source_netting_set_id = <netting_set_id>
    ccr_method         = "sa_ccr"

Pipeline position:
    RawDataBundle -> Loader -> HierarchyResolver -> [CCR stage] -> Classifier
        -> CRMProcessor -> SA/IRB/Slotting/Equity Calculators -> OutputAggregator

Key responsibilities of this test module:
- Assert the CCR stage emits exactly one synthetic row for NS_001.
- Assert the synthetic row's EAD equals the SA-CCR engine's direct result.
- Assert provenance columns are populated correctly.
- Assert the stage_timer emits a "ccr_sa_ccr completed" log record.
- Assert the stage is a no-op when data.ccr is None (zero synthetic rows).
- Assert total RWA is unchanged (= 0.0) when CCR is absent.

Fixtures:
    build_raw_data_bundle_with_ccr_a1()  — CP_001 institution CQS 2, NS_001
    build_raw_data_bundle_no_ccr()       — same stub, ccr=None

Scenario:
    CCR-A1: single 10-year GBP vanilla IR swap (T_001), notional GBP 100m,
    MtM = 0.0 (at-par), delta = 1.0, unmargined, legally enforceable,
    counterparty CP_001 (institution, CQS 2, GB).

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274 (SA-CCR EAD = alpha × (RC + PFE))
    - CRR Art. 275(1) (unmargined RC = max(V − C, 0) = 0 for at-par)
    - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% SA risk weight)
    - CRR Art. 295-297 (contractual netting recognition)
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.observability import RunIdFilter
from tests.fixtures.ccr.golden_ccr_a1 import (
    CCR_A1_NETTING_SET_ID,
    build_raw_data_bundle_no_ccr,
    build_raw_data_bundle_with_ccr_a1,
)

_REPORTING_DATE = date(2026, 1, 15)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CCR_EXPOSURE_REF = f"ccr__{CCR_A1_NETTING_SET_ID}"  # "ccr__NS_001"
_CCR_STAGE_NAME = "ccr_sa_ccr"
_PIPELINE_LOGGER = "rwa_calc.engine.pipeline"
# stage_timer records are emitted by the fold orchestrator (migration
# Phase 4); run-level records stay on the pipeline facade logger.
_ORCHESTRATOR_LOGGER = "rwa_calc.engine.orchestrator"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures (run once per bundle variant)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _crr_config() -> CalculationConfig:
    """CRR configuration for CCR-A1 integration tests."""
    return CalculationConfig.crr(reporting_date=_REPORTING_DATE)


@pytest.fixture(scope="module")
def result_with_ccr(_crr_config: CalculationConfig):
    """Run the full CRR pipeline with the CCR-A1 bundle (ccr populated).

    Arrange:
        build_raw_data_bundle_with_ccr_a1() — CP_001 institution CQS 2, NS_001
        CalculationConfig.crr()
    Act:
        PipelineOrchestrator().run_with_data(data, config)
    """
    # Arrange
    data = build_raw_data_bundle_with_ccr_a1()

    # Act
    orchestrator = PipelineOrchestrator()
    return orchestrator.run_with_data(data, _crr_config)


@pytest.fixture(scope="module")
def result_no_ccr(_crr_config: CalculationConfig):
    """Run the full CRR pipeline with the no-CCR bundle (ccr=None).

    Arrange:
        build_raw_data_bundle_no_ccr() — same stub, ccr=None
        CalculationConfig.crr()
    Act:
        PipelineOrchestrator().run_with_data(data, config)
    """
    # Arrange
    data = build_raw_data_bundle_no_ccr()

    # Act
    orchestrator = PipelineOrchestrator()
    return orchestrator.run_with_data(data, _crr_config)


# ---------------------------------------------------------------------------
# Assertion 1 — no PIPELINE_CCR errors in result.errors
# ---------------------------------------------------------------------------


def test_pipeline_runs_without_ccr_errors(result_with_ccr) -> None:
    """Pipeline must accumulate zero PIPELINE_CCR* errors when CCR data is present.

    Arrange:
        result_with_ccr — full pipeline run with CCR-A1 bundle.
    Act:
        Filter result.errors to those whose code starts with 'PIPELINE_CCR'.
    Assert:
        The filtered list is empty (no CCR-related pipeline errors).

    References:
        CRR Art. 271 (CCR scope); CRR Art. 274 (SA-CCR EAD).
    """
    # Arrange
    result = result_with_ccr

    # Act
    ccr_errors = [e for e in result.errors if getattr(e, "code", "").startswith("PIPELINE_CCR")]

    # Assert
    assert ccr_errors == [], (
        f"P8.20: expected zero PIPELINE_CCR errors, got {len(ccr_errors)}: {ccr_errors}"
    )


# ---------------------------------------------------------------------------
# Assertion 2 — CCR synthetic row appears in results
# ---------------------------------------------------------------------------


def test_ccr_synthetic_row_appears_in_results(result_with_ccr) -> None:
    """The CCR stage must emit exactly one synthetic row with exposure_reference='ccr__NS_001'.

    Arrange:
        result_with_ccr.results — combined SA/IRB/slotting/CCR results frame.
    Act:
        Collect and filter to exposure_reference == 'ccr__NS_001'.
    Assert:
        Exactly one row exists.

    This test FAILS until the CCR pipeline stage (P8.20) is implemented:
    the engine currently does not emit any CCR synthetic rows.

    References:
        CRR Art. 271 (CCR scope — one EAD row per netting set).
    """
    # Arrange
    result = result_with_ccr

    # Act — filter the combined results frame for the CCR synthetic row
    results_df = result.results.collect()
    ccr_rows = results_df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF)

    # Assert
    assert len(ccr_rows) == 1, (
        f"P8.20: expected exactly 1 CCR synthetic row with "
        f"exposure_reference={_CCR_EXPOSURE_REF!r}, "
        f"got {len(ccr_rows)}. "
        f"Implement the CCR pipeline stage (P8.20) to emit one row per netting set."
    )


# ---------------------------------------------------------------------------
# Assertion 3 — CCR row EAD matches direct engine computation
# ---------------------------------------------------------------------------


def test_ccr_row_ead_matches_direct_compute_ead(result_with_ccr, _crr_config) -> None:
    """CCR row EAD must equal compute_ead(compute_pfe(...), config.ccr) on the same NS frame.

    This test compares the EAD that the pipeline attaches to the CCR synthetic
    row against the result of calling compute_ead + compute_pfe directly on a
    netting-set frame built from the same CCR-A1 inputs.

    For CCR-A1 (at-par, unmargined, zero collateral):
        RC = max(V - C, 0) = max(0 - 0, 0) = 0
        The PFE add-on drives the EAD via EAD = alpha * (RC + PFE_addon)

    The direct-compute frame uses the same v_net / c_net / addon_aggregate
    values that the pipeline stage would have computed from the CCR-A1 trade
    inputs.  Both paths call the same engine functions, so any discrepancy
    indicates a wiring bug in the pipeline adapter.

    Arrange:
        result_with_ccr.results — filter to exposure_reference == 'ccr__NS_001'.
        Direct compute via rwa_calc.engine.ccr.sa_ccr.compute_ead +
                          rwa_calc.engine.ccr.pfe.compute_pfe.
    Act:
        Extract pipeline EAD; compute direct EAD on matching NS frame.
    Assert:
        pipeline_ead == pytest.approx(direct_ead, rel=1e-9).

    Note:
        This test FAILS until P8.20 is implemented (no CCR row → KeyError or
        empty filter). The hand-calc literal value for addon_aggregate is deferred
        to P8.41; this test only checks the two paths agree with each other.

    References:
        CRR Art. 274(2) (EAD = alpha * (RC + PFE)).
        CRR Art. 275(1) (RC = max(V - C, 0) = 0 for at-par unmargined).
        CRR Art. 278 (PFE multiplier + add-on).
    """
    from rwa_calc.engine.ccr.pfe import compute_pfe
    from rwa_calc.engine.ccr.sa_ccr import compute_ead

    # Arrange — extract pipeline EAD (this step fails if assertion 2 has not landed)
    result = result_with_ccr
    results_df = result.results.collect()
    ccr_rows = results_df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF)
    assert len(ccr_rows) == 1, (
        f"P8.20 prerequisite: no CCR row found for {_CCR_EXPOSURE_REF!r}; "
        "implement P8.20 CCR pipeline stage first."
    )
    pipeline_ead = ccr_rows["ead_final"][0]

    # Arrange — build a netting-set grain frame matching CCR-A1 inputs.
    # For the direct computation we need v_net, c_net, addon_aggregate.
    # CCR-A1: MtM=0 (at-par) → V=0; no collateral → C=0.
    # addon_aggregate comes from the pipeline's internal compute — we read it
    # from the CCR row so both paths use the same value (pipeline stores it).
    addon_aggregate = ccr_rows["addon_aggregate"][0]

    ns_frame = pl.LazyFrame(
        {
            "netting_set_id": [CCR_A1_NETTING_SET_ID],
            "v_net": [0.0],
            "c_net": [0.0],
            "addon_aggregate": [float(addon_aggregate)],
        }
    )

    # Act — direct engine computation
    config = _crr_config
    pfe_frame = compute_pfe(ns_frame, config.ccr)
    ead_frame = compute_ead(pfe_frame, config.ccr)
    direct_ead = ead_frame.collect()["ead_ccr"][0]

    # Assert
    assert pipeline_ead == pytest.approx(direct_ead, rel=1e-9), (
        f"P8.20: pipeline EAD {pipeline_ead} does not match direct engine EAD {direct_ead} "
        f"for netting set {CCR_A1_NETTING_SET_ID}."
    )


# ---------------------------------------------------------------------------
# Assertion 4 — CCR row provenance columns
# ---------------------------------------------------------------------------


def test_ccr_row_provenance_columns_populated(result_with_ccr) -> None:
    """CCR synthetic row must carry correct provenance columns.

    The pipeline stage must attach:
        source_netting_set_id = "NS_001"
        ccr_method            = "sa_ccr"
        risk_type             = "CCR_DERIVATIVE"

    These columns allow downstream consumers (COREP reporting, CRM processor)
    to identify CCR-derived rows and distinguish them from traditional lending.

    Arrange:
        result_with_ccr.results — filter to exposure_reference == 'ccr__NS_001'.
    Act:
        Extract source_netting_set_id, ccr_method, risk_type from the row.
    Assert:
        All three columns carry the expected values.

    References:
        CRR Art. 271 (CCR scope — derivatives carry CCR EAD, not traditional EAD).
    """
    # Arrange
    result = result_with_ccr
    results_df = result.results.collect()
    ccr_rows = results_df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF)
    assert len(ccr_rows) == 1, (
        f"P8.20 prerequisite: no CCR row for {_CCR_EXPOSURE_REF!r}; implement P8.20 first."
    )
    row = ccr_rows.row(0, named=True)

    # Assert — source_netting_set_id
    assert row.get("source_netting_set_id") == CCR_A1_NETTING_SET_ID, (
        f"P8.20: expected source_netting_set_id={CCR_A1_NETTING_SET_ID!r}, "
        f"got {row.get('source_netting_set_id')!r}."
    )

    # Assert — ccr_method
    assert row.get("ccr_method") == "sa_ccr", (
        f"P8.20: expected ccr_method='sa_ccr', got {row.get('ccr_method')!r}."
    )

    # Assert — risk_type
    assert row.get("risk_type") == "CCR_DERIVATIVE", (
        f"P8.20: expected risk_type='CCR_DERIVATIVE', got {row.get('risk_type')!r}."
    )


# ---------------------------------------------------------------------------
# Assertion 5 — stage_timer emits ccr_sa_ccr record
# ---------------------------------------------------------------------------


def test_stage_timer_emits_ccr_sa_ccr_record(
    _crr_config: CalculationConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The CCR pipeline stage must emit a stage_timer 'ccr_sa_ccr completed' log record.

    stage_timer (rwa_calc.observability.context) emits an INFO record on
    successful completion with:
        record.stage    == 'ccr_sa_ccr'
        record.message.contains('completed')
        record.elapsed_ms >= 0.0

    Arrange:
        build_raw_data_bundle_with_ccr_a1() + CalculationConfig.crr().
    Act:
        Run PipelineOrchestrator with caplog capturing INFO on
        rwa_calc.engine.orchestrator (the fold emits stage_timer records).
    Assert:
        Exactly one record with stage='ccr_sa_ccr' and 'completed' in message.
        That record's elapsed_ms >= 0.0.

    This test FAILS until P8.20 wires the CCR stage into the pipeline with
    stage_timer(logger, 'ccr_sa_ccr').

    References:
        docs/specifications/observability.md (stage_timer contract).
        rwa_calc.observability.context.stage_timer.
    """
    # Arrange
    data = build_raw_data_bundle_with_ccr_a1()
    config = _crr_config
    orchestrator = PipelineOrchestrator()

    # Act — run with caplog capturing INFO on the pipeline logger.
    # rwa_calc.observability.configure_logging() (called by any earlier
    # CreditRiskCalc.calculate() test that shares the xdist worker) sets
    # propagate=False on the rwa_calc namespace logger, which severs it
    # from caplog's root-attached handler. Temporarily re-enable
    # propagation so caplog captures the stage_timer record. Mirrors the
    # pattern in tests/unit/test_loader_optional_error_handling.py and
    # tests/unit/test_fx_rate_sync.py.
    namespace_logger = logging.getLogger("rwa_calc")
    saved_propagate = namespace_logger.propagate
    namespace_logger.propagate = True
    try:
        caplog.set_level(logging.INFO, logger=_ORCHESTRATOR_LOGGER)
        caplog.handler.addFilter(RunIdFilter())
        with caplog.at_level(logging.INFO, logger=_ORCHESTRATOR_LOGGER):
            orchestrator.run_with_data(data, config)
    finally:
        namespace_logger.propagate = saved_propagate

    # Find records with stage='ccr_sa_ccr' and 'completed' in message
    ccr_stage_records = [
        r
        for r in caplog.records
        if getattr(r, "stage", None) == _CCR_STAGE_NAME
        and "completed" in (r.getMessage() if callable(r.getMessage) else str(r.message))
    ]

    # Assert — exactly one completed record
    assert len(ccr_stage_records) == 1, (
        f"P8.20: expected exactly 1 stage_timer record with "
        f"stage={_CCR_STAGE_NAME!r} and 'completed' in message, "
        f"got {len(ccr_stage_records)}. "
        f"Wire stage_timer(logger, {_CCR_STAGE_NAME!r}) in the CCR pipeline stage."
    )

    # Assert — elapsed_ms is non-negative
    record = ccr_stage_records[0]
    elapsed_ms = getattr(record, "elapsed_ms", None)
    assert elapsed_ms is not None and elapsed_ms >= 0.0, (
        f"P8.20: stage_timer record for {_CCR_STAGE_NAME!r} missing elapsed_ms >= 0.0, "
        f"got {elapsed_ms!r}."
    )


# ---------------------------------------------------------------------------
# Assertion 6 — CCR stage no-ops when data.ccr is None
# ---------------------------------------------------------------------------


def test_ccr_stage_noop_when_data_ccr_is_none(result_no_ccr) -> None:
    """When data.ccr is None, the pipeline must produce zero CCR synthetic rows.

    The CCR pipeline stage must guard on data.ccr is None and skip the
    SA-CCR computation entirely.  No ccr__ prefixed exposure_reference values
    must appear in the output.

    Arrange:
        result_no_ccr — pipeline run with build_raw_data_bundle_no_ccr() (ccr=None).
    Act:
        Collect result.results; filter to exposure_reference starting with 'ccr__'.
    Assert:
        Zero rows match the ccr__ prefix.

    References:
        CRR Art. 271 (scope — firms without derivatives book have no CCR).
    """
    # Arrange
    result = result_no_ccr

    # Act
    results_df = result.results.collect()

    # Guard: check if exposure_reference column exists; if empty frame, that is fine
    if "exposure_reference" not in results_df.columns:
        ccr_rows = results_df  # 0-column frame — trivially empty
    else:
        ccr_rows = results_df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))

    # Assert
    assert len(ccr_rows) == 0, (
        f"P8.20: expected zero CCR rows when data.ccr is None, "
        f"got {len(ccr_rows)}. "
        f"Ensure the CCR stage guards on data.ccr is None."
    )


# ---------------------------------------------------------------------------
# Assertion 7 — total RWA unchanged (= 0.0) when CCR absent
# ---------------------------------------------------------------------------


def test_rwa_total_unchanged_when_ccr_absent(result_no_ccr) -> None:
    """Total RWA must be 0.0 when CCR is absent and all lending frames are empty.

    This is a regression guard: the new CCR stage must be a true no-op when
    data.ccr is None.  With no traditional lending rows and no CCR rows, the
    aggregated RWA must be 0.0.

    Arrange:
        result_no_ccr — pipeline run with build_raw_data_bundle_no_ccr().
        All lending frames (facilities, loans, contingents) are zero-row.
        ccr=None.
    Act:
        Collect result.results["rwa_final"].sum().
    Assert:
        rwa_sum == pytest.approx(0.0, abs=1e-6).

    References:
        PRA PS1/26 Art. 92 para 2A (output floor — no-op when no exposures).
    """
    # Arrange
    result = result_no_ccr

    # Act
    results_df = result.results.collect()

    if "rwa_final" not in results_df.columns or len(results_df) == 0:
        rwa_sum = 0.0
    else:
        rwa_sum = float(results_df["rwa_final"].fill_null(0.0).sum())

    # Assert
    assert rwa_sum == pytest.approx(0.0, abs=1e-6), (
        f"P8.20: expected total RWA=0.0 when CCR is absent and lending frames are empty, "
        f"got rwa_sum={rwa_sum}. "
        f"The CCR stage must be a strict no-op when data.ccr is None."
    )
