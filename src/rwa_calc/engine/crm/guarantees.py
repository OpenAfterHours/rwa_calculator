"""
Guarantee substitution for CRM processing.

Pipeline position:
    Collateral -> apply_guarantees -> Finalise EAD

Key responsibilities:
- Multi-level guarantee resolution (direct / facility / counterparty)
- Multi-guarantor row splitting
- Cross-approach CCF substitution (IRB exposure + SA guarantor)
- Guarantor attribute lookup for risk weight substitution

References:
    CRR Art. 213-217: Unfunded credit protection
    CRE22.70-85: Basel 3.1 guarantee substitution
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_INELIGIBLE_GUARANTOR,
    ERROR_INELIGIBLE_UNFUNDED_PROTECTION,
    crm_warning,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import DIRECT_BENEFICIARY_TYPES
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.ccf import (
    drawn_for_ead,
    interest_for_ead,
    on_balance_ead,
    sa_ccf_expression,
)
from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    denomination_currency_expr,
)
from rwa_calc.engine.kernels.allocation import (
    expand_items_pro_rata,
    explode_facility_membership,
)
from rwa_calc.engine.utils import exact_fractional_years_expr
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack


def _stock_split_cols() -> tuple[str, ...]:
    """Stock columns that must be split proportionally when guarantee row-splits
    occur, so downstream per-counterparty aggregations (e.g. SME supporting
    factor) and cross-approach CCF recalculations remain correct."""
    return (
        "drawn_amount",
        "undrawn_amount",
        "nominal_amount",
        "interest",
        "ead_pre_crm",
        "ead_from_ccf",
        "provision_deducted",
        "provision_on_drawn",
        "provision_on_nominal",
        "nominal_after_provision",
    )


def _cols_to_drop_before_join() -> tuple[str, ...]:
    """Columns initialised to null on exposures that must be dropped before
    joining guarantee data, to avoid suffixed duplicates (e.g.
    protection_type_right) and lost guarantee values."""
    return (
        "protection_type",
        "guarantee_currency",
        "includes_restructuring",
        "guarantor_seniority",
        "guarantee_fx_haircut",
        "guarantee_restructuring_haircut",
        "guarantee_amount",
        "guaranteed_portion",
        "unguaranteed_portion",
        "guarantor_reference",
    )


@cites("CRR Art. 213")
@cites("CRR Art. 217")
def apply_guarantees(
    exposures: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    counterparty_lookup: pl.LazyFrame,
    config: CalculationConfig,
    rating_inheritance: pl.LazyFrame | None = None,
    *,
    pack: ResolvedRulepack | None = None,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """
    Apply guarantee substitution.

    For guaranteed portion, substitute borrower RW with guarantor RW.

    Args:
        exposures: Exposures with EAD
        guarantees: Guarantee data
        counterparty_lookup: For guarantor risk weights
        config: Calculation configuration
        rating_inheritance: For guarantor CQS lookup
        errors: Optional CRM error channel. When provided, guarantees dropped by
            the Art. 213(1)(c)(i) eligibility gate append a CRM012 warning each.

    Returns:
        Exposures with guarantee effects applied
    """
    guarantees = _prepare_guarantees(guarantees, exposures, config, pack=pack, errors=errors)

    exposures = exposures.with_columns(
        pl.col("exposure_reference").alias("parent_exposure_reference"),
    )

    exposures = _apply_guarantee_splits(guarantees, exposures)
    exposures = _join_guarantor_counterparty(exposures, counterparty_lookup)
    exposures = _join_guarantor_ratings(exposures, rating_inheritance)

    exposures = exposures.with_columns(
        pl.col("guarantor_entity_type").fill_null("").alias("guarantor_entity_type"),
    )

    # Derive guarantor's exposure class from their entity type. Needed for
    # post-CRM reporting where the guaranteed portion is reported under the
    # guarantor's exposure class.
    exposures = exposures.with_columns(
        pl.col("guarantor_entity_type")
        .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
        .alias("guarantor_exposure_class"),
    )

    exposures = _assign_guarantor_approach(exposures, config, errors=errors)

    # Cross-approach CCF substitution (CRR Art. 111 / COREP C07)
    # When IRB exposure guaranteed by SA counterparty, use SA CCFs for guaranteed portion
    exposures = _apply_cross_approach_ccf(exposures)

    # Add post-CRM composite attributes for regulatory reporting. For the
    # guaranteed portion, the post-CRM counterparty is the guarantor.
    exposures = exposures.with_columns(
        # Post-CRM counterparty for guaranteed portion (guarantor or original)
        pl.when(pl.col("guaranteed_portion") > 0)
        .then(pl.col("guarantor_reference"))
        .otherwise(pl.col("counterparty_reference"))
        .alias("post_crm_counterparty_guaranteed"),
        # Post-CRM exposure class for guaranteed portion (guarantor's class or original)
        pl.when((pl.col("guaranteed_portion") > 0) & (pl.col("guarantor_exposure_class") != ""))
        .then(pl.col("guarantor_exposure_class"))
        .otherwise(pl.col("exposure_class"))
        .alias("post_crm_exposure_class_guaranteed"),
        # Flag indicating whether exposure has an effective guarantee
        (pl.col("guaranteed_portion").fill_null(0.0) > 0).alias("is_guaranteed"),
    )

    # Note: Transient columns (guarantor_entity_type, guarantor_cqs, etc.) are kept
    # because downstream SA/IRB calculators need them for risk weight substitution.
    # They can be dropped in the final output aggregation if needed.

    return exposures


def _prepare_guarantees(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Normalise, filter, expand, and haircut guarantees before the split."""
    # Art. 233 H_fx and Art. 233(2) restructuring-exclusion haircuts are
    # regime-invariant scalars sourced from the rulepack. Production threads the
    # run's pack; direct callers resolve an identical one from config.
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    # Default protection_type to "guarantee" when absent, then fill nulls with
    # the same default (backward compatibility for legacy data).
    guarantees = ensure_columns(
        guarantees,
        {"protection_type": ColumnSpec(pl.String, default="guarantee", required=False)},
    )
    guarantees = guarantees.with_columns(
        pl.col("protection_type").fill_null("guarantee").alias("protection_type"),
    )

    # CRR Art. 237(2)(a): unfunded credit protection with original maturity
    # < 1 year is ineligible. Drop ineligible guarantee rows here so the
    # downstream pipeline treats the exposure as un-guaranteed. Null is
    # treated permissively (>= 1y) — mirrors the collateral fallback in
    # engine/crm/haircuts.py:478-484.
    guarantees = ensure_columns(
        guarantees,
        {"original_maturity_years": ColumnSpec(pl.Float64, required=False)},
    )
    guarantees = guarantees.filter(pl.col("original_maturity_years").fill_null(10.0) >= 1.0)

    # CRR / PS1-26 Art. 213(1)(c)(i): drop guarantees the provider can
    # unilaterally cancel (both regimes) or unilaterally change (Basel 3.1
    # only). Runs on the raw per-guarantee rows — before multi-level expansion
    # — so exactly one CRM012 warning is raised per ineligible guarantee.
    guarantees = _gate_unilateral_protection(guarantees, resolved_pack, errors)

    guarantees = _resolve_guarantees_multi_level(guarantees, exposures)

    # Apply haircuts to guarantee amounts BEFORE splitting (Art. 233).
    # Haircuts reduce the nominal credit protection value G, then capping
    # at EAD happens inside the split. This ensures large cross-currency
    # guarantees still fully cover smaller exposures after the haircut.
    guarantees = _apply_fx_haircut_to_guarantees(guarantees, exposures, pack=resolved_pack)
    guarantees = _apply_restructuring_haircut_to_guarantees(guarantees, pack=resolved_pack)

    # CRR Art. 239(3) / PS1/26 Art. 239(3): maturity mismatch adjustment for
    # unfunded credit protection. When the protection's residual maturity t is
    # shorter than the exposure's effective maturity T, the covered amount G is
    # scaled by (t - 0.25) / (T - 0.25), with T capped at 5y. Applied before
    # splitting so the reduced amount_covered propagates through cap-at-EAD.
    # Framework-agnostic (reads only reporting_date + maturity columns; the
    # multiplier is identical under CRR and Basel 3.1), so it runs
    # unconditionally — mirroring the collateral sibling in collateral.py.
    guarantees = _apply_maturity_mismatch_to_guarantees(guarantees, exposures, config)
    return guarantees


