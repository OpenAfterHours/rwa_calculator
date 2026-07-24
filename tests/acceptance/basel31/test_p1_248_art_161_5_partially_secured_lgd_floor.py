"""
P1.248: PS1/26 Art. 161(5) — corporate A-IRB LGD input floor for secured and
PARTIALLY secured exposures is the Art. 230/231 LGD* blend, not a flat 25%.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> IRBCalculator
        -> OutputAggregator

Key responsibilities:
- Prove that a corporate A-IRB exposure whose funded credit protection IS taken
  into account is floored on the EAD-weighted blend of the 25% substituted LGDU
  and the per-collateral-type LGDS values (0% / 10% / 10% / 15%), for every
  collateral type in the Art. 231 waterfall.
- Prove the Art. 161(5)(a) limb is untouched: with NO recognised collateral the
  floor stays a flat 25%.

Regulatory basis (PS1/26 Appendix 1, Article 161(5), page 111 of 492):

    5. An institution using the Advanced IRB Approach shall not, for exposures
       to corporates and institutions, ... use LGD values as inputs to the risk
       weight and expected loss formulae that are less than the following LGD
       input floor values:
       (a) a flat 25% floor value for unsecured exposures to corporates and for
           exposures where the institution chooses not to take into account
           funded credit protection covering that exposure;
       (b) for secured and partially secured exposures where the institution
           chooses to take into account funded credit protection covering the
           exposure:
           (i)  in the case of a single type of collateral, a variable LGD input
                floor value equal to the value of LGD* in ... Article 230; or
           (ii) in the case of multiple types of collateral, ... Article 231,
           ... the institution shall substitute:
           (iii) 25% for LGDU; and
           (iv) the following values for LGDS or LGDSi as applicable:
                (1) 0% for financial collateral;
                (2) 10% for receivables;
                (3) 10% for immovable property;
                (4) 15% for other physical collateral.

    Art. 230(1): LGD* = LGDU x (EU / (E x (1 + HE))) + LGDS x (ES / (E x (1 + HE)))

Defect under test (pre-fix):
    ``engine/irb/formulas.py::_lgd_floor_blended_expression`` gated the LGD*
    blend to ``retail_other`` / ``retail_qrre`` only, so every corporate and
    institution A-IRB row fell through to the flat unsecured floor irrespective
    of recognised collateral — all four exposures below were floored at 25%
    and produced an identical RWA of 6,734,189.18.

References:
    - PRA PS1/26 Art. 161(5)(a)/(b): the two limbs pinned here.
    - PRA PS1/26 Art. 230(1)/(2): LGD* formula and the LGDS / HC = 40% table.
    - PRA PS1/26 Art. 231(1): the multi-collateral summation form.
    - BCBS CRE32.17: equivalent Basel 3.1 reference.
    - tests/unit/test_lgd_floor_blended.py: expression-level coverage.
"""

from __future__ import annotations

import math
from datetime import date
from statistics import NormalDist
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 1)
_MATURITY_DATE = date(2030, 1, 1)  # M = 3.0y exactly

EAD: float = 10_000_000.0
OWN_PD: float = 0.02  # above the B31 corporate 0.05% PD floor -> pd_floored = PD
OWN_LGD: float = 0.05  # deliberately below every candidate floor
# > GBP 44m so the row is CORPORATE (not CORPORATE_SME), < GBP 440m so
# Art. 147A(1)(d) leaves A-IRB permission intact.
ANNUAL_REVENUE: float = 100_000_000.0

# Art. 161(5)(b)(iii)/(iv) substituted floor parameters.
LGDU: float = 0.25
LGDS_FINANCIAL: float = 0.00
LGDS_IMMOVABLE: float = 0.10
LGDS_OTHER_PHYSICAL: float = 0.15

# Art. 230(2) volatility adjustment on non-financial collateral.
HC_NON_FINANCIAL: float = 0.40


# ---------------------------------------------------------------------------
# Independent hand-calc (stdlib NormalDist — not the engine's stats backend)
# ---------------------------------------------------------------------------


