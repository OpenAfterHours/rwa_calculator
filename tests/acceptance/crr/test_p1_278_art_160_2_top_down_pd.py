"""
P1.278 — CRR Art. 160(2)(a): capital for a purchased corporate receivables pool
whose PD is derived top-down from the institution's EL estimate.

Pipeline position:
    ExposureClassifier (derive_purchased_receivables_pd) -> IRB transform chain

Scenario (CRR-PR-TOPDOWN):
    A GB corporate purchased-receivables pool, EAD GBP 1,000,000, bought at a
    senior claim (``purchased_receivables_subtype="senior"``). The institution
    has an IRB corporate model permission but CANNOT produce a Section-6
    compliant PD for the pool; it supplies only an EL estimate of 2.25%.
    Reporting date 2025-12-31, maturity_date 2027-12-31 (M = 2.0y exactly on the
    engine's /365 ordinal-day basis).

    Pre-fix the pool had no PD at all, so the classifier's IRB gate
    (``internal_pd.is_not_null()``) sent it to the Standardised Approach: an
    unrated corporate at 100% RW, RWA 1,000,000.

Hand calculation (CRR Art. 153(1), computed with stdlib NormalDist):
    Step 1 — Art. 160(2)(a) PD, denominator per Art. 161(1)(e):
        PD = EL / LGD = 0.0225 / 0.45 = 0.05
        (above the Art. 160(1) 0.03% floor, so the floor does not bind)
    Step 2 — Art. 161(1)(e) supervisory LGD for the senior subtype:
        LGD = 0.45
    Step 3 — correlation and maturity adjustment at PD = 5%, M = 2.0:
        R  = 0.12 x 0.917915001 + 0.24 x 0.082084999 = 0.129850200
        b  = (0.11852 - 0.05478 x ln 0.05)^2         = 0.079877577
        MA = (1 + (2.0 - 2.5) x b) / (1 - 1.5 x b)   = 1.090751036
    Step 4 — capital requirement and risk weight:
        K_base = 0.45 x [N(...) - 0.05] = 0.105519519
        K      = K_base x MA            = 0.115095524
        RW     = K x 12.5 x 1.06        = 1.525015697
        RWA    = 1,525,015.70
    Step 5 — expected loss round-trip (the identity EL = PD x LGD):
        EL_amount = PD x LGD x EAD = 0.05 x 0.45 x 1,000,000 = 22,500
                  = el_estimate x EAD = 0.0225 x 1,000,000   -> the firm's own
        EL estimate must survive the PD derivation exactly.

    Capital direction: RWA rises from 1,000,000 (SA, unrated corporate 100%) to
    1,525,015.70 — the IRB treatment is not a relief here, and that is the point:
    Art. 160(2) is a mandatory method for a pool the firm cannot rate, not an
    election a firm would take for capital benefit.

References:
    - CRR Art. 160(2)(a): senior purchased corporate receivables PD = EL / LGD
    - CRR Art. 160(1): 0.03% corporate PD floor (not binding at PD = 5%)
    - CRR Art. 160(2)(b): subordinated purchased corporate receivables PD = EL
    - CRR Art. 160(6) first sentence: dilution-risk PD = EL estimate for dilution
    - CRR Art. 161(1)(e)/(f)/(g): the paired supervisory LGDs — 45% senior /
      100% subordinated / 75% dilution (PS1/26: 40% / 100% / 100%)
    - CRR Art. 153(1): correlation, maturity adjustment, K, 1.06 scaling factor
    - CRR Art. 162(2): date-derived M clipped to [1, 5] -> M = 2.0y
    - PS1/26 Art. 160(2)(a) / 161(1)(e): same method, 40% senior LGD under B31
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.irb.transforms import (
    apply_all_formulas,
    apply_firb_lgd,
    classify_approach,
    prepare_columns,
)

# ---------------------------------------------------------------------------
# Scenario inputs
# ---------------------------------------------------------------------------

_CP = "CP_PR_TOPDOWN"
_LOAN = "LN_PR_TOPDOWN"
_REPORTING_DATE = date(2025, 12, 31)
_MATURITY_DATE = date(2027, 12, 31)
# Post-2027 dates giving the same M = 2.0y under Basel 3.1.
_B31_REPORTING_DATE = date(2027, 12, 31)
_B31_MATURITY_DATE = date(2029, 12, 31)
_EAD = 1_000_000.0
_EL_RATE = 0.0225
_EL_SUBORDINATED = 0.30  # Art. 160(2)(b): PD = EL, no division
_EL_DILUTION = 0.40  # Art. 160(6) first sentence: PD = EL for dilution risk

# ---------------------------------------------------------------------------
# Hand-calc expectations (module docstring)
# ---------------------------------------------------------------------------

_PD_EXPECTED = 0.05  # 0.0225 / 0.45
_LGD_EXPECTED = 0.45  # Art. 161(1)(e)
_M_EXPECTED = 2.0
_MA_EXPECTED = 1.090751036
_RW_EXPECTED = 1.525015697
_RWA_EXPECTED = 1_525_015.70
_EL_AMOUNT_EXPECTED = 22_500.0  # = el_estimate x EAD

# Pre-fix counterfactual: SA, unrated corporate 100% RW.
_RWA_PREFIX_SA = 1_000_000.0

_ABS_TOL = 0.50  # GBP 0.50 on a 7-figure RWA


def _config(regime: str = "crr") -> CalculationConfig:
    """F-IRB permission on CORPORATE only (no own PD, hence no own LGD)."""
    base = (
        CalculationConfig.crr(reporting_date=_REPORTING_DATE)
        if regime == "crr"
        else CalculationConfig.basel_3_1(reporting_date=_B31_REPORTING_DATE)
    )
    return replace(
        base,
        irb_permissions=IRBPermissions(
            permissions={ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB}}
        ),
    )


def _classified_row(
    *,
    regime: str = "crr",
    subtype: str = "senior",
    el_estimate: float | None = _EL_RATE,
    el_dilution_estimate: float | None = None,
) -> pl.DataFrame:
    """Run the real classifier over the pool and return the classified frame."""
    exposures = pl.LazyFrame(
        {
            "exposure_reference": [_LOAN],
            "exposure_type": ["loan"],
            "counterparty_reference": [_CP],
            "value_date": [date(2025, 1, 15)],
            "maturity_date": [_MATURITY_DATE if regime == "crr" else _B31_MATURITY_DATE],
            "currency": ["GBP"],
            "drawn_amount": [_EAD],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "seniority": ["senior"],
            # No obligor PD and no own LGD — the Art. 160(2) population.
            "internal_pd": [None],
            "lgd": [None],
            "purchased_receivables_subtype": [subtype],
            "el_estimate": [el_estimate],
            "el_dilution_estimate": [el_dilution_estimate],
        },
        schema={
            "exposure_reference": pl.String,
            "exposure_type": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "undrawn_amount": pl.Float64,
            "nominal_amount": pl.Float64,
            "seniority": pl.String,
            "internal_pd": pl.Float64,
            "lgd": pl.Float64,
            "purchased_receivables_subtype": pl.String,
            "el_estimate": pl.Float64,
            "el_dilution_estimate": pl.Float64,
        },
    )
    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": [_CP],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            # Large corporate so the row stays CORPORATE (not CORPORATE_SME) and
            # the Art. 153(4) firm-size correlation adjustment does not apply.
            "annual_revenue": [500_000_000.0],
            "total_assets": [800_000_000.0],
            "default_status": [False],
        }
    )
    bundle = make_resolved_bundle(
        exposures,
        counterparty_lookup=make_counterparty_lookup(counterparties=counterparties),
        lending_group_totals=pl.LazyFrame(
            schema={"lending_group_reference": pl.String, "total_exposure": pl.Float64}
        ),
        hierarchy_errors=[],
    )
    return ExposureClassifier().classify(bundle, _config(regime)).all_exposures.collect()


def _irb_row(classified: pl.DataFrame, regime: str = "crr") -> dict:
    """Feed the classifier's own output through the F-IRB transform chain."""
    config = _config(regime)
    irb_input = classified.lazy().with_columns(
        [
            pl.lit(_EAD).alias("ead_final"),
            pl.lit("corporate").alias("exposure_class"),
        ]
    )
    return (
        _pad(irb_input)
        .pipe(classify_approach, config)
        .pipe(apply_firb_lgd, config)
        .pipe(prepare_columns, config)
        .pipe(apply_all_formulas, config)
        .collect()
        .to_dicts()[0]
    )


