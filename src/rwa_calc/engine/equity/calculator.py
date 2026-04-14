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

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, EquityResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.tables.b31_equity_rw import B31_SA_EQUITY_RISK_WEIGHTS
from rwa_calc.data.tables.crr_equity_rw import (
    IRB_SIMPLE_EQUITY_RISK_WEIGHTS,
    SA_EQUITY_RISK_WEIGHTS,
)
from rwa_calc.domain.enums import ApproachType, EquityApproach, EquityType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

# Float-converted risk weight tables for Polars expressions.
# Authoritative Decimal values live in data/tables/*_equity_rw.py;
# these are derived once at module load for use with pl.lit().
_CRR_SA_RW = {k: float(v) for k, v in SA_EQUITY_RISK_WEIGHTS.items()}
_B31_SA_RW = {k: float(v) for k, v in B31_SA_EQUITY_RISK_WEIGHTS.items()}
_IRB_RW = {k: float(v) for k, v in IRB_SIMPLE_EQUITY_RISK_WEIGHTS.items()}

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
}

# Sentinel for null CQS in join operations (data processing convention)
_NULL_CQS_SENTINEL = -1

# Default holding risk weight when CQS lookup returns null (Art. 132a)
_DEFAULT_HOLDING_RW = 1.00

# Audit formatting: convert decimal RW to percentage display
_RW_TO_PERCENT = 100
_AUDIT_RWA_ROUND = 0


