"""
Real estate loan-splitter for SA exposures collateralised by property.

Pipeline position:
    CRMProcessor -> RealEstateSplitter -> SA Calculator
    (pass-through for IRB / Slotting / Equity rows)

Scope: loan-splitting is a Standardised Approach mechanism (CRR Art. 125/126,
PRA PS1/26 Art. 124F/H all sit in the Credit Risk: Standardised Approach
Part). For IRB and Slotting exposures the regulatory treatment of real estate
collateral is via LGD (Art. 161(5) FIRB supervisory RRE floor / AIRB
own-estimate LGD / Art. 230-231 funded-credit-protection), handled upstream
by the CRM processor. Rows with ``approach != SA/EQUITY`` therefore pass
through this stage untouched even when the classifier flagged them as
``re_split_mode='split'``.

Key responsibilities (SA-bound rows only):
- Physically partitions a flagged exposure into one or two secured rows
  (reclassified to RESIDENTIAL_MORTGAGE / COMMERCIAL_MORTGAGE) plus a
  single residual row that retains the original counterparty exposure
  class so the standard corporate / retail risk weight applies on the
  uncollateralised remainder.
- Allocates EAD per component using the regime-specific
  ``SplitParameters.secured_ltv_cap`` (less prior charges under B3.1 per
  Art. 124F(2)).
- Emits a parent-id audit trail so downstream aggregations can reconcile
  the sum of (secured_rre + secured_cre + residual) EADs back to the parent.

Mixed RRE+CRE collateral (per-regime allocation):

- **CRR Art. 124(1) "any part of an exposure" — RRE-first sequential.**
  The lower-RW residential bucket is consumed first up to 80% × RRE value
  (Art. 125), then the CRE bucket on the remainder up to 50% × CRE value
  if rental coverage is met (Art. 126(2)(d)). Rationale: CRR has no
  explicit "mixed RE" paragraph; the "any part" wording lets the bank
  claim each preferential treatment on its respective pledged portion,
  and prioritising RRE minimises capital. Documented design choice.

- **PRA PS1/26 Art. 124(4) — pro-rata by collateral value (mandatory).**
  Compute ``rre_share = rre_v / (rre_v + cre_v)``; allocate
  ``rre_secured = min(EAD × rre_share, 0.55 × rre_v − prior_rre)`` and
  ``cre_secured = min(EAD × cre_share, 0.55 × cre_v − prior_cre)``;
  residual goes to the original counterparty class via Art. 124L. The
  single ``prior_charge_ltv`` input column is currently applied to both
  caps as a v1 simplification — known limitation, can be split into
  ``prior_charge_residential`` / ``prior_charge_commercial`` later.

Decision logic per regime (driven by ``data/tables/re_split_parameters.py``
constants — engine code declares no regulatory scalars):

| Regime / class                  | Secured LTV cap | Secured RW |
|---------------------------------|-----------------|------------|
| CRR Art. 125 (RRE)              | 80% LTV         | 35%        |
| CRR Art. 126 (CRE, rental met)  | 50% LTV         | 50%        |
| B3.1 Art. 124F (RRE)            | 55% × prop val  | 20%        |
| B3.1 Art. 124H(1)-(2) (CRE)     | 55% × prop val  | 60%        |
| B3.1 Art. 124H(3) (CRE other)   | whole-loan      | n/a        |

The actual risk weight is *not* set by the splitter — each secured row
is labelled ``RESIDENTIAL_MORTGAGE`` / ``COMMERCIAL_MORTGAGE`` with its
own ``property_type`` / ``ltv`` and the existing
``b31_residential_rw_expr`` / ``b31_commercial_rw_expr`` /
CRR ``_apply_residential_mortgage_rw`` paths in the SA calculator compute
the correct RW from those columns. The residual row keeps its original
``exposure_class`` so the SA calculator's normal corporate / retail path
applies.

Output ``re_split_role`` semantics (consumed by ``CRMAdjustedBundle``
audit and COREP reconciliation):

- ``secured`` — single-component preferential row (pure RRE or pure CRE)
- ``secured_rre`` / ``secured_cre`` — emitted as a pair for mixed exposures
- ``residual`` — uncollateralised remainder at counterparty RW
- ``whole`` — B3.1 Art. 124H(3) non-NP/SME corporate CRE-only path

References:
- CRR Art. 124(1): "any part of an exposure" framing for partial security.
- CRR Art. 125: Residential mortgage 35% on portion up to 80% LTV.
- CRR Art. 126(2)(d): Commercial real estate 50% — rental income must
  cover >= 1.5x interest costs.
- PRA PS1/26 Art. 124(4): Mixed RE pro-rata split by collateral value.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting (cap 55% less prior charges).
- PRA PS1/26 Art. 124H(1)-(2): B3.1 CRE loan-splitting for natural person / SME.
- PRA PS1/26 Art. 124H(3): B3.1 CRE max(60%, min(cp_rw, Art. 124I)) for other.
- PRA PS1/26 Art. 124L: Counterparty type residual RW table.

Classes:
    RealEstateSplitter: Implements RealEstateSplitterProtocol.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.errors import (
    ERROR_RE_CRR_RENTAL_COVERAGE_FAILED,
    ERROR_RE_MIXED_PROPERTY_TYPES,
    ERROR_RE_NON_ELIGIBLE_COLLATERAL,
    ERROR_RE_ZERO_EFFECTIVE_CAP,
    CalculationError,
    re_split_warning,
)
from rwa_calc.data.tables.re_split_parameters import (
    SplitParameters,
    re_split_parameters,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass

_SA_BOUND_APPROACHES: tuple[str, ...] = (ApproachType.SA.value, ApproachType.EQUITY.value)


@dataclass(frozen=True)
class _ComponentMeta:
    """Per-component naming + class metadata for the secured-row builder."""

    target_class: str
    prop_type: str
    secured_ead_col: str
    component_value_col: str
    ref_suffix_mixed: str
    role_mixed: str


_COMPONENT_META: dict[str, _ComponentMeta] = {
    "rre": _ComponentMeta(
        target_class=ExposureClass.RESIDENTIAL_MORTGAGE.value,
        prop_type="residential",
        secured_ead_col="_re_rre_secured_ead",
        component_value_col="_re_rre_value",
        ref_suffix_mixed="_rre",
        role_mixed="secured_rre",
    ),
    "cre": _ComponentMeta(
        target_class=ExposureClass.COMMERCIAL_MORTGAGE.value,
        prop_type="commercial",
        secured_ead_col="_re_cre_secured_ead",
        component_value_col="_re_cre_value",
        ref_suffix_mixed="_cre",
        role_mixed="secured_cre",
    ),
}


if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


class RealEstateSplitter:
    """Materialise the RE loan-split into two physical rows per exposure.

    Implements ``RealEstateSplitterProtocol`` from
    ``contracts/protocols.py``.
    """

    @cites("CRR Art. 125")
    @cites("CRR Art. 126")
    @cites("PS1/26, paragraph 124F")
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

        return CRMAdjustedBundle(
            exposures=unified,
            equity_exposures=data.equity_exposures,
            ciu_holdings=data.ciu_holdings,
            collateral_allocation=data.collateral_allocation,
            collateral_link_allocation=data.collateral_link_allocation,
            re_split_audit=audit,
            securitisation_audit=data.securitisation_audit,
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

    Per-component allocation: each row is annotated with both an RRE-
    secured EAD and a CRE-secured EAD using the regime-specific rule
    (CRR sequential RRE-first; B3.1 pro-rata by collateral value). Rows
    with both components > 0 are emitted as a triple (secured_rre +
    secured_cre + residual); single-component rows preserve the original
    ``secured + residual`` shape with ``re_split_role = "secured"``.

    Returns:
        Tuple of (new_unified_lazyframe, audit_lazyframe_or_none,
        accumulated_calculation_errors).
    """
    schema_names = set(exposures.collect_schema().names())

    # Short-circuit when the classifier did not flag any candidates
    # (older test fixtures, or no property collateral). The post-splitter
    # columns are added as nulls so downstream ensure_columns() is a no-op.
    required = {
        "re_split_mode",
        "re_split_target_class",
        "re_split_property_value",
        "ead_final",
    }
    if required - schema_names:
        return _annotate_unsplit(exposures), None, []

    ead_col = "ead_final"
    annotated = _annotate_with_components(
        exposures,
        rrep=rrep,
        crep=crep,
        is_basel_3_1=is_basel_3_1,
        schema_names=schema_names,
        ead_col=ead_col,
    )

    is_sa_bound = _sa_bound_mask(schema_names)
    mode = pl.col("re_split_mode").fill_null("none")
    is_split_mode = (mode == "split") & is_sa_bound
    is_whole_mode = (mode == "whole") & is_sa_bound
    has_any_secured = (pl.col("_re_rre_secured_ead") > 0.0) | (pl.col("_re_cre_secured_ead") > 0.0)
    is_actual_split = is_split_mode & has_any_secured

    # Pass-through: rows the splitter does not touch.
    pass_through = (
        annotated.filter(~(is_actual_split | is_whole_mode))
        .pipe(_strip_temp_columns)
        .with_columns(
            [
                pl.lit(None).cast(pl.String).alias("split_parent_id"),
                pl.lit(None).cast(pl.String).alias("re_split_role"),
            ]
        )
    )

    # Whole-loan reclassification (B3.1 CRE Art. 124H(3) corporate path).
    whole_rows = (
        annotated.filter(is_whole_mode)
        .with_columns(
            [
                pl.col("re_split_target_class").alias("exposure_class"),
                _new_ltv_for_whole_expr(ead_col).alias("ltv"),
                pl.col("re_split_property_type").alias("property_type"),
                pl.col("exposure_reference").alias("split_parent_id"),
                pl.lit("whole").alias("re_split_role"),
            ]
        )
        .pipe(_strip_temp_columns)
    )

    # True split: emit one secured row per non-zero component plus a
    # single residual row per parent.
    split_base = annotated.filter(is_actual_split)

    rre_secured_rows = (
        split_base.filter(pl.col("_re_rre_secured_ead") > 0.0)
        .with_columns(_secured_columns(component="rre", is_basel_3_1=is_basel_3_1, ead_col=ead_col))
        .pipe(_strip_temp_columns)
    )
    cre_secured_rows = (
        split_base.filter(pl.col("_re_cre_secured_ead") > 0.0)
        .with_columns(_secured_columns(component="cre", is_basel_3_1=is_basel_3_1, ead_col=ead_col))
        .pipe(_strip_temp_columns)
    )
    residual_rows = split_base.with_columns(_residual_columns(ead_col=ead_col)).pipe(
        _strip_temp_columns
    )

    new_unified = pl.concat(
        [pass_through, whole_rows, rre_secured_rows, cre_secured_rows, residual_rows],
        how="diagonal_relaxed",
    )
    audit = _build_audit_frame(
        annotated.filter(is_actual_split | is_whole_mode),
        is_basel_3_1=is_basel_3_1,
        ead_col=ead_col,
    )
    errors = _accumulate_split_errors(annotated, is_basel_3_1=is_basel_3_1)
    return new_unified, audit, errors


