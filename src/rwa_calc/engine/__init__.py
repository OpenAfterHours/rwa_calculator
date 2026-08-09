"""
RWA calculation engine components.

This package contains the production implementations of the calculator
pipeline stages:

    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA/IRB/Slotting Calculators -> Aggregator

Each component implements a protocol from rwa_calc.contracts.protocols.

Modules:
    loader: Data loading from files/databases
    registry: The ordered, literal StageSpec list folded by the orchestrator
    orchestrator: run_stages — threads an immutable PipelineContext
    pipeline: Run-lifecycle facade (run_id, edge capture, audit persistence)

Subpackages:
    stages: One package or module per registered pipeline stage. Each holds
        its own stage recipe plus the uniform
        ``run(ctx, rulepack, run_config)`` adapter — e.g. stages.hierarchy
        (HierarchyResolver), stages.classify (ExposureClassifier),
        stages.re_split (RealEstateSplitter), stages.fx (FXConverter).
    crm: Credit Risk Mitigation processing
    sa: Standardised Approach calculator
    irb: IRB approach calculator
    slotting: Specialised lending slotting calculator
    equity: Equity exposure calculator
    aggregator: Result aggregation and output floor application
"""

from .loader import CSVLoader, ParquetLoader
from .pipeline import PipelineOrchestrator, create_pipeline, create_test_pipeline
from .stages.hierarchy import HierarchyResolver

__all__ = [
    "ParquetLoader",
    "CSVLoader",
    "HierarchyResolver",
    "PipelineOrchestrator",
    "create_pipeline",
    "create_test_pipeline",
]
