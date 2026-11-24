"""
Guarantee substitution for IRB exposures.

Pipeline position:
    IRB adjustments -> Guarantee substitution -> Supporting factors

Key responsibilities:
- SA risk weight substitution (CRR Art. 215-217, Basel 3.1 SA guarantors)
- Parameter substitution (Basel 3.1 CRE22.70-85, IRB guarantors)
- Double default treatment (CRR Art. 153(3), 202-203)
- RWA blending (guaranteed vs unguaranteed portions)
- Expected loss adjustment for guaranteed portions

References:
- CRR Art. 153(3), 202-203: Double default treatment; Art. 202 limits the
  protection provider to the institution entity types (P1.203)
- CRR Art. 161(3): Guarantor PD substitution for expected loss
- CRR Art. 193(1), (3): CRM recognition principles — the no-worse RWEA/EL cap
  and the election to amend, i.e. the basis for declining a guarantee
- CRR Art. 213, 215-217: Guarantee eligibility and substitution
- CRR Art. 235 / PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM)
- CRR Art. 114-122: guarantor SA risk weights (shared builder —
  data/tables/guarantor_rw.py)
- Basel 3.1 CRE22.70-85: Parameter substitution approach
- CRR Art. 306, CRE54.14-15: CCP risk weights
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import polars.selectors as cs
from watchfire import cites

from rwa_calc.contracts.edges import CROSS_APPROACH_CCF_OWN_EAD_COL
from rwa_calc.data.schemas import DOUBLE_DEFAULT_PROVIDER_ENTITY_TYPES
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    denomination_currency_expr,
    funding_currency_expr,
)
from rwa_calc.engine.irb.formulas import (
    _double_default_multiplier_expr,
    _parametric_irb_risk_weight_expr,
    _pd_floor_expression,
    firb_supervisory_lgd_values,
)
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr, ensure_guarantor_rw_columns
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

#: Transient: a swapped leg's CRM-exit exposure value and covered amount on the SA
#: conversion factor, captured before ``redistribute_non_beneficial`` and consumed
#: by :func:`_settle_cross_approach_ccf` in the same call.
_SA_CCF_EAD_COL = "_ead_sa_ccf"
_SA_CCF_COVERED_COL = "_covered_sa_ccf"


@cites("CRR Art. 161(3)")
def apply_guarantee_substitution(
    lf: pl.LazyFrame, config: CalculationConfig, *, pack: ResolvedRulepack | None = None
) -> pl.LazyFrame:
    """
    Apply guarantee substitution for IRB exposures with unfunded credit protection.

    Three methods depending on framework and guarantor approach:

    1. **SA risk weight substitution** (CRR Art. 215-217, Basel 3.1 SA guarantors):
       Guaranteed portion uses guarantor's SA risk weight.

    2. **Parameter substitution** (Basel 3.1 CRE22.70-85, IRB guarantors):
       Guaranteed portion recalculated using guarantor's PD and F-IRB supervisory
       LGD through the full IRB formula (K × 12.5 × scaling × MA).

    3. **Double default** (CRR Art. 153(3), 202-203, CRR only):
       K_dd = K_obligor × (0.15 + 160 × PD_guarantor). Requires A-IRB permission,
       corporate underlying, and an Art. 202 protection provider (an institution
       or bank guarantor) with an internal PD. Provides lower capital charge than
       substitution for high-quality guarantors.

    The final RWA blends:
    - Unguaranteed portion: borrower's IRB RWA (pro-rated)
    - Guaranteed portion: guarantor's equivalent RWA (method-dependent)

    Args:
        lf: LazyFrame with IRB formula results
        config: Calculation configuration

    Returns:
        LazyFrame with guarantee-adjusted RWA
    """
    schema = lf.collect_schema()
    cols = schema.names()

    # Run-level sentinel gate: guarantor_entity_type is the one crm_exit
    # column still CONDITIONAL (inject=False) — present iff the CRM guarantee
    # sub-step ran. Keying on it keeps this machinery (and its derived audit
    # columns: rwa_irb_original, guarantor_rw*, guarantee_status, ...) off
    # unguaranteed runs; see contracts/edges.py. The guaranteed_portion check
    # covers direct (non-pipeline) invocation.
    if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
        return lf

    has_expected_loss = "expected_loss" in cols
    has_guarantor_pd = "guarantor_pd" in cols
    origin_pd_col = next(name for name in ("pd_floored", "pd") if name in cols)
    origin_lgd_col = next(name for name in ("lgd_floored", "lgd", "lgd_input") if name in cols)
    # The PRE-INPUT-FLOOR twin of ``origin_pd_col``. OF 08.03's row axis is
    # "PD RANGE (PRE-INPUT FLOOR)" (PS1/26 Annex II §3.3.5.2), so the post-CRM
    # banding needs an unfloored post-CRM PD or an unguaranteed Basel 3.1 book
    # would band on the floored value and move rows at the 0.05% split that
    # regime adds. Preference is the mirror image of ``origin_pd_col``'s.
    origin_pd_pre_floor_col = next(name for name in ("pd", "pd_floored") if name in cols)
    # PD substitution applies whenever the guarantor has an internal PD.
    # Per-row routing (IRB-derived RW vs SA-derived RW) is decided inside
    # _apply_parameter_substitution by guarantor_approach, which is itself
    # beneficiary-aware (set in engine/crm/guarantees.py). This covers both
    # CRR Art. 161(3) and Basel 3.1 CRE22.70-85 — only the F-IRB LGD differs.
    use_parameter_substitution = has_guarantor_pd

    # Store original IRB values before substitution (pre-CRM values)
    store_originals = [
        pl.col("rwa").alias("rwa_irb_original"),
        pl.col("risk_weight").alias("risk_weight_irb_original"),
        pl.col("risk_weight").alias("pre_crm_risk_weight"),
        pl.col("rwa").alias("pre_crm_rwa"),
    ]
    if has_expected_loss:
        store_originals.append(pl.col("expected_loss").alias("expected_loss_irb_original"))

    lf = lf.with_columns(store_originals)

    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # --- Compute SA risk weight for guarantor (used for SA guarantors) ---
    lf = _compute_guarantor_rw_sa(lf, cols, config, pack=resolved_pack)

    # --- Basel 3.1 parameter substitution for IRB guarantors (CRE22.70-85) ---
    lf = _apply_parameter_substitution(
        lf,
        cols,
        config,
        use_parameter_substitution,
        origin_pd_col,
        origin_lgd_col,
        origin_pd_pre_floor_col,
        pack=resolved_pack,
    )

    # --- Double default treatment (CRR Art. 153(3), 202-203) ---
    lf = _apply_double_default(lf, cols, config, has_guarantor_pd, pack=resolved_pack)

    # --- Blend RWA and adjust expected loss ---
    ead_col = "ead_final" if "ead_final" in cols else "ead"

    # The Art. 193(1) benefit test on the IRB leg (guarantor RW < borrower IRB
    # RW). Art. 193(1) binds the EXPECTED LOSS amount as well as the RWEA, and
    # Art. 193(3)'s "may amend" reaches the IRB approach explicitly — which is
    # why the basis here is Art. 193 and NOT Art. 113(3) (Chapter 2, SA-only) or
    # Art. 213 (an eligibility gate on the protection contract, gated upstream).
    # Declining rather than applying-and-capping, and the strict ``<``, are both
    # elections the text does not force: the single recorded basis for this flag
    # and every consumer of it is
    # ``engine/sa/rw_adjustments.py::apply_guarantee_substitution``.
    lf = lf.with_columns(
        [
            pl.when(
                (pl.col("guaranteed_portion").fill_null(0) > 0)
                & (pl.col("guarantor_rw").is_not_null())
                & (pl.col("guarantor_rw") < pl.col("risk_weight_irb_original"))
            )
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_guarantee_beneficial"),
        ]
    )

    # The cross-approach CCF carrier is written wherever the CRM guarantee step
    # ran (``engine/crm/guarantees.py::apply_guarantees``), whether or not
    # ``restore_own_irb_exposure_value`` ran before the formulas — the settle
    # step below works from either basis. Keep each swapped leg's CRM-exit
    # (SA-factor) exposure value and covered amount BEFORE redistribution moves
    # them: a leg that stays SA-substituted takes the value back, and a reverted
    # leg's own cover is told apart from cover redistribution moves onto it.
    settles_ccf_swap = CROSS_APPROACH_CCF_OWN_EAD_COL in cols
    if settles_ccf_swap:
        swapped = pl.col(CROSS_APPROACH_CCF_OWN_EAD_COL).is_not_null()
        no_swap = pl.lit(None, dtype=pl.Float64)
        lf = lf.with_columns(
            pl.when(swapped)
            .then(pl.col("ead_after_collateral"))
            .otherwise(no_swap)
            .alias(_SA_CCF_EAD_COL),
            pl.when(swapped)
            .then(pl.col("guaranteed_portion"))
            .otherwise(no_swap)
            .alias(_SA_CCF_COVERED_COL),
        )

    # Redistribute non-beneficial guarantee portions to beneficial guarantors.
    # For multi-guarantor exposures, non-beneficial guarantors' EAD is reallocated
    # to the most beneficial (lowest RW) guarantors using greedy fill.
    from rwa_calc.engine.crm.guarantees import redistribute_non_beneficial

    lf = redistribute_non_beneficial(lf)

    if settles_ccf_swap:
        stored = [expr.meta.output_name() for expr in store_originals]
        lf = _settle_cross_approach_ccf(lf, present={*cols, *stored})

    # Calculate blended RWA using substitution approach. The predicate and the
    # retained share are named once and reused below, so the post-model-adjustment
    # DISCLOSURE carriers cannot drift from the RWA they decompose.
    substituted = (
        (pl.col("guaranteed_portion").fill_null(0) > 0)
        & (pl.col("guarantor_rw").is_not_null())
        & (pl.col("is_guarantee_beneficial"))
    )
    retained_share = (
        pl.when(pl.col(ead_col) > 0)
        .then(pl.col("unguaranteed_portion") / pl.col(ead_col))
        .otherwise(pl.lit(1.0))
        .fill_null(1.0)
    )
    substituted_rwa = pl.col("rwa_irb_original") * retained_share + pl.col(
        "guaranteed_portion"
    ) * pl.col("guarantor_rw")
    blend_exprs = [
        pl.when(substituted)
        .then(substituted_rwa)
        .otherwise(pl.col("rwa_irb_original"))
        .alias("rwa")
    ]
    # PUT THE POST-MODEL-ADJUSTMENT DISCLOSURE CARRIERS ON THE SUBSTITUTED BASIS.
    # ``apply_post_model_adjustments`` runs BEFORE this function, so its four
    # carriers are all measured on the BORROWER basis. PS1/26 Annex II §3.3.1
    # defines OF 08.01 col 0260 as ``0251 + 0252 + 0253 + 0254`` and the published
    # rules state it as live ERROR checks (``boe_b0751`` / ``boe_b0763``). Writing
    # out the blend shows why leaving them alone cannot satisfy it:
    #     rwa = (rwa_pre_adjustments + SUM adj) * share + gp * guarantor_rw
    # so the identity holds only when col 0251 is
    # ``rwa_pre_adjustments * share + gp * guarantor_rw`` and each adjustment is
    # ``adj * share``. Leaving them on the borrower basis overstated the
    # adjustments by ``adj * (1 - share)`` and left col 0251 exceeding col 0260 by
    # exactly the Art. 235 relief (reproduced at 326,708.85 on one guaranteed leg).
    # Scaling is substantively right independently of the identity: only the
    # RETAINED share of a mortgage-floor or unrecognised-exposure overlay survives
    # into the reported RWEA, and the substituted part carries no model overlay at
    # all — which is why the whole ``gp x guarantor_rw`` term lands in the col 0251
    # BASE. Art. 235 relief has no home among the three named adjustment columns
    # and is NOT forced into one. Disclosure carriers only: ``rwa`` above is final
    # and is not read here, so no RWA number moves.
    rebased_disclosure = {
        "rwa_pre_adjustments": pl.col("rwa_pre_adjustments") * retained_share
        + pl.col("guaranteed_portion") * pl.col("guarantor_rw"),
        "post_model_adjustment_rwa": pl.col("post_model_adjustment_rwa") * retained_share,
        "mortgage_rw_floor_adjustment": pl.col("mortgage_rw_floor_adjustment") * retained_share,
        "unrecognised_exposure_adjustment": pl.col("unrecognised_exposure_adjustment")
        * retained_share,
    }
    blend_exprs.extend(
        pl.when(substituted).then(expr).otherwise(pl.col(name)).alias(name)
        for name, expr in rebased_disclosure.items()
        if name in cols
    )
    lf = lf.with_columns(blend_exprs)

    # Calculate blended risk weight for reporting. Guard the divisor so a
    # zero-EAD guaranteed row yields a finite 0.0 rather than 0/0 -> NaN (or
    # x/0 -> inf); .fill_null does not catch a non-finite quotient.
    lf = lf.with_columns(
        [
            pl.when(pl.col(ead_col) > 0)
            .then(pl.col("rwa") / pl.col(ead_col))
            .otherwise(pl.lit(0.0))
            .fill_null(0.0)
            .alias("risk_weight"),
        ]
    )

    # Adjust expected loss for guaranteed portion
    if has_expected_loss:
        lf = _adjust_expected_loss(
            lf, config, ead_col, use_parameter_substitution, pack=resolved_pack
        )
        # ``apply_post_model_adjustments`` also ran before substitution. Rebase
        # its EL disclosure carriers on the effective EL just calculated. The
        # configured general PMA is a firm-level fraction of base EL, so an
        # IRB-guarantor covered share receives the same scalar; an SA-guarantor
        # share contributes no EL and therefore no PMA. Double-default treatment
        # is excluded because it deliberately retains the full obligor EL.
        # NOTE THE ASYMMETRY WITH THE RWA REBASE ABOVE, which SCALES the carriers
        # ``apply_post_model_adjustments`` wrote and is therefore inert wherever
        # that stage wrote zeros. This one RECOMPUTES from the config election,
        # so it must re-apply that stage's ``post_model_adjustments`` pack-feature
        # gate itself. ``el_after_adjustment`` is the Art. 159 EL
        # (``adjustments.art_159_expected_loss``), so a CRR config carrying a
        # non-zero ``pma_el_scalar`` (reachable by direct construction —
        # ``CalculationConfig.crr()`` takes no PMA argument) would otherwise
        # resurrect here a PMA the adjustments stage suppressed, and move CRR
        # CET1 and T2. With the Feature off the scalar is zero: the carriers are
        # still rebased onto the post-CRM EL, with no PS1/26 Art. 158(6A) add-on.
        el_substituted = substituted & ~pl.col("_is_dd_applied")
        el_pma_scalar = (
            float(config.post_model_adjustments.pma_el_scalar)
            if resolved_pack.feature("post_model_adjustments")
            else 0.0
        )
        post_crm_el_pma = pl.max_horizontal(pl.lit(0.0), pl.col("expected_loss") * el_pma_scalar)
        rebased_el_disclosure = {
            "el_pre_adjustment": pl.col("expected_loss"),
            "post_model_adjustment_el": post_crm_el_pma,
            "el_after_adjustment": pl.col("expected_loss") + post_crm_el_pma,
        }
        lf = lf.with_columns(
            pl.when(el_substituted).then(expr).otherwise(pl.col(name)).alias(name)
            for name, expr in rebased_el_disclosure.items()
            if name in cols
        )

    # Seal the effective post-CRM parameters used by each IRB leg.  C 08.03's
    # post-CRM column block reports both the VALUES (cols 0050/0070) and the PD
    # RANGE ROW they sit in off these carriers, so a beneficial PSM-covered leg
    # needs the guarantor's parameters here.  Declined guarantees, retained legs
    # and double-default treatment keep the obligor parameters, which is what
    # makes the post-CRM banding degrade to the obligor banding on a book that
    # never substitutes.  ``reporting_pd_post_crm_pre_floor`` is the same value
    # BEFORE the Art. 160(1)/163(1) input floor — the basis OF 08.03's row axis
    # is stated on.
    parameter_substituted = substituted & pl.col("_is_pd_substitution") & ~pl.col("_is_dd_applied")
    lf = lf.with_columns(
        pl.when(parameter_substituted)
        .then(pl.col("_reporting_pd_post_crm_candidate"))
        .otherwise(pl.col(origin_pd_col))
        .alias("reporting_pd_post_crm"),
        pl.when(parameter_substituted)
        .then(pl.col("_reporting_pd_post_crm_pre_floor_candidate"))
        .otherwise(pl.col(origin_pd_pre_floor_col))
        .alias("reporting_pd_post_crm_pre_floor"),
        pl.when(parameter_substituted)
        .then(pl.col("_reporting_lgd_post_crm_candidate"))
        .otherwise(pl.col(origin_lgd_col))
        .alias("reporting_lgd_post_crm"),
    )

    # Track guarantee status and method for reporting
    lf = _add_guarantee_status_columns(lf)

    # Drop internal tracking columns
    lf = lf.drop(
        "_is_pd_substitution",
        "_is_dd_applied",
        "guarantor_rw_sa",
        "_reporting_pd_post_crm_candidate",
        "_reporting_pd_post_crm_pre_floor_candidate",
        "_reporting_lgd_post_crm_candidate",
    )

    return lf


@cites("CRR Art. 166")
@cites("CRR Art. 193")
@cites("PS1/26, paragraph 166C")
@cites("PS1/26, paragraph 166D")
@cites("PS1/26, paragraph 193")
def restore_own_irb_exposure_value(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Run the IRB formulas of a cross-approach CCF leg on its own exposure value.

    The CRM stage re-values the covered part of an F-IRB / A-IRB leg at the SA
    conversion factor as soon as its guarantor routes to risk-weight
    substitution (``engine/crm/guarantees.py::_apply_cross_approach_ccf``), but
    whether the guarantee is recognised is only decided in
    :func:`apply_guarantee_substitution`. A guarantee that is not recognised
    leaves the exposure value of an IRB exposure with no protection — CRR
    Art. 166(8)-(10) (Art. 193(3) "may amend"; not amending changes nothing) /
    PS1/26 Art. 166A-166D (Art. 193(2A): a disregarded item of protection) —
    and the double-default RWEA is "RW · exposure value · (0.15 + 160 · PD_pp)"
    (CRR Art. 153(3)) on that same value.

    So ``ead_final`` takes ``CROSS_APPROACH_CCF_OWN_EAD_COL`` wherever the CRM
    stage swapped, and the formulas run on it. That value is always positive on
    a swapped leg (the CRM stage swaps only a leg with a positive covered amount,
    which is part of it); the ``> 0`` guard is defensive, keeping the formulas
    off a zero basis on a hand-built frame.

    This step decides no result on its own: :func:`apply_guarantee_substitution`
    puts every swapped leg on its final value — the own one, or the SA-factor
    one where the guarantee ends SA risk-weight substituted — by rescaling the
    IRB amounts from whatever value they were computed on (all linear in
    ``ead_final``), so a chain that skips this step settles to the same figures.
    Running it first means the main population, a declined guarantee, needs no
    rescale at all. ``IRBCalculator`` runs it immediately before
    :func:`~rwa_calc.engine.irb.transforms.apply_all_formulas`. An absent
    carrier (a frame that never passed the CRM guarantee step) or a null one
    (no swap on that row) leaves ``ead_final`` untouched.

    References:
        CRR Art. 166(8)-(10), 193(1)/(3), 153(3); PS1/26 Art. 166C, 166D,
        193(2A) (P1.398)
    """
    # A selector, so a frame without the carrier needs no schema probe: it then
    # selects nothing and the coalesce falls through to the typed null.
    own_ead = pl.coalesce(
        cs.by_name(CROSS_APPROACH_CCF_OWN_EAD_COL, require_all=False),
        pl.lit(None, dtype=pl.Float64),
    )
    return lf.with_columns(
        pl.when(own_ead > 0).then(own_ead).otherwise(pl.col("ead_final")).alias("ead_final")
    )


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


