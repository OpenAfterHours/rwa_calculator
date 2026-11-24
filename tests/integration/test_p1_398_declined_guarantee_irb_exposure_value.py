"""
P1.398 — a declined guarantee leaves the IRB leg on its own exposure value.

Pipeline wired end to end through ``PipelineOrchestrator`` (loader seal ->
hierarchy -> classifier -> CRM -> IRB calculator -> aggregator). No mocking.

What is under test. The CRM stage re-values the covered part of an F-IRB or A-IRB
leg at the Standardised Approach conversion factor whenever its guarantor is
routed to risk-weight substitution (``guarantor_approach == 'sa'``,
``engine/crm/guarantees.py::_apply_cross_approach_ccf``). The decision whether
to recognise that guarantee is taken later, in the IRB stage
(``engine/irb/guarantee.py::apply_guarantee_substitution``). Before P1.398
nothing reverted the swap when the guarantee was then declined, so the leg kept
the SA factor on an exposure the guarantee no longer touched.

The rule. A declined guarantee is not recognised, so the exposure keeps the
exposure value of an IRB exposure with no credit protection:

- CRR Art. 193(1)/(3): credit protection "may amend" the IRB calculation; not
  amending it leaves the Art. 166(8)-(10) exposure value. Art. 166(8)(b): "for
  short-term letters of credit arising from the movement of goods, a conversion
  factor of 20 %"; Art. 166(8)(d): "for other credit lines ... 75 %"; or the
  firm's own estimate (Art. 166(8), last subparagraph).
- PS1/26 Art. 193(2A): "an institution may choose to disregard any item of credit
  protection" — disregarded, the exposure is valued under Art. 166A-166D:
  Art. 166C(1) (Foundation IRB: the Art. 111 factor) and Art. 166D(1)(a)
  (Advanced IRB revolving commitments: an own estimate).
- CRR Art. 153(3): the double-default RWEA is "RW · exposure value ·
  (0.15 + 160 · PD_pp)" — the IRB exposure value, so a double-default covered
  leg is not an SA-substituted one either.

Shape (every case). A corporate obligor, PD 0.3%, a 500,000 drawn loan under an
800,000 facility (300,000 undrawn), 60% guaranteed at facility level. The
guarantor is ECAI-rated with no internal PD, so it routes to SA substitution.
A CQS 3 corporate takes 100% (CRR) / 75% (Basel 3.1), above the obligor's IRB
weight in both regimes, so the guarantee is declined. That choice is deliberate
(skeptic note on the premise audit): an UNRATED institution's weight depends on
open item P1.335, and if that lands such a guarantee becomes beneficial and the
test would stop exercising a decline. Each test asserts the decline first.

Hand calculation of the exposure value the leg must keep (drawn + CCF x undrawn):

    CRR  F-IRB commitment     500,000 + 0.75 x 300,000 = 725,000  (was 680,000)
    CRR  F-IRB trade LC       500,000 + 0.20 x 300,000 = 560,000  (was 614,000)
    CRR  A-IRB own CCF 80%    500,000 + 0.80 x 300,000 = 740,000  (was 686,000)
    B3.1 A-IRB own CCF 80%    500,000 + 0.80 x 300,000 = 740,000  (was 686,000)
    B3.1 F-IRB commitment     500,000 + 0.50 x 300,000 = 650,000  (was 650,000)

Further shapes, each with its own hand calculation in its test: two guarantors
on one facility (a declined one beside a recognised one, and beside a
double-default one — both reach ``redistribute_non_beneficial``), a Basel 3.1
A-IRB commitment carrying an Art. 166D(3) own estimate of EAD, and the IRB chain
composed WITHOUT ``restore_own_irb_exposure_value`` (the documented transform
chain a direct caller may build), which must settle to the same figures.

The last row CANNOT be reddened (LESSONS C7): under PS1/26 Art. 166C(1) the
Foundation IRB factor IS the Art. 111 factor, so the swap is neutral there. It
stays parametrised so the regime is still covered; the Basel 3.1 failure is
shown on the A-IRB own-CCF row instead.

Basel 3.1 assertions read the PRE-FLOOR IRB RWEA (``rwa_pre_floor``), never the
floored ``rwa_final``: the SA-equivalent leg recognises the guarantee
(CQS 3 corporate 75% < unrated 100%), so a floored total would move for a
reason unrelated to this change (skeptic note; LESSONS C8).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.data.schemas import GUARANTEE_SCHEMA
from rwa_calc.domain.enums import ExposureClass, PermissionMode
from rwa_calc.engine.irb import calculator as irb_calculator
from rwa_calc.engine.irb.transforms import (
    apply_all_formulas,
    apply_firb_lgd,
    apply_guarantee_substitution,
    apply_post_model_adjustments,
    classify_approach,
    prepare_columns,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import seal_raw_table

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_model_permission,
    make_rating,
    make_raw_data_bundle,
)

# =============================================================================
# SCENARIO CONSTANTS
# =============================================================================

DRAWN: float = 500_000.0
LIMIT: float = 800_000.0
UNDRAWN: float = LIMIT - DRAWN
COVERED_SHARE: float = 0.6
OBLIGOR_PD: float = 0.003
OWN_LGD: float = 0.45
OWN_CCF: float = 0.80

_MODEL_ID: str = "P1398_MODEL"
_GUARANTOR: str = "P1398_GTOR"
_OBLIGOR: str = "P1398_BORR"
_FACILITY: str = "P1398_FAC"

_DECLINED = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"

#: Extra facility columns for one test (``monkeypatch.setitem``); empty otherwise.
_FACILITY_OVERRIDES: dict[str, Any] = {}


# =============================================================================
# HELPERS
# =============================================================================


def _config(regime: str, *, double_default: bool = False) -> CalculationConfig:
    """IRB run in the named regime; double default is a CRR-only election.

    With double default on, the firm holds no IRB permission for the
    institutions class: the double-default provider is an institution (CRR
    Art. 202, P1.203), and it must route to SA substitution for the CRM stage to
    swap the covered leg's CCF, which is the case these tests exist for.
    """
    if regime == "CRR":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            permission_mode=PermissionMode.IRB,
            enable_double_default=double_default,
        )
        if not double_default:
            return config
        full = IRBPermissions.full_irb().permissions
        return dataclasses.replace(
            config,
            irb_permissions=IRBPermissions(
                permissions={k: v for k, v in full.items() if k != ExposureClass.INSTITUTION}
            ),
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.IRB
    )


def _bundle(
    *,
    approach: str,
    risk_type: str = "medium_risk",
    trade_lc: bool = False,
    guarantor_entity_type: str = "corporate",
    guarantor_cqs: int = 3,
    guarantor_internal_pd: float | None = None,
    own_ccf: float = OWN_CCF,
) -> RawDataBundle:
    """One obligor, one drawn loan under one facility, a 60% facility guarantee."""
    is_airb = approach == "advanced_irb"
    counterparties = [
        make_counterparty(counterparty_reference=_OBLIGOR, entity_type="corporate"),
        make_counterparty(counterparty_reference=_GUARANTOR, entity_type=guarantor_entity_type),
    ]
    loans = [
        make_loan(
            loan_reference="P1398_LN",
            counterparty_reference=_OBLIGOR,
            drawn_amount=DRAWN,
            interest=0.0,
            lgd=OWN_LGD if is_airb else None,
        )
    ]
    facilities = [
        make_facility(
            facility_reference=_FACILITY,
            counterparty_reference=_OBLIGOR,
            limit=LIMIT,
            risk_type=risk_type,
            is_short_term_trade_lc=trade_lc,
            is_revolving=is_airb,
            ccf_modelled=own_ccf if is_airb else None,
            lgd=OWN_LGD if is_airb else None,
            **_FACILITY_OVERRIDES,
        )
    ]
    guarantor_rating: dict[str, Any] = (
        {"rating_type": "internal", "pd": guarantor_internal_pd, "cqs": guarantor_cqs}
        if guarantor_internal_pd is not None
        else {
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "BBB",
            "cqs": guarantor_cqs,
            "pd": None,
        }
    )
    ratings = [
        make_rating(
            rating_reference="P1398_R_BORR",
            counterparty_reference=_OBLIGOR,
            pd=OBLIGOR_PD,
            model_id=_MODEL_ID,
        ),
        make_rating(
            rating_reference="P1398_R_GTOR", counterparty_reference=_GUARANTOR, **guarantor_rating
        ),
    ]
    permissions = [
        make_model_permission(model_id=_MODEL_ID, exposure_class="corporate", approach=approach)
    ]
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=loans,
        facilities=facilities,
        model_permissions=permissions,
        ratings=ratings,
    )
    guarantee = _rows_to_lazyframe(
        [
            {
                "guarantee_reference": "P1398_G",
                "guarantee_type": "guarantee",
                "guarantor": _GUARANTOR,
                "currency": "GBP",
                "maturity_date": date(2030, 12, 31),
                "amount_covered": None,
                "percentage_covered": COVERED_SHARE,
                "beneficiary_type": "facility",
                "beneficiary_reference": _FACILITY,
                "protection_type": "guarantee",
                "includes_restructuring": True,
            }
        ],
        GUARANTEE_SCHEMA,
    )
    return dataclasses.replace(bundle, guarantees=seal_raw_table(guarantee, "guarantees"))


def _run(bundle: RawDataBundle, config: CalculationConfig) -> pl.DataFrame:
    result = PipelineOrchestrator().run_with_data(bundle, config)
    frame = result.results
    return frame.collect() if isinstance(frame, pl.LazyFrame) else frame


def _guarantor_legs(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("exposure_reference").str.contains("__G_"))


def _undrawn_guarantor_leg(df: pl.DataFrame) -> dict[str, Any]:
    legs = _guarantor_legs(df).filter(pl.col("nominal_amount") > 0)
    assert legs.height == 1, "expected exactly one covered off-balance-sheet leg"
    return legs.row(0, named=True)


def _pre_floor_rwa(df: pl.DataFrame) -> float:
    """The IRB RWEA before the Basel 3.1 output floor (CRR has no floor)."""
    column = "rwa_pre_floor" if "rwa_pre_floor" in df.columns else "rwa_final"
    return float(df[column].sum())


def _single(df: pl.DataFrame, column: str) -> float:
    values = df[column].unique().to_list()
    assert len(values) == 1, f"{column} differs across the legs: {values}"
    return float(values[0])


# =============================================================================
# A DECLINED GUARANTEE — every leg keeps the IRB exposure value
# =============================================================================


_DECLINED_CASES = [
    pytest.param("CRR", "foundation_irb", "medium_risk", False, 0.75, id="crr-firb-commitment"),
    pytest.param("CRR", "foundation_irb", "MR_ISSUED", True, 0.20, id="crr-firb-trade-lc"),
    pytest.param("CRR", "advanced_irb", "medium_risk", False, OWN_CCF, id="crr-airb-own-ccf"),
    pytest.param("BASEL_3_1", "advanced_irb", "medium_risk", False, OWN_CCF, id="b31-airb-own-ccf"),
    # Cannot be reddened: PS1/26 Art. 166C(1) makes the F-IRB factor the SA one.
    pytest.param(
        "BASEL_3_1", "foundation_irb", "medium_risk", False, 0.50, id="b31-firb-commitment"
    ),
]


@pytest.mark.parametrize(
    ("regime", "approach", "risk_type", "trade_lc", "own_ccf"), _DECLINED_CASES
)
def test_declined_guarantee_keeps_the_irb_exposure_value(
    regime: str, approach: str, risk_type: str, trade_lc: bool, own_ccf: float
) -> None:
    """Sum of ead_final over the split legs is drawn + own CCF x undrawn."""
    # Arrange
    bundle = _bundle(approach=approach, risk_type=risk_type, trade_lc=trade_lc)

    # Act
    df = _run(bundle, _config(regime))

    # Assert — adequacy: the population is the one P1.398 is about.
    legs = _guarantor_legs(df)
    assert legs.height == 2, "the guarantee did not split the loan and the undrawn leg"
    assert set(legs["guarantor_approach"].to_list()) == {"sa"}
    assert set(legs["guarantee_status"].to_list()) == {_DECLINED}
    assert not any(legs["is_guarantee_beneficial"].to_list())
    assert _undrawn_guarantor_leg(df)["nominal_amount"] > 0

    expected_ead = DRAWN + own_ccf * UNDRAWN
    assert float(df["ead_final"].sum()) == pytest.approx(expected_ead, rel=1e-12)


@pytest.mark.parametrize(
    ("regime", "approach", "risk_type", "trade_lc", "own_ccf"), _DECLINED_CASES
)
def test_declined_guarantee_keeps_the_irb_rwa_and_expected_loss(
    regime: str, approach: str, risk_type: str, trade_lc: bool, own_ccf: float
) -> None:
    """RWEA and EL are the obligor's per-unit figures on the IRB exposure value."""
    # Arrange
    bundle = _bundle(approach=approach, risk_type=risk_type, trade_lc=trade_lc)
    expected_ead = DRAWN + own_ccf * UNDRAWN

    # Act
    df = _run(bundle, _config(regime))

    # Assert — the per-unit parameters are the obligor's on every leg (the
    # change moves the exposure value, never the weight, PD or LGD).
    assert set(df["guarantee_status"].to_list()) <= {_DECLINED, "NO_GUARANTEE"}
    obligor_rw = _single(df, "risk_weight_irb_original")
    pd_floored = _single(df, "pd_floored")
    lgd_floored = _single(df, "lgd_floored")

    assert _pre_floor_rwa(df) == pytest.approx(expected_ead * obligor_rw, rel=1e-9)
    assert float(df["expected_loss"].sum()) == pytest.approx(
        expected_ead * pd_floored * lgd_floored, rel=1e-9
    )


