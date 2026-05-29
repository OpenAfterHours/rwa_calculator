"""
CRR Art. 165 PD/LGD equity approach supervisory parameters (CRR Art. 155(3)).

Provides the supervisory parameter tables for the equity PD/LGD method under
CRR Art. 155(3), which calculates risk-weighted exposure amounts using the
corporate IRB K formula (Art. 153(1)) with supervisory PD floors, LGDs, and a
fixed maturity from Art. 165:

- PD floors (Art. 165(1)):
    (a) 0.09% exchange-traded equity in a long-term customer relationship
    (b) 0.09% non-exchange-traded equity with regular/periodic cash flows
    (c) 0.40% exchange-traded equity (including short positions, Art. 155(2))
    (d) 1.25% all other equity exposures
- Supervisory LGD (Art. 165(2)): 65% sufficiently-diversified private equity,
  90% all other equity.
- Maturity (Art. 165(3)): M = 5 years for all PD/LGD equity exposures.
- Scaling factor (Art. 155(3)): 1.5x applied to the risk weights where the
  institution lacks sufficient information to use the Art. 178 default
  definition.

All values expressed as decimals (e.g., Decimal("0.0040") = 0.40%).

References:
    - CRR Art. 155(3): PD/LGD approach for equity; 1.5x scaling absent default data
    - CRR Art. 165(1)(a)-(d): minimum PDs (PD floors) by equity sub-type
    - CRR Art. 165(2): supervisory LGD (65% diversified PE / 90% other)
    - CRR Art. 165(3): fixed maturity M = 5 years
"""

from __future__ import annotations

from decimal import Decimal

#: Art. 165(1)(a)-(d): minimum PDs (PD floors) by equity sub-type.
#: Keyed by an internal sub-type identifier resolved from equity_type /
#: is_exchange_traded in the equity calculator.
EQUITY_PD_FLOORS: dict[str, Decimal] = {
    "exchange_traded_long_term": Decimal("0.0009"),  # 0.09% Art. 165(1)(a)
    "non_exchange_regular_cashflow": Decimal("0.0009"),  # 0.09% Art. 165(1)(b)
    "exchange_traded": Decimal("0.0040"),  # 0.40% Art. 165(1)(c)
    "other": Decimal("0.0125"),  # 1.25% Art. 165(1)(d)
}

#: Art. 165(2): supervisory LGD. Diversified private equity may use 65%;
#: all other equity uses 90%. Keyed on the equity_type enum string.
EQUITY_PD_LGD_LGD: dict[str, Decimal] = {
    "private_equity_diversified": Decimal("0.65"),  # 65% Art. 165(2)
    "other": Decimal("0.90"),  # 90% Art. 165(2)
}

#: Art. 165(3): fixed maturity for the equity PD/LGD approach (5 years).
EQUITY_PD_LGD_MATURITY: Decimal = Decimal("5.0")

#: Art. 155(3): scaling factor applied to the risk weights where the institution
#: lacks sufficient information for the Art. 178 default definition.
EQUITY_PD_LGD_NO_DEFAULT_INFO_SCALING: Decimal = Decimal("1.5")
