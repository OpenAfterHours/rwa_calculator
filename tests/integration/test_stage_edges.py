"""
Integration tests: stage-edge materialisation discipline (migration Phase 1).

Asserts two invariants over the orchestrated pipeline:

1. **Edge inventory** — every stage exit materialises through
   ``materialise_edge`` and lands in the run manifest's materialisation map,
   in pipeline order. A missing edge means a stage started exchanging lazy
   plans across its boundary again; an unexpected edge means a new
   materialisation was added without updating the documented inventory
   (docs/architecture/pipeline-collect-barriers.md).

2. **Plan-node ceilings** — the unoptimised plan arriving at each edge stays
   under a pinned per-edge ceiling, so residual *intra-stage* depth growth is
   a failing test instead of a Polars SIGSEGV. Measured on Polars 1.37 the
   crash threshold is ~25,000 nodes for trivial chains and far lower for
   heavy when/then + join expressions.

RECALIBRATION (required on every Polars upgrade): run with
``RWA_PRINT_EDGE_NODES=1`` to print the measured per-edge node counts, then
re-pin ``_EDGE_NODE_CEILINGS`` at roughly 2x the measured value. Never trust
a stale ceiling — the ">500 nodes" comment that survived while the measured
threshold was ~25,000 is the standing warning.

References:
- docs/plans/target-architecture-migration.md (Phase 1)
- docs/plans/single-lazy-plan-refactor.md (depth evidence, superseded)
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import GUARANTEE_SCHEMA
from rwa_calc.engine import pipeline as pipeline_module
from rwa_calc.engine.materialise import begin_edge_capture
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import seal_raw_table

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_loan,
    make_raw_data_bundle,
)

# ---------------------------------------------------------------------------
# Per-edge plan-node ceilings (see module docstring for recalibration)
# ---------------------------------------------------------------------------

# Measured 2026-06-11 on Polars 1.37 (RWA_PRINT_EDGE_NODES=1): hierarchy_exit
# 1586, classifier_exit 88, crm_post_ead 22, crm_pre_guarantee_unified 1021,
# crm_exit 1025 (1225 with guarantees), re_split_exit 100, branches 28-85.
# Ceilings pinned at ~2-4x measured; SIGSEGV threshold ~25,000.
_EDGE_NODE_CEILINGS: dict[str, int] = {
    "hierarchy_exit": 3200,
    "ccr_exit": 800,
    "classifier_exit": 400,
    "crm_post_ead": 2400,
    "crm_pre_guarantee_unified": 4000,
    "crm_exit": 4000,
    "re_split_exit": 500,
    "sa_branch": 500,
    "irb_branch": 500,
    "slotting_branch": 300,
}

# The orchestrated edge sequence for a plain (no-CCR, no-guarantee) run.
_BASE_EDGE_SEQUENCE = [
    "hierarchy_exit",
    "classifier_exit",
    "crm_post_ead",
    "crm_exit",
    "re_split_exit",
    "sa_branch",
    "irb_branch",
    "slotting_branch",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guarantee_row() -> dict[str, Any]:
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


def _run_and_read_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_guarantee: bool = False,
) -> list[dict[str, Any]]:
    """Run the pipeline with the audit cache on; return the materialisation map."""
    # Count plan nodes during this run (off by default in production).
    monkeypatch.setattr(
        pipeline_module,
        "begin_edge_capture",
        lambda: begin_edge_capture(count_plan_nodes=True),
    )

    counterparties = [make_counterparty(counterparty_reference="CP_001")]
    if with_guarantee:
        counterparties.append(
            make_counterparty(counterparty_reference="CP_GUARANTOR", entity_type="corporate")
        )
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=[make_loan(loan_reference="LOAN_001", counterparty_reference="CP_001")],
    )
    if with_guarantee:
        bundle = replace(
            bundle,
            guarantees=seal_raw_table(
                _rows_to_lazyframe([_guarantee_row()], GUARANTEE_SCHEMA), "guarantees"
            ),
        )

    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
        audit_cache_dir=tmp_path,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    assert result.results is not None

    manifests = sorted(tmp_path.glob("*/manifest.json"))
    assert manifests, "audit cache must write a manifest"
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    edge_map: list[dict[str, Any]] = manifest["materialisation_map"]

    if os.environ.get("RWA_PRINT_EDGE_NODES"):
        for event in edge_map:
            print(  # noqa: T201 — explicit recalibration aid, env-gated
                f"EDGE {event['label']}: nodes={event.get('plan_nodes')} "
                f"rows={event['rows']} wall_ms={event['wall_ms']}"
            )
    return edge_map


# ---------------------------------------------------------------------------
# Edge inventory
# ---------------------------------------------------------------------------


class TestEdgeInventory:
    """Every stage exit goes through materialise_edge, in pipeline order."""

    def test_plain_run_emits_the_documented_edge_sequence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        edge_map = _run_and_read_map(tmp_path, monkeypatch)

        assert [e["label"] for e in edge_map] == _BASE_EDGE_SEQUENCE

    def test_guaranteed_run_adds_the_crm_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pre-guarantee intra-stage checkpoint appears iff guarantees exist."""
        edge_map = _run_and_read_map(tmp_path, monkeypatch, with_guarantee=True)

        labels = [e["label"] for e in edge_map]
        assert "crm_pre_guarantee_unified" in labels
        without_checkpoint = [lbl for lbl in labels if lbl != "crm_pre_guarantee_unified"]
        assert without_checkpoint == _BASE_EDGE_SEQUENCE
        # The checkpoint sits inside the CRM stage: after the post-EAD
        # checkpoint, before crm_exit.
        assert labels.index("crm_post_ead") < labels.index("crm_pre_guarantee_unified")
        assert labels.index("crm_pre_guarantee_unified") < labels.index("crm_exit")

    def test_exposure_edges_carry_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        edge_map = _run_and_read_map(tmp_path, monkeypatch)

        by_label = {e["label"]: e for e in edge_map}
        for label in ("hierarchy_exit", "classifier_exit", "crm_exit", "re_split_exit"):
            assert by_label[label]["rows"] >= 1, f"{label} materialised an empty frame"
            assert by_label[label]["estimated_bytes"] > 0


