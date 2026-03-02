"""
Data path validation utilities for RWA Calculator API.

DataPathValidator: Validates directory structure before calculation
validate_data_path: Convenience function for quick validation

Checks that required files exist and reports missing files clearly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rwa_calc.api.errors import create_file_not_found_error, create_validation_error
from rwa_calc.api.models import APIError, ValidationRequest, ValidationResponse
from rwa_calc.config.data_sources import DataSourceRegistry


class DataPathValidator:
    """
    Validates directory structure for RWA calculation.

    Checks that the data directory exists and contains
    all required files before running a calculation.

    Usage:
        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(
            data_path="/path/to/data",
            data_format="parquet",
        ))
        if response.valid:
            # Proceed with calculation
        else:
            # Handle missing files
    """

    def __init__(self, registry: DataSourceRegistry | None = None) -> None:
        """
        Initialize validator with a data source registry.

        Args:
            registry: Registry defining expected files (defaults to global registry)
        """
        self.registry = registry or DataSourceRegistry()

    def validate(self, request: ValidationRequest) -> ValidationResponse:
        """
        Validate a data path for calculation readiness.

        Args:
            request: ValidationRequest with path and format

          Returns:
            ValidationResponse with validation results
        """
        path = request.path
        errors: list[APIError] = []

        # 1. Base directory validation
        if not path.exists():
            return self._fail(path, f"Data path does not exist: {path}")

        if not path.is_dir():
            return self._fail(path, f"Data path is not a directory: {path}")

        # 2. File content validation
        files_found: list[Path] = []
        files_missing: list[Path] = []

        self._check_mandatory(path, request.data_format, files_found, files_missing, errors)
        self._check_groups(path, request.data_format, files_found, files_missing, errors)
        self._check_optional(path, request.data_format, files_found)

        return ValidationResponse(
            valid=len(errors) == 0,
            data_path=path,
            files_found=sorted(files_found),
            files_missing=sorted(files_missing),
            errors=errors,
        )

    def _fail(self, path: Path, message: str) -> ValidationResponse:
        """Create a failure response for top-level path errors."""
        return ValidationResponse(
            valid=False,
            data_path=path,
            errors=[create_validation_error(message, path=path)],
        )

    def _check_mandatory(
        self,
        base_path: Path,
        fmt: str,
        found: list[Path],
        missing: list[Path],
        errors: list[APIError],
    ) -> None:
        """Check all strictly mandatory files."""
        for file_path in self.registry.get_mandatory(fmt):
            if (base_path / file_path).exists():
                found.append(file_path)
            else:
                missing.append(file_path)
                errors.append(create_file_not_found_error(file_path))

    def _check_groups(
        self,
        base_path: Path,
        fmt: str,
        found: list[Path],
        missing: list[Path],
        errors: list[APIError],
    ) -> None:
        """Check group-based mandatory files (e.g. at least one counterparty)."""
        for group_name, group_files in self.registry.get_groups().items():
            group_found = []
            group_missing = []

            for source in group_files:
                file_path = source.get_path(fmt)
                if (base_path / file_path).exists():
                    group_found.append(file_path)
                else:
                    group_missing.append(file_path)

            if not group_found:
                errors.append(
                    create_validation_error(
                        f"At least one {group_name} file is required",
                        path=base_path / group_name,
                    )
                )
                missing.extend(group_missing)
            else:
                found.extend(group_found)

    def _check_optional(self, base_path: Path, fmt: str, found: list[Path]) -> None:
        """Check optional files and record if they exist."""
        for file_path in self.registry.get_optional(fmt):
            if (base_path / file_path).exists():
                found.append(file_path)


# =============================================================================
# Convenience Functions
# =============================================================================


def validate_data_path(
    data_path: str | Path,
    data_format: Literal["parquet", "csv"] = "parquet",
) -> ValidationResponse:
    """
    Validate a data path for calculation readiness.

    Convenience function for quick validation without creating
    a validator instance.

    Args:
        data_path: Path to data directory
        data_format: Format of data files

    Returns:
        ValidationResponse with validation results
    """
    validator = DataPathValidator()
    request = ValidationRequest(data_path=data_path, data_format=data_format)
    return validator.validate(request)


def get_required_files(
    data_format: Literal["parquet", "csv"] = "parquet",
) -> list[Path]:
    """
    Get list of all expected files for a given format.

    Args:
        data_format: Format of data files

    Returns:
        Sorted list of expected file paths
    """
    registry = DataSourceRegistry()
    return sorted(registry.get_all_paths(data_format))
