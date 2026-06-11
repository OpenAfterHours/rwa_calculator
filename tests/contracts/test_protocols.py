"""Protocol conformance — asserted on the REAL implementations.

Migration Phase 2 (docs/plans/target-architecture-migration.md): protocol
compliance is verified against the production classes via runtime isinstance
checks (every protocol is @runtime_checkable) plus typed assignment, NOT via
hand-written stubs — a stub can satisfy a protocol the real component has
drifted away from, which is exactly the failure a conformance test exists to
catch.

Protocols whose conformance is asserted in their own test modules (and not
re-asserted here): ReconciliationRunnerProtocol (tests/unit/engine/
test_reconciliation.py), ResultExporterProtocol (tests/unit/api/
test_export.py).
"""

from __future__ import annotations

import pytest

from rwa_calc.api.export import ResultExporter
from rwa_calc.contracts.protocols import (
    CapitalImpactAnalyzerProtocol,
    ClassifierProtocol,
    CollateralLinkAllocatorProtocol,
    ComparisonRunnerProtocol,
    CRMProcessorProtocol,
    EquityCalculatorProtocol,
    HierarchyResolverProtocol,
    IRBCalculatorProtocol,
    LoaderProtocol,
    OutputAggregatorProtocol,
    PipelineProtocol,
    RealEstateSplitterProtocol,
    ReconciliationRunnerProtocol,
    ResultExporterProtocol,
    SACalculatorProtocol,
    SecuritisationAllocatorProtocol,
    SlottingCalculatorProtocol,
)
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.comparison import CapitalImpactAnalyzer, DualFrameworkRunner
from rwa_calc.engine.crm.link_allocation import CollateralLinkAllocator
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.loader import ParquetLoader
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.re_splitter import RealEstateSplitter
from rwa_calc.engine.reconciliation import ReconciliationRunner
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.securitisation.allocator import SecuritisationAllocator
from rwa_calc.engine.slotting.calculator import SlottingCalculator

# (protocol, real implementation instance factory) — one row per pipeline
# component the orchestrator wires. Typed assignment below each isinstance
# check keeps the static checker honest as well.
_CONFORMANCE_CASES = [
    (LoaderProtocol, lambda: ParquetLoader(base_path=".")),
    (SecuritisationAllocatorProtocol, SecuritisationAllocator),
    (HierarchyResolverProtocol, HierarchyResolver),
    (ClassifierProtocol, ExposureClassifier),
    (CRMProcessorProtocol, CRMProcessor),
    (CollateralLinkAllocatorProtocol, CollateralLinkAllocator),
    (RealEstateSplitterProtocol, RealEstateSplitter),
    (SACalculatorProtocol, SACalculator),
    (IRBCalculatorProtocol, IRBCalculator),
    (SlottingCalculatorProtocol, SlottingCalculator),
    (EquityCalculatorProtocol, EquityCalculator),
    (OutputAggregatorProtocol, OutputAggregator),
    (PipelineProtocol, PipelineOrchestrator),
    (ComparisonRunnerProtocol, DualFrameworkRunner),
    (CapitalImpactAnalyzerProtocol, CapitalImpactAnalyzer),
    (ReconciliationRunnerProtocol, ReconciliationRunner),
    (ResultExporterProtocol, ResultExporter),
]


class TestRealImplementationConformance:
    """Every production component satisfies its protocol at runtime."""

    @pytest.mark.parametrize(
        ("protocol", "factory"),
        _CONFORMANCE_CASES,
        ids=[proto.__name__ for proto, _ in _CONFORMANCE_CASES],
    )
    def test_real_implementation_satisfies_protocol(self, protocol, factory) -> None:
        instance = factory()

        assert isinstance(instance, protocol), (
            f"{type(instance).__name__} no longer satisfies {protocol.__name__} — "
            "the implementation drifted from the contract (or the protocol grew "
            "a method the orchestrator does not need)."
        )

    def test_unrelated_object_fails_isinstance(self) -> None:
        """runtime_checkable protocols reject arbitrary objects."""
        for protocol, _ in _CONFORMANCE_CASES:
            assert not isinstance(object(), protocol), protocol.__name__


class TestTypedAssignment:
    """Static conformance — these assignments are checked by ty."""

    def test_pipeline_component_assignments(self) -> None:
        loader: LoaderProtocol = ParquetLoader(base_path=".")
        allocator: SecuritisationAllocatorProtocol = SecuritisationAllocator()
        resolver: HierarchyResolverProtocol = HierarchyResolver()
        classifier: ClassifierProtocol = ExposureClassifier()
        crm: CRMProcessorProtocol = CRMProcessor()
        link_allocator: CollateralLinkAllocatorProtocol = CollateralLinkAllocator()
        splitter: RealEstateSplitterProtocol = RealEstateSplitter()
        sa: SACalculatorProtocol = SACalculator()
        irb: IRBCalculatorProtocol = IRBCalculator()
        slotting: SlottingCalculatorProtocol = SlottingCalculator()
        equity: EquityCalculatorProtocol = EquityCalculator()
        aggregator: OutputAggregatorProtocol = OutputAggregator()
        pipeline: PipelineProtocol = PipelineOrchestrator()
        comparison: ComparisonRunnerProtocol = DualFrameworkRunner()
        impact: CapitalImpactAnalyzerProtocol = CapitalImpactAnalyzer()
        reconciliation: ReconciliationRunnerProtocol = ReconciliationRunner()
        exporter: ResultExporterProtocol = ResultExporter()

        components = (
            loader,
            allocator,
            resolver,
            classifier,
            crm,
            link_allocator,
            splitter,
            sa,
            irb,
            slotting,
            equity,
            aggregator,
            pipeline,
            comparison,
            impact,
            reconciliation,
            exporter,
        )
        assert all(component is not None for component in components)
