"""
Real estate loan-splitter for SA exposures collateralised by property.

Pipeline position:
    CRMProcessor -> RealEstateSplitter -> SA / IRB / Slotting Calculators

Key responsibilities:
- Physically partitions a flagged exposure into:
    - a secured row reclassified to RESIDENTIAL_MORTGAGE / COMMERCIAL_MORTGAGE,
    - a residual row that retains the original counterparty exposure class so
      the standard corporate / retail risk weight applies on the remainder.
- Allocates EAD between the two rows using the regime-specific
  ``SplitParameters.secured_ltv_cap`` (less prior charges under B3.1 per
  Art. 124F(2)).
- Emits a parent-id audit trail so downstream aggregations can reconcile
  the sum of secured + residual EADs back to the parent exposure.

Decision logic per regime (driven by ``data/tables/re_split_parameters.py``
constants — engine code declares no regulatory scalars):

| Regime / class                  | Secured LTV cap | Secured RW |
|---------------------------------|-----------------|------------|
| CRR Art. 125 (RRE)              | 80% LTV         | 35%        |
| CRR Art. 126 (CRE, rental met)  | 50% LTV         | 50%        |
| B3.1 Art. 124F (RRE)            | 55% × prop val  | 20%        |
| B3.1 Art. 124H(1)-(2) (CRE)     | 55% × prop val  | 60%        |
| B3.1 Art. 124H(3) (CRE other)   | whole-loan      | n/a        |

The actual risk weight is *not* set by the splitter — the secured row is
labelled ``RESIDENTIAL_MORTGAGE`` / ``COMMERCIAL_MORTGAGE`` and the existing
``b31_residential_rw_expr`` / ``b31_commercial_rw_expr`` /
CRR ``_apply_residential_mortgage_rw`` paths in the SA calculator compute
the correct RW from ``ltv``, ``has_income_cover``, ``prior_charge_ltv`` and
counterparty-type columns. The residual row keeps its original
``exposure_class`` so the SA calculator's normal corporate / retail path
applies.

References:
- CRR Art. 125: Residential mortgage 35% on portion up to 80% LTV.
- CRR Art. 126(2)(d): Commercial real estate 50% — rental income must
  cover >= 1.5x interest costs.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting (cap 55% less prior charges).
- PRA PS1/26 Art. 124H(1)-(2): B3.1 CRE loan-splitting for natural person / SME.
- PRA PS1/26 Art. 124H(3): B3.1 CRE max(60%, min(cp_rw, Art. 124I)) for other.
- PRA PS1/26 Art. 124L: Counterparty type residual RW table.

Classes:
    RealEstateSplitter: Implements RealEstateSplitterProtocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.errors import (
    ERROR_RE_CRR_RENTAL_COVERAGE_FAILED,
    ERROR_RE_NON_ELIGIBLE_COLLATERAL,
    ERROR_RE_ZERO_EFFECTIVE_CAP,
    CalculationError,
    re_split_warning,
)
from rwa_calc.data.tables.re_split_parameters import (
    SplitParameters,
    re_split_parameters,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


class RealEstateSplitter:
    """Materialise the RE loan-split into two physical rows per exposure.

    Implements ``RealEstateSplitterProtocol`` from
    ``contracts/protocols.py``.
    """

    def split(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """Apply RE loan-splitting to candidate rows.

        See module docstring for the regime-specific decision matrix.
        """
        params = re_split_parameters(is_basel_3_1=config.is_basel_3_1)
        rrep = params["residential"]
        crep = params["commercial"]

        unified, audit, errors = _split_unified_frame(
            data.exposures,
            rrep=rrep,
            crep=crep,
            is_basel_3_1=config.is_basel_3_1,
        )

        # Approach-split frames mirror the unified frame and are not used in
        # the single-pass pipeline path; we only rebuild them when callers
        # have populated them explicitly. The pipeline orchestrator splits
        # by approach later, after the calculator runs on the unified frame.
        sa_exposures = data.sa_exposures
        if sa_exposures is not None:
            sa_split, _, _ = _split_unified_frame(
                sa_exposures,
                rrep=rrep,
                crep=crep,
                is_basel_3_1=config.is_basel_3_1,
            )
        else:
            sa_split = sa_exposures

        return CRMAdjustedBundle(
            exposures=unified,
            sa_exposures=sa_split if sa_exposures is not None else data.sa_exposures,
            irb_exposures=data.irb_exposures,
            slotting_exposures=data.slotting_exposures,
            equity_exposures=data.equity_exposures,
            ciu_holdings=data.ciu_holdings,
            crm_audit=data.crm_audit,
            collateral_allocation=data.collateral_allocation,
            re_split_audit=audit,
            crm_errors=list(data.crm_errors) + errors,
        )


def _split_unified_frame(
    exposures: pl.LazyFrame,
    *,
    rrep: SplitParameters,
    crep: SplitParameters,
    is_basel_3_1: bool,
) -> tuple[pl.LazyFrame, pl.LazyFrame | None, list[CalculationError]]:
    """Partition the unified frame into untouched + split-emitted rows.

    Returns:
        Tuple of (new_unified_lazyframe, audit_lazyframe_or_none,
        accumulated_calculation_errors).
    """
    schema_names = set(exposures.collect_schema().names())

    # When the classifier did not flag any candidates (e.g. older test
    # fixtures, or no property collateral), short-circuit: keep the frame
    # intact and add the post-splitter columns as nulls so downstream
    # ensure_columns() calls remain a no-op.
    required = {
        "re_split_mode",
        "re_split_target_class",
        "re_split_property_value",
        "ead_final",
    }
    missing = required - schema_names
    if missing:
        return _annotate_unsplit(exposures), None, []

    ead_col = "ead_final"
    secured_rrep_rw_cap = float(rrep.secured_ltv_cap)
    secured_crep_rw_cap = float(crep.secured_ltv_cap)
    rrep_uses_prior = rrep.uses_prior_charge_reduction
    crep_uses_prior = crep.uses_prior_charge_reduction

    prior_charge = (
        pl.col("prior_charge_ltv").fill_null(0.0)
        if "prior_charge_ltv" in schema_names
        else pl.lit(0.0)
    )

    is_residential_target = pl.col("re_split_target_class") == rrep.target_class
    is_commercial_target = pl.col("re_split_target_class") == crep.target_class

    # Effective cap per regime: B3.1 reduces cap by prior charges (Art. 124F(2)).
    # CRR has no analogous reduction.
    rrep_cap_expr = (
        pl.max_horizontal(pl.lit(0.0), pl.lit(secured_rrep_rw_cap) - prior_charge)
        if rrep_uses_prior
        else pl.lit(secured_rrep_rw_cap)
    )
    crep_cap_expr = (
        pl.max_horizontal(pl.lit(0.0), pl.lit(secured_crep_rw_cap) - prior_charge)
        if crep_uses_prior
        else pl.lit(secured_crep_rw_cap)
    )

    effective_cap_expr = (
        pl.when(is_residential_target)
        .then(rrep_cap_expr)
        .when(is_commercial_target)
        .then(crep_cap_expr)
        .otherwise(pl.lit(0.0))
    )

    property_value_eligible = pl.col("re_split_property_value").fill_null(0.0)

    # Annotate every row with split-execution metadata. Downstream filters
    # split the frame by re_split_mode.
    annotated = (
        exposures.with_columns(
            [
                effective_cap_expr.alias("_re_effective_cap"),
                property_value_eligible.alias("_re_property_value_eligible"),
            ]
        )
        .with_columns(
            [
                (pl.col("_re_effective_cap") * pl.col("_re_property_value_eligible")).alias(
                    "_re_secured_cap_eur"
                ),
            ]
        )
        .with_columns(
            [
                pl.min_horizontal(
                    pl.col(ead_col).fill_null(0.0), pl.col("_re_secured_cap_eur")
                ).alias("_re_secured_ead"),
            ]
        )
        .with_columns(
            [
                (pl.col(ead_col).fill_null(0.0) - pl.col("_re_secured_ead")).alias(
                    "_re_residual_ead"
                ),
            ]
        )
    )

    # Split mode = "split" with non-zero secured cap → emit two rows.
    # Split mode = "split" with zero secured cap → keep original row + RE002.
    # Split mode = "whole" → reclassify single row to COMMERCIAL_MORTGAGE.
    # Split mode is null → pass-through.
    # ``fill_null("none")`` so the boolean comparisons return False rather
    # than null on unflagged rows (Polars filter drops null rows by default).
    mode = pl.col("re_split_mode").fill_null("none")
    is_split_mode = mode == "split"
    is_whole_mode = mode == "whole"
    has_secured_cap = pl.col("_re_secured_ead").fill_null(0.0) > 0.0
    is_actual_split = is_split_mode & has_secured_cap

    # Pass-through: rows that the splitter does not touch.
    pass_through = annotated.filter(~(is_actual_split | is_whole_mode))

    pass_through = _strip_temp_columns(pass_through).with_columns(
        [
            pl.lit(None).cast(pl.String).alias("split_parent_id"),
            pl.lit(None).cast(pl.String).alias("re_split_role"),
        ]
    )

    # Whole-loan reclassification (B3.1 CRE Art. 124H(3) corporate path).
    whole_rows = annotated.filter(is_whole_mode)
    whole_rows = whole_rows.with_columns(
        [
            pl.col("re_split_target_class").alias("exposure_class"),
            _new_ltv_expr(ead_col).alias("ltv"),
            pl.col("re_split_property_type").alias("property_type"),
            pl.col("exposure_reference").alias("split_parent_id"),
            pl.lit("whole").alias("re_split_role"),
        ]
    ).pipe(_strip_temp_columns)

    # True split: secured + residual rows.
    split_base = annotated.filter(is_actual_split)
    secured_rows = split_base.with_columns(
        [
            pl.col("re_split_target_class").alias("exposure_class"),
            pl.col("_re_secured_ead").alias(ead_col),
            pl.col("_re_property_value_eligible").alias("property_collateral_value"),
            _new_ltv_for_secured_expr().alias("ltv"),
            pl.col("re_split_property_type").alias("property_type"),
            # B3.1 splits go through the general (non-income) Art. 124F/H
            # path; CRR CRE splits set has_income_cover=True so the
            # Art. 126 condition `(ltv <= 0.50) & has_income_cover`
            # produces the 50% preferential RW.
            _has_income_cover_for_secured(is_basel_3_1).alias("has_income_cover"),
            _scale_provision_expr(numerator="_re_secured_ead").alias("provision_allocated"),
            pl.col("exposure_reference").alias("split_parent_id"),
            (pl.col("exposure_reference") + pl.lit("_sec")).alias("exposure_reference"),
            pl.lit("secured").alias("re_split_role"),
        ]
    ).pipe(_strip_temp_columns)

    residual_rows = (
        split_base.with_columns(
            [
                # exposure_class unchanged → corporate / retail RW path.
                pl.col("_re_residual_ead").alias(ead_col),
                pl.lit(None).cast(pl.Float64).alias("property_collateral_value"),
                pl.lit(None).cast(pl.Float64).alias("residential_collateral_value"),
                pl.lit(None).cast(pl.Float64).alias("ltv"),
                pl.lit(None).cast(pl.String).alias("property_type"),
                pl.lit(False).alias("has_income_cover"),
                _scale_provision_expr(numerator="_re_residual_ead").alias("provision_allocated"),
                pl.col("exposure_reference").alias("split_parent_id"),
                (pl.col("exposure_reference") + pl.lit("_res")).alias("exposure_reference"),
                pl.lit("residual").alias("re_split_role"),
            ]
        ).pipe(_strip_temp_columns)
        # Residual rows with zero EAD are still kept so reconciliation works
        # (sum_child_ead == parent_ead). The downstream SA calculator
        # produces RWA = 0 × RW = 0 for them.
    )

    new_unified = pl.concat(
        [pass_through, whole_rows, secured_rows, residual_rows],
        how="diagonal_relaxed",
    )

    # Audit trail: one row per parent exposure that was split (or treated
    # as whole). Useful for COREP reconciliation and debugging.
    affected_rows = annotated.filter(is_actual_split | is_whole_mode)
    audit = affected_rows.select(
        [
            pl.col("exposure_reference").alias("split_parent_id"),
            pl.col(ead_col).alias("parent_ead"),
            pl.col("_re_secured_ead").alias("secured_ead"),
            pl.col("_re_residual_ead").alias("residual_ead"),
            pl.col("_re_property_value_eligible").alias("property_value_eligible"),
            pl.col("_re_effective_cap").alias("effective_cap"),
            pl.col("re_split_target_class").alias("target_class"),
            pl.col("re_split_property_type").alias("property_type"),
            pl.col("re_split_mode").alias("re_split_mode"),
            pl.lit("basel_3_1" if is_basel_3_1 else "crr").alias("regime"),
        ]
    )

    errors = _accumulate_split_errors(annotated, is_basel_3_1=is_basel_3_1)
    return new_unified, audit, errors


def _annotate_unsplit(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Add post-splitter columns (null) when no candidates are present."""
    return exposures.with_columns(
        [
            pl.lit(None).cast(pl.String).alias("split_parent_id"),
            pl.lit(None).cast(pl.String).alias("re_split_role"),
        ]
    )