@pytest.mark.parametrize(
    ("regime", "approach", "risk_type", "trade_lc", "own_ccf"), _DECLINED_CASES
)
def test_declined_guarantee_reports_the_irb_conversion_factor_on_the_covered_leg(
    regime: str, approach: str, risk_type: str, trade_lc: bool, own_ccf: float
) -> None:
    """The covered undrawn leg's EAD, CCF carriers and covered amount agree."""
    # Arrange
    bundle = _bundle(approach=approach, risk_type=risk_type, trade_lc=trade_lc)

    # Act
    leg = _undrawn_guarantor_leg(_run(bundle, _config(regime)))

    # Assert
    expected_leg_ead = COVERED_SHARE * UNDRAWN * own_ccf
    assert leg["guarantee_status"] == _DECLINED
    assert leg["ead_final"] == pytest.approx(expected_leg_ead, rel=1e-12)
    assert leg["guaranteed_portion"] == pytest.approx(expected_leg_ead, rel=1e-12)
    assert leg["ead_after_guarantee"] == pytest.approx(expected_leg_ead, rel=1e-12)
    assert leg["ccf_guaranteed"] == pytest.approx(leg["ccf_original"], rel=1e-12)
    assert leg["ccf_guaranteed"] == pytest.approx(own_ccf, rel=1e-12)


