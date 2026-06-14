"""
Regulatory monetary-threshold resolution (Phase 5 S11c — the FX seam).

The CRR monetary thresholds (SME turnover/balance-sheet/exposure, retail max,
QRRE limit, …) are EUR source amounts converted to GBP at the run's EUR/GBP
rate; the Basel 3.1 thresholds are PRA-native GBP values (with the sole
exception of the SME balance-sheet fallback, which PS1/26 does not restate and
so stays the Commission Rec 2003/361/EC EUR 43m frozen at the default rate).

The rulepack holds the FX-INVARIANT regulatory values (CRR: EUR bases; B31:
final GBP) under ``regulatory_thresholds``, plus the
``regulatory_thresholds_fx_derived`` Feature. This module applies the per-run
EUR/GBP rate ENGINE-SIDE so the pack stays FX-free and ``eur_gbp_rate`` — a
market input, not a regulatory value — stays on the run config. The result
reproduces ``contracts/config.py::RegulatoryThresholds.crr(rate)`` /
``.basel_3_1(rate)`` exactly (same ``Decimal × Decimal`` arithmetic).

Pipeline position: read by the classifier, IRB and supporting-factor stages.

References:
- CRR Art. 123 / 123A / 501 / 501a / 4(1)(146): EUR monetary thresholds.
- PRA PS1/26 Art. 147(5A) / 147A(1)(d) / 153(4): native GBP thresholds.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


def regulatory_threshold(
    pack: ResolvedRulepack,
    name: str,
    eur_gbp_rate: Decimal,
) -> Decimal:
    """Return a GBP regulatory threshold from the pack, applying × FX where due.

    Args:
        pack: The run's resolved rulepack.
        name: A ``regulatory_thresholds`` key (a ``RegulatoryThresholds`` field
            name, e.g. ``"sme_turnover_threshold"``).
        eur_gbp_rate: The run's EUR/GBP rate (``config.eur_gbp_rate`` — a market
            input). Used only when the regime's thresholds are EUR-derived.

    Returns:
        The GBP threshold as a ``Decimal``. CRR: ``EUR_base × eur_gbp_rate``;
        Basel 3.1: the native GBP value as-is (the Feature is False).
    """
    base = pack.formula("regulatory_thresholds").params[name]
    if pack.feature("regulatory_thresholds_fx_derived"):
        return base * eur_gbp_rate
    return base
