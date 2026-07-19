"""
Synthetic facility-undrawn exposure rows for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (stages/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``unify`` when
    building the unified exposures frame.

Key responsibilities:
- Calculate undrawn headroom per root/standalone facility (limit minus
  aggregated descendant loan drawn + contingent nominal).
- Expand Multiple Option Facility (MOF) parents into per-sub CCF-descending
  waterfall rows plus an optional residual row.
- Facility Share riskiest-counterparty override via the non-binding
  SA-equivalent risk-weight preview, compiled from the shared
  ``build_entity_rw_expr`` builder (``data/tables/guarantor_rw``).
- Project the canonical facility_undrawn exposure schema, emitting the
  ``original_counterparty_reference`` / ``mof_risk_type_source`` audit
  columns (Site A of the ``_FACILITY_QRRE_COUPLED_COLUMNS`` coupling).

References:
- CRR Art. 166(8)(d) / Art. 166(10): commitment vs issued-item CCF buckets
- CRR Art. 195 / 219: on-balance-sheet netting of drawn balances
- CRR Art. 147(5) / CRE30.55: QRRE classification fields
- CRR Art. 114-128: SA risk weights read by the RW preview (see
  ``data/tables/guarantor_rw.build_entity_rw_expr``)
- PRA PS1/26 Art. 111(1) Table A1 Row 4(b): residential mortgage commitments
- PRA PS1/26 Art. 166E(5): revolving purchased-receivables commitments
- PRA PS1/26 Art. 124(3) / Art. 124K: under-construction (ADC) flag
- PRA PS1/26 Art. 162(2A)(k): revolving M via facility termination date
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine.ccf import sa_ccf_expression
from rwa_calc.engine.sa.guarantor_rw import build_entity_rw_expr
from rwa_calc.engine.stages.hierarchy.graph import (
    filter_mappings_by_child_type,
    resolve_to_root_facility,
)
from rwa_calc.engine.utils import has_required_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CounterpartyLookup
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


def calculate_facility_undrawn(
    facilities: pl.LazyFrame | None,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    facility_root_lookup: pl.LazyFrame | None = None,
    counterparty_lookup: CounterpartyLookup | None = None,
    config: CalculationConfig | None = None,
) -> pl.LazyFrame:
    """
    Calculate undrawn amounts for facilities.

    For each root/standalone facility:
        undrawn = facility.limit - sum(descendant loans' drawn_amount)
                                 - sum(descendant contingents' nominal_amount)

    For multi-level hierarchies, amounts from loans and contingents under
    sub-facilities are aggregated up to the root facility. Sub-facilities
    do not produce their own undrawn exposure records.

    Two facility-product overrides are applied to the resulting undrawn
    rows when ``counterparty_lookup`` and ``config`` are provided:

    - **Multiple Option Facility (MOF)**: any facility with at least one
      ``child_type='facility'`` mapping inherits the descendant ``risk_type``
      producing the highest SA CCF, ensuring the parent's undrawn EAD
      reflects the worst-case off-balance commitment among its components.
    - **Facility Share**: when the descendant loans/contingents reference
      more than one distinct counterparty, the undrawn is allocated to the
      riskiest member by SA-equivalent risk weight.

    Both overrides preserve the original facility values in audit columns
    (``original_counterparty_reference``, ``mof_risk_type_source``).

    Args:
        facilities: Facilities with limit, risk_type, and other CCF fields
        loans: Loans with drawn_amount
        contingents: Contingents with nominal_amount (optional)
        facility_mappings: Mappings between facilities and children
        facility_root_lookup: Root lookup from graph.build_facility_root_lookup
        counterparty_lookup: Used to resolve riskiest counterparty for
            Facility Shares (entity_type + cqs preview lookup)
        config: Calculation configuration (frame switch for SA CCF /
            SA RW preview tables)

    Returns:
        LazyFrame with facility_undrawn exposure records
    """
    # Validate facilities have required columns; bail out with empty frame if not.
    if not has_required_columns(facilities, {"facility_reference", "limit"}):
        return _empty_facility_undrawn_frame()

    # Defensive empty mapping frame so downstream joins are well-typed even
    # when the caller passes a malformed facility_mappings.
    if not has_required_columns(
        facility_mappings, {"parent_facility_reference", "child_reference"}
    ):
        facility_mappings = pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )

    # Root lookup for multi-level hierarchies (used by both loan and contingent
    # aggregations). Left join with empty lookup naturally produces nulls; coalesce
    # falls back to the directly-mapped parent.
    root_lookup = (
        facility_root_lookup
        if facility_root_lookup is not None
        else pl.LazyFrame(
            schema={
                "child_facility_reference": pl.String,
                "root_facility_reference": pl.String,
            }
        )
    )

    loan_drawn_totals = _aggregate_loan_drawn_per_facility(loans, facility_mappings, root_lookup)
    contingent_totals = _aggregate_contingent_per_facility(
        contingents, facility_mappings, root_lookup
    )

    facility_with_drawn = _compute_facility_undrawn_per_root(
        facilities, loan_drawn_totals, contingent_totals, root_lookup
    )

    facility_with_drawn = _apply_mof_parent_marker(facility_with_drawn, root_lookup)

    is_basel_3_1 = bool(getattr(config, "is_basel_3_1", False)) if config is not None else False

    facility_with_drawn = _apply_facility_share_override(
        facility_with_drawn,
        facilities,
        facility_mappings,
        loans,
        contingents,
        counterparty_lookup,
        root_lookup,
        is_basel_3_1,
    )

    # Expand MOF parents into per-sub waterfall rows + optional residual.
    # Non-MOF parents pass through unchanged. After this step
    # facility_with_drawn contains:
    #   - 1 row per non-MOF parent (existing behaviour)
    #   - N waterfall rows + optional 1 residual row per MOF parent
    # Each row carries the right risk_type / counterparty / undrawn_amount
    # for its emit slot, plus an exposure_suffix for a unique exposure_reference.
    facility_with_drawn = _expand_mof_facility_undrawn(
        facility_with_drawn,
        facilities,
        root_lookup,
        loans,
        contingents,
        facility_mappings,
        is_basel_3_1,
    )

    select_exprs = _undrawn_select_expressions()

    # Create exposure records for facilities with undrawn > 0 AND committed=True.
    # Uncommitted (unconditionally cancellable) facilities generate no synthetic
    # undrawn exposure: the bank can refuse to lend, so no commitment EAD/RWA is
    # held against the unused headroom. Loans/contingents already mapped to the
    # facility are unaffected — they remain independent exposure rows. The
    # ``committed`` column is loader-defaulted to True via
    # ``apply_boolean_column_defaults`` (data/column_spec.py), so we can read
    # it directly without a defensive fill_null.
    return facility_with_drawn.filter((pl.col("undrawn_amount") > 0) & pl.col("committed")).select(
        select_exprs
    )


def _empty_facility_undrawn_frame() -> pl.LazyFrame:
    """Empty LazyFrame matching the canonical facility-undrawn output schema.

    Returned by ``calculate_facility_undrawn`` when the input ``facilities``
    frame lacks the required columns to compute undrawn amounts.
    """
    return pl.LazyFrame(
        schema={
            "exposure_reference": pl.String,
            "exposure_type": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "original_counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "funding_currency": pl.String,
            "drawn_amount": pl.Float64,
            "interest": pl.Float64,
            "undrawn_amount": pl.Float64,
            "nominal_amount": pl.Float64,
            "lgd": pl.Float64,
            "beel": pl.Float64,
            "seniority": pl.String,
            "risk_type": pl.String,
            "mof_risk_type_source": pl.String,
            "underlying_risk_type": pl.String,
            "ccf_modelled": pl.Float64,
            "ead_modelled": pl.Float64,
            "is_short_term_trade_lc": pl.Boolean,
            "is_obs_commitment": pl.Boolean,
            "is_uk_residential_mortgage_commitment": pl.Boolean,
            "is_purchased_receivable_commitment": pl.Boolean,
            "is_payroll_loan": pl.Boolean,
            "is_buy_to_let": pl.Boolean,
            "is_under_construction": pl.Boolean,
            "has_one_day_maturity_floor": pl.Boolean,
            "is_sft": pl.Boolean,
            "netting_agreement_reference": pl.String,
            "is_revolving": pl.Boolean,
            "is_qrre_transactor": pl.Boolean,
            "is_secured": pl.Boolean,
            "facility_limit": pl.Float64,
            "source_facility_reference": pl.String,
            "source_exposure_reference": pl.String,
            "facility_termination_date": pl.Date,
            "effective_maturity": pl.Float64,
        }
    )


def _aggregate_loan_drawn_per_facility(
    loans: pl.LazyFrame,
    facility_mappings: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Sum drawn amounts per (root or standalone) facility, netting-aware.

    Positive drawn balances always sum normally. Negative drawn balances
    only contribute when the loan carries a ``netting_agreement_reference``
    (CRR Art. 195 / 219, PS1/26 Art. 195 / 219) — these represent deposits
    booked under an on-balance-sheet netting agreement and reduce facility
    utilisation. Negative drawn amounts without a netting agreement
    reference are clamped to 0 (data-quality guard), preserving the
    historical behaviour.
    """
    loan_mappings = filter_mappings_by_child_type(facility_mappings, "loan")

    loan_with_parent = loans.join(
        loan_mappings,
        left_on="loan_reference",
        right_on="child_reference",
        how="inner",
    )

    loan_with_parent = resolve_to_root_facility(loan_with_parent, root_lookup)

    drawn_expr = (
        pl.when((pl.col("drawn_amount") < 0) & pl.col("netting_agreement_reference").is_null())
        .then(pl.lit(0.0))
        .otherwise(pl.col("drawn_amount"))
    )

    return loan_with_parent.group_by("aggregation_facility").agg(
        [
            drawn_expr.sum().alias("total_drawn"),
        ]
    )


def _aggregate_contingent_per_facility(
    contingents: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Sum positive contingent nominal amounts per (root or standalone) facility.

    Parallel to ``_aggregate_loan_drawn_per_facility``. Negative balances are
    clamped to 0. Returns an empty 2-col frame if no contingents are provided.
    """
    if contingents is None:
        return pl.LazyFrame(
            schema={
                "aggregation_facility": pl.String,
                "total_contingent": pl.Float64,
            }
        )

    contingent_mappings = filter_mappings_by_child_type(facility_mappings, "contingent")

    contingent_with_parent = contingents.join(
        contingent_mappings,
        left_on="contingent_reference",
        right_on="child_reference",
        how="inner",
    )

    contingent_with_parent = resolve_to_root_facility(contingent_with_parent, root_lookup)

    return contingent_with_parent.group_by("aggregation_facility").agg(
        [
            pl.col("nominal_amount").clip(lower_bound=0.0).sum().alias("total_contingent"),
        ]
    )


def _compute_facility_undrawn_per_root(
    facilities: pl.LazyFrame,
    loan_drawn_totals: pl.LazyFrame,
    contingent_totals: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Join drawn/contingent totals onto facilities and compute undrawn headroom.

    Sub-facilities (those that appear as a child in ``root_lookup``) are
    anti-joined out — only root or standalone facilities emit an undrawn
    exposure row.
    """
    sub_facility_refs = root_lookup.select(
        pl.col("child_facility_reference").alias("_sub_ref"),
    )

    facility_with_drawn = (
        facilities.join(
            loan_drawn_totals,
            left_on="facility_reference",
            right_on="aggregation_facility",
            how="left",
        )
        .join(
            contingent_totals,
            left_on="facility_reference",
            right_on="aggregation_facility",
            how="left",
        )
        .with_columns(
            [
                pl.col("total_drawn").fill_null(0.0),
                pl.col("total_contingent").fill_null(0.0),
            ]
        )
        .with_columns(
            [
                (pl.col("total_drawn") + pl.col("total_contingent")).alias("total_utilised"),
                (pl.col("limit") - (pl.col("total_drawn") + pl.col("total_contingent")))
                .clip(lower_bound=0.0)
                .alias("undrawn_amount"),
            ]
        )
    )

    return facility_with_drawn.join(
        sub_facility_refs,
        left_on="facility_reference",
        right_on="_sub_ref",
        how="anti",
    )


def _apply_mof_parent_marker(
    facility_with_drawn: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Tag each row with ``_is_mof_parent`` (True for facilities that have
    at least one facility-typed descendant).

    MOF parents are expanded into per-sub waterfall rows by
    ``_expand_mof_facility_undrawn``; non-MOF parents flow through the
    single-row path with the optional Facility Share counterparty override.

    Scratch: ``_is_mof_parent`` is added here, read by
    ``_apply_facility_share_override`` (suppress override on MOF) and by
    ``_expand_mof_facility_undrawn`` (route into waterfall vs. pass-through);
    kept on the frame through to the final select where it is dropped
    implicitly by not appearing in ``_undrawn_select_expressions``.
    """
    mof_parent_marker = (
        root_lookup.select(pl.col("root_facility_reference").alias("facility_reference"))
        .unique()
        .with_columns(pl.lit(True).alias("_is_mof_parent"))
    )

    return facility_with_drawn.join(
        mof_parent_marker,
        on="facility_reference",
        how="left",
    ).with_columns(pl.col("_is_mof_parent").fill_null(False))


def _apply_facility_share_override(
    facility_with_drawn: pl.LazyFrame,
    facilities: pl.LazyFrame,
    facility_mappings: pl.LazyFrame,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    counterparty_lookup: CounterpartyLookup | None,
    root_lookup: pl.LazyFrame,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """Attach ``share_counterparty_reference`` to non-MOF facilities.

    MOF parents do not need the share override — each waterfall row already
    carries its sub-facility's own counterparty. Non-MOF parents benefit
    from the riskiest-CP allocation when more than one counterparty appears
    among the facility's descendants.

    When ``counterparty_lookup`` is None, the column is added as NULL
    on every row so the downstream select keeps a stable schema.
    """
    if counterparty_lookup is None:
        return facility_with_drawn.with_columns(
            pl.lit(None).cast(pl.String).alias("share_counterparty_reference")
        )

    share_lookup = _derive_facility_share_counterparty(
        facilities,
        facility_mappings,
        loans,
        contingents,
        counterparty_lookup,
        root_lookup,
        is_basel_3_1,
    )
    return facility_with_drawn.join(
        share_lookup,
        on="facility_reference",
        how="left",
    ).with_columns(
        # Suppress share override on MOF parents — sub rows handle it.
        pl.when(pl.col("_is_mof_parent"))
        .then(pl.lit(None).cast(pl.String))
        .otherwise(pl.col("share_counterparty_reference"))
        .alias("share_counterparty_reference")
    )


def _undrawn_select_expressions() -> list[pl.Expr]:
    """List of select expressions that shape ``facility_with_drawn`` into the
    canonical facility_undrawn exposure schema.

    The facilities frame is sealed at the loader edge (schema-complete per
    ``FACILITY_SCHEMA``; Boolean columns with a schema default are non-null),
    so every column can be read directly.

    Note: ``parent_facility_reference`` is set to the source facility to
    enable facility-level collateral allocation to undrawn amounts.
    ``_exposure_suffix`` is "" for non-MOF rows, "_{sub_ref}" for MOF
    waterfall rows, and "_RESIDUAL" for the optional MOF residual row —
    set by ``_expand_mof_facility_undrawn``.

    Site A of the two-site QRRE coupling pinned by
    ``_FACILITY_QRRE_COUPLED_COLUMNS`` (stages/hierarchy/__init__.py): the
    QRRE-relevant facility columns are projected directly from the facility
    frame here; Site B (``enrich.propagate_facility_qrre_columns``)
    join+coalesces the same column set onto loan / contingent rows.
    """
    return [
        (pl.col("facility_reference") + pl.lit("_UNDRAWN") + pl.col("_exposure_suffix")).alias(
            "exposure_reference"
        ),
        # Pre-concatenation base reference for reconciliation linking: the
        # facility the undrawn headroom belongs to (strips the
        # _UNDRAWN[_<sub>|_RESIDUAL] suffix). Legacy parallel-run extracts key
        # undrawn commitments on the facility reference, so every MOF waterfall
        # and residual sub-row collapses to a single facility base line.
        pl.col("facility_reference").alias("source_exposure_reference"),
        pl.lit("facility_undrawn").alias("exposure_type"),
        pl.col("product_type"),
        pl.col("book_code").cast(pl.String, strict=False),
        pl.coalesce(
            pl.col("share_counterparty_reference"),
            pl.col("counterparty_reference"),
        ).alias("counterparty_reference"),
        pl.col("counterparty_reference").alias("original_counterparty_reference"),
        pl.col("value_date"),
        pl.col("maturity_date"),
        pl.col("currency"),
        # CRR Art. 114(4)/(7) via Art. 235(3): funding-currency pass-through for
        # undrawn facility exposures (see unify._coerce_loans_to_unified).
        pl.col("funding_currency"),
        pl.lit(0.0).alias("drawn_amount"),
        pl.lit(0.0).alias("interest"),
        pl.col("undrawn_amount"),
        pl.col("undrawn_amount").alias("nominal_amount"),
        pl.col("lgd").cast(pl.Float64, strict=False),
        pl.col("lgd_unsecured").cast(pl.Float64, strict=False),
        pl.col("has_sufficient_collateral_data").cast(pl.Boolean, strict=False),
        pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0),
        pl.col("seniority"),
        pl.coalesce(
            pl.col("mof_risk_type"),
            pl.col("risk_type"),
        ).alias("risk_type"),
        pl.col("mof_risk_type_source"),
        pl.col("underlying_risk_type"),
        pl.col("ccf_modelled").cast(pl.Float64, strict=False),
        pl.col("ead_modelled").cast(pl.Float64, strict=False),
        pl.col("is_short_term_trade_lc"),
        # CRR Art. 166(8)(d): facility undrawn is a credit line by construction,
        # so default True. An explicit False override flips the row to the
        # Art. 166(10) issued-item bucket (50% MR / 20% MLR). The column is
        # loader-defaulted (schema default True), so we can read it directly.
        pl.col("is_obs_commitment"),
        # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): residential-property
        # commitment flag carried through to the CCF stage so the 50%
        # override fires under Basel 3.1.
        pl.col("is_uk_residential_mortgage_commitment"),
        # PRA PS1/26 Art. 166E(5): revolving purchased-receivables undrawn
        # purchase commitment flag carried through to the CCF stage so the
        # OC (40%) / LR (10%) routing fires under Basel 3.1.
        pl.col("is_purchased_receivable_commitment"),
        pl.col("is_payroll_loan"),
        pl.col("is_buy_to_let"),
        # PRA PS1/26 Art. 124(3) / Art. 124K: under-construction flag drives
        # ADC classification derivation in the classifier. Facility-level
        # value flows through to facility_undrawn rows so commitments to
        # development-finance facilities also surface the flag.
        pl.col("is_under_construction"),
        pl.col("has_one_day_maturity_floor"),
        pl.col("is_sft"),
        pl.col("effective_maturity"),
        pl.lit(None).cast(pl.String).alias("netting_agreement_reference"),
        # QRRE classification fields (CRR Art. 147(5), CRE30.55).
        # Both columns are loader-defaulted (schema default False), so we
        # can read them directly.
        pl.col("is_revolving"),
        pl.col("is_qrre_transactor"),
        # PRA PS1/26 Art. 147(5A)(b): carry the facility "secured" attestation onto
        # the undrawn commitment row so a secured revolving retail facility's
        # undrawn portion is demoted from QRRE alongside its drawn exposures.
        # Loader-defaulted (schema default False), so we can read it directly.
        pl.col("is_secured"),
        pl.col("limit").alias("facility_limit"),
        # Art. 162(2A)(k): max contractual termination date for revolving M under B31
        pl.col("facility_termination_date"),
        # Propagate facility reference for collateral allocation
        # This allows facility-level collateral to be linked to undrawn exposures
        pl.col("facility_reference").alias("source_facility_reference"),
    ]


def _expand_mof_facility_undrawn(
    facility_with_drawn: pl.LazyFrame,
    facilities: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """Expand Multiple Option Facility (MOF) parent rows into per-sub waterfall rows.

    For non-MOF parents (no ``child_type='facility'`` descendants), the input
    row passes through unchanged with empty ``_exposure_suffix`` and null
    ``mof_risk_type`` — downstream :func:`select_exprs` therefore uses the
    parent's own ``risk_type`` and ``counterparty_reference``.

    For MOF parents, the parent row is replaced by:
        - One waterfall row per committed descendant sub-facility with
          positive headroom, sorted by descending SA CCF (tie-break:
          alphabetical risk_type, then descendant reference).
        - At most one residual row when ``parent_headroom`` exceeds the
          sum of sub allocations — emitted at the parent's own ``risk_type``
          and ``counterparty_reference``.

    Allocation rule per parent:
        sub_headroom_i = max(0, sub_limit_i - sub_drawn_i)         # per-sub netting
        cum_i          = sum(sub_headroom_j for j <= i)
        allocation_i   = min(sub_headroom_i,
                             max(0, parent_headroom - cum_{i-1}))

    Uncommitted (``committed=False``) sub-facilities are skipped entirely —
    the bank can refuse to lend on them, so they carry no commitment EAD and
    do not consume parent headroom.

    Args:
        facility_with_drawn: One row per parent with ``_is_mof_parent`` flag,
            aggregate ``undrawn_amount`` (= parent_headroom), parent fields,
            and ``share_counterparty_reference`` (suppressed for MOF parents).
        facilities: Facilities frame; supplies sub-facility risk_type,
            counterparty_reference, limit, and committed flag.
        root_lookup: Output of :func:`graph.build_facility_root_lookup`.
        loans: Loans frame; per-sub drawn aggregates net each sub's headroom.
        contingents: Contingents frame (optional); same role as loans.
        facility_mappings: Mappings between facilities and children.
        is_basel_3_1: Frame switch passed to :func:`sa_ccf_expression`.

    Returns:
        LazyFrame with the same column shape as the input, plus three
        expansion columns (``_exposure_suffix``, ``mof_risk_type``,
        ``mof_risk_type_source``) populated per emitted row.
    """
    # Add expansion columns with defaults — non-MOF rows keep these defaults.
    expanded = facility_with_drawn.with_columns(
        [
            pl.lit("").alias("_exposure_suffix"),
            pl.lit(None).cast(pl.String).alias("mof_risk_type"),
            pl.lit(None).cast(pl.String).alias("mof_risk_type_source"),
        ]
    )

    non_mof_rows = expanded.filter(~pl.col("_is_mof_parent"))
    mof_parents = expanded.filter(pl.col("_is_mof_parent"))

    # Per-sub netting: aggregate loans/contingents at the directly-mapped
    # facility level (NOT rolled up to root). This is what lets the waterfall
    # reflect actual sub-level utilisation rather than parent-level totals.

    def _per_sub_drawn(
        frame: pl.LazyFrame | None,
        ref_col: str,
        amount_col: str,
        child_type: str,
        out_col: str,
    ) -> pl.LazyFrame:
        if frame is None:
            return pl.LazyFrame(schema={"_sub_ref": pl.String, out_col: pl.Float64})
        child_mappings = filter_mappings_by_child_type(facility_mappings, child_type)
        # Mirror the netting-aware aggregation used at root level: a negative
        # drawn loan only offsets sub-facility utilisation when the loan is
        # carrying a netting_agreement_reference (CRR Art. 195/219). For
        # contingents (no netting reference) the historical clip-at-0 applies.
        select_cols = [pl.col(ref_col), pl.col(amount_col)]
        has_netting_flag = child_type == "loan" and amount_col == "drawn_amount"
        if has_netting_flag:
            select_cols.append(pl.col("netting_agreement_reference"))
            amount_expr = (
                pl.when((pl.col(amount_col) < 0) & pl.col("netting_agreement_reference").is_null())
                .then(pl.lit(0.0))
                .otherwise(pl.col(amount_col))
            )
        else:
            amount_expr = pl.col(amount_col).clip(lower_bound=0.0)
        return (
            frame.select(select_cols)
            .join(
                child_mappings.select(
                    [pl.col("child_reference"), pl.col("parent_facility_reference")]
                ),
                left_on=ref_col,
                right_on="child_reference",
                how="inner",
            )
            .group_by("parent_facility_reference")
            .agg(amount_expr.sum().alias(out_col))
            .rename({"parent_facility_reference": "_sub_ref"})
        )

    loan_per_sub = _per_sub_drawn(
        loans, "loan_reference", "drawn_amount", "loan", "sub_drawn_loans"
    )
    cont_per_sub = _per_sub_drawn(
        contingents,
        "contingent_reference",
        "nominal_amount",
        "contingent",
        "sub_drawn_contingents",
    )

    # Pull sub-facility attributes from the facilities frame — risk_type,
    # counterparty, limit, and the committed flag (defaulting to True).
    # Scratch: `_sub_*` columns drive the per-sub waterfall — `_sub_risk_type`
    # / `_sub_counterparty` are written into the sub-row's `mof_risk_type` /
    # `share_counterparty_reference`; `_sub_limit` feeds `sub_headroom`;
    # `_sub_committed` filters out unconditionally cancellable sub-facilities;
    # `_sub_ref` is the join key and is also baked into `_exposure_suffix`
    # so each waterfall row gets a unique `<facility>_UNDRAWN_<sub>` reference.
    # All scratch columns are dropped via `helper_cols` before concat.
    # `committed` is loader-defaulted (schema default True), so we can
    # read it directly here.
    sub_facilities = facilities.select(
        [
            pl.col("facility_reference").alias("_sub_ref"),
            pl.col("risk_type").alias("_sub_risk_type"),
            pl.col("counterparty_reference").alias("_sub_counterparty"),
            pl.col("limit").alias("_sub_limit"),
            pl.col("committed").alias("_sub_committed"),
        ]
    )

    # Build (parent, sub) frame — only descendants that exist as actual
    # facilities and are committed participate in the waterfall.
    descendants = (
        root_lookup.select(
            [
                pl.col("root_facility_reference").alias("facility_reference"),
                pl.col("child_facility_reference").alias("_sub_ref"),
            ]
        )
        .join(sub_facilities, on="_sub_ref", how="inner")
        .filter(pl.col("_sub_committed"))
        .filter(pl.col("_sub_risk_type").is_not_null())
        .join(loan_per_sub, on="_sub_ref", how="left")
        .join(cont_per_sub, on="_sub_ref", how="left")
        .with_columns(
            sub_drawn=(
                pl.col("sub_drawn_loans").fill_null(0.0)
                + pl.col("sub_drawn_contingents").fill_null(0.0)
            ),
            sub_sa_ccf=sa_ccf_expression(risk_type_col="_sub_risk_type", is_basel_3_1=is_basel_3_1),
        )
        .with_columns(
            sub_headroom=(pl.col("_sub_limit") - pl.col("sub_drawn")).clip(lower_bound=0.0)
        )
    )

    # Join parent_headroom (= parent's undrawn_amount), sort by descending
    # SA CCF then risk_type then sub reference, and apply the waterfall.
    parent_headroom = mof_parents.select(
        [
            pl.col("facility_reference"),
            pl.col("undrawn_amount").alias("_parent_headroom"),
        ]
    )

    waterfall = (
        descendants.join(parent_headroom, on="facility_reference", how="inner")
        .sort(
            ["facility_reference", "sub_sa_ccf", "_sub_risk_type", "_sub_ref"],
            descending=[False, True, False, False],
        )
        .with_columns(
            cum_sub_headroom=pl.col("sub_headroom").cum_sum().over("facility_reference"),
        )
        .with_columns(
            allocation=pl.min_horizontal(
                pl.col("sub_headroom"),
                (
                    pl.col("_parent_headroom")
                    - (pl.col("cum_sub_headroom") - pl.col("sub_headroom"))
                ).clip(lower_bound=0.0),
            ).clip(lower_bound=0.0)
        )
        .filter(pl.col("allocation") > 0.0)
    )

    # Build sub waterfall rows: replicate parent's row per sub, then override
    # the per-row attributes (allocation, risk_type, counterparty, suffix).
    # The helper columns are dropped at the end so the schema matches non-MOF.
    helper_cols = [
        "_sub_ref",
        "_sub_risk_type",
        "_sub_counterparty",
        "_sub_limit",
        "_sub_committed",
        "sub_drawn_loans",
        "sub_drawn_contingents",
        "sub_drawn",
        "sub_sa_ccf",
        "sub_headroom",
        "cum_sub_headroom",
        "allocation",
        "_parent_headroom",
    ]
    sub_rows = (
        mof_parents.join(waterfall, on="facility_reference", how="inner")
        .with_columns(
            [
                pl.col("allocation").alias("undrawn_amount"),
                pl.col("_sub_risk_type").alias("mof_risk_type"),
                pl.col("_sub_ref").alias("mof_risk_type_source"),
                pl.col("_sub_counterparty").alias("share_counterparty_reference"),
                (pl.lit("_") + pl.col("_sub_ref")).alias("_exposure_suffix"),
            ]
        )
        .drop(helper_cols)
    )

    # Residual: parent_headroom - sum(allocation). Emitted only when positive,
    # at parent's own risk_type / counterparty (mof_risk_type stays null so
    # select_exprs falls back through pl.coalesce to the parent's risk_type).
    parent_alloc_total = waterfall.group_by("facility_reference").agg(
        pl.col("allocation").sum().alias("_total_alloc")
    )
    residual_rows = (
        mof_parents.join(parent_alloc_total, on="facility_reference", how="left")
        .with_columns(
            _residual=(pl.col("undrawn_amount") - pl.col("_total_alloc").fill_null(0.0)).clip(
                lower_bound=0.0
            )
        )
        .filter(pl.col("_residual") > 0.0)
        .with_columns(
            undrawn_amount=pl.col("_residual"),
            _exposure_suffix=pl.lit("_RESIDUAL"),
        )
        .drop(["_total_alloc", "_residual"])
    )

    return pl.concat([non_mof_rows, sub_rows, residual_rows], how="diagonal_relaxed")


def _derive_facility_share_counterparty(
    facilities: pl.LazyFrame,
    facility_mappings: pl.LazyFrame,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    counterparty_lookup: CounterpartyLookup,
    root_lookup: pl.LazyFrame,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """Derive the riskiest counterparty for facilities with multi-CP shares.

    A Facility Share is a single facility linked to multiple counterparties
    — identified here by the union of distinct ``counterparty_reference``
    values on descendant loans, contingents, **and sub-facilities**. When
    that set has more than one member, the facility's undrawn must be
    allocated to the riskiest member (highest SA-equivalent risk weight),
    because any of the linked counterparties could draw against the limit
    and the conservative undrawn EAD must sit with the worst credit.

    Sub-facility counterparties are included so that a MOF parent whose
    sub-facilities span multiple obligors triggers riskiest-CP allocation
    even when nothing has been drawn yet (the all-undrawn case).

    The risk-weight preview uses the shared
    :func:`rwa_calc.engine.sa.guarantor_rw.build_entity_rw_expr` builder
    and is non-binding: the chosen counterparty still flows through the
    full classifier and SA/IRB pipeline downstream.

    Args:
        facilities: Facilities frame, used for the root-facility schema only.
        facility_mappings: Mappings between facilities and children.
        loans: Loans frame; descendant counterparties come from here.
        contingents: Contingents frame (optional); descendants also come from here.
        counterparty_lookup: Used to look up ``entity_type``, ``cqs`` and
            ``country_code`` (when present) per candidate counterparty.
        root_lookup: Output of :func:`graph.build_facility_root_lookup`.
        is_basel_3_1: Framework switch passed to
            :func:`rwa_calc.engine.sa.guarantor_rw.build_entity_rw_expr`.

    Returns:
        LazyFrame with columns:
            - facility_reference: root facility with a multi-CP share.
            - share_counterparty_reference: the chosen riskiest member.
    """
    empty = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "share_counterparty_reference": pl.String,
        }
    )

    if not has_required_columns(
        facility_mappings, {"parent_facility_reference", "child_reference"}
    ):
        return empty

    # Gather descendant (root_facility_reference, counterparty_reference) pairs
    # from loans, contingents, and sub-facilities that map to a facility.
    candidate_frames: list[pl.LazyFrame] = []

    # Sub-facility counterparties — every descendant facility's own owner
    # is a potential drawer against the parent's limit. Joining via the
    # root_lookup gives every sub-facility its MOF root in a single hop.
    sub_fac_with_root = (
        facilities.select([pl.col("facility_reference"), pl.col("counterparty_reference")])
        .join(
            root_lookup.select(
                [
                    pl.col("child_facility_reference"),
                    pl.col("root_facility_reference"),
                ]
            ),
            left_on="facility_reference",
            right_on="child_facility_reference",
            how="inner",
        )
        .select(
            [
                pl.col("root_facility_reference").alias("facility_reference"),
                pl.col("counterparty_reference"),
            ]
        )
    )
    candidate_frames.append(sub_fac_with_root)

    loan_mappings = filter_mappings_by_child_type(facility_mappings, "loan")

    loan_with_parent = loans.select(
        [pl.col("loan_reference"), pl.col("counterparty_reference")]
    ).join(
        loan_mappings.select([pl.col("child_reference"), pl.col("parent_facility_reference")]),
        left_on="loan_reference",
        right_on="child_reference",
        how="inner",
    )
    loan_with_parent = resolve_to_root_facility(loan_with_parent, root_lookup)
    candidate_frames.append(
        loan_with_parent.select(
            [
                pl.col("aggregation_facility").alias("facility_reference"),
                pl.col("counterparty_reference"),
            ]
        )
    )

    if contingents is not None:
        cont_mappings = filter_mappings_by_child_type(facility_mappings, "contingent")

        cont_with_parent = contingents.select(
            [pl.col("contingent_reference"), pl.col("counterparty_reference")]
        ).join(
            cont_mappings.select([pl.col("child_reference"), pl.col("parent_facility_reference")]),
            left_on="contingent_reference",
            right_on="child_reference",
            how="inner",
        )
        cont_with_parent = resolve_to_root_facility(cont_with_parent, root_lookup)
        candidate_frames.append(
            cont_with_parent.select(
                [
                    pl.col("aggregation_facility").alias("facility_reference"),
                    pl.col("counterparty_reference"),
                ]
            )
        )

    candidates = (
        pl.concat(candidate_frames, how="diagonal_relaxed")
        .filter(pl.col("counterparty_reference").is_not_null())
        .unique(subset=["facility_reference", "counterparty_reference"])
    )

    # Only facilities with > 1 distinct member are Facility Shares.
    member_counts = candidates.group_by("facility_reference").agg(pl.len().alias("_member_count"))
    candidates = candidates.join(member_counts, on="facility_reference", how="inner").filter(
        pl.col("_member_count") > 1
    )

    # Pull entity_type + cqs (+ country_code when present) from the resolved
    # counterparty lookup.
    cp_cols = set(counterparty_lookup.counterparties.collect_schema().names())
    cp_select = [pl.col("counterparty_reference")]
    if "entity_type" in cp_cols:
        cp_select.append(pl.col("entity_type").alias("_share_entity_type"))
    else:
        return empty
    if "cqs" in cp_cols:
        cp_select.append(pl.col("cqs").alias("_share_cqs"))
    else:
        cp_select.append(pl.lit(None).cast(pl.Int8).alias("_share_cqs"))
    # country_code drives the unrated PSE / RGLA GB-vs-other approximation in
    # the preview. No presence probe: CounterpartyLookup frames are
    # brand-validated against the cp_lookup_counterparties edge, which
    # declares (and injects) country_code — the column is always present.
    cp_select.append(pl.col("country_code").alias("_share_country_code"))

    candidates = candidates.join(
        counterparty_lookup.counterparties.select(cp_select),
        on="counterparty_reference",
        how="left",
    ).with_columns(
        build_entity_rw_expr(
            entity_type_col="_share_entity_type",
            cqs_col="_share_cqs",
            is_basel_3_1=is_basel_3_1,
            country_code_col="_share_country_code",
        ).alias("_preview_rw")
    )

    # Per facility, pick the candidate with max preview RW. Tie-break on
    # higher CQS (worse credit) then alphabetical counterparty_reference.
    return (
        candidates.sort(
            [
                "facility_reference",
                "_preview_rw",
                "_share_cqs",
                "counterparty_reference",
            ],
            descending=[False, True, True, False],
            nulls_last=True,
        )
        .group_by("facility_reference")
        .agg(pl.col("counterparty_reference").first().alias("share_counterparty_reference"))
    )
