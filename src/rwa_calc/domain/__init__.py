"""
Domain module for RWA calculator.

Contains core domain entities, enumerations, and value objects
used throughout the calculation pipeline.
"""

from rwa_calc.domain.enums import (
    ApproachType,
    CollateralType,
    CommitmentType,
    CQS,
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
    IFRSStage,
    PropertyType,
    RegulatoryFramework,
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
    "PropertyType",
    "RegulatoryFramework",
    "Seniority",
    "SlottingCategory",
    "SpecialisedLendingType",
]
