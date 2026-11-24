"""
P1.395 — a guarantor flagged ``is_natural_person`` is not an eligible provider.

Pipeline position:
    ClassifiedExposuresBundle -> CRMProcessor.get_crm_unified_bundle
        -> apply_guarantees (_join_guarantor_counterparty)
        -> assign_guarantor_approach (Art. 201 gate)
        -> record_ineligible_guarantors (CRM013)

Why this exists: P1.384 taught the Art. 201 gate that a natural person is in no
limb of the eligible-provider list, but keyed the test on the guarantor's
``entity_type`` alone (``individual`` / ``natural_person`` / ``retail``). A sole
trader booked ``entity_type='corporate'`` (or ``company`` /
``specialised_lending``) with the counterparty's own ``is_natural_person=True``
was handled as an ordinary corporate: the CRM guarantor join never selected the
flag. With a CQS it took SA risk-weight substitution on SA, slotting and F-IRB
beneficiaries (the Art. 201(1)(g) ECAI limb); with only an internal PD it took
parameter substitution on an F-IRB beneficiary (the Art. 201(2) internal-rating
limb). Both limbs admit "other corporate ENTITIES"; a natural person is not one,
in either regime.

What is pinned, per regime x corporate-class entity type x path:
- the guaranteed leg exists (adequacy - without it every assertion is vacuous);
- ``guarantor_approach`` is ``""`` and ``guarantor_exposure_class`` is ``""``,
  so the covered leg keeps the obligor's class;
- exactly one CRM013 names the guarantor with the NATURAL-PERSON cause and
  reference - not the corporate "without an ECAI credit assessment" cause, which
  would be false for a rated sole trader.

Controls (each shows the flag, and only the guarantor's flag, is the discriminator):
- the same guarantor with the flag False or null keeps 'sa' / 'irb', no CRM013;
- a natural-person OBLIGOR with an unflagged rated corporate guarantor keeps
  'sa' - the obligor's ``cp_is_natural_person`` must not leak into the
  guarantor predicate;
- CRR A-IRB (own-LGD) beneficiary: outside the Art. 201 list (Art. 108(2)), so
  the flagged guarantor's routing is unchanged ('sa' with a CQS, 'irb' with an
  internal PD). The Basel 3.1 A-IRB limb is an open owner decision (P1.394) and
  is deliberately not pinned here;
- a direct ``apply_guarantees`` caller whose counterparty lookup genuinely lacks
  the ``is_natural_person`` column (LESSONS B1: absent, not a typed null) still
  routes a rated corporate to 'sa', with a non-null False eligibility flag.

The gate's means are not its outcome: clearing the class stops substitution only
if the guarantor RW chain then prices nothing. ``TestClearedGuarantorClassPricesNoRiskWeight``
pins that invariant on ``build_guarantor_rw_expr`` for every entity type (its former
CCP branch, keyed on the entity type, priced a declined ``ccp`` guarantor at 2% / 4%;
P1.396 removed it);
``tests/acceptance/test_p1_395_flagged_natural_person_guarantor_pipeline.py`` pins
the end-to-end RWEA.

References:
- CRR Art. 201(1)(g), 201(2), Art. 194(5), Art. 108(2)
- PS1/26 Credit Risk Mitigation (CRR) Part Art. 201(1)(g), 201(2), Art. 194(6)(c)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle, make_counterparty_lookup

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR, CalculationError
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.crm.guarantees import apply_guarantees
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr

_GUARANTOR = "GTOR_SOLE_TRADER"
_BORROWER = "BORROWER01"
_EXPOSURE = "EXP001"
_GUARANTOR_PD = 0.02
_GUARANTOR_CQS = 3

#: Every entity type the engine books into the corporate guarantor class - read
#: off the production map, not hand-listed, so a new corporate alias is covered.
_CORPORATE_ENTITY_TYPES: tuple[str, ...] = tuple(
    sorted(k for k, v in ENTITY_TYPE_TO_SA_CLASS.items() if v == "corporate")
)

#: Beneficiary approaches the Art. 201 ECAI limb governs, with the class each is
#: booked under here (slotting is its own specialised-lending class).
_ECAI_LIMB_APPROACHES: dict[str, str] = {
    "standardised": "corporate",
    "slotting": "specialised_lending",
    "foundation_irb": "corporate",
}

_RATING_SCHEMA: dict[str, Any] = {
    "counterparty_reference": pl.String,
    "cqs": pl.Int8,
    "pd": pl.Float64,
    "internal_pd": pl.Float64,
    "rating_type": pl.String,
}


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.IRB
    )


def _rating(*, cqs: int | None, internal_pd: float | None) -> pl.LazyFrame:
    rating_type = "internal" if internal_pd is not None else "external"
    return pl.LazyFrame(
        [
            {
                "counterparty_reference": _GUARANTOR,
                "cqs": cqs,
                "pd": internal_pd,
                "internal_pd": internal_pd,
                "rating_type": rating_type,
            }
        ],
        schema=_RATING_SCHEMA,
    )


def _run(
    config: CalculationConfig,
    *,
    approach: str,
    exposure_class: str,
    guarantor_entity_type: str,
    guarantor_is_natural_person: bool | None,
    cqs: int | None,
    internal_pd: float | None,
    borrower_is_natural_person: bool = False,
    guarantor_country_code: str | None = None,
) -> tuple[pl.DataFrame, list[CalculationError]]:
    """One 60%-guaranteed exposure through the CRM stage; returns its guaranteed leg."""
    borrower_entity_type = "individual" if borrower_is_natural_person else "corporate"
    exposures = pl.LazyFrame(
        [
            {
                "exposure_reference": _EXPOSURE,
                "counterparty_reference": _BORROWER,
                "exposure_class": exposure_class,
                "approach": approach,
                "drawn_amount": 1000.0,
                "interest": 0.0,
                "nominal_amount": 0.0,
                "risk_type": "MR",
                "lgd": 0.45,
                "seniority": "senior",
                "currency": "GBP",
                "original_currency": "GBP",
                "cp_entity_type": borrower_entity_type,
                "cp_is_natural_person": borrower_is_natural_person,
            }
        ]
    )
    guarantees = pl.LazyFrame(
        [
            {
                "beneficiary_reference": _EXPOSURE,
                "guarantor": _GUARANTOR,
                "amount_covered": 0.0,
                "percentage_covered": 0.6,
            }
        ]
    )
    counterparties = pl.LazyFrame(
        [
            {
                "counterparty_reference": _GUARANTOR,
                "entity_type": guarantor_entity_type,
                "is_natural_person": guarantor_is_natural_person,
                "country_code": guarantor_country_code,
            },
            {
                "counterparty_reference": _BORROWER,
                "entity_type": borrower_entity_type,
                "is_natural_person": borrower_is_natural_person,
                "country_code": "GB",
            },
        ],
        schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
            "is_natural_person": pl.Boolean,
            "country_code": pl.String,
        },
    )
    bundle = make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        counterparty_lookup=make_counterparty_lookup(
            counterparties=counterparties,
            rating_inheritance=_rating(cqs=cqs, internal_pd=internal_pd),
        ),
        collateral=None,
        guarantees=guarantees,
        provisions=None,
    )

    result = CRMProcessor().get_crm_unified_bundle(bundle, config)

    leg = result.exposures.collect().filter(pl.col("guaranteed_portion") > 0)
    crm013 = [e for e in result.crm_errors if e.code == ERROR_INELIGIBLE_GUARANTOR]
    return leg, crm013


def _assert_declined_as_natural_person(
    leg: pl.DataFrame, crm013: list[CalculationError], exposure_class: str, label: str
) -> None:
    assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
    assert leg["guarantor_approach"][0] == "", (
        f"{label}: a guarantor flagged is_natural_person must not route to "
        f"'{leg['guarantor_approach'][0]}' - a natural person is in no Art. 201 limb"
    )
    assert leg["guarantor_exposure_class"][0] == ""
    assert leg["post_crm_exposure_class_guaranteed"][0] == exposure_class
    assert len(crm013) == 1, [e.message for e in crm013]
    assert _GUARANTOR in crm013[0].message
    assert "natural person" in crm013[0].message, crm013[0].message
    assert "without an ECAI credit assessment" not in crm013[0].message
    assert crm013[0].regulatory_reference == "CRR Art. 201(1)"


class TestFlaggedCorporateIsNotAnEligibleProvider:
    """Art. 201(1)(g) and (2) admit corporate ENTITIES; a sole trader is a natural person."""

    def test_corporate_entity_types_are_read_off_the_production_map(self) -> None:
        """Adequacy: the parametrisation below covers the corporate-class bookings."""
        assert {"corporate", "company"} <= set(_CORPORATE_ENTITY_TYPES)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("entity_type", _CORPORATE_ENTITY_TYPES)
    @pytest.mark.parametrize("approach", list(_ECAI_LIMB_APPROACHES))
    def test_ecai_rated_sole_trader_is_declined(
        self, regime: str, entity_type: str, approach: str
    ) -> None:
        """Case A: CQS 3, no internal PD - the ECAI limb no longer admits it."""
        exposure_class = _ECAI_LIMB_APPROACHES[approach]

        leg, crm013 = _run(
            _config(regime),
            approach=approach,
            exposure_class=exposure_class,
            guarantor_entity_type=entity_type,
            guarantor_is_natural_person=True,
            cqs=_GUARANTOR_CQS,
            internal_pd=None,
        )

        _assert_declined_as_natural_person(
            leg, crm013, exposure_class, f"{regime}/{approach}/{entity_type}/CQS"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("entity_type", _CORPORATE_ENTITY_TYPES)
    def test_internally_rated_sole_trader_is_declined_on_firb(
        self, regime: str, entity_type: str
    ) -> None:
        """Case B: internal PD only, F-IRB - the internal-rating limb no longer admits it."""
        leg, crm013 = _run(
            _config(regime),
            approach="foundation_irb",
            exposure_class="corporate",
            guarantor_entity_type=entity_type,
            guarantor_is_natural_person=True,
            cqs=None,
            internal_pd=_GUARANTOR_PD,
        )

        _assert_declined_as_natural_person(
            leg, crm013, "corporate", f"{regime}/foundation_irb/{entity_type}/internal PD"
        )


class TestContradictoryFlaggedNonCorporate:
    """Scope choice: the flag is read whatever the booking, as the classifier reads it.

    A row flagged ``is_natural_person`` but booked ``sovereign`` is contradictory
    input. Art. 201 admits no natural person, so the engine takes the conservative
    reading and declines it - the domestic-currency CGCB short-circuit included -
    and the CRM013 names the contradiction for the user to correct.
    """

    @staticmethod
    def _run_gb_sovereign(regime: str, flag: bool) -> tuple[pl.DataFrame, list[CalculationError]]:
        """A GB sovereign guaranteeing a GBP F-IRB exposure - the Art. 114(4) short-circuit."""
        return _run(
            _config(regime),
            approach="foundation_irb",
            exposure_class="corporate",
            guarantor_entity_type="sovereign",
            guarantor_is_natural_person=flag,
            cqs=1,
            internal_pd=0.0003,
            guarantor_country_code="GB",
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_unflagged_domestic_sovereign_takes_the_short_circuit(self, regime: str) -> None:
        """Adequacy: the domestic-CGCB branch routes 'sa' despite the internal PD."""
        leg, crm013 = self._run_gb_sovereign(regime, flag=False)

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == "sa"
        assert leg["guarantor_exposure_class"][0] == "central_govt_central_bank"
        assert crm013 == []

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_flagged_domestic_sovereign_is_declined(self, regime: str) -> None:
        leg, crm013 = self._run_gb_sovereign(regime, flag=True)

        _assert_declined_as_natural_person(leg, crm013, "corporate", f"{regime}/sovereign")
        assert "entity_type 'sovereign', is_natural_person flag set" in crm013[0].message


class TestTheGuarantorFlagIsTheDiscriminator:
    """Controls: without the guarantor's own flag, routing is what it was."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("flag", [False, None], ids=["flag_false", "flag_null"])
    @pytest.mark.parametrize(
        ("approach", "cqs", "internal_pd", "expected"),
        [
            ("standardised", _GUARANTOR_CQS, None, "sa"),
            ("foundation_irb", _GUARANTOR_CQS, None, "sa"),
            ("foundation_irb", None, _GUARANTOR_PD, "irb"),
        ],
        ids=["sa_cqs", "firb_cqs", "firb_internal_pd"],
    )
    def test_unflagged_corporate_keeps_its_route(
        self,
        regime: str,
        flag: bool | None,
        approach: str,
        cqs: int | None,
        internal_pd: float | None,
        expected: str,
    ) -> None:
        leg, crm013 = _run(
            _config(regime),
            approach=approach,
            exposure_class="corporate",
            guarantor_entity_type="corporate",
            guarantor_is_natural_person=flag,
            cqs=cqs,
            internal_pd=internal_pd,
        )

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == expected
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert crm013 == []

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_natural_person_obligor_does_not_taint_a_rated_corporate_guarantor(
        self, regime: str
    ) -> None:
        """The obligor's ``cp_is_natural_person`` is not the guarantor's flag."""
        leg, crm013 = _run(
            _config(regime),
            approach="standardised",
            exposure_class="retail_other",
            guarantor_entity_type="corporate",
            guarantor_is_natural_person=False,
            cqs=_GUARANTOR_CQS,
            internal_pd=None,
            borrower_is_natural_person=True,
        )

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["cp_is_natural_person"][0] is True, "the obligor is not a natural person"
        assert leg["guarantor_approach"][0] == "sa"
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert crm013 == []