# =============================================================================
# DOUBLE DEFAULT — the covered leg is not SA-substituted either (CRR only)
# =============================================================================


def test_double_default_on_an_sa_routed_guarantor_keeps_the_irb_exposure_value() -> None:
    """CRR Art. 153(3): RWEA = RW_dd x the IRB exposure value of the covered leg.

    An institution guarantor (the only provider CRR Art. 202 admits, P1.203)
    with an internal PD but no IRB permission for its class routes to SA
    substitution (so the CRM stage swaps its CCF), and double default then
    beats the SA weight. Basel 3.1 has no double default, so the
    regime cannot express this case; the Basel 3.1 run of the same input is the
    recognised-substitution case below.
    """
    # Arrange
    bundle = _bundle(
        approach="advanced_irb",
        guarantor_entity_type="institution",
        guarantor_cqs=3,
        guarantor_internal_pd=0.0005,
    )

    # Act
    df = _run(bundle, _config("CRR", double_default=True))

    # Assert — adequacy: double default applied on an SA-routed guarantor.
    legs = _guarantor_legs(df)
    assert set(legs["guarantor_approach"].to_list()) == {"sa"}
    assert set(legs["guarantee_status"].to_list()) == {"DOUBLE_DEFAULT"}

    expected_ead = DRAWN + OWN_CCF * UNDRAWN
    covered_ead = COVERED_SHARE * expected_ead
    rw_dd = _single(legs, "guarantor_rw")
    assert float(df["ead_final"].sum()) == pytest.approx(expected_ead, rel=1e-12)
    assert float(legs["rwa_final"].sum()) == pytest.approx(covered_ead * rw_dd, rel=1e-9)
    # DD changes K, not EL: the obligor's EL on the IRB exposure value.
    assert float(df["expected_loss"].sum()) == pytest.approx(
        expected_ead * OBLIGOR_PD * OWN_LGD, rel=1e-9
    )
    # C 08.01 col 0220 reads the protected amount double default is applied to.
    assert float(legs["double_default_unfunded_protection"].sum()) == pytest.approx(
        covered_ead, rel=1e-12
    )


