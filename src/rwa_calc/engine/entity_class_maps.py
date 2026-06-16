"""
Entity-type -> exposure-class maps, rebound from the rulepack at module load.

Pipeline position:
    Consumed across the engine wherever an ``entity_type`` input string must
    resolve to its Standardised / IRB exposure class — the classifier
    (``stages/classify/attributes.py``), the SA / IRB / CRM guarantee branches
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

from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Regime-invariant base maps live in the common pack — resolve against "crr"
# (b31 inherits the same entries). Rebound to plain dicts once at module load.
_PACK = resolve("crr", date(2026, 1, 1))

# entity_type -> SA exposure class (for risk weight lookup), CRR Art. 112.
ENTITY_TYPE_TO_SA_CLASS: dict[str, str] = dict(
    _PACK.category_map("entity_type_to_sa_class").entries
)

# entity_type -> IRB exposure class (for IRB formula selection), CRR Art. 147.
ENTITY_TYPE_TO_IRB_CLASS: dict[str, str] = dict(
    _PACK.category_map("entity_type_to_irb_class").entries
)

# Inverse of ENTITY_TYPE_TO_SA_CLASS: SA exposure class -> tuple of entity_types.
# Derived at module load so any pack change flows through to consumers (e.g. the
# entity-level SA RW preview ``build_entity_rw_expr`` in sa/guarantor_rw.py).
ENTITY_TYPES_BY_SA_CLASS: dict[str, tuple[str, ...]] = {
    sa_class: tuple(et for et, c in ENTITY_TYPE_TO_SA_CLASS.items() if c == sa_class)
    for sa_class in dict.fromkeys(ENTITY_TYPE_TO_SA_CLASS.values())
}

__all__ = [
    "ENTITY_TYPE_TO_IRB_CLASS",
    "ENTITY_TYPE_TO_SA_CLASS",
    "ENTITY_TYPES_BY_SA_CLASS",
]
