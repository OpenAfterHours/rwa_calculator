"""Unit tests for the ResultExporter module.

Tests cover:
- ResultExporter: export_to_parquet, export_to_csv, export_to_excel
- ExportResult: frozen dataclass properties
- CalculationResponse convenience methods: to_parquet, to_csv, to_excel

Why: FR-4.7 requires a programmatic export API for downstream consumption
of RWA results. Parquet enables analytics pipelines, CSV enables ad-hoc
analysis, and Excel enables stakeholder reporting with multi-sheet workbooks.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from rwa_calc.api.export import ExportResult, ResultExporter
from rwa_calc.api.models import (
    CalculationResponse,
    SummaryStatistics,
)
from rwa_calc.api.results_cache import ResultsCache

# =============================================================================
# Fixtures
# =============================================================================

XLSXWRITER_AVAILABLE = bool(sys.modules.get("xlsxwriter")) or (
    __import__("importlib").util.find_spec("xlsxwriter") is not None
)


@pytest.fixture
def sample_response(tmp_path: Path) -> CalculationResponse:
    """Create a sample CalculationResponse with cached parquet data."""
    cache = ResultsCache(tmp_path / "cache")

    results_lf = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "approach_applied": ["standardised", "standardised", "foundation_irb"],
            "exposure_class": ["corporate", "retail", "corporate"],
            "ead_final": [1_000_000.0, 500_000.0, 750_000.0],
            "risk_weight": [1.0, 0.75, 0.5],
            "rwa_final": [1_000_000.0, 375_000.0, 375_000.0],
        }
    )

    summary_by_class_lf = pl.LazyFrame(
        {
            "exposure_class": ["corporate", "retail"],
            "total_ead": [1_750_000.0, 500_000.0],
            "total_rwa": [1_375_000.0, 375_000.0],
        }
    )

    summary_by_approach_lf = pl.LazyFrame(
        {
            "approach_applied": ["standardised", "foundation_irb"],
            "total_ead": [1_500_000.0, 750_000.0],
            "total_rwa": [1_375_000.0, 375_000.0],
        }
    )

    cached = cache.sink_results(
        results=results_lf,
        summary_by_class=summary_by_class_lf,
        summary_by_approach=summary_by_approach_lf,
    )

    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2024, 12, 31),
        summary=SummaryStatistics(
            total_ead=Decimal("2250000"),
            total_rwa=Decimal("1750000"),
            exposure_count=3,
            average_risk_weight=Decimal("0.7778"),
        ),
        results_path=cached.results_path,
        summary_by_class_path=cached.summary_by_class_path,
        summary_by_approach_path=cached.summary_by_approach_path,
    )


@pytest.fixture
def minimal_response(tmp_path: Path) -> CalculationResponse:
    """Create a minimal CalculationResponse with no summaries."""
    cache = ResultsCache(tmp_path / "cache")

    results_lf = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "ead_final": [100_000.0],
            "rwa_final": [50_000.0],
        }
    )

    cached = cache.sink_results(results=results_lf)

    return CalculationResponse(
        success=True,
        framework="BASEL_3_1",
        reporting_date=date(2027, 6, 30),
        summary=SummaryStatistics(
            total_ead=Decimal("100000"),
            total_rwa=Decimal("50000"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=cached.results_path,
    )


@pytest.fixture
def empty_response(tmp_path: Path) -> CalculationResponse:
    """Create a CalculationResponse with no data."""
    cache = ResultsCache(tmp_path / "cache")

    results_lf = pl.LazyFrame(
        {
            "exposure_reference": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "rwa_final": pl.Series([], dtype=pl.Float64),
        }
    )

    cached = cache.sink_results(results=results_lf)

    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2024, 12, 31),
        summary=SummaryStatistics(
            total_ead=Decimal("0"),
            total_rwa=Decimal("0"),
            exposure_count=0,
            average_risk_weight=Decimal("0"),
        ),
        results_path=cached.results_path,
    )


# =============================================================================
# ExportResult Tests
# =============================================================================


class TestExportResult:
    """Tests for ExportResult frozen dataclass."""

    def test_frozen_dataclass(self) -> None:
        """ExportResult should be immutable."""
        result = ExportResult(format="parquet", files=[], row_count=0)
        with pytest.raises(AttributeError):
            result.format = "csv"  # type: ignore[misc]

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        result = ExportResult(format="parquet")
        assert result.files == []
        assert result.row_count == 0

    def test_stores_file_paths(self) -> None:
        """Should store the list of written file paths."""
        paths = [Path("a.parquet"), Path("b.parquet")]
        result = ExportResult(format="parquet", files=paths, row_count=100)
        assert result.files == paths
        assert result.row_count == 100
        assert result.format == "parquet"


# =============================================================================
# ResultExporter.export_to_parquet Tests
# =============================================================================


class TestExportToParquet:
    """Tests for ResultExporter.export_to_parquet."""

    def test_creates_results_parquet(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should write results.parquet with all exposure data."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_parquet(sample_response, output_dir)

        assert result.format == "parquet"
        results_path = output_dir / "results.parquet"
        assert results_path.exists()
        df = pl.read_parquet(results_path)
        assert df.height == 3
        assert "exposure_reference" in df.columns
        assert "rwa_final" in df.columns

    def test_creates_summary_parquets(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should write summary parquet files when available."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_parquet(sample_response, output_dir)

        assert (output_dir / "summary_by_class.parquet").exists()
        assert (output_dir / "summary_by_approach.parquet").exists()
        assert len(result.files) == 3

        class_df = pl.read_parquet(output_dir / "summary_by_class.parquet")
        assert "exposure_class" in class_df.columns
        assert class_df.height == 2

    def test_skips_missing_summaries(
        self,
        minimal_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should only write results.parquet when no summaries exist."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_parquet(minimal_response, output_dir)

        assert len(result.files) == 1
        assert result.files[0] == output_dir / "results.parquet"
        assert not (output_dir / "summary_by_class.parquet").exists()

    def test_reports_row_count(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should report the total number of result rows."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_parquet(sample_response, output_dir)

        assert result.row_count == 3

    def test_creates_output_directory(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should create output directory if it doesn't exist."""
        output_dir = tmp_path / "nested" / "export" / "dir"
        exporter = ResultExporter()

        result = exporter.export_to_parquet(sample_response, output_dir)

        assert output_dir.exists()
        assert len(result.files) > 0

    def test_empty_results(
        self,
        empty_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should handle empty results gracefully."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_parquet(empty_response, output_dir)

        assert result.row_count == 0
        df = pl.read_parquet(output_dir / "results.parquet")
        assert df.height == 0
        assert df.columns == ["exposure_reference", "ead_final", "rwa_final"]

    def test_parquet_roundtrip_preserves_data(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Exported parquet should be identical to source data."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        exporter.export_to_parquet(sample_response, output_dir)

        original = sample_response.collect_results()
        exported = pl.read_parquet(output_dir / "results.parquet")
        assert original.equals(exported)


# =============================================================================
# ResultExporter.export_to_csv Tests
# =============================================================================


class TestExportToCSV:
    """Tests for ResultExporter.export_to_csv."""

    def test_creates_results_csv(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should write results.csv with all exposure data."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_csv(sample_response, output_dir)

        assert result.format == "csv"
        results_path = output_dir / "results.csv"
        assert results_path.exists()
        df = pl.read_csv(results_path)
        assert df.height == 3

    def test_creates_summary_csvs(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should write summary CSV files when available."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_csv(sample_response, output_dir)

        assert (output_dir / "summary_by_class.csv").exists()
        assert (output_dir / "summary_by_approach.csv").exists()
        assert len(result.files) == 3

    def test_skips_missing_summaries(
        self,
        minimal_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should only write results.csv when no summaries exist."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_csv(minimal_response, output_dir)

        assert len(result.files) == 1
        assert not (output_dir / "summary_by_class.csv").exists()

    def test_csv_readable_by_polars(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Exported CSV should be parseable back into a DataFrame."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        exporter.export_to_csv(sample_response, output_dir)

        df = pl.read_csv(output_dir / "results.csv")
        assert df.height == 3
        assert "exposure_reference" in df.columns
        assert df["ead_final"].sum() == pytest.approx(2_250_000.0)

    def test_empty_results(
        self,
        empty_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should handle empty results gracefully."""
        output_dir = tmp_path / "export"
        exporter = ResultExporter()

        result = exporter.export_to_csv(empty_response, output_dir)

        assert result.row_count == 0


# =============================================================================
# ResultExporter.export_to_excel Tests
# =============================================================================


class TestExportToExcel:
    """Tests for ResultExporter.export_to_excel."""

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_creates_excel_workbook(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should create an Excel workbook at the specified path."""
        output_path = tmp_path / "export" / "results.xlsx"
        exporter = ResultExporter()

        result = exporter.export_to_excel(sample_response, output_path)

        assert result.format == "excel"
        assert output_path.exists()
        assert len(result.files) == 1
        assert result.files[0] == output_path
        assert result.row_count == 3

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_excel_contains_multiple_sheets(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should create sheets for results and summaries."""
        output_path = tmp_path / "results.xlsx"
        exporter = ResultExporter()

        exporter.export_to_excel(sample_response, output_path)

        # Read back with fastexcel to verify sheets
        import fastexcel

        reader = fastexcel.read_excel(str(output_path))
        sheet_names = reader.sheet_names
        assert "Results" in sheet_names
        assert "Summary by Class" in sheet_names
        assert "Summary by Approach" in sheet_names

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_excel_results_data(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should write correct data to the Results sheet."""
        output_path = tmp_path / "results.xlsx"
        exporter = ResultExporter()

        exporter.export_to_excel(sample_response, output_path)

        df = pl.read_excel(output_path, sheet_name="Results")
        assert df.height == 3
        assert "exposure_reference" in df.columns

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_excel_minimal_response(
        self,
        minimal_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should create workbook with only Results sheet when no summaries."""
        output_path = tmp_path / "results.xlsx"
        exporter = ResultExporter()

        result = exporter.export_to_excel(minimal_response, output_path)

        assert output_path.exists()
        assert result.row_count == 1

    def test_excel_raises_without_xlsxwriter(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """Should raise ModuleNotFoundError with helpful message when xlsxwriter missing."""
        output_path = tmp_path / "results.xlsx"
        exporter = ResultExporter()

        with (
            patch.dict("sys.modules", {"xlsxwriter": None}),
            pytest.raises(ModuleNotFoundError, match="xlsxwriter"),
        ):
            exporter.export_to_excel(sample_response, output_path)


# =============================================================================
# CalculationResponse convenience method tests
# =============================================================================


class TestCalculationResponseExportMethods:
    """Tests for CalculationResponse.to_parquet / to_csv / to_excel."""

    def test_to_parquet(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """to_parquet should delegate to ResultExporter."""
        output_dir = tmp_path / "export"

        result = sample_response.to_parquet(output_dir)

        assert result.format == "parquet"
        assert (output_dir / "results.parquet").exists()
        assert result.row_count == 3

    def test_to_csv(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """to_csv should delegate to ResultExporter."""
        output_dir = tmp_path / "export"

        result = sample_response.to_csv(output_dir)

        assert result.format == "csv"
        assert (output_dir / "results.csv").exists()
        assert result.row_count == 3

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_to_excel(
        self,
        sample_response: CalculationResponse,
        tmp_path: Path,
    ) -> None:
        """to_excel should delegate to ResultExporter."""
        output_path = tmp_path / "results.xlsx"

        result = sample_response.to_excel(output_path)

        assert result.format == "excel"
        assert output_path.exists()


# =============================================================================
# Protocol conformance tests
# =============================================================================


class TestResultExporterProtocol:
    """Tests that ResultExporter conforms to ResultExporterProtocol."""

    def test_conforms_to_protocol(self) -> None:
        """ResultExporter should satisfy ResultExporterProtocol."""
        from rwa_calc.contracts.protocols import ResultExporterProtocol

        exporter = ResultExporter()
        assert isinstance(exporter, ResultExporterProtocol)
