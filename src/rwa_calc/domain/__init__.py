"""
Domain module for RWA calculator.

Contains core domain entities, enumerations, and value objects
used throughout the calculation pipeline.
"""

from rwa_calc.domain.enums import (
    CQS,
    ApproachType,
    CollateralType,
    CommitmentType,
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
    IFRSStage,
    IRBApproachOption,
    PropertyType,
    RegulatoryFramework,
    RiskType,
    Seniority,
    SlottingCategory,
    SpecialisedLendingType,
)

__all__ = [
    "ApproachType",
    "CollateralType",
    "CommitmentType",
    "CQS",
    "ErrorCategory",
    "ErrorSeverity",
    "ExposureClass",
    "IFRSStage",
    "IRBApproachOption",
    "PropertyType",
    "RegulatoryFramework",
    "RiskType",
    "Seniority",
    "SlottingCategory",
    "SpecialisedLendingType",
]
