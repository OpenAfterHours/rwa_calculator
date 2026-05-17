"""
Credit Risk Mitigation (CRM) processor for RWA calculator.

Pipeline position:
    Classifier -> CRMProcessor -> SA/IRB/Slotting Calculators

Orchestrates all CRM techniques:
- Provision deduction (CRR Art. 110-111)
- CCF for off-balance sheet items (CRR Art. 111)
- Collateral haircuts and allocation (CRR Art. 223-224, 230)
- Guarantee substitution (CRR Art. 213-217)
- Cross-approach CCF (CRR Art. 111 / COREP C07)

Classes:
    CRMProcessor: Main processor implementing CRMProcessorProtocol

Usage:
    from rwa_calc.engine.crm.processor import CRMProcessor

    processor = CRMProcessor()
    adjusted = processor.apply_crm(classified_data, config)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
)
from rwa_calc.contracts.errors import (
    ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED,
    ERROR_INELIGIBLE_COLLATERAL,
    ERROR_INVALID_GUARANTEE,
    LazyFrameResult,
    crm_warning,
)
from rwa_calc.domain.enums import ApproachType, CRMCollateralMethod
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.engine.crm import collateral as collateral_mod
from rwa_calc.engine.crm import guarantees as guarantees_mod
from rwa_calc.engine.crm import provisions as provisions_mod
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.life_insurance import compute_life_insurance_columns
from rwa_calc.engine.crm.look_through import apply_funded_only_look_through
from rwa_calc.engine.crm.simple_method import compute_fcsm_columns, undo_sa_ead_reduction
from rwa_calc.engine.materialise import materialise_barrier
from rwa_calc.engine.utils import has_required_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)

# Regulatory citation string (not a regulatory scalar — citation only).
_CRR_ART_213_217 = "CRR Art. 213-217"


def _optional_bool_col(
    col_name: str,
    alias: str,
    available: bool,
    *,
    aggregate: str | None = None,
) -> pl.Expr:
    """
    Build a Boolean column expression that falls back to literal False if absent.

    When ``aggregate`` is ``"max"`` (used in group_by aggregations to flag a group
    if any row carries the bit), apply the aggregation; otherwise return the
    raw fill_null(False) expression.
    """
    if not available:
        return pl.lit(False).alias(alias)
    base = pl.col(col_name).fill_null(False)
    if aggregate == "max":
        base = base.max()
    return base.alias(alias)


def _build_direct_lookup(
    exposures: pl.LazyFrame,
    exposure_ccy_col: str,
    *,
    has_floor_col: bool,
    has_sft_col: bool,
) -> pl.LazyFrame:
    """Build the direct (per-exposure) lookup frame."""
    direct_cols = [
        pl.col("exposure_reference").alias("_ben_ref_direct"),
        pl.col("ead_for_crm").alias("_ead_direct"),
        pl.col(exposure_ccy_col).alias("_currency_direct"),
        pl.col("maturity_date").alias("_maturity_direct"),
        _optional_bool_col("has_one_day_maturity_floor", "_floor_direct", has_floor_col),
        _optional_bool_col("is_sft", "_sft_direct", has_sft_col),
    ]
    return exposures.select(direct_cols)


def _build_facility_lookup(
    exposures: pl.LazyFrame,
    exposure_ccy_col: str,
    pool_expr: pl.Expr,
    *,
    has_parent_col: bool,
    has_floor_col: bool,
    has_sft_col: bool,
) -> pl.LazyFrame:
    """Build the facility (parent_facility_reference) aggregated lookup frame."""
    if not has_parent_col:
        return pl.LazyFrame(
            schema={
                "_ben_ref_facility": pl.String,
                "_ead_facility": pl.Float64,
                "_ead_facility_airb": pl.Float64,
                "_ead_facility_non_airb": pl.Float64,
                "_currency_facility": pl.String,
                "_maturity_facility": pl.Date,
                "_floor_facility": pl.Boolean,
                "_sft_facility": pl.Boolean,
            }
        )
    facility_agg = [
        pl.col("ead_for_crm").sum().alias("_ead_facility"),
        pl.col("ead_for_crm").filter(pool_expr).sum().alias("_ead_facility_airb"),
        pl.col("ead_for_crm").filter(~pool_expr).sum().alias("_ead_facility_non_airb"),
        pl.col(exposure_ccy_col).first().alias("_currency_facility"),
        pl.col("maturity_date").first().alias("_maturity_facility"),
        # Conservative: if ANY exposure in facility has flag, flag whole facility
        _optional_bool_col(
            "has_one_day_maturity_floor", "_floor_facility", has_floor_col, aggregate="max"
        ),
        _optional_bool_col("is_sft", "_sft_facility", has_sft_col, aggregate="max"),
    ]
    return (
        exposures.filter(pl.col("parent_facility_reference").is_not_null())
        .group_by("parent_facility_reference")
        .agg(facility_agg)
        .with_columns(
            pl.col("parent_facility_reference").cast(pl.String),
        )
        .rename({"parent_facility_reference": "_ben_ref_facility"})
    )


def _build_cp_lookup(
    exposures: pl.LazyFrame,
    exposure_ccy_col: str,
    pool_expr: pl.Expr,
    *,
    has_floor_col: bool,
    has_sft_col: bool,
) -> pl.LazyFrame:
    """Build the counterparty-aggregated lookup frame."""
    cp_agg = [
        pl.col("ead_for_crm").sum().alias("_ead_cp"),
        pl.col("ead_for_crm").filter(pool_expr).sum().alias("_ead_cp_airb"),
        pl.col("ead_for_crm").filter(~pool_expr).sum().alias("_ead_cp_non_airb"),
        pl.col(exposure_ccy_col).first().alias("_currency_cp"),
        pl.col("maturity_date").first().alias("_maturity_cp"),
        # Conservative: if ANY exposure for counterparty has flag, flag whole group
        _optional_bool_col(
            "has_one_day_maturity_floor", "_floor_cp", has_floor_col, aggregate="max"
        ),
        _optional_bool_col("is_sft", "_sft_cp", has_sft_col, aggregate="max"),
    ]
    return (
        exposures.group_by("counterparty_reference")
        .agg(cp_agg)
        .rename({"counterparty_reference": "_ben_ref_cp"})
    )


def _build_exposure_lookups(
    exposures: pl.LazyFrame,
) -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
    """
    Pre-compute exposure lookups for collateral processing.

    Builds three lookup LazyFrames (direct, facility, counterparty) with all
    columns needed by _join_collateral_to_lookups and the multi-level allocation
    methods. Computing these once avoids duplicate references to the upstream
    exposures plan.

    Pool-aware EAD aggregates are also computed at facility and counterparty
    level: ``_ead_facility_airb`` / ``_ead_facility_non_airb`` and the cp
    equivalents. These are used by ``_apply_collateral_unified`` to pro-rata
    collateral within the appropriate pool, preventing double-counting against
    AIRB exposures whose modelled LGD already reflects collateral effects
    (CRR Art. 181, CRE36, Basel 3.1 Art. 169A). The caller must add the
    ``_is_airb_pool`` column to ``exposures`` before invoking this function;
    when the column is absent it is treated as all-False (legacy behaviour).

    Returns:
        (direct_lookup, facility_lookup, cp_lookup) where each has a _ben_ref_*
        key column plus _ead_*, _currency_*, and _maturity_* value columns.
        Facility and counterparty lookups additionally carry pool-aware EAD
        aggregates.
    """
    exp_schema = exposures.collect_schema()
    schema_names = exp_schema.names()

    # Determine whether optional columns are available
    has_floor_col = "has_one_day_maturity_floor" in schema_names
    has_sft_col = "is_sft" in schema_names
    has_pool_col = "_is_airb_pool" in schema_names
    has_parent_col = "parent_facility_reference" in schema_names
    pool_expr = pl.col("_is_airb_pool").fill_null(False) if has_pool_col else pl.lit(False)

    # Graceful fallback for direct unit-test callers that hand-build the
    # exposures frame without going through _initialize_ead.  Production
    # always supplies ead_for_crm; test fixtures with pure on-BS rows can
    # fall back to ead_gross with no semantic change.
    if "ead_for_crm" not in schema_names:  # arch-exempt: test-fallback default
        exposures = exposures.with_columns(pl.col("ead_gross").alias("ead_for_crm"))

    # Use pre-FX-conversion currency for downstream Art. 224 H_fx mismatch check.
    # After FX conversion the `currency` column holds the reporting currency, so a
    # raw `currency` join would silently zero the collateral FX haircut (P1.135).
    exposure_ccy_col = "original_currency" if "original_currency" in schema_names else "currency"

    # Direct: one row per exposure.  CRR Art. 223(4) / PS1/26 Art. 223(4):
    # off-BS items must be valued at 100% of nominal for CRM purposes, so
    # all pro-rata bases use ead_for_crm rather than the post-CCF ead_gross.
    direct_lookup = _build_direct_lookup(
        exposures, exposure_ccy_col, has_floor_col=has_floor_col, has_sft_col=has_sft_col
    )
    facility_lookup = _build_facility_lookup(
        exposures,
        exposure_ccy_col,
        pool_expr,
        has_parent_col=has_parent_col,
        has_floor_col=has_floor_col,
        has_sft_col=has_sft_col,
    )
    cp_lookup = _build_cp_lookup(
        exposures,
        exposure_ccy_col,
        pool_expr,
        has_floor_col=has_floor_col,
        has_sft_col=has_sft_col,
    )

    return direct_lookup, facility_lookup, cp_lookup


def _join_collateral_to_lookups(
    collateral: pl.LazyFrame,
    direct_lookup: pl.LazyFrame,
    facility_lookup: pl.LazyFrame,
    cp_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Join all lookup columns (EAD, currency, maturity) onto collateral in one pass.

    Replaces the separate _resolve_pledge_percentages and join_exposure_currency
    join passes — each used 3 left joins, so 6 total. Now we do 3 joins total,
    halving the plan size from lookup subtree duplication.

    When beneficiary_type is absent, falls back to a single direct join.
    """
    from rwa_calc.data.schemas import DIRECT_BENEFICIARY_TYPES

    coll_schema = collateral.collect_schema()

    if "beneficiary_type" not in coll_schema.names():  # arch-exempt: early-exit guard
        # Direct-only join — single pass with all columns
        return collateral.join(
            direct_lookup.select(
                pl.col("_ben_ref_direct"),
                pl.col("_ead_direct").alias("_beneficiary_ead"),
                pl.col("_currency_direct").alias("exposure_currency"),
                pl.col("_maturity_direct").alias("exposure_maturity"),
                pl.col("_floor_direct").alias("exposure_has_one_day_maturity_floor"),
                pl.col("_sft_direct").alias("exposure_is_sft"),
            ),
            left_on="beneficiary_reference",
            right_on="_ben_ref_direct",
            how="left",
        )

    bt_lower = pl.col("beneficiary_type").str.to_lowercase()

    # 3 left joins — each adds level-specific EAD, currency, maturity columns
    collateral = (
        collateral.join(
            direct_lookup,
            left_on="beneficiary_reference",
            right_on="_ben_ref_direct",
            how="left",
        )
        .join(
            facility_lookup,
            left_on="beneficiary_reference",
            right_on="_ben_ref_facility",
            how="left",
        )
        .join(
            cp_lookup,
            left_on="beneficiary_reference",
            right_on="_ben_ref_cp",
            how="left",
        )
    )

    # Select correct EAD, currency, maturity based on beneficiary_type
    collateral = collateral.with_columns(
        [
            pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
            .then(pl.col("_ead_direct"))
            .when(bt_lower == "facility")
            .then(pl.col("_ead_facility"))
            .when(bt_lower == "counterparty")
            .then(pl.col("_ead_cp"))
            .otherwise(pl.lit(0.0))
            .alias("_beneficiary_ead"),
            pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
            .then(pl.col("_currency_direct"))
            .when(bt_lower == "facility")
            .then(pl.col("_currency_facility"))
            .when(bt_lower == "counterparty")
            .then(pl.col("_currency_cp"))
            .otherwise(pl.lit(None).cast(pl.String))
            .alias("exposure_currency"),
            pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
            .then(pl.col("_maturity_direct"))
            .when(bt_lower == "facility")
            .then(pl.col("_maturity_facility"))
            .when(bt_lower == "counterparty")
            .then(pl.col("_maturity_cp"))
            .otherwise(pl.lit(None).cast(pl.Date))
            .alias("exposure_maturity"),
            # Art. 162(3) 1-day maturity floor flag — for Art. 237(2) ineligibility
            pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
            .then(pl.col("_floor_direct"))
            .when(bt_lower == "facility")
            .then(pl.col("_floor_facility"))
            .when(bt_lower == "counterparty")
            .then(pl.col("_floor_cp"))
            .otherwise(pl.lit(False))
            .alias("exposure_has_one_day_maturity_floor"),
            # Art. 224(2)(c) SFT flag — drives 5-day FX/collateral haircut default
            # (P1.186). Resolved direct -> facility -> cp; defaults False.
            pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
            .then(pl.col("_sft_direct"))
            .when(bt_lower == "facility")
            .then(pl.col("_sft_facility"))
            .when(bt_lower == "counterparty")
            .then(pl.col("_sft_cp"))
            .otherwise(pl.lit(False))
            .alias("exposure_is_sft"),
        ]
    ).drop(
        [
            "_ead_direct",
            "_ead_facility",
            "_ead_facility_airb",
            "_ead_facility_non_airb",
            "_ead_cp",
            "_ead_cp_airb",
            "_ead_cp_non_airb",
            "_currency_direct",
            "_currency_facility",
            "_currency_cp",
            "_maturity_direct",
            "_maturity_facility",
            "_maturity_cp",
            "_floor_direct",
            "_floor_facility",
            "_floor_cp",
            "_sft_direct",
            "_sft_facility",
            "_sft_cp",
        ]
    )

    return collateral


