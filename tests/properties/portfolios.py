"""
Portfolio model, builder and cached runner for the property suite.

Pipeline position:
    ExposureSpec -> build_bundle -> PipelineOrchestrator -> AggregatedResultBundle
        -> (optionally) COREPGenerator / Pillar3Generator

Key responsibilities:
- Describe a portfolio as a hashable, shrinkable value (``ExposureSpec``), so a
  Hypothesis counter-example is a literal that can be pasted into a deterministic
  reproducer without a fixture build step.
- Seal it into a ``RawDataBundle`` exactly as the production loader would
  (``tests.fixtures.raw_bundle.make_raw_bundle``), so a property failure is never
  an artefact of a hand-shaped frame.
- Cache runs by ``(portfolio, regime)`` — the perturbation properties re-run the
  same baseline portfolio many times, and a pipeline run is the dominant cost.

Deliberate composition choices:
- Off-balance-sheet nominals are first-class (``off_bs_nominal``), not an
  afterthought. ``.claude/LESSONS.md`` B5 records four C 07.00 defects that
  survived for the template's entire life because the golden portfolio was 100%
  drawn and no data ever reached the conversion-factor columns.
- Retail obligors are generated below the Art. 123 GBP-equivalent EUR 1m limit,
  because above it the classifier correctly reclassifies them to corporate and
  the row is no longer about retail at all.

References:
- CRR Art. 111 / Annex I: off-balance-sheet conversion factors
- CRR Art. 123: retail exposure class limit
- docs/plans/independent-validation-system.md §C2
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The model_id ``create_full_irb_model_permissions`` grants FIRB/AIRB/slotting for.
MODEL_ID = "TEST_FULL_IRB"

#: Origination date, comfortably before every reporting date used here.
VALUE_DATE = date(2015, 1, 1)

#: Regime name -> (framework string, reporting date). ``B31_FLOORED`` uses a
#: post-2030 date so the Art. 92(5) transitional phase-in is complete and the
#: output floor multiplier is the fully-phased-in 72.5%.
REGIMES: dict[str, tuple[str, date]] = {
    "CRR": ("CRR", date(2025, 12, 31)),
    "B31": ("BASEL_3_1", date(2027, 6, 1)),
    "B31_FLOORED": ("BASEL_3_1", date(2030, 6, 30)),
}

#: Entity types that reach a distinct SA exposure class. Kept to obligor types a
#: credit-risk portfolio actually contains; equity / CIU / CCR have their own
#: pipelines and their own fixtures.
#:
#: ``high_risk`` is DELIBERATELY absent, and its absence is a recorded finding
#: rather than a judgement about coverage: a Basel 3.1 ``high_risk`` leg reaches
#: no Pillar 3 CR4 class row, so generating it would make the CR4 footing property
#: fail on most examples instead of once, deterministically, where it is
#: explained. See ``test_template_row_axis.test_cr4_high_risk_leg_reaches_a_class_row``
#: — when that xfail flips, add ``"high_risk"`` here.
SA_ENTITY_TYPES: tuple[str, ...] = (
    "sovereign",
    "institution",
    "corporate",
    "individual",
    "rgla_sovereign",
    "rgla_institution",
    "pse_institution",
    "mdb",
    "mdb_named",
    "international_org",
    "covered_bond",
)

#: Entity types that can additionally route to an IRB approach — the classes
#: ``create_full_irb_model_permissions`` grants (``_IRB_EXPOSURE_CLASSES``).
IRB_ENTITY_TYPES: tuple[str, ...] = ("sovereign", "institution", "corporate", "individual")

#: Off-balance-sheet ``risk_type`` values, one per CRR Annex I / PS1/26 Table A1
#: conversion-factor bucket. ``None`` means the exposure has no off-BS leg.
OFF_BS_RISK_TYPES: tuple[str, ...] = ("FR", "FRC", "MR", "MR_ISSUED", "MLR", "OC", "LR")

#: Art. 123 retail limit is EUR 1m; stay well inside its GBP equivalent so a
#: retail obligor is not silently reclassified to corporate.
RETAIL_MAX_DRAWN = 700_000.0


# ---------------------------------------------------------------------------
# The portfolio value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExposureSpec:
    """One obligor with one drawn leg and, optionally, one off-balance-sheet leg.

    Frozen and hashable so a whole portfolio is a cache key and a Hypothesis
    counter-example prints as a literal.
    """

    entity_type: str = "corporate"
    drawn: float = 1_000_000.0
    off_bs_nominal: float = 0.0
    off_bs_risk_type: str = "MR"
    maturity_years: float = 5.0
    external_cqs: int | None = 3
    internal_pd: float | None = None
    firm_lgd: float | None = None
    annual_revenue: float | None = None
    is_defaulted: bool = False
    country_code: str = "GB"
    collateral_value: float = 0.0
    collateral_type: str = "cash"
    guarantee_amount: float = 0.0
    guarantor_entity_type: str = "sovereign"
    guarantor_cqs: int | None = 1
    provision_amount: float = 0.0
    is_specialised_lending: bool = False
    sl_type: str = "project_finance"


#: A portfolio is an ordered tuple of specs. References are assigned positionally
#: by the builder, so two structurally equal portfolios are the same cache key.
type Portfolio = tuple[ExposureSpec, ...]


def scale_eads(portfolio: Portfolio, k: float) -> Portfolio:
    """Return ``portfolio`` with every monetary amount multiplied by ``k``.

    Collateral, guarantee and provision amounts scale with the exposure — the
    homogeneity property is about a uniformly larger book, not about a book whose
    protection stayed the same size.
    """
    return tuple(
        replace(
            spec,
            drawn=spec.drawn * k,
            off_bs_nominal=spec.off_bs_nominal * k,
            collateral_value=spec.collateral_value * k,
            guarantee_amount=spec.guarantee_amount * k,
            provision_amount=spec.provision_amount * k,
            annual_revenue=spec.annual_revenue,
        )
        for spec in portfolio
    )


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


def build_bundle(portfolio: Portfolio) -> RawDataBundle:
    """Seal ``portfolio`` into a loader-shaped ``RawDataBundle``."""
    counterparties: list[dict] = []
    loans: list[dict] = []
    contingents: list[dict] = []
    ratings: list[dict] = []
    collateral: list[dict] = []
    guarantees: list[dict] = []
    provisions: list[dict] = []
    specialised_lending: list[dict] = []

    for i, spec in enumerate(portfolio):
        cp_ref = f"CP{i:03d}"
        loan_ref = f"LN{i:03d}"
        counterparties.append(_counterparty(cp_ref, spec))
        loans.append(_loan(loan_ref, cp_ref, spec))
        if spec.off_bs_nominal > 0.0:
            contingents.append(_contingent(f"CT{i:03d}", cp_ref, spec))
        rating = _rating(f"RT{i:03d}", cp_ref, spec)
        if rating is not None:
            ratings.append(rating)
        if spec.collateral_value > 0.0:
            collateral.append(_collateral(f"CL{i:03d}", loan_ref, spec))
        if spec.guarantee_amount > 0.0:
            g_ref = f"GCP{i:03d}"
            counterparties.append(_guarantor_counterparty(g_ref, spec))
            guarantor_rating = _guarantor_rating(f"GRT{i:03d}", g_ref, spec)
            if guarantor_rating is not None:
                ratings.append(guarantor_rating)
            guarantees.append(_guarantee(f"GT{i:03d}", g_ref, loan_ref, spec))
        if spec.provision_amount > 0.0:
            provisions.append(_provision(f"PV{i:03d}", loan_ref, spec))
        if spec.is_specialised_lending:
            specialised_lending.append(_specialised_lending(cp_ref, spec))

    return make_raw_bundle(
        counterparties=pl.DataFrame(
            counterparties, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA)
        ),
        loans=pl.DataFrame(loans, schema_overrides=dtypes_of(LOAN_SCHEMA)),
        contingents=_frame_or_none(contingents, CONTINGENTS_SCHEMA),
        ratings=_frame_or_none(ratings, RATINGS_SCHEMA),
        collateral=_frame_or_none(collateral, COLLATERAL_SCHEMA),
        guarantees=_frame_or_none(guarantees, GUARANTEE_SCHEMA),
        provisions=_frame_or_none(provisions, PROVISION_SCHEMA),
        specialised_lending=_frame_or_none(specialised_lending, SPECIALISED_LENDING_SCHEMA),
        model_permissions=create_full_irb_model_permissions(),
    )


def config_for(regime: str) -> CalculationConfig:
    """The ``CalculationConfig`` for a named regime in :data:`REGIMES`.

    ``enforce_retail_granularity=False`` under Basel 3.1 for the reason the
    reporting goldens record: Art. 123A(1)(b)(ii)'s 0.2%-of-portfolio granularity
    limb is unsatisfiable for a compact portfolio, and CRE20.66 leaves it to
    national discretion. With it on, every generated retail obligor reclassifies
    to corporate and the retail properties test nothing.
    """
    _framework, reporting_date = REGIMES[regime]
    if regime == "CRR":
        return CalculationConfig.crr(
            reporting_date=reporting_date, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


@lru_cache(maxsize=96)
def run(portfolio: Portfolio, regime: str) -> AggregatedResultBundle:
    """Run ``portfolio`` under ``regime``, memoised on the pair."""
    return PipelineOrchestrator().run_with_data(build_bundle(portfolio), config_for(regime))


@lru_cache(maxsize=96)
def results_df(portfolio: Portfolio, regime: str) -> pl.DataFrame:
    """The collected aggregator-exit frame for ``portfolio`` under ``regime``."""
    return run(portfolio, regime).results.collect()


@lru_cache(maxsize=16)
def corep_bundle(portfolio: Portfolio, regime: str) -> COREPTemplateBundle:
    """The COREP template bundle for ``portfolio`` under ``regime``, memoised.

    Generation costs an order of magnitude more than a pipeline run, so the cache
    is what makes the template properties affordable in the dev loop.
    """
    framework, _reporting_date = REGIMES[regime]
    return COREPGenerator().generate_from_lazyframe(
        run(portfolio, regime).results, framework=framework
    )


@lru_cache(maxsize=16)
def pillar3_bundle(portfolio: Portfolio, regime: str) -> Pillar3TemplateBundle:
    """The Pillar 3 template bundle for ``portfolio`` under ``regime``, memoised."""
    framework, _reporting_date = REGIMES[regime]
    return Pillar3Generator().generate_from_lazyframe(
        run(portfolio, regime).results, framework=framework
    )


def total_rwa(portfolio: Portfolio, regime: str) -> float:
    """Portfolio total ``rwa_final`` — already post-floor (see LESSONS.md)."""
    return float(results_df(portfolio, regime)["rwa_final"].fill_null(0.0).sum())


def total_ead(portfolio: Portfolio, regime: str) -> float:
    """Portfolio total ``ead_final``."""
    return float(results_df(portfolio, regime)["ead_final"].fill_null(0.0).sum())


def own_funds_requirement(portfolio: Portfolio, regime: str) -> float:
    """8% of TREA plus the Art. 36(1)(d) EL-shortfall CET1 deduction.

    The COMPLETE capital quantity, and the one the monotonicity properties are
    stated on wherever the output floor is in scope. RWEA alone is not the whole
    requirement: an IRB expected-loss shortfall is taken as a CET1 deduction, and
    PS1/26 Art. 92 para 2A's OF-ADJ term subtracts 12.5x that same deduction from
    the floor threshold so the floor comparison stays like-for-like. The two
    cancel here exactly — which is why RWEA alone can FALL as PD rises while the
    capital requirement does not.
    """
    el_summary = run(portfolio, regime).el_summary
    deduction = float(el_summary.cet1_deduction) if el_summary is not None else 0.0
    return 0.08 * total_rwa(portfolio, regime) + deduction


# ---------------------------------------------------------------------------
# Row builders (private)
# ---------------------------------------------------------------------------


def _frame_or_none(rows: list[dict], schema: dict) -> pl.DataFrame | None:
    """A typed frame, or None when the table is empty (the loader's own idiom)."""
    if not rows:
        return None
    return pl.DataFrame(rows, schema_overrides=dtypes_of(schema))


def _counterparty(ref: str, spec: ExposureSpec) -> dict:
    """One obligor row.

    ``is_managed_as_retail`` is attested explicitly rather than left null. PS1/26
    Art. 123A(1)(b)(iii) requires the attestation for a non-SME retail obligor,
    and the loader edge contract gives the column a Boolean default of ``False``
    — so an unset field is a positive "not managed as retail", not the permissive
    null the classifier's own docstring describes. Without it every generated
    natural person reclassifies to corporate under Basel 3.1 and the retail
    properties would silently test corporates.
    """
    is_person = spec.entity_type in ("individual", "natural_person", "retail")
    return {
        "counterparty_reference": ref,
        "counterparty_name": ref,
        "entity_type": spec.entity_type,
        "country_code": spec.country_code,
        "annual_revenue": spec.annual_revenue,
        "is_natural_person": is_person,
        "is_managed_as_retail": is_person,
        "default_status": spec.is_defaulted,
    }


def _guarantor_counterparty(ref: str, spec: ExposureSpec) -> dict:
    return {
        "counterparty_reference": ref,
        "counterparty_name": ref,
        "entity_type": spec.guarantor_entity_type,
        "country_code": "GB",
        "default_status": False,
    }


def _loan(ref: str, cp_ref: str, spec: ExposureSpec) -> dict:
    row: dict = {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "product_type": "term_loan",
        "drawn_amount": spec.drawn,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": _maturity_date(spec),
        "seniority": "senior",
        "is_defaulted": spec.is_defaulted,
    }
    if spec.firm_lgd is not None:
        row["lgd"] = spec.firm_lgd
        row["has_sufficient_collateral_data"] = True
    return row


def _contingent(ref: str, cp_ref: str, spec: ExposureSpec) -> dict:
    return {
        "contingent_reference": ref,
        "counterparty_reference": cp_ref,
        "product_type": "commitment",
        "nominal_amount": spec.off_bs_nominal,
        "risk_type": spec.off_bs_risk_type,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": _maturity_date(spec),
        "bs_type": "OFB",
        "is_defaulted": spec.is_defaulted,
    }


def _rating(ref: str, cp_ref: str, spec: ExposureSpec) -> dict | None:
    """Internal PD (+ model_id) routes IRB; an external CQS routes SA."""
    if spec.internal_pd is not None:
        return {
            "rating_reference": ref,
            "counterparty_reference": cp_ref,
            "rating_type": "internal",
            "pd": spec.internal_pd,
            "model_id": MODEL_ID,
            "rating_date": VALUE_DATE,
        }
    if spec.external_cqs is not None:
        return {
            "rating_reference": ref,
            "counterparty_reference": cp_ref,
            "rating_type": "external",
            "rating_agency": "TEST_AGENCY",
            "cqs": spec.external_cqs,
            "rating_date": VALUE_DATE,
        }
    return None


def _guarantor_rating(ref: str, cp_ref: str, spec: ExposureSpec) -> dict | None:
    if spec.guarantor_cqs is None:
        return None
    return {
        "rating_reference": ref,
        "counterparty_reference": cp_ref,
        "rating_type": "external",
        "rating_agency": "TEST_AGENCY",
        "cqs": spec.guarantor_cqs,
        "rating_date": VALUE_DATE,
    }


def _collateral(ref: str, loan_ref: str, spec: ExposureSpec) -> dict:
    """Fully eligible collateral pledged to one loan.

    Eligibility is attested on both limbs on purpose: ``is_eligible_irb_collateral``
    gates the Art. 199 non-financial route, and a fixture that leaves it unset is
    silently zeroed there (recorded in memory as the P1.235 blast radius).
    """
    return {
        "collateral_reference": ref,
        "collateral_type": spec.collateral_type,
        "currency": "GBP",
        "market_value": spec.collateral_value,
        "nominal_value": spec.collateral_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_ref,
        "issuer_cqs": 1,
        "issuer_type": "sovereign",
        "residual_maturity_years": spec.maturity_years,
        "original_maturity_years": spec.maturity_years,
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        "valuation_date": VALUE_DATE,
        "valuation_type": "market",
    }


def _guarantee(ref: str, guarantor_ref: str, loan_ref: str, spec: ExposureSpec) -> dict:
    """A fully eligible, senior, restructuring-covering guarantee on one loan."""
    return {
        "guarantee_reference": ref,
        "guarantor": guarantor_ref,
        "currency": "GBP",
        "maturity_date": _maturity_date(spec),
        "amount_covered": spec.guarantee_amount,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_ref,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "original_maturity_years": max(spec.maturity_years, 1.0),
        "guarantor_seniority": "senior",
        "is_unilaterally_cancellable": False,
        "is_unilaterally_changeable": False,
    }


def _specialised_lending(cp_ref: str, spec: ExposureSpec) -> dict:
    """Specialised-lending metadata, which moves the obligor to the SL class.

    With no internal rating on the obligor there is no ``model_id``, so the
    slotting permission cannot attach and the leg routes standardised while still
    carrying the ``specialised_lending`` class — the SA specialised-lending shape
    (PS1/26 Art. 122A/122B).
    """
    return {
        "counterparty_reference": cp_ref,
        "sl_type": spec.sl_type,
        "project_phase": "operational",
        "slotting_category": "strong",
        "is_hvcre": False,
    }


def _provision(ref: str, loan_ref: str, spec: ExposureSpec) -> dict:
    return {
        "provision_reference": ref,
        "provision_type": "scra",
        "ifrs9_stage": 3,
        "currency": "GBP",
        "amount": spec.provision_amount,
        "as_of_date": VALUE_DATE,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_ref,
    }


def _maturity_date(spec: ExposureSpec) -> date:
    """Maturity measured from the LATEST reporting date, so residual maturity is
    the same under every regime and a cross-regime comparison is like-for-like."""
    latest = max(reporting for _framework, reporting in REGIMES.values())
    return latest + timedelta(days=int(round(365.25 * spec.maturity_years)))
