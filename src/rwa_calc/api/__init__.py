"""
RWA Calculator API Module.

Public API for RWA calculations providing:
- CreditRiskCalc: Single entry point for calculations
- Response models: Clean interface contracts
- ResultsCache: Memory-efficient parquet caching
- Validation utilities: Data path validation

Usage:
    from datetime import date
    from rwa_calc.api import CreditRiskCalc

    response = CreditRiskCalc(
        data_path="/path/to/data",
        framework="CRR",
        reporting_date=date(2024, 12, 31),
        permission_mode="irb",
    ).calculate()

    if response.success:
        print(f"Total RWA: {response.summary.total_rwa:,.0f}")
        print(f"Exposures: {response.summary.exposure_count}")
        results_df = response.collect_results()
"""

from rwa_calc.api.export import (
    ExportResult,
    ResultExporter,
)
from rwa_calc.api.models import (
    APIError,
    CalculationResponse,
    PerformanceMetrics,
    ReconciliationResponse,
    SummaryStatistics,
    ValidationRequest,
    ValidationResponse,
)
from rwa_calc.api.reconciliation import (
    LegacyOutputLoader,
    ReconciliationSettings,
    dump_reconciliation_config,
    load_reconciliation_config,
    loads_reconciliation_config,
)
from rwa_calc.api.rest import (
    create_api_app,
)
from rwa_calc.api.rest import (
    router as api_router,
)
from rwa_calc.api.results_cache import (
    CachedResults,
    ResultsCache,
)
from rwa_calc.api.service import (
    CreditRiskCalc,
    get_default_config,
    get_supported_frameworks,
)
from rwa_calc.api.validation import (
    DataPathValidator,
    get_required_files,
    validate_data_path,
)
from rwa_calc.contracts.config import (
    ComponentMapping,
    LegacyColumnMapping,
)

__all__ = [
    # Service
    "CreditRiskCalc",
    # Utilities
    "get_supported_frameworks",
    "get_default_config",
    # Request models
    "ValidationRequest",
    # Response models
    "CalculationResponse",
    "ValidationResponse",
    "SummaryStatistics",
    "APIError",
    "PerformanceMetrics",
    # REST API
    "create_api_app",
    "api_router",
    # Reconciliation
    "ReconciliationResponse",
    "ReconciliationSettings",
    "LegacyOutputLoader",
    "LegacyColumnMapping",
    "ComponentMapping",
    "load_reconciliation_config",
    "loads_reconciliation_config",
    "dump_reconciliation_config",
    # Export
    "ResultExporter",
    "ExportResult",
    # Cache
    "ResultsCache",
    "CachedResults",
    # Validation
    "DataPathValidator",
    "validate_data_path",
    "get_required_files",
]