def _expected_rwa(lgd: float, *, maturity: float = 3.0, ead: float = EAD) -> float:
    """RWA for the shared corporate A-IRB row at a given floored LGD.

    Reproduces CRR/PS1-26 Art. 153(1) from first principles so the expected
    numbers do not borrow the engine's own correlation / K / MA code:

        R   = 0.12 x f(PD) + 0.24 x (1 - f(PD)),  f(PD) = (1-e^-50PD)/(1-e^-50)
        K   = LGD x N[ (1-R)^-0.5 G(PD) + (R/(1-R))^0.5 G(0.999) ] - PD x LGD
        b   = (0.11852 - 0.05478 ln PD)^2
        MA  = (1 + (M - 2.5) b) / (1 - 1.5 b)
        RWA = K x 12.5 x 1.0 x EAD x MA        (B31 scaling factor = 1.0)
    """
    nd = NormalDist()
    f_pd = (1.0 - math.exp(-50.0 * OWN_PD)) / (1.0 - math.exp(-50.0))
    r = 0.12 * f_pd + 0.24 * (1.0 - f_pd)
    inner = math.sqrt(1.0 / (1.0 - r)) * nd.inv_cdf(OWN_PD) + math.sqrt(r / (1.0 - r)) * nd.inv_cdf(
        0.999
    )
    k = lgd * nd.cdf(inner) - OWN_PD * lgd
    b = (0.11852 - 0.05478 * math.log(OWN_PD)) ** 2
    ma = (1.0 + (maturity - 2.5) * b) / (1.0 - 1.5 * b)
    return k * 12.5 * 1.0 * ead * ma


def _blend(secured: float, lgds: float) -> float:
    """Art. 230(1) LGD* with the Art. 161(5)(b) substituted parameters."""
    return LGDU * ((EAD - secured) / EAD) + lgds * (secured / EAD)


# Recognised collateral (ES) per scenario. Financial collateral takes its own
# volatility adjustment (zero for GBP cash against a GBP exposure); the two
# non-financial types take the flat Art. 230(2) HC = 40%.
_ES_CASH: float = 4_000_000.0
_ES_NON_FINANCIAL: float = 10_000_000.0 * (1.0 - HC_NON_FINANCIAL)  # 6,000,000

EXPECTED_FLOOR: dict[str, float] = {
    # 0.6 x 25% + 0.4 x 0%  = 15%
    "L-CASH": _blend(_ES_CASH, LGDS_FINANCIAL),
    # 0.4 x 25% + 0.6 x 15% = 19%
    "L-OPHYS": _blend(_ES_NON_FINANCIAL, LGDS_OTHER_PHYSICAL),
    # 0.4 x 25% + 0.6 x 10% = 16%
    "L-RE": _blend(_ES_NON_FINANCIAL, LGDS_IMMOVABLE),
    # Art. 161(5)(a): nothing recognised -> flat 25%
    "L-UNSEC": LGDU,
}

# The single pre-fix answer every scenario collapsed onto.
PRE_FIX_FLOOR: float = 0.25
PRE_FIX_RWA: float = _expected_rwa(PRE_FIX_FLOOR)

# The floor a naive "use the collateral-type LGDS" fix would produce — the
# blend must land strictly between this and the flat unsecured floor.
SINGLE_TYPE_FLOOR: dict[str, float] = {
    "L-CASH": LGDS_FINANCIAL,
    "L-OPHYS": LGDS_OTHER_PHYSICAL,
    "L-RE": LGDS_IMMOVABLE,
}

# ---------------------------------------------------------------------------
# Art. 230(1) exposure basis: E' = E x (1 + HE) with E = the CCF=100% value
# ---------------------------------------------------------------------------
# An undrawn committed facility separates the two candidate denominators: the
# Art. 223(4) CRM basis E is the full 1,000,000 nominal, while the post-CCF EAD
# is only 400,000. Every LGDS sits below every LGDU, so where the recognised
# collateral fits inside the post-CCF EAD — as the 200,000 cash below does —
# weighting the secured share by that smaller basis *lowers* the floor beneath
# the article: the pre-fix engine returned 12.5% here against the mandated 20%.
# (The old denominator erred in both directions; above the post-CCF EAD the
# unsecured weight clipped to zero and the floor came out too HIGH instead —
# neither is a convex combination. tests/unit/test_lgd_floor_blended.py::
# TestArt2301ExposureBasisDenominator pins both regimes.)
UNDRAWN_REF: str = "F-L-UNDR_UNDRAWN"
UNDRAWN_LIMIT: float = 1_000_000.0
UNDRAWN_CCF: float = 0.40  # PS1/26 Art. 111(1) Table A1 Row 5 — risk_type "OC"
UNDRAWN_EAD_GROSS: float = UNDRAWN_LIMIT * UNDRAWN_CCF  # 400,000
UNDRAWN_CASH: float = 200_000.0  # GBP cash: HC = 0, so ES = market value
UNDRAWN_HE: float = 0.0  # not an SFT — no exposure-side volatility haircut

