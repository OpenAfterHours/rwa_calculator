"""
Standardised Approach post-base risk-weight adjustments.

Plain typed functions applied after the base SA risk-weight assignment, in
regulatory order: Art. 222 FCSM substitution, Art. 232 life-insurance
mapping, Art. 235 guarantee substitution, the Basel 3.1 Art. 123B
currency-mismatch multiplier, and the Basel 3.1 Art. 110A due-diligence
override. ``SACalculator`` composes them via ``LazyFrame.pipe``.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- Art. 222 Financial Collateral Simple Method RW substitution
- Art. 232 life-insurance collateral RW mapping
- Art. 235 unfunded credit protection (guarantee substitution)
- PRA PS1/26 Art. 123B currency-mismatch multiplier (Basel 3.1)
- PRA PS1/26 Art. 120(4) / 122(4) / 129(4A) due-diligence override (Basel 3.1)
- The SA004 / SA010 entry censuses (Art. 110A attestation, Art. 123B income
  currency), returned as expressions for ``SACalculator``'s one entry collect

References:
- CRR Art. 193: CRM recognition principles (the no-worse cap and the
  election to amend the calculation) — the basis for declining a guarantee
- CRR Art. 235: SA guarantee substitution formula
- CRR Art. 213-217: Eligibility of the protection (gated upstream in
  ``engine/crm/guarantees.py``, not here)
- CRR Art. 222: Financial Collateral Simple Method
- CRR Art. 232: Life insurance collateral
- PRA PS1/26 Art. 110A: Basel 3.1 due-diligence obligation (SA004 census)
- PRA PS1/26 Art. 120(4), 122(4), 129(4A): the "at least one step higher" risk
  weight the due-diligence override applies
- PRA PS1/26 Art. 123B: Basel 3.1 currency mismatch multiplier
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_DUE_DILIGENCE_NOT_PERFORMED,
    ERROR_INCOME_CURRENCY_UNKNOWN,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.domain.enums import ApproachType, CRMCollateralMethod, ExposureClass, ReportingBasis
from rwa_calc.engine.branch_split import is_sa_branch_approach
from rwa_calc.engine.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    country_domestic_currency_expr,
    denomination_currency_expr,
    funding_currency_expr,
)
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr
from rwa_calc.engine.sa.risk_weights import _SA_B31_RW
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from collections.abc import Collection

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# PRA PS1/26 Basel 3.1 commencement date, resolved from the b31 pack once at
# module load. Reporting dates strictly before this fall under pre-Basel-3.1
# treatment (the Art. 123B currency-mismatch multiplier this gates does not
# apply). Raw date compared date-to-date (no coercion). (S13-g)
_B31_PACK = resolve("b31", date(2027, 1, 1))
_B31_EFFECTIVE_DATE = _B31_PACK.date_param("b31_effective_date").value

# PS1/26 Art. 123B(1) scope: retail (Art. 112(1)(h)) and residential real estate
# (Art. 112(1)(i)) classes. Commercial RE and corporate are out of scope.
_ART_123B_CLASSES: tuple[str, ...] = (
    ExposureClass.RETAIL_OTHER.value,
    ExposureClass.RETAIL_QRRE.value,
    ExposureClass.RETAIL_MORTGAGE.value,
    ExposureClass.RESIDENTIAL_MORTGAGE.value,
)

# Obligor-residence carriers read by the Art. 123B(3) fallback (RE-05). Both ride
# the sealed SA input; ``ensure_columns`` injects them as typed nulls on a
# hand-built frame, which reads as "residence unknown".
_OBLIGOR_RESIDENCE_COLUMNS: dict[str, ColumnSpec] = {
    "cp_country_code": ColumnSpec(pl.String, required=False),
    "cp_local_currency": ColumnSpec(pl.String, required=False),
}

# SA010 census (RE-05): the carriers it reads — injected as typed nulls where a
# frame lacks them, so a hand-built frame counts rather than raises — and the
# names of its two aggregates.
_INCOME_CENSUS_COLUMNS: dict[str, ColumnSpec] = {
    "value_date": ColumnSpec(pl.Date, required=False),
}
_CENSUS_UNKNOWN = "_sa010_income_currency_unknown"
_CENSUS_PRE_2027 = "_sa010_income_currency_unknown_pre_2027"

# PS1/26 Art. 110A(5): the exposure classes outside the due-diligence obligation.
# Points (a) to (c) of Art. 112(1) are the CGCB, RGLA and PSE classes; the
# international-organisation class holds exactly the Art. 118(1) list (weighted 0%
# unconditionally). The Art. 117(2) MDBs are a subset of the MDB class, told apart
# inside ``due_diligence_census_exprs`` by their ``mdb_named`` entity type.
_ART_110A_EXEMPT_CLASSES: tuple[str, ...] = (
    ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    ExposureClass.RGLA.value,
    ExposureClass.PSE.value,
    ExposureClass.INTERNATIONAL_ORGANISATION.value,
)

# SA004 census (P1.368): the carriers it reads — injected as typed nulls where a
# hand-built frame lacks them, and a null is never counted — and its aggregate.
_DUE_DILIGENCE_CENSUS_COLUMNS: dict[str, ColumnSpec] = {
    "due_diligence_performed": ColumnSpec(pl.Boolean, required=False),
    "exposure_class": ColumnSpec(pl.String, required=False),
    "cp_entity_type": ColumnSpec(pl.String, required=False),
    "approach": ColumnSpec(pl.String, required=False),
}
_CENSUS_DD_NOT_PERFORMED = "_sa004_due_diligence_not_performed"

# The override weight ``apply_due_diligence_override`` reads; the hierarchy edge
# always carries it, so the injection only ever fires on a hand-built frame.
_DUE_DILIGENCE_OVERRIDE_COLUMNS: dict[str, ColumnSpec] = {
    "due_diligence_override_rw": ColumnSpec(pl.Float64, required=False),
}


@cites("CRR Art. 222")
def apply_fcsm_rw_substitution(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply Art. 222 Financial Collateral Simple Method risk weight substitution.

    When the Simple Method is elected, the secured portion of each SA exposure
    gets the collateral's SA risk weight instead of the exposure's own risk
    weight. The unsecured portion retains the original RW.

    Blended RW = secured_pct × collateral_rw + unsecured_pct × exposure_rw

    The 20% floor (Art. 222(1)/(3)) and same-currency 0% carve-outs (CRR
    Art. 222(4) / PRA PS1/26 Art. 222(6)) are applied per item in
    ``compute_fcsm_columns``. Applying the floor again on the aggregate would
    re-impose it on carve-out items — contrary to "except as specified in
    paragraphs 4 to 6".

    This function is a no-op when the Comprehensive Method is elected (default)
    or when fcsm_collateral_value is zero/null — the crm_exit contract
    injects both fcsm_* columns as typed nulls when the FCSM sub-step did
    not run, and ``fill_null(0.0)`` makes an all-null column equivalent to
    the historical absent-column early return.
    """
    if config.crm_collateral_method != CRMCollateralMethod.SIMPLE:
        return lf

    ead = pl.col("ead_final").fill_null(0.0)
    fcsm_value = pl.col("fcsm_collateral_value").fill_null(0.0)
    fcsm_rw = pl.col("fcsm_collateral_rw").fill_null(0.0)

    # Secured percentage (capped at 100%)
    secured_pct = pl.when(ead > 0).then((fcsm_value / ead).clip(0.0, 1.0)).otherwise(0.0)
    unsecured_pct = pl.lit(1.0) - secured_pct

    # Blended risk weight; secured RW already reflects per-item floor + carve-outs.
    blended_rw = secured_pct * fcsm_rw + unsecured_pct * pl.col("risk_weight")

    # Only apply when there is actual collateral value
    has_fcsm = fcsm_value > 0

    return lf.with_columns(
        # Save pre-FCSM risk weight for audit
        pl.col("risk_weight").alias("pre_fcsm_risk_weight"),
        # Apply blended RW
        pl.when(has_fcsm).then(blended_rw).otherwise(pl.col("risk_weight")).alias("risk_weight"),
        # Track method for audit/COREP
        pl.when(has_fcsm)
        .then(pl.lit("simple"))
        .otherwise(pl.lit("comprehensive"))
        .alias("ead_calculation_method"),
    )


