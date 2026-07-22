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

# =============================================================================
# Fixtures
# =============================================================================
import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.api.export import ExportResult, ResultExporter
from rwa_calc.api.models import (
    CalculationResponse,
    ComparisonExportResponse,
    SummaryStatistics,
)
from rwa_calc.api.results_cache import ResultsCache
from rwa_calc.reporting.facts import FilingMetadata

XLSXWRITER_AVAILABLE = bool(sys.modules.get("xlsxwriter")) or (
    importlib.util.find_spec("xlsxwriter") is not None
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
        results=with_reporting_ledger(results_lf),
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

    cached = cache.sink_results(results=with_reporting_ledger(results_lf))

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

    cached = cache.sink_results(results=with_reporting_ledger(results_lf))

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
            result.format = "csv"  # type: ignore[misc]  # ty: ignore[invalid-assignment]

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
        # The fixture mirrors the sealed ledger shape (with_reporting_ledger),
        # so the export carries the reporting projection columns too.
        assert df.columns == [
            "exposure_reference",
            "ead_final",
            "rwa_final",
            "reporting_class",
            "reporting_class_origin",
            "reporting_approach",
            "reporting_approach_origin",
            "reporting_ead",
            "reporting_rw",
            "reporting_gross_drawn",
            "reporting_gross_interest",
            "reporting_gross_nominal",
            "reporting_gross_undrawn",
            "reporting_on_balance_sheet",
            "reporting_gross_on_bs",
            "reporting_gross_off_bs",
        ]

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


class TestCsvNestedColumns:
    """CSV export must represent nested columns (CSV has no nested types)."""

    def test_export_to_csv_stringifies_nested_columns(self, tmp_path: Path) -> None:
        # Arrange — a results frame with a nested List column CSV cannot hold.
        cache = ResultsCache(tmp_path / "cache")
        cached = cache.sink_results(
            results=with_reporting_ledger(
                pl.LazyFrame(
                    {
                        "exposure_reference": ["E1", "E2"],
                        "rwa_final": [100.0, 200.0],
                        "ancestor_facilities": [["F1", "F2"], None],
                    }
                )
            ),
        )
        response = CalculationResponse(
            success=True,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            summary=SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("300"),
                exposure_count=2,
                average_risk_weight=Decimal("0"),
            ),
            results_path=cached.results_path,
        )

        # Act
        ResultExporter().export_to_csv(response, tmp_path / "out")

        # Assert — the file has data and the nested column round-trips as JSON
        # (CSV-escaped on disk), not a blank file.
        csv_path = tmp_path / "out" / "results.csv"
        assert csv_path.stat().st_size > 0
        back = pl.read_csv(csv_path)
        assert back["exposure_reference"].to_list() == ["E1", "E2"]
        assert back["ancestor_facilities"][0] == '["F1", "F2"]'
        assert back["ancestor_facilities"][1] is None


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


# =============================================================================
# Comparison export
# =============================================================================


# Frame names the comparison exporter writes one file / sheet per (report order).
_COMPARISON_FRAME_NAMES = (
    "executive_summary",
    "summary_by_class",
    "summary_by_approach",
    "waterfall",
    "exposure_deltas",
    "exposure_attribution",
)


def _comparison_export_response() -> ComparisonExportResponse:
    """A small CRR vs Basel 3.1 comparison-export response for the exporter tests.

    ``from_bundles`` only reads the summary / delta / waterfall / attribution
    frames (not the nested AggregatedResultBundles), so a stub bundle suffices.
    """
    from tests.fixtures.resolved_bundle import make_aggregated_bundle

    from rwa_calc.contracts.bundles import CapitalImpactBundle, ComparisonBundle

    agg = make_aggregated_bundle(results=pl.LazyFrame())
    comparison = ComparisonBundle(
        baseline_results=agg,
        variant_results=agg,
        exposure_deltas=pl.LazyFrame(
            {"exposure_reference": ["E1", "E2"], "delta_rwa": [100.0, -50.0]}
        ),
        summary_by_class=pl.LazyFrame(
            {"exposure_class": ["corporate", "retail"], "total_delta_rwa": [100.0, -50.0]}
        ),
        summary_by_approach=pl.LazyFrame(
            {"approach_applied": ["standardised"], "total_delta_rwa": [50.0]}
        ),
        baseline_label="crr",
        variant_label="b31",
    )
    impact = CapitalImpactBundle(
        exposure_attribution=pl.LazyFrame(
            {"exposure_reference": ["E1", "E2"], "methodology_impact": [100.0, -50.0]}
        ),
        portfolio_waterfall=pl.LazyFrame(
            {
                "step": [1, 2],
                "driver": ["Scaling factor removal", "Methodology & parameter changes"],
                "impact_rwa": [-100.0, 50.0],
                "cumulative_rwa": [-100.0, -50.0],
            }
        ),
        summary_by_class=pl.LazyFrame({"exposure_class": ["corporate"]}),
        summary_by_approach=pl.LazyFrame({"approach_applied": ["standardised"]}),
    )
    return ComparisonExportResponse.from_bundles(
        comparison,
        impact,
        summary={"crr_rwa": 1000.0, "b31_rwa": 1050.0, "delta_rwa": 50.0},
    )