@cites("CRR Art. 213")
@cites("PS1/26, paragraph 213")
def _gate_unilateral_protection(
    guarantees: pl.LazyFrame,
    pack: ResolvedRulepack,
    errors: list[CalculationError] | None,
) -> pl.LazyFrame:
    """
    Drop guarantees ineligible under Art. 213(1)(c)(i) (unilateral cancel / change).

    A guarantee the protection provider can unilaterally CANCEL is ineligible
    under both regimes; one whose terms the provider can unilaterally CHANGE
    (increasing the effective cost of protection) is additionally ineligible
    under Basel 3.1 — the "or change" limb is new in PS1/26, gated by the
    ``ucp_unilateral_change_ineligible`` pack Feature. Dropped rows leave the
    exposure un-guaranteed and each raises one CRM012 warning.

    Both flags are null-permissive: a null means "no known defect => eligible",
    mirroring the Art. 237(2)(a) original-maturity fallback in the caller.

    References:
        CRR Art. 213(1)(c)(i): unfunded credit protection eligibility.
        PS1/26 Art. 213(1)(c)(i): adds the unilateral-change arm.
    """
    guarantees = ensure_columns(
        guarantees,
        {
            "is_unilaterally_cancellable": ColumnSpec(pl.Boolean, required=False),
            "is_unilaterally_changeable": ColumnSpec(pl.Boolean, required=False),
        },
    )

    change_gated = pack.feature("ucp_unilateral_change_ineligible")
    ineligible = pl.col("is_unilaterally_cancellable")
    if change_gated:
        ineligible = ineligible | pl.col("is_unilaterally_changeable")
    # Null is permissive (no known defect => eligible): coalesce the Kleene-OR
    # result to False so a null flag never drops the guarantee.
    ineligible = ineligible.fill_null(False)

    if errors is not None:
        _record_ucp_ineligibility(guarantees, ineligible, change_gated, errors)

    return guarantees.filter(~ineligible)


def _record_ucp_ineligibility(
    guarantees: pl.LazyFrame,
    ineligible: pl.Expr,
    change_gated: bool,
    errors: list[CalculationError],
) -> None:
    """Append one CRM012 warning per guarantee dropped by the Art. 213 gate.

    The guarantee table is a small dimension frame (already materialised
    upstream by the CRM stage's ``collect_all``), so a targeted collect of the
    dropped rows to build the per-guarantee messages is cheap — the only
    mid-pipeline collect on this path.
    """
    # The PS1/26 "or change" wording only applies when the change arm is gated
    # (Basel 3.1); under CRR only the cancellation arm can drop a guarantee.
    reg_ref = "PS1/26 Art. 213(1)(c)(i)" if change_gated else "CRR Art. 213(1)(c)(i)"
    arm = "cancel or change" if change_gated else "cancel"
    dropped = guarantees.filter(ineligible).collect()
    for row in dropped.iter_rows(named=True):
        guar_ref = row.get("guarantee_reference")
        beneficiary_ref = row.get("beneficiary_reference")
        errors.append(
            crm_warning(
                ERROR_INELIGIBLE_UNFUNDED_PROTECTION,
                f"Guarantee '{guar_ref}' is ineligible unfunded credit protection "
                f"under Art. 213(1)(c)(i) (the protection provider can unilaterally "
                f"{arm} it); dropped — the exposure flows unguaranteed.",
                exposure_reference=beneficiary_ref,
                regulatory_reference=reg_ref,
            )
        )


def _join_guarantor_counterparty(
    exposures: pl.LazyFrame, counterparty_lookup: pl.LazyFrame
) -> pl.LazyFrame:
    """Join guarantor entity type / country / CCP / SCRA from counterparty data."""
    cp_names = counterparty_lookup.collect_schema().names()
    cp_select_cols = [
        pl.col("counterparty_reference"),
        pl.col("entity_type").str.to_lowercase().alias("guarantor_entity_type"),
    ]
    if "country_code" in cp_names:
        cp_select_cols.append(pl.col("country_code").alias("guarantor_country_code"))
    if "is_ccp_client_cleared" in cp_names:
        cp_select_cols.append(
            pl.col("is_ccp_client_cleared").alias("guarantor_is_ccp_client_cleared")
        )
    if "scra_grade" in cp_names:
        cp_select_cols.append(pl.col("scra_grade").alias("guarantor_scra_grade"))

    exposures = exposures.join(
        counterparty_lookup.select(cp_select_cols),
        left_on="guarantor_reference",
        right_on="counterparty_reference",
        how="left",
    )

    # Ensure optional guarantor columns exist (fill null if not in counterparty data)
    post_join_names = exposures.collect_schema().names()
    fillers: dict[str, PolarsDataType] = {
        "guarantor_country_code": pl.String,
        "guarantor_is_ccp_client_cleared": pl.Boolean,
        "guarantor_scra_grade": pl.String,
    }
    missing_guarantor_cols = [
        pl.lit(None).cast(dtype).alias(name)
        for name, dtype in fillers.items()
        if name not in post_join_names
    ]
    if missing_guarantor_cols:
        exposures = exposures.with_columns(missing_guarantor_cols)
    return exposures


def _join_guarantor_ratings(
    exposures: pl.LazyFrame, rating_inheritance: pl.LazyFrame | None
) -> pl.LazyFrame:
    """Join guarantor CQS / PD / internal_pd from rating inheritance data."""
    if rating_inheritance is None:
        return exposures.with_columns(
            pl.lit(None).cast(pl.Int8).alias("guarantor_cqs"),
            pl.lit(None).cast(pl.Float64).alias("guarantor_pd"),
            pl.lit(None).cast(pl.Float64).alias("guarantor_internal_pd"),
        )

    ri_names = rating_inheritance.collect_schema().names()
    ri_cols = [
        pl.col("counterparty_reference"),
        pl.col("cqs").alias("guarantor_cqs"),
    ]
    # Guarantor PD needed for Basel 3.1 parameter substitution (CRE22.70-85)
    if "pd" in ri_names:
        ri_cols.append(pl.col("pd").alias("guarantor_pd"))
    # Internal PD for approach determination (IRB requires internal rating)
    if "internal_pd" in ri_names:
        ri_cols.append(pl.col("internal_pd").alias("guarantor_internal_pd"))

    exposures = exposures.join(
        rating_inheritance.select(ri_cols),
        left_on="guarantor_reference",
        right_on="counterparty_reference",
        how="left",
    )

    missing_rating_cols: list[pl.Expr] = []
    if "pd" not in ri_names:
        missing_rating_cols.append(pl.lit(None).cast(pl.Float64).alias("guarantor_pd"))
    if "internal_pd" not in ri_names:
        missing_rating_cols.append(pl.lit(None).cast(pl.Float64).alias("guarantor_internal_pd"))
    if missing_rating_cols:
        exposures = exposures.with_columns(missing_rating_cols)
    return exposures


