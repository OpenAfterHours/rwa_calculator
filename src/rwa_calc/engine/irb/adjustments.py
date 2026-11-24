"""
Post-formula adjustments for IRB calculations.

Pipeline position:
    IRB formulas -> Adjustments -> Guarantee substitution

Key responsibilities:
- Defaulted exposure treatment (CRR Art. 153(1)(ii) / 154(1)(i), Basel CRE31.3),
  including the PD of 100% for obligors in default (Art. 160(3) / 163(2))
- Post-model adjustments for known model deficiencies (Basel 3.1 PRA PS1/26)
- EL shortfall/excess comparison against provisions (CRR Art. 158-159), on the
  EL after any PS1/26 Art. 158(6A) post-model increase (``art_159_expected_loss``)

References:
- CRR Art. 153(1)(ii), 154(1)(i): Defaulted exposure treatment
- CRR / PRA PS1/26 Art. 160(3), 163(2): PD of 100% for obligors in default
- PRA PS1/26 Art. 153(5A), 154(4A), 158(6A): Post-model adjustments
- CRR Art. 158-159: EL shortfall treatment
- PRA PS1/26 Art. 159(1): 'A' and 'C' include the Art. 158(6A) EL increase
- CRR Art. 62(d): Excess provisions as T2 capital (capped)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_MISSING_EXPECTED_LOSS,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from collections.abc import Collection

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack


# =============================================================================
# DEFAULTED EXPOSURE TREATMENT
# =============================================================================


@cites("CRR Art. 160(3)")
@cites("CRR Art. 163(2)")
@cites("PS1/26, paragraph 160")
@cites("PS1/26, paragraph 163")
def apply_defaulted_treatment(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Apply regulatory treatment for defaulted exposures (PD=100%).

    Per CRR Art. 153(1)(ii) / 154(1)(i) and Basel CRE31.3, defaulted
    exposures bypass the Vasicek formula entirely:
    - F-IRB: K=0, RW=0 (capital held via provisions)
    - A-IRB: K = max(0, LGD_in_default - BEEL)

    Expected loss for defaulted exposures:
    - F-IRB: EL = LGD × EAD (supervisory LGD)
    - A-IRB: EL = BEEL × EAD (best estimate)

    PD of a defaulted obligor — CRR and PS1/26 Art. 160(3): "An institution
    shall use a PD of 100% for obligors in default"; Art. 163(2) is the retail
    twin, which also covers a default defined at facility level. It is the PD
    itself, not a floor, so BOTH carriers read 1.0 on a defaulted row:
    ``pd_floored`` (post-input-floor: C 08.01 c0010, C 08.03 c0050, C 09.02
    c0080, CR6 / CR9 col f) and ``pd`` (pre-input-floor: the basis Basel 3.1's
    OF 08.03 / 08.05 row axis is stated on). Every PD-band template therefore
    puts the leg in its 100% row, as Annex II requires: "All defaulted exposures
    shall be included in the bucket representing PD of 100%". The guarantee
    stage runs after this and seals its post-CRM PD carriers from these two, so
    a leg that is not parameter-substituted carries 100% there too. The firm's
    own estimate stays on ``internal_pd``. The PD is set here, after the K,
    correlation and maturity batches, so no Vasicek term is evaluated at PD 1,
    and K, RWEA and EL here are overridden from the default flag, not the PD.
    One later reader is order-only: the aggregator's facility-share tie-break
    ranks PD descending (``engine/aggregator/_facility_share.py``), where a
    defaulted leg now ranks as the worse credit. P1.381.

    Runs after calculate_expected_loss (so all standard columns exist)
    and before apply_guarantee_substitution.

    Args:
        lf: LazyFrame with IRB formula results

    Returns:
        LazyFrame with defaulted rows overwritten
    """
    schema = lf.collect_schema()
    cols = schema.names()

    is_defaulted = pl.col("is_defaulted").fill_null(False)
    beel = pl.col("beel").fill_null(0.0)

    # K for defaulted: A-IRB = max(0, lgd_floored - beel), F-IRB = 0
    is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in cols else pl.lit(False)
    k_defaulted = (
        pl.when(is_airb)
        .then(pl.max_horizontal(pl.lit(0.0), pl.col("lgd_floored") - beel))
        .otherwise(pl.lit(0.0))
    )

    # Art. 153(1)(ii): no maturity adjustment, no 1.06 for defaulted
    rwa_defaulted = k_defaulted * 12.5 * pl.col("ead_final")

    # Risk weight = K × 12.5
    rw_defaulted = k_defaulted * 12.5

    # Expected loss: A-IRB = BEEL × EAD, F-IRB = LGD × EAD
    el_defaulted = (
        pl.when(is_airb)
        .then(beel * pl.col("ead_final"))
        .otherwise(pl.col("lgd_floored") * pl.col("ead_final"))
    )

    # Override only defaulted rows
    return lf.with_columns(
        [
            # Art. 160(3) / 163(2): PD 100%, on the pre- AND post-input-floor basis.
            *(
                pl.when(is_defaulted).then(pl.lit(1.0)).otherwise(pl.col(pd_col)).alias(pd_col)
                for pd_col in ("pd", "pd_floored")
            ),
            pl.when(is_defaulted).then(k_defaulted).otherwise(pl.col("k")).alias("k"),
            pl.when(is_defaulted)
            .then(pl.lit(0.0))
            .otherwise(pl.col("correlation"))
            .alias("correlation"),
            pl.when(is_defaulted)
            .then(pl.lit(1.0))
            .otherwise(pl.col("maturity_adjustment"))
            .alias("maturity_adjustment"),
            pl.when(is_defaulted).then(rwa_defaulted).otherwise(pl.col("rwa")).alias("rwa"),
            pl.when(is_defaulted)
            .then(rw_defaulted)
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
            pl.when(is_defaulted)
            .then(el_defaulted)
            .otherwise(pl.col("expected_loss"))
            .alias("expected_loss"),
        ]
    )


