"""
Domain module for RWA calculator.

Holds the shared enumerations (``enums.py``) used throughout the calculation
pipeline. There are no domain entities or value objects here — typed data
transfer lives in ``rwa_calc.contracts.bundles``.
"""

from rwa_calc.domain.enums import (
    CQS,
    AIRBCollateralMethod,
    ApproachType,
    CollateralType,
    CommitmentType,
    CRMCollateralMethod,
    EquityApproach,
    EquityType,
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
    IFRSStage,
    InstitutionType,
    PermissionMode,
    PropertyType,
    RegulatoryFramework,
    ReportingBasis,
    RiskType,
    SCRAGrade,
    Seniority,
    SlottingCategory,
    SpecialisedLendingType,
)

__all__ = [
    "AIRBCollateralMethod",
    "ApproachType",
    "CollateralType",
    "CommitmentType",
    "CQS",
    "CRMCollateralMethod",
    "ErrorCategory",
    "ErrorSeverity",
    "EquityApproach",
    "EquityType",
    "ExposureClass",
    "IFRSStage",
    "InstitutionType",
    "PermissionMode",
    "PropertyType",
    "RegulatoryFramework",
    "ReportingBasis",
    "RiskType",
    "SCRAGrade",
    "Seniority",
    "SlottingCategory",
    "SpecialisedLendingType",
]