@cites("CRR Art. 153(3)")
@cites("CRR Art. 166")
@cites("CRR Art. 236")
def _settle_cross_approach_ccf(lf: pl.LazyFrame, *, present: set[str]) -> pl.LazyFrame:
    """Keep the SA conversion factor only on a leg that stays SA-substituted.

    A swapped leg (``CROSS_APPROACH_CCF_OWN_EAD_COL`` not null) has two values:
    its OWN IRB exposure value (the carrier) and its CRM-exit value on the SA
    factor (``_SA_CCF_EAD_COL``, captured before ``redistribute_non_beneficial``).
    Its final value depends on the outcome:

    - **Kept** — SA risk-weight substituted (beneficial, neither parameter-
      substituted nor double default): the SA-factor value, the basis of the
      covered part under that method. Portions and CCF carriers stay as the CRM
      stage left them.
    - **Reverted** — declined, or double default (Art. 153(3) prices the IRB
      exposure value): the own value. ``ccf_guaranteed`` returns to
      ``ccf_original`` so the reported CCF and the exposure value agree;
      ``ead_from_ccf`` moves by exactly the exposure-value move;
      ``ead_after_guarantee`` (an output carrier no template reads), where the
      frame has it, takes the own value, since no substitution happened.

    THE IRB AMOUNTS ARE RESCALED FROM WHATEVER VALUE THEY WERE COMPUTED ON. Every
    amount the formulas, the defaulted treatment and the post-model adjustments
    derive from ``ead_final`` — and the pre-substitution copies taken from them —
    is LINEAR in it, so each is multiplied by ``final value / ead_final on
    entry``. That makes the outcome independent of whether
    :func:`restore_own_irb_exposure_value` ran before the formulas (the
    ``IRBCalculator`` chain, where entry is the own value) or not (a composition
    that skipped it, where entry is the CRM-exit value): either way a leg leaves
    with the amounts it would have had with no swap at all, to floating-point
    rounding. A rescale cannot repair amounts computed on a ZERO ``ead_final``
    whose final value is not zero, so such a leg is left exactly as it reached
    this function. No frame from the CRM stage produces one — the restore puts
    the positive own value on every swapped leg, and the CRM-exit value of a
    swapped leg is positive too (a 0% SA factor leaves its exposure value on the
    own one: ``_apply_cross_approach_ccf`` re-reads the covered amount it has just
    zeroed) — so the guard is for a hand-built frame.

    THE PORTIONS OF A REVERTED LEG. ``guarantee_ratio`` is the leg's pre-swap
    covered share (``_apply_cross_approach_ccf``), so its own covered and
    uncovered amounts are ``own x ratio`` and ``own x (1 - ratio)`` — not the
    CRM-exit portions times ``own / SA``, which is wrong wherever the uncovered
    part never left the own factor. ``redistribute_non_beneficial`` has already
    run on the CRM-exit amounts, and the two things it can have done are kept
    apart:

    - a row it ZEROED (a non-beneficial guarantor in a group with a beneficial
      one) keeps its zero portions: its cover was handed to another row;
    - a row it FILLED (a double-default row in such a group) keeps the absorbed
      amount UNSCALED — it is another row's cover, not this row's — and only up
      to the protection still unused on the own basis,
      ``original_guarantee_amount - own x ratio``: the covered portion never
      exceeds the protection amount GA (CRR Art. 236(1)/(3)). Without that bound
      the absorbed amount, measured against headroom on the SA basis, could
      take the row past GA.

    ``ead_after_collateral`` is then ``guaranteed + unguaranteed`` on the row,
    as ``redistribute_non_beneficial`` sets it for a guarantor row, and the
    double-default protection amount (C 08.01 col 0220, set from the
    pre-redistribution cover) becomes the own covered amount. So
    ``guaranteed_portion + unguaranteed_portion == ead_final`` holds on a
    reverted leg redistribution did not touch, and does NOT hold on one it did:
    a zeroed row keeps its whole own ``ead_final`` and RWEA with zero portions,
    and a filled row's covered portion includes cover from its co-guarantor's
    exposure. Both are ``redistribute_non_beneficial``'s own behaviour (its
    headroom compares the CCF = 100% ``original_guarantee_amount`` with a
    post-CCF ``guaranteed_portion``), present before P1.398 and left as it is.

    Runs after ``redistribute_non_beneficial`` and before the RWA blend reads
    ``guaranteed_portion`` and ``ead_final``. ``present`` is the frame's column
    set, which names the amounts to rescale.
    """
    ead_linear = (
        "rwa",
        "expected_loss",
        "rwa_irb_original",
        "pre_crm_rwa",
        "expected_loss_irb_original",
        "rwa_pre_adjustments",
        "post_model_adjustment_rwa",
        "mortgage_rw_floor_adjustment",
        "unrecognised_exposure_adjustment",
        "el_pre_adjustment",
        "post_model_adjustment_el",
        "el_after_adjustment",
    )
    own_ead = pl.col(CROSS_APPROACH_CCF_OWN_EAD_COL).clip(lower_bound=0.0)
    sa_ead = pl.col(_SA_CCF_EAD_COL).clip(lower_bound=0.0)
    entry_ead = pl.col("ead_final")
    swapped = pl.col(CROSS_APPROACH_CCF_OWN_EAD_COL).is_not_null()
    kept = (
        swapped
        & pl.col("is_guarantee_beneficial")
        & ~pl.col("_is_pd_substitution")
        & ~pl.col("_is_dd_applied")
    )
    final_ead = pl.when(kept).then(sa_ead).otherwise(own_ead)
    stranded = (entry_ead <= 0) & (final_ead > 0)
    settles = swapped & ~stranded
    reverted = settles & ~kept
    scale = pl.when(entry_ead > 0).then(final_ead / entry_ead).otherwise(pl.lit(1.0))

    # The reverted leg's own portions, kept apart from what redistribution did.
    ratio = pl.col("guarantee_ratio")
    own_covered = own_ead * ratio
    covered_before = pl.col(_SA_CCF_COVERED_COL)
    covered_after = pl.col("guaranteed_portion")
    zeroed = covered_after < covered_before
    # ``original_guarantee_amount`` is written by the same CRM guarantee step as
    # the carrier, on every row it emits (``_apply_guarantee_splits``).
    unused_protection = (pl.col("original_guarantee_amount") - own_covered).clip(lower_bound=0.0)
    absorbed = pl.min_horizontal(
        (covered_after - covered_before).clip(lower_bound=0.0), unused_protection
    )
    reverted_covered = pl.when(zeroed).then(covered_after).otherwise(own_covered + absorbed)
    reverted_uncovered = (
        pl.when(zeroed).then(pl.col("unguaranteed_portion")).otherwise(own_ead * (1.0 - ratio))
    )

    def _on_reverted(name: str, value: pl.Expr) -> pl.Expr:
        return pl.when(reverted).then(value).otherwise(pl.col(name)).alias(name)

    settled = [
        _on_reverted("guaranteed_portion", reverted_covered),
        _on_reverted("unguaranteed_portion", reverted_uncovered),
        _on_reverted("ead_after_collateral", reverted_covered + reverted_uncovered),
        _on_reverted("ead_from_ccf", pl.col("ead_from_ccf") + own_ead - sa_ead),
        _on_reverted("ccf_guaranteed", pl.col("ccf_original")),
        # C 08.01 col 0220: always present (``_apply_double_default`` writes it on
        # both of its branches), non-zero only where double default is eligible.
        _on_reverted(
            "double_default_unfunded_protection",
            pl.when(pl.col("double_default_unfunded_protection") > 0)
            .then(own_covered)
            .otherwise(pl.col("double_default_unfunded_protection")),
        ),
        pl.when(settles).then(final_ead).otherwise(pl.col("ead_final")).alias("ead_final"),
        # Written by the CRM stage's ``_finalize_ead`` only, so absent from a frame
        # taken straight from ``apply_guarantees``: the selector then expands to
        # nothing. The selector sits in ``then`` so the output keeps its name.
        pl.when(~reverted)
        .then(cs.by_name("ead_after_guarantee", require_all=False))
        .otherwise(own_ead),
    ]
    settled.extend(
        pl.when(settles).then(pl.col(name) * scale).otherwise(pl.col(name)).alias(name)
        for name in ead_linear
        if name in present
    )
    return lf.with_columns(settled).drop(_SA_CCF_EAD_COL, _SA_CCF_COVERED_COL)


