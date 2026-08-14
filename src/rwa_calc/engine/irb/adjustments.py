"""
Post-formula adjustments for IRB calculations.

Pipeline position:
    IRB formulas -> Adjustments -> Guarantee substitution

Key responsibilities:
- Defaulted exposure treatment (CRR Art. 153(1)(ii) / 154(1)(i), Basel CRE31.3)
- Post-model adjustments for known model deficiencies (Basel 3.1 PRA PS1/26)
- EL shortfall/excess comparison against provisions (CRR Art. 158-159)

References:
- CRR Art. 153(1)(ii), 154(1)(i): Defaulted exposure treatment
- PRA PS1/26 Art. 153(5A), 154(4A), 158(6A): Post-model adjustments
- CRR Art. 158-159: EL shortfall treatment
- CRR Art. 62(d): Excess provisions as T2 capital (capped)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_MISSING_EXPECTED_LOSS,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack


# =============================================================================
# DEFAULTED EXPOSURE TREATMENT
# =============================================================================


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
    2. General PMA: scalar add-on to post-floor RWEA (supervisory requirement)
    3. Unrecognised exposure: scalar for model coverage gaps

    Adjustment sequencing per Art. 154(4A). The chapeau — "An institution shall
    increase the total risk-weighted exposure amounts calculated under
    paragraphs 1, 3 and 4 ... to reflect" — makes (a), (b) and (c) three
    ADDITIVE increases to one common base, not a pipeline:

        (a) general PMA               = base x pma_rwa_scalar
        (b) mortgage floor shortfall  = max(0, floor_rw x EAD - (base + (a)))
        (c) unrecognised exposure     = base x unrecognised_exposure_scalar
        RWEA = base + (a) + (b) + (c)

    Limb (b) is a TEST, not a value in a chain: "any amount needed to ensure
    that risk-weighted exposure amounts ... are greater than or equal to 10% of
    the exposure value ... (following application of any post model adjustments
    calculated under point (b) of Article 146(3))". That parenthetical is what
    puts limb (a) inside the comparison.

    Limb (c) is deliberately OUTSIDE the comparison: the parenthetical names
    only Art. 146(3)(b) adjustments, and (c) is "calculated under Article
    166D(6)" — a different provision.

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
    unrecognised_expr = pl.col("rwa") * unrecognised_scalar

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


def compute_el_shortfall_excess(
    lf: pl.LazyFrame,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """
    Compute EL shortfall and excess for IRB exposures.

    Compares expected loss against Art. 159(1) Pool B to determine
    whether the bank has a shortfall (EL > Pool B) or excess
    (Pool B > EL). Shortfall reduces CET1/T2; excess may be
    added to T2 capital (subject to 0.6% IRB RWA cap).

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
        el_shortfall: max(0, expected_loss - pool_b)
        el_excess:    max(0, pool_b - expected_loss)

    References:
        CRR Art. 158-159: EL shortfall treatment
        CRR Art. 159(1): Pool B composition (provisions + AVA + other)
        CRR Art. 34, Art. 105: Additional value adjustments
        CRR Art. 62(d): Excess provisions as T2 capital (capped)
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

    el = pl.col("expected_loss").fill_null(0.0)

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
