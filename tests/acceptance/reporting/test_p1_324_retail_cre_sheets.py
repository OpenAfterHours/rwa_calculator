"""
P1.324 - retail secured only on commercial property, end to end, both regimes.

Pipeline position:
    build_reporting_retail_cre_bundle() -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator (OF 08.01 / C 08.01)

What is pinned, in order, so a failure is diagnosable:

1. **The portfolio has the shape.** Three A-IRB ``retail_mortgage`` legs, each
   40% covered by RECOGNISED immovable property (``crm_alloc_real_estate``), two
   on shops and one on a house, with own estimates below every Basel 3.1 floor.
   The class is the same on all three in both regimes: P1.324 does not move it.
2. **Basel 3.1 capital.** The two shop-secured legs are PS1/26 Art. 147(5C)
   other retail for the three residential-limbed floors: the Art. 163(1)(c)
   0.05% PD floor, no Art. 154(4A)(b) 10% RWEA floor, and the Art. 164(4)(c)
   LGD* blend 0.4 x 10% + 0.6 x 30% = 22%. The house-secured leg keeps the
   0.10% PD floor, the flat 5% LGD floor and the 10% floor add-on.
3. **Basel 3.1 reporting.** OF 08.01 sheets 0018 / 0019 (retail CRE, SME /
   non-SME) carry column 0253 = 0 beside a NON-zero column 0260, and sheet 0021
   (retail RRE) keeps its positive column 0253 — the two-leg shape that tells
   "the floor no longer reaches CRE" from "the cell was zeroed" (LESSONS B5).
4. **CRR is untouched.** One flat 0.03% PD floor, no A-IRB LGD floor, no post
   model adjustment — and the CRR Art. 164(4) 15% COMMERCIAL bucket still sees
   the shop-secured legs, which is why the class could not be narrowed instead.

Every expected modelled figure is re-derived here from the Art. 154(1) retail
formula with ``statistics.NormalDist``, not read off the engine.

References:
- PS1/26 Art. 147(5B)/(5C), 154(1)/(3), 154(4A)(b), 163(1)(b)/(c), 164(4)(a)-(c)
- CRR Art. 154(3), 163(1), 164(4)
- PS1/26 Annex II (reporting instructions) 3.3 items 4.1-4.4; column 0253
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from statistics import NormalDist

import polars as pl
import pytest
from tests.fixtures.reporting_retail_cre_portfolio import (
    DRAWN,
    LGD_RETAIL,
    LN_CRE,
    LN_CRE_SME,
    LN_RRE,
    PD_RETAIL,
    PROPERTY_VALUE,
    RETAIL_CRE_EXPECTED_B31_SHEET,
    RETAIL_CRE_EXPECTED_CLASS,
    build_reporting_retail_cre_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

#: Recognised immovable property per leg. Basel 3.1: 200,000 less the 40% immovable
#: property haircut, i.e. 40% cover — the figure the Art. 164(4)(c) LGD* reads. CRR
#: recognises 200,000 / 1.4 (its own Art. 230 basis); it is asserted only to be a
#: PARTIAL cover there, because nothing on the CRR path under test reads it.
_RECOGNISED_RE: dict[str, float] = {"b31": 120_000.0, "crr": PROPERTY_VALUE / 1.4}
#: Art. 154(3): R = 0.15 for retail secured by immovable property (any kind).
_R_RETAIL_RE: float = 0.15
#: Art. 164(4)(c) LGD* at 40% cover: 0.4 x 10% (immovable property) + 0.6 x 30% LGDU.
_LGD_STAR_40PCT: float = 0.4 * 0.10 + 0.6 * 0.30
#: Art. 154(4A)(b) floor: 10% of the exposure value.
_RWEA_FLOOR: float = 0.10 * DRAWN

_TOTAL_ROW: str = "0010"


def _retail_rwea(pd: float, lgd: float) -> float:
    """Art. 154(1) retail RWEA at R = 0.15: no maturity adjustment, no 1.06 (B31)."""
    norm = NormalDist()
    r = _R_RETAIL_RE
    k = (
        lgd
        * norm.cdf((1 - r) ** -0.5 * norm.inv_cdf(pd) + (r / (1 - r)) ** 0.5 * norm.inv_cdf(0.999))
        - pd * lgd
    )
    return k * 12.5 * DRAWN


#: Basel 3.1 modelled (paragraph 1/3/4) RWEA per leg, before any post model adjustment.
_B31_MODELLED: dict[str, float] = {
    LN_CRE: _retail_rwea(0.0005, _LGD_STAR_40PCT),
    LN_CRE_SME: _retail_rwea(0.0005, _LGD_STAR_40PCT),
    LN_RRE: _retail_rwea(0.0010, 0.05),
}
#: Basel 3.1 (PD floor, LGD floor, Art. 154(4A)(b) add-on) per leg.
_B31_FLOORS: dict[str, tuple[float, float, float]] = {
    LN_CRE: (0.0005, _LGD_STAR_40PCT, 0.0),
    LN_CRE_SME: (0.0005, _LGD_STAR_40PCT, 0.0),
    LN_RRE: (0.0010, 0.05, _RWEA_FLOOR - _B31_MODELLED[LN_RRE]),
}


def _config(regime_key: str) -> CalculationConfig:
    """IRB configuration at the registered runs' reference dates (``_irb_config``)."""
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


@lru_cache(maxsize=2)
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle, tuple[CalculationError, ...]]:
    """Run the portfolio through one regime and generate COREP; memoised."""
    result = PipelineOrchestrator().run_with_data(
        build_reporting_retail_cre_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=_REGIMES[regime_key])
    return result.results.collect(), corep, tuple(result.errors)


