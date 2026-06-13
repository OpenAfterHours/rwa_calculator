"""
Byte-identical parity pins: rulebook floor bundles vs the config floor factories.

Phase 5 S5c moves the IRB PD/LGD floors off ``contracts/config.py`` (PDFloors /
LGDFloors dataclasses) and onto the resolved rulepack (``pd_floors`` / ``lgd_floors``
FormulaParams in packs/crr.py + packs/b31.py, gated by the ``airb_lgd_floor``
Feature). These pins guarantee the pack-authored values reproduce the config
factory values field-for-field, so the engine swap (config-read -> pack-read) is
byte-identical. They are the safety net for the floor migration: any drift between
the two sources fails here before it can move an RWA number.

References:
- CRR Art. 160(1): uniform 0.03% IRB PD floor.
- PRA PS1/26 Art. 160(1)/163(1): differentiated Basel 3.1 PD floors.
- PRA PS1/26 Art. 161(5)/164(4): Basel 3.1 A-IRB LGD floors.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date

from rwa_calc.contracts.config import LGDFloors, PDFloors
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))


def _factory_params(floors: object) -> dict[str, object]:
    """Project a PDFloors / LGDFloors instance to its ``{field_name: Decimal}`` map."""
    return {f.name: getattr(floors, f.name) for f in fields(floors)}


# ---------------------------------------------------------------------------
# PD floors — pack bundle vs PDFloors factory
# ---------------------------------------------------------------------------


def test_pd_floors_crr_pack_matches_config_factory() -> None:
    # Arrange / Act / Assert
    assert dict(_CRR_PACK.formula("pd_floors").params) == _factory_params(PDFloors.crr())


def test_pd_floors_b31_pack_matches_config_factory() -> None:
    # Arrange / Act / Assert
    assert dict(_B31_PACK.formula("pd_floors").params) == _factory_params(PDFloors.basel_3_1())


# ---------------------------------------------------------------------------
# LGD floors — pack bundle vs LGDFloors factory
# ---------------------------------------------------------------------------


def test_lgd_floors_crr_pack_matches_config_factory() -> None:
    # Arrange / Act / Assert
    assert dict(_CRR_PACK.formula("lgd_floors").params) == _factory_params(LGDFloors.crr())


def test_lgd_floors_b31_pack_matches_config_factory() -> None:
    # Arrange / Act / Assert
    assert dict(_B31_PACK.formula("lgd_floors").params) == _factory_params(LGDFloors.basel_3_1())


# ---------------------------------------------------------------------------
# airb_lgd_floor Feature — CRR has no A-IRB LGD floor; Basel 3.1 does
# ---------------------------------------------------------------------------


def test_airb_lgd_floor_feature_disabled_under_crr() -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature("airb_lgd_floor") is False


def test_airb_lgd_floor_feature_enabled_under_b31() -> None:
    # Arrange / Act / Assert
    assert _B31_PACK.feature("airb_lgd_floor") is True
