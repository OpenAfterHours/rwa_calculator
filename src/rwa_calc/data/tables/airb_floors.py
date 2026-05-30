"""
A-IRB floor multipliers — PRA PS1/26 Art. 166D / BCBS CRE32.27.

Pipeline position:
    Consumed by ``engine/ccf.py`` (``_compute_ccf`` and ``_compute_ead``) when
    applying the Basel 3.1 A-IRB own-estimate CCF floor and the Art. 166D(5)(b)
    facility-level EAD floor.

Key responsibilities:
- Expose the two A-IRB 50% floor multipliers as ``Decimal`` constants so
  ``engine/**`` modules never embed numerical regulatory values directly.

Regulatory references:
- BCBS CRE32.27: A-IRB own-estimate CCFs must be at least 50% of the SA CCF
  for the same item type (the own-estimate CCF floor).
- PRA PS1/26 Art. 166D(5)(b): facility-level EAD floor — EAD must be at least
  on-balance-sheet EAD + 50% of the off-balance-sheet EAD at the F-IRB CCF.
"""

from __future__ import annotations

from decimal import Decimal

# =============================================================================
# A-IRB OWN-ESTIMATE CCF FLOOR (BCBS CRE32.27)
# =============================================================================
# Own-estimate CCFs are floored at 50% of the SA CCF for the same item type.
# Applied in ``engine.ccf._compute_ccf`` to the revolving-facility own CCF.

#: A-IRB own-estimate CCF floor multiplier (own estimate >= 50% x SA CCF).
AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER: Decimal = Decimal("0.5")


# =============================================================================
# A-IRB FACILITY-LEVEL EAD FLOOR (PRA PS1/26 Art. 166D(5)(b))
# =============================================================================
# The single-EAD (Art. 166D(3)) approach floors EAD at on-balance-sheet EAD
# plus 50% of the off-balance-sheet EAD measured at the F-IRB CCF. Applied in
# ``engine.ccf._compute_ead`` as floor (b).

#: A-IRB off-balance-sheet EAD floor multiplier (drawn + 50% x off-BS at F-IRB CCF).
AIRB_OBS_FLOOR_B_MULTIPLIER: Decimal = Decimal("0.5")
