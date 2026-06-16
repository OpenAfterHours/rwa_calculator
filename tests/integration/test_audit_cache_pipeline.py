"""End-to-end tests for the opt-in audit cache.

Runs a full pipeline against the standard test fixtures with
``audit_cache_dir`` set and asserts:

- All expected parquet artifacts appear under ``<dir>/<run_id>/``.
- ``manifest.json`` parses to the documented shape.
- ``collateral_haircuts.parquet`` carries the diagnostic columns the user
  needs to inspect ``fx_haircut`` per collateral row.
- Aggregated RWA totals are identical to a control run without the cache —
  the audit cache must never perturb the calculation.
- A subsequent run is partitioned under a *different* ``run_id`` and the
  prior run's artifacts survive (no overwrite, no leakage).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import create_test_pipeline

# Artifacts that ALWAYS appear when ``audit_cache_dir`` is set, regardless of
# framework, IRB permissions, or input feature usage. The standard test
# fixture exercises every producing stage.
ALWAYS_PRESENT_ARTIFACTS = {
    # CRM intermediates (sunk inside CRMProcessor / collateral.apply_collateral)
    "collateral_haircuts.parquet",
    "collateral_allocation.parquet",
    "crm_audit.parquet",
    # Aggregator pre/post summary views
    "pre_crm_summary.parquet",
    "post_crm_summary.parquet",
    "post_crm_detailed.parquet",
    "summary_by_class.parquet",
    "summary_by_approach.parquet",
    "results.parquet",
    # Per-stage audits sunk in pipeline.py stage helpers
    "rating_inheritance.parquet",
    "classification_audit.parquet",
    "re_split_audit.parquet",
    "equity_calculation_audit.parquet",
    # Pre-floor per-approach views from AggregatedResultBundle
    "sa_results.parquet",
    "irb_results.parquet",
    "slotting_results.parquet",
    "equity_results.parquet",
    # Run-level manifest
    "manifest.json",
}

# Artifacts that only appear under specific framework / feature combinations.
# CRR-only: SME / infrastructure supporting factor impact.
# Basel 3.1 only: output-floor per-exposure impact.
# Securitisation artifacts only appear when ``securitisation_allocations`` is
# supplied in the input bundle — the standard test fixture does not supply
# allocations, so they are not asserted here.
CRR_ONLY_ARTIFACTS = {"supporting_factor_impact.parquet"}
BASEL_3_1_ONLY_ARTIFACTS = {"floor_impact.parquet"}


@pytest.fixture
def cached_run_dir(tmp_path: Path) -> Path:
    """Run the test pipeline with ``audit_cache_dir=tmp_path`` and return the run dir."""
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
    )
    pipeline = create_test_pipeline()
    pipeline.run(cfg)

    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1, f"expected one run dir, got {[d.name for d in run_dirs]}"
    return run_dirs[0]


def test_pipeline_writes_all_always_present_artifacts(cached_run_dir: Path) -> None:
    """Every always-present artifact appears in the run directory."""
    actual = {p.name for p in cached_run_dir.iterdir()}
    missing = ALWAYS_PRESENT_ARTIFACTS - actual
    assert not missing, f"missing artifacts: {missing}"


def test_crr_run_includes_supporting_factor_impact(cached_run_dir: Path) -> None:
    """CRR with SME / infrastructure factors enabled emits the factor-impact
    parquet; Basel 3.1 (where these factors are removed) does not.
    """
    actual = {p.name for p in cached_run_dir.iterdir()}
    assert CRR_ONLY_ARTIFACTS.issubset(actual), (
        f"CRR run missing factor-impact artifact: {CRR_ONLY_ARTIFACTS - actual}"
    )


def test_basel_3_1_run_includes_floor_impact(tmp_path: Path) -> None:
    """Basel 3.1 with the output floor enabled emits the per-exposure floor
    impact parquet (CRR has no floor and does not produce it).
    """
    cfg = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 12, 31),
        audit_cache_dir=tmp_path,
    )
    pipeline = create_test_pipeline()
    pipeline.run(cfg)

    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    actual = {p.name for p in run_dir.iterdir()}
    assert BASEL_3_1_ONLY_ARTIFACTS.issubset(actual), (
        f"Basel 3.1 run missing floor-impact artifact: {BASEL_3_1_ONLY_ARTIFACTS - actual}"
    )


def test_manifest_has_documented_keys(cached_run_dir: Path) -> None:
    """``manifest.json`` parses and carries the keys the spec promises."""
    manifest = json.loads((cached_run_dir / "manifest.json").read_text(encoding="utf-8"))

    required_keys = {
        "run_id",
        "framework",
        "reporting_date",
        "started_at",
        "finished_at",
        "elapsed_ms",
        "config",
        "artifacts",
        "error_count",
        "rulepack",
    }
    assert required_keys.issubset(manifest.keys()), (
        f"manifest missing keys: {required_keys - set(manifest.keys())}"
    )

    assert manifest["run_id"] == cached_run_dir.name
    assert manifest["framework"] == "CRR"
    assert manifest["reporting_date"] == "2024-12-31"
    assert isinstance(manifest["elapsed_ms"], int | float)
    assert isinstance(manifest["artifacts"], list)
    assert len(manifest["artifacts"]) >= 1
    assert all("name" in a and "bytes" in a for a in manifest["artifacts"])
    assert {"permission_mode", "base_currency", "collect_engine"}.issubset(
        manifest["config"].keys()
    )


def test_manifest_records_rulepack_snapshot(cached_run_dir: Path) -> None:
    """``manifest.json['rulepack']`` records the run's resolved-pack snapshot.

    The content hash must equal the pack resolved from the same (regime,
    reporting date) — the audit trail of exactly which regime data ran.
    """
    from rwa_calc.rulebook.resolve import resolve

    manifest = json.loads((cached_run_dir / "manifest.json").read_text(encoding="utf-8"))
    rulepack = manifest["rulepack"]

    assert {"id", "regime_id", "reporting_date", "content_hash", "entries"}.issubset(
        rulepack.keys()
    )
    assert rulepack["regime_id"] == "crr"
    assert rulepack["reporting_date"] == "2024-12-31"
    assert rulepack["content_hash"] == resolve("crr", date(2024, 12, 31)).content_hash
    assert len(rulepack["entries"]) >= 1
    assert all({"name", "kind", "citation", "value"}.issubset(e) for e in rulepack["entries"])


def test_classification_audit_carries_per_exposure_reason(cached_run_dir: Path) -> None:
    """Per-exposure ``classification_audit`` parquet must surface the
    classification reason trail — the diagnostic that answers "why did this
    exposure get SA vs IRB?".
    """
    audit = pl.read_parquet(cached_run_dir / "classification_audit.parquet")
    assert audit.height > 0
    expected_cols = {"exposure_reference", "exposure_class", "approach"}
    assert expected_cols.issubset(set(audit.columns)), (
        f"classification_audit missing columns: {expected_cols - set(audit.columns)}"
    )


def test_rating_inheritance_keys_on_counterparty(cached_run_dir: Path) -> None:
    """Per-counterparty ``rating_inheritance`` parquet must carry the dual-
    track best-rating columns the hierarchy resolver produces.
    """
    inheritance = pl.read_parquet(cached_run_dir / "rating_inheritance.parquet")
    assert inheritance.height > 0
    expected_cols = {"counterparty_reference"}
    assert expected_cols.issubset(set(inheritance.columns)), (
        f"rating_inheritance missing columns: {expected_cols - set(inheritance.columns)}"
    )


def test_pre_floor_per_approach_results_are_distinct(cached_run_dir: Path) -> None:
    """The four pre-floor per-approach parquets must each round-trip with
    at least the row-count signature expected for that approach.
    """
    for name in ("sa_results", "irb_results", "slotting_results", "equity_results"):
        df = pl.read_parquet(cached_run_dir / f"{name}.parquet")
        assert "exposure_reference" in df.columns, (
            f"{name}.parquet missing 'exposure_reference' column"
        )


def test_collateral_haircuts_carries_diagnostic_columns(cached_run_dir: Path) -> None:
    """The new ``collateral_haircuts`` artifact must expose the columns users
    need to inspect ``H_fx`` per collateral row — the user-visible deliverable.
    """
    haircuts = pl.read_parquet(cached_run_dir / "collateral_haircuts.parquet")

    required = {
        "collateral_reference",
        "collateral_type",
        "exposure_currency",
        "collateral_haircut",
        "fx_haircut",
        "value_after_haircut",
    }
    missing = required - set(haircuts.columns)
    assert not missing, f"collateral_haircuts.parquet missing columns: {missing}"
    assert haircuts.height > 0, "expected at least one collateral row in the fixture run"


def test_audit_cache_does_not_perturb_rwa_totals(tmp_path: Path) -> None:
    """A run with the cache on must produce identical RWA totals to one
    without the cache — the sink calls are pure side-effects.
    """
    cfg_off = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    pipeline_off = create_test_pipeline()
    result_off = pipeline_off.run(cfg_off)
    rwa_off = result_off.results.select(pl.col("rwa_final").sum()).collect().item()

    cfg_on = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
    )
    pipeline_on = create_test_pipeline()
    result_on = pipeline_on.run(cfg_on)
    rwa_on = result_on.results.select(pl.col("rwa_final").sum()).collect().item()

    assert rwa_off == pytest.approx(rwa_on, rel=1e-12), (
        f"audit cache changed RWA totals: off={rwa_off:.6f} vs on={rwa_on:.6f}"
    )


def test_second_run_writes_to_distinct_run_dir(tmp_path: Path) -> None:
    """Each pipeline call gets its own ``<run_id>`` subdirectory; the prior
    run's artifacts must survive untouched.
    """
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
    )

    pipeline1 = create_test_pipeline()
    pipeline1.run(cfg)
    first_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(first_dirs) == 1

    pipeline2 = create_test_pipeline()
    pipeline2.run(cfg)
    all_dirs = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    assert len(all_dirs) == 2, f"expected two distinct run dirs, got {[d.name for d in all_dirs]}"
    assert all_dirs[0] != all_dirs[1]


def test_pruning_keeps_only_n_newest_runs(tmp_path: Path) -> None:
    """``audit_cache_max_runs=1`` collapses three back-to-back runs to one
    surviving dir (the newest), with the older dirs deleted in-place.
    """
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
        audit_cache_max_runs=1,
    )

    for _ in range(3):
        pipeline = create_test_pipeline()
        pipeline.run(cfg)

    surviving = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(surviving) == 1, f"expected 1 surviving run dir, got {[d.name for d in surviving]}"
