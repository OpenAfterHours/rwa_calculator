"""
Shared pipeline plumbing for the P1.235 FIRB FCM eligibility-gate scenarios.

Pipeline position:
    (test fixtures) -> build_p1_235_bundle -> PipelineOrchestrator.run_with_data

Key responsibilities:
- Build the RawDataBundle for a P1.235 scenario from its parquet fixtures, wiring
  the facility -> loan mapping so facility-level collateral flows through to the
  loan exposure.
- Reuse the scenario-agnostic result-row helpers from the P1.190 module.

This is a plain importable module (NOT a conftest) so both tests/acceptance/crr/
and tests/acceptance/basel31/ can import it without cross-directory conftest coupling.

References:
    - CRR/PS1-26 Art. 199(2)/(5)/(6): FIRB FCM collateral eligibility.
    - IMPLEMENTATION_PLAN.md: P1.235.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle

# Re-export the shared row helpers (same lookup plumbing as P1.190).
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows, first  # noqa: F401
from tests.fixtures.raw_bundle import make_raw_bundle

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "p1_235"


def build_p1_235_bundle(scenario: str, fac_ref: str, loan_ref: str) -> RawDataBundle:
    """Build the RawDataBundle for a P1.235 scenario from its parquet fixtures."""
    empty_mappings_lf = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings_lf = pl.LazyFrame(
        {
            "parent_facility_reference": [fac_ref],
            "child_reference": [loan_ref],
            "child_type": ["loan"],
        },
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        },
    )

    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / f"facility_{scenario}.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / f"loan_{scenario}.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / f"counterparty_{scenario}.parquet"),
        collateral=pl.scan_parquet(_FIXTURES_DIR / f"collateral_{scenario}.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / f"rating_{scenario}.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / f"model_permission_{scenario}.parquet"),
        facility_mappings=facility_mappings_lf,
        lending_mappings=empty_mappings_lf,
    )
