"""
Centralized data source configuration for RWA Calculator.

Defines all input files, their relative paths, and requirement levels
to ensure consistency between validation and loading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class RequirementLevel(Enum):
    """Requirement level for a data file."""

    MANDATORY = auto()
    """Data file is mandatory for calculation"""

    OPTIONAL = auto()
    """Data file is optional for calculation"""

    AT_LEAST_ONE_IN_GROUP = auto()
    """At least one file from this group is required for calculation"""


@dataclass(frozen=True)
class DataSourceFile:
    """Definition of a single data source file."""

    id: str
    relative_path: Path
    requirement: RequirementLevel
    group: str | None = None
    description: str | None = None

    def get_path(self, extension: str) -> Path:
        """Get the relative path with the given extension."""
        suffix = extension if extension.startswith(".") else f".{extension}"
        return self.relative_path.with_suffix(suffix)


# =============================================================================
# Data Source Registry
# =============================================================================

DATA_SOURCES = [
    # Exposures
    DataSourceFile(
        id="facilities",
        relative_path=Path("exposures/facilities"),
        requirement=RequirementLevel.MANDATORY,
        description="Credit limits and facility details",
    ),
    DataSourceFile(
        id="loans",
        relative_path=Path("exposures/loans"),
        requirement=RequirementLevel.MANDATORY,
        description="Drawn loan balances and characteristics",
    ),
    DataSourceFile(
        id="contingents",
        relative_path=Path("exposures/contingents"),
        requirement=RequirementLevel.OPTIONAL,
        description="Off-balance sheet contingent liabilities",
    ),
    DataSourceFile(
        id="facility_mapping",
        relative_path=Path("exposures/facility_mapping"),
        requirement=RequirementLevel.MANDATORY,
        description="Hierarchy mapping between loans and facilities",
    ),
    # Counterparties
    DataSourceFile(
        id="sovereign",
        relative_path=Path("counterparty/sovereign"),
        requirement=RequirementLevel.AT_LEAST_ONE_IN_GROUP,
        group="counterparty",
        description="Sovereign and central bank counterparties",
    ),
    DataSourceFile(
        id="institution",
        relative_path=Path("counterparty/institution"),
        requirement=RequirementLevel.AT_LEAST_ONE_IN_GROUP,
        group="counterparty",
        description="Bank and investment firm counterparties",
    ),
    DataSourceFile(
        id="corporate",
        relative_path=Path("counterparty/corporate"),
        requirement=RequirementLevel.AT_LEAST_ONE_IN_GROUP,
        group="counterparty",
        description="Corporate and SME counterparties",
    ),
    DataSourceFile(
        id="retail",
        relative_path=Path("counterparty/retail"),
        requirement=RequirementLevel.AT_LEAST_ONE_IN_GROUP,
        group="counterparty",
        description="Individual and small business retail counterparties",
    ),
    DataSourceFile(
        id="specialised_lending",
        relative_path=Path("counterparty/specialised_lending"),
        requirement=RequirementLevel.OPTIONAL,
        description="Specialised lending (project/object finance) counterparties",
    ),
    # Risk Mitigants & Others
    DataSourceFile(
        id="collateral",
        relative_path=Path("collateral/collateral"),
        requirement=RequirementLevel.OPTIONAL,
        description="Collateral and security details",
    ),
    DataSourceFile(
        id="guarantee",
        relative_path=Path("guarantee/guarantee"),
        requirement=RequirementLevel.OPTIONAL,
        description="Personal and corporate guarantees",
    ),
    DataSourceFile(
        id="provision",
        relative_path=Path("provision/provision"),
        requirement=RequirementLevel.OPTIONAL,
        description="Accounting provisions and impairments",
    ),
    DataSourceFile(
        id="ratings",
        relative_path=Path("ratings/ratings"),
        requirement=RequirementLevel.OPTIONAL,
        description="External and internal credit ratings",
    ),
    DataSourceFile(
        id="equity",
        relative_path=Path("equity/equity_exposures"),
        requirement=RequirementLevel.OPTIONAL,
        description="Equity investment exposures",
    ),
    # Mappings
    DataSourceFile(
        id="lending_mapping",
        relative_path=Path("mapping/lending_mapping"),
        requirement=RequirementLevel.MANDATORY,
        description="Mapping to regulatory lending categories",
    ),
    DataSourceFile(
        id="org_mapping",
        relative_path=Path("mapping/org_mapping"),
        requirement=RequirementLevel.OPTIONAL,
        description="Organisational and business unit hierarchy",
    ),
    # Market Data
    DataSourceFile(
        id="fx_rates",
        relative_path=Path("fx_rates/fx_rates"),
        requirement=RequirementLevel.OPTIONAL,
        description="Foreign exchange rates for currency conversion",
    ),
]


@dataclass(frozen=True)
class DataSourceRegistry:
    """Helper to query the data source registry."""

    sources: list[DataSourceFile] = field(default_factory=lambda: DATA_SOURCES)

    def get_by_id(self, source_id: str) -> DataSourceFile | None:
        """Find a source by its ID."""
        for s in self.sources:
            if s.id == source_id:
                return s
        return None

    def get_mandatory(self, extension: str) -> list[Path]:
        """Get relative paths for all strictly mandatory files."""
        return [
            s.get_path(extension)
            for s in self.sources
            if s.requirement == RequirementLevel.MANDATORY
        ]

    def get_optional(self, extension: str) -> list[Path]:
        """Get relative paths for all optional files."""
        return [
            s.get_path(extension)
            for s in self.sources
            if s.requirement == RequirementLevel.OPTIONAL
        ]

    def get_groups(self) -> dict[str, list[DataSourceFile]]:
        """Get all files grouped by their group name."""
        groups: dict[str, list[DataSourceFile]] = {}
        for s in self.sources:
            if s.group:
                if s.group not in groups:
                    groups[s.group] = []
                groups[s.group].append(s)
        return groups

    def get_all_paths(self, extension: str) -> list[Path]:
        """Get relative paths for all known files for a format."""
        return [s.get_path(extension) for s in self.sources]
