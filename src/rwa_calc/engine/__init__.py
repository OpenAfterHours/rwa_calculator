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
    stages: The wiring layer, and only the wiring layer — one module per
        registry stage, each exposing the uniform
        ``run(ctx, rulepack, run_config)`` adapter and nothing else. The
        domains those adapters drive are the sibling packages below.
    hierarchy: Counterparty/facility resolution (HierarchyResolver)
    classify: Exposure classification (ExposureClassifier)
    re_split: Real-estate loan splitting (RealEstateSplitter)
    scope: Multi-entity reporting scope resolution
    fx: FX conversion kernel (FXConverter) — not a registry stage; called
        from inside the hierarchy resolver
    crm: Credit Risk Mitigation processing
    sa: Standardised Approach calculator
    irb: IRB approach calculator
    slotting: Specialised lending slotting calculator
    equity: Equity exposure calculator
    aggregator: Result aggregation and output floor application
    kernels: Shared expression kernels reused across calculators
    securitisation: Securitisation pool allocation
    sft: Securities-financing transaction exposure
    ccr: Counterparty credit risk (SA-CCR)
    cva: Credit valuation adjustment
"""

from .hierarchy import HierarchyResolver
from .loader import CSVLoader, ParquetLoader
from .pipeline import PipelineOrchestrator, create_pipeline, create_test_pipeline

__all__ = [
    "ParquetLoader",
    "CSVLoader",
    "HierarchyResolver",
    "PipelineOrchestrator",
    "create_pipeline",
    "create_test_pipeline",
]
