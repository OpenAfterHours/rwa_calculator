"""
Data path validation utilities for RWA Calculator API.

DataPathValidator: Validates directory structure before calculation
validate_data_path: Convenience function for quick validation

Checks that required files exist and reports missing files clearly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from rwa_calc.api.errors import (
    create_file_not_found_error,
    create_irb_required_file_error,
    create_validation_error,
)
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
        self._check_optional(path, request.data_format, files_found)
        if request.permission_mode == "irb":
            self._check_irb_required(path, request.data_format, files_found, files_missing, errors)

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

    def _check_optional(self, base_path: Path, fmt: str, found: list[Path]) -> None:
        """Check optional files and record if they exist."""
        for file_path in self.registry.get_optional(fmt):
            if (base_path / file_path).exists():
                found.append(file_path)

    def _check_irb_required(
        self,
        base_path: Path,
        fmt: str,
        found: list[Path],
        missing: list[Path],
        errors: list[APIError],
    ) -> None:
        """
        Check files that are required only when permission_mode='irb'.

        Currently this is just config/model_permissions — it is registered
        as OPTIONAL in DataSourceRegistry (because in standardised mode it
        is genuinely optional) but is mandatory in IRB mode (P1.147).
        """
        source = self.registry.get_by_id("model_permissions")
        if source is None:
            return
        relative = source.get_path(fmt)
        if (base_path / relative).exists():
            if relative not in found:
                found.append(relative)
            return
        missing.append(relative)
        errors.append(create_irb_required_file_error(relative))


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


# Windows device names that are invalid as a path component — rejected up front
# so an output write can never be silently redirected to a device.
_WIN_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def validate_output_path(output_path: str | Path) -> ValidationResponse:
    """
    Validate a directory the user has chosen to write calculation outputs into.

    Output semantics (distinct from ``validate_data_path``, which checks input-file
    presence): the path must be absolute and resolvable; if it already exists it
    must be a writable directory; if it does not, its immediate parent must exist
    and be writable, so a typo cannot create a deep tree in a surprising place.
    Errors are accumulated into the ``ValidationResponse`` — never raised.

    ``os.access(W_OK)`` is advisory only (it ignores Windows ACLs), so the
    authoritative writability check remains the wrapped write itself.

    Args:
        output_path: The chosen output folder.

    Returns:
        ValidationResponse with ``valid`` set and any VAL001 errors.
    """
    raw = str(output_path).strip()
    if not raw:
        return _output_fail(raw, "Output folder is empty.")

    path = Path(raw).expanduser()
    if not path.is_absolute():
        return _output_fail(path, f"Output folder must be an absolute path: {raw}")

    if sys.platform == "win32" and any(
        part.split(".")[0].upper() in _WIN_RESERVED for part in path.parts
    ):
        return _output_fail(path, f"Output folder uses a reserved device name: {raw}")

    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir():
            return _output_fail(resolved, f"Output path is not a directory: {resolved}")
        if not os.access(resolved, os.W_OK):
            return _output_fail(resolved, f"Output folder is not writable: {resolved}")
        return ValidationResponse(valid=True, data_path=resolved)

    parent = resolved.parent
    if not parent.exists() or not parent.is_dir():
        return _output_fail(resolved, f"Output folder's parent does not exist: {parent}")
    if not os.access(parent, os.W_OK):
        return _output_fail(resolved, f"Cannot create the output folder under: {parent}")
    return ValidationResponse(valid=True, data_path=resolved)


def _output_fail(path: Path | str, message: str) -> ValidationResponse:
    """Build a non-valid output-path ValidationResponse carrying a VAL001 error."""
    return ValidationResponse(
        valid=False,
        data_path=path,
        errors=[create_validation_error(message, path=path)],
    )
