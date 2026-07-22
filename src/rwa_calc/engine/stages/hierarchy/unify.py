"""
Exposure unification for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (stages/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``resolver``.

Key responsibilities:
- Project loans and contingents onto the unified exposure schema
  (including the ONB/OFB drawn-vs-nominal switch and the FCCM / Pool-B
  pass-through columns).
- Concat loans + contingents + synthetic facility_undrawn rows into the
  single unified exposures frame.
- Attach facility metadata (parent/root facility refs, hierarchy depth,
  ancestor closure) and delegate QRRE propagation + rating attach to
  ``enrich``.

References:
- CRR Art. 166: exposure value components (drawn / undrawn / contingent)
- CRR Art. 223(5): FCCM exposure volatility haircut (HE) inputs
- CRR Art. 159(1)(c)/(d): Pool B inputs (AVAs, other own-funds reductions)
- CRR Art. 230-231: facility-level collateral cascade (ancestor closure)
- PRA PS1/26 Art. 111(1) Table A1 Row 4(b) / Art. 166E(5): commitment flags
- PRA PS1/26 Art. 124(3) / Art. 124K: under-construction (ADC) flag
- PRA PS1/26 Art. 161(1)(e)/(f)/(g): purchased receivables F-IRB LGD subtype
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine.stages.hierarchy.enrich import (
    attach_counterparty_rating,
    propagate_facility_qrre_columns,
)
from rwa_calc.engine.stages.hierarchy.facility_undrawn import calculate_facility_undrawn
from rwa_calc.engine.stages.hierarchy.graph import (
    build_facility_ancestor_closure,
    build_facility_root_lookup,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CounterpartyLookup
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


def unify_exposures(
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    facilities: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    counterparty_lookup: CounterpartyLookup,
    config: CalculationConfig | None = None,
) -> tuple[pl.LazyFrame, list[CalculationError]]:
    """
    Unify loans, contingents, and facility undrawn into a single exposures LazyFrame.

    Creates three types of exposures:
    - loan: Drawn amounts from loans
    - contingent: Off-balance sheet items (guarantees, LCs, etc.)
    - facility_undrawn: Undrawn facility headroom (limit - drawn loans)

    Returns:
        Tuple of (unified exposures LazyFrame, list of errors)
    """
    # Output schema invariants — the unified exposures frame must surface these
    # columns for downstream calculators (EAD / LGD / maturity). Listed here as
    # a bytecode anchor for tests/unit/test_effective_maturity.py::
    # test_effective_maturity_on_exposures_frame_schema, which validates the
    # invariant via __code__.co_consts introspection. Keep at least one entry
    # so the test continues to find the literal after per-source coercion has
    # been factored into helpers.
    _OUTPUT_SCHEMA_INVARIANTS: tuple[str, ...] = ("effective_maturity",)  # noqa: F841

    errors: list[CalculationError] = []

    loans_unified = _coerce_loans_to_unified(loans)
    exposure_frames: list[pl.LazyFrame] = [loans_unified]

    contingents_unified = _coerce_contingents_to_unified(contingents)
    if contingents_unified is not None:
        exposure_frames.append(contingents_unified)

    # Build facility root lookup for multi-level hierarchies, then add
    # synthetic facility_undrawn exposures for the unused headroom.
    facility_root_lookup = build_facility_root_lookup(facility_mappings)
    facility_undrawn = calculate_facility_undrawn(
        facilities,
        loans,
        contingents,
        facility_mappings,
        facility_root_lookup,
        counterparty_lookup=counterparty_lookup,
        config=config,
    )
    exposure_frames.append(facility_undrawn)

    # Combine all exposure types into the unified frame, then enrich with
    # parent/root facility mapping, QRRE-relevant facility-level columns,
    # and counterparty rating fields needed by downstream stages.
    exposures = pl.concat(exposure_frames, how="diagonal_relaxed")
    exposures = _join_facility_metadata(exposures, facility_mappings, facility_root_lookup)
    exposures = propagate_facility_qrre_columns(exposures, facilities)
    exposures = attach_counterparty_rating(exposures, counterparty_lookup)

    return exposures, errors


def _coerce_loans_to_unified(loans: pl.LazyFrame) -> pl.LazyFrame:
    """Project the loans frame onto the unified exposure schema.

    Loans are drawn exposures, so CCF fields are N/A — EAD = drawn_amount +
    interest directly. CCF only applies to off-balance sheet items (undrawn
    commitments, contingents).
    """
    loan_select_exprs = [
        pl.col("loan_reference").alias("exposure_reference"),
        # Pre-concatenation base reference for reconciliation linking. A loan is
        # base-grain, so it equals exposure_reference here; guarantee / RE-split
        # sub-rows inherit this value unchanged (they only mutate
        # exposure_reference), recovering the original loan reference on collapse.
        pl.col("loan_reference").alias("source_exposure_reference"),
        pl.lit("loan").alias("exposure_type"),
        pl.col("product_type"),
        pl.col("book_code").cast(pl.String, strict=False),  # Ensure consistent type
        # CRR Art. 113(6) core-UK-group 0% RW carrier — declared on LOAN_SCHEMA,
        # set by the scope resolver; without this pass-through the unified select
        # would drop it and the SA final-RW override would never see it.
        pl.col("intragroup_zero_rw_eligible"),
        # CRR Art. 148/150 IRB roll-out-plan flag — declared on LOAN_SCHEMA, a pure
        # pass-through carried to the aggregator exit for COREP C 08.07 col 0040;
        # without this the unified select would drop it (dropping it silently
        # collapses genuine roll-out exposures into permanent-partial-use).
        pl.col("is_under_irb_rollout"),
        pl.col("counterparty_reference"),
        pl.col("value_date"),
        pl.col("maturity_date"),
        pl.col("currency"),
        # CRR Art. 114(4)/(7) via Art. 235(3): funding currency for the domestic-
        # CGCB 0%-extension funding limb. Declared on LOAN_SCHEMA (nullable), so
        # the sealed loans frame always carries it; without this pass-through the
        # unified ``select`` would drop it and the funding limb would silently
        # fall back to the denomination currency for every exposure.
        pl.col("funding_currency"),
        pl.col("drawn_amount"),
        pl.col("interest").fill_null(0.0),
        pl.lit(0.0).alias("undrawn_amount"),
        pl.lit(0.0).alias("nominal_amount"),
        pl.col("lgd").cast(pl.Float64, strict=False),
        pl.col("lgd_unsecured").cast(pl.Float64, strict=False),
        pl.col("has_sufficient_collateral_data").cast(pl.Boolean, strict=False),
        pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0),
        pl.col("seniority"),
        pl.lit(None).cast(pl.String).alias("risk_type"),  # N/A for drawn loans
        pl.lit(None).cast(pl.String).alias("underlying_risk_type"),  # N/A for drawn loans
        pl.lit(None).cast(pl.Float64).alias("ccf_modelled"),  # N/A for drawn loans
        pl.lit(None).cast(pl.Float64).alias("ead_modelled"),  # N/A for drawn loans
        pl.lit(None).cast(pl.Boolean).alias("is_short_term_trade_lc"),  # N/A for drawn loans
        pl.lit(None).cast(pl.Boolean).alias("is_obs_commitment"),  # N/A for drawn loans
        # PRA PS1/26 Art. 111(1) Table A1 Row 4(b) and Art. 166E(5): both
        # commitment flags are off-balance-sheet only and are not declared
        # on LOAN_SCHEMA — a sealed loans frame never carries them, so emit
        # False purely for schema alignment.
        pl.lit(False).alias("is_uk_residential_mortgage_commitment"),
        pl.lit(False).alias("is_purchased_receivable_commitment"),
        pl.col("is_payroll_loan"),
        pl.col("is_buy_to_let"),
        # PRA PS1/26 Art. 124(3) / Art. 124K: under-construction flag drives
        # ADC classification derivation in the classifier.
        pl.col("is_under_construction"),
        pl.col("has_one_day_maturity_floor"),
        pl.col("is_sft"),
        pl.col("effective_maturity"),
        pl.col("netting_agreement_reference"),
        # facility_termination_date is facility-level; inherited via facility join later
        pl.lit(None).cast(pl.Date).alias("facility_termination_date"),
    ]
    # CLASSIFIER_OUTPUT_SCHEMA pass-through columns. CRE / RRE acceptance
    # fixtures (e.g. P1.181 Art. 126(2)(d) proportion split) carry these on
    # the loan row instead of a separate collateral row; without explicit
    # pass-through ``select`` would drop them and the downstream SA
    # real-estate branch would mis-route the exposure. All are declared on
    # LOAN_SCHEMA, so the sealed loans frame always carries them.
    loan_select_exprs.extend(
        pl.col(col_name).cast(col_dtype, strict=False)
        for col_name, col_dtype in (
            ("ltv", pl.Float64),
            ("property_type", pl.String),
            ("has_income_cover", pl.Boolean),
            ("is_defaulted", pl.Boolean),
            # PRA PS1/26 Art. 161(1)(e)/(f)/(g): purchased receivables F-IRB LGD subtype.
            ("purchased_receivables_subtype", pl.String),
            # CRR Art. 223(5) FCCM exposure volatility haircut (HE) inputs — used
            # by the CRM engine to gross up E by (1 + HE) when the exposure is
            # itself a debt security (typically SFTs lending out a bond). The CRM
            # path keys off these fields per loan; without explicit pass-through
            # the select would drop them and HE would default to 0.
            ("exposure_collateral_type", pl.String),
            ("exposure_security_cqs", pl.Int8),
            ("exposure_security_residual_maturity_years", pl.Float64),
            # CRR Art. 159(1)(c)/(d) Pool B inputs — additional value adjustments
            # (AVAs per Art. 34) and other own funds reductions enter the per-
            # exposure Pool B exactly once at the IRB EL shortfall stage
            # (engine/irb/adjustments.py compute_el_shortfall_excess). Without
            # explicit pass-through the unified select would drop them and
            # Pool B would silently lose components (c) and (d).
            ("ava_amount", pl.Float64),
            ("other_own_funds_reductions", pl.Float64),
        )
    )
    return loans.select(loan_select_exprs)


def _coerce_contingents_to_unified(
    contingents: pl.LazyFrame | None,
) -> pl.LazyFrame | None:
    """Project contingents onto the unified exposure schema with bs_type-dependent
    drawn / undrawn behaviour.

    ONB (drawn): drawn_amount = nominal, nominal = 0, CCF fields nullified.
    OFB (undrawn, default): drawn_amount = 0, nominal = nominal, CCF fields preserved.

    Returns ``None`` if no contingents were provided so the caller can skip
    the concat-frame append.
    """
    if contingents is None:
        return None

    is_drawn = pl.col("bs_type").fill_null("OFB").str.to_uppercase() == "ONB"

    return contingents.select(
        [
            pl.col("contingent_reference").alias("exposure_reference"),
            # Pre-concatenation base reference for reconciliation linking
            # (base-grain; guarantee / RE-split sub-rows inherit it unchanged).
            pl.col("contingent_reference").alias("source_exposure_reference"),
            pl.lit("contingent").alias("exposure_type"),
            pl.col("product_type"),
            pl.col("book_code").cast(pl.String, strict=False),
            # CRR Art. 113(6) core-UK-group 0% RW carrier (see
            # _coerce_loans_to_unified). Declared on CONTINGENTS_SCHEMA.
            pl.col("intragroup_zero_rw_eligible"),
            # CRR Art. 148/150 IRB roll-out-plan flag (see _coerce_loans_to_unified).
            # Declared on CONTINGENTS_SCHEMA; carried for COREP C 08.07 col 0040.
            pl.col("is_under_irb_rollout"),
            pl.col("counterparty_reference"),
            pl.col("value_date"),
            pl.col("maturity_date"),
            pl.col("currency"),
            # CRR Art. 114(4)/(7) via Art. 235(3): funding-currency pass-through
            # (see _coerce_loans_to_unified). Declared on CONTINGENTS_SCHEMA.
            pl.col("funding_currency"),
            pl.when(is_drawn)
            .then(pl.col("nominal_amount"))
            .otherwise(pl.lit(0.0))
            .alias("drawn_amount"),
            pl.lit(0.0).alias("interest"),
            pl.lit(0.0).alias("undrawn_amount"),
            pl.when(is_drawn)
            .then(pl.lit(0.0))
            .otherwise(pl.col("nominal_amount"))
            .alias("nominal_amount"),
            pl.col("lgd").cast(pl.Float64, strict=False),
            pl.col("lgd_unsecured").cast(pl.Float64, strict=False),
            pl.col("has_sufficient_collateral_data").cast(pl.Boolean, strict=False),
            pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0),
            pl.col("seniority"),
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.String))
            .otherwise(pl.col("risk_type"))
            .alias("risk_type"),
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.String))
            .otherwise(pl.col("underlying_risk_type"))
            .alias("underlying_risk_type"),
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("ccf_modelled").cast(pl.Float64, strict=False))
            .alias("ccf_modelled"),
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("ead_modelled").cast(pl.Float64, strict=False))
            .alias("ead_modelled"),
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.Boolean))
            .otherwise(pl.col("is_short_term_trade_lc"))
            .alias("is_short_term_trade_lc"),
            # CRR Art. 166(8)(d) vs Art. 166(10): contingent rows are issued
            # OBS items by default (False -> Art. 166(10) fallback under F-IRB).
            # Callers may override to True for commitment-style contingents
            # (e.g., a contingent representing a NIF/RUF). The column is
            # loader-defaulted (schema default False), so no null fill needed.
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.Boolean))
            .otherwise(pl.col("is_obs_commitment"))
            .alias("is_obs_commitment"),
            # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): residential-property
            # commitment flag. Meaningful only for undrawn (OFB) contingents;
            # nullified for drawn (ONB) rows, mirroring is_obs_commitment.
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.Boolean))
            .otherwise(pl.col("is_uk_residential_mortgage_commitment"))
            .alias("is_uk_residential_mortgage_commitment"),
            # PRA PS1/26 Art. 166E(5): revolving purchased-receivables undrawn
            # purchase commitment flag. Meaningful only for undrawn (OFB)
            # contingents; nullified for drawn (ONB) rows, mirroring
            # is_uk_residential_mortgage_commitment.
            pl.when(is_drawn)
            .then(pl.lit(None).cast(pl.Boolean))
            .otherwise(pl.col("is_purchased_receivable_commitment"))
            .alias("is_purchased_receivable_commitment"),
            pl.lit(False).alias("is_payroll_loan"),  # Payroll loans are term loans, not contingents
            pl.lit(False).alias(
                "is_buy_to_let"
            ),  # BTL is a property lending characteristic, not for contingents
            # PRA PS1/26 Art. 124(3) / Art. 124K: under-construction flag drives
            # ADC classification derivation in the classifier.
            pl.col("is_under_construction"),
            pl.col("has_one_day_maturity_floor"),
            pl.col("is_sft"),
            pl.col("effective_maturity"),
            pl.lit(None).cast(pl.String).alias("netting_agreement_reference"),
            # facility_termination_date is facility-level; inherited via facility join later
            pl.lit(None).cast(pl.Date).alias("facility_termination_date"),
        ]
    )


def _join_facility_metadata(
    exposures: pl.LazyFrame,
    facility_mappings: pl.LazyFrame,
    facility_root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Attach ``parent_facility_reference``, ``exposure_has_parent``,
    ``root_facility_reference``, and ``facility_hierarchy_depth`` to the
    unified exposures frame.

    Uses ``facility_mappings`` for the immediate parent (filtered to
    non-facility children to avoid duplication when a sub-facility shares a
    reference with a loan), and ``facility_root_lookup`` for the multi-level
    root resolution. Single-level cases (no entry in the lookup) collapse to
    parent-as-root with depth = 1.
    """
    # Filter out child_type="facility" entries since unified exposures contain only
    # loans, contingents, and facility_undrawn (never raw facilities).
    # Without this filter, when facility_reference = loan_reference AND the facility
    # is a sub-facility, child_reference has duplicate values causing row duplication.
    # Null child_type values (legacy mappings) fill to "" and naturally
    # pass through the != "facility" filter, preserving today's behaviour.
    exposure_level_mappings = (
        facility_mappings.filter(
            pl.col("child_type").fill_null("").str.to_lowercase() != "facility"
        )
        .select(
            [
                pl.col("child_reference"),
                pl.col("parent_facility_reference").alias("mapped_parent_facility"),
            ]
        )
        .unique(subset=["child_reference"], keep="first")
    )

    exposures = exposures.join(
        exposure_level_mappings,
        left_on="exposure_reference",
        right_on="child_reference",
        how="left",
    )

    # Add facility hierarchy fields.
    # For facility_undrawn exposures, source_facility_reference provides
    # the parent facility; for loans/contingents it's null after diagonal_relaxed
    # concat. Coalesce handles both cases without a collect_schema() call.
    _parent_expr = pl.coalesce(
        pl.col("mapped_parent_facility"),
        pl.col("source_facility_reference"),
    )
    exposures = exposures.with_columns(
        [
            _parent_expr.alias("parent_facility_reference"),
            _parent_expr.is_not_null().alias("exposure_has_parent"),
        ]
    )

    # Attach the facility ancestor closure (parent + every ancestor up to the
    # root, incl. self) so the CRM stage can cascade facility-level collateral
    # down nested facility hierarchies. Facilities absent from the closure
    # (roots / single-level) fall back to the 1-element [parent] list, which
    # makes the CRM cascade reduce to the legacy single-level allocation.
    ancestor_lists = build_facility_ancestor_closure(facility_mappings)
    exposures = (
        exposures.join(
            ancestor_lists.select(
                [
                    pl.col("child_facility_reference").alias("_anc_child"),
                    pl.col("ancestor_facilities").alias("_anc_list"),
                ]
            ),
            left_on="parent_facility_reference",
            right_on="_anc_child",
            how="left",
        )
        .with_columns(
            pl.when(pl.col("_anc_list").is_not_null())
            .then(pl.col("_anc_list"))
            .when(pl.col("parent_facility_reference").is_not_null())
            .then(pl.concat_list("parent_facility_reference"))
            .otherwise(pl.lit(None, dtype=pl.List(pl.String)))
            .alias("ancestor_facilities")
        )
        .drop("_anc_list")
    )

    # Resolve root_facility_reference and facility_hierarchy_depth using root lookup.
    # Left join is safe even when lookup is empty — NULLs fall through to the
    # when/then/otherwise chain, producing identical results to the no-lookup case.
    # Scratch: facility-root-lookup columns join as `_frl_child` (consumed by the
    # join `right_on`), `_frl_root` and `_frl_depth` (consumed by the when/then
    # chain below); all dropped by the trailing `.drop(["_frl_root", "_frl_depth"])`.
    return (
        exposures.join(
            facility_root_lookup.select(
                [
                    pl.col("child_facility_reference").alias("_frl_child"),
                    pl.col("root_facility_reference").alias("_frl_root"),
                    pl.col("facility_hierarchy_depth").alias("_frl_depth"),
                ]
            ),
            left_on="parent_facility_reference",
            right_on="_frl_child",
            how="left",
        )
        .with_columns(
            [
                # Multi-level: root from lookup; single-level: parent itself; no parent: null
                pl.when(pl.col("_frl_root").is_not_null())
                .then(pl.col("_frl_root"))
                .when(pl.col("parent_facility_reference").is_not_null())
                .then(pl.col("parent_facility_reference"))
                .otherwise(pl.lit(None).cast(pl.String))
                .alias("root_facility_reference"),
                # Multi-level: lookup depth + 1; single-level: 1; no parent: 0
                pl.when(pl.col("_frl_depth").is_not_null())
                .then((pl.col("_frl_depth") + 1).cast(pl.Int8))
                .when(pl.col("parent_facility_reference").is_not_null())
                .then(pl.lit(1).cast(pl.Int8))
                .otherwise(pl.lit(0).cast(pl.Int8))
                .alias("facility_hierarchy_depth"),
            ]
        )
        .drop(["_frl_root", "_frl_depth"])
    )
