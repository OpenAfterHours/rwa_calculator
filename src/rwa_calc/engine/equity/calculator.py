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
- Apply transitional floor (PRA Rules 4.1-4.10) during phase-in
- Calculate RWA = EAD x RW
- Build audit trail of calculations

Basel 3.1 key changes from CRR:
- All standard equity (incl. government-supported): 100% -> 250% (Art. 133(3))
- CIU fallback: 1,250% (Art. 132(2), unchanged from CRR)
- IRB equity removed (Art. 147A) — all equity uses SA
- Transitional floor phases from 160%/220% (2027) to 250%/400% (2030)

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
- PRA PS1/26 Art. 133(3)-(6): Basel 3.1 SA equity weights
- PRA Rules 4.1-4.10: Equity transitional schedule
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import CRMAdjustedBundle, EquityResultBundle
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.domain.enums import ApproachType, EquityApproach, EquityType, ExposureClass
from rwa_calc.engine.irb.formulas import (
    _capital_k_expr_from_params,
    _correlation_expr_from_pd,
    _maturity_adjustment_expr_from_pd,
)
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import formula_float_map, lookup_float_map, scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
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

# Art. 132(2): CIU fallback risk weight — 1,250% under both CRR and B31.
# Punitive weight incentivises firms to use look-through or mandate-based approaches.
CIU_FALLBACK_RW = _CRR_SA_RW[EquityType.CIU]

# Art. 132b(2): multiplier for third-party CIU mandate calculations (20% uplift)
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
    "fund_reference": ColumnSpec(pl.String, required=False),
    "ciu_look_through_rw": ColumnSpec(pl.Float64, required=False),
    "fund_nav": ColumnSpec(pl.Float64, required=False),
    # Years the underlying PE/VC business has existed; used by the B31
    # Art. 133(4) higher-risk test (PRA PS1/26 Glossary p.5).
    "business_age_years": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 155(3): True -> firm has Art. 178 default-definition data so the
    # 1.5x PD/LGD scaling does NOT apply; False/null -> 1.5x scaling applies.
    "has_default_definition_info": ColumnSpec(pl.Boolean, default=False, required=False),
}

# Sentinel for null CQS in join operations (data processing convention)
_NULL_CQS_SENTINEL = -1

# Default holding risk weight when CQS lookup returns null (Art. 132a)
_DEFAULT_HOLDING_RW = 1.00

# Audit formatting: convert decimal RW to percentage display
_RW_TO_PERCENT = 100
_AUDIT_RWA_ROUND = 0


@cites("PS1/26, paragraph 132")
def _append_ciu_branches(chain: pl.Expr) -> ChainedThen:
    """Append CIU approach-aware risk weight branches to a when/then chain (Art. 132-132C).

    Covers: fallback (1,250%), mandate_based (ciu_mandate_rw x1.2 if third-party),
    look_through (ciu_look_through_rw), and unclassified CIU (1,250% default).
    """
    _is_ciu = pl.col("equity_type").str.to_lowercase() == "ciu"
    # The piped-in chain is an in-progress when/then; narrow for the checker.
    then_chain = cast("Then | ChainedThen", chain)
    return (
        then_chain.when(_is_ciu & (pl.col("ciu_approach") == "fallback"))
        .then(pl.lit(CIU_FALLBACK_RW))
        .when(_is_ciu & (pl.col("ciu_approach") == "mandate_based"))
        .then(
            pl.col("ciu_mandate_rw").fill_null(CIU_FALLBACK_RW)
            * pl.when(pl.col("ciu_third_party_calc").fill_null(False))
            .then(pl.lit(_CIU_THIRD_PARTY_MULTIPLIER))
            .otherwise(pl.lit(_CIU_INTERNAL_MULTIPLIER))
        )
        .when(_is_ciu & (pl.col("ciu_approach") == "look_through"))
        .then(pl.col("ciu_look_through_rw").fill_null(CIU_FALLBACK_RW))
        .when(_is_ciu)
        .then(pl.lit(CIU_FALLBACK_RW))
    )


