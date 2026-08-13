"""
P1.294: CRR Art. 124(1) — the RRE excess takes the OBLIGOR's unsecured RW.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> RealEstateSplitter -> SACalculator -> Aggregator

Key responsibilities:
- Pin the whole-loan Art. 125 blend's residual leg to the counterparty's own
  unsecured risk weight, across every obligor type, in both directions.
- Prove the retail limb does NOT move (a naive 75% -> 100% swap breaks it).
- Prove the already-correct RE-splitter path does NOT move (a fix must not
  double-apply Art. 124(1)).

The rule, verbatim (CRR Art. 124(1), first sub-paragraph, second sentence):

    "The part of the exposure that exceeds the mortgage value of the immovable
    property shall be assigned the risk weight applicable to the unsecured
    exposures of the counterparty involved."

That is an OPEN REFERRAL to the obligor's own class ladder, not a 75%/100%
binary. Art. 125 itself contains no 75% and no 100% — it sets only the 35%
weight and the Art. 125(2)(d) 80% limit. The 75% seen in the engine today is
Art. 124(1)'s referral composed with Art. 123's regulatory-retail weight, and
it is applied unconditionally: ``risk_weights.py::_crr_append_real_estate_
branches`` blends the above-80%-LTV excess at a flat ``resi_rw_high`` (0.75)
with no obligor input at all.

Hand-calculation (EAD 1,000,000, LTV 1.00, so secured share = 0.80/1.00):

    blended_rw = 0.35 x 0.80 + X x 0.20 = 0.28 + 0.20X

where X is the Art. 124(1) unsecured RW of the counterparty:

    | obligor                             | X    | blended RW | RWA     |
    |-------------------------------------|------|------------|---------|
    | retail qualifying (Art. 123)        | 0.75 | 0.4300     | 430,000 |
    | natural person failing Art. 123     | 1.00 | 0.4800     | 480,000 |
    | corporate CQS 1 (Art. 122 Table 6)  | 0.20 | 0.3200     | 320,000 |
    | corporate CQS 2                     | 0.50 | 0.3800     | 380,000 |
    | corporate CQS 3                     | 1.00 | 0.4800     | 480,000 |
    | corporate CQS 4                     | 1.00 | 0.4800     | 480,000 |
    | corporate CQS 5                     | 1.50 | 0.5800     | 580,000 |
    | corporate CQS 6                     | 1.50 | 0.5800     | 580,000 |

MEASURED pre-fix: the engine returns 0.4300 / 430,000 for EVERY row above —
verified invariant across ``qualifies_as_retail`` in {True, False} and ``cqs``
in {null, 1..6}. So the retail row is already right and two rows (CQS 1, CQS 2)
move capital DOWN; those two need their own RWA-reduction sign-off.

Cross-path identity (the discriminating measurement): the RE splitter already
implements Art. 124(1) correctly, and the CRR RRE split cap equals the Art. 125
LTV threshold (both 0.80, ``re_split_rre_secured_ltv_cap`` / ``residential_
mortgage_params``). A whole-loan blend and a loan-split of the same exposure
must therefore agree exactly. Today they do not: 430,000 whole-loan against
580,000 split for the same CQS-6 corporate — a 150,000 gap. That gap is the
defect, measured, and it must close to 0.00.

References:
- CRR Art. 124(1) first sub-paragraph, second sentence: excess takes the
  counterparty's unsecured RW (docs/assets/crr.pdf PAGE_INDEX 121)
- CRR Art. 125(2)(d): the 80% limit on the preferential 35% weight
- CRR Art. 122 Table 6: corporate RW by CQS (pack ``corporate_risk_weights``)
- CRR Art. 123: regulatory retail 75% (pack ``retail_risk_weight``)
- tests/oracle/derivations/sa_crr.py ORC-029: the retail limb's oracle anchor,
  shadowed here so a fix cannot break it silently
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CQS, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa.crr_risk_weight_tables import CORPORATE_RISK_WEIGHTS

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_EAD = Decimal("1000000")
_HIGH_LTV = Decimal("1.00")  # excess share = 0.20
_LOW_LTV = Decimal("0.60")  # wholly inside the Art. 125(2)(d) 80% limit

# CRR Art. 125(2)(d) / pack ``residential_mortgage_params``.
_SECURED_RW = 0.35
_LTV_THRESHOLD = 0.80

# CRR Art. 123 / pack ``retail_risk_weight``.
_RETAIL_UNSECURED_RW = 0.75

# The single value the engine returns today for every obligor type.
_PRE_FIX_RW = 0.43
_PRE_FIX_RWA = 430_000.0

_RW_TOL = 1e-6
_RWA_TOL = 0.01

_CRR_DATE = date(2024, 12, 31)
_B31_DATE = date(2027, 6, 30)


def _blended(unsecured_rw: float) -> float:
    """Art. 125(2)(d) + Art. 124(1) blend at LTV 1.00: 0.28 + 0.20 x X."""
    return _SECURED_RW * _LTV_THRESHOLD + unsecured_rw * (1.0 - _LTV_THRESHOLD)


# (case_id, obligor kwargs, Art. 124(1) unsecured RW X)
_OBLIGOR_LADDER: list[tuple[str, dict, float]] = [
    (
        "retail_qualifying",
        {"qualifies_as_retail": True, "cp_is_natural_person": True, "cqs": None},
        _RETAIL_UNSECURED_RW,
    ),
    (
        "natural_person_failing_art_123",
        {"qualifies_as_retail": False, "cp_is_natural_person": True, "cqs": None},
        1.00,
    ),
    (
        "corporate_cqs1",
        {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 1},
        0.20,
    ),
    (
        "corporate_cqs2",
        {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 2},
        0.50,
    ),
    (
        "corporate_cqs3",
        {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 3},
        1.00,
    ),
    (
        "corporate_cqs4",
        {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 4},
        1.00,
    ),
    (
        "corporate_cqs5",
        {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 5},
        1.50,
    ),
    (
        "corporate_cqs6",
        {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 6},
        1.50,
    ),
]

_LADDER_PARAMS = [pytest.param(kwargs, x, id=case_id) for case_id, kwargs, x in _OBLIGOR_LADDER]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sa_calculator() -> SACalculator:
    """SA calculator instance shared by the whole-loan cases."""
    return SACalculator()


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    """CRR configuration — the regime the defect lives in."""
    return CalculationConfig.crr(reporting_date=_CRR_DATE)


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration — the invariance control arm."""
    return CalculationConfig.basel_3_1(reporting_date=_B31_DATE)


