"""
Failed-trade settlement-risk multipliers — CRR Art. 378 / Art. 379.

Pipeline position:
    Consumed by ``engine/ccr/failed_trades.py`` when computing own-funds
    requirements and RWA for failed Delivery-versus-Payment (DvP) and
    non-DvP free-delivery transactions per CRR Title V (Settlement Risk).

Key responsibilities:
- Expose every regulatory scalar required by the failed-trade calculation
  as a ``Decimal`` constant so ``engine/**`` modules never embed
  numerical regulatory values directly.

Regulatory references:
- CRR Art. 378 + Table 1: DvP multiplier ladder by working-days-past-due
  band (5-15 -> 8%, 16-30 -> 50%, 31-45 -> 75%, 46+ -> 100%).
- CRR Art. 379(1) + Table 2 Column 4: non-DvP free-delivery transactions
  t+5 onwards carry a 1250% risk weight (own-funds factor 1.0 against the
  full transferred value plus current positive exposure).
- CRR Art. 92(3)(ca): own-funds -> RWA conversion factor 12.5 (= 1 / 0.08).
- PRA PS1/26 Art. 92(3)(a), 92(3)(ca): UK-onshored equivalents; numerical
  values unchanged.
"""

from __future__ import annotations

from decimal import Decimal

# =============================================================================
# DvP MULTIPLIER LADDER (CRR Art. 378 Table 1)
# =============================================================================
# Band thresholds are working-days-past-due lower bounds (inclusive). The
# applicable multiplier is the value associated with the highest band whose
# lower bound is <= ``working_days_past_due``. Settlement that is not yet
# 5 working days overdue carries no own-funds requirement under Art. 378.

#: Multiplier for failed DvP trades 5-15 working days past due (8%).
FAILED_TRADE_DVP_MULT_5_15: Decimal = Decimal("0.08")

#: Multiplier for failed DvP trades 16-30 working days past due (50%).
FAILED_TRADE_DVP_MULT_16_30: Decimal = Decimal("0.50")

#: Multiplier for failed DvP trades 31-45 working days past due (75%).
FAILED_TRADE_DVP_MULT_31_45: Decimal = Decimal("0.75")

#: Multiplier for failed DvP trades 46+ working days past due (100%).
FAILED_TRADE_DVP_MULT_46_PLUS: Decimal = Decimal("1.00")

# Lower bounds (inclusive, in working days past due) of the Art. 378 Table 1
# bands. Engine modules use these to map ``working_days_past_due`` to the
# applicable multiplier above without embedding the integer literals.

#: Lower bound (working days past due) of the DvP 5-15 band.
FAILED_TRADE_DVP_BAND_5_15_LOWER_DAYS: int = 5

#: Lower bound (working days past due) of the DvP 16-30 band.
FAILED_TRADE_DVP_BAND_16_30_LOWER_DAYS: int = 16

#: Lower bound (working days past due) of the DvP 31-45 band.
FAILED_TRADE_DVP_BAND_31_45_LOWER_DAYS: int = 31

#: Lower bound (working days past due) of the DvP 46+ band.
FAILED_TRADE_DVP_BAND_46_PLUS_LOWER_DAYS: int = 46


# =============================================================================
# NON-DvP RISK WEIGHT (CRR Art. 379(1) Table 2 Column 4)
# =============================================================================
# Non-DvP free-delivery transactions: if the second contractual leg has not
# been received by t+5 working days, the firm treats the transferred value
# plus any current positive exposure on the open second leg as a credit-risk
# exposure carrying a 1250% risk weight. Expressed here as the own-funds ->
# RWA multiplier 12.5 (since own-funds factor against full exposure = 1.0,
# RWA = exposure * 12.5).

#: Effective RWA multiplier on the non-DvP Column-4 exposure (1250% RW => 12.5).
FAILED_TRADE_NON_DVP_COL4_RW_MULTIPLIER: Decimal = Decimal("12.50")

#: Lower bound (working days past due) of the non-DvP Column-4 band (t+5).
FAILED_TRADE_NON_DVP_COL4_LOWER_DAYS: int = 5


# =============================================================================
# OWN-FUNDS -> RWA CONVERSION (CRR Art. 92(3)(ca); PS1/26 Art. 92(3)(ca))
# =============================================================================
# Own-funds requirements (Pillar 1) are expressed as 8% of RWA, so the
# inverse conversion factor is 1 / 0.08 = 12.5. Applied to the DvP own-funds
# result to produce the RWA-equivalent number consumed downstream.

#: Conversion factor used to convert an own-funds requirement to RWA (1/0.08).
OWN_FUNDS_TO_RWA_FACTOR: Decimal = Decimal("12.5")
