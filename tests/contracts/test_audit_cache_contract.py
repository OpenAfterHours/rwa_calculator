"""Contract tests for the opt-in audit cache parquet layout.

Pins the columns each artifact must expose, so silent schema drift in the CRM
processor or output aggregator does not break downstream consumers that
read these parquet files directly (regulators, auditors, internal MI tooling).

If a column is intentionally removed, this test must be updated in the same PR
as the production change — the failing assertion serves as the gate.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import create_test_pipeline

# Minimum column set per artifact. Additions are allowed (the producer may
# carry more columns); silent removals are not. Order is irrelevant.
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "collateral_haircuts.parquet": {
        "collateral_reference",
        "collateral_type",
        "exposure_currency",
        "collateral_haircut",
        "fx_haircut",
        "value_after_haircut",
    },
    "collateral_allocation.parquet": {
        "exposure_reference",
        "counterparty_reference",
        "approach",
        "ead_gross",
        "total_collateral_for_lgd",
        "collateral_coverage_pct",
        "collateral_adjusted_value",
        "collateral_market_value",
        "lgd_post_crm",
        "ead_after_collateral",
    },
    "crm_audit.parquet": {
        "exposure_reference",
        "counterparty_reference",
        "approach",
        "ead_gross",
        "ead_final",
        "lgd_pre_crm",
        "lgd_post_crm",
        "crm_calculation",
    },
    # Tier-2 per-stage audits — sunk by pipeline.py stage helpers.
    "classification_audit.parquet": {
        "exposure_reference",
        "counterparty_reference",
        "cp_entity_type",
        "exposure_class",
        "approach",
        "is_defaulted",
        "classification_reason",
    },
    "rating_inheritance.parquet": {
        "counterparty_reference",
        "cqs",
        "pd",
        "external_cqs",
        "internal_pd",
    },
    # Tier-3 equity calculator audit.
    "equity_calculation_audit.parquet": {
        "exposure_reference",
        "equity_type",
        "ead_final",
        "risk_weight",
        "rwa",
    },
    # Tier-1 pre-floor per-approach views (from AggregatedResultBundle).
    "sa_results.parquet": {
        "exposure_reference",
        "approach_applied",
        "risk_weight",
        "rwa_final",
    },
    "irb_results.parquet": {
        "exposure_reference",
        "approach_applied",
        "risk_weight",
        "rwa_final",
    },
    "slotting_results.parquet": {
        "exposure_reference",
        "approach_applied",
        "risk_weight",
        "rwa_final",
    },
    "equity_results.parquet": {
        "exposure_reference",
        "equity_type",
        "ead_final",
        "risk_weight",
        "rwa",
    },
    # CRR-only: SME / infrastructure factor impact.
    "supporting_factor_impact.parquet": {
        "exposure_reference",
        "exposure_class",
        "is_sme",
        "is_infrastructure",
        "supporting_factor",
        "supporting_factor_applied",
        "rwa_pre_factor",
        "rwa_post_factor",
        "supporting_factor_impact",
    },
}


@pytest.fixture(scope="module")
def cached_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the test pipeline once with audit_cache_dir set and reuse its output.

    Module-scoped to avoid running the full pipeline once per parametrize case.
    """
    cache_root = tmp_path_factory.mktemp("audit_cache_contract")
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=cache_root,
    )
    create_test_pipeline().run(cfg)

    run_dirs = [p for p in cache_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    return run_dirs[0]


@pytest.mark.parametrize(
    ("artifact", "expected_columns"),
    list(REQUIRED_COLUMNS.items()),
)
def test_artifact_carries_required_columns(
    cached_run_dir: Path,
    artifact: str,
    expected_columns: set[str],
) -> None:
    """Each artifact must expose the documented column set."""
    parquet = cached_run_dir / artifact
    assert parquet.is_file(), f"missing artifact {artifact}"

    columns = set(pl.read_parquet(parquet).columns)
    missing = expected_columns - columns
    assert not missing, f"{artifact} missing columns: {missing}"
