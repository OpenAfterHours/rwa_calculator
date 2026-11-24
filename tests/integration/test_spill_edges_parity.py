"""
Integration tests: spill-edge mode produces identical results to in-memory mode.

Migration Phase 1 (docs/plans/target-architecture-migration.md) introduced an
opt-in spill-to-parquet edge mode (``config.spill_edges``): every stage-exit
materialisation is sunk to parquet and scanned back instead of held in memory.
The only acceptable difference between the two modes is peak memory — these
tests pin the parity contract:

1. **Result parity** — the final results frame from a spill run is identical
   to the in-memory run on the same bundle (same rows, same values, same
   dtypes). Any divergence means the parquet roundtrip is lossy or an edge
   plan changed semantics under spill.

2. **Manifest honesty** — the spill run's materialisation map records
   ``spilled: true`` on every edge, including the ``crm_pre_guarantee_unified``
   checkpoint (the bundle carries a guarantee so the checkpoint fires).

3. **Spill-file lifecycle** — ``end_edge_capture`` deletes every spill file at
   run end; the spill directory holds no parquet files after the run.

References:
- docs/plans/target-architecture-migration.md (Phase 1)
- src/rwa_calc/engine/materialise.py (materialise_edge, spill mode)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import GUARANTEE_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import seal_raw_table

from .conftest import (
    _rows_to_lazyframe,
    make_contingent,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

_REPORTING_DATE = date(2026, 12, 31)


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _guarantee_row() -> dict[str, Any]:
    """Guarantee on LOAN_001 so the crm_pre_guarantee checkpoint fires."""
    return {
        "guarantee_reference": "GTEE_1",
        "guarantee_type": "corporate_guarantee",
        "guarantor": "CP_GUARANTOR",
        "currency": "GBP",
        "maturity_date": date(2030, 12, 31),
        "amount_covered": 500_000.0,
        "percentage_covered": None,
        "beneficiary_type": "loan",
        "beneficiary_reference": "LOAN_001",
        "protection_type": "guarantee",
        "includes_restructuring": True,
    }


def _build_bundle() -> RawDataBundle:
    """Moderately-featured bundle: loans + facilities + contingent + guarantee.

    Built fresh per run so neither run can observe state from the other's
    LazyFrame plans.
    """
    bundle = make_raw_data_bundle(
        counterparties=[
            make_counterparty(counterparty_reference="CP_001"),
            make_counterparty(counterparty_reference="CP_002", annual_revenue=2_000_000.0),
            make_counterparty(counterparty_reference="CP_GUARANTOR", entity_type="corporate"),
        ],
        loans=[
            make_loan(loan_reference="LOAN_001", counterparty_reference="CP_001"),
            make_loan(
                loan_reference="LOAN_002",
                counterparty_reference="CP_002",
                drawn_amount=250_000.0,
            ),
        ],
        facilities=[
            make_facility(facility_reference="FAC_001", counterparty_reference="CP_001"),
            make_facility(
                facility_reference="FAC_002",
                counterparty_reference="CP_002",
                limit=750_000.0,
            ),
        ],
        contingents=[
            make_contingent(contingent_reference="CONT_001", counterparty_reference="CP_001"),
        ],
    )
    return replace(
        bundle,
        guarantees=seal_raw_table(
            _rows_to_lazyframe([_guarantee_row()], GUARANTEE_SCHEMA), "guarantees"
        ),
    )


#: The headroom rows ``_build_dust_bundle`` must produce. Every other headroom in
#: it is exactly zero in the inputs and one ulp away from zero in binary.
_DUST_BUNDLE_UNDRAWN_ROWS = ["MOF_P_UNDRAWN_MOF_S1", "MOF_P_UNDRAWN_MOF_S2", "MOF_Q_UNDRAWN_MOF_Q1"]


def _build_dust_bundle() -> RawDataBundle:
    """Facility headroom that is exactly zero in the inputs, and float dust in binary.

    The spill-parity gate's first bundle holds no Multiple Option Facility and no
    amount that is inexact in binary, so it never reached the three headroom gates
    in ``engine/hierarchy/facility_undrawn.py``. On the 200K benchmark those gates
    turned summation residue into ``<facility>_UNDRAWN_RESIDUAL`` rows whose number
    varied with the order a chunked parquet re-read summed in (escape log
    2026-11-24). Each structure here reproduces that residue at the hierarchy stage:

    - ``MOF_P``: sub-lines that together cover the umbrella's headroom - residual
      exactly 0, binary 9.3e-10.
    - ``MOF_Q``: a first sub-line that takes the whole headroom - the second's slice
      is exactly 0, binary 4.7e-10.
    - ``FAC_FULL``: a line drawn to exactly its limit - headroom exactly 0, binary
      1.9e-09.
    """
    facilities = [
        make_facility(facility_reference="MOF_P", limit=7_816_127.22, risk_type="OC"),
        make_facility(facility_reference="MOF_S1", limit=1_343_643.31, risk_type="OC"),
        make_facility(facility_reference="MOF_S2", limit=8_474_337.52, risk_type="OC"),
        make_facility(facility_reference="MOF_Q", limit=3_751_040.52, risk_type="OC"),
        make_facility(facility_reference="MOF_Q1", limit=3_751_040.52, risk_type="FR"),
        make_facility(facility_reference="MOF_Q2", limit=9_823_853.46, risk_type="OC"),
        make_facility(facility_reference="FAC_FULL", limit=12_996_896.49),
    ]
    loans = [
        make_loan(loan_reference="LOAN_A", drawn_amount=6_737_013.93),
        make_loan(loan_reference="LOAN_B", drawn_amount=6_259_882.56),
    ]
    mappings = [
        {"parent_facility_reference": parent, "child_reference": child, "child_type": kind}
        for parent, child, kind in (
            ("MOF_P", "MOF_S1", "facility"),
            ("MOF_P", "MOF_S2", "facility"),
            ("MOF_Q", "MOF_Q1", "facility"),
            ("MOF_Q", "MOF_Q2", "facility"),
            ("FAC_FULL", "LOAN_A", "loan"),
            ("FAC_FULL", "LOAN_B", "loan"),
        )
    ]
    return make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference="CP001")],
        loans=loans,
        facilities=facilities,
        facility_mappings=mappings,
    )


# ---------------------------------------------------------------------------
# Shared parity runs (one in-memory run + one spill run per module)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParityRuns:
    """Collected outputs of the in-memory and spill runs."""

    in_memory_results: pl.DataFrame
    spill_results: pl.DataFrame
    spill_edge_map: list[dict[str, Any]]
    spill_dir: Path


@pytest.fixture(scope="module")
def parity_runs(tmp_path_factory: pytest.TempPathFactory) -> ParityRuns:
    """Run the pipeline twice on the same bundle: in-memory, then spill mode."""
    base_dir = tmp_path_factory.mktemp("spill_parity")
    spill_dir = base_dir / "spill"
    spill_dir.mkdir()
    audit_dir = base_dir / "audit"

    config = CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    spill_config = replace(
        config,
        spill_edges=True,
        spill_dir=spill_dir,
        audit_cache_dir=audit_dir,
    )

    in_memory = PipelineOrchestrator().run_with_data(_build_bundle(), config)
    spill = PipelineOrchestrator().run_with_data(_build_bundle(), spill_config)
    assert in_memory.results is not None
    assert spill.results is not None

    manifests = sorted(audit_dir.glob("*/manifest.json"))
    assert manifests, "spill run with audit_cache_dir must write a manifest"
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))

    return ParityRuns(
        in_memory_results=in_memory.results.collect().sort("exposure_reference"),
        spill_results=spill.results.collect().sort("exposure_reference"),
        spill_edge_map=manifest["materialisation_map"],
        spill_dir=spill_dir,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_spill_run_results_identical_to_in_memory_run(parity_runs: ParityRuns) -> None:
    """The parquet roundtrip at every edge must be value- and dtype-lossless."""
    assert parity_runs.in_memory_results.height > 0

    assert_frame_equal(
        parity_runs.in_memory_results,
        parity_runs.spill_results,
        check_exact=True,
    )


def test_spill_run_manifest_records_spilled_edges(parity_runs: ParityRuns) -> None:
    """Every edge in the spill run's materialisation map is marked spilled."""
    edge_map = parity_runs.spill_edge_map
    assert edge_map, "spill run must record a materialisation map"

    not_spilled = [e["label"] for e in edge_map if not e["spilled"]]
    assert not not_spilled, f"edges materialised in-memory during a spill run: {not_spilled}"

    labels = [e["label"] for e in edge_map]
    assert "crm_pre_guarantee_unified" in labels, (
        "the guarantee row must trigger the crm_pre_guarantee checkpoint so "
        "the intra-stage spill path is exercised too"
    )


