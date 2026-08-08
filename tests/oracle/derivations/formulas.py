"""
Shared arithmetic for the oracle derivations.

Pipeline position:
    (none) -- this module is deliberately outside the engine.

Key responsibilities:
- Reproduce the regulatory formulae from the article text, in scalar Python,
  using only the standard library.
- Stay readable: one function per named regulatory quantity, no vectorisation,
  no caching, no cleverness.

Hard constraint:
    **Nothing in this package may import ``rwa_calc``.** The whole value of the
    oracle is that it is a causally independent re-derivation. A contract test
    (``test_oracle.py::test_derivations_never_import_rwa_calc``) enforces this.

References:
- CRR Art. 153(1): corporate/institution IRB risk-weight formula (with the
  1.06 scaling factor).
- CRR Art. 154(1): retail IRB risk-weight formula (no maturity adjustment).
- PS1/26 Art. 153(1)(c) and 154(1)(b): the same formulae with the 1.06
  scaling factor removed.
"""

from __future__ import annotations

import math
import statistics

NORMAL = statistics.NormalDist(0.0, 1.0)

#: CRR Art. 153(1) / 154(1) apply a 1.06 multiplier to IRB risk weights.
#: PS1/26 Art. 153(1)(c) / 154(1)(b) restate the formulae without it.
CRR_IRB_SCALING_FACTOR = 1.06
B31_IRB_SCALING_FACTOR = 1.0


def systemic_factor(pd_value: float, decay: float) -> float:
    """The ``(1 - e^(-k*PD)) / (1 - e^(-k))`` term shared by every correlation.

    ``decay`` is 50 for corporates/institutions (CRR Art. 153(1)) and 35 for
    retail (CRR Art. 154(1)).
    """
    return (1.0 - math.exp(-decay * pd_value)) / (1.0 - math.exp(-decay))


def correlation_corporate(pd_value: float) -> float:
    """R for corporates, institutions and sovereigns.

    CRR Art. 153(1); PS1/26 Art. 153(1)(c):
        R = 0.12 * A + 0.24 * (1 - A),  A = (1-e^-50PD)/(1-e^-50)
    """
    a = systemic_factor(pd_value, 50.0)
    return 0.12 * a + 0.24 * (1.0 - a)


def correlation_corporate_sme(
    pd_value: float,
    size_metric: float,
    *,
    floor: float,
    cap: float,
) -> float:
    """R for SME corporates: the corporate curve less the size adjustment.

    CRR Art. 153(4):  floor = EUR 5m,   cap = EUR 50m,  span = 45
    PS1/26 Art. 153(4): floor = GBP 4.4m, cap = GBP 44m, span = 39.6

    ``size_metric`` is total annual revenue in millions, clamped to
    ``[floor, cap]`` before the adjustment is applied.
    """
    base = correlation_corporate(pd_value)
    clamped = min(max(floor, size_metric), cap)
    span = cap - floor
    return base - 0.04 * (1.0 - (clamped - floor) / span)


def correlation_retail(pd_value: float) -> float:
    """R for 'other retail'.

    CRR Art. 154(1); PS1/26 Art. 154(1)(b):
        R = 0.03 * A + 0.16 * (1 - A),  A = (1-e^-35PD)/(1-e^-35)
    """
    a = systemic_factor(pd_value, 35.0)
    return 0.03 * a + 0.16 * (1.0 - a)


#: CRR Art. 154(3) / PS1/26 Art. 154(3): retail secured by immovable property.
CORRELATION_RETAIL_MORTGAGE = 0.15

#: CRR Art. 154(4) / PS1/26 Art. 154(4): qualifying revolving retail.
CORRELATION_RETAIL_QRRE = 0.04

#: CRR Art. 153(2) / PS1/26 Art. 153(2): large / unregulated financial sector
#: entities multiply the correlation by 1.25.
FINANCIAL_SECTOR_CORRELATION_MULTIPLIER = 1.25