@cites("CRR Art. 122")
@cites("CRR Art. 235")
def _compute_guarantor_rw_sa(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Compute the guarantor's SA risk weight via the shared builder.

    Compiles ``build_guarantor_rw_expr`` (data/tables/guarantor_rw.py) with
    the IRB chain's column names — the same branch chain and order as the
    SA-side twin (engine/sa/namespace.py::_build_guarantor_rw_expr). This
    closes the IRB-guarantor PSE / RGLA substitution gap (the recorded
    Phase 4 fix) plus the IO 0%, named-MDB 0% and MDB Table 2B closures, and
    carries the CRR Art. 116(5) gate on a third-country PSE guarantor's own
    jurisdiction. ``pse`` is an IRB class in neither shipped permission set (CRR
    ``full_irb`` has no entry; Basel 3.1 ``full_irb_b31`` pins it to SA), so with
    them a PSE guarantor always takes this RWSM path.
    """

    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # Ensure guarantor_exposure_class is available (set by CRM processor;
    # fallback for unit tests that construct LazyFrames directly)
    if "guarantor_exposure_class" not in cols:
        from rwa_calc.engine.entity_class_maps import entity_type_to_sa_class

        lf = lf.with_columns(
            pl.col("guarantor_entity_type")
            .fill_null("")
            .replace_strict(entity_type_to_sa_class(resolved_pack), default="")
            .alias("guarantor_exposure_class"),
        )

    _gec = pl.col("guarantor_exposure_class").fill_null("")

    # Art. 114(4)/(7): Domestic CGCB guarantors -> 0% RW regardless of CQS.
    # Evaluate the domestic-currency (denomination) test against the guarantee
    # currency (the currency of the substituted exposure to the sovereign); the
    # Art. 233(3) 8% FX haircut separately handles any mismatch between the
    # guarantee and the underlying exposure. Fall back to the exposure's pre-FX
    # denomination when `guarantee_currency` is missing (legacy / no-guarantee
    # rows). Art. 235(3): the 0% extension additionally requires the exposure to
    # be *funded* in the domestic currency, so the funding limb (null-PERMISSIVE
    # fallback to the denomination — see `funding_currency_expr`) is ANDed in.
    _irb_schema_names = lf.collect_schema().names()
    _has_country = "guarantor_country_code" in _irb_schema_names
    _has_exposure_ccy_irb = (
        "original_currency" in _irb_schema_names or "currency" in _irb_schema_names
    )
    _has_guarantee_ccy_irb = "guarantee_currency" in _irb_schema_names
    if _has_guarantee_ccy_irb and _has_exposure_ccy_irb:
        _ccy_expr_irb = pl.col("guarantee_currency").fill_null(
            denomination_currency_expr(_irb_schema_names)
        )
    elif _has_guarantee_ccy_irb:
        _ccy_expr_irb = pl.col("guarantee_currency")
    elif _has_exposure_ccy_irb:
        _ccy_expr_irb = denomination_currency_expr(_irb_schema_names)
    else:
        _ccy_expr_irb = None

    _is_domestic_guarantor = (
        build_domestic_cgcb_guarantor_expr(
            "guarantor_country_code", _ccy_expr_irb, funding_currency_expr(_irb_schema_names)
        )
        if _has_country and _ccy_expr_irb is not None
        else pl.lit(False)
    )

    # The shared expression reads the guarantor's country (the Art. 116(5) PSE
    # gate and the unrated PSE/RGLA fallback), equivalence flag (Art. 116(5))
    # and SCRA grade (B31 unrated institutions). The
    # CRM guarantee join (engine/crm/guarantees.py) always carries them; inject
    # typed nulls for a direct (non-pipeline) invocation that skipped it.
    lf = ensure_guarantor_rw_columns(lf, _irb_schema_names)

    return lf.with_columns(
        build_guarantor_rw_expr(
            exposure_class_col="guarantor_exposure_class",
            entity_type_col="guarantor_entity_type",
            cqs_col="guarantor_cqs",
            country_code_col="guarantor_country_code",
            equivalence_col="guarantor_is_equivalent_jurisdiction",
            scra_grade_col="guarantor_scra_grade",
            is_basel_3_1=resolved_pack.feature("sa_revised_risk_weight_tables"),
            domestic_cgcb_expr=_is_domestic_guarantor,
            # No borrower-maturity short-term flag is threaded on the IRB
            # path today (the SA twin derives one from its own stage
            # scratch); long-term Table 3 applies throughout.
            short_term_flag_col=None,
            no_guarantee_expr=pl.col("guaranteed_portion").fill_null(0) <= 0,
        ).alias("guarantor_rw_sa"),
    )


def _apply_parameter_substitution(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    use_parameter_substitution: bool,
    origin_pd_col: str,
    origin_lgd_col: str,
    origin_pd_pre_floor_col: str,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Apply parameter substitution for IRB guarantors (CRR Art. 161(3) /
    Basel 3.1 CRE22.70-85). The F-IRB supervisory LGD is selected per row
    by guarantor seniority and (Basel 3.1 only) FSE status:

    - subordinated guarantor       -> 0.75  (Art. 161(1)(b), both frameworks)
    - senior + FSE guarantor (B31) -> 0.45  (Art. 161(1)(a))
    - senior + non-FSE guarantor   -> 0.40 B31 / 0.45 CRR (Art. 161(1)(aa)/(a))

    Also enforces the "no better than direct" output floor (Art. 160(4)):
    after computing ``guarantor_rw_irb`` from PSM, derive ``RW_direct`` —
    the IRB risk weight the guarantor would attract as a *direct* borrower
    (using the guarantor's own exposure class, floored PD, and F-IRB LGD)
    — and expose ``guarantor_rw_post_nbd = max(guarantor_rw_irb, RW_direct)``.
    The downstream beneficial-gate uses ``guarantor_rw_post_nbd``.
    """
    if not use_parameter_substitution:
        # No guarantor PD anywhere in the frame -> SA RW substitution for every
        # row. This is a SCHEMA test, not a regime test: ``guarantor_pd`` drives
        # it (see the caller), so the parameter-substitution path is live under
        # CRR too whenever a modelled guarantor PD is supplied.
        return lf.with_columns(
            [
                pl.col("guarantor_rw_sa").alias("guarantor_rw"),
                pl.lit(False).alias("_is_pd_substitution"),
                pl.col(origin_pd_col).alias("_reporting_pd_post_crm_candidate"),
                pl.col(origin_pd_pre_floor_col).alias("_reporting_pd_post_crm_pre_floor_candidate"),
                pl.col(origin_lgd_col).alias("_reporting_lgd_post_crm_candidate"),
            ]
        )

    firb_lgd_senior, firb_lgd_senior_fse, firb_lgd_subordinated = _firb_lgd_tuple(pack)

    lf = _ensure_parameter_substitution_columns(lf, cols)

    # Floor the guarantor's PD using the GUARANTOR's exposure class context
    # (Art. 160(4) / 163(1)): the guaranteed portion is economically
    # equivalent to a direct exposure to the guarantor, so the guarantor's
    # class floor governs. For a corporate guarantor under B31 the floor is
    # 0.0005 (Art. 163(1)(a)) — not the borrower's QRRE-revolver floor of
    # 0.0010. Guarantors are not QRRE in our model, so the transactor flag
    # is intentionally disabled for the guarantor floor.
    pd_floor_expr = _pd_floor_expression(
        config,
        has_transactor_col=False,
        exposure_class_col="guarantor_exposure_class",
        pack=pack,
    )
    guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

    scaling_factor = scalar_value(pack.scalar_param("irb_scaling_factor"))
    eur_gbp_rate = float(config.eur_gbp_rate)

    # Per-row F-IRB supervisory LGD selection (Art. 161(1)(a)/(aa)/(b)).
    # Missing seniority defaults to "senior". This is the option (ii) LGD
    # — the supervisory LGD for a direct obligation of the guarantor's
    # seniority — which is also used unconditionally for the Art. 160(4)
    # "no better than direct" floor regardless of psm_lgd_source.
    guarantor_supervisory_lgd_expr = _guarantor_supervisory_lgd_expr(
        firb_lgd_senior=firb_lgd_senior,
        firb_lgd_senior_fse=firb_lgd_senior_fse,
        firb_lgd_subordinated=firb_lgd_subordinated,
    )

    psm_lgd_expr = _psm_lgd_expr(config, guarantor_supervisory_lgd_expr)

    # Compute IRB risk weight from guarantor's PD and the chosen PSM LGD.
    # Per Art. 236(1)(a)(i) (PRA PS1/26): the PSM substitutes the guarantor's
    # PD/LGD AND derives the correlation R from the GUARANTOR's exposure
    # class context, not the borrower's. ``_parametric_irb_risk_weight_expr``
    # reads ``exposure_class``, ``turnover_m``, ``requires_fi_scalar`` and
    # ``is_qrre_transactor`` from the LazyFrame — so we compute both
    # ``guarantor_rw_irb`` (PSM) and ``rw_direct`` (Art. 160(4) NBD floor)
    # inside a single swap-restore window where those columns hold the
    # guarantor's values. The NBD floor always uses the option_ii
    # supervisory LGD so the comparison stays meaningful for option_i rows.
    sme_turnover_m = (
        float(regulatory_threshold(pack, "sme_turnover_threshold", config.eur_gbp_rate)) / 1_000_000
    )
    lf = _apply_no_better_than_direct_floor(
        lf,
        guarantor_pd_floored=guarantor_pd_floored,
        psm_lgd_expr=psm_lgd_expr,
        direct_lgd_expr=guarantor_supervisory_lgd_expr,
        scaling_factor=scaling_factor,
        eur_gbp_rate=eur_gbp_rate,
        is_b31=pack.feature("irb_correlation_sme_gbp_native"),
        sme_turnover_threshold_m=sme_turnover_m,
    )

    # Select method: IRB guarantor under Basel 3.1 -> parameter substitution,
    # SA guarantor -> SA RW substitution. The "no better than direct" floor
    # applies to the IRB-substituted RW only.
    is_irb_guarantor = (pl.col("guarantor_approach").fill_null("") == "irb") & pl.col(
        "guarantor_pd"
    ).is_not_null()

    return lf.with_columns(
        [
            pl.when(is_irb_guarantor)
            .then(pl.col("guarantor_rw_post_nbd"))
            .otherwise(pl.col("guarantor_rw_sa"))
            .alias("guarantor_rw"),
            # Preserve the exact risk parameters used by parameter substitution.
            # C 08.03's post-CRM column block reads them for both its values and
            # its PD-range row, so they must be the parameters actually applied
            # to each covered leg.  These candidates are gated by the final
            # beneficial / double-default decision in the caller before becoming
            # reporting carriers.
            pl.when(is_irb_guarantor)
            .then(guarantor_pd_floored)
            .otherwise(pl.col(origin_pd_col))
            .alias("_reporting_pd_post_crm_candidate"),
            # The same substituted PD BEFORE the Art. 163(1) floor
            # ``guarantor_pd_floored`` applies — OF 08.03 bands its rows on the
            # pre-input-floor PD, so the post-CRM banding needs the raw estimate.
            pl.when(is_irb_guarantor)
            .then(pl.col("guarantor_pd"))
            .otherwise(pl.col(origin_pd_pre_floor_col))
            .alias("_reporting_pd_post_crm_pre_floor_candidate"),
            pl.when(is_irb_guarantor)
            .then(
                pl.when(pl.col("guarantor_rw_irb") >= pl.col("rw_direct"))
                .then(psm_lgd_expr)
                .otherwise(guarantor_supervisory_lgd_expr)
            )
            .otherwise(pl.col(origin_lgd_col))
            .alias("_reporting_lgd_post_crm_candidate"),
            # Track which method is being used per-row
            pl.when((pl.col("guaranteed_portion").fill_null(0) > 0) & is_irb_guarantor)
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("_is_pd_substitution"),
        ]
    )


def _firb_lgd_tuple(pack: ResolvedRulepack) -> tuple[float, float, float]:
    """Return (senior, senior_fse, subordinated) F-IRB supervisory LGDs.

    The FSE-specific senior key only exists in the Basel 3.1 table; CRR has
    no FSE split (Art. 161(1)(a) covers all senior unsecured at 45%).
    """
    firb_lgd_table = firb_supervisory_lgd_values(pack)
    firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])
    firb_lgd_senior_fse = float(
        firb_lgd_table.get("unsecured_senior_fse", firb_lgd_table["unsecured_senior"])
    )
    firb_lgd_subordinated = float(firb_lgd_table["subordinated"])
    return firb_lgd_senior, firb_lgd_senior_fse, firb_lgd_subordinated