class TestComparisonExport:
    """Tests for the comparison-page CSV / Parquet / Excel export."""

    def test_csv_writes_one_file_per_frame(self, tmp_path: Path) -> None:
        # Arrange
        response = _comparison_export_response()

        # Act
        result = response.to_csv(tmp_path / "out")

        # Assert: one CSV per export frame, each non-empty.
        assert result.format == "csv"
        assert {p.name for p in result.files} == {
            f"comparison_{n}.csv" for n in _COMPARISON_FRAME_NAMES
        }
        assert all(p.stat().st_size > 0 for p in result.files)

    def test_parquet_roundtrips_per_exposure_deltas(self, tmp_path: Path) -> None:
        # Arrange
        response = _comparison_export_response()

        # Act
        response.to_parquet(tmp_path / "out")

        # Assert: the per-exposure delta frame survives the round-trip.
        deltas = pl.read_parquet(tmp_path / "out" / "comparison_exposure_deltas.parquet")
        assert deltas.height == 2
        assert "delta_rwa" in deltas.columns

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_excel_has_a_sheet_per_frame(self, tmp_path: Path) -> None:
        # Arrange
        response = _comparison_export_response()
        output_path = tmp_path / "comparison.xlsx"

        # Act
        response.to_excel(output_path)

        # Assert: the friendly, comparison-specific sheet titles are present.
        import fastexcel

        sheets = fastexcel.read_excel(str(output_path)).sheet_names
        assert "Executive Summary" in sheets
        assert "Capital Impact Waterfall" in sheets
        assert "Driver Attribution" in sheets

    def test_excel_raises_without_xlsxwriter(self, tmp_path: Path) -> None:
        # Arrange
        response = _comparison_export_response()

        # Act / Assert
        with (
            patch.dict("sys.modules", {"xlsxwriter": None}),
            pytest.raises(ModuleNotFoundError, match="xlsxwriter"),
        ):
            response.to_excel(tmp_path / "comparison.xlsx")


# =============================================================================
# Pillar III export
# =============================================================================


