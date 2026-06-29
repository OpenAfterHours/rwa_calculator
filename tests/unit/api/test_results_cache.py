"""Unit tests for the ResultsCache module.

Tests cover:
- ResultsCache: sink_results, load_cached, get_page
- CachedResults: scan accessors, path validation
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from rwa_calc.api.results_cache import CachedResults, ResultsCache

# =============================================================================
# CachedResults Tests
# =============================================================================


class TestCachedResults:
    """Tests for CachedResults scan accessors."""

    def test_scan_results_returns_lazyframe(self, tmp_path: Path) -> None:
        """scan_results should return a LazyFrame."""
        results_path = tmp_path / "results.parquet"
        pl.DataFrame({"a": [1, 2, 3]}).write_parquet(results_path)

        cached = CachedResults(results_path=results_path)
        lf = cached.scan_results()

        assert isinstance(lf, pl.LazyFrame)
        assert lf.collect().height == 3

    def test_scan_summary_by_class_returns_lazyframe(self, tmp_path: Path) -> None:
        """scan_summary_by_class should return LazyFrame when path exists."""
        results_path = tmp_path / "results.parquet"
        class_path = tmp_path / "class.parquet"
        pl.DataFrame({"a": [1]}).write_parquet(results_path)
        pl.DataFrame({"class": ["corporate"], "rwa": [100.0]}).write_parquet(class_path)

        cached = CachedResults(
            results_path=results_path,
            summary_by_class_path=class_path,
        )
        lf = cached.scan_summary_by_class()

        assert lf is not None
        assert isinstance(lf, pl.LazyFrame)

    def test_scan_summary_by_class_returns_none_when_no_path(self, tmp_path: Path) -> None:
        """scan_summary_by_class should return None when path is None."""
        results_path = tmp_path / "results.parquet"
        pl.DataFrame({"a": [1]}).write_parquet(results_path)

        cached = CachedResults(results_path=results_path)
        assert cached.scan_summary_by_class() is None

    def test_scan_summary_by_approach_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        """scan_summary_by_approach should return None when file doesn't exist."""
        results_path = tmp_path / "results.parquet"
        pl.DataFrame({"a": [1]}).write_parquet(results_path)

        cached = CachedResults(
            results_path=results_path,
            summary_by_approach_path=tmp_path / "nonexistent.parquet",
        )
        assert cached.scan_summary_by_approach() is None


# =============================================================================
# ResultsCache Tests
# =============================================================================


