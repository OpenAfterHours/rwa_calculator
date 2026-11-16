"""
P1.384 — a natural person is not an eligible provider of unfunded credit protection.

Pipeline position:
    ClassifiedExposuresBundle -> CRMProcessor.get_crm_unified_bundle
        -> apply_guarantees -> assign_guarantor_approach (Art. 201 gate)
        -> record_ineligible_guarantors (CRM013)

Why this exists: the P1.227 Art. 201 gate covered CORPORATE guarantors only and
let every other guarantor class through. A natural person (entity_type
``individual`` / ``natural_person`` / ``retail`` -> guarantor class
``retail_other``) is in no limb of the Art. 201 list in either regime. On an
F-IRB beneficiary whose guarantor carries an internal PD the engine applied
parameter substitution at the person's retail PD, so capital fell (registered
portfolio crm-substitution, leg S2). On SA and slotting beneficiaries the same
guarantee was declined only because the SA guarantor-RW builder has no retail
branch, silently and without a CRM013. P1.227 probed the natural person on an SA
beneficiary only (its G5) and generalised from there.

What is pinned, per regime x natural-person alias x beneficiary approach (SA,
slotting, F-IRB):
- the guaranteed leg exists (adequacy - without it every assertion is vacuous);
- ``guarantor_approach`` is ``""`` - in particular NOT ``"irb"``, which is the
  half-fix that clears the class but leaves parameter substitution running;
- ``guarantor_exposure_class`` is ``""`` and the covered leg keeps the obligor's
  class;
- exactly one CRM013 names the guarantor, with the natural-person cause.

Control: under CRR an A-IRB (own-LGD) beneficiary is outside the Art. 201 list
altogether - CRR Art. 108(2) routes it to Chapter 3 (Art. 161(3), 164(2),
183), where the firm specifies the guarantor types it recognises - so its
natural-person guarantee keeps parameter substitution and raises no CRM013.

References:
- CRR Art. 201(1)/(2), Art. 194(5), Art. 108(1)/(2)
- PS1/26 Credit Risk Mitigation (CRR) Part Art. 201(1)/(2), Art. 194(A1)/(6)(c)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle, make_counterparty_lookup

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR, CalculationError
from rwa_calc.data.schemas import NATURAL_PERSON_ENTITY_TYPES
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

_GUARANTOR = "GTOR_NP"
_EXPOSURE = "EXP001"
_GUARANTOR_PD = 0.02

#: The beneficiary approaches the Art. 201 list governs, with the exposure class
#: each is booked under here (slotting is its own specialised-lending class).
_GATED_APPROACHES: dict[str, str] = {
    "foundation_irb": "corporate",
    "standardised": "corporate",
    "slotting": "specialised_lending",
}


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.IRB
    )


def _run(
    config: CalculationConfig, approach: str, exposure_class: str, guarantor_entity_type: str
) -> tuple[pl.DataFrame, list[CalculationError]]:
    """One 60%-guaranteed exposure whose guarantor carries an internal PD.

    The internal PD and the firm's retail IRB permission are what route an IRB
    beneficiary's natural-person guarantor to parameter substitution today.
    """
    exposures = pl.LazyFrame(
        [
            {
                "exposure_reference": _EXPOSURE,
                "counterparty_reference": "BORROWER01",
                "exposure_class": exposure_class,
                "approach": approach,
                "drawn_amount": 1000.0,
                "interest": 0.0,
                "nominal_amount": 0.0,
                "risk_type": "MR",
                "lgd": 0.45,
                "seniority": "senior",
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
            {"counterparty_reference": _GUARANTOR, "entity_type": guarantor_entity_type},
            {"counterparty_reference": "BORROWER01", "entity_type": "corporate"},
        ]
    )
    ratings = pl.LazyFrame(
        [
            {
                "counterparty_reference": _GUARANTOR,
                "cqs": None,
                "pd": _GUARANTOR_PD,
                "internal_pd": _GUARANTOR_PD,
                "rating_type": "internal",
            }
        ],
        schema={
            "counterparty_reference": pl.String,
            "cqs": pl.Int8,
            "pd": pl.Float64,
            "internal_pd": pl.Float64,
            "rating_type": pl.String,
        },
    )
    bundle = make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        counterparty_lookup=make_counterparty_lookup(
            counterparties=counterparties,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=ratings,
        ),
        collateral=None,
        guarantees=guarantees,
        provisions=None,
    )

    result = CRMProcessor().get_crm_unified_bundle(bundle, config)

    leg = result.exposures.collect().filter(pl.col("guaranteed_portion") > 0)
    crm013 = [e for e in result.crm_errors if e.code == ERROR_INELIGIBLE_GUARANTOR]
    return leg, crm013


class TestNaturalPersonIsNotAnEligibleProvider:
    """Art. 201(1)/(2) name no natural person, in either regime."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("entity_type", NATURAL_PERSON_ENTITY_TYPES)
    @pytest.mark.parametrize("approach", list(_GATED_APPROACHES))
    def test_guarantee_is_not_recognised(
        self, regime: str, entity_type: str, approach: str
    ) -> None:
        """The leg routes nowhere, keeps the obligor's class, and names the cause."""
        exposure_class = _GATED_APPROACHES[approach]

        leg, crm013 = _run(_config(regime), approach, exposure_class, entity_type)

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == "", (
            f"{regime}/{approach}/{entity_type}: a natural person must not route to "
            f"'{leg['guarantor_approach'][0]}' - 'irb' here means parameter substitution "
            "still runs at the person's retail PD"
        )
        assert leg["guarantor_exposure_class"][0] == ""
        assert leg["post_crm_exposure_class_guaranteed"][0] == exposure_class
        assert len(crm013) == 1, [e.message for e in crm013]
        assert _GUARANTOR in crm013[0].message
        assert "natural person" in crm013[0].message
        assert crm013[0].regulatory_reference == "CRR Art. 201(1)"


class TestOwnLgdBeneficiaryUnderCrr:
    """CRR Art. 108(2): an own-LGD exposure takes CRM under Chapter 3, not Art. 201."""

    def test_airb_beneficiary_keeps_parameter_substitution(self) -> None:
        """Art. 161(3) / 164(2) / 183 - the firm specifies the guarantor types it recognises."""
        leg, crm013 = _run(_config("crr"), "advanced_irb", "corporate", "individual")

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == "irb"
        assert leg["guarantor_exposure_class"][0] == "retail_other"
        assert crm013 == []