# =============================================================================
# THE LEG THAT DOES NOT MOVE — a recognised SA substitution keeps the SA factor
# =============================================================================


_SA_CCF_MEDIUM_RISK: float = 0.50


@pytest.mark.parametrize(
    ("regime", "approach", "own_ccf"),
    [
        pytest.param("CRR", "foundation_irb", 0.75, id="crr-firb"),
        pytest.param("BASEL_3_1", "foundation_irb", 0.50, id="b31-firb"),
        pytest.param("CRR", "advanced_irb", OWN_CCF, id="crr-airb"),
        pytest.param("BASEL_3_1", "advanced_irb", OWN_CCF, id="b31-airb"),
    ],
)
def test_recognised_sa_substitution_keeps_the_sa_conversion_factor(
    regime: str, approach: str, own_ccf: float
) -> None:
    """A CQS 1 corporate (20%) is beneficial; its covered part stays on Art. 111.

    The two-leg rule of LESSONS B5: this is the leg that must SURVIVE the fix,
    so a fix that simply dropped the swap would redden here.
    """
    # Arrange
    bundle = _bundle(approach=approach, guarantor_cqs=1)

    # Act
    df = _run(bundle, _config(regime))

    # Assert
    legs = _guarantor_legs(df)
    assert set(legs["guarantee_status"].to_list()) == {"SA_RW_SUBSTITUTION"}
    covered_undrawn = COVERED_SHARE * UNDRAWN * _SA_CCF_MEDIUM_RISK
    retained_undrawn = (1.0 - COVERED_SHARE) * UNDRAWN * own_ccf
    assert _undrawn_guarantor_leg(df)["ead_final"] == pytest.approx(covered_undrawn, rel=1e-12)
    assert float(df["ead_final"].sum()) == pytest.approx(
        DRAWN + covered_undrawn + retained_undrawn, rel=1e-12
    )
    covered_ead = COVERED_SHARE * DRAWN + covered_undrawn
    guarantor_rw = _single(legs, "guarantor_rw")
    assert float(
        legs["rwa_pre_floor" if "rwa_pre_floor" in legs.columns else "rwa_final"].sum()
    ) == (pytest.approx(covered_ead * guarantor_rw, rel=1e-9))


@pytest.mark.parametrize(
    "regime",
    [pytest.param("CRR", id="crr"), pytest.param("BASEL_3_1", id="b31")],
)
def test_recognised_sa_substitution_keeps_its_pre_substitution_amounts_on_the_sa_value(
    regime: str,
) -> None:
    """The kept covered leg's pre-substitution IRB amounts sit on its SA-factor value.

    ``rwa_irb_original`` / ``pre_crm_rwa`` / ``expected_loss_irb_original`` are the
    obligor's per-unit figures times the leg's exposure value. The IRB stage runs
    its formulas on the own value and must hand a kept leg back WHOLE — a kept leg
    whose exposure value returned to the SA factor while these stayed on the own
    one would carry a pre-substitution RWEA for an exposure it does not have.
    F-IRB, so the CRR own factor (75%) differs from the SA one (50%).
    """
    # Arrange
    bundle = _bundle(approach="foundation_irb", guarantor_cqs=1)

    # Act
    leg = _undrawn_guarantor_leg(_run(bundle, _config(regime)))

    # Assert
    covered_undrawn = COVERED_SHARE * UNDRAWN * _SA_CCF_MEDIUM_RISK
    assert leg["guarantee_status"] == "SA_RW_SUBSTITUTION"
    assert leg["ead_final"] == pytest.approx(covered_undrawn, rel=1e-12)
    obligor_rw = leg["risk_weight_irb_original"]
    assert leg["rwa_irb_original"] == pytest.approx(covered_undrawn * obligor_rw, rel=1e-9)
    assert leg["pre_crm_rwa"] == pytest.approx(covered_undrawn * obligor_rw, rel=1e-9)
    assert leg["expected_loss_irb_original"] == pytest.approx(
        covered_undrawn * leg["pd_floored"] * leg["lgd_floored"], rel=1e-9
    )
    assert leg["expected_loss"] == pytest.approx(0.0, abs=1e-12)


