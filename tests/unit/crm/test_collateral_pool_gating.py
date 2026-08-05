"""
Tests for defect D1 (pool-gate asymmetry) in multi-level collateral allocation.

``docs/plans/irb-collateral-corep-reporting.md`` RD-4: flagged
(``is_airb_model_collateral=True``) collateral stays pool-gated — the flag
asserts the collateral was used to build the internal LGD model, so it must
not reach non-AIRB exposures (CRR Art. 181 / PS1/26 Art. 169A). Unflagged
collateral carries no such assertion and must reach every exposure it is
pledged against, at every beneficiary level.

RD-6 — the fix is purely additive; no EXISTING carrier is repointed.
``collateral_adjusted_value`` drives the SA Comprehensive-Method EAD
reduction (``engine/crm/collateral.py:1438-1453``) and ``collateral_re_value``
/ ``collateral_other_physical_value`` feed the CRR Art. 230 minimum-
collateralisation threshold gate (``:1274-1300``) — all effect paths.
Repointing them would move SA and FIRB capital and revert the deliberate
migration pinned by
``test_airb_model_collateral_flag.py::TestUnflaggedCounterpartyCollateral::test_airb_excluded_from_pro_rata_base``
(that test needs NO edit — it stays green throughout this fix). Instead the
NEW per-category **market-value** carriers (``collateral_re_market_value`` et
al., work item W2, shared naming with
``tests/unit/crm/test_collateral_market_value_carriers.py`` which owns the
basis/routing/regime tests for that carrier family — not edited here) are
computed pool-agnostically and consumed by the reporting layer only.

RD-5 — recognition follows the firm-level election; the row flag is a
positive override. PS1/26 Art. 169A(1)/(2) (``ps126app1.pdf`` p.120): an
institution applying the LGD Modelling Collateral Method may recognise
collateral in its LGD estimates as an INSTITUTION-LEVEL election. So on an
A-IRB exposure, collateral pledged against it at any beneficiary level is
recognised for the cols 0150-0210 block by virtue of the firm's election —
UNLESS the firm has elected the Foundation Collateral Method instead
(``AIRBCollateralMethod.FOUNDATION``), in which case Art. 169A/B recognition
does not apply to that row at all and it must not pick up the new
market-value carrier.

Carrier classification pinned by these tests:
- **Existing adjusted carriers** (``collateral_re_value`` and siblings) —
  effect-adjacent, UNTOUCHED by this fix. Stay exactly as they are today.
- **New market-value carriers** (``collateral_re_market_value`` and
  siblings) — additive, pool-agnostic disclosure-only carriers. Do not exist
  yet, so the tests below fail with ``ColumnNotFoundError`` until W2 lands —
  that is the correct failure mode for a purely additive contract.
- **Effect carriers** (``crm_alloc_<category>``, ``total_collateral_for_lgd``,
  ``ead_after_collateral``, ``lgd_post_crm``) — pool gate unchanged, and
  additionally untouched by the new market-value carrier's existence.

Coverage:
- Unflagged real-estate collateral pledged at counterparty level raises the
  new market-value carrier on an AIRB exposure to its pro-rata share, while
  the existing adjusted carrier stays at 0.0 (additive-only, pinned by
  asserting both).
- Same at facility level.
- Unflagged real-estate collateral pledged at loan (direct) level is
  unaffected on the existing carrier — regression guard, passes today and
  must keep passing.
- Flagged real-estate collateral never reaches a non-AIRB exposure on the
  existing adjusted carrier or the effect carrier, at any of the three
  beneficiary levels — the gate that must survive the fix.
- Conservation: an unflagged counterparty-level pledge shared by an AIRB and
  a non-AIRB exposure splits pro-rata (new market-value carrier) over the
  whole (pool-agnostic) population; the non-AIRB row's EXISTING adjusted
  carrier is unchanged from today (still absorbs the full pledge) — the
  proof that no capital moved.
- Split invariant: an unflagged counterparty-level pledge against an AIRB
  exposure raises the new market-value carrier but leaves the existing
  adjusted carrier and every effect carrier at their current values.
- Election invariant (RD-5): an AIRB exposure under the Foundation
  Collateral Method election gets NO new-carrier recognition from an
  unflagged pledge — the election actually doing work.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import empty_counterparty_lookup, with_ancestor_facilities

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import AIRBCollateralMethod, ApproachType, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def b31_foundation_config() -> CalculationConfig:
    """B3.1 AIRB firm that has elected the Foundation Collateral Method
    instead of LGD Modelling — Art. 169A/B recognition does not apply, so
    Foundation is B3.1-only (``airb_lgd_collateral_method_applicable``
    is a B3.1 pack feature; CRR AIRB has no such election)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
        airb_collateral_method=AIRBCollateralMethod.FOUNDATION,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exposure(
    ref: str,
    approach: str,
    *,
    drawn: float,
    lgd: float = 0.45,
    cp_ref: str = "CP001",
    facility_ref: str = "FAC001",
) -> dict:
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": approach,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "risk_type": "FR",
        "lgd": lgd,
        "seniority": "senior",
        "parent_facility_reference": facility_ref,
        "currency": "GBP",
        "maturity_date": None,
    }