# =============================================================================
# POST-MODEL ADJUSTMENTS (Basel 3.1)
# =============================================================================


@cites("PS1/26, paragraph 153")
@cites("PS1/26, paragraph 154")
@cites("PS1/26, paragraph 166D")
def apply_post_model_adjustments(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Apply post-model adjustments to IRB RWEA and EL (Basel 3.1 only).

    PRA PS1/26 Art. 153(5A), 154(4A), 158(6A) require firms to apply
    adjustments for known model deficiencies. Three RWEA components:

    1. Mortgage RW floor: min risk weight for **non-defaulted** retail
       exposures secured by residential immovable property (Art. 154(4A)(b),
       via the ``retail_mortgage`` class as an over-inclusive proxy for the
       Art. 147(5B)(d)(ii) subclass — see the scope comment below)
    2. General PMA: an additive amount, base x pma_rwa_scalar (Art. 146(3)(b))
    3. Unrecognised exposure: base x unrecognised_exposure_scalar, on Advanced
       IRB legs only (Art. 166D(6))

    Adjustment sequencing per Art. 154(4A). The chapeau — "An institution shall
    increase the total risk-weighted exposure amounts calculated under
    paragraphs 1, 3 and 4 ... to reflect" — makes (a), (b) and (c) three
    ADDITIVE increases to one common base, not a pipeline:

        (a) general PMA               = base x pma_rwa_scalar
        (b) mortgage floor shortfall  = max(0, floor_rw x EAD - (base + (a)))
        (c) unrecognised exposure     = base x unrecognised_exposure_scalar
                                        (Advanced IRB legs only)
        RWEA = base + (a) + (b) + (c)

    Limb (b) is a TEST, not a value in a chain: "any amount needed to ensure
    that risk-weighted exposure amounts ... are greater than or equal to 10% of
    the exposure value ... (following application of any post model adjustments
    calculated under point (b) of Article 146(3))". That parenthetical is what
    puts limb (a) inside the comparison.

    Limb (c) is deliberately OUTSIDE the comparison: the parenthetical names
    only Art. 146(3)(b) adjustments, and (c) is "calculated under Article
    166D(6)" — a different provision.

    Limb (c) also reaches **Advanced IRB legs only** (``approach`` ==
    ``advanced_irb``). Art. 166D(6)(a)(ii) confines the adjustment to facilities
    where "the institution would have applied the Advanced IRB Approach in
    accordance with Article 147A", and Annex II p.112 says column 0254 "shall
    not be reported for sheets relating to the FIRB approach or the slotting
    approach". Applying the scalar to F-IRB legs as well overstated their RWEA
    and left an F-IRB sheet's column 0260 above 0251 + 0252 + 0253 + 0254
    (``boe_b0751``, ERROR). Limb (a) is an Art. 146(3) amount and still reaches
    F-IRB legs. P1.399.

    An earlier revision of this docstring asserted the opposite ordering — floor
    first, then both scalars on the post-floor base — and attributed it to
    Art. 154(4A). It is recorded here because it read as settled: the stated
    justification ("PMA scalars must capture the mortgage floor increase in
    their base, otherwise capital is understated") is a conservatism argument,
    not a reading of the text, and the text says the reverse. Correcting it
    RELEASES capital where the floor binds. P1.325.

    EL adjustment mirrors the general PMA scalar, floored at zero
    per Art. 158(6A) — PMAs cannot decrease expected loss.

    Under CRR, no adjustments are applied (returns frame unchanged).

    Produces columns:
        rwa_pre_adjustments: RWEA before any PMAs
        post_model_adjustment_rwa: General PMA RWEA add-on
        mortgage_rw_floor_adjustment: RWEA increase from mortgage floor
        unrecognised_exposure_adjustment: RWEA increase for unrecognised exposures
        el_pre_adjustment: EL before PMAs
        post_model_adjustment_el: General PMA EL add-on (floored at 0)
        el_after_adjustment: EL after all PMAs

    Args:
        lf: LazyFrame with IRB formula results
        config: Calculation configuration
        pack: Resolved rulepack for the run's regime/date (Phase 5 — sources the
            ``post_model_adjustments`` regime gate). Production threads the
            orchestrator's pack; direct callers may omit it, in which case one is
            resolved from ``config``.

    Returns:
        LazyFrame with post-model adjustment columns
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    pma_config = config.post_model_adjustments

    if not resolved_pack.feature("post_model_adjustments"):
        # CRR or disabled: add zero-valued columns for schema consistency
        return lf.with_columns(
            [
                pl.col("rwa").alias("rwa_pre_adjustments"),
                pl.lit(0.0).alias("post_model_adjustment_rwa"),
                pl.lit(0.0).alias("mortgage_rw_floor_adjustment"),
                pl.lit(0.0).alias("unrecognised_exposure_adjustment"),
                pl.col("expected_loss").alias("el_pre_adjustment"),
                pl.lit(0.0).alias("post_model_adjustment_el"),
                pl.col("expected_loss").alias("el_after_adjustment"),
            ]
        )

    schema = lf.collect_schema()
    cols = schema.names()

    pma_rwa_scalar = float(pma_config.pma_rwa_scalar)
    pma_el_scalar = float(pma_config.pma_el_scalar)
    # Regulatory mortgage RW floor (Art. 154(4A)(b)) — pack scalar (Phase 5 S11e-v3),
    # overridable via with_overrides. The PMA scalars above stay config ELECTIONS.
    mortgage_rw_floor = float(resolved_pack.scalar("mortgage_rw_floor"))
    unrecognised_scalar = float(pma_config.unrecognised_exposure_scalar)

    # Mortgage RW floor scope — Art. 154(4A)(b), two separable limbs:
    #   1. "non-defaulted exposures" — is_defaulted is the carrier (a null reads as
    #      not-defaulted, the conservative side, matching apply_defaulted_treatment
    #      above). Modelled risk_weight/rwa are NOT proxies for it: an A-IRB
    #      defaulted mortgage with LGD > BEEL has RW > 0.
    #   2. "retail exposures secured by ... residential immovable property" — the
    #      Art. 147(5B)(d)(ii) subclass. RETAIL_MORTGAGE is the engine's closest
    #      available proxy for that subclass, over-inclusive of retail exposures
    #      secured by commercial property (property_collateral_value spans both).
    #      The over-inclusion is conservative; correcting it is a separate item.
    # The third limb of (4A)(b) — UK-situated property — is not implementable: no
    # property-country carrier exists on the sealed edge.
    # Adjustment = max(0, floor_rw - modelled_rw) × EAD
    is_mortgage = (
        pl.col("exposure_class").cast(pl.String) == ExposureClass.RETAIL_MORTGAGE.value
    ) & (pl.col("is_defaulted").eq_missing(True).not_())

    # Art. 154(4A) makes (a), (b) and (c) three ADDITIVE increases to one common
    # base — "the total risk-weighted exposure amounts calculated under
    # paragraphs 1, 3 and 4" — not a pipeline in which each feeds the next. So
    # (a) and (c) both multiply the PRE-floor modelled RWEA.
    #
    # (b) is a TEST rather than a value: "any amount needed to ensure that
    # risk-weighted exposure amounts ... are greater than or equal to 10% of the
    # exposure value ... (following application of any post model adjustments
    # calculated under point (b) of Article 146(3))". The parenthetical fixes
    # the figure the >= comparison is made against: the base plus limb (a).
    #
    # ⚠ Limb (c) is NOT in that comparison. The parenthetical names only
    # Art. 146(3)(b) post model adjustments, which is limb (a);
    # ``unrecognised_exposure_scalar`` is limb (c), "calculated under
    # Article 166D(6)" — a different provision. It is a sibling increase on the
    # same base and must stay outside the floor test (P1.325).
    general_pma_expr = pl.col("rwa") * pma_rwa_scalar
    # Limb (c) is Art. 166D(6)'s adjustment, which covers only facilities where
    # "the institution would have applied the Advanced IRB Approach in accordance
    # with Article 147A" (166D(6)(a)(ii)). Read the leg's approach off the sealed
    # ``approach`` column (classifier exit, required) — not a regime branch: the
    # whole block is already behind the ``post_model_adjustments`` pack Feature.
    # Read without a presence guard on purpose: ``classify_approach`` emits the
    # column on every production path before this transform, and a frame
    # without it is a programming error, not an F-IRB leg (P1.399).
    is_airb_leg = pl.col("approach") == ApproachType.AIRB.value
    unrecognised_expr = (
        pl.when(is_airb_leg).then(pl.col("rwa") * unrecognised_scalar).otherwise(pl.lit(0.0))
    )

    rw_col = "risk_weight" if "risk_weight" in cols else None
    if rw_col and mortgage_rw_floor > 0:
        # The shortfall is measured in RWEA space against base + (a). Expressed
        # as (floor_rw - modelled_rw) x EAD this would be the pre-(a) shortfall,
        # which is what the inverted ordering computed.
        floor_rwea = pl.lit(mortgage_rw_floor) * pl.col("ead_final")
        post_pma_rwea = pl.col("rwa") + general_pma_expr
        mortgage_adj_expr = (
            pl.when(is_mortgage)
            .then(pl.max_horizontal(pl.lit(0.0), floor_rwea - post_pma_rwea))
            .otherwise(pl.lit(0.0))
        )
    else:
        mortgage_adj_expr = pl.lit(0.0)

    # EL column detection
    el_col = "expected_loss" if "expected_loss" in cols else None

    # Compute all three Art. 154(4A) increases against the SAME paragraph-1/3/4
    # base, in one pass, before any of them is added. The floor expression above
    # already folds limb (a) into its own comparison; nothing here may mutate
    # ``rwa`` before all three are evaluated, or the base drifts under them.
    lf = lf.with_columns(
        [
            pl.col("rwa").alias("rwa_pre_adjustments"),
            general_pma_expr.alias("post_model_adjustment_rwa"),
            unrecognised_expr.alias("unrecognised_exposure_adjustment"),
            mortgage_adj_expr.alias("mortgage_rw_floor_adjustment"),
        ]
    )

    # Add all three Art. 154(4A) increases to the base. The chapeau — "An
    # institution shall increase the total risk-weighted exposure amounts
    # calculated under paragraphs 1, 3 and 4 ... to reflect: (a) ... (b) ...
    # (c) ..." — makes them additive to that one base, so this is a sum and not
    # a chain.
    lf = lf.with_columns(
        (
            pl.col("rwa")
            + pl.col("post_model_adjustment_rwa")
            + pl.col("mortgage_rw_floor_adjustment")
            + pl.col("unrecognised_exposure_adjustment")
        ).alias("rwa")
    )

    # Step 3: EL adjustments — Art. 158(6A) requires PMAs cannot decrease EL
    if el_col:
        el_pma_expr = pl.max_horizontal(pl.lit(0.0), pl.col(el_col) * pma_el_scalar)
        lf = lf.with_columns(
            [
                pl.col(el_col).alias("el_pre_adjustment"),
                el_pma_expr.alias("post_model_adjustment_el"),
                (pl.col(el_col) + el_pma_expr).alias("el_after_adjustment"),
            ]
        )
    else:
        lf = lf.with_columns(
            [
                pl.lit(0.0).alias("el_pre_adjustment"),
                pl.lit(0.0).alias("post_model_adjustment_el"),
                pl.lit(0.0).alias("el_after_adjustment"),
            ]
        )

    return lf


# =============================================================================
# EL SHORTFALL / EXCESS
# =============================================================================


@cites("CRR Art. 159")
@cites("PS1/26, paragraph 159")
def compute_el_shortfall_excess(
    lf: pl.LazyFrame,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """
    Compute EL shortfall and excess for IRB exposures.

    Compares the Art. 159 expected loss against Art. 159(1) Pool B to
    determine whether the bank has a shortfall (EL > Pool B) or excess
    (Pool B > EL). Shortfall reduces CET1/T2; excess may be
    added to T2 capital (subject to 0.6% IRB RWA cap).

    The EL compared is ``art_159_expected_loss``: under Basel 3.1 the amount
    AFTER the PS1/26 Art. 158(6A) post-model increase, because Art. 159(1)
    defines 'A' and 'C' as the EL "calculated in accordance with Article
    158(5), (6), (6A) and (10)". ``expected_loss`` itself stays pre-6A (OF 08.01
    col 0280 reports it). These per-row columns are audit carriers; the capital
    figures come from the portfolio netting in
    ``engine/aggregator/_el_summary.py``, which reads the same EL (P1.209).

    Pool B per Art. 159(1) includes:
        (a) General credit risk adjustments (GCRA)
        (b) Specific credit risk adjustments (SCRA) for non-defaulted
        (c) Additional value adjustments (AVAs per Art. 34)
        (d) Other own funds reductions

    Components (a) and (b) are captured via ``provision_allocated``.
    Components (c) and (d) are captured via ``ava_amount`` and
    ``other_own_funds_reductions`` respectively.

    Requires ``expected_loss`` to be computed first. Null
    ``provision_allocated`` values (no provisions resolved) are treated
    as zero, so shortfall equals the full EL and excess is zero.

    Produces:
        el_shortfall: max(0, art_159_el - pool_b)
        el_excess:    max(0, pool_b - art_159_el)

    References:
        CRR Art. 158-159: EL shortfall treatment
        CRR Art. 159(1): Pool B composition (provisions + AVA + other)
        CRR Art. 34, Art. 105: Additional value adjustments
        CRR Art. 62(d): Excess provisions as T2 capital (capped)
        PS1/26 Art. 158(6A), 159(1): 'A' and 'C' include the post-model EL increase
        CRE35.1-3: Basel 3.1 expected loss calculation
    """
    schema = lf.collect_schema()
    cols = schema.names()

    if "expected_loss" not in cols:
        if errors is not None:
            errors.append(
                CalculationError(
                    code=ERROR_MISSING_EXPECTED_LOSS,
                    message=(
                        "expected_loss column absent — EL shortfall/excess defaulted "
                        "to zero. T2 credit cap and CET1 deduction may be affected."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    field_name="expected_loss",
                    regulatory_reference="CRR Art. 158-159",
                )
            )
        return lf.with_columns(
            [
                pl.lit(0.0).alias("el_shortfall"),
                pl.lit(0.0).alias("el_excess"),
            ]
        )

    el = art_159_expected_loss(cols).fill_null(0.0)

    prov = pl.col("provision_allocated").fill_null(0.0)
    # Art. 159(1)(c): Additional value adjustments (AVAs per Art. 34)
    ava = pl.col("ava_amount").fill_null(0.0)
    # Art. 159(1)(d): Other own funds reductions
    other_ofr = pl.col("other_own_funds_reductions").fill_null(0.0)

    # Pool B = provisions + AVA + other own funds reductions
    pool_b = prov + ava + other_ofr

    return lf.with_columns(
        [
            pl.max_horizontal(pl.lit(0.0), el - pool_b).alias("el_shortfall"),
            pl.max_horizontal(pl.lit(0.0), pool_b - el).alias("el_excess"),
        ]
    )


@cites("PS1/26, paragraph 158")
@cites("PS1/26, paragraph 159")
def art_159_expected_loss(cols: Collection[str]) -> pl.Expr:
    """
    The expected loss amount that enters the Art. 159 comparison with Pool B.

    PS1/26 Art. 159(1) defines 'A' (non-defaulted) and 'C' (defaulted) as the
    sum of EL "calculated in accordance with Article 158(5), (6), (6A) and
    (10)", and Art. 158(6A) requires the institution to "increase the total
    expected loss amounts calculated under paragraphs 5 and 6 to reflect any
    post model adjustments in respect of expected loss amounts calculated under
    point (c) of Article 146(3)". The post-6A amount is ``el_after_adjustment``
    (``apply_post_model_adjustments``, rebased post-CRM by
    ``guarantee.apply_guarantee_substitution``).

    Carrier ladder, per leg:
    - ``el_after_adjustment`` where the column is present and non-null
      (formula-IRB legs);
    - else ``expected_loss`` — a slotting leg carries no PMA EL carrier, so the
      column is NULL on its rows after a diagonal concat with IRB results and
      ABSENT on a slotting-only frame.

    Regime: no regime branch here. Both producers of ``el_after_adjustment``
    are gated on the ``post_model_adjustments`` pack Feature, so wherever it is
    off (CRR, whose Art. 159 nets Art. 158(5), (6) and (10) EL only) the
    carrier equals ``expected_loss`` and this reads the unadjusted EL.

    ``expected_loss`` itself is deliberately left pre-6A: OF 08.01 col 0280 is
    the EL "pre post-model adjustments" (PS1/26 Annex II), col 0282 the EL after.

    Args:
        cols: Column names of the frame the expression will be evaluated on.

    Returns:
        Expression for the per-leg Art. 159 expected loss (nulls preserved).

    References:
        PS1/26 Art. 146(3)(c), 158(6A), 159(1)
        CRR Art. 159
    """
    if "el_after_adjustment" in cols:
        return pl.coalesce("el_after_adjustment", "expected_loss")
    return pl.col("expected_loss")
