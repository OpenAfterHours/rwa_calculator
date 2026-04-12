"""
Output floor regulatory constants (PRA PS1/26 / Basel 3.1).

Pipeline position:
    Data Tables -> aggregator._floor (OF-ADJ + portfolio floor)

Key responsibilities:
- Hold the GCRA cap rate used in the OF-ADJ formula. GCRA is capped at
  1.25% of S-TREA before entering OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1
  - GCRA + SA_T2).
- Basel 3.1 only — the output floor and OF-ADJ are introduced by PS1/26.

References:
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ)
- PRA PS1/26 Art. 92 para 2A: GCRA cap definition (1.25% of S-TREA)
- CRE99.1-8: Basel 3.1 output floor
"""

from __future__ import annotations

from decimal import Decimal

# GCRA cap: 1.25% of S-TREA per Art. 92 para 2A definition
GCRA_CAP_RATE: Decimal = Decimal("0.0125")