def _ensure_parameter_substitution_columns(lf: pl.LazyFrame, cols: list[str]) -> pl.LazyFrame:
    """Add the columns required by ``_parametric_irb_risk_weight_expr`` when
    missing. No-op if all expected columns are already present.
    """
    defaults: list[tuple[str, pl.Expr]] = [
        ("turnover_m", pl.lit(None).cast(pl.Float64)),
        ("requires_fi_scalar", pl.lit(False)),
        ("has_one_day_maturity_floor", pl.lit(False)),
        ("guarantor_seniority", pl.lit(None).cast(pl.String)),
        ("guarantor_is_financial_sector_entity", pl.lit(False)),
    ]
    ensure_cols = [expr.alias(name) for name, expr in defaults if name not in cols]
    if not ensure_cols:
        return lf
    return lf.with_columns(ensure_cols)


def _guarantor_supervisory_lgd_expr(
    *,
    firb_lgd_senior: float,
    firb_lgd_senior_fse: float,
    firb_lgd_subordinated: float,
) -> pl.Expr:
    """Build the per-row F-IRB supervisory LGD expression (Art. 161(1))."""
    seniority = pl.col("guarantor_seniority").cast(pl.String).fill_null("senior")
    is_fse = pl.col("guarantor_is_financial_sector_entity").fill_null(False)
    return (
        pl.when(seniority == "subordinated")
        .then(pl.lit(firb_lgd_subordinated))
        .when(is_fse)
        .then(pl.lit(firb_lgd_senior_fse))
        .otherwise(pl.lit(firb_lgd_senior))
    )