# =============================================================================
# A SWAP TO ZERO — a CRR 0% SA factor under an A-IRB own CCF (CRR only)
# =============================================================================


_LOW_RISK_OWN_CCF: float = 0.30


def test_swap_to_a_zero_sa_value_leaves_the_leg_on_its_own_value() -> None:
    """A low-risk A-IRB commitment: the CRR SA factor is 0%, the own CCF is 30%.

    The CRM swap prices the covered undrawn leg's cover at ZERO, so no covered
    amount reaches the IRB benefit test and the guarantee cannot be beneficial.
    The swap is also only half-applied there (its own corner, filed separately):
    it zeroes the covered and uncovered portions but leaves the exposure value
    on the own 54,000, because its ``needs_ccf_sub`` predicate re-reads the
    covered portion it has just zeroed. The leg must carry its own exposure
    value, 0.6 x 300,000 x 30% = 54,000, its RWEA and EL on it, portions that add
    up to it, and the CCF that value was built with — before P1.398 the portions
    read 0 + 0 and ``ccf_guaranteed`` the SA 0% beside a 54,000 exposure value.
    Basel 3.1 cannot express the case: no Table A1 factor is below 10%.
    """
    # Arrange
    bundle = _bundle(
        approach="advanced_irb",
        risk_type="low_risk",
        guarantor_cqs=3,
        own_ccf=_LOW_RISK_OWN_CCF,
    )

    # Act
    leg = _undrawn_guarantor_leg(_run(bundle, _config("CRR")))

    # Assert
    expected_leg_ead = COVERED_SHARE * UNDRAWN * _LOW_RISK_OWN_CCF
    assert leg["guarantor_approach"] == "sa"
    assert leg["ead_final"] == pytest.approx(expected_leg_ead, rel=1e-12)
    assert leg["rwa_final"] == pytest.approx(
        expected_leg_ead * leg["risk_weight_irb_original"], rel=1e-9
    )
    assert leg["expected_loss"] == pytest.approx(
        expected_leg_ead * leg["pd_floored"] * leg["lgd_floored"], rel=1e-9
    )
    assert leg["ccf_guaranteed"] == pytest.approx(_LOW_RISK_OWN_CCF, rel=1e-12)
    assert leg["guaranteed_portion"] + leg["unguaranteed_portion"] == pytest.approx(
        expected_leg_ead, rel=1e-12
    )


# =============================================================================
# TWO GUARANTORS — a declined and a recognised one on the same facility
# =============================================================================

_SHARE_DECLINED: float = 0.5
_SHARE_RECOGNISED: float = 0.3
_GTOR_DECL: str = "P1398_GTOR_DECL"
_GTOR_REC: str = "P1398_GTOR_REC"
#: An institution internal PD low enough that double default beats its SA weight.
_DD_GUARANTOR_PD: float = 0.0005


def _two_guarantor_bundle(
    approach: str, *, double_default_guarantor: bool = False
) -> RawDataBundle:
    """The single-guarantor shape with the cover split between two guarantors.

    A CQS 3 corporate covers 50% (declined in both regimes) and a CQS 1 corporate
    30% (recognised, or double default where ``double_default_guarantor`` makes
    it an institution with an internal PD — CRR Art. 202 admits no other
    provider, P1.203); 20% is uncovered. The group holds a
    beneficial and a non-beneficial guarantor row, so ``redistribute_non_
    beneficial`` runs on it and zeroes the declined guarantor's portions.
    """
    is_airb = approach == "advanced_irb"
    guarantors = (
        (_GTOR_DECL, 3, "BBB", _SHARE_DECLINED),
        (_GTOR_REC, 1, "AA", _SHARE_RECOGNISED),
    )

    def _entity_type(ref: str) -> str:
        return "institution" if double_default_guarantor and ref == _GTOR_REC else "corporate"

    def _rating(ref: str, cqs: int, value: str) -> dict[str, Any]:
        if double_default_guarantor and ref == _GTOR_REC:
            return {"rating_type": "internal", "pd": _DD_GUARANTOR_PD, "cqs": cqs}
        return {
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": value,
            "cqs": cqs,
            "pd": None,
        }

    counterparties = [
        make_counterparty(counterparty_reference=_OBLIGOR, entity_type="corporate"),
        *(
            make_counterparty(counterparty_reference=ref, entity_type=_entity_type(ref))
            for ref, _, _, _ in guarantors
        ),
    ]
    ratings = [
        make_rating(
            rating_reference="P1398_R_BORR",
            counterparty_reference=_OBLIGOR,
            pd=OBLIGOR_PD,
            model_id=_MODEL_ID,
        ),
        *(
            make_rating(
                rating_reference=f"P1398_R_{ref}",
                counterparty_reference=ref,
                **_rating(ref, cqs, value),
            )
            for ref, cqs, value, _ in guarantors
        ),
    ]
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=[
            make_loan(
                loan_reference="P1398_LN",
                counterparty_reference=_OBLIGOR,
                drawn_amount=DRAWN,
                interest=0.0,
                lgd=OWN_LGD if is_airb else None,
            )
        ],
        facilities=[
            make_facility(
                facility_reference=_FACILITY,
                counterparty_reference=_OBLIGOR,
                limit=LIMIT,
                risk_type="medium_risk",
                is_revolving=is_airb,
                ccf_modelled=OWN_CCF if is_airb else None,
                lgd=OWN_LGD if is_airb else None,
            )
        ],
        model_permissions=[
            make_model_permission(model_id=_MODEL_ID, exposure_class="corporate", approach=approach)
        ],
        ratings=ratings,
    )
    guarantees = _rows_to_lazyframe(
        [
            {
                "guarantee_reference": f"P1398_G_{ref}",
                "guarantee_type": "guarantee",
                "guarantor": ref,
                "currency": "GBP",
                "maturity_date": date(2030, 12, 31),
                "amount_covered": None,
                "percentage_covered": share,
                "beneficiary_type": "facility",
                "beneficiary_reference": _FACILITY,
                "protection_type": "guarantee",
                "includes_restructuring": True,
            }
            for ref, _, _, share in guarantors
        ],
        GUARANTEE_SCHEMA,
    )
    return dataclasses.replace(bundle, guarantees=seal_raw_table(guarantees, "guarantees"))


