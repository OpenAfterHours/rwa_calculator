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
    - lf.sa: Standardised Approach calculations
    - lf.irb: IRB approach calculations
    - lf.crm: Credit Risk Mitigation
    - lf.haircuts: Collateral haircuts
    - lf.slotting: Specialised lending slotting
    - lf.hierarchy: Hierarchy resolution
    - lf.aggregator: Result aggregation
    - lf.audit: Audit trail formatting
"""

# Import namespace modules to register namespaces on module load
import rwa_calc.engine.aggregator_namespace  # noqa: F401
import rwa_calc.engine.audit_namespace  # noqa: F401
import rwa_calc.engine.hierarchy_namespace  # noqa: F401

from .aggregator import OutputAggregator, create_output_aggregator
from .aggregator_namespace import AggregatorLazyFrame
from .audit_namespace import AuditExpr, AuditLazyFrame
from .comparison import DualFrameworkRunner
from .hierarchy import HierarchyResolver, create_hierarchy_resolver
from .hierarchy_namespace import HierarchyLazyFrame
from .loader import CSVLoader, ParquetLoader
from .pipeline import PipelineOrchestrator, create_pipeline, create_test_pipeline

__all__ = [
    "ParquetLoader",
    "CSVLoader",
    "HierarchyResolver",
    "create_hierarchy_resolver",
    "OutputAggregator",
    "create_output_aggregator",
    "DualFrameworkRunner",
    "PipelineOrchestrator",
    "create_pipeline",
    "create_test_pipeline",
    # Namespace classes
    "HierarchyLazyFrame",
    "AggregatorLazyFrame",
    "AuditLazyFrame",
    "AuditExpr",
]
