"""
Real-estate loan-split candidate flagging for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    after subtype classification. The ``re_split_*`` candidate columns it
    emits are consumed only by the downstream ``RealEstateSplitter`` stage
    (``engine/re_splitter.py``) — this module is deliberately self-contained
    so the Slice-4 re_split co-location decision never has to move it again.

Key responsibilities:
- Flag SA-bound exposures eligible for the RE loan-split
  (``flag_property_reclassification_candidates``) — 10 ``re_split_*``
  candidate columns; no row duplication (physical splitting happens in the
  splitter, after CRM has run).
- Property-value primitives, candidate gates, per-component eligibility,
  legacy single-target outputs, and per-component values (the 5
  ``_re_split_*`` expression-block helpers).

References:
- CRR Art. 125 / Art. 126: RRE / CRE preferential treatment (split candidacy)
- CRR Art. 124(1): "any part of an exposure" wording (mixed collateral)
- PS1/26, paragraph 124.4: mixed-RE per-component eligibility gate
- PRA PS1/26 Art. 124F / Art. 124H / Art. 124I / Art. 124J: B3.1 RE tables
- PRA PS1/26 Art. 124(3) / Art. 124K: ADC exclusion from the split
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import ExposureClass

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


# Target exposure-class labels used by the RE loan-splitter. Sourced from
# ``ExposureClass`` so the lowercase enum convention (e.g. ``"retail_mortgage"``)
# extends consistently to the loan-splitter outputs. The SA calculator's RE
# branch in ``engine/sa/namespace.py`` uppercases ``exposure_class`` before
# substring-matching, so either case routes correctly.
_SECURED_TARGET_RESIDENTIAL = ExposureClass.RESIDENTIAL_MORTGAGE.value
_SECURED_TARGET_COMMERCIAL = ExposureClass.COMMERCIAL_MORTGAGE.value


# =========================================================================
# Real estate loan-split candidate flagging
# =========================================================================


def flag_property_reclassification_candidates(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    schema_names: set[str],
) -> pl.LazyFrame:
    """
    Flag SA-bound exposures eligible for the RE loan-split.

    Adds the candidate columns consumed by the downstream
    ``RealEstateSplitter`` stage (re_split_target_class,
    re_split_mode, re_split_property_value, re_split_property_type,
    re_split_cre_rental_coverage_met). Does NOT duplicate rows —
    physical splitting happens in the splitter, after CRM has run.

    Decision logic per regime:

    - **CRR Art. 125 (RRE):** any non-mortgage SA exposure with
      residential property collateral becomes a split candidate.
      Secured cap = 80% LTV, secured RW = 35%.
    - **CRR Art. 126 (CRE):** commercial property collateral is a
      candidate only when the rental-income coverage test
      (>= 1.5x interest costs) is met. The flag
      re_split_cre_rental_coverage_met carries the test outcome;
      the splitter emits ``RE004`` when False.
    - **B3.1 Art. 124F (RRE):** loan-split with cap = 55% × property
      value (less prior charges per Art. 124F(2)), secured RW = 20%.
    - **B3.1 Art. 124H(1)-(2) (CRE NP/SME):** loan-split with cap
      55%, secured RW = 60%.
    - **B3.1 Art. 124H(3) (CRE other):** ``re_split_mode = "whole"``
      — single ``COMMERCIAL_MORTGAGE`` row so the existing
      ``b31_commercial_rw_expr`` Art. 124H(3) branch
      (max(60%, min(cp_rw, Art. 124I RW))) handles it.

    **Mixed RRE+CRE collateral (PRA PS1/26 Art. 124(4) and CRR Art.
    124(1) "any part" wording):** when an exposure carries both
    residential and commercial property collateral, the per-component
    columns ``re_split_residential_value`` /
    ``re_split_commercial_value`` and the per-component eligibility
    flags ``re_split_residential_eligible`` /
    ``re_split_commercial_eligible`` are emitted so the splitter can
    materialise a secured row per property type plus a single residual.
    The legacy ``re_split_target_class`` /
    ``re_split_property_type`` / ``re_split_property_value`` columns
    are kept populated for audit and warning consumers — for mixed
    rows ``re_split_property_type = "mixed"`` and
    ``re_split_property_value = rre_v + cre_v``.

    Exclusions (higher-priority Art. 112 classes must not be
    downgraded): defaulted, securitisation, covered bond, equity,
    CIU, subordinated, high-risk, and exposures already classified
    as RESIDENTIAL_MORTGAGE / RETAIL_MORTGAGE / COMMERCIAL_MORTGAGE.
    """
    primitives = _re_split_property_primitives(schema_names)
    gates = _re_split_candidate_gates(primitives)
    eligibility = _re_split_per_component_eligibility(primitives, gates, config)
    legacy_outputs = _re_split_legacy_outputs(primitives, gates, eligibility, config)
    per_component_values = _re_split_per_component_values(primitives, eligibility)

    return exposures.with_columns(
        [
            legacy_outputs["re_split_target_class"].alias("re_split_target_class"),
            legacy_outputs["re_split_mode"].alias("re_split_mode"),
            legacy_outputs["re_split_property_type"].alias("re_split_property_type"),
            legacy_outputs["re_split_property_value"].alias("re_split_property_value"),
            per_component_values["re_split_residential_value"].alias("re_split_residential_value"),
            per_component_values["re_split_commercial_value"].alias("re_split_commercial_value"),
            eligibility["rre_eligible"].alias("re_split_residential_eligible"),
            eligibility["cre_eligible"].alias("re_split_commercial_eligible"),
            primitives["cre_rental_coverage_met"].alias("re_split_cre_rental_coverage_met"),
            eligibility["force_other_re"].alias("re_split_force_other_re"),
        ]
    )


def _re_split_property_primitives(schema_names: set[str]) -> dict[str, pl.Expr]:
    """Build the property-value primitives consumed by every later block.

    Returns expressions for residential / commercial / total property
    value, the corresponding ``has_*`` predicates, residential-dominance,
    and the CRR CRE rental-coverage test (≥ 1.5× interest costs;
    conservative default of False when ``rental_to_interest_ratio`` is
    absent).
    """
    # Loan-split component values use the UNCAPPED RE collateral values
    # (PRA PS1/26 Art. 124(4) pro-rata is by raw collateral value, and the
    # 0.55xV cap is on raw property value). Both are hierarchy_exit
    # contract columns — always present, null = no RE collateral.
    residential_value = pl.col("residential_collateral_value_uncapped").fill_null(0.0)
    commercial_value = pl.col("commercial_collateral_value_uncapped").fill_null(0.0)
    property_value = residential_value + commercial_value

    # KEEP (presence guard on a non-contract column): the CRR Art. 126
    # rental-coverage input is not declared on hierarchy_exit, so a sealed
    # frame never carries it and the conservative False branch applies.
    if "rental_to_interest_ratio" in schema_names:
        cre_rental_coverage_met = pl.col("rental_to_interest_ratio").fill_null(0.0) >= 1.5
    else:
        cre_rental_coverage_met = pl.lit(False)

    # PRA PS1/26 Art. 124(4): per-beneficiary flag (set by the hierarchy
    # resolver) marking that at least one RE collateral component fails
    # Art. 124A. Drives the all-or-nothing gate for mixed-RE exposures.
    re_collateral_non_qualifying = pl.col("re_collateral_non_qualifying").fill_null(False)

    return {
        "residential_value": residential_value,
        "property_value": property_value,
        "commercial_value": commercial_value,
        "has_property": property_value > 0.0,
        "has_rre": residential_value > 0.0,
        "has_cre": commercial_value > 0.0,
        "is_residential_dominant": residential_value >= commercial_value,
        "cre_rental_coverage_met": cre_rental_coverage_met,
        "re_collateral_non_qualifying": re_collateral_non_qualifying,
    }


def _re_split_candidate_gates(
    primitives: dict[str, pl.Expr],
) -> dict[str, pl.Expr]:
    """Build the row-level eligibility predicates that gate the split.

    - ``is_candidate``: row may be considered for splitting (eligible class,
      has property collateral, not income-producing).
    - ``is_npsme``: counterparty is natural-person OR SME — drives the
      B3.1 Art. 124H(3) whole-loan path for pure-CRE non-NP/SME corporates.

    Already-classified RE rows are excluded because they're handled by the
    existing whole-loan path (CRR ``_apply_residential_mortgage_rw`` /
    B3.1 ``b31_residential_rw_expr``). Higher-priority Art. 112 classes
    (defaulted, equity, covered bond, high-risk) are also excluded — they
    must never be downgraded. ADC-flagged rows (PRA PS1/26 Art. 124(3)) are
    also excluded so the 150% Art. 124K(1) ADC RW applies to the whole
    exposure rather than a loan-split residential / corporate residual.
    """
    existing_re_classes = [
        _SECURED_TARGET_RESIDENTIAL,
        _SECURED_TARGET_COMMERCIAL,
        ExposureClass.RETAIL_MORTGAGE.value,
    ]
    excluded_classes = existing_re_classes + [
        ExposureClass.DEFAULTED.value,
        ExposureClass.EQUITY.value,
        ExposureClass.COVERED_BOND.value,
        ExposureClass.HIGH_RISK.value,
    ]
    is_eligible_class = ~pl.col("exposure_class").is_in(excluded_classes) & ~pl.col("is_defaulted")

    # Income-producing RE goes through the existing whole-loan path
    # (Art. 124G / Art. 124I bands), not the split mechanism.
    is_income_producing = pl.col("has_income_cover").fill_null(False)

    # PRA PS1/26 Art. 124(3) / Art. 124K: ADC exposures route to the 150%
    # ADC path on the whole exposure — they must not be loan-split.
    is_adc = pl.col("is_adc").fill_null(False)

    is_candidate = is_eligible_class & primitives["has_property"] & ~is_income_producing & ~is_adc

    is_natural_person = pl.col("cp_is_natural_person").fill_null(False)
    is_sme_flag = pl.col("is_sme").fill_null(False)

    return {
        "is_candidate": is_candidate,
        "is_npsme": is_natural_person | is_sme_flag,
    }


@cites("PS1/26, paragraph 124.4")
def _re_split_per_component_eligibility(
    primitives: dict[str, pl.Expr],
    gates: dict[str, pl.Expr],
    config: CalculationConfig,
) -> dict[str, pl.Expr]:
    """Build per-component eligibility flags for the RE loan splitter.

    Implements the PRA PS1/26 Art. 124(4) mixed-RE rule (and CRR Art.
    124(1) "any part of an exposure" wording): each property component
    is evaluated against its own regime gate. Under CRR, CRE additionally
    requires the rental-coverage test. ``is_mixed`` flags rows where
    both components are eligible — the splitter materialises one secured
    row per eligible component plus a single residual.

    Art. 124(4) all-or-nothing qualifying gate (Basel 3.1 only): the
    preferential Art. 124F-124I tables apply to a mixed-RE exposure only
    when BOTH components separately qualify under Art. 124A. If either
    component fails (``re_collateral_non_qualifying``), ``force_other_re``
    fires and the splitter routes BOTH secured rows through Art. 124J
    (Other RE) — no partial preference. CRR has no Art. 124(4) limb, so
    the gate is suppressed on the CRR path.
    """
    rre_eligible = gates["is_candidate"] & primitives["has_rre"]
    if config.is_basel_3_1:
        cre_eligible = gates["is_candidate"] & primitives["has_cre"]
    else:
        cre_eligible = (
            gates["is_candidate"] & primitives["has_cre"] & primitives["cre_rental_coverage_met"]
        )
    is_mixed = rre_eligible & cre_eligible
    force_other_re = (
        is_mixed & primitives["re_collateral_non_qualifying"]
        if config.is_basel_3_1
        else pl.lit(False)
    )
    return {
        "rre_eligible": rre_eligible,
        "cre_eligible": cre_eligible,
        "is_mixed": is_mixed,
        "force_other_re": force_other_re,
    }


def _re_split_legacy_outputs(
    primitives: dict[str, pl.Expr],
    gates: dict[str, pl.Expr],
    eligibility: dict[str, pl.Expr],
    config: CalculationConfig,
) -> dict[str, pl.Expr]:
    """Build the legacy single-target output expressions.

    These columns predate the per-component split and are kept populated
    for audit and warning consumers. For mixed rows
    ``re_split_property_type = "mixed"`` and
    ``re_split_property_value = rre_v + cre_v``.

    ``re_split_mode`` is regime-gated:
    - **B3.1**: ``"whole"`` for the Art. 124H(3) pure-CRE non-NP/SME
      corporate path (existing behaviour preserved); ``"split"`` for
      NP/SME or any RRE-eligible row.
    - **CRR**: ``"split"`` whenever any component is eligible (Art. 125
      RRE / Art. 126 CRE).
    """
    is_candidate = gates["is_candidate"]
    is_mixed = eligibility["is_mixed"]
    is_residential_dominant = primitives["is_residential_dominant"]
    rre_eligible = eligibility["rre_eligible"]
    cre_eligible = eligibility["cre_eligible"]

    if config.is_basel_3_1:
        cre_only_whole = (~rre_eligible) & cre_eligible & (~gates["is_npsme"])
        mode_expr = (
            pl.when(~is_candidate)
            .then(pl.lit(None, dtype=pl.String))
            .when(cre_only_whole)
            .then(pl.lit("whole"))  # B3.1 CRE Art. 124H(3) pure-CRE non-NP/SME
            .when(rre_eligible | cre_eligible)
            .then(pl.lit("split"))
            .otherwise(pl.lit(None, dtype=pl.String))
        )
    else:
        mode_expr = (
            pl.when(~is_candidate)
            .then(pl.lit(None, dtype=pl.String))
            .when(rre_eligible | cre_eligible)
            .then(pl.lit("split"))  # CRR Art. 125 / Art. 126 (per-component)
            .otherwise(pl.lit(None, dtype=pl.String))
        )

    target_class_expr = (
        pl.when(~is_candidate)
        .then(pl.lit(None, dtype=pl.String))
        .when(is_mixed)
        .then(pl.lit(None, dtype=pl.String))
        .when(is_residential_dominant)
        .then(pl.lit(_SECURED_TARGET_RESIDENTIAL))
        .otherwise(pl.lit(_SECURED_TARGET_COMMERCIAL))
    )

    property_type_expr = (
        pl.when(~is_candidate)
        .then(pl.lit(None, dtype=pl.String))
        .when(is_mixed)
        .then(pl.lit("mixed"))
        .when(is_residential_dominant)
        .then(pl.lit("residential"))
        .otherwise(pl.lit("commercial"))
    )

    property_value_expr = (
        pl.when(is_mixed)
        .then(primitives["residential_value"] + primitives["commercial_value"])
        .when(is_residential_dominant)
        .then(primitives["residential_value"])
        .otherwise(primitives["commercial_value"])
    )

    return {
        "re_split_target_class": target_class_expr,
        "re_split_mode": mode_expr,
        "re_split_property_type": property_type_expr,
        "re_split_property_value": property_value_expr,
    }


def _re_split_per_component_values(
    primitives: dict[str, pl.Expr],
    eligibility: dict[str, pl.Expr],
) -> dict[str, pl.Expr]:
    """Build per-component property value expressions.

    Always emitted so the splitter can rely on their presence;
    ineligible components carry zero so allocation expressions
    naturally short-circuit.
    """
    return {
        "re_split_residential_value": (
            pl.when(eligibility["rre_eligible"])
            .then(primitives["residential_value"])
            .otherwise(pl.lit(0.0))
        ),
        "re_split_commercial_value": (
            pl.when(eligibility["cre_eligible"])
            .then(primitives["commercial_value"])
            .otherwise(pl.lit(0.0))
        ),
    }
