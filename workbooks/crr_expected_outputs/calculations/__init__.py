"""CRR calculation modules for RWA computations.

This module contains CRR (EU 575/2013) specific calculation logic.
For Basel 3.1 calculations, see workbooks/basel31_expected_outputs/calculations/.
"""

# Re-export shared correlation (same for CRR and Basel 3.1)
from workbooks.shared.correlation import calculate_correlation

from .crr_ccf import (
    calculate_ead_off_balance_sheet,
    get_ccf,
)
from .crr_haircuts import (
    apply_maturity_mismatch,
    calculate_adjusted_collateral_value,
    get_collateral_haircut,
    get_fx_haircut,
)
from .crr_irb import (
    apply_pd_floor,
    calculate_irb_rwa,
    get_firb_lgd,
)
from .crr_risk_weights import (
    calculate_sa_rwa,
    get_cgcb_rw,
    get_commercial_re_rw,
    get_corporate_rw,
    get_institution_rw,
    get_residential_mortgage_rw,
    get_retail_rw,
    get_slotting_rw,
)
from .crr_supporting_factors import (
    apply_infrastructure_supporting_factor,
    apply_sme_supporting_factor,
    is_sme_eligible,
)

__all__ = [
    # SA risk weights
    "get_cgcb_rw",
    "get_institution_rw",
    "get_corporate_rw",
    "get_retail_rw",
    "get_residential_mortgage_rw",
    "get_commercial_re_rw",
    "get_slotting_rw",
    "calculate_sa_rwa",
    # CCF
    "get_ccf",
    "calculate_ead_off_balance_sheet",
    # CRM
    "get_collateral_haircut",
    "get_fx_haircut",
    "calculate_adjusted_collateral_value",
    "apply_maturity_mismatch",
    # Supporting factors
    "apply_sme_supporting_factor",
    "apply_infrastructure_supporting_factor",
    "is_sme_eligible",
    # IRB
    "calculate_irb_rwa",
    "apply_pd_floor",
    "get_firb_lgd",
    # Correlation (shared)
    "calculate_correlation",
]
