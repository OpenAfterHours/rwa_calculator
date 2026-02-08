"""CRR calculation modules for RWA computations.

This module contains CRR (EU 575/2013) specific calculation logic.
For Basel 3.1 calculations, see workbooks/basel31_expected_outputs/calculations/.
"""

from .crr_risk_weights import (
    get_cgcb_rw,
    get_institution_rw,
    get_corporate_rw,
    get_retail_rw,
    get_residential_mortgage_rw,
    get_commercial_re_rw,
    get_slotting_rw,
    calculate_sa_rwa,
)
from .crr_ccf import (
    get_ccf,
    calculate_ead_off_balance_sheet,
)
from .crr_haircuts import (
    get_collateral_haircut,
    get_fx_haircut,
    calculate_adjusted_collateral_value,
    apply_maturity_mismatch,
)
from .crr_supporting_factors import (
    apply_sme_supporting_factor,
    apply_infrastructure_supporting_factor,
    is_sme_eligible,
)
from .crr_irb import (
    calculate_irb_rwa,
    apply_pd_floor,
    get_firb_lgd,
)

# Re-export shared correlation (same for CRR and Basel 3.1)
from workbooks.shared.correlation import calculate_correlation

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
