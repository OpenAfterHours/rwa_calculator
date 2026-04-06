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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
)
from rwa_calc.contracts.errors import LazyFrameResult
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.engine.crm import collateral as collateral_mod
from rwa_calc.engine.crm import guarantees as guarantees_mod
from rwa_calc.engine.crm import provisions as provisions_mod
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.materialise import materialise_barrier
from rwa_calc.engine.utils import has_required_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def _build_exposure_lookups(
    exposures: pl.LazyFrame,
) -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
    """
    Pre-compute exposure lookups for collateral processing.

    Builds three lookup LazyFrames (direct, facility, counterparty) with all
    columns needed by _join_collateral_to_lookups and the multi-level allocation
    methods. Computing these once avoids duplicate references to the upstream
    exposures plan.

    Returns:
        (direct_lookup, facility_lookup, cp_lookup) where each has a _ben_ref_*
        key column plus _ead_*, _currency_*, and _maturity_* value columns.
    """
    exp_schema = exposures.collect_schema()

    # Direct: one row per exposure
    direct_lookup = exposures.select(
        [
            pl.col("exposure_reference").alias("_ben_ref_direct"),
            pl.col("ead_gross").alias("_ead_direct"),
            pl.col("currency").alias("_currency_direct"),
            pl.col("maturity_date").alias("_maturity_direct"),
        ]
    )

    # Facility: aggregated per parent_facility_reference
    if "parent_facility_reference" in exp_schema.names():
        facility_lookup = (
            exposures.filter(pl.col("parent_facility_reference").is_not_null())
            .group_by("parent_facility_reference")
            .agg(
                [
                    pl.col("ead_gross").sum().alias("_ead_facility"),
                    pl.col("currency").first().alias("_currency_facility"),
                    pl.col("maturity_date").first().alias("_maturity_facility"),
                ]
            )
            .with_columns(
                pl.col("parent_facility_reference").cast(pl.String),
            )
            .rename({"parent_facility_reference": "_ben_ref_facility"})
        )
    else:
        facility_lookup = pl.LazyFrame(
            schema={
                "_ben_ref_facility": pl.String,
                "_ead_facility": pl.Float64,
                "_currency_facility": pl.String,
                "_maturity_facility": pl.Date,
            }
        )

    # Counterparty: aggregated per counterparty_reference
    cp_lookup = (
        exposures.group_by("counterparty_reference")
        .agg(
            [
                pl.col("ead_gross").sum().alias("_ead_cp"),
                pl.col("currency").first().alias("_currency_cp"),
                pl.col("maturity_date").first().alias("_maturity_cp"),
            ]
        )
        .rename({"counterparty_reference": "_ben_ref_cp"})
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
    from rwa_calc.engine.crm.constants import DIRECT_BENEFICIARY_TYPES

    coll_schema = collateral.collect_schema()

    if "beneficiary_type" not in coll_schema.names():
        # Direct-only join — single pass with all columns
        return collateral.join(
            direct_lookup.select(
                pl.col("_ben_ref_direct"),
                pl.col("_ead_direct").alias("_beneficiary_ead"),
                pl.col("_currency_direct").alias("exposure_currency"),
                pl.col("_maturity_direct").alias("exposure_maturity"),
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
        ]
    ).drop(
        [
            "_ead_direct",
            "_ead_facility",
            "_ead_cp",
            "_currency_direct",
            "_currency_facility",
            "_currency_cp",
            "_maturity_direct",
            "_maturity_facility",
            "_maturity_cp",
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
    if "pledge_percentage" not in coll_schema.names():
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


@dataclass
class CRMError:
    """Error encountered during CRM processing."""

    error_type: str
    message: str
    exposure_reference: str | None = None
    context: dict = field(default_factory=dict)


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

        # Convert to LazyFrameResult format
        return LazyFrameResult(
            frame=bundle.exposures,
            errors=[],  # CRMError objects would need conversion to CalculationError
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
        errors: list[CRMError] = []

        # Start with all exposures
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

        # Materialise the deep lazy plan (provisions → CCF → init_ead) once.
        # Without this, _generate_netting_collateral's two-join matching and
        # apply_collateral's 3 lookup collects each re-execute the full upstream
        # plan, and the plan depth causes Polars optimizer segfaults.
        # In streaming mode, spills to disk instead of loading into memory.
        exposures = materialise_barrier(exposures, config, "crm_post_ead_fanout")

        # Step 3.5: Generate synthetic collateral from netting (CRR Art. 195)
        netting_collateral = collateral_mod.generate_netting_collateral(exposures)
        collateral: pl.LazyFrame | None = data.collateral
        if netting_collateral is not None:
            # Track per-exposure netting amount for COREP col 0035
            exposures = _join_netting_amounts(exposures, netting_collateral)
            if collateral is not None and has_required_columns(
                collateral, self.COLLATERAL_REQUIRED_COLUMNS
            ):
                collateral = pl.concat([collateral, netting_collateral], how="diagonal")
            else:
                collateral = netting_collateral
        else:
            exposures = exposures.with_columns(pl.lit(0.0).alias("on_bs_netting_amount"))

        # Step 4: Apply collateral (if available and valid)
        if has_required_columns(collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            exposures = self.apply_collateral(exposures, collateral, config)
        else:
            # No collateral: still need to set F-IRB supervisory LGD based on seniority
            exposures = collateral_mod.apply_firb_supervisory_lgd_no_collateral(
                exposures, self._is_basel_3_1
            )

        # Step 5: Apply guarantees (if available and valid)
        if (
            has_required_columns(data.guarantees, self.GUARANTEE_REQUIRED_COLUMNS)
            and data.counterparty_lookup is not None
        ):
            # Materialise guarantee lookup tables to prevent parquet re-scans.
            guarantees_df, cp_lookup_df, ri_df = pl.collect_all(
                [
                    data.guarantees,
                    data.counterparty_lookup.counterparties,
                    data.counterparty_lookup.rating_inheritance,
                ]
            )
            exposures = self.apply_guarantees(
                exposures,
                guarantees_df.lazy(),
                cp_lookup_df.lazy(),
                config,
                ri_df.lazy(),
            )

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
            collateral_allocation=None,  # Would be populated from collateral processing
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
        errors: list[CRMError] = []

        exposures = data.all_exposures

        # Steps 1-7: Same CRM processing as get_crm_adjusted_bundle
        if has_required_columns(data.provisions, self.PROVISION_REQUIRED_COLUMNS):
            exposures = self.resolve_provisions(exposures, data.provisions, config)

        exposures = self._apply_ccf(exposures, config)
        exposures = self._initialize_ead(exposures)

        # Materialise the deep lazy plan (provisions → CCF → init_ead) once.
        # Without this, apply_collateral's 3 lookup collects each re-execute
        # the full upstream plan, and the final collect re-executes it again
        # (4× total).  Collecting here means all downstream operations
        # (collateral, guarantees, finalize, audit) work on materialised data.
        # In streaming mode, spills to disk instead of loading into memory.
        exposures = materialise_barrier(exposures, config, "crm_post_ead_unified")

        # Generate synthetic collateral from netting (CRR Art. 195)
        netting_collateral = collateral_mod.generate_netting_collateral(exposures)
        collateral: pl.LazyFrame | None = data.collateral
        if netting_collateral is not None:
            # Track per-exposure netting amount for COREP col 0035
            exposures = _join_netting_amounts(exposures, netting_collateral)
            if collateral is not None and has_required_columns(
                collateral, self.COLLATERAL_REQUIRED_COLUMNS
            ):
                collateral = pl.concat([collateral, netting_collateral], how="diagonal")
            else:
                collateral = netting_collateral
        else:
            exposures = exposures.with_columns(pl.lit(0.0).alias("on_bs_netting_amount"))

        if has_required_columns(collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            exposures = self.apply_collateral(exposures, collateral, config)
        else:
            exposures = collateral_mod.apply_firb_supervisory_lgd_no_collateral(
                exposures, self._is_basel_3_1
            )

        # Materialise after collateral before guarantee processing.
        # Collateral adds 3 lookup joins + haircuts + unified allocation;
        # without this collect, the guarantee module's 3-path concat
        # (no-guarantee / single / multi-guarantor split) re-evaluates the
        # full collateral plan per branch, causing ~4x slowdown at 100K scale.
        if (
            has_required_columns(data.guarantees, self.GUARANTEE_REQUIRED_COLUMNS)
            and data.counterparty_lookup is not None
        ):
            # Materialise exposures via barrier (disk-spill in streaming mode).
            # Lookup tables (guarantees, counterparties, rating_inheritance)
            # are small reference data — collect in-memory via collect_all.
            exposures = materialise_barrier(exposures, config, "crm_pre_guarantee_unified")
            guarantees_df, cp_lookup_df, ri_df = pl.collect_all(
                [
                    data.guarantees,
                    data.counterparty_lookup.counterparties,
                    data.counterparty_lookup.rating_inheritance,
                ]
            )
            exposures = self.apply_guarantees(
                exposures,
                guarantees_df.lazy(),
                cp_lookup_df.lazy(),
                config,
                ri_df.lazy(),
            )
        else:
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
            collateral_allocation=None,
            crm_errors=errors,
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
    ) -> pl.LazyFrame:
        """Apply F-IRB supervisory LGD when no collateral is available."""
        return collateral_mod.apply_firb_supervisory_lgd_no_collateral(
            exposures, self._is_basel_3_1
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

        return exposures.with_columns(
            [
                # Pre-CRM attributes for regulatory reporting
                pl.col("counterparty_reference").alias("pre_crm_counterparty_reference"),
                pl.col("exposure_class").alias("pre_crm_exposure_class"),
                # Gross EAD = drawn + CCF-adjusted contingent
                pl.col("ead_pre_crm").alias("ead_gross"),
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
                # Unfunded protection type (guarantee vs credit_derivative)
                pl.lit(None).cast(pl.String).alias("protection_type"),
                # FX mismatch haircut on guarantees (Art. 233(3-4))
                pl.lit(0.0).alias("guarantee_fx_haircut"),
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
