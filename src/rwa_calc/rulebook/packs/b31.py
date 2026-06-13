"""
Basel 3.1 rulebook pack — PRA PS1/26 cited regime entries.

Pipeline position:
    Amendment layer for the ``"b31"`` regime (``REGIME_PACKS["b31"] =
    ("common", "b31")``); overlaid on the common pack by
    ``rulebook/resolve.py``, overriding any colliding entry names (e.g. the
    IRB scaling factor, which Basel 3.1 removes).

Key responsibilities:
- Hold the Basel-3.1-specific proof-pack values: the removed IRB scaling
  factor (1.0), the A-IRB LGD floor and output-floor feature flags, and the
  output-floor transitional ``Schedule``.

References:
- PRA PS1/26 Art. 153(1): IRB scaling factor removed under Basel 3.1 (1.0).
- PRA PS1/26 Art. 161(5): A-IRB own-estimate LGD floors.
- PRA PS1/26 Art. 92: the aggregate output floor.
- PRA PS1/26 Art. 92(5): output-floor transitional phase-in percentages.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.rulebook.model import (
    Citation,
    DecisionTable,
    Feature,
    RuleEntry,
    ScalarParam,
    Schedule,
)

ENTRIES: dict[str, RuleEntry] = {
    "irb_scaling_factor": ScalarParam(
        name="irb_scaling_factor",
        value=Decimal("1.0"),
        citation=Citation("PS1/26", "153(1)"),
    ),
    "airb_lgd_floor": Feature(
        name="airb_lgd_floor",
        enabled=True,
        citation=Citation("PS1/26", "161(5)"),
    ),
    "output_floor": Feature(
        name="output_floor",
        enabled=True,
        citation=Citation("PS1/26", "92"),
    ),
    "output_floor_pct": Schedule(
        name="output_floor_pct",
        steps=(
            (date(2027, 1, 1), Decimal("0.60")),
            (date(2028, 1, 1), Decimal("0.65")),
            (date(2029, 1, 1), Decimal("0.70")),
            (date(2030, 1, 1), Decimal("0.725")),
        ),
        before_first=Decimal("0.0"),
        citation=Citation("PS1/26", "92(5)"),
    ),
    # Basel 3.1 replaces the CRR Art. 230 F-IRB collateral step-functions with
    # the continuous LGD* formula (PS1/26 Art. 230(1)): no overcollateralisation
    # divisor and no minimum collateralisation threshold. Overrides the CRR
    # Features of the same name.
    "firb_overcollateralisation_divisor_applies": Feature(
        name="firb_overcollateralisation_divisor_applies",
        enabled=False,
        citation=Citation("PS1/26", "230(1)", "LGD* formula — no overcollateralisation divisor"),
    ),
    "firb_min_collateralisation_threshold_applies": Feature(
        name="firb_min_collateralisation_threshold_applies",
        enabled=False,
        citation=Citation(
            "PS1/26", "230(1)", "LGD* formula — no minimum collateralisation threshold"
        ),
    ),
    # Canonical F-IRB supervisory LGD under Basel 3.1 (PRA PS1/26 Art. 161 /
    # CRE32.9-12). Overrides the CRR table of the same name. Key changes:
    # non-FSE senior 45%->40% with a distinct FSE row at 45%; receivables/RE
    # 35%->20%, other physical 40%->25%, dilution risk 75%->100%; Art. 230(2)
    # drops the *_subordinated secured-portion LGDS rows. life_insurance is
    # CRM-only (Art. 232(2)(b), unchanged at 40%).
    "firb_supervisory_lgd": DecisionTable(
        name="firb_supervisory_lgd",
        key_names=("collateral_type", "seniority", "is_fse"),
        rows=(
            (("unsecured", "senior", False), Decimal("0.40")),
            (("unsecured", "senior", True), Decimal("0.45")),
            (("unsecured", "subordinated", False), Decimal("0.75")),
            (("covered_bond", "senior", False), Decimal("0.1125")),
            (("financial_collateral", "senior", False), Decimal("0.00")),
            (("receivables", "senior", False), Decimal("0.20")),
            (("residential_re", "senior", False), Decimal("0.20")),
            (("commercial_re", "senior", False), Decimal("0.20")),
            (("other_physical", "senior", False), Decimal("0.25")),
            (("purchased_receivables", "senior", False), Decimal("0.40")),
            (("purchased_receivables", "subordinated", False), Decimal("1.00")),
            (("purchased_receivables", "dilution_risk", False), Decimal("1.00")),
            (("life_insurance", "senior", False), Decimal("0.40")),
        ),
        citation=Citation("PS1/26", "161", "Basel 3.1 F-IRB supervisory LGD (CRE32.9-12)"),
    ),
    # Basel 3.1 FCCM supervisory haircuts (PRA PS1/26 Art. 224 Tables 1/3 /
    # CRE22.52-53). Overrides the CRR table of the same name. 5 maturity bands
    # (0_1y / 1_3y / 3_5y / 5_10y / 10y_plus); long-dated corporate steps up to
    # 12%/20%, gold 15%->20%, equity 15%/25%->20%/30%; non-financial Art. 230(2)
    # HC is 40% for all types. cqs 2 and 3 carry identical values.
    "collateral_haircuts": DecisionTable(
        name="collateral_haircuts",
        key_names=("collateral_type", "cqs", "maturity_band", "is_main_index"),
        rows=(
            (("cash", None, None, None), Decimal("0.00")),
            (("gold", None, None, None), Decimal("0.20")),
            (("govt_bond", 1, "0_1y", None), Decimal("0.005")),
            (("govt_bond", 1, "1_3y", None), Decimal("0.02")),
            (("govt_bond", 1, "3_5y", None), Decimal("0.02")),
            (("govt_bond", 1, "5_10y", None), Decimal("0.04")),
            (("govt_bond", 1, "10y_plus", None), Decimal("0.04")),
            (("govt_bond", 2, "0_1y", None), Decimal("0.01")),
            (("govt_bond", 2, "1_3y", None), Decimal("0.03")),
            (("govt_bond", 2, "3_5y", None), Decimal("0.03")),
            (("govt_bond", 2, "5_10y", None), Decimal("0.06")),
            (("govt_bond", 2, "10y_plus", None), Decimal("0.06")),
            (("govt_bond", 3, "0_1y", None), Decimal("0.01")),
            (("govt_bond", 3, "1_3y", None), Decimal("0.03")),
            (("govt_bond", 3, "3_5y", None), Decimal("0.03")),
            (("govt_bond", 3, "5_10y", None), Decimal("0.06")),
            (("govt_bond", 3, "10y_plus", None), Decimal("0.06")),
            (("govt_bond", 4, "0_1y", None), Decimal("0.15")),
            (("govt_bond", 4, "1_3y", None), Decimal("0.15")),
            (("govt_bond", 4, "3_5y", None), Decimal("0.15")),
            (("govt_bond", 4, "5_10y", None), Decimal("0.15")),
            (("govt_bond", 4, "10y_plus", None), Decimal("0.15")),
            (("corp_bond", 1, "0_1y", None), Decimal("0.01")),
            (("corp_bond", 1, "1_3y", None), Decimal("0.03")),
            (("corp_bond", 1, "3_5y", None), Decimal("0.04")),
            (("corp_bond", 1, "5_10y", None), Decimal("0.06")),
            (("corp_bond", 1, "10y_plus", None), Decimal("0.12")),
            (("corp_bond", 2, "0_1y", None), Decimal("0.02")),
            (("corp_bond", 2, "1_3y", None), Decimal("0.04")),
            (("corp_bond", 2, "3_5y", None), Decimal("0.06")),
            (("corp_bond", 2, "5_10y", None), Decimal("0.12")),
            (("corp_bond", 2, "10y_plus", None), Decimal("0.20")),
            (("corp_bond", 3, "0_1y", None), Decimal("0.02")),
            (("corp_bond", 3, "1_3y", None), Decimal("0.04")),
            (("corp_bond", 3, "3_5y", None), Decimal("0.06")),
            (("corp_bond", 3, "5_10y", None), Decimal("0.12")),
            (("corp_bond", 3, "10y_plus", None), Decimal("0.20")),
            (("equity", None, None, True), Decimal("0.20")),
            (("equity", None, None, False), Decimal("0.30")),
            (("real_estate", None, None, None), Decimal("0.40")),
            (("receivables", None, None, None), Decimal("0.40")),
            (("other_physical", None, None, None), Decimal("0.40")),
        ),
        citation=Citation(
            "PS1/26", "224", "Basel 3.1 FCCM supervisory haircuts (5 maturity bands)"
        ),
    ),
}
