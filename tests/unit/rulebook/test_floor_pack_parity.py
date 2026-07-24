"""
Regulatory-value pins for the rulebook IRB PD/LGD floor bundles.

Phase 5 S5c moved the IRB PD/LGD floors onto the resolved rulepack (``pd_floors``
/ ``lgd_floors`` FormulaParams in packs/crr.py + packs/b31.py, gated by the
``airb_lgd_floor`` Feature). Phase 5 S11e-carve(2) then deleted the legacy
``contracts/config.py`` PDFloors / LGDFloors dataclasses (the engine reads the
pack). These pins assert the pack-authored floor values directly — the canonical
regulatory values — so any drift fails here before it can move an RWA number.

References:
- CRR Art. 160(1): uniform 0.03% IRB PD floor.
- PRA PS1/26 Art. 160(1)/163(1): differentiated Basel 3.1 PD floors.
- PRA PS1/26 Art. 161(5)/164(4): Basel 3.1 A-IRB LGD floors.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# CRR Art. 160(1): 0.03% PD floor for corporates and institutions only ("The PD
# of an exposure to a corporate or an institution shall be at least 0,03 %").
# Retail is floored at the same rate by the separate Art. 163(1). Central
# governments / central banks are in neither article, so ``sovereign`` is 0
# (P1.277) — which is also what keeps _pd_floor_expression's all-equal scalar
# shortcut from collapsing the CRR class ladder.
_CRR_PD_FLOORS = {
    "corporate": Decimal("0.0003"),
    "corporate_sme": Decimal("0.0003"),
    "sovereign": Decimal("0"),
    "institution": Decimal("0.0003"),
    "retail_mortgage": Decimal("0.0003"),
    "retail_other": Decimal("0.0003"),
    "retail_qrre_transactor": Decimal("0.0003"),
    "retail_qrre_revolver": Decimal("0.0003"),
}
# PRA PS1/26 Art. 160(1) wholesale / 163(1) retail: differentiated PD floors.
_B31_PD_FLOORS = {
    "corporate": Decimal("0.0005"),
    "corporate_sme": Decimal("0.0005"),
    "sovereign": Decimal("0.0005"),
    "institution": Decimal("0.0005"),
    "retail_mortgage": Decimal("0.0010"),
    "retail_other": Decimal("0.0005"),
    "retail_qrre_transactor": Decimal("0.0005"),
    "retail_qrre_revolver": Decimal("0.0010"),
}
# CRR Art. 164: no A-IRB own-estimate LGD floor (all zero).
_CRR_LGD_FLOORS = {
    "unsecured": Decimal("0.0"),
    "subordinated_unsecured": Decimal("0.0"),
    "financial_collateral": Decimal("0.0"),
    "receivables": Decimal("0.0"),
    "commercial_real_estate": Decimal("0.0"),
    "residential_real_estate": Decimal("0.0"),
    "other_physical": Decimal("0.0"),
    "retail_rre": Decimal("0.0"),
    "retail_qrre_unsecured": Decimal("0.0"),
    "retail_other_unsecured": Decimal("0.0"),
    "retail_lgdu": Decimal("0.0"),
}
# PRA PS1/26 Art. 161(5) corporate / 164(4) retail: A-IRB LGD floors.
_B31_LGD_FLOORS = {
    "unsecured": Decimal("0.25"),
    "subordinated_unsecured": Decimal("0.50"),
    "financial_collateral": Decimal("0.0"),
    "receivables": Decimal("0.10"),
    "commercial_real_estate": Decimal("0.10"),
    "residential_real_estate": Decimal("0.10"),
    "other_physical": Decimal("0.15"),
    "retail_rre": Decimal("0.05"),
    "retail_qrre_unsecured": Decimal("0.50"),
    "retail_other_unsecured": Decimal("0.30"),
    "retail_lgdu": Decimal("0.30"),
}


# ---------------------------------------------------------------------------
# PD floors — pack bundle holds the canonical values
# ---------------------------------------------------------------------------


def test_pd_floors_crr_pack_values() -> None:
    # Arrange / Act / Assert
    assert dict(_CRR_PACK.formula("pd_floors").params) == _CRR_PD_FLOORS


def test_pd_floors_b31_pack_values() -> None:
    # Arrange / Act / Assert
    assert dict(_B31_PACK.formula("pd_floors").params) == _B31_PD_FLOORS


# ---------------------------------------------------------------------------
# LGD floors — pack bundle holds the canonical values
# ---------------------------------------------------------------------------


def test_lgd_floors_crr_pack_values() -> None:
    # Arrange / Act / Assert
    assert dict(_CRR_PACK.formula("lgd_floors").params) == _CRR_LGD_FLOORS


def test_lgd_floors_b31_pack_values() -> None:
    # Arrange / Act / Assert
    assert dict(_B31_PACK.formula("lgd_floors").params) == _B31_LGD_FLOORS


# ---------------------------------------------------------------------------
# airb_lgd_floor Feature — CRR has no A-IRB LGD floor; Basel 3.1 does
# ---------------------------------------------------------------------------


def test_airb_lgd_floor_feature_disabled_under_crr() -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature("airb_lgd_floor") is False


def test_airb_lgd_floor_feature_enabled_under_b31() -> None:
    # Arrange / Act / Assert
    assert _B31_PACK.feature("airb_lgd_floor") is True
