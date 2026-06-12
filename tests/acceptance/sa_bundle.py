"""
Shared SA loan-bundle assembly helper for acceptance tests.

Several single-factor SA acceptance scenarios (P1.99, P1.100, P1.121, P2.47)
share an identical RawDataBundle-assembly block: scan the scenario-local
counterparty / loan / rating parquets, supply an empty lending_mappings frame,
and construct a RawDataBundle whose facilities and facility_mappings are empty
typed LazyFrames (loan-only scenarios). This helper extracts that block so each
test fixture keeps only its own config, pipeline run, and result filtering.

References:
    - tests/fixtures/<pcode>/<pcode>.py: per-scenario fixture builders
    - src/rwa_calc/contracts/bundles.py: RawDataBundle
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from pathlib import Path


def build_sa_loan_bundle(fixtures_dir: Path) -> RawDataBundle:
    """
    Assemble the shared loan-only RawDataBundle for an SA acceptance scenario.

    Scans counterparty.parquet / loan.parquet / rating.parquet from
    ``fixtures_dir``, supplies an empty lending_mappings frame, and constructs a
    RawDataBundle whose facilities and facility_mappings are empty typed
    LazyFrames (no facilities in these single-factor loan scenarios).

    Args:
        fixtures_dir: Directory holding the scenario-local parquet fixtures.

    Returns:
        A RawDataBundle ready to feed PipelineOrchestrator.run_with_data.
    """
    counterparties = pl.scan_parquet(fixtures_dir / "counterparty.parquet")
    loans = pl.scan_parquet(fixtures_dir / "loan.parquet")
    ratings = pl.scan_parquet(fixtures_dir / "rating.parquet")

    lending_mappings: pl.LazyFrame = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=lending_mappings,
        ratings=ratings,
    )