def _psm_lgd_expr(config: CalculationConfig, guarantor_supervisory_lgd_expr: pl.Expr) -> pl.Expr:
    """Select the PSM LGD per ``psm_lgd_source`` (Art. 236(1)(a)(i)).

    Option (i) returns the borrower's own unprotected LGD (read from
    ``lgd``, which by this stage carries the seniority-correct borrower
    supervisory value from ``transforms.apply_firb_lgd``). ``lgd_pre_crm``
    is unsuitable because the CRM processor initialises it to the raw input
    ``lgd`` (often null for F-IRB inputs, falling back to the 45% default).

    Option (ii) returns the guarantor supervisory LGD expression — the
    historical engine default.
    """
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    if config.irb_permissions.psm_lgd_source == "option_i":  # ty: ignore[unresolved-attribute]
        return pl.col("lgd")
    return guarantor_supervisory_lgd_expr


def _apply_no_better_than_direct_floor(
    lf: pl.LazyFrame,
    *,
    guarantor_pd_floored: pl.Expr,
    psm_lgd_expr: pl.Expr,
    direct_lgd_expr: pl.Expr,
    scaling_factor: float,
    eur_gbp_rate: float,
    is_b31: bool,
    sme_turnover_threshold_m: float,
) -> pl.LazyFrame:
    """Compute ``guarantor_rw_irb``, ``rw_direct`` and ``guarantor_rw_post_nbd``.

    ``_parametric_irb_risk_weight_expr`` reads the borrower's exposure-class
    and correlation-driving columns (``exposure_class``, ``turnover_m``,
    ``requires_fi_scalar``, ``is_qrre_transactor``) from the LazyFrame. Per
    Art. 236(1)(a)(i) (PRA PS1/26) the PSM correlation must be derived from
    the **guarantor's** class context, and per Art. 160(4) the same applies
    to the "no better than direct" floor — so we compute both inside a single
    swap-restore window where those columns hold guarantor-specific values.

    Two LGDs are accepted to support the ``psm_lgd_source`` switch:
    - ``psm_lgd_expr``: the LGD used for the PSM RW (option_i = borrower's
      pre-CRM LGD, option_ii = guarantor supervisory LGD).
    - ``direct_lgd_expr``: the LGD used for the Art. 160(4) NBD direct RW
      — always the option_ii guarantor supervisory LGD so the floor stays
      meaningful regardless of the option chosen for the PSM.

    Adds three columns:
    - ``guarantor_rw_irb``: PSM RW from guarantor's PD and the PSM LGD.
    - ``rw_direct``: IRB RW the guarantor would attract as a direct borrower
      (always uses the option_ii guarantor supervisory LGD).
    - ``guarantor_rw_post_nbd``: max(guarantor_rw_irb, rw_direct).
    """
    schema_names = lf.collect_schema().names()

    # Stash the borrower's class-driving columns so we can restore them after
    # computing the guarantor-direct RW. The maturity column is left as-is —
    # the parametric formula caps M at 5y and floors at 1y; using the
    # borrower's M is conservative for the direct-to-guarantor RW.
    stash_cols = [
        pl.col("exposure_class").alias("_nbd_borrower_exposure_class"),
        pl.col("turnover_m").alias("_nbd_borrower_turnover_m"),
        pl.col("requires_fi_scalar").alias("_nbd_borrower_requires_fi_scalar"),
    ]
    if "is_qrre_transactor" in schema_names:
        stash_cols.append(pl.col("is_qrre_transactor").alias("_nbd_borrower_is_qrre_transactor"))

    lf = lf.with_columns(stash_cols)

    # Swap in guarantor-driving values. Guarantor-specific turnover is not
    # carried through CRM today, so disable the SME correlation adjustment
    # by setting turnover_m to NULL. Ditto requires_fi_scalar (the FI scalar
    # is a property of the borrower's own corporate exposure under
    # Art. 153(2) and does not transfer to the guarantor's PSM correlation).
    swap_cols = [
        pl.col("guarantor_exposure_class").alias("exposure_class"),
        pl.lit(None).cast(pl.Float64).alias("turnover_m"),
        pl.lit(False).alias("requires_fi_scalar"),
    ]
    if "is_qrre_transactor" in schema_names:
        swap_cols.append(pl.lit(False).alias("is_qrre_transactor"))

    lf = lf.with_columns(swap_cols)

    # Evaluate the parametric IRB RW with the guarantor's class context.
    # Both the PSM RW (Art. 236(1)(a)(i)) and the NBD direct RW (Art. 160(4))
    # use the same guarantor-class formula here — the guarantor_rw_irb /
    # rw_direct split is preserved for downstream reporting and the
    # max-horizontal floor below.
    psm_rw_expr = _parametric_irb_risk_weight_expr(
        pd_expr=guarantor_pd_floored,
        lgd=psm_lgd_expr,
        scaling_factor=scaling_factor,
        eur_gbp_rate=eur_gbp_rate,
        is_b31=is_b31,
        sme_turnover_threshold_m=sme_turnover_threshold_m,
    )
    rw_direct_expr = _parametric_irb_risk_weight_expr(
        pd_expr=guarantor_pd_floored,
        lgd=direct_lgd_expr,
        scaling_factor=scaling_factor,
        eur_gbp_rate=eur_gbp_rate,
        is_b31=is_b31,
        sme_turnover_threshold_m=sme_turnover_threshold_m,
    )
    lf = lf.with_columns(
        [
            psm_rw_expr.alias("guarantor_rw_irb"),
            rw_direct_expr.alias("rw_direct"),
        ]
    )

    # Restore the borrower's original class-driving columns.
    restore_cols = [
        pl.col("_nbd_borrower_exposure_class").alias("exposure_class"),
        pl.col("_nbd_borrower_turnover_m").alias("turnover_m"),
        pl.col("_nbd_borrower_requires_fi_scalar").alias("requires_fi_scalar"),
    ]
    if "is_qrre_transactor" in schema_names:
        restore_cols.append(
            pl.col("_nbd_borrower_is_qrre_transactor").alias("is_qrre_transactor"),
        )
    lf = lf.with_columns(restore_cols)

    # Drop the stash columns and emit the NBD-floored guarantor RW.
    drop_cols = [
        "_nbd_borrower_exposure_class",
        "_nbd_borrower_turnover_m",
        "_nbd_borrower_requires_fi_scalar",
    ]
    if "is_qrre_transactor" in schema_names:
        drop_cols.append("_nbd_borrower_is_qrre_transactor")
    lf = lf.drop(drop_cols)

    return lf.with_columns(
        pl.max_horizontal(pl.col("guarantor_rw_irb"), pl.col("rw_direct")).alias(
            "guarantor_rw_post_nbd"
        ),
    )


