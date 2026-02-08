"""Calculation modules for RWA computations."""

from .sa_risk_weights import (
    get_cgcb_risk_weight,
    get_institution_risk_weight,
    get_corporate_risk_weight,
    get_retail_risk_weight,
    get_mortgage_risk_weight,
    get_commercial_re_risk_weight,
    get_slotting_risk_weight,
    calculate_sa_rwa,
)
from .irb_formulas import (
    calculate_k,
    calculate_maturity_adjustment,
    calculate_irb_rwa,
    apply_pd_floor,
    apply_lgd_floor,
)
from .correlation import (
    calculate_correlation,
)
from .crm_haircuts import (
    get_collateral_haircut,
    apply_maturity_mismatch,
    apply_fx_mismatch,
    calculate_adjusted_collateral_value,
    calculate_guarantee_substitution,
)
from .ccf import (
    get_ccf,
    calculate_ead_from_contingent,
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
