"""
CRR rulebook pack — pre-Basel-3.1 cited regime entries.

Pipeline position:
    Amendment layer for the ``"crr"`` regime (``REGIME_PACKS["crr"] =
    ("common", "crr")``); overlaid on the common pack by
    ``rulebook/resolve.py``, overriding any colliding entry names.

Key responsibilities:
- Hold the CRR-specific proof-pack values: the IRB K scaling factor, the
  SME/infrastructure supporting-factor feature flag, and a small CQS->RW
  lookup demonstrating the ``LookupTable`` shape.

References:
- CRR Art. 153(1): IRB risk-weight scaling factor (1.06).
- CRR Art. 501: SME supporting factor (and Art. 501a infrastructure).
- CRR Art. 122: standardised corporate risk weights by credit-quality step.
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.rulebook.model import Citation, Feature, LookupTable, RuleEntry, ScalarParam

ENTRIES: dict[str, RuleEntry] = {
    "irb_scaling_factor": ScalarParam(
        name="irb_scaling_factor",
        value=Decimal("1.06"),
        citation=Citation("CRR", "153(1)"),
    ),
    "supporting_factors": Feature(
        name="supporting_factors",
        enabled=True,
        citation=Citation("CRR", "501"),
    ),
    "corporate_cqs_rw": LookupTable(
        name="corporate_cqs_rw",
        entries={1: Decimal("0.20"), 2: Decimal("0.50")},
        key="cqs",
        citation=Citation("CRR", "122"),
        default=Decimal("1.00"),
    ),
    # F-IRB collateral step-functions apply under CRR (Art. 230 Table 5): the
    # overcollateralisation divisor and the 30% C*/C** minimum threshold. Basel
    # 3.1 removes both (see packs/b31.py); the divisor/threshold values
    # themselves live regime-invariantly in packs/common.py.
    "firb_overcollateralisation_divisor_applies": Feature(
        name="firb_overcollateralisation_divisor_applies",
        enabled=True,
        citation=Citation("CRR", "230", "Table 5 overcollateralisation divisor applies"),
    ),
    "firb_min_collateralisation_threshold_applies": Feature(
        name="firb_min_collateralisation_threshold_applies",
        enabled=True,
        citation=Citation("CRR", "230", "30% C*/C** minimum collateralisation threshold applies"),
    ),
}
