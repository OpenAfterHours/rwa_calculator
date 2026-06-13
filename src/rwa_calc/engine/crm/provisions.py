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
from watchfire import cites

from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import interest_for_ead, sa_ccf_expression
from rwa_calc.engine.kernels.allocation import (
    LevelSpec,
    allocate_multi_level,
    beneficiary_level_expr,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@cites("CRR Art. 111")
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
    has_risk_type = "risk_type" in exp_schema.names()

    if has_beneficiary_type:
        exposures = _resolve_provisions_multi_level(
            exposures, provisions, has_parent_facility, has_risk_type, config.is_basel_3_1
        )
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
    has_risk_type: bool,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """
    Resolve provisions from direct, facility, and counterparty levels.

    Thin parameterisation of the allocation kernel
    (:func:`rwa_calc.engine.kernels.allocation.allocate_multi_level`):

    - Facility-level provisions cascade over the ancestor facility set —
      a provision pledged at any ancestor facility (parent, grandparent, ...
      root) is allocated pro-rata across that facility's whole descendant
      subtree, contributions stacking across ancestor levels (the
      ``cascade=True`` level).
    - Null / unknown ``beneficiary_type`` rows are DROPPED (the
      ``unknown=None`` classifier — provisions-copy behaviour, unlike the
      collateral copy's unknown->direct fallback).

    For facility and counterparty levels, provisions are allocated pro-rata
    by the post-CCF EAD-equivalent weight
    ``max(0, drawn) + max(0, interest) + nominal * ccf``. The CCF is derived
    inline from ``risk_type`` (via ``sa_ccf_expression``) because this stage
    runs *before* the CCF stage, so no ``ead_gross`` column exists yet. When
    the frame has no ``risk_type`` column the CCF is treated as 1.0, so the
    weight degrades to the bare-nominal proxy ``max(0, drawn) + interest +
    nominal``.

    Args:
        exposures: Exposures LazyFrame
        provisions: Provisions with beneficiary_type column
        has_parent_facility: Whether exposures have parent_facility_reference
        has_risk_type: Whether exposures have a risk_type column to CCF-weight
        is_basel_3_1: Whether to use Basel 3.1 SA CCFs (else CRR)

    Returns:
        Exposures with provision_allocated column added
    """
    # Post-CCF EAD-equivalent pro-rata basis: nominal is weighted by its SA
    # CCF (derived inline from risk_type, since the CCF stage has not yet
    # run). On-balance rows have nominal=0 so the CCF term vanishes;
    # unknown/null risk_type falls through to sa_ccf_expression's
    # conservative full-risk default rather than crashing. Frames without a
    # risk_type column fall back to a CCF of 1.0 (bare nominal).
    ccf_expr = (
        sa_ccf_expression("risk_type", is_basel_3_1=is_basel_3_1) if has_risk_type else pl.lit(1.0)
    )
    weight_expr = (
        pl.col("drawn_amount").clip(lower_bound=0.0)
        + interest_for_ead()
        + pl.col("nominal_amount") * ccf_expr
    )

    levels: list[LevelSpec] = [LevelSpec("direct", "exposure_reference", pro_rata=False)]
    if has_parent_facility:
        levels.append(LevelSpec("facility", "parent_facility_reference", cascade=True))
    levels.append(LevelSpec("counterparty", "counterparty_reference"))

    return allocate_multi_level(
        exposures,
        provisions,
        values={"provision_allocated": pl.col("amount").sum()},
        basis=weight_expr,
        level_of=beneficiary_level_expr(unknown=None),
        levels=levels,
    )