def maturity_adjustment_b(pd_value: float) -> float:
    """b = (0.11852 - 0.05478 * ln(PD))^2  (CRR Art. 153(1); PS1/26 Art. 153(1)(c))."""
    return (0.11852 - 0.05478 * math.log(pd_value)) ** 2


def maturity_adjustment(pd_value: float, maturity: float) -> float:
    """MA = (1 + (M - 2.5) * b) / (1 - 1.5 * b)."""
    b = maturity_adjustment_b(pd_value)
    return (1.0 + (maturity - 2.5) * b) / (1.0 - 1.5 * b)


def conditional_pd(pd_value: float, correlation: float) -> float:
    """N( (G(PD) + sqrt(R) * G(0.999)) / sqrt(1 - R) ) -- the downturn PD."""
    g_pd = NORMAL.inv_cdf(pd_value)
    g_999 = NORMAL.inv_cdf(0.999)
    inner = (g_pd + math.sqrt(correlation) * g_999) / math.sqrt(1.0 - correlation)
    return NORMAL.cdf(inner)


def irb_risk_weight_corporate(
    *,
    pd_value: float,
    lgd: float,
    maturity: float,
    correlation: float,
    scaling_factor: float,
) -> float:
    """RW for a non-defaulted corporate / institution exposure.

    CRR Art. 153(1):
        RW = (LGD * N(...) - LGD * PD) * MA * 12.5 * 1.06
    PS1/26 Art. 153(1)(c): identical with the 1.06 factor removed.
    """
    cond = conditional_pd(pd_value, correlation)
    ma = maturity_adjustment(pd_value, maturity)
    return lgd * (cond - pd_value) * ma * 12.5 * scaling_factor


def irb_risk_weight_retail(
    *,
    pd_value: float,
    lgd: float,
    correlation: float,
    scaling_factor: float,
) -> float:
    """RW for a non-defaulted retail exposure. No maturity adjustment.

    CRR Art. 154(1)(ii); PS1/26 Art. 154(1)(b).
    """
    cond = conditional_pd(pd_value, correlation)
    return lgd * (cond - pd_value) * 12.5 * scaling_factor


def irb_risk_weight_defaulted_airb(lgd: float, beel: float) -> float:
    """RW = max(0, 12.5 * (LGD - BEEL)) for a defaulted A-IRB exposure.

    CRR Art. 154(1)(i); PS1/26 Art. 153(1)(b) and 154(1)(a). Note PS1/26
    Art. 153(1)(b) sets RW = 0 for defaulted F-IRB corporate exposures.
    """
    return max(0.0, 12.5 * (lgd - beel))


def expected_loss(pd_value: float, lgd: float) -> float:
    """EL = PD * LGD (CRR Art. 158(5); PS1/26 Art. 158(5))."""
    return pd_value * lgd


def sme_supporting_factor(total_owed: float) -> float:
    """CRR Art. 501(1) SME supporting factor as a multiplier on RWEA.

        RWEA* = RWEA * [ min(E*, 2.5m) * 0.7619
                         + max(E* - 2.5m, 0) * 0.85 ] / E*

    ``total_owed`` is E* -- the total amount owed by the SME (or its group of
    connected clients), excluding residential-property-secured claims.
    """
    threshold = 2_500_000.0
    below = min(total_owed, threshold)
    above = max(total_owed - threshold, 0.0)
    return (below * 0.7619 + above * 0.85) / total_owed


def blend_two_bands(
    *,
    exposure: float,
    secured_amount: float,
    secured_rw: float,
    residual_rw: float,
) -> float:
    """Exposure-weighted RW where a fixed slice carries a preferential weight.

    Used by CRR Art. 125(2)(d) (35% up to 80% of value) and PS1/26 Art. 124F/
    124H (20% / 60% up to 55% of value, counterparty RW on the residual).
    """
    secured = min(secured_amount, exposure)
    residual = exposure - secured
    return (secured * secured_rw + residual * residual_rw) / exposure
