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
"""

from .loader import ParquetLoader, CSVLoader
from .hierarchy import HierarchyResolver, create_hierarchy_resolver
from .aggregator import OutputAggregator, create_output_aggregator

__all__ = [
    "ParquetLoader",
    "CSVLoader",
    "HierarchyResolver",
    "create_hierarchy_resolver",
    "OutputAggregator",
    "create_output_aggregator",
]
