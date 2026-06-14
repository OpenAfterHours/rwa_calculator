"""
Approach assignment for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    after permission resolution (``permissions``). Final classification
    step before the stage-exit materialise + seal.

Key responsibilities:
- ``assign_approach``: the four-step recipe — permission expressions
  (via ``permissions.build_permission_exprs``), Basel 3.1 Art. 147A
  restrictions, the 10-branch ``pl.when`` decision ladder, and the
  post-decision FIRB LGD clearing + rgla/pse exposure-class re-alignment.

References:
- CRR Art. 147-153: IRB approach assignment
- CRR Art. 114(4)/(7): EU domestic sovereign SA routing (B31 approach gate)
- CRR Art. 150(1): PPU election (CRR path keeps IRB routing available)
- PRA PS1/26 Art. 147A(1)(a)-(e): B31 approach restrictions
  (sovereign-like SA-only, institution no-AIRB, FSE / large-corp no-AIRB,
  IPRE / HVCRE slotting-only)
- CRR Art. 300-311 / CRE54.14-15: CCP trade exposures → SA
- Art. 155 / CRE60: equity SA-only under Basel 3.1
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import (
    B31_SOVEREIGN_LIKE_ENTITY_TYPES,
    RGLA_PSE_ENTITY_TYPES,
)
from rwa_calc.data.tables.eu_sovereign import (
    build_eu_domestic_currency_expr,
    denomination_currency_expr,
)
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    SpecialisedLendingType,
)
from rwa_calc.engine.stages.classify.permissions import build_permission_exprs
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


# SL types restricted to slotting-only under B31 Art. 147A(1)(c)
_B31_SLOTTING_ONLY_SL_TYPES = {
    SpecialisedLendingType.IPRE.value,
    SpecialisedLendingType.HVCRE.value,
}


# =========================================================================
# Approach assignment (1 .with_columns)
# =========================================================================


def assign_approach(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    schema_names: set[str],
    *,
    has_model_permissions: bool = False,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Determine calculation approach and finalize classification.

    Reads as a recipe of four named steps:
      1. Build permission expressions (model-level / org-wide / IRB-mode).
      2. Apply Basel 3.1 Art. 147A approach restrictions (FSE, large corp,
         institution AIRB block, sovereign-like SA-only).
      3. Compose the ``pl.when`` decision ladder for ``approach``.
      4. Apply post-decision LGD clearing and rgla/pse exposure_class
         re-alignment.

    Sets: approach, lgd (cleared for FIRB), exposure_class (re-aligned
    for IRB-routed rgla_* / pse_*).
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # IRB requires an internal rating (PD from the firm's IRB model).
    # Counterparties with only external ratings fall through to SA.
    has_internal_rating = pl.col("internal_pd").is_not_null()
    has_modelled_lgd = pl.col("lgd").is_not_null()

    # Step 1: permission expressions
    airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting = build_permission_exprs(
        config,
        has_internal_rating=has_internal_rating,
        has_modelled_lgd=has_modelled_lgd,
        has_model_permissions=has_model_permissions,
    )

    # Step 2: B3.1 Art. 147A restrictions (no-op under CRR)
    airb_expr, firb_expr, firb_clear_expr = _apply_b31_approach_restrictions(
        airb_expr,
        firb_expr,
        firb_clear_expr,
        config,
        pack=resolved_pack,
    )

    # Step 3: approach decision ladder
    approach_expr = _build_approach_expr(
        schema_names=schema_names,
        config=config,
        airb_expr=airb_expr,
        firb_expr=firb_expr,
        sl_airb=sl_airb,
        sl_slotting=sl_slotting,
        has_internal_rating=has_internal_rating,
        has_modelled_lgd=has_modelled_lgd,
        pack=resolved_pack,
    )

    # FIRB LGD clearing — clear LGD when FIRB approach is chosen (FIRB uses
    # regulatory supervisory LGD). Must NOT clear for reclassified retail.
    lgd_expr = (
        pl.when(firb_clear_expr & ~pl.col("reclassified_to_retail"))
        .then(pl.lit(None).cast(pl.Float64))
        .otherwise(pl.col("lgd"))
        .alias("lgd")
    )

    # Step 4: align exposure_class for IRB-routed rgla_* / pse_*
    return _align_irb_exposure_class(exposures.with_columns([approach_expr, lgd_expr]))


def _apply_b31_approach_restrictions(
    airb_expr: pl.Expr,
    firb_expr: pl.Expr,
    firb_clear_expr: pl.Expr,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """Apply Basel 3.1 Art. 147A approach restrictions.

    Returns the inputs unchanged when the
    ``approach_restrictions_b31_applicable`` Feature is off (CRR).
    Under Basel 3.1, removes A-IRB eligibility for FSE / large-corporate /
    institution exposures (Art. 147A(1)(b)/(d)/(e)) and removes both A-IRB
    and F-IRB for sovereign-like entity types (Art. 147A(1)(a)). Also
    widens ``firb_clear_expr`` to include rows whose A-IRB was blocked but
    which still receive F-IRB.

    These supplement the permissions-level restrictions in
    ``full_irb_b31()`` with data-dependent checks that cannot be encoded
    in the permission map.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("approach_restrictions_b31_applicable"):
        return airb_expr, firb_expr, firb_clear_expr

    # Art. 147A(1)(d)/(e): FSE → no A-IRB (null = not flagged as FSE)
    is_fse = (
        (pl.col("cp_is_financial_sector_entity") == True)  # noqa: E712
        .fill_null(False)
    )
    # Art. 147A(1)(d): the large-corporate F-IRB restriction applies ONLY
    # to counterparties of entity_type == "corporate". Non-corporate
    # entity types are governed by their own Art. 147A sub-clauses and
    # must never trip this branch. Within the corporate slice:
    #   - When annual_revenue is non-null, compare to the large-corp
    #     threshold (GBP 440m).
    #   - When annual_revenue is null but total_assets indicates the
    #     counterparty is SME-sized (assets < EUR 43m per Commission
    #     Rec 2003/361/EC Art. 2), it is definitively not large.
    #   - Otherwise (both fields null, or null revenue with assets that
    #     don't resolve the question) treat conservatively as large;
    #     CLS008 is emitted to flag the missing data.
    balance_sheet_threshold = float(
        regulatory_threshold(resolved_pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    is_corporate_cp = pl.col("cp_entity_type").fill_null("") == "corporate"
    is_large_corp = is_corporate_cp & (
        pl.when(pl.col("cp_annual_revenue").is_not_null())
        .then(
            pl.col("cp_annual_revenue")
            > float(
                regulatory_threshold(
                    resolved_pack, "large_corporate_revenue_threshold", config.eur_gbp_rate
                )
            )
        )
        .when(pl.col("cp_total_assets").is_not_null())
        .then(pl.col("cp_total_assets") >= balance_sheet_threshold)
        .otherwise(pl.lit(True))
    )
    # Art. 147A(1)(b): Institution (including RGLAs/PSEs treated as
    # institutions per Art. 147(4)(b)) → F-IRB only. Key on
    # exposure_class_irb so rgla_institution / pse_institution inherit
    # the restriction.
    b31_institution_no_airb = pl.col("exposure_class_irb") == ExposureClass.INSTITUTION.value
    b31_airb_blocked = is_fse | is_large_corp | b31_institution_no_airb

    # Art. 147A(1)(a) read with Art. 147(3): sovereigns and
    # quasi-sovereigns with 0% SA RW → SA only. See
    # ``B31_SOVEREIGN_LIKE_ENTITY_TYPES`` for the full list.
    b31_sa_only = pl.col("cp_entity_type").is_in(list(B31_SOVEREIGN_LIKE_ENTITY_TYPES))

    # Art. 155 / CRE60 / PRA PS1/26: equity exposures are SA-only under
    # Basel 3.1 (IRB equity approaches withdrawn from 1 Jan 2027). Block
    # both A-IRB and F-IRB so the decision ladder falls through to the
    # equity branch in ``_build_approach_expr``.
    b31_equity_sa_only = pl.col("exposure_class_irb") == ExposureClass.EQUITY.value
    b31_sa_only_combined = b31_sa_only | b31_equity_sa_only

    new_airb = airb_expr & ~b31_airb_blocked & ~b31_sa_only_combined
    new_firb_clear = firb_clear_expr | (firb_expr & b31_airb_blocked)
    new_firb = firb_expr & ~b31_sa_only_combined
    return new_airb, new_firb, new_firb_clear


def _build_approach_expr(
    *,
    schema_names: set[str],
    config: CalculationConfig,
    airb_expr: pl.Expr,
    firb_expr: pl.Expr,
    sl_airb: pl.Expr,
    sl_slotting: pl.Expr,
    has_internal_rating: pl.Expr,
    has_modelled_lgd: pl.Expr,
    pack: ResolvedRulepack | None = None,
) -> pl.Expr:
    """Compose the ``pl.when`` decision ladder for ``approach``.

    Branch order (top wins):
    1. Managed-as-retail without LGD → SA
    2. Art. 114(4) EU domestic sovereign → SA (forced 0% RW)
    3. CCP trade exposures → SA (CRE54.14-15)
    4. Basel 3.1 Art. 147A(1)(c) IPRE/HVCRE → slotting
    5. SL A-IRB (PD + modelled LGD required, CRR Art. 153(1)-(4))
    6. SL slotting fallback (no internal rating required)
    7. A-IRB (model or org-wide, with B3.1 FSE/large-corp restriction applied)
    8. F-IRB (model or org-wide)
    9. Equity → EQUITY approach
    10. Otherwise → SA
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    managed_as_retail_without_lgd = (
        (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
        & (pl.col("lgd").is_null())
    )

    # Art. 114(4)/(7): EU domestic sovereign → SA. Use original
    # (pre-FX) denomination — `currency` is overwritten by the FX
    # converter with the reporting currency, which would otherwise
    # reject legitimate Art. 114(4) treatment for any non-base-currency
    # exposure. Gated to Basel 3.1: under CRR, Art. 114(4) sets only the
    # SA *risk weight*, not the *approach* — Art. 150(1) PPU is an
    # election ("may apply"), so a firm holding CGCB IRB permission must
    # be allowed to route to IRB. Under B31 (PS1/26 Art. 147A(1)(a)),
    # sovereign-like exposures are SA-only as a mandatory restriction,
    # also backstopped by the `b31_sa_only` IRB-blocker.
    is_eu_domestic_sovereign = (
        pl.lit(resolved_pack.feature("approach_restrictions_b31_applicable"))
        & (pl.col("exposure_class") == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value)
        & build_eu_domestic_currency_expr(
            "cp_country_code", denomination_currency_expr(schema_names)
        )
    )

    # Art. 147A(1)(c): IPRE/HVCRE → slotting only (overrides model perms)
    b31_ipre_hvcre_forced_slotting = pl.lit(False)
    if resolved_pack.feature("approach_restrictions_b31_applicable"):
        b31_ipre_hvcre_forced_slotting = (
            pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value
        ) & pl.col("sl_type").is_in(list(_B31_SLOTTING_ONLY_SL_TYPES))

    # CCP exposures must always use SA (CRR Art. 300-311, CRE54)
    is_ccp = pl.col("cp_entity_type") == "ccp"

    is_sl = pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value

    return (
        pl.when(managed_as_retail_without_lgd)
        .then(pl.lit(ApproachType.SA.value))
        .when(is_eu_domestic_sovereign)
        .then(pl.lit(ApproachType.SA.value))
        .when(is_ccp)
        .then(pl.lit(ApproachType.SA.value))
        .when(b31_ipre_hvcre_forced_slotting)
        .then(pl.lit(ApproachType.SLOTTING.value))
        # SL A-IRB takes precedence over slotting (non-IPRE/HVCRE under B31).
        # Requires both PD and modelled LGD — without LGD, fall through to
        # slotting (CRR Art. 153(1)-(4) vs Art. 153(5)).
        .when(is_sl & sl_airb & has_internal_rating & has_modelled_lgd)
        .then(pl.lit(ApproachType.AIRB.value))
        # SL slotting fallback (slotting does not require internal rating)
        .when(is_sl & sl_slotting)
        .then(pl.lit(ApproachType.SLOTTING.value))
        .when(airb_expr)
        .then(pl.lit(ApproachType.AIRB.value))
        .when(firb_expr)
        .then(pl.lit(ApproachType.FIRB.value))
        # Equity exposure class → EQUITY approach (routes to SA equity RW
        # logic; full equity treatment requires the dedicated
        # equity_exposures table).
        .when(pl.col("exposure_class") == ExposureClass.EQUITY.value)
        .then(pl.lit(ApproachType.EQUITY.value))
        .otherwise(pl.lit(ApproachType.SA.value))
        .alias("approach")
    )


@cites("CRR Art. 147")
def _align_irb_exposure_class(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Align exposure_class with exposure_class_irb for rgla/pse rows.

    For IRB-routed rgla_* / pse_* rows, the IRB calculator (which reads
    exposure_class for correlation/LGD selection) needs CGCB / INSTITUTION
    rather than the SA labels RGLA / PSE. Scoped to these entity types
    because later phases (retail reclassification, SME/QRRE) mutate
    exposure_class in place without updating exposure_class_irb — a
    blanket rewrite would revert those legitimate adjustments.
    """
    needs_alignment = pl.col("cp_entity_type").is_in(list(RGLA_PSE_ENTITY_TYPES))
    return exposures.with_columns(
        pl.when(
            pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
            & needs_alignment
        )
        .then(pl.col("exposure_class_irb"))
        .otherwise(pl.col("exposure_class"))
        .alias("exposure_class")
    )
