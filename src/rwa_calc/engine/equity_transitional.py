"""
Standardised Transitional Approach for equities: the firm fact and the weights.

Pipeline position:
    Shared helper, no stage of its own. Read by EquityCalculator (direct equity
    exposures) and by the Financial Collateral Simple Method
    (engine/crm/simple_method.py), whose Art. 222(3) collateral weight is the
    weight of "a direct exposure to the collateral instrument".

Key responsibilities:
- Rule 4.1's firm fact: whether the firm had IRB permission under Art. 143 of
  CRR on 31 December 2026 (F-IRB, A-IRB or slotting, or the stated override)
- The rule 4.2 / 4.3 weights for a reporting date, or None outside the
  transitional period (1 January 2027 up to, not including, 1 January 2030)

References:
- PRA PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.1-4.3
- PRA PS1/26 Art. 143(2A), Art. 153(5): slotting is an IRB Approach
- CRR Art. 143: permission to use the IRB Approach
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from watchfire import cites

from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from datetime import date

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

#: The approaches Art. 143(2A) names as IRB Approaches.
_IRB_APPROACHES = frozenset({ApproachType.FIRB, ApproachType.AIRB, ApproachType.SLOTTING})


@cites("CRR Art. 143")
@cites("CRR Art. 153(5)")
@cites("PS1/26, paragraph 4.1")
def had_irb_permission_at_2026_year_end(config: CalculationConfig) -> bool:
    """Rule 4.1's firm fact: IRB permission under Art. 143 of CRR on 31 December 2026.

    Rule 4.1 (ps126app1.pdf p.20): "4.2 and 4.3 only apply to an institution
    that did not have permission to use the Internal Ratings Based Approach
    under Article 143 of CRR on 31 December 2026." Slotting is one of those
    approaches: Art. 143(2A) (p.81) has an application name "one or more of the
    following IRB Approaches instead of the Standardised Approach: (a) the
    Slotting Approach; (b) the Foundation IRB Approach; or (c) the Advanced IRB
    Approach", and Art. 153(5) (p.102), "The Slotting Approach applies as
    follows for specialised lending exposures", sits in the IRB Part. So a firm
    whose only IRB permission is slotting HAD IRB permission and is outside
    rules 4.2 / 4.3.

    ``EquityTransitionalConfig.irb_permission_at_2026_year_end`` states the fact
    when the run's permissions do not (a Standardised shadow run of an IRB firm,
    or a permission granted after that date). Left as None, it is derived from
    the run: any F-IRB, A-IRB or slotting permission. That is deliberately wider
    than the F-IRB / A-IRB-only predicate ``EquityCalculator._determine_approach``
    reads to route CRR equity to Art. 155, which this fact does not change.
    """
    stated = config.equity_transitional.irb_permission_at_2026_year_end
    if stated is not None:
        return stated
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    permissions = config.irb_permissions.permissions  # ty: ignore[unresolved-attribute]
    return any(not _IRB_APPROACHES.isdisjoint(approaches) for approaches in permissions.values())


def standardised_transitional_weights(
    pack: ResolvedRulepack, on: date
) -> tuple[float, float] | None:
    """Rules 4.2 / 4.3 (standard, higher risk) weights for ``on``, or None outside the period.

    The period is the ``equity_transitional_std_rw`` Schedule's first step
    (1 January 2027) up to, not including, its last step (1 January 2030), which
    is the Art. 133(3) / (4) end state rather than a transitional weight. Before
    the first step the Schedule resolves to its ``before_first`` 0.0, which is
    not a weight; this returns None there instead.

    The caller gates on the ``equity_transitional`` Feature: the CRR pack has no
    such Schedule.
    """
    standard = pack.schedule("equity_transitional_std_rw")
    first_day, end_state_day = standard.steps[0][0], standard.steps[-1][0]
    if not first_day <= on < end_state_day:
        return None
    higher_risk = pack.schedule("equity_transitional_hr_rw")
    return float(standard.resolve(on)), float(higher_risk.resolve(on))