def _apply_double_default(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    has_guarantor_pd: bool,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Apply double default treatment (CRR Art. 153(3), 202-203).

    A covered leg is DD-eligible when the underlying is corporate, the protection
    provider is on the Art. 202 list (``_double_default_provider_expr``), the
    provider has an internal PD and the beneficiary is A-IRB. DD is then applied
    only where RW_dd is below the substitution RW.
    """
    use_double_default = (
        pack.feature("double_default_treatment")
        and config.enable_double_default
        and has_guarantor_pd
    )
    if not use_double_default:
        return lf.with_columns(
            [
                pl.lit(False).alias("is_double_default_eligible"),
                pl.lit(0.0).alias("double_default_unfunded_protection"),
                pl.lit(None).cast(pl.Float64).alias("irb_lgd_double_default"),
                pl.lit(False).alias("_is_dd_applied"),
            ]
        )

    # Art. 217(1)(a)(i): the underlying is corporate (not sovereign, institution,
    # retail, equity, SL).
    _exp_class_upper = pl.col("exposure_class").cast(pl.String).fill_null("").str.to_uppercase()
    _is_corporate_underlying = _exp_class_upper.str.contains("CORPORATE")

    # Art. 202: the protection provider is an institution or bank guarantor.
    _is_eligible_guarantor_type = _double_default_provider_expr()

    # Art. 153(3): RW_dd needs the protection provider's internal PD.
    _has_guarantor_pd = pl.col("guarantor_pd").is_not_null()

    # Firm uses A-IRB (own LGD estimates) -- check is_airb column
    _is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in cols else pl.lit(False)

    # Combined eligibility
    _is_dd_eligible = (
        (pl.col("guaranteed_portion").fill_null(0) > 0)
        & _is_corporate_underlying
        & _is_eligible_guarantor_type
        & _has_guarantor_pd
        & _is_airb
    )

    # Floor guarantor PD using the guarantor's own class floor (Art. 163(1)).
    pd_floor_expr_dd = _pd_floor_expression(
        config,
        has_transactor_col=False,
        exposure_class_col="guarantor_exposure_class",
        pack=pack,
    )
    guarantor_pd_floored_dd = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr_dd)

    # Double default multiplier: (0.15 + 160 x PD_g)
    dd_multiplier = _double_default_multiplier_expr(guarantor_pd_floored_dd)

    # RW_dd = RW_obligor x multiplier (risk_weight_irb_original already = K x 12.5 x s x MA).
    # CRR Art. 153(3) carries NO "not lower than a direct exposure to the protection
    # provider" floor (that was Basel II para 286, not onshored), so rw_dd is compared
    # unfloored against the substitution RW in the beneficial gate below.
    rw_dd = pl.col("risk_weight_irb_original") * dd_multiplier

    return lf.with_columns(
        [
            _is_dd_eligible.alias("is_double_default_eligible"),
            # Override guarantor_rw with DD RW when eligible and beneficial vs. substitution
            pl.when(_is_dd_eligible & (rw_dd < pl.col("guarantor_rw")))
            .then(rw_dd)
            .otherwise(pl.col("guarantor_rw"))
            .alias("guarantor_rw"),
            # Track DD-specific columns
            pl.when(_is_dd_eligible)
            .then(pl.col("guaranteed_portion"))
            .otherwise(pl.lit(0.0))
            .alias("double_default_unfunded_protection"),
            pl.when(_is_dd_eligible)
            .then(pl.col("lgd_floored") if "lgd_floored" in cols else pl.col("lgd"))
            .otherwise(pl.lit(None).cast(pl.Float64))
            .alias("irb_lgd_double_default"),
            # Track DD method — True only when actual double-default treatment is
            # applied (eligible AND beneficial vs. plain substitution). PD substitution
            # is tracked independently via _is_pd_substitution.
            pl.when(_is_dd_eligible & (rw_dd < pl.col("guarantor_rw")))
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("_is_dd_applied"),
        ]
    )


@cites("CRR Art. 202")
def _double_default_provider_expr() -> pl.Expr:
    """Whether the guarantor may provide Art. 153(3) double-default protection.

    CRR Art. 202 admits only "institutions, investment firms, insurance and
    reinsurance undertakings and export credit agencies" as providers. Of the input
    entity types only those in ``data.schemas.DOUBLE_DEFAULT_PROVIDER_ENTITY_TYPES``
    (``institution``, ``bank``) are certainly on that list. Sovereigns, central
    banks, MDBs, international organisations, RGLAs, PSEs, CCPs, generic financial
    institutions and corporates never qualify, whatever their rating: insurers are
    on the list but cannot be told apart from other corporates, and a generic
    financial institution may be an investment firm or a non-listed holding company.

    The guarantor must also still hold the institution exposure class. The Art. 201
    gate (``engine/crm/guarantor_eligibility.py``) clears the class of a rejected
    guarantor but keeps its entity type, so the entity type alone is not enough.

    Not tested here: Art. 202(a) expertise, (b) regulated-equivalent OR an ECAI
    assessment of CQS 3 or better, and (c)/(d) an internal PD no worse than the
    firm's PD for corporate CQS 2 (when the protection was provided, or at any time
    after) and for corporate CQS 3 (now). They need inputs the schema does not
    carry: an attestation and the firm's own grade-to-PD mapping, which is not a
    regulatory value.
    """
    is_institution_class = pl.col("guarantor_exposure_class").eq_missing(
        ExposureClass.INSTITUTION.value
    )
    is_listed_entity_type = pl.col("guarantor_entity_type").is_in(
        list(DOUBLE_DEFAULT_PROVIDER_ENTITY_TYPES), nulls_equal=True
    )
    return is_institution_class & is_listed_entity_type


def _adjust_expected_loss(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    ead_col: str,
    use_parameter_substitution: bool,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Adjust expected loss for guaranteed portion.

    SA guarantor: SA has no EL concept; only the unguaranteed portion retains EL.
    IRB guarantor: blend borrower EL (unguaranteed) + guarantor EL (guaranteed)
        per CRR Art. 161(3) / Basel 3.1 CRE22.70-85, using the framework's
        F-IRB supervisory LGD (0.45 CRR / 0.40 Basel 3.1).
    Double-default exposures (CRR Art. 153(3)) retain the full obligor EL —
        DD modifies K, not EL.
    """
    _base_el = (
        (pl.col("guaranteed_portion").fill_null(0) > 0)
        & (pl.col("guarantor_rw").is_not_null())
        & (pl.col("is_guarantee_beneficial"))
    )
    _el_unguaranteed = pl.col("expected_loss_irb_original") * (
        pl.col("unguaranteed_portion") / pl.col(ead_col)
    ).fill_null(1.0)

    if use_parameter_substitution:
        firb_lgd_table = firb_supervisory_lgd_values(pack)
        firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])
        firb_lgd_senior_fse = float(
            firb_lgd_table.get("unsecured_senior_fse", firb_lgd_table["unsecured_senior"])
        )
        firb_lgd_subordinated = float(firb_lgd_table["subordinated"])

        # Mirror the guarantor-context PD floor used in _apply_parameter_substitution
        # so EL is computed against the same floored guarantor PD as RW.
        pd_floor_expr = _pd_floor_expression(
            config,
            has_transactor_col=False,
            exposure_class_col="guarantor_exposure_class",
            pack=pack,
        )
        guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

        _is_dd_applied = pl.col("_is_dd_applied")
        _is_irb_non_dd = pl.col("_is_pd_substitution") & ~_is_dd_applied

        # Mirror the per-row F-IRB LGD selection used in _apply_parameter_substitution
        # so EL is computed against the same supervisory LGD as RW. Both columns
        # are guaranteed present on this path: use_parameter_substitution is True,
        # so _apply_parameter_substitution already ran
        # _ensure_parameter_substitution_columns on this same frame.
        seniority_el = pl.col("guarantor_seniority").cast(pl.String).fill_null("senior")
        is_fse_el = pl.col("guarantor_is_financial_sector_entity").fill_null(False)
        guarantor_supervisory_lgd_el = (
            pl.when(seniority_el == "subordinated")
            .then(pl.lit(firb_lgd_subordinated))
            .when(is_fse_el)
            .then(pl.lit(firb_lgd_senior_fse))
            .otherwise(pl.lit(firb_lgd_senior))
        )

        # Mirror the psm_lgd_source switch from _apply_parameter_substitution so
        # EL uses the same LGD_covered as RW (Art. 236(1A)(b) PRA PS1/26).
        # See note in _apply_parameter_substitution on column choice — ``lgd``
        # carries the seniority-correct borrower supervisory LGD by this stage.
        # irb_permissions is derived non-None in CalculationConfig.__post_init__.
        if config.irb_permissions.psm_lgd_source == "option_i":  # ty: ignore[unresolved-attribute]
            guarantor_lgd_el = pl.col("lgd")
        else:
            guarantor_lgd_el = guarantor_supervisory_lgd_el

        return lf.with_columns(
            [
                # DD changes K, not EL. Check it before the SA-guarantor limb:
                # an SA-routed guarantor can still qualify for DD when it has an
                # internal PD, and must retain the full obligor EL rather than
                # zeroing the covered share as ordinary SA substitution does.
                pl.when(_base_el & _is_dd_applied)
                .then(pl.col("expected_loss_irb_original"))
                .when(_base_el & _is_irb_non_dd)
                .then(
                    _el_unguaranteed
                    + guarantor_pd_floored * guarantor_lgd_el * pl.col("guaranteed_portion")
                )
                .when(_base_el & (pl.col("guarantor_approach").fill_null("") == "sa"))
                .then(_el_unguaranteed)
                .otherwise(pl.col("expected_loss_irb_original"))
                .alias("expected_loss"),
            ]
        )

    # No guarantor_pd column — only SA guarantor EL reduction
    return lf.with_columns(
        [
            pl.when(_base_el & (pl.col("guarantor_approach").fill_null("") == "sa"))
            .then(_el_unguaranteed)
            .otherwise(pl.col("expected_loss_irb_original"))
            .alias("expected_loss"),
        ]
    )