def _annotate_with_components(
    exposures: pl.LazyFrame,
    *,
    rrep: SplitParameters,
    crep: SplitParameters,
    is_basel_3_1: bool,
    schema_names: set[str],
    ead_col: str,
) -> pl.LazyFrame:
    """Add the splitter's `_re_*` per-component temp columns to every row.

    Owns the three-step `.with_columns()` chain that materialises:

    - ``_re_rre_value`` / ``_re_cre_value`` — eligible property values
    - ``_re_rre_eligible`` / ``_re_cre_eligible`` — per-regime gates
    - ``_re_rre_secured_ead`` / ``_re_cre_secured_ead`` — allocated EAD per regime
    - ``_re_residual_ead`` — uncollateralised remainder
    - ``_re_is_mixed`` — both components contributed > 0 secured EAD

    Backward-compat: when the classifier hasn't emitted the per-component
    columns (older unit-test fixtures), the value/eligibility expressions
    derive them from the legacy single-target columns.
    """
    rre_v_expr, cre_v_expr = _component_value_exprs(schema_names)
    rre_eligible_expr, cre_eligible_expr = _component_eligibility_exprs(
        schema_names, is_basel_3_1=is_basel_3_1, rre_v_expr=rre_v_expr, cre_v_expr=cre_v_expr
    )
    prior_charge = (
        pl.col("prior_charge_ltv").fill_null(0.0)
        if "prior_charge_ltv" in schema_names
        else pl.lit(0.0)
    )
    # PRA PS1/26 Art. 124(4) all-or-nothing gate: mixed-RE rows whose qualifying
    # test failed take the Art. 124J path. The pro-rata EAD split still applies
    # but WITHOUT the 0.55xV preferential cap — the full apportioned share lands
    # on each secured row so no residual remains at the counterparty class.
    force_other_re = (
        pl.col("re_split_force_other_re").fill_null(False)
        if "re_split_force_other_re" in schema_names
        else pl.lit(False)
    )
    # Secured-row qualifying flag: when the Art. 124(4) gate fires, BOTH secured
    # rows become non-qualifying so the SA calculator routes them to Art. 124J;
    # otherwise the parent's existing is_qualifying_re (or null) is preserved.
    parent_qualifying = (
        pl.col("is_qualifying_re")
        if "is_qualifying_re" in schema_names
        else pl.lit(None, dtype=pl.Boolean)
    )
    secured_qualifying_expr = (
        pl.when(force_other_re).then(pl.lit(False)).otherwise(parent_qualifying)
    )
    ead_safe = pl.col(ead_col).fill_null(0.0)
    rre_secured_expr, cre_secured_expr = _allocation_exprs(
        is_basel_3_1=is_basel_3_1,
        rrep=rrep,
        crep=crep,
        ead_expr=ead_safe,
        rre_v_expr=rre_v_expr,
        cre_v_expr=cre_v_expr,
        rre_eligible_expr=rre_eligible_expr,
        cre_eligible_expr=cre_eligible_expr,
        prior_charge=prior_charge,
        force_other_re=force_other_re,
    )
    return (
        exposures.with_columns(
            [
                rre_v_expr.alias("_re_rre_value"),
                cre_v_expr.alias("_re_cre_value"),
                rre_eligible_expr.alias("_re_rre_eligible"),
                cre_eligible_expr.alias("_re_cre_eligible"),
                secured_qualifying_expr.alias("_re_secured_qualifying"),
            ]
        )
        .with_columns(
            [
                rre_secured_expr.alias("_re_rre_secured_ead"),
                cre_secured_expr.alias("_re_cre_secured_ead"),
            ]
        )
        .with_columns(
            [
                (
                    ead_safe
                    - pl.col("_re_rre_secured_ead").fill_null(0.0)
                    - pl.col("_re_cre_secured_ead").fill_null(0.0)
                )
                .clip(lower_bound=0.0)
                .alias("_re_residual_ead"),
                (
                    (pl.col("_re_rre_secured_ead") > 0.0) & (pl.col("_re_cre_secured_ead") > 0.0)
                ).alias("_re_is_mixed"),
            ]
        )
    )