def test_spill_files_cleaned_up_after_run(parity_runs: ParityRuns) -> None:
    """end_edge_capture deletes every spill file when the run finishes."""
    leftovers = sorted(parity_runs.spill_dir.glob("*.parquet"))

    assert not leftovers, f"spill files not cleaned up: {[p.name for p in leftovers]}"


@pytest.fixture(scope="module")
def dust_parity_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The dust bundle through both modes, Basel 3.1 (LR undrawn is 10%, not 0%)."""
    spill_dir = tmp_path_factory.mktemp("spill_dust")
    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
    spill_config = replace(config, spill_edges=True, spill_dir=spill_dir)

    in_memory = PipelineOrchestrator().run_with_data(_build_dust_bundle(), config)
    spill = PipelineOrchestrator().run_with_data(_build_dust_bundle(), spill_config)
    assert in_memory.results is not None
    assert spill.results is not None
    return (
        in_memory.results.collect().sort("exposure_reference"),
        spill.results.collect().sort("exposure_reference"),
    )


def test_spill_run_matches_in_memory_on_float_dust_headroom(
    dust_parity_runs: tuple[pl.DataFrame, pl.DataFrame],
) -> None:
    """Exact parity on a book whose zero headrooms are one ulp from zero in binary."""
    in_memory, spill = dust_parity_runs

    assert_frame_equal(in_memory, spill, check_exact=True)


@pytest.mark.parametrize("mode", ["in_memory", "spill"])
def test_float_dust_headroom_emits_no_undrawn_row(
    dust_parity_runs: tuple[pl.DataFrame, pl.DataFrame], mode: str
) -> None:
    """Parity alone cannot see this at this scale: a one-chunk book sums in one order,
    so both modes emit the SAME dust row. The row set itself is the gate."""
    results = dict(zip(("in_memory", "spill"), dust_parity_runs, strict=True))[mode]

    undrawn = sorted(r for r in results["exposure_reference"].to_list() if "_UNDRAWN" in r)

    assert undrawn == _DUST_BUNDLE_UNDRAWN_ROWS
