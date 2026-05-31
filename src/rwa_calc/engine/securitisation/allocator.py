"""
Securitisation pool allocator stage.

Pipeline position:
    Loader -> SecuritisationAllocator -> HierarchyResolver -> ...

Phase 1 scope: flag and exclude. The user supplies a many-rows-per-exposure
``securitisation_allocations`` table mapping each securitised exposure (loan,
contingent, or facility-undrawn parent) to one or more pools with a fractional
allocation. This stage resolves the table into a per-exposure lookup carrying:

- ``securitisation_residual_pct`` -- ``1 - sum(allocation_pct)``, clipped to
  ``[0, 1]``. Defaults to 1.0 for exposures with no allocations (entirely
  on-balance-sheet).
- ``securitisation_pool_allocations`` -- list of struct ``{pool_reference,
  allocation_pct}`` rows. Empty list when no allocations.

The lookup is joined onto the unified exposures frame by the
HierarchyResolver, so the two columns ride through CRM and the calculators
unchanged. The aggregator then multiplies any money column by the residual
pct to produce the on-balance-sheet view, and explodes the struct list to
build the per-pool summary.

Validation codes (see contracts/errors.py for canonical strings):

- SEC001 OVER_ALLOCATED: per-exposure sum > 1.0 -- drop all pool slices,
  keep exposure fully on-balance-sheet (residual_pct = 1.0).
- SEC002 INVALID_PCT: an individual allocation_pct is <= 0 or > 1 -- row
  dropped before per-exposure aggregation.
- SEC003 UNKNOWN_REFERENCE: ``exposure_reference`` does not resolve to any
  loan / contingent / facility -- row dropped.
- SEC004 DUPLICATE: two rows share the same ``(exposure_reference,
  pool_reference)`` -- first row kept, others dropped.
- SEC005 FULLY_SECURITISED: per-exposure sum == 1.0 (residual = 0) --
  informational only; exposure flows through pipeline with zero
  on-balance-sheet contribution.

References:
- CRR Art. 109: gateway to securitisation framework
- CRR Art. 244-246: significant risk transfer
- PRA PS1/26 Art. 147A(1)(j): securitisation positions excluded from IRB

Classes:
    SecuritisationAllocator: implements SecuritisationAllocatorProtocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_SEC_DUPLICATE,
    ERROR_SEC_FULLY_SECURITISED,
    ERROR_SEC_INVALID_PCT,
    ERROR_SEC_OVER_ALLOCATED,
    ERROR_SEC_UNKNOWN_REFERENCE,
    CalculationError,
    securitisation_warning,
)
from rwa_calc.domain.enums import ErrorSeverity

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)

# Regulatory reference for securitisation significant risk transfer criteria
CRR_ART_244 = "CRR Art. 244"

# Schema of the resolved lookup frame returned by ``allocate``. Centralised
# here so the hierarchy resolver and aggregator can build empty placeholder
# frames with matching dtypes when no allocations are supplied.
RESOLVED_SECURITISATION_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String,
    "exposure_type": pl.String,
    "securitisation_residual_pct": pl.Float64,
    "securitisation_pool_allocations": pl.List(
        pl.Struct(
            {
                "pool_reference": pl.String,
                "allocation_pct": pl.Float64,
            }
        )
    ),
    "total_allocated_pct": pl.Float64,
    "audit_status": pl.String,
}


def empty_resolved_lookup() -> pl.LazyFrame:
    """Return an empty resolved-lookup LazyFrame with the canonical schema.

    Used by the hierarchy resolver / aggregator as a safe default when no
    securitisation allocations were supplied. Matching dtypes prevent
    surprises in downstream joins and explodes.
    """
    return pl.LazyFrame(schema=RESOLVED_SECURITISATION_SCHEMA)


class SecuritisationAllocator:
    """Resolve the securitisation_allocations input into a per-exposure lookup.

    Implements ``SecuritisationAllocatorProtocol`` from
    ``contracts/protocols.py``. Pure pass-through on the raw bundle; the
    resolved lookup is returned alongside for the orchestrator to attach
    via ResolvedHierarchyBundle.
    """

    @cites("CRR Art. 109")
    @cites(CRR_ART_244)
    @cites("PS1/26, paragraph 147A")
    def allocate(
        self,
        data: RawDataBundle,
        config: CalculationConfig,  # noqa: ARG002 -- config reserved for future use
    ) -> tuple[RawDataBundle, pl.LazyFrame | None, list[CalculationError]]:
        """Resolve allocations into a per-exposure lookup.

        Args:
            data: Raw data bundle from loader.
            config: Calculation configuration (currently unused; reserved
                so the SRT validation gate can later read framework flags).

        Returns:
            Tuple of (original raw bundle, resolved lookup or None, list
            of validation errors). The lookup is None when no allocations
            were supplied; an empty input frame returns an empty lookup.
        """
        if data.securitisation_allocations is None:
            return data, None, []

        # Materialise once -- the allocator runs row-level validation that
        # is far easier to reason about on a concrete frame than on a
        # lazy plan, and the input table is by definition small (one row
        # per exposure-pool pair).
        raw = data.securitisation_allocations.collect()

        if raw.height == 0:
            return data, empty_resolved_lookup(), []

        errors: list[CalculationError] = []

        # ------------------------------------------------------------------
        # Step 1: SEC002 -- drop rows with invalid allocation_pct.
        # ------------------------------------------------------------------
        invalid_pct = raw.filter(
            (pl.col("allocation_pct").is_null())
            | (pl.col("allocation_pct") <= 0.0)
            | (pl.col("allocation_pct") > 1.0)
        )
        if invalid_pct.height > 0:
            errors.append(
                securitisation_warning(
                    code=ERROR_SEC_INVALID_PCT,
                    message=(
                        f"{invalid_pct.height} securitisation allocation row(s) had "
                        "allocation_pct outside (0, 1] or null; rows dropped."
                    ),
                    severity=ErrorSeverity.ERROR,
                    regulatory_reference=CRR_ART_244,
                )
            )
        raw = raw.filter(
            (pl.col("allocation_pct").is_not_null())
            & (pl.col("allocation_pct") > 0.0)
            & (pl.col("allocation_pct") <= 1.0)
        )

        if raw.height == 0:
            return data, empty_resolved_lookup(), errors

        # ------------------------------------------------------------------
        # Step 2: SEC003 -- orphan exposure_reference (unknown to any of
        # loans / contingents / facilities). Each row is checked against
        # the source table matching its exposure_type to keep the lookup
        # surface narrow.
        # ------------------------------------------------------------------
        known_refs = _collect_known_references(data)
        raw = raw.with_columns(
            pl.struct(["exposure_reference", "exposure_type"])
            .map_elements(
                lambda row: (row["exposure_reference"], row["exposure_type"]) in known_refs,
                return_dtype=pl.Boolean,
            )
            .alias("_is_known"),
        )
        unknown = raw.filter(~pl.col("_is_known"))
        if unknown.height > 0:
            errors.append(
                securitisation_warning(
                    code=ERROR_SEC_UNKNOWN_REFERENCE,
                    message=(
                        f"{unknown.height} securitisation allocation row(s) referenced "
                        "an exposure that does not exist in loans / contingents / "
                        "facilities; rows dropped."
                    ),
                    severity=ErrorSeverity.WARNING,
                    regulatory_reference=CRR_ART_244,
                )
            )
        raw = raw.filter(pl.col("_is_known")).drop("_is_known")

        if raw.height == 0:
            return data, empty_resolved_lookup(), errors

        # ------------------------------------------------------------------
        # Step 3: SEC004 -- duplicate (exposure_reference, pool_reference).
        # Keep first, drop subsequent.
        # ------------------------------------------------------------------
        before_dedup = raw.height
        raw = raw.unique(
            subset=["exposure_reference", "exposure_type", "pool_reference"],
            keep="first",
        )
        dropped = before_dedup - raw.height
        if dropped > 0:
            errors.append(
                securitisation_warning(
                    code=ERROR_SEC_DUPLICATE,
                    message=(
                        f"{dropped} duplicate (exposure_reference, pool_reference) "
                        "securitisation allocation row(s) dropped; first row kept."
                    ),
                    severity=ErrorSeverity.WARNING,
                    regulatory_reference=CRR_ART_244,
                )
            )

        # ------------------------------------------------------------------
        # Step 4: per-exposure aggregation. Group into struct list and
        # compute total_allocated_pct.
        # ------------------------------------------------------------------
        aggregated = (
            raw.lazy()
            .group_by(["exposure_reference", "exposure_type"])
            .agg(
                [
                    pl.struct(
                        [
                            pl.col("pool_reference"),
                            pl.col("allocation_pct"),
                        ]
                    ).alias("securitisation_pool_allocations"),
                    pl.col("allocation_pct").sum().alias("total_allocated_pct"),
                ]
            )
        ).collect()

        # ------------------------------------------------------------------
        # Step 5: SEC001 -- per-exposure sum > 1. Drop the allocations
        # entirely for those rows; the exposure is treated as fully
        # on-balance-sheet (residual_pct = 1.0) with audit_status =
        # "over_allocated" so the audit row still surfaces the issue.
        # ------------------------------------------------------------------
        # Use a small tolerance to absorb floating-point summation noise --
        # ``0.4 + 0.3 + 0.3`` is not exactly 1.0 in IEEE-754.
        _SUM_TOLERANCE = 1e-9
        over = aggregated.filter(pl.col("total_allocated_pct") > 1.0 + _SUM_TOLERANCE)
        if over.height > 0:
            errors.append(
                securitisation_warning(
                    code=ERROR_SEC_OVER_ALLOCATED,
                    message=(
                        f"{over.height} exposure(s) had securitisation allocations "
                        "summing to > 1.0; all pool slices dropped, exposure(s) "
                        "kept fully on-balance-sheet."
                    ),
                    severity=ErrorSeverity.ERROR,
                    regulatory_reference=CRR_ART_244,
                )
            )

        # ------------------------------------------------------------------
        # Step 6: SEC005 -- per-exposure sum == 1 (residual = 0). Inform-
        # ational only -- the exposure flows through the pipeline with
        # zero on-balance-sheet contribution.
        # ------------------------------------------------------------------
        fully = aggregated.filter(
            (pl.col("total_allocated_pct") >= 1.0 - _SUM_TOLERANCE)
            & (pl.col("total_allocated_pct") <= 1.0 + _SUM_TOLERANCE)
        )
        if fully.height > 0:
            errors.append(
                securitisation_warning(
                    code=ERROR_SEC_FULLY_SECURITISED,
                    message=(
                        f"{fully.height} exposure(s) fully securitised "
                        "(residual = 0); zero on-balance-sheet contribution."
                    ),
                    severity=ErrorSeverity.WARNING,
                    regulatory_reference=CRR_ART_244,
                )
            )

        # ------------------------------------------------------------------
        # Step 7: build the resolved lookup. Over-allocated rows keep
        # residual_pct = 1.0 and an empty pool_allocations list so the
        # aggregator does not double-count them.
        # ------------------------------------------------------------------
        is_over = pl.col("total_allocated_pct") > 1.0 + _SUM_TOLERANCE
        is_fully = (pl.col("total_allocated_pct") >= 1.0 - _SUM_TOLERANCE) & (
            pl.col("total_allocated_pct") <= 1.0 + _SUM_TOLERANCE
        )

        empty_struct_list = pl.lit([]).cast(
            pl.List(
                pl.Struct(
                    {
                        "pool_reference": pl.String,
                        "allocation_pct": pl.Float64,
                    }
                )
            )
        )

        resolved = aggregated.with_columns(
            [
                pl.when(is_over)
                .then(pl.lit(1.0))
                .otherwise((pl.lit(1.0) - pl.col("total_allocated_pct")).clip(lower_bound=0.0))
                .alias("securitisation_residual_pct"),
                pl.when(is_over)
                .then(empty_struct_list)
                .otherwise(pl.col("securitisation_pool_allocations"))
                .alias("securitisation_pool_allocations"),
                pl.when(is_over)
                .then(pl.lit("over_allocated"))
                .when(is_fully)
                .then(pl.lit("fully_securitised"))
                .otherwise(pl.lit("ok"))
                .alias("audit_status"),
            ]
        ).select(list(RESOLVED_SECURITISATION_SCHEMA.keys()))

        logger.info(
            "securitisation_allocator resolved %d exposure(s); %d error(s)",
            resolved.height,
            len(errors),
        )

        return data, resolved.lazy(), errors


def attach_securitisation_lookup(
    exposures: pl.LazyFrame,
    lookup: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """Join the resolved securitisation lookup onto the unified exposures frame.

    Adds two columns to every row:

    - ``securitisation_residual_pct``: 1.0 when no allocation was supplied.
    - ``securitisation_pool_allocations``: empty list when no allocations.

    Join keys differ by exposure type:

    - ``loan`` / ``contingent`` rows: key = (exposure_reference, exposure_type).
    - ``facility_undrawn`` rows: key = (source_facility_reference,
      ``"facility"``) -- the user supplies allocations against the parent
      facility reference, and the synthetic undrawn row inherits the same
      ratio.

    When ``lookup`` is None, returns the exposures frame with the two
    columns added at their canonical defaults so downstream code can
    assume both are always present.
    """
    empty_struct_list = pl.lit([]).cast(
        pl.List(
            pl.Struct(
                {
                    "pool_reference": pl.String,
                    "allocation_pct": pl.Float64,
                }
            )
        )
    )

    if lookup is None:
        return exposures.with_columns(
            [
                pl.lit(1.0).alias("securitisation_residual_pct"),
                empty_struct_list.alias("securitisation_pool_allocations"),
            ]
        )

    schema_names = set(exposures.collect_schema().names())
    if "exposure_type" not in schema_names or "exposure_reference" not in schema_names:
        # Schema doesn't carry the columns we need to join on -- bail out
        # with defaults so the downstream contract still holds.
        return exposures.with_columns(
            [
                pl.lit(1.0).alias("securitisation_residual_pct"),
                empty_struct_list.alias("securitisation_pool_allocations"),
            ]
        )

    # Build per-row join keys. facility_undrawn rows redirect to the
    # parent facility's allocation entry.
    source_facility_expr = (
        pl.col("source_facility_reference")
        if "source_facility_reference" in schema_names
        else pl.lit(None).cast(pl.String)
    )
    is_facility_undrawn = pl.col("exposure_type") == "facility_undrawn"

    keyed = exposures.with_columns(
        [
            pl.when(is_facility_undrawn)
            .then(source_facility_expr)
            .otherwise(pl.col("exposure_reference"))
            .alias("_sec_join_ref"),
            pl.when(is_facility_undrawn)
            .then(pl.lit("facility"))
            .otherwise(pl.col("exposure_type"))
            .alias("_sec_join_type"),
        ]
    )

    # Pre-select the lookup columns we need so the join surface stays
    # narrow and we don't pull total_allocated_pct / audit_status onto
    # every exposure row.
    lookup_slim = lookup.select(
        [
            pl.col("exposure_reference").alias("_sec_lookup_ref"),
            pl.col("exposure_type").alias("_sec_lookup_type"),
            pl.col("securitisation_residual_pct"),
            pl.col("securitisation_pool_allocations"),
        ]
    )

    joined = keyed.join(
        lookup_slim,
        left_on=["_sec_join_ref", "_sec_join_type"],
        right_on=["_sec_lookup_ref", "_sec_lookup_type"],
        how="left",
    )

    # Coalesce nulls to canonical defaults. Polars' fill_null doesn't
    # handle list-of-struct cleanly, so use a when/then chain.
    return joined.with_columns(
        [
            pl.col("securitisation_residual_pct").fill_null(1.0),
            pl.when(pl.col("securitisation_pool_allocations").is_null())
            .then(empty_struct_list)
            .otherwise(pl.col("securitisation_pool_allocations"))
            .alias("securitisation_pool_allocations"),
        ]
    ).drop(["_sec_join_ref", "_sec_join_type"])


def _collect_known_references(data: RawDataBundle) -> set[tuple[str, str]]:
    """Collect the universe of valid (exposure_reference, exposure_type) pairs.

    Used by SEC003 to drop allocations that reference exposures absent from
    every input table. Returns a Python set so the per-row lookup is O(1)
    -- the alternative (a lazy join) would require materialising the join
    key columns from three different frames and is no cheaper at this
    scale (allocations tables are typically very small).
    """
    known: set[tuple[str, str]] = set()
    sources = (
        ("loan", data.loans, "loan_reference"),
        ("contingent", data.contingents, "contingent_reference"),
        ("facility", data.facilities, "facility_reference"),
    )
    for exposure_type, frame, ref_col in sources:
        if frame is None:
            continue
        try:
            df = frame.select(pl.col(ref_col)).collect()
        except Exception:
            # If the source table does not expose the reference column
            # (badly shaped fixtures, partial loads), treat it as having
            # no known references rather than failing the whole stage.
            continue
        for ref in df[ref_col].drop_nulls().to_list():
            known.add((str(ref), exposure_type))
    return known