def _resolve_pledge_from_joined(collateral: pl.LazyFrame) -> pl.LazyFrame:
    """
    Resolve pledge_percentage to market_value using pre-joined _beneficiary_ead.

    Assumes _beneficiary_ead column already exists on collateral (from
    _join_collateral_to_lookups). market_value takes precedence when non-null
    and non-zero.
    """
    coll_schema = collateral.collect_schema()
    if "pledge_percentage" not in coll_schema.names():  # arch-exempt: early-exit guard
        return collateral.drop("_beneficiary_ead")

    needs_resolve = (
        (
            pl.col("market_value").is_null()
            | (pl.col("market_value").cast(pl.Float64, strict=False).abs() < 1e-10)
        )
        & pl.col("pledge_percentage").is_not_null()
        & (pl.col("pledge_percentage") > 0.0)
    )

    collateral = collateral.with_columns(
        pl.col("_beneficiary_ead").fill_null(0.0),
    )

    collateral = collateral.with_columns(
        pl.when(needs_resolve)
        .then(pl.col("pledge_percentage") * pl.col("_beneficiary_ead"))
        .otherwise(pl.col("market_value"))
        .alias("market_value"),
    )

    return collateral.drop("_beneficiary_ead")


def _join_netting_amounts(
    exposures: pl.LazyFrame, netting_collateral: pl.LazyFrame
) -> pl.LazyFrame:
    """
    Join per-exposure on-BS netting amounts from synthetic netting collateral.

    The netting collateral has one row per beneficiary exposure with market_value
    equal to the pro-rata netting pool allocation. Sum by beneficiary_reference
    (an exposure may match multiple pools) and join back as on_bs_netting_amount.
    """
    netting_by_exposure = netting_collateral.group_by("beneficiary_reference").agg(
        pl.col("market_value").sum().alias("on_bs_netting_amount"),
    )
    exposures = exposures.join(
        netting_by_exposure,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    ).with_columns(
        pl.col("on_bs_netting_amount").fill_null(0.0),
    )
    return exposures


