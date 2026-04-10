"""
Materialization strategies for pipeline collect barriers.

Pipeline position:
    Used by CRMProcessor and PipelineOrchestrator at every .collect() barrier

Key responsibilities:
- Replace raw .collect().lazy() with strategy-aware materialization
- Support disk-spill (streaming mode) for out-of-core datasets
- Support in-memory (cpu mode) for backward compatibility
- Manage temp file lifecycle

The pipeline has several points where lazy plans must be materialized to prevent
Polars optimizer issues (deep plan re-execution, segfaults on >500-node plans).
Previously these used .collect().lazy() which forces the full dataset into RAM.

This module provides two strategies controlled by config.collect_engine:
- "cpu": .collect().lazy() — existing behavior, full in-memory
- "streaming": sink_parquet → scan_parquet — caps memory at ~1 column batch
"""

from __future__ import annotations

import atexit
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)

# Module-level registry of temp files for cleanup
_spill_files: list[Path] = []


def materialise_barrier(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    label: str,
) -> pl.LazyFrame:
    """
    Materialise a LazyFrame at a pipeline barrier point.

    Replaces the pattern ``lf.collect().lazy()`` with a strategy that
    respects ``config.collect_engine``:

    - ``"cpu"``: In-memory collect (existing behavior).
    - ``"streaming"``: Sink to a temp parquet file, then scan it back.
      This caps peak memory to approximately one column-batch at a time.

    Args:
        lf: LazyFrame to materialise
        config: Calculation configuration (provides collect_engine and spill_dir)
        label: Human-readable label for temp file naming and logging

    Returns:
        A fresh LazyFrame backed by either in-memory data or a parquet scan
    """
    if config.collect_engine == "cpu":
        return lf.collect().lazy()

    # Streaming mode: sink to parquet for out-of-core support
    return _spill_to_disk(lf, config, label)


def materialise_branches(
    branches: list[pl.LazyFrame],
    config: CalculationConfig,
    labels: list[str],
) -> list[pl.DataFrame]:
    """
    Materialise multiple branches, replacing ``pl.collect_all()``.

    - ``"cpu"``: Uses ``pl.collect_all()`` which leverages CSE (Common
      Subexpression Elimination) to compute shared upstream plans once.
    - ``"streaming"``: Sinks each branch to parquet sequentially, then
      reads back as DataFrames. Peak memory = one branch at a time.

    Args:
        branches: LazyFrames to materialise
        config: Calculation configuration
        labels: Human-readable labels for each branch

    Returns:
        List of DataFrames in the same order as input branches
    """
    if config.collect_engine == "cpu":
        result: list[pl.DataFrame] = pl.collect_all(branches)
        return result

    # Streaming mode: sink each branch individually
    results: list[pl.DataFrame] = []
    for lf, label in zip(branches, labels, strict=True):
        scanned = _spill_to_disk(lf, config, label)
        results.append(scanned.collect())
    return results


def cleanup_spill_files() -> None:
    """Remove all temp parquet files created during materialization."""
    for path in _spill_files:
        try:
            if path.exists():
                path.unlink()
                logger.debug("Cleaned up spill file: %s", path)
        except OSError:
            logger.warning("Failed to clean up spill file: %s", path)
    _spill_files.clear()


def _spill_to_disk(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    label: str,
) -> pl.LazyFrame:
    """Sink a LazyFrame to a temp parquet file and scan it back.

    Falls back to in-memory collect if sink_parquet fails (e.g., unsupported
    expression types in the streaming engine).

    Args:
        lf: LazyFrame to sink
        config: Calculation configuration
        label: Label for temp file naming

    Returns:
        LazyFrame backed by the parquet scan
    """
    spill_dir = config.spill_dir if config.spill_dir is not None else None
    safe_label = label.replace("/", "_").replace(" ", "_")

    try:
        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".parquet",
            prefix=f"rwa_{safe_label}_",
            dir=spill_dir,
        )
        # Close the file descriptor — sink_parquet will write to the path
        import os

        os.close(fd)
        tmp_path = Path(tmp_path_str)

        lf.sink_parquet(tmp_path)
        _spill_files.append(tmp_path)
        logger.debug("Spilled %s to %s", label, tmp_path)
        return pl.scan_parquet(tmp_path)
    except Exception:
        logger.warning(
            "sink_parquet failed for %s, falling back to in-memory collect",
            label,
        )
        return lf.collect().lazy()


# Register cleanup at interpreter exit as a safety net
atexit.register(cleanup_spill_files)
