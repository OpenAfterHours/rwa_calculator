"""Tests for the materialise module — disk-spill and in-memory strategies."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.materialise import (
    _spill_files,
    cleanup_spill_files,
    materialise_barrier,
    materialise_branches,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cpu_config() -> CalculationConfig:
    """Config with cpu engine — uses in-memory collect."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31), collect_engine="cpu")


@pytest.fixture()
def streaming_config(tmp_path: Path) -> CalculationConfig:
    """Config with streaming engine — uses disk-spill via sink_parquet."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        collect_engine="streaming",
        spill_dir=tmp_path,
    )


@pytest.fixture(autouse=True)
def _cleanup_spill():
    """Ensure spill files are cleaned up after each test."""
    yield
    cleanup_spill_files()


def _sample_lf() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "id": [1, 2, 3],
            "value": [10.0, 20.0, 30.0],
        }
    )


# ---------------------------------------------------------------------------
# materialise_barrier
# ---------------------------------------------------------------------------


class TestMaterialiseBarrier:
    """Tests for materialise_barrier."""

    def test_cpu_mode_returns_correct_data(self, cpu_config: CalculationConfig) -> None:
        lf = _sample_lf()
        result = materialise_barrier(lf, cpu_config, "test_cpu")
        df = result.collect()

        assert df.shape == (3, 2)
        assert df["id"].to_list() == [1, 2, 3]
        assert df["value"].to_list() == [10.0, 20.0, 30.0]

    def test_streaming_mode_returns_correct_data(self, streaming_config: CalculationConfig) -> None:
        lf = _sample_lf()
        result = materialise_barrier(lf, streaming_config, "test_streaming")
        df = result.collect()

        assert df.shape == (3, 2)
        assert df["id"].to_list() == [1, 2, 3]
        assert df["value"].to_list() == [10.0, 20.0, 30.0]

    def test_streaming_mode_creates_spill_file(
        self, streaming_config: CalculationConfig, tmp_path: Path
    ) -> None:
        lf = _sample_lf()
        materialise_barrier(lf, streaming_config, "test_spill")

        parquet_files = list(tmp_path.glob("rwa_test_spill_*.parquet"))
        assert len(parquet_files) >= 1

    def test_cpu_mode_no_spill_files(self, cpu_config: CalculationConfig, tmp_path: Path) -> None:
        lf = _sample_lf()
        materialise_barrier(lf, cpu_config, "test_no_spill")

        parquet_files = list(tmp_path.glob("rwa_*.parquet"))
        assert len(parquet_files) == 0

    def test_streaming_preserves_schema(self, streaming_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "str_col": ["a", "b"],
                "int_col": [1, 2],
                "float_col": [1.5, 2.5],
                "bool_col": [True, False],
            }
        )
        result = materialise_barrier(lf, streaming_config, "schema_test")
        schema = result.collect_schema()

        assert schema["str_col"] == pl.String
        assert schema["int_col"] == pl.Int64
        assert schema["float_col"] == pl.Float64
        assert schema["bool_col"] == pl.Boolean

    def test_empty_lazyframe(self, streaming_config: CalculationConfig) -> None:
        lf = pl.LazyFrame({"id": pl.Series([], dtype=pl.Int64)})
        result = materialise_barrier(lf, streaming_config, "empty_test")
        df = result.collect()

        assert df.shape == (0, 1)
        assert df.schema["id"] == pl.Int64


# ---------------------------------------------------------------------------
# materialise_branches
# ---------------------------------------------------------------------------


class TestMaterialiseBranches:
    """Tests for materialise_branches."""

    def test_cpu_mode_returns_correct_data(self, cpu_config: CalculationConfig) -> None:
        branches = [
            pl.LazyFrame({"id": [1], "val": [10.0]}),
            pl.LazyFrame({"id": [2], "val": [20.0]}),
            pl.LazyFrame({"id": [3], "val": [30.0]}),
        ]
        results = materialise_branches(branches, cpu_config, ["sa", "irb", "slotting"])

        assert len(results) == 3
        assert all(isinstance(r, pl.DataFrame) for r in results)
        assert results[0]["id"].to_list() == [1]
        assert results[1]["id"].to_list() == [2]
        assert results[2]["id"].to_list() == [3]

    def test_streaming_mode_returns_correct_data(self, streaming_config: CalculationConfig) -> None:
        branches = [
            pl.LazyFrame({"id": [1], "val": [10.0]}),
            pl.LazyFrame({"id": [2], "val": [20.0]}),
            pl.LazyFrame({"id": [3], "val": [30.0]}),
        ]
        results = materialise_branches(branches, streaming_config, ["sa", "irb", "slotting"])

        assert len(results) == 3
        assert results[0]["id"].to_list() == [1]
        assert results[1]["val"].to_list() == [20.0]
        assert results[2]["id"].to_list() == [3]

    def test_streaming_mode_creates_spill_files(
        self, streaming_config: CalculationConfig, tmp_path: Path
    ) -> None:
        branches = [
            pl.LazyFrame({"id": [1]}),
            pl.LazyFrame({"id": [2]}),
        ]
        materialise_branches(branches, streaming_config, ["a", "b"])

        parquet_files = list(tmp_path.glob("rwa_*.parquet"))
        assert len(parquet_files) >= 2


# ---------------------------------------------------------------------------
# cleanup_spill_files
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for cleanup_spill_files."""

    def test_cleanup_removes_files(
        self, streaming_config: CalculationConfig, tmp_path: Path
    ) -> None:
        lf = _sample_lf()
        materialise_barrier(lf, streaming_config, "cleanup_test")

        parquet_files = list(tmp_path.glob("rwa_*.parquet"))
        assert len(parquet_files) >= 1

        cleanup_spill_files()

        remaining = list(tmp_path.glob("rwa_*.parquet"))
        assert len(remaining) == 0
        assert len(_spill_files) == 0

    def test_cleanup_is_idempotent(self) -> None:
        cleanup_spill_files()
        cleanup_spill_files()  # Should not raise

    def test_cleanup_handles_already_deleted_files(
        self, streaming_config: CalculationConfig, tmp_path: Path
    ) -> None:
        lf = _sample_lf()
        materialise_barrier(lf, streaming_config, "already_deleted")

        # Manually delete the file before cleanup
        for f in tmp_path.glob("rwa_*.parquet"):
            f.unlink()

        # Should not raise
        cleanup_spill_files()
        assert len(_spill_files) == 0
