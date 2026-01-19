"""
RWA Calculator API Module.

Public API for RWA calculations providing:
- RWAService: Main service facade for calculations
- Request/Response models: Clean interface contracts
- Validation utilities: Data path validation

Usage:
    from rwa_calc.api import RWAService, CalculationRequest
    from datetime import date

    service = RWAService()
    response = service.calculate(
        CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            enable_irb=True,
        )
    )

    if response.success:
        print(f"Total RWA: {response.summary.total_rwa:,.0f}")
        print(f"Exposures: {response.summary.exposure_count}")
        print(response.results)
    else:
        for error in response.errors:
            print(f"{error.code}: {error.message}")
"""

from rwa_calc.api.models import (
    APIError,
    CalculationRequest,
    CalculationResponse,
    PerformanceMetrics,
    SummaryByDimension,
    SummaryStatistics,
    ValidationRequest,
    ValidationResponse,
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
    "SummaryByDimension",
    "APIError",
    "PerformanceMetrics",
    # Validation
    "DataPathValidator",
    "validate_data_path",
    "get_required_files",
]
