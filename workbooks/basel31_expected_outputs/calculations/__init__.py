"""Calculation modules for RWA computations."""

from .ccf import (
    calculate_ead_from_contingent,
    get_ccf,
)
from .correlation import (
    calculate_correlation,
)
from .crm_haircuts import (
    apply_fx_mismatch,
    apply_maturity_mismatch,
    calculate_adjusted_collateral_value,
    calculate_guarantee_substitution,
    get_collateral_haircut,
)
from .irb_formulas import (
    apply_lgd_floor,
    apply_pd_floor,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
)
from .sa_risk_weights import (
    calculate_sa_rwa,
    get_cgcb_risk_weight,
    get_commercial_re_risk_weight,
    get_corporate_risk_weight,
    get_institution_risk_weight,
    get_mortgage_risk_weight,
    get_retail_risk_weight,
    get_slotting_risk_weight,
)

__all__ = [
    # SA
    "get_cgcb_risk_weight",
    "get_institution_risk_weight",
    "get_corporate_risk_weight",
    "get_retail_risk_weight",
    "get_mortgage_risk_weight",
    "get_commercial_re_risk_weight",
    "get_slotting_risk_weight",
    "calculate_sa_rwa",
    # IRB
    "calculate_k",
    "calculate_maturity_adjustment",
    "calculate_irb_rwa",
    "apply_pd_floor",
    "apply_lgd_floor",
    # Correlation
    "calculate_correlation",
    # CRM
    "get_collateral_haircut",
    "apply_maturity_mismatch",
    "apply_fx_mismatch",
    "calculate_adjusted_collateral_value",
    "calculate_guarantee_substitution",
    # CCF
    "get_ccf",
    "calculate_ead_from_contingent",
]
