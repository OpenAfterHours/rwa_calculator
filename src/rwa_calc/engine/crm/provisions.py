"""
Provision resolution for CRM processing.

Pipeline position:
    Classifier -> resolve_provisions -> CCF -> EAD initialisation

Key responsibilities:
- Multi-level provision allocation (direct / facility / counterparty), twice:
  the total of every provision row (``provision_allocated``) and the specific
  credit risk adjustments alone (``provision_specific_allocated``)
- SA drawn-first deduction of SPECIFIC credit risk adjustments only
  (CRR Art. 111(1) / PS1/26 Art. 111(1)(a)-(b)); general credit risk
  adjustments go to Tier 2 under Art. 110(1) / 62(c) and never reduce the SA
  exposure value
- IRB/Slotting pass-through (the total feeds EL shortfall/excess, because
  PS1/26 Art. 159(1) 'B' includes general credit risk adjustments)

References:
    CRR Art. 110(1): SA general CRA treated under Art. 62(c) (Tier 2)
    CRR Art. 111(1): SA exposure value net of specific CRA
    CRR Art. 127(1): default test on specific CRA (reads the specific carrier)
    PS1/26 Art. 110(1), 111(1), 127(1), 159(1): unchanged in substance
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import PROVISION_SCHEMA
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import interest_for_ead, sa_ccf_expression
from rwa_calc.engine.kernels.allocation import (
    LevelSpec,
    allocate_multi_level,
    beneficiary_level_expr,
)
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack


@cites("CRR Art. 111(1)")
@cites("PS1/26, paragraph 111")
def resolve_provisions(
    exposures: pl.LazyFrame,
    provisions: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Resolve provisions with multi-level beneficiary and drawn-first deduction.

    This is called *before* CCF so that nominal_after_provision feeds into
    the CCF calculation: ``ead_from_ccf = nominal_after_provision * ccf``.

    Resolution levels (based on beneficiary_type):
    1. Direct (loan/exposure/contingent): join on exposure_reference
    2. Facility: join on parent_facility_reference, pro-rata by exposure weight
    3. Counterparty: join on counterparty_reference, pro-rata by exposure weight

    Two amounts are allocated per exposure, on the same levels and basis:

    - ``provision_allocated`` — every provision row (specific AND general).
      The IRB / slotting expected-loss comparison reads it: PS1/26 Art. 159(1)
      'B' sums (i) general and (ii) specific credit risk adjustments.
    - ``provision_specific_allocated`` — specific credit risk adjustments
      only: a row whose ``provision_type`` is ``scra`` (any case) or NULL.
      NULL stays specific because it is what the loader injects when a book
      omits the optional column, and untyped provisions have always been
      deducted. A ``gcra`` row (or any other label) is excluded: CRR
      Art. 110(1) sends SA general CRA to Tier 2 under Art. 62(c). A direct
      caller whose frame has no ``provision_type`` column at all gets the
      typed NULL injected here, so every row counts as specific.

    SA drawn-first deduction of the SPECIFIC amount (CRR Art. 111(1); PS1/26
    Art. 111(1)(a) asset items, (b)(i) "nominal value after reduction of
    specific credit risk adjustments"):
    - ``floored_drawn = max(0, drawn_amount)``
    - ``provision_on_drawn = min(provision_specific_allocated, floored_drawn)``
    - ``provision_on_nominal = min(remainder, nominal_amount)``
    - Interest is never reduced by provision.

    IRB/Slotting: provision_on_drawn=0, provision_on_nominal=0 (provisions
    feed into EL shortfall/excess instead). Both allocated amounts are
    tracked; the specific one is also the Art. 127(1) numerator that sets a
    defaulted row's SA (and SA-equivalent) risk weight.

    Args:
        exposures: Exposures with drawn_amount, interest, nominal_amount, approach
        provisions: Provision data with beneficiary_reference, amount,
                    and optionally beneficiary_type
        config: Calculation configuration

    Returns:
        Exposures with provision_allocated, provision_specific_allocated,
        provision_on_drawn, provision_on_nominal, provision_deducted,
        nominal_after_provision
    """
    prov_schema = provisions.collect_schema()
    exp_schema = exposures.collect_schema()
    provisions = ensure_columns(
        provisions,
        {"provision_type": PROVISION_SCHEMA["provision_type"]},
        present=prov_schema.names(),
    )
    has_beneficiary_type = "beneficiary_type" in prov_schema.names()
    has_parent_facility = "parent_facility_reference" in exp_schema.names()
    has_risk_type = "risk_type" in exp_schema.names()

    if has_beneficiary_type:
        # S9e: the SA-CCF table used as the pro-rata provision-weighting basis is
        # regime-selected via the cited pack Feature; _resolve_provisions_multi_level
        # (and the sa_ccf_expression it calls) keep their is_basel_3_1 bool param
        # (Option B). The CCF table VALUES stay static data-layer constants.
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        exposures = _resolve_provisions_multi_level(
            exposures,
            provisions,
            has_parent_facility,
            has_risk_type,
            resolved_pack.feature("sa_revised_ccf_table"),
        )
    else:
        # Fallback: direct-only join (backward compat)
        provisions_agg = provisions.group_by("beneficiary_reference").agg(
            pl.col("amount").sum().alias("provision_allocated"),
            _specific_amount().alias("provision_specific_allocated"),
        )
        exposures = exposures.join(
            provisions_agg,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        ).with_columns(
            pl.col("provision_allocated", "provision_specific_allocated").fill_null(0.0),
        )

    # --- SA drawn-first deduction of SPECIFIC CRA; IRB/Slotting: no deduction ---
    is_sa = pl.col("approach") == ApproachType.SA.value
    specific = pl.col("provision_specific_allocated")

    floored_drawn = pl.col("drawn_amount").clip(lower_bound=0.0)

    # provision_on_drawn: min(specific, floored_drawn) for SA; 0 for IRB
    provision_on_drawn = (
        pl.when(is_sa).then(pl.min_horizontal(specific, floored_drawn)).otherwise(pl.lit(0.0))
    )

    exposures = exposures.with_columns(
        provision_on_drawn.alias("provision_on_drawn"),
    )

    # provision_on_nominal: min(remaining, nominal) for SA; 0 for IRB
    remaining = (specific - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
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
        Exposures with provision_allocated and provision_specific_allocated
        columns added
    """
    # Post-CCF EAD-equivalent pro-rata basis: nominal is weighted by its SA
    # CCF (derived inline from risk_type, since the CCF stage has not yet
    # run). On-balance rows have nominal=0 so the CCF term vanishes;
    # unknown/null risk_type falls through to sa_ccf_expression's residual
    # limb rather than crashing. Frames without a risk_type column fall back
    # to a CCF of 1.0 (bare nominal).
    #
    # ``commitment_col=None`` because this frame is a provision-WEIGHTING basis
    # assembled before the CCF stage and is not guaranteed to carry
    # ``is_obs_commitment``; it selects the Table A1 Row 3 (issued, 50%) limb,
    # the higher of the two B31 residuals. A weighting denominator, not a
    # capital number.
    ccf_expr = (
        sa_ccf_expression("risk_type", is_basel_3_1=is_basel_3_1, commitment_col=None)
        if has_risk_type
        else pl.lit(1.0)
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
        values={
            "provision_allocated": pl.col("amount").sum(),
            "provision_specific_allocated": _specific_amount(),
        },
        basis=weight_expr,
        level_of=beneficiary_level_expr(unknown=None),
        levels=levels,
    )


def _specific_amount() -> pl.Expr:
    """Per-beneficiary sum of the SPECIFIC credit risk adjustments.

    A row is specific when ``provision_type`` is ``scra`` in any case (the
    validator compares case-insensitively; books and fixtures write ``SCRA``)
    or NULL (the loader's injected value for an untyped book, deducted as
    before). ``gcra`` is not: CRR Art. 110(1) / PS1/26 Art. 110(1) treat SA
    general credit risk adjustments under Art. 62(c). Nor is a label outside
    ``scra`` / ``gcra``: the validator reports it as a DQ006 warning and keeps
    the row, and it stays out of the exposure-value deduction (the
    conservative reading of an unrecognised label).
    """
    provision_type = pl.col("provision_type").cast(pl.String)
    is_specific = provision_type.is_null() | (provision_type.str.to_lowercase() == "scra")
    return pl.col("amount").filter(is_specific).sum()
