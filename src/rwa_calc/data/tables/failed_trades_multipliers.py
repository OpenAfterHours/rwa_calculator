"""
Failed-trade settlement-risk band bounds — CRR Art. 378 / Art. 379.

Pipeline position:
    Consumed by ``engine/ccr/failed_trades.py`` to map ``working_days_past_due``
    to the Art. 378 Table 1 DvP multiplier band (and the matching audit
    ``regulatory_band`` string) and to gate the non-DvP Column-4 treatment.

Key responsibilities:
- Expose the working-days-past-due band LOWER BOUNDS (inclusive int day counts)
  as the single source of truth for the engine's band cascade. The regulatory
  multipliers and the own-funds -> RWA conversion factor themselves live in the
  rulepack (``failed_trade_*`` / ``own_funds_to_rwa_factor`` in packs/common.py).

Regulatory references:
- CRR Art. 378 + Table 1: DvP multiplier ladder by working-days-past-due band
  (5-15, 16-30, 31-45, 46+).
- CRR Art. 379(1) + Table 2 Column 4: non-DvP free-delivery t+5 onwards.
- PRA PS1/26 Art. 92(3)(a), 92(3)(ca): UK-onshored equivalents; values unchanged.
"""

from __future__ import annotations

# =============================================================================
# DvP MULTIPLIER LADDER BAND BOUNDS (CRR Art. 378 Table 1)
# =============================================================================
# Working-days-past-due lower bounds (inclusive). The applicable multiplier is
# the value associated with the highest band whose lower bound is <=
# ``working_days_past_due``; settlement that is not yet 5 working days overdue
# carries no own-funds requirement under Art. 378. The multipliers themselves
# live in the rulepack.

#: Lower bound (working days past due) of the DvP 5-15 band.
FAILED_TRADE_DVP_BAND_5_15_LOWER_DAYS: int = 5

#: Lower bound (working days past due) of the DvP 16-30 band.
FAILED_TRADE_DVP_BAND_16_30_LOWER_DAYS: int = 16

#: Lower bound (working days past due) of the DvP 31-45 band.
FAILED_TRADE_DVP_BAND_31_45_LOWER_DAYS: int = 31

#: Lower bound (working days past due) of the DvP 46+ band.
FAILED_TRADE_DVP_BAND_46_PLUS_LOWER_DAYS: int = 46


# =============================================================================
# NON-DvP COLUMN-4 BAND BOUND (CRR Art. 379(1) Table 2 Column 4)
# =============================================================================
# Non-DvP free-delivery transactions whose second contractual leg is unreceived
# by t+5 working days are treated as a 1250%-RW credit exposure (the Column-4
# RWA multiplier lives in the rulepack).

#: Lower bound (working days past due) of the non-DvP Column-4 band (t+5).
FAILED_TRADE_NON_DVP_COL4_LOWER_DAYS: int = 5