@cites("CRR Art. 232")
def apply_life_insurance_rw_mapping(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Apply Art. 232 life insurance risk weight mapping for SA exposures.

    When life insurance collateral secures an exposure, the secured portion
    receives a mapped risk weight (not direct substitution):
        Insurer RW 20%           -> 20%
        Insurer RW 30% or 50%    -> 35%
        Insurer RW 65%-135%      -> 70%
        Insurer RW 150%          -> 150%

    Blended RW = secured_pct x mapped_rw + unsecured_pct x exposure_rw

    This function is a no-op when no life insurance collateral is present.
    """
    ead = pl.col("ead_final").fill_null(0.0)
    li_value = pl.col("life_ins_collateral_value").fill_null(0.0)
    li_rw = pl.col("life_ins_secured_rw").fill_null(0.0)

    # Secured percentage (capped at 100%)
    secured_pct = pl.when(ead > 0).then((li_value / ead).clip(0.0, 1.0)).otherwise(0.0)
    unsecured_pct = pl.lit(1.0) - secured_pct

    # Blended risk weight: no floor — Art. 232 has no 20% floor like FCSM
    blended_rw = secured_pct * li_rw + unsecured_pct * pl.col("risk_weight")

    # Only apply when there is actual life insurance collateral
    has_li = li_value > 0

    return lf.with_columns(
        pl.when(has_li).then(blended_rw).otherwise(pl.col("risk_weight")).alias("risk_weight"),
    )


@cites("CRR Art. 232")
def apply_third_party_deposit_rw_mapping(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Apply Art. 232(2) third-party-deposit risk-weight substitution for SA.

    A cash deposit held at a third-party institution is other funded credit
    protection treated as a guarantee by that holder institution: the covered
    part of the exposure takes the holder's own SA risk weight (P1.239/P1.240).

        blended = secured_pct x holder_rw + unsecured_pct x exposure_rw

    Benefit-only cap (Art. 232 protection can never increase RWA): the blended
    weight is applied only where it is at or below the exposure's own weight, so
    a holder RW >= obligor RW leaves the exposure unchanged. No-op when no
    third-party deposit is present (columns absent or value 0).
    """
    cols = lf.collect_schema().names()
    if "third_party_deposit_value" not in cols or "third_party_deposit_secured_rw" not in cols:
        return lf

    ead = pl.col("ead_final").fill_null(0.0)
    value = pl.col("third_party_deposit_value").fill_null(0.0)
    holder_rw = pl.col("third_party_deposit_secured_rw").fill_null(0.0)

    secured_pct = pl.when(ead > 0).then((value / ead).clip(0.0, 1.0)).otherwise(0.0)
    unsecured_pct = pl.lit(1.0) - secured_pct
    blended_rw = secured_pct * holder_rw + unsecured_pct * pl.col("risk_weight")

    # Substitution only helps: cap at the exposure's own risk weight.
    beneficial_rw = pl.min_horizontal(blended_rw, pl.col("risk_weight"))
    has_tpd = value > 0

    return lf.with_columns(
        pl.when(has_tpd).then(beneficial_rw).otherwise(pl.col("risk_weight")).alias("risk_weight"),
    )


@cites("CRR Art. 193")
@cites("CRR Art. 235")
def apply_guarantee_substitution(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply guarantee substitution for unfunded credit protection.

    For guaranteed portions the risk weight is substituted with the guarantor's
    risk weight, and the row's RWA is the Art. 235(1) blend of the two:
    ``max(0, E - GA) x r + GA x g``.

    THE DECLINE AND ITS AUTHORITY. This is the canonical account for the whole
    ``is_guarantee_beneficial`` machinery — its IRB twin
    (``engine/irb/guarantee.py``) and the three reporting consumers that gate on
    it (``engine/aggregator/aggregator.py::_beneficial_gate``,
    ``reporting/corep/crm_substitution.py::_decline_gate``,
    ``reporting/corep/c07.py::_protection_exprs``) all point here rather than
    restating it.

    THE BASIS IS ART. 193, NOT ART. 213. Art. 213 ("Requirements common to
    guarantees and credit derivatives") is an ELIGIBILITY gate on the protection
    CONTRACT — the protection is direct, its extent clearly defined and
    incontrovertible, no clause permitting unilateral cancellation / cost
    escalation on credit deterioration / obstruction of timely payout / reduction
    of protection maturity, legally effective and enforceable — plus
    concentration-risk systems (213(2)) and contractual/statutory fulfilment
    (213(3)). It says nothing about whether a recognised guarantee must be
    APPLIED, yet this code recorded "recognition is permissive (Art. 213)" in six
    places. The two provisions that actually carry the decline both sit in
    Art. 193, "Principles for recognising the effect of credit risk mitigation
    techniques":

    - Art. 193(1), MANDATORY, about the OUTCOME: "No exposure in respect of which
      an institution obtains credit risk mitigation shall produce a higher
      risk-weighted exposure amount or expected loss amount than an otherwise
      identical exposure in respect of which an institution has no credit risk
      mitigation." The unit is THE EXPOSURE, not the portfolio, and it binds the
      EXPECTED LOSS amount as well as the RWEA — which is what makes it the right
      authority for the IRB leg too.
    - Art. 193(3), PERMISSIVE, about the MECHANISM: "Where the provisions in
      Sections 2 and 3 are met, institutions MAY amend the calculation of
      risk-weighted exposure amounts under the Standardised Approach and the
      calculation of risk-weighted exposure amounts and expected loss amounts
      under the IRB Approach in accordance with the provisions of Sections 4, 5
      and 6." Art. 213 sits IN Section 2 — it is one of the preconditions 193(3)
      makes the election conditional on, which is exactly why it kept being
      mistaken for the election itself.

    Art. 113(3) ("Where an exposure is subject to credit protection the risk
    weight applicable to that item may be amended in accordance with Chapter 4")
    says the same thing per ITEM, and is the hook Art. 235(1) opens with — "For
    the purposes of Article 113(3) institutions shall calculate ..." — so that
    ``shall`` governs HOW you compute if you amend, not WHETHER you amend. But
    113(3) lives in Chapter 2 and speaks only to the SA risk weight; it does not
    reach the IRB path. Art. 193(3) covers both, so it is the citation of record.

    THE ARGUMENT THAT NEEDS NO CITATION. The Art. 235(1) formula carries no
    ``min`` against ``E x r``. Applied mechanically with ``g > r`` it returns a
    HIGHER RWEA than the identical unprotected exposure — a credit risk
    mitigation chapter that penalises mitigation. That reading cannot be right,
    which is precisely why Art. 193(1) exists.

    TWO ELECTIONS THE TEXT DOES NOT FORCE, recorded because nothing else records
    them:

    (1) DECLINE vs APPLY-AND-CAP — AND ITS CAPITAL-NEUTRALITY IS CRR-CONDITIONAL,
        WHICH IS THE WHOLE POINT. Art. 193(1) mandates the OUTCOME, not the
        mechanism, so under CRR there are exactly TWO compliant implementations:
        decline the guarantee, or apply Art. 235(1) and then cap the RWEA at the
        unmitigated amount. They give IDENTICAL CAPITAL — but only BECAUSE the
        Art. 193(1) cap is MANDATORY. That is what collapses the two onto one
        number and leaves the choice affecting DISCLOSURE alone: under
        apply-and-cap Art. 235 HAS fired, the covered part HAS been assigned to
        the guarantor's class, and the C 07.00 / C 08.01 outflow and inflow would
        both be reported. We decline; that is an implementation election, not a
        reading of the text. Remove the mandatory cap and a THIRD option appears
        — apply Art. 235(1) UNCAPPED, returning a HIGHER RWEA — at which point
        the election stops being capital-neutral and our decline stops being the
        only permissible behaviour. Whether that coincidence survives into
        PS1/26 is UNVERIFIED (below); if it does not, this election acquires a
        capital consequence and needs a recorded policy basis rather than a code
        comment. Note the scope: this is the ENGINE gate, which moves RWA. The
        reporting gates that consume its flag
        (``engine/aggregator/aggregator.py::_beneficial_gate``,
        ``reporting/corep/crm_substitution.py::_decline_gate``) move no RWA at
        all, so THEIR capital-neutrality is unconditional and nothing here
        qualifies it.
    (2) THE STRICT ``<``. The benefit test below is
        ``guarantor_rw < pre_crm_risk_weight`` (the IRB twin is identical against
        ``risk_weight_irb_original``). At EQUALITY Art. 193(1) is SILENT — equal
        is not "higher" — so an equally-weighted guarantor is declined BY CHOICE:
        zero capital effect, and a real effect on which sheet the exposure
        appears on.

    A PS1/26 GAP, STATED RATHER THAN GLOSSED. PS1/26 Art. 113(3) is word for word
    the CRR text with "the Credit Risk Mitigation (CRR) Part" substituted for
    "Chapter 4", so the permissive hook carries into 2027. A PS1/26 equivalent of
    Art. 193(1) has NOT been verified: the PRA renumbers (in ``ps126app1.pdf``
    "Article 193" is the CRR Art. 161 IRB-parameter-substitution rule — read the
    ``[Note: This rule corresponds to Article NNN of CRR ...]`` line, never the
    number), and the PRA Credit Risk Mitigation (CRR) Part is not in
    ``docs/assets/`` at all. The consequence matters: under CRR the decline is
    COMPELLED, so doing neither it nor apply-and-cap is a breach; if the PRA CRM
    Part turns out to lack the equivalent, from 1 Jan 2027 this becomes a pure
    ELECTION — and an election needs a recorded policy basis in a way that
    compliance with a mandatory cap does not. No PS1/26 citation is asserted
    here, because none has been read.

    References:
        CRR Art. 193(1), (3): CRM recognition principles — the no-worse outcome
            cap, and the election to amend the calculation at all.
        CRR Art. 113(3): the SA per-item permissive hook Art. 235(1) hangs off.
        CRR Art. 235: SA risk-weight substitution formula.
        CRR Art. 213-217: eligibility of the protection itself, gated upstream in
            ``engine/crm/guarantees.py``.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    exposures = lf
    cols = exposures.collect_schema().names()

    # Run-level sentinel gate: guarantor_entity_type is the one crm_exit
    # column still CONDITIONAL (inject=False) — present iff the CRM
    # guarantee sub-step ran. Keying on it keeps this machinery (and its
    # derived audit columns: pre_crm_risk_weight, guarantor_rw,
    # is_guarantee_beneficial, guarantee_status, guarantee_benefit_rw)
    # off unguaranteed runs; see contracts/edges.py. The
    # guaranteed_portion check covers direct (non-pipeline) invocation.
    if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
        return exposures

    # Ensure defensive column fallbacks (guarantor_exposure_class,
    # guarantor_country_code, guarantor_scra_grade). In
    # production these are set by the CRM processor; this fallback covers
    # tests that construct LazyFrames directly and skip the CRM stage.
    exposures = _ensure_guarantee_substitution_columns(exposures, resolved_pack)

    # Preserve pre-CRM risk weight for regulatory reporting (pre-CRM vs
    # post-CRM views).
    exposures = exposures.with_columns(
        pl.col("risk_weight").alias("pre_crm_risk_weight"),
    )

    # Art. 114(4)/(7) domestic CGCB-guarantor currency check.
    is_domestic_guarantor = _build_domestic_guarantor_expr(exposures.collect_schema().names())

    # CRR/PS1/26 Art. 120(2) Table 4 short-term institution guarantor flag.
    # The substituted exposure's original maturity (≤ 3 months / 0.25y)
    # drives the short-term carve-out — same convention as the direct
    # institution short-term branches in ``risk_weights.py`` (Art. 120(2),
    # Art. 121(3)). ``original_maturity_years`` is derived earlier in
    # ``apply_risk_weights`` from (maturity_date - value_date) when absent,
    # so it is always populated here.
    short_term_flag_col = "_inst_guarantor_short_term"
    if "original_maturity_years" in exposures.collect_schema().names():
        short_term_expr = pl.col("original_maturity_years").is_not_null() & (
            pl.col("original_maturity_years") <= 0.25
        )
    else:
        short_term_expr = pl.lit(False)
    exposures = exposures.with_columns(
        short_term_expr.fill_null(False).alias(short_term_flag_col),
    )

    # Look up guarantor's RW based on exposure class + CQS. The short-term
    # flag is calculator scratch consumed only by this expression — drop it
    # immediately so it never leaks into the branch/aggregator frames.
    exposures = exposures.with_columns(
        _build_guarantor_rw_expr(
            is_domestic_guarantor,
            resolved_pack.feature("sa_revised_risk_weight_tables"),
            institution_short_term_flag_col=short_term_flag_col,
        ).alias("guarantor_rw"),
    ).drop(short_term_flag_col)

    # The Art. 193(1) benefit test: no exposure with CRM may produce a HIGHER
    # RWEA than the identical unprotected exposure, and the Art. 235(1) formula
    # carries no ``min`` to stop it. DECLINING (rather than applying Art. 235
    # then capping) and the STRICT ``<`` (equality is declined too) are both
    # elections the text does not force — see this function's docstring, which is
    # the single recorded basis for every consumer of this flag.
    exposures = exposures.with_columns(
        [
            pl.when(
                (pl.col("guaranteed_portion") > 0)
                & (pl.col("guarantor_rw").is_not_null())
                & (pl.col("guarantor_rw") < pl.col("pre_crm_risk_weight"))
            )
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_guarantee_beneficial"),
        ]
    )

    # Redistribute non-beneficial guarantee portions to beneficial guarantors.
    # For multi-guarantor exposures, non-beneficial guarantors' EAD is reallocated
    # to the most beneficial (lowest RW) guarantors using greedy fill.
    from rwa_calc.engine.crm.guarantees import redistribute_non_beneficial

    exposures = redistribute_non_beneficial(exposures)

    # Calculate blended risk weight using substitution approach
    # Only apply if guarantee is beneficial
    # RWA = (unguaranteed_portion * borrower_rw + guaranteed_portion * guarantor_rw) / ead_final
    exposures = exposures.with_columns(
        [
            # Blended risk weight when guarantee exists AND is beneficial
            pl.when(
                (pl.col("guaranteed_portion") > 0)
                & (pl.col("guarantor_rw").is_not_null())
                & (pl.col("is_guarantee_beneficial"))
            )
            .then(
                # weighted average of borrower and guarantor risk weights
                (
                    pl.col("unguaranteed_portion") * pl.col("pre_crm_risk_weight")
                    + pl.col("guaranteed_portion") * pl.col("guarantor_rw")
                )
                / pl.col("ead_final")
            )
            # No guarantee, no guarantor RW, or non-beneficial - use original risk weight
            .otherwise(pl.col("pre_crm_risk_weight"))
            .alias("risk_weight"),
        ]
    )

    # Track guarantee status for reporting
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("guaranteed_portion") <= 0)
            .then(pl.lit("NO_GUARANTEE"))
            .when(~pl.col("is_guarantee_beneficial"))
            .then(pl.lit("GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"))
            .otherwise(pl.lit("SA_RW_SUBSTITUTION"))
            .alias("guarantee_status"),
            # Calculate RW benefit from guarantee (positive = RW reduced)
            pl.when(pl.col("is_guarantee_beneficial"))
            .then(pl.col("pre_crm_risk_weight") - pl.col("risk_weight"))
            .otherwise(pl.lit(0.0))
            .alias("guarantee_benefit_rw"),
        ]
    )

    return exposures


@cites("PS1/26, paragraph 123B")
def apply_currency_mismatch_multiplier(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply 1.5x RW multiplier for retail/RE currency mismatch (Basel 3.1 only).

    PS1/26 Art. 123B(1)(a): an unhedged retail / residential RE exposure whose
    LENDING currency differs from the currency of the obligor's source of income
    takes 1.5x its risk weight, capped at 150%. The lending currency is the
    exposure's denomination (``denomination_currency_expr``): the FX converter
    overwrites ``currency`` with the reporting currency, and comparing THAT with
    the income currency inverted the test on every FX-converted run (RE-05).

    Art. 123B(3) — income currency unknown (RE-05): where the institution "is
    unable to identify those exposures with a currency mismatch" it "shall apply
    the risk weight multiplier of 1.5 to all unhedged retail exposures ... except
    where the lending currency is the same as the domestic currency of the
    country of residence of the obligor". A null ``borrower_income_currency``
    takes that fallback (``_unknown_income_mismatch_expr``). The rule's text
    covers exposures incurred before 1 January 2027; for later ones Art. 123B(1)
    obliges the institution to know the income currency, so the same fallback is
    the conservative proxy and SA010 says so
    (``income_currency_unknown_census_exprs`` / ``income_currency_unknown_warnings``).

    Commencement: the multiplier is a PS1/26 measure in force from
    ``_B31_EFFECTIVE_DATE`` (1 January 2027). Reporting dates strictly before
    that fall under the pre-Basel-3.1 treatment and the frame is returned with
    the flag False. The boundary date is in scope (strict ``<``). This is the
    Basel 3.1 commencement date, not Art. 123B(3).
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("sa_currency_mismatch_multiplier"):
        return lf

    # Commencement: pre-1-January-2027 reporting dates suppress the multiplier
    # entirely. Emit the reporting column as ``False`` (consistent with the
    # no-mismatch branch below) so downstream reporting always sees the flag.
    if config.reporting_date < _B31_EFFECTIVE_DATE:
        return lf.with_columns(pl.lit(False).alias("currency_mismatch_multiplier_applied"))

    schema = lf.collect_schema()
    cols = schema.names()

    # Need both exposure currency and borrower income currency
    income_col = _income_currency_column(cols)
    if income_col is None or "currency" not in cols:
        return lf

    # PRA PS1/26 Art. 123B: the 1.5x currency-mismatch multiplier is in scope
    # ONLY for retail (Art. 112(h)) and residential RE (Art. 112(i)) exposures.
    # Commercial RE (Art. 112(j) per Art. 124H/124I) and corporate are OUT of
    # scope. Use exact-match against ExposureClass enum string values rather
    # than substring matching to avoid COMMERCIAL_MORTGAGE matching "COMMERCIAL".
    is_retail_or_re = pl.col("exposure_class").fill_null("").is_in(list(_ART_123B_CLASSES))

    lf = ensure_columns(lf, _OBLIGOR_RESIDENCE_COLUMNS, present=cols)
    lending_currency = denomination_currency_expr(cols)
    income = pl.col(income_col)
    # Art. 123B(1)(a): a KNOWN income currency differing from the lending currency;
    # Art. 123B(3): an UNKNOWN one, unless the lending currency is domestic.
    has_mismatch = (income.is_not_null() & (income != lending_currency)) | (
        _unknown_income_mismatch_expr(income, lending_currency)
    )

    # Art. 123B(2) / CRE20.93: the 1.5x mismatch multiplier is suppressed when
    # the exposure is hedged against currency risk. A full hedge can be signalled
    # either by ``is_hedged=True`` OR by ``hedge_coverage_ratio >= 0.90`` (the
    # Art. 123B(2) partial-hedge coverage floor). Both columns default to their
    # "no hedge" sentinel when missing or null (False / 0.0).
    is_hedged_flag = pl.col("is_hedged").fill_null(False) if "is_hedged" in cols else pl.lit(False)
    # Art. 123B(2A): for revolving facilities the 90%-coverage test denominator is
    # the fully-drawn committed amount (the "instalment amount" = greater of the
    # contractual minimum and the fully-drawn contractual amount; leg (b) here,
    # there being no contractual-minimum field). The firm-supplied
    # ``hedge_coverage_ratio`` measures coverage of the CURRENT drawn balance, so
    # for revolving rows it is rescaled onto the full-draw base:
    #     full_draw_base     = max(drawn_amount, facility_limit)
    #     effective_coverage = (hedge_coverage_ratio * drawn_amount) / full_draw_base
    # Non-revolving rows are unchanged (effective_coverage = hedge_coverage_ratio).
    # is_revolving / facility_limit / drawn_amount may be absent on production SA
    # frames — default safely so the rescale is a no-op and legacy behaviour holds.
    if "hedge_coverage_ratio" in cols:
        raw_coverage = pl.col("hedge_coverage_ratio").fill_null(0.0)
        is_revolving_flag = (
            pl.col("is_revolving").fill_null(False) if "is_revolving" in cols else pl.lit(False)
        )
        drawn_amount = (
            pl.col("drawn_amount").fill_null(0.0) if "drawn_amount" in cols else pl.lit(0.0)
        )
        # Absent facility_limit -> use drawn_amount so full_draw_base == drawn_amount
        # and the rescale collapses to the legacy coverage ratio.
        facility_limit = (
            pl.col("facility_limit").fill_null(drawn_amount)
            if "facility_limit" in cols
            else drawn_amount
        )
        full_draw_base = pl.max_horizontal(drawn_amount, facility_limit)
        effective_coverage = (
            pl.when(is_revolving_flag & (full_draw_base > 0.0))
            .then((raw_coverage * drawn_amount) / full_draw_base)
            .otherwise(raw_coverage)
        )
        hedge_coverage_ok = effective_coverage >= _SA_B31_RW["currency_mismatch_hedge_floor"]
    else:
        hedge_coverage_ok = pl.lit(False)
    waive_expr = is_hedged_flag | hedge_coverage_ok

    mismatch_applies = is_retail_or_re & has_mismatch & ~waive_expr

    return lf.with_columns(
        [
            # Snapshot pre-multiplier RW for audit/reporting (mirrors the
            # pre_fcsm_risk_weight pattern). For non-mismatch rows this equals
            # the unchanged risk_weight; CR5 buckets EAD on this column.
            pl.col("risk_weight").alias("risk_weight_pre_currency_mismatch"),
            pl.when(mismatch_applies)
            .then(
                (pl.col("risk_weight") * _SA_B31_RW["currency_mismatch_multiplier"]).clip(
                    upper_bound=pl.lit(_SA_B31_RW["currency_mismatch_cap"])
                )
            )
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
            mismatch_applies.alias("currency_mismatch_multiplier_applied"),
        ]
    )


@cites("PS1/26, paragraph 123B")
def income_currency_unknown_census_exprs(
    config: CalculationConfig,
    schema_names: Collection[str],
    *,
    pack: ResolvedRulepack | None = None,
) -> tuple[pl.Expr, ...]:
    """Return the SA010 census aggregates, or ``()`` where Art. 123B does not run.

    Two row counts over the SA calculator's input: Art. 123B-scope exposures
    (retail / residential RE class) with no borrower income currency, and those
    of them incurred before 1 January 2027 (``value_date``). They are returned as
    expressions, not counted here, so ``SACalculator`` can fold them into the ONE
    collect it already makes at entry (the SA005 check) — the pipeline's fixed
    collect budget does not grow. ``income_currency_unknown_warnings`` turns the
    counts into the warning. Empty under CRR and before commencement, where the
    multiplier does not run, and on a frame with no income-currency column, which
    the multiplier skips too.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("sa_currency_mismatch_multiplier"):
        return ()
    if config.reporting_date < _B31_EFFECTIVE_DATE:
        return ()
    income_col = _income_currency_column(schema_names)
    if income_col is None:
        return ()
    unknown = pl.col("exposure_class").is_in(list(_ART_123B_CLASSES)) & pl.col(income_col).is_null()
    return (
        unknown.sum().alias(_CENSUS_UNKNOWN),
        (unknown & (pl.col("value_date") < _B31_EFFECTIVE_DATE)).sum().alias(_CENSUS_PRE_2027),
    )


def with_income_currency_census_columns(lf: pl.LazyFrame, present: Collection[str]) -> pl.LazyFrame:
    """Inject (as typed nulls) the carriers the SA010 census reads, where absent.

    ``present`` is the caller's already-resolved column list, so this costs no
    second schema resolution.
    """
    return ensure_columns(lf, _INCOME_CENSUS_COLUMNS, present=present)


@cites("PS1/26, paragraph 123B")
def income_currency_unknown_warnings(census: pl.DataFrame) -> list[CalculationError]:
    """Return the SA010 warning from a census row built from the expressions above.

    One WARNING per run, split by value date: exposures incurred before
    1 January 2027 are inside the PS1/26 Art. 123B(3) fallback verbatim; for
    later ones Art. 123B(1) requires the institution to identify the income
    currency, and the same fallback is applied as a conservative proxy. The
    count covers every row the SA risk-weight pipeline weights — SA rows, and
    IRB rows whose SA-equivalent weight feeds the Basel 3.1 output floor.
    """
    unknown = int(census[_CENSUS_UNKNOWN].item())
    if unknown == 0:
        return []
    pre_2027 = int(census[_CENSUS_PRE_2027].item())
    return [
        CalculationError(
            code=ERROR_INCOME_CURRENCY_UNKNOWN,
            message=(
                f"{unknown} retail / residential real estate exposure(s) carry no "
                "borrower_income_currency, so a currency mismatch cannot be identified. The "
                "Art. 123B(3) fallback was applied to their SA risk weight (the output-floor "
                "SA-equivalent for IRB rows): 1.5x (capped at 150%) on each unhedged exposure "
                "whose lending currency is not the obligor's domestic currency "
                f"(local_currency, else country_code). {pre_2027} were incurred before "
                f"1 January 2027 (Art. 123B(3)(b)); {unknown - pre_2027} were incurred on or "
                "after it, or carry no value_date, where Art. 123B(1) requires the income "
                "currency to be known. Populate borrower_income_currency."
            ),
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.DATA_QUALITY,
            regulatory_reference="PRA PS1/26 Art. 123B(1), 123B(3)",
            field_name="borrower_income_currency",
        )
    ]


@cites("PS1/26, paragraph 110A")
@cites("PS1/26, paragraph 120")
@cites("PS1/26, paragraph 122")
@cites("PS1/26, paragraph 129")
def apply_due_diligence_override(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply the firm's due-diligence risk-weight override (Basel 3.1).

    PS1/26 Art. 110A(2) obliges an SA institution to perform due diligence on its
    exposures, and Art. 120(4) (rated institutions), 122(4) (rated corporates) and
    129(4A) (eligible covered bonds) require that, where it shows higher risk than
    the credit quality step implies, the institution "shall assign a risk weight
    associated with a credit quality step that is at least one step higher". The
    firm supplies that weight per loan / contingent as ``due_diligence_override_rw``
    and this step applies it as a floor: ``max(override, risk_weight)``, recorded
    in ``due_diligence_override_applied``.

    The override only increases the risk weight — it can never reduce it. It is
    applied after every standard RW determination, CRM substitution and the
    currency-mismatch multiplier, and is independent of ``due_diligence_performed``
    (a firm-supplied uplift is honoured whatever the attestation says). It is
    read off the row, so the guarantee-substituted and real-estate-split legs of an
    exposure inherit it. Under the Basel 3.1 output floor ``calculate_unified`` runs
    this over IRB and slotting rows too, where it can raise only the SA-equivalent
    weight behind S-TREA. That is deliberate and must NOT be narrowed to
    ``is_sa_branch_approach()`` the way the census is: PS1/26 Art. 92(3A)(b)(ii)
    computes S-TREA "as if permission to use [the IRB Approach] has not been
    granted", i.e. under the SA in full, Art. 122(4) included — skipping IRB rows
    would lower S-TREA (pinned by ``TestDueDiligenceOverrideOutputFloor``). The SA004
    attestation warning is a separate census (``due_diligence_census_exprs``),
    counted once at calculator entry.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("sa_due_diligence_override"):
        return lf

    lf = ensure_columns(lf, _DUE_DILIGENCE_OVERRIDE_COLUMNS)
    override_applies = pl.col("due_diligence_override_rw").is_not_null() & (
        pl.col("due_diligence_override_rw") > pl.col("risk_weight")
    )

    return lf.with_columns(
        [
            pl.when(override_applies)
            .then(pl.col("due_diligence_override_rw"))
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
            override_applies.alias("due_diligence_override_applied"),
        ]
    )


@cites("PS1/26, paragraph 110A")
def due_diligence_census_exprs(
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> tuple[pl.Expr, ...]:
    """Return the SA004 census aggregate, or ``()`` where Art. 110A does not apply.

    One row count over the SA calculator's input: the rows inside the scope of
    PS1/26 Art. 110A whose ``due_diligence_performed`` is explicitly False. The
    scope is the article's own:

    - SA-branch rows only (``is_sa_branch_approach``) — Art. 110A(1) applies to
      "an institution subject to the Standardised Approach", so the IRB and
      slotting rows ``calculate_unified`` also weights (for the output floor) are
      not counted;
    - not the Art. 110A(5) exemptions — the CGCB, RGLA and PSE classes
      (Art. 112(1)(a)-(c)), the Art. 117(2) named MDBs (``mdb_named``) and the
      Art. 118(1) international organisations;
    - not a null attestation — facility-undrawn, SA-CCR and SFT rows have no
      attestation field (the hierarchy edge leaves it null rather than False), so
      counting them would fire the alarm on every facility or derivatives book
      whatever the firm attested.

    Returned as an expression, not counted here, so ``SACalculator`` folds it into
    the ONE collect it already makes at entry — the pipeline's fixed collect budget
    does not grow. Empty where the ``sa_due_diligence_override`` Feature is off
    (CRR has no Art. 110A).
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("sa_due_diligence_override"):
        return ()
    exposure_class = pl.col("exposure_class")
    exempt = exposure_class.is_in(list(_ART_110A_EXEMPT_CLASSES)) | (
        (exposure_class == ExposureClass.MDB.value)
        & pl.col("cp_entity_type").eq_missing("mdb_named")
    )
    unattested = (
        is_sa_branch_approach() & ~exempt & pl.col("due_diligence_performed").eq_missing(False)
    )
    return (unattested.sum().alias(_CENSUS_DD_NOT_PERFORMED),)


def with_due_diligence_census_columns(lf: pl.LazyFrame, present: Collection[str]) -> pl.LazyFrame:
    """Inject (as typed nulls) the carriers the SA004 census reads, where absent.

    ``present`` is the caller's already-resolved column list, so this costs no
    second schema resolution on the sealed calculator input.
    """
    return ensure_columns(lf, _DUE_DILIGENCE_CENSUS_COLUMNS, present=present)


@cites("PS1/26, paragraph 110A")
def due_diligence_not_performed_warnings(census: pl.DataFrame) -> list[CalculationError]:
    """Return the SA004 warning from a census row built by ``due_diligence_census_exprs``.

    One WARNING per run carrying the count, or nothing when every in-scope row
    attests — so a book that has done its due diligence is silent and one that has
    not is not (LESSONS B9: the two cases must produce different output).
    """
    unattested = int(census[_CENSUS_DD_NOT_PERFORMED].item())
    if unattested == 0:
        return []
    return [
        CalculationError(
            code=ERROR_DUE_DILIGENCE_NOT_PERFORMED,
            message=(
                f"{unattested} Standardised Approach exposure row(s) carry "
                "due_diligence_performed = False. PS1/26 Art. 110A(2) requires due "
                "diligence on every SA exposure outside the Art. 110A(5) exemptions "
                "(central governments and central banks, regional governments and local "
                "authorities, public sector entities, the Art. 117(2) multilateral "
                "development banks and the Art. 118(1) international organisations). "
                "Where it shows higher risk than the external rating implies, "
                "Art. 120(4) / 122(4) / 129(4A) require a risk weight at least one credit "
                "quality step higher: supply it as due_diligence_override_rw. "
                "Facility-undrawn, SA-CCR and SFT rows and equity_exposures holdings "
                "carry no attestation field and are not counted."
            ),
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.DATA_QUALITY,
            regulatory_reference="PRA PS1/26 Art. 110A",
            field_name="due_diligence_performed",
            expected_value="True",
            actual_value=f"False on {unattested} exposure row(s)",
        )
    ]


@cites("CRR Art. 113")
def apply_intragroup_zero_rw(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply the CRR Art. 113(6) core-UK-group 0% risk weight.

    On an individual-basis run the scope resolver flips
    ``intragroup_zero_rw_eligible`` True for exposures to a core-UK-group entity
    (both the reporting entity and the counterparty inside the same permission
    perimeter). Those rows take the pack's cited 0% final risk weight, applied
    as the LAST risk-weight step — after standard SA assignment and every CRM
    adjustment (FCSM, life-insurance, guarantee substitution, currency mismatch,
    due diligence). The permission is a hard override, not a benefit blended
    against the counterparty risk weight, so it deliberately wins over the
    due-diligence increase that precedes it.

    Keyed on the row's OWN eligibility carrier: a guarantee-split leg of an
    eligible intragroup loan inherits the flag (splits copy row columns), while
    an external loan merely guaranteed BY a group member is untouched —
    Art. 113(6) covers direct exposures to members, not protection from them.

    SA-routed rows only. IRB rows are unaffected: the IRB route to a 0%
    intragroup exposure is Art. 150(1)(e) permanent partial use, which
    reclassifies the exposure to SA upstream, where this override then fires.
    The Feature (enabled under both CRR and Basel 3.1 — PS1/26 retains the
    permission) carries the regime story, so there is no is_crr branch.

    The override fires ONLY on a scoped **individual**-basis run — the one path
    on which the resolver is authoritative over the carrier. This closes the
    user-loadable bypass: ``intragroup_zero_rw_eligible`` is a declared (optional)
    schema column, so an input file could ship it True, but on an unscoped or
    consolidated run the resolver never overwrites it; gating here means a stray
    input True can never win the 0% without the PRA permission. Reading
    ``reporting_entity`` / ``reporting_basis`` is scope gating, not regime
    branching (arch_check check 17 is untouched).

    No-op when the Feature is disabled, the run is not scoped-individual, or the
    carrier column is absent (a direct calculator invocation that never went
    through the scope resolver).
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("intragroup_zero_rw"):
        return lf

    # Scope gate (bypass closure): the 0% can only apply where the resolver has
    # authoritatively set the carrier — a scoped individual-basis run.
    if config.reporting_entity is None or config.reporting_basis is not ReportingBasis.INDIVIDUAL:
        return lf

    cols = lf.collect_schema().names()
    if "intragroup_zero_rw_eligible" not in cols:
        return lf

    zero_rw = scalar_value(resolved_pack.scalar_param("intragroup_zero_rw_pct"))
    # A null carrier routes to the ``otherwise`` branch below (unchanged RW),
    # identical to False — no fill needed (and the edge seal already null-fills).
    eligible = pl.col("intragroup_zero_rw_eligible")
    # SA-routed rows only (Art. 150(1)(e) PPU is the IRB route to SA treatment).
    # On the output-floor path the SA pipe runs over the full unified frame, so
    # gate on the approach column to leave IRB / slotting SA-equivalent RWs alone.
    if "approach" in cols:
        eligible = eligible & (pl.col("approach") == ApproachType.SA.value)

    return lf.with_columns(
        pl.when(eligible)
        .then(pl.lit(zero_rw))
        .otherwise(pl.col("risk_weight"))
        .alias("risk_weight"),
    )


# ---------------------------------------------------------------------------
# Guarantee-substitution helpers (CRR Art. 235; guarantor eligibility Art. 213-217)
#
# The guarantee-substitution stage relies on a few columns that may be missing
# when the calculator is invoked directly from tests (i.e. bypassing the CRM
# processor). These helpers own the defensive preparation and the
# guarantor-RW when/then chain in one place.
# ---------------------------------------------------------------------------


def _ensure_guarantee_substitution_columns(
    exposures: pl.LazyFrame, pack: ResolvedRulepack
) -> pl.LazyFrame:
    """Ensure optional guarantor columns exist before guarantee substitution.

    In production ``guarantor_exposure_class`` is set by the CRM processor
    (``engine/crm/guarantees.py``) from the run pack's
    ``entity_type_to_sa_class``. This fallback covers unit tests that construct
    LazyFrames directly and skip the CRM stage; it derives the class from the
    same ``pack`` the caller resolved, so the two paths read one map.

    Adds (if absent):
        guarantor_exposure_class — derived from guarantor_entity_type
        guarantor_country_code   — null String
        guarantor_scra_grade     — null String (B31 SCRA dispatch fallback)
    """
    schema_names = exposures.collect_schema().names()
    to_add: list[pl.Expr] = []

    if "guarantor_exposure_class" not in schema_names:
        from rwa_calc.engine.entity_class_maps import entity_type_to_sa_class

        to_add.append(
            pl.col("guarantor_entity_type")
            .fill_null("")
            .replace_strict(entity_type_to_sa_class(pack), default="")
            .alias("guarantor_exposure_class")
        )
    if "guarantor_country_code" not in schema_names:
        to_add.append(pl.lit(None).cast(pl.String).alias("guarantor_country_code"))
    if "guarantor_scra_grade" not in schema_names:
        to_add.append(pl.lit(None).cast(pl.Utf8).alias("guarantor_scra_grade"))

    return exposures.with_columns(to_add) if to_add else exposures


def _build_domestic_guarantor_expr(schema_names: list[str]) -> pl.Expr:
    """Build the Art. 114(4)/(7) + Art. 235(3) domestic CGCB-guarantor check.

    Evaluates the domestic-currency (denomination) test against the guarantee
    currency (the currency of the substituted exposure to the sovereign); the
    Art. 233(3) 8% FX haircut separately handles any mismatch between the
    guarantee and the underlying exposure. Falls back to the exposure's pre-FX
    denomination when ``guarantee_currency`` is missing (legacy / no-guarantee
    rows).

    Art. 235(3): the 0% extension also requires the exposure to be *funded* in
    the domestic currency, so the funding limb (``funding_currency``, null-
    PERMISSIVE fallback to the denomination — see :func:`funding_currency_expr`)
    is ANDed in; a USD-funded, EUR-guaranteed loan therefore falls to the
    guarantor's own CQS risk weight rather than 0%.
    """
    has_country = "guarantor_country_code" in schema_names
    has_exposure_ccy = "currency" in schema_names or "original_currency" in schema_names
    has_guarantee_ccy = "guarantee_currency" in schema_names

    if has_guarantee_ccy and has_exposure_ccy:
        ccy_expr = pl.col("guarantee_currency").fill_null(denomination_currency_expr(schema_names))
    elif has_guarantee_ccy:
        ccy_expr = pl.col("guarantee_currency")
    elif has_exposure_ccy:
        ccy_expr = denomination_currency_expr(schema_names)
    else:
        ccy_expr = None

    if not has_country or ccy_expr is None:
        return pl.lit(False)
    return build_domestic_cgcb_guarantor_expr(
        "guarantor_country_code", ccy_expr, funding_currency_expr(schema_names)
    )


def _build_guarantor_rw_expr(
    is_domestic_guarantor: pl.Expr,
    is_basel_3_1: bool,
    institution_short_term_flag_col: str | None = None,
) -> pl.Expr:
    """Compile the shared guarantor RW chain with the SA path's bindings.

    Thin wrapper over ``data/tables/guarantor_rw.build_guarantor_rw_expr`` —
    the single rulepack-compiled source for the guarantor branch chain
    (branch order, tables and the unrated PSE/RGLA approximation are
    documented there). The SA path binds its ``guarantor_*`` column names,
    the Art. 114(4)/(7) domestic-CGCB currency test, the Art. 120(2)
    short-term institution scratch flag, and the ``guaranteed_portion``
    no-guarantee guard.
    """
    return build_guarantor_rw_expr(
        exposure_class_col="guarantor_exposure_class",
        entity_type_col="guarantor_entity_type",
        cqs_col="guarantor_cqs",
        country_code_col="guarantor_country_code",
        scra_grade_col="guarantor_scra_grade",
        is_basel_3_1=is_basel_3_1,
        domestic_cgcb_expr=is_domestic_guarantor,
        short_term_flag_col=institution_short_term_flag_col,
        no_guarantee_expr=pl.col("guaranteed_portion") <= 0,
    )


# =========================================================================
# Currency-mismatch helpers (PS1/26 Art. 123B)
# =========================================================================


def _income_currency_column(schema_names: Collection[str]) -> str | None:
    """Pick the borrower income-currency carrier: the sealed ``cp_`` twin, else raw."""
    if "cp_borrower_income_currency" in schema_names:
        return "cp_borrower_income_currency"
    if "borrower_income_currency" in schema_names:
        return "borrower_income_currency"
    return None


@cites("PS1/26, paragraph 123B.3")
def _unknown_income_mismatch_expr(income: pl.Expr, lending_currency: pl.Expr) -> pl.Expr:
    """Art. 123B(3): income currency unknown and lending currency not shown domestic.

    PS1/26 Art. 123B(3) applies the multiplier to all unhedged retail / RRE
    exposures whose mismatch cannot be identified "except where the lending
    currency is the same as the domestic currency of the country of residence of
    the obligor or the country of employment of the obligor". The obligor's
    domestic currency is ``cp_local_currency`` when supplied, else the domestic
    currency of ``cp_country_code`` (UK + EU from the pack); there is no
    country-of-employment input. A null domestic currency — an unmapped or null
    country with no local currency — cannot establish the exception, so the
    multiplier applies (``eq_missing`` keeps the expression total without a
    ``fill_null``). A null LENDING currency leaves the test unevaluable, exactly
    as it leaves the known-income limb unevaluable: no multiplier from either.
    """
    domestic_currency = pl.coalesce(
        pl.col("cp_local_currency"), country_domestic_currency_expr("cp_country_code")
    )
    return (
        lending_currency.is_not_null()
        & income.is_null()
        & ~domestic_currency.eq_missing(lending_currency)
    )