# ---------------------------------------------------------------------------
# Plan-node ceilings
# ---------------------------------------------------------------------------


class TestPlanNodeCeilings:
    """Intra-stage plan depth stays under the pinned per-edge ceilings."""

    def test_plain_run_edges_under_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        edge_map = _run_and_read_map(tmp_path, monkeypatch)

        breaches = {
            e["label"]: (e["plan_nodes"], _EDGE_NODE_CEILINGS[e["label"]])
            for e in edge_map
            if e["plan_nodes"] > _EDGE_NODE_CEILINGS[e["label"]]
        }
        assert not breaches, (
            f"plan-node ceiling breached (nodes, ceiling): {breaches}. "
            "If this is intentional intra-stage growth, re-measure with "
            "RWA_PRINT_EDGE_NODES=1 and justify the new ceiling in review; "
            "unbounded depth is the Polars SIGSEGV class."
        )

    def test_guaranteed_run_checkpoint_under_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        edge_map = _run_and_read_map(tmp_path, monkeypatch, with_guarantee=True)

        breaches = {
            e["label"]: (e["plan_nodes"], _EDGE_NODE_CEILINGS[e["label"]])
            for e in edge_map
            if e["plan_nodes"] > _EDGE_NODE_CEILINGS[e["label"]]
        }
        assert not breaches, f"plan-node ceiling breached (nodes, ceiling): {breaches}"

    def test_every_documented_edge_has_a_ceiling(self) -> None:
        """New edges must be added to the ceiling table, not silently skipped."""
        assert set(_BASE_EDGE_SEQUENCE) <= set(_EDGE_NODE_CEILINGS)


def test_pipeline_polars_version_pin_reminder() -> None:
    """Ceilings are calibrated per Polars version — recalibrate on upgrade.

    This test pins the Polars minor version the ceilings were measured on.
    When it fails after a Polars upgrade: re-run with RWA_PRINT_EDGE_NODES=1,
    re-pin _EDGE_NODE_CEILINGS, and update this version string.
    """
    assert pl.__version__.startswith("1.37"), (
        f"Polars {pl.__version__}: plan-node ceilings in this module were "
        "measured on 1.37 — recalibrate (see module docstring) before bumping "
        "this pin."
    )