@pytest.fixture(scope="module")
def classified() -> pl.DataFrame:
    return _classified_row()


@pytest.fixture(scope="module")
def irb_row(classified: pl.DataFrame) -> dict:
    return _irb_row(classified)


class TestP1278Art1602TopDownPDCapital:
    """CRR Art. 160(2)(a): EL/LGD PD reaches the IRB capital calculation."""

    # -- Step 1: the derived PD ---------------------------------------------

    def test_classifier_derives_pd_from_the_el_estimate(self, classified: pl.DataFrame) -> None:
        # Assert — 0.0225 / 0.45 = 0.05 (Art. 161(1)(e) denominator)
        assert classified["internal_pd"][0] == pytest.approx(_PD_EXPECTED)
        assert classified["pd"][0] == pytest.approx(_PD_EXPECTED)

    def test_pool_routes_to_foundation_irb_not_sa(self, classified: pl.DataFrame) -> None:
        # Assert — pre-fix: ApproachType.SA (the pool had no PD at all)
        assert classified["approach"][0] == ApproachType.FIRB.value

    # -- Step 2: the Art. 161(1)(e) supervisory LGD -------------------------

    def test_supervisory_senior_receivables_lgd_is_applied(self, irb_row: dict) -> None:
        # Assert — 45% via the purchased_receivables_subtype routing, not the
        # generic senior unsecured LGD (which is also 45% under CRR but is
        # reached by a different branch; the subtype branch is asserted by the
        # subordinated/dilution cases in the unit suite).
        assert irb_row["lgd_input"] == pytest.approx(_LGD_EXPECTED)

    # -- Steps 3-4: the capital number --------------------------------------

    def test_maturity_is_date_derived_two_years(self, irb_row: dict) -> None:
        # Assert
        assert irb_row["maturity"] == pytest.approx(_M_EXPECTED)

    def test_rwa_matches_hand_calc(self, irb_row: dict) -> None:
        # Assert — RW 1.525015697 x EAD 1,000,000
        assert irb_row["maturity_adjustment"] == pytest.approx(_MA_EXPECTED, abs=1e-8)
        assert irb_row["risk_weight"] == pytest.approx(_RW_EXPECTED, abs=1e-8)
        assert irb_row["rwa"] == pytest.approx(_RWA_EXPECTED, abs=_ABS_TOL)

    def test_rwa_is_not_the_pre_fix_sa_amount(self, irb_row: dict) -> None:
        # Assert — the pre-fix SA route gave RWA = EAD x 100% = 1,000,000
        assert irb_row["rwa"] != pytest.approx(_RWA_PREFIX_SA, abs=_ABS_TOL)
        assert irb_row["rwa"] > _RWA_PREFIX_SA

    # -- Step 5: the EL identity round-trip ---------------------------------

    def test_expected_loss_round_trips_the_firm_el_estimate(self, irb_row: dict) -> None:
        """PD = EL/LGD implies PD x LGD = EL, so EL x EAD must be reproduced."""
        # Assert
        assert irb_row["expected_loss"] == pytest.approx(_EL_AMOUNT_EXPECTED, abs=_ABS_TOL)
        assert irb_row["expected_loss"] == pytest.approx(_EL_RATE * _EAD, abs=_ABS_TOL)