def _re_collateral(
    coll_ref: str,
    beneficiary_ref: str,
    *,
    market_value: float,
    beneficiary_type: str = "counterparty",
    is_airb_model: bool = False,
) -> dict:
    """Real-estate collateral row. CRR Art. 224 Table 1 real-estate haircut is
    0%, so the CRR-side existing adjusted carrier equals ``market_value``
    once allocated — isolating the pool-gating defect from haircut effects
    (D2). ``is_eligible_irb_collateral=True`` attests Art. 199(2)/(5)/(6)
    FIRB FCM eligibility (P1.235) so that gate does not confound the
    Foundation-election test below, which targets the RD-5 recognition
    election specifically.
    """
    return {
        "collateral_reference": coll_ref,
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": "real_estate",
        "market_value": market_value,
        "currency": "GBP",
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        # Real estate is not Art. 197 eligible financial collateral (D7); this
        # only affects collateral_adjusted_value/collateral_market_value, not
        # the collateral_re_value / collateral_re_market_value carriers these
        # tests assert on.
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "is_airb_model_collateral": is_airb_model,
        "pledge_percentage": None,
        "collateral_maturity_date": None,
    }


_COLL_SCHEMA: dict[str, PolarsDataType] = {
    "collateral_reference": pl.String,
    "beneficiary_reference": pl.String,
    "beneficiary_type": pl.String,
    "collateral_type": pl.String,
    "market_value": pl.Float64,
    "currency": pl.String,
    "issuer_cqs": pl.Int8,  # production loader dtype (COLLATERAL_SCHEMA)
    "issuer_type": pl.String,
    "residual_maturity_years": pl.Float64,
    "is_eligible_financial_collateral": pl.Boolean,
    "is_eligible_irb_collateral": pl.Boolean,
    "is_airb_model_collateral": pl.Boolean,
    "pledge_percentage": pl.Float64,
    "collateral_maturity_date": pl.Date,
}


def _make_bundle(exposures: pl.LazyFrame, collateral: pl.LazyFrame) -> ClassifiedExposuresBundle:
    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        counterparty_lookup=empty_counterparty_lookup(),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )


def _run(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposures: list[dict],
    collateral: list[dict],
):
    exposures_lf = with_ancestor_facilities(pl.LazyFrame(exposures))
    collateral_lf = pl.LazyFrame(collateral, schema=_COLL_SCHEMA)
    bundle = _make_bundle(exposures_lf, collateral_lf)
    result = processor.get_crm_unified_bundle(bundle, config)
    return result.exposures.collect(), result.crm_errors


# ---------------------------------------------------------------------------
# Unflagged counterparty-level collateral must reach the AIRB pool via the
# NEW market-value carrier; the existing adjusted carrier stays untouched.
# ---------------------------------------------------------------------------