# LGD* = LGDU x EU / (E x (1 + HE)) + LGDS x ES / (E x (1 + HE))
#      = 25% x 800,000/1,000,000 + 0% x 200,000/1,000,000 = 20%
EXPECTED_UNDRAWN_FLOOR: float = LGDU * (
    (UNDRAWN_LIMIT * (1.0 + UNDRAWN_HE) - UNDRAWN_CASH) / (UNDRAWN_LIMIT * (1.0 + UNDRAWN_HE))
) + LGDS_FINANCIAL * (UNDRAWN_CASH / (UNDRAWN_LIMIT * (1.0 + UNDRAWN_HE)))

# What the pre-fix ead_gross denominator produced: 25% x 200,000/400,000.
PRE_FIX_UNDRAWN_FLOOR: float = LGDU * (
    (UNDRAWN_EAD_GROSS - UNDRAWN_CASH) / UNDRAWN_EAD_GROSS
) + LGDS_FINANCIAL * (UNDRAWN_CASH / UNDRAWN_EAD_GROSS)


# ---------------------------------------------------------------------------
# Fixture construction (in-memory, no parquet)
# ---------------------------------------------------------------------------

# label -> (collateral_type, market_value, is_eligible_financial_collateral)
_SCENARIOS: tuple[tuple[str, str | None, float, bool], ...] = (
    ("L-CASH", "cash", 4_000_000.0, True),
    ("L-OPHYS", "equipment", 10_000_000.0, False),
    ("L-RE", "real_estate", 10_000_000.0, False),
    ("L-UNSEC", None, 0.0, False),
)

_MODEL_ID = "P1248-CORP-AIRB"

_FACILITY_MAPPING_SCHEMA = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,
}


