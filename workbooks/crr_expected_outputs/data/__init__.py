"""Data loaders and CRR regulatory parameters for RWA calculations.

This module contains CRR (EU 575/2013) specific parameters as onshored
into UK law. For Basel 3.1 parameters (PRA PS9/24), see
workbooks/basel31_expected_outputs/data/.
"""

from workbooks.shared.fixture_loader import load_fixtures, load_fixtures_eager, FixtureData

from .crr_params import (
    # SA risk weights
    CRR_CGCB_RW,
    CRR_INSTITUTION_RW_UK,
    CRR_INSTITUTION_RW_STANDARD,
    CRR_CORPORATE_RW,
    CRR_RETAIL_RW,
    CRR_RESIDENTIAL_RW_LOW_LTV,
    CRR_RESIDENTIAL_RW_HIGH_LTV,
    CRR_RESIDENTIAL_LTV_THRESHOLD,
    CRR_COMMERCIAL_RW_LOW_LTV,
    CRR_COMMERCIAL_RW_STANDARD,
    CRR_COMMERCIAL_LTV_THRESHOLD,
    # Slotting
    CRR_SLOTTING_RW,
    CRR_SLOTTING_RW_HVCRE,
    # CCF
    CRR_CCF,
    # Supporting factors
    CRR_SME_SUPPORTING_FACTOR,
    CRR_INFRASTRUCTURE_SUPPORTING_FACTOR,
    CRR_SME_TURNOVER_THRESHOLD_EUR,
    CRR_SME_TURNOVER_THRESHOLD_GBP,
    # CRM haircuts
    CRR_HAIRCUTS,
    CRR_FX_HAIRCUT,
    # IRB
    CRR_PD_FLOOR,
    CRR_FIRB_LGD,
    # Maturity
    CRR_MATURITY_FLOOR,
    CRR_MATURITY_CAP,
)

__all__ = [
    # Fixture loading
    "load_fixtures",
    "load_fixtures_eager",
    "FixtureData",
    # SA risk weights
    "CRR_CGCB_RW",
    "CRR_INSTITUTION_RW_UK",
    "CRR_INSTITUTION_RW_STANDARD",
    "CRR_CORPORATE_RW",
    "CRR_RETAIL_RW",
    "CRR_RESIDENTIAL_RW_LOW_LTV",
    "CRR_RESIDENTIAL_RW_HIGH_LTV",
    "CRR_RESIDENTIAL_LTV_THRESHOLD",
    "CRR_COMMERCIAL_RW_LOW_LTV",
    "CRR_COMMERCIAL_RW_STANDARD",
    "CRR_COMMERCIAL_LTV_THRESHOLD",
    # Slotting
    "CRR_SLOTTING_RW",
    "CRR_SLOTTING_RW_HVCRE",
    # CCF
    "CRR_CCF",
    # Supporting factors
    "CRR_SME_SUPPORTING_FACTOR",
    "CRR_INFRASTRUCTURE_SUPPORTING_FACTOR",
    "CRR_SME_TURNOVER_THRESHOLD_EUR",
    "CRR_SME_TURNOVER_THRESHOLD_GBP",
    # CRM haircuts
    "CRR_HAIRCUTS",
    "CRR_FX_HAIRCUT",
    # IRB
    "CRR_PD_FLOOR",
    "CRR_FIRB_LGD",
    # Maturity
    "CRR_MATURITY_FLOOR",
    "CRR_MATURITY_CAP",
]
