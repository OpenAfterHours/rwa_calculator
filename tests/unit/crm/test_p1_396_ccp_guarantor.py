"""
P1.396 — a CCP guarantor is an institution (QCCP) or a corporate (non-QCCP), never 2% / 4%.

Pipeline position:
    ClassifiedExposuresBundle -> CRMProcessor.get_crm_unified_bundle
        -> apply_guarantees (_join_guarantor_counterparty: guarantor_is_qccp)
        -> assign_guarantor_approach (Art. 107(2) class, Art. 201 gate)
        -> record_ineligible_guarantors (CRM013)
    -> SA / slotting / IRB guarantee substitution (build_guarantor_rw_expr)

Why this exists: ``build_guarantor_rw_expr`` gave every guarantor booked
``entity_type='ccp'`` the CCR (CRR) Part Art. 306(1) trade-exposure weight - 2%, or
4% when the guarantor's counterparty row said client-cleared - ahead of the
institution and corporate branches, and nothing read ``is_qccp``. A guarantee is not
a trade exposure. Art. 235(1) prices the covered part at the SA weight of a
(comparable) direct exposure to the provider, and Art. 107(2) (CRR and PS1/26,
identical) sends only trade exposures and default-fund contributions to Section 9:
"(a) as exposures to an institution for other types of exposures to a qualifying
CCP; (b) as exposures to a corporate for other types of exposures to a
non-qualifying CCP". Art. 201(1)(h) admits qualifying CCPs; a non-qualifying one is
an "other corporate entity", eligible only under (1)(g) (ECAI assessment) or, on the
parameter-substitution path, (2) / CRR (1)(g)(ii) (internal rating).

What is pinned, per regime (each regime red on its own at HEAD):
- QCCP: class ``institution``, route 'sa', no CRM013, and the RW chain prices it on
  the institution ladder exactly as a guarantor booked ``institution``.
- Non-QCCP (flag False, explicit null, or column absent from the lookup): class
  ``corporate``; with a CQS it routes 'sa' and is priced on the corporate ladder;
  unrated and with no internal rating it is declined (class and route cleared) with
  one CRM013 that names the non-qualifying CCP - on SA and slotting beneficiaries.
- Slotting reuses the SA substitution: a QCCP on a slotting leg takes the
  institution weight.

Weights are read from the pack, never typed (LESSONS A4).

References:
- CRR Art. 107(2), 201(1)(f)-(h), 235(1); PS1/26 Art. 107(2), CRM (CRR) Part
  Art. 194(6)(c), 201(1)-(2), 235(1)(a)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle, make_counterparty_lookup

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR, CalculationError
from rwa_calc.domain.enums import CQS, PermissionMode
from rwa_calc.engine.crm.guarantees import apply_guarantees
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.sa.rw_adjustments import (
    apply_guarantee_substitution as sa_apply_guarantee_substitution,
)
from rwa_calc.engine.slotting.transforms import (
    apply_guarantee_substitution as slotting_apply_guarantee_substitution,
)
from rwa_calc.rulebook.resolve import resolve

_GUARANTOR = "GTOR_CCP"
_BORROWER = "BORROWER01"
_EXPOSURE = "EXP001"
_REGIMES = ["crr", "b31"]

_RATING_SCHEMA: dict[str, Any] = {
    "counterparty_reference": pl.String,
    "cqs": pl.Int8,
    "pd": pl.Float64,
    "internal_pd": pl.Float64,
    "rating_type": pl.String,
}

#: Beneficiary approaches reached by SA risk-weight substitution, with the class each
#: is booked under here (slotting is its own specialised-lending class).
_RWSM_APPROACHES: dict[str, str] = {
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


def _pack_weight(regime: str, ladder: str, cqs: int) -> float:
    """The SA weight of a direct exposure at ``cqs`` on ``ladder``, from the regime's pack."""
    if regime == "crr":
        pack = resolve("crr", date(2025, 12, 31))
        name = "institution_rw_crr" if ladder == "institution" else "corporate_risk_weights"
        entries: dict[object, Decimal] = dict(pack.lookup(name).entries)
        return float(entries[CQS(cqs)])
    pack = resolve("b31", date(2027, 6, 1))
    if ladder == "institution":
        entries = dict(pack.lookup("institution_rw_b31_ecra").entries)
        return float(entries[CQS(cqs)])
    entries = dict(pack.lookup("b31_corporate_risk_weights").entries)
    return float(entries[cqs])


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
    is_qccp: bool | None,
    cqs: int | None,
    internal_pd: float | None = None,
    approach: str = "standardised",
    exposure_class: str = "corporate",
) -> tuple[pl.DataFrame, list[CalculationError]]:
    """One 60%-guaranteed exposure through the CRM stage; returns its guaranteed leg."""
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
                "cp_entity_type": "corporate",
                "cp_is_natural_person": False,
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
                "entity_type": "ccp",
                "is_qccp": is_qccp,
                "is_ccp_client_cleared": True,
                "country_code": "GB",
            },
            {
                "counterparty_reference": _BORROWER,
                "entity_type": "corporate",
                "is_qccp": None,
                "is_ccp_client_cleared": None,
                "country_code": "GB",
            },
        ],
        schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
            "is_qccp": pl.Boolean,
            "is_ccp_client_cleared": pl.Boolean,
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


def _price(
    *, entity_type: str, exposure_class: str, cqs: int | None, config: CalculationConfig
) -> float | None:
    """The guarantor RW the SA substitution step prices for one fully covered row."""
    frame = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [2.0],
            "guaranteed_portion": [1_000_000.0],
            "unguaranteed_portion": [0.0],
            "guarantor_entity_type": [entity_type],
            "guarantor_exposure_class": [exposure_class],
            "guarantor_cqs": [cqs],
            "guarantor_country_code": ["GB"],
            "guarantor_scra_grade": ["A"],
            "currency": ["GBP"],
        },
        schema_overrides={"guarantor_cqs": pl.Int8},
    )
    return sa_apply_guarantee_substitution(frame, config).collect()["guarantor_rw"][0]


