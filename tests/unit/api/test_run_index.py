"""Unit tests for the calculation run index (rwa_calc.api.run_index).

The index answers "has this exact calculation already been run on this exact
data?" so the reconciliation flow can reuse a cached run instead of re-running
the pipeline. Reuse must be *conservative*: any parameter difference, any input
file change (mtime, size, added, removed), a failed run, or a vanished results
parquet must all miss.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api import run_index
from rwa_calc.api.models import CalculationResponse, PerformanceMetrics, SummaryStatistics

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clean_index() -> None:
    """Each test starts from an empty in-process index."""
    run_index.clear()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data directory with two parquet inputs (one nested, like config/)."""
    root = tmp_path / "data"
    (root / "config").mkdir(parents=True)
    pl.DataFrame({"id": ["1"]}).write_parquet(root / "exposures.parquet")
    pl.DataFrame({"id": ["1"]}).write_parquet(root / "config" / "model_permissions.parquet")
    return root


@pytest.fixture
def response(tmp_path: Path) -> CalculationResponse:
    """A successful CalculationResponse backed by a real results parquet."""
    results = tmp_path / "cache" / "last_results.parquet"
    results.parent.mkdir(parents=True)
    pl.DataFrame({"exposure_reference": ["LN-1"], "rwa_final": [1.0]}).write_parquet(results)
    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("100"),
            total_rwa=Decimal("50"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=results,
    )


def _fingerprint(data_dir: Path, **overrides: object) -> run_index.CalculationFingerprint:
    params: dict = {
        "data_path": data_dir,
        "framework": "CRR",
        "reporting_date": date(2025, 1, 1),
        "permission_mode": "standardised",
        "data_format": "parquet",
    }
    params.update(overrides)
    return run_index.compute_fingerprint(**params)


# =============================================================================
# Fingerprint behaviour
# =============================================================================


class TestComputeFingerprint:
    def test_stable_for_unchanged_inputs(self, data_dir: Path) -> None:
        assert _fingerprint(data_dir) == _fingerprint(data_dir)

    def test_signature_covers_nested_files(self, data_dir: Path) -> None:
        rels = {rel for rel, _, _ in _fingerprint(data_dir).data_signature}
        assert rels == {"exposures.parquet", "config/model_permissions.parquet"}

    def test_csv_format_signs_csv_files_only(self, data_dir: Path) -> None:
        (data_dir / "loans.csv").write_text("id\n1\n")
        rels = {rel for rel, _, _ in _fingerprint(data_dir, data_format="csv").data_signature}
        assert rels == {"loans.csv"}


# =============================================================================
# Register / find
# =============================================================================


class TestFindReusable:
    def test_roundtrip_hit(self, data_dir: Path, response: CalculationResponse) -> None:
        fp = _fingerprint(data_dir)
        run_index.register_calculation(fp, "run-1", response)

        hit = run_index.find_reusable(_fingerprint(data_dir))

        assert hit is not None
        assert hit.run_id == "run-1"
        assert hit.response is response
        assert isinstance(hit.completed_at, datetime)

    def test_param_mismatch_misses(self, data_dir: Path, response: CalculationResponse) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        assert run_index.find_reusable(_fingerprint(data_dir, framework="BASEL_3_1")) is None
        assert run_index.find_reusable(_fingerprint(data_dir, permission_mode="irb")) is None
        assert (
            run_index.find_reusable(_fingerprint(data_dir, reporting_date=date(2025, 6, 30)))
            is None
        )

    def test_data_file_touch_misses(self, data_dir: Path, response: CalculationResponse) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        target = data_dir / "exposures.parquet"
        stat = target.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_data_file_content_change_misses(
        self, data_dir: Path, response: CalculationResponse
    ) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        pl.DataFrame({"id": ["1", "2"]}).write_parquet(data_dir / "exposures.parquet")

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_data_file_added_misses(self, data_dir: Path, response: CalculationResponse) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        pl.DataFrame({"id": ["9"]}).write_parquet(data_dir / "collateral.parquet")

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_data_file_removed_misses(self, data_dir: Path, response: CalculationResponse) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        (data_dir / "config" / "model_permissions.parquet").unlink()

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_failed_run_never_registered(
        self, data_dir: Path, response: CalculationResponse
    ) -> None:
        failed = CalculationResponse(
            success=False,
            framework=response.framework,
            reporting_date=response.reporting_date,
            summary=response.summary,
            results_path=response.results_path,
        )
        run_index.register_calculation(_fingerprint(data_dir), "run-1", failed)

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_deleted_results_parquet_misses(
        self, data_dir: Path, response: CalculationResponse
    ) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        Path(response.results_path).unlink()

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_latest_registration_wins(self, data_dir: Path, response: CalculationResponse) -> None:
        fp = _fingerprint(data_dir)
        run_index.register_calculation(fp, "run-1", response)
        run_index.register_calculation(fp, "run-2", response)

        hit = run_index.find_reusable(fp)

        assert hit is not None
        assert hit.run_id == "run-2"


