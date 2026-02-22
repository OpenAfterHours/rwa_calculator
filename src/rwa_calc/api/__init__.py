"""
RWA Calculator API Module.

Public API for RWA calculations providing:
- RWAService: Main service facade for calculations
- Request/Response models: Clean interface contracts
- ResultsCache: Memory-efficient parquet caching
- Validation utilities: Data path validation

Usage:
    from rwa_calc.api import RWAService, CalculationRequest
    from datetime import date
    from pathlib import Path

    service = RWAService(cache_dir=Path(".cache"))
    response = service.calculate(
        CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="full_irb",
        )
    )

    if response.success:
        print(f"Total RWA: {response.summary.total_rwa:,.0f}")
        print(f"Exposures: {response.summary.exposure_count}")
        results_df = response.collect_results()
"""

from rwa_calc.api.models import (
    APIError,
    CalculationRequest,
    CalculationResponse,
    PerformanceMetrics,
    SummaryStatistics,
    ValidationRequest,
    ValidationResponse,
)
from rwa_calc.api.results_cache import (
    CachedResults,
    ResultsCache,
)
from rwa_calc.api.service import (
    RWAService,
    create_service,
    quick_calculate,
)
from rwa_calc.api.validation import (
    DataPathValidator,
    get_required_files,
    validate_data_path,
)

__all__ = [
    # Service
    "RWAService",
    "create_service",
    "quick_calculate",
    # Request models
    "CalculationRequest",
    "ValidationRequest",
    # Response models
    "CalculationResponse",
    "ValidationResponse",
    "SummaryStatistics",
    "APIError",
    "PerformanceMetrics",
    # Cache
    "ResultsCache",
    "CachedResults",
    # Validation
    "DataPathValidator",
    "validate_data_path",
    "get_required_files",
]