@cites("CRR Art. 201")
@cites("PS1/26, paragraph 201")
def _assign_guarantor_approach(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    errors: list[CalculationError] | None = None,
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

    CRR/PS1-26 Art. 201(1)(g)/(2) eligibility gate: a CORPORATE guarantor is an
    eligible protection provider only if it has an ECAI credit assessment
    (``guarantor_cqs``) or — Art. 201(2), IRB-beneficiary-only — an internal
    rating (``guarantor_internal_pd``) when the beneficiary is itself IRB. An
    ineligible corporate guarantor is rejected: its ``guarantor_exposure_class``
    is cleared so the SA guarantor-RW lookup returns null (non-beneficial), the
    covered leg reverts to the borrower's own basis, and a CRM013 warning is
    raised. Non-corporate classes are governed by other Art. 201 limbs and are
    not gated here.
    """
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    irb_exposure_class_values = {
        ec.value
        for ec, approaches in config.irb_permissions.permissions.items()  # ty: ignore[unresolved-attribute]
        if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches
    }

    irb_beneficiary_approaches = [ApproachType.FIRB.value, ApproachType.AIRB.value]
    schema_names = exposures.collect_schema().names()
    beneficiary_is_irb = (
        pl.col("approach").fill_null("").is_in(irb_beneficiary_approaches)
        if "approach" in schema_names
        else pl.lit(False)
    )

    is_domestic_cgcb_guarantor = _build_domestic_cgcb_flag(schema_names)

    # Art. 201(1)(g)/(2) gate. All inputs are non-null booleans (is_not_null /
    # == on the default-"" class), so no Kleene-null leaks into the gate. The
    # class column can only ever say "corporate" (never "corporate_sme" — the
    # entity->SA-class map has no such entity_type; SME-ness is derived later).
    is_corporate_guarantor = pl.col("guarantor_exposure_class") == "corporate"
    corporate_eligible = pl.col("guarantor_cqs").is_not_null() | (
        beneficiary_is_irb & pl.col("guarantor_internal_pd").is_not_null()
    )
    guarantor_ineligible = (
        is_corporate_guarantor & corporate_eligible.not_() & (pl.col("guaranteed_portion") > 0)
    )

    if errors is not None:
        _record_ineligible_guarantors(exposures, guarantor_ineligible, errors)

    return exposures.with_columns(
        pl.when(is_domestic_cgcb_guarantor)
        .then(pl.lit("sa"))
        .when(
            beneficiary_is_irb
            & (pl.col("guarantor_exposure_class") != "")
            & pl.col("guarantor_exposure_class").is_in(list(irb_exposure_class_values))
            & pl.col("guarantor_internal_pd").is_not_null()
        )
        .then(pl.lit("irb"))
        # SA fallback — gated: an ineligible corporate guarantor takes "" (the
        # existing no-substitution value) rather than "sa".
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
        # corporate so ``build_guarantor_rw_expr`` returns null -> non-beneficial
        # -> the covered leg reverts to the borrower's own basis. Mirrors the
        # existing unmapped-guarantor (class "") no-substitution path.
        pl.when(guarantor_ineligible)
        .then(pl.lit(""))
        .otherwise(pl.col("guarantor_exposure_class"))
        .alias("guarantor_exposure_class"),
    )


def _record_ineligible_guarantors(
    exposures: pl.LazyFrame,
    ineligible: pl.Expr,
    errors: list[CalculationError],
) -> None:
    """Append one CRM013 warning per Art. 201-ineligible corporate guarantor leg.

    Targeted mid-pipeline collect of the ineligible guarantor sub-rows' parent
    loan + guarantor references only — the guarantee book is a small dimension
    (empty when every guarantor is eligible), so materialising just those two
    columns to build the per-leg CRM013 messages is cheap.
    """
    dropped = (
        exposures.filter(ineligible)
        .select("parent_exposure_reference", "guarantor_reference")
        .collect()
    )
    for row in dropped.iter_rows(named=True):
        loan_ref = row.get("parent_exposure_reference")
        guar_ref = row.get("guarantor_reference")
        errors.append(
            crm_warning(
                ERROR_INELIGIBLE_GUARANTOR,
                f"Guarantor '{guar_ref}' is an ineligible protection provider for "
                f"exposure '{loan_ref}': a corporate guarantor without an ECAI credit "
                "assessment (or, for an IRB-approach beneficiary, an internal rating) "
                "is not eligible under Art. 201(1)(g)/(2); the guarantee is not "
                "recognised and the exposure reverts to the borrower's own basis.",
                exposure_reference=loan_ref,
                regulatory_reference="CRR Art. 201(1)(g)",
            )
        )


def _build_domestic_cgcb_flag(schema_names: list[str]) -> pl.Expr:
    """
    Build the EU/UK domestic-currency CGCB guarantor indicator.

    Art. 114(4)/(7): a domestic-currency CGCB guarantor must receive 0% RW
    via the SA short-circuit, even if the guarantor has an internal PD that
    would otherwise route to IRB parameter substitution. The domestic-currency
    test is evaluated against the guarantee currency (the currency of the
    substituted exposure to the sovereign), not the underlying loan's
    currency — Art. 233(3) FX haircut handles any mismatch between guarantee
    and underlying.
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
        "guarantor_country_code", ccy_expr
    )