class TestUnflaggedCounterpartyLevelPoolGating:
    def test_airb_exposure_receives_unflagged_re_collateral_at_counterparty_level(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """
        A single AIRB exposure at a counterparty with an unflagged real-estate
        pledge at counterparty level must receive its pro-rata share (here,
        the full pledge — it is the only exposure at CP001) on the NEW
        ``collateral_re_market_value`` carrier. The carrier does not exist
        yet (W2 not implemented), so this fails with ``ColumnNotFoundError``
        today -- correct for a purely additive contract.

        The EXISTING ``collateral_re_value`` carrier must stay at 0.0 (RD-6:
        additive-only, no existing carrier is repointed).
        """
        df, _ = _run(
            processor,
            crr_config,
            [_exposure("AIRB1", ApproachType.AIRB.value, drawn=300_000.0, lgd=0.20)],
            [_re_collateral("C1", "CP001", market_value=500_000.0)],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        assert airb_row["collateral_re_market_value"][0] == pytest.approx(500_000.0, abs=1.0)
        assert airb_row["collateral_re_value"][0] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Unflagged facility-level collateral must reach the AIRB pool via the NEW
# market-value carrier; the existing adjusted carrier stays untouched.
# ---------------------------------------------------------------------------


class TestUnflaggedFacilityLevelPoolGating:
    def test_airb_exposure_receives_unflagged_re_collateral_at_facility_level(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """Same as the counterparty-level test but for a facility-level
        pledge: the NEW carrier picks up the AIRB row's share;
        ``collateral_re_value`` stays 0.0 (unchanged, additive-only)."""
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure(
                    "AIRB1",
                    ApproachType.AIRB.value,
                    drawn=300_000.0,
                    lgd=0.20,
                    facility_ref="FAC001",
                )
            ],
            [_re_collateral("C1", "FAC001", market_value=500_000.0, beneficiary_type="facility")],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        assert airb_row["collateral_re_market_value"][0] == pytest.approx(500_000.0, abs=1.0)
        assert airb_row["collateral_re_value"][0] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Unflagged direct/loan-level collateral is unaffected — regression guard
# (unchanged: this test targets the EXISTING carrier only, which was never
# gated at direct level and is not repointed by this fix).
# ---------------------------------------------------------------------------


class TestUnflaggedDirectLevelUnchanged:
    def test_airb_exposure_receives_unflagged_re_collateral_at_loan_level(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """
        Regression guard: direct (loan-level) unflagged collateral already
        flows unconditionally via the ungated ``_n_d`` term in ``_sum6`` and
        must keep doing so on the existing ``collateral_re_value`` carrier.
        Passes today; must still pass after the D1/W2 fix.
        """
        df, _ = _run(
            processor,
            crr_config,
            [_exposure("AIRB1", ApproachType.AIRB.value, drawn=300_000.0, lgd=0.20)],
            [_re_collateral("C1", "AIRB1", market_value=500_000.0, beneficiary_type="loan")],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        assert airb_row["collateral_re_value"][0] == pytest.approx(500_000.0, abs=1.0)


# ---------------------------------------------------------------------------
# Flagged collateral must stay pool-gated at every level — must survive
# (unchanged: targets the EXISTING carrier + the effect carrier only).
# ---------------------------------------------------------------------------


class TestFlaggedCollateralGateSurvivesAllLevels:
    """RD-4: flagged (``is_airb_model_collateral=True``) collateral stays
    pool-gated — it must never reach a non-AIRB exposure, at any beneficiary
    level, on EITHER the existing adjusted carrier (``collateral_re_value``)
    or the effect carrier (``crm_alloc_real_estate``). This invariant already
    holds today on both carriers and the D1/W2 fix must not break it."""

    @pytest.mark.parametrize(
        ("beneficiary_type", "beneficiary_ref"),
        [
            pytest.param("loan", "FIRB1", id="direct"),
            pytest.param("facility", "FAC001", id="facility"),
            pytest.param("counterparty", "CP001", id="counterparty"),
        ],
    )
    def test_flagged_re_collateral_never_reaches_non_airb_exposure(
        self,
        processor: CRMProcessor,
        crr_config: CalculationConfig,
        beneficiary_type: str,
        beneficiary_ref: str,
    ):
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure(
                    "AIRB1",
                    ApproachType.AIRB.value,
                    drawn=600_000.0,
                    lgd=0.20,
                    facility_ref="FAC001",
                ),
                _exposure(
                    "FIRB1",
                    ApproachType.FIRB.value,
                    drawn=400_000.0,
                    facility_ref="FAC001",
                ),
            ],
            [
                _re_collateral(
                    "C1",
                    beneficiary_ref,
                    market_value=500_000.0,
                    beneficiary_type=beneficiary_type,
                    is_airb_model=True,
                )
            ],
        )
        firb_row = df.filter(pl.col("exposure_reference") == "FIRB1")
        assert firb_row["collateral_re_value"][0] == pytest.approx(0.0, abs=0.01)
        assert firb_row["crm_alloc_real_estate"][0] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Conservation: a mixed-pool counterparty pledge splits pro-rata on the NEW
# market-value carrier; the non-AIRB row's EXISTING carrier is unchanged.
# ---------------------------------------------------------------------------


class TestConservationAcrossMixedPools:
    def test_unflagged_re_collateral_split_conserves_pledged_value(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """
        CP001 has one AIRB and one FIRB exposure sharing one unflagged
        counterparty-level pledge. Both must receive a non-zero, EAD-weighted
        pro-rata share of the pledge on the NEW ``collateral_re_market_value``
        carrier (AIRB1 60% / FIRB1 40% of the 1,000,000 pledge — fails today,
        carrier does not exist).

        The proof that no capital moved (RD-6): FIRB1's EXISTING
        ``collateral_re_value`` carrier is unchanged from today — it still
        absorbs the FULL 1,000,000 pledge, exactly as it does before this fix
        (the existing carrier's pool-gated blend is untouched; only the new,
        additive carrier is pool-agnostic).
        """
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure("AIRB1", ApproachType.AIRB.value, drawn=600_000.0, lgd=0.20),
                _exposure("FIRB1", ApproachType.FIRB.value, drawn=400_000.0),
            ],
            [_re_collateral("C1", "CP001", market_value=1_000_000.0)],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        firb_row = df.filter(pl.col("exposure_reference") == "FIRB1")

        # New carrier: EAD-weighted pro-rata over the whole (pool-agnostic)
        # counterparty population.
        assert airb_row["collateral_re_market_value"][0] == pytest.approx(600_000.0, abs=1.0)
        assert firb_row["collateral_re_market_value"][0] == pytest.approx(400_000.0, abs=1.0)
        # Existing carrier: unchanged from today -- no capital moved.
        assert firb_row["collateral_re_value"][0] == pytest.approx(1_000_000.0, abs=1.0)


# ---------------------------------------------------------------------------
# Split invariant: the new market-value carrier moves, the existing adjusted
# carrier and every effect (LGD/EAD) carrier do not.
# ---------------------------------------------------------------------------


class TestDisclosureEffectSplit:
    def test_unflagged_cp_pledge_raises_market_value_carrier_only(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """
        An unflagged counterparty-level real-estate pledge against a sole
        AIRB exposure must raise the NEW ``collateral_re_market_value``
        carrier to the pro-rata share (fails today -- carrier does not
        exist) while leaving:
        - the EXISTING ``collateral_re_value`` carrier at 0.0 (RD-6:
          additive-only, not repointed);
        - every effect carrier exactly where it would sit with no collateral
          at all: the AIRB row's modelled LGD is preserved (CRR Art. 181 /
          PS1/26 Art. 169A), so ``total_collateral_for_lgd`` /
          ``crm_alloc_real_estate`` stay 0.0, ``lgd_post_crm`` stays equal to
          the firm's own ``lgd_pre_crm`` (0.20), and ``ead_after_collateral``
          stays at ``ead_gross`` (300,000 -- AIRB keeps EAD unchanged).

        This is the guarantee that the D1/W2 fix moves no capital number,
        only a new disclosure figure.
        """
        df, _ = _run(
            processor,
            crr_config,
            [_exposure("AIRB1", ApproachType.AIRB.value, drawn=300_000.0, lgd=0.20)],
            [_re_collateral("C1", "CP001", market_value=500_000.0)],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")

        # New carrier: raised to the pro-rata share (fails today).
        assert airb_row["collateral_re_market_value"][0] == pytest.approx(500_000.0, abs=1.0)

        # Existing adjusted carrier: untouched.
        assert airb_row["collateral_re_value"][0] == pytest.approx(0.0, abs=0.01)

        # Effect carriers: unchanged from the no-collateral-effect baseline.
        assert airb_row["total_collateral_for_lgd"][0] == pytest.approx(0.0, abs=0.01)
        assert airb_row["crm_alloc_real_estate"][0] == pytest.approx(0.0, abs=0.01)
        assert airb_row["lgd_post_crm"][0] == pytest.approx(0.20, abs=1e-6)
        assert airb_row["ead_after_collateral"][0] == pytest.approx(300_000.0, abs=1.0)


# ---------------------------------------------------------------------------
# Election invariant (RD-5): Foundation Collateral Method excludes the row
# from the new carrier's recognition entirely.
# ---------------------------------------------------------------------------


class TestFoundationElectionExcludedFromMarketValueCarrier:
    def test_foundation_election_excludes_market_value_carrier(
        self, processor: CRMProcessor, b31_foundation_config: CalculationConfig
    ):
        """
        RD-5: recognition of collateral in LGD estimates follows the firm's
        institution-level election (PS1/26 Art. 169A(1)/(2)). Under the
        Foundation Collateral Method (no LGD-Modelling election), Art. 169A/B
        recognition does not apply -- the row is not on the AIRB
        market-value reporting limb (RD-1) and must NOT pick up the new
        market-value carrier from an unflagged pledge, even though it is
        still an A-IRB APPROACH exposure. This is the election actually
        doing work: without it, RD-5 would be trivially true for every A-IRB
        row regardless of the firm's method choice.
        """
        df, _ = _run(
            processor,
            b31_foundation_config,
            [_exposure("AIRB1", ApproachType.AIRB.value, drawn=300_000.0, lgd=0.20)],
            [_re_collateral("C1", "CP001", market_value=500_000.0)],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        assert airb_row["collateral_re_market_value"][0] == pytest.approx(0.0, abs=0.01)
