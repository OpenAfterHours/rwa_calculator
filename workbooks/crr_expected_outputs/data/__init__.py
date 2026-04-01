"""Data loaders and CRR regulatory parameters for RWA calculations.

This module contains CRR (EU 575/2013) specific parameters as onshored
into UK law. For Basel 3.1 parameters (PRA PS1/26), see
workbooks/basel31_expected_outputs/data/.
"""

from workbooks.shared.fixture_loader import FixtureData, load_fixtures, load_fixtures_eager

from .crr_params import (
    # CCF
    CRR_CCF,
    # SA risk weights
    CRR_CGCB_RW,
    CRR_COMMERCIAL_LTV_THRESHOLD,
    CRR_COMMERCIAL_RW_LOW_LTV,
    CRR_COMMERCIAL_RW_STANDARD,
    CRR_CORPORATE_RW,
    CRR_FIRB_LGD,
    CRR_FX_HAIRCUT,
    # CRM haircuts
    CRR_HAIRCUTS,
    CRR_INFRASTRUCTURE_SUPPORTING_FACTOR,
    CRR_INSTITUTION_RW_STANDARD,
    CRR_INSTITUTION_RW_UK,
    CRR_MATURITY_CAP,
    # Maturity
    CRR_MATURITY_FLOOR,
    # IRB
    CRR_PD_FLOOR,
    CRR_RESIDENTIAL_LTV_THRESHOLD,
    CRR_RESIDENTIAL_RW_HIGH_LTV,
    CRR_RESIDENTIAL_RW_LOW_LTV,
    CRR_RETAIL_RW,
    # Slotting
    CRR_SLOTTING_RW,
    CRR_SLOTTING_RW_HVCRE,
    # Supporting factors
    CRR_SME_SUPPORTING_FACTOR,
    CRR_SME_TURNOVER_THRESHOLD_EUR,
    CRR_SME_TURNOVER_THRESHOLD_GBP,
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