def _resolve_guarantees_multi_level(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Expand facility and counterparty-level guarantees to exposure-level.

    Direct (loan/contingent) guarantees pass through unchanged. Facility-level
    guarantees are allocated pro-rata by ``ead_after_collateral`` to all child
    exposures under that facility. Counterparty-level guarantees are allocated
    pro-rata across all exposures of that counterparty.

    For amount-based guarantees (``amount_covered``), the amount is split
    proportionally. For percentage-based guarantees (``percentage_covered``),
    the percentage passes through unchanged since it applies equally to each
    child exposure's EAD.

    References:
        CRR Art. 213-217: Unfunded credit protection
        CRE22.70-85: Basel 3.1 guarantee substitution

    Args:
        guarantees: Guarantee data with beneficiary_type and beneficiary_reference
        exposures: Exposures with ead_after_collateral, parent_facility_reference,
                   counterparty_reference

    Returns:
        Guarantees expanded to exposure-level beneficiary_reference
    """
    guar_schema = guarantees.collect_schema()

    if "beneficiary_type" not in guar_schema.names():  # arch-exempt: early-exit guard
        return guarantees

    bt_lower = pl.col("beneficiary_type").str.to_lowercase()

    # --- 1. Direct guarantees — pass through unchanged ---
    direct_guarantees = guarantees.filter(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))

    expanded_parts: list[pl.LazyFrame] = [direct_guarantees]

    # --- 2. Facility-level guarantees — cascade pro-rata over the ancestor set ---
    # A guarantee pledged at any ancestor facility (parent, grandparent, ...
    # root) is allocated pro-rata across that facility's whole descendant subtree
    # — mirroring the collateral / provision cascade. The kernel's membership
    # helper explodes ``ancestor_facilities`` (parent + ancestors incl. self,
    # from the HierarchyResolver), falling back to the 1-element [parent] list
    # when absent — identical to the legacy single-level behaviour.
    exp_schema = exposures.collect_schema()
    has_parent_fac = "parent_facility_reference" in exp_schema.names()

    if has_parent_fac:
        facility_guarantees = guarantees.filter(bt_lower == "facility")
        fac_exposures = explode_facility_membership(exposures, exp_schema.names(), alias="_anc_fac")
        expanded_parts.append(
            _allocate_guarantees_pro_rata(facility_guarantees, fac_exposures, "_anc_fac")
        )

    # --- 3. Counterparty-level guarantees — allocate pro-rata ---
    cp_guarantees = guarantees.filter(bt_lower == "counterparty")
    expanded_parts.append(
        _allocate_guarantees_pro_rata(cp_guarantees, exposures, "counterparty_reference")
    )

    return pl.concat(expanded_parts, how="diagonal")


def _apply_guarantee_splits(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Split guaranteed exposures into per-guarantor sub-rows.

    For each exposure with N guarantors (N >= 1), produces N+1 rows:
    - N guarantor sub-rows, each with that guarantor's covered amount
    - 1 remainder sub-row for the uncovered portion

    Non-guaranteed exposures pass through unchanged.

    References:
        CRR Art. 215-217: Each guarantor's portion receives its own risk weight

    Args:
        guarantees: Exposure-level guarantees (after multi-level resolution)
        exposures: Exposures with ead_after_collateral and parent_exposure_reference

    Returns:
        Exposures with guarantee portions set, potentially with additional rows
    """
    guar_cols = guarantees.collect_schema().names()

    # Pre-aggregate by (beneficiary_reference, guarantor) so that multiple
    # protections from the same guarantor (e.g. direct + facility-level) are
    # summed before we decide whether to split.
    guarantees = guarantees.group_by("beneficiary_reference", "guarantor").agg(
        _build_guarantee_agg_exprs(guar_cols),
    )

    # Refresh schema after aggregation
    guar_cols = guarantees.collect_schema().names()
    guar_select = _build_guarantee_select_cols(guar_cols)

    exposures_with_counts = _attach_guarantee_counts(exposures, guarantees)

    # --- Path 1: No guarantees ---
    no_guarantee = _build_no_guarantee_rows(exposures_with_counts)

    # --- Path 2: Guaranteed exposures — row splitting (N >= 1 guarantors) ---
    multi_joined, join_names = _join_multi_guarantees(
        exposures_with_counts, guarantees, guar_select, "percentage_covered" in guar_cols
    )

    guarantor_sub_rows = _build_guarantor_sub_rows(multi_joined, join_names)
    remainder_sub_rows = _build_remainder_sub_rows(multi_joined)

    # Drop transient columns used during splitting
    transient = [
        "_guar_amount",
        "_guar_ratio",
        "_total_coverage",
        "_scale",
        "_crm_basis",
        "_effective_amount",
        "_effective_ead",
        "_total_effective",
        "amount_covered",
        # CRR Art. 234 tranching points are consumed inside the remainder
        # builder and must not leak downstream.
        "attachment_amount",
        "detachment_amount",
    ]
    if "percentage_covered" in guar_cols:
        transient.append("percentage_covered")

    guarantor_sub_rows = _drop_columns_if_present(guarantor_sub_rows, transient)
    remainder_sub_rows = _drop_columns_if_present(remainder_sub_rows, transient)

    # Concat all paths
    parts = [no_guarantee, guarantor_sub_rows, remainder_sub_rows]
    return pl.concat(parts, how="diagonal_relaxed")


def _build_guarantee_agg_exprs(guar_cols: list[str]) -> list[pl.Expr]:
    """Build aggregation expressions for guarantees, preserving optional columns."""
    agg_exprs: list[pl.Expr] = [pl.col("amount_covered").sum().alias("amount_covered")]
    # (col_name, alias) — alias differs only for currency, where we always
    # rename to guarantee_currency for downstream FX mismatch logic.
    optional_first: list[tuple[str, str]] = [
        ("percentage_covered", "percentage_covered"),
        ("guarantee_reference", "guarantee_reference"),
        ("protection_type", "protection_type"),
    ]
    for src, alias in optional_first:
        if src in guar_cols:
            agg_exprs.append(pl.col(src).first().alias(alias))

    # Preserve guarantee currency for FX mismatch haircut (Art. 233(3-4)).
    # Use original_currency (pre-FX-conversion) if available, else currency.
    if "original_currency" in guar_cols:
        agg_exprs.append(pl.col("original_currency").first().alias("guarantee_currency"))
    elif "currency" in guar_cols:
        agg_exprs.append(pl.col("currency").first().alias("guarantee_currency"))

    # Remaining optional pass-through columns.
    for col in (
        "includes_restructuring",
        "guarantor_seniority",
        "guarantee_fx_haircut",
        "guarantee_restructuring_haircut",
        # CRR Art. 234 mezzanine tranching attachment/detachment points.
        "attachment_amount",
        "detachment_amount",
    ):
        if col in guar_cols:
            agg_exprs.append(pl.col(col).first().alias(col))
    return agg_exprs


def _build_guarantee_select_cols(guar_cols: list[str]) -> list[str]:
    """Build the list of guarantee columns to select for the multi-join."""
    base = ["beneficiary_reference", "amount_covered", "guarantor"]
    optional = (
        "percentage_covered",
        "guarantee_reference",
        "protection_type",
        "guarantee_currency",
        "includes_restructuring",
        "guarantor_seniority",
        "guarantee_fx_haircut",
        "guarantee_restructuring_haircut",
        # CRR Art. 234 mezzanine tranching attachment/detachment points.
        "attachment_amount",
        "detachment_amount",
    )
    return base + [c for c in optional if c in guar_cols]


def _attach_guarantee_counts(exposures: pl.LazyFrame, guarantees: pl.LazyFrame) -> pl.LazyFrame:
    """Attach a per-exposure guarantee_count and clear conflicting columns."""
    guarantee_counts = guarantees.group_by("beneficiary_reference").agg(
        pl.len().alias("guarantee_count"),
    )

    exposures_with_counts = exposures.join(
        guarantee_counts,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    ).with_columns(pl.col("guarantee_count").fill_null(0))

    existing = exposures_with_counts.collect_schema().names()
    to_drop = [c for c in _cols_to_drop_before_join() if c in existing]
    if to_drop:
        exposures_with_counts = exposures_with_counts.drop(to_drop)
    return exposures_with_counts


def _build_no_guarantee_rows(exposures_with_counts: pl.LazyFrame) -> pl.LazyFrame:
    """Return the pass-through rows for exposures with no guarantees."""
    return exposures_with_counts.filter(pl.col("guarantee_count") == 0).with_columns(
        pl.lit(0.0).alias("guaranteed_portion"),
        pl.col("ead_after_collateral").alias("unguaranteed_portion"),
        pl.lit(None).cast(pl.String).alias("guarantor_reference"),
        pl.lit(0.0).alias("guarantee_amount"),
        pl.lit(0.0).alias("original_guarantee_amount"),
        pl.lit(None).cast(pl.String).alias("protection_type"),
        pl.lit(None).cast(pl.String).alias("guarantee_currency"),
        pl.lit(None).cast(pl.Boolean).alias("includes_restructuring"),
        pl.lit(None).cast(pl.String).alias("guarantor_seniority"),
        pl.lit(0.0).alias("guarantee_fx_haircut"),
        pl.lit(0.0).alias("guarantee_restructuring_haircut"),
    )


def _join_multi_guarantees(
    exposures_with_counts: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    guar_select: list[str],
    has_percentage: bool,
) -> tuple[pl.LazyFrame, list[str]]:
    """Join guarantees onto guaranteed exposures and compute effective amounts.

    Returns the joined frame plus its post-join column names (reused by
    ``_build_guarantor_sub_rows`` so the schema is only materialised once).
    """
    multi_guar_exposures = exposures_with_counts.filter(pl.col("guarantee_count") >= 1)
    multi_guarantees = guarantees.select(guar_select)

    multi_joined = multi_guar_exposures.join(
        multi_guarantees,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="inner",
    )

    # CRR Art. 235(1) / 236(3): the covered part Eg = min(GA, E) measures the
    # exposure value E at the CCF=100% basis (ead_for_crm) -- before any credit
    # conversion factor -- with the CCF re-applied to the covered/uncovered split
    # afterwards. Capping and pro-rating coverage against the post-CCF
    # ead_after_collateral would over-recognise cover on undrawn commitments. For
    # pure on-balance-sheet rows ead_for_crm == ead_after_collateral, so the two
    # bases coincide. Fall back to ead_after_collateral only if ead_for_crm is
    # absent/null (defensive; collateral.py always populates it in the pipeline).
    join_names = multi_joined.collect_schema().names()
    crm_basis = (
        pl.coalesce(pl.col("ead_for_crm"), pl.col("ead_after_collateral"))
        if "ead_for_crm" in join_names
        else pl.col("ead_after_collateral")
    )
    multi_joined = multi_joined.with_columns(crm_basis.alias("_crm_basis")).with_columns(
        _resolve_guarantee_amount_expr(has_percentage, "_guar_amount"),
    )

    # Cap total coverage to the CCF=100% basis using pro-rata scaling, then derive
    # the coverage fraction (Eg / E) and re-apply the CCF to size the covered EAD.
    return (
        multi_joined.with_columns(
            pl.col("_guar_amount").sum().over("parent_exposure_reference").alias("_total_coverage"),
        )
        .with_columns(
            pl.min_horizontal(
                pl.lit(1.0),
                pl.col("_crm_basis") / pl.col("_total_coverage"),
            ).alias("_scale"),
        )
        .with_columns(
            (pl.col("_guar_amount") * pl.col("_scale")).alias("_effective_amount"),
        )
        .with_columns(
            # Coverage fraction on the CCF=100% basis. Guard against a null/zero
            # basis (rows with no exposure value) to avoid division-by-zero.
            pl.when(pl.col("_crm_basis") > 0)
            .then(pl.col("_effective_amount") / pl.col("_crm_basis"))
            .otherwise(pl.lit(0.0))
            .alias("_guar_ratio"),
        )
        .with_columns(
            # Re-apply the CCF (Art. 236(3)): covered EAD = coverage fraction x
            # post-CCF EAD. Total EAD stays invariant; only the RW split moves.
            (pl.col("_guar_ratio") * pl.col("ead_after_collateral")).alias("_effective_ead"),
        )
        .with_columns(
            pl.col("_effective_ead")
            .sum()
            .over("parent_exposure_reference")
            .alias("_total_effective"),
        )
    ), join_names


def _build_guarantor_sub_rows(multi_joined: pl.LazyFrame, schema_names: list[str]) -> pl.LazyFrame:
    """Build the per-guarantor sub-rows for guaranteed exposures.

    ``schema_names`` is the post-join column set from ``_join_multi_guarantees``
    (reused here so the joined schema is only materialised once).
    """
    guar_stock_splits: list[pl.Expr] = [
        # Covered EAD (post-CCF) = coverage fraction x ead_after_collateral. The
        # nominal credit-protection amount (G*) stays on guarantee_amount /
        # original_guarantee_amount. CRR Art. 235(1) / 236(3).
        pl.col("_effective_ead").alias("guaranteed_portion"),
        pl.lit(0.0).alias("unguaranteed_portion"),
        pl.col("_effective_ead").alias("ead_after_collateral"),
        pl.col("_effective_amount").alias("guarantee_amount"),
        pl.col("_guar_amount").alias("original_guarantee_amount"),
        pl.col("guarantor").alias("guarantor_reference"),
        pl.concat_str(
            [pl.col("parent_exposure_reference"), pl.lit("__G_"), pl.col("guarantor")],
        ).alias("exposure_reference"),
    ]
    guar_stock_splits.extend(
        (pl.col(c) * pl.col("_guar_ratio")).alias(c)
        for c in _stock_split_cols()
        if c in schema_names
    )
    return multi_joined.with_columns(guar_stock_splits)


@cites("CRR Art. 234")
def _build_remainder_sub_rows(multi_joined: pl.LazyFrame) -> pl.LazyFrame:
    """
    Build the borrower-retained remainder sub-rows (uncovered portion).

    Default (first-loss attach, CRR Art. 235): the protection covers loss band
    ``[0, G*)`` and the borrower retains a single senior remainder ``[G*, EAD]``
    emitted as one ``__REM`` row.

    CRR Art. 234 (tranched coverage): when the guarantee carries an
    ``attachment_amount`` (a) and ``detachment_amount`` (d), the protection
    attaches to the mezzanine band ``[a, d)`` instead of first loss. The
    borrower then retains TWO tranches at its own obligor risk weight:
    a first-loss tranche ``[0, a)`` (``__REM_FL``) and a senior tranche
    ``[d, EAD]`` (``__REM_SEN``). Both retained tranches carry a null
    ``guarantor_reference`` so downstream SA/IRB risk-weight the obligor.

    Tranche widths compose AFTER the existing FX / restructuring / maturity
    mismatch haircuts have reduced ``amount_covered`` to G* (the protected
    width on the guarantor sub-row); ``_total_effective`` is that post-haircut
    capped coverage. When ``attachment_amount`` is null behaviour is unchanged.

    References:
        CRR Art. 234: tranching of credit protection (attachment/detachment).
        CRR Art. 235: SA risk-weight substitution on the protected tranche.
    """
    remainder = (
        multi_joined.sort("parent_exposure_reference", "guarantor")
        .group_by("parent_exposure_reference", maintain_order=True)
        .first()
    )
    schema_names = remainder.collect_schema().names()
    has_tranching = "attachment_amount" in schema_names

    # Total borrower-retained EAD (uncovered portion across all guarantors).
    retained_total = pl.col("ead_after_collateral") - pl.col("_total_effective")

    if not has_tranching:
        return _retained_tranche_rows(remainder, schema_names, retained_total, "__REM")

    # CRR Art. 234: attachment a (null/0 => first-loss). Detachment d defaults to
    # a + protected width so a null detachment collapses to the legacy split.
    attach = pl.col("attachment_amount").fill_null(0.0)
    detach = pl.col("detachment_amount").fill_null(attach + pl.col("_total_effective"))

    # First-loss tranche [0, a) and senior tranche [d, EAD]. Clip widths to the
    # exposure EAD to guard against attachment/detachment overshoot.
    first_loss_width = attach.clip(lower_bound=0.0, upper_bound=pl.col("ead_after_collateral"))
    senior_width = (pl.col("ead_after_collateral") - detach).clip(lower_bound=0.0)

    is_tranched = pl.col("attachment_amount").is_not_null() & (pl.col("attachment_amount") > 0.0)

    legacy_rows = _retained_tranche_rows(
        remainder.filter(~is_tranched), schema_names, retained_total, "__REM"
    )
    first_loss_rows = _retained_tranche_rows(
        remainder.filter(is_tranched), schema_names, first_loss_width, "__REM_FL"
    )
    senior_rows = _retained_tranche_rows(
        remainder.filter(is_tranched), schema_names, senior_width, "__REM_SEN"
    )
    return pl.concat([legacy_rows, first_loss_rows, senior_rows], how="diagonal_relaxed")


def _retained_tranche_rows(
    remainder: pl.LazyFrame,
    schema_names: list[str],
    tranche_ead: pl.Expr,
    suffix: str,
) -> pl.LazyFrame:
    """
    Project one borrower-retained tranche of the given EAD width and suffix.

    Stock columns are split proportionally to this tranche's share of the
    parent EAD so downstream per-counterparty aggregations stay consistent.
    """
    tranche_ratio = (
        pl.when(pl.col("ead_after_collateral") > 0)
        .then(tranche_ead / pl.col("ead_after_collateral"))
        .otherwise(pl.lit(0.0))
    )
    rem_exprs: list[pl.Expr] = [
        pl.lit(0.0).alias("guaranteed_portion"),
        tranche_ead.alias("unguaranteed_portion"),
        tranche_ead.alias("ead_after_collateral"),
        pl.lit(0.0).alias("guarantee_amount"),
        pl.lit(0.0).alias("original_guarantee_amount"),
        pl.lit(None).cast(pl.String).alias("guarantor_reference"),
        pl.lit(None).cast(pl.String).alias("protection_type"),
        pl.lit(None).cast(pl.String).alias("guarantee_currency"),
        pl.lit(None).cast(pl.Boolean).alias("includes_restructuring"),
        pl.lit(None).cast(pl.String).alias("guarantor_seniority"),
        pl.lit(0.0).alias("guarantee_fx_haircut"),
        pl.lit(0.0).alias("guarantee_restructuring_haircut"),
        pl.concat_str(
            [pl.col("parent_exposure_reference"), pl.lit(suffix)],
        ).alias("exposure_reference"),
    ]
    rem_exprs.extend(
        (pl.col(c) * tranche_ratio).alias(c) for c in _stock_split_cols() if c in schema_names
    )
    return remainder.with_columns(rem_exprs)


def _apply_cross_approach_ccf(
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Apply cross-approach CCF substitution for guaranteed exposures.

    When an IRB exposure (F-IRB or A-IRB) is guaranteed by an SA counterparty,
    the guaranteed portion must use SA CCFs for COREP C07 reporting.
    If the guarantor is also IRB, the original IRB CCF is retained.

    Returns:
        Exposures with CCF-adjusted guaranteed/unguaranteed portions
    """
    schema = exposures.collect_schema()
    has_interest = "interest" in schema.names()
    has_risk_type = "risk_type" in schema.names()

    if not has_risk_type:
        return exposures

    # Only IRB exposures with SA guarantors and off-balance-sheet items
    needs_ccf_sub = (
        pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        & (pl.col("guarantor_approach") == "sa")
        & (pl.col("guaranteed_portion") > 0)
        & (pl.col("nominal_amount") > 0)
    )

    sa_ccf = sa_ccf_expression()

    exposures = exposures.with_columns(
        [
            pl.when(pl.col("ead_after_collateral") > 0)
            .then(
                (pl.col("guaranteed_portion") / pl.col("ead_after_collateral")).clip(
                    upper_bound=1.0
                )
            )
            .otherwise(pl.lit(0.0))
            .alias("guarantee_ratio"),
            pl.col("ccf").alias("ccf_original"),
            pl.when(needs_ccf_sub).then(sa_ccf).otherwise(pl.col("ccf")).alias("ccf_guaranteed"),
            pl.col("ccf").alias("ccf_unguaranteed"),
        ]
    )

    # Recalculate EAD with split CCFs when cross-approach substitution applies
    # Use provision-adjusted on-balance and nominal when available
    has_provision_cols = "provision_on_drawn" in schema.names()

    if has_provision_cols and has_interest:
        on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(
            lower_bound=0.0
        ) + interest_for_ead()
    elif has_provision_cols:
        on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
    elif has_interest:
        on_bal = on_balance_ead()
    else:
        on_bal = drawn_for_ead()

    # Use nominal_after_provision if available, else nominal_amount
    nominal_col = (
        pl.col("nominal_after_provision")
        if "nominal_after_provision" in schema.names()
        else pl.col("nominal_amount")
    )
    ratio = pl.col("guarantee_ratio")

    new_guaranteed = (on_bal * ratio) + (nominal_col * ratio * pl.col("ccf_guaranteed"))
    new_unguaranteed = (on_bal * (pl.lit(1.0) - ratio)) + (
        nominal_col * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
    )

    exposures = exposures.with_columns(
        [
            pl.when(needs_ccf_sub)
            .then(new_guaranteed)
            .otherwise(pl.col("guaranteed_portion"))
            .alias("guaranteed_portion"),
            pl.when(needs_ccf_sub)
            .then(new_unguaranteed)
            .otherwise(pl.col("unguaranteed_portion"))
            .alias("unguaranteed_portion"),
        ]
    )

    # Update ead_after_collateral and ead_from_ccf when substitution occurs
    exposures = exposures.with_columns(
        [
            pl.when(needs_ccf_sub)
            .then(pl.col("guaranteed_portion") + pl.col("unguaranteed_portion"))
            .otherwise(pl.col("ead_after_collateral"))
            .alias("ead_after_collateral"),
            pl.when(needs_ccf_sub)
            .then(
                nominal_col * ratio * pl.col("ccf_guaranteed")
                + nominal_col * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
            )
            .otherwise(pl.col("ead_from_ccf"))
            .alias("ead_from_ccf"),
        ]
    )

    return exposures


def _resolve_guarantee_amount_expr(has_percentage: bool, alias: str) -> pl.Expr:
    """Build expression resolving guarantee amount from amount_covered or percentage_covered.

    Percentage-based cover is measured against the CCF=100% basis (``_crm_basis``,
    i.e. ``ead_for_crm``), not the post-CCF ``ead_after_collateral`` -- CRR
    Art. 235(1) / 236(3). ``_crm_basis`` is materialised on the frame in
    ``_join_multi_guarantees`` before this expression is applied.
    """
    if has_percentage:
        return (
            pl.when(
                (
                    pl.col("amount_covered").is_null()
                    | (pl.col("amount_covered").cast(pl.Float64, strict=False).abs() < 1e-10)
                )
                & pl.col("percentage_covered").is_not_null()
                & (pl.col("percentage_covered") > 0)
            )
            .then(pl.col("percentage_covered") * pl.col("_crm_basis"))
            .otherwise(pl.col("amount_covered").fill_null(0.0))
            .alias(alias)
        )
    return pl.col("amount_covered").fill_null(0.0).alias(alias)


def _allocate_guarantees_pro_rata(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    group_col: str,
) -> pl.LazyFrame:
    """Allocate amount-based guarantees pro-rata by ead_after_collateral within a group.

    Thin parameterisation of the allocation kernel's expand direction
    (:func:`rwa_calc.engine.kernels.allocation.expand_items_pro_rata`),
    preserving the guarantee-copy drift axes: the basis is
    ``ead_after_collateral`` (post-collateral EAD — deliberately different
    from the collateral copy's ``ead_for_crm``); the items -> weights join is
    INNER (facility / counterparty guarantees whose group has no exposures
    vanish silently); expanded rows are re-anchored as direct loan-level
    beneficiaries (``beneficiary_type = "loan"``).
    """
    return expand_items_pro_rata(
        guarantees,
        exposures,
        group_key=group_col,
        basis=pl.col("ead_after_collateral"),
        scale_columns=("amount_covered",),
        rewrite_type="loan",
    )


def _apply_fx_haircut_to_guarantees(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """
    Apply FX mismatch haircut to guarantee amounts BEFORE splitting.

    Reduces ``amount_covered`` by H_fx (8%) when the guarantee currency
    differs from the exposure currency. Haircut is applied to the nominal
    credit protection value *before* capping at EAD, per CRR Art. 233(3-4):

        G* = G × (1 − H_fx)

    This ensures that a large guarantee in a foreign currency still fully
    covers a smaller exposure (e.g. £200m guarantee on €1m loan with 8%
    haircut → £184m effective → still fully covers €1m).

    References:
        CRR Art. 233(3-4), Art. 235(1): G = nominal credit protection value
        Art. 224 Table 4: H_fx = 8% (10-day liquidation period)
    """
    guar_schema = guarantees.collect_schema()
    guar_cols = guar_schema.names()

    # Determine guarantee currency column
    if "original_currency" in guar_cols:
        guar_ccy_col = "original_currency"
    elif "currency" in guar_cols:
        guar_ccy_col = "currency"
    else:
        return guarantees.with_columns(pl.lit(0.0).alias("guarantee_fx_haircut"))

    # Determine exposure currency column
    exp_schema = exposures.collect_schema()
    exp_cols = exp_schema.names()
    if "original_currency" in exp_cols:
        exp_ccy_col = "original_currency"
    elif "currency" in exp_cols:
        exp_ccy_col = "currency"
    else:
        return guarantees.with_columns(pl.lit(0.0).alias("guarantee_fx_haircut"))

    # Join guarantees with exposure currency (lightweight join)
    exp_ccy = exposures.select(
        pl.col("exposure_reference"),
        pl.col(exp_ccy_col).alias("_exp_ccy"),
    )

    guarantees = guarantees.join(
        exp_ccy,
        left_on="beneficiary_reference",
        right_on="exposure_reference",
        how="left",
    )

    h_fx = scalar_value(pack.scalar_param("fx_haircut"))
    has_pct = "percentage_covered" in guar_cols

    # Guarantee provides coverage via amount or percentage
    has_coverage = pl.col("amount_covered").fill_null(0.0) > 0
    if has_pct:
        has_coverage = has_coverage | (pl.col("percentage_covered").fill_null(0.0) > 0)

    fx_mismatch = (
        pl.col(guar_ccy_col).is_not_null()
        & pl.col("_exp_ccy").is_not_null()
        & (pl.col(guar_ccy_col) != pl.col("_exp_ccy"))
        & has_coverage
    )

    haircut_exprs: list[pl.Expr] = [
        # Amount-based: reduce amount_covered
        pl.when(fx_mismatch)
        .then(pl.col("amount_covered") * (1.0 - h_fx))
        .otherwise(pl.col("amount_covered"))
        .alias("amount_covered"),
        # Track the haircut applied
        pl.when(fx_mismatch)
        .then(pl.lit(h_fx))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_fx_haircut"),
    ]

    # Percentage-based: reduce percentage_covered (G = pct × EAD, so G* = pct × (1-H) × EAD)
    if has_pct:
        haircut_exprs.append(
            pl.when(fx_mismatch)
            .then(pl.col("percentage_covered") * (1.0 - h_fx))
            .otherwise(pl.col("percentage_covered"))
            .alias("percentage_covered"),
        )

    guarantees = guarantees.with_columns(haircut_exprs)

    return guarantees.drop("_exp_ccy")


def _apply_restructuring_haircut_to_guarantees(
    guarantees: pl.LazyFrame,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """
    Apply CDS restructuring exclusion haircut to guarantee amounts BEFORE splitting.

    When a credit derivative does not include restructuring as a credit event,
    ``amount_covered`` is reduced by 40%:

        G* = G × (1 − H_restructuring) = G × 0.60

    Applied to nominal credit protection value before capping/splitting,
    consistent with CRR Art. 233(2).

    References:
        CRR Art. 233(2), PRA PS1/26 Art. 233(2)
        Art. 216(1): Credit events for credit derivatives
    """
    schema = guarantees.collect_schema()
    cols = schema.names()

    has_protection_type = "protection_type" in cols
    has_includes_restructuring = "includes_restructuring" in cols

    if not has_protection_type or not has_includes_restructuring:
        return guarantees.with_columns(
            pl.lit(0.0).alias("guarantee_restructuring_haircut"),
        )

    h_restructuring = scalar_value(pack.scalar_param("restructuring_exclusion_haircut"))

    applies = (
        (pl.col("protection_type") == "credit_derivative")
        & (pl.col("includes_restructuring").fill_null(True).not_())
        & (pl.col("amount_covered").fill_null(0.0) > 0)
    )

    return guarantees.with_columns(
        pl.when(applies)
        .then(pl.col("amount_covered") * (1.0 - h_restructuring))
        .otherwise(pl.col("amount_covered"))
        .alias("amount_covered"),
        pl.when(applies)
        .then(pl.lit(h_restructuring))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_restructuring_haircut"),
    )


def redistribute_non_beneficial(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """
    Redistribute non-beneficial guarantee portions to beneficial guarantors.

    When multi-guarantor exposures have mixed beneficial/non-beneficial sub-rows,
    the non-beneficial portions are reallocated to beneficial guarantors using a
    greedy strategy ordered by ascending ``guarantor_rw`` (lowest risk weight first).
    This minimises total RWA by filling the best guarantors first.

    Only operates on multi-guarantor sub-rows (created by ``_apply_guarantee_splits``).
    Single-guarantor and non-guaranteed exposures pass through unchanged.

    References:
        CRR Art. 213: Only beneficial guarantees should be applied
        CRR Art. 215-217: Guarantee substitution with multiple protections
    """
    schema = exposures.collect_schema()
    cols = schema.names()

    # Guard: need the columns created by _apply_guarantee_splits and the beneficial check
    required = [
        "parent_exposure_reference",
        "exposure_reference",
        "is_guarantee_beneficial",
        "guaranteed_portion",
        "ead_after_collateral",
        "original_guarantee_amount",
        "guarantor_rw",
    ]
    if not all(c in cols for c in required):
        return exposures

    # Classify row types
    is_sub_row = pl.col("parent_exposure_reference") != pl.col("exposure_reference")
    # Art. 234 tranching emits two retained sub-rows ("__REM_FL"/"__REM_SEN")
    # alongside the legacy single "__REM" row, so match the "__REM" stem anywhere.
    is_remainder = pl.col("exposure_reference").str.contains("__REM")
    is_guarantor_sub = is_sub_row & ~is_remainder

    # Check if any parent group has mixed beneficial/non-beneficial sub-rows.
    # If no non-beneficial sub-rows exist at all, skip redistribution entirely.
    has_non_ben = (
        pl.when(~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .sum()
        .over("parent_exposure_reference")
    )
    has_ben = (
        pl.when(pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .sum()
        .over("parent_exposure_reference")
    )

    # Only redistribute for groups that have BOTH beneficial and non-beneficial
    needs_redistribution = (has_non_ben > 0) & (has_ben > 0) & is_sub_row

    # Pre-compute group-level amounts
    exposures = exposures.with_columns(
        # Total non-beneficial amount to free up (per parent group)
        pl.when(~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.col("guaranteed_portion"))
        .otherwise(pl.lit(0.0))
        .sum()
        .over("parent_exposure_reference")
        .alias("_non_ben_total"),
        # Total parent EAD (sum of all sub-row EADs in the group)
        pl.when(is_sub_row)
        .then(pl.col("ead_after_collateral"))
        .otherwise(pl.lit(0.0))
        .sum()
        .over("parent_exposure_reference")
        .alias("_parent_ead"),
    )

    # For beneficial sub-rows, compute remaining capacity and sort rank
    exposures = exposures.with_columns(
        pl.when(pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(
            (pl.col("original_guarantee_amount") - pl.col("guaranteed_portion")).clip(
                lower_bound=0.0
            )
        )
        .otherwise(pl.lit(0.0))
        .alias("_remaining_capacity"),
    )

    # Greedy fill: sort beneficial guarantors by guarantor_rw ascending,
    # compute cumulative capacity, and determine how much each absorbs.
    # Use ordered window function so lowest-RW guarantors fill first.
    exposures = exposures.with_columns(
        # Cumulative capacity of beneficial guarantors sorted by RW (ascending)
        # For non-beneficial or non-sub-rows, capacity is 0 so cumsum stays 0.
        pl.col("_remaining_capacity")
        .cum_sum()
        .over("parent_exposure_reference", order_by="guarantor_rw")
        .alias("_cum_capacity"),
    )

    exposures = exposures.with_columns(
        # Previous cumulative (capacity of better-ranked guarantors)
        (pl.col("_cum_capacity") - pl.col("_remaining_capacity")).alias("_prev_cum"),
    )

    # Each beneficial guarantor absorbs:
    #   min(remaining_capacity, max(0, freed_amount - prev_cumulative))
    absorbed = pl.min_horizontal(
        pl.col("_remaining_capacity"),
        (pl.col("_non_ben_total") - pl.col("_prev_cum")).clip(lower_bound=0.0),
    )

    # Compute new guaranteed portion for each row
    new_guaranteed = (
        pl.when(needs_redistribution & pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.col("guaranteed_portion") + absorbed)
        .when(needs_redistribution & ~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(0.0))
        .otherwise(pl.col("guaranteed_portion"))
    )

    # Compute total new beneficial EAD per group (for remainder calculation)
    exposures = exposures.with_columns(new_guaranteed.alias("_new_guaranteed"))

    new_ben_total = (
        pl.when(is_guarantor_sub)
        .then(pl.col("_new_guaranteed"))
        .otherwise(pl.lit(0.0))
        .sum()
        .over("parent_exposure_reference")
    )

    # Update all affected columns
    exposures = exposures.with_columns(
        # guaranteed_portion
        pl.col("_new_guaranteed").alias("guaranteed_portion"),
        # ead_after_collateral: for guarantor sub-rows = guaranteed_portion,
        # for remainder = parent_ead - sum(guarantor sub-row EADs)
        pl.when(needs_redistribution & is_guarantor_sub)
        .then(pl.col("_new_guaranteed"))
        .when(needs_redistribution & is_remainder)
        .then((pl.col("_parent_ead") - new_ben_total).clip(lower_bound=0.0))
        .otherwise(pl.col("ead_after_collateral"))
        .alias("ead_after_collateral"),
        # unguaranteed_portion
        pl.when(needs_redistribution & pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(0.0))
        .when(needs_redistribution & ~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(0.0))
        .when(needs_redistribution & is_remainder)
        .then((pl.col("_parent_ead") - new_ben_total).clip(lower_bound=0.0))
        .otherwise(pl.col("unguaranteed_portion"))
        .alias("unguaranteed_portion"),
    )

    # Drop transient columns
    transient = [
        "_non_ben_total",
        "_parent_ead",
        "_remaining_capacity",
        "_cum_capacity",
        "_prev_cum",
        "_new_guaranteed",
    ]
    return _drop_columns_if_present(exposures, transient)


@cites("CRR Art. 217")
def _apply_maturity_mismatch_to_guarantees(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Apply CRR Art. 239(3) maturity mismatch scaling to guarantee amounts.

    When the protection's residual maturity ``t`` is shorter than the
    exposure's effective maturity ``T``, the covered amount ``G`` is scaled:

        GA = G* × (t - 0.25) / (T - 0.25)

    with ``T`` capped at 5.0 years and both ``t`` and ``T`` floored at 0.25
    (so any t < 0.25 yields zero coverage; the >=1y original-maturity floor
    in Art. 237(2)(a) is enforced separately upstream). Scaling is applied
    to ``amount_covered`` and ``percentage_covered`` before the split, so
    the reduced nominal protection value propagates through cap-at-EAD.

    The protection residual maturity ``t`` is derived from the guarantee
    row's ``maturity_date`` if present, otherwise from
    ``original_maturity_years``. The exposure residual ``T`` is derived
    from the exposure's ``maturity_date``.

    References:
        CRR Art. 237(2): minimum maturity / mismatch eligibility
        CRR Art. 238(1): maturity of credit protection — ``t`` is the RESIDUAL
            maturity (time remaining to protection maturity), not the original
            contract term; the residual from ``maturity_date`` therefore wins
            and ``original_maturity_years`` is only a fallback.
        CRR Art. 239(3): maturity mismatch adjustment formula
    """
    guar_schema = guarantees.collect_schema()
    guar_cols = guar_schema.names()
    exp_schema = exposures.collect_schema()
    exp_cols = exp_schema.names()

    # Need exposure maturity_date and at least one of guarantee maturity_date
    # / original_maturity_years to compute t and T.
    if "maturity_date" not in exp_cols:
        return guarantees
    has_guar_maturity_date = "maturity_date" in guar_cols
    has_guar_original_maturity = "original_maturity_years" in guar_cols
    if not (has_guar_maturity_date or has_guar_original_maturity):
        return guarantees

    # Bring exposure residual maturity (years) onto each guarantee row.
    exp_t_expr = exact_fractional_years_expr(config.reporting_date, "maturity_date").alias("_exp_T")
    exp_lookup = exposures.select(
        pl.col("exposure_reference"),
        exp_t_expr,
    )

    guarantees = guarantees.join(
        exp_lookup,
        left_on="beneficiary_reference",
        right_on="exposure_reference",
        how="left",
    )

    # Compute t = RESIDUAL maturity (Art. 238(1)): the time REMAINING to
    # protection maturity, derived from the guarantee ``maturity_date`` minus
    # the reporting date. ``original_maturity_years`` is the ORIGINAL contract
    # term and must NOT override the residual — otherwise a seasoned guarantee
    # (long original term, short residual) is over-recognised. It is used for
    # ``t`` only as a fallback when ``maturity_date`` is null. The separate
    # Art. 237(2)(a) >=1y eligibility gate upstream still reads
    # ``original_maturity_years`` (the original term). Null t means "no info"
    # and yields no scaling.
    if has_guar_maturity_date and has_guar_original_maturity:
        t_from_date = exact_fractional_years_expr(config.reporting_date, "maturity_date")
        t_raw = (
            pl.when(pl.col("maturity_date").is_not_null())
            .then(t_from_date)
            .otherwise(pl.col("original_maturity_years"))
        )
    elif has_guar_maturity_date:
        t_raw = exact_fractional_years_expr(config.reporting_date, "maturity_date")
    else:
        t_raw = pl.col("original_maturity_years")

    # Apply Art. 239(3) floors / caps:
    #   t floored at 0.25, T capped at 5.0 and floored at 0.25.
    floor = pl.lit(0.25)
    cap = pl.lit(5.0)
    t_eff = pl.max_horizontal(t_raw, floor)
    t_eff_safe = pl.when(t_raw.is_null()).then(pl.lit(None, dtype=pl.Float64)).otherwise(t_eff)
    exp_t_eff = pl.max_horizontal(pl.min_horizontal(pl.col("_exp_T"), cap), floor)
    exp_t_eff_safe = (
        pl.when(pl.col("_exp_T").is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(exp_t_eff)
    )

    # Mismatch only applies when t < T (else no scaling).
    is_mismatch = (
        t_eff_safe.is_not_null() & exp_t_eff_safe.is_not_null() & (t_eff_safe < exp_t_eff_safe)
    )
    scale = (t_eff_safe - floor) / (exp_t_eff_safe - floor)
    scale_safe = pl.when(is_mismatch).then(scale).otherwise(pl.lit(1.0))

    scale_exprs: list[pl.Expr] = []
    if "amount_covered" in guar_cols:
        scale_exprs.append((pl.col("amount_covered") * scale_safe).alias("amount_covered"))
    if "percentage_covered" in guar_cols:
        scale_exprs.append((pl.col("percentage_covered") * scale_safe).alias("percentage_covered"))

    if scale_exprs:
        guarantees = guarantees.with_columns(scale_exprs)

    return guarantees.drop("_exp_T")


def _drop_columns_if_present(lf: pl.LazyFrame, cols: list[str]) -> pl.LazyFrame:
    """Drop columns from LazyFrame, ignoring those not present."""
    schema = lf.collect_schema()
    to_drop = [c for c in cols if c in schema.names()]
    return lf.drop(to_drop) if to_drop else lf
