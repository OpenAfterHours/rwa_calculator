"""
Zero-haircut sovereign eligibility for CRM collateral processing — CRR Art. 227(3).

Pipeline position:
    Data Tables -> CRM Processor (collateral.py, haircuts.py)

Key responsibilities:
- Hold the maximum sovereign CQS eligible for zero-haircut repo treatment.

The supervisory-LGD dicts and the Art. 230 overcollateralisation ratios /
minimum thresholds that previously lived here have moved to the rulepack
(``firb_supervisory_lgd``, ``overcollateralisation_ratios``,
``min_collateralisation_thresholds``); engine CRM expressions read those
per-run via ``rulebook.resolve``.

References:
- CRR Art. 222(3), 227(3): Zero-haircut sovereign eligibility
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Zero-haircut sovereign eligibility (CRR Art. 227(3))
# ---------------------------------------------------------------------------

# Maximum CQS for sovereign bonds eligible for zero-haircut treatment in repos.
# Only CQS 1 (0%-RW) sovereign debt qualifies.
ZERO_HAIRCUT_MAX_SOVEREIGN_CQS: int = 1
