"""Unit tests for the UI output writer (write calculation results to a folder).

Tests cover:
- write_selected_formats writes the dependency-free formats into a run-stamped
  subfolder of the chosen folder.
- A failing single-format write (e.g. xlsxwriter missing) is captured as an
  error string and never raised, and does not stop the other formats.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.results_cache import ResultsCache
from rwa_calc.ui.app.output_writer import OutputWriteResult, write_selected_formats


@pytest.fixture
def sample_response(tmp_path: Path) -> CalculationResponse:
    """A CalculationResponse backed by a small cached parquet result set."""
    cache = ResultsCache(tmp_path / "cache")
    cached = cache.sink_results(
        results=pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "retail"],
                "ead_final": [1_000_000.0, 500_000.0],
                "risk_weight": [1.0, 0.75],
                "rwa_final": [1_000_000.0, 375_000.0],
            }
        ),
        summary_by_class=pl.LazyFrame(
            {"exposure_class": ["corporate", "retail"], "total_rwa": [1_000_000.0, 375_000.0]}
        ),
        summary_by_approach=pl.LazyFrame(
            {"approach_applied": ["standardised"], "total_rwa": [1_375_000.0]}
        ),
    )
    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2024, 12, 31),
        summary=SummaryStatistics(
            total_ead=Decimal("1500000"),
            total_rwa=Decimal("1375000"),
            exposure_count=2,
            average_risk_weight=Decimal("0.9167"),
        ),
        results_path=cached.results_path,
        summary_by_class_path=cached.summary_by_class_path,
        summary_by_approach_path=cached.summary_by_approach_path,
    )


def test_writes_selected_formats_into_run_stamped_subfolder(
    sample_response: CalculationResponse, tmp_path: Path
) -> None:
    # Act
    result = write_selected_formats(sample_response, tmp_path, ["parquet", "csv"], run_id="r1")

    # Assert — files land under <folder>/rwa_export_r1/, isolated from other runs.
    subdir = tmp_path / "rwa_export_r1"
    assert (subdir / "results.parquet").exists()
    assert (subdir / "results.csv").exists()
    assert isinstance(result, OutputWriteResult)
    assert result.errors == ()
    assert subdir.resolve() == Path(result.folder)
    assert any(f.name == "results.parquet" for f in result.files)


def test_failed_format_is_captured_not_raised(
    sample_response: CalculationResponse, tmp_path: Path
) -> None:
    # Arrange — simulate xlsxwriter being unavailable for the Excel workbook.
    with patch.object(
        CalculationResponse, "to_excel", side_effect=ModuleNotFoundError("xlsxwriter")
    ):
        # Act — must not raise even though the only requested format fails.
        result = write_selected_formats(sample_response, tmp_path, ["excel"], run_id="r2")

    # Assert
    assert result.files == ()
    assert len(result.errors) == 1
    assert "xlsxwriter" in result.errors[0]


def test_polars_export_error_is_captured(
    sample_response: CalculationResponse, tmp_path: Path
) -> None:
    # Arrange — a format that cannot represent the data (e.g. nested -> CSV).
    with patch.object(
        CalculationResponse, "to_csv", side_effect=pl.exceptions.ComputeError("nested")
    ):
        # Act
        result = write_selected_formats(sample_response, tmp_path, ["csv"], run_id="r3")

    # Assert — captured as an error, not raised.
    assert result.files == ()
    assert len(result.errors) == 1
    assert "csv" in result.errors[0]