class CRMProcessor:
    """
    Apply credit risk mitigation to exposures.

    Implements CRMProcessorProtocol for:
    - CCF application for off-balance sheet items (CRR Art. 111)
    - Collateral haircuts and allocation (CRR Art. 223-224)
    - Guarantee substitution (CRR Art. 213-215)
    - Provision deduction (CRR Art. 110)

    The CRM process follows this order:
    1. Apply CCF to calculate base EAD for contingents
    2. Apply collateral (reduce EAD for SA, reduce LGD for IRB)
    3. Apply guarantees (substitution approach)
    4. Deduct provisions from EAD
    """

    # Required columns for each CRM data type
    COLLATERAL_REQUIRED_COLUMNS = {"beneficiary_reference", "market_value"}
    GUARANTEE_REQUIRED_COLUMNS = {"beneficiary_reference", "amount_covered", "guarantor"}
    PROVISION_REQUIRED_COLUMNS = {"beneficiary_reference", "amount"}

    def __init__(self, is_basel_3_1: bool = False) -> None:
        """Initialize CRM processor with sub-calculators.

        Args:
            is_basel_3_1: True for Basel 3.1 framework (affects haircuts and supervisory LGD)
        """
        self._ccf_calculator = CCFCalculator()
        self._haircut_calculator = HaircutCalculator(is_basel_3_1=is_basel_3_1)
        self._is_basel_3_1 = is_basel_3_1

    @cites("CRR Art. 194")
    def apply_crm(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Apply credit risk mitigation to exposures.

        Args:
            data: Classified exposures from classifier
            config: Calculation configuration

        Returns:
            LazyFrameResult with CRM-adjusted exposures and any errors
        """
        bundle = self.get_crm_adjusted_bundle(data, config)

        return LazyFrameResult(
            frame=bundle.exposures,
            errors=bundle.crm_errors,
        )

    def get_crm_adjusted_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM and return as a bundle.

        Args:
            data: Classified exposures from classifier
            config: Calculation configuration

        Returns:
            CRMAdjustedBundle with adjusted exposures
        """
        errors: list[CalculationError] = []

        # Step 0: PRA Art. 191A(2)(e)(i) two-layer protection look-through.
        # Re-anchors collateral pledged against a guarantee onto the obligor
        # exposure when the bank elects "funded_only" — and suppresses the
        # guarantee row so RWSM substitution does not also apply.  Runs
        # before any other CRM step so the rewritten collateral / guarantee
        # frames feed the rest of the pipeline normally.
        guarantees_lf, collateral_lf, look_through_errors = apply_funded_only_look_through(
            data.guarantees, data.collateral
        )
        errors.extend(look_through_errors)

        # Steps 1-3: provisions -> CCF -> init EAD -> materialise barrier
        exposures = self._run_ead_pipeline(data, config, "crm_post_ead_fanout")

        # Step 3.5: Generate synthetic collateral from netting (CRR Art. 195)
        exposures, collateral = self._merge_netting_collateral(exposures, collateral_lf)

        # Step 3.6: Pre-compute FCSM columns if Simple Method is elected
        # Must run BEFORE Comprehensive Method (which is still needed for IRB LGD)
        use_simple_method = config.crm_collateral_method == CRMCollateralMethod.SIMPLE
        if use_simple_method and has_required_columns(collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            exposures = compute_fcsm_columns(exposures, collateral, config)

        # Step 4: Apply collateral (if available and valid)
        # Under Simple Method, the Comprehensive pipeline still runs for IRB LGD
        # adjustment. SA EAD reduction is undone in Step 4b.
        exposures, collateral_applied = self._apply_collateral_step(
            exposures, collateral, config, errors, use_simple_method=use_simple_method
        )

        # Step 4b: Under Simple Method, undo SA financial collateral EAD reduction.
        # The Comprehensive pipeline reduced SA EAD by collateral_adjusted_value,
        # but Art. 222 does not reduce EAD — it substitutes risk weights instead.
        if use_simple_method:
            exposures = undo_sa_ead_reduction(exposures)

        # Step 4c: Pre-compute life insurance method columns (Art. 232).
        exposures = self._apply_life_insurance_step(exposures, collateral, config)

        # Step 5: Apply guarantees (if available and valid)
        exposures = self._apply_guarantees_step(exposures, guarantees_lf, data, config, errors)

        # Step 6: Calculate final EAD after all CRM adjustments
        # Provisions already baked into ead_pre_crm — no double deduction
        exposures = self._finalize_ead(exposures)

        # Step 7: Add CRM audit trail
        exposures = self._add_crm_audit(exposures)

        # Materialise CRM results before the approach split fan-out.
        # The pipeline runs independent .collect() calls on each branch
        # (SA, IRB, slotting) via has_rows() and individual calculators.
        # Without this collect, the full pipeline plan is re-evaluated per
        # branch and the plan depth causes Polars optimizer segfaults.
        # In streaming mode, spills to disk instead of loading into memory.
        exposures = materialise_barrier(exposures, config, "crm_post_audit_fanout")

        # Split by approach for output
        sa_exposures = exposures.filter(pl.col("approach") == ApproachType.SA.value)
        irb_exposures = exposures.filter(
            (pl.col("approach") == ApproachType.FIRB.value)
            | (pl.col("approach") == ApproachType.AIRB.value)
        )
        slotting_exposures = exposures.filter(pl.col("approach") == ApproachType.SLOTTING.value)

        return CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=sa_exposures,
            irb_exposures=irb_exposures,
            slotting_exposures=slotting_exposures,
            equity_exposures=data.equity_exposures,  # Pass through equity (no CRM)
            ciu_holdings=data.ciu_holdings,
            crm_audit=self._build_crm_audit(exposures),
            collateral_allocation=(
                self._build_collateral_allocation(exposures) if collateral_applied else None
            ),
            crm_errors=errors,
        )

    def get_crm_unified_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM without fan-out split. No mid-pipeline collect.

        Same CRM processing as get_crm_adjusted_bundle() but skips the
        collect().lazy() materialisation barrier and approach split. Returns
        the unified LazyFrame for single-pass calculator processing.

        Args:
            data: Classified exposures from classifier
            config: Calculation configuration

        Returns:
            CRMAdjustedBundle with unified exposures (split fields empty)
        """
        errors: list[CalculationError] = []

        # Step 0: PRA Art. 191A(2)(e)(i) two-layer protection look-through.
        # Mirrors get_crm_adjusted_bundle so the unified path honours the
        # funded-only election before any other CRM step runs.
        guarantees_lf, collateral_lf, look_through_errors = apply_funded_only_look_through(
            data.guarantees, data.collateral
        )
        errors.extend(look_through_errors)

        # Steps 1-3: provisions -> CCF -> init EAD -> materialise barrier
        exposures = self._run_ead_pipeline(data, config, "crm_post_ead_unified")

        # Generate synthetic collateral from netting (CRR Art. 195)
        exposures, collateral = self._merge_netting_collateral(exposures, collateral_lf)

        # Step 4: Apply collateral (unified path — no misdirected-AIRB diagnostic)
        exposures, collateral_applied = self._apply_collateral_unified_step(
            exposures, collateral, config, errors
        )

        # Pre-compute life insurance method columns (Art. 232) for SA RW mapping
        exposures = self._apply_life_insurance_step(exposures, collateral, config)

        # Materialise after collateral before guarantee processing.
        # Collateral adds 3 lookup joins + haircuts + unified allocation;
        # without this collect, the guarantee module's 3-path concat
        # (no-guarantee / single / multi-guarantor split) re-evaluates the
        # full collateral plan per branch, causing ~4x slowdown at 100K scale.
        if (
            has_required_columns(guarantees_lf, self.GUARANTEE_REQUIRED_COLUMNS)
            and data.counterparty_lookup is not None
        ):
            exposures = materialise_barrier(exposures, config, "crm_pre_guarantee_unified")
            exposures = self._apply_guarantees_step(exposures, guarantees_lf, data, config, errors)
        else:
            self._collect_guarantee_skip_errors(guarantees_lf, data, errors)
            exposures = materialise_barrier(exposures, config, "crm_no_guarantee")

        exposures = self._finalize_ead(exposures)
        exposures = self._add_crm_audit(exposures)

        return CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=pl.LazyFrame(),
            irb_exposures=pl.LazyFrame(),
            slotting_exposures=None,
            equity_exposures=data.equity_exposures,
            ciu_holdings=data.ciu_holdings,
            crm_audit=None,  # Audit computed at collect time if needed
            collateral_allocation=(
                self._build_collateral_allocation(exposures) if collateral_applied else None
            ),
            crm_errors=errors,
        )

    # --- Internal step helpers ---

    def _run_ead_pipeline(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
        barrier_label: str,
    ) -> pl.LazyFrame:
        """Run provisions -> CCF -> init_ead and apply the materialise barrier."""
        exposures = data.all_exposures
        # Step 1: Resolve provisions BEFORE CCF (CRR Art. 111(2))
        # This adds provision_on_drawn, provision_on_nominal, nominal_after_provision
        # so CCF can use the provision-adjusted nominal amount
        if has_required_columns(data.provisions, self.PROVISION_REQUIRED_COLUMNS):
            exposures = self.resolve_provisions(exposures, data.provisions, config)
        # Step 2: Apply CCF to calculate EAD for contingents
        # Uses nominal_after_provision when available
        exposures = self._apply_ccf(exposures, config)
        # Step 3: Initialize EAD columns
        exposures = self._initialize_ead(exposures)
        # Materialise the deep lazy plan once.  Without this, downstream join
        # collects each re-execute the full upstream plan, and the plan depth
        # causes Polars optimizer segfaults.  In streaming mode, spills to disk.
        return materialise_barrier(exposures, config, barrier_label)

    def _merge_netting_collateral(
        self,
        exposures: pl.LazyFrame,
        collateral_lf: pl.LazyFrame | None,
    ) -> tuple[pl.LazyFrame, pl.LazyFrame | None]:
        """Generate synthetic netting collateral and merge with input collateral.

        Returns the (possibly joined) exposures frame and the merged collateral.
        """
        netting_collateral = collateral_mod.generate_netting_collateral(exposures)
        collateral: pl.LazyFrame | None = collateral_lf
        if netting_collateral is None:
            exposures = exposures.with_columns(pl.lit(0.0).alias("on_bs_netting_amount"))
            return exposures, collateral
        # Track per-exposure netting amount for COREP col 0035
        exposures = _join_netting_amounts(exposures, netting_collateral)
        if collateral is not None and has_required_columns(
            collateral, self.COLLATERAL_REQUIRED_COLUMNS
        ):
            collateral = pl.concat([collateral, netting_collateral], how="diagonal")
        else:
            collateral = netting_collateral
        return exposures, collateral

    def _apply_collateral_step(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
        config: CalculationConfig,
        errors: list[CalculationError],
        *,
        use_simple_method: bool,
    ) -> tuple[pl.LazyFrame, bool]:
        """Apply collateral with misdirected-AIRB diagnostics (fan-out path)."""
        if has_required_columns(collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            assert collateral is not None  # narrowed by has_required_columns
            self._record_misdirected_airb_errors(exposures, collateral, config, errors)
            exposures = self.apply_collateral(exposures, collateral, config)
            return exposures, True
        # No (valid) collateral path
        self._record_missing_collateral_columns(collateral, errors)
        # No collateral: still need to set F-IRB supervisory LGD based on seniority.
        # Under B31, AIRB Foundation/169B exposures also get formula-based LGD.
        exposures = collateral_mod.apply_firb_supervisory_lgd_no_collateral(
            exposures, self._is_basel_3_1, config=config
        )
        if use_simple_method:
            # Add default (zero) FCSM columns when no collateral
            from rwa_calc.engine.crm.simple_method import _add_default_fcsm_columns

            exposures = _add_default_fcsm_columns(exposures)
        return exposures, False

    def _apply_collateral_unified_step(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
        config: CalculationConfig,
        errors: list[CalculationError],
    ) -> tuple[pl.LazyFrame, bool]:
        """Apply collateral (unified path — no misdirected diagnostics)."""
        if has_required_columns(collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            assert collateral is not None
            exposures = self.apply_collateral(exposures, collateral, config)
            return exposures, True
        self._record_missing_collateral_columns(collateral, errors)
        exposures = collateral_mod.apply_firb_supervisory_lgd_no_collateral(
            exposures, self._is_basel_3_1, config=config
        )
        return exposures, False

    def _record_misdirected_airb_errors(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
        errors: list[CalculationError],
    ) -> None:
        """Append warnings for AIRB-model-collateral pledged to non-AIRB exposures."""
        misdirected = collateral_mod.find_misdirected_airb_model_collateral(
            exposures, collateral, config, self._is_basel_3_1
        )
        for coll_ref, exp_ref in misdirected:
            errors.append(
                crm_warning(
                    ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED,
                    f"Collateral '{coll_ref}' is flagged as is_airb_model_collateral "
                    f"but is pledged directly to non-AIRB exposure '{exp_ref}'. "
                    "The flag asserts the collateral is incorporated in the firm's "
                    "internal LGD model; pledging it to a non-AIRB exposure has no "
                    "LGD effect and is treated as zero allocation.",
                    exposure_reference=exp_ref,
                    regulatory_reference="CRR Art. 181 / Basel 3.1 Art. 169A",
                )
            )

    def _record_missing_collateral_columns(
        self,
        collateral: pl.LazyFrame | None,
        errors: list[CalculationError],
    ) -> None:
        """Append a warning when collateral data is present but lacks required columns."""
        if collateral is None:
            return
        errors.append(
            crm_warning(
                ERROR_INELIGIBLE_COLLATERAL,
                "Collateral data provided but missing required columns "
                f"{self.COLLATERAL_REQUIRED_COLUMNS}; collateral CRM skipped",
                regulatory_reference="CRR Art. 223-224",
            )
        )

    def _apply_life_insurance_step(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Pre-compute life insurance method columns (Art. 232).

        Life insurance uses mapped risk weight for SA (not EAD reduction).
        IRB LGD handled via the waterfall (LGDS = 40%).  SA EAD is not reduced
        because life_insurance has is_eligible_financial_collateral=False —
        the Comprehensive Method's eligible-only filter already excludes it.
        """
        if has_required_columns(collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            assert collateral is not None
            return compute_life_insurance_columns(exposures, collateral, config)
        from rwa_calc.engine.crm.life_insurance import _add_default_life_ins_columns

        return _add_default_life_ins_columns(exposures)

    def _apply_guarantees_step(
        self,
        exposures: pl.LazyFrame,
        guarantees_lf: pl.LazyFrame | None,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
        errors: list[CalculationError],
    ) -> pl.LazyFrame:
        """Apply guarantees or record skip warnings if not applicable."""
        if (
            has_required_columns(guarantees_lf, self.GUARANTEE_REQUIRED_COLUMNS)
            and data.counterparty_lookup is not None
        ):
            assert guarantees_lf is not None
            # Materialise guarantee lookup tables to prevent parquet re-scans.
            guarantees_df, cp_lookup_df, ri_df = pl.collect_all(
                [
                    guarantees_lf,
                    data.counterparty_lookup.counterparties,
                    data.counterparty_lookup.rating_inheritance,
                ]
            )
            return self.apply_guarantees(
                exposures,
                guarantees_df.lazy(),
                cp_lookup_df.lazy(),
                config,
                ri_df.lazy(),
            )
        self._collect_guarantee_skip_errors(guarantees_lf, data, errors)
        return exposures

    def _collect_guarantee_skip_errors(
        self,
        guarantees_lf: pl.LazyFrame | None,
        data: ClassifiedExposuresBundle,
        errors: list[CalculationError],
    ) -> None:
        """Append warnings when guarantee processing is skipped."""
        if guarantees_lf is None:
            return
        if not has_required_columns(guarantees_lf, self.GUARANTEE_REQUIRED_COLUMNS):
            errors.append(
                crm_warning(
                    ERROR_INVALID_GUARANTEE,
                    "Guarantee data provided but missing required columns "
                    f"{self.GUARANTEE_REQUIRED_COLUMNS}; guarantee CRM skipped",
                    regulatory_reference=_CRR_ART_213_217,
                )
            )
        elif data.counterparty_lookup is None:
            errors.append(
                crm_warning(
                    ERROR_INVALID_GUARANTEE,
                    "Guarantee data provided but counterparty lookup is missing; "
                    "guarantee CRM skipped",
                    regulatory_reference=_CRR_ART_213_217,
                )
            )

    # --- Thin delegation methods ---

    def resolve_provisions(
        self,
        exposures: pl.LazyFrame,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Resolve provisions with multi-level beneficiary and drawn-first deduction."""
        return provisions_mod.resolve_provisions(exposures, provisions, config)

    def _apply_firb_supervisory_lgd_no_collateral(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig | None = None,
    ) -> pl.LazyFrame:
        """Apply F-IRB supervisory LGD when no collateral is available."""
        return collateral_mod.apply_firb_supervisory_lgd_no_collateral(
            exposures, self._is_basel_3_1, config=config
        )

    def _generate_netting_collateral(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame | None:
        """Generate synthetic cash collateral from netting-eligible loans."""
        return collateral_mod.generate_netting_collateral(exposures)

    def apply_collateral(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply collateral to reduce EAD (SA) or LGD (IRB)."""
        return collateral_mod.apply_collateral(
            exposures,
            collateral,
            config,
            haircut_calculator=self._haircut_calculator,
            is_basel_3_1=self._is_basel_3_1,
            build_exposure_lookups_fn=_build_exposure_lookups,
            join_collateral_to_lookups_fn=_join_collateral_to_lookups,
            resolve_pledge_from_joined_fn=_resolve_pledge_from_joined,
        )

    def apply_guarantees(
        self,
        exposures: pl.LazyFrame,
        guarantees: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        config: CalculationConfig,
        rating_inheritance: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """Apply guarantee substitution."""
        return guarantees_mod.apply_guarantees(
            exposures,
            guarantees,
            counterparty_lookup,
            config,
            rating_inheritance,
        )

    # --- Internal methods ---

    def _apply_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply CCF to off-balance sheet exposures."""
        return self._ccf_calculator.apply_ccf(exposures, config)

    def _initialize_ead(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Initialize EAD columns and preserve pre-CRM attributes.

        Sets up the EAD waterfall:
        - ead_gross: drawn + CCF-adjusted undrawn
        - ead_after_collateral: EAD after collateral
        - ead_after_guarantee: EAD after guarantee substitution
        - ead_after_provision: Final EAD after provision deduction

        Also captures pre-CRM state for regulatory reporting:
        - pre_crm_counterparty_reference: Original borrower reference
        - pre_crm_exposure_class: Original exposure class before substitution
        """
        schema = exposures.collect_schema()
        has_provision_cols = "provision_allocated" in schema.names()

        # Provision columns: preserve if already set by resolve_provisions,
        # otherwise initialize to zero
        if has_provision_cols:
            provision_cols = [
                pl.col("provision_allocated"),
                pl.col("provision_deducted"),
            ]
        else:
            provision_cols = [
                pl.lit(0.0).alias("provision_allocated"),
                pl.lit(0.0).alias("provision_deducted"),
            ]

        # Art. 159(1) Pool B additional components: AVAs (Art. 34) and other
        # own funds reductions.  Preserve if already on the frame; default 0.0.
        col_names = schema.names()
        pool_b_cols = [
            (
                pl.col("ava_amount").fill_null(0.0)
                if "ava_amount" in col_names
                else pl.lit(0.0).alias("ava_amount")
            ),
            (
                pl.col("other_own_funds_reductions").fill_null(0.0)
                if "other_own_funds_reductions" in col_names
                else pl.lit(0.0).alias("other_own_funds_reductions")
            ),
        ]

        # Exposure value used for CRM (CRR Art. 223(4) / PS1/26 Art. 223(4)):
        # off-balance-sheet items enter CRM at 100% of nominal (CCF override).
        # ead_for_crm composes the on-BS portion with the unconverted nominal,
        # so any row computes correctly whether it's pure on-BS, pure off-BS,
        # or mixed.  effective_ccf re-couples the actual CCF in SA's
        # post-collateral EAD per Art. 228(1).
        ead_for_crm_expr = pl.col("on_bs_for_ead").fill_null(0.0) + pl.col(
            "nominal_after_provision"
        ).fill_null(0.0)
        effective_ccf_expr = (
            pl.when(ead_for_crm_expr > 0)
            .then(pl.col("ead_pre_crm") / ead_for_crm_expr)
            .otherwise(pl.lit(1.0))
        )

        return exposures.with_columns(
            [
                # Pre-CRM attributes for regulatory reporting
                pl.col("counterparty_reference").alias("pre_crm_counterparty_reference"),
                pl.col("exposure_class").alias("pre_crm_exposure_class"),
                # Gross EAD = drawn + CCF-adjusted contingent (post-CCF; actual EAD basis)
                pl.col("ead_pre_crm").alias("ead_gross"),
                # CRR Art. 223(4) / PS1/26 Art. 223(4) override: CCF=100% basis for CRM
                ead_for_crm_expr.alias("ead_for_crm"),
                effective_ccf_expr.alias("effective_ccf"),
                # Initialize subsequent EAD columns (will be adjusted by CRM)
                pl.col("ead_pre_crm").alias("ead_after_collateral"),
                pl.col("ead_pre_crm").alias("ead_after_guarantee"),
                pl.col("ead_pre_crm").alias("ead_final"),
                # Initialize collateral-related columns
                pl.lit(0.0).alias("collateral_allocated"),
                pl.lit(0.0).alias("collateral_adjusted_value"),
                # Initialize guarantee-related columns
                pl.lit(0.0).alias("guarantee_amount"),
                pl.lit(None).cast(pl.String).alias("guarantor_reference"),
                pl.lit(None).cast(pl.Float64).alias("substitute_rw"),
                # Provision-related columns
                *provision_cols,
                # Art. 159(1) Pool B additional components
                *pool_b_cols,
                # LGD for IRB (may be adjusted by collateral)
                pl.col("lgd").fill_null(0.45).alias("lgd_pre_crm"),
                pl.col("lgd").fill_null(0.45).alias("lgd_post_crm"),
                # Initialize guarantee tracking columns
                pl.lit(False).alias("is_guaranteed"),
                pl.lit(0.0).alias("guaranteed_portion"),
                pl.lit(0.0).alias("unguaranteed_portion"),
                # Initialize post-CRM columns (will be updated by apply_guarantees if called)
                pl.col("counterparty_reference").alias("post_crm_counterparty_guaranteed"),
                pl.col("exposure_class").alias("post_crm_exposure_class_guaranteed"),
                pl.lit("").alias("guarantor_exposure_class"),
                # Cross-approach CCF substitution columns
                pl.col("ccf").alias("ccf_original"),
                pl.col("ccf").alias("ccf_guaranteed"),
                pl.col("ccf").alias("ccf_unguaranteed"),
                pl.lit(0.0).alias("guarantee_ratio"),
                pl.lit("").alias("guarantor_approach"),
                pl.lit(None).cast(pl.String).alias("guarantor_rating_type"),
                # Unfunded protection type (guarantee vs credit_derivative)
                pl.lit(None).cast(pl.String).alias("protection_type"),
                # FX mismatch haircut on guarantees (Art. 233(3-4))
                pl.lit(0.0).alias("guarantee_fx_haircut"),
                # CDS restructuring exclusion haircut (Art. 233(2))
                pl.lit(0.0).alias("guarantee_restructuring_haircut"),
            ]
        )

    def _finalize_ead(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Finalize EAD after all CRM adjustments.

        Provisions are already baked into ead_pre_crm (deducted before CCF),
        so finalize_ead does NOT subtract provision_deducted again.

        Sets ead_final = ead_after_collateral floored at 0.
        """
        return exposures.with_columns(
            [
                pl.col("ead_after_collateral").clip(lower_bound=0).alias("ead_final"),
                pl.col("ead_after_collateral").alias("ead_after_guarantee"),
            ]
        )

    def _add_crm_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Add CRM processing audit trail."""
        return exposures.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("EAD: gross="),
                        pl.col("ead_gross").round(0).cast(pl.String),
                        pl.lit("; coll="),
                        pl.col("collateral_adjusted_value").round(0).cast(pl.String),
                        pl.lit("; guar="),
                        pl.col("guarantee_amount").round(0).cast(pl.String),
                        pl.lit("; prov="),
                        pl.col("provision_allocated").round(0).cast(pl.String),
                        pl.lit("; final="),
                        pl.col("ead_final").round(0).cast(pl.String),
                    ]
                ).alias("crm_calculation"),
            ]
        )

    def _build_collateral_allocation(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build per-exposure collateral allocation summary.

        Extracts allocation details produced by the Art. 231 sequential
        waterfall.  Each row shows how much EAD each collateral category
        absorbed and the resulting LGD impact for a single exposure.

        Only called when ``apply_collateral`` actually ran (i.e. valid
        collateral data was present).  When no collateral exists the
        bundle field remains ``None``.

        References:
            CRR Art. 230-231, PRA PS1/26 Art. 230-231
        """
        from rwa_calc.engine.crm.expressions import CRM_ALLOC_COLUMNS

        alloc_cols = list(CRM_ALLOC_COLUMNS.values())
        return exposures.select(
            [
                pl.col("exposure_reference"),
                pl.col("counterparty_reference"),
                pl.col("approach"),
                pl.col("ead_gross"),
                # Per-type Art. 231 waterfall allocations (EAD absorbed)
                *[pl.col(c) for c in alloc_cols],
                # Totals and coverage
                pl.col("total_collateral_for_lgd"),
                pl.col("collateral_coverage_pct"),
                # Financial collateral values (post-haircut, for SA EAD reduction)
                pl.col("collateral_adjusted_value"),
                pl.col("collateral_market_value"),
                # Per-type collateral values (post-haircut)
                pl.col("collateral_financial_value"),
                pl.col("collateral_cash_value"),
                pl.col("collateral_re_value"),
                pl.col("collateral_receivables_value"),
                pl.col("collateral_other_physical_value"),
                # LGD impact
                pl.col("lgd_secured"),
                pl.col("lgd_unsecured"),
                pl.col("lgd_post_crm"),
                pl.col("ead_after_collateral"),
            ]
        )

    def _build_crm_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build CRM audit trail for reporting."""
        return exposures.select(
            [
                pl.col("exposure_reference"),
                pl.col("counterparty_reference"),
                pl.col("approach"),
                pl.col("ead_gross"),
                pl.col("ead_from_ccf"),
                pl.col("ccf"),
                pl.col("collateral_adjusted_value"),
                pl.col("guarantee_amount"),
                pl.col("provision_allocated"),
                pl.col("ead_final"),
                pl.col("lgd_pre_crm"),
                pl.col("lgd_post_crm"),
                pl.col("crm_calculation"),
                # Pre/Post CRM tracking columns
                pl.col("pre_crm_counterparty_reference"),
                pl.col("pre_crm_exposure_class"),
                pl.col("post_crm_counterparty_guaranteed"),
                pl.col("post_crm_exposure_class_guaranteed"),
                pl.col("is_guaranteed"),
                pl.col("guaranteed_portion"),
                pl.col("unguaranteed_portion"),
                pl.col("guarantor_reference"),
                # Cross-approach CCF columns
                pl.col("ccf_original"),
                pl.col("ccf_guaranteed"),
                pl.col("ccf_unguaranteed"),
                pl.col("guarantee_ratio"),
                pl.col("guarantor_approach"),
                pl.col("guarantor_rating_type"),
                pl.col("protection_type"),
            ]
        )


def create_crm_processor(is_basel_3_1: bool = False) -> CRMProcessor:
    """
    Create a CRM processor instance.

    Args:
        is_basel_3_1: True for Basel 3.1 framework (affects haircuts and supervisory LGD)

    Returns:
        CRMProcessor ready for use
    """
    return CRMProcessor(is_basel_3_1=is_basel_3_1)
