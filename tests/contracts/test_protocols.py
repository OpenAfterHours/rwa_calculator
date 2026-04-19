"""Tests for protocol definitions.

Tests that stub implementations correctly satisfy the Protocol
definitions for type checking.
"""

from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.api.export import ExportResult
from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
    create_empty_classified_bundle,
    create_empty_crm_adjusted_bundle,
    create_empty_raw_data_bundle,
    create_empty_resolved_hierarchy_bundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import LazyFrameResult
from rwa_calc.contracts.protocols import (
    ClassifierProtocol,
    CRMProcessorProtocol,
    HierarchyResolverProtocol,
    IRBCalculatorProtocol,
    LoaderProtocol,
    RealEstateSplitterProtocol,
    ResultExporterProtocol,
    SACalculatorProtocol,
)


class StubLoader:
    """Stub implementation of LoaderProtocol."""

    def load(self) -> RawDataBundle:
        return create_empty_raw_data_bundle()


class StubHierarchyResolver:
    """Stub implementation of HierarchyResolverProtocol."""

    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        return create_empty_resolved_hierarchy_bundle()


class StubClassifier:
    """Stub implementation of ClassifierProtocol."""

    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        return create_empty_classified_bundle()


class StubCRMProcessor:
    """Stub implementation of CRMProcessorProtocol."""

    def apply_crm(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        return LazyFrameResult(frame=pl.LazyFrame())

    def get_crm_adjusted_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        return create_empty_crm_adjusted_bundle()

    def get_crm_unified_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        return create_empty_crm_adjusted_bundle()


class StubSACalculator:
    """Stub implementation of SACalculatorProtocol."""

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        return exposures

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        return exposures

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        return LazyFrameResult(frame=pl.LazyFrame())


class StubIRBCalculator:
    """Stub implementation of IRBCalculatorProtocol."""

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        return exposures

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        return LazyFrameResult(frame=pl.LazyFrame())

    def calculate_expected_loss(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        return LazyFrameResult(frame=pl.LazyFrame())


class StubRealEstateSplitter:
    """Stub implementation of RealEstateSplitterProtocol."""

    def split(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        return data


class StubResultExporter:
    """Stub implementation of ResultExporterProtocol."""

    def export_to_parquet(
        self,
        response: object,
        output_dir: Path,
    ) -> ExportResult:
        return ExportResult(format="parquet")

    def export_to_csv(
        self,
        response: object,
        output_dir: Path,
    ) -> ExportResult:
        return ExportResult(format="csv")

    def export_to_excel(
        self,
        response: object,
        output_path: Path,
    ) -> ExportResult:
        return ExportResult(format="excel")

    def export_to_corep(
        self,
        response: object,
        output_path: Path,
        *,
        output_floor_config: object | None = None,
    ) -> ExportResult:
        return ExportResult(format="corep_excel")

    def export_to_pillar3(
        self,
        response: object,
        output_path: Path,
    ) -> ExportResult:
        return ExportResult(format="pillar3_excel")


class TestProtocolCompliance:
    """Tests that stub implementations satisfy protocols."""

    def test_loader_protocol_satisfied(self):
        """StubLoader should satisfy LoaderProtocol."""
        loader = StubLoader()
        assert isinstance(loader, LoaderProtocol)

        result = loader.load()
        assert isinstance(result, RawDataBundle)

    def test_hierarchy_resolver_protocol_satisfied(self):
        """StubHierarchyResolver should satisfy HierarchyResolverProtocol."""
        resolver = StubHierarchyResolver()
        assert isinstance(resolver, HierarchyResolverProtocol)

        data = create_empty_raw_data_bundle()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = resolver.resolve(data, config)
        assert isinstance(result, ResolvedHierarchyBundle)

    def test_classifier_protocol_satisfied(self):
        """StubClassifier should satisfy ClassifierProtocol."""
        classifier = StubClassifier()
        assert isinstance(classifier, ClassifierProtocol)

        data = create_empty_resolved_hierarchy_bundle()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = classifier.classify(data, config)
        assert isinstance(result, ClassifiedExposuresBundle)

    def test_crm_processor_protocol_satisfied(self):
        """StubCRMProcessor should satisfy CRMProcessorProtocol."""
        processor = StubCRMProcessor()
        assert isinstance(processor, CRMProcessorProtocol)

        data = create_empty_classified_bundle()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = processor.apply_crm(data, config)
        assert isinstance(result, LazyFrameResult)

    def test_crm_processor_unified_bundle_protocol_satisfied(self):
        """StubCRMProcessor.get_crm_unified_bundle should satisfy CRMProcessorProtocol."""
        processor = StubCRMProcessor()
        assert isinstance(processor, CRMProcessorProtocol)

        data = create_empty_classified_bundle()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = processor.get_crm_unified_bundle(data, config)
        assert isinstance(result, CRMAdjustedBundle)

    def test_sa_calculator_protocol_satisfied(self):
        """StubSACalculator should satisfy SACalculatorProtocol."""
        calculator = StubSACalculator()
        assert isinstance(calculator, SACalculatorProtocol)

        data = create_empty_crm_adjusted_bundle()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = calculator.calculate(data, config)
        assert isinstance(result, LazyFrameResult)

    def test_irb_calculator_protocol_satisfied(self):
        """StubIRBCalculator should satisfy IRBCalculatorProtocol."""
        calculator = StubIRBCalculator()
        assert isinstance(calculator, IRBCalculatorProtocol)

        data = create_empty_crm_adjusted_bundle()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = calculator.calculate(data, config)
        assert isinstance(result, LazyFrameResult)

    def test_result_exporter_protocol_satisfied(self, tmp_path):
        """StubResultExporter should satisfy ResultExporterProtocol."""
        exporter = StubResultExporter()
        assert isinstance(exporter, ResultExporterProtocol)

        result = exporter.export_to_corep(None, tmp_path / "test.xlsx")
        assert isinstance(result, ExportResult)
        assert result.format == "corep_excel"


class TestProtocolRuntimeCheckable:
    """Tests that protocols are runtime checkable."""

    def test_loader_isinstance_check(self):
        """isinstance should work with LoaderProtocol."""
        loader = StubLoader()
        not_loader = object()

        assert isinstance(loader, LoaderProtocol)
        assert not isinstance(not_loader, LoaderProtocol)

    def test_hierarchy_resolver_isinstance_check(self):
        """isinstance should work with HierarchyResolverProtocol."""
        resolver = StubHierarchyResolver()

        assert isinstance(resolver, HierarchyResolverProtocol)

    def test_classifier_isinstance_check(self):
        """isinstance should work with ClassifierProtocol."""
        classifier = StubClassifier()

        assert isinstance(classifier, ClassifierProtocol)

    def test_crm_processor_isinstance_check(self):
        """isinstance should work with CRMProcessorProtocol."""
        processor = StubCRMProcessor()

        assert isinstance(processor, CRMProcessorProtocol)

    def test_sa_calculator_isinstance_check(self):
        """isinstance should work with SACalculatorProtocol."""
        calculator = StubSACalculator()

        assert isinstance(calculator, SACalculatorProtocol)

    def test_irb_calculator_isinstance_check(self):
        """isinstance should work with IRBCalculatorProtocol."""
        calculator = StubIRBCalculator()

        assert isinstance(calculator, IRBCalculatorProtocol)

    def test_re_splitter_isinstance_check(self):
        """isinstance should work with RealEstateSplitterProtocol."""
        splitter = StubRealEstateSplitter()

        assert isinstance(splitter, RealEstateSplitterProtocol)
        assert not isinstance(object(), RealEstateSplitterProtocol)

    def test_concrete_re_splitter_satisfies_protocol(self):
        """The real RealEstateSplitter should satisfy the protocol."""
        from rwa_calc.engine.re_splitter import RealEstateSplitter

        assert isinstance(RealEstateSplitter(), RealEstateSplitterProtocol)

    def test_result_exporter_isinstance_check(self):
        """isinstance should work with ResultExporterProtocol."""
        exporter = StubResultExporter()

        assert isinstance(exporter, ResultExporterProtocol)
        assert not isinstance(object(), ResultExporterProtocol)


class TestResultExporterProtocol:
    """Tests for ResultExporterProtocol compliance including export_to_corep."""

    def test_result_exporter_protocol_satisfied(self):
        """StubResultExporter should satisfy ResultExporterProtocol."""
        exporter = StubResultExporter()
        assert isinstance(exporter, ResultExporterProtocol)

    def test_export_to_parquet_returns_export_result(self, tmp_path):
        """export_to_parquet should return ExportResult."""
        exporter = StubResultExporter()
        result = exporter.export_to_parquet(None, tmp_path)
        assert isinstance(result, ExportResult)
        assert result.format == "parquet"

    def test_export_to_csv_returns_export_result(self, tmp_path):
        """export_to_csv should return ExportResult."""
        exporter = StubResultExporter()
        result = exporter.export_to_csv(None, tmp_path)
        assert isinstance(result, ExportResult)
        assert result.format == "csv"

    def test_export_to_excel_returns_export_result(self, tmp_path):
        """export_to_excel should return ExportResult."""
        exporter = StubResultExporter()
        result = exporter.export_to_excel(None, tmp_path)
        assert isinstance(result, ExportResult)
        assert result.format == "excel"

    def test_export_to_corep_returns_export_result(self, tmp_path):
        """export_to_corep should return ExportResult."""
        exporter = StubResultExporter()
        result = exporter.export_to_corep(None, tmp_path)
        assert isinstance(result, ExportResult)
        assert result.format == "corep_excel"

    def test_export_to_pillar3_returns_export_result(self, tmp_path):
        """export_to_pillar3 should return ExportResult."""
        exporter = StubResultExporter()
        result = exporter.export_to_pillar3(None, tmp_path)
        assert isinstance(result, ExportResult)
        assert result.format == "pillar3_excel"

    def test_missing_export_to_corep_fails_isinstance(self):
        """Class without export_to_corep should not satisfy protocol."""

        class IncompleteExporter:
            def export_to_parquet(self, response, output_dir):
                return ExportResult(format="parquet")

            def export_to_csv(self, response, output_dir):
                return ExportResult(format="csv")

            def export_to_excel(self, response, output_path):
                return ExportResult(format="excel")

            def export_to_pillar3(self, response, output_path):
                return ExportResult(format="pillar3_excel")

        assert not isinstance(IncompleteExporter(), ResultExporterProtocol)

    def test_concrete_result_exporter_satisfies_protocol(self):
        """The real ResultExporter from api.export should satisfy the protocol."""
        from rwa_calc.api.export import ResultExporter

        exporter = ResultExporter()
        assert isinstance(exporter, ResultExporterProtocol)
