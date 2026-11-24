"""
Art. 201 protection-provider eligibility and guarantor-approach routing.

Pipeline position:
    apply_guarantees (guarantor joins)
        -> assign_guarantor_approach (Art. 107(2) CCP class, routing + Art. 201 gate)
        -> CRMProcessor crm_exit edge
        -> record_ineligible_guarantors (CRM013)

Key responsibilities:
- Book a CCP guarantor in the class Art. 107(2) gives an exposure to it that is
  not a trade exposure: institution for a qualifying CCP, corporate for any other
  (``demote_non_qualifying_ccp_guarantors``)
- Route each guaranteed leg to IRB parameter substitution, SA risk-weight
  substitution, or no substitution (``guarantor_approach``)
- Apply the Art. 201 eligible-provider gate (unrated corporates, non-qualifying
  CCPs among them, and natural persons), clearing the guarantor class and
  approach of a rejected leg so it reverts to the borrower's own basis
- Name every rejected guarantor in one CRM013 warning per leg

Kept out of ``guarantees.py``, following ``min_collateralisation.py``: that module
sits at the engine module-size ceiling tracked by ``scripts/arch_check.py``, and
the eligibility gate has no dependency on the split and allocation machinery
there.

References:
    CRR Art. 107(2) / PS1/26 Art. 107(2): an exposure to a CCP that is not a trade
        exposure or a default-fund contribution is an exposure to an institution
        (qualifying CCP) or to a corporate (non-qualifying CCP)
    CRR Art. 201: eligibility of protection providers under all approaches
    CRR Art. 194(5): only an Art. 201 provider is an eligible protection provider
    CRR Art. 108(2): own-LGD (A-IRB) exposures take CRM under Chapter 3 instead
    PS1/26 Credit Risk Mitigation (CRR) Part Art. 201: eligible providers under
        the Risk-Weight Substitution and Parameter Substitution Methods
    PS1/26 Credit Risk Mitigation (CRR) Part Art. 194(6)(c): the provider must be
        of a kind listed in Art. 201
    CRR Art. 114(4)/(7), Art. 235(3): domestic-currency CGCB guarantor short-circuit
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR, crm_warning
from rwa_calc.data.schemas import NATURAL_PERSON_ENTITY_TYPES
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    denomination_currency_expr,
    funding_currency_expr,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


@cites("CRR Art. 201")
@cites("CRR Art. 194")
@cites("CRR Art. 108")
@cites("PS1/26, paragraph 201")
@cites("PS1/26, paragraph 194")
def assign_guarantor_approach(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    present: list[str] | None = None,
) -> pl.LazyFrame:
    """
    Determine guarantor approach (IRB / SA) and rating provenance.

    A guarantor is treated under IRB only if:
    1. The beneficiary exposure is itself on FIRB/AIRB (CRR Art. 161 /
       Basel 3.1 CRE22.70-85: parameter substitution applies only to IRB
       beneficiaries; SA beneficiaries always substitute via guarantor's
       SA risk weight regardless of the guarantor's internal rating —
       SLOTTING beneficiaries are deliberately excluded, so the Art. 201(2)
       internal-rating eligibility limb does not reach them either), AND
    2. The firm has IRB permission for the guarantor's exposure class, AND
    3. The guarantor has an internal rating (PD) — indicating the firm
       actively rates this counterparty under its IRB model.
    Counterparties with only external ratings (CQS) are treated under SA.

    CRR/PS1-26 Art. 201 eligibility gate — two limbs, one flag:

    - CORPORATE (Art. 201(1)(g)/(2)): eligible only if it has an ECAI credit
      assessment (``guarantor_cqs``) or — Art. 201(2), IRB-beneficiary-only — an
      internal rating (``guarantor_internal_pd``) when the beneficiary is itself
      IRB.
    - NATURAL PERSON (the guarantor's own ``is_natural_person`` flag, joined as
      ``guarantor_is_natural_person``, OR ``guarantor_entity_type`` in
      ``data.schemas.NATURAL_PERSON_ENTITY_TYPES`` — the classifier's
      ``natural_person_expr`` signal, read on the guarantor rather than the
      obligor): in no limb of Art. 201(1) or (2) in either regime, so never
      eligible — on an SA, slotting or F-IRB beneficiary alike. The flag decides
      whatever the booking: a sole trader booked ``corporate`` / ``company`` /
      ``specialised_lending`` is not one of the "other corporate entities" of
      Art. 201(1)(g)/(2), so neither its CQS nor its internal rating admits it
      (P1.395). A flagged row booked under any other entity type (``sovereign``,
      ``institution``, ``ccp``, ...) is contradictory input and is declined too,
      domestic-CGCB short-circuit included — the conservative reading, surfaced
      by its CRM013. CRR Art. 194(5) and PS1/26 Art. 194(6)(c) make the
      Art. 201 list a precondition for recognising unfunded protection. The one
      carve-out is an A-IRB (own-LGD) beneficiary: CRR Art. 108(2) routes its CRM
      to Chapter 3 (Art. 161(3) / 164(2) / 183, firm-specified guarantor types),
      outside the Art. 201 list, so it keeps parameter substitution. The engine
      applies the same carve-out under Basel 3.1 pending an owner decision on the
      PS1/26 reading (Art. 194(A1) binds the Parameter Substitution Method to
      Art. 201; the LGD Adjustment Method that admits retail guarantors,
      Art. 183(1)(c), is not implemented).

    A CCP guarantor is first booked in its Art. 107(2) class
    (:func:`demote_non_qualifying_ccp_guarantors`): a qualifying CCP stays
    ``institution`` and is admitted by Art. 201(1)(h); any other CCP becomes
    ``corporate`` and so meets the corporate limb above — eligible with an ECAI
    assessment, or an internal rating on an IRB beneficiary, and otherwise
    declined (P1.396).

    A rejected guarantor takes guarantor approach ``""`` — on BOTH the SA fallback
    and the IRB branch, since clearing the class alone would leave parameter
    substitution running — and its ``guarantor_exposure_class`` is cleared. Both
    substitution paths price the covered leg with
    ``engine/sa/guarantor_rw.py::build_guarantor_rw_expr``, which prices nothing
    for an empty class (its named-MDB branch, which also reads the entity type,
    requires a class too), so the leg is never beneficially substituted and stays
    on the borrower's own basis: SA risk weight, IRB PD / LGD and the output-floor
    SA-equivalent alike. The leg is flagged on ``_guarantor_ineligible`` for
    :func:`record_ineligible_guarantors` (CRM013). The other listed classes
    (sovereign, RGLA, MDB, international organisation, PSE, institution —
    qualifying CCPs included) are not gated here, except a row flagged a natural
    person (above).
    """
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    irb_exposure_class_values = {
        ec.value
        for ec, approaches in config.irb_permissions.permissions.items()  # ty: ignore[unresolved-attribute]
        if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches
    }

    irb_beneficiary_approaches = [ApproachType.FIRB.value, ApproachType.AIRB.value]
    schema_names = list(present) if present is not None else exposures.collect_schema().names()
    beneficiary_approach = (
        pl.col("approach").fill_null("") if "approach" in schema_names else pl.lit("")
    )
    beneficiary_is_irb = beneficiary_approach.is_in(irb_beneficiary_approaches)

    exposures = demote_non_qualifying_ccp_guarantors(exposures)
    is_domestic_cgcb_guarantor = _build_domestic_cgcb_flag(schema_names)

    # Art. 201 gate. All inputs are non-null booleans (is_not_null / == on the
    # default-"" class and approach / is_in on the entity type apply_guarantees
    # fills with "" / eq_missing on the nullable natural-person flag), so no
    # Kleene-null leaks into the gate. The class column can only ever say
    # "corporate" (never "corporate_sme" — the entity->SA-class map has no such
    # entity_type; SME-ness is derived later).
    is_corporate_guarantor = pl.col("guarantor_exposure_class") == "corporate"
    corporate_eligible = pl.col("guarantor_cqs").is_not_null() | (
        beneficiary_is_irb & pl.col("guarantor_internal_pd").is_not_null()
    )
    # The GUARANTOR's own flag (joined by apply_guarantees), never the obligor's
    # ``cp_is_natural_person``; a null flag (unmatched guarantor) is not flagged.
    flagged_natural_person = pl.col("guarantor_is_natural_person").eq_missing(True)
    is_natural_person_guarantor = flagged_natural_person | pl.col("guarantor_entity_type").is_in(
        list(NATURAL_PERSON_ENTITY_TYPES)
    )
    outside_art_201 = beneficiary_approach == ApproachType.AIRB.value
    declined_as_natural_person = is_natural_person_guarantor & outside_art_201.not_()
    guarantor_ineligible = (
        (is_corporate_guarantor & corporate_eligible.not_()) | declined_as_natural_person
    ) & (pl.col("guaranteed_portion") > 0)

    return exposures.with_columns(
        # A flagged CGCB is contradictory input; declined like any natural person.
        pl.when(is_domestic_cgcb_guarantor & guarantor_ineligible.not_())
        .then(pl.lit("sa"))
        .when(
            beneficiary_is_irb
            & (pl.col("guarantor_exposure_class") != "")
            & pl.col("guarantor_exposure_class").is_in(list(irb_exposure_class_values))
            & pl.col("guarantor_internal_pd").is_not_null()
            & guarantor_ineligible.not_()
        )
        .then(pl.lit("irb"))
        # SA fallback — gated: an ineligible guarantor takes "" (the existing
        # no-substitution value) rather than "sa".
        .when((pl.col("guarantor_exposure_class") != "") & guarantor_ineligible.not_())
        .then(pl.lit("sa"))
        .otherwise(pl.lit(""))
        .alias("guarantor_approach"),
        # Audit: track whether guarantor approach was derived from internal or
        # external rating (spec output field per CRR Art. 153(3) / Art. 233A).
        pl.when(pl.col("guarantor_internal_pd").is_not_null())
        .then(pl.lit("internal"))
        .when(pl.col("guarantor_cqs").is_not_null())
        .then(pl.lit("external"))
        .otherwise(pl.lit(None).cast(pl.String))
        .alias("guarantor_rating_type"),
        # Explicit revert (Art. 201): clear the guarantor class for an ineligible
        # guarantor so ``build_guarantor_rw_expr`` returns null -> non-beneficial
        # -> the covered leg reverts to the borrower's own basis. Mirrors the
        # existing unmapped-guarantor (class "") no-substitution path. This holds
        # only because every branch of that chain requires a non-empty class;
        # pinned per entity type by the P1.395 unit and pipeline tests.
        pl.when(guarantor_ineligible)
        .then(pl.lit(""))
        .otherwise(pl.col("guarantor_exposure_class"))
        .alias("guarantor_exposure_class"),
        # Scratch for the processor's CRM013 recorder (stripped by the exit seal):
        # the decline, and which limb made it, decided here once.
        guarantor_ineligible.alias("_guarantor_ineligible"),
        declined_as_natural_person.alias("_guarantor_declined_as_natural_person"),
        (guarantor_ineligible & declined_as_natural_person.not_() & _is_ccp_guarantor()).alias(
            "_guarantor_declined_as_non_qualifying_ccp"
        ),
    )


@cites("CRR Art. 107")
@cites("PS1/26, paragraph 107")
def demote_non_qualifying_ccp_guarantors(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Book a CCP guarantor that is not a qualifying CCP in the corporate class.

    A guarantee is not a trade exposure or a default-fund contribution, so the
    Section 9 (Art. 306) weights never reach it. CRR Art. 107(2) = PS1/26
    Art. 107(2): "For all other types of exposures to a central counterparty,
    institutions shall treat those exposures as follows: (a) as exposures to an
    institution for other types of exposures to a qualifying CCP; (b) as exposures
    to a corporate for other types of exposures to a non-qualifying CCP." The
    run pack's entity map books ``ccp`` as ``institution``, which is limb (a);
    this moves every other CCP guarantor to ``corporate`` (limb (b)), so the
    Art. 201 corporate limb, the IRB-permission routing, the Art. 235 covered-part
    weight and the COREP inflow class all read the class Art. 107(2) gives it.

    Qualifying means ``guarantor_is_qccp`` True. False, an explicit null and an
    unmatched guarantor are all non-qualifying (an unreported qualification is not
    shown) — the loader already seals a null or unsupplied ``is_qccp`` to the
    schema default False, and ``apply_guarantees`` joins the column on every run.
    """
    demote = (
        _is_ccp_guarantor()
        & (pl.col("guarantor_exposure_class") == ExposureClass.INSTITUTION.value)
        & pl.col("guarantor_is_qccp").eq_missing(True).not_()
    )
    return exposures.with_columns(
        pl.when(demote)
        .then(pl.lit(ExposureClass.CORPORATE.value))
        .otherwise(pl.col("guarantor_exposure_class"))
        .alias("guarantor_exposure_class"),
    )