def _strip_temp_columns(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Drop the splitter's internal temporary columns."""
    schema_names = set(lf.collect_schema().names())
    to_drop = {
        "_re_effective_cap",
        "_re_property_value_eligible",
        "_re_secured_cap_eur",
        "_re_secured_ead",
        "_re_residual_ead",
    } & schema_names
    if not to_drop:
        return lf
    return lf.drop(list(to_drop))


def _new_ltv_expr(ead_col: str) -> pl.Expr:
    """LTV for whole-mode rows: full EAD over property value."""
    prop = pl.col("_re_property_value_eligible")
    return (
        pl.when(prop > 0.0)
        .then(pl.col(ead_col).fill_null(0.0) / prop)
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )


def _new_ltv_for_secured_expr() -> pl.Expr:
    """LTV for the secured row: secured_ead / property_value.

    Capped at the regulatory secured-LTV cap by construction
    (secured_ead = min(ead_final, cap × property_value)).
    """
    prop = pl.col("_re_property_value_eligible")
    return (
        pl.when(prop > 0.0)
        .then(pl.col("_re_secured_ead") / prop)
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )


def _has_income_cover_for_secured(is_basel_3_1: bool) -> pl.Expr:
    """has_income_cover for secured rows.

    CRR Art. 126(2)(d): True for CRE splits (rental coverage met is the
    precondition for emitting re_split_mode='split'). Residential CRR
    splits do not depend on income cover — set False.

    B3.1 Art. 124F/H general path requires has_income_cover=False so the
    Art. 124G/I income-producing branches are bypassed.
    """
    if is_basel_3_1:
        return pl.lit(False)
    is_commercial = pl.col("re_split_property_type") == "commercial"
    return pl.when(is_commercial).then(pl.lit(True)).otherwise(pl.lit(False))


def _scale_provision_expr(*, numerator: str) -> pl.Expr:
    """Allocate provisions pro-rata to the child row's EAD share."""
    parent_ead = pl.col("ead_final").fill_null(0.0)
    return (
        pl.when(parent_ead > 0.0)
        .then(
            pl.col("provision_allocated").fill_null(0.0)
            * pl.col(numerator).fill_null(0.0)
            / parent_ead
        )
        .otherwise(pl.lit(0.0))
    )


def _accumulate_split_errors(
    annotated: pl.LazyFrame,
    *,
    is_basel_3_1: bool,
) -> list[CalculationError]:
    """Collect informational warnings for diagnostically interesting rows.

    Three buckets:

    - ``RE002``: row has re_split_mode='split' but the effective cap
      multiplied by the property value yielded zero (e.g. property
      value zero after eligibility filtering, or B3.1 prior charges
      consumed the entire 55% cap).
    - ``RE004``: row had property collateral but failed CRR Art. 126
      rental coverage and was left in its original class.

    The diagnostics roll up to per-cause counts so the user sees one
    summary message per cause rather than an error per exposure.
    """
    errors: list[CalculationError] = []
    is_split_mode = pl.col("re_split_mode") == "split"
    has_secured_cap = pl.col("_re_secured_ead") > 0.0

    diagnostics = (
        annotated.with_columns(
            [
                (is_split_mode & ~has_secured_cap).alias("_re002"),
            ]
        )
        .select(
            [
                pl.col("_re002").sum().alias("re002_count"),
            ]
        )
        .collect()
    )
    if diagnostics.height > 0:
        re002_n = int(diagnostics["re002_count"][0] or 0)
        if re002_n > 0:
            errors.append(
                re_split_warning(
                    code=ERROR_RE_ZERO_EFFECTIVE_CAP,
                    message=(
                        f"{re002_n} exposure(s) flagged for the RE loan-split had "
                        "zero effective secured cap (after prior-charge reduction "
                        "or with zero eligible property value); rows left in their "
                        "original exposure class."
                    ),
                    regulatory_reference=(
                        "PRA PS1/26 Art. 124F(2)" if is_basel_3_1 else "CRR Art. 125"
                    ),
                )
            )

    # CRR-only: count rows that had property collateral but failed the
    # rental-coverage test. They are NOT flagged with re_split_mode='split'
    # but the user benefits from knowing why no preferential RW applied.
    if not is_basel_3_1:
        cre_failed = (
            annotated.filter(
                (pl.col("re_split_target_class") == "COMMERCIAL_MORTGAGE")
                & (pl.col("re_split_mode").is_null())
                & (pl.col("re_split_property_value").fill_null(0.0) > 0.0)
            )
            .select(pl.len().alias("n"))
            .collect()
        )
        if cre_failed.height > 0:
            n_failed = int(cre_failed["n"][0] or 0)
            if n_failed > 0:
                errors.append(
                    re_split_warning(
                        code=ERROR_RE_CRR_RENTAL_COVERAGE_FAILED,
                        message=(
                            f"{n_failed} commercial real estate exposure(s) had "
                            "qualifying property collateral but failed the CRR "
                            "Art. 126(2)(d) rental coverage test (>= 1.5x interest "
                            "costs); rows left at counterparty risk weight."
                        ),
                        regulatory_reference="CRR Art. 126(2)(d)",
                    )
                )

    # RE001 (non-eligible RE) is emitted earlier in the pipeline by the CRM
    # eligibility check; preserved here as a placeholder import to keep all
    # RE_* codes co-located in one module.
    _ = ERROR_RE_NON_ELIGIBLE_COLLATERAL
    return errors
