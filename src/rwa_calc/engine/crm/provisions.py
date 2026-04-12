"""
Provision resolution for CRM processing.

Pipeline position:
    Classifier -> resolve_provisions -> CCF -> EAD initialisation

Key responsibilities:
- Multi-level provision allocation (direct / facility / counterparty)
- SA drawn-first deduction (CRR Art. 111(2))
- IRB/Slotting pass-through (provisions feed EL shortfall/excess)

References:
    CRR Art. 110-111: Provision treatment
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.schemas import DIRECT_BENEFICIARY_TYPES
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import interest_for_ead

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def resolve_provisions(
    exposures: pl.LazyFrame,
    provisions: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Resolve provisions with multi-level beneficiary and drawn-first deduction.

    This is called *before* CCF so that nominal_after_provision feeds into
    the CCF calculation: ``ead_from_ccf = nominal_after_provision * ccf``.

    Resolution levels (based on beneficiary_type):
    1. Direct (loan/exposure/contingent): join on exposure_reference
    2. Facility: join on parent_facility_reference, pro-rata by exposure weight
    3. Counterparty: join on counterparty_reference, pro-rata by exposure weight

    SA drawn-first deduction (CRR Art. 111(2)):
    - ``floored_drawn = max(0, drawn_amount)``
    - ``provision_on_drawn = min(provision_allocated, floored_drawn)``
    - ``provision_on_nominal = min(remainder, nominal_amount)``
    - Interest is never reduced by provision.

    IRB/Slotting: provision_on_drawn=0, provision_on_nominal=0 (provisions
    feed into EL shortfall/excess instead). provision_allocated is tracked.

    Args:
        exposures: Exposures with drawn_amount, interest, nominal_amount, approach
        provisions: Provision data with beneficiary_reference, amount,
                    and optionally beneficiary_type
        config: Calculation configuration

    Returns:
        Exposures with provision_allocated, provision_on_drawn,
        provision_on_nominal, provision_deducted, nominal_after_provision
    """
    prov_schema = provisions.collect_schema()
    exp_schema = exposures.collect_schema()
    has_beneficiary_type = "beneficiary_type" in prov_schema.names()
    has_parent_facility = "parent_facility_reference" in exp_schema.names()

    if has_beneficiary_type:
        exposures = _resolve_provisions_multi_level(exposures, provisions, has_parent_facility)
    else:
        # Fallback: direct-only join (backward compat)
        provisions_agg = provisions.group_by("beneficiary_reference").agg(
            pl.col("amount").sum().alias("provision_allocated"),
        )
        exposures = exposures.join(
            provisions_agg,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        ).with_columns(
            pl.col("provision_allocated").fill_null(0.0),
        )

    # --- SA drawn-first deduction; IRB/Slotting: no deduction ---
    is_sa = pl.col("approach") == ApproachType.SA.value

    floored_drawn = pl.col("drawn_amount").clip(lower_bound=0.0)

    # provision_on_drawn: min(allocated, floored_drawn) for SA; 0 for IRB
    provision_on_drawn = (
        pl.when(is_sa)
        .then(pl.min_horizontal("provision_allocated", floored_drawn))
        .otherwise(pl.lit(0.0))
    )

    exposures = exposures.with_columns(
        provision_on_drawn.alias("provision_on_drawn"),
    )

    # provision_on_nominal: min(remaining, nominal) for SA; 0 for IRB
    remaining = (pl.col("provision_allocated") - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
    provision_on_nominal = (
        pl.when(is_sa)
        .then(pl.min_horizontal(remaining, pl.col("nominal_amount")))
        .otherwise(pl.lit(0.0))
    )

    exposures = exposures.with_columns(
        provision_on_nominal.alias("provision_on_nominal"),
    )

    # provision_deducted = on_drawn + on_nominal
    exposures = exposures.with_columns(
        (pl.col("provision_on_drawn") + pl.col("provision_on_nominal")).alias("provision_deducted"),
    )

    # nominal_after_provision for CCF: nominal - provision_on_nominal
    exposures = exposures.with_columns(
        (pl.col("nominal_amount") - pl.col("provision_on_nominal")).alias(
            "nominal_after_provision"
        ),
    )

    return exposures


def _resolve_provisions_multi_level(
    exposures: pl.LazyFrame,
    provisions: pl.LazyFrame,
    has_parent_facility: bool,
) -> pl.LazyFrame:
    """
    Resolve provisions from direct, facility, and counterparty levels.

    For facility and counterparty levels, provisions are allocated pro-rata
    based on ``max(0, drawn) + interest + nominal`` as the weight proxy.

    Args:
        exposures: Exposures LazyFrame
        provisions: Provisions with beneficiary_type column
        has_parent_facility: Whether exposures have parent_facility_reference

    Returns:
        Exposures with provision_allocated column added
    """
    bt_lower = pl.col("beneficiary_type").str.to_lowercase()

    # --- 1. Direct-level provisions ---
    direct_provs = (
        provisions.filter(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
        .group_by("beneficiary_reference")
        .agg(pl.col("amount").sum().alias("_prov_direct"))
    )

    exposures = exposures.join(
        direct_provs,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    ).with_columns(pl.col("_prov_direct").fill_null(0.0))

    # --- Compute exposure weight for pro-rata allocation ---
    weight_expr = (
        pl.col("drawn_amount").clip(lower_bound=0.0) + interest_for_ead() + pl.col("nominal_amount")
    )
    exposures = exposures.with_columns(weight_expr.alias("_exp_weight"))

    # --- 2. Facility-level provisions ---
    if has_parent_facility:
        fac_provs = (
            provisions.filter(bt_lower == "facility")
            .group_by("beneficiary_reference")
            .agg(pl.col("amount").sum().alias("_prov_facility"))
        )

        fac_totals = (
            exposures.filter(pl.col("parent_facility_reference").is_not_null())
            .group_by("parent_facility_reference")
            .agg(pl.col("_exp_weight").sum().alias("_fac_total_weight"))
        )

        exposures = (
            exposures.join(
                fac_provs,
                left_on="parent_facility_reference",
                right_on="beneficiary_reference",
                how="left",
            )
            .join(fac_totals, on="parent_facility_reference", how="left")
            .with_columns(
                [
                    pl.col("_prov_facility").fill_null(0.0),
                    pl.col("_fac_total_weight").fill_null(0.0),
                ]
            )
            .with_columns(
                pl.when(pl.col("_fac_total_weight") > 0)
                .then(
                    pl.col("_prov_facility") * pl.col("_exp_weight") / pl.col("_fac_total_weight")
                )
                .otherwise(pl.lit(0.0))
                .alias("_prov_facility_alloc"),
            )
        )
    else:
        exposures = exposures.with_columns(pl.lit(0.0).alias("_prov_facility_alloc"))

    # --- 3. Counterparty-level provisions ---
    cp_provs = (
        provisions.filter(bt_lower == "counterparty")
        .group_by("beneficiary_reference")
        .agg(pl.col("amount").sum().alias("_prov_cp"))
    )

    cp_totals = exposures.group_by("counterparty_reference").agg(
        pl.col("_exp_weight").sum().alias("_cp_total_weight")
    )

    exposures = (
        exposures.join(
            cp_provs,
            left_on="counterparty_reference",
            right_on="beneficiary_reference",
            how="left",
        )
        .join(cp_totals, on="counterparty_reference", how="left")
        .with_columns(
            [
                pl.col("_prov_cp").fill_null(0.0),
                pl.col("_cp_total_weight").fill_null(0.0),
            ]
        )
        .with_columns(
            pl.when(pl.col("_cp_total_weight") > 0)
            .then(pl.col("_prov_cp") * pl.col("_exp_weight") / pl.col("_cp_total_weight"))
            .otherwise(pl.lit(0.0))
            .alias("_prov_cp_alloc"),
        )
    )

    # --- Combine all levels ---
    exposures = exposures.with_columns(
        (pl.col("_prov_direct") + pl.col("_prov_facility_alloc") + pl.col("_prov_cp_alloc")).alias(
            "provision_allocated"
        ),
    )

    # --- Drop temporary columns ---
    drop_cols = [
        "_prov_direct",
        "_exp_weight",
        "_prov_facility_alloc",
        "_prov_cp_alloc",
        "_prov_cp",
        "_cp_total_weight",
    ]
    if has_parent_facility:
        drop_cols.extend(["_prov_facility", "_fac_total_weight"])
    exposures = exposures.drop(drop_cols)

    return exposures