# ---------------------------------------------------------------------------
# The paired supervisory LGD (Art. 161(1)(e)/(f)/(g)) follows the derived PD
# ---------------------------------------------------------------------------

# (regime, subtype, el_estimate, el_dilution_estimate, expected PD, expected LGD,
#  expected RW) — RWs re-derived independently with stdlib NormalDist at M = 2.0y,
#  CRR carrying the Art. 153(1) 1.06 scaling factor and B31 not.
_PAIRING_CASES = [
    # Art. 160(2)(a) + Art. 161(1)(e): senior — CRR 45%, PS1/26 40%
    ("crr", "senior", _EL_RATE, None, 0.05, 0.45, 1.525015697),
    ("b31", "senior", _EL_RATE, None, 0.05625, 0.40, 1.333876130),
    # Art. 160(2)(b) + Art. 161(1)(f): subordinated — 100% both regimes
    ("crr", "subordinated", _EL_SUBORDINATED, None, 0.30, 1.00, 5.761284760),
    ("b31", "subordinated", _EL_SUBORDINATED, None, 0.30, 1.00, 5.435174302),
    # Art. 160(6) + Art. 161(1)(g): dilution risk — CRR 75%, PS1/26 100%
    ("crr", "dilution_risk", None, _EL_DILUTION, 0.40, 0.75, 4.176524278),
    ("b31", "dilution_risk", None, _EL_DILUTION, 0.40, 1.00, 5.253489658),
]


