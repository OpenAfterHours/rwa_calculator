"""
Contracts module for RWA calculator.

Provides interfaces, data transfer objects, and validation utilities
for the RWA calculation pipeline. This module enables:
- Isolated unit testing of each component
- Parallel development of different components
- Clear data flow boundaries
- Dual-framework support (CRR + Basel 3.1)

Submodules:
- bundles: Data transfer dataclasses for pipeline stages
- config: CalculationConfig and related configuration classes
- errors: CalculationError and LazyFrameResult for error handling
- protocols: Protocol definitions for component interfaces
- validation: Schema validation utilities
"""

# Configuration contracts
from rwa_calc.contracts.config import (
    CalculationConfig,
    IRBPermissions,
    LGDFloors,
    OutputFloorConfig,
    PDFloors,
    RetailThresholds,
    SupportingFactors,
)

# Error handling contracts
from rwa_calc.contracts.errors import (
    ERROR_APPROACH_NOT_PERMITTED,
    ERROR_CIRCULAR_HIERARCHY,
    ERROR_COLLATERAL_OVERALLOCATION,
    ERROR_CURRENCY_MISMATCH,
    ERROR_DUPLICATE_KEY,
    ERROR_HIERARCHY_DEPTH,
    ERROR_INELIGIBLE_COLLATERAL,
    ERROR_INVALID_CONFIG,
    ERROR_INVALID_CQS,
    ERROR_INVALID_LTV,
    ERROR_INVALID_VALUE,
    ERROR_LGD_OUT_OF_RANGE,
    ERROR_MATURITY_INVALID,
    ERROR_MATURITY_MISMATCH,
    ERROR_MISSING_FIELD,
    ERROR_MISSING_LGD,
    ERROR_MISSING_PARENT,
    ERROR_MISSING_PD,
    ERROR_MISSING_PERMISSION,
    ERROR_MISSING_RATING,
    ERROR_MISSING_RISK_WEIGHT,
    ERROR_ORPHAN_REFERENCE,
    ERROR_PD_OUT_OF_RANGE,
    ERROR_TYPE_MISMATCH,
    ERROR_UNKNOWN_EXPOSURE_CLASS,
    ERROR_INVALID_GUARANTEE,
    CalculationError,
    LazyFrameResult,
    business_rule_error,
    crm_warning,
    hierarchy_error,
    invalid_value_error,
    missing_field_error,
)

# Data bundle contracts
from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    CRMAdjustedBundle,
    IRBResultBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
    SAResultBundle,
    create_empty_classified_bundle,
    create_empty_counterparty_lookup,
    create_empty_crm_adjusted_bundle,
    create_empty_raw_data_bundle,
    create_empty_resolved_hierarchy_bundle,
)

# Protocol definitions
from rwa_calc.contracts.protocols import (
    ClassifierProtocol,
    CRMProcessorProtocol,
    DataQualityCheckerProtocol,
    HierarchyResolverProtocol,
    IRBCalculatorProtocol,
    LoaderProtocol,
    OutputAggregatorProtocol,
    PipelineProtocol,
    SACalculatorProtocol,
    SchemaValidatorProtocol,
    SlottingCalculatorProtocol,
)

# Validation utilities
from rwa_calc.contracts.validation import (
    validate_classified_bundle,
    validate_crm_adjusted_bundle,
    validate_lgd_range,
    validate_non_negative_amounts,
    validate_pd_range,
    validate_raw_data_bundle,
    validate_required_columns,
    validate_resolved_hierarchy_bundle,
    validate_schema,
    validate_schema_to_errors,
)

__all__ = [
    # Configuration
    "CalculationConfig",
    "IRBPermissions",
    "LGDFloors",
    "OutputFloorConfig",
    "PDFloors",
    "RetailThresholds",
    "SupportingFactors",
    # Errors
    "CalculationError",
    "LazyFrameResult",
    "business_rule_error",
    "crm_warning",
    "hierarchy_error",
    "invalid_value_error",
    "missing_field_error",
    # Error codes
    "ERROR_APPROACH_NOT_PERMITTED",
    "ERROR_CIRCULAR_HIERARCHY",
    "ERROR_COLLATERAL_OVERALLOCATION",
    "ERROR_CURRENCY_MISMATCH",
    "ERROR_DUPLICATE_KEY",
    "ERROR_HIERARCHY_DEPTH",
    "ERROR_INELIGIBLE_COLLATERAL",
    "ERROR_INVALID_CONFIG",
    "ERROR_INVALID_CQS",
    "ERROR_INVALID_GUARANTEE",
    "ERROR_INVALID_LTV",
    "ERROR_INVALID_VALUE",
    "ERROR_LGD_OUT_OF_RANGE",
    "ERROR_MATURITY_INVALID",
    "ERROR_MATURITY_MISMATCH",
    "ERROR_MISSING_FIELD",
    "ERROR_MISSING_LGD",
    "ERROR_MISSING_PARENT",
    "ERROR_MISSING_PD",
    "ERROR_MISSING_PERMISSION",
    "ERROR_MISSING_RATING",
    "ERROR_MISSING_RISK_WEIGHT",
    "ERROR_ORPHAN_REFERENCE",
    "ERROR_PD_OUT_OF_RANGE",
    "ERROR_TYPE_MISMATCH",
    "ERROR_UNKNOWN_EXPOSURE_CLASS",
    # Bundles
    "AggregatedResultBundle",
    "ClassifiedExposuresBundle",
    "CounterpartyLookup",
    "CRMAdjustedBundle",
    "IRBResultBundle",
    "RawDataBundle",
    "ResolvedHierarchyBundle",
    "SAResultBundle",
    "create_empty_classified_bundle",
    "create_empty_counterparty_lookup",
    "create_empty_crm_adjusted_bundle",
    "create_empty_raw_data_bundle",
    "create_empty_resolved_hierarchy_bundle",
    # Protocols
    "ClassifierProtocol",
    "CRMProcessorProtocol",
    "DataQualityCheckerProtocol",
    "HierarchyResolverProtocol",
    "IRBCalculatorProtocol",
    "LoaderProtocol",
    "OutputAggregatorProtocol",
    "PipelineProtocol",
    "SACalculatorProtocol",
    "SchemaValidatorProtocol",
    "SlottingCalculatorProtocol",
    # Validation
    "validate_classified_bundle",
    "validate_crm_adjusted_bundle",
    "validate_lgd_range",
    "validate_non_negative_amounts",
    "validate_pd_range",
    "validate_raw_data_bundle",
    "validate_required_columns",
    "validate_resolved_hierarchy_bundle",
    "validate_schema",
    "validate_schema_to_errors",
]