def record_ineligible_guarantors(
    exposures: pl.LazyFrame,
    errors: list[CalculationError],
) -> None:
    """Append one CRM013 warning per Art. 201-ineligible guarantor leg, naming the cause.

    Reads the ``_guarantor_ineligible`` flag ``assign_guarantor_approach`` sets.
    The CRM processor calls this on the materialised ``crm_exit`` frame — an
    in-memory scan, where the flag's own site re-executed the guarantee split
    (23 ms of a 150-row run). Nothing is appended to ``errors`` between the two
    points, so CRM013 keeps its place in the list; the exit seal strips the flag.
    The cause is the limb the gate itself recorded on
    ``_guarantor_declined_as_natural_person`` /
    ``_guarantor_declined_as_non_qualifying_ccp`` — never re-derived here, so the
    two cannot drift: a natural person (flagged, or booked under a natural-person
    entity type) is outside the Art. 201 list altogether; a CCP that is not
    qualifying is outside Art. 201(1)(h) and, as the corporate Art. 107(2)(b)
    makes it, lacks the rating Art. 201(1)(g)/(2) requires; otherwise a corporate
    lacks that rating.
    """
    dropped = (
        exposures.filter(pl.col("_guarantor_ineligible"))
        .select(
            "parent_exposure_reference",
            "guarantor_reference",
            "guarantor_entity_type",
            "guarantor_is_natural_person",
            "_guarantor_declined_as_natural_person",
            "_guarantor_declined_as_non_qualifying_ccp",
        )
        .collect()
    )
    for row in dropped.iter_rows(named=True):
        loan_ref = row.get("parent_exposure_reference")
        guar_ref = row.get("guarantor_reference")
        entity_type = row.get("guarantor_entity_type")
        if row.get("_guarantor_declined_as_natural_person"):
            flagged = (
                ", is_natural_person flag set" if row.get("guarantor_is_natural_person") else ""
            )
            cause = (
                f"a natural person (entity_type '{entity_type}'{flagged}) is not an "
                "eligible provider of unfunded credit protection under Art. 201(1)/(2)"
            )
            reference = "CRR Art. 201(1)"
        elif row.get("_guarantor_declined_as_non_qualifying_ccp"):
            cause = (
                "a central counterparty that is not a qualifying central counterparty is "
                "not admitted by Art. 201(1)(h); Art. 107(2)(b) treats it as a corporate, "
                "and without an ECAI credit assessment (or, for an IRB-approach "
                "beneficiary, an internal rating) it is not eligible under Art. 201(1)(g)/(2)"
            )
            reference = "CRR Art. 201(1)(h)"
        else:
            cause = (
                "a corporate guarantor without an ECAI credit assessment (or, for an "
                "IRB-approach beneficiary, an internal rating) is not eligible under "
                "Art. 201(1)(g)/(2)"
            )
            reference = "CRR Art. 201(1)(g)"
        errors.append(
            crm_warning(
                ERROR_INELIGIBLE_GUARANTOR,
                f"Guarantor '{guar_ref}' is an ineligible protection provider for "
                f"exposure '{loan_ref}': {cause}; the guarantee is not recognised and "
                "the exposure reverts to the borrower's own basis.",
                exposure_reference=loan_ref,
                regulatory_reference=reference,
            )
        )