@dataclass
class EquityCalculationError:
    """Error during equity calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


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
        # bypasses both the IRB Simple transitional floor and _calculate_rwa.
        if approach == EquityApproach.PD_LGD:
            return self._apply_equity_weights_pd_lgd(exposures, config)

        if approach == EquityApproach.IRB_SIMPLE:
            exposures = self._apply_equity_weights_irb_simple(exposures, config)
        else:
            exposures = self._apply_equity_weights_sa(exposures, config)

        exposures = self._apply_transitional_floor(exposures, config)

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
        # the IRB Simple transitional floor and _calculate_rwa.
        if approach == EquityApproach.PD_LGD:
            exposures = self._apply_equity_weights_pd_lgd(exposures, config, pack=pack)
        else:
            if approach == EquityApproach.IRB_SIMPLE:
                exposures = self._apply_equity_weights_irb_simple(exposures, config)
            else:
                exposures = self._apply_equity_weights_sa(exposures, config, pack=pack)

            exposures = self._apply_transitional_floor(exposures, config, pack=pack)
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

        # CRR: Check if firm has any IRB permissions beyond SA
        # If permissions dict is empty, it's SA-only
        # irb_permissions is derived non-None in CalculationConfig.__post_init__.
        if not config.irb_permissions.permissions:  # ty: ignore[unresolved-attribute]
            return EquityApproach.SA

        # Check if any exposure class has FIRB or AIRB permission
        for _exposure_class, approaches in config.irb_permissions.permissions.items():  # ty: ignore[unresolved-attribute]
            if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
                # Art. 155(3): PD/LGD approach when the firm has elected it
                if config.equity_pd_lgd:
                    return EquityApproach.PD_LGD
                return EquityApproach.IRB_SIMPLE

        return EquityApproach.SA

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
        Resolve look-through risk weights for CIU exposures (Art. 132a).

        Joins CIU holdings to SA risk weight tables, aggregates a
        value-weighted effective RW per fund, and sets ciu_look_through_rw.

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
            from rwa_calc.data.tables.b31_risk_weights import (
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
        # RW) instead of the _DEFAULT_HOLDING_RW fallback (the transitional
        # regime only applies to firms that held IRB equity permission, so
        # equity_transitional.enabled is the correct proxy here).
        equity_holding_fallback_rw = self._equity_holding_higher_of_rw(config, pack=resolved_pack)
        if equity_holding_fallback_rw is not None:
            holding_rw_expr = (
                pl.when(
                    (pl.col("exposure_class") == ExposureClass.EQUITY.value.upper())
                    & pl.col("risk_weight").is_null()
                )
                .then(pl.lit(equity_holding_fallback_rw))
                .otherwise(pl.col("risk_weight").fill_null(_DEFAULT_HOLDING_RW))
            )
        else:
            holding_rw_expr = pl.col("risk_weight").fill_null(_DEFAULT_HOLDING_RW)

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

        The transitional regime only applies to firms that held IRB equity
        permission, so ``equity_transitional.enabled`` (plus a transitional RW
        existing for the reporting date) is the gate.

        Per Rule 4.9-4.10, a firm that has irrevocably opted out of the
        transitional regime (``equity_transitional.opt_out``) suppresses the
        higher-of: ``None`` is returned so the holding falls back to the
        ``_DEFAULT_HOLDING_RW`` standard treatment. The opt-out applies jointly
        with the direct-equity transitional floor (Rule 4.9).

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
            return self._apply_b31_equity_weights_sa(exposures, config)
        return self._apply_crr_equity_weights_sa(exposures, config)

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
        """
        # Art. 133(4) / Glossary p.5 higher-risk test — unlisted equity whose
        # underlying business has existed < 5 years. Two routings combine:
        #
        #   (1) PE/VC legacy routing: unlisted PE/VC with business age < 5y OR
        #       unknown -> 400%. Null/missing age is treated conservatively as
        #       <5y (a firm cannot claim the long-established carve-out without
        #       evidence of business age >= 5), preserving the prior behaviour
        #       for callers that supply no business_age_years.
        #
        #   (2) Generalised routing: ANY other equity that is NOT
        #       central-bank (0%), subordinated-debt (150%, Art. 133(5)), CIU
        #       (Art. 132 look-through/mandate/fallback) or government-supported
        #       (standard 250%, Art. 133(3)) is higher-risk only when it has an
        #       *evidenced* young business age (non-null AND < 5.0). Absent age
        #       data, such equity stays at the standard 250% — listed/unlisted/
        #       other without business-age evidence is not uplifted.
        schema_names = exposures.collect_schema().names()
        is_pe_or_pe_div = (
            pl.col("equity_type")
            .str.to_lowercase()
            .is_in([EquityType.PRIVATE_EQUITY, EquityType.PRIVATE_EQUITY_DIVERSIFIED])
        )
        is_dedicated_treatment = (
            pl.col("equity_type")
            .str.to_lowercase()
            .is_in(
                [
                    EquityType.CENTRAL_BANK,
                    EquityType.SUBORDINATED_DEBT,
                    EquityType.CIU,
                    EquityType.GOVERNMENT_SUPPORTED,
                ]
            )
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
        is_higher_risk = is_unlisted & (
            (is_pe_or_pe_div & is_young_or_unknown) | (~is_dedicated_treatment & is_young_evidenced)
        )

        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(_B31_SA_RW[EquityType.CENTRAL_BANK]))
                # Art. 133(5): subordinated debt / non-equity own funds = 150%
                .when(pl.col("equity_type").str.to_lowercase() == "subordinated_debt")
                .then(pl.lit(_B31_SA_RW[EquityType.SUBORDINATED_DEBT]))
                .when(pl.col("is_speculative") == True)  # noqa: E712
                .then(pl.lit(_B31_SA_RW[EquityType.SPECULATIVE]))
                .when(pl.col("equity_type").str.to_lowercase() == "speculative")
                .then(pl.lit(_B31_SA_RW[EquityType.SPECULATIVE]))
                # Art. 133(4) + Glossary p.5: unlisted equity with business age
                # < 5y (or unknown) is higher-risk (400%); long-established or
                # exchange-traded equity falls through to standard 250%.
                .when(is_higher_risk)
                .then(pl.lit(_B31_SA_RW[EquityType.PRIVATE_EQUITY]))
                # CIU: approach-aware risk weights (Art. 132-132C)
                .pipe(_append_ciu_branches)
                .otherwise(pl.lit(_B31_SA_RW[EquityType.OTHER]))
                .alias("risk_weight"),
            ]
        )

    def _apply_equity_weights_irb_simple(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply Article 155 (IRB Simple) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Private equity (diversified portfolio): 190%
        - Exchange-traded: 290%
        - Other equity: 370%

        Before assigning risk weights this nets non-trading-book short positions
        against long positions in the same individual stock per Art. 155(2)
        (see ``_net_short_positions``).
        """
        exposures = self._net_short_positions(exposures)
        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(_IRB_RW[EquityType.CENTRAL_BANK]))
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                    | (
                        (pl.col("equity_type").str.to_lowercase() == "private_equity")
                        & (pl.col("is_diversified_portfolio") == True)  # noqa: E712
                    )
                )
                .then(pl.lit(_IRB_RW[EquityType.PRIVATE_EQUITY_DIVERSIFIED]))
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(_IRB_RW[EquityType.EXCHANGE_TRADED]))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(_IRB_RW[EquityType.LISTED]))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(_IRB_RW[EquityType.EXCHANGE_TRADED]))
                # CRR Art. 155(2)(c): "all other equity" 370% — including
                # government_supported, which has no Art. 155 carve-out.
                .otherwise(pl.lit(_IRB_RW[EquityType.OTHER]))
                .alias("risk_weight"),
            ]
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

        The IRB Simple transitional floor (PRA Rules 4.1-4.10) does NOT apply —
        it is Simple-approach machinery.
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

        exposures = exposures.with_columns(
            risk_weight.alias("risk_weight"),
            (pl.col("pd_floored") * pl.col("lgd") * pl.col("ead_final")).alias("expected_loss"),
        )

        # Uncapped RWEA = RW x EAD.
        rwea = pl.col("risk_weight") * pl.col("ead_final")
        # Art. 155(3) cap: EL x 12.5 + RWEA <= EAD x 12.5, i.e.
        # RWEA <= EAD x 12.5 - EL x 12.5, clamped at 0.
        rwea_cap = (pl.col("ead_final") * 12.5 - pl.col("expected_loss") * 12.5).clip(
            lower_bound=0.0
        )
        rwea_capped = pl.min_horizontal(rwea, rwea_cap)

        return exposures.with_columns(
            (rwea > rwea_cap).alias("equity_pd_lgd_cap_binds"),
            rwea_capped.alias("rwa"),
            rwea_capped.alias("rwa_final"),
        )

    def _apply_transitional_floor(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Apply equity transitional risk weight floor (PRA Rules 4.1-4.10).

        During the transitional period (2027-2029), equity risk weights phase
        in from CRR levels to full Basel 3.1 levels. The transitional RW acts
        as a floor: final_rw = max(assigned_rw, transitional_rw).

        For firms with prior IRB equity permission (Rules 4.4-4.6), the floor
        is the higher of the IRB model RW and the transitional SA RW.

        Per Rules 4.9-4.10, a firm that has irrevocably opted out
        (``equity_transitional.opt_out``) keeps its end-state assigned RW: the
        floor comparison is skipped. The opt-out applies jointly with the CIU
        underlying higher-of suppression (Rule 4.9).
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        eq_config = config.equity_transitional
        if not resolved_pack.feature("equity_transitional") or eq_config.opt_out:
            return exposures

        std_rw = _equity_transitional_rw(resolved_pack, config.reporting_date, is_higher_risk=False)
        hr_rw = _equity_transitional_rw(resolved_pack, config.reporting_date, is_higher_risk=True)

        if std_rw is None or hr_rw is None:
            return exposures

        schema = exposures.collect_schema()
        is_hr_speculative = (
            pl.col("is_speculative").fill_null(False)
            if "is_speculative" in schema.names()
            else pl.lit(False)
        )
        # PE/VC is higher-risk under Art. 133(4) only when unlisted AND business
        # age < 5y (or unknown — null treated conservatively per Glossary p.5).
        # Long-established / exchange-traded PE/VC is standard equity (250%).
        eq_type_for_hr = pl.col("equity_type").str.to_lowercase()
        is_pe_or_pe_div_hr = (eq_type_for_hr == "private_equity") | (
            eq_type_for_hr == "private_equity_diversified"
        )
        is_unlisted_hr = (
            ~pl.col("is_exchange_traded").fill_null(False)
            if "is_exchange_traded" in schema.names()
            else pl.lit(True)
        )
        is_young_or_unknown_hr = (
            pl.col("business_age_years").is_null() | (pl.col("business_age_years") < 5.0)
            if "business_age_years" in schema.names()
            else pl.lit(True)
        )
        is_hr_pe = is_pe_or_pe_div_hr & is_unlisted_hr & is_young_or_unknown_hr
        is_hr = is_hr_speculative | is_hr_pe

        # PRA Rule 4.2/4.3: transitional does NOT apply to exposures within
        # scope of Art. 133(6) (own funds deductions) or subordinated debt (150%).
        # CIU look-through/mandate-based RWs are derived from underlying assets
        # (Art. 132a/132b), not from Art. 133 equity weights — exclude from floor.
        # CIU fallback (1,250%) is far above transitional max, so exclusion is moot.
        # Note: government-supported equity IS subject to transitional floor under
        # B31 (it's standard 250% equity, Art. 133(3); there is no 100% legislative
        # carve-out in B31 — CRR Art. 133(3)(c) was removed).
        eq_type_lower = pl.col("equity_type").str.to_lowercase()
        is_ciu_non_fallback = (eq_type_lower == "ciu") & (
            (pl.col("ciu_approach") == "look_through") | (pl.col("ciu_approach") == "mandate_based")
        )
        is_excluded = (
            (eq_type_lower == "central_bank")
            | (eq_type_lower == "subordinated_debt")
            | is_ciu_non_fallback
        )

        transitional_rw = (
            pl.when(is_excluded)
            .then(pl.lit(0.0))  # No floor for excluded types
            .when(is_hr)
            .then(pl.lit(float(hr_rw)))
            .otherwise(pl.lit(float(std_rw)))
        )

        # Determine transitional approach type for COREP reporting (OF 07.00
        # rows 0371-0374).  CRR firms with prior IRB equity permission use
        # "irb_transitional"; all others use "sa_transitional".
        approach_label = (
            "irb_transitional"
            if resolved_pack.feature("equity_irb_approaches_available")
            and any(
                ApproachType.FIRB in a or ApproachType.AIRB in a
                for a in config.irb_permissions.permissions.values()  # ty: ignore[unresolved-attribute]
            )
            else "sa_transitional"
        )

        return exposures.with_columns(
            pl.max_horizontal(pl.col("risk_weight"), transitional_rw).alias("risk_weight"),
            # Annotation columns for COREP OF 07.00 equity transitional rows
            pl.lit(approach_label).alias("equity_transitional_approach"),
            is_hr.alias("equity_higher_risk"),
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
