"""
Equity Calculator for Equity Exposure RWA.

Implements framework-dependent approaches:
- CRR Article 133: Standardised Approach (SA) — 0%/100%/250%/400%
- CRR Article 155: IRB Simple Risk Weight Method — 190%/290%/370%
- Basel 3.1 Art. 133(3)-(5): SA only — 0%/150%/250%/400% (IRB removed)

Pipeline position:
    CRMProcessor -> EquityCalculator -> Aggregation

Key responsibilities:
- Determine equity risk weights based on equity type and framework
- Handle diversified portfolio treatment for private equity
- Assign the Standardised Transitional Approach weights (PS1/26 Credit Risk:
  General Provisions rules 4.1-4.3) to a firm without IRB permission on
  31 December 2026, for reporting dates in 2027-2029, and mark those legs with
  the carriers OF 07.00 needs (``equity_transitional_approach``,
  ``equity_higher_risk``, ``risk_weight_pre_equity_transitional``)
- Calculate RWA = EAD x RW
- Tag the CRR method actually applied (``equity_method``: ``sa`` / ``irb_simple``
  / ``pd_lgd``) so the reporting ledger can disclose Art. 155(2) simple-RW
  equity in Pillar 3 CR10.5 without re-deriving the approach
- Build audit trail of calculations

Basel 3.1 key changes from CRR:
- All standard equity (incl. government-supported): 100% -> 250% (Art. 133(3))
- CIU fallback: 1,250% (Art. 132(2), unchanged from CRR)
- IRB equity removed (Art. 147A) — all equity uses SA
- A firm without IRB permission on 31 December 2026 is ASSIGNED 160% / 190% /
  220% (higher risk 220% / 280% / 340%) in 2027 / 2028 / 2029 in place of the
  Art. 133(3) / (4) 250% / 400% (rules 4.1-4.3); the end state applies from
  1 January 2030. A firm that had IRB permission (F-IRB, A-IRB or slotting)
  keeps the Art. 133 weights: its rules 4.5 / 4.6 (4.5(1): the 4.2 / 4.3
  weights for equity it held under Standardised permission; 4.6: the higher of
  the legacy Art. 155 weight and the 4.2 / 4.3 weight for equity it held under
  the IRB Approach) are not implemented, and the run is warned (CFG003)

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
- PRA PS1/26 Art. 133(3)-(6): Basel 3.1 SA equity weights
- PRA PS1/26 Credit Risk: General Provisions rules 4.1-4.10: equity transitional
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import CRMAdjustedBundle, EquityResultBundle
from rwa_calc.contracts.errors import ERROR_EQUITY_TRANSITIONAL_CONFIG, CalculationError
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.domain.enums import (
    ApproachType,
    EquityApproach,
    EquityType,
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
)
from rwa_calc.engine.irb.formulas import (
    _capital_k_expr_from_params,
    _correlation_expr_from_pd,
    _maturity_adjustment_expr_from_pd,
)
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import formula_float_map, lookup_float_map, scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from collections.abc import Collection
    from decimal import Decimal

    from polars.expr.whenthen import ChainedThen, Then

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# Float-converted risk weight tables for Polars expressions. Authoritative
# Decimal values live in the rulepack (packs/crr.py + packs/b31.py); resolved and
# float-converted once at module load via compile.lookup_float_map for use with
# pl.lit(). Enum (EquityType)-keyed.
_CRR_SA_RW = lookup_float_map(resolve("crr", date(2026, 1, 1)).lookup("equity_sa_risk_weights"))
_B31_SA_RW = lookup_float_map(resolve("b31", date(2027, 1, 1)).lookup("equity_sa_risk_weights"))
_IRB_RW = lookup_float_map(
    resolve("crr", date(2026, 1, 1)).lookup("equity_irb_simple_risk_weights")
)
# Art. 158(7) IRB-simple equity EL rates (EquityType-keyed), paired with the
# Art. 155(2) simple-RW bucket: 0.8% for diversified-PE/exchange-traded/listed,
# 2.4% for all other equity, 0% for central-bank. CRR-only (B31 removes IRB equity).
_IRB_SIMPLE_EL = lookup_float_map(resolve("crr", date(2026, 1, 1)).lookup("equity_irb_simple_el"))
# CRR Art. 133(2) / Art. 48(4): the 250% weight of a non-deducted significant
# investment in a financial sector entity. Art. 155(1) keeps it outside the IRB
# equity approaches, so every CRR equity path (SA, IRB simple, PD/LGD) reads it.
_CRR_SIGNIFICANT_INVESTMENT_RW = scalar_value(
    resolve("crr", date(2026, 1, 1)).scalar_param("equity_significant_investment_rw")
)

# Art. 132(2): CIU fallback risk weight — 1,250% under both CRR and B31.
# Punitive weight incentivises firms to use look-through or mandate-based approaches.
CIU_FALLBACK_RW = _CRR_SA_RW[EquityType.CIU]

# Art. 132(4): multiplier for third-party CIU calculations (20% uplift). Applies
# to BOTH approaches -- point (b) requires the third party to calculate "in
# accordance with the approaches set out in Article 132A(1), (2) or (3)", and
# 132A(1) IS the look-through approach. (The previous "Art. 132b(2)" attribution
# here was uncorroborated; the rule is Art. 132(4), verified against
# ps126app1.pdf pp.63-64.)
_CIU_THIRD_PARTY_MULTIPLIER = 1.2

# No multiplier for internally-managed CIU mandate calculations
_CIU_INTERNAL_MULTIPLIER = 1.0


# Equity input contract — defensive defaults for columns read by the equity
# calculator. `ead_final` is derived (not defaulted) so is handled separately.
_EQUITY_INPUT_CONTRACT: dict[str, ColumnSpec] = {
    "equity_type": ColumnSpec(pl.String, default="other", required=False),
    "is_diversified_portfolio": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_speculative": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_exchange_traded": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_government_supported": ColumnSpec(pl.Boolean, default=False, required=False),
    "ciu_approach": ColumnSpec(pl.String, required=False),
    "ciu_mandate_rw": ColumnSpec(pl.Float64, required=False),
    "ciu_third_party_calc": ColumnSpec(pl.Boolean, required=False),
    # Art. 132(4) derogation: unrestricted access to the third party's detailed
    # calculations disapplies the 1.2x factor.
    "ciu_unrestricted_access": ColumnSpec(pl.Boolean, default=False, required=False),
    "fund_reference": ColumnSpec(pl.String, required=False),
    "ciu_look_through_rw": ColumnSpec(pl.Float64, required=False),
    "fund_nav": ColumnSpec(pl.Float64, required=False),
    # Years the underlying PE/VC business has existed; used by the B31
    # Art. 133(4) higher-risk test (PRA PS1/26 Glossary p.5).
    "business_age_years": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 155(3): True -> firm has Art. 178 default-definition data so the
    # 1.5x PD/LGD scaling does NOT apply; False/null -> 1.5x scaling applies.
    "has_default_definition_info": ColumnSpec(pl.Boolean, default=False, required=False),
    # PS1/26 Art. 133(6)(c): a holding weighted 250% under Own Funds Art. 48(4)
    # (a significant investment) is "within scope of paragraph 6", which the
    # transitional rules 4.2 / 4.3 exclude by name. Read only by the
    # transitional; absent or null means not such a holding.
    "is_significant_investment": ColumnSpec(pl.Boolean, default=False, required=False),
}

# The OF 07.00 label of a leg weighted under the Standardised Transitional
# Approach for equities (Annex II rows 0371 / 0372, rules 4.1-4.3).
_SA_TRANSITIONAL_LABEL = "sa_transitional"

# Sentinel for null CQS in join operations (data processing convention)
_NULL_CQS_SENTINEL = -1

# Look-through weight of a holding whose class the engine identifies but the
# (exposure_class, CQS) table cannot price -- an unrated corporate, a retail or
# real-estate holding, ``other``. Nested CIUs, Basel 3.1 high-risk items and
# unidentified classes are resolved before it (see ``_holding_rw_expr``).
_DEFAULT_HOLDING_RW = 1.00

# Audit formatting: convert decimal RW to percentage display
_RW_TO_PERCENT = 100
_AUDIT_RWA_ROUND = 0


@cites("PS1/26, paragraph 132")
def _ciu_computed_rw_expr(rw_col: str) -> pl.Expr:
    """Art. 132(4): a CIU approach's own RW, uplifted 1.2x for third-party calcs.

    Two things the previous shape got wrong, both fixed here:

    - **The uplift reaches look-through, not just mandate-based.** Art. 132(4)(b)
      requires the third party to calculate "in accordance with the approaches set
      out in Article 132A(1), (2) or (3)", and 132A(1) *is* the look-through
      approach. Gating the multiplier on ``mandate_based`` recognised
      third-party look-through RW 20% too low.
    - **The fall-back is never uplifted.** Art. 132(4) multiplies the RWEA
      "resulting from those calculations". A null ``rw_col`` means there is no
      third-party calculation to multiply, so the row takes the Art. 132(2)
      1,250% fall-back flat. The old ``fill_null(CIU_FALLBACK_RW) * 1.2``
      produced 1,500% -- a weight no provision authorises, reachable purely
      from missing data.

    The derogation in the final sub-paragraph ("where the institution has
    unrestricted access to the detailed calculations carried out by the third
    party, the factor of 1.2 shall not apply") is an affirmative carve-out: a
    null ``ciu_unrestricted_access`` keeps the uplift.
    """
    # Both operands are filled before combining: a frame that carries the column
    # as an all-null literal has dtype Null, and `~` on Null raises rather than
    # returning null. Production frames always arrive Boolean via the contract
    # default, so this only guards synthetic single-row test frames.
    is_third_party = pl.col("ciu_third_party_calc").fill_null(False)
    has_unrestricted_access = pl.col("ciu_unrestricted_access").fill_null(False)
    multiplier = (
        pl.when(is_third_party & ~has_unrestricted_access)
        .then(pl.lit(_CIU_THIRD_PARTY_MULTIPLIER))
        .otherwise(pl.lit(_CIU_INTERNAL_MULTIPLIER))
    )
    return (
        pl.when(pl.col(rw_col).is_null())
        .then(pl.lit(CIU_FALLBACK_RW))
        .otherwise(pl.col(rw_col) * multiplier)
    )


@cites("PS1/26, paragraph 132")
def _append_ciu_branches(chain: pl.Expr) -> ChainedThen:
    """Append CIU approach-aware risk weight branches to a when/then chain (Art. 132-132C).

    Covers: fallback (1,250%), mandate_based and look_through (each x1.2 where the
    calculation is a third party's and Art. 132(4)'s unrestricted-access
    derogation does not apply), and unclassified CIU (1,250% default).
    """
    _is_ciu = pl.col("equity_type").str.to_lowercase() == "ciu"
    # The piped-in chain is an in-progress when/then; narrow for the checker.
    then_chain = cast("Then | ChainedThen", chain)
    return (
        then_chain.when(_is_ciu & (pl.col("ciu_approach") == "fallback"))
        .then(pl.lit(CIU_FALLBACK_RW))
        .when(_is_ciu & (pl.col("ciu_approach") == "mandate_based"))
        .then(_ciu_computed_rw_expr("ciu_mandate_rw"))
        .when(_is_ciu & (pl.col("ciu_approach") == "look_through"))
        .then(_ciu_computed_rw_expr("ciu_look_through_rw"))
        .when(_is_ciu)
        .then(pl.lit(CIU_FALLBACK_RW))
    )


class EquityCalculator:
    """
    Calculate RWA for equity exposures.

    Supports two approaches under CRR:
    - Article 133: Standardised Approach (100%/250%/400% RW)
    - Article 155: IRB Simple Risk Weight (190%/290%/370% RW)

    The approach is determined by config.irb_approach_option:
    - SA_ONLY: Uses Article 133
    - FIRB/AIRB/FULL_IRB: Uses Article 155

    Usage:
        calculator = EquityCalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def __init__(self) -> None:
        """Initialize equity calculator."""
        pass

    @cites("CRR Art. 133")
    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate equity RWA on pre-filtered equity-only rows.

        Args:
            exposures: Pre-filtered equity rows only
            config: Calculation configuration

        Returns:
            LazyFrame with equity RWA columns populated
        """
        approach = self._determine_approach(config)

        exposures = self._prepare_columns(exposures, config)

        # Art. 155(3) PD/LGD computes RWEA inside the branch (K formula) and
        # bypasses both the transitional and _calculate_rwa (CRR only).
        if approach == EquityApproach.PD_LGD:
            return self._apply_equity_weights_pd_lgd(exposures, config)

        if approach == EquityApproach.IRB_SIMPLE:
            exposures = self._apply_equity_weights_irb_simple(exposures, config)
        else:
            exposures = self._apply_equity_weights_sa(exposures, config)

        exposures = self._apply_standardised_equity_transitional(exposures, config)

        return self._calculate_rwa(exposures)

    @cites("CRR Art. 133")
    @cites("CRR Art. 155")
    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> EquityResultBundle:
        """
        Calculate equity RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            EquityResultBundle with results and audit trail
        """
        errors: list[CalculationError] = []

        exposures = data.equity_exposures

        if exposures is None:
            empty_frame = pl.LazyFrame(
                {
                    "exposure_reference": pl.Series([], dtype=pl.String),
                    "equity_type": pl.Series([], dtype=pl.String),
                    "ead_final": pl.Series([], dtype=pl.Float64),
                    "risk_weight": pl.Series([], dtype=pl.Float64),
                    "rwa": pl.Series([], dtype=pl.Float64),
                }
            )
            return EquityResultBundle(
                results=empty_frame,
                calculation_audit=empty_frame,
                approach=EquityApproach.SA,
                errors=[],
            )

        approach = self._determine_approach(config, pack=pack)

        exposures = self._prepare_columns(exposures, config)
        exposures = self._resolve_look_through_rw(exposures, data.ciu_holdings, config, pack=pack)

        # Art. 155(3) PD/LGD computes RWEA inside the branch and bypasses both
        # the transitional and _calculate_rwa (CRR only).
        if approach == EquityApproach.PD_LGD:
            exposures = self._apply_equity_weights_pd_lgd(exposures, config, pack=pack)
        else:
            if approach == EquityApproach.IRB_SIMPLE:
                exposures = self._apply_equity_weights_irb_simple(exposures, config)
            else:
                exposures = self._apply_equity_weights_sa(exposures, config, pack=pack)

            exposures = self._apply_standardised_equity_transitional(
                exposures, config, pack=pack, errors=errors
            )
            exposures = self._calculate_rwa(exposures)

        audit = self._build_audit(exposures, approach)

        return EquityResultBundle(
            results=exposures,
            calculation_audit=audit,
            approach=approach,
            errors=errors,
        )

    @cites("CRR Art. 155(3)")
    def _determine_approach(
        self,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> EquityApproach:
        """
        Determine SA, IRB_SIMPLE, or PD_LGD based on config.

        Under Basel 3.1 (CRE20.58-62): IRB for equity is removed — all equity
        exposures must use SA treatment. The IRB Simple Risk Weight Method
        (Art. 155: 190%/290%/370%) and the PD/LGD approach (Art. 155(3)) are no
        longer available; the ``equity_pd_lgd`` flag is ignored.

        Under CRR: If the firm has IRB permissions (FIRB or AIRB) for any
        exposure class, equity uses either the Art. 155(3) PD/LGD approach (when
        ``config.equity_pd_lgd`` is True) or the Art. 155(2) IRB Simple approach.
        If SA-only, use Article 133 SA approach.

        Args:
            config: Calculation configuration

        Returns:
            EquityApproach.SA (Art. 133), EquityApproach.IRB_SIMPLE (Art. 155(2)),
            or EquityApproach.PD_LGD (Art. 155(3))
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        # Basel 3.1: IRB equity removed — all equity uses SA (CRE20.58-62).
        # The equity_pd_lgd flag is ignored under Basel 3.1.
        if not resolved_pack.feature("equity_irb_approaches_available"):
            return EquityApproach.SA

        # CRR: a firm with FIRB or AIRB permission for any exposure class takes
        # an Art. 155 approach; an SA-only firm takes Art. 133.
        if not _has_irb_model_permission(config):
            return EquityApproach.SA

        # Art. 155(3): PD/LGD approach when the firm has elected it
        if config.equity_pd_lgd:
            return EquityApproach.PD_LGD
        return EquityApproach.IRB_SIMPLE

    def _prepare_columns(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults."""
        schema = exposures.collect_schema()

        if "ead_final" not in schema.names():
            if "fair_value" in schema.names():
                exposures = exposures.with_columns(
                    [
                        pl.col("fair_value").alias("ead_final"),
                    ]
                )
            elif "carrying_value" in schema.names():
                exposures = exposures.with_columns(
                    [
                        pl.col("carrying_value").alias("ead_final"),
                    ]
                )
            elif "ead" in schema.names():
                exposures = exposures.with_columns(
                    [
                        pl.col("ead").alias("ead_final"),
                    ]
                )
            else:
                exposures = exposures.with_columns(
                    [
                        pl.lit(0.0).alias("ead_final"),
                    ]
                )

        return ensure_columns(exposures, _EQUITY_INPUT_CONTRACT)

    def _resolve_look_through_rw(
        self,
        exposures: pl.LazyFrame,
        ciu_holdings: pl.LazyFrame | None,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Resolve look-through risk weights for CIU exposures (Art. 132A(1)).

        Joins CIU holdings to SA risk weight tables, weights each holding by
        its class (``_holding_rw_expr``: a nested CIU or an unidentified class
        takes the 1,250% fall-back, a Basel 3.1 high-risk item 150%),
        aggregates a value-weighted effective RW per fund, and sets
        ciu_look_through_rw.

        Leverage adjustment (Art. 132a(3)): When fund_nav is provided and total
        underlying assets exceed fund_nav (leveraged fund), the effective RW is
        grossed up by dividing weighted sum by fund_nav instead of total holding
        value. This ensures RWA reflects the fund's leverage.

        If no holdings are available, exposures are returned unchanged
        and the look-through CIU falls back to 1,250% in the when-chain.
        """
        if ciu_holdings is None:
            return exposures

        fallback_rw = CIU_FALLBACK_RW

        # Get CQS-based risk weight table for holding-level RW lookup
        from rwa_calc.engine.sa.crr_risk_weight_tables import get_combined_cqs_risk_weights

        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if resolved_pack.feature("sa_revised_risk_weight_tables"):
            from rwa_calc.engine.sa.b31_risk_weight_tables import (
                get_b31_combined_cqs_risk_weights,
            )

            rw_table = get_b31_combined_cqs_risk_weights().lazy()
        else:
            rw_table = get_combined_cqs_risk_weights().lazy()

        # Rules 4.7-4.8 higher-of for EQUITY-class look-through holdings.
        # An equity holding carries no ECAI CQS, so the (exposure_class, cqs)
        # join misses and risk_weight is null. When the Basel 3.1 equity
        # transitional regime is active for the reporting date, such holdings
        # take max(legacy Art. 155(2) simple RW, Rule 4.2/4.3 transitional SA
        # RW) instead of the _DEFAULT_HOLDING_RW fallback. Rule 4.7 confines
        # 4.8 to a firm that HAD IRB permission on 31 December 2026; this path
        # does not yet read that firm fact (direct equity does, in
        # _apply_standardised_equity_transitional), so a firm without IRB
        # permission also receives the higher-of here — a known gap, left
        # unchanged by the direct-equity fix and filed as its own item.
        equity_holding_fallback_rw = self._equity_holding_higher_of_rw(config, pack=resolved_pack)
        holding_rw_expr = _holding_rw_expr(resolved_pack, equity_holding_fallback_rw)

        # Join holdings to RW table by (exposure_class, cqs)
        # Use sentinel for null CQS to allow join
        holdings_with_rw = (
            ciu_holdings.with_columns(
                pl.col("cqs").fill_null(_NULL_CQS_SENTINEL).cast(pl.Int8).alias("cqs"),
                pl.col("exposure_class").str.to_uppercase().alias("exposure_class"),
            )
            .join(
                rw_table.with_columns(
                    pl.col("cqs").fill_null(_NULL_CQS_SENTINEL).cast(pl.Int8).alias("cqs"),
                ),
                on=["exposure_class", "cqs"],
                how="left",
            )
            .with_columns(holding_rw_expr.alias("holding_rw"))
        )

        # Aggregate risk-weighted sum and total holding value per fund
        fund_agg = holdings_with_rw.group_by("fund_reference").agg(
            (pl.col("holding_value") * pl.col("holding_rw")).sum().alias("_weighted_sum"),
            pl.col("holding_value").sum().alias("_total_value"),
        )

        # Get fund_nav per fund from exposures for leverage adjustment (Art. 132a(3))
        # When fund_nav is provided and > 0, use it as the denominator instead of
        # total holding value. This correctly handles leveraged funds where
        # total_assets > NAV.
        fund_nav_df = (
            exposures.filter(
                (pl.col("equity_type").str.to_lowercase() == "ciu")
                & (pl.col("ciu_approach") == "look_through")
                & pl.col("fund_reference").is_not_null()
            )
            .select(["fund_reference", "fund_nav"])
            .unique(subset=["fund_reference"])
        )

        fund_rw = (
            fund_agg.join(fund_nav_df, on="fund_reference", how="left")
            .with_columns(
                # Art. 132a(3): use fund_nav as denominator when available (leverage-aware)
                # Fall back to total holding value when fund_nav absent (backward compat)
                pl.coalesce(
                    pl.when(pl.col("fund_nav") > 0).then(pl.col("fund_nav")),
                    pl.when(pl.col("_total_value") > 0).then(pl.col("_total_value")),
                ).alias("_denominator"),
            )
            .with_columns(
                pl.when(pl.col("_denominator").is_not_null() & (pl.col("_denominator") > 0))
                .then(pl.col("_weighted_sum") / pl.col("_denominator"))
                .otherwise(pl.lit(fallback_rw))
                .alias("_fund_look_through_rw"),
            )
            .select(["fund_reference", "_fund_look_through_rw"])
        )

        # Join back to exposures and set ciu_look_through_rw
        return (
            exposures.join(fund_rw, on="fund_reference", how="left")
            .with_columns(
                pl.when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "look_through")
                    & pl.col("_fund_look_through_rw").is_not_null()
                )
                .then(pl.col("_fund_look_through_rw"))
                .otherwise(pl.col("ciu_look_through_rw"))
                .alias("ciu_look_through_rw"),
            )
            .drop("_fund_look_through_rw")
        )

    @cites("CRR Art. 155(2)")
    @cites("PS1/26, paragraph 4.8")
    @cites("PS1/26, paragraph 4.9")
    def _equity_holding_higher_of_rw(
        self, config: CalculationConfig, *, pack: ResolvedRulepack | None = None
    ) -> float | None:
        """Rules 4.7-4.8 higher-of RW for EQUITY-class CIU look-through holdings.

        Returns ``max(legacy Art. 155(2) "other equity" simple RW, Rule 4.2/4.3
        transitional SA RW)`` when the Basel 3.1 equity transitional regime is
        active for the reporting date, else ``None`` (no override — holdings keep
        the _DEFAULT_HOLDING_RW fallback).

        The gate is the ``equity_transitional`` Feature plus a transitional RW
        existing for the reporting date. Rule 4.7 confines rule 4.8 to a firm
        that had IRB permission on 31 December 2026; this helper does not read
        that firm fact (see the note in ``_resolve_look_through_rw``).

        Per Rule 4.9-4.10, a firm that has irrevocably opted out of the
        transitional regime (``equity_transitional.opt_out``) suppresses the
        higher-of: ``None`` is returned so the holding falls back to the
        ``_DEFAULT_HOLDING_RW`` standard treatment.

        References:
        - CRR Art. 155(2): IRB simple method equity RW ("other" = 370%).
        - PRA PS1/26 Rule 4.8: higher-of(Art. 155(2) simple, Rule 4.2/4.3 band).
        - PRA PS1/26 Rule 4.9-4.10: irrevocable joint opt-out suppresses higher-of.
        """
        if config.equity_transitional.opt_out:
            return None

        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        transitional_rw = _equity_transitional_rw(
            resolved_pack, config.reporting_date, is_higher_risk=False
        )
        if transitional_rw is None:
            return None

        legacy_simple_rw = _IRB_RW[EquityType.OTHER]
        return max(legacy_simple_rw, float(transitional_rw))

    def _apply_equity_weights_sa(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Apply SA equity risk weights, branching by framework.

        CRR Art. 133(2): 100% flat (with 0% for central bank);
            CIU via Art. 132 (1,250% fallback per Art. 132(2))
        Basel 3.1 Art. 133(3)-(5): 250% / 400% / 150% (sub debt)
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if resolved_pack.feature("equity_revised_sa_risk_weights"):
            weighted = self._apply_b31_equity_weights_sa(exposures, config)
        else:
            weighted = self._apply_crr_equity_weights_sa(exposures, config)
        # Record the CRR equity method actually applied (Art. 133 SA here) so
        # the reporting ledger can partition simple-RW (Art. 155(2)) equity into
        # Pillar 3 CR10.5 without re-deriving the approach downstream.
        return weighted.with_columns(pl.lit(EquityApproach.SA.value).alias("equity_method"))

    def _apply_crr_equity_weights_sa(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply CRR Article 133 SA equity risk weights.

        Art. 133(2): "Equity exposures shall be assigned a risk weight of 100%,
        unless they are required to be deducted [...], assigned a 250% risk weight
        in accordance with Article 48(4), assigned a 1250% risk weight in accordance
        with Article 89(3) or treated as high risk items in accordance with Article 128."

        Risk weights:
        - Central bank: 0% (sovereign treatment)
        - CIU: Art. 132 treatment (1,250% fallback, look-through, mandate-based)
        - Significant investment (``is_significant_investment``): 250%, the
          Art. 48(4) weight Art. 133(2) defers to (IV-06; see
          ``_crr_significant_investment_expr``)
        - All other equity: 100% (Art. 133(2) flat)

        Note: PE/VC qualifying as high-risk is routed to Art. 128 (150%) via the
        classifier's HIGH_RISK exposure class, not through this equity calculator.
        """
        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(_CRR_SA_RW[EquityType.CENTRAL_BANK]))
                # CIU: approach-aware risk weights (Art. 132-132C)
                .pipe(_append_ciu_branches)
                # Art. 133(2) / Art. 48(4): significant investment = 250%
                .when(_crr_significant_investment_expr())
                .then(pl.lit(_CRR_SIGNIFICANT_INVESTMENT_RW))
                # Art. 133(2): all other equity = 100%
                .otherwise(pl.lit(_CRR_SA_RW[EquityType.OTHER]))
                .alias("risk_weight"),
            ]
        )

    @cites("PS1/26, paragraph 133")
    def _apply_b31_equity_weights_sa(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply Basel 3.1 PRA PS1/26 Art. 133 SA equity risk weights.

        Risk weights (in priority order per classification decision tree):
        1. Central bank: 0%  (sovereign treatment)
        2. Subordinated debt / non-equity own funds: 150%  (Art. 133(5))
        3. Speculative / higher risk: 400%  (Art. 133(4))
        4. Higher-risk test (Art. 133(4) + Glossary p.5), for any equity that
           is not central-bank / subordinated-debt / CIU / government-supported:
           - unlisted (NOT is_exchange_traded) AND business_age_years < 5.0
             (or null, treated conservatively) -> 400% (higher-risk)
           - otherwise -> falls through to standard 250% (Art. 133(3))
        5. CIU: approach-dependent  (Art. 132-132C)
           - CIU fallback: 1,250%  (Art. 132(2))
        6. All other standard equity (incl. government-supported, listed, and
           long-established/exchange-traded equity): 250%  (Art. 133(3))

        Note: B31 Art. 133(6) is an exclusion clause (own funds deductions,
        Art. 89(3), Art. 48(4)) — NOT a risk weight assignment. CRR's 100%
        legislative equity (Art. 133(3)(c)) has no equivalent in B31.

        Rows 3 and 4 are one predicate, ``_b31_higher_risk_expr``, which the
        rules 4.2 / 4.3 transitional reads too: the leg the transitional
        treats as higher risk is exactly the leg this chain put on the
        Art. 133(4) rung.
        """
        is_higher_risk = _b31_higher_risk_expr(exposures.collect_schema().names())

        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(_B31_SA_RW[EquityType.CENTRAL_BANK]))
                # Art. 133(5): subordinated debt / non-equity own funds = 150%
                .when(pl.col("equity_type").str.to_lowercase() == "subordinated_debt")
                .then(pl.lit(_B31_SA_RW[EquityType.SUBORDINATED_DEBT]))
                # Art. 133(4): higher risk equity = 400% (speculative flag or
                # type, or the Glossary unlisted-and-under-five-years test).
                .when(is_higher_risk)
                .then(pl.lit(_B31_SA_RW[EquityType.SPECULATIVE]))
                # CIU: approach-aware risk weights (Art. 132-132C)
                .pipe(_append_ciu_branches)
                .otherwise(pl.lit(_B31_SA_RW[EquityType.OTHER]))
                .alias("risk_weight"),
            ]
        )

    @cites("CRR Art. 155(2)")
    def _apply_equity_weights_irb_simple(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply Article 155 (IRB Simple) equity risk weights and Art. 158(7) EL.

        Risk weights (Art. 155(2)) and paired expected-loss rates (Art. 158(7)):
        - Central bank: 0% RW, 0.0% EL
        - Private equity (diversified portfolio): 190% RW, 0.8% EL
        - Exchange-traded / listed: 290% RW, 0.8% EL
        - All other equity: 370% RW, 2.4% EL

        The Art. 158(7) expected-loss amount is ``EL rate x ead_final`` and shares
        the RW when-chain's bucket predicates so each EL rate pairs with its RW.
        It is a disclosure quantity (COREP C08 / Pillar 3 IRB EL) — Art. 155(2)
        does not gross the equity RWA up by EL, and Art. 159 subtracts only the
        Art. 158(5),(6),(10) EL amounts from provisions, so equity simple EL does
        not enter the EL-vs-provisions shortfall/excess machinery.

        Before assigning risk weights this nets non-trading-book short positions
        against long positions in the same individual stock per Art. 155(2)
        (see ``_net_short_positions``).

        A leg flagged ``is_significant_investment`` is not an Art. 155 leg at
        all: Art. 155(1) applies the approaches to equity "excluding those
        deducted in accordance with Part Two or subject to a 250 % risk weight
        in accordance with Article 48". It takes the Art. 48(4) 250% (lower than
        the 290% / 370% simple weights -- RWA-reducing, IV-06), no Art. 158(7)
        EL, and is sealed ``equity_method == "sa"`` so CR10.5 and C 02.00's
        Equity IRB row do not disclose it as simple-RW equity.
        """
        exposures = self._net_short_positions(exposures)

        # Shared bucket predicates so the RW and EL when-chains stay in lockstep
        # (each Art. 158(7) EL rate must pair with its Art. 155(2) RW bucket).
        eq_type = pl.col("equity_type").str.to_lowercase()
        is_central_bank = eq_type == "central_bank"
        is_significant_investment = _crr_significant_investment_expr()
        is_diversified_pe = (eq_type == "private_equity_diversified") | (
            (eq_type == "private_equity") & (pl.col("is_diversified_portfolio") == True)  # noqa: E712
        )
        is_exchange_traded = pl.col("is_exchange_traded") == True  # noqa: E712
        is_listed = eq_type == "listed"
        is_exchange_traded_type = eq_type == "exchange_traded"

        risk_weight = (
            pl.when(is_central_bank)
            .then(pl.lit(_IRB_RW[EquityType.CENTRAL_BANK]))
            # Art. 155(1) exclusion: the Art. 48(4) 250% leg.
            .when(is_significant_investment)
            .then(pl.lit(_CRR_SIGNIFICANT_INVESTMENT_RW))
            .when(is_diversified_pe)
            .then(pl.lit(_IRB_RW[EquityType.PRIVATE_EQUITY_DIVERSIFIED]))
            .when(is_exchange_traded)
            .then(pl.lit(_IRB_RW[EquityType.EXCHANGE_TRADED]))
            .when(is_listed)
            .then(pl.lit(_IRB_RW[EquityType.LISTED]))
            .when(is_exchange_traded_type)
            .then(pl.lit(_IRB_RW[EquityType.EXCHANGE_TRADED]))
            # CRR Art. 155(2)(c): "all other equity" 370% — including
            # government_supported, which has no Art. 155 carve-out.
            .otherwise(pl.lit(_IRB_RW[EquityType.OTHER]))
        )

        # Art. 158(7) EL rate, matched bucket-for-bucket to the RW chain above.
        el_rate = (
            pl.when(is_central_bank)
            .then(pl.lit(_IRB_SIMPLE_EL[EquityType.CENTRAL_BANK]))
            # Outside Art. 155, so no Art. 158(7) simple-RW EL (null, as on SA legs).
            .when(is_significant_investment)
            .then(pl.lit(None, dtype=pl.Float64))
            .when(is_diversified_pe)
            .then(pl.lit(_IRB_SIMPLE_EL[EquityType.PRIVATE_EQUITY_DIVERSIFIED]))
            .when(is_exchange_traded)
            .then(pl.lit(_IRB_SIMPLE_EL[EquityType.EXCHANGE_TRADED]))
            .when(is_listed)
            .then(pl.lit(_IRB_SIMPLE_EL[EquityType.LISTED]))
            .when(is_exchange_traded_type)
            .then(pl.lit(_IRB_SIMPLE_EL[EquityType.EXCHANGE_TRADED]))
            .otherwise(pl.lit(_IRB_SIMPLE_EL[EquityType.OTHER]))
        )

        return exposures.with_columns(
            risk_weight.alias("risk_weight"),
            (el_rate * pl.col("ead_final")).alias("expected_loss"),
            # Art. 155(2) simple-RW method tag — the discriminator Pillar 3
            # CR10.5 filters on (reporting_approach_origin == "equity" AND
            # equity_method == "irb_simple"). An Art. 48(4) leg is excluded
            # from Art. 155 by its paragraph 1, so it is sealed ``sa``.
            _significant_investment_method_expr(
                is_significant_investment, EquityApproach.IRB_SIMPLE
            ).alias("equity_method"),
        )

    @cites("CRR Art. 155(2)")
    def _net_short_positions(self, exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Net non-trading-book short positions against longs (CRR Art. 155(2)).

        Under the IRB Simple Risk Weight Method, short cash positions and
        derivatives held in the non-trading book may offset long positions in
        the *same individual stock* provided the offsetting short is an explicit
        hedge covering at least one year. Other short positions are treated as
        long with the relevant RW applied to their absolute value.

        Mechanics (LazyFrame-first, column-absence defensive):
        - Eligibility requires the optional inputs ``position_value`` and
          ``issuer_reference``; absent either, ``exposures`` is returned
          unchanged so production frames behave exactly as before.
        - A row is netting-eligible when it carries a non-null
          ``issuer_reference`` and ``is_explicitly_hedged`` is True (the boolean
          encodes "explicit hedge >= 1 year", ``CRR_EQUITY_NETTING_MIN_HEDGE_YEARS``).
        - Net long per issuer = ``max(0, sum(signed position_value))`` over the
          eligible rows. The surviving long row(s) carry the netted EAD pro-rata
          to their gross long value; absorbed shorts (and any rows whose group
          nets to <= 0) collapse to ``ead_final`` 0. Net-short residual is
          floored at 0 (out of scope here).
        - Ineligible rows keep their existing ``ead_final`` (the absolute-value
          ``fair_value``/``carrying_value``/``ead`` chain).
        """
        schema_names = exposures.collect_schema().names()
        if "position_value" not in schema_names or "issuer_reference" not in schema_names:
            return exposures

        is_hedged = (
            pl.col("is_explicitly_hedged").fill_null(False)
            if "is_explicitly_hedged" in schema_names
            else pl.lit(False)
        )
        # Eligible: a hedged position on a known issuer with a signed value.
        eligible = (
            pl.col("issuer_reference").is_not_null()
            & pl.col("position_value").is_not_null()
            & is_hedged
        )
        signed = pl.col("position_value").fill_null(0.0)
        gross_long = pl.when(eligible & (signed > 0)).then(signed).otherwise(pl.lit(0.0))

        # Per-issuer windowed aggregates over eligible rows only.
        net_long_per_issuer = (
            pl.when(eligible)
            .then(signed)
            .otherwise(pl.lit(0.0))
            .sum()
            .over("issuer_reference")
            .clip(lower_bound=0.0)
        )
        gross_long_per_issuer = gross_long.sum().over("issuer_reference")

        # Distribute the issuer's net long across its long rows pro-rata to
        # their gross long value; eligible shorts (and longs in a net-short or
        # fully-netted group) collapse to 0. Ineligible rows are untouched.
        share = (
            pl.when(gross_long_per_issuer > 0)
            .then(gross_long / gross_long_per_issuer)
            .otherwise(pl.lit(0.0))
        )
        netted_ead = net_long_per_issuer * share

        return exposures.with_columns(
            pl.when(eligible).then(netted_ead).otherwise(pl.col("ead_final")).alias("ead_final"),
        )

    @cites("CRR Art. 155(3)")
    @cites("CRR Art. 165")
    def _apply_equity_weights_pd_lgd(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Apply the Article 155(3) PD/LGD equity approach.

        Risk-weighted exposure amounts are calculated with the corporate IRB K
        formula (Art. 153(1)) using supervisory parameters from Art. 165:

        - PD floor (Art. 165(1)): by equity sub-type —
            exchange-traded long-term / non-exchange regular cash flow -> 0.09%,
            exchange-traded (incl. short positions) -> 0.40%,
            all other equity -> 1.25%.
        - LGD (Art. 165(2)): 65% for sufficiently-diversified private equity
            (equity_type == "private_equity_diversified"), else 90%.
        - M (Art. 165(3)): fixed at 5 years.
        - Scaling (Art. 153): 1.06 for CRR.

        RWEA = K x 12.5 x scaling x MA x EAD, EL = PD x LGD x EAD. Per Art. 155(3)
        the result is capped at the individual-exposure level so that
        ``EL x 12.5 + RWEA <= EAD x 12.5`` (equivalently RWEA <= EAD x 12.5 - EL x 12.5,
        clamped at 0). A 1.5x scaling is applied to the risk weights where the
        institution lacks Art. 178 default-definition data
        (has_default_definition_info == False).

        The PS1/26 rules 4.1-4.3 transitional does NOT apply: PD/LGD is a CRR
        approach, and the transitional modifies Basel 3.1 Art. 133.
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        scaling_factor = scalar_value(resolved_pack.scalar_param("irb_scaling_factor"))
        maturity = scalar_value(resolved_pack.scalar_param("equity_pd_lgd_maturity"))
        equity_lgd = formula_float_map(resolved_pack.formula("equity_pd_lgd_lgd"))
        lgd_diversified = equity_lgd["private_equity_diversified"]
        lgd_other = equity_lgd["other"]
        no_default_info_scaling = scalar_value(
            resolved_pack.scalar_param("equity_pd_lgd_no_default_info_scaling")
        )
        equity_pd_floors = formula_float_map(resolved_pack.formula("equity_pd_floors"))
        pd_floor_exchange_traded = equity_pd_floors["exchange_traded"]
        pd_floor_other = equity_pd_floors["other"]

        eq_type = pl.col("equity_type").str.to_lowercase()
        is_exchange_traded = pl.col("is_exchange_traded").fill_null(False)

        # Art. 165(1): PD floor by equity sub-type. Exchange-traded equity uses
        # the 0.40% Art. 165(1)(c) floor; all other equity uses 1.25% (165(1)(d)).
        pd_floored = (
            pl.when(is_exchange_traded | (eq_type == "exchange_traded") | (eq_type == "listed"))
            .then(pl.lit(pd_floor_exchange_traded))
            .otherwise(pl.lit(pd_floor_other))
        )

        # Art. 165(2): supervisory LGD — 65% diversified PE, else 90%.
        lgd = (
            pl.when(eq_type == "private_equity_diversified")
            .then(pl.lit(lgd_diversified))
            .otherwise(pl.lit(lgd_other))
        )

        # Corporate IRB K formula inputs (Art. 153(1)). The shared expressions
        # read exposure_class, turnover_m, requires_fi_scalar, maturity and
        # has_one_day_maturity_floor — set them to the corporate-equity defaults.
        exposures = exposures.with_columns(
            pl.lit(ExposureClass.CORPORATE.value.upper()).alias("exposure_class"),
            pl.lit(None).cast(pl.Float64).alias("turnover_m"),
            pl.lit(False).alias("requires_fi_scalar"),
            pl.lit(maturity).alias("maturity"),
            pl.lit(False).alias("has_one_day_maturity_floor"),
            pd_floored.alias("pd_floored"),
            lgd.alias("lgd"),
        )

        correlation = _correlation_expr_from_pd(
            pl.col("pd_floored"),
            eur_gbp_rate=float(config.eur_gbp_rate),
            is_b31=resolved_pack.feature("irb_correlation_sme_gbp_native"),
        )
        exposures = exposures.with_columns(correlation.alias("correlation"))

        k = _capital_k_expr_from_params(pl.col("pd_floored"), pl.col("lgd"), pl.col("correlation"))
        ma = _maturity_adjustment_expr_from_pd(pl.col("pd_floored"))
        exposures = exposures.with_columns(
            k.alias("k"),
            ma.alias("maturity_adjustment"),
            pl.lit(scaling_factor).alias("scaling_factor"),
        )

        # Art. 155(3): 1.5x scaling where the firm lacks Art. 178 default data.
        no_default_info = ~pl.col("has_default_definition_info").fill_null(False)
        rw_scaling = (
            pl.when(no_default_info).then(pl.lit(no_default_info_scaling)).otherwise(pl.lit(1.0))
        )

        # Base risk weight (Art. 153(1)): K x 12.5 x scaling x MA, then 1.5x where applicable.
        risk_weight = (
            pl.col("k") * 12.5 * pl.col("scaling_factor") * pl.col("maturity_adjustment")
        ) * rw_scaling

        # Art. 155(1) excludes the Art. 48(4) 250% leg from the PD/LGD approach:
        # it takes the flat 250% (IV-06), no EL and no Art. 155(3) cap, and keeps
        # the equity class the K formula's corporate inputs overwrote.
        is_significant_investment = _crr_significant_investment_expr()
        exposures = exposures.with_columns(
            pl.when(is_significant_investment)
            .then(pl.lit(_CRR_SIGNIFICANT_INVESTMENT_RW))
            .otherwise(risk_weight)
            .alias("risk_weight"),
            pl.when(is_significant_investment)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("pd_floored") * pl.col("lgd") * pl.col("ead_final"))
            .alias("expected_loss"),
        )

        # Uncapped RWEA = RW x EAD.
        rwea = pl.col("risk_weight") * pl.col("ead_final")
        # Art. 155(3) cap: EL x 12.5 + RWEA <= EAD x 12.5, i.e.
        # RWEA <= EAD x 12.5 - EL x 12.5, clamped at 0.
        rwea_cap = (pl.col("ead_final") * 12.5 - pl.col("expected_loss") * 12.5).clip(
            lower_bound=0.0
        )
        rwea_capped = (
            pl.when(is_significant_investment)
            .then(rwea)
            .otherwise(pl.min_horizontal(rwea, rwea_cap))
        )

        return exposures.with_columns(
            (~is_significant_investment & (rwea > rwea_cap)).alias("equity_pd_lgd_cap_binds"),
            rwea_capped.alias("rwa"),
            rwea_capped.alias("rwa_final"),
            # Art. 155(3) PD/LGD method tag — kept OUT of Pillar 3 CR10.5, which
            # discloses only the Art. 155(2) simple-RW method. The Art. 48(4)
            # leg is not an Art. 155 leg and is sealed ``sa``.
            _significant_investment_method_expr(
                is_significant_investment, EquityApproach.PD_LGD
            ).alias("equity_method"),
            pl.when(is_significant_investment)
            .then(pl.lit(ExposureClass.EQUITY.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),
        )

    @cites("PS1/26, paragraph 4.1")
    @cites("PS1/26, paragraph 4.2")
    @cites("PS1/26, paragraph 4.3")
    def _apply_standardised_equity_transitional(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Assign the Standardised Transitional Approach weights (PS1/26 rules 4.1-4.3).

        Rule 4.1: "4.2 and 4.3 only apply to an institution that did not have
        permission to use the Internal Ratings Based Approach under Article 143
        of CRR on 31 December 2026." Rule 4.2 "modifies paragraph 3 of [...]
        Article 133 for a transitional period beginning with 1 January 2027 and
        ending with 31 December 2029, in which equity exposures that are not
        higher risk equity exposures or within the scope of paragraph 6 [...]
        shall be assigned the following risk weights": 160% / 190% / 220%.
        Rule 4.3 does the same for higher risk equity under paragraph 4:
        220% / 280% / 340% (ps126app1.pdf pp.20-21).

        The weights REPLACE the Art. 133(3) / (4) 250% / 400% ("shall be
        assigned", the verb Art. 133 itself uses); they are not a floor under
        them. For such a firm, inside the period, each leg in scope takes the
        rule 4.3 weight when ``_b31_higher_risk_expr`` — the predicate that put
        it on the Art. 133(4) rung — holds, else the rule 4.2 weight.

        In scope: equity exposures weighted under Art. 133(3) / (4). Out of
        scope, weight untouched: subordinated debt (Art. 133(5), not an equity
        exposure), CIUs (Arts. 132-132C), the 0% central-bank type, and an
        Art. 133(6)(c) significant investment (``is_significant_investment``).

        Carriers, for OF 07.00 (Annex II p.95: report "against the risk weights
        set out in Article 133 [...] disregarding the transitional provisions.
        However, the RWEA shall still reflect the transitional provisions"):
        ``equity_transitional_approach`` ("sa_transitional"),
        ``equity_higher_risk`` and ``risk_weight_pre_equity_transitional`` (the
        Art. 133 weight) are non-null ONLY on a leg whose weight this method
        set. Under Basel 3.1 all three are always emitted, as typed nulls when
        nothing is in scope; under CRR (no ``equity_transitional`` Feature)
        none is.

        Not applied, weights untouched, carriers null:
        - outside 1 January 2027 - 31 December 2029 (the schedule's last step
          is the end state; Annex II: no values in rows 0371-0374 from 2030);
        - a firm that HAD IRB permission on 31 December 2026 (rule 4.1; F-IRB,
          A-IRB or slotting, see ``_had_irb_permission_at_2026_year_end``). Its
          own rules are not implemented: 4.5(1), the 4.2 / 4.3 weights for
          equity it held under Art. 148 / 150 Standardised permission, and 4.6,
          the higher of the legacy Art. 155 weight and the 4.2 / 4.3 weight for
          equity it held under the IRB Approach. So it keeps the Art. 133
          weights, which is the rule 4.9 election; unless it has made that
          election (``opt_out``) the run is warned (CFG003), on any equity table
          (the warning is not gated on an in-scope leg, see
          ``_irb_firm_transitional_warning``).

        ``opt_out`` has no effect for a firm without IRB permission: rule 4.9
        replaces only "the alternative approaches set out in 4.5, 4.6 and
        4.8", so there is nothing for it to elect, and setting it is warned.
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if not resolved_pack.feature("equity_transitional"):
            return exposures

        weights = _standardised_transitional_weights(resolved_pack, config.reporting_date)
        if weights is None:
            return _with_null_transitional_carriers(exposures)

        opt_out = config.equity_transitional.opt_out
        if _had_irb_permission_at_2026_year_end(config):
            if errors is not None and not opt_out:
                errors.append(_irb_firm_transitional_warning())
            return _with_null_transitional_carriers(exposures)
        if errors is not None and opt_out:
            errors.append(_opt_out_without_irb_permission_warning())

        std_rw, hr_rw = weights
        in_scope = _standardised_transitional_scope_expr()
        # A null predicate takes the otherwise arm, exactly as it does in the
        # Art. 133 weight chain, so a leg is higher risk here iff it got 400%.
        is_higher_risk = (
            pl.when(_b31_higher_risk_expr(exposures.collect_schema().names()))
            .then(pl.lit(value=True))
            .otherwise(pl.lit(value=False))
        )
        return exposures.with_columns(
            pl.when(in_scope)
            .then(pl.col("risk_weight"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias("risk_weight_pre_equity_transitional"),
            pl.when(in_scope)
            .then(pl.lit(_SA_TRANSITIONAL_LABEL))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("equity_transitional_approach"),
            pl.when(in_scope)
            .then(is_higher_risk)
            .otherwise(pl.lit(None, dtype=pl.Boolean))
            .alias("equity_higher_risk"),
            pl.when(in_scope & is_higher_risk)
            .then(pl.lit(hr_rw))
            .when(in_scope)
            .then(pl.lit(std_rw))
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
        )

    def _calculate_rwa(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Calculate RWA = EAD x RW."""
        return exposures.with_columns(
            [
                (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"),
                (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa_final"),
            ]
        )

    def _build_audit(
        self,
        exposures: pl.LazyFrame,
        approach: EquityApproach,
    ) -> pl.LazyFrame:
        """Build equity calculation audit trail."""
        schema = exposures.collect_schema()
        available_cols = schema.names()

        select_cols = ["exposure_reference"]
        optional_cols = [
            "counterparty_reference",
            "equity_type",
            "is_speculative",
            "is_exchange_traded",
            "is_government_supported",
            "is_diversified_portfolio",
            "ead_final",
            "risk_weight",
            "rwa",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = exposures.select(select_cols)

        article = "Art. 133 SA" if approach == EquityApproach.SA else "Art. 155 IRB Simple"

        audit = audit.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit(f"Equity ({article}): Type="),
                        pl.col("equity_type"),
                        pl.lit(", RW="),
                        (pl.col("risk_weight") * _RW_TO_PERCENT)
                        .round(_AUDIT_RWA_ROUND)
                        .cast(pl.String),
                        pl.lit("%, RWA="),
                        pl.col("rwa").round(_AUDIT_RWA_ROUND).cast(pl.String),
                    ]
                ).alias("equity_calculation"),
            ]
        )

        return audit


def create_equity_calculator() -> EquityCalculator:
    """
    Create an equity calculator instance.

    Returns:
        EquityCalculator ready for use
    """
    return EquityCalculator()


def _equity_transitional_rw(
    pack: ResolvedRulepack, on: date, *, is_higher_risk: bool
) -> Decimal | None:
    """Transitional equity RW for ``on``, or None outside the transition window.

    Pack twin of ``EquityTransitionalConfig.get_transitional_rw`` (Phase 5
    S11e): the VALUES live in the ``equity_transitional_std_rw`` /
    ``equity_transitional_hr_rw`` rulepack Schedules, gated by the
    ``equity_transitional`` Feature. Returns ``None`` when the regime is off
    or ``on`` precedes the first scheduled step — the Schedule's
    ``before_first`` (0.0) would otherwise read as a real 0% floor, so the
    explicit ``None`` preserves the config method's "no transition → skip"
    contract byte-identically.
    """
    if not pack.feature("equity_transitional"):
        return None
    sched = pack.schedule(
        "equity_transitional_hr_rw" if is_higher_risk else "equity_transitional_std_rw"
    )
    if on < sched.steps[0][0]:
        return None
    return sched.resolve(on)


def _has_irb_model_permission(config: CalculationConfig) -> bool:
    """True when the firm holds F-IRB or A-IRB permission for any exposure class."""
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    permissions = config.irb_permissions.permissions  # ty: ignore[unresolved-attribute]
    return any(
        ApproachType.FIRB in approaches or ApproachType.AIRB in approaches
        for approaches in permissions.values()
    )


@cites("CRR Art. 143")
@cites("CRR Art. 153(5)")
@cites("PS1/26, paragraph 4.1")
def _had_irb_permission_at_2026_year_end(config: CalculationConfig) -> bool:
    """Rule 4.1's firm fact: IRB permission under Art. 143 of CRR on 31 December 2026.

    Rule 4.1 (ps126app1.pdf p.20): "4.2 and 4.3 only apply to an institution
    that did not have permission to use the Internal Ratings Based Approach
    under Article 143 of CRR on 31 December 2026." Slotting is one of those
    approaches: Art. 143(2A) (p.81) has an application name "one or more of the
    following IRB Approaches instead of the Standardised Approach: (a) the
    Slotting Approach; (b) the Foundation IRB Approach; or (c) the Advanced IRB
    Approach", and Art. 153(5) (p.102), "The Slotting Approach applies as
    follows for specialised lending exposures", sits in the IRB Part. So a firm
    whose only IRB permission is slotting HAD IRB permission and is outside
    rules 4.2 / 4.3.

    ``EquityTransitionalConfig.irb_permission_at_2026_year_end`` states the fact
    when the run's permissions do not (a Standardised shadow run of an IRB firm,
    or a permission granted after that date). Left as None, it is derived from
    the run: any F-IRB, A-IRB or slotting permission. That is deliberately wider
    than ``_has_irb_model_permission``, which ``EquityCalculator._determine_approach``
    reads to route CRR equity to Art. 155 and which this fact does not change.
    """
    stated = config.equity_transitional.irb_permission_at_2026_year_end
    if stated is not None:
        return stated
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    permissions = config.irb_permissions.permissions  # ty: ignore[unresolved-attribute]
    irb_approaches = {ApproachType.FIRB, ApproachType.AIRB, ApproachType.SLOTTING}
    return any(not irb_approaches.isdisjoint(approaches) for approaches in permissions.values())


def _standardised_transitional_weights(
    pack: ResolvedRulepack, on: date
) -> tuple[float, float] | None:
    """Rules 4.2 / 4.3 (standard, higher risk) weights for ``on``, or None outside the period.

    The period is the ``equity_transitional_std_rw`` Schedule's first step
    (1 January 2027) up to, not including, its last step (1 January 2030), which
    is the Art. 133(3) / (4) end state rather than a transitional weight.
    """
    standard = pack.schedule("equity_transitional_std_rw")
    first_day, end_state_day = standard.steps[0][0], standard.steps[-1][0]
    if not first_day <= on < end_state_day:
        return None
    higher_risk = pack.schedule("equity_transitional_hr_rw")
    return float(standard.resolve(on)), float(higher_risk.resolve(on))


@cites("PS1/26, paragraph 133")
def _b31_higher_risk_expr(schema_names: Collection[str]) -> pl.Expr:
    """Art. 133(4): the one predicate that puts a Basel 3.1 equity leg on the 400% rung.

    True for the ``is_speculative`` flag, the ``speculative`` type, and the
    Glossary "higher risk equity exposure" test (p.5: "not listed on a
    recognised exchange; and [...] whose business has existed for a period of
    less than five years"), routed two ways:

    - unlisted private equity (diversified or not) whose business age is under
      five years OR unknown — a firm cannot claim the long-established
      carve-out without evidence of age;
    - any other unlisted equity that is not central-bank, subordinated debt, a
      CIU or government-supported, when its business age is evidenced (non-null)
      and under five years.

    Read by the Art. 133 weight chain and by the rules 4.2 / 4.3 transitional,
    so the transitional treats as higher risk exactly the legs that were
    weighted as such. Callers outside the input contract may lack
    ``is_exchange_traded`` / ``business_age_years``; absent means unlisted /
    unknown age.
    """
    eq_type = pl.col("equity_type").str.to_lowercase()
    is_pe_or_pe_div = eq_type.is_in(
        [EquityType.PRIVATE_EQUITY, EquityType.PRIVATE_EQUITY_DIVERSIFIED]
    )
    is_dedicated_treatment = eq_type.is_in(
        [
            EquityType.CENTRAL_BANK,
            EquityType.SUBORDINATED_DEBT,
            EquityType.CIU,
            EquityType.GOVERNMENT_SUPPORTED,
        ]
    )
    is_unlisted = (
        ~pl.col("is_exchange_traded").fill_null(False)
        if "is_exchange_traded" in schema_names
        else pl.lit(True)
    )
    has_age = "business_age_years" in schema_names
    is_young_or_unknown = (
        pl.col("business_age_years").is_null() | (pl.col("business_age_years") < 5.0)
        if has_age
        else pl.lit(True)
    )
    is_young_evidenced = (
        pl.col("business_age_years").is_not_null() & (pl.col("business_age_years") < 5.0)
        if has_age
        else pl.lit(False)
    )
    is_glossary_higher_risk = is_unlisted & (
        (is_pe_or_pe_div & is_young_or_unknown) | (~is_dedicated_treatment & is_young_evidenced)
    )
    return (
        pl.col("is_speculative").eq_missing(True)
        | eq_type.eq_missing(EquityType.SPECULATIVE.value)
        | is_glossary_higher_risk
    )


@cites("PS1/26, paragraph 4.2")
@cites("PS1/26, paragraph 4.3")
def _standardised_transitional_scope_expr() -> pl.Expr:
    """Legs rules 4.2 / 4.3 reach: equity exposures weighted under Art. 133(3) / (4).

    Excluded: subordinated debt (Art. 133(5) — "not classified as an equity
    exposure"), CIUs (weighted under Arts. 132-132C), the central-bank type
    (not an Art. 133(3) weight), and an Art. 133(6)(c) significant investment,
    which both rules exclude by name ("within the scope of paragraph 6"). A
    null type or flag excludes nothing: such a leg took the 250% / 400% weight.
    """
    eq_type = pl.col("equity_type").str.to_lowercase()
    is_not_article_133_3_or_4 = (
        eq_type.eq_missing(EquityType.CENTRAL_BANK.value)
        | eq_type.eq_missing(EquityType.SUBORDINATED_DEBT.value)
        | eq_type.eq_missing(EquityType.CIU.value)
    )
    return ~is_not_article_133_3_or_4 & pl.col("is_significant_investment").ne_missing(True)


@cites("CRR Art. 133(2)")
@cites("CRR Art. 155(1)")
def _crr_significant_investment_expr() -> pl.Expr:
    """CRR legs that take the Art. 48(4) 250% in place of their equity weight (IV-06).

    CRR Art. 133(2): "Equity exposures shall be assigned a risk weight of 100 %,
    unless they are required to be deducted in accordance with Part Two,
    assigned a 250 % risk weight in accordance with Article 48(4), ...". Art.
    155(1) applies the IRB equity approaches to equity "excluding those deducted
    in accordance with Part Two or subject to a 250 % risk weight in accordance
    with Article 48", so the 250% holds on the SA, IRB-simple and PD/LGD paths.
    ``is_significant_investment`` is the firm's assertion that the leg is the
    non-deducted amount of a significant investment in a financial sector entity
    (the engine performs no deduction; the flag is documented that way).

    Two types keep their own treatment whatever the flag says: a CIU unit
    (weighted under Arts. 132-132C -- not an Art. 133 equity exposure), and the
    0% central-bank type. A null flag is not an assertion (``eq_missing``).
    """
    equity_type = pl.col("equity_type").str.to_lowercase()
    return (
        pl.col("is_significant_investment").eq_missing(True)
        & equity_type.ne_missing(EquityType.CIU.value)
        & equity_type.ne_missing(EquityType.CENTRAL_BANK.value)
    )


def _significant_investment_method_expr(
    is_significant_investment: pl.Expr, irb_method: EquityApproach
) -> pl.Expr:
    """The sealed ``equity_method`` of a CRR IRB-path leg: ``sa`` for an Art. 48(4) leg.

    Art. 155(1) excludes the 250% leg from the IRB equity approaches, so it is
    not ``irb_simple`` / ``pd_lgd`` equity; ``sa`` records its weight's basis
    (Art. 133(2) / Art. 48(4), the same as an SA firm's) and keeps it out of
    Pillar 3 CR10.5 and C 02.00 row 0420 (Equity IRB).
    """
    return (
        pl.when(is_significant_investment)
        .then(pl.lit(EquityApproach.SA.value))
        .otherwise(pl.lit(irb_method.value))
    )


@cites("PS1/26, paragraph 132")
@cites("PS1/26, paragraph 132A")
@cites("PS1/26, paragraph 128")
def _holding_rw_expr(pack: ResolvedRulepack, equity_holding_rw: float | None) -> pl.Expr:
    """The look-through weight of one CIU holding, by its class (Art. 132A(1)).

    Art. 132A(1) risk-weights "all underlying exposures of the CIU as if they
    were directly held by the institution". The caller has already joined the
    (exposure_class, CQS) table and upper-cased ``exposure_class``; a hit there
    wins. A miss resolves, in order:

    - **A nested CIU** (``ciu``) -> the 1,250% fall-back. Art. 132(5): a level 2
      CIU's exposures "may be calculated by using any of the three approaches
      described in paragraph 2 ... In any other scenario it shall use the
      fall-back approach." The holdings table carries no look-through or mandate
      data for a level 2 CIU, so the fall-back is the only approach this row can
      evidence. Same weight in both regimes (the PS1/26 rule "corresponds to
      Article 132 of CRR as it applied immediately before revocation").
    - **An unidentified class** -- null, or a value outside the ``ExposureClass``
      vocabulary (``securitisation``, ``subordinated_debt``, a typo) -> 1,250%.
      Such an underlying cannot be weighted "as if directly held", so that slice
      of the fund takes the fall-back, which Art. 132(2) lets a firm combine with
      look-through ("a combination of the approaches referred to in this
      paragraph"). The input-domain gate warns on these values (SA008,
      ``contracts/validation.py::_validate_ciu_holding_classes``).
    - **A high-risk item** -> the pack's Art. 128 150% where the
      ``b31_high_risk_class_applicable`` Feature is on (Basel 3.1). UK CRR
      Art. 128 was omitted by SI 2021/1078, so under CRR the holding falls to
      the default, exactly as a direct ``high_risk`` row is demoted to OTHER.
    - **An equity holding** -> the rules 4.7-4.8 higher-of, when the caller has
      one for the reporting date (``equity_holding_rw``).
    - **Anything else the vocabulary knows** (unrated corporate, retail, real
      estate, ``other``) -> ``_DEFAULT_HOLDING_RW``. Retail and real-estate
      holdings are overstated at 100%; left as they were by decision (IV-05).
    """
    holding_class = pl.col("exposure_class")
    vocabulary = [member.value.upper() for member in ExposureClass]
    is_fall_back = (
        holding_class.is_null()
        | ~holding_class.is_in(vocabulary)
        | (holding_class == ExposureClass.CIU.value.upper())
    )
    branches: list[tuple[pl.Expr, pl.Expr]] = [
        (pl.col("risk_weight").is_not_null(), pl.col("risk_weight")),
        (is_fall_back, pl.lit(CIU_FALLBACK_RW)),
    ]
    if pack.feature("b31_high_risk_class_applicable"):
        high_risk_rw = scalar_value(pack.scalar_param("high_risk_rw"))
        branches.append(
            (holding_class == ExposureClass.HIGH_RISK.value.upper(), pl.lit(high_risk_rw))
        )
    if equity_holding_rw is not None:
        branches.append(
            (holding_class == ExposureClass.EQUITY.value.upper(), pl.lit(equity_holding_rw))
        )

    weight: pl.Expr = pl.lit(_DEFAULT_HOLDING_RW)
    for condition, value in reversed(branches):
        weight = pl.when(condition).then(value).otherwise(weight)
    return weight


def _with_null_transitional_carriers(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Emit the three transitional carriers as typed nulls (nothing weighted under 4.2 / 4.3)."""
    return exposures.with_columns(
        pl.lit(None, dtype=pl.String).alias("equity_transitional_approach"),
        pl.lit(None, dtype=pl.Boolean).alias("equity_higher_risk"),
        pl.lit(None, dtype=pl.Float64).alias("risk_weight_pre_equity_transitional"),
    )


def _irb_firm_transitional_warning() -> CalculationError:
    """CFG003: a firm with IRB permission at end-2026 receives the rule 4.9 treatment.

    Raised, unless ``opt_out`` is set, for every run of such a firm inside
    2027-2029 whose equity table is present, whatever it holds — even an empty
    table, or one holding only legs outside the rules 4.2 / 4.3 scope (CIUs,
    subordinated debt, the central-bank type, significant investments). Gating
    it on an in-scope leg would mean collecting the equity frame here, where
    the error list is built while the frame is still lazy and nothing else in
    the stage materialises it; so the message is conditional ("if the firm
    holds Art. 133 equity") instead.
    """
    return CalculationError(
        code=ERROR_EQUITY_TRANSITIONAL_CONFIG,
        message=(
            "Equity transitional: the firm had IRB permission on 31 December 2026, so "
            "PS1/26 Credit Risk: General Provisions rules 4.4-4.6 govern its Art. 133 "
            "equity during 2027-2029: rule 4.5(1) assigns the rule 4.2 / 4.3 weights to "
            "equity it then held under Standardised Approach permission (Article 148 or "
            "150 of CRR), and rule 4.6 the higher of the legacy Art. 155 weight and the "
            "rule 4.2 / 4.3 weight to equity it then held under the IRB Approach. The "
            "engine applies neither: if the firm holds Art. 133 equity, it is weighted "
            "under Art. 133 (250% / 400%), which is the treatment of the rule 4.9 "
            "election, not the default. Set equity_transitional.opt_out if the firm has "
            "given the PRA notice of that election under rule 4.10."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CONFIGURATION,
        regulatory_reference="PS1/26 Credit Risk: General Provisions rules 4.4-4.6, 4.9-4.10",
        field_name="equity_transitional.opt_out",
    )


def _opt_out_without_irb_permission_warning() -> CalculationError:
    """CFG003: ``opt_out`` set by a firm that has no rule 4.9 election to make."""
    return CalculationError(
        code=ERROR_EQUITY_TRANSITIONAL_CONFIG,
        message=(
            "Equity transitional: equity_transitional.opt_out is set, but the firm did "
            "not have IRB permission on 31 December 2026. PS1/26 Credit Risk: General "
            "Provisions rule 4.9 replaces only rules 4.5, 4.6 and 4.8, which apply to a "
            "firm that had that permission, so the election is not available and the "
            "rule 4.2 / 4.3 weights are applied to direct equity regardless."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CONFIGURATION,
        regulatory_reference="PS1/26 Credit Risk: General Provisions rules 4.1-4.3, 4.9",
        field_name="equity_transitional.opt_out",
    )
