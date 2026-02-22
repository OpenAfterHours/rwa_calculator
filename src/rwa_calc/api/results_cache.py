"""
Results cache for streaming RWA results to parquet.

CachedResults: Frozen dataclass holding paths to parquet files with lazy scan accessors
ResultsCache: Manages cache directory lifecycle — sink, load, paginate

Eliminates in-memory materialization by sinking results directly to parquet
and scanning lazily everywhere else. Peak memory drops from ~3x to ~1x dataset size.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


# =============================================================================
# Cached Results Handle
# =============================================================================


@dataclass(frozen=True)
class CachedResults:
    """
    Handle to cached parquet results with lazy scan accessors.

    Holds paths to parquet files — no data is loaded until scan methods are called.

    Attributes:
        results_path: Path to main results parquet file
        summary_by_class_path: Path to class summary parquet (or None)
        summary_by_approach_path: Path to approach summary parquet (or None)
        metadata_path: Path to metadata JSON file
    """

    results_path: Path
    summary_by_class_path: Path | None = None
    summary_by_approach_path: Path | None = None
    metadata_path: Path | None = None

    def scan_results(self) -> pl.LazyFrame:
        """Lazy-scan the results parquet file."""
        return pl.scan_parquet(self.results_path)

    def scan_summary_by_class(self) -> pl.LazyFrame | None:
        """Lazy-scan the class summary parquet, or None if not available."""
        if self.summary_by_class_path and self.summary_by_class_path.exists():
            return pl.scan_parquet(self.summary_by_class_path)
        return None

    def scan_summary_by_approach(self) -> pl.LazyFrame | None:
        """Lazy-scan the approach summary parquet, or None if not available."""
        if self.summary_by_approach_path and self.summary_by_approach_path.exists():
            return pl.scan_parquet(self.summary_by_approach_path)
        return None


# =============================================================================
# Results Cache Manager
# =============================================================================


class ResultsCache:
    """
    Manages the cache directory lifecycle for RWA results.

    Sinks LazyFrames to parquet via streaming, loads cached handles
    without reading data, and provides paginated access.

    Usage:
        cache = ResultsCache(Path(".cache"))
        cached = cache.sink_results(results_lf, summary_class_lf, summary_approach_lf, metadata)
        lf = cached.scan_results()
        page = cache.get_page(lf, offset=0, page_size=100)
    """

    def __init__(self, cache_dir: Path) -> None:
        """
        Initialize cache with directory path, creating it if needed.

        Args:
            cache_dir: Directory for cached parquet files
        """
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        """Return the cache directory path."""
        return self._cache_dir

    def sink_results(
        self,
        results: pl.LazyFrame,
        summary_by_class: pl.LazyFrame | None = None,
        summary_by_approach: pl.LazyFrame | None = None,
        metadata: dict | None = None,
    ) -> CachedResults:
        """
        Stream results to parquet, collect small summaries eagerly, write metadata.

        Falls back to collect().write_parquet() if sink_parquet() fails.

        Args:
            results: Main results LazyFrame (streamed to parquet)
            summary_by_class: Optional class summary LazyFrame (collected eagerly)
            summary_by_approach: Optional approach summary LazyFrame (collected eagerly)
            metadata: Optional metadata dict written as JSON

        Returns:
            CachedResults handle with paths to all cached files
        """
        results_path = self._cache_dir / "last_results.parquet"
        metadata_path = self._cache_dir / "last_results_meta.json"
        class_path = self._cache_dir / "last_summary_by_class.parquet"
        approach_path = self._cache_dir / "last_summary_by_approach.parquet"

        # Sink main results to parquet via streaming
        self._sink_or_collect(results, results_path)

        # Collect small summary frames eagerly (they're tiny)
        class_out = None
        if summary_by_class is not None:
            try:
                summary_by_class.collect().write_parquet(class_path)
                class_out = class_path
            except Exception:
                logger.warning("Failed to write summary_by_class parquet")

        approach_out = None
        if summary_by_approach is not None:
            try:
                summary_by_approach.collect().write_parquet(approach_path)
                approach_out = approach_path
            except Exception:
                logger.warning("Failed to write summary_by_approach parquet")

        # Write metadata JSON
        if metadata is not None:
            metadata_path.write_text(json.dumps(metadata, indent=2))

        return CachedResults(
            results_path=results_path,
            summary_by_class_path=class_out,
            summary_by_approach_path=approach_out,
            metadata_path=metadata_path if metadata is not None else None,
        )

    def load_cached(self) -> CachedResults | None:
        """
        Load cached result handles without reading any data.

        Returns:
            CachedResults if cache exists, None otherwise
        """
        results_path = self._cache_dir / "last_results.parquet"
        if not results_path.exists():
            return None

        metadata_path = self._cache_dir / "last_results_meta.json"
        class_path = self._cache_dir / "last_summary_by_class.parquet"
        approach_path = self._cache_dir / "last_summary_by_approach.parquet"

        return CachedResults(
            results_path=results_path,
            summary_by_class_path=class_path if class_path.exists() else None,
            summary_by_approach_path=approach_path if approach_path.exists() else None,
            metadata_path=metadata_path if metadata_path.exists() else None,
        )

    def get_page(
        self,
        lazy: pl.LazyFrame,
        offset: int,
        page_size: int,
    ) -> pl.DataFrame:
        """
        Materialize a single page of results from a LazyFrame.

        Args:
            lazy: LazyFrame to paginate
            offset: Row offset (0-based)
            page_size: Number of rows to return

        Returns:
            DataFrame with the requested page of results
        """
        return lazy.slice(offset, page_size).collect()

    def _sink_or_collect(self, lf: pl.LazyFrame, path: Path) -> None:
        """
        Attempt streaming sink_parquet; fall back to collect + write_parquet.

        Args:
            lf: LazyFrame to write
            path: Output parquet file path
        """
        try:
            lf.sink_parquet(path)
        except Exception:
            logger.warning(
                "sink_parquet() failed, falling back to collect().write_parquet()"
            )
            lf.collect().write_parquet(path)