# ---------------------------------------------------------------------------
# The whole-loan obligor ladder — the defect
# ---------------------------------------------------------------------------


class TestP1294WholeLoanObligorLadder:
    """CRR Art. 124(1): the above-80%-LTV excess follows the obligor's ladder.

    The whole-loan path (a row already classified ``residential_mortgage``,
    which ``re_split/flagging.py`` deliberately excludes from the splitter) is
    the ONLY place the defect lives. Every case here is the same exposure with
    the same LTV — only the counterparty changes — so any surviving invariance
    across the parametrisation is the defect itself.
    """

    @pytest.mark.parametrize(("obligor", "unsecured_rw"), _LADDER_PARAMS)
    def test_p1_294_whole_loan_excess_takes_obligor_unsecured_rw(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        obligor: dict,
        unsecured_rw: float,
    ) -> None:
        """The blended RW is 0.28 + 0.20 x (the obligor's unsecured RW).

        Arrange: residential_mortgage, EAD 1,000,000, LTV 1.00, one obligor.
        Act:     SACalculator.calculate_branch under CRR.
        Assert:  risk_weight == 0.35x0.80 + X x 0.20 for that obligor's X.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_HIGH_LTV,
            config=crr_config,
            **obligor,
        )

        # Assert — the cell is emitted at all, and carries a number
        assert result["risk_weight"] is not None, (
            "P1.294: risk_weight is null for a residential_mortgage row with "
            f"exposure — obligor {obligor}"
        )
        assert result["rwa_final"] is not None, (
            f"P1.294: rwa_final is null for an exposure of {_EAD} — obligor {obligor}"
        )

        # Assert — the Art. 124(1) referral resolved to this obligor's ladder
        expected_rw = _blended(unsecured_rw)
        assert result["risk_weight"] == pytest.approx(expected_rw, rel=_RW_TOL), (
            f"P1.294: expected risk_weight={expected_rw:.4f} "
            f"(0.35x0.80 + {unsecured_rw:.2f}x0.20, CRR Art. 124(1) referral to the "
            f"unsecured RW of {obligor}), got {result['risk_weight']} "
            f"(pre-fix the engine returns {_PRE_FIX_RW} for EVERY obligor)"
        )

    @pytest.mark.parametrize(("obligor", "unsecured_rw"), _LADDER_PARAMS)
    def test_p1_294_whole_loan_rwa_follows_the_blend(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        obligor: dict,
        unsecured_rw: float,
    ) -> None:
        """RWA = 1,000,000 x the blended RW, absolute — never relative.

        Arrange: residential_mortgage, EAD 1,000,000, LTV 1.00, one obligor.
        Act:     SACalculator.calculate_branch under CRR.
        Assert:  rwa_final equals the hand-calculated absolute figure.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_HIGH_LTV,
            config=crr_config,
            **obligor,
        )

        # Assert
        expected_rwa = float(_EAD) * _blended(unsecured_rw)
        assert result["rwa_final"] == pytest.approx(expected_rwa, abs=_RWA_TOL), (
            f"P1.294: expected rwa_final={expected_rwa:,.2f} for obligor {obligor}, "
            f"got {result['rwa_final']:,.2f} "
            f"(pre-fix the engine returns {_PRE_FIX_RWA:,.2f} for EVERY obligor)"
        )

    def test_p1_294_the_ladder_is_not_invariant_across_obligors(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """The eight obligors must NOT all land on one weight.

        This is the defect stated as a single measurement: today the engine
        returns exactly one distinct risk weight (0.4300) across the whole
        ladder because no obligor column is read at all. Art. 124(1) produces
        four distinct weights — 0.32, 0.38, 0.43, 0.48, 0.58.

        Arrange: the full obligor ladder at LTV 1.00.
        Act:     SACalculator.calculate_branch under CRR, once per obligor.
        Assert:  the set of distinct risk weights has five members.
        """
        # Arrange / Act
        weights = {
            case_id: calculate_single_sa_exposure(
                sa_calculator,
                ead=_EAD,
                exposure_class="residential_mortgage",
                ltv=_HIGH_LTV,
                config=crr_config,
                **kwargs,
            )["risk_weight"]
            for case_id, kwargs, _ in _OBLIGOR_LADDER
        }

        # Assert
        distinct = {round(rw, 6) for rw in weights.values()}
        assert distinct == {0.32, 0.38, 0.43, 0.48, 0.58}, (
            "P1.294: the Art. 124(1) referral must produce five distinct blended "
            f"weights across the obligor ladder, got {sorted(distinct)} from {weights} "
            f"(pre-fix: a single value, {_PRE_FIX_RW})"
        )


# ---------------------------------------------------------------------------
# The limbs that must NOT move
# ---------------------------------------------------------------------------


class TestP1294LimbsThatMustNotMove:
    """Guards bounding the fix on both sides.

    A fix that simply swaps 0.75 for 1.00 breaks the retail limb; a fix that
    routes every obligor through the Art. 122 corporate ladder (the shape of
    the CRE sibling three lines above in ``risk_weights.py``) breaks it a
    different way. Pinning only the RWA-increasing cells would let both
    through.
    """

    def test_p1_294_retail_qualifying_obligor_stays_at_43pct(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """A retail-qualifying obligor's excess stays at Art. 123's 75%.

        Arrange: residential_mortgage, LTV 1.00, natural person meeting
                 Art. 123 (``qualifies_as_retail=True``).
        Act:     SACalculator.calculate_branch under CRR.
        Assert:  risk_weight == 0.43 and rwa_final == 430,000 — unchanged.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_HIGH_LTV,
            config=crr_config,
            qualifies_as_retail=True,
            cp_is_natural_person=True,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(
            _blended(_RETAIL_UNSECURED_RW), rel=_RW_TOL
        ), (
            "P1.294: the Art. 123 retail limb must NOT move — expected "
            f"{_PRE_FIX_RW} (0.35x0.80 + 0.75x0.20), got {result['risk_weight']}"
        )
        assert result["rwa_final"] == pytest.approx(_PRE_FIX_RWA, abs=_RWA_TOL), (
            f"P1.294: retail rwa_final must stay {_PRE_FIX_RWA:,.2f}, "
            f"got {result['rwa_final']:,.2f}"
        )

    def test_p1_294_orc_029_retail_mortgage_shape_stays_at_43pct(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Shadow of oracle case ORC-029, which this fix must leave green.

        ``tests/oracle/derivations/sa_crr.py`` ORC-029 pins 0.43 for
        ``retail_mortgage`` at LTV 1.00 with ``cqs=None``,
        ``cp_is_natural_person=True`` and the driver's ``qualifies_as_retail``
        default of True. The oracle tree is barred to agents, so the same shape
        is asserted here — a fix that reddens ORC-029 reddens this first, in a
        file whose failure message says why.

        Arrange: ORC-029's exact obligor shape, class ``retail_mortgage``.
        Act:     SACalculator.calculate_branch under CRR.
        Assert:  risk_weight == 0.43.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="retail_mortgage",
            ltv=_HIGH_LTV,
            config=crr_config,
            cqs=None,
            cp_is_natural_person=True,
            qualifies_as_retail=True,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(
            _blended(_RETAIL_UNSECURED_RW), rel=_RW_TOL
        ), (
            "P1.294: ORC-029's shape (retail_mortgage, natural person meeting "
            f"Art. 123, LTV 1.00) must stay at {_PRE_FIX_RW} — got "
            f"{result['risk_weight']}. Breaking this breaks the oracle."
        )

    def test_p1_294_a_rated_retail_obligor_still_takes_the_art_123_weight(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Art. 123 precedes Art. 122 even when the row carries a CQS.

        The nearest sibling in ``risk_weights.py`` — the Art. 126 CRE blend —
        resolves its residual through ``CORPORATE_RISK_WEIGHTS`` for every row
        unconditionally. Copying that shape onto RRE would price a retail
        obligor's excess at the corporate CQS-6 weight (1.50 -> 0.58) instead
        of Art. 123's 75%. Art. 123 assigns retail exposures 75% and makes no
        reference to a credit quality step, so the referral resolves to 75%
        whatever rating the row happens to carry.

        Arrange: residential_mortgage, LTV 1.00, qualifying retail, cqs=6.
        Act:     SACalculator.calculate_branch under CRR.
        Assert:  risk_weight == 0.43, NOT the 0.58 corporate CQS-6 blend.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_HIGH_LTV,
            config=crr_config,
            qualifies_as_retail=True,
            cp_is_natural_person=True,
            cqs=6,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(
            _blended(_RETAIL_UNSECURED_RW), rel=_RW_TOL
        ), (
            "P1.294: a rated obligor that still qualifies as regulatory retail "
            f"takes Art. 123's 75% on the excess ({_PRE_FIX_RW} blended), not the "
            f"Art. 122 CQS-6 weight ({_blended(1.50):.4f}) — got {result['risk_weight']}"
        )

    @pytest.mark.parametrize(("obligor", "unsecured_rw"), _LADDER_PARAMS)
    def test_p1_294_low_ltv_stays_at_the_preferential_35pct(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        obligor: dict,
        unsecured_rw: float,
    ) -> None:
        """Below the Art. 125(2)(d) limit there is no excess, for any obligor.

        Art. 124(1) only speaks to "the part of the exposure that exceeds the
        mortgage value". At LTV 0.60 there is no such part, so the obligor's
        unsecured RW is irrelevant and the whole exposure keeps the 35%.

        Arrange: residential_mortgage, LTV 0.60, each obligor in turn.
        Act:     SACalculator.calculate_branch under CRR.
        Assert:  risk_weight == 0.35 regardless of obligor.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_LOW_LTV,
            config=crr_config,
            **obligor,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(_SECURED_RW, rel=_RW_TOL), (
            f"P1.294: LTV {float(_LOW_LTV)} is inside the Art. 125(2)(d) 80% limit, so "
            f"the obligor's unsecured RW ({unsecured_rw:.2f}) must not reach the "
            f"weight — expected {_SECURED_RW}, got {result['risk_weight']}"
        )

    @pytest.mark.parametrize(
        ("obligor", "expected_rw"),
        [
            pytest.param(
                {"qualifies_as_retail": True, "cp_is_natural_person": True, "cqs": None},
                0.4475,
                id="b31_natural_person",
            ),
            pytest.param(
                {"qualifies_as_retail": False, "cp_is_natural_person": False, "cqs": 6},
                0.56,
                id="b31_corporate_cqs6",
            ),
        ],
    )
    def test_p1_294_basel_31_arm_is_unchanged(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        obligor: dict,
        expected_rw: float,
    ) -> None:
        """Basel 3.1 already implements the referral (Art. 124L) — do not touch it.

        ``_b31_art_124l_cp_rw_expr`` resolves the residual leg from a PS1/26
        Art. 124L counterparty-type table whose 85% other-SME band and social-
        housing floor have no CRR equivalent. This control fails if a CRR-side
        change leaks into the Basel 3.1 branch.

        Arrange: residential_mortgage, LTV 1.00, under a Basel 3.1 config.
        Act:     SACalculator.calculate_branch.
        Assert:  the measured pre-change Basel 3.1 weights are unchanged.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_HIGH_LTV,
            config=b31_config,
            **obligor,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(expected_rw, rel=_RW_TOL), (
            f"P1.294: the Basel 3.1 arm must not move — expected {expected_rw} "
            f"(Art. 124F 55% split cap + Art. 124L residual) for {obligor}, "
            f"got {result['risk_weight']}"
        )


# ---------------------------------------------------------------------------
# Scope control: the RE-splitter path is already correct
# ---------------------------------------------------------------------------


def _splitter_bundle(cqs: int) -> RawDataBundle:
    """Corporate obligor rated ``cqs``, GBP 1m loan, GBP 1m residential pledge.

    The row is classified ``corporate`` and carries property collateral, so it
    traverses ``RealEstateSplitter`` (``re_split/flagging.py`` only excludes
    rows already classified as mortgages). The splitter emits a secured leg
    capped at ``re_split_rre_secured_ltv_cap`` (0.80) of the property value and
    a residual leg that keeps the corporate class — which is exactly what
    Art. 124(1) requires, and is why this path must not move.
    """
    empty_facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "limit": pl.Float64,
            "committed": pl.Boolean,
            "lgd": pl.Float64,
            "lgd_unsecured": pl.Float64,
            "has_sufficient_collateral_data": pl.Boolean,
            "beel": pl.Float64,
            "is_revolving": pl.Boolean,
            "is_qrre_transactor": pl.Boolean,
            "seniority": pl.String,
            "risk_type": pl.String,
            "underlying_risk_type": pl.String,
            "ccf_modelled": pl.Float64,
            "ead_modelled": pl.Float64,
            "is_short_term_trade_lc": pl.Boolean,
            "is_payroll_loan": pl.Boolean,
            "is_buy_to_let": pl.Boolean,
            "has_one_day_maturity_floor": pl.Boolean,
            "facility_termination_date": pl.Date,
        }
    )
    return make_raw_bundle(
        counterparties=pl.LazyFrame(
            {
                "counterparty_reference": ["CP-294"],
                "counterparty_name": ["P1.294 Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [200_000_000.0],
                "total_assets": [None],
                "default_status": [False],
                "sector_code": [None],
                "apply_fi_scalar": [None],
                "is_managed_as_retail": [False],
                "is_natural_person": [False],
                "is_social_housing": [False],
                "is_financial_sector_entity": [False],
                "scra_grade": [None],
                "is_investment_grade": [None],
                "is_ccp_client_cleared": [False],
                "borrower_income_currency": [None],
                "sovereign_cqs": [None],
                "local_currency": [None],
                "institution_cqs": [None],
            }
        ),
        facilities=empty_facilities,
        loans=pl.LazyFrame(
            {
                "loan_reference": ["LN-294"],
                "product_type": ["term_loan"],
                "book_code": ["BANK"],
                "counterparty_reference": ["CP-294"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "drawn_amount": [float(_EAD)],
                "interest": [0.0],
                "lgd": [0.45],
                "lgd_unsecured": [0.45],
                "has_sufficient_collateral_data": [True],
                "beel": [None],
                "seniority": ["senior"],
                "is_payroll_loan": [False],
                "is_buy_to_let": [False],
                "has_one_day_maturity_floor": [False],
                "netting_agreement_reference": [None],
                "due_diligence_performed": [None],
                "due_diligence_override_rw": [None],
            }
        ),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.LazyFrame(
            {
                "rating_reference": ["RT-294"],
                "counterparty_reference": ["CP-294"],
                "rating_type": ["external"],
                "rating_agency": ["S&P"],
                "rating_value": ["CCC"],
                "cqs": [cqs],
                "pd": [None],
                "rating_date": [date(2024, 1, 1)],
                "is_solicited": [True],
                "model_id": [None],
                "is_short_term": [False],
                "scope_type": [None],
                "scope_id": [None],
                "rating_is_issue_specific": [False],
                "rating_is_inferred": [False],
                "internal_rating_grade": [None],
            },
            schema_overrides={"cqs": pl.Int8},
        ),
        collateral=pl.LazyFrame(
            {
                "collateral_reference": ["CL-294"],
                "collateral_type": ["real_estate"],
                "currency": ["GBP"],
                "maturity_date": [None],
                "market_value": [float(_EAD)],
                "nominal_value": [float(_EAD)],
                "pledge_percentage": [None],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["LN-294"],
                "issuer_cqs": [None],
                "issuer_type": [None],
                "residual_maturity_years": [None],
                "original_maturity_years": [None],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [True],
                "is_main_index": [None],
                "valuation_date": [date(2026, 12, 31)],
                "valuation_type": ["market"],
                "property_type": ["residential"],
                "property_ltv": [1.0],
                "is_income_producing": [False],
                "is_adc": [False],
                "is_presold": [False],
                "is_qualifying_re": [True],
                "prior_charge_ltv": [0.0],
                "liquidation_period_days": [None],
                "qualifies_for_zero_haircut": [False],
                "insurer_risk_weight": [None],
                "credit_event_reduction": [0.0],
                "rental_to_interest_ratio": [None],
            }
        ),
    )


@pytest.fixture(scope="module")
def splitter_legs() -> dict[str, dict]:
    """Run the CQS-6 corporate splitter scenario through the whole pipeline."""
    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )
    result = PipelineOrchestrator().run_with_data(_splitter_bundle(6), config)
    assert result.results is not None, "P1.294: the pipeline produced no results frame"

    df = result.results.collect().filter(pl.col("split_parent_id") == "LN-294")
    return {row["re_split_role"]: row for row in df.to_dicts()}


class TestP1294SplitterPathUnchanged:
    """CRR Art. 124(1) is ALREADY implemented on the RE-splitter path.

    ``re_split/splitter.py::_residual_columns`` keeps the original counterparty
    class on the residual leg so the standard corporate path applies, citing
    "CRR Art. 124(1), first subparagraph, second sentence". A whole-loan fix
    must not double-apply.
    """

    def test_p1_294_splitter_emits_both_legs(self, splitter_legs: dict[str, dict]) -> None:
        """Both legs are emitted and both carry a risk weight and an RWA.

        Arrange: corporate CQS 6, GBP 1m loan, GBP 1m residential pledge.
        Act:     full CRR SA pipeline.
        Assert:  a secured and a residual row exist, both non-null throughout.
        """
        # Assert — presence
        assert set(splitter_legs) == {"secured", "residual"}, (
            f"P1.294: expected a secured and a residual leg, got {sorted(splitter_legs)}"
        )

        # Assert — non-null where the portfolio has exposure
        for role, row in splitter_legs.items():
            for column in ("ead_final", "risk_weight", "rwa_final"):
                assert row[column] is not None, (
                    f"P1.294: {role} leg has a null {column} on a GBP 1m exposure"
                )

    def test_p1_294_splitter_legs_keep_their_pre_change_weights(
        self, splitter_legs: dict[str, dict]
    ) -> None:
        """The split legs are pinned absolutely — 800k @ 35%, 200k @ 150%.

        secured EAD  = min(1,000,000, 0.80 x 1,000,000) = 800,000 @ 0.35
        residual EAD = 200,000 @ Art. 122 Table 6 CQS 6 = 1.50

        Arrange: corporate CQS 6, GBP 1m loan, GBP 1m residential pledge.
        Act:     full CRR SA pipeline.
        Assert:  per-leg EAD and risk weight unchanged; EAD sums to the parent.
        """
        # Arrange
        secured = splitter_legs["secured"]
        residual = splitter_legs["residual"]

        # Assert — secured leg
        assert secured["exposure_class"] == "residential_mortgage"
        assert secured["ead_final"] == pytest.approx(800_000.0, rel=_RW_TOL)
        assert secured["risk_weight"] == pytest.approx(_SECURED_RW, rel=_RW_TOL), (
            "P1.294: the splitter's secured leg sits at exactly the 0.80 cap and must "
            f"keep the Art. 125 preferential {_SECURED_RW}, got {secured['risk_weight']}"
        )
        assert secured["rwa_final"] == pytest.approx(280_000.0, abs=_RWA_TOL)

        # Assert — residual leg (already Art. 124(1)-correct)
        assert residual["exposure_class"] == "corporate"
        assert residual["ead_final"] == pytest.approx(200_000.0, rel=_RW_TOL)
        assert residual["risk_weight"] == pytest.approx(1.50, rel=_RW_TOL), (
            "P1.294: the splitter's residual leg already takes the Art. 122 CQS-6 "
            f"weight 1.50 and must not move, got {residual['risk_weight']}"
        )
        assert residual["rwa_final"] == pytest.approx(300_000.0, abs=_RWA_TOL)

        # Assert — the breakdown foots to the parent exposure
        assert secured["ead_final"] + residual["ead_final"] == pytest.approx(
            float(_EAD), abs=_RWA_TOL
        ), "P1.294: the split legs must sum to the parent EAD"

    def test_p1_294_whole_loan_and_split_agree_on_the_same_exposure(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        splitter_legs: dict[str, dict],
    ) -> None:
        """The two Art. 124(1) paths must produce the same capital.

        The CRR RRE split cap (``re_split_rre_secured_ltv_cap`` = 0.80) equals
        the Art. 125(2)(d) whole-loan threshold, so splitting an exposure and
        blending it are the same arithmetic. Measured today: 430,000 whole-loan
        against 580,000 split — a 150,000 gap on a GBP 1m exposure. The gap is
        non-zero, which is what makes this comparison a test at all.

        Arrange: the same CQS-6 corporate at LTV 1.00, once whole-loan and once
                 through the splitter.
        Act:     SACalculator.calculate_branch / full CRR SA pipeline.
        Assert:  the two RWA figures agree, both at 580,000.
        """
        # Arrange / Act
        whole_loan = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="residential_mortgage",
            ltv=_HIGH_LTV,
            config=crr_config,
            qualifies_as_retail=False,
            cp_is_natural_person=False,
            cqs=6,
        )
        split_rwa = sum(row["rwa_final"] for row in splitter_legs.values())

        # Assert
        assert split_rwa == pytest.approx(580_000.0, abs=_RWA_TOL), (
            f"P1.294: the splitter path is the reference and must stay at 580,000, "
            f"got {split_rwa:,.2f}"
        )
        assert whole_loan["rwa_final"] == pytest.approx(split_rwa, abs=_RWA_TOL), (
            "P1.294: the whole-loan Art. 125 blend and the Art. 124(1) loan split "
            f"describe the same exposure and must agree — whole-loan "
            f"{whole_loan['rwa_final']:,.2f} vs split {split_rwa:,.2f} "
            f"(pre-fix gap: {split_rwa - _PRE_FIX_RWA:,.2f})"
        )


# ---------------------------------------------------------------------------
# Anchor: the expected values track the pack, not a copy of the engine
# ---------------------------------------------------------------------------


class TestP1294ExpectedValuesTrackThePack:
    """The blends above are derived from Art. 122 Table 6, not invented here.

    If the pack's corporate ladder is ever re-priced, this test names which
    claim broke instead of letting the ladder tests drift silently against a
    hand-written copy.
    """

    def test_p1_294_pinned_unsecured_weights_match_the_pack_ladder(self) -> None:
        """Every rated obligor's X equals ``corporate_risk_weights[cqs]``.

        Arrange: the parametrised obligor ladder above.
        Act:     read the resolved pack table through the engine binding.
        Assert:  each rated case's X is that CQS's pack weight, and the pack
                 covers every member of the CQS enum.
        """
        # Arrange
        pack_ladder = {cqs.value: float(rw) for cqs, rw in CORPORATE_RISK_WEIGHTS.items()}

        # Assert — the table is complete against the enum, not a hand-written list
        assert set(pack_ladder) == {m.value for m in CQS}, (
            "P1.294: corporate_risk_weights must cover every CQS enum member — "
            f"missing {sorted({m.value for m in CQS} - set(pack_ladder))}"
        )

        # Assert — every rated case's expected X is the pack's value
        for case_id, kwargs, unsecured_rw in _OBLIGOR_LADDER:
            cqs = kwargs["cqs"]
            if cqs is None:
                continue
            assert unsecured_rw == pytest.approx(pack_ladder[cqs], rel=_RW_TOL), (
                f"P1.294: case {case_id} pins X={unsecured_rw} but the pack's "
                f"Art. 122 Table 6 weight for CQS {cqs} is {pack_ladder[cqs]}"
            )
