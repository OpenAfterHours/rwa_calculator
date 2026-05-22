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


@dataclass(frozen=True)
class DataSourceFile:
    """Definition of a single data source file."""

    id: str
    relative_path: Path
    requirement: RequirementLevel
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
        id="counterparties",
        relative_path=Path("counterparty/counterparties"),
        requirement=RequirementLevel.MANDATORY,
        description="All counterparty data (sovereigns, institutions, corporates, retail, specialised lending)",
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
    DataSourceFile(
        id="ciu_holdings",
        relative_path=Path("equity/ciu_holdings"),
        requirement=RequirementLevel.OPTIONAL,
        description="CIU look-through holdings for Art. 132(3) equity treatment",
    ),
    DataSourceFile(
        id="specialised_lending",
        relative_path=Path("ratings/specialised_lending"),
        requirement=RequirementLevel.OPTIONAL,
        description="Specialised lending metadata for slotting approach (CRE33)",
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
    # Configuration Data
    DataSourceFile(
        id="model_permissions",
        relative_path=Path("config/model_permissions"),
        requirement=RequirementLevel.OPTIONAL,
        description="Per-model IRB permissions (overrides org-wide IRBPermissions when present)",
    ),
    # Securitisation
    DataSourceFile(
        id="securitisation_allocations",
        relative_path=Path("securitisation/securitisation_allocations"),
        requirement=RequirementLevel.OPTIONAL,
        description=(
            "User-supplied flag mapping originated exposures to securitisation pools. "
            "Phase 1: flag and exclude securitised portions from standard credit-risk "
            "RWA totals (CRR Art. 244-246 / PS1/26 Art. 147A(1)(j))."
        ),
    ),
    # Counterparty Credit Risk (CCR) — P8.5
    # Four optional parquet-backed tables consumed by the SA-CCR pipeline
    # (CRR Art. 271-272). Composed into ``RawCCRBundle`` and attached to
    # ``RawDataBundle.ccr``. Firms without derivative or SFT books leave all
    # four absent and the CCR stage no-ops.
    DataSourceFile(
        id="ccr_trades",
        relative_path=Path("ccr/trades"),
        requirement=RequirementLevel.OPTIONAL,
        description="OTC derivative and SFT trade-level inputs for SA-CCR (CRR Art. 271-272).",
    ),
    DataSourceFile(
        id="ccr_netting_sets",
        relative_path=Path("ccr/netting_sets"),
        requirement=RequirementLevel.OPTIONAL,
        description="Netting-set-level inputs for SA-CCR (CRR Art. 272(4), 295-297).",
    ),
    DataSourceFile(
        id="ccr_margin_agreements",
        relative_path=Path("ccr/margin_agreements"),
        requirement=RequirementLevel.OPTIONAL,
        description="Margin-agreement (CSA) inputs for SA-CCR (CRR Art. 272(7), 285).",
    ),
    DataSourceFile(
        id="ccr_collateral",
        relative_path=Path("ccr/ccr_collateral"),
        requirement=RequirementLevel.OPTIONAL,
        description="Netting-set-keyed collateral inputs for SA-CCR (CRR Art. 275(1)).",
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

    def get_all_paths(self, extension: str) -> list[Path]:
        """Get relative paths for all known files for a format."""
        return [s.get_path(extension) for s in self.sources]
