"""
CRM-shape supervisory values for F-IRB collateral processing — CRR Art. 161 /
230 and PRA PS1/26 / CRE32.9-12.

Pipeline position:
    Data Tables -> CRM Processor (collateral.py, haircuts.py)

Key responsibilities:
- Hold the CRM-shape view of supervisory data for both CRR and Basel 3.1
- Provide LGD, overcollateralisation ratio, and minimum threshold dicts
  keyed by simple collateral category (financial, receivables, real_estate,
  other_physical, covered_bond, life_insurance, unsecured) for use by
  Polars expression builders in engine/crm/

Sibling modules:
- firb_lgd.py holds the FIRB-shape view (split into residential_re/
  commercial_re, FSE/non-FSE, senior/subordinated) used by IRB-direct
  lookups. Both shapes encode the same regulatory data — this module is
  the canonical CRM-side view.

References:
- CRR Art. 161 / PRA PS1/26 Art. 161: Supervisory LGD for F-IRB
- CRR Art. 222(3), 227(3): Zero-haircut sovereign eligibility
- CRR Art. 230 (Table 5) / CRE32.9-12: Overcollateralisation ratios and thresholds
- CRR Art. 232: Life insurance treatment (no overcollateralisation)
- CRE22.52-53: Basel 3.1 supervisory haircut equivalents
"""

from __future__ import annotations

from .firb_lgd import (
    FIRB_MIN_COLLATERALISATION_THRESHOLDS,
    FIRB_OVERCOLLATERALISATION_RATIOS,
)

# ---------------------------------------------------------------------------
# Zero-haircut sovereign eligibility (CRR Art. 227(3))
# ---------------------------------------------------------------------------

# Maximum CQS for sovereign bonds eligible for zero-haircut treatment in repos.
# Only CQS 1 (0%-RW) sovereign debt qualifies.
ZERO_HAIRCUT_MAX_SOVEREIGN_CQS: int = 1

# ---------------------------------------------------------------------------
# F-IRB supervisory LGD values by framework — CRM-shape view
# CRR Art. 161 vs Basel 3.1 CRE32.9-12
# ---------------------------------------------------------------------------

CRR_SUPERVISORY_LGD: dict[str, float] = {
    "financial": 0.0,
    "receivables": 0.35,
    "real_estate": 0.35,
    "other_physical": 0.40,
    "unsecured": 0.45,
    "covered_bond": 0.1125,
    "life_insurance": 0.40,  # Art. 232(2)(b): secured portion LGD = 40%
    # CRR Art. 230 Table 5 subordinated LGDS (secured portion of subordinated claims)
    "receivables_subordinated": 0.65,
    "real_estate_subordinated": 0.65,
    "other_physical_subordinated": 0.70,
}

BASEL31_SUPERVISORY_LGD: dict[str, float] = {
    "financial": 0.0,
    "receivables": 0.20,
    "real_estate": 0.20,
    "other_physical": 0.25,
    "unsecured": 0.40,  # Art. 161(1)(aa): non-FSE corporates
    "unsecured_fse": 0.45,  # Art. 161(1)(a): financial sector entities
    "covered_bond": 0.1125,  # Art. 161(1)(d)
    "life_insurance": 0.40,  # Art. 232(2)(b): secured portion LGD = 40%
}

# ---------------------------------------------------------------------------
# Overcollateralisation ratios and minimum thresholds — same under both
# frameworks (CRR Art. 230 / CRE32.9-12). Re-exported from firb_lgd.py
# under CRM-shape names; the underlying dicts are the single source of truth.
# ---------------------------------------------------------------------------

OVERCOLLATERALISATION_RATIOS: dict[str, float] = FIRB_OVERCOLLATERALISATION_RATIOS
MIN_COLLATERALISATION_THRESHOLDS: dict[str, float] = FIRB_MIN_COLLATERALISATION_THRESHOLDS