def _append_ciu_branches(chain: pl.Expr) -> pl.Expr:
    """Append CIU approach-aware risk weight branches to a when/then chain (Art. 132-132C).

    Covers: fallback (1,250%), mandate_based (ciu_mandate_rw x1.2 if third-party),
    look_through (ciu_look_through_rw), and unclassified CIU (1,250% default).
    """
    _is_ciu = pl.col("equity_type").str.to_lowercase() == "ciu"
    return (
        chain.when(_is_ciu & (pl.col("ciu_approach") == "fallback"))
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

        if approach == EquityApproach.IRB_SIMPLE:
            exposures = self._apply_equity_weights_irb_simple(exposures, config)
        else:
            exposures = self._apply_equity_weights_sa(exposures, config)

        exposures = self._apply_transitional_floor(exposures, config)

        return self._calculate_rwa(exposures)

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA for equity exposures.

        Args:
            data: CRM-adjusted exposures (uses equity_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with equity RWA calculations
        """
        bundle = self.get_equity_result_bundle(data, config)

        calc_errors = [
            CalculationError(
                code="EQUITY001",
                message=str(err),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CALCULATION,
            )
            for err in bundle.errors
        ]

        return LazyFrameResult(
            frame=bundle.results,
            errors=calc_errors,
        )

    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle:
        """
        Calculate equity RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            EquityResultBundle with results and audit trail
        """
        errors: list[EquityCalculationError] = []

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

        approach = self._determine_approach(config)

        exposures = self._prepare_columns(exposures, config)
        exposures = self._resolve_look_through_rw(exposures, data.ciu_holdings, config)

        if approach == EquityApproach.IRB_SIMPLE:
            exposures = self._apply_equity_weights_irb_simple(exposures, config)
        else:
            exposures = self._apply_equity_weights_sa(exposures, config)

        exposures = self._apply_transitional_floor(exposures, config)
        exposures = self._calculate_rwa(exposures)

        audit = self._build_audit(exposures, approach)

        return EquityResultBundle(
            results=exposures,
            calculation_audit=audit,
            approach=approach,
            errors=errors,
        )

    def _determine_approach(self, config: CalculationConfig) -> EquityApproach:
        """
        Determine SA vs IRB_SIMPLE based on config.

        Under Basel 3.1 (CRE20.58-62): IRB for equity is removed — all equity
        exposures must use SA treatment. The IRB Simple Risk Weight Method
        (Art. 155: 190%/290%/370%) is no longer available.

        Under CRR: If the firm has IRB permissions (FIRB or AIRB) for any
        exposure class, they must use Article 155 IRB Simple approach for equity.
        If SA-only, use Article 133 SA approach.

        Args:
            config: Calculation configuration

        Returns:
            EquityApproach.SA for Article 133, EquityApproach.IRB_SIMPLE for Article 155
        """
        # Basel 3.1: IRB equity removed — all equity uses SA (CRE20.58-62)
        if config.is_basel_3_1:
            return EquityApproach.SA

        # CRR: Check if firm has any IRB permissions beyond SA
        # If permissions dict is empty, it's SA-only
        if not config.irb_permissions.permissions:
            return EquityApproach.SA

        # Check if any exposure class has FIRB or AIRB permission
        for _exposure_class, approaches in config.irb_permissions.permissions.items():
            if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
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
        from rwa_calc.data.tables.crr_risk_weights import get_combined_cqs_risk_weights

        use_uk_deviation = config.base_currency == "GBP"
        if config.is_basel_3_1:
            from rwa_calc.data.tables.b31_risk_weights import (
                get_b31_combined_cqs_risk_weights,
            )

            rw_table = get_b31_combined_cqs_risk_weights(use_uk_deviation).lazy()
        else:
            rw_table = get_combined_cqs_risk_weights(use_uk_deviation).lazy()

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
            .with_columns(
                pl.col("risk_weight").fill_null(_DEFAULT_HOLDING_RW).alias("holding_rw"),
            )
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

    def _apply_equity_weights_sa(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SA equity risk weights, branching by framework.

        CRR Art. 133(2): 100% flat (with 0% for central bank);
            CIU via Art. 132 (1,250% fallback per Art. 132(2))
        Basel 3.1 Art. 133(3)-(5): 250% / 400% / 150% (sub debt)
        """
        if config.is_basel_3_1:
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
        4. PE / VC (always higher risk): 400%  (Art. 133(4))
        5. CIU: approach-dependent  (Art. 132-132C)
           - CIU fallback: 1,250%  (Art. 132(2))
        6. All other standard equity (incl. government-supported): 250%  (Art. 133(3))

        Note: B31 Art. 133(6) is an exclusion clause (own funds deductions,
        Art. 89(3), Art. 48(4)) — NOT a risk weight assignment. CRR's 100%
        legislative equity (Art. 133(3)(c)) has no equivalent in B31.
        """
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
                # Art. 133(4): PE/VC is always higher risk (400%)
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity")
                .then(pl.lit(_B31_SA_RW[EquityType.PRIVATE_EQUITY]))
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                .then(pl.lit(_B31_SA_RW[EquityType.PRIVATE_EQUITY_DIVERSIFIED]))
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
        """
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
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(_IRB_RW[EquityType.GOVERNMENT_SUPPORTED]))
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(_IRB_RW[EquityType.GOVERNMENT_SUPPORTED]))
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(_IRB_RW[EquityType.EXCHANGE_TRADED]))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(_IRB_RW[EquityType.LISTED]))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(_IRB_RW[EquityType.EXCHANGE_TRADED]))
                .otherwise(pl.lit(_IRB_RW[EquityType.OTHER]))
                .alias("risk_weight"),
            ]
        )

    def _apply_transitional_floor(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply equity transitional risk weight floor (PRA Rules 4.1-4.10).

        During the transitional period (2027-2029), equity risk weights phase
        in from CRR levels to full Basel 3.1 levels. The transitional RW acts
        as a floor: final_rw = max(assigned_rw, transitional_rw).

        For firms with prior IRB equity permission (Rules 4.4-4.6), the floor
        is the higher of the IRB model RW and the transitional SA RW.
        """
        eq_config = config.equity_transitional
        if not eq_config.enabled:
            return exposures

        std_rw = eq_config.get_transitional_rw(config.reporting_date, is_higher_risk=False)
        hr_rw = eq_config.get_transitional_rw(config.reporting_date, is_higher_risk=True)

        if std_rw is None or hr_rw is None:
            return exposures

        schema = exposures.collect_schema()
        is_hr_speculative = (
            pl.col("is_speculative").fill_null(False)
            if "is_speculative" in schema.names()
            else pl.lit(False)
        )
        # PE/VC is always higher-risk under Art. 133(4)
        eq_type_for_hr = pl.col("equity_type").str.to_lowercase()
        is_hr_pe = (eq_type_for_hr == "private_equity") | (
            eq_type_for_hr == "private_equity_diversified"
        )
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
            if not config.is_basel_3_1
            and any(
                ApproachType.FIRB in a or ApproachType.AIRB in a
                for a in config.irb_permissions.permissions.values()
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
