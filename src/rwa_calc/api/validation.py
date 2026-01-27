"""
Data path validation utilities for RWA Calculator API.

DataPathValidator: Validates directory structure before calculation
validate_data_path: Convenience function for quick validation

Checks that required files exist and reports missing files clearly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rwa_calc.api.errors import create_file_not_found_error, create_validation_error
from rwa_calc.api.models import APIError, ValidationRequest, ValidationResponse


# =============================================================================
# Required Files Configuration
# =============================================================================


@dataclass(frozen=True)
class RequiredFiles:
    """
    Configuration of required files for RWA calculation.

    Defines mandatory and optional files for each data format.
    """

    mandatory: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)

    @classmethod
    def for_format(cls, data_format: Literal["parquet", "csv"]) -> RequiredFiles:
        """
        Get required files configuration for a data format.

        Args:
            data_format: Either "parquet" or "csv"

        Returns:
            RequiredFiles with appropriate file extensions
        """
        ext = data_format

        mandatory = [
            f"exposures/facilities.{ext}",
            f"exposures/loans.{ext}",
            f"exposures/facility_mapping.{ext}",
            f"mapping/lending_mapping.{ext}",
        ]

        counterparty_files = [
            f"counterparty/sovereign.{ext}",
            f"counterparty/institution.{ext}",
            f"counterparty/corporate.{ext}",
            f"counterparty/retail.{ext}",
        ]

        optional = [
            f"exposures/contingents.{ext}",
            f"collateral/collateral.{ext}",
            f"guarantee/guarantee.{ext}",
            f"provision/provision.{ext}",
            f"ratings/ratings.{ext}",
            f"counterparty/specialised_lending.{ext}",
            f"equity/equity_exposures.{ext}",
            f"mapping/org_mapping.{ext}",
        ]

        return cls(
            mandatory=mandatory + counterparty_files,
            optional=optional,
        )


# =============================================================================
# Data Path Validator
# =============================================================================


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

        if not path.exists():
            errors.append(create_validation_error(
                f"Data path does not exist: {path}",
                path=str(path),
            ))
            return ValidationResponse(
                valid=False,
                data_path=str(path),
                errors=errors,
            )

        if not path.is_dir():
            errors.append(create_validation_error(
                f"Data path is not a directory: {path}",
                path=str(path),
            ))
            return ValidationResponse(
                valid=False,
                data_path=str(path),
                errors=errors,
            )

        required = RequiredFiles.for_format(request.data_format)

        files_found: list[str] = []
        files_missing: list[str] = []

        has_any_counterparty = False
        counterparty_prefix = f"counterparty/"

        for file_path in required.mandatory:
            full_path = path / file_path

            if full_path.exists():
                files_found.append(file_path)
                if file_path.startswith(counterparty_prefix):
                    has_any_counterparty = True
            else:
                if file_path.startswith(counterparty_prefix):
                    files_missing.append(file_path)
                else:
                    files_missing.append(file_path)
                    errors.append(create_file_not_found_error(file_path))

        counterparty_missing = [
            f for f in files_missing if f.startswith(counterparty_prefix)
        ]
        if counterparty_missing and not has_any_counterparty:
            errors.append(create_validation_error(
                "At least one counterparty file is required",
                path=str(path / "counterparty"),
            ))

        files_missing = [
            f for f in files_missing if not f.startswith(counterparty_prefix) or not has_any_counterparty
        ]

        for file_path in required.optional:
            full_path = path / file_path
            if full_path.exists():
                files_found.append(file_path)

        valid = len(errors) == 0

        return ValidationResponse(
            valid=valid,
            data_path=str(path),
            files_found=sorted(files_found),
            files_missing=sorted(files_missing),
            errors=errors,
        )

    def check_file_exists(
        self,
        base_path: Path,
        relative_path: str,
    ) -> tuple[bool, str | None]:
        """
        Check if a specific file exists.

        Args:
            base_path: Base directory path
            relative_path: Relative path to file

        Returns:
            Tuple of (exists, full_path_if_exists)
        """
        full_path = base_path / relative_path
        if full_path.exists():
            return True, str(full_path)
        return False, None


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

    Example:
        response = validate_data_path("/path/to/data")
        if response.valid:
            print("Ready for calculation")
        else:
            for file in response.files_missing:
                print(f"Missing: {file}")
    """
    validator = DataPathValidator()
    request = ValidationRequest(data_path=data_path, data_format=data_format)
    return validator.validate(request)


def get_required_files(
    data_format: Literal["parquet", "csv"] = "parquet",
) -> list[str]:
    """
    Get list of required files for a given format.

    Args:
        data_format: Format of data files

    Returns:
        List of required file paths
    """
    required = RequiredFiles.for_format(data_format)
    return required.mandatory + required.optional
