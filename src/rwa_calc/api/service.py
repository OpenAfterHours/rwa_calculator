"""
RWA Calculator API Service.

RWAService provides a clean facade for RWA calculations:
- calculate: Run RWA calculation with pre-validated data
- validate_data_path: Check data directory before calculation
- get_supported_frameworks: List available regulatory frameworks
- get_default_config: Get default configuration for a framework

This is the main entry point for UI and CLI integration.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rwa_calc.api.errors import create_load_error
from rwa_calc.api.formatters import ResultFormatter
from rwa_calc.api.models import (
    CalculationRequest,
    CalculationResponse,
    ValidationRequest,
    ValidationResponse,
)
from rwa_calc.api.validation import DataPathValidator

if TYPE_CHECKING:
    pass


# =============================================================================
# RWA Service
# =============================================================================


class RWAService:
    """
    High-level service for RWA calculations.

    Wraps the PipelineOrchestrator with a clean API surface suitable
    for UI integration. Handles configuration setup, data loading,
    and result formatting.

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
            print(response.results)
    """

    def __init__(self) -> None:
        """Initialize RWAService with default components."""
        self._validator = DataPathValidator()
        self._formatter = ResultFormatter()

    def calculate(self, request: CalculationRequest) -> CalculationResponse:
        """
        Run RWA calculation with the specified parameters.

        Creates pipeline configuration from request, loads data,
        runs calculation, and formats results.

        Args:
            request: CalculationRequest with all parameters

        Returns:
            CalculationResponse with results or errors
        """
        started_at = datetime.now()

        validation = self._validator.validate(
            ValidationRequest(
                data_path=request.data_path,
                data_format=request.data_format,
            )
        )
        if not validation.valid:
            return self._formatter.format_error_response(
                errors=validation.errors,
                framework=request.framework,
                reporting_date=request.reporting_date,
                started_at=started_at,
            )

        try:
            config = self._create_config(request)
            loader = self._create_loader(request)
            pipeline = self._create_pipeline(loader)

            result_bundle = pipeline.run(config)

            return self._formatter.format_response(
                bundle=result_bundle,
                framework=request.framework,
                reporting_date=request.reporting_date,
                started_at=started_at,
            )

        except Exception as e:
            error = create_load_error(str(e))
            return self._formatter.format_error_response(
                errors=[error],
                framework=request.framework,
                reporting_date=request.reporting_date,
                started_at=started_at,
            )

    def validate_data_path(self, request: ValidationRequest) -> ValidationResponse:
        """
        Validate a data path for calculation readiness.

        Checks that the directory exists and contains required files.

        Args:
            request: ValidationRequest with path and format

        Returns:
            ValidationResponse with validation results
        """
        return self._validator.validate(request)

    def get_supported_frameworks(self) -> list[dict[str, str]]:
        """
        Get list of supported regulatory frameworks.

        Returns:
            List of framework descriptors with id, name, and description
        """
        return [
            {
                "id": "CRR",
                "name": "CRR (Basel 3.0)",
                "description": "Capital Requirements Regulation - effective until Dec 2026",
            },
            {
                "id": "BASEL_3_1",
                "name": "Basel 3.1",
                "description": "PRA PS9/24 UK implementation - effective from Jan 2027",
            },
        ]

    def get_default_config(
        self,
        framework: Literal["CRR", "BASEL_3_1"],
        reporting_date: date,
    ) -> dict:
        """
        Get default configuration values for a framework.

        Args:
            framework: Regulatory framework
            reporting_date: As-of date for calculation

        Returns:
            Dictionary of default configuration values
        """
        from rwa_calc.contracts.config import CalculationConfig

        if framework == "CRR":
            config = CalculationConfig.crr(reporting_date=reporting_date)
        else:
            config = CalculationConfig.basel_3_1(reporting_date=reporting_date)

        return {
            "framework": config.framework.value,
            "reporting_date": config.reporting_date.isoformat(),
            "base_currency": config.base_currency,
            "scaling_factor": str(config.scaling_factor),
            "eur_gbp_rate": str(config.eur_gbp_rate),
            "pd_floors": {
                "corporate": str(config.pd_floors.corporate),
                "retail_mortgage": str(config.pd_floors.retail_mortgage),
            },
            "supporting_factors_enabled": config.supporting_factors.enabled,
            "output_floor_enabled": config.output_floor.enabled,
            "output_floor_percentage": str(
                config.output_floor.get_floor_percentage(reporting_date)
            ),
        }

    def _create_config(self, request: CalculationRequest) -> "CalculationConfig":
        """
        Create CalculationConfig from request parameters.

        Args:
            request: CalculationRequest with parameters

        Returns:
            Configured CalculationConfig
        """
        from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

        irb_permissions = (
            IRBPermissions.full_irb() if request.enable_irb else IRBPermissions.sa_only()
        )

        if request.framework == "CRR":
            return CalculationConfig.crr(
                reporting_date=request.reporting_date,
                irb_permissions=irb_permissions,
                eur_gbp_rate=request.eur_gbp_rate,
            )
        else:
            return CalculationConfig.basel_3_1(
                reporting_date=request.reporting_date,
                irb_permissions=irb_permissions,
            )

    def _create_loader(self, request: CalculationRequest) -> "LoaderProtocol":
        """
        Create data loader based on request format.

        Args:
            request: CalculationRequest with data path and format

        Returns:
            Appropriate loader instance
        """
        from rwa_calc.engine.loader import CSVLoader, ParquetLoader

        if request.data_format == "csv":
            return CSVLoader(base_path=request.path)
        else:
            return ParquetLoader(base_path=request.path)

    def _create_pipeline(self, loader: "LoaderProtocol") -> "PipelineOrchestrator":
        """
        Create pipeline orchestrator with loader.

        Args:
            loader: Data loader instance

        Returns:
            Configured PipelineOrchestrator
        """
        from rwa_calc.engine.pipeline import PipelineOrchestrator

        return PipelineOrchestrator(loader=loader)


# =============================================================================
# Type Hints for Internal Use
# =============================================================================


if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.protocols import LoaderProtocol
    from rwa_calc.engine.pipeline import PipelineOrchestrator


# =============================================================================
# Convenience Functions
# =============================================================================


def create_service() -> RWAService:
    """
    Factory function to create RWAService instance.

    Returns:
        Configured RWAService
    """
    return RWAService()


def quick_calculate(
    data_path: str | Path,
    framework: Literal["CRR", "BASEL_3_1"] = "CRR",
    reporting_date: date | None = None,
    enable_irb: bool = False,
    data_format: Literal["parquet", "csv"] = "parquet",
) -> CalculationResponse:
    """
    Run a quick calculation with minimal configuration.

    Convenience function for simple use cases.

    Args:
        data_path: Path to data directory
        framework: Regulatory framework
        reporting_date: As-of date (defaults to today)
        enable_irb: Whether to enable IRB approaches
        data_format: Format of input files

    Returns:
        CalculationResponse with results

    Example:
        response = quick_calculate("/path/to/data", framework="CRR")
        print(f"Total RWA: {response.summary.total_rwa:,.0f}")
    """
    service = RWAService()
    request = CalculationRequest(
        data_path=data_path,
        framework=framework,
        reporting_date=reporting_date or date.today(),
        enable_irb=enable_irb,
        data_format=data_format,
    )
    return service.calculate(request)
