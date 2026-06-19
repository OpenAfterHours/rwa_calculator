"""
Shared pipeline plumbing for the P1.190 F-IRB foundation-collateral scenarios.

Pipeline position:
    (test fixtures) -> build_p1_190_bundle -> PipelineOrchestrator.run_with_data

Key responsibilities:
- Provide scenario-agnostic result-row helpers (`find_loan_rows`, `first`) shared
  across the CRR and Basel 3.1 P1.190 acceptance tests (and the P1.165 receivables
  test, which reuses the same row-lookup plumbing).
- Build the RawDataBundle for a P1.190 scenario from its parquet fixtures, wiring the
  facility -> loan mapping so facility-level collateral flows through to the loan.

This is a plain importable module (NOT a conftest) so both tests/acceptance/crr/ and
tests/acceptance/basel31/ can import it without cross-directory conftest coupling.

References:
    - PRA PS1/26 Art. 230 / CRR Art. 230: F-IRB Foundation Collateral Method
    - IMPLEMENTATION_PLAN.md: P1.190 (and P1.165 row-lookup reuse)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "p1_190"


# ---------------------------------------------------------------------------
# Result-row helpers (scenario-agnostic)
# ---------------------------------------------------------------------------


def find_loan_rows(results: AggregatedResultBundle, loan_ref: str) -> list[dict]:
    """Return all result rows containing loan_ref in exposure_reference."""
    rows: list[dict] = []
    for lf in [results.sa_results, results.irb_results, results.slotting_results]:
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        rows.extend(df.to_dicts())
    return rows


def first(rows: list[dict], field: str) -> Any:
    """Return the first non-null value of field from the result rows."""
    for r in rows:
        v = r.get(field)
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def build_p1_190_bundle(scenario: str, fac_ref: str, loan_ref: str) -> RawDataBundle:
    """
    Build the RawDataBundle for a P1.190 scenario from its parquet fixtures.

    Wires an empty lending-mappings frame and a single facility -> loan mapping so
    facility-level collateral flows through to the loan exposure via the CRM
    facility lookup. The caller selects the CRR vs Basel 3.1 config and runs the
    pipeline; the framework choice and refs stay visible in the test file because
    they are the load-bearing per-scenario inputs.
    """
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