def _is_ccp_guarantor() -> pl.Expr:
    """True on a guarantor booked ``entity_type='ccp'``; never null.

    ``ccp`` is an input-domain value (``data/schemas.py`` VALID_ENTITY_TYPES), the
    same one ``engine/sa/ccp_exposures.py`` keys the obligor side on.
    """
    return pl.col("guarantor_entity_type").eq_missing("ccp")


def _build_domestic_cgcb_flag(schema_names: list[str]) -> pl.Expr:
    """
    Build the EU/UK domestic-currency CGCB guarantor indicator.

    Art. 114(4)/(7): a domestic-currency CGCB guarantor must receive 0% RW
    via the SA short-circuit, even if the guarantor has an internal PD that
    would otherwise route to IRB parameter substitution. The domestic-currency
    (denomination) test is evaluated against the guarantee currency (the
    currency of the substituted exposure to the sovereign), not the underlying
    loan's currency — Art. 233(3) FX haircut handles any mismatch between
    guarantee and underlying.

    Art. 235(3): the 0% extension additionally requires the exposure to be
    *funded* in the same domestic currency. The funding limb (``funding_currency``,
    null-PERMISSIVE fallback to the exposure denomination — see
    :func:`funding_currency_expr`) is ANDed in, so a loan funded in a
    non-domestic currency (e.g. USD-funded, EUR-guaranteed) no longer receives
    the 0% short-circuit.
    """
    has_exposure_ccy = "original_currency" in schema_names or "currency" in schema_names
    has_guarantee_ccy = "guarantee_currency" in schema_names
    if has_guarantee_ccy and has_exposure_ccy:
        ccy_expr: pl.Expr | None = pl.col("guarantee_currency").fill_null(
            denomination_currency_expr(schema_names)
        )
    elif has_guarantee_ccy:
        ccy_expr = pl.col("guarantee_currency")
    elif has_exposure_ccy:
        ccy_expr = denomination_currency_expr(schema_names)
    else:
        return pl.lit(False)

    cgcb = ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value
    return (pl.col("guarantor_exposure_class") == cgcb) & build_domestic_cgcb_guarantor_expr(
        "guarantor_country_code", ccy_expr, funding_currency_expr(schema_names)
    )