def _build_audit_frame(affected: pl.LazyFrame, *, is_basel_3_1: bool, ead_col: str) -> pl.LazyFrame:
    """Select one audit row per affected parent (split or whole-loan).

    Carries the per-component breakdown so COREP reconciliation can
    decompose mixed-collateral splits back to the parent EAD.
    """
    return affected.select(
        [
            pl.col("exposure_reference").alias("split_parent_id"),
            pl.col(ead_col).alias("parent_ead"),
            (
                pl.col("_re_rre_secured_ead").fill_null(0.0)
                + pl.col("_re_cre_secured_ead").fill_null(0.0)
            ).alias("secured_ead"),
            pl.col("_re_rre_secured_ead").alias("rre_secured_ead"),
            pl.col("_re_cre_secured_ead").alias("cre_secured_ead"),
            pl.col("_re_residual_ead").alias("residual_ead"),
            pl.col("_re_rre_value").alias("rre_property_value"),
            pl.col("_re_cre_value").alias("cre_property_value"),
            (pl.col("_re_rre_value") + pl.col("_re_cre_value")).alias("property_value_eligible"),
            pl.col("re_split_target_class").alias("target_class"),
            pl.col("re_split_property_type").alias("property_type"),
            pl.col("re_split_mode").alias("re_split_mode"),
            pl.col("_re_is_mixed").alias("is_mixed"),
            pl.lit("basel_3_1" if is_basel_3_1 else "crr").alias("regime"),
        ]
    )