class TestExportToPillar3:
    """Tests for the Pillar III disclosure export (workbook + convenience method)."""

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_creates_pillar3_workbook(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "pillar3.xlsx"

        # Act
        result = ResultExporter().export_to_pillar3(sample_response, output_path)

        # Assert
        assert result.format == "pillar3_excel"
        assert output_path.exists()
        assert result.row_count > 0

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_pillar3_workbook_has_uk_prefixed_sheets(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange / Act — the sample response is CRR, so sheets carry the UK prefix.
        output_path = tmp_path / "pillar3.xlsx"
        ResultExporter().export_to_pillar3(sample_response, output_path)

        # Assert
        import fastexcel

        sheets = fastexcel.read_excel(str(output_path)).sheet_names
        assert "UK OV1" in sheets
        assert "UK CR5" in sheets

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_to_pillar3_convenience_delegates(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange / Act
        result = sample_response.to_pillar3(tmp_path / "pillar3.xlsx")

        # Assert
        assert result.format == "pillar3_excel"
        assert (tmp_path / "pillar3.xlsx").exists()

    def test_pillar3_raises_without_xlsxwriter(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange / Act / Assert
        with (
            patch.dict("sys.modules", {"xlsxwriter": None}),
            pytest.raises(ModuleNotFoundError, match="xlsxwriter"),
        ):
            sample_response.to_pillar3(tmp_path / "pillar3.xlsx")


# =============================================================================
# Filing metadata — workbook sheet + cell-fact export
# =============================================================================


def _filing_metadata(**overrides: object) -> FilingMetadata:
    fields: dict[str, Any] = {
        "reporting_date": date(2024, 12, 31),
        "framework": "CRR",
        "run_id": "run-abc",
        "entity_identifier": "LEI-999",
    }
    fields.update(overrides)
    return FilingMetadata(**fields)


class TestExportToCorepWithMetadata:
    """export_to_corep(..., metadata=...) — the workbook metadata sheet hook."""

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_metadata_sheet_is_written_when_supplied(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "corep.xlsx"

        # Act
        ResultExporter().export_to_corep(sample_response, output_path, metadata=_filing_metadata())

        # Assert
        md = pl.read_excel(output_path, sheet_name="metadata")
        fields = dict(zip(md["Field"], md["Value"], strict=True))
        assert fields["Reporting date"] == "2024-12-31"
        assert fields["Entity identifier"] == "LEI-999"
        assert fields["Run ID"] == "run-abc"

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_no_metadata_sheet_when_metadata_omitted(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "corep.xlsx"

        # Act — no metadata kwarg, matching existing callers unchanged.
        ResultExporter().export_to_corep(sample_response, output_path)

        # Assert
        import fastexcel

        sheets = fastexcel.read_excel(str(output_path)).sheet_names
        assert "metadata" not in sheets


class TestExportToPillar3WithMetadata:
    """export_to_pillar3(..., metadata=...) — the workbook metadata sheet hook."""

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_metadata_sheet_is_written_when_supplied(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "pillar3.xlsx"

        # Act
        ResultExporter().export_to_pillar3(
            sample_response, output_path, metadata=_filing_metadata()
        )

        # Assert
        import fastexcel

        assert "metadata" in fastexcel.read_excel(str(output_path)).sheet_names


class TestExportCorepFacts:
    """Tests for ResultExporter.export_corep_facts (the keyed cell-fact feed)."""

    def test_writes_parquet_by_default(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "corep_facts.parquet"

        # Act
        result = ResultExporter().export_corep_facts(sample_response, output_path)

        # Assert
        assert result.format == "corep_facts_parquet"
        assert output_path.exists()
        assert result.row_count > 0
        frame = pl.read_parquet(output_path)
        assert frame.height == result.row_count
        assert "template_id" in frame.columns
        assert (frame["template_id"] == "c07_00").any()

    def test_writes_ndjson(self, sample_response: CalculationResponse, tmp_path: Path) -> None:
        # Arrange
        output_path = tmp_path / "corep_facts.ndjson"

        # Act
        result = ResultExporter().export_corep_facts(sample_response, output_path, fmt="ndjson")

        # Assert — infer_schema_length=None: sheet/value/text_value/
        # entity_identifier are all sparse columns (e.g. "sheet" is null for
        # single-frame templates, a string for per-class ones), so a small
        # inference sample can type a column Null and then choke on a later
        # non-null row.
        assert result.format == "corep_facts_ndjson"
        frame = pl.read_ndjson(output_path, infer_schema_length=None)
        assert frame.height == result.row_count

    def test_ndjson_null_cells_are_not_filled(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "corep_facts.ndjson"

        # Act
        ResultExporter().export_corep_facts(sample_response, output_path, fmt="ndjson")

        # Assert — same null-preservation guarantee as the parquet path; a
        # fill_null regression on the ndjson writer must be caught here too.
        frame = pl.read_ndjson(output_path, infer_schema_length=None)
        assert frame["value"].null_count() > 0

    def test_stamps_metadata_columns(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "corep_facts.parquet"

        # Act
        ResultExporter().export_corep_facts(
            sample_response, output_path, metadata=_filing_metadata()
        )

        # Assert
        frame = pl.read_parquet(output_path)
        assert (frame["entity_identifier"] == "LEI-999").all()
        assert (frame["run_id"] == "run-abc").all()

    def test_null_cells_are_not_filled(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "corep_facts.parquet"

        # Act
        ResultExporter().export_corep_facts(sample_response, output_path)

        # Assert — a real bundle carries genuine null cells (e.g. inapplicable
        # memorandum rows); this must not have been coerced to 0.0.
        frame = pl.read_parquet(output_path)
        assert frame["value"].null_count() > 0


class TestExportPillar3Facts:
    """Tests for ResultExporter.export_pillar3_facts (the keyed cell-fact feed)."""

    def test_writes_parquet_by_default(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange
        output_path = tmp_path / "pillar3_facts.parquet"

        # Act
        result = ResultExporter().export_pillar3_facts(sample_response, output_path)

        # Assert
        assert result.format == "pillar3_facts_parquet"
        frame = pl.read_parquet(output_path)
        assert frame.height == result.row_count
        assert (frame["template_id"] == "ov1").any()

    def test_writes_ndjson(self, sample_response: CalculationResponse, tmp_path: Path) -> None:
        # Arrange
        output_path = tmp_path / "pillar3_facts.ndjson"

        # Act
        result = ResultExporter().export_pillar3_facts(sample_response, output_path, fmt="ndjson")

        # Assert — infer_schema_length=-1: the "sheet" column is sparse (null for
        # single-frame templates, a string for per-class ones like CR7-A's
        # "foundation_irb"/"advanced_irb" keys), so a small inference sample can
        # type it Null and then choke on a later non-null row.
        assert result.format == "pillar3_facts_ndjson"
        frame = pl.read_ndjson(output_path, infer_schema_length=None)
        assert frame.height == result.row_count


class TestExportToPillar3WithPriorPeriodAndRatios:
    """export_to_pillar3 / export_pillar3_facts thread previous_period_results
    and output_floor_summary straight through to the generator (rather than
    through the ResultsSource-only ``generate`` shortcut, which cannot carry
    output_floor_summary at all)."""

    def _cr8_opening(self, frame: pl.DataFrame) -> object:
        row = frame.filter(
            (pl.col("template_id") == "cr8")
            & (pl.col("row_ref") == "1")
            & (pl.col("col_ref") == "a")
        )
        assert row.height == 1
        return row["value"][0]

    def test_previous_period_results_populates_cr8_opening_row(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange — sample_response's only IRB row is foundation_irb=375_000.0
        # (its CR8 closing balance); the prior period sums to 300_000.0.
        prior_lf = pl.LazyFrame(
            {
                "approach_applied": ["foundation_irb"],
                "rwa_final": [300_000.0],
            }
        )
        output_path = tmp_path / "pillar3_facts.parquet"

        # Act
        ResultExporter().export_pillar3_facts(
            sample_response, output_path, previous_period_results=prior_lf
        )

        # Assert
        frame = pl.read_parquet(output_path)
        assert self._cr8_opening(frame) == pytest.approx(300_000.0)

    def test_without_previous_period_results_cr8_opening_row_is_null(
        self, sample_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange / Act — no previous_period_results kwarg: unchanged behaviour.
        output_path = tmp_path / "pillar3_facts.parquet"
        ResultExporter().export_pillar3_facts(sample_response, output_path)

        # Assert
        frame = pl.read_parquet(output_path)
        assert self._cr8_opening(frame) is None

    @pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
    def test_output_floor_summary_populates_ov1_of_adj_row(
        self, minimal_response: CalculationResponse, tmp_path: Path
    ) -> None:
        # Arrange — row 27 ("of which OF-ADJ") reads output_floor_summary.of_adj
        # via a SideContext binding; minimal_response is BASEL_3_1 (UKB OV1).
        from rwa_calc.contracts.bundles import OutputFloorSummary

        floor_summary = OutputFloorSummary(
            u_trea=900_000.0,
            s_trea=1_000_000.0,
            floor_pct=0.725,
            floor_threshold=725_000.0,
            shortfall=0.0,
            portfolio_floor_binding=False,
            floored_modelled_rwa=900_000.0,
            of_adj=12_345.0,
        )
        output_path = tmp_path / "pillar3.xlsx"

        # Act
        ResultExporter().export_to_pillar3(
            minimal_response, output_path, output_floor_summary=floor_summary
        )

        # Assert
        df = pl.read_excel(output_path, sheet_name="UKB OV1")
        value = df.filter(pl.col("Row code") == "27")["RWEAs (T)"][0]
        assert float(value) == pytest.approx(12_345.0)