class TestQualifyingCcpIsAnInstitutionProvider:
    """Art. 201(1)(h) admits it; Art. 107(2)(a) makes the covered part an institution exposure."""

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize("approach", list(_RWSM_APPROACHES))
    def test_qccp_keeps_the_institution_class_and_the_sa_route(
        self, regime: str, approach: str
    ) -> None:
        leg, crm013 = _run(
            _config(regime),
            is_qccp=True,
            cqs=2,
            approach=approach,
            exposure_class=_RWSM_APPROACHES[approach],
        )

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_exposure_class"][0] == "institution"
        assert leg["guarantor_approach"][0] == "sa"
        assert leg["post_crm_exposure_class_guaranteed"][0] == "institution"
        assert crm013 == []

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize("cqs", [1, 2, 3, 6])
    def test_ccp_is_priced_as_any_institution_booking_of_its_class(
        self, regime: str, cqs: int
    ) -> None:
        """No entity-type override: a 'ccp' row prices exactly as an 'institution' row."""
        config = _config(regime)
        assert ENTITY_TYPE_TO_SA_CLASS["ccp"] == "institution"

        rw = _price(entity_type="ccp", exposure_class="institution", cqs=cqs, config=config)

        assert rw == pytest.approx(_pack_weight(regime, "institution", cqs))
        assert rw == _price(
            entity_type="institution", exposure_class="institution", cqs=cqs, config=config
        )

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_demoted_ccp_is_priced_on_the_corporate_ladder(self, regime: str) -> None:
        rw = _price(entity_type="ccp", exposure_class="corporate", cqs=3, config=_config(regime))

        assert rw == pytest.approx(_pack_weight(regime, "corporate", 3))

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_slotting_leg_takes_the_institution_weight(self, regime: str) -> None:
        """Slotting reuses the SA substitution, so it inherits the corrected chain."""
        config = _config(regime)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["SL001__G_GTOR_CCP"],
                "ead_final": [1_000_000.0],
                "risk_weight": [1.15],
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["ccp"],
                "guarantor_exposure_class": ["institution"],
                "guarantor_cqs": [2],
                "guarantor_country_code": ["GB"],
                "currency": ["GBP"],
            },
            schema_overrides={"guarantor_cqs": pl.Int8},
        )

        result = frame.pipe(slotting_apply_guarantee_substitution, config).collect()

        assert result["guarantor_rw"][0] == pytest.approx(_pack_weight(regime, "institution", 2))


class TestNonQualifyingCcpIsACorporateProvider:
    """Art. 107(2)(b): an ``other corporate entity``, eligible only under Art. 201(1)(g)/(2)."""

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize("is_qccp", [False, None], ids=["flag_false", "flag_null"])
    def test_rated_non_qccp_is_a_corporate_on_the_sa_route(
        self, regime: str, is_qccp: bool | None
    ) -> None:
        leg, crm013 = _run(_config(regime), is_qccp=is_qccp, cqs=3)

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert leg["guarantor_approach"][0] == "sa"
        assert leg["post_crm_exposure_class_guaranteed"][0] == "corporate"
        assert crm013 == []

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize("approach", list(_RWSM_APPROACHES))
    def test_unrated_non_qccp_is_declined(self, regime: str, approach: str) -> None:
        exposure_class = _RWSM_APPROACHES[approach]

        leg, crm013 = _run(
            _config(regime),
            is_qccp=False,
            cqs=None,
            approach=approach,
            exposure_class=exposure_class,
        )

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_approach"][0] == ""
        assert leg["guarantor_exposure_class"][0] == ""
        assert leg["post_crm_exposure_class_guaranteed"][0] == exposure_class
        assert len(crm013) == 1, [e.message for e in crm013]
        assert _GUARANTOR in crm013[0].message
        assert "not a qualifying central counterparty" in crm013[0].message, crm013[0].message
        assert crm013[0].regulatory_reference == "CRR Art. 201(1)(h)"

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_internally_rated_non_qccp_on_firb_takes_parameter_substitution(
        self, regime: str
    ) -> None:
        """Art. 201(2) / CRR 201(1)(g)(ii): the internal-rating limb admits it as a corporate."""
        leg, crm013 = _run(
            _config(regime),
            is_qccp=False,
            cqs=None,
            internal_pd=0.01,
            approach="foundation_irb",
        )

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert leg["guarantor_approach"][0] == "irb"
        assert crm013 == []

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_lookup_without_the_flag_column_reads_as_non_qualifying(self, regime: str) -> None:
        """A direct caller's lookup may omit ``is_qccp`` (LESSONS B1: absent, not a typed null)."""
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
        lookup = pl.LazyFrame({"counterparty_reference": [_GUARANTOR], "entity_type": ["ccp"]})
        assert "is_qccp" not in lookup.collect_schema().names(), (
            "the lookup must genuinely omit the column - a typed null is a different path"
        )

        result = apply_guarantees(
            exposures,
            guarantees,
            lookup,
            _config(regime),
            rating_inheritance=_rating(cqs=3, internal_pd=None),
        ).collect()
        leg = result.filter(pl.col("guaranteed_portion") > 0)

        assert leg.height == 1, "no guaranteed leg - every assertion below would be vacuous"
        assert leg["guarantor_exposure_class"][0] == "corporate"
        assert leg["guarantor_approach"][0] == "sa"
        assert leg["_guarantor_ineligible"].to_list() == [False], (
            "the eligibility flag must be a non-null False, never a Kleene null"
        )
