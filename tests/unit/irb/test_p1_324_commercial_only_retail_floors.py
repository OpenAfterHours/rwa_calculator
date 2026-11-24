"""
P1.324 - commercial-only-secured retail is "other retail" for three Basel 3.1 floors.

Pipeline stage: IRB calculator -
    ``engine/irb/transforms.py::apply_pd_floor`` / ``apply_lgd_floor`` and
    ``engine/irb/adjustments.py::apply_post_model_adjustments``.

The classifier puts every property-secured retail row in ``retail_mortgage``,
commercial security included, and that is right for the three consumers that
need it: R = 0.15 (Art. 154(3), "secured by immovable property collateral" in
both regimes), the CRR Art. 164(4) 15% commercial LGD bucket, and the Basel 3.1
OF 08.01 "secured by commercial immovable property" sheets. But PS1/26 ties three
retail treatments to RESIDENTIAL security, and the engine read all three off the
class:

- Art. 154(4A)(b): the 10% RWEA floor is for "retail exposures secured by UK
  residential immovable property";
- Art. 163(1): "(b) 0.1% for retail exposures secured by residential immovable
  property located in the UK; and (c) 0.05% for all other retail exposures";
- Art. 164(4): "(a) a flat 5% floor value for retail exposures secured by
  residential immovable property ... (c) for secured and partially secured
  exposures not within the scope of point (a) ... LGD* ... substitute: (iii) 30%
  for LGDU; and (iv) ... (3) 10% for immovable property".

Art. 147(5B) puts "retail exposures secured by residential immovable property"
in (d)(ii) and Art. 147(5C) puts every other retail exposure in (d)(iii) other
retail. So a row secured ONLY on commercial property takes the (c) PD floor, no
10% floor, and the (c) LGD* blend (or the (b)(ii) flat 30% with no recognised
collateral). The first two lower RWEA. The third moves it EITHER way: the blend is
not bounded below by the (a) flat 5% it replaces, and Art. 164(4)(c)(iv)(1) gives
financial collateral a 0% LGDS, so a row covered mostly by property (or thinly)
floors above 5% and a row covered mostly by financial collateral floors below it.
``COMM_ONLY_CASH`` pins the second side at an absolute value: a floor written as
max(LGD*, 5%) - the version of the rule that only adds capital - fails it.

The residential test reads EVERY residential carrier, not one. Two of them are
blind on real rows: ``residential_collateral_value`` is drawn-basis and capped
at drawn, so it is 0 on a house-secured facility's undrawn row, and
``property_type`` is keep-first by input row order, so a house-plus-shop
security can read ``commercial``. The GUARD rows are each residential-secured
(or of unknown security) on a carrier the others miss — the hierarchy's
``re_collateral_may_be_residential`` flag, the uncapped residential value, or
the firm's UK residential mortgage commitment attestation — and each must keep
the residential limbs, at HEAD and after the fix. The routes the flag itself
follows (links, the facility cascade, type synonyms) are pinned at the hierarchy
(``tests/unit/test_p1_324_re_collateral_may_be_residential.py``) and end to end
(``tests/acceptance/basel31/test_p1_324_residential_security_guards.py``).

CRR is the control: one flat 0.03% PD floor, no A-IRB LGD input floor, no post
model adjustments, so none of these rows can move there.

References:
    - PRA PS1/26 Art. 147(5B)/(5C), 154(3), 154(4A)(b), 163(1)(b)/(c), 164(4)(a)-(c)
    - CRR Art. 154(3), 163(1), 164(4)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PropertyType
from rwa_calc.engine.irb.transforms import (
    apply_lgd_floor,
    apply_pd_floor,
    apply_post_model_adjustments,
)
from rwa_calc.rulebook.compile import formula_float_map
from rwa_calc.rulebook.resolve import resolve

#: Every leg's exposure value, and the base the 10% floor is measured against.
EAD = 100_000.0
#: Modelled (paragraph 1/3/4) risk weight, below the 10% floor so the floor binds.
MODELLED_RW = 0.04
#: Own-estimate PD below every Basel 3.1 retail floor, so the floor is the result.
OWN_PD = 0.0001
#: Own-estimate LGD below every Basel 3.1 retail LGD floor.
OWN_LGD = 0.03
#: 40% of the exposure covered by recognised immovable-property collateral.
RE_COVER = 40_000.0

_COMMERCIAL = PropertyType.COMMERCIAL.value
_RESIDENTIAL = PropertyType.RESIDENTIAL.value
_MORTGAGE = ExposureClass.RETAIL_MORTGAGE.value


@dataclass(frozen=True)
class _Leg:
    """One retail leg: its security carriers and the three floors it must take."""

    reference: str
    exposure_class: str
    property_type: str | None
    residential_value: float
    residential_value_uncapped: float
    may_be_residential: bool | None
    re_alloc: float
    b31_floor_add_on: float
    b31_pd: float
    b31_lgd: float
    uk_resi_commitment: bool | None = False
    own_lgd: float = OWN_LGD
    financial_alloc: float = 0.0


#: (B31) 10% floor shortfall = 0.10 x 100,000 - 0.04 x 100,000.
_FLOOR_ADD_ON = 6_000.0

_LEGS: tuple[_Leg, ...] = (
    # 1 DEMO: commercial-only, 40% covered -> other retail on all three limbs.
    #   HEAD: add-on 6,000 / PD 0.0010 / LGD 0.05. LGD* = 0.4 x 0.10 + 0.6 x 0.30.
    _Leg("COMM_ONLY", _MORTGAGE, _COMMERCIAL, 0.0, 0.0, False, RE_COVER, 0.0, 0.0005, 0.22),
    # 1b DEMO: commercial-only, 95% covered by FINANCIAL collateral (0% LGDS), own LGD
    #   1%. LGD* = 0.95 x 0.00 + 0.05 x 0.30 = 0.015, BELOW the old flat 5%: limb (c)
    #   releases capital here. HEAD: add-on 6,000 / PD 0.0010 / LGD 0.05.
    _Leg(
        "COMM_ONLY_CASH",
        _MORTGAGE,
        _COMMERCIAL,
        0.0,
        0.0,
        False,
        0.0,
        0.0,
        0.0005,
        0.015,
        own_lgd=0.01,
        financial_alloc=95_000.0,
    ),
    # 2 DEMO: commercial-only with no RECOGNISED collateral -> Art. 164(4)(b)(ii) 30%.
    #   HEAD: add-on 6,000 / PD 0.0010 / LGD 0.05.
    _Leg("COMM_ONLY_UNSEC", _MORTGAGE, _COMMERCIAL, 0.0, 0.0, False, 0.0, 0.0, 0.0005, 0.30),
    # 3 CONTROL: residential, drawn -> every carrier says residential.
    _Leg(
        "RES_DRAWN",
        _MORTGAGE,
        _RESIDENTIAL,
        RE_COVER,
        RE_COVER,
        True,
        RE_COVER,
        _FLOOR_ADD_ON,
        0.0010,
        0.05,
    ),
    # 4 GUARD: residential facility, UNDRAWN row -> both values 0 (drawn basis).
    _Leg("RES_UNDRAWN", _MORTGAGE, _RESIDENTIAL, 0.0, 0.0, True, 0.0, _FLOOR_ADD_ON, 0.0010, 0.05),
    # 5 GUARD: label-only mortgage -> no property evidence at all; stays as today.
    _Leg("LABEL_ONLY", _MORTGAGE, None, 0.0, 0.0, False, 0.0, _FLOOR_ADD_ON, 0.0010, 0.05),
    # 6 GUARD: house + shop facility, shop listed first, UNDRAWN row. property_type
    #   reads "commercial" by keep-first and both values are 0; only the
    #   may-be-residential flag sees the house.
    _Leg("MIXED_UNDRAWN", _MORTGAGE, _COMMERCIAL, 0.0, 0.0, True, 0.0, _FLOOR_ADD_ON, 0.0010, 0.05),
    # 7 GUARD: house + shop pledged directly to a drawn=0 loan, shop first. The
    #   capped value is 0; the UNCAPPED value carries the house. The flag is
    #   False here so the uncapped carrier is the only residential evidence.
    _Leg(
        "MIXED_DIRECT_DRAWN0",
        _MORTGAGE,
        _COMMERCIAL,
        0.0,
        500_000.0,
        False,
        0.0,
        _FLOOR_ADD_ON,
        0.0010,
        0.05,
    ),
    # 8 GUARD: commercial type but an UNKNOWN (null) residential flag -> unknown
    #   security is not commercial-only; the row stays where it is today.
    _Leg("FLAG_NULL", _MORTGAGE, _COMMERCIAL, 0.0, 0.0, None, 0.0, _FLOOR_ADD_ON, 0.0010, 0.05),
    # 9 GUARD: commercial-only on every collateral carrier, but the firm attests a
    #   UK residential mortgage commitment (the CCF stage's Table A1 row 4(b)
    #   carrier). Residential evidence on the row: it stays residential.
    _Leg(
        "UK_RESI_COMMITMENT",
        _MORTGAGE,
        _COMMERCIAL,
        0.0,
        0.0,
        False,
        0.0,
        _FLOOR_ADD_ON,
        0.0010,
        0.05,
        uk_resi_commitment=True,
    ),
    # 10 DEMO: an UNKNOWN (null) attestation reads as not-True, exactly like False
    #   (both reach IRB legs of the registered runs, measured), so it is not
    #   residential evidence; the commercial-only row still moves (to 30%).
    _Leg(
        "COMM_ONLY_ATTEST_NULL",
        _MORTGAGE,
        _COMMERCIAL,
        0.0,
        0.0,
        False,
        0.0,
        0.0,
        0.0005,
        0.30,
        uk_resi_commitment=None,
    ),
    # 11 CONTROL: other retail is untouched (no floor, 0.05%, LGD* at 30% LGDU).
    _Leg(
        "RET_OTHER",
        ExposureClass.RETAIL_OTHER.value,
        None,
        0.0,
        0.0,
        False,
        RE_COVER,
        0.0,
        0.0005,
        0.22,
    ),
)

_BY_REF: dict[str, _Leg] = {leg.reference: leg for leg in _LEGS}

#: Rows the fix moves under Basel 3.1. Every other row must not move.
_MOVED: frozenset[str] = frozenset(
    {"COMM_ONLY", "COMM_ONLY_CASH", "COMM_ONLY_UNSEC", "COMM_ONLY_ATTEST_NULL"}
)

#: CRR: one flat Art. 163(1) PD floor, no A-IRB LGD floor, no post model adjustments.
_CRR_PD = 0.0003


def _frame() -> pl.LazyFrame:
    """The twelve-leg frame, shaped as the sealed IRB-branch input carries it.

    No ``collateral_type`` column: the sealed edge never carries one, so the
    production LGD floor takes the no-``collateral_type`` route this frame takes.
    """
    n = len(_LEGS)
    return pl.LazyFrame(
        {
            "exposure_reference": [leg.reference for leg in _LEGS],
            "approach": [ApproachType.AIRB.value] * n,
            "is_airb": [True] * n,
            "exposure_class": [leg.exposure_class for leg in _LEGS],
            "is_defaulted": pl.Series([False] * n, dtype=pl.Boolean),
            "is_qrre_transactor": [False] * n,
            "property_type": pl.Series([leg.property_type for leg in _LEGS], dtype=pl.String),
            "residential_collateral_value": [leg.residential_value for leg in _LEGS],
            "residential_collateral_value_uncapped": [
                leg.residential_value_uncapped for leg in _LEGS
            ],
            "re_collateral_may_be_residential": pl.Series(
                [leg.may_be_residential for leg in _LEGS], dtype=pl.Boolean
            ),
            "is_uk_residential_mortgage_commitment": pl.Series(
                [leg.uk_resi_commitment for leg in _LEGS], dtype=pl.Boolean
            ),
            "pd": [OWN_PD] * n,
            "lgd_input": [leg.own_lgd for leg in _LEGS],
            "ead_final": [EAD] * n,
            "ead_for_crm": [EAD] * n,
            "exposure_volatility_haircut": [0.0] * n,
            "total_collateral_for_lgd": [leg.re_alloc + leg.financial_alloc for leg in _LEGS],
            "crm_alloc_financial": [leg.financial_alloc for leg in _LEGS],
            "crm_alloc_covered_bond": [0.0] * n,
            "crm_alloc_receivables": [0.0] * n,
            "crm_alloc_real_estate": [leg.re_alloc for leg in _LEGS],
            "crm_alloc_other_physical": [0.0] * n,
            "crm_alloc_life_insurance": [0.0] * n,
            "risk_weight": [MODELLED_RW] * n,
            "rwa": [MODELLED_RW * EAD] * n,
            "expected_loss": [0.0] * n,
        }
    )


def _config(regime: str) -> CalculationConfig:
    if regime == "b31":
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


def _run(frame: pl.LazyFrame, config: CalculationConfig) -> dict[str, dict[str, object]]:
    """Run a frame through the three floors; index the rows by reference."""
    result = (
        frame.pipe(apply_pd_floor, config)
        .pipe(apply_lgd_floor, config)
        .pipe(apply_post_model_adjustments, config)
        .collect()
    )
    return {row["exposure_reference"]: row for row in result.to_dicts()}


@pytest.fixture(scope="module", params=["b31", "crr"])
def regime_result(request: pytest.FixtureRequest) -> tuple[str, dict[str, dict[str, object]]]:
    """Run the frame through the three floors under one regime; index by reference."""
    regime = request.param
    return regime, _run(_frame(), _config(regime))


class TestFrameAdequacy:
    """The frame can express what it claims to (LESSONS C11)."""

    def test_floor_values_are_the_basel_3_1_pack_values(self) -> None:
        """The expected PD / LGD / RW floors are the production pack's, not typed guesses."""
        # Arrange
        pack = resolve("b31", date(2027, 6, 30))
        pd_floors = formula_float_map(pack.formula("pd_floors"))
        lgd_floors = formula_float_map(pack.formula("lgd_floors"))

        # Assert
        assert pd_floors["retail_mortgage"] == pytest.approx(0.0010)
        assert pd_floors["retail_other"] == pytest.approx(0.0005)
        assert lgd_floors["retail_rre"] == pytest.approx(0.05)
        assert lgd_floors["retail_other_unsecured"] == pytest.approx(0.30)
        assert lgd_floors["retail_lgdu"] == pytest.approx(0.30)
        assert lgd_floors["commercial_real_estate"] == pytest.approx(0.10)
        assert pack.scalar("mortgage_rw_floor") == Decimal("0.10")

    def test_own_estimates_sit_below_every_floor(self) -> None:
        """Every floor binds, so each result IS the floor and a wrong floor shows."""
        # Assert
        assert all(leg.b31_pd > OWN_PD for leg in _LEGS)
        assert all(leg.b31_lgd > leg.own_lgd for leg in _LEGS)
        assert MODELLED_RW * EAD < 0.10 * EAD

    def test_a_commercial_only_leg_floors_below_the_flat_residential_floor(self) -> None:
        """Limb (c) can LOWER the floor: some commercial-only leg expects less than 5%.

        Without such a leg, max(LGD*, 5%) - a floor that can only add capital -
        passes every expectation here (LESSONS C11: the frame must be able to
        express the defect it guards against).
        """
        # Arrange
        pack = resolve("b31", date(2027, 6, 30))
        retail_rre = formula_float_map(pack.formula("lgd_floors"))["retail_rre"]

        # Act
        below = {ref for ref in _MOVED if _BY_REF[ref].b31_lgd < retail_rre}

        # Assert
        assert below == {"COMM_ONLY_CASH"}


