"""
CRR Supporting Factors for SA calculator (CRR2 Art. 501).

Applies SME and infrastructure supporting factors to RWA calculations.
These factors are CRR-specific and NOT available under Basel 3.1.

SME Supporting Factor - Tiered Approach (CRR2 Art. 501):
- Applies only to non-defaulted exposures (Art. 501 exclusion)
- Exposures up to EUR 2.5m (GBP 2.2m): factor of 0.7619
- Exposures above EUR 2.5m (GBP 2.2m): factor of 0.85

Formula:
    factor = [min(D, threshold) × 0.7619 + max(D - threshold, 0) × 0.85] / D

    Where D (= E* in Art. 501) is the on-balance-sheet amount owed by the SME's
    group of connected clients, excluding claims secured on residential property
    collateral.

The tier threshold is applied to drawn (on-balance-sheet) amounts only,
not the full post-CRM EAD which includes CCF-adjusted undrawn commitments.
Drawn amounts are aggregated across the SME's group of connected clients
(``lending_group_reference``), with fallback to ``counterparty_reference``
when no lending group is mapped. The aggregation runs on the **unified
frame before the SA / IRB / slotting branch split** (via the module-level
helper ``compute_e_star_group_drawn`` called from the pipeline orchestrator),
so siblings under any approach contribute to E*. Each branch's
``apply_factors`` then reads the pre-computed ``e_star_group_drawn`` column;
the legacy per-branch window sum remains as a fallback for test harnesses
that bypass the pipeline. The Art. 501 residential carve-out
("excluding claims or contingent claims secured on residential property
collateral") is applied per row by subtracting ``residential_collateral_value``
(capped at drawn) from each row's contribution to E*, mirroring the
retail-threshold treatment in ``engine/hierarchy/`` (CRR Art. 123(c)).
Buy-to-let rows additionally receive ``factor=1.0`` (BTL is not eligible
for the SF); a typical BTL row's RRE coverage equals its drawn balance so
its E* contribution lands at 0 by virtue of the netting. The resulting
blended factor is applied to each SME row's full RWA.

Infrastructure Supporting Factor (CRR Art. 501a):
- Qualifying infrastructure: factor of 0.75

**Only limb (a) of Art. 501a(1) is enforced — this is not full Art. 501a
compliance.** ``apply_factors`` gates the factor on the exposure being "included
either in the corporate exposure class or in the specialised lending exposures
class, with the exclusion of exposures in default", and on the
``is_infrastructure`` candidate flag. Limbs (b)-(o) — the special-purpose entity
test (b), the two-thirds cash-flow source (c), stressed conditions (d),
predictable cash flows (e), refinancing risk (f), the seven lender-protection
tests (g), seniority (h), the construction-phase equity-investor tests (i),
completion safeguards (j), operating risk (k), tested technology (l), permits
(m), derivatives use (n) and the environmental assessment (o) — and paragraph 2
(what makes cash flows "predictable") are implemented nowhere in this codebase.
Most of them are attestations rather than derivations and need an input field
that does not exist yet.

Cumulation of the two factors: where a row is eligible for both, the engine
takes the lower (more beneficial) factor. That is a **firm policy choice, not a
regulatory requirement** — Art. 501 ends at paragraph 2(c), Art. 501a at
paragraph 3, and neither cross-references the other, so CRR states no cumulation
rule; COREP Annex II is silent too, defining cols 0216/0217 only against their
own articles. Do not attach a citation to it.

References:
- CRR2 Art. 501 (EU 2019/876 amending EU 575/2013)
- CRR Art. 501a: Infrastructure supporting factor
- CRR Art. 501a(1)(a): corporate / specialised lending class, non-defaulted
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_SME_MISSING_COUNTERPARTY_REF,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity, ExposureClass
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import formula_float_map

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack


@dataclass
class SupportingFactorResult:
    """Result of supporting factor calculation."""

    factor: Decimal
    was_applied: bool
    description: str


class SupportingFactorCalculator:
    """
    Calculate SME and infrastructure supporting factors for CRR.

    The supporting factors reduce RWA for qualifying exposures:
    - SME: Tiered factor (0.7619 up to threshold, 0.85 above)
    - Infrastructure: Flat 0.75 factor

    Under Basel 3.1, these factors are not available (returns 1.0).
    """

    @cites("CRR Art. 501")
    def calculate_sme_factor(
        self,
        total_exposure: Decimal,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> Decimal:
        """
        Calculate SME supporting factor based on total drawn exposure.

        Args:
            total_exposure: Total drawn (on-balance-sheet) amount to the SME
            config: Calculation configuration

        Returns:
            Effective supporting factor (0.7619 to 0.85)
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if not resolved_pack.feature("supporting_factors"):
            return Decimal("1.0")

        if total_exposure <= 0:
            return Decimal("1.0")

        # FX-derived SME exposure threshold stays config (RegulatoryThresholds → S11c);
        # the factor multipliers are pack-sourced (Decimal, exact).
        threshold_gbp = regulatory_threshold(
            resolved_pack, "sme_exposure_threshold", config.eur_gbp_rate
        )

        sf_values = resolved_pack.formula("supporting_factors_values").params
        factor_tier1 = sf_values["sme_factor_under_threshold"]
        factor_tier2 = sf_values["sme_factor_above_threshold"]

        # Use GBP threshold for GBP currency (default)
        threshold = threshold_gbp

        # Calculate tiered factor
        tier1_amount = min(total_exposure, threshold)
        tier2_amount = max(total_exposure - threshold, Decimal("0"))

        weighted_factor = tier1_amount * factor_tier1 + tier2_amount * factor_tier2

        return weighted_factor / total_exposure

    @cites("CRR Art. 501a")
    def calculate_infrastructure_factor(
        self,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> Decimal:
        """
        Get infrastructure supporting factor.

        Args:
            config: Calculation configuration

        Returns:
            Infrastructure factor (0.75 for CRR, 1.0 for Basel 3.1)
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if not resolved_pack.feature("supporting_factors"):
            return Decimal("1.0")

        return resolved_pack.formula("supporting_factors_values").params["infrastructure_factor"]

    def get_effective_factor(
        self,
        is_sme: bool,
        is_infrastructure: bool,
        total_exposure: Decimal,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> Decimal:
        """
        Get the most beneficial supporting factor.

        If both SME and infrastructure apply, returns the lower factor
        (more beneficial to the bank).

        This scalar helper applies NO eligibility test of its own: unlike
        ``apply_factors``, it does not check the Art. 501a(1)(a) class limb or
        the default exclusion. Callers pass ``is_infrastructure`` already
        eligibility-tested.

        Args:
            is_sme: Whether exposure qualifies for SME factor
            is_infrastructure: Whether exposure qualifies for infrastructure
            total_exposure: Total drawn (on-balance-sheet) amount for tier calc
            config: Calculation configuration

        Returns:
            Most beneficial factor (lowest value)
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if not resolved_pack.feature("supporting_factors"):
            return Decimal("1.0")

        factors = [Decimal("1.0")]

        if is_sme:
            factors.append(self.calculate_sme_factor(total_exposure, config, pack=resolved_pack))

        if is_infrastructure:
            factors.append(self.calculate_infrastructure_factor(config, pack=resolved_pack))

        # Return lowest factor (most beneficial)
        return min(factors)

    @cites("CRR Art. 501")
    @cites("CRR Art. 501a")
    def apply_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Apply supporting factors to exposures LazyFrame.

        The SME supporting factor threshold (EUR 2.5m) is applied to E*,
        which CRR Art. 501 defines as the total drawn amount owed by the SME's
        group of connected clients, excluding claims secured on residential
        property collateral. Aggregation runs on the unified frame **before**
        the pipeline's SA / IRB / slotting branch split via
        ``compute_e_star_group_drawn``; this method reads the pre-computed
        ``e_star_group_drawn`` column when present (production path) and
        falls back to a local windowed sum over ``lending_group_reference``
        (with fallback to ``counterparty_reference``) when the column is
        absent (test harnesses that bypass the pipeline). The residential
        carve-out is applied per row by subtracting
        ``residential_collateral_value`` (capped at drawn) from each row's
        contribution to E*, mirroring the retail-threshold logic in
        ``engine/hierarchy/`` (Art. 123(c)). BTL rows receive factor=1.0
        via a separate eligibility gate. The resulting blended factor is
        applied to each SME row's full RWA.

        The tier calculation uses drawn_amount + interest ("amount owed"),
        NOT ead_final which includes CCF-adjusted undrawn commitments.

        The infrastructure factor (Art. 501a) is gated on limb (1)(a) only:
        ``is_infrastructure`` AND ``exposure_class`` in {corporate,
        corporate_sme, specialised_lending} AND not defaulted. The class and
        default limbs are independently necessary — a defaulted corporate keeps
        its corporate ``exposure_class`` in the engine, so the class test alone
        would not exclude it. Limbs (b)-(o) and paragraph 2 of Art. 501a are not
        implemented anywhere; see the module docstring. Where both factors
        apply, the lower is taken — a policy choice CRR does not prescribe.

        Expects columns:
        - is_sme: bool
        - is_infrastructure: bool (Art. 501a eligibility CANDIDATE flag — the
          class and default limbs are applied here, not at derivation, because
          COREP row 0035 reads the raw flag with its Annex II meaning)
        - exposure_class: str (optional; Art. 501a(1)(a) class limb — always
          present on the pipeline's branch edges, absent only on minimal test
          harness frames, where the class limb is skipped)
        - drawn_amount: float (on-balance-sheet drawn amount)
        - interest: float (accrued interest)
        - ead_final: float (fallback if drawn_amount not available)
        - rwa_pre_factor: float (RWA before supporting factor)
        - counterparty_reference: str (optional, for fallback aggregation)
        - lending_group_reference: str (optional, primary aggregation key)
        - residential_collateral_value: float (optional, netted from E* per
          Art. 501 residential carve-out)
        - is_buy_to_let: bool (optional, factor=1.0 eligibility gate)
        - e_star_group_drawn: float (optional, pre-computed unified-frame E*
          from ``compute_e_star_group_drawn`` — when present, the per-branch
          windowed sum is bypassed and this column is used directly so the
          tier threshold honours cross-approach siblings)

        Adds columns:
        - supporting_factor: float
        - rwa_post_factor: float (RWA after supporting factor)
        - supporting_factor_applied: bool
        - total_cp_drawn: float (E* — drawn aggregated across the SME's group of
          connected clients, net of residential collateral per Art. 501)

        Args:
            exposures: Exposures with RWA calculated
            config: Calculation configuration
            errors: Optional error accumulator for data quality warnings

        Returns:
            Exposures with supporting factors applied
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if not resolved_pack.feature("supporting_factors"):
            # Basel 3.1: No supporting factors
            return exposures.with_columns(
                [
                    pl.lit(1.0).alias("supporting_factor"),
                    pl.col("rwa_pre_factor").alias("rwa_post_factor"),
                    pl.lit(False).alias("supporting_factor_applied"),
                ]
            )

        # FX-derived threshold stays config (RegulatoryThresholds → S11c); the factor
        # multipliers are pack-sourced (float boundary via formula_float_map).
        threshold_gbp = float(
            regulatory_threshold(resolved_pack, "sme_exposure_threshold", config.eur_gbp_rate)
        )
        sf_values = formula_float_map(resolved_pack.formula("supporting_factors_values"))
        factor_tier1 = sf_values["sme_factor_under_threshold"]
        factor_tier2 = sf_values["sme_factor_above_threshold"]
        infra_factor = sf_values["infrastructure_factor"]

        # Check for optional columns (is_sme / is_infrastructure /
        # lending_group_reference are crm_exit contract columns and read
        # directly).
        schema = exposures.collect_schema()
        has_counterparty = "counterparty_reference" in schema.names()
        has_drawn = "drawn_amount" in schema.names()
        has_res_coll = "residential_collateral_value" in schema.names()

        # Build the drawn (on-balance-sheet) expression for tier calculation.
        # Use drawn_amount + interest when available; fall back to ead_final.
        # fill_nan before clip/sum — a single NaN in the group would otherwise
        # poison the windowed sum and zero out the supporting factor.
        if has_drawn:
            drawn_expr = pl.col("drawn_amount").fill_nan(0.0).fill_null(0.0).clip(
                lower_bound=0.0
            ) + pl.col("interest").fill_nan(0.0).fill_null(0.0)
        else:
            drawn_expr = pl.col("ead_final").fill_nan(0.0).fill_null(0.0)

        # Build SME factor expression with group-of-connected-clients aggregation.
        # CRR Art. 501 defines E* as the total amount owed across the SME's group
        # of connected clients, excluding claims secured on residential property.
        # The unified-frame helper ``compute_e_star_group_drawn`` (called by the
        # pipeline orchestrator before the approach split) populates
        # ``e_star_group_drawn`` across SA / IRB / slotting rows so the tier
        # calculation honours the full cross-approach group. When that column is
        # absent (test harnesses that bypass the pipeline) we fall back to the
        # legacy per-branch windowed sum.
        has_e_star_pre_computed = "e_star_group_drawn" in schema.names()
        if has_e_star_pre_computed:
            # Pre-computed unified-frame E* (CRR Art. 501 cross-approach).
            # Mirror to ``total_cp_drawn`` so downstream consumers and the
            # output schema stay stable.
            exposures = exposures.with_columns(pl.col("e_star_group_drawn").alias("total_cp_drawn"))
            ead_for_tier = pl.col("total_cp_drawn")
        elif has_counterparty:
            group_key_expr = (
                pl.when(pl.col("lending_group_reference").is_not_null())
                .then(pl.col("lending_group_reference"))
                .otherwise(pl.col("counterparty_reference"))
            ).alias("_sme_group_key")

            exposures = exposures.with_columns([group_key_expr])

            # Art. 501 carve-out: "excluding claims or contingent claims
            # secured on residential property collateral". Implemented as
            # per-row netting of residential_collateral_value (capped at
            # drawn so the contribution never goes negative), mirroring
            # the retail-threshold logic in engine/hierarchy/
            # (Art. 123(c)). Defaulted exposures stay in E* (Art. 501
            # explicitly includes "any exposure in default").
            if has_res_coll:
                res_coll_expr = (
                    pl.col("residential_collateral_value")
                    .fill_nan(0.0)
                    .fill_null(0.0)
                    .clip(lower_bound=0.0)
                )
                drawn_in_e_star = drawn_expr - pl.min_horizontal(res_coll_expr, drawn_expr)
            else:
                drawn_in_e_star = drawn_expr

            total_cp_drawn_expr = (
                pl.when(pl.col("is_sme") & pl.col("_sme_group_key").is_not_null())
                .then(drawn_in_e_star.sum().over("_sme_group_key"))
                .otherwise(drawn_in_e_star)
            )
            exposures = exposures.with_columns([total_cp_drawn_expr.alias("total_cp_drawn")])
            ead_for_tier = pl.col("total_cp_drawn")
        else:
            # counterparty_reference is not present — per-exposure fallback.
            # This can misclassify the tier when multiple exposures to the
            # same group individually fall below the EUR 2.5m threshold but
            # aggregate above it (Art. 501 requires aggregation across the
            # SME's group of connected clients).
            if errors is not None:
                errors.append(
                    CalculationError(
                        code=ERROR_SME_MISSING_COUNTERPARTY_REF,
                        message=(
                            "SME supporting factor: neither counterparty_reference "
                            "nor lending_group_reference is available. Tier threshold "
                            "(EUR 2.5m) evaluated per-exposure instead of across the "
                            "SME's group of connected clients as required by CRR "
                            "Art. 501. This may produce an incorrectly low supporting "
                            "factor when multiple exposures to the same group "
                            "individually fall below the threshold but aggregate above it."
                        ),
                        severity=ErrorSeverity.WARNING,
                        category=ErrorCategory.DATA_QUALITY,
                        regulatory_reference="CRR Art. 501",
                        field_name="counterparty_reference",
                    )
                )
            ead_for_tier = drawn_expr

        # Calculate tiered factor based on aggregated drawn exposure
        tier1_expr = (
            pl.when(ead_for_tier <= threshold_gbp)
            .then(ead_for_tier)
            .otherwise(pl.lit(threshold_gbp))
        )

        tier2_expr = (
            pl.when(ead_for_tier > threshold_gbp)
            .then(ead_for_tier - threshold_gbp)
            .otherwise(pl.lit(0.0))
        )

        # BTL exposures are excluded from the SME factor itself (the
        # eligibility gate is separate from the E* netting). For E* the
        # residential carve-out is applied via residential_collateral_value
        # netting on drawn_in_e_star above; a typical BTL row's RRE
        # collateral covers its drawn balance so its E* contribution is 0.
        is_btl = _optional_bool_column(schema, "is_buy_to_let")
        # Defaulted exposures are excluded from the SME factor (CRR Art. 501,
        # "non-defaulted exposures") and from the infrastructure factor
        # (CRR Art. 501a(1)(a), "with the exclusion of exposures in default").
        is_defaulted = _optional_bool_column(schema, "is_defaulted")
        # Art. 501(2)(c): the SME supporting factor is keyed on annual
        # turnover only — the Commission Rec 2003/361/EC total-assets
        # fallback (used by other SME-classification gates and by the
        # IRB Art. 153(4) correlation adjustment) does NOT apply here.
        # Counterparties identified as SME via assets receive the
        # CORPORATE_SME class and IRB correlation benefit but
        # supporting_factor=1.0. The check is conditional on the column
        # being present so test harnesses that build minimal LazyFrames
        # without cp_annual_revenue still hit the legacy is_sme-only
        # predicate; production pipelines always project this column via
        # the classifier so the gate fires there.
        has_revenue = "cp_annual_revenue" in schema.names()
        turnover_eligible = (
            (pl.col("cp_annual_revenue").is_not_null() & (pl.col("cp_annual_revenue") > 0))
            if has_revenue
            else pl.lit(True)
        )

        sme_eligible = pl.col("is_sme") & turnover_eligible & ~is_btl & ~is_defaulted

        sme_factor_expr = (
            pl.when(sme_eligible & (ead_for_tier > 0))
            .then((tier1_expr * factor_tier1 + tier2_expr * factor_tier2) / ead_for_tier)
            .when(sme_eligible & (ead_for_tier <= 0))
            .then(
                # Zero drawn = all within tier 1 → pure 0.7619
                pl.lit(factor_tier1)
            )
            .otherwise(pl.lit(1.0))
        )

        # Build infrastructure factor expression inline.
        # Art. 501a(1)(a): "the exposure is included either in the corporate
        # exposure class or in the specialised lending exposures class, with
        # the exclusion of exposures in default". ``is_infrastructure`` is the
        # eligibility CANDIDATE flag (a product_type match set by
        # engine/classify/attributes.py, and read with that meaning by COREP
        # row 0035), so the class and default limbs are applied here at the
        # point of application rather than at derivation. Both limbs are
        # independently necessary: a defaulted corporate keeps
        # ``exposure_class == "corporate"`` in the engine (the "defaulted"
        # C 07.00 sheet is a reporting-side derivation, not an engine class),
        # so the class test alone would let the largest ineligible rows
        # through. ``is_infrastructure`` is nullable wherever ``product_type``
        # is null; ``&`` propagates that null into the ``otherwise`` branch
        # (factor 1.0), which is the conservative direction.
        # ``exposure_class`` is a crm_exit contract column, so the class limb
        # always binds in production; the presence guard mirrors
        # ``turnover_eligible`` above so minimal test-harness frames that
        # bypass the pipeline stay constructible (they keep the legacy
        # is_infrastructure-only predicate).
        #
        # DO NOT "restore" an exact ``.value`` comparison here. That was tried
        # and withdrawn, on this argument: engine/classify/*.py compares this
        # column exactly (approach.py:303/313/319, subtypes.py passim), so an
        # exact match looks like the house style. It is the wrong precedent.
        # The nearest sibling is the SA risk-weight pipe that produces the very
        # ``rwa_pre_factor`` this factor multiplies, and both of its class
        # comparisons case-fold first (engine/sa/risk_weights.py:1044, :1626).
        # A third site in the same package does NOT —
        # engine/sa/rw_adjustments.py:494 matches exact lowercase against a
        # hand-written list — so the exact-match precedent is live here;
        # ``test_p1_211_the_class_limb_is_case_insensitive`` is what stops it
        # being copied. The two failure modes are also asymmetric: an exact match
        # silently DENIES relief to a row entitled to it whenever the class
        # arrives uppercase — conservative, but a wrong number — whereas the
        # opposite error, granting to an ineligible row, is what the class list
        # itself prevents: folding admits only case-variants of these same
        # three class names, never a fourth class.
        #
        # No ``fill_null`` is needed to deny a null class — measured, not
        # assumed: null survives ``str.to_uppercase`` and ``is_in``, and
        # ``pl.when`` routes it to ``otherwise`` (factor 1.0). Adding one would
        # also breach the ``engine_fill_null_sites`` ratchet (arch_check
        # check 11), which is at its baseline.
        infra_class_eligible = (
            pl.col("exposure_class")
            .str.to_uppercase()
            .is_in(
                [
                    ExposureClass.CORPORATE.value.upper(),
                    ExposureClass.CORPORATE_SME.value.upper(),
                    ExposureClass.SPECIALISED_LENDING.value.upper(),
                ]
            )
            if "exposure_class" in schema.names()
            else pl.lit(True)
        )
        infra_eligible = pl.col("is_infrastructure") & infra_class_eligible & ~is_defaulted
        infra_factor_expr = (
            pl.when(infra_eligible).then(pl.lit(infra_factor)).otherwise(pl.lit(1.0))
        )

        # Compute minimum (most beneficial) factor. Taking the minimum where
        # both factors apply is a FIRM POLICY CHOICE, not a regulatory
        # requirement: Art. 501 ends at paragraph 2(c), Art. 501a at paragraph
        # 3, and neither cross-references the other, so CRR states no
        # cumulation rule. COREP Annex II is silent too — cols 0216/0217 are
        # each defined only against their own article. Do not cite an article
        # for this line.
        min_factor_expr = pl.min_horizontal(sme_factor_expr, infra_factor_expr)

        # Single with_columns call for maximum performance
        return exposures.with_columns(
            [
                min_factor_expr.alias("supporting_factor"),
                (pl.col("rwa_pre_factor") * min_factor_expr).alias("rwa_post_factor"),
                (min_factor_expr < 1.0).alias("supporting_factor_applied"),
            ]
        )


def create_supporting_factor_calculator() -> SupportingFactorCalculator:
    """Create a SupportingFactorCalculator instance."""
    return SupportingFactorCalculator()


@cites("CRR Art. 501")
def compute_e_star_group_drawn(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    errors: list[CalculationError] | None = None,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Compute Art. 501 E* across the unified frame before the approach split.

    The SME supporting factor's EUR 2.5m / GBP 2.2m tier threshold is defined
    by CRR Art. 501 against the total amount owed by the SME's *group of
    connected clients*, regardless of which regulatory approach (SA, IRB,
    slotting) each member is treated under. Running the windowed sum inside
    each branch after the pipeline splits by approach (the historical
    behaviour) under-counts E* whenever a lending group spans multiple
    approaches.

    This helper runs once on the unified frame, before the split in
    ``engine/pipeline.py``, so SA / IRB / slotting siblings all contribute.
    The resulting ``e_star_group_drawn`` column is then read by
    ``apply_factors`` in each branch.

    Population rules (mirroring the existing ``apply_factors`` logic):
    - per-row contribution = ``drawn_amount + interest`` (clipped at zero),
      minus ``min(residential_collateral_value, contribution)``
      (Art. 501 residential carve-out)
    - aggregation key = ``lending_group_reference`` if not null, else
      ``counterparty_reference`` (mirrors the connected-clients pattern)
    - written to every row (SME and non-SME) in a partition so all three
      branch calculators can read it

    No-ops:
    - if supporting factors are disabled (Basel 3.1), returns the frame
      unchanged — column is not added
    - if ``counterparty_reference`` is not present (missing group key),
      emits the existing ``SF001`` warning and returns unchanged

    Args:
        exposures: Unified-frame LazyFrame post-CRM, pre-branch-split
        config: Calculation configuration
        errors: Optional error accumulator for data-quality warnings

    Returns:
        LazyFrame with ``e_star_group_drawn`` column added
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("supporting_factors"):
        return exposures

    schema = exposures.collect_schema()
    names = schema.names()

    if "counterparty_reference" not in names:
        if errors is not None:
            errors.append(
                CalculationError(
                    code=ERROR_SME_MISSING_COUNTERPARTY_REF,
                    message=(
                        "SME supporting factor: neither counterparty_reference "
                        "nor lending_group_reference is available on the unified "
                        "frame. Cross-approach E* (CRR Art. 501) cannot be "
                        "computed; the tier threshold will fall back to per-branch "
                        "aggregation and may under-count exposures."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference="CRR Art. 501",
                    field_name="counterparty_reference",
                )
            )
        return exposures

    has_drawn = "drawn_amount" in names
    has_interest = "interest" in names
    has_res_coll = "residential_collateral_value" in names

    drawn_principal = (
        pl.col("drawn_amount").fill_nan(0.0).fill_null(0.0).clip(lower_bound=0.0)
        if has_drawn
        else pl.lit(0.0)
    )
    interest_expr = pl.col("interest").fill_nan(0.0).fill_null(0.0) if has_interest else pl.lit(0.0)
    drawn_expr = drawn_principal + interest_expr

    if has_res_coll:
        res_coll_expr = (
            pl.col("residential_collateral_value")
            .fill_nan(0.0)
            .fill_null(0.0)
            .clip(lower_bound=0.0)
        )
        drawn_in_e_star = drawn_expr - pl.min_horizontal(res_coll_expr, drawn_expr)
    else:
        drawn_in_e_star = drawn_expr

    group_key_expr = (
        pl.when(pl.col("lending_group_reference").is_not_null())
        .then(pl.col("lending_group_reference"))
        .otherwise(pl.col("counterparty_reference"))
    )

    exposures = exposures.with_columns(group_key_expr.alias("_sme_group_key"))
    exposures = exposures.with_columns(
        drawn_in_e_star.sum().over("_sme_group_key").alias("e_star_group_drawn")
    )
    return exposures.drop("_sme_group_key")


def _optional_bool_column(schema: pl.Schema, column: str) -> pl.Expr:
    """
    Read an optional Boolean eligibility flag, or a ``False`` literal when absent.

    ``is_buy_to_let`` and ``is_defaulted`` are crm_exit contract columns, so the
    fallback is unreachable from the pipeline; it keeps the minimal LazyFrames
    built by test harnesses that call ``apply_factors`` directly constructible.
    Shared by the two callers rather than duplicated so the engine's
    presence-guard census does not grow (arch_check check 11).
    """
    return pl.col(column) if column in schema else pl.lit(False)