def _build_bundle() -> RawDataBundle:
    """One corporate A-IRB loan per scenario, each with its own counterparty.

    ``has_sufficient_collateral_data=True`` on the loan plus
    ``is_airb_model_collateral=True`` on the collateral is what makes the firm
    "choose to take into account funded credit protection" for an A-IRB row
    under the LGD-modelling method — i.e. the Art. 161(5)(b) limb. L-UNSEC has
    no collateral row at all and therefore sits on the Art. 161(5)(a) limb.
    """
    counterparties, facilities, loans, collateral, ratings = [], [], [], [], []
    for label, coll_type, market_value, is_financial in _SCENARIOS:
        counterparties.append(
            {
                "counterparty_reference": f"CP-{label}",
                "counterparty_name": f"P1.248 A-IRB Corporate ({label})",
                "entity_type": "corporate",
                "country_code": "GB",
                "default_status": False,
                "is_financial_sector_entity": False,
                "apply_fi_scalar": False,
                "annual_revenue": ANNUAL_REVENUE,
            }
        )
        facilities.append(
            {
                "facility_reference": f"F-{label}",
                "counterparty_reference": f"CP-{label}",
                "currency": "GBP",
                "value_date": _REPORTING_DATE,
                "maturity_date": _MATURITY_DATE,
                "limit": EAD,
                "committed": True,
                "seniority": "senior",
                "risk_type": "funded",
            }
        )
        loans.append(
            {
                "loan_reference": label,
                "counterparty_reference": f"CP-{label}",
                "currency": "GBP",
                "value_date": _REPORTING_DATE,
                "maturity_date": _MATURITY_DATE,
                "drawn_amount": EAD,
                "interest": 0.0,
                "seniority": "senior",
                "lgd": OWN_LGD,
                "has_sufficient_collateral_data": True,
            }
        )
        ratings.append(
            {
                "rating_reference": f"RTG-{label}",
                "counterparty_reference": f"CP-{label}",
                "rating_type": "internal",
                "pd": OWN_PD,
                "model_id": _MODEL_ID,
                "rating_date": _REPORTING_DATE,
            }
        )
        if coll_type is None:
            continue
        collateral.append(
            {
                "collateral_reference": f"C-{label}",
                "collateral_type": coll_type,
                "currency": "GBP",
                "market_value": market_value,
                "beneficiary_type": "loan",
                "beneficiary_reference": label,
                "is_eligible_financial_collateral": is_financial,
                # Art. 199(2)/(5)/(6) attestation — without it the FCM
                # eligibility gate zeroes non-financial collateral.
                "is_eligible_irb_collateral": True,
                "is_airb_model_collateral": True,
                "property_type": "commercial" if coll_type == "real_estate" else None,
            }
        )

    # Art. 230(1) denominator scenario: a wholly undrawn committed facility, so
    # the synthetic F-L-UNDR_UNDRAWN row carries nominal 1,000,000 at CCF 40%
    # (ead_gross 400,000, ead_for_crm 1,000,000). The facility itself carries the
    # A-IRB own LGD and the collateral-data attestation, exactly as the drawn
    # loans above do — no loan row exists, so the whole limit is headroom.
    counterparties.append(
        {
            "counterparty_reference": "CP-L-UNDR",
            "counterparty_name": "P1.248 A-IRB Corporate (undrawn commitment)",
            "entity_type": "corporate",
            "country_code": "GB",
            "default_status": False,
            "is_financial_sector_entity": False,
            "apply_fi_scalar": False,
            "annual_revenue": ANNUAL_REVENUE,
        }
    )
    facilities.append(
        {
            "facility_reference": "F-L-UNDR",
            "counterparty_reference": "CP-L-UNDR",
            "currency": "GBP",
            "value_date": _REPORTING_DATE,
            "maturity_date": _MATURITY_DATE,
            "limit": UNDRAWN_LIMIT,
            "committed": True,
            "seniority": "senior",
            # PS1/26 Art. 111(1) Table A1 Row 5 "other commitments" -> CCF 40%.
            "risk_type": "OC",
            "lgd": OWN_LGD,
            "has_sufficient_collateral_data": True,
        }
    )
    ratings.append(
        {
            "rating_reference": "RTG-L-UNDR",
            "counterparty_reference": "CP-L-UNDR",
            "rating_type": "internal",
            "pd": OWN_PD,
            "model_id": _MODEL_ID,
            "rating_date": _REPORTING_DATE,
        }
    )
    collateral.append(
        {
            "collateral_reference": "C-L-UNDR",
            "collateral_type": "cash",
            "currency": "GBP",
            "market_value": UNDRAWN_CASH,
            # Pledged at the facility, which is where the undrawn row lives.
            "beneficiary_type": "facility",
            "beneficiary_reference": "F-L-UNDR",
            "is_eligible_financial_collateral": True,
            "is_eligible_irb_collateral": True,
            "is_airb_model_collateral": True,
            "property_type": None,
        }
    )

    collateral_df = pl.DataFrame(collateral, schema=dtypes_of(COLLATERAL_SCHEMA)).with_columns(
        # No Art. 237-239 maturity mismatch.
        pl.Series("original_maturity_years", [10.0] * len(collateral), dtype=pl.Float64)
    )

    return make_raw_bundle(
        facilities=pl.DataFrame(facilities, schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(loans, schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.DataFrame(counterparties, schema=dtypes_of(COUNTERPARTY_SCHEMA)),
        facility_mappings=pl.LazyFrame(schema=_FACILITY_MAPPING_SCHEMA),
        collateral=collateral_df,
        ratings=pl.DataFrame(ratings, schema=dtypes_of(RATINGS_SCHEMA)),
        model_permissions=pl.DataFrame(
            [
                {
                    "model_id": _MODEL_ID,
                    "exposure_class": "corporate",
                    "approach": "advanced_irb",
                    "country_codes": None,
                    "excluded_book_codes": None,
                }
            ],
            schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
        ),
    )


# ---------------------------------------------------------------------------
# P1.248 acceptance tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def irb_rows() -> dict[str, dict]:
    """Basel 3.1 A-IRB results keyed by exposure_reference."""
    results: AggregatedResultBundle = PipelineOrchestrator().run_with_data(
        _build_bundle(),
        CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        ),
    )
    assert results.irb_results is not None, (
        "IRB results must not be None — check PermissionMode.IRB and the "
        "advanced_irb model permission"
    )
    rows = {row["exposure_reference"]: row for row in results.irb_results.collect().to_dicts()}
    assert set(rows) == {label for label, *_ in _SCENARIOS} | {UNDRAWN_REF}, (
        f"Expected one A-IRB row per scenario plus the undrawn commitment row, got {sorted(rows)}"
    )
    return rows


class TestP1248Art1615PartiallySecuredLGDFloor:
    """PS1/26 Art. 161(5)(b): corporate A-IRB LGD floor is the LGD* blend."""

    @pytest.mark.parametrize("label", ["L-CASH", "L-OPHYS", "L-RE", "L-UNSEC"])
    def test_row_is_airb_with_expected_collateral_recognised(
        self, irb_rows: dict[str, dict], label: str
    ) -> None:
        """
        Guard: each row really is A-IRB and really recognised the collateral.

        Arrange: the four-scenario book.
        Act:     read is_airb and total_collateral_for_lgd.
        Assert:  A-IRB, and ES matches the Art. 230(2) hand-calc — so a later
                 failure is a floor defect, not a routing or CRM defect.
        """
        row = irb_rows[label]
        expected_es = {
            "L-CASH": _ES_CASH,
            "L-OPHYS": _ES_NON_FINANCIAL,
            "L-RE": _ES_NON_FINANCIAL,
            "L-UNSEC": 0.0,
        }[label]

        assert row["is_airb"] is True, (
            f"{label} must route to A-IRB, got approach={row['approach']}"
        )
        assert row["total_collateral_for_lgd"] == pytest.approx(expected_es), (
            f"{label}: recognised collateral (ES) must be {expected_es:,.0f} "
            f"per Art. 230(2) (HC=40% on non-financial), got "
            f"{row['total_collateral_for_lgd']:,.2f}"
        )

    @pytest.mark.parametrize("label", ["L-CASH", "L-OPHYS", "L-RE"])
    def test_partially_secured_corporate_floored_on_lgd_star_blend(
        self, irb_rows: dict[str, dict], label: str
    ) -> None:
        """
        Art. 161(5)(b): the floor is the EAD-weighted LGD* blend.

        Arrange: corporate A-IRB, EAD 10m, own LGD 5%, one collateral type
                 recognised inside the A-IRB model.
        Act:     read lgd_floored off the B31 pipeline.
        Assert:  lgd_floored equals LGDU x EU/E + LGDS x ES/E with LGDU = 25%
                 (Art. 161(5)(b)(iii)) and the Art. 161(5)(b)(iv) LGDS.
        """
        expected = EXPECTED_FLOOR[label]
        actual = irb_rows[label]["lgd_floored"]

        assert actual == pytest.approx(expected, rel=1e-12), (
            f"{label}: Art. 161(5)(b) floor must be the LGD* blend "
            f"{expected:.4f} (LGDU 25% on the unsecured portion + LGDS on the "
            f"secured portion), got {actual:.6f}"
        )

    @pytest.mark.parametrize("label", ["L-CASH", "L-OPHYS", "L-RE"])
    def test_blend_is_neither_the_flat_floor_nor_the_single_type_floor(
        self, irb_rows: dict[str, dict], label: str
    ) -> None:
        """
        Anti-confound: the blend is strictly between both wrong answers.

        Arrange: the same three partially secured rows.
        Act:     compare lgd_floored against the flat 25% (the pre-fix value)
                 and against the bare collateral-type LGDS.
        Assert:  strictly less than 25% and strictly greater than the LGDS —
                 so neither "leave it flat" nor "swap in the secured-type
                 floor" can make this test pass.
        """
        actual = irb_rows[label]["lgd_floored"]

        assert actual < PRE_FIX_FLOOR, (
            f"{label}: partially secured floor must be below the flat "
            f"unsecured {PRE_FIX_FLOOR:.0%} (Art. 161(5)(a) applies only where "
            f"the firm does NOT take the protection into account), got {actual:.6f}"
        )
        assert actual > SINGLE_TYPE_FLOOR[label], (
            f"{label}: partially secured floor must exceed the bare "
            f"collateral-type LGDS {SINGLE_TYPE_FLOOR[label]:.0%} — the "
            f"unsecured remainder carries LGDU 25%, got {actual:.6f}"
        )

    @pytest.mark.parametrize("label", ["L-CASH", "L-OPHYS", "L-RE"])
    def test_partially_secured_rwa_matches_hand_calc(
        self, irb_rows: dict[str, dict], label: str
    ) -> None:
        """
        The floor change flows through to capital.

        Arrange: the same three partially secured rows.
        Act:     read rwa.
        Assert:  matches the independent Art. 153(1) hand-calc at the blended
                 LGD, and is NOT the pre-fix 6,734,189.18 that all four rows
                 shared when every corporate was floored flat at 25%.
        """
        expected = _expected_rwa(EXPECTED_FLOOR[label])
        actual = irb_rows[label]["rwa"]

        assert actual == pytest.approx(expected, rel=1e-8), (
            f"{label}: RWA must be {expected:,.2f} at the blended floor "
            f"{EXPECTED_FLOOR[label]:.4f}, got {actual:,.2f}"
        )
        assert actual != pytest.approx(PRE_FIX_RWA, rel=1e-8), (
            f"{label}: RWA must have moved off the pre-fix flat-25% value {PRE_FIX_RWA:,.2f}"
        )

    def test_unsecured_corporate_keeps_flat_25pct_floor(self, irb_rows: dict[str, dict]) -> None:
        """
        Art. 161(5)(a) negative control: no recognised protection, no blend.

        Arrange: identical corporate A-IRB row with no collateral at all.
        Act:     read lgd_floored and rwa.
        Assert:  still the flat 25% floor and the unchanged 6,734,189.18 RWA —
                 the Art. 161(5)(b) blend must not leak onto the (a) limb.
        """
        row = irb_rows["L-UNSEC"]

        assert row["lgd_floored"] == pytest.approx(LGDU, rel=1e-12), (
            f"L-UNSEC: Art. 161(5)(a) flat {LGDU:.0%} floor must be unchanged, "
            f"got {row['lgd_floored']:.6f}"
        )
        assert row["rwa"] == pytest.approx(PRE_FIX_RWA, rel=1e-8), (
            f"L-UNSEC: RWA must stay at {PRE_FIX_RWA:,.2f}, got {row['rwa']:,.2f}"
        )


class TestP1248Art2301ExposureBasisIsPreCCF:
    """PS1/26 Art. 230(1): LGD* divides by E x (1 + HE), E = the CCF=100% value.

    The Art. 161(5)(b) blend inherits the Art. 230(1) denominator, and
    Art. 223(4) fixes E at 100% of nominal for off-balance-sheet items. A
    partially collateralised undrawn commitment is the only shape that separates
    that basis from the post-CCF ``ead_gross``; because every substituted LGDS
    lies below LGDU, the smaller divisor understates the floor.
    """

    def test_undrawn_row_shape_is_as_designed(self, irb_rows: dict[str, dict]) -> None:
        """
        Guard: the row really is an A-IRB commitment with CCF < 100%.

        Arrange: the wholly undrawn 1,000,000 committed facility.
        Act:     read approach / CCF / both EAD bases / recognised collateral.
        Assert:  A-IRB, CCF 40%, ead_gross 400,000 vs ead_for_crm 1,000,000,
                 HE = 0 and ES = 200,000 — so a floor failure below is a
                 denominator defect, not a CCF, CRM or routing defect.
        """
        row = irb_rows[UNDRAWN_REF]

        assert row["is_airb"] is True, (
            f"{UNDRAWN_REF} must route to A-IRB, got approach={row['approach']}"
        )
        assert row["ccf"] == pytest.approx(UNDRAWN_CCF), (
            f"CCF must be the Table A1 Row 5 {UNDRAWN_CCF:.0%} for risk_type 'OC', got {row['ccf']}"
        )
        assert row["ead_gross"] == pytest.approx(UNDRAWN_EAD_GROSS), (
            f"post-CCF ead_gross must be {UNDRAWN_EAD_GROSS:,.0f}, got {row['ead_gross']:,.2f}"
        )
        assert row["ead_for_crm"] == pytest.approx(UNDRAWN_LIMIT), (
            f"Art. 223(4) CRM basis must be the full {UNDRAWN_LIMIT:,.0f} nominal, "
            f"got {row['ead_for_crm']:,.2f}"
        )
        assert row["exposure_volatility_haircut"] == pytest.approx(UNDRAWN_HE), (
            f"a lending commitment carries no Art. 223(5) exposure haircut, "
            f"got {row['exposure_volatility_haircut']}"
        )
        assert row["total_collateral_for_lgd"] == pytest.approx(UNDRAWN_CASH), (
            f"ES must be the full {UNDRAWN_CASH:,.0f} GBP cash (HC = 0), "
            f"got {row['total_collateral_for_lgd']:,.2f}"
        )

    def test_floor_divides_by_the_pre_ccf_basis(self, irb_rows: dict[str, dict]) -> None:
        """
        Art. 230(1): the secured share is ES / (E x (1 + HE)), not ES / EAD.

        Arrange: the undrawn commitment — E = 1,000,000, ES = 200,000 cash.
        Act:     read lgd_floored.
        Assert:  20.0% = 25% x 800,000/1,000,000 + 0% x 200,000/1,000,000.
        """
        actual = irb_rows[UNDRAWN_REF]["lgd_floored"]

        assert actual == pytest.approx(EXPECTED_UNDRAWN_FLOOR, rel=1e-12), (
            f"Art. 230(1) floor must be {EXPECTED_UNDRAWN_FLOOR:.4f} on the "
            f"{UNDRAWN_LIMIT:,.0f} pre-CCF basis, got {actual:.6f}"
        )

    def test_floor_is_not_the_post_ccf_under_floor(self, irb_rows: dict[str, dict]) -> None:
        """
        Anti-confound: not the pre-fix ead_gross answer, not the flat limb.

        Arrange: the same undrawn commitment.
        Act:     read lgd_floored.
        Assert:  strictly above the 12.5% the post-CCF denominator produced —
                 the defect was anti-conservative, so a silent revert cannot
                 pass — and strictly below the 25% flat (a) limb, which a
                 "give up and use LGDU" fix would produce.
        """
        actual = irb_rows[UNDRAWN_REF]["lgd_floored"]

        assert actual != pytest.approx(PRE_FIX_UNDRAWN_FLOOR, rel=1e-9), (
            f"floor must have moved off the pre-fix post-CCF value "
            f"{PRE_FIX_UNDRAWN_FLOOR:.4f}, got {actual:.6f}"
        )
        assert actual > PRE_FIX_UNDRAWN_FLOOR, (
            f"the post-CCF denominator was anti-conservative: the corrected floor "
            f"must exceed {PRE_FIX_UNDRAWN_FLOOR:.4f}, got {actual:.6f}"
        )
        assert actual < LGDU, (
            f"floor must stay below the flat {LGDU:.0%} — 20% of the basis is "
            f"secured by cash, got {actual:.6f}"
        )

    def test_undrawn_rwa_matches_hand_calc(self, irb_rows: dict[str, dict]) -> None:
        """
        The corrected floor flows through to capital on the post-CCF EAD.

        Arrange: the same undrawn commitment (EAD = 400,000 post-CCF).
        Act:     read rwa.
        Assert:  matches the independent Art. 153(1) hand-calc at LGD = 20% and
                 exceeds the RWA the pre-fix 12.5% floor produced — the fix
                 raises capital, as an anti-conservative defect must.
        """
        expected = _expected_rwa(EXPECTED_UNDRAWN_FLOOR, ead=UNDRAWN_EAD_GROSS)
        pre_fix = _expected_rwa(PRE_FIX_UNDRAWN_FLOOR, ead=UNDRAWN_EAD_GROSS)
        actual = irb_rows[UNDRAWN_REF]["rwa"]

        assert actual == pytest.approx(expected, rel=1e-8), (
            f"{UNDRAWN_REF}: RWA must be {expected:,.2f} at the {EXPECTED_UNDRAWN_FLOOR:.4f} "
            f"floor on EAD {UNDRAWN_EAD_GROSS:,.0f}, got {actual:,.2f}"
        )
        assert actual > pre_fix, (
            f"{UNDRAWN_REF}: RWA must exceed the pre-fix {pre_fix:,.2f} — the "
            f"under-floor understated capital"
        )
