"""
Common rulebook pack — regime-invariant cited scalars.

Pipeline position:
    Base layer of both regimes (``REGIME_PACKS["crr"]`` and
    ``REGIME_PACKS["b31"]`` both start with ``"common"``); merged first by
    ``rulebook/resolve.py``, then overlaid by the regime amendment pack.

Key responsibilities:
- Hold values that do not differ between CRR and Basel 3.1 (the FX haircut
  and the SA-CCR supervisory alpha in this proof pack).

References:
- CRR Art. 224: FCCM supervisory haircuts (the FX/currency-mismatch
  haircut, 8% base).
- CRR Art. 274(2) / BCBS CRE52.1: SA-CCR default supervisory alpha (1.4).
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.rulebook.model import Citation, RuleEntry, ScalarParam

ENTRIES: dict[str, RuleEntry] = {
    "fx_haircut": ScalarParam(
        name="fx_haircut",
        value=Decimal("0.08"),
        citation=Citation("CRR", "224"),
    ),
    "sa_ccr_alpha": ScalarParam(
        name="sa_ccr_alpha",
        value=Decimal("1.4"),
        citation=Citation("CRR", "274(2)"),
    ),
}
