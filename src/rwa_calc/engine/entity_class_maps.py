"""
Entity-type -> exposure-class maps, rebound from the rulepack at module load.

Pipeline position:
    Consumed across the engine wherever an ``entity_type`` input string must
    resolve to its Standardised / IRB exposure class — the classifier
    (``engine/classify/attributes.py``), the SA / IRB / CRM guarantee branches
    (``crm/guarantees.py``, ``irb/guarantee.py``, ``sa/rw_adjustments.py``), and
    the entity-level SA RW preview (``sa/guarantor_rw.py``).

Key responsibilities:
- Rebind the cited ``entity_type_to_sa_class`` / ``entity_type_to_irb_class``
  rulepack ``CategoryMap`` entries (CRR Art. 112 / 147) into plain ``dict``s for
  ``Expr.replace_strict`` — the rulepack is the value home; this module is the
  consumer-side binding so the engine never imports ``data/tables``.
- Derive the inverse SA-class -> tuple-of-entity-types index used by the
  entity-level SA RW preview (``sa/guarantor_rw.py``).

Each call site keeps its own ``replace_strict`` default (the residual ``OTHER``
class in the classifier, an empty "no-class" sentinel in the guarantee
branches), so no single default is baked in here.

References:
- CRR Art. 112 Table A2 — SA exposure classes
- CRR Art. 147(3)/(4)(b) — RGLA/PSE sovereign-/institution-equivalence under IRB
- CRR Art. 147(8) — specialised lending as an IRB sub-class
- CRR Art. 128 — high-risk items (SA-only); Art. 134 — Other Items (SA-only)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# The regime this module binds when no pack is supplied. The maps live in the
# common pack and are currently identical under both regimes — measured, 31
# entries each with zero differences — so the CRR resolution is a correct
# default rather than an arbitrary one.
#
# It is still a DEFAULT and not the only path (P1.311). Both maps are
# expressible as regime-divergent overrides in ``packs/b31.py``: ``resolve()``
# would merge such an override, but a module that only ever asks for "crr"
# would never see it, and the failure would be silent — the b31 engine quietly
# keeping CRR classes. That trap has been hit twice, by P1.276 and P1.286, both
# of which proposed a pack-map edit at this site and were dead on arrival.
#
# The accessors below take an optional resolved pack so a caller that already
# holds one (the classifier, the SA guarantor preview) can bind the maps for
# ITS regime. They return plain dicts, so every ``Expr.replace_strict`` call
# site is unchanged.
#
# Note the date below is immaterial: ``resolve()`` passes ``reporting_date``
# only to its content hash and does not filter entries — measured, the entry
# set is identical at 2020-01-01 and 2030-12-31 — and a ``CategoryMap`` has no
# date dimension at all. Only ``Schedule`` entries resolve by date.
_DEFAULT_REGIME = "crr"
_DEFAULT_DATE = date(2026, 1, 1)
_DEFAULT_PACK = resolve(_DEFAULT_REGIME, _DEFAULT_DATE)


def entity_type_to_sa_class(pack: ResolvedRulepack | None = None) -> dict[str, str]:
    """entity_type -> SA exposure class (CRR Art. 112), for the given pack."""
    return dict((pack or _DEFAULT_PACK).category_map("entity_type_to_sa_class").entries)


def entity_type_to_irb_class(pack: ResolvedRulepack | None = None) -> dict[str, str]:
    """entity_type -> IRB exposure class (CRR Art. 147), for the given pack."""
    return dict((pack or _DEFAULT_PACK).category_map("entity_type_to_irb_class").entries)


def entity_types_by_sa_class(pack: ResolvedRulepack | None = None) -> dict[str, tuple[str, ...]]:
    """Inverse of the SA map: SA exposure class -> tuple of entity_types.

    Used by the entity-level SA RW preview (``sa/guarantor_rw.py``).
    """
    sa_map = entity_type_to_sa_class(pack)
    return {
        sa_class: tuple(et for et, c in sa_map.items() if c == sa_class)
        for sa_class in dict.fromkeys(sa_map.values())
    }


# Module-level bindings against the default pack, retained for the call sites
# that hold no pack. They are the accessors' output, so the two cannot diverge.
ENTITY_TYPE_TO_SA_CLASS: dict[str, str] = entity_type_to_sa_class()
ENTITY_TYPE_TO_IRB_CLASS: dict[str, str] = entity_type_to_irb_class()
ENTITY_TYPES_BY_SA_CLASS: dict[str, tuple[str, ...]] = entity_types_by_sa_class()

__all__ = [
    "ENTITY_TYPES_BY_SA_CLASS",
    "ENTITY_TYPE_TO_IRB_CLASS",
    "ENTITY_TYPE_TO_SA_CLASS",
    "entity_type_to_irb_class",
    "entity_type_to_sa_class",
    "entity_types_by_sa_class",
]
