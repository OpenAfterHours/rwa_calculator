"""
Common rulebook pack — regime-invariant cited scalars.

Pipeline position:
    Base layer of both regimes (``REGIME_PACKS["crr"]`` and
    ``REGIME_PACKS["b31"]`` both start with ``"common"``); merged first by
    ``rulebook/resolve.py``, then overlaid by the regime amendment pack.

Key responsibilities:
- Hold values that do not differ between CRR and Basel 3.1 (the FX haircut,
  the SA-CCR supervisory alpha, and the Financial Collateral Simple Method
  floors — Art. 222 is retained unchanged under PRA PS1/26).

References:
- CRR Art. 224: FCCM supervisory haircuts (the FX/currency-mismatch
  haircut, 8% base).
- CRR Art. 274(2) / BCBS CRE52.1: SA-CCR default supervisory alpha (1.4).
- CRR Art. 222 / PRA PS1/26 Art. 222: Financial Collateral Simple Method
  floors and carve-outs (retained for SA exposures under Basel 3.1).
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.rulebook.model import Citation, LookupTable, RuleEntry, ScalarParam

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
    # Financial Collateral Simple Method (CRR Art. 222 / PRA PS1/26 Art. 222).
    # Single-regime: PS1/26 retains Art. 222 unchanged for SA exposures.
    "fcsm_rw_floor": ScalarParam(
        name="fcsm_rw_floor",
        value=Decimal("0.20"),
        citation=Citation("CRR", "222(1)", "minimum 20% RW floor for the secured portion"),
    ),
    "fcsm_sovereign_bond_discount": ScalarParam(
        name="fcsm_sovereign_bond_discount",
        value=Decimal("0.20"),
        citation=Citation("CRR", "222(4)(b)", "20% market-value discount on 0%-RW sovereign bonds"),
    ),
    "fcsm_sft_cmp_floor": ScalarParam(
        name="fcsm_sft_cmp_floor",
        value=Decimal("0.00"),
        citation=Citation("CRR", "222(4)(a)", "SFT zero-haircut core-market-participant floor"),
    ),
    "fcsm_sft_non_cmp_floor": ScalarParam(
        name="fcsm_sft_non_cmp_floor",
        value=Decimal("0.10"),
        citation=Citation("CRR", "222(4)(b)", "SFT zero-haircut non-CMP 10% floor"),
    ),
    "fcsm_equity_collateral_rw": ScalarParam(
        name="fcsm_equity_collateral_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "222(1)", "equity held as FCSM collateral risk-weighted at 100%"),
    ),
    # F-IRB overcollateralisation divisors and minimum collateralisation
    # thresholds (CRR Art. 230 Table 5 / CRE32.9-12). The values are
    # regime-INVARIANT; whether CRR applies them is carried by the regime
    # Features ``firb_overcollateralisation_divisor_applies`` /
    # ``firb_min_collateralisation_threshold_applies`` (Basel 3.1 replaces the
    # step-function with the continuous LGD* formula, PS1/26 Art. 230(1)).
    "overcollateralisation_ratios": LookupTable(
        name="overcollateralisation_ratios",
        entries={
            "financial": Decimal("1.0"),
            "receivables": Decimal("1.25"),
            "real_estate": Decimal("1.40"),
            "other_physical": Decimal("1.40"),
            "life_insurance": Decimal("1.0"),
        },
        key="collateral_category",
        citation=Citation("CRR", "230", "Table 5 overcollateralisation divisors"),
        default=Decimal("1.0"),
    ),
    "min_collateralisation_thresholds": LookupTable(
        name="min_collateralisation_thresholds",
        entries={
            "financial": Decimal("0.0"),
            "receivables": Decimal("0.0"),
            "real_estate": Decimal("0.30"),
            "other_physical": Decimal("0.30"),
            "life_insurance": Decimal("0.0"),
        },
        key="collateral_category",
        citation=Citation("CRR", "230", "minimum collateralisation thresholds"),
        default=Decimal("0.0"),
    ),
}