class TestFindLatestForParams:
    """Signature-blind lookup backing the UI's 'input data changed' note."""

    def test_hit_when_only_data_changed(
        self, data_dir: Path, response: CalculationResponse
    ) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        pl.DataFrame({"id": ["1", "2"]}).write_parquet(data_dir / "exposures.parquet")
        stale_fp = _fingerprint(data_dir)

        assert run_index.find_reusable(stale_fp) is None  # the fresh lookup misses...
        hit = run_index.find_latest_for_params(stale_fp)  # ...but the params still match

        assert hit is not None
        assert hit.run_id == "run-1"

    def test_miss_when_params_differ(self, data_dir: Path, response: CalculationResponse) -> None:
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)

        stale_fp = _fingerprint(data_dir, framework="BASEL_3_1")

        assert run_index.find_latest_for_params(stale_fp) is None


# =============================================================================
# Persistence — the index survives a restart
# =============================================================================


def _response_at(tmp_path: Path, run_id: str, completed_at: datetime) -> CalculationResponse:
    """A successful response with a real results parquet and a pinned timestamp."""
    results = tmp_path / "state" / "runs" / run_id / "last_results.parquet"
    results.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"exposure_reference": [run_id], "rwa_final": [1.0]}).write_parquet(results)
    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("100"),
            total_rwa=Decimal("50"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=results,
        performance=PerformanceMetrics(
            started_at=completed_at,
            completed_at=completed_at,
            duration_seconds=1.0,
            exposure_count=1,
        ),
    )


class TestPersistence:
    def test_roundtrip_across_restart(
        self, tmp_path: Path, data_dir: Path, response: CalculationResponse
    ) -> None:
        # Arrange — persistence on; one indexed run.
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)

        # Act — simulate a process restart: memory gone, then reload from disk.
        run_index.clear()
        assert run_index.find_reusable(_fingerprint(data_dir)) is None  # really gone
        run_index.configure_persistence(state)

        # Assert — the run is reusable again, with Decimal fidelity preserved.
        hit = run_index.find_reusable(_fingerprint(data_dir))
        assert hit is not None
        assert hit.run_id == "run-1"
        assert hit.response.success is True
        assert hit.response.summary.total_rwa == Decimal("50")
        assert hit.response.framework == "CRR"
        assert hit.response.reporting_date == date(2025, 1, 1)

    def test_corrupt_persist_file_is_ignored(self, tmp_path: Path, data_dir: Path) -> None:
        state = tmp_path / "state"
        state.mkdir()
        (state / "run_index.json").write_text("{not json", encoding="utf-8")

        run_index.configure_persistence(state)  # must not raise

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_dead_results_are_dropped_on_load(
        self, tmp_path: Path, data_dir: Path, response: CalculationResponse
    ) -> None:
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        Path(response.results_path).unlink()

        run_index.clear()
        run_index.configure_persistence(state)

        assert run_index.find_reusable(_fingerprint(data_dir)) is None

    def test_cap_evicts_oldest_entry(self, tmp_path: Path, data_dir: Path) -> None:
        # Arrange — one more distinct fingerprint than the cap, oldest first.
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        base = datetime(2026, 7, 10, 12, 0, 0)
        dates = [date(2025, 1, d) for d in range(1, run_index.MAX_INDEXED_RUNS + 2)]
        for i, d in enumerate(dates):
            run_index.register_calculation(
                _fingerprint(data_dir, reporting_date=d),
                f"run-{i}",
                _response_at(tmp_path, f"run-{i}", base.replace(minute=i)),
            )

        # Assert — the oldest fell out; the newest survive (in memory and on disk).
        assert run_index.find_reusable(_fingerprint(data_dir, reporting_date=dates[0])) is None
        assert run_index.find_reusable(_fingerprint(data_dir, reporting_date=dates[-1])) is not None
        run_index.clear()
        run_index.configure_persistence(state)
        assert run_index.find_reusable(_fingerprint(data_dir, reporting_date=dates[0])) is None
        assert run_index.find_reusable(_fingerprint(data_dir, reporting_date=dates[-1])) is not None

    def test_startup_sweep_removes_orphan_run_dirs(self, tmp_path: Path, data_dir: Path) -> None:
        # Arrange — one referenced run dir and one orphan under the runs root.
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        response = _response_at(tmp_path, "run-1", datetime(2026, 7, 10, 12, 0, 0))
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)
        orphan = state / "runs" / "dead-run"
        orphan.mkdir(parents=True)
        (orphan / "last_results.parquet").write_bytes(b"junk")

        # Act — restart: the sweep runs at configure time.
        run_index.clear()
        run_index.configure_persistence(state)

        # Assert — the orphan is gone; the referenced run dir survives.
        assert not orphan.exists()
        assert Path(response.results_path).exists()
        assert run_index.find_reusable(_fingerprint(data_dir)) is not None

    def test_entries_lists_loaded_runs(
        self, tmp_path: Path, data_dir: Path, response: CalculationResponse
    ) -> None:
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        run_index.register_calculation(_fingerprint(data_dir), "run-1", response)

        run_index.clear()
        run_index.configure_persistence(state)

        assert [e.run_id for e in run_index.entries()] == ["run-1"]

    def test_run_cache_dir_under_configured_root(self, tmp_path: Path) -> None:
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        assert run_index.run_cache_dir("abc") == state / "runs" / "abc"
        run_index.clear()
        assert run_index.run_cache_dir("abc") is None  # unconfigured -> caller falls back
