"""
RWA calculation engine components.

This package contains the production implementations of the calculator
pipeline stages:

    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA/IRB/Slotting Calculators -> Aggregator

Each component implements a protocol from rwa_calc.contracts.protocols.

Modules:
    loader: Data loading from files/databases
    hierarchy: Counterparty and facility hierarchy resolution
    classifier: Exposure classification and approach assignment
    aggregator: Result aggregation and output floor application
    pipeline: Pipeline orchestration

Subpackages:
    crm: Credit Risk Mitigation processing
    sa: Standardised Approach calculator
    irb: IRB approach calculator
    slotting: Specialised lending slotting calculator

Polars Namespaces:
    All namespaces are registered when their parent modules are imported.
    - lf.irb: IRB approach calculations
    - lf.slotting: Specialised lending slotting
"""

from .comparison import CapitalImpactAnalyzer, DualFrameworkRunner, TransitionalScheduleRunner
from .hierarchy import HierarchyResolver
from .loader import CSVLoader, ParquetLoader
from .pipeline import PipelineOrchestrator, create_pipeline, create_test_pipeline

__all__ = [
    "ParquetLoader",
    "CSVLoader",
    "HierarchyResolver",
    "CapitalImpactAnalyzer",
    "DualFrameworkRunner",
    "TransitionalScheduleRunner",
    "PipelineOrchestrator",
    "create_pipeline",
    "create_test_pipeline",
]