def _leg(regime_key: str, reference: str) -> dict[str, object]:
    frame, _corep, _errors = _run(regime_key)
    rows = frame.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, f"{reference} emitted {rows.height} times"
    return rows.row(0, named=True)


def _total_row(regime_key: str, sheet_key: str) -> dict[str, object]:
    _frame, corep, _errors = _run(regime_key)
    assert sheet_key in corep.c08_01, f"sheet {sheet_key!r} not emitted: {sorted(corep.c08_01)}"
    rows = corep.c08_01[sheet_key].filter(pl.col("row_ref") == _TOTAL_ROW)
    assert rows.height == 1
    return rows.row(0, named=True)


class TestPortfolioShape:
    """The fixture can express what it exists for (LESSONS C11)."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize("reference", list(RETAIL_CRE_EXPECTED_CLASS))
    def test_every_leg_is_a_partially_covered_airb_retail_mortgage(
        self, regime_key: str, reference: str
    ) -> None:
        """Same class in both regimes; 40% recognised property cover; A-IRB."""
        # Act
        leg = _leg(regime_key, reference)

        # Assert
        assert leg["exposure_class"] == RETAIL_CRE_EXPECTED_CLASS[reference]
        assert leg["approach_applied"] == "advanced_irb"
        assert leg["crm_alloc_real_estate"] == pytest.approx(_RECOGNISED_RE[regime_key])
        assert 0.0 < leg["crm_alloc_real_estate"] < DRAWN, "the leg must be PARTIALLY covered"
        assert leg["correlation"] == pytest.approx(_R_RETAIL_RE)

    def test_own_estimates_sit_below_every_basel_3_1_floor(self) -> None:
        """Every Basel 3.1 floor binds, so each result IS the floor."""
        # Assert
        assert PD_RETAIL < 0.0005
        assert LGD_RETAIL < 0.05
        assert _B31_MODELLED[LN_RRE] < _RWEA_FLOOR


class TestBasel31Capital:
    """The shop-secured legs are other retail for the three residential-limbed floors."""

    @pytest.mark.parametrize("reference", list(_B31_FLOORS))
    def test_pd_lgd_and_rwea_floor_per_leg(self, reference: str) -> None:
        """Art. 163(1)(b)/(c), 164(4)(a)/(c), 154(4A)(b) per leg."""
        # Arrange
        pd_floor, lgd_floor, add_on = _B31_FLOORS[reference]

        # Act
        leg = _leg("b31", reference)

        # Assert
        assert leg["pd_floored"] == pytest.approx(pd_floor)
        assert leg["lgd_floored"] == pytest.approx(lgd_floor)
        assert leg["mortgage_rw_floor_adjustment"] == pytest.approx(add_on, abs=1e-6)

    @pytest.mark.parametrize("reference", list(_B31_MODELLED))
    def test_modelled_rwea_per_leg(self, reference: str) -> None:
        """The modelled RWEA is the Art. 154(1) formula on the floored inputs."""
        # Act
        leg = _leg("b31", reference)

        # Assert
        assert leg["rwa_pre_adjustments"] == pytest.approx(_B31_MODELLED[reference], rel=1e-9)


class TestBasel31Reporting:
    """OF 08.01: CRE sheets carry no 0253 add-on; the RRE sheet keeps its own."""

    @pytest.mark.parametrize("reference", [LN_CRE, LN_CRE_SME])
    def test_cre_sheet_has_no_mortgage_floor_add_on_but_live_rwea(self, reference: str) -> None:
        """Column 0253 is 0 and column 0260 is the modelled RWEA (not zero)."""
        # Act
        row = _total_row("b31", RETAIL_CRE_EXPECTED_B31_SHEET[reference])

        # Assert
        assert row["0253"] == pytest.approx(0.0)
        assert row["0260"] == pytest.approx(_B31_MODELLED[reference], rel=1e-9)
        assert row["0260"] > 0.0

    def test_rre_sheet_keeps_its_mortgage_floor_add_on(self) -> None:
        """The live-cell control: sheet 0021 column 0253 is the floor shortfall."""
        # Act
        row = _total_row("b31", RETAIL_CRE_EXPECTED_B31_SHEET[LN_RRE])

        # Assert
        assert row["0253"] == pytest.approx(_RWEA_FLOOR - _B31_MODELLED[LN_RRE], rel=1e-9)
        assert row["0260"] == pytest.approx(_RWEA_FLOOR, rel=1e-9)


class TestCRRUntouched:
    """CRR: flat PD floor, no LGD input floor, no PMA; the 15% CRE bucket still live."""

    @pytest.mark.parametrize("reference", list(RETAIL_CRE_EXPECTED_CLASS))
    def test_own_estimates_pass_through(self, reference: str) -> None:
        """PD 0.04% is above CRR's 0.03%; A-IRB LGD is not floored per exposure."""
        # Act
        leg = _leg("crr", reference)

        # Assert
        assert leg["pd_floored"] == pytest.approx(PD_RETAIL)
        assert leg["lgd_floored"] == pytest.approx(LGD_RETAIL)
        assert leg["mortgage_rw_floor_adjustment"] == pytest.approx(0.0)

    def test_commercial_bucket_of_art_164_4_still_sees_the_shop_secured_legs(self) -> None:
        """IRB007 fires for the COMMERCIAL bucket: the legs stayed in retail_mortgage."""
        # Act
        _frame, _corep, errors = _run("crr")
        messages = [e.message for e in errors if e.code == "IRB007"]

        # Assert
        assert any("commercial real-estate retail" in m for m in messages), messages
        assert any("residential real-estate retail" in m for m in messages), messages