def _annotate_unsplit(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Add post-splitter columns (null) when no candidates are present."""
    return exposures.with_columns(
        [
            pl.lit(None).cast(pl.String).alias("split_parent_id"),
            pl.lit(None).cast(pl.String).alias("re_split_role"),
        ]
    )


def _strip_temp_columns(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Drop the splitter's internal temporary columns.

    All temporaries share the ``_re_`` prefix; using a column selector
    avoids the per-call ``collect_schema()`` walk that would otherwise
    hit the lazy plan four times per pipeline run.
    """
    return lf.select(pl.exclude("^_re_.*$"))


def _sa_bound_mask(schema_names: set[str]) -> pl.Expr:
    """SA-only gate: treat IRB / Slotting rows as out of scope for the splitter."""
    if "approach" in schema_names:
        return pl.col("approach").is_in(list(_SA_BOUND_APPROACHES))
    return pl.lit(True)


def _component_value_exprs(schema_names: set[str]) -> tuple[pl.Expr, pl.Expr]:
    """Return (rre_v_expr, cre_v_expr) with backward-compat fallback.

    Prefers the new per-component classifier columns; falls back to
    deriving values from the legacy single-target ``re_split_property_type``
    + ``re_split_property_value`` columns for older test fixtures that
    bypass the classifier.
    """
    if "re_split_residential_value" in schema_names and "re_split_commercial_value" in schema_names:
        return (
            pl.col("re_split_residential_value").fill_null(0.0),
            pl.col("re_split_commercial_value").fill_null(0.0),
        )
    prop_v = pl.col("re_split_property_value").fill_null(0.0)
    prop_t = pl.col("re_split_property_type").fill_null("none")
    return (
        pl.when(prop_t == "residential").then(prop_v).otherwise(pl.lit(0.0)),
        pl.when(prop_t == "commercial").then(prop_v).otherwise(pl.lit(0.0)),
    )


def _component_eligibility_exprs(
    schema_names: set[str],
    *,
    is_basel_3_1: bool,
    rre_v_expr: pl.Expr,
    cre_v_expr: pl.Expr,
) -> tuple[pl.Expr, pl.Expr]:
    """Return (rre_eligible_expr, cre_eligible_expr) with backward-compat fallback."""
    if (
        "re_split_residential_eligible" in schema_names
        and "re_split_commercial_eligible" in schema_names
    ):
        return (
            pl.col("re_split_residential_eligible").fill_null(False),
            pl.col("re_split_commercial_eligible").fill_null(False),
        )
    is_split = pl.col("re_split_mode").fill_null("none") == "split"
    prop_t = pl.col("re_split_property_type").fill_null("none")
    rre_elig = is_split & (prop_t == "residential") & (rre_v_expr > 0.0)
    if is_basel_3_1:
        cre_elig = is_split & (prop_t == "commercial") & (cre_v_expr > 0.0)
    else:
        rental_met = (
            pl.col("re_split_cre_rental_coverage_met").fill_null(False)
            if "re_split_cre_rental_coverage_met" in schema_names
            else pl.lit(False)
        )
        cre_elig = is_split & (prop_t == "commercial") & (cre_v_expr > 0.0) & rental_met
    return rre_elig, cre_elig


def _allocation_exprs(
    *,
    is_basel_3_1: bool,
    rrep: SplitParameters,
    crep: SplitParameters,
    ead_expr: pl.Expr,
    rre_v_expr: pl.Expr,
    cre_v_expr: pl.Expr,
    rre_eligible_expr: pl.Expr,
    cre_eligible_expr: pl.Expr,
    prior_charge: pl.Expr,
    force_other_re: pl.Expr,
) -> tuple[pl.Expr, pl.Expr]:
    """Return (rre_secured_ead_expr, cre_secured_ead_expr) per regime.

    - **CRR**: sequential RRE-first (Art. 124(1) "any part of an
      exposure"). RRE consumes up to its 80% LTV cap on the full EAD,
      then CRE picks up the remainder up to its 50% LTV cap (Art. 126
      with rental coverage gate already enforced via cre_eligible).
    - **B3.1**: pro-rata by collateral value (PRA PS1/26 Art. 124(4)).
      Each component's secured EAD = min(EAD × component_share, cap_pct
      × component_value), where component_share = component_v / (rre_v +
      cre_v) and cap_pct is reduced by ``prior_charge_ltv`` per
      Art. 124F(2) / 124H(2).
    - **B3.1 Art. 124(4) all-or-nothing gate** (``force_other_re``): a
      mixed-RE exposure with any non-qualifying component drops to Art.
      124J. The pro-rata split still applies, but the 0.55×V preferential
      cap is removed — each component takes its FULL apportioned share
      (EAD × component_share) so the residual is zero.
    """
    rrep_cap_pct = float(rrep.secured_ltv_cap)
    crep_cap_pct = float(crep.secured_ltv_cap)

    rrep_eff_cap = (
        pl.max_horizontal(pl.lit(0.0), pl.lit(rrep_cap_pct) - prior_charge)
        if rrep.uses_prior_charge_reduction
        else pl.lit(rrep_cap_pct)
    )
    crep_eff_cap = (
        pl.max_horizontal(pl.lit(0.0), pl.lit(crep_cap_pct) - prior_charge)
        if crep.uses_prior_charge_reduction
        else pl.lit(crep_cap_pct)
    )

    rre_cap_eur = rrep_eff_cap * rre_v_expr
    cre_cap_eur = crep_eff_cap * cre_v_expr

    if is_basel_3_1:
        total_v = rre_v_expr + cre_v_expr
        rre_share = pl.when(total_v > 0.0).then(rre_v_expr / total_v).otherwise(pl.lit(0.0))
        cre_share = pl.when(total_v > 0.0).then(cre_v_expr / total_v).otherwise(pl.lit(0.0))
        rre_alloc = ead_expr * rre_share
        cre_alloc = ead_expr * cre_share
        # Art. 124(4) all-or-nothing: full pro-rata share when the gate fires
        # (Art. 124J path, no preferential cap); capped pro-rata otherwise.
        rre_capped = (
            pl.when(force_other_re)
            .then(rre_alloc)
            .otherwise(pl.min_horizontal(rre_alloc, rre_cap_eur))
        )
        cre_capped = (
            pl.when(force_other_re)
            .then(cre_alloc)
            .otherwise(pl.min_horizontal(cre_alloc, cre_cap_eur))
        )
        rre_secured = pl.when(rre_eligible_expr).then(rre_capped).otherwise(pl.lit(0.0))
        cre_secured = pl.when(cre_eligible_expr).then(cre_capped).otherwise(pl.lit(0.0))
    else:
        # CRR sequential RRE-first: RRE first against full EAD, CRE on the remainder.
        rre_secured = (
            pl.when(rre_eligible_expr)
            .then(pl.min_horizontal(ead_expr, rre_cap_eur))
            .otherwise(pl.lit(0.0))
        )
        cre_remaining = pl.max_horizontal(pl.lit(0.0), ead_expr - rre_secured)
        cre_secured = (
            pl.when(cre_eligible_expr)
            .then(pl.min_horizontal(cre_remaining, cre_cap_eur))
            .otherwise(pl.lit(0.0))
        )

    return rre_secured, cre_secured


def _secured_columns(
    *,
    component: str,
    is_basel_3_1: bool,
    ead_col: str,
) -> list[pl.Expr]:
    """Build the with_columns expression list for one secured child row.

    Mixed splits emit ``secured_rre`` + ``secured_cre`` so audit
    consumers can identify mixed-collateral lineage; single-component
    splits keep the legacy ``secured`` role for backward compat.
    """
    meta = _COMPONENT_META[component]
    return [
        pl.lit(meta.target_class).alias("exposure_class"),
        pl.col(meta.secured_ead_col).alias(ead_col),
        pl.col(meta.component_value_col).alias("property_collateral_value"),
        _new_ltv_for_component_expr(component).alias("ltv"),
        pl.lit(meta.prop_type).alias("property_type"),
        # PRA PS1/26 Art. 124(4) all-or-nothing gate: when the mixed-RE
        # qualifying test fails, this secured row is forced non-qualifying
        # (materialised upstream as ``_re_secured_qualifying``) so the SA
        # calculator routes it through Art. 124J (Other RE) instead of the
        # preferential Art. 124F / 124H tables.
        pl.col("_re_secured_qualifying").alias("is_qualifying_re"),
        # CRR CRE splits set has_income_cover=True so Art. 126's
        # `(ltv <= 0.50) & has_income_cover` returns the 50% RW.
        # B3.1 + RRE always pass False so the general Art. 124F/H
        # path is taken (income-producing branches are bypassed).
        _has_income_cover_for_component(is_basel_3_1, meta.prop_type).alias("has_income_cover"),
        _scale_provision_expr(numerator=meta.secured_ead_col).alias("provision_allocated"),
        pl.col("exposure_reference").alias("split_parent_id"),
        pl.when(pl.col("_re_is_mixed"))
        .then(pl.col("exposure_reference") + pl.lit(meta.ref_suffix_mixed))
        .otherwise(pl.col("exposure_reference") + pl.lit("_sec"))
        .alias("exposure_reference"),
        pl.when(pl.col("_re_is_mixed"))
        .then(pl.lit(meta.role_mixed))
        .otherwise(pl.lit("secured"))
        .alias("re_split_role"),
    ]


def _residual_columns(*, ead_col: str) -> list[pl.Expr]:
    """Build the with_columns list for a residual row.

    The residual carries the uncollateralised EAD and keeps the original
    counterparty exposure class so the SA calculator's standard corporate
    / retail RW path applies (CRR Art. 124(1) ¶3 / PS1/26 Art. 124L).
    Zero-EAD residuals are still emitted so per-parent reconciliation
    (sum_child_ead == parent_ead) holds.
    """
    return [
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


def _new_ltv_for_whole_expr(ead_col: str) -> pl.Expr:
    """LTV for whole-mode rows: full EAD over the eligible property value.

    Whole mode is only emitted by the classifier for B3.1 pure-CRE non-
    NP/SME corporates (Art. 124H(3)), so the eligible property value is
    the CRE component value.
    """
    prop = pl.col("_re_cre_value")
    return (
        pl.when(prop > 0.0)
        .then(pl.col(ead_col).fill_null(0.0) / prop)
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )


def _new_ltv_for_component_expr(component: str) -> pl.Expr:
    """LTV for a secured component row: secured_ead / component_property_value.

    Capped at the regulatory secured-LTV cap by construction
    (secured_ead = min(allocation, cap_pct × component_value)).
    """
    meta = _COMPONENT_META[component]
    prop = pl.col(meta.component_value_col)
    secured = pl.col(meta.secured_ead_col)
    return pl.when(prop > 0.0).then(secured / prop).otherwise(pl.lit(None, dtype=pl.Float64))


def _has_income_cover_for_component(is_basel_3_1: bool, prop_type: str) -> pl.Expr:
    """has_income_cover for a per-component secured row.

    CRR Art. 126(2)(d): True for CRE splits (rental coverage met is a
    precondition of CRE-eligibility — already enforced upstream).
    Residential splits do not depend on income cover.

    B3.1 Art. 124F/H general path requires has_income_cover=False so the
    Art. 124G/I income-producing branches are bypassed.
    """
    if is_basel_3_1 or prop_type == "residential":
        return pl.lit(False)
    return pl.lit(True)


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

    Buckets:

    - ``RE002``: row has re_split_mode='split' but every eligible
      component yielded zero secured EAD (property value zero after
      eligibility filtering, or B3.1 prior charges consumed the full
      55% cap).
    - ``RE003``: mixed RRE+CRE exposure split per regime — informational
      count of how many exposures were apportioned across both classes.
    - ``RE004``: row had commercial property collateral but failed CRR
      Art. 126 rental coverage and was left in its original class.

    The diagnostics roll up to per-cause counts so the user sees one
    summary message per cause rather than an error per exposure.
    """
    counts = _collect_diagnostic_counts(annotated)
    candidates = (
        _warning_re002(counts["re002"], is_basel_3_1=is_basel_3_1),
        _warning_re003(counts["re003"], is_basel_3_1=is_basel_3_1),
        _warning_re004(counts["re004"]) if not is_basel_3_1 else None,
    )
    return [w for w in candidates if w is not None]


def _collect_diagnostic_counts(annotated: pl.LazyFrame) -> dict[str, int]:
    """Single-pass collect of the RE002 / RE003 / RE004 row counts."""
    schema_names = set(annotated.collect_schema().names())
    is_sa_bound = _sa_bound_mask(schema_names)
    is_split_mode = (pl.col("re_split_mode") == "split") & is_sa_bound
    has_any_secured = (pl.col("_re_rre_secured_ead") > 0.0) | (pl.col("_re_cre_secured_ead") > 0.0)
    # CRR-only: rows with commercial property collateral whose split was
    # blocked because Art. 126(2)(d) rental coverage failed (re_split_mode
    # is null but the classifier left target_class for diagnostics).
    cre_rental_failed_predicate = (
        (pl.col("re_split_target_class") == ExposureClass.COMMERCIAL_MORTGAGE.value)
        & (pl.col("re_split_mode").is_null())
        & (pl.col("re_split_property_value").fill_null(0.0) > 0.0)
        & is_sa_bound
    )
    df = (
        annotated.with_columns(
            [
                (is_split_mode & ~has_any_secured).alias("_re002"),
                (is_split_mode & pl.col("_re_is_mixed")).alias("_re003"),
                cre_rental_failed_predicate.alias("_re004"),
            ]
        )
        .select(
            [
                pl.col("_re002").sum().alias("re002"),
                pl.col("_re003").sum().alias("re003"),
                pl.col("_re004").sum().alias("re004"),
            ]
        )
        .collect()
    )
    if df.height == 0:
        return {"re002": 0, "re003": 0, "re004": 0}
    row = df.row(0, named=True)
    return {key: int(row[key] or 0) for key in ("re002", "re003", "re004")}


def _warning_re002(count: int, *, is_basel_3_1: bool) -> CalculationError | None:
    """Zero effective secured cap on a flagged split row."""
    if count <= 0:
        return None
    return re_split_warning(
        code=ERROR_RE_ZERO_EFFECTIVE_CAP,
        message=(
            f"{count} exposure(s) flagged for the RE loan-split had "
            "zero effective secured cap (after prior-charge reduction "
            "or with zero eligible property value); rows left in their "
            "original exposure class."
        ),
        regulatory_reference="PRA PS1/26 Art. 124F(2)" if is_basel_3_1 else "CRR Art. 125",
    )


def _warning_re003(count: int, *, is_basel_3_1: bool) -> CalculationError | None:
    """Mixed RRE+CRE exposure apportioned across both classes."""
    if count <= 0:
        return None
    allocation_rule = (
        "pro-rata by collateral value (PRA PS1/26 Art. 124(4))"
        if is_basel_3_1
        else "RRE-first sequential (CRR Art. 124(1) 'any part of an exposure')"
    )
    return re_split_warning(
        code=ERROR_RE_MIXED_PROPERTY_TYPES,
        message=(
            f"{count} exposure(s) carried both residential and "
            f"commercial real-estate collateral; allocated using "
            f"{allocation_rule} and emitted as paired "
            "secured_rre + secured_cre + residual rows."
        ),
        regulatory_reference="PRA PS1/26 Art. 124(4)" if is_basel_3_1 else "CRR Art. 124(1)",
    )


def _warning_re004(count: int) -> CalculationError | None:
    """CRR-only: CRE collateral failed Art. 126(2)(d) rental coverage."""
    if count <= 0:
        return None
    return re_split_warning(
        code=ERROR_RE_CRR_RENTAL_COVERAGE_FAILED,
        message=(
            f"{count} commercial real estate exposure(s) had "
            "qualifying property collateral but failed the CRR "
            "Art. 126(2)(d) rental coverage test (>= 1.5x interest "
            "costs); rows left at counterparty risk weight."
        ),
        regulatory_reference="CRR Art. 126(2)(d)",
    )


# RE001 (non-eligible RE) is emitted earlier in the pipeline by the CRM
# eligibility check; the import is preserved so all RE_* codes stay
# discoverable from one module.
_ = ERROR_RE_NON_ELIGIBLE_COLLATERAL