@pytest.mark.parametrize(
    ("regime", "approach", "own_ccf"),
    [
        pytest.param("CRR", "foundation_irb", 0.75, id="crr-firb"),
        pytest.param("BASEL_3_1", "advanced_irb", OWN_CCF, id="b31-airb-own-ccf"),
    ],
)
def test_two_guarantors_only_the_recognised_cover_keeps_the_sa_factor(
    regime: str, approach: str, own_ccf: float
) -> None:
    """Declined cover back on the own CCF; recognised cover on the SA 50%.

    Undrawn 300,000: declined 50% = 150,000 x own, recognised 30% = 90,000 x 50%
    = 45,000, uncovered 20% = 60,000 x own. CRR F-IRB: 500,000 + 112,500 + 45,000
    + 45,000 = 702,500 (665,000 before P1.398). Basel 3.1 A-IRB own 80%: 500,000 +
    120,000 + 45,000 + 48,000 = 713,000 (668,000 before). The multi-guarantor
    rows pass through ``redistribute_non_beneficial``, which the single-guarantor
    cases above never reach.

    What this test does NOT assert, and why. ``redistribute_non_beneficial`` does
    move cover onto the recognised leg, on both trees: it measures the CQS 1
    guarantor's headroom as ``original_guarantee_amount`` (90,000, on the
    CCF = 100% basis) less ``guaranteed_portion`` (45,000, post-CCF), so it fills
    45,000 of phantom headroom from the declined guarantor's cover. The recognised
    leg then carries a covered portion of 90,000 on an exposure value of 45,000
    (RWEA 18,000, an effective 40% for a 20% guarantor), while the declined leg
    keeps its whole RWEA — the absorbed amount is counted twice. That is
    ``redistribute_non_beneficial``'s own defect, present before P1.398 (filed as
    a residual), so its outputs are deliberately left unasserted here.
    """
    # Arrange
    bundle = _two_guarantor_bundle(approach)

    # Act
    df = _run(bundle, _config(regime))

    # Assert — adequacy: one declined and one recognised SA-routed covered undrawn leg.
    undrawn = _guarantor_legs(df).filter(pl.col("nominal_amount") > 0)
    by_guarantor = {row["guarantor_reference"]: row for row in undrawn.iter_rows(named=True)}
    assert set(by_guarantor) == {_GTOR_DECL, _GTOR_REC}
    assert set(undrawn["guarantor_approach"].to_list()) == {"sa"}
    declined, recognised = by_guarantor[_GTOR_DECL], by_guarantor[_GTOR_REC]
    assert not declined["is_guarantee_beneficial"]
    assert recognised["guarantee_status"] == "SA_RW_SUBSTITUTION"

    assert declined["ead_final"] == pytest.approx(_SHARE_DECLINED * UNDRAWN * own_ccf, rel=1e-12)
    assert declined["ccf_guaranteed"] == pytest.approx(own_ccf, rel=1e-12)
    assert recognised["ead_final"] == pytest.approx(
        _SHARE_RECOGNISED * UNDRAWN * _SA_CCF_MEDIUM_RISK, rel=1e-12
    )
    uncovered_share = 1.0 - _SHARE_DECLINED - _SHARE_RECOGNISED
    expected_total = DRAWN + UNDRAWN * (
        (_SHARE_DECLINED + uncovered_share) * own_ccf + _SHARE_RECOGNISED * _SA_CCF_MEDIUM_RISK
    )
    assert float(df["ead_final"].sum()) == pytest.approx(expected_total, rel=1e-12)
    # The declined undrawn leg's RWEA is the obligor's weight on its own value
    # (pre-floor under Basel 3.1, as for every Basel 3.1 RWEA assertion here).
    rwa_column = "rwa_pre_floor" if "rwa_pre_floor" in undrawn.columns else "rwa_final"
    assert declined[rwa_column] == pytest.approx(
        declined["ead_final"] * declined["risk_weight_irb_original"], rel=1e-9
    )


