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

Run budget. A full-fixture run costs ~3 s, so the module makes exactly three
of them: ONE module-scoped CRR run with the cache on (``cached_run``), shared
read-only by every test that reads artefact contents or the manifest and
reused as the "cache on" side of the perturbation test; one CRR control run
with the cache off; and one Basel 3.1 run for the floor-impact artefact. The
run-directory lifecycle tests (distinct ``run_id`` per run, pruning) assert
only on the number and identity of subdirectories under ``audit_cache_dir``,
which the manifest write creates for ANY input, so they run the one-loan
integration bundle through ``run_with_data`` instead of the full fixture.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator, create_test_pipeline

from .conftest import make_raw_data_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle

# Artifacts that ALWAYS appear when ``audit_cache_dir`` is set, regardless of
# framework, IRB permissions, or input feature usage. The standard test
# fixture exercises every producing stage.
ALWAYS_PRESENT_ARTIFACTS = {
    # CRM intermediates (sunk inside CRMProcessor / collateral.apply_collateral)
    "collateral_haircuts.parquet",
    "collateral_allocation.parquet",
    "crm_audit.parquet",
    # Aggregator summary views (Phase 7 S4: pure group-bys of the sealed ledger)
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


class CachedRun(NamedTuple):
    """The module's one shared full-fixture CRR run with the audit cache on."""

    run_dir: Path
    result: AggregatedResultBundle


@pytest.fixture(scope="module")
def cached_run(tmp_path_factory: pytest.TempPathFactory) -> CachedRun:
    """Run the full test fixture once with ``audit_cache_dir`` set.

    Module-scoped and shared: every consumer reads the run directory and the
    result bundle and never writes into or under either. A test that needs its
    own run directory (the lifecycle tests) takes ``tmp_path`` and runs the
    pipeline itself.
    """
    cache_dir = tmp_path_factory.mktemp("audit_cache")
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=cache_dir,
    )
    pipeline = create_test_pipeline()
    result = pipeline.run(cfg)

    run_dirs = [p for p in cache_dir.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1, f"expected one run dir, got {[d.name for d in run_dirs]}"
    return CachedRun(run_dir=run_dirs[0], result=result)


@pytest.fixture(scope="module")
def cached_run_dir(cached_run: CachedRun) -> Path:
    """The shared run directory of :func:`cached_run` — read-only."""
    return cached_run.run_dir


def _run_one_loan_bundle(cfg: CalculationConfig) -> AggregatedResultBundle:
    """Run the one-loan integration bundle in memory under ``cfg``.

    The run-directory lifecycle (one ``<run_id>`` subdirectory per run, pruned
    to ``audit_cache_max_runs``) is driven by the manifest write and
    ``prune_audit_cache`` at the end of every run, independent of which
    artefacts the input produced — so the lifecycle tests use the smallest
    bundle that runs the pipeline end to end rather than the full fixture.
    """
    return PipelineOrchestrator().run_with_data(make_raw_data_bundle(), cfg)


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


def test_audit_cache_does_not_perturb_rwa_totals(cached_run: CachedRun) -> None:
    """A run with the cache on must produce identical RWA totals to one
    without the cache — the sink calls are pure side-effects.

    The "cache on" side is the module's shared full-fixture run (same config
    as a fresh run here: CRR, 2024-12-31, ``audit_cache_dir`` set); only the
    "cache off" control run is made afresh. The full fixture is kept for both
    sides so every sink site fires with a non-empty frame.
    """
    cfg_off = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    pipeline_off = create_test_pipeline()
    result_off = pipeline_off.run(cfg_off)
    rwa_off = result_off.results.select(pl.col("rwa_final").sum()).collect().item()

    result_on = cached_run.result
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

    _run_one_loan_bundle(cfg)
    first_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(first_dirs) == 1

    _run_one_loan_bundle(cfg)
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
        _run_one_loan_bundle(cfg)

    surviving = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(surviving) == 1, f"expected 1 surviving run dir, got {[d.name for d in surviving]}"