class TestResultsCache:
    """Tests for ResultsCache sink, load, and pagination."""

    def test_creates_cache_directory(self, tmp_path: Path) -> None:
        """Should create cache directory if it doesn't exist."""
        cache_dir = tmp_path / "new_cache"
        assert not cache_dir.exists()

        ResultsCache(cache_dir)
        assert cache_dir.exists()

    def test_sink_results_creates_parquet(self, tmp_path: Path) -> None:
        """sink_results should create a parquet file."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]})

        cached = cache.sink_results(results=lf)

        assert cached.results_path.exists()
        df = pl.read_parquet(cached.results_path)
        assert df.height == 3
        assert df.columns == ["x", "y"]

    def test_sink_results_with_summaries(self, tmp_path: Path) -> None:
        """sink_results should write summary parquet files."""
        cache = ResultsCache(tmp_path / "cache")
        results_lf = pl.LazyFrame({"a": [1, 2]})
        class_lf = pl.LazyFrame({"class": ["corp"], "rwa": [100.0]})
        approach_lf = pl.LazyFrame({"approach": ["SA"], "rwa": [100.0]})

        cached = cache.sink_results(
            results=results_lf,
            summary_by_class=class_lf,
            summary_by_approach=approach_lf,
        )

        assert cached.summary_by_class_path is not None
        assert cached.summary_by_class_path.exists()
        assert cached.summary_by_approach_path is not None
        assert cached.summary_by_approach_path.exists()

    def test_sink_and_scan_summary_by_class_method(self, tmp_path: Path) -> None:
        """sink_results round-trips the class-by-method summary parquet."""
        cache = ResultsCache(tmp_path / "cache")
        results_lf = pl.LazyFrame({"a": [1]})
        class_method_lf = pl.LazyFrame(
            {"exposure_class": ["corp"], "method": ["AIRB"], "total_rwa": [100.0]}
        )

        cached = cache.sink_results(results=results_lf, summary_by_class_method=class_method_lf)

        assert cached.summary_by_class_method_path is not None
        assert cached.summary_by_class_method_path.exists()
        scanned = cached.scan_summary_by_class_method()
        assert scanned is not None
        assert scanned.collect().get_column("method").to_list() == ["AIRB"]

    def test_load_cached_picks_up_class_method(self, tmp_path: Path) -> None:
        """load_cached re-discovers the class-by-method summary on disk."""
        cache = ResultsCache(tmp_path / "cache")
        cache.sink_results(
            results=pl.LazyFrame({"a": [1]}),
            summary_by_class_method=pl.LazyFrame(
                {"exposure_class": ["corp"], "method": ["STD"], "total_rwa": [50.0]}
            ),
        )

        loaded = cache.load_cached()

        assert loaded is not None
        assert loaded.summary_by_class_method_path is not None
        assert loaded.scan_summary_by_class_method().collect().height == 1

    def test_sink_with_none_summary_clears_stale_parquet(self, tmp_path: Path) -> None:
        """A later run that writes no summary clears a prior run's stale parquet.

        Guards against ``format_error_response`` (which sinks no summaries) leaving
        a previous successful run's summary on disk for ``load_cached`` to resurrect.
        """
        cache = ResultsCache(tmp_path / "cache")
        cache.sink_results(
            results=pl.LazyFrame({"a": [1]}),
            summary_by_class_method=pl.LazyFrame(
                {"exposure_class": ["corp"], "method": ["STD"], "total_rwa": [1.0]}
            ),
        )
        assert cache.load_cached().summary_by_class_method_path is not None

        # Second run produces no summary (e.g. an error run) -> stale file removed.
        cache.sink_results(results=pl.LazyFrame({"a": [2]}))

        assert cache.load_cached().summary_by_class_method_path is None

    def test_sink_results_writes_metadata(self, tmp_path: Path) -> None:
        """sink_results should write metadata JSON."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame({"a": [1]})
        meta = {"framework": "CRR", "total_rwa": 1000.0}

        cached = cache.sink_results(results=lf, metadata=meta)

        assert cached.metadata_path is not None
        assert cached.metadata_path.exists()
        loaded_meta = json.loads(cached.metadata_path.read_text())
        assert loaded_meta["framework"] == "CRR"

    def test_sink_results_no_metadata(self, tmp_path: Path) -> None:
        """sink_results without metadata should set metadata_path to None."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame({"a": [1]})

        cached = cache.sink_results(results=lf)

        assert cached.metadata_path is None

    def test_load_cached_returns_handles(self, tmp_path: Path) -> None:
        """load_cached should return CachedResults after sink."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame({"a": [1, 2, 3]})
        class_lf = pl.LazyFrame({"class": ["x"]})

        cache.sink_results(results=lf, summary_by_class=class_lf)
        loaded = cache.load_cached()

        assert loaded is not None
        assert loaded.results_path.exists()
        assert loaded.summary_by_class_path is not None

    def test_load_cached_returns_none_when_empty(self, tmp_path: Path) -> None:
        """load_cached should return None when no cache exists."""
        cache = ResultsCache(tmp_path / "empty_cache")

        assert cache.load_cached() is None

    def test_get_page_returns_slice(self, tmp_path: Path) -> None:
        """get_page should return the requested page of data."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame({"x": list(range(100))})
        cached = cache.sink_results(results=lf)

        page = cache.get_page(cached.scan_results(), offset=10, page_size=5)

        assert isinstance(page, pl.DataFrame)
        assert page.height == 5
        assert page["x"].to_list() == [10, 11, 12, 13, 14]

    def test_get_page_past_end(self, tmp_path: Path) -> None:
        """get_page past end of data should return empty or partial."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame({"x": [1, 2, 3]})
        cached = cache.sink_results(results=lf)

        page = cache.get_page(cached.scan_results(), offset=10, page_size=5)
        assert page.height == 0

    def test_sink_empty_lazyframe(self, tmp_path: Path) -> None:
        """Should handle sinking an empty LazyFrame."""
        cache = ResultsCache(tmp_path / "cache")
        lf = pl.LazyFrame(
            {
                "a": pl.Series([], dtype=pl.String),
                "b": pl.Series([], dtype=pl.Float64),
            }
        )

        cached = cache.sink_results(results=lf)

        assert cached.results_path.exists()
        df = pl.read_parquet(cached.results_path)
        assert df.height == 0
        assert df.columns == ["a", "b"]
