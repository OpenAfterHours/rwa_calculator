"""
P1.324 - a house the CRM recognises keeps the residential floors, end to end.

Pipeline position:
    build_residential_security_guard_bundle() -> PipelineOrchestrator (Basel 3.1)
        -> results frame (IRB legs)

PS1/26 Art. 147(5B) puts "retail exposures secured by residential immovable
property" in the (d)(ii) subclass, and Basel 3.1 ties three floors to it: the
Art. 154(4A)(b) 10% RWEA floor, the Art. 163(1)(b) 0.1% PD floor and the
Art. 164(4)(a) "flat 5% floor value for retail exposures secured by residential
immovable property, irrespective of the level of collateral provided". A
``retail_mortgage`` row leaves those floors only when it is secured on commercial
property AND on nothing residential (Art. 147(5C) other retail).

Each guard leg is secured by a house that the CRM sees (``collateral_re_market_value``
counts it) on a route the hierarchy's drawn-basis property values and keep-first
``property_type`` do not follow — the ``collateral_links`` table, a pledge at an
ancestor facility, a real-estate ``collateral_type`` synonym. A residential test
blind to those routes reads each leg as commercial-only and RELEASES capital on a
house-secured exposure (P1.324 review F1, measured at 89,764 against 97,167 on
the links shape). So each guard must take PD 0.10%, LGD 5% and a positive 10%
floor add-on — at HEAD and after the fix.

The control leg (a shop and nothing else) MUST move — 0.05% / LGD* 22% / no add-on
— or every guard could pass simply because the change was not active.

Each test first asserts the leg's shape (LESSONS C11): ``property_type`` reads
``commercial``, the hierarchy's residential values are 0 (on the links leg, since
P1.450 spreads linked real estate in the hierarchy, they are positive and only the
keep-first type is blind), and the CRM sees more real estate than the shop.
Without these the guard could not fail.

References:
- PS1/26 Art. 147(5B)/(5C), 154(4A)(b), 163(1)(b)/(c), 164(4)(a)/(c)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.retail_residential_security_guards import (
    DRAWN,
    GUARD_LOANS,
    LN_CONTROL,
    LN_LINKS,
    PD_RETAIL,
    SHOP_RECOGNISED_B31,
    SHOP_VALUE,
    build_residential_security_guard_bundle,
)

#: Art. 163(1)(b) / (c) Basel 3.1 retail PD floors (pack ``pd_floors``).
_PD_FLOOR_RESIDENTIAL: float = 0.0010
_PD_FLOOR_OTHER_RETAIL: float = 0.0005
#: Art. 164(4)(a) flat floor for residential-secured retail.
_LGD_FLOOR_RESIDENTIAL: float = 0.05
#: Art. 164(4)(c) LGD* on the control's 40% immovable-property cover:
#: 0.4 x 10% (LGDS, immovable property) + 0.6 x 30% (LGDU).
_LGD_STAR_CONTROL: float = (SHOP_RECOGNISED_B31 / DRAWN) * 0.10 + (
    1.0 - SHOP_RECOGNISED_B31 / DRAWN
) * 0.30


@lru_cache(maxsize=1)
def _results() -> pl.DataFrame:
    """Run the guard portfolio once under Basel 3.1 (A-IRB permissions)."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )
    result = PipelineOrchestrator().run_with_data(build_residential_security_guard_bundle(), config)
    return result.results.collect()


def _leg(reference: str) -> dict[str, object]:
    rows = _results().filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, f"{reference} emitted {rows.height} times"
    return rows.row(0, named=True)


class TestGuardShape:
    """Each guard is the shape that defeats a residential test blind to its route."""

    @pytest.mark.parametrize("reference", [*GUARD_LOANS, LN_CONTROL])
    def test_leg_is_an_airb_retail_mortgage_below_every_floor(self, reference: str) -> None:
        """A-IRB ``retail_mortgage``; own PD below both floors, so the floor IS the result."""
        # Act
        leg = _leg(reference)

        # Assert
        assert leg["exposure_class"] == "retail_mortgage"
        assert leg["approach_applied"] == "advanced_irb"
        assert PD_RETAIL < _PD_FLOOR_OTHER_RETAIL

    @pytest.mark.parametrize("reference", GUARD_LOANS)
    def test_hierarchy_values_miss_the_house_but_the_crm_sees_it(self, reference: str) -> None:
        """``commercial`` by keep-first, no residential value, yet more RE than the shop."""
        # Act
        leg = _leg(reference)

        # Assert
        assert leg["property_type"] == "commercial"
        if reference == LN_LINKS:
            # Since P1.450 the hierarchy follows ``collateral_links`` too, so the linked
            # house reaches this leg's residential values; the keep-first
            # ``property_type`` still reads the shop, which is the trap this leg keeps.
            assert leg["residential_collateral_value_uncapped"] > 0.0
        else:
            assert leg["residential_collateral_value"] == pytest.approx(0.0)
            assert leg["residential_collateral_value_uncapped"] == pytest.approx(0.0)
        assert leg["collateral_re_market_value"] > SHOP_VALUE, (
            "the CRM must see the house, or this leg is not residential-secured"
        )


class TestHouseSecuredGuardsKeepTheResidentialFloors:
    """Art. 147(5B): each guard is (d)(ii) residential-secured retail."""

    @pytest.mark.parametrize("reference", GUARD_LOANS)
    def test_pd_floor_is_the_residential_floor(self, reference: str) -> None:
        """Art. 163(1)(b): 0.1%."""
        # Act
        leg = _leg(reference)

        # Assert
        assert leg["pd_floored"] == pytest.approx(_PD_FLOOR_RESIDENTIAL)

    @pytest.mark.parametrize("reference", GUARD_LOANS)
    def test_lgd_floor_is_the_flat_residential_floor(self, reference: str) -> None:
        """Art. 164(4)(a): flat 5%, irrespective of the collateral."""
        # Act
        leg = _leg(reference)

        # Assert
        assert leg["lgd_floored"] == pytest.approx(_LGD_FLOOR_RESIDENTIAL)

    @pytest.mark.parametrize("reference", GUARD_LOANS)
    def test_ten_percent_rwea_floor_still_adds(self, reference: str) -> None:
        """Art. 154(4A)(b): the modelled RWEA is below 10% of EAD, so the add-on is positive."""
        # Act
        leg = _leg(reference)

        # Assert
        assert leg["mortgage_rw_floor_adjustment"] > 0.0
        assert leg["rwa_pre_adjustments"] + leg["mortgage_rw_floor_adjustment"] == pytest.approx(
            0.10 * DRAWN, rel=1e-9
        )


class TestCommercialOnlyControlMoves:
    """Art. 147(5C): the shop-only leg is other retail on all three floors."""

    def test_control_takes_the_other_retail_floors(self) -> None:
        """0.05% PD, the Art. 164(4)(c) LGD* blend, and no 10% floor add-on."""
        # Act
        leg = _leg(LN_CONTROL)

        # Assert
        assert leg["collateral_re_market_value"] == pytest.approx(SHOP_VALUE)
        assert leg["pd_floored"] == pytest.approx(_PD_FLOOR_OTHER_RETAIL)
        assert leg["lgd_floored"] == pytest.approx(_LGD_STAR_CONTROL)
        assert leg["mortgage_rw_floor_adjustment"] == pytest.approx(0.0)
