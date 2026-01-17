"""Tests for protocol definitions.

Tests that stub implementations correctly satisfy the Protocol
definitions for type checking.
"""

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
    create_empty_classified_bundle,
    create_empty_counterparty_lookup,
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
    OutputAggregatorProtocol,
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


class StubSACalculator:
    """Stub implementation of SACalculatorProtocol."""

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        return LazyFrameResult(frame=pl.LazyFrame())


class StubIRBCalculator:
    """Stub implementation of IRBCalculatorProtocol."""

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


class StubOutputAggregator:
    """Stub implementation of OutputAggregatorProtocol."""

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        return pl.LazyFrame()

    def aggregate_with_audit(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        config: CalculationConfig,
    ):
        from rwa_calc.contracts.bundles import AggregatedResultBundle
        return AggregatedResultBundle(results=pl.LazyFrame())

    def apply_output_floor(
        self,
        irb_rwa: pl.LazyFrame,
        sa_equivalent_rwa: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        return pl.LazyFrame()


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

    def test_output_aggregator_protocol_satisfied(self):
        """StubOutputAggregator should satisfy OutputAggregatorProtocol."""
        aggregator = StubOutputAggregator()
        assert isinstance(aggregator, OutputAggregatorProtocol)

        sa = pl.LazyFrame()
        irb = pl.LazyFrame()
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        result = aggregator.aggregate(sa, irb, config)
        assert isinstance(result, pl.LazyFrame)


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

    def test_output_aggregator_isinstance_check(self):
        """isinstance should work with OutputAggregatorProtocol."""
        aggregator = StubOutputAggregator()

        assert isinstance(aggregator, OutputAggregatorProtocol)
