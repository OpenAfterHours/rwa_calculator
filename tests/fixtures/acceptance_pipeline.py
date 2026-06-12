"""
Shared acceptance-pipeline test-data builder.

Pipeline position:
    (test fixtures) -> run_parquet_pipeline -> PipelineOrchestrator -> AggregatedResultBundle

Key responsibilities:
- Scan the standard four P-code parquet fixtures
  (counterparty / loan / rating / model_permission).
- Attach the empty lending/facility mapping frames and the empty facilities frame
  that the orchestrator requires but which P-code scenarios leave unused.
- Assemble the seven-keyword RawDataBundle and run the orchestrator under a
  caller-supplied CalculationConfig.

This collapses byte-identical bundle-assembly plumbing that was cloned across
the per-scenario acceptance tests. The per-scenario CalculationConfig factory
call stays in each test's _run_pipeline_pXXX() helper.

References:
- src/rwa_calc/contracts/bundles.py: RawDataBundle / AggregatedResultBundle
- src/rwa_calc/engine/pipeline.py: PipelineOrchestrator.run_with_data
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_calc.contracts.bundles import AggregatedResultBundle
    from rwa_calc.contracts.config import CalculationConfig


def run_parquet_pipeline(
    fixtures_dir: Path,
    config: CalculationConfig,
) -> AggregatedResultBundle:
    """Run the orchestrator over the standard four P-code parquet fixtures.

    Scans ``counterparty.parquet``, ``loan.parquet``, ``rating.parquet`` and
    ``model_permission.parquet`` from ``fixtures_dir``, attaches the empty
    lending/facility mapping frames and the empty facilities frame, assembles
    the RawDataBundle, and runs ``PipelineOrchestrator().run_with_data`` under
    ``config``.

    Returns the AggregatedResultBundle from the run.
    """
    # Minimal empty frames for unused input types
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
        }
    )

    counterparties = pl.scan_parquet(fixtures_dir / "counterparty.parquet")
    loans = pl.scan_parquet(fixtures_dir / "loan.parquet")
    ratings = pl.scan_parquet(fixtures_dir / "rating.parquet")
    model_permissions = pl.scan_parquet(fixtures_dir / "model_permission.parquet")

    bundle = make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=ratings,
        model_permissions=model_permissions,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)