class TestCommercialOnlyRetailFloors:
    """Art. 154(4A)(b) / 163(1) / 164(4) read the security, not the class."""

    @pytest.mark.parametrize("reference", list(_BY_REF))
    def test_mortgage_rw_floor_add_on(
        self, reference: str, regime_result: tuple[str, dict[str, dict[str, object]]]
    ) -> None:
        """Art. 154(4A)(b): only residential (or unknown) security takes the 10% add-on."""
        # Arrange
        regime, rows = regime_result
        expected = _BY_REF[reference].b31_floor_add_on if regime == "b31" else 0.0

        # Act
        row = rows[reference]

        # Assert
        assert row["mortgage_rw_floor_adjustment"] == pytest.approx(expected)
        assert row["rwa"] == pytest.approx(MODELLED_RW * EAD + expected)

    @pytest.mark.parametrize("reference", list(_BY_REF))
    def test_pd_floor(
        self, reference: str, regime_result: tuple[str, dict[str, dict[str, object]]]
    ) -> None:
        """Art. 163(1)(b)/(c): 0.10% for residential security, 0.05% for other retail."""
        # Arrange
        regime, rows = regime_result
        expected = _BY_REF[reference].b31_pd if regime == "b31" else _CRR_PD

        # Act
        row = rows[reference]

        # Assert
        assert row["pd_floored"] == pytest.approx(expected)

    @pytest.mark.parametrize("reference", list(_BY_REF))
    def test_lgd_floor(
        self, reference: str, regime_result: tuple[str, dict[str, dict[str, object]]]
    ) -> None:
        """Art. 164(4)(a)/(b)(ii)/(c): flat 5% only for residential security."""
        # Arrange
        regime, rows = regime_result
        leg = _BY_REF[reference]
        expected = leg.b31_lgd if regime == "b31" else leg.own_lgd

        # Act
        row = rows[reference]

        # Assert
        assert row["lgd_floored"] == pytest.approx(expected)

    def test_only_the_commercial_only_rows_differ_from_a_residential_mortgage(
        self, regime_result: tuple[str, dict[str, dict[str, object]]]
    ) -> None:
        """Set diff, not a total: exactly the commercial-only rows leave the residential limbs.

        Each row is compared with its residential twin - the same row with the
        hierarchy's residential flag set - so the legs' different own LGDs and
        collateral cannot show as a move.
        """
        # Arrange
        regime, rows = regime_result
        twin_frame = _frame().with_columns(pl.lit(True).alias("re_collateral_may_be_residential"))
        twins = _run(twin_frame, _config(regime))
        limbs = ("mortgage_rw_floor_adjustment", "pd_floored", "lgd_floored")

        # Act
        moved = {
            ref
            for ref, row in rows.items()
            if row["exposure_class"] == _MORTGAGE
            and any(row[limb] != pytest.approx(twins[ref][limb]) for limb in limbs)
        }

        # Assert
        assert moved == (set(_MOVED) if regime == "b31" else set())