class TestSupervisoryLGDPairsWithTheDerivedPD:
    """Art. 161(1)(e)/(f)/(g) pin the LGD for exactly the top-down PD population.

    CRR Art. 161(1)(e)/(f) condition the supervisory LGD on the institution being
    "not able to estimate PDs or [its] PD estimates do not meet the requirements
    set out in Section 6"; PS1/26 Art. 161(1)(e)-(g) state the same condition as
    "where PD is determined in accordance with point (a) of Article 160(2)" (and
    (g) as the first sentence of Article 160(6)). A top-down PD married to the
    generic senior/subordinated LGD would not be the schedule the article states.

    No derived-PD carrier flag is needed for this: both the PD derivation and the
    LGD ladder key on the SAME ``purchased_receivables_subtype`` column, which is
    why the PD fork was keyed on that column rather than on ``seniority``.
    """

    @pytest.mark.parametrize(
        ("regime", "subtype", "el", "el_dilution", "expected_pd", "expected_lgd", "expected_rw"),
        _PAIRING_CASES,
        ids=[f"{regime}-{subtype}" for regime, subtype, *_ in _PAIRING_CASES],
    )
    def test_paired_supervisory_lgd_and_rw(
        self,
        regime: str,
        subtype: str,
        el: float | None,
        el_dilution: float | None,
        expected_pd: float,
        expected_lgd: float,
        expected_rw: float,
    ) -> None:
        # Arrange / Act
        classified = _classified_row(
            regime=regime, subtype=subtype, el_estimate=el, el_dilution_estimate=el_dilution
        )
        row = _irb_row(classified, regime)

        # Assert — the derived PD, its paired supervisory LGD, and the resulting RW
        assert row["pd_floored"] == pytest.approx(expected_pd)
        assert row["lgd_input"] == pytest.approx(expected_lgd)
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-8)

    def test_dilution_el_is_a_pd_not_an_el_amount(self) -> None:
        """The dilution EL sets PD; the EL *amount* is then PD x LGD x EAD.

        Art. 160(6) sets PD = EL for dilution risk while Art. 161(1)(g) sets a
        SEPARATE supervisory LGD (75% CRR), so the reported EL amount is
        0.40 x 0.75 x EAD = 300,000 — deliberately NOT el_dilution_estimate x EAD
        (400,000). The senior limb round-trips only because its LGD is the same
        value the PD was divided by.
        """
        # Arrange / Act
        classified = _classified_row(
            subtype="dilution_risk", el_estimate=None, el_dilution_estimate=_EL_DILUTION
        )
        row = _irb_row(classified)

        # Assert
        assert row["expected_loss"] == pytest.approx(_EL_DILUTION * 0.75 * _EAD, abs=_ABS_TOL)
        assert row["expected_loss"] != pytest.approx(_EL_DILUTION * _EAD, abs=_ABS_TOL)