# =============================================================================
# A DOUBLE-DEFAULT CO-GUARANTOR — redistribution fills a reverted leg (CRR only)
# =============================================================================


def test_double_default_co_guarantor_keeps_its_own_value_and_stays_within_its_cover() -> None:
    """The double-default leg is reverted to its own value without inflating its cover.

    CRR, A-IRB own CCF 80%, double default enabled. On the undrawn 300,000 the
    CQS 3 corporate covers 50% (declined) and an institution with an internal PD
    of 0.05% covers 30% (no IRB permission for its class, so it routes to SA
    substitution and the CRM stage swaps its CCF; double default then beats the
    institution's SA weight). The group holds a beneficial and a non-beneficial guarantor row, so
    ``redistribute_non_beneficial`` zeroes the declined row and fills the
    double-default row up to its SA-basis headroom (90,000 - 45,000 = 45,000).

    Hand calculation on the own value (CRR Art. 153(3) prices the IRB exposure
    value): double-default leg 0.3 x 300,000 x 80% = 72,000 (45,000 before
    P1.398), declined leg 0.5 x 300,000 x 80% = 120,000 (75,000 before), and the
    C 08.01 col 0220 protected amount is the leg's own covered 72,000 (45,000
    before). The covered portion may never exceed the protection amount GA
    (``original_guarantee_amount``, 90,000; CRR Art. 236(1)/(3)): rebasing the
    absorbed cover by the leg's own/SA factor took it to 144,000 = 2 x its
    exposure value (reviewer finding on the first P1.398 attempt).

    Not asserted: the leg's RWEA and its covered portion against its exposure
    value. Both carry the cover redistribution moved on from the declined row
    (the covered portion is 90,000 on a 72,000 exposure value, on both trees),
    which is ``redistribute_non_beneficial``'s own defect (filed as a residual).
    """
    # Arrange
    bundle = _two_guarantor_bundle("advanced_irb", double_default_guarantor=True)

    # Act
    df = _run(bundle, _config("CRR", double_default=True))

    # Assert — adequacy: an SA-routed double-default leg beside a declined one,
    # in a group redistribution reached (it zeroed the declined row's cover).
    undrawn = _guarantor_legs(df).filter(pl.col("nominal_amount") > 0)
    by_guarantor = {row["guarantor_reference"]: row for row in undrawn.iter_rows(named=True)}
    assert set(by_guarantor) == {_GTOR_DECL, _GTOR_REC}
    assert set(undrawn["guarantor_approach"].to_list()) == {"sa"}
    declined, dd_leg = by_guarantor[_GTOR_DECL], by_guarantor[_GTOR_REC]
    assert dd_leg["guarantee_status"] == "DOUBLE_DEFAULT"
    assert not declined["is_guarantee_beneficial"]
    assert declined["guaranteed_portion"] == 0.0, "redistribution did not reach the group"

    own_dd_leg = _SHARE_RECOGNISED * UNDRAWN * OWN_CCF
    assert dd_leg["ead_final"] == pytest.approx(own_dd_leg, rel=1e-12)
    assert dd_leg["ccf_guaranteed"] == pytest.approx(OWN_CCF, rel=1e-12)
    assert dd_leg["double_default_unfunded_protection"] == pytest.approx(own_dd_leg, rel=1e-12)
    assert dd_leg["guaranteed_portion"] <= dd_leg["original_guarantee_amount"] + 1e-6
    assert declined["ead_final"] == pytest.approx(_SHARE_DECLINED * UNDRAWN * OWN_CCF, rel=1e-12)


# =============================================================================
# THE CHAIN WITHOUT THE RESTORE STEP — the settle step does not depend on it
# =============================================================================