class TestOwnLgdBeneficiaryUnderCrr:
    """CRR Art. 108(2): an own-LGD exposure takes CRM under Chapter 3, not Art. 201."""

    @pytest.mark.parametrize(
        ("cqs", "internal_pd", "expected"),
        [(_GUARANTOR_CQS, None, "sa"), (None, _GUARANTOR_PD, "irb")],
        ids=["cqs", "internal_pd"],
    )
    def test_airb_beneficiary_keeps_its_route(
        self, cqs: int | None, internal_pd: float | None, expected: str
    ) -> None:
        leg, crm013 = _run(
            _config("crr"),
            approach="advanced_irb",
            exposure_class="corporate",
            guarantor_entity_type="corporate",
            guarantor_is_natural_person=True,
            cqs=cqs,
            internal_pd=internal_pd,
        )

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == expected
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert crm013 == []


class TestLookupWithoutTheFlagColumn:
    """A direct ``apply_guarantees`` caller may pass a lookup with no ``is_natural_person``."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_absent_flag_column_reads_as_not_a_natural_person(self, regime: str) -> None:
        exposures = pl.LazyFrame(
            {
                "exposure_reference": [_EXPOSURE],
                "counterparty_reference": [_BORROWER],
                "exposure_class": ["corporate"],
                "approach": ["standardised"],
                "ead_pre_crm": [1000.0],
                "lgd": [0.45],
                "drawn_amount": [1000.0],
                "undrawn_amount": [0.0],
                "nominal_amount": [0.0],
                "risk_type": [None],
                "interest": [0.0],
                "maturity_date": [date(2029, 12, 31)],
                "ead_after_collateral": [1000.0],
                "ead_from_ccf": [0.0],
                "ccf": [1.0],
            }
        )
        guarantees = pl.LazyFrame(
            {
                "guarantee_reference": ["G001"],
                "guarantor": [_GUARANTOR],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 12, 31)],
                "amount_covered": [600.0],
                "percentage_covered": [None],
                "beneficiary_type": ["exposure"],
                "beneficiary_reference": [_EXPOSURE],
            }
        )
        lookup = pl.LazyFrame(
            {"counterparty_reference": [_GUARANTOR], "entity_type": ["corporate"]}
        )
        assert "is_natural_person" not in lookup.collect_schema().names(), (
            "the lookup must genuinely omit the column - a typed null is a different path"
        )

        result = apply_guarantees(
            exposures,
            guarantees,
            lookup,
            _config(regime),
            rating_inheritance=_rating(cqs=_GUARANTOR_CQS, internal_pd=None),
        ).collect()
        leg = result.filter(pl.col("guaranteed_portion") > 0)

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == "sa"
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert leg["_guarantor_ineligible"].to_list() == [False], (
            "the eligibility flag must be a non-null False, never a Kleene null"
        )


class TestClearedGuarantorClassPricesNoRiskWeight:
    """The gate declines by clearing the class; the RW chain must then price nothing.

    ``assign_guarantor_approach`` cannot stop substitution on its own: the SA and IRB
    paths both price the covered leg with ``build_guarantor_rw_expr`` and substitute
    when that RW is lower. The chain's CCP branch was keyed on ``entity_type ==
    "ccp"`` alone, so a declined (class-cleared) CCP-booked guarantor still priced
    2% / 4% and was substituted. That branch is gone (P1.396: a guarantee from a CCP
    takes the institution or corporate weight its Art. 107(2) class gives it); every
    entity type the class map knows is still checked, so a future branch keyed on the
    entity type alone is caught here too.
    """

    @staticmethod
    def _price(entity_type: str, exposure_class: str, *, is_basel_3_1: bool) -> float | None:
        frame = pl.DataFrame(
            {
                "guarantor_exposure_class": [exposure_class],
                "guarantor_entity_type": [entity_type],
                "guarantor_cqs": [1],
                "guarantor_country_code": ["GB"],
                "guarantor_scra_grade": ["A"],
            },
            schema_overrides={"guarantor_cqs": pl.Int8},
        )
        expr = build_guarantor_rw_expr(
            exposure_class_col="guarantor_exposure_class",
            entity_type_col="guarantor_entity_type",
            cqs_col="guarantor_cqs",
            country_code_col="guarantor_country_code",
            scra_grade_col="guarantor_scra_grade",
            is_basel_3_1=is_basel_3_1,
            domestic_cgcb_expr=pl.lit(True),
        )
        return frame.select(expr.alias("rw"))["rw"][0]

    @pytest.mark.parametrize("is_basel_3_1", [False, True], ids=["crr", "b31"])
    def test_unflagged_ccp_is_priced_on_its_class_ladder(self, is_basel_3_1: bool) -> None:
        """Control: with its class in place a CCP guarantor is priced, as its class prices."""
        rw = self._price("ccp", ENTITY_TYPE_TO_SA_CLASS["ccp"], is_basel_3_1=is_basel_3_1)

        assert rw is not None
        assert rw == self._price(
            "institution", ENTITY_TYPE_TO_SA_CLASS["ccp"], is_basel_3_1=is_basel_3_1
        )

    @pytest.mark.parametrize("is_basel_3_1", [False, True], ids=["crr", "b31"])
    @pytest.mark.parametrize("entity_type", sorted(ENTITY_TYPE_TO_SA_CLASS))
    def test_cleared_class_prices_nothing(self, entity_type: str, is_basel_3_1: bool) -> None:
        rw = self._price(entity_type, "", is_basel_3_1=is_basel_3_1)

        assert rw is None, (
            f"a guarantor booked '{entity_type}' whose class the Art. 201 gate cleared "
            f"still prices a {rw} risk weight, so it would be substituted"
        )
