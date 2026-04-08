"""
Domain module for RWA calculator.

Contains core domain entities, enumerations, and value objects
used throughout the calculation pipeline.
"""

from rwa_calc.domain.enums import (
    CQS,
    AIRBCollateralMethod,
    ApproachType,
    CollateralType,
    CommitmentType,
    CRMCollateralMethod,
    ErrorCategory,
    ErrorSeverity,
    EquityApproach,
    EquityType,
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