@pytest.mark.parametrize(
    ("regime", "approach", "own_ccf"),
    [
        pytest.param("CRR", "foundation_irb", 0.75, id="crr-firb"),
        pytest.param("BASEL_3_1", "advanced_irb", OWN_CCF, id="b31-airb-own-ccf"),
    ],
)
@pytest.mark.parametrize(
    ("guarantor_cqs", "recognised"),
    [pytest.param(1, True, id="recognised"), pytest.param(3, False, id="declined")],
)
def test_the_transform_chain_without_the_restore_step_settles_the_same_figures(
    monkeypatch: pytest.MonkeyPatch,
    regime: str,
    approach: str,
    own_ccf: float,
    guarantor_cqs: int,
    recognised: bool,
) -> None:
    """A caller composing the documented IRB transforms without the restore step.

    ``IRBCalculator`` runs ``restore_own_irb_exposure_value`` before the formulas;
    the two acceptance files that compose the chain by hand
    (``test_scenario_b31_d7_parameter_substitution.py``,
    ``test_p1_160_art_161_psm_lgd_seniority_routing.py``) skip it, and so may any
    caller of the public transforms. The real IRB input
    frame is captured from a pipeline run and the chain re-run on it WITHOUT that
    step, so the formulas run on the CRM-exit (SA-factor) value of the covered
    undrawn leg. The settle step must still land each leg on its final value with
    every IRB amount on that value:

    - recognised: the SA value 0.6 x 300,000 x 50% = 90,000;
    - declined: the own value 0.6 x 300,000 x own CCF (CRR F-IRB 75%: 135,000;
      Basel 3.1 A-IRB 80%: 144,000).

    The first P1.398 attempt assumed the restore had run: here it put the
    recognised CRR leg's ``rwa_irb_original`` on 44,481.49 instead of 66,722.24
    and left the declined leg's RWEA at 66,722.24 on a 135,000 exposure value
    (reviewer measurement). Before P1.398 the declined leg stayed on 90,000.
    """
    # Arrange
    captured: dict[str, Any] = {}
    run_irb_chain = irb_calculator.IRBCalculator._run_irb_chain

    def _capture(self: Any, exposures: pl.LazyFrame, config: Any, **kwargs: Any) -> Any:
        captured["frame"] = exposures.collect()
        captured["config"] = config
        captured["pack"] = kwargs.get("pack")
        return run_irb_chain(self, captured["frame"].lazy(), config, **kwargs)

    monkeypatch.setattr(irb_calculator.IRBCalculator, "_run_irb_chain", _capture)
    _run(_bundle(approach=approach, guarantor_cqs=guarantor_cqs), _config(regime))
    config, pack = captured["config"], captured["pack"]

    # Act
    result = (
        captured["frame"]
        .lazy()
        .pipe(classify_approach, config)
        .pipe(apply_firb_lgd, config, pack=pack)
        .pipe(prepare_columns, config, pack=pack)
        .pipe(apply_all_formulas, config, pack=pack)
        .pipe(apply_post_model_adjustments, config, pack=pack)
        .pipe(apply_guarantee_substitution, config, pack=pack)
        .collect()
    )

    # Assert
    leg = _undrawn_guarantor_leg(result)
    assert leg["is_guarantee_beneficial"] is recognised
    covered_nominal = COVERED_SHARE * UNDRAWN
    expected_ead = covered_nominal * (_SA_CCF_MEDIUM_RISK if recognised else own_ccf)
    obligor_rw = leg["risk_weight_irb_original"]
    expected_el = expected_ead * leg["pd_floored"] * leg["lgd_floored"]
    assert leg["ead_final"] == pytest.approx(expected_ead, rel=1e-12)
    assert leg["guaranteed_portion"] == pytest.approx(expected_ead, rel=1e-12)
    assert leg["rwa_irb_original"] == pytest.approx(expected_ead * obligor_rw, rel=1e-9)
    assert leg["expected_loss_irb_original"] == pytest.approx(expected_el, rel=1e-9)
    if recognised:
        assert leg["rwa"] == pytest.approx(expected_ead * leg["guarantor_rw"], rel=1e-9)
    else:
        assert leg["rwa"] == pytest.approx(expected_ead * obligor_rw, rel=1e-9)
        assert leg["expected_loss"] == pytest.approx(expected_el, rel=1e-9)


# =============================================================================
# AN OWN ESTIMATE OF EAD — PS1/26 Art. 166D(3) (Basel 3.1 A-IRB only)
# =============================================================================

_OWN_EAD: float = 700_000.0


def test_declined_guarantee_keeps_the_own_estimate_of_ead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The covered commitment leg keeps its share of the Art. 166D(3) own EAD.

    The revolving facility carries ``ead_modelled`` 700,000, above the
    Art. 166D(5)(b) floor. The swap re-valued the 60% covered commitment leg as
    180,000 x SA 50% = 90,000 — it recomputes drawn + nominal x CCF and so drops
    an own EAD altogether (skeptic addition 3 on the premise audit). A declined
    guarantee must leave each commitment leg on its share of the commitment
    row's own exposure value, read here from the same input run WITHOUT the
    guarantee — not the 700,000 itself, so the test does not pin how the engine
    allocates a facility-level own EAD between the drawn loan and the commitment
    (Art. 166D(3)(b); not this item). CRR cannot express the case — the CRR
    engine reads no own EAD.
    """
    # Arrange
    monkeypatch.setitem(_FACILITY_OVERRIDES, "ead_modelled", _OWN_EAD)
    bundle = _bundle(approach="advanced_irb")
    unguaranteed = _run(dataclasses.replace(bundle, guarantees=None), _config("BASEL_3_1"))
    commitment_rows = unguaranteed.filter(pl.col("nominal_amount") > 0)
    assert commitment_rows.height == 1, "expected one commitment row with no guarantee"
    own_commitment_ead = float(commitment_rows["ead_final"][0])
    swapped_leg_ead = COVERED_SHARE * UNDRAWN * _SA_CCF_MEDIUM_RISK
    assert COVERED_SHARE * own_commitment_ead != pytest.approx(swapped_leg_ead), (
        "the own EAD coincides with the swapped value - the test would prove nothing"
    )

    # Act
    df = _run(bundle, _config("BASEL_3_1"))

    # Assert
    leg = _undrawn_guarantor_leg(df)
    assert leg["guarantee_status"] == _DECLINED
    remainder = df.filter(
        (pl.col("nominal_amount") > 0) & pl.col("exposure_reference").str.ends_with("__REM")
    )
    assert leg["ead_final"] == pytest.approx(COVERED_SHARE * own_commitment_ead, rel=1e-12)
    assert float(remainder["ead_final"].sum()) == pytest.approx(
        (1.0 - COVERED_SHARE) * own_commitment_ead, rel=1e-12
    )
    assert leg["rwa_pre_floor"] == pytest.approx(
        COVERED_SHARE * own_commitment_ead * leg["risk_weight_irb_original"], rel=1e-9
    )