def _add_guarantee_status_columns(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add guarantee status and method tracking columns for reporting."""
    has_guaranteed_portion = pl.col("guaranteed_portion").fill_null(0) > 0
    is_beneficial_guaranteed = has_guaranteed_portion & pl.col("is_guarantee_beneficial")

    return lf.with_columns(
        [
            pl.when(pl.col("guaranteed_portion").fill_null(0) <= 0)
            .then(pl.lit("NO_GUARANTEE"))
            .when(~pl.col("is_guarantee_beneficial"))
            .then(pl.lit("GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"))
            .when(pl.col("_is_dd_applied"))
            .then(pl.lit("DOUBLE_DEFAULT"))
            .when(pl.col("_is_pd_substitution"))
            .then(pl.lit("PD_PARAMETER_SUBSTITUTION"))
            .otherwise(pl.lit("SA_RW_SUBSTITUTION"))
            .alias("guarantee_status"),
            # guarantee_method_used reports the substitution PATH taken: PSM is
            # recorded whenever the parameter-substitution route was followed
            # (IRB guarantor with internal PD), independent of the beneficial
            # gate. The GUARANTEE_NOT_APPLIED_NON_BENEFICIAL signal lives on
            # ``guarantee_status``. PRA PS1/26 Art. 236(1)(a): an IRB guarantor
            # always traverses parameter substitution.
            pl.when(is_beneficial_guaranteed & pl.col("_is_dd_applied"))
            .then(pl.lit("DOUBLE_DEFAULT"))
            .when(has_guaranteed_portion & pl.col("_is_pd_substitution"))
            .then(pl.lit("PD_PARAMETER_SUBSTITUTION"))
            .when(is_beneficial_guaranteed)
            .then(pl.lit("SA_RW_SUBSTITUTION"))
            .otherwise(pl.lit("NO_SUBSTITUTION"))
            .alias("guarantee_method_used"),
            # Calculate RW benefit from guarantee (positive = RW reduced)
            pl.when(pl.col("is_guarantee_beneficial"))
            .then(pl.col("risk_weight_irb_original") - pl.col("risk_weight"))
            .otherwise(pl.lit(0.0))
            .alias("guarantee_benefit_rw"),
        ]
    )
